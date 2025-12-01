#!/usr/bin/env python3
"""
filen_cli/cli.py
Command-line interface for Filen CLI - UPDATED WITH BETTER AUTH
"""

import sys
import argparse
import os
from pathlib import Path
from typing import Optional

from config.config import config_service
from services.auth import auth_service
from services.drive import drive_service, format_size, format_date
from services.network_utils import network_utils
from services.webdav_server import webdav_server

class FilenCLI:
    """Main CLI application"""

    def __init__(self):
        self.config = config_service
        self.auth = auth_service
        self.drive = drive_service
        self.network = network_utils
        self.debug = False
        self.force = False

    def run(self, args: list) -> int:
        """Main entry point"""
        parser = argparse.ArgumentParser(
            description='Filen CLI - Command-line client for Filen.io',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  filen login
  filen ls /Documents -d
  filen upload file.txt -t /Docs -p
  filen download /file.txt -p
  filen tree / -l 2
  filen find / "*.pdf" --maxdepth 3
  filen search "report"
  
WebDAV Examples:
  filen webdav-start -b --port 8080
  filen webdav-status
  filen webdav-test
  filen webdav-mount
  filen webdav-stop
            """
        )
        
        # Global flags
        parser.add_argument('-v', '--verbose', action='store_true',
                          help='Enable verbose debug output')
        parser.add_argument('-f', '--force', action='store_true',
                          help='Force overwrite / ignore conflicts')
        
        # Subcommands
        subparsers = parser.add_subparsers(dest='command', help='Commands')
        
        # ========================================================================
        # Authentication Commands
        # ========================================================================
        
        subparsers.add_parser('login', help='Login to account')
        subparsers.add_parser('logout', help='Logout and clear credentials')
        subparsers.add_parser('whoami', help='Show current user')
        
        # ========================================================================
        # File Operations
        # ========================================================================
        
        # List (ls)
        ls_parser = subparsers.add_parser('ls', help='List folder contents')
        ls_parser.add_argument('path', nargs='?', default='/', help='Folder path or pattern')
        ls_parser.add_argument('-d', '--detailed', action='store_true', help='Show detailed information')
        ls_parser.add_argument('--uuids', action='store_true', help='Show full UUIDs')
        ls_parser.add_argument('--include', action='append', help='Include file pattern')
        ls_parser.add_argument('--exclude', action='append', help='Exclude file pattern')
        
        # Make directory
        mkdir_parser = subparsers.add_parser('mkdir', help='Create folder(s)')
        mkdir_parser.add_argument('path', help='Folder path to create')
        
        # Upload
        upload_parser = subparsers.add_parser('upload', help='Upload files')
        upload_parser.add_argument('sources', nargs='+', help='Source files/folders')
        upload_parser.add_argument('-t', '--target', default='/',
                                 help='Destination path')
        upload_parser.add_argument('-r', '--recursive', action='store_true',
                                 help='Recursive upload')
        upload_parser.add_argument('-p', '--preserve-timestamps', action='store_true',
                                 help='Preserve modification times')
        upload_parser.add_argument('--on-conflict', choices=['skip', 'overwrite', 'newer'],
                                 default='skip', help='Action if target exists')
        upload_parser.add_argument('--include', action='append',
                                 help='Include file pattern')
        upload_parser.add_argument('--exclude', action='append',
                                 help='Exclude file pattern')
        
        # Download
        download_parser = subparsers.add_parser('download', help='Download file')
        download_parser.add_argument('path', help='File path or UUID')
        download_parser.add_argument('-o', '--output', help='Output file path')
        download_parser.add_argument('--on-conflict', choices=['skip', 'overwrite', 'newer'],
                                   default='skip', help='Action if target exists')
        
        # Download Path - Now accepts "download-path /remote/path /local/dest"
        download_path_parser = subparsers.add_parser('download-path', help='Download by path')
        download_path_parser.add_argument('paths', nargs='+', help='Remote path(s) [and local destination]')
        download_path_parser.add_argument('-t', '--target', help='Local destination (optional override)')
        download_path_parser.add_argument('-r', '--recursive', action='store_true', help='Recursive download')
        download_path_parser.add_argument('-p', '--preserve-timestamps', action='store_true', help='Preserve timestamps')
        download_path_parser.add_argument('--on-conflict', choices=['skip', 'overwrite', 'newer'], default='skip', help='Conflict action')
        download_path_parser.add_argument('--include', action='append', help='Include pattern')
        download_path_parser.add_argument('--exclude', action='append', help='Exclude pattern')
        
        # Move (mv) - Now accepts "mv src1 src2 dest"
        move_parser = subparsers.add_parser('mv', help='Move file/folder')
        move_parser.add_argument('paths', nargs='+', help='Source path(s) and Destination')
        move_parser.add_argument('--include', action='append', help='Include file pattern')
        move_parser.add_argument('--exclude', action='append', help='Exclude file pattern')

        # Copy (cp) - Now accepts "cp src1 src2 dest"
        copy_parser = subparsers.add_parser('cp', help='Copy file')
        copy_parser.add_argument('paths', nargs='+', help='Source path(s) and Destination')
        copy_parser.add_argument('--include', action='append', help='Include file pattern')
        copy_parser.add_argument('--exclude', action='append', help='Exclude file pattern')
        
        # Rename
        rename_parser = subparsers.add_parser('rename', help='Rename item')
        rename_parser.add_argument('path', help='Item path')
        rename_parser.add_argument('new_name', help='New name')
        
        # Trash
        trash_parser = subparsers.add_parser('trash', help='Move to trash')
        trash_parser.add_argument('path', help='Item path')
        trash_parser.add_argument('--include', action='append', help='Include pattern')
        trash_parser.add_argument('--exclude', action='append', help='Exclude pattern')
        trash_parser.add_argument('-r', '--recursive', action='store_true', help='Allow deleting folders via wildcard')
        
        # Delete
        delete_parser = subparsers.add_parser('delete-path', help='Permanently delete')
        delete_parser.add_argument('path', help='Item path')
        delete_parser.add_argument('--include', action='append', help='Include pattern')
        delete_parser.add_argument('--exclude', action='append', help='Exclude pattern')
        
        # Verify
        verify_parser = subparsers.add_parser('verify', help='Verify upload (SHA-512)')
        verify_parser.add_argument('remote', help='File UUID or path')
        verify_parser.add_argument('local', help='Local file path')
        
        # List Trash
        list_trash_parser = subparsers.add_parser('list-trash', help='Show trash contents')
        list_trash_parser.add_argument('--uuids', action='store_true', help='Show full UUIDs')
        list_trash_parser.add_argument('--include', action='append', help='Include file pattern')
        list_trash_parser.add_argument('--exclude', action='append', help='Exclude file pattern')
        
        # Restore by UUID
        restore_uuid_parser = subparsers.add_parser('restore-uuid', 
                                                   help='Restore from trash by UUID')
        restore_uuid_parser.add_argument('uuid', help='Item UUID')
        
        # Restore by path
        restore_path_parser = subparsers.add_parser('restore-path',
                                                   help='Restore from trash by name')
        restore_path_parser.add_argument('name', help='Item name')
        
        # Resolve
        resolve_parser = subparsers.add_parser('resolve', help='Debug path resolution')
        resolve_parser.add_argument('path', help='Path to resolve')
        
        # Search
        search_parser = subparsers.add_parser('search', help='Server-side search')
        search_parser.add_argument('query', help='Search query')
        search_parser.add_argument('--uuids', action='store_true', help='Show full UUIDs')
        search_parser.add_argument('--include', action='append', help='Include file pattern')
        search_parser.add_argument('--exclude', action='append', help='Exclude file pattern')
        
        # Find (Update to include filters)
        find_parser = subparsers.add_parser('find', help='Recursive file find')
        find_parser.add_argument('path', help='Starting path')
        find_parser.add_argument('pattern', help='File pattern (e.g., "*.pdf")')
        find_parser.add_argument('--maxdepth', type=int, default=-1, help='Limit depth (-1 for infinite)')
        find_parser.add_argument('--include', action='append', help='Additional include pattern')
        find_parser.add_argument('--exclude', action='append', help='Exclude file pattern')
        
        # Tree
        tree_parser = subparsers.add_parser('tree', help='Show folder tree')
        tree_parser.add_argument('path', nargs='?', default='/', help='Starting path')
        tree_parser.add_argument('-l', '--depth', type=int, default=3,
                               help='Maximum depth (default: 3)')
        
        # ========================================================================
        # WebDAV Commands
        # ========================================================================
        
        # Mount (foreground)
        mount_parser = subparsers.add_parser('mount', help='Start WebDAV (foreground)')
        mount_parser.add_argument('--port', type=int, default=8080,
                                help='WebDAV port (default: 8080)')
        mount_parser.add_argument('-m', '--mount-point', help='Mount point path')
        mount_parser.add_argument('--webdav-debug', action='store_true',
                                help='Enable WebDAV debug logging')
        
        # WebDAV start
        webdav_start_parser = subparsers.add_parser('webdav-start', 
                                                    help='Start WebDAV server')
        webdav_start_parser.add_argument('-b', '--background', action='store_true',
                                        help='Run in background')
        webdav_start_parser.add_argument('--port', type=int, default=8080,
                                        help='WebDAV port (default: 8080)')
        webdav_start_parser.add_argument('--daemon', action='store_true',
                                        help=argparse.SUPPRESS)  # Hidden: internal flag
        
        # WebDAV stop
        subparsers.add_parser('webdav-stop', help='Stop background server')
        
        # WebDAV status
        webdav_status_parser = subparsers.add_parser('webdav-status', 
                                                     help='Check server status')
        webdav_status_parser.add_argument('--port', type=int, default=8080,
                                        help='WebDAV port (default: 8080)')
        
        # WebDAV test
        webdav_test_parser = subparsers.add_parser('webdav-test',
                                                   help='Test server connection')
        webdav_test_parser.add_argument('--port', type=int, default=8080,
                                       help='WebDAV port (default: 8080)')
        
        # WebDAV mount instructions
        webdav_mount_parser = subparsers.add_parser('webdav-mount',
                                                    help='Show mount instructions')
        webdav_mount_parser.add_argument('--port', type=int, default=8080,
                                        help='WebDAV port (default: 8080)')
        
        # WebDAV config
        webdav_config_parser = subparsers.add_parser('webdav-config',
                                                     help='Show server config')
        webdav_config_parser.add_argument('--port', type=int, default=8080,
                                         help='WebDAV port (default: 8080)')
        
        # ========================================================================
        # Other Commands
        # ========================================================================
        
        subparsers.add_parser('config', help='Show configuration')
        subparsers.add_parser('help', help='Show help')
        
        # Parse arguments
        parsed = parser.parse_args(args)
        
        if not parsed.command:
            parser.print_help()
            return 0
        
        # Set debug/force mode
        self.debug = parsed.verbose
        self.force = parsed.force
        self.drive.debug = self.debug
        self.auth.api.debug = self.debug
        
        # Handle commands
        try:
            # Authentication
            if parsed.command == 'login':
                return self.handle_login()
            elif parsed.command == 'logout':
                return self.handle_logout()
            elif parsed.command == 'whoami':
                return self.handle_whoami()
            
            # File operations
            elif parsed.command == 'ls':
                return self.handle_list(parsed)
            elif parsed.command == 'mkdir':
                return self.handle_mkdir(parsed)
            elif parsed.command == 'upload':
                return self.handle_upload(parsed)
            elif parsed.command == 'download':
                return self.handle_download(parsed)
            elif parsed.command == 'download-path':
                return self.handle_download_path(parsed)
            elif parsed.command == 'mv':
                return self.handle_move(parsed)
            elif parsed.command == 'cp':
                return self.handle_copy(parsed)
            elif parsed.command == 'rename':
                return self.handle_rename(parsed)
            elif parsed.command == 'trash':
                return self.handle_trash(parsed)
            elif parsed.command == 'delete-path':
                return self.handle_delete(parsed)
            elif parsed.command == 'verify':
                return self.handle_verify(parsed)
            
            # Trash operations
            elif parsed.command == 'list-trash':
                return self.handle_list_trash(parsed)
            elif parsed.command == 'restore-uuid':
                return self.handle_restore_uuid(parsed)
            elif parsed.command == 'restore-path':
                return self.handle_restore_path(parsed)
            
            # Search/find
            elif parsed.command == 'resolve':
                return self.handle_resolve(parsed)
            elif parsed.command == 'search':
                return self.handle_search(parsed)
            elif parsed.command == 'find':
                return self.handle_find(parsed)
            elif parsed.command == 'tree':
                return self.handle_tree(parsed)
            
            # WebDAV
            elif parsed.command == 'mount':
                return self.handle_mount(parsed)
            elif parsed.command == 'webdav-start':
                return self.handle_webdav_start(parsed)
            elif parsed.command == 'webdav-stop':
                return self.handle_webdav_stop(parsed)
            elif parsed.command == 'webdav-status':
                return self.handle_webdav_status(parsed)
            elif parsed.command == 'webdav-test':
                return self.handle_webdav_test(parsed)
            elif parsed.command == 'webdav-mount':
                return self.handle_webdav_mount(parsed)
            elif parsed.command == 'webdav-config':
                return self.handle_webdav_config(parsed)
            
            # Other
            elif parsed.command == 'config':
                return self.handle_config()
            elif parsed.command == 'help':
                parser.print_help()
                return 0
            
            else:
                print(f"Unknown command: {parsed.command}")
                return 1
        
        except KeyboardInterrupt:
            print("\n❌ Cancelled by user")
            return 1
        except ValueError as e:
            # Handle auth errors specially
            if 'MissingCredentialsError' in str(e):
                print(f"❌ {e}")
                print("💡 Run 'filen login' to authenticate")
                return 1
            print(f"❌ Error: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return 1
        except Exception as e:
            print(f"❌ Error: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return 1

    # ============================================================================
    # AUTHENTICATION HANDLERS
    # ============================================================================

    def handle_login(self) -> int:
        """Handle login command - IMPROVED"""
        try:
            email = input('Email: ').strip()
            if not email:
                print("❌ Email is required")
                return 1
            
            # Check if 2FA might be needed (informational only)
            self.auth.is_2fa_needed(email)
            
            import getpass
            password = getpass.getpass('Password: ')
            if not password:
                print("❌ Password is required")
                return 1
            
            print("\n🔐 Logging in...")
            
            try:
                credentials = self.auth.login(email, password)
                return 0
            
            except ValueError as e:
                error_str = str(e)
                
                # Handle 2FA requirement
                if '2FA_REQUIRED' in error_str or 'enter_2fa' in error_str.lower() or 'wrong_2fa' in error_str.lower():
                    print("\n🔐 Two-factor authentication required.")
                    tfa_code = input('Enter 2FA code: ').strip()
                    
                    if not tfa_code:
                        print("❌ 2FA code required")
                        return 1
                    
                    try:
                        print("\n🔐 Logging in with 2FA...")
                        credentials = self.auth.login(email, password, tfa_code)
                        return 0
                    
                    except Exception as e2:
                        print(f"❌ Login failed: {e2}")
                        if self.debug:
                            import traceback
                            traceback.print_exc()
                        return 1
                else:
                    # Other error
                    print(f"❌ Login failed: {e}")
                    if self.debug:
                        import traceback
                        traceback.print_exc()
                    return 1
        
        except Exception as e:
            print(f"❌ Login failed: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return 1

    def handle_logout(self) -> int:
        """Handle logout command"""
        self.auth.logout()
        print("✅ Logged out successfully")
        return 0

    def handle_whoami(self) -> int:
        """Handle whoami command - IMPROVED"""
        try:
            info = self.auth.whoami()
            
            if not info:
                print("❌ Not logged in")
                print("💡 Run 'filen login' to authenticate")
                return 1
            
            print("╔════════════════════════════════════════╗")
            print("║         User Information               ║")
            print("╚════════════════════════════════════════╝")
            print(f"📧 Email: {info['email']}")
            print(f"🆔 User ID: {info['userId']}")
            print(f"📁 Root Folder: {info['rootFolderId']}")
            
            # Show master keys count and last login
            try:
                creds = self.auth.get_credentials()
                keys = creds.get('masterKeys', '').split('|')
                print(f"🔑 Master Keys: {len([k for k in keys if k])}")
                
                last_login = creds.get('lastLoggedInAt', '')
                if last_login:
                    from datetime import datetime
                    dt = datetime.fromisoformat(last_login.replace('Z', '+00:00'))
                    print(f"🕐 Last Login: {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            except:
                pass
            
            return 0
        
        except Exception as e:
            print(f"❌ Error: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return 1

    # ============================================================================
    # HELPER METHOD - Prepare Client with Session Validation
    # ============================================================================

    def _prepare_client(self, validate_session: bool = False) -> None:
        """
        Prepare client with credentials and optionally validate session
        """
        try:
            creds = self.auth.get_credentials()
            self.drive.set_credentials(creds)
            
            # Optionally validate session for long-running operations
            if validate_session:
                if not self.auth.validate_session():
                    print("⚠️  Session validation failed. Please login again.")
                    raise ValueError("Session is no longer valid")
        
        except ValueError as e:
            if 'MissingCredentialsError' in str(e):
                raise ValueError("Not logged in. Run 'filen login' first.")
            raise

    # ============================================================================
    # WILDCARD & FILTER HELPERS
    # ============================================================================

    def _should_process_item(self, name: str, include: list, exclude: list) -> bool:
        """Filter items based on include/exclude patterns"""
        import fnmatch
        
        # If include patterns exist, file MUST match at least one
        if include:
            if not any(fnmatch.fnmatch(name, pattern) for pattern in include):
                return False
                
        # If exclude patterns exist, file MUST NOT match any
        if exclude:
            if any(fnmatch.fnmatch(name, pattern) for pattern in exclude):
                return False
                
        return True

    def _expand_remote_path(self, path_pattern: str) -> list:
        """
        Expands a remote path with wildcards into a list of actual items.
        Example: "/Code/project_*" -> returns list of matching file/folder objects
        """
        import fnmatch
        
        # If no wildcard, just resolve strictly
        if not any(char in path_pattern for char in ['*', '?', '[']):
            try:
                resolved = self.drive.resolve_path(path_pattern)
                return [{
                    'uuid': resolved['uuid'],
                    'type': resolved['type'],
                    'path': resolved['path'],
                    'name': resolved['metadata']['name']
                }]
            except FileNotFoundError:
                return []

        # Split into parent dir and pattern
        path_pattern = path_pattern.replace('\\', '/')
        parent_path = os.path.dirname(path_pattern)
        pattern = os.path.basename(path_pattern)
        
        if not parent_path:
            parent_path = '/'
            
        try:
            # Resolve parent folder
            parent_node = self.drive.resolve_path(parent_path)
            if parent_node['type'] != 'folder':
                return []
                
            parent_uuid = parent_node['uuid']
            
            # List contents to match against
            files = self.drive.list_files(parent_uuid, detailed=False)
            folders = self.drive.list_folders(parent_uuid, detailed=False)
            all_items = files + folders
            
            matches = []
            for item in all_items:
                if fnmatch.fnmatch(item['name'], pattern):
                    full_path = os.path.join(parent_path, item['name']).replace('\\', '/')
                    matches.append({
                        'uuid': item['uuid'],
                        'type': item['type'],
                        'path': full_path,
                        'name': item['name']
                    })
            
            return matches

        except Exception as e:
            if "not found" in str(e).lower():
                return []
            raise e

    # ============================================================================
    # FILE OPERATION HANDLERS (Updated to use _prepare_client)
    # ============================================================================

    def handle_list(self, args) -> int:
        """Handle list command with wildcards and filtering"""
        try:
            self._prepare_client()
            
            # 1. Expand path/pattern
            # If args.path looks like a glob (contains *?[), expand it
            # Otherwise treat as a folder list unless it's a file
            import fnmatch
            path_arg = args.path
            
            is_pattern = any(char in path_arg for char in ['*', '?', '['])
            
            # Get filters
            include = getattr(args, 'include', []) or []
            exclude = getattr(args, 'exclude', []) or []
            
            if is_pattern:
                # Case A: "ls *.txt" -> List matches
                items = self._expand_remote_path(path_arg)
                # Apply filters
                filtered = [i for i in items if self._should_process_item(i['name'], include, exclude)]
                
                if not filtered:
                    print(f"📭 No items found matching '{path_arg}'")
                    return 0
                    
                print(f"🔍 Found {len(filtered)} items matching '{path_arg}':\n")
                self._print_item_list(filtered, args.detailed, args.uuids)
                return 0
            else:
                # Case B: Standard folder list "ls /Docs"
                # Resolve strictly first
                resolved = self.drive.resolve_path(path_arg)
                
                if resolved['type'] == 'file':
                    # Check filters for single file
                    if not self._should_process_item(resolved['metadata']['name'], include, exclude):
                        print("🚫 File filtered out")
                        return 0
                    print(f"📄 File: {resolved['metadata']['name']} ({resolved['uuid']})")
                    return 0
                
                # It's a folder, list contents
                uuid = resolved['uuid']
                print(f"📂 {resolved['path']} (UUID: {uuid[:8]}...)\n")
                
                folders = self.drive.list_folders(uuid, detailed=args.detailed)
                files = self.drive.list_files(uuid, detailed=args.detailed)
                all_items = folders + files
                
                # Filter contents
                filtered = [i for i in all_items if self._should_process_item(i['name'], include, exclude)]
                
                if not filtered:
                    print("   (empty or all items filtered)")
                    return 0
                
                self._print_item_list(filtered, args.detailed, args.uuids)
                return 0

        except Exception as e:
            print(f"❌ List failed: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return 1

    def _print_item_list(self, items, detailed, show_uuids):
        """Helper to print table of items"""
        name_width = 40
        size_width = 12
        date_width = 16
        uuid_width = 36 if show_uuids else 11
        
        if detailed:
            top = f"╔{'═' * 9}{'═' * name_width}{'═' * (size_width + 2)}{'═' * (date_width + 2)}{'═' * (uuid_width + 2)}╗"
            header = f"║  Type    {'Name'.ljust(name_width)}  {'Size'.rjust(size_width)}  {'Modified'.rjust(date_width)}  {'UUID'.ljust(uuid_width)} ║"
            sep = f"╠{'═' * 9}{'═' * name_width}{'═' * (size_width + 2)}{'═' * (date_width + 2)}{'═' * (uuid_width + 2)}╣"
            footer = f"╚{'═' * 9}{'═' * name_width}{'═' * (size_width + 2)}{'═' * (date_width + 2)}{'═' * (uuid_width + 2)}╝"
        else:
            top = f"╔{'═' * 9}{'═' * name_width}{'═' * (size_width + 2)}{'═' * (uuid_width + 2)}╗"
            header = f"║  Type    {'Name'.ljust(name_width)}  {'Size'.rjust(size_width)}  {'UUID'.ljust(uuid_width)} ║"
            sep = f"╠{'═' * 9}{'═' * name_width}{'═' * (size_width + 2)}{'═' * (uuid_width + 2)}╣"
            footer = f"╚{'═' * 9}{'═' * name_width}{'═' * (size_width + 2)}{'═' * (uuid_width + 2)}╝"
        
        print(top)
        print(header)
        print(sep)
        
        folder_count = 0
        file_count = 0
        
        for item in items:
            is_folder = item.get('type') == 'folder' or item.get('itemType') == 'folder'
            icon = '📁' if is_folder else '📄'
            if is_folder: folder_count += 1
            else: file_count += 1
            
            name = item.get('name', 'Unknown')
            if len(name) > name_width:
                name = name[:name_width - 3] + '...'
            name = name.ljust(name_width)
            
            size = '<DIR>' if is_folder else format_size(item.get('size', 0))
            size = size.rjust(size_width)
            
            item_uuid = item.get('uuid', item.get('itemId', 'N/A'))
            uuid_display = (item_uuid if show_uuids else f"{item_uuid[:8]}...").ljust(uuid_width)
            
            if detailed:
                mod_raw = item.get('lastModified', item.get('timestamp', 0))
                date_display = format_date(mod_raw).rjust(date_width)
                print(f"║  {icon}  {name}  {size}  {date_display}  {uuid_display} ║")
            else:
                print(f"║  {icon}  {name}  {size}  {uuid_display} ║")
        
        print(footer)
        print(f"\n📊 Total: {len(items)} items ({folder_count} folders, {file_count} files)")


    def handle_mkdir(self, args) -> int:
        """Handle mkdir command"""
        try:
            self._prepare_client()
            
            print(f"📂 Creating \"{args.path}\"...")
            result = self.drive.create_folder_recursive(args.path)
            print("✅ Folder created successfully")
            
            return 0
        except Exception as e:
            print(f"❌ Mkdir failed: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return 1

    def handle_upload(self, args) -> int:
        """Handle upload command with batching and resume"""
        try:
            # Fix for "upload src dest" pattern (e.g. 'filen upload "*.pdf" /texte')
            # If target is default ('/') and we have multiple items in sources,
            # we check if the last item is intended as a destination.
            if args.target == '/' and len(args.sources) > 1:
                potential_dest = args.sources[-1]
                
                # Heuristic: It's a target if it starts with '/' (remote path)
                # OR if it doesn't exist locally (so it's not a source file)
                if potential_dest.startswith('/') or not os.path.exists(potential_dest):
                    args.target = potential_dest
                    args.sources = args.sources[:-1]
                    print(f"ℹ️  Inferring target: {args.target}")

            # Validate session for long-running operation
            self._prepare_client(validate_session=True)
            
            # Generate batch ID
            batch_id = self.config.generate_batch_id('upload', args.sources, args.target)
            print(f"🔄 Batch ID: {batch_id}")
            print(f"🎯 Target: {args.target}")
            
            # Load batch state
            batch_state = self.config.load_batch_state(batch_id)
            
            # Upload
            self.drive.upload(
                args.sources,
                args.target,
                recursive=args.recursive,
                on_conflict=args.on_conflict,
                preserve_timestamps=args.preserve_timestamps,
                include=args.include or [],
                exclude=args.exclude or [],
                batch_id=batch_id,
                initial_batch_state=batch_state,
                save_state_callback=lambda state: self.config.save_batch_state(batch_id, state)
            )
            
            # Clean up batch state
            self.config.delete_batch_state(batch_id)
            print("✅ Upload batch completed successfully")
            
            return 0
        
        except Exception as e:
            print(f"❌ Upload failed: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return 1

    def handle_download(self, args) -> int:
        """Handle download command"""
        try:
            self._prepare_client()
            
            # Check if UUID or path
            input_str = args.path
            is_uuid = (input_str.count('-') == 4 and len(input_str) == 36)
            
            if is_uuid:
                file_uuid = input_str
                filename = args.output or 'file'
            else:
                resolved = self.drive.resolve_path(input_str)
                if resolved['type'] != 'file':
                    print(f"❌ Not a file: {input_str}")
                    return 1
                file_uuid = resolved['uuid']
                filename = args.output or os.path.basename(input_str)
            
            # Check conflict
            if os.path.exists(filename):
                if args.on_conflict == 'skip':
                    print(f"⏭️  Skipping: {filename} (exists)")
                    return 0
                elif args.on_conflict == 'overwrite' or self.force:
                    print(f"⚠️  File exists, overwriting")
                else:
                    response = input(f"⚠️  File \"{filename}\" exists. Overwrite? [y/N]: ")
                    if response.lower() not in ['y', 'yes']:
                        print("❌ Download cancelled")
                        return 0
            
            print(f"📥 Downloading file...")
            
            result = self.drive.download_file(file_uuid, save_path=filename)
            
            print(f"✅ Downloaded: {result['filename']} ({format_size(result['size'])})")
            
            return 0
        
        except Exception as e:
            print(f"❌ Download failed: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return 1

    def handle_download_path(self, args) -> int:
        """Handle download-path with optional positional destination"""
        try:
            self._prepare_client(validate_session=True)
            
            # PARSING LOGIC:
            remote_patterns = args.paths
            local_target = args.target

            # Heuristic: If target flag NOT set, check if last arg looks like a local path
            if not local_target:
                if len(args.paths) > 1:
                    # Assume last arg is local destination
                    local_target = args.paths[-1]
                    remote_patterns = args.paths[:-1]
                else:
                    # Only one arg provided, default to current dir
                    local_target = '.'
            
            # 1. Expand Remote Sources
            items_to_process = []
            include = getattr(args, 'include', []) or []
            exclude = getattr(args, 'exclude', []) or []

            for pattern in remote_patterns:
                expanded = self._expand_remote_path(pattern)
                filtered = [i for i in expanded if self._should_process_item(i['name'], include, exclude)]
                items_to_process.extend(filtered)

            if not items_to_process:
                print(f"❌ No items found matching: {remote_patterns}")
                return 1

            # 2. Prepare Destination
            if len(items_to_process) > 1 and not os.path.isdir(local_target):
                # If downloading multiple, force target to be a directory
                os.makedirs(local_target, exist_ok=True)

            print(f"📥 Downloading {len(items_to_process)} items to '{local_target}'...")

            # 3. Execute Batch
            # Generate batch ID for resume capability
            batch_id = self.config.generate_batch_id('download', [i['path'] for i in items_to_process], local_target)
            batch_state = self.config.load_batch_state(batch_id)

            success = 0
            for item in items_to_process:
                try:
                    # Recursive download for folders
                    if item['type'] == 'folder':
                        self.drive.download_path(
                            item['path'],
                            local_destination=local_target,
                            recursive=args.recursive,
                            on_conflict=args.on_conflict,
                            preserve_timestamps=args.preserve_timestamps,
                            include=include,
                            exclude=exclude
                        )
                        success += 1
                    else:
                        # Single file download
                        # If target is dir, join path. If file, use as is (only if 1 item)
                        if os.path.isdir(local_target):
                            save_path = os.path.join(local_target, item['name'])
                        else:
                            save_path = local_target

                        self.drive.download_file(
                            item['uuid'],
                            save_path=save_path,
                            preserve_timestamps=args.preserve_timestamps
                        )
                        success += 1
                        print(f"  ✅ {item['name']}")
                
                except Exception as e:
                    print(f"  ❌ Error downloading {item['name']}: {e}")

            # Cleanup
            if success == len(items_to_process):
                self.config.delete_batch_state(batch_id)

            return 0
            
        except Exception as e:
            print(f"❌ Download failed: {e}")
            return 1

    def handle_move(self, args) -> int:
        """Handle move command with multi-source support"""
        return self._handle_transfer('move', args)

    def handle_copy(self, args) -> int:
        """Handle copy command with multi-source support"""
        return self._handle_transfer('copy', args)

    def _handle_transfer(self, mode: str, args) -> int:
        """Shared logic for mv/cp with 'last arg is destination' logic"""
        try:
            self._prepare_client()
            
            # PARSING LOGIC:
            if len(args.paths) < 2:
                print(f"❌ Error: {mode} requires at least a source and a destination.")
                return 1
            
            # Last argument is ALWAYS destination
            dest_path_raw = args.paths[-1]
            source_patterns = args.paths[:-1]
            
            # 1. Expand all Source Patterns
            all_items_to_process = []
            include = getattr(args, 'include', []) or []
            exclude = getattr(args, 'exclude', []) or []

            for pattern in source_patterns:
                expanded = self._expand_remote_path(pattern)
                # Filter
                filtered = [i for i in expanded if self._should_process_item(i['name'], include, exclude)]
                all_items_to_process.extend(filtered)
            
            if not all_items_to_process:
                print(f"❌ No items found matching sources: {source_patterns}")
                return 1
            
            # 2. Resolve Destination
            # If multiple items, destination MUST be a folder
            try:
                dest = self.drive.resolve_path(dest_path_raw)
                
                if len(all_items_to_process) > 1 and dest['type'] != 'folder':
                     print(f"❌ Destination '{dest_path_raw}' must be a folder when processing multiple items.")
                     return 1
                     
                dest_uuid = dest['uuid']
                
            except FileNotFoundError:
                # If destination doesn't exist...
                if len(all_items_to_process) > 1 or dest_path_raw.endswith('/'):
                    # We are moving multiple things, so we create the folder
                    print(f"📂 Creating destination folder '{dest_path_raw}'...")
                    dest = self.drive.create_folder_recursive(dest_path_raw)
                    dest_uuid = dest['uuid']
                else:
                    # Single item rename/move scenario
                    # We need the PARENT of the non-existent destination
                    parent_path = os.path.dirname(dest_path_raw)
                    if not parent_path: parent_path = '/'
                    
                    try:
                        parent_dest = self.drive.resolve_path(parent_path)
                        dest_uuid = parent_dest['uuid']
                        # For single file rename/move, we might handle it differently, 
                        # but standard API move is UUID->UUID. 
                        # If the user wants to RENAME, they should use 'rename' command or we implement implicit rename here.
                        # For simplicity in this logic, we assume standard folder-to-folder move.
                        if mode == 'move':
                            print(f"ℹ️  To rename a file, use the 'rename' command.")
                            print(f"❌ Destination folder '{dest_path_raw}' not found.")
                            return 1
                        else:
                            print(f"❌ Destination folder '{dest_path_raw}' not found.")
                            return 1
                    except FileNotFoundError:
                        print(f"❌ Destination path '{dest_path_raw}' invalid.")
                        return 1

            # 3. Execute
            success_count = 0
            action_name = "Moving" if mode == 'move' else "Copying"
            
            print(f"📦 {action_name} {len(all_items_to_process)} items to '{dest_path_raw}'...")
            
            for item in all_items_to_process:
                try:
                    if mode == 'move':
                        self.drive.move_item(item['uuid'], dest_uuid, item['type'])
                    else:
                        if item['type'] == 'folder':
                            print(f"⚠️  Skipping folder '{item['name']}' (Folder copy not supported)")
                            continue
                        self.drive.copy_file(item['uuid'], dest_uuid, item['name'])
                    
                    print(f"  ✅ {item['name']}")
                    success_count += 1
                except Exception as e:
                    print(f"  ❌ Error processing {item['name']}: {e}")

            print(f"✅ {action_name} completed. ({success_count}/{len(all_items_to_process)} successful)")
            return 0
            
        except Exception as e:
            print(f"❌ Operation failed: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return 1

    def handle_rename(self, args) -> int:
        """Handle rename command"""
        try:
            self._prepare_client()
            
            src = self.drive.resolve_path(args.path)
            
            print(f"✏️ Renaming \"{src['path']}\" to \"{args.new_name}\"...")
            
            self.drive.rename_item(src['uuid'], args.new_name, src['type'], src['metadata'])
            
            print("✅ Rename completed successfully")
            return 0
        
        except Exception as e:
            print(f"❌ Rename failed: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return 1

    def handle_trash(self, args) -> int:
        """Handle trash command with wildcards"""
        try:
            self._prepare_client()
            
            # 1. Expand Wildcards
            items = self._expand_remote_path(args.path)
            
            # Get filter lists (might be None in argparse)
            include = getattr(args, 'include', []) or []
            exclude = getattr(args, 'exclude', []) or []
            recursive = getattr(args, 'recursive', False)
            
            # 2. Apply Filters
            items_to_process = []
            for item in items:
                if self._should_process_item(item['name'], include, exclude):
                    items_to_process.append(item)
            
            if not items_to_process:
                print(f"❌ No items found matching '{args.path}'")
                return 1

            # 3. Confirmation
            print(f"🔍 Found {len(items_to_process)} items to trash:")
            for item in items_to_process[:10]:
                print(f"  - {item['path']} ({item['type']})")
            if len(items_to_process) > 10:
                print(f"  ... and {len(items_to_process) - 10} more.")

            if not self.force:
                response = input(f"❓ Move these {len(items_to_process)} items to trash? [y/N]: ")
                if response.lower() not in ['y', 'yes']:
                    print("❌ Cancelled")
                    return 0

            # 4. Execution
            success_count = 0
            for item in items_to_process:
                try:
                    # Safety check for folders in wildcard mode
                    if item['type'] == 'folder' and not recursive and ('*' in args.path or '?' in args.path):
                         print(f"⚠️  Skipping folder '{item['name']}' (use -r to include folders in wildcard match)")
                         continue

                    print(f"🗑️ Moving \"{item['path']}\" to trash...")
                    self.drive.trash_item(item['uuid'], item['type'])
                    success_count += 1
                except Exception as e:
                    print(f"❌ Error trashing {item['name']}: {e}")

            print(f"✅ Successfully moved {success_count} items to trash")
            return 0
        
        except Exception as e:
            print(f"❌ Trash failed: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return 1

    def handle_delete(self, args) -> int:
        """Handle delete-path command with wildcards"""
        try:
            self._prepare_client()
            
            # 1. Expand
            items = self._expand_remote_path(args.path)
            
            include = getattr(args, 'include', []) or []
            exclude = getattr(args, 'exclude', []) or []
            
            # 2. Filter
            items_to_process = []
            for item in items:
                if self._should_process_item(item['name'], include, exclude):
                    items_to_process.append(item)
            
            if not items_to_process:
                print(f"❌ No items found matching '{args.path}'")
                return 1

            # 3. Confirmation
            print("⚠️  WARNING: PERMANENT DELETION detected!")
            print(f"🔍 Found {len(items_to_process)} items to DELETE PERMANENTLY:")
            for item in items_to_process[:5]:
                print(f"  🔥 {item['path']}")
            if len(items_to_process) > 5:
                print(f"  ... {len(items_to_process) - 5} more")

            if not self.force:
                response = input("❓ Type 'DELETE' to confirm permanent deletion: ")
                if response != 'DELETE':
                    print("❌ Cancelled")
                    return 0

            # 4. Execution
            success_count = 0
            for item in items_to_process:
                try:
                    print(f"🔥 Deleting \"{item['path']}\"...")
                    self.drive.delete_permanent(item['uuid'], item['type'])
                    success_count += 1
                except Exception as e:
                    print(f"❌ Error deleting {item['name']}: {e}")

            print(f"✅ Permanently deleted {success_count} items")
            return 0
        
        except Exception as e:
            print(f"❌ Delete failed: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return 1

    def handle_verify(self, args) -> int:
        """Handle verify command"""
        try:
            self._prepare_client()
            
            # Check if UUID or path
            input_str = args.remote
            is_uuid = (input_str.count('-') == 4 and len(input_str) == 36)
            
            if is_uuid:
                file_uuid = input_str
                print("🔍 Verifying upload by UUID")
                print(f"   Remote UUID: {file_uuid}")
                print(f"   Local file: {args.local}")
                print()
            else:
                print(f"🔍 Resolving remote path: {input_str}")
                resolved = self.drive.resolve_path(input_str)
                
                if resolved['type'] != 'file':
                    print(f"❌ Error: \"{input_str}\" is not a file")
                    return 1
                
                file_uuid = resolved['uuid']
                print(f"   ✅ Resolved to UUID: {file_uuid}")
                print(f"   Local file: {args.local}")
                print()
            
            match = self.drive.verify_upload_metadata(file_uuid, args.local)
            
            return 0 if match else 1
        
        except Exception as e:
            print(f"❌ Verification failed: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return 1

    def handle_list_trash(self, args) -> int:
        """Handle list-trash command with filtering"""
        try:
            self._prepare_client()
            
            print("🗑️ Listing trash contents...\n")
            items = self.drive.get_trash_content()
            
            # Apply Filters
            include = getattr(args, 'include', []) or []
            exclude = getattr(args, 'exclude', []) or []
            filtered = [i for i in items if self._should_process_item(i['name'], include, exclude)]
            
            if not filtered:
                print("📭 Trash is empty (or all items filtered)")
                return 0
            
            self._print_item_list(filtered, detailed=True, show_uuids=args.uuids)
            return 0
            
        except Exception as e:
            print(f"❌ List trash failed: {e}")
            return 1

    def handle_tree(self, args) -> int:
        """Handle tree command"""
        try:
            self._prepare_client()
            
            print(f"\n🌳 Folder tree: {args.path}")
            print("=" * 60)
            print(args.path if args.path == '/' else f"📁 {os.path.basename(args.path)}")
            
            self.drive.print_tree(
                args.path,
                lambda line: print(line),
                max_depth=args.depth
            )
            
            print(f"\n(Showing max {args.depth} levels deep)")
            
            return 0
        
        except Exception as e:
            print(f"❌ Tree failed: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return 1

    # ============================================================================
    # WEBDAV HANDLERS
    # ============================================================================

    def handle_mount(self, args) -> int:
        """Handle mount command (foreground WebDAV server)"""
        try:
            self._prepare_client()
            print(f"🏔️ Mounting Filen Drive via WebDAV on port {args.port}...")
            print("   Press Ctrl+C to stop")
            
            # This will block until stopped
            result = webdav_server.start(port=args.port, background=False)
            
            if not result['success']:
                print(f"❌ Failed to start server: {result.get('message')}")
                return 1
            return 0
            
        except KeyboardInterrupt:
            print("\n🛑 Stopping...")
            return 0
        except Exception as e:
            print(f"❌ Error: {e}")
            return 1

    def handle_webdav_start(self, args) -> int:
        """Handle webdav-start command"""
        is_daemon = args.daemon
        background = args.background
        port = args.port
        
        # --- DAEMON PROCESS (Child) ---
        if is_daemon:
            try:
                # 1. Initialize credentials in this detached process
                self._prepare_client()
                
                # 2. Start the server (blocks here)
                # We use background=True mode in webdav_server which uses quiet logging
                webdav_server.start(port=port, background=True)
                return 0
            except Exception:
                return 1

        # --- PARENT PROCESS (CLI) ---
        
        # Check for existing instance
        existing_pid = self.config.read_webdav_pid()
        if existing_pid:
            is_running = self.network.is_process_running(existing_pid)
            if is_running:
                print(f"❌ WebDAV server is already running (PID: {existing_pid}).")
                print("💡 Run \"filen webdav-stop\" to stop it first.")
                return 1
            else:
                # Stale PID file
                self.config.clear_webdav_pid()
        
        if background:
            print("🚀 Starting WebDAV server in background...")
            
            try:
                # Start daemon process
                import subprocess
                
                # Launch self with --daemon flag
                process = subprocess.Popen(
                    [sys.executable, __file__, 'webdav-start', '--daemon', f'--port={port}'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                
                # Give it time to start
                import time
                time.sleep(1)
                
                # Verify running
                if not self.network.is_process_running(process.pid):
                    print("❌ Failed to start background process")
                    self.config.clear_webdav_pid()
                    return 1
                
                self.config.save_webdav_pid(process.pid)
                
                print(f"✅ WebDAV server started in background (PID: {process.pid})")
                print(f"   URL: http://localhost:{port}/")
                print("   User: filen")
                print("   Pass: filen-webdav")
                print("\n💡 Use \"filen webdav-test\" to verify connection")
                print("💡 Use \"filen webdav-stop\" to stop")
                
                return 0
            
            except Exception as e:
                print(f"❌ Failed to start background process: {e}")
                self.config.clear_webdav_pid()
                return 1
        
        # If not background and not daemon, run in foreground (same as mount)
        return self.handle_mount(args)

    def handle_webdav_stop(self, args) -> int:
        """Handle webdav-stop command"""
        print("🛑 Stopping WebDAV server...")
        
        # 1. Try PID file
        pid = self.config.read_webdav_pid()
        killed_via_pid = False
        
        if pid:
            if self.network.is_process_running(pid):
                if self.network.kill_process(pid):
                    print(f"✅ Server process (PID: {pid}) terminated.")
                    killed_via_pid = True
            self.config.clear_webdav_pid()
            
        # 2. Force cleanup by port (catch zombies)
        # We need the port. If not passed in args, check config or default
        # NOTE: args for webdav-stop usually doesn't have --port in your current argparse setup
        # unless you add it. Let's assume default 8080 or read from config.
        
        # Read saved config to find the port
        dav_config = self.config.read_webdav_config()
        port = dav_config.get('port', 8080)
        
        if self.network.kill_process_by_port(port):
            print(f"🧹 Cleaned up zombie process on port {port}.")
        elif not killed_via_pid:
             print("❌ Server does not appear to be running (no PID file or process on port).")

        return 0

    def handle_webdav_status(self, args) -> int:
        """Handle webdav-status command"""
        pid = self.config.read_webdav_pid()
        port = args.port
        
        if not pid:
            print("❌ WebDAV server is not running (no PID file).")
            print("💡 Start with: filen webdav-start --background")
            return 1
        
        # Check if running
        if not self.network.is_process_running(pid):
            print("❌ WebDAV server PID file exists but process is not running.")
            print(f"   Stale PID: {pid}")
            print("💡 Run \"filen webdav-stop\" to clean up.")
            return 1
        
        print("✅ WebDAV server is running in background.")
        print(f"   PID: {pid}")
        print(f"   URL: http://localhost:{port}/")
        print("   User: filen")
        print("   Pass: filen-webdav")
        print("\n💡 Use \"filen webdav-test\" to verify connection.")
        print("💡 Use \"filen webdav-stop\" to stop it.")
        
        return 0

    def handle_webdav_test(self, args) -> int:
        """Handle webdav-test command"""
        port = args.port
        url = f"http://localhost:{port}/"
        
        print(f"🧪 Testing WebDAV server connection at {url} ...")
        
        result = self.network.test_webdav_connection(url, 'filen', 'filen-webdav')
        
        if result['success']:
            print(f"✅ {result['message']}")
            print("   Server is running and authentication is working.")
        else:
            print(f"❌ {result['message']}")
        
        return 0 if result['success'] else 1

    def handle_webdav_mount(self, args) -> int:
        """Handle webdav-mount command"""
        port = args.port
        url = f"http://localhost:{port}/"
        
        print("🗂️  Mount Instructions for Filen Drive")
        print("=" * 50)
        print(f"Server URL: {url}")
        print("Username:   filen")
        print("Password:   filen-webdav")
        
        print("\n--- macOS ---")
        print("1. Open Finder")
        print("2. Press Cmd+K (Go > Connect to Server)")
        print(f"3. Enter: {url}")
        print("4. Connect, then enter username and password.")
        
        print("\n--- Windows ---")
        print("1. Open File Explorer")
        print("2. Right-click \"This PC\" > \"Map network drive...\"")
        print(f"3. Enter: {url}")
        print("4. Check \"Connect using different credentials\"")
        print("5. Connect, then enter username and password.")
        
        print("\n--- Linux (davfs2) ---")
        print("sudo apt install davfs2")
        print("sudo mkdir -p /mnt/filen")
        print(f"sudo mount -t davfs {url} /mnt/filen")
        print("(You will be prompted for username and password)")
        
        return 0

    def handle_webdav_config(self, args) -> int:
        """Handle webdav-config command"""
        port = args.port
        
        print("⚙️  WebDAV Server Configuration")
        print("=" * 40)
        print("   Host: localhost")
        print(f"   Port: {port}")
        print("   User: filen")
        print("   Pass: filen-webdav")
        print("   Protocol: http (SSL not implemented in this version)")
        print(f"   Background PID File: {self.config.webdav_pid_file}")
        
        return 0
    
    def handle_config(self) -> int:
        """Handle config command"""
        print("╔════════════════════════════════════════╗")
        print("║         Configuration                  ║")
        print("╚════════════════════════════════════════╝")
        print(f"📁 Config dir: {self.config.filen_cli_data_dir}")
        print(f"🔐 Credentials: {self.config.credentials_file}")
        print(f"🔄 Batch states: {self.config.batch_state_dir}")
        print("")
        print("🌐 API Endpoints:")
        print(f"   Gateway: {self.config.api_url}")
        print(f"   Ingest: {self.config.ingest_url}")
        print(f"   Egest: {self.config.egest_url}")
        
        # Show session info if logged in
        try:
            creds = self.auth.get_credentials()
            print("")
            print("👤 Current Session:")
            print(f"   User: {creds.get('email', 'N/A')}")
            
            last_login = creds.get('lastLoggedInAt', '')
            if last_login:
                from datetime import datetime
                dt = datetime.fromisoformat(last_login.replace('Z', '+00:00'))
                print(f"   Last Login: {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        except:
            print("")
            print("👤 Current Session: Not logged in")
        
        return 0

    def handle_restore_uuid(self, args) -> int:
        """Restore item from trash by UUID"""
        try:
            self._prepare_client()
            
            # We need to know if it's a file or folder to call the right API
            print("🔍 Searching trash...")
            trash = self.drive.get_trash_content()
            
            item = next((i for i in trash if i['uuid'] == args.uuid), None)
            
            if not item:
                print(f"❌ Item {args.uuid} not found in trash")
                return 1
                
            print(f"♻️  Restoring {item['type']} \"{item['name']}\"...")
            self.drive.restore_item(item['uuid'], item['type'])
            print("✅ Restore successful")
            return 0
            
        except Exception as e:
            print(f"❌ Restore failed: {e}")
            return 1

    def handle_restore_path(self, args) -> int:
        """Restore item from trash by Name"""
        try:
            self._prepare_client()
            
            print("🔍 Searching trash...")
            trash = self.drive.get_trash_content()
            
            # Find items matching the name
            matches = [i for i in trash if i['name'] == args.name]
            
            if not matches:
                print(f"❌ No item named \"{args.name}\" found in trash")
                return 1
            
            if len(matches) > 1:
                print(f"⚠️  Multiple items found named \"{args.name}\":")
                for i in matches:
                    print(f"   - {i['type'].ljust(6)} {i['uuid']} (Size: {format_size(i.get('size', 0))})")
                print("💡 Use 'restore-uuid' with the specific UUID")
                return 1
            
            item = matches[0]
            print(f"♻️  Restoring {item['type']} \"{item['name']}\"...")
            self.drive.restore_item(item['uuid'], item['type'])
            print("✅ Restore successful")
            return 0
            
        except Exception as e:
            print(f"❌ Restore failed: {e}")
            return 1

    def handle_resolve(self, args) -> int:
        """Debug command to resolve a path"""
        try:
            self._prepare_client()
            print(f"🔍 Resolving: {args.path}")
            
            result = self.drive.resolve_path(args.path)
            
            print("\n✅ Found:")
            print(f"   Name: {result['metadata'].get('name')}")
            print(f"   Type: {result['type']}")
            print(f"   UUID: {result['uuid']}")
            if 'parent' in result:
                print(f"   Parent: {result['parent']}")
            return 0
            
        except FileNotFoundError:
            print("❌ Path not found")
            return 1
        except Exception as e:
            print(f"❌ Error: {e}")
            return 1

    def handle_find(self, args) -> int:
        """Handle find command"""
        try:
            self._prepare_client()
            
            print(f"🔍 Finding \"{args.pattern}\" in \"{args.path}\"...")
            
            results = self.drive.find_files(
                args.path, 
                args.pattern, 
                max_depth=args.maxdepth
            )
            
            if not results:
                print("   No matches found")
                return 0
                
            print(f"\nFound {len(results)} matches:")
            for item in results:
                print(f"   {item['fullPath']}")
                
            return 0
            
        except Exception as e:
            print(f"❌ Find failed: {e}")
            return 1

    def handle_search(self, args) -> int:
        """Handle search command with filtering"""
        try:
            self._prepare_client()
            
            print(f"🔍 Searching for \"{args.query}\"...")
            
            # This is server-side fuzzy search
            results = self.drive.find_files('/', f'*{args.query}*')
            
            # Apply Client-side Filters
            include = getattr(args, 'include', []) or []
            exclude = getattr(args, 'exclude', []) or []
            
            filtered = []
            for item in results:
                # find_files returns objects with 'name', 'path', etc.
                if self._should_process_item(item['name'], include, exclude):
                    filtered.append(item)

            if not filtered:
                print("   No matches found")
                return 0
                
            print(f"\nFound {len(filtered)} matches:")
            for item in filtered:
                uuid_str = f" ({item['uuid']})" if args.uuids else ""
                print(f"   {item['fullPath']}{uuid_str}")
                
            return 0
            
        except Exception as e:
            print(f"❌ Search failed: {e}")
            return 1
        
def main():
    """Main entry point"""
    cli = FilenCLI()
    sys.exit(cli.run(sys.argv[1:]))


if __name__ == '__main__':
    main()