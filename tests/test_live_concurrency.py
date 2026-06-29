#!/usr/bin/env python3
"""
Live integration tests for Step 1 (bounded chunk concurrency) against the real
Filen backend. Authenticates via the saved CLI session
(~/.filen-cli/credentials.json) — no password needed. All work is confined to a
unique test folder and cleaned up.

Covers the live half of the Step 1 matrix:
  - round-trip a large multi-chunk file (10 MB): hash + byte-exact content,
  - an interrupted upload resumes (resume-as-a-set) and completes,
  - concurrent upload of a large file beats the sequential baseline,
  - a directory of many small files round-trips through the batch path.

Skipped automatically when no credentials are available.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_live_concurrency -v
"""

import os
import sys
import time
import hashlib
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.config import config_service  # noqa: E402
from services.drive import DriveService, ChunkUploadException  # noqa: E402

MB = 1048576


def _have_live_credentials():
    creds = config_service.read_credentials()
    return bool(creds and creds.get("apiKey") and creds.get("masterKeys"))


def _sha512(path):
    h = hashlib.sha512()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(MB), b""):
            h.update(block)
    return h.hexdigest().lower()


@unittest.skipUnless(
    _have_live_credentials(),
    "no saved Filen session (~/.filen-cli/credentials.json)",
)
class LiveConcurrencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.drive = DriveService()
        cls.drive.set_credentials(config_service.read_credentials())
        cls.folder_path = f"/__test_filen_python_concurrency__/{int(time.time() * 1000)}"
        cls.folder = cls.drive.create_folder_recursive(cls.folder_path)
        cls.parent_uuid = cls.folder["uuid"]
        cls.tmpdir = tempfile.mkdtemp(prefix="filen_conc_live_")

    @classmethod
    def tearDownClass(cls):
        for path in (cls.folder_path, "/__test_filen_python_concurrency__"):
            try:
                resolved = cls.drive.resolve_path(path)
                cls.drive.trash_item(resolved["uuid"], "folder")
                cls.drive.delete_permanent(resolved["uuid"], "folder")
            except Exception as e:  # cleanup is best-effort
                print(f"cleanup warning for {path}: {e}")
        try:
            import shutil
            shutil.rmtree(cls.tmpdir, ignore_errors=True)
        except Exception:
            pass

    def _tmp_file(self, name, nbytes):
        path = os.path.join(self.tmpdir, name)
        with open(path, "wb") as f:
            f.write(os.urandom(nbytes))
        return path

    def test_large_file_roundtrip(self):
        up = self._tmp_file("large.bin", 10 * MB + 4321)  # 11 chunks
        down = os.path.join(self.tmpdir, "large.down.bin")
        original_hash = _sha512(up)

        result = self.drive.upload_file_chunked(up, self.parent_uuid,
                                                max_concurrent_chunks=4)
        # The returned whole-file hash is the in-order plaintext SHA-512.
        self.assertEqual(result["hash"], original_hash)

        self.drive.download_file(result["uuid"], save_path=down, quiet=True,
                                 max_concurrent_chunks=4)
        self.assertEqual(_sha512(down), original_hash,
                         "downloaded content must be byte-exact")

    def test_interrupted_upload_resumes(self):
        up = self._tmp_file("resume.bin", 6 * MB + 50)  # 7 chunks
        down = os.path.join(self.tmpdir, "resume.down.bin")
        original_hash = _sha512(up)

        # Simulate a mid-upload failure: wrap the pooled session.post so the
        # 3rd chunk POST raises. Sequential (N=1) makes the failure point
        # deterministic: chunks 0,1 land, chunk 2 fails.
        real_post = self.drive.api.session.post
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 3:
                raise ConnectionError("simulated mid-upload failure")
            return real_post(*args, **kwargs)

        self.drive.api.session.post = flaky
        try:
            with self.assertRaises(ChunkUploadException) as ctx:
                self.drive.upload_file_chunked(up, self.parent_uuid,
                                               max_concurrent_chunks=1)
            exc = ctx.exception
        finally:
            self.drive.api.session.post = real_post

        self.assertTrue(exc.completed_chunks, "some chunks should have completed")
        self.assertTrue(exc.file_key, "resume must carry the file key")

        # Resume: reuse uuid + upload key + file key, skip the completed set,
        # finish the rest concurrently.
        result = self.drive.upload_file_chunked(
            up, self.parent_uuid,
            file_uuid=exc.file_uuid,
            upload_key=exc.upload_key,
            file_key=exc.file_key,
            completed_chunks=exc.completed_chunks,
            max_concurrent_chunks=4,
        )
        self.assertEqual(result["hash"], original_hash)

        self.drive.download_file(result["uuid"], save_path=down, quiet=True)
        self.assertEqual(_sha512(down), original_hash,
                         "resumed upload must reassemble byte-exactly")

    def test_concurrent_is_faster_than_sequential(self):
        up = self._tmp_file("speed.bin", 16 * MB)  # 16 chunks

        t0 = time.monotonic()
        seq = self.drive.upload_file_chunked(up, self.parent_uuid,
                                             target_filename="speed_seq.bin",
                                             max_concurrent_chunks=1)
        seq_time = time.monotonic() - t0

        t0 = time.monotonic()
        par = self.drive.upload_file_chunked(up, self.parent_uuid,
                                             target_filename="speed_par.bin",
                                             max_concurrent_chunks=8)
        par_time = time.monotonic() - t0

        print(f"\n[throughput] sequential={seq_time:.2f}s  "
              f"concurrent(8)={par_time:.2f}s  speedup={seq_time / par_time:.2f}x")
        self.assertEqual(seq["hash"], par["hash"])
        self.assertLess(par_time, seq_time,
                        "concurrent upload should beat the sequential baseline")

    def test_directory_of_small_files_roundtrips(self):
        src = os.path.join(self.tmpdir, "manyfiles")
        os.makedirs(src, exist_ok=True)
        expected = {}
        for i in range(12):
            name = f"small_{i:02d}.txt"
            content = (f"file {i} " * (50 + i)).encode()
            with open(os.path.join(src, name), "wb") as f:
                f.write(content)
            expected[name] = hashlib.sha512(content).hexdigest().lower()

        remote_dir = f"{self.folder_path}/manyfiles_upload"
        self.drive.upload([src], remote_dir, recursive=True, on_conflict="overwrite")

        dest = os.path.join(self.tmpdir, "manyfiles_down")
        os.makedirs(dest, exist_ok=True)
        self.drive.download_path(f"{remote_dir}/manyfiles", dest, recursive=True)

        # Find every downloaded file and check its hash.
        got = {}
        for root, _dirs, files in os.walk(dest):
            for fn in files:
                with open(os.path.join(root, fn), "rb") as f:
                    got[fn] = hashlib.sha512(f.read()).hexdigest().lower()

        for name, h in expected.items():
            self.assertIn(name, got, f"{name} missing from download")
            self.assertEqual(got[name], h, f"{name} content mismatch")


if __name__ == "__main__":
    unittest.main()
