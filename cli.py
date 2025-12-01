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
    """Main CLI application - matches Dart FilenCLI"""

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
        
        # List
        ls_parser = subparsers.add_parser('ls', help='List folder contents')
        ls_parser.add_argument('path', nargs='?', default='/', help='Folder path')
        ls_parser.add_argument('-d', '--detailed', action='store_true',
                             help='Show detailed information')
        ls_parser.add_argument('--uuids', action='store_true',
                             help='Show full UUIDs')
        
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
        
        # Download path (recursive)
        download_path_parser = subparsers.add_parser('download-path', 
                                                     help='Download by path (recursive)')
        download_path_parser.add_argument('path', help='Remote path')
        download_path_parser.add_argument('-t', '--target', help='Local destination')
        download_path_parser.add_argument('-r', '--recursive', action='store_true',
                                        help='Recursive download')
        download_path_parser.add_argument('-p', '--preserve-timestamps', action='store_true',
                                        help='Preserve modification times')
        download_path_parser.add_argument('--on-conflict', choices=['skip', 'overwrite', 'newer'],
                                        default='skip', help='Action if target exists')
        download_path_parser.add_argument('--include', action='append',
                                        help='Include file pattern')
        download_path_parser.add_argument('--exclude', action='append',
                                        help='Exclude file pattern')
        
        # Move
        move_parser = subparsers.add_parser('mv', help='Move file/folder')
        move_parser.add_argument('source', help='Source path')
        move_parser.add_argument('dest', help='Destination path')
        
        # Copy
        copy_parser = subparsers.add_parser('cp', help='Copy file')
        copy_parser.add_argument('source', help='Source path')
        copy_parser.add_argument('dest', help='Destination path')
        
        # Rename
        rename_parser = subparsers.add_parser('rename', help='Rename item')
        rename_parser.add_argument('path', help='Item path')
        rename_parser.add_argument('new_name', help='New name')
        
        # Trash
        trash_parser = subparsers.add_parser('trash', help='Move to trash')
        trash_parser.add_argument('path', help='Item path')
        
        # Delete
        delete_parser = subparsers.add_parser('delete-path', help='Permanently delete')
        delete_parser.add_argument('path', help='Item path')
        
        # Verify
        verify_parser = subparsers.add_parser('verify', help='Verify upload (SHA-512)')
        verify_parser.add_argument('remote', help='File UUID or path')
        verify_parser.add_argument('local', help='Local file path')
        
        # List trash
        list_trash_parser = subparsers.add_parser('list-trash', help='Show trash contents')
        list_trash_parser.add_argument('--uuids', action='store_true',
                                      help='Show full UUIDs')
        
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
        search_parser.add_argument('--uuids', action='store_true',
                                  help='Show full UUIDs')
        
        # Find
        find_parser = subparsers.add_parser('find', help='Recursive file find')
        find_parser.add_argument('path', help='Starting path')
        find_parser.add_argument('pattern', help='File pattern (e.g., "*.pdf")')
        find_parser.add_argument('--maxdepth', type=int, default=-1,
                               help='Limit depth (-1 for infinite)')
        
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
    # FILE OPERATION HANDLERS (Updated to use _prepare_client)
    # ============================================================================

    def handle_list(self, args) -> int:
        """Handle list command"""
        try:
            self._prepare_client()
            
            resolved = self.drive.resolve_path(args.path)
            
            if resolved['type'] == 'file':
                print(f"📄 File: {resolved['metadata']['name']} ({resolved['uuid']})")
                return 0
            
            uuid = resolved['uuid']
            show_full_uuids = args.uuids or args.detailed
            
            print(f"📂 {resolved['path']} (UUID: {uuid[:8]}...)\n")
            
            folders = self.drive.list_folders(uuid, detailed=args.detailed)
            files = self.drive.list_files(uuid, detailed=args.detailed)
            items = folders + files
            
            if not items:
                print("   (empty)")
                return 0
            
            # Build table
            name_width = 40
            size_width = 12
            date_width = 10
            uuid_width = 36 if show_full_uuids else 11
            
            if args.detailed:
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
                icon = '📁' if item['type'] == 'folder' else '📄'
                if item['type'] == 'folder':
                    folder_count += 1
                else:
                    file_count += 1
                
                name = item['name']
                if len(name) > name_width:
                    name = name[:name_width - 3] + '...'
                name = name.ljust(name_width)
                
                size = '<DIR>' if item['type'] == 'folder' else format_size(item.get('size', 0))
                size = size.rjust(size_width)
                
                item_uuid = item.get('uuid', 'N/A')
                uuid_display = (item_uuid if show_full_uuids else f"{item_uuid[:8]}...").ljust(uuid_width)
                
                if args.detailed:
                    modified = item.get('lastModified', item.get('timestamp', 0))
                    date_display = format_date(modified).rjust(date_width)
                    print(f"║  {icon}  {name}  {size}  {date_display}  {uuid_display} ║")
                else:
                    print(f"║  {icon}  {name}  {size}  {uuid_display} ║")
            
            print(footer)
            print(f"\n📊 Total: {len(items)} items ({folder_count} folders, {file_count} files)")
            
            return 0
        
        except Exception as e:
            print(f"❌ List failed: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return 1

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
        """Handle download-path command with batching and resume"""
        try:
            # Validate session for long-running operation
            self._prepare_client(validate_session=True)
            
            # Generate batch ID
            batch_id = self.config.generate_batch_id('download', [args.path], args.target or '.')
            print(f"🔄 Batch ID: {batch_id}")
            
            # Load batch state
            batch_state = self.config.load_batch_state(batch_id)
            
            # Download
            self.drive.download_path(
                args.path,
                local_destination=args.target,
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
            print("✅ Download batch completed successfully")
            
            return 0
        
        except Exception as e:
            print(f"❌ Download failed: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return 1

    def handle_move(self, args) -> int:
        """Handle move command"""
        try:
            self._prepare_client()
            
            src = self.drive.resolve_path(args.source)
            
            # Resolve or create destination
            try:
                dest = self.drive.resolve_path(args.dest)
                if dest['type'] != 'folder':
                    print(f"❌ Destination must be a folder")
                    return 1
                dest_uuid = dest['uuid']
            except FileNotFoundError:
                dest_info = self.drive.create_folder_recursive(args.dest)
                dest_uuid = dest_info['uuid']
            
            print(f"🚚 Moving \"{src['path']}\" to \"{args.dest}\"...")
            
            self.drive.move_item(src['uuid'], dest_uuid, src['type'])
            
            print("✅ Move completed successfully")
            return 0
        
        except Exception as e:
            print(f"❌ Move failed: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return 1

    def handle_copy(self, args) -> int:
        """Handle copy command"""
        try:
            self._prepare_client()
            
            src = self.drive.resolve_path(args.source)
            if src['type'] == 'folder':
                print("❌ Folder copy not yet supported")
                return 1
            
            # Resolve destination
            try:
                dest = self.drive.resolve_path(args.dest)
                if dest['type'] == 'folder':
                    dest_uuid = dest['uuid']
                    target_name = os.path.basename(args.source)
                else:
                    if not self.force:
                        print("❌ Destination exists. Use -f to overwrite.")
                        return 1
                    parent_path = os.path.dirname(args.dest)
                    dest_folder = self.drive.resolve_path(parent_path if parent_path else '/')
                    dest_uuid = dest_folder['uuid']
                    target_name = os.path.basename(args.dest)
            except FileNotFoundError:
                parent_path = os.path.dirname(args.dest)
                dest_folder = self.drive.create_folder_recursive(parent_path if parent_path else '/')
                dest_uuid = dest_folder['uuid']
                target_name = os.path.basename(args.dest)
            
            print(f"📋 Copying \"{src['path']}\"...")
            
            self.drive.copy_file(src['uuid'], dest_uuid, target_name)
            
            print("✅ Copy completed successfully")
            return 0
        
        except Exception as e:
            print(f"❌ Copy failed: {e}")
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
        """Handle trash command"""
        try:
            self._prepare_client()
            
            src = self.drive.resolve_path(args.path)
            
            if not self.force:
                prompt = f"❓ Move {src['type']} \"{args.path}\" to trash? [y/N]: "
                response = input(prompt)
                if response.lower() not in ['y', 'yes']:
                    print("❌ Cancelled")
                    return 0
            
            print(f"🗑️ Moving \"{src['path']}\" to trash...")
            
            self.drive.trash_item(src['uuid'], src['type'])
            
            print("✅ Item moved to trash successfully")
            return 0
        
        except Exception as e:
            print(f"❌ Trash failed: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return 1

    def handle_delete(self, args) -> int:
        """Handle delete-path command"""
        try:
            self._prepare_client()
            
            src = self.drive.resolve_path(args.path)
            
            print("⚠️ WARNING: This will PERMANENTLY delete the item!")
            
            if not self.force:
                prompt = f"❓ Permanently delete {src['type']} \"{args.path}\"? [y/N]: "
                response = input(prompt)
                if response.lower() not in ['y', 'yes']:
                    print("❌ Cancelled")
                    return 0
            
            print(f"🗑️ Permanently deleting \"{src['path']}\"...")
            
            self.drive.delete_permanent(src['uuid'], src['type'])
            
            print("✅ Item permanently deleted")
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

    # trash, search, find, tree, webdav handlers all follow the same pattern with _prepare_client()
    
    def handle_list_trash(self, args) -> int:
        """Handle list-trash command"""
        try:
            self._prepare_client()
            
            print("🗑️ Listing trash contents...\n")
            
            items = self.drive.get_trash_content()
            
            if not items:
                print("📭 Trash is empty")
                return 0
            
            # Build table (same as handle_list)
            name_width = 40
            size_width = 12
            uuid_width = 36 if args.uuids else 11
            
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
                icon = '📁' if item['type'] == 'folder' else '📄'
                if item['type'] == 'folder':
                    folder_count += 1
                else:
                    file_count += 1
                
                name = item['name']
                if len(name) > name_width:
                    name = name[:name_width - 3] + '...'
                name = name.ljust(name_width)
                
                size = '<DIR>' if item['type'] == 'folder' else format_size(item.get('size', 0))
                size = size.rjust(size_width)
                
                item_uuid = item.get('uuid', 'N/A')
                uuid_display = (item_uuid if args.uuids else f"{item_uuid[:8]}...").ljust(uuid_width)
                
                print(f"║  {icon}  {name}  {size}  {uuid_display} ║")
            
            print(footer)
            print(f"\n📊 Total: {len(items)} items ({folder_count} folders, {file_count} files)")
            
            return 0
        
        except Exception as e:
            print(f"❌ List trash failed: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
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
        """Handle search command (Global find)"""
        try:
            self._prepare_client()
            
            # Map search to a global recursive find
            print(f"🔍 Searching for \"*{args.query}*\"...")
            
            results = self.drive.find_files('/', f'*{args.query}*')
            
            if not results:
                print("   No matches found")
                return 0
                
            print(f"\nFound {len(results)} matches:")
            for item in results:
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