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
from wsgidav.dav_error import DAVError, HTTP_NOT_FOUND, HTTP_FORBIDDEN, HTTP_INTERNAL_ERROR

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

class StreamingFileWrapper:
    """
    Wraps the Filen download generator into a file-like object 
    compatible with WsgiDAV (supports read and seek).
    """
    def __init__(self, drive_instance, file_uuid, size):
        self.drive = drive_instance
        self.uuid = file_uuid
        self.total_size = size
        self.position = 0
        self.generator = None
        self.buffer = b""
    
    def seek(self, offset, whence=0):
        if whence == 0:   # Absolute
            new_pos = offset
        elif whence == 1: # Relative
            new_pos = self.position + offset
        elif whence == 2: # From end
            new_pos = self.total_size + offset
        else:
            raise ValueError("Invalid whence argument")
            
        # If position changed, reset generator to fetch from new offset
        if new_pos != self.position:
            self.position = max(0, min(new_pos, self.total_size))
            self.generator = None
            self.buffer = b""
        return self.position
        
    def read(self, size=-1):
        # Initialize generator if needed (lazy loading)
        if self.generator is None:
            self.generator = self.drive.download_file_generator(
                self.uuid, 
                offset=self.position
            )
            
        # Helper to fetch chunks until we have enough data
        def fill_buffer(target_size):
            try:
                while len(self.buffer) < target_size:
                    chunk = next(self.generator)
                    self.buffer += chunk
            except StopIteration:
                pass

        if size == -1:
            # Read everything
            chunks = [self.buffer]
            self.buffer = b""
            for chunk in self.generator:
                chunks.append(chunk)
            data = b"".join(chunks)
            self.position += len(data)
            return data
            
        # Read specific size
        fill_buffer(size)
        
        # Slice the buffer
        data = self.buffer[:size]
        self.buffer = self.buffer[size:]
        self.position += len(data)
        return data

    def tell(self):
        return self.position

    def close(self):
        self.generator = None
        self.buffer = b""

# --- Resources ---

class FilenDAVResource(DAVNonCollection):
    """Represents a File"""
    def __init__(self, path: str, environ: dict, metadata: dict):
        super().__init__(path, environ)
        self.metadata = metadata
        self._upload_handler = None
        
        # CRITICAL FIX: Initialize self.drive from environ or fallback to global
        # This prevents the AttributeError
        if "filen.drive_service" in environ:
            self.drive = environ["filen.drive_service"]
        else:
            # Fallback if environ wasn't set (shouldn't happen with correct Provider)
            self.drive = drive_service

    def get_content_length(self) -> int:
        return int(self.metadata.get('size', 0))

    def get_creation_date(self) -> float:
        return float(self.metadata.get('timestamp', 0)) / 1000.0

    def get_last_modified(self) -> float:
        return float(self.metadata.get('lastModified', 0)) / 1000.0

    def get_etag(self) -> str:
        return f"{self.metadata['uuid']}-{self.metadata.get('lastModified')}"

    # --- REQUIRED ABSTRACT METHODS IMPLEMENTATION ---
    def support_etag(self) -> bool:
        return True

    def support_modified(self) -> bool:
        return True
        
    def support_content_length(self) -> bool:
        return True
    
    def support_ranges(self) -> bool:
        return True
    # ------------------------------------------------

    def get_content(self) -> Any:
        """Stream download using the wrapper to prevent 500 errors"""
        return StreamingFileWrapper(
            self.drive, 
            self.metadata['uuid'], 
            int(self.metadata.get('size', 0))
        )

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
                    resolved = self.drive.resolve_path(parent_path)
                    parent_uuid = resolved['uuid']
                else:
                    parent_uuid = self.drive.base_folder_uuid

                # Check if this is an overwrite (update) or new
                existing_uuid = self.metadata.get('uuid') if not self.metadata.get('virtual') else None
                
                if existing_uuid:
                     self.drive.trash_item(existing_uuid, 'file')
                
                # Upload
                self.drive.upload_file_chunked(
                    file_path=temp_path,
                    parent_uuid=parent_uuid,
                    preserve_timestamps=True 
                )
        except Exception as e:
            print(f"❌ WebDAV Upload Error: {e}")
            raise DAVError(HTTP_FORBIDDEN, str(e))
        finally:
            self._upload_handler.cleanup()

    def delete(self):
        self.drive.trash_item(self.metadata['uuid'], 'file')

    def set_property(self, name, value, dry_run=False):
        """Handle PROPPATCH (timestamps)"""
        # WsgiDAV property setting logic
        if name == "{DAV:}getlastmodified":
            pass # Implement timestamp update logic here if desired
        return

    def move_recursive(self, dest_path):
        """Move file to new location"""
        try:
            # 1. Resolve destination parent
            parent_path = os.path.dirname(dest_path)
            parent_node = self.drive.resolve_path(parent_path)
            
            if parent_node['type'] != 'folder':
                 raise DAVError(HTTP_FORBIDDEN, "Destination parent is not a folder")

            # 2. Perform Move
            self.drive.move_item(self.metadata['uuid'], parent_node['uuid'], 'file')
            
            # 3. Rename if needed
            new_name = os.path.basename(dest_path)
            if new_name != self.metadata['name']:
                self.drive.rename_item(self.metadata['uuid'], new_name, 'file')
                
        except Exception as e:
            raise DAVError(HTTP_INTERNAL_ERROR, f"Move failed: {e}")

    def copy_move(self, dest_path):
        """Copy file to new location"""
        try:
            parent_path = os.path.dirname(dest_path)
            parent_node = self.drive.resolve_path(parent_path)

            if parent_node['type'] != 'folder':
                 raise DAVError(HTTP_FORBIDDEN, "Destination parent is not a folder")

            new_name = os.path.basename(dest_path)
            self.drive.copy_file(self.metadata['uuid'], parent_node['uuid'], new_name)
            
        except Exception as e:
            raise DAVError(HTTP_INTERNAL_ERROR, f"Copy failed: {e}")

