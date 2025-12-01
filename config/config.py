#!/usr/bin/env python3
"""
filen_cli/config/config.py
Configuration management for Filen CLI - COMPLETE VERSION
"""

import os
import json
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any


class ConfigService:
    """Manages local configuration and credential storage"""

    def __init__(self):
        self.home_dir = Path.home()
        self.filen_cli_data_dir = self.home_dir / '.filen-cli'
        self.credentials_file = self.filen_cli_data_dir / 'credentials.json'
        self.batch_state_dir = self.filen_cli_data_dir / 'batch_states'
        self.webdav_pid_file = self.filen_cli_data_dir / 'webdav.pid'
        self.webdav_config_file = self.filen_cli_data_dir / 'webdav_config.json'
        self.webdav_ssl_dir = self.filen_cli_data_dir / 'webdav-ssl'
        self.webdav_ssl_cert = self.webdav_ssl_dir / 'cert.crt'
        self.webdav_ssl_key = self.webdav_ssl_dir / 'priv.key'
        
        # API endpoints
        self.api_url = 'https://gateway.filen.io'
        self.ingest_url = 'https://ingest.filen.io'
        self.egest_url = 'https://egest.filen.io'
        
        # WebDAV defaults
        self.webdav_default_port = 8080
        self.webdav_default_protocol = 'http'
        
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Ensure all necessary directories exist"""
        self.filen_cli_data_dir.mkdir(parents=True, exist_ok=True)
        self.batch_state_dir.mkdir(parents=True, exist_ok=True)
        self.webdav_ssl_dir.mkdir(parents=True, exist_ok=True)

    def save_credentials(self, credentials: Dict[str, Any]) -> None:
        """Save user credentials to file"""
        self._ensure_directories()
        with open(self.credentials_file, 'w') as f:
            json.dump(credentials, f, indent=2)

    def read_credentials(self) -> Optional[Dict[str, Any]]:
        """Read user credentials from file"""
        try:
            if self.credentials_file.exists():
                with open(self.credentials_file, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    def clear_credentials(self) -> None:
        """Clear user credentials"""
        if self.credentials_file.exists():
            self.credentials_file.unlink()

    def save_batch_state(self, batch_id: str, state: Dict[str, Any]) -> None:
        """Save batch operation state"""
        batch_file = self.batch_state_dir / f'batch_state_{batch_id}.json'
        with open(batch_file, 'w') as f:
            json.dump(state, f, indent=2)

    def load_batch_state(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Load batch operation state"""
        batch_file = self.batch_state_dir / f'batch_state_{batch_id}.json'
        try:
            if batch_file.exists():
                with open(batch_file, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    def delete_batch_state(self, batch_id: str) -> None:
        """Delete batch operation state"""
        batch_file = self.batch_state_dir / f'batch_state_{batch_id}.json'
        if batch_file.exists():
            batch_file.unlink()

    def generate_batch_id(self, operation_type: str, sources: list, target: str) -> str:
        """Generate unique batch ID - matches Dart implementation"""
        input_str = f"{operation_type}-{'|'.join(str(s) for s in sources)}-{target}"
        return hashlib.sha1(input_str.encode()).hexdigest()[:16]

    def save_webdav_pid(self, pid: int) -> None:
        """Save WebDAV server PID"""
        with open(self.webdav_pid_file, 'w') as f:
            f.write(str(pid))

    def read_webdav_pid(self) -> Optional[int]:
        """Read WebDAV server PID"""
        try:
            if self.webdav_pid_file.exists():
                with open(self.webdav_pid_file, 'r') as f:
                    return int(f.read().strip())
        except Exception:
            pass
        return None

    def clear_webdav_pid(self) -> None:
        """Clear WebDAV server PID"""
        if self.webdav_pid_file.exists():
            self.webdav_pid_file.unlink()

    def save_webdav_config(self, config: Dict[str, Any]) -> None:
        """Save WebDAV configuration"""
        with open(self.webdav_config_file, 'w') as f:
            json.dump(config, f, indent=2)

    def read_webdav_config(self) -> Dict[str, Any]:
        """Read WebDAV configuration with defaults"""
        try:
            if self.webdav_config_file.exists():
                with open(self.webdav_config_file, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        
        return {
            'port': self.webdav_default_port,
            'protocol': self.webdav_default_protocol,
            'username': 'filen',
            'password': 'filen-webdav'
        }


# Global instance
config_service = ConfigService()