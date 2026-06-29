#!/usr/bin/env python3
"""
Unit tests for Step 2 (file-level / batch concurrency) on DriveService.upload
and DriveService.download_path.

Hermetic: the pooled `requests.Session`, the crypto service, and the
folder/listing helpers are mocked, so no network or real encryption happens.
They pin the four non-negotiable Step 2 constraints:

  1. a batch never runs more than W whole FILES at once (peak ≤ W),
  2. total chunks in flight across files × chunks never exceed the ONE shared
     byte budget (GLOBAL_MAX_INFLIGHT_CHUNKS) — proven by lowering the budget
     below the number of concurrent files and observing the peak,
  3. a single file (or max_workers<=1) stays on the sequential path — no shared
     budget object is threaded into the per-file transfer,
  4. shared batch_state writes are race-free under concurrent completion.

Run from the repo root:
    .venv/bin/python -m unittest discover -s tests -v
"""

import os
import re
import sys
import json
import time
import shutil
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.drive as drive_module  # noqa: E402
from services.drive import DriveService  # noqa: E402

MB = 1048576


def _ok_post():
    resp = mock.Mock()
    resp.status_code = 200
    resp.text = ""
    return resp


def _index_of(url):
    return int(re.search(r"[?&]index=(\d+)", url).group(1))


class _Tracker:
    """Records the peak number of concurrently-held slots."""

    def __init__(self):
        self.cur = 0
        self.peak = 0
        self.lock = threading.Lock()

    def enter(self):
        with self.lock:
            self.cur += 1
            self.peak = max(self.peak, self.cur)

    def leave(self):
        with self.lock:
            self.cur -= 1


def _make_batch_upload_drive(post_side_effect=None):
    """A DriveService wired for batch-upload tests (mocked session + crypto +
    folder/listing helpers). Real upload_file_chunked / chunk pool run."""
    drive = DriveService()
    drive.email = "user@example.com"
    drive.master_keys = ["m" * 32]
    drive.debug = False

    drive.api = mock.Mock()
    drive.api.api_key = "token"
    drive.api.session = mock.Mock()
    if post_side_effect is not None:
        drive.api.session.post.side_effect = post_side_effect
    else:
        drive.api.session.post.return_value = _ok_post()
    drive.api.check_file_exists.return_value = False

    # Each file gets a distinct uuid so chunk URLs are per-file.
    uuids = {"n": 0}
    uuid_lock = threading.Lock()

    def gen_uuid():
        with uuid_lock:
            uuids["n"] += 1
            return f"file-{uuids['n']}"

    drive.crypto = mock.Mock()
    drive.crypto.random_string.return_value = "k" * 32
    drive.crypto.generate_uuid.side_effect = gen_uuid
    drive.crypto.encrypt_data.side_effect = lambda data, key: data  # identity
    drive.crypto.encrypt_metadata_002.return_value = "enc"
    drive.crypto.hash_filename.return_value = "hashed"

    drive.config = mock.Mock()
    drive.config.ingest_url = "https://ingest.example"

    drive.create_folder_recursive = mock.Mock(return_value={"uuid": "parent"})
    drive.list_files = mock.Mock(return_value=[])
    drive._invalidate_cache = mock.Mock()
    return drive


def _make_src_dir(n_files, nbytes):
    root = tempfile.mkdtemp(prefix="filen_step2_")
    for i in range(n_files):
        with open(os.path.join(root, f"f{i:02d}.bin"), "wb") as fh:
            fh.write(os.urandom(nbytes))
    return root


class PeakFilesTest(unittest.TestCase):
    """Constraint 1: never more than W files in flight at once."""

    def test_batch_never_exceeds_w_concurrent_files(self):
        w = 3
        src = _make_src_dir(8, MB)  # 8 single-chunk files
        track = _Tracker()
        drive = _make_batch_upload_drive()

        real = drive.upload_file_chunked

        def slow_upload(*args, **kwargs):
            track.enter()
            try:
                time.sleep(0.03)  # hold the file "in flight" so overlap shows
                return real(*args, **kwargs)
            finally:
                track.leave()

        try:
            with mock.patch.object(drive, "upload_file_chunked",
                                   side_effect=slow_upload):
                drive.upload([src], "/remote", recursive=True,
                             on_conflict="overwrite", max_workers=w)
            self.assertLessEqual(track.peak, w,
                                 f"observed {track.peak} files in flight, bound is {w}")
            self.assertGreater(track.peak, 1, "expected real file-level overlap")
        finally:
            shutil.rmtree(src, ignore_errors=True)


