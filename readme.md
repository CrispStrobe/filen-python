# Filen Python CLI

A (work in progress and unofficial) Python implementation of a Filen Command Line Interface for encrypted cloud storage with **path-based operations**, **batching with resume support**, and **comprehensive file management**.

## ⚠️ Disclaimer

This is an unofficial, open-source project and is **not** affiliated with, endorsed by, or supported by Filen. It is a personal project built for learning and to provide an alternative interface. Use it at your own risk.

## ✨ Features

### 🔄 **Batching & Resume Support**

  - ✅ **Chunk-level resume**: Interrupted uploads/downloads resume from the exact chunk where they stopped (tracked as a completed-index set, so out-of-order completion is safe).
  - ✅ **Bounded chunk concurrency**: Uploads and downloads transfer multiple 1 MB chunks in parallel via a `ThreadPoolExecutor` + in-flight semaphore (`max_concurrent_chunks`, default 4). In-order hashing is preserved; tiny files stay sequential.
  - ✅ **Batch state persistence**: All progress saved automatically, survive crashes and network failures.
  - ✅ **Pattern filtering**: Include/exclude files with glob patterns during batch operations.
  - ✅ **Conflict handling**: Smart conflict resolution (skip/overwrite/newer) for uploads and downloads.
  - ✅ **Progress tracking**: Real-time progress for individual files and entire batches.

### 🛣️ **Path-Based Operations**

  - ✅ **Human-readable paths**: Use `/Documents/report.pdf` instead of UUIDs.
  - ✅ **Client-side search**: Find files recursively with wildcard patterns like `*.pdf`.
  - ✅ **Tree visualization**: See your folder structure at a glance.
  - ✅ **Path navigation**: Browse folders like your local filesystem.
  - ✅ **Path resolution**: Automatic path-to-UUID conversion with caching.

### 🔐 **Core Functionality**

  - ✅ **Timestamp Preservation**: Preserves original file modification dates on upload and download.
  - ✅ **Secure authentication**: Login/logout with 2FA support.
  - ✅ **File verification**: SHA-512 hash verification without re-downloading files.
  - ✅ **Trash operations**: Move to trash, restore, and permanent deletion.
  - ✅ **Folder management**: Create folders recursively, move, rename, copy.
  - ✅ **Zero-knowledge encryption**: AES-256-GCM client-side encryption with metadata protection.

### 🌐 **WebDAV Server Control** (Commands Only)

  - ✅ **Start/Stop control**: Manage background WebDAV server instances.
  - ✅ **Status checking**: Monitor server health and availability.
  - ✅ **Mount instructions**: Platform-specific mounting guides.
  - ✅ **SSL certificate management**: Auto-generate and validate self-signed certificates.
  - ⚠️ **Note**: Full WebDAV server implementation requires additional dependencies (not included).

## 🚀 Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Login to your account
python filen.py login

# Use path-based commands
python filen.py ls /Documents -d
python filen.py upload -r -p ./my-docs /Backups
python filen.py download-path -r /Photos ./local-photos -p
python filen.py find / "*.pdf" --maxdepth 3
python filen.py tree /Projects -l 2
```

## 📖 Usage Guide

### 🔐 Authentication

```bash
# Login with interactive prompts
python filen.py login

# Check current user
python filen.py whoami

# Logout and clear credentials
python filen.py logout
```

The CLI will automatically detect if 2FA is required and prompt for the code.

### 🛣️ Path-Based Operations

#### List & Navigate

```bash
# List root folder with readable paths
python filen.py ls /

# List specific folders
python filen.py ls /Documents
python filen.py ls /Photos/2023/Summer

# Show detailed information (size, date, UUID)
python filen.py ls /Documents -d --uuids

# Show folder structure as tree
python filen.py tree /
python filen.py tree /Projects -l 2  # Limit depth to 2 levels
```

#### Search & Find

```bash
# Client-side recursive search with wildcards
python filen.py find / "*.pdf"                    # All PDF files
python filen.py find /Documents "report*"         # Files starting with "report"
python filen.py find /Photos "*.jpg" --maxdepth 2 # JPGs, max 2 levels deep

