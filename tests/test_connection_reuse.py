#!/usr/bin/env python3
"""
Unit tests for Step 0 (connection reuse).

Before the fix, every API call and every 1 MB chunk transfer used the bare
module-level `requests.get/post/delete`, opening a fresh TCP+TLS connection
each time. These tests pin the fix: a single pooled `requests.Session` is
created once per APIClient and reused for every request, and DriveService
shares that same session for chunk transfers.

Run from the repo root:
    .venv/bin/python -m unittest discover -s tests -v
"""

import os
import sys
import unittest
from unittest import mock

# Allow `import services...` / `import config...` when run from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402
from services.api import APIClient, api_client  # noqa: E402
from services.drive import DriveService  # noqa: E402


def _ok_response(payload=None):
    """A minimal stand-in for a requests.Response that _request accepts."""
    resp = mock.Mock()
    resp.status_code = 200
    resp.text = ""
    resp.json.return_value = payload or {"status": True, "data": {}}
    return resp


class PooledSessionTest(unittest.TestCase):
    def test_apiclient_creates_a_pooled_session(self):
        api = APIClient()
        self.assertIsInstance(api.session, requests.Session)

    def test_each_apiclient_owns_one_session(self):
        a, b = APIClient(), APIClient()
        self.assertIsNot(a.session, b.session)

    def test_request_goes_through_the_session_not_module_level(self):
        api = APIClient()
        api.session = mock.Mock()
        api.session.get.return_value = _ok_response()

        # Patch the module-level requests.* to ensure they're NOT used.
        with mock.patch("services.api.requests.get") as bare_get:
            result = api._request("GET", "/v3/test", use_auth=False)

        api.session.get.assert_called_once()
        bare_get.assert_not_called()
        self.assertTrue(result["status"])

    def test_session_is_reused_across_requests(self):
        # Session must be constructed once (at init), never per request.
        with mock.patch("services.api.requests.Session") as session_cls:
            session_cls.return_value.get.return_value = _ok_response()
            session_cls.return_value.post.return_value = _ok_response()

            api = APIClient()  # 1 construction
            api._request("GET", "/v3/a", use_auth=False)
            api._request("POST", "/v3/b", data={}, use_auth=False)

            self.assertEqual(
                session_cls.call_count, 1,
                "Session must be created once and reused, not per request",
            )


class DriveSharesSessionTest(unittest.TestCase):
    def test_drive_reuses_the_api_session_for_chunk_transfers(self):
        drive = DriveService()
        # DriveService binds to the api_client singleton, whose pooled session
        # is what the chunk download/upload paths now call (self.api.session).
        self.assertIs(drive.api, api_client)
        self.assertIsInstance(drive.api.session, requests.Session)

    def test_chunk_download_uses_the_pooled_session(self):
        """download_file_generator must fetch chunks via self.api.session.get."""
        drive = DriveService()
        drive.master_keys = ["k"]

        # Stub metadata + decrypt so we reach the chunk-fetch line, then assert
        # it is the pooled session (not module-level requests) doing the GET.
        drive.api = mock.Mock()
        drive.api.session = mock.Mock()
        chunk_resp = mock.Mock()
        chunk_resp.status_code = 200
        chunk_resp.content = b"\x00" * 16
        drive.api.session.get.return_value = chunk_resp
        drive.api.get_file_metadata.return_value = {
            "metadata": "enc", "chunks": 1, "region": "r", "bucket": "b",
        }
        drive._try_decrypt = mock.Mock(
            return_value='{"key": "0123456789abcdef0123456789abcdef", "size": 5}'
        )
        drive.crypto = mock.Mock()
        drive.crypto.decrypt_data.return_value = b"hello"

        chunks = list(drive.download_file_generator("file-uuid"))

        drive.api.session.get.assert_called_once()
        self.assertEqual(b"".join(chunks), b"hello")


if __name__ == "__main__":
    unittest.main()
