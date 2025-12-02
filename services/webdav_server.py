#!/usr/bin/env python3
"""
filen_cli/services/webdav_server.py
WebDAV Server implementation for Filen
"""

import os
import sys
import atexit
from typing import Optional, Dict, Any

try:
    from wsgidav.wsgidav_app import WsgiDAVApp
except ImportError:
    print("❌ Missing WebDAV dependencies. Install with: pip install WsgiDAV waitress")
    sys.exit(1)

from config.config import config_service
from services.network_utils import network_utils
from services.webdav_provider import FilenDAVProvider

# --- CORS MIDDLEWARE (FIXED FOR AUTH) ---
class CorsMiddleware:
    """
    Handles CORS for Web clients. 
    Critically, this echoes the 'Origin' header and sets 'Access-Control-Allow-Credentials'.
    Without this, browsers block the 401 Unauthorized response, breaking login.
    """
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        # 1. Capture the specific Origin from the request (e.g., http://localhost:52026)
        # Browsers require the exact origin (not '*') if Credentials=true
        origin = environ.get('HTTP_ORIGIN', '*')
        
        def custom_start_response(status, headers, exc_info=None):
            # 2. Inject headers into EVERY response (including 401s and 500s)
            headers.append(('Access-Control-Allow-Origin', origin))
            headers.append(('Access-Control-Allow-Credentials', 'true'))
            headers.append(('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, PROPFIND, PROPPATCH, MKCOL, COPY, MOVE, LOCK, UNLOCK, OPTIONS, HEAD'))
            headers.append(('Access-Control-Allow-Headers', 'Authorization, Content-Type, Depth, Destination, If-Match, If-None-Match, If-Modified-Since, Overwrite, Range'))
            headers.append(('Access-Control-Expose-Headers', 'DAV, ETag, Link, Content-Range, Content-Length, WWW-Authenticate'))
            return start_response(status, headers, exc_info)

        # 3. Handle Pre-flight OPTIONS immediately
        if environ['REQUEST_METHOD'] == 'OPTIONS':
            start_response('200 OK', [
                ('Access-Control-Allow-Origin', origin),
                ('Access-Control-Allow-Credentials', 'true'),
                ('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, PROPFIND, PROPPATCH, MKCOL, COPY, MOVE, LOCK, UNLOCK, OPTIONS, HEAD'),
                ('Access-Control-Allow-Headers', 'Authorization, Content-Type, Depth, Destination, If-Match, If-None-Match, If-Modified-Since, Overwrite, Range'),
                ('Content-Length', '0')
            ])
            return [b'']

        return self.app(environ, custom_start_response)

class WebDAVServer:
    """WebDAV Server for Filen Drive"""
    
    def __init__(self):
        self.server = None
        self.app = None
        atexit.register(self._cleanup_on_exit)
        
    def _create_wsgidav_app(self, port: int, preserve_timestamps: bool) -> WsgiDAVApp:
        """Create WsgiDAV application configuration"""
        
        # Get WebDAV credentials from config
        dav_conf = config_service.read_webdav_config()
        username = dav_conf.get('username', 'filen')
        password = dav_conf.get('password', 'filen-webdav')
        
        # DEBUG: Print credentials so user knows exactly what to type
        print(f"   🔑 WebDAV Credentials: {username} / {password}")

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
            
            print(f"🚀 Starting Filen WebDAV Server on port {port}...")
            
            # Initialize App
            raw_app = self._create_wsgidav_app(port, preserve_timestamps)
            
            # --- APPLY CORS MIDDLEWARE ---
            self.app = CorsMiddleware(raw_app)
            print(f"   🌐 CORS Enabled (Credentials Allowed)")
            
            if background:
                from waitress import serve
                serve(self.app, host="0.0.0.0", port=port, _quiet=True)
            else:
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