# Simple search (uses find with wildcards)
python filen.py search "*.pdf"

# Debug path resolution
python filen.py resolve "/Documents/report.pdf"
```

### ⬆️ Upload with Batching & Resume

```bash
# Upload a single file, preserving timestamp
python filen.py upload ./report.pdf -t /Documents -p

# Upload folder recursively with timestamps
python filen.py upload -r -p ./my-project -t /Backups

# Upload with pattern filtering
python filen.py upload -r ./photos -t /Photos --include "*.jpg" --include "*.png"

# Upload with conflict handling
python filen.py upload ./file.pdf -t /Docs --on-conflict overwrite
python filen.py upload -r ./folder -t /Backup --on-conflict newer  # Only if local is newer

# Resume interrupted upload (automatic)
# If upload is interrupted, just run the same command again:
python filen.py upload -r ./large-folder -t /Backups -p
# ↑ Will automatically resume from last completed chunk
```

**Batch Features:**
- Each batch gets a unique ID (shown at start)
- State saved after every chunk (throttled to avoid excessive I/O)
- Re-running the same command automatically resumes
- State cleaned up on successful completion

### ⬇️ Download with Batching & Resume

```bash
# Download single file by path
python filen.py download /Documents/report.pdf

# Download single file by UUID
python filen.py download a1b2c3d4-e5f6-7890-abcd-ef1234567890

# Download with custom output name
python filen.py download /file.pdf -o ./local-file.pdf

# Download folder recursively
python filen.py download-path -r /Photos -t ./local-photos -p

# Download with pattern filtering
python filen.py download-path -r /Music -t ./my-music --include "*.mp3" --exclude "demo_*"

# Download with conflict handling
python filen.py download-path /folder -t ./local --on-conflict newer

# Resume interrupted download (automatic)
python filen.py download-path -r /LargeFolder -t ./local -p
# ↑ Will automatically resume from where it stopped
```

### 🔍 Verification

```bash
# Verify upload without re-downloading (compares SHA-512 hashes)
python filen.py verify /Documents/report.pdf ./local-report.pdf
python filen.py verify a1b2c3d4-uuid ./local-file.pdf

# Returns exit code 0 if hashes match, 1 if they don't
```

### 📁 Folder Operations

```bash
# Create folders (recursive)
python filen.py mkdir /Projects/NewProject/src

# Move items
python filen.py mv /Documents/old.pdf /Archive

# Copy files (download + re-upload)
python filen.py cp /file.pdf /Backup/file-copy.pdf

# Rename items
python filen.py rename /Documents/old-name.pdf new-name.pdf
```

### 🗑️ Trash & Delete Operations

```bash
# Move to trash (recoverable)
python filen.py trash /OldFolder
python filen.py trash /Documents/outdated.pdf  # With confirmation prompt
python filen.py trash /file.pdf -f              # Skip confirmation

# List trash contents
python filen.py list-trash
python filen.py list-trash --uuids  # Show full UUIDs

# Restore from trash
python filen.py restore-uuid a1b2c3d4-uuid     # By UUID
python filen.py restore-path "filename.pdf"    # By name (errors if multiple matches)

# Permanent delete (⚠️ cannot be undone)
python filen.py delete-path /TempFile.txt      # With warning and confirmation
python filen.py delete-path /folder -f         # Skip confirmation
```

### 🌐 WebDAV Server Control

**Note:** These commands control WebDAV server instances. Full server implementation requires additional dependencies (like wsgidav).

```bash
# Start WebDAV server
python filen.py webdav-start              # Foreground mode
python filen.py webdav-start -b           # Background mode
python filen.py webdav-start --port 8080  # Custom port

# Check server status
python filen.py webdav-status
python filen.py webdav-status --port 8080

# Test server connection
python filen.py webdav-test
python filen.py webdav-test --port 8080

# Show mount instructions for your OS
python filen.py webdav-mount
python filen.py webdav-mount --port 8080

# Show server configuration
python filen.py webdav-config

# Stop server
python filen.py webdav-stop
```

**Default WebDAV credentials:**
- URL: `http://localhost:8080`
- Username: `filen`
- Password: `filen-webdav`

