#!/usr/bin/env python3
"""
Unit tests for Step 1 (bounded chunk concurrency) on the upload + download
paths of DriveService.

These are hermetic: the pooled `requests.Session` and the crypto service are
mocked, so no network or real encryption happens. They pin the three
non-negotiable constraints:

  1. in-order hashing  — a parallel multi-chunk upload yields the SAME
     whole-file SHA-512 as the sequential path,
  2. resume-as-a-set   — restart skips exactly the completed indices and
     retries only the gaps (out-of-order completion safe),
  3. bound by bytes/in-flight — the pool never exceeds N concurrent chunks and
     the producer blocks once the in-flight budget is full,

plus: tiny files stay on the sequential path (no thread pool spun up).

Run from the repo root:
    .venv/bin/python -m unittest discover -s tests -v
"""

import os
import re
import sys
import time
import hashlib
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.drive as drive_module  # noqa: E402
from services.drive import DriveService, ChunkUploadException  # noqa: E402


def _ok_post():
    resp = mock.Mock()
    resp.status_code = 200
    resp.text = ""
    return resp


def _index_of(url):
    """Pull the chunk index out of an /v3/upload?...&index=N&... URL."""
    return int(re.search(r"[?&]index=(\d+)", url).group(1))


def _make_upload_drive(post_side_effect=None):
    """A DriveService wired with mocked session + crypto for upload tests."""
    drive = DriveService()
    drive.email = "user@example.com"
    drive.master_keys = ["m" * 32]

    drive.api = mock.Mock()
    drive.api.api_key = "token"
    drive.api.session = mock.Mock()
    if post_side_effect is not None:
        drive.api.session.post.side_effect = post_side_effect
    else:
        drive.api.session.post.return_value = _ok_post()

    drive.crypto = mock.Mock()
    drive.crypto.random_string.return_value = "k" * 32
    drive.crypto.generate_uuid.return_value = "file-uuid"
    drive.crypto.encrypt_data.side_effect = lambda data, key: data  # identity
    drive.crypto.encrypt_metadata_002.return_value = "enc"
    drive.crypto.hash_filename.return_value = "hashed"

    drive.config = mock.Mock()
    drive.config.ingest_url = "https://ingest.example"
    drive._invalidate_cache = mock.Mock()
    return drive


def _write_tmp(nbytes):
    fd, path = tempfile.mkstemp(prefix="filen_conc_")
    os.write(fd, os.urandom(nbytes))
    os.close(fd)
    return path


MB = 1048576


class InOrderHashTest(unittest.TestCase):
    def test_parallel_upload_matches_sequential_sha512(self):
        path = _write_tmp(5 * MB + 123)  # 6 chunks
        try:
            with open(path, "rb") as fh:
                expected = hashlib.sha512(fh.read()).hexdigest().lower()

            seq = _make_upload_drive()
            r_seq = seq.upload_file_chunked(path, "parent", max_concurrent_chunks=1)

            par = _make_upload_drive()
            r_par = par.upload_file_chunked(path, "parent", max_concurrent_chunks=4)

            self.assertEqual(r_seq["hash"], expected)
            self.assertEqual(r_par["hash"], expected,
                             "parallel hash must equal the sequential whole-file hash")
            # And every chunk index was uploaded exactly once.
            posted = sorted(_index_of(c.args[0])
                            for c in par.api.session.post.call_args_list)
            self.assertEqual(posted, [0, 1, 2, 3, 4, 5])
        finally:
            os.remove(path)


class BoundedPoolTest(unittest.TestCase):
    def test_never_exceeds_n_in_flight(self):
        n = 3
        state = {"cur": 0, "peak": 0}
        lock = threading.Lock()

        def post(*args, **kwargs):
            with lock:
                state["cur"] += 1
                state["peak"] = max(state["peak"], state["cur"])
            time.sleep(0.02)  # hold the slot so overlap is observable
            with lock:
                state["cur"] -= 1
            return _ok_post()

        path = _write_tmp(10 * MB)  # 10 chunks
        try:
            drive = _make_upload_drive(post_side_effect=post)
            drive.upload_file_chunked(path, "parent", max_concurrent_chunks=n)
            self.assertEqual(drive.api.session.post.call_count, 10)
            self.assertLessEqual(state["peak"], n,
                                 f"observed peak {state['peak']} exceeded bound {n}")
            self.assertGreater(state["peak"], 1, "expected real overlap")
        finally:
            os.remove(path)