class GlobalByteBudgetTest(unittest.TestCase):
    """Constraint 2: total chunks in flight across files × chunks are capped by
    the ONE shared budget — even when more files than the budget run at once."""

    def test_peak_inflight_chunks_never_exceeds_shared_budget(self):
        budget = 3
        n_files = 4  # more concurrent files than the budget allows chunks
        src = _make_src_dir(n_files, 4 * MB)  # 4 chunks each → real chunk work
        track = _Tracker()

        def post(*args, **kwargs):
            track.enter()
            try:
                time.sleep(0.01)
                return _ok_post()
            finally:
                track.leave()

        drive = _make_batch_upload_drive(post_side_effect=post)
        try:
            # Shrink the shared budget below the worker count so it is the
            # binding constraint, not the per-file degree.
            with mock.patch.object(drive_module, "GLOBAL_MAX_INFLIGHT_CHUNKS", budget):
                drive.upload([src], "/remote", recursive=True,
                             on_conflict="overwrite", max_workers=n_files)
            self.assertLessEqual(
                track.peak, budget,
                f"peak {track.peak} chunks in flight exceeded shared budget {budget}")
            self.assertGreater(track.peak, 1,
                               "expected genuine cross-file chunk overlap")
            # Every chunk of every file still got uploaded.
            self.assertEqual(drive.api.session.post.call_count, n_files * 4)
        finally:
            shutil.rmtree(src, ignore_errors=True)


class SequentialPathTest(unittest.TestCase):
    """Constraint: a single file / W<=1 stays sequential — no shared budget
    object is created or threaded into the per-file transfer."""

    def _captured_global_slots(self, src, **upload_kwargs):
        drive = _make_batch_upload_drive()
        seen = []

        real = drive.upload_file_chunked

        def capture(*args, **kwargs):
            seen.append(kwargs.get("global_chunk_slots"))
            return real(*args, **kwargs)

        with mock.patch.object(drive, "upload_file_chunked", side_effect=capture):
            drive.upload([src], "/remote", recursive=True,
                         on_conflict="overwrite", **upload_kwargs)
        return seen

    def test_single_file_stays_sequential(self):
        src = _make_src_dir(1, 3 * MB)
        try:
            seen = self._captured_global_slots(src, max_workers=4)
            self.assertEqual(seen, [None],
                             "single-file batch must not thread a shared budget")
        finally:
            shutil.rmtree(src, ignore_errors=True)

    def test_workers_le_1_stays_sequential(self):
        src = _make_src_dir(5, MB)
        try:
            seen = self._captured_global_slots(src, max_workers=1)
            self.assertTrue(seen and all(s is None for s in seen),
                            "max_workers<=1 must keep every file on the sequential path")
        finally:
            shutil.rmtree(src, ignore_errors=True)

    def test_multi_file_uses_shared_budget(self):
        # Counterpoint: with W>1 and several files, a shared budget IS threaded.
        src = _make_src_dir(4, 3 * MB)
        try:
            seen = self._captured_global_slots(src, max_workers=4)
            self.assertTrue(seen and all(isinstance(s, type(threading.Semaphore()))
                                         for s in seen))
            self.assertEqual(len({id(s) for s in seen}), 1,
                             "all files must share ONE budget instance")
        finally:
            shutil.rmtree(src, ignore_errors=True)


class RaceFreeStateTest(unittest.TestCase):
    """Constraint: concurrent file completion must not corrupt batch_state.
    The callback serializes the whole state to JSON on every write — a data
    race (dict resized mid-iteration) would raise here."""

    def test_concurrent_saves_never_corrupt_state(self):
        src = _make_src_dir(6, 3 * MB)  # 3 chunks each → frequent chunk saves
        saves = {"n": 0, "error": None}

        def save_state(state):
            try:
                json.dumps(state)  # would raise if another thread mutates mid-dump
                saves["n"] += 1
            except Exception as e:  # noqa: BLE001
                saves["error"] = e

        drive = _make_batch_upload_drive()
        try:
            drive.upload([src], "/remote", recursive=True, on_conflict="overwrite",
                         max_workers=4, save_state_callback=save_state)
        finally:
            shutil.rmtree(src, ignore_errors=True)

        self.assertIsNone(saves["error"], f"state serialization raced: {saves['error']}")
        self.assertGreater(saves["n"], 0)


