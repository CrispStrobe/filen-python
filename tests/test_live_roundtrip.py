#!/usr/bin/env python3
"""
Live integration test against the real Filen backend.

Authenticates via a saved CLI session (~/.filen-cli/credentials.json) — apiKey +
master keys, so no password is needed. Exercises the full chunked upload +
download round-trip, which now flows through the pooled requests.Session
(Step 0). All work is confined to a unique test folder and cleaned up.

Skipped automatically when no credentials are available.

Run from the repo root:
    .venv/bin/python -m unittest tests.test_live_roundtrip -v
"""

import os
import sys
import time
import json
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.config import config_service  # noqa: E402
from services.drive import DriveService  # noqa: E402
from services.api import api_client  # noqa: E402
import requests  # noqa: E402


def _have_live_credentials():
    creds = config_service.read_credentials()
    return bool(creds and creds.get("apiKey") and creds.get("masterKeys"))


@unittest.skipUnless(
    _have_live_credentials(),
    "no saved Filen session (~/.filen-cli/credentials.json)",
)
class LiveRoundTripTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.drive = DriveService()
        cls.drive.set_credentials(config_service.read_credentials())
        cls.folder_path = f"/__test_filen_python_smoke__/{int(time.time() * 1000)}"
        cls.folder = cls.drive.create_folder_recursive(cls.folder_path)

    @classmethod
    def tearDownClass(cls):
        for path in (cls.folder_path, "/__test_filen_python_smoke__"):
            try:
                resolved = cls.drive.resolve_path(path)
                cls.drive.trash_item(resolved["uuid"], "folder")
                cls.drive.delete_permanent(resolved["uuid"], "folder")
            except Exception as e:  # cleanup is best-effort
                print(f"cleanup warning for {path}: {e}")

    def test_session_is_pooled(self):
        # The same pooled session backs both API calls and chunk transfers.
        self.assertIsInstance(self.drive.api.session, requests.Session)
        self.assertIs(self.drive.api, api_client)

    def test_upload_then_download_roundtrip(self):
        payload = "Hello from filen-python live test!"
        parent_uuid = self.folder["uuid"]

        up_path = os.path.join(tempfile.gettempdir(), "filen_py_live_up.txt")
        down_path = os.path.join(tempfile.gettempdir(), "filen_py_live_down.txt")
        with open(up_path, "w") as f:
            f.write(payload)

        try:
            result = self.drive.upload_file_chunked(up_path, parent_uuid)
            self.assertTrue(result.get("uuid"))

            self.drive.download_file(result["uuid"], save_path=down_path,
                                     quiet=True)
            with open(down_path) as f:
                self.assertEqual(f.read(), payload)
        finally:
            for p in (up_path, down_path):
                if os.path.exists(p):
                    os.remove(p)


if __name__ == "__main__":
    unittest.main()
