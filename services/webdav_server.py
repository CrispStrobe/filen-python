#!/usr/bin/env python3
"""
filen_cli/services/webdav_server.py
WebDAV Server implementation for Filen
"""

import os
import sys
import signal
import atexit
import socket
from typing import Optional, Dict, Any

try:
    from wsgidav.wsgidav_app import WsgiDAVApp
except ImportError:
    print("❌ Missing WebDAV dependencies. Install with: pip install WsgiDAV waitress")
    sys.exit(1)

from config.config import config_service
from services.network_utils import network_utils
from services.webdav_provider import FilenDAVProvider

class WebDAVServer:
    """WebDAV Server for Filen Drive"""
    
    def __init__(self):
        self.server = None
        self.app = None
        self.is_running = False
        atexit.register(self._cleanup_on_exit)
        
    def _create_wsgidav_app(self, port: int, preserve_timestamps: bool) -> WsgiDAVApp:
        """Create WsgiDAV application configuration"""
        
        # Get WebDAV credentials from config
        dav_conf = config_service.read_webdav_config()
        username = dav_conf.get('username', 'filen')
        password = dav_conf.get('password', 'filen-webdav')

        config = {
            'host': '0.0.0.0',
            'port': port,
            'provider_mapping': {
                '/': FilenDAVProvider(preserve_timestamps=preserve_timestamps),
            },
            'simple_dc': {
                'user_mapping': {
                    '*': {
                        username: {
                            'password': password,
                            'description': 'Filen Drive User',
                        }
                    }
                }
            },
            'verbose': 1,
            'logging': {
                "enable": True,
                "enable_loggers": ["wsgidav"],
            },
            'property_manager': True, 
            'lock_storage': True,
        }
        return WsgiDAVApp(config)
    
    def start(self, port: Optional[int] = None, background: bool = False, 
            preserve_timestamps: bool = True) -> Dict[str, Any]: 
        """Start the WebDAV server"""
        try:
            dav_conf = config_service.read_webdav_config()
            port = port or int(dav_conf.get('port', 8080))
            
            # Initialize App
            self.app = self._create_wsgidav_app(port, preserve_timestamps)
            
            print(f"🚀 Starting Filen WebDAV Server on port {port}...")
            print(f"   Preserve Timestamps: {preserve_timestamps}")
            
            if background:
                # Background handling is done via CLI wrapper, this is the process entry
                from waitress import serve
                serve(self.app, host="0.0.0.0", port=port, _quiet=True)
            else:
                # Foreground with Waitress
                from waitress import serve
                serve(self.app, host="0.0.0.0", port=port)

            return {"success": True}

        except Exception as e:
            return {"success": False, "message": str(e)}

    def stop(self) -> Dict[str, Any]:
        """Stop WebDAV server (kills process by PID)"""
        pid = config_service.read_webdav_pid()
        if not pid:
            return {'success': False, 'message': 'No PID file found'}
            
        if network_utils.kill_process(pid):
            config_service.clear_webdav_pid()
            return {'success': True, 'message': 'Server stopped'}
        return {'success': False, 'message': 'Failed to kill process'}

    def _cleanup_on_exit(self):
        config_service.clear_webdav_pid()

# Global instance
webdav_server = WebDAVServer()