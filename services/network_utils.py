#!/usr/bin/env python3
"""
filen_cli/services/network_utils.py
Network utilities for Filen CLI - COMPLETE VERSION
"""

import os
import hashlib
import subprocess
import platform
import socket
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

from config.config import config_service


class NetworkUtils:
    """Network utilities for WebDAV SSL certificates and process management"""
    
    @classmethod
    def is_process_running(cls, pid: int) -> bool:
        """Check if process is running - matches Dart _isProcessRunning"""
        try:
            if platform.system() == 'Windows':
                # Windows: use tasklist
                result = subprocess.run(
                    ['tasklist', '/FI', f'PID eq {pid}'],
                    capture_output=True,
                    text=True
                )
                return str(pid) in result.stdout
            else:
                # Unix: use ps
                result = subprocess.run(
                    ['ps', '-p', str(pid)],
                    capture_output=True
                )
                return result.returncode == 0
        except Exception:
            return False
    
    @classmethod
    def kill_process(cls, pid: int, force: bool = False) -> bool:
        """
        Kill process by PID
        Matches Dart handleWebdavStop implementation
        """
        try:
            if platform.system() == 'Windows':
                cmd = ['taskkill', '/PID', str(pid)]
                if force:
                    cmd.append('/F')
                subprocess.run(cmd)
                return True
            else:
                import signal
                sig = signal.SIGKILL if force else signal.SIGTERM
                os.kill(pid, sig)
                return True
        except Exception:
            return False
    
    @classmethod
    def get_local_ip(cls) -> str:
        """Get local IP address - matches Dart _getLocalIpAddress"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return 'localhost'
    
    @classmethod
    def get_webdav_ssl_certs(cls) -> Dict[str, bytes]:
        """
        Get WebDAV SSL certificates, generating new ones if needed
        Matches TypeScript getWebdavSSLCerts from Internxt
        """
        cert_file = config_service.webdav_ssl_cert
        key_file = config_service.webdav_ssl_key
        
        # Check if certificates exist and are valid
        if cert_file.exists() and key_file.exists():
            try:
                # Read existing certificates
                cert_pem = cert_file.read_bytes()
                key_pem = key_file.read_bytes()
                
                # Check if certificate is still valid
                cert = x509.load_pem_x509_certificate(cert_pem, default_backend())
                now = datetime.now(timezone.utc)
                
                # Use UTC-aware method
                try:
                    expiry_date = cert.not_valid_after_utc
                except AttributeError:
                    expiry_date = cert.not_valid_after.replace(tzinfo=timezone.utc)
                
                if now < expiry_date:
                    print("✅ Using existing SSL certificate")
                    return {
                        'cert': cert_pem,
                        'key': key_pem
                    }
                else:
                    print("🔄 SSL certificate expired, generating new one...")
            
            except Exception as e:
                print(f"🔄 SSL certificate invalid ({e}), generating new one...")
        
        # Generate new certificates
        return cls.generate_new_selfsigned_certs()
    
    @classmethod
    def generate_new_selfsigned_certs(cls) -> Dict[str, bytes]:
        """
        Generate new self-signed SSL certificates
        Matches TypeScript generateNewSelfSignedCerts
        """
        print("🔐 Generating new SSL certificate for WebDAV server...")
        
        try:
            # Generate private key
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            )
            
            # Create certificate subject
            subject = issuer = x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Filen WebDAV Server"),
                x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Local Development"),
                x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            ])
            
            # Certificate valid for 1 year
            valid_from = datetime.now(timezone.utc)
            valid_to = valid_from + timedelta(days=365)
            
            # Build certificate
            builder = x509.CertificateBuilder().subject_name(
                subject
            ).issuer_name(
                issuer
            ).public_key(
                private_key.public_key()
            ).serial_number(
                x509.random_serial_number()
            ).not_valid_before(
                valid_from
            ).not_valid_after(
                valid_to
            )
            
            # Add Subject Alternative Names
            import ipaddress
            
            san_list = [
                x509.DNSName("localhost"),
                x509.DNSName("127.0.0.1"),
                x509.DNSName("::1"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                x509.IPAddress(ipaddress.IPv6Address("::1")),
                x509.DNSName("webdav.local.filen.io"),
                x509.DNSName("filen.local"),
                x509.DNSName("webdav.local")
            ]
            
            builder = builder.add_extension(
                x509.SubjectAlternativeName(san_list),
                critical=False,
            )
            
            # Add basic constraints
            builder = builder.add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
            
            # Add key usage
            builder = builder.add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    key_encipherment=True,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    content_commitment=False,
                    data_encipherment=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            
            # Add extended key usage
            builder = builder.add_extension(
                x509.ExtendedKeyUsage([
                    x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
                    x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
                ]),
                critical=True,
            )
            
            # Sign the certificate
            cert = builder.sign(private_key, hashes.SHA256(), default_backend())
            
            # Serialize to PEM format
            cert_pem = cert.public_bytes(serialization.Encoding.PEM)
            key_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            
            # Save certificates
            cls.save_webdav_ssl_certs(cert_pem, key_pem)
            
            print("✅ SSL certificate generated and saved successfully")
            print(f"📋 Certificate valid until: {valid_to.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            
            return {
                'cert': cert_pem,
                'key': key_pem
            }
        
        except Exception as e:
            print(f"❌ Failed to generate SSL certificate: {e}")
            raise RuntimeError(f"SSL certificate generation failed: {e}")
    
    @classmethod
    def save_webdav_ssl_certs(cls, cert_pem: bytes, key_pem: bytes) -> None:
        """Save SSL certificates to disk with proper permissions"""
        try:
            # Ensure directory exists
            config_service.webdav_ssl_dir.mkdir(parents=True, exist_ok=True)
            
            # Write certificate
            config_service.webdav_ssl_cert.write_bytes(cert_pem)
            config_service.webdav_ssl_key.write_bytes(key_pem)
            
            # Set secure permissions (owner read/write only)
            if os.name != 'nt':  # Unix-like systems
                os.chmod(config_service.webdav_ssl_cert, 0o600)
                os.chmod(config_service.webdav_ssl_key, 0o600)
            
            print(f"🔐 Certificates saved to: {config_service.webdav_ssl_dir}")
        
        except Exception as e:
            raise RuntimeError(f"Failed to save SSL certificates: {e}")
    
    @classmethod
    def validate_ssl_certificates(cls) -> Dict[str, Any]:
        """Validate existing SSL certificates"""
        cert_file = config_service.webdav_ssl_cert
        key_file = config_service.webdav_ssl_key
        
        if not cert_file.exists() or not key_file.exists():
            return {
                'valid': False,
                'message': 'Certificate files not found'
            }
        
        try:
            cert_pem = cert_file.read_bytes()
            key_pem = key_file.read_bytes()
            
            # Load and validate certificate
            cert = x509.load_pem_x509_certificate(cert_pem, default_backend())
            private_key = serialization.load_pem_private_key(key_pem, password=None, backend=default_backend())
            
            # Check expiry
            now = datetime.now(timezone.utc)
            try:
                expiry_date = cert.not_valid_after_utc
            except AttributeError:
                expiry_date = cert.not_valid_after.replace(tzinfo=timezone.utc)
            
            is_expired = now >= expiry_date
            days_until_expiry = (expiry_date - now).days
            
            return {
                'valid': not is_expired,
                'expired': is_expired,
                'expiry_date': expiry_date.isoformat(),
                'days_until_expiry': days_until_expiry,
                'subject': cert.subject.rfc4514_string(),
                'issuer': cert.issuer.rfc4514_string(),
                'message': 'Valid' if not is_expired else f'Expired {abs(days_until_expiry)} days ago'
            }
        
        except Exception as e:
            return {
                'valid': False,
                'message': f'Certificate validation failed: {e}'
            }
        
    @classmethod
    def kill_process_by_port(cls, port: int) -> bool:
        """Find and kill process listening on specific port"""
        try:
            if platform.system() == 'Windows':
                # Windows: netstat -> findstr -> taskkill
                cmd = f"netstat -ano | findstr :{port}"
                result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
                lines = result.stdout.strip().split('\n')
                killed_any = False
                for line in lines:
                    parts = line.split()
                    if parts and 'LISTENING' in line:
                        pid = parts[-1]
                        cls.kill_process(int(pid), force=True)
                        killed_any = True
                return killed_any
            else:
                # Unix/MacOS: lsof
                cmd = ["lsof", "-t", "-i", f":{port}"]
                result = subprocess.run(cmd, capture_output=True, text=True)
                pids = result.stdout.strip().split('\n')
                killed_any = False
                for pid in pids:
                    if pid:
                        print(f"🔪 Force killing zombie process PID {pid} on port {port}...")
                        cls.kill_process(int(pid), force=True)
                        killed_any = True
                return killed_any
        except Exception as e:
            print(f"⚠️ Failed to kill by port: {e}")
            return False
    
    @classmethod
    def test_webdav_connection(cls, url: str, username: str, password: str) -> Dict[str, Any]:
        """
        Test WebDAV connection
        Matches Dart handleWebdavTest implementation
        """
        try:
            import requests
            from requests.auth import HTTPBasicAuth
            
            auth = HTTPBasicAuth(username, password)
            
            # Construct PROPFIND request
            propfind_body = '''<?xml version="1.0" encoding="utf-8"?>
<D:propfind xmlns:D="DAV:">
    <D:prop>
        <D:resourcetype/>
    </D:prop>
</D:propfind>'''
            
            # Test PROPFIND request (WebDAV discovery)
            response = requests.request(
                'PROPFIND',
                url,
                auth=auth,
                timeout=10,
                verify=False,  # Allow self-signed certificates
                headers={
                    'User-Agent': 'Filen WebDAV Test Client',
                    'Depth': '0',
                    'Content-Type': 'application/xml'
                },
                data=propfind_body
            )
            
            if response.status_code == 207 and '<?xml' in response.text:
                return {
                    'success': True,
                    'status_code': response.status_code,
                    'message': 'Connection successful! (Received 207 Multi-Status)',
                    'server': response.headers.get('Server', 'Unknown'),
                    'response_preview': response.text[:100]
                }
            else:
                return {
                    'success': False,
                    'status_code': response.status_code,
                    'message': f'Server returned status: {response.status_code}',
                    'response_preview': response.text[:100]
                }
        
        except Exception as e:
            if 'Connection' in str(e):
                return {
                    'success': False,
                    'message': 'Connection failed: Server is not running or unreachable'
                }
            elif 'timeout' in str(e).lower():
                return {
                    'success': False,
                    'message': 'Connection timed out. Is the server running?'
                }
            else:
                return {
                    'success': False,
                    'message': f'Connection test failed: {e}'
                }


# Global instance
network_utils = NetworkUtils()