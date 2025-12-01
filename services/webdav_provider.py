#!/usr/bin/env python3
"""
filen_cli/services/webdav_provider.py
WebDAV Provider bridging WsgiDAV and Filen DriveService
"""

import os
import io
import time
import tempfile
from typing import Dict, Any, List, Optional, Union
from wsgidav.dav_provider import DAVProvider, DAVCollection, DAVNonCollection
from wsgidav.dav_error import DAVError, HTTP_NOT_FOUND, HTTP_FORBIDDEN

from services.drive import drive_service
from services.auth import auth_service

# --- Helpers ---

class StreamingFileUpload:
    """Buffers upload to temp file, then hands off to DriveService"""
    def __init__(self):
        self.fd, self.temp_path = tempfile.mkstemp(prefix="filen_dav_")
        self.file = os.fdopen(self.fd, 'wb')
        
    def write(self, data):
        self.file.write(data)
        
    def close(self):
        if not self.file.closed:
            self.file.close()

    def cleanup(self):
        self.close()
        if os.path.exists(self.temp_path):
            os.unlink(self.temp_path)

# --- Resources ---

class FilenDAVResource(DAVNonCollection):
    """Represents a File"""
    def __init__(self, path: str, environ: dict, metadata: dict):
        super().__init__(path, environ)
        self.metadata = metadata
        self._upload_handler = None

    def get_content_length(self) -> int:
        return int(self.metadata.get('size', 0))

    def get_creation_date(self) -> float:
        return float(self.metadata.get('timestamp', 0)) / 1000.0

    def get_last_modified(self) -> float:
        return float(self.metadata.get('lastModified', 0)) / 1000.0

    def get_etag(self) -> str:
        return f"{self.metadata['uuid']}-{self.metadata.get('lastModified')}"

    def support_ranges(self) -> bool:
        return True

    def get_content(self) -> Any:
        """Stream download"""
        uuid = self.metadata['uuid']
        # drive_service.download_file_generator yields bytes
        # We wrap it in an iterator suitable for WSGI response
        return drive_service.download_file_generator(uuid)

    def begin_write(self, content_type=None):
        self._upload_handler = StreamingFileUpload()
        return self._upload_handler

    def end_write(self, with_errors: bool):
        if not self._upload_handler:
            return

        try:
            if not with_errors:
                self._upload_handler.close()
                temp_path = self._upload_handler.temp_path
                
                # Determine parent UUID
                path_parts = self.path.strip('/').split('/')
                filename = path_parts[-1]
                
                if len(path_parts) > 1:
                    parent_path = '/' + '/'.join(path_parts[:-1])
                    resolved = drive_service.resolve_path(parent_path)
                    parent_uuid = resolved['uuid']
                else:
                    parent_uuid = drive_service.base_folder_uuid

                # Check if this is an overwrite (update) or new
                existing_uuid = self.metadata.get('uuid') if not self.metadata.get('virtual') else None
                
                if existing_uuid:
                     # Delete old, upload new (simplest atomic update for now)
                     # Or implement versioning update if API supports it easily
                     drive_service.trash_item(existing_uuid, 'file')
                
                # Upload
                # We reuse upload_file_chunked which expects a path
                drive_service.upload_file_chunked(
                    file_path=temp_path,
                    parent_uuid=parent_uuid,
                    preserve_timestamps=True # Respect client timestamps if possible
                )
                
                # Since we uploaded a new file, the old UUID in self.metadata is stale
                # But WsgiDAV will re-fetch the resource on next access
        except Exception as e:
            print(f"❌ WebDAV Upload Error: {e}")
            raise DAVError(HTTP_FORBIDDEN, str(e))
        finally:
            self._upload_handler.cleanup()

    def delete(self):
        drive_service.trash_item(self.metadata['uuid'], 'file')

    def copy_move(self, dest_path):
        # Implementation depends on logic in drive_service
        # For now, we can simply map Move to drive_service.move_item
        pass # To be implemented similar to delete

class FilenDAVCollection(DAVCollection):
    """Represents a Folder"""
    def __init__(self, path: str, environ: dict, metadata: dict):
        super().__init__(path, environ)
        self.metadata = metadata
        
    def get_member_names(self) -> List[str]:
        # Using cache logic from DriveService
        uuid = self.metadata['uuid']
        folders = drive_service.list_folders(uuid, detailed=False)
        files = drive_service.list_files(uuid, detailed=False)
        return [f['name'] for f in folders] + [f['name'] for f in files]

    def get_member(self, name: str) -> Optional[Union['FilenDAVCollection', 'FilenDAVResource']]:
        uuid = self.metadata['uuid']
        
        # Check cache via DriveService (it handles caching internally)
        folders = drive_service.list_folders(uuid, detailed=True)
        for f in folders:
            if f['name'] == name:
                child_path = os.path.join(self.path, name).replace('\\', '/')
                return FilenDAVCollection(child_path, self.environ, f)
                
        files = drive_service.list_files(uuid, detailed=True)
        for f in files:
            if f['name'] == name:
                child_path = os.path.join(self.path, name).replace('\\', '/')
                return FilenDAVResource(child_path, self.environ, f)
        
        return None

    def create_empty_resource(self, name: str):
        # Return a virtual resource that will be actualized on end_write
        child_path = os.path.join(self.path, name).replace('\\', '/')
        virtual_meta = {'name': name, 'size': 0, 'uuid': None, 'virtual': True}
        return FilenDAVResource(child_path, self.environ, virtual_meta)

    def create_collection(self, name: str):
        drive_service.create_folder(name, self.metadata['uuid'])

    def delete(self):
        if self.path == '/':
            raise DAVError(HTTP_FORBIDDEN, "Cannot delete root")
        drive_service.trash_item(self.metadata['uuid'], 'folder')

# --- Provider ---

class FilenDAVProvider(DAVProvider):
    def __init__(self, preserve_timestamps: bool = True):
        super().__init__()
        self.preserve_timestamps = preserve_timestamps
        
        # Ensure we are logged in
        if not auth_service.read_credentials():
            print("❌ WebDAV Provider: No credentials found. Please login first.")

    def get_resource_inst(self, path: str, environ: dict) -> Optional[Union['FilenDAVCollection', 'FilenDAVResource']]:
        try:
            # We use DriveService's resolve_path to find the UUID and type
            # Note: resolve_path throws FileNotFoundError if not found
            if path == '/':
                meta = {'uuid': drive_service.base_folder_uuid, 'name': 'Root'}
                return FilenDAVCollection('/', environ, meta)
                
            try:
                resolved = drive_service.resolve_path(path)
            except FileNotFoundError:
                return None

            if resolved['type'] == 'folder':
                return FilenDAVCollection(path, environ, resolved['metadata'])
            else:
                return FilenDAVResource(path, environ, resolved['metadata'])

        except Exception as e:
            print(f"DAV Error resolving {path}: {e}")
            return None