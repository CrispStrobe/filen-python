#!/usr/bin/env python3
"""
filen_cli/services/api.py
API client for Filen - COMPLETE VERSION with ALL endpoints
"""

import requests
import json
from typing import Dict, Any, Optional
from config.config import config_service


class APIClient:
    """Handles all API requests to Filen"""

    def __init__(self):
        self.config = config_service
        self.api_key = None
        self.base_url = config_service.api_url
        self.ingest_url = config_service.ingest_url
        self.egest_url = config_service.egest_url
        self.debug = False

    def set_auth(self, api_key: str) -> None:
        """Set authentication API key"""
        self.api_key = api_key

    def _log(self, message: str) -> None:
        """Debug logging"""
        if self.debug:
            print(f"🔍 [DEBUG] {message}")

    def _request(self, method: str, endpoint: str, data: Any = None, 
                 use_auth: bool = True, max_retries: int = 3) -> Dict[str, Any]:
        """
        Make HTTP request with retry logic
        Matches Dart _makeRequest implementation
        """
        url = f"{self.base_url}{endpoint}"
        headers = {'Content-Type': 'application/json'}
        
        if use_auth and self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        
        for attempt in range(max_retries):
            try:
                if method == 'GET':
                    response = requests.get(url, headers=headers, timeout=30)
                elif method == 'POST':
                    response = requests.post(url, headers=headers, 
                                           json=data, timeout=30)
                elif method == 'DELETE':
                    response = requests.delete(url, headers=headers,
                                             json=data, timeout=30)
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                # Handle server errors with retry
                if 500 <= response.status_code < 600:
                    if attempt < max_retries - 1:
                        import time
                        delay = 2 ** attempt
                        self._log(f"Server error {response.status_code}, retrying in {delay}s...")
                        time.sleep(delay)
                        continue
                
                # Check response
                if response.status_code >= 400:
                    self._log(f"API Error {response.status_code}: {response.text}")
                    raise Exception(f"API Error: {response.status_code} - {response.text}")
                
                result = response.json()
                
                if not result.get('status'):
                    raise Exception(result.get('message', 'Unknown error'))
                
                return result
                
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    import time
                    delay = 2 ** attempt
                    self._log(f"Network error, retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                raise Exception(f"Network request failed: {e}")
        
        raise Exception(f"Request failed after {max_retries} attempts")

    # ============================================================================
    # Authentication
    # ============================================================================

    def get_auth_info(self, email: str) -> Dict[str, Any]:
        """Get authentication info for user"""
        response = self._request('POST', '/v3/auth/info', 
                                {'email': email}, use_auth=False)
        return response.get('data', response)

    def login(self, email: str, derived_password: str, auth_version: int,
              tfa_code: str = "XXXXXX") -> Dict[str, Any]:
        """Perform login"""
        payload = {
            'email': email.lower(),
            'password': derived_password,
            'authVersion': auth_version,
            'twoFactorCode': tfa_code
        }
        
        response = self._request('POST', '/v3/login', payload, use_auth=False)
        return response.get('data', response)

    def get_base_folder_uuid(self) -> str:
        """Get user's root folder UUID"""
        response = self._request('GET', '/v3/user/baseFolder')
        data = response.get('data', response)
        return data.get('uuid', '')

    # ============================================================================
    # Folder Operations
    # ============================================================================

    def get_dir_content(self, folder_uuid: str, folders_only: bool = False) -> Dict[str, Any]:
        """Get folder contents"""
        response = self._request('POST', '/v3/dir/content', 
                                {'uuid': folder_uuid, 'foldersOnly': folders_only})
        return response.get('data', {})

    def create_folder(self, uuid: str, name_encrypted: str, name_hashed: str,
                     parent_uuid: str) -> None:
        """Create a folder"""
        payload = {
            'uuid': uuid,
            'name': name_encrypted,
            'nameHashed': name_hashed,
            'parent': parent_uuid
        }
        self._request('POST', '/v3/dir/create', payload)

    def get_folder_metadata(self, folder_uuid: str) -> Dict[str, Any]:
        """Get folder metadata"""
        response = self._request('POST', '/v3/dir', {'uuid': folder_uuid})
        return response.get('data', response)

    def move_folder(self, uuid: str, to_uuid: str) -> None:
        """Move folder"""
        self._request('POST', '/v3/dir/move', {'uuid': uuid, 'to': to_uuid})

    def rename_folder(self, uuid: str, name_encrypted: str, name_hashed: str) -> None:
        """Rename folder"""
        payload = {
            'uuid': uuid,
            'name': name_encrypted,
            'nameHashed': name_hashed
        }
        self._request('POST', '/v3/dir/rename', payload)

    def trash_folder(self, uuid: str) -> None:
        """Move folder to trash"""
        self._request('POST', '/v3/dir/trash', {'uuid': uuid})

    def restore_folder(self, uuid: str) -> None:
        """Restore folder from trash"""
        self._request('POST', '/v3/dir/restore', {'uuid': uuid})

    def delete_folder_permanent(self, uuid: str) -> None:
        """Permanently delete folder"""
        self._request('POST', '/v3/dir/delete/permanent', {'uuid': uuid})

    # ============================================================================
    # File Operations
    # ============================================================================

    def get_file_metadata(self, file_uuid: str) -> Dict[str, Any]:
        """Get file metadata"""
        response = self._request('POST', '/v3/file', {'uuid': file_uuid})
        return response.get('data', response)

    def check_file_exists(self, parent_uuid: str, name_hashed: str) -> bool:
        """Check if file exists"""
        try:
            response = self._request('POST', '/v3/file/exists',
                                    {'parent': parent_uuid, 'nameHashed': name_hashed})
            return response.get('data', {}).get('exists', False)
        except:
            return False

    def upload_empty_file(self, uuid: str, name_encrypted: str, name_hashed: str,
                         size_encrypted: str, parent_uuid: str, mime_encrypted: str,
                         metadata_encrypted: str) -> None:
        """Upload empty file"""
        payload = {
            'uuid': uuid,
            'name': name_encrypted,
            'nameHashed': name_hashed,
            'size': size_encrypted,
            'parent': parent_uuid,
            'mime': mime_encrypted,
            'metadata': metadata_encrypted,
            'version': 2
        }
        self._request('POST', '/v3/upload/empty', payload)

    def upload_done(self, uuid: str, name_encrypted: str, name_hashed: str,
                   size_encrypted: str, chunks: int, mime_encrypted: str,
                   metadata_encrypted: str, upload_key: str, rm: str) -> None:
        """Mark chunked upload as complete"""
        payload = {
            'uuid': uuid,
            'name': name_encrypted,
            'nameHashed': name_hashed,
            'size': size_encrypted,
            'chunks': chunks,
            'mime': mime_encrypted,
            'rm': rm,
            'metadata': metadata_encrypted,
            'version': 2,
            'uploadKey': upload_key
        }
        self._request('POST', '/v3/upload/done', payload)

    def move_file(self, uuid: str, to_uuid: str) -> None:
        """Move file"""
        self._request('POST', '/v3/file/move', {'uuid': uuid, 'to': to_uuid})

    def rename_file(self, uuid: str, name_encrypted: str, metadata_encrypted: str,
                   name_hashed: str) -> None:
        """Rename file"""
        payload = {
            'uuid': uuid,
            'name': name_encrypted,
            'metadata': metadata_encrypted,
            'nameHashed': name_hashed
        }
        self._request('POST', '/v3/file/rename', payload)

    def trash_file(self, uuid: str) -> None:
        """Move file to trash"""
        self._request('POST', '/v3/file/trash', {'uuid': uuid})

    def restore_file(self, uuid: str) -> None:
        """Restore file from trash"""
        self._request('POST', '/v3/file/restore', {'uuid': uuid})

    def delete_file_permanent(self, uuid: str) -> None:
        """Permanently delete file"""
        self._request('POST', '/v3/file/delete/permanent', {'uuid': uuid})


# Global instance
api_client = APIClient()