# ---------------------------------------------------------------------------
# Download side
# ---------------------------------------------------------------------------


def _make_batch_download_drive(n_files):
    """A DriveService wired for batch-download tests. The flat-tree endpoint
    yields `n_files` files at the root; download_file is patched per test."""
    drive = DriveService()
    drive.master_keys = ["m" * 32]
    drive.debug = False
    drive.api = mock.Mock()
    drive.api.get_flat_folder_tree.return_value = {
        "folders": [],
        "files": [
            {"uuid": f"u{i}", "metadata": f"meta{i}", "parent": "ROOT"}
            for i in range(n_files)
        ],
    }
    drive.resolve_path = mock.Mock(return_value={
        "type": "folder", "uuid": "ROOT", "metadata": {"name": "d"},
    })
    # Decrypt each file's metadata into a unique filename.
    drive._try_decrypt = mock.Mock(
        side_effect=lambda enc: json.dumps({"name": f"{enc}.bin", "lastModified": 0}))
    drive.config = mock.Mock()
    return drive


class DownloadPeakFilesTest(unittest.TestCase):
    def test_download_batch_never_exceeds_w_concurrent_files(self):
        w = 3
        n = 8
        dest = tempfile.mkdtemp(prefix="filen_step2_dl_")
        track = _Tracker()
        drive = _make_batch_download_drive(n)

        def fake_download_file(file_uuid, save_path=None, quiet=True,
                               global_chunk_slots=None, **kwargs):
            track.enter()
            try:
                time.sleep(0.03)
                with open(save_path, "wb") as fh:
                    fh.write(b"x")
                return {"lastModified": 0}
            finally:
                track.leave()

        try:
            with mock.patch.object(drive, "download_file",
                                   side_effect=fake_download_file):
                drive.download_path("/d", dest, recursive=True,
                                    on_conflict="overwrite", max_workers=w)
            self.assertLessEqual(track.peak, w,
                                 f"observed {track.peak} files in flight, bound is {w}")
            self.assertGreater(track.peak, 1, "expected real file-level overlap")
        finally:
            shutil.rmtree(dest, ignore_errors=True)


class DownloadSharedBudgetTest(unittest.TestCase):
    """The shared budget threads through to download_file and bounds the peak
    chunks in flight across concurrently-downloading files."""

    def test_shared_budget_caps_inflight_download_chunks(self):
        budget = 3
        track = _Tracker()
        blob = os.urandom(4 * MB)  # 4 chunks per file

        def make_drive():
            drive = DriveService()
            drive.master_keys = ["m" * 32]
            drive.api = mock.Mock()
            drive.api.get_file_metadata.return_value = {
                "metadata": "enc", "chunks": 4, "region": "r", "bucket": "b",
            }
            drive._try_decrypt = mock.Mock(return_value=json.dumps(
                {"name": "f.bin", "size": len(blob),
                 "key": "0123456789abcdef0123456789abcdef"}))
            drive.config = mock.Mock()
            drive.config.egest_url = "https://egest.example"

            def get(url, *a, **k):
                track.enter()
                try:
                    i = int(url.rstrip("/").split("/")[-1])
                    resp = mock.Mock()
                    resp.status_code = 200
                    resp.content = blob[i * MB:(i + 1) * MB]
                    time.sleep(0.01)
                    return resp
                finally:
                    track.leave()

            drive.api.session = mock.Mock()
            drive.api.session.get.side_effect = get
            drive.crypto = mock.Mock()
            drive.crypto.decrypt_data.side_effect = lambda d, k: d
            return drive

        shared = threading.Semaphore(budget)
        drive = make_drive()
        outs = [tempfile.mkstemp(prefix="filen_dl_")[1] for _ in range(3)]
        try:
            threads = [
                threading.Thread(target=drive.download_file, kwargs={
                    "file_uuid": "u", "save_path": outs[i], "quiet": True,
                    "max_concurrent_chunks": 4, "global_chunk_slots": shared,
                })
                for i in range(3)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(10)
            self.assertLessEqual(track.peak, budget,
                                 f"peak {track.peak} download chunks exceeded budget {budget}")
            self.assertGreater(track.peak, 1, "expected real cross-file overlap")
        finally:
            for o in outs:
                os.remove(o)


if __name__ == "__main__":
    unittest.main()