class MemoryCeilingTest(unittest.TestCase):
    def test_producer_blocks_once_in_flight_budget_is_full(self):
        n = 2
        release = threading.Event()
        full = threading.Event()
        state = {"blocked": 0}
        lock = threading.Lock()

        def post(*args, **kwargs):
            with lock:
                state["blocked"] += 1
                if state["blocked"] >= n:
                    full.set()
            release.wait(5)  # park here until the test lets go
            return _ok_post()

        path = _write_tmp(8 * MB)  # 8 chunks, far more than n
        drive = _make_upload_drive(post_side_effect=post)

        t = threading.Thread(
            target=drive.upload_file_chunked,
            args=(path, "parent"),
            kwargs={"max_concurrent_chunks": n},
        )
        t.start()
        try:
            self.assertTrue(full.wait(5), "first N chunks never dispatched")
            time.sleep(0.1)  # give a stuck producer time to over-read
            # The semaphore caps in-flight at N: only N chunks have been
            # encrypted + handed to the network; the rest wait in memory budget.
            self.assertLessEqual(drive.crypto.encrypt_data.call_count, n)
            self.assertEqual(state["blocked"], n)
        finally:
            release.set()
            t.join(10)
        self.assertFalse(t.is_alive())
        self.assertEqual(drive.api.session.post.call_count, 8)


class ResumeAsSetTest(unittest.TestCase):
    def test_restart_retries_only_the_gaps(self):
        path = _write_tmp(6 * MB)  # 6 chunks: 0..5
        try:
            already_done = {0, 1, 3}  # note the GAP at 2 (out-of-order resume)
            drive = _make_upload_drive()
            drive.upload_file_chunked(
                path, "parent",
                completed_chunks=set(already_done),
                max_concurrent_chunks=4,
            )
            posted = sorted(_index_of(c.args[0])
                            for c in drive.api.session.post.call_args_list)
            self.assertEqual(posted, [2, 4, 5],
                             "must upload exactly the missing indices, not a range")
        finally:
            os.remove(path)

    def test_failure_carries_the_completed_set(self):
        path = _write_tmp(6 * MB)

        def post(url, *a, **k):
            if _index_of(url) == 4:
                raise ConnectionError("boom on chunk 4")
            return _ok_post()

        try:
            # Sequential so the failure point is deterministic: 0..3 succeed,
            # 4 fails before 5 is attempted.
            drive = _make_upload_drive(post_side_effect=post)
            with self.assertRaises(ChunkUploadException) as ctx:
                drive.upload_file_chunked(path, "parent", max_concurrent_chunks=1)
            exc = ctx.exception
            self.assertEqual(exc.completed_chunks, {0, 1, 2, 3})
            self.assertEqual(exc.last_successful_chunk, 3)  # contiguous prefix
        finally:
            os.remove(path)


class TinyFileStaysSequentialTest(unittest.TestCase):
    def test_no_thread_pool_for_tiny_file(self):
        path = _write_tmp(MB + 10)  # 2 chunks == SEQUENTIAL_CHUNK_THRESHOLD
        try:
            drive = _make_upload_drive()
            with mock.patch.object(drive_module, "ThreadPoolExecutor") as pool:
                drive.upload_file_chunked(path, "parent", max_concurrent_chunks=4)
                pool.assert_not_called()
            self.assertEqual(drive.api.session.post.call_count, 2)
        finally:
            os.remove(path)


class DownloadConcurrencyTest(unittest.TestCase):
    def _make_download_drive(self, blob, chunks):
        """A drive whose session.get serves chunk i of `blob` (1 MB plaintext)."""
        drive = DriveService()
        drive.master_keys = ["m" * 32]
        drive.api = mock.Mock()
        drive.api.get_file_metadata.return_value = {
            "metadata": "enc", "chunks": chunks, "region": "r", "bucket": "b",
        }
        drive._try_decrypt = mock.Mock(return_value=(
            '{"name": "f.bin", "size": %d, '
            '"key": "0123456789abcdef0123456789abcdef"}' % len(blob)
        ))
        drive.config = mock.Mock()
        drive.config.egest_url = "https://egest.example"

        def get(url, *a, **k):
            i = int(url.rstrip("/").split("/")[-1])
            resp = mock.Mock()
            resp.status_code = 200
            resp.content = blob[i * MB:(i + 1) * MB]  # "encrypted" == plaintext here
            time.sleep(0.01)
            return resp

        drive.api.session = mock.Mock()
        drive.api.session.get.side_effect = get
        drive.crypto = mock.Mock()
        drive.crypto.decrypt_data.side_effect = lambda data, key: data  # identity
        return drive

    def test_concurrent_download_reassembles_in_order(self):
        chunks = 5
        blob = os.urandom(4 * MB + 777)  # 5 chunks, last partial
        drive = self._make_download_drive(blob, chunks)
        out = _write_tmp(0)
        try:
            drive.download_file("file-uuid", save_path=out, quiet=True,
                                max_concurrent_chunks=4)
            with open(out, "rb") as fh:
                self.assertEqual(fh.read(), blob,
                                 "out-of-order chunk writes must reassemble byte-exactly")
        finally:
            os.remove(out)


if __name__ == "__main__":
    unittest.main()