### 🔧 Utility Commands

```bash
# Show configuration and paths
python filen.py config

# Get help
python filen.py --help
python filen.py <command> --help

# Enable verbose debug output
python filen.py -v upload ./file.pdf -t /Documents

# Force operations (skip confirmations)
python filen.py -f trash /folder
```

## 📦 Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/filen-python-cli.git
cd filen-python-cli

# Install dependencies
pip install -r requirements.txt

# Create directory structure
mkdir -p filen_cli/config filen_cli/services

# Copy all files to appropriate locations:
# - filen.py (entry point)
# - filen_cli/cli.py
# - filen_cli/config/config.py
# - filen_cli/services/auth.py
# - filen_cli/services/api.py
# - filen_cli/services/crypto.py
# - filen_cli/services/drive.py
# - filen_cli/services/network_utils.py

# Start using immediately
python filen.py login
python filen.py ls /
```

### Requirements

  - **Python 3.8+**
  - **Dependencies**: 
    - `cryptography` - AES-256-GCM encryption
    - `requests` - HTTP API client

### requirements.txt

```txt
requests>=2.28.0
cryptography>=41.0.0
```

## 🔒 Security & Privacy

This CLI implements **the same security model** as official Filen clients:

  - **Client-side encryption**: All files encrypted on your device before upload (AES-256-GCM).
  - **Zero-knowledge**: Filen servers never see your unencrypted data or keys.
  - **Metadata protection**: File names and metadata encrypted with version "002" format.
  - **PBKDF2 key derivation**: 200,000 iterations for password-based key derivation.
  - **Per-chunk encryption**: Each 1MB chunk encrypted separately with unique IV.
  - **SHA-512 hashing**: File integrity verification with SHA-512 hashes.
  - **Secure credentials**: Stored locally in `~/.filen-cli/credentials.json`.

### Encryption Details

- **File encryption**: AES-256-GCM, 1MB chunks, 12-byte IV prepended to each chunk
- **Metadata encryption**: AES-256-GCM with "002" version prefix, 12-byte IV
- **Filename hashing**: HMAC-SHA-256 using master key + email
- **File hashing**: SHA-512 computed in 1MB chunks
- **Key derivation**: PBKDF2-HMAC-SHA512, 200,000 iterations, 64-byte output

## 🏗️ Development

### Project Structure

```
filen-python-cli/
├── filen.py                      # Entry point
├── filen_cli/
│   ├── cli.py                    # Main CLI interface
│   ├── config/
│   │   └── config.py             # Configuration & state management
│   └── services/
│       ├── auth.py               # Authentication & session management
│       ├── api.py                # HTTP API client with retry logic
│       ├── crypto.py             # Encryption/decryption/hashing
│       ├── drive.py              # File operations, batching, caching
│       └── network_utils.py      # WebDAV utilities & SSL management
└── requirements.txt
```

### Key Components

**config.py**
- Directory structure: `~/.filen-cli/`
- Credentials storage (unencrypted JSON)
- Batch state persistence (individual JSON files per batch)
- WebDAV configuration and PID management
- Batch ID generation (SHA1-based)

**crypto.py**
- PBKDF2 key derivation (200k iterations)
- AES-256-GCM encryption/decryption
- Metadata encryption with "002" prefix
- Filename hashing with HMAC-SHA256
- File hashing with SHA-512

**api.py**
- Automatic retry with exponential backoff
- All Filen API endpoints (v3)
- Upload/download chunk handling
- Error handling and status checks

**drive.py** (largest module, ~1000 lines)
- Path resolution with caching (10-minute TTL)
- Chunked upload/download (1MB chunks)
- Batch operations with resume support
- File/folder operations (create, move, rename, copy, delete)
- Trash operations (trash, restore, list, permanent delete)
- Search and find functionality
- Tree visualization
- SHA-512 verification

**auth.py**
- Login flow with 2FA support
- Master key decryption
- Session validation
- Credential management

**network_utils.py**
- WebDAV server status checking
- SSL certificate generation and validation
- Process management (start/stop servers)
- Connection testing

### Development Setup

```bash
# Clone and setup development environment
git clone https://github.com/yourusername/filen-python-cli.git
cd filen-python-cli

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# or
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Run tests (if implemented)
python -m pytest tests/