class FilenDAVCollection(DAVCollection):
    """Represents a Folder"""
    def __init__(self, path: str, environ: dict, metadata: dict):
        super().__init__(path, environ)
        self.metadata = metadata
        
        # CRITICAL FIX: Initialize self.drive
        if "filen.drive_service" in environ:
            self.drive = environ["filen.drive_service"]
        else:
            self.drive = drive_service

    # --- REQUIRED ABSTRACT METHODS IMPLEMENTATION ---
    def support_etag(self) -> bool:
        return True

    def support_modified(self) -> bool:
        return True
        
    def support_content_length(self) -> bool:
        return False
    # ------------------------------------------------
        
    def get_member_names(self) -> List[str]:
        uuid = self.metadata['uuid']
        # Use isolated session
        folders = self.drive.list_folders(uuid, detailed=False)
        files = self.drive.list_files(uuid, detailed=False)
        return [f['name'] for f in folders] + [f['name'] for f in files]

    def get_member(self, name: str) -> Optional[Union['FilenDAVCollection', 'FilenDAVResource']]:
        uuid = self.metadata['uuid']
        
        folders = self.drive.list_folders(uuid, detailed=True)
        for f in folders:
            if f['name'] == name:
                child_path = os.path.join(self.path, name).replace('\\', '/')
                return FilenDAVCollection(child_path, self.environ, f)
                
        files = self.drive.list_files(uuid, detailed=True)
        for f in files:
            if f['name'] == name:
                child_path = os.path.join(self.path, name).replace('\\', '/')
                return FilenDAVResource(child_path, self.environ, f)
        
        return None

    def create_empty_resource(self, name: str):
        child_path = os.path.join(self.path, name).replace('\\', '/')
        virtual_meta = {'name': name, 'size': 0, 'uuid': None, 'virtual': True}
        return FilenDAVResource(child_path, self.environ, virtual_meta)

    def create_collection(self, name: str):
        self.drive.create_folder(name, self.metadata['uuid'])

    def delete(self):
        if self.path == '/':
            raise DAVError(HTTP_FORBIDDEN, "Cannot delete root")
        self.drive.trash_item(self.metadata['uuid'], 'folder')

    def move_recursive(self, dest_path):
        """Move folder to new location"""
        try:
            parent_path = os.path.dirname(dest_path)
            parent_node = self.drive.resolve_path(parent_path)
            
            if parent_node['type'] != 'folder':
                 raise DAVError(HTTP_FORBIDDEN, "Destination parent is not a folder")

            self.drive.move_item(self.metadata['uuid'], parent_node['uuid'], 'folder')
            
            new_name = os.path.basename(dest_path)
            if new_name != self.metadata['name']:
                self.drive.rename_item(self.metadata['uuid'], new_name, 'folder')
                
        except Exception as e:
             raise DAVError(HTTP_INTERNAL_ERROR, f"Move failed: {e}")

# --- Provider ---

class FilenDAVProvider(DAVProvider):
    def __init__(self, preserve_timestamps: bool = True):
        super().__init__()
        self.preserve_timestamps = preserve_timestamps
        
        if not auth_service.whoami():
            print("❌ WebDAV Provider: No credentials found. Please login first.")

    def _get_drive(self, environ: dict):
        """Get or create the thread-local drive service"""
        # Checks if we already created an isolated service for this request
        if "filen.drive_service" not in environ:
            try:
                # Attempt to create a fresh, isolated session
                environ["filen.drive_service"] = drive_service.get_isolated_instance()
            except AttributeError:
                # If user hasn't updated drive.py yet, fallback to global (not thread safe but works)
                environ["filen.drive_service"] = drive_service
        return environ["filen.drive_service"]

    def exists(self, path: str, environ: dict) -> bool:
        """Fast existence check"""
        drive = self._get_drive(environ)
        try:
            if path == '/' or path == '':
                return True
            drive.resolve_path(path)
            return True
        except FileNotFoundError:
            return False

    def get_resource_inst(self, path: str, environ: dict) -> Optional[Union['FilenDAVCollection', 'FilenDAVResource']]:
        try:
            # Ensure drive is initialized in environ
            drive = self._get_drive(environ)
            
            if path == '/':
                meta = {'uuid': drive.base_folder_uuid, 'name': 'Root'}
                return FilenDAVCollection('/', environ, meta)
                
            try:
                resolved = drive.resolve_path(path)
            except FileNotFoundError:
                return None

            if resolved['type'] == 'folder':
                return FilenDAVCollection(path, environ, resolved['metadata'])
            else:
                return FilenDAVResource(path, environ, resolved['metadata'])

        except Exception as e:
            print(f"DAV Error resolving {path}: {e}")
            return None