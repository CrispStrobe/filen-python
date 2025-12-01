#!/usr/bin/env python3
"""
filen_cli/services/crypto.py
Cryptographic operations for Filen - COMPLETE VERSION
"""

import os
import hashlib
import base64
import secrets
import string
from typing import Tuple, Dict, Any
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend


class CryptoService:
    """Handles all cryptographic operations matching Filen's protocol"""

    def __init__(self):
        self.backend = default_backend()

    def derive_keys(self, password: str, auth_version: int, salt: str) -> Dict[str, str]:
        """
        Derive keys from password using PBKDF2
        """
        # PBKDF2 with 200000 iterations, 64-byte output
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA512(),
            length=64,
            salt=salt.encode('utf-8'),
            iterations=200000,
            backend=self.backend
        )
        
        derived = kdf.derive(password.encode('utf-8'))
        key_hex = derived.hex().lower()
        
        if auth_version == 2:
            # v2: first 64 chars = master key, hash rest for password
            master_key = key_hex[:64]
            password_hash = hashlib.sha512(key_hex[64:].encode()).hexdigest().lower()
            return {
                'masterKey': master_key,
                'password': password_hash
            }
        else:
            # v1: use full key for both
            return {
                'masterKey': key_hex,
                'password': key_hex
            }

    def encrypt_metadata_002(self, text: str, key: str) -> str:
        """
        Encrypt metadata using version 002 format
        AES-256-GCM with 12-byte IV
        """
        # Generate random 12-byte IV
        iv = self.random_string(12)
        
        # Derive key using PBKDF2
        dk = self._pbkdf2(key.encode(), key.encode(), 1, 32)
        
        # Encrypt with AES-256-GCM
        cipher = Cipher(
            algorithms.AES(dk),
            modes.GCM(iv.encode()),
            backend=self.backend
        )
        encryptor = cipher.encryptor()
        
        ciphertext = encryptor.update(text.encode()) + encryptor.finalize()
        tag = encryptor.tag
        
        # Format: "002" + IV + base64(ciphertext + tag)
        encrypted = base64.b64encode(ciphertext + tag).decode()
        return f"002{iv}{encrypted}"

    def decrypt_metadata_002(self, encrypted: str, key: str) -> str:
        """
        Decrypt metadata using version 002 format
        """
        if not encrypted.startswith('002'):
            raise ValueError('Invalid metadata version')
        
        # Extract IV and ciphertext
        iv = encrypted[3:15]
        encrypted_data = base64.b64decode(encrypted[15:])
        
        # Split ciphertext and tag (last 16 bytes)
        ciphertext = encrypted_data[:-16]
        tag = encrypted_data[-16:]
        
        # Derive key
        dk = self._pbkdf2(key.encode(), key.encode(), 1, 32)
        
        # Decrypt
        cipher = Cipher(
            algorithms.AES(dk),
            modes.GCM(iv.encode(), tag),
            backend=self.backend
        )
        decryptor = cipher.decryptor()
        
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        return plaintext.decode('utf-8')

    def encrypt_data(self, data: bytes, key: bytes) -> bytes:
        """
        Encrypt file data using AES-256-GCM
        12-byte random IV prepended
        """
        iv = os.urandom(12)
        
        cipher = Cipher(
            algorithms.AES(key),
            modes.GCM(iv),
            backend=self.backend
        )
        encryptor = cipher.encryptor()
        
        ciphertext = encryptor.update(data) + encryptor.finalize()
        tag = encryptor.tag
        
        # Return: IV + ciphertext + tag
        return iv + ciphertext + tag

    def decrypt_data(self, encrypted: bytes, key: bytes) -> bytes:
        """
        Decrypt file data using AES-256-GCM
        """
        # Extract components
        iv = encrypted[:12]
        tag = encrypted[-16:]
        ciphertext = encrypted[12:-16]
        
        cipher = Cipher(
            algorithms.AES(key),
            modes.GCM(iv, tag),
            backend=self.backend
        )
        decryptor = cipher.decryptor()
        
        return decryptor.update(ciphertext) + decryptor.finalize()

    def hash_file_sha512(self, file_path: str, chunk_size: int = 1048576) -> str:
        """Hash file using SHA-512"""
        hasher = hashlib.sha512()
        
        with open(file_path, 'rb') as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        
        return hasher.hexdigest().lower()

    def hash_filename(self, filename: str, email: str, master_key: str) -> str:
        """
        Generate HMAC-SHA256 hash of filename
        """
        import hmac
        
        # Generate HMAC key from master key and email
        hmac_key = self._pbkdf2(
            master_key.encode(),
            email.lower().encode(),
            1,
            32
        )
        
        # HMAC-SHA256 of lowercase filename
        h = hmac.new(hmac_key, filename.lower().encode(), hashlib.sha256)
        return h.hexdigest().lower()

    def _pbkdf2(self, password: bytes, salt: bytes, iterations: int, length: int) -> bytes:
        """PBKDF2 key derivation"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA512(),
            length=length,
            salt=salt,
            iterations=iterations,
            backend=self.backend
        )
        return kdf.derive(password)

    def random_string(self, length: int) -> str:
        """Generate random string for keys/IVs"""
        alphabet = string.ascii_letters + string.digits + '-_'
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    def random_bytes(self, length: int) -> bytes:
        """Generate random bytes"""
        return os.urandom(length)

    def generate_uuid(self) -> str:
        """Generate UUID v4"""
        import uuid
        return str(uuid.uuid4())


# Global instance
crypto_service = CryptoService()