# Try it out
python filen.py login
python filen.py ls /
```

## 🎯 Batch Operations Deep Dive

### How Batching Works

1. **Batch ID Generation**: SHA1 hash of operation type + sources + target (first 16 chars)
2. **State Structure**: JSON file per batch with tasks array
3. **Task States**: `pending`, `uploading`, `interrupted`, `completed`, `skipped_*`, `error_*`
4. **Resume Detection**: Checks for `interrupted` or `uploading` status with `lastChunk >= 0`
5. **State Persistence**: Saved after each chunk (throttled: every 10 chunks or 5 seconds)
6. **Cleanup**: State deleted on successful completion

### Batch State Example

```json
{
  "batchId": "a1b2c3d4e5f67890",
  "operation": "upload",
  "source": ["./folder"],
  "target": "/Backups",
  "createdAt": "2024-12-01T12:00:00Z",
  "updatedAt": "2024-12-01T12:05:30Z",
  "tasks": [
    {
      "localPath": "./folder/file1.pdf",
      "remotePath": "/Backups/file1.pdf",
      "status": "completed",
      "fileUuid": "uuid-here",
      "uploadKey": "key-here",
      "lastChunk": 10
    },
    {
      "localPath": "./folder/file2.pdf",
      "remotePath": "/Backups/file2.pdf",
      "status": "interrupted",
      "fileUuid": "uuid-here",
      "uploadKey": "key-here",
      "lastChunk": 5
    }
  ]
}
```

### Resume Example

```bash
# Start upload
python filen.py upload -r ./large-folder -t /Backups -p
# Batch ID: abc123def4567890
# Uploading file1.pdf... 50% (5/10 chunks)
# [Connection lost or Ctrl+C]

# Resume upload (same command)
python filen.py upload -r ./large-folder -t /Backups -p
# Batch ID: abc123def4567890 (same ID)
# ✅ Resuming from previous batch
# Uploading file1.pdf... Resuming from chunk 6/10
# ✅ file1.pdf completed
# Uploading file2.pdf...
```

## 📝 Examples

### Common Workflows

**Backup local folder to Filen:**
```bash
python filen.py upload -r -p ~/Documents /Backups/Documents-$(date +%Y%m%d)
```

**Download entire project folder:**
```bash
python filen.py download-path -r /Projects/MyApp -t ~/code/MyApp -p
```

**Sync photos (only newer files):**
```bash
python filen.py upload -r -p ~/Photos /Photos --on-conflict newer
```

**Find all PDFs and verify one:**
```bash
python filen.py find / "*.pdf"
python filen.py verify /Documents/important.pdf ~/local-copy.pdf
```

**Clean up trash:**
```bash
python filen.py list-trash
python filen.py restore-path "important-file.pdf"
python filen.py delete-path /trash/old-stuff -f  # Permanent delete
```

**Browse and explore:**
```bash
python filen.py tree / -l 3              # Overview
python filen.py ls /Projects -d          # Detailed view
python filen.py resolve "/path/to/file"  # Debug resolution
```

## 🐛 Troubleshooting

### Login Issues

```bash
# Enable verbose mode to see full error details
python filen.py -v login

# Check credentials file
cat ~/.filen-cli/credentials.json

# Clear credentials and re-login
python filen.py logout
python filen.py login
```

### Upload/Download Issues

```bash
# Enable verbose mode
python filen.py -v upload ./file.pdf -t /Documents

# Check batch state (if interrupted)
ls ~/.filen-cli/batch_states/

# Force overwrite conflicts
python filen.py upload ./file.pdf -t /Documents --on-conflict overwrite

# Clear batch state manually (if corrupt)
rm ~/.filen-cli/batch_states/<batch-id>.json
```

### Path Resolution Issues

```bash
# Debug path resolution
python filen.py resolve "/path/to/item"

# List parent folder to verify
python filen.py ls /path/to

# Check folder structure
python filen.py tree /path -l 3
```
