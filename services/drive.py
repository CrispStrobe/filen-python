#!/usr/bin/env python3
"""
filen_cli/services/drive.py
File operations for Filen with batching, resume, search, etc.
"""

import os
import json
import hashlib
import glob as glob_module
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Tuple, Iterator
from datetime import datetime

try:
    from tqdm import tqdm
except ImportError:
    # Fallback if not installed: return a dummy iterator
    def tqdm(iterable=None, **kwargs):
        return iterable if iterable else []

from config.config import config_service
from services.api import api_client
from services.crypto import crypto_service


class ChunkUploadException(Exception):
    """Exception for chunk upload failures with resume info"""
    def __init__(self, message: str, file_uuid: str, upload_key: str, 
                 last_successful_chunk: int, original_error: Exception = None):
        self.message = message
        self.file_uuid = file_uuid
        self.upload_key = upload_key
        self.last_successful_chunk = last_successful_chunk
        self.original_error = original_error
        super().__init__(message)


class DriveService:
    """Handles all file operations"""

    def __init__(self):
        self.config = config_service
        self.api = api_client
        self.crypto = crypto_service
        self.email = None
        self.master_keys = []
        self.base_folder_uuid = None
        self.debug = False
        
        # Cache
        self._folder_cache = {}
        self._file_cache = {}
        self._path_cache = {}  # Caches path strings to UUIDs
        self._cache_duration = 600  # 10 minutes

    def set_credentials(self, credentials: Dict[str, Any]) -> None:
        """Set credentials from login"""
        self.email = credentials.get('email')
        self.base_folder_uuid = credentials.get('baseFolderUUID')
        
        master_keys_str = credentials.get('masterKeys', '')
        self.master_keys = [k for k in master_keys_str.split('|') if k]
        
        self.api.set_auth(credentials.get('apiKey'))

    def _log(self, message: str) -> None:
        """Debug logging"""
        if self.debug:
            print(f"🔍 [DEBUG] {message}")

    def _get_master_key(self) -> str:
        """Get the latest master key"""
        if not self.master_keys:
            raise ValueError("No master keys available")
        return self.master_keys[-1]

    def _invalidate_cache(self, folder_uuid: str) -> None:
        """Invalidate cache for a folder"""
        self._folder_cache.pop(folder_uuid, None)
        self._file_cache.pop(folder_uuid, None)
        
        # Clear path cache on modification to be safe
        self._path_cache = {} 
        
        self._log(f"Cache invalidated for folder: {folder_uuid}")

    def _try_decrypt(self, encrypted: str) -> str:
        """Try to decrypt with all master keys"""
        for key in reversed(self.master_keys):
            try:
                return self.crypto.decrypt_metadata_002(encrypted, key)
            except:
                continue
        raise Exception("Failed to decrypt with any master key")
    
    def download_file_generator(self, file_uuid: str, offset: int = 0, length: Optional[int] = None) -> Iterator[bytes]:
        """
        Yields decrypted file bytes for streaming (WebDAV support).
        """
        import requests
        
        # Get metadata and decrypt
        metadata = self.api.get_file_metadata(file_uuid)
        encrypted_metadata = metadata.get('metadata')
        decrypted_str = self._try_decrypt(encrypted_metadata)
        meta = json.loads(decrypted_str)
        
        file_key = meta.get('key', '')
        chunks = int(metadata.get('chunks', 0))
        region = metadata.get('region')
        bucket = metadata.get('bucket')
        total_size = int(meta.get('size', 0))

        # Decode file key
        if len(file_key) == 32:
            file_key_bytes = file_key.encode('utf-8')
        else:
            import base64
            file_key_bytes = base64.b64decode(file_key)

        # Calculate start/end chunks based on offset (Simplification: assumes 1MB chunks)
        # Note: Precision seeking in encrypted GCM streams is hard without overhead. 
        # We will stream from the specific chunk containing the offset.
        CHUNK_SIZE = 1048576 # 1MB standard Filen chunk
        
        start_chunk = offset // CHUNK_SIZE
        bytes_to_skip_in_first_chunk = offset % CHUNK_SIZE
        
        bytes_yielded = 0
        limit = length if length is not None else (total_size - offset)

        for i in range(start_chunk, chunks):
            if bytes_yielded >= limit:
                break

            url = f"{self.config.egest_url}/{region}/{bucket}/{file_uuid}/{i}"
            response = requests.get(url, stream=True, timeout=30)
            
            if response.status_code != 200:
                raise Exception(f"Chunk download failed: {response.status_code}")
            
            # Read full chunk and decrypt (GCM requires full block for tag verification)
            encrypted_data = response.content
            try:
                decrypted_chunk = self.crypto.decrypt_data(encrypted_data, file_key_bytes)
            except Exception as e:
                print(f"Decryption error on chunk {i}: {e}")
                break

            # Handle offset logic
            if i == start_chunk:
                data_slice = decrypted_chunk[bytes_to_skip_in_first_chunk:]
            else:
                data_slice = decrypted_chunk

            # Handle length limit
            if bytes_yielded + len(data_slice) > limit:
                data_slice = data_slice[:limit - bytes_yielded]

            if data_slice:
                yield data_slice
                bytes_yielded += len(data_slice)

    # ============================================================================
    # LIST OPERATIONS WITH CACHING
    # ============================================================================

    def list_folders(self, folder_uuid: str, use_cache: bool = True, detailed: bool = False) -> List[Dict[str, Any]]:
        """List folders in a directory"""
        # Check cache
        if use_cache and folder_uuid in self._folder_cache:
            cache_entry = self._folder_cache[folder_uuid]
            age = (datetime.now() - cache_entry['timestamp']).seconds
            if age < self._cache_duration:
                self._log(f"Using cached folder list for {folder_uuid}")
                data = cache_entry['data']
                if not detailed:
                    return [{k: v for k, v in item.items() if k in ['type', 'name', 'uuid', 'size']} 
                            for item in data]
                return data
        
        # Fetch from API
        content = self.api.get_dir_content(folder_uuid, folders_only=False)
        folders = content.get('folders', [])
        
        result = []
        for f in folders:
            try:
                encrypted_name = f.get('name', '')
                decrypted = self._try_decrypt(encrypted_name)
                
                # Parse name from JSON if needed
                if decrypted.startswith('{'):
                    name = json.loads(decrypted).get('name', 'Unknown')
                else:
                    name = decrypted
                
                result.append({
                    'type': 'folder',
                    'name': name,
                    'uuid': f.get('uuid'),
                    'parent': f.get('parent'),
                    'timestamp': f.get('timestamp', 0),
                    'lastModified': f.get('lastModified', 0),
                    'size': 0
                })
            except Exception as e:
                self._log(f"Failed to decrypt folder name: {e}")
                result.append({
                    'type': 'folder',
                    'name': '[Encrypted]',
                    'uuid': f.get('uuid'),
                    'parent': f.get('parent'),
                    'size': 0
                })
        
        # Update cache
        self._folder_cache[folder_uuid] = {
            'data': result,
            'timestamp': datetime.now()
        }
        
        if not detailed:
            return [{k: v for k, v in item.items() if k in ['type', 'name', 'uuid', 'size']} 
                    for item in result]
        return result

    def list_files(self, folder_uuid: str, use_cache: bool = True, detailed: bool = False) -> List[Dict[str, Any]]:
        """List files in a directory"""
        # Check cache
        if use_cache and folder_uuid in self._file_cache:
            cache_entry = self._file_cache[folder_uuid]
            age = (datetime.now() - cache_entry['timestamp']).seconds
            if age < self._cache_duration:
                self._log(f"Using cached file list for {folder_uuid}")
                data = cache_entry['data']
                if not detailed:
                    return [{k: v for k, v in item.items() if k in ['type', 'name', 'uuid', 'size']} 
                            for item in data]
                return data
        
        # Fetch from API
        content = self.api.get_dir_content(folder_uuid, folders_only=False)
        files = content.get('uploads', [])
        
        result = []
        for f in files:
            try:
                encrypted_metadata = f.get('metadata', '')
                decrypted = self._try_decrypt(encrypted_metadata)
                metadata = json.loads(decrypted)
                
                result.append({
                    'type': 'file',
                    'name': metadata.get('name', 'Unknown'),
                    'uuid': f.get('uuid'),
                    'size': metadata.get('size', 0),
                    'parent': f.get('parent'),
                    'timestamp': f.get('timestamp', 0),
                    'lastModified': metadata.get('lastModified', 0),
                    'chunks': int(f.get('chunks', 0)),
                    'region': f.get('region'),
                    'bucket': f.get('bucket'),
                    'key': metadata.get('key'),
                    'hash': metadata.get('hash', '')
                })
            except Exception as e:
                self._log(f"Failed to decrypt file metadata: {e}")
                result.append({
                    'type': 'file',
                    'name': '[Encrypted]',
                    'uuid': f.get('uuid'),
                    'size': 0
                })
        
        # Update cache
        self._file_cache[folder_uuid] = {
            'data': result,
            'timestamp': datetime.now()
        }
        
        if not detailed:
            return [{k: v for k, v in item.items() if k in ['type', 'name', 'uuid', 'size']} 
                    for item in result]
        return result

    # ============================================================================
    # PATH RESOLUTION
    # ============================================================================

    def resolve_path(self, path: str) -> Dict[str, Any]:
        """
        Resolve a path to a folder or file
        """
        if not self.base_folder_uuid:
            raise ValueError("Not logged in")
        
        # Clean path
        path = path.strip()
        if path.startswith('/'):
            path = path[1:]
        if path.endswith('/'):
            path = path[:-1]
        
        # Root folder
        if not path or path == '.':
            return {
                'type': 'folder',
                'uuid': self.base_folder_uuid,
                'path': '/',
                'metadata': {'uuid': self.base_folder_uuid, 'name': 'Root'}
            }
        
        # Traverse path
        parts = [p for p in path.split('/') if p]
        current_uuid = self.base_folder_uuid
        current_path = '/'
        
        for i, part in enumerate(parts):
            is_last = (i == len(parts) - 1)
            
            # List folders
            folders = self.list_folders(current_uuid, detailed=True)
            
            # Find matching folder
            found_folder = None
            for folder in folders:
                if folder['name'] == part:
                    found_folder = folder
                    break
            
            # Check files if last part
            found_file = None
            if is_last:
                files = self.list_files(current_uuid, detailed=True)
                for file in files:
                    if file['name'] == part:
                        found_file = file
                        break
            
            # Determine what we found
            if found_folder and (not is_last or not found_file):
                current_uuid = found_folder['uuid']
                current_path = f"{current_path}{part}/"
                
                if is_last:
                    return {
                        'type': 'folder',
                        'uuid': found_folder['uuid'],
                        'path': current_path.rstrip('/'),
                        'metadata': found_folder,
                        'parent': found_folder.get('parent')
                    }
            elif found_file and is_last:
                current_path = f"{current_path}{part}"
                return {
                    'type': 'file',
                    'uuid': found_file['uuid'],
                    'path': current_path,
                    'metadata': found_file,
                    'parent': current_uuid
                }
            else:
                raise FileNotFoundError(f"Path not found: /{'/'.join(parts[:i+1])}")
        
        # Should not reach here
        raise FileNotFoundError(f"Path not found: {path}")

    # ============================================================================
    # FOLDER OPERATIONS
    # ============================================================================

    def create_folder(self, name: str, parent_uuid: str) -> None:
        """Create a single folder"""
        uuid = self.crypto.generate_uuid()
        master_key = self._get_master_key()
        
        # Encrypt name
        name_json = json.dumps({'name': name})
        name_encrypted = self.crypto.encrypt_metadata_002(name_json, master_key)
        
        # Hash name
        name_hashed = self.crypto.hash_filename(name, self.email, master_key)
        
        # Create folder
        self.api.create_folder(uuid, name_encrypted, name_hashed, parent_uuid)
        self._invalidate_cache(parent_uuid)

    def create_folder_recursive(self, path: str) -> Dict[str, Any]:
        """
        Create folders recursively (Optimized with Path Cache)
        """
        if not self.base_folder_uuid:
            raise ValueError("Not logged in")
        
        # Clean path
        path = path.strip().strip('/')
        if not path:
            return {
                'uuid': self.base_folder_uuid,
                'name': 'Root',
                'path': '/'
            }
        
        # Check Cache
        if path in self._path_cache:
            return self._path_cache[path]
        
        parts = path.split('/')
        current_uuid = self.base_folder_uuid
        current_path = '/'
        current_info = {'uuid': self.base_folder_uuid, 'name': 'Root', 'path': '/'}
        
        # We try to find the deepest cached parent to start from
        # We scan parts backwards later if needed, but linear forward is fine for now
        
        for i, part in enumerate(parts):
            if not part:
                continue
            
            part_path_str = f"{current_path}{part}/".replace('//', '/')
            clean_part_path = part_path_str.strip('/')
            
            # Check if this specific level is cached
            if clean_part_path in self._path_cache:
                cached = self._path_cache[clean_part_path]
                current_uuid = cached['uuid']
                current_info = cached
                current_path = part_path_str
                continue

            # Check if folder exists in current_uuid
            folders = self.list_folders(current_uuid)
            found = None
            
            for folder in folders:
                if folder['name'] == part:
                    found = folder
                    break
            
            if found:
                current_uuid = found['uuid']
                current_info = found
                current_info['path'] = clean_part_path
                current_path = part_path_str
                # Cache this level
                self._path_cache[clean_part_path] = current_info
            else:
                # Create folder
                self._log(f"Creating folder: {part} in {current_path}")
                
                try:
                    self.create_folder(part, current_uuid)
                except Exception as e:
                    # Handle 409 conflict
                    if '409' in str(e) or 'already exists' in str(e).lower():
                        import time
                        time.sleep(1)
                        self._invalidate_cache(current_uuid)
                    else:
                        raise
                
                import time
                time.sleep(0.5)
                self._invalidate_cache(current_uuid)
                folders = self.list_folders(current_uuid, use_cache=False)
                
                new_folder = None
                for folder in folders:
                    if folder['name'] == part:
                        new_folder = folder
                        break
                
                if not new_folder:
                    raise Exception(f"Created folder but couldn't find it: {part}")
                
                current_uuid = new_folder['uuid']
                current_info = new_folder
                current_info['path'] = clean_part_path
                current_path = part_path_str
                
                # Cache new folder
                self._path_cache[clean_part_path] = current_info
        
        return current_info

    # ============================================================================
    # FILE UPLOAD WITH CHUNKING AND RESUME
    # ============================================================================

    def upload_file_chunked(
        self,
        file_path: str,
        parent_uuid: str,
        file_uuid: Optional[str] = None,
        upload_key: Optional[str] = None,
        resume_from_chunk: int = 0,
        preserve_timestamps: bool = False,
        on_progress: Optional[Callable[[int, int, int, int], None]] = None,
        on_upload_start: Optional[Callable[[str, str], None]] = None,
        target_filename: Optional[str] = None  # for webdav override
    ) -> Dict[str, str]:
        """
        Upload file in chunks with resume support
        """
        import requests
        
        # Use target_filename if provided (WebDAV), otherwise use file system name (CLI)
        filename = target_filename if target_filename else os.path.basename(file_path)
        
        file_size = os.path.getsize(file_path)
        uuid = file_uuid or self.crypto.generate_uuid()
        master_key = self._get_master_key()
        
        # Generate file key
        file_key_str = self.crypto.random_string(32)
        file_key_bytes = file_key_str.encode('utf-8')
        
        # Get modification time
        stat = os.stat(file_path)
        last_modified = int(stat.st_mtime * 1000) if preserve_timestamps else int(datetime.now().timestamp() * 1000)
        
        # Handle empty files
        if file_size == 0:
            self._log("Uploading empty file via /v3/upload/empty")
            
            metadata_json = json.dumps({
                'name': filename, # Uses the correct name
                'size': 0,
                'mime': 'application/octet-stream',
                'key': file_key_str,
                'hash': '',
                'lastModified': last_modified
            })
            
            name_encrypted = self.crypto.encrypt_metadata_002(filename, file_key_str)
            size_encrypted = self.crypto.encrypt_metadata_002('0', file_key_str)
            mime_encrypted = self.crypto.encrypt_metadata_002('application/octet-stream', file_key_str)
            metadata_encrypted = self.crypto.encrypt_metadata_002(metadata_json, master_key)
            name_hashed = self.crypto.hash_filename(filename, self.email, master_key)
            
            self.api.upload_empty_file(
                uuid, name_encrypted, name_hashed, size_encrypted,
                parent_uuid, mime_encrypted, metadata_encrypted
            )
            
            self._invalidate_cache(parent_uuid)
            
            if on_progress:
                on_progress(1, 1, 0, 0)
            
            return {
                'uuid': uuid,
                'hash': '',
                'size': '0'
            }
        
        # Regular chunked upload
        upload_key = upload_key or self.crypto.random_string(32)
        
        # Notify on upload start
        if on_upload_start and resume_from_chunk == 0:
            on_upload_start(uuid, upload_key)
        
        chunk_size = 1048576  # 1MB
        total_chunks = (file_size + chunk_size - 1) // chunk_size
        
        if resume_from_chunk > 0:
            self._log(f"RESUMING upload from chunk {resume_from_chunk}")
            self._log(f"  UUID: {uuid}")
            self._log(f"  Upload Key: {upload_key[:8]}...")
            self._log(f"  Total chunks: {total_chunks}")
        else:
            self._log(f"STARTING new upload")
            self._log(f"  UUID: {uuid}")
            self._log(f"  Upload Key: {upload_key[:8]}...")
            self._log(f"  Total chunks: {total_chunks}")
        
        # Hash file
        hasher = hashlib.sha512()
        
        with open(file_path, 'rb') as f:
            # Re-hash previous chunks if resuming
            if resume_from_chunk > 0:
                self._log(f"Re-hashing previous {resume_from_chunk} chunks...")
                for i in range(resume_from_chunk):
                    chunk = f.read(chunk_size)
                    hasher.update(chunk)
                self._log("Re-hashing complete, resuming upload")
            
            # Upload chunks
            chunk_index = resume_from_chunk
            
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                
                # Update hash
                hasher.update(chunk)
                
                # Encrypt chunk
                encrypted_chunk = self.crypto.encrypt_data(chunk, file_key_bytes)
                
                # Calculate chunk hash
                chunk_hash = hashlib.sha512(encrypted_chunk).hexdigest().lower()
                
                # Upload chunk
                url = (f"{self.config.ingest_url}/v3/upload?"
                      f"uuid={uuid}&index={chunk_index}&parent={parent_uuid}"
                      f"&uploadKey={upload_key}&hash={chunk_hash}")
                
                headers = {'Authorization': f'Bearer {self.api.api_key}'}
                
                # Progress
                if on_progress:
                    bytes_uploaded = min((chunk_index + 1) * chunk_size, file_size)
                    on_progress(chunk_index + 1, total_chunks, bytes_uploaded, file_size)
                else:
                    progress = ((chunk_index + 1) / total_chunks * 100)
                    # print(f"     Uploading... {chunk_index + 1}/{total_chunks} chunks ({progress:.1f}%)  ", end='\r')
                
                try:
                    response = requests.post(url, data=encrypted_chunk, headers=headers, timeout=30)
                    
                    if response.status_code != 200:
                        raise Exception(f"Chunk upload failed: {response.status_code} - {response.text}")
                    
                except Exception as e:
                    self._log(f"Chunk {chunk_index} failed: {e}")
                    # Raise ChunkUploadException with resume info
                    raise ChunkUploadException(
                        f"Chunk {chunk_index} upload failed",
                        file_uuid=uuid,
                        upload_key=upload_key,
                        last_successful_chunk=chunk_index - 1,
                        original_error=e
                    )
                
                chunk_index += 1
        
        # print()  # Clear progress line
        
        # Get final hash
        total_hash = hasher.hexdigest().lower()
        
        # Finalize upload
        metadata_json = json.dumps({
            'name': filename, # Uses the correct variable
            'size': file_size,
            'mime': 'application/octet-stream',
            'key': file_key_str,
            'hash': total_hash,
            'lastModified': last_modified
        })
        
        name_encrypted = self.crypto.encrypt_metadata_002(filename, file_key_str)
        size_encrypted = self.crypto.encrypt_metadata_002(str(file_size), file_key_str)
        mime_encrypted = self.crypto.encrypt_metadata_002('application/octet-stream', file_key_str)
        metadata_encrypted = self.crypto.encrypt_metadata_002(metadata_json, master_key)
        name_hashed = self.crypto.hash_filename(filename, self.email, master_key)
        
        rm = self.crypto.random_string(32)
        
        self.api.upload_done(
            uuid, name_encrypted, name_hashed, size_encrypted,
            chunk_index, mime_encrypted, metadata_encrypted, upload_key, rm
        )
        
        self._invalidate_cache(parent_uuid)
        
        return {
            'uuid': uuid,
            'hash': total_hash,
            'size': str(file_size)
        }

    # ============================================================================
    # BATCH UPLOAD WITH RESUME
    # ============================================================================

    def should_include_file(self, filename: str, include: List[str], exclude: List[str]) -> bool:
        """Check if file should be included based on patterns"""
        import fnmatch
        
        # Check include patterns
        if include:
            matches_include = any(fnmatch.fnmatch(filename, pattern) for pattern in include)
            if not matches_include:
                return False
        
        # Check exclude patterns
        if exclude:
            matches_exclude = any(fnmatch.fnmatch(filename, pattern) for pattern in exclude)
            if matches_exclude:
                return False
        
        return True

    def upload(
        self,
        sources: List[str],
        target_path: str,
        recursive: bool = False,
        on_conflict: str = 'skip',
        preserve_timestamps: bool = False,
        include: List[str] = None,
        exclude: List[str] = None,
        batch_id: Optional[str] = None,
        initial_batch_state: Optional[Dict[str, Any]] = None,
        save_state_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> None:
        """
        Batch upload with resume support and extensive logging
        """
        include = include or []
        exclude = exclude or []
        
        self._log(f"--- STARTING UPLOAD ---")
        self._log(f"Sources: {sources}")
        self._log(f"Target: {target_path}")
        self._log(f"Options: recursive={recursive}, conflict={on_conflict}")
        
        # Load or create batch state
        if initial_batch_state:
            print("🔄 Resuming batch...")
            self._log("Loaded initial batch state")
            batch_state = initial_batch_state
            tasks = batch_state['tasks']
        else:
            print("🔍 Building task list...")
            tasks = []
            
            # Resolve target folder
            self._log(f"Resolving target folder: {target_path}")
            target_info = self.create_folder_recursive(target_path)
            target_uuid = target_info['uuid']
            self._log(f"Target UUID resolved: {target_uuid}")
            
            # Build task list
            self._log("Scanning sources for files...")
            for source in sources:
                self._log(f"expanding glob: {source}")
                expanded = glob_module.glob(source, recursive=True)
                self._log(f"Found {len(expanded)} items in source")
                
                for item_path in expanded:
                    item = Path(item_path)
                    
                    if item.is_dir():
                        if not recursive:
                            self._log(f"Skipping dir (non-recursive): {item}")
                            continue
                        
                        for root, dirs, files in os.walk(item):
                            for filename in files:
                                file_path = os.path.join(root, filename)
                                rel_path = os.path.relpath(file_path, item.parent)
                                remote_path = os.path.join(target_path, rel_path).replace('\\', '/')
                                
                                if self.should_include_file(filename, include, exclude):
                                    tasks.append({
                                        'localPath': file_path,
                                        'remotePath': remote_path,
                                        'status': 'pending',
                                        'fileUuid': None,
                                        'uploadKey': None,
                                        'lastChunk': -1
                                    })
                                else:
                                    self._log(f"Filtered out: {filename}")
                    
                    elif item.is_file():
                        remote_path = os.path.join(target_path, item.name).replace('\\', '/')
                        if self.should_include_file(item.name, include, exclude):
                            tasks.append({
                                'localPath': str(item),
                                'remotePath': remote_path,
                                'status': 'pending',
                                'fileUuid': None,
                                'uploadKey': None,
                                'lastChunk': -1
                            })
                        else:
                            self._log(f"Filtered out: {item.name}")
            
            batch_state = {
                'operationType': 'upload',
                'targetRemotePath': target_path,
                'tasks': tasks
            }
            
            if save_state_callback:
                save_state_callback(batch_state)
            
            print(f"📝 Task list: {len(tasks)} files")
            self._log(f"Task list built with {len(tasks)} items")
        
        success_count = 0
        skipped_count = 0
        error_count = 0
        completed_previously = 0
        
        completed_count = sum(1 for t in tasks if t['status'] == 'completed')
        self._log(f"Previously completed: {completed_count}")
        
        with tqdm(total=len(tasks), initial=completed_count, unit="file", desc="Uploading", disable=None) as pbar:
            for i, task in enumerate(tasks):
                local_path = task['localPath']
                remote_path = task['remotePath']
                status = task['status']
                
                remote_filename = os.path.basename(remote_path)
                pbar.set_description(f"Up: {remote_filename[:20]:<20}")

                # Debug every 10th item or if specific status
                if i % 10 == 0: self._log(f"Processing index {i}: {remote_filename}")

                if status == 'completed':
                    completed_previously += 1
                    # self._log(f"Skipping completed: {remote_filename}")
                    continue
                
                if status.startswith('skipped'):
                    skipped_count += 1
                    pbar.update(1)
                    continue
                
                if not os.path.exists(local_path):
                    if self.debug: print(f"⚠️  Source missing: {Path(local_path).name}")
                    skipped_count += 1
                    task['status'] = 'skipped_missing'
                    if save_state_callback: save_state_callback(batch_state)
                    pbar.update(1)
                    continue
                
                # Resolve parent folder
                remote_parent = os.path.dirname(remote_path).replace('\\', '/')
                try:
                    # self._log(f"Ensuring parent exists: {remote_parent}")
                    parent_info = self.create_folder_recursive(remote_parent)
                except Exception as e:
                    if self.debug: print(f"❌ Error creating parent {remote_parent}: {e}")
                    error_count += 1
                    task['status'] = 'error_parent'
                    if save_state_callback: save_state_callback(batch_state)
                    pbar.update(1)
                    continue
                
                # Check conflict
                should_upload = True
                if not task.get('fileUuid'):
                    name_hashed = self.crypto.hash_filename(remote_filename, self.email, self._get_master_key())
                    
                    # self._log(f"Checking existence: {remote_filename} in {parent_info['uuid']}")
                    existing_files = self.list_files(parent_info['uuid'], detailed=False)
                    exists = any(f['name'] == remote_filename for f in existing_files)
                    
                    if not exists:
                        # Fallback API check if cache empty
                        exists = self.api.check_file_exists(parent_info['uuid'], name_hashed)
                    
                    if exists:
                        if on_conflict == 'skip':
                            if self.debug: print(f"⏭️  Skipping: {remote_filename} (exists)")
                            skipped_count += 1
                            task['status'] = 'skipped_conflict'
                            if save_state_callback: save_state_callback(batch_state)
                            pbar.update(1)
                            should_upload = False
                
                if not should_upload:
                    continue
                
                # Upload
                try:
                    file_size = os.path.getsize(local_path)
                    is_resuming = (status in ['interrupted', 'uploading']) and task.get('lastChunk', -1) >= 0
                    
                    if self.debug:
                        if is_resuming:
                            print(f"📤 Resuming: {remote_filename} ({format_size(file_size)})")
                        else:
                            print(f"📤 Uploading: {remote_filename} ({format_size(file_size)})")
                    
                    task['status'] = 'uploading'
                    if save_state_callback: save_state_callback(batch_state)
                    
                    last_save_time = datetime.now()
                    last_saved_chunk = task.get('lastChunk', -1)
                    
                    def on_upload_start_handler(uuid: str, key: str):
                        # self._log(f"Upload initiated: {uuid}")
                        task['fileUuid'] = uuid
                        task['uploadKey'] = key
                        task['lastChunk'] = -1
                        if save_state_callback: save_state_callback(batch_state)
                    
                    def on_progress_handler(current: int, total: int, bytes_up: int, total_bytes: int):
                        nonlocal last_save_time, last_saved_chunk
                        task['lastChunk'] = current - 1
                        now = datetime.now()
                        if (current - last_saved_chunk >= 10) or (now - last_save_time).seconds >= 5:
                            if save_state_callback: save_state_callback(batch_state)
                            last_save_time = now
                            last_saved_chunk = current - 1
                    
                    self.upload_file_chunked(
                        local_path,
                        parent_info['uuid'],
                        file_uuid=task.get('fileUuid'),
                        upload_key=task.get('uploadKey'),
                        resume_from_chunk=(task.get('lastChunk', -1) + 1) if is_resuming else 0,
                        preserve_timestamps=preserve_timestamps,
                        on_upload_start=on_upload_start_handler if not is_resuming else None,
                        on_progress=on_progress_handler
                    )
                    
                    if self.debug:
                        print(f"   ✅ Complete: {remote_filename}")
                    
                    success_count += 1
                    task['status'] = 'completed'
                    task['fileUuid'] = None
                    task['uploadKey'] = None
                    task['lastChunk'] = -1
                    
                except ChunkUploadException as e:
                    if self.debug: print(f"\n⚠️  Interrupted: {e.message}")
                    task['fileUuid'] = e.file_uuid
                    task['uploadKey'] = e.upload_key
                    task['lastChunk'] = e.last_successful_chunk
                    task['status'] = 'interrupted'
                    error_count += 1
                    if save_state_callback: save_state_callback(batch_state)
                    if self.debug: print("💾 State saved")
                    
                except Exception as e:
                    if self.debug: print(f"\n❌ Error uploading {remote_filename}: {e}")
                    error_count += 1
                    task['status'] = 'error_upload'
                
                if save_state_callback: save_state_callback(batch_state)
                pbar.update(1)
        
        print("\n" + "=" * 40)
        print(f"📊 Summary: ✅ {success_count} | ⏭️ {skipped_count} | ❌ {error_count}")
        if error_count > 0:
            raise Exception(f"Upload completed with {error_count} errors")

    # ============================================================================
    # FILE DOWNLOAD
    # ============================================================================

    def download_file(self, file_uuid: str, save_path: Optional[str] = None,
                     on_progress: Optional[Callable[[int, int], None]] = None,
                     quiet: bool = False) -> Dict[str, Any]:
        """
        Download file from Filen
        """
        import requests
        
        self._log(f"Downloading file: {file_uuid}")
        
        # Get file metadata
        metadata = self.api.get_file_metadata(file_uuid)
        
        # Decrypt metadata
        encrypted_metadata = metadata.get('metadata')
        decrypted_str = self._try_decrypt(encrypted_metadata)
        meta = json.loads(decrypted_str)
        
        # Get file info
        filename = meta.get('name', 'file')
        file_size = meta.get('size', 0)
        file_key = meta.get('key', '')
        chunks = int(metadata.get('chunks', 0))
        region = metadata.get('region')
        bucket = metadata.get('bucket')
        last_modified = meta.get('lastModified')
        
        # Decode file key
        if len(file_key) == 32:
            file_key_bytes = file_key.encode('utf-8')
        else:
            import base64
            file_key_bytes = base64.b64decode(file_key)
        
        # Only print if not quiet (used by batch download to silence individual file lines)
        if not on_progress and not quiet:
            print(f"   📄 File: {filename} ({format_size(file_size)})")
        
        # Download and decrypt chunks
        target_path = save_path or filename
        
        bytes_downloaded = 0
        
        with open(target_path, 'wb') as f:
            for i in range(chunks):
                url = f"{self.config.egest_url}/{region}/{bucket}/{file_uuid}/{i}"
                
                response = requests.get(url, timeout=30)
                if response.status_code != 200:
                    raise Exception(f"Chunk download failed: {response.status_code}")
                
                # Decrypt chunk
                decrypted = self.crypto.decrypt_data(response.content, file_key_bytes)
                f.write(decrypted)
                
                bytes_downloaded += len(decrypted)
                
                if on_progress:
                    on_progress(bytes_downloaded, file_size)
        
        return {
            'filename': filename,
            'size': file_size,
            'path': target_path,
            'lastModified': last_modified
        }

    # ============================================================================
    # BATCH DOWNLOAD WITH RESUME
    # ============================================================================

    def download_path(
        self,
        remote_path: str,
        local_destination: Optional[str] = None,
        recursive: bool = False,
        on_conflict: str = 'skip',
        preserve_timestamps: bool = False,
        include: List[str] = None,
        exclude: List[str] = None,
        batch_id: Optional[str] = None,
        initial_batch_state: Optional[Dict[str, Any]] = None,
        save_state_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> None:
        """
        Batch download with resume support and FAST tree retrieval (Handles list/dict responses)
        """
        include = include or []
        exclude = exclude or []
        
        self._log(f"--- STARTING DOWNLOAD ---")
        self._log(f"Remote: {remote_path}")
        self._log(f"Recursive: {recursive}")
        
        # Resolve item
        self._log("Resolving remote path...")
        item_info = self.resolve_path(remote_path)
        self._log(f"Resolved: {item_info['type']} {item_info['uuid']}")
        
        # Handle single file (Simple non-batch logic)
        if item_info['type'] == 'file':
            filename = os.path.basename(remote_path)
            
            if not self.should_include_file(filename, include, exclude):
                print(f"🚫 Filtered out: {filename}")
                return
            
            # Determine local path
            if local_destination:
                if os.path.isdir(local_destination):
                    local_path = os.path.join(local_destination, filename)
                else:
                    local_path = local_destination
            else:
                local_path = filename
            
            # Check conflict
            if os.path.exists(local_path):
                if on_conflict == 'skip':
                    print(f"⏭️  Skipping: {local_path} (exists)")
                    return
                elif on_conflict == 'newer':
                    metadata = item_info['metadata']
                    remote_mod_time = metadata.get('lastModified', metadata.get('timestamp', 0))
                    
                    if remote_mod_time:
                        local_mod_time = int(os.path.getmtime(local_path) * 1000)
                        if remote_mod_time <= local_mod_time:
                            print(f"⏭️  Skipping: {local_path} (local is newer)")
                            return
                        print(f"📥 Downloading: {filename} (remote is newer)")
            
            print(f"📥 Downloading: {filename}")
            result = self.download_file(item_info['uuid'], save_path=local_path)
            
            if preserve_timestamps and result.get('lastModified'):
                try:
                    mod_time = result['lastModified'] / 1000.0
                    os.utime(local_path, (mod_time, mod_time))
                except Exception as e:
                    self._log(f"Could not set timestamp: {e}")
            
            print(f"✅ Downloaded: {local_path}")
            return
        
        # Handle folder (Batch Logic)
        if item_info['type'] == 'folder':
            if not recursive:
                raise Exception(f"'{remote_path}' is a folder. Use -r for recursive download.")
            
            # Determine base destination
            if local_destination:
                base_dest = local_destination
            else:
                folder_name = item_info['metadata'].get('name', 'download')
                base_dest = folder_name
            
            os.makedirs(base_dest, exist_ok=True)
            self._log(f"Local Target: {base_dest}")
            
            # Load or create batch state
            if initial_batch_state:
                print("🔄 Resuming batch...")
                batch_state = initial_batch_state
                tasks = batch_state['tasks']
            else:
                print("🔍 Building task list (Fast)...")
                tasks = []
                
                # --- OPTIMIZATION: Use flattened tree endpoint ---
                try:
                    self._log(f"Calling get_flat_folder_tree for {item_info['uuid']}...")
                    tree_data = self.api.get_flat_folder_tree(item_info['uuid'])
                    
                    raw_folders = tree_data.get('folders', [])
                    # Support both 'uploads' and 'files' keys
                    raw_files = tree_data.get('files', []) or tree_data.get('uploads', [])
                    
                    self._log(f"Tree Response: {len(raw_folders)} folders, {len(raw_files)} files")
                    
                    # 1. Map Folders
                    folder_map = {}
                    self._log("Mapping folder structure...")
                    
                    for f in raw_folders:
                        # Normalize data (Handle dict vs list)
                        if isinstance(f, list):
                            # CORRECT SCHEMA FOR FOLDERS: [uuid, encrypted_name, parent_uuid]
                            if len(f) < 3: continue
                            f_data = {
                                'uuid': f[0],
                                'name_enc': f[1],
                                'parent': f[2]
                            }
                        else:
                            if f.get('deleted') or f.get('trash'): continue
                            f_data = {
                                'uuid': f.get('uuid'),
                                'name_enc': f.get('name', ''),
                                'parent': f.get('parent')
                            }

                        try:
                            # Decrypt name
                            enc_name = f_data['name_enc']
                            dec_name = self._try_decrypt(enc_name)
                            if dec_name.startswith('{'):
                                dec_name = json.loads(dec_name).get('name', 'Unknown')
                            
                            folder_map[f_data['uuid']] = {
                                'name': dec_name,
                                'parent': f_data['parent']
                            }
                        except Exception:
                            continue

                    # Helper to trace path
                    def get_rel_path(parent_uuid):
                        path_parts = []
                        curr = parent_uuid
                        seen = set()
                        
                        while curr and curr != item_info['uuid']:
                            if curr in seen: return None # Cycle
                            seen.add(curr)
                            
                            if curr not in folder_map: 
                                return None # Orphaned or parent not in tree
                            
                            folder = folder_map[curr]
                            path_parts.append(folder['name'])
                            curr = folder['parent']
                        
                        return os.path.join(*reversed(path_parts)) if path_parts else ''

                    # 2. Process Files
                    self._log("Processing file list...")
                    for f in raw_files:
                        # Normalize data (Handle dict vs list)
                        if isinstance(f, list):
                            # CORRECT SCHEMA FOR FILES based on logs:
                            # [0:uuid, 1:bucket, 2:region, 3:chunks, 4:parent, 5:metadata_enc, ...]
                            if len(f) < 6:
                                if self.debug: self._log(f"⚠️ Skipping malformed file list item: {f}")
                                continue
                                
                            f_data = {
                                'uuid': f[0],
                                'metadata_enc': f[5], # FIXED: Index 5 is metadata
                                'parent': f[4]        # FIXED: Index 4 is parent
                            }
                        else:
                            if f.get('deleted') or f.get('trash'): continue
                            f_data = {
                                'uuid': f.get('uuid'),
                                'metadata_enc': f.get('metadata', ''),
                                'parent': f.get('parent')
                            }

                        try:
                            # Decrypt metadata
                            enc_meta = f_data['metadata_enc']
                            dec_meta = self._try_decrypt(enc_meta)
                            meta = json.loads(dec_meta)
                            
                            filename = meta.get('name', 'Unknown')
                            
                            if not self.should_include_file(filename, include, exclude):
                                continue
                                
                            rel_dir = get_rel_path(f_data['parent'])
                            
                            # Handle files directly in root vs subfolders
                            if f_data['parent'] == item_info['uuid']:
                                rel_dir = ''
                            elif rel_dir is None:
                                continue
                            
                            local_file_path = os.path.join(base_dest, rel_dir, filename)
                            os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                            
                            tasks.append({
                                'remoteUuid': f_data['uuid'],
                                'localPath': local_file_path,
                                'status': 'pending',
                                'remoteModificationTime': meta.get('lastModified', 0)
                            })
                        except Exception as e:
                            # Only log detail errors in debug mode
                            if self.debug: self._log(f"⚠️ File processing error ({f_data.get('uuid')}): {e}")
                            continue

                except Exception as e:
                    print(f"❌ Failed to fetch folder tree: {e}")
                    raise

                batch_state = {
                    'operationType': 'download',
                    'remotePath': remote_path,
                    'localDestination': base_dest,
                    'tasks': tasks
                }
                if save_state_callback: save_state_callback(batch_state)
                
                print(f"📝 Task list: {len(tasks)} files")
                self._log(f"Tasks prepared: {len(tasks)}")
            
            # Counters
            success_count = 0
            skipped_count = 0
            error_count = 0
            completed_previously = 0
            
            completed_start = sum(1 for t in tasks if t['status'] == 'completed')
            self._log(f"Starting download loop. Completed previously: {completed_start}")

            with tqdm(total=len(tasks), initial=completed_start, unit="file", desc="Downloading", disable=None) as pbar:
                for i, task in enumerate(tasks):
                    remote_uuid = task['remoteUuid']
                    local_path = task['localPath']
                    status = task['status']
                    remote_mod_time = task.get('remoteModificationTime')
                    
                    filename = os.path.basename(local_path)
                    pbar.set_description(f"Down: {filename[:20]:<20}")

                    if status == 'completed':
                        completed_previously += 1
                        continue
                    
                    if status.startswith('skipped'):
                        skipped_count += 1
                        pbar.update(1)
                        continue
                    
                    # Check Conflict
                    if os.path.exists(local_path):
                        if on_conflict == 'skip':
                            if self.debug: print(f"⏭️  Skipping: {filename} (exists)")
                            skipped_count += 1
                            task['status'] = 'skipped_conflict'
                            if save_state_callback: save_state_callback(batch_state)
                            pbar.update(1)
                            continue
                        elif on_conflict == 'newer':
                            if remote_mod_time:
                                local_mod_time = int(os.path.getmtime(local_path) * 1000)
                                if remote_mod_time <= local_mod_time:
                                    if self.debug: print(f"⏭️  Skipping: {filename} (local is newer)")
                                    skipped_count += 1
                                    task['status'] = 'skipped_newer'
                                    if save_state_callback: save_state_callback(batch_state)
                                    pbar.update(1)
                                    continue
                                if self.debug: print(f"📥 Downloading: {filename} (remote is newer)")
                    
                    # Download
                    try:
                        if self.debug and on_conflict != 'newer':
                            print(f"📥 Downloading: {filename}")
                        
                        result = self.download_file(remote_uuid, save_path=local_path, quiet=True)
                        
                        mod_time = result.get('lastModified') or remote_mod_time
                        if preserve_timestamps and mod_time:
                            try:
                                mod_time_sec = mod_time / 1000.0
                                os.utime(local_path, (mod_time_sec, mod_time_sec))
                            except Exception as e:
                                self._log(f"Could not set timestamp: {e}")
                        
                        success_count += 1
                        task['status'] = 'completed'
                        
                    except Exception as e:
                        if self.debug: print(f"❌ Download error: {e}")
                        error_count += 1
                        task['status'] = 'error_download'
                    
                    if save_state_callback:
                        save_state_callback(batch_state)
                    
                    pbar.update(1)
            
            print("\n" + "=" * 40)
            print("📊 Download Summary:")
            if completed_previously > 0:
                print(f"  ✅ Previous: {completed_previously}")
            print(f"  ✅ Downloaded: {success_count}")
            print(f"  ⏭️  Skipped: {skipped_count}")
            print(f"  ❌ Errors: {error_count}")
            print("=" * 40)
            
            if error_count > 0:
                raise Exception(f"Download completed with {error_count} errors")

    # ============================================================================
    # OTHER FILE OPERATIONS
    # ============================================================================

    def move_item(self, uuid: str, to_uuid: str, item_type: str) -> None:
        """Move file or folder"""
        if item_type == 'folder':
            self.api.move_folder(uuid, to_uuid)
        else:
            self.api.move_file(uuid, to_uuid)
        self._invalidate_cache(to_uuid)

    def copy_file(self, src_uuid: str, dest_folder_uuid: str, new_name: Optional[str] = None) -> None:
        """
        Copy file (download then re-upload)
        """
        import tempfile
        
        # Download to temp
        temp_dir = tempfile.mkdtemp(prefix='filen_cli_cp_')
        
        try:
            # Get file metadata
            file_metadata = self.api.get_file_metadata(src_uuid)
            encrypted_meta = file_metadata.get('metadata')
            decrypted = self._try_decrypt(encrypted_meta)
            meta = json.loads(decrypted)
            
            original_name = meta.get('name', 'file')
            target_name = new_name or original_name
            
            temp_file = os.path.join(temp_dir, target_name)
            
            print(f"   1/2 Downloading...  ", end='\r')
            self.download_file(src_uuid, save_path=temp_file)
            
            print(f"   2/2 Uploading...    ", end='\r')
            self.upload_file_chunked(temp_file, dest_folder_uuid)
            
            print("\n✅ Copy complete.")
            
        finally:
            # Cleanup
            if os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir)

    def rename_item(self, uuid: str, new_name: str, item_type: str, 
                   current_metadata: Optional[Dict[str, Any]] = None) -> None:
        """Rename file or folder"""
        master_key = self._get_master_key()
        name_hashed = self.crypto.hash_filename(new_name, self.email, master_key)
        
        if item_type == 'folder':
            name_json = json.dumps({'name': new_name})
            name_encrypted = self.crypto.encrypt_metadata_002(name_json, master_key)
            self.api.rename_folder(uuid, name_encrypted, name_hashed)
        else:
            # Get current metadata if not provided
            if not current_metadata:
                file_meta = self.api.get_file_metadata(uuid)
                encrypted = file_meta.get('metadata')
                decrypted = self._try_decrypt(encrypted)
                current_metadata = json.loads(decrypted)
            
            # Update metadata
            metadata = current_metadata.copy()
            metadata['name'] = new_name
            
            file_key = metadata.get('key', '')
            name_encrypted = self.crypto.encrypt_metadata_002(new_name, file_key)
            metadata_encrypted = self.crypto.encrypt_metadata_002(json.dumps(metadata), master_key)
            
            self.api.rename_file(uuid, name_encrypted, metadata_encrypted, name_hashed)

    def trash_item(self, uuid: str, item_type: str) -> None:
        """Move item to trash"""
        if item_type == 'folder':
            self.api.trash_folder(uuid)
        else:
            self.api.trash_file(uuid)

    def delete_permanent(self, uuid: str, item_type: str) -> None:
        """Permanently delete item"""
        if item_type == 'folder':
            self.api.delete_folder_permanent(uuid)
        else:
            self.api.delete_file_permanent(uuid)

    def restore_item(self, uuid: str, item_type: str) -> None:
        """Restore item from trash"""
        if item_type == 'folder':
            self.api.restore_folder(uuid)
        else:
            self.api.restore_file(uuid)

    # ============================================================================
    # TRASH OPERATIONS
    # ============================================================================

    def get_trash_content(self) -> List[Dict[str, Any]]:
        """
        Get trash contents
        """
        # Use special "trash" UUID
        content = self.api.get_dir_content('trash', folders_only=False)
        
        raw_folders = content.get('folders', [])
        raw_uploads = content.get('uploads', [])
        
        results = []
        
        # Process folders
        for f in raw_folders:
            try:
                encrypted_name = f.get('name', '')
                decrypted = self._try_decrypt(encrypted_name)
                if decrypted.startswith('{'):
                    name = json.loads(decrypted).get('name', 'Unknown')
                else:
                    name = decrypted
            except:
                name = '[Encrypted]'
            
            results.append({
                'type': 'folder',
                'name': name,
                'uuid': f.get('uuid'),
                'size': 0,
                'parent': f.get('parent'),
                'timestamp': f.get('timestamp', 0),
                'lastModified': f.get('lastModified', 0)
            })
        
        # Process files
        for f in raw_uploads:
            try:
                encrypted_metadata = f.get('metadata', '')
                decrypted = self._try_decrypt(encrypted_metadata)
                metadata = json.loads(decrypted)
                name = metadata.get('name', 'Unknown')
                size = metadata.get('size', 0)
                last_modified = metadata.get('lastModified', 0)
            except:
                name = '[Encrypted]'
                size = 0
                last_modified = 0
            
            results.append({
                'type': 'file',
                'name': name,
                'uuid': f.get('uuid'),
                'size': size,
                'parent': f.get('parent'),
                'timestamp': f.get('timestamp', 0),
                'lastModified': last_modified
            })
        
        return results

    # ============================================================================
    # SEARCH AND FIND
    # ============================================================================

    def find_files(self, start_path: str, pattern: str, max_depth: int = -1) -> List[Dict[str, Any]]:
        """
        Find files matching pattern
        """
        import fnmatch
        
        results = []
        
        # Stack for traversal: (path, depth)
        stack = [(start_path, 0)]
        
        while stack:
            current_path, current_depth = stack.pop()
            
            if max_depth != -1 and current_depth >= max_depth:
                continue
            
            try:
                resolved = self.resolve_path(current_path)
                if resolved['type'] != 'folder':
                    continue
            except Exception as e:
                self._log(f"Could not resolve: {current_path}")
                continue
            
            current_uuid = resolved['uuid']
            
            # Check files
            try:
                files = self.list_files(current_uuid)
                for file in files:
                    name = file['name']
                    
                    if fnmatch.fnmatch(name, pattern):
                        full_path = f"{current_path}/{name}".replace('//', '/')
                        results.append({
                            **file,
                            'fullPath': full_path
                        })
            except Exception as e:
                self._log(f"Could not list files in {current_path}: {e}")
            
            # Add subfolders to stack
            if max_depth == -1 or (current_depth + 1) < max_depth:
                try:
                    folders = self.list_folders(current_uuid)
                    for folder in folders:
                        folder_name = folder['name']
                        sub_path = f"{current_path}/{folder_name}".replace('//', '/')
                        stack.append((sub_path, current_depth + 1))
                except Exception as e:
                    self._log(f"Could not list folders in {current_path}: {e}")
        
        return results

    # ============================================================================
    # TREE DISPLAY
    # ============================================================================

    def print_tree(self, path: str, print_fn: Callable[[str], None], 
                   max_depth: int = 3, current_depth: int = 0, prefix: str = "") -> None:
        """
        Print folder tree
        """
        if current_depth >= max_depth:
            return
        
        try:
            resolved = self.resolve_path(path)
            if resolved['type'] != 'folder':
                print_fn(f"{prefix}└── 📄 {os.path.basename(path)}")
                return
        except Exception as e:
            print_fn(f"{prefix}└── ❌ Error: {e}")
            return
        
        try:
            uuid = resolved['uuid']
            folders = self.list_folders(uuid)
            files = self.list_files(uuid)
            all_items = folders + files
            
            if not all_items:
                return
            
            for i, item in enumerate(all_items):
                is_last = (i == len(all_items) - 1)
                
                connector = "└── " if is_last else "├── "
                child_prefix = prefix + ("    " if is_last else "│   ")
                
                name = item.get('name', 'Unknown')
                
                if item['type'] == 'folder':
                    folder_path = f"{path}/{name}".replace('//', '/')
                    print_fn(f"{prefix}{connector}📁 {name}/")
                    
                    self.print_tree(
                        folder_path,
                        print_fn,
                        max_depth=max_depth,
                        current_depth=current_depth + 1,
                        prefix=child_prefix
                    )
                else:
                    size = format_size(item.get('size', 0))
                    print_fn(f"{prefix}{connector}📄 {name} ({size})")
        
        except Exception as e:
            print_fn(f"{prefix}└── ❌ Error: {e}")

    # ============================================================================
    # VERIFY
    # ============================================================================

    def verify_upload_metadata(self, file_uuid: str, local_file: str) -> bool:
        """
        Verify uploaded file using metadata hash (no download needed)
        """
        self._log("Verifying upload using metadata check...")
        
        # Hash local file
        print("   📊 Hashing local file...")
        local_hash = self.crypto.hash_file_sha512(local_file)
        self._log(f"   Local SHA-512: {local_hash}")
        
        # Get file metadata
        print("   📋 Fetching metadata from server...")
        file_meta = self.api.get_file_metadata(file_uuid)
        
        encrypted = file_meta.get('metadata')
        decrypted = self._try_decrypt(encrypted)
        meta = json.loads(decrypted)
        
        server_hash = meta.get('hash', '')
        
        if not server_hash:
            print("   ⚠️  No hash in metadata (empty file?)")
            return os.path.getsize(local_file) == 0
        
        self._log(f"   Server SHA-512: {server_hash}")
        
        match = (local_hash == server_hash)
        
        if match:
            print("   ✅ Verification successful - hashes match!")
        else:
            print("   ❌ Verification failed - hashes differ!")
            print(f"      Local:  {local_hash}")
            print(f"      Server: {server_hash}")
        
        return match


# Global instance
drive_service = DriveService()


def format_size(size: int) -> str:
    """Format bytes to human-readable size"""
    if size <= 0:
        return '0 B'
    
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    i = 0
    size_float = float(size)
    
    while size_float >= 1024 and i < len(units) - 1:
        size_float /= 1024
        i += 1
    
    return f"{size_float:.1f} {units[i]}"


def format_date(timestamp: int) -> str:
    """Format timestamp to date string"""
    if not timestamp:
        return ''
    
    try:
        dt = datetime.fromtimestamp(timestamp / 1000.0)
        return dt.strftime('%Y-%m-%d')
    except:
        return ''

