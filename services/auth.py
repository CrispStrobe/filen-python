#!/usr/bin/env python3
"""
filen_cli/services/auth.py
Authentication service for Filen CLI - ENHANCED VERSION
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional

from config.config import config_service
from services.api import api_client
from services.crypto import crypto_service


class AuthService:
    """Handles authentication flow - matches Internxt patterns"""

    def __init__(self):
        self.config = config_service
        self.api = api_client
        self.crypto = crypto_service

    def is_2fa_needed(self, email: str) -> bool:
        """
        Check if 2FA is required for this account
        Pre-check before attempting login
        """
        try:
            auth_info = self.api.get_auth_info(email)
            # Filen API doesn't explicitly tell us if 2FA is enabled
            # We'll know when we try to login
            return False  # Return False for now, we handle 2FA on error
        except Exception as e:
            print(f"    ⚠️  Could not determine 2FA status. Reason: {e}")
            return False

    def do_login(self, email: str, password: str, tfa_code: Optional[str] = None) -> Dict[str, Any]:
        """
        Performs the full login flow and correctly handles credentials.
        Matches Internxt do_login pattern
        """
        # Step 1: Get authentication info
        print("    📊 Getting authentication info...")
        auth_info = self.api.get_auth_info(email)
        auth_version = auth_info.get('authVersion', 2)
        salt = auth_info.get('salt', '')
        
        if not salt:
            raise ValueError("Login failed: Did not receive salt from auth info.")

        # Step 2: Perform client-side crypto operations
        print("    🔐 Performing client-side crypto operations...")
        derived = self.crypto.derive_keys(password, auth_version, salt)
        derived_password = derived['password']
        local_master_key = derived['masterKey']
        print("    ✅ Crypto operations complete.")

        # Step 3: Attempt login
        try:
            login_data = self.api.login(
                email,
                derived_password,
                auth_version,
                tfa_code or "XXXXXX"
            )
        except Exception as e:
            error_str = str(e)
            # Check for 2FA requirement
            if 'enter_2fa' in error_str.lower() or 'wrong_2fa' in error_str.lower():
                # Re-raise as specific 2FA error
                raise ValueError(f"2FA_REQUIRED: {error_str}")
            raise

        print("    ✅ Login API call successful!")

        # Step 4: Process master keys
        raw_keys = login_data.get('masterKeys', [])
        if isinstance(raw_keys, str):
            raw_keys = [raw_keys]
        
        print(f"    🔑 Decrypting {len(raw_keys)} master keys...")
        
        decrypted_keys = []
        for encrypted_key in raw_keys:
            try:
                decrypted = self.crypto.decrypt_metadata_002(encrypted_key, local_master_key)
                decrypted_keys.append(decrypted)
                print(f"    ✅ Master key decrypted successfully")
            except Exception as e:
                print(f"    ⚠️  Failed to decrypt a master key: {e}")
        
        if not decrypted_keys:
            print("    ⚠️  Warning: No master keys decrypted. Using local master key.")
            decrypted_keys.append(local_master_key)

        # Step 5: Get base folder UUID
        api_key = login_data.get('apiKey')
        if not api_key:
            raise ValueError("Login failed: No API key received")
        
        self.api.set_auth(api_key)
        
        print("    📂 Fetching root folder info...")
        base_folder_uuid = self.api.get_base_folder_uuid()
        
        if not base_folder_uuid:
            raise ValueError("Login failed: Could not fetch base folder UUID")

        # Step 6: Build credentials object
        credentials = {
            'email': email,
            'apiKey': api_key,
            'masterKeys': '|'.join(decrypted_keys),
            'baseFolderUUID': base_folder_uuid,
            'userId': str(login_data.get('id', login_data.get('userId', ''))),
            'lastLoggedInAt': datetime.now(timezone.utc).isoformat(),
        }

        return credentials

    def login(self, email: str, password: str, tfa_code: Optional[str] = None) -> Dict[str, Any]:
        """
        Public login method - saves credentials after successful login
        Matches Internxt pattern
        """
        credentials = self.do_login(email, password, tfa_code)
        self.config.save_credentials(credentials)
        self.api.set_auth(credentials.get('apiKey'))
        
        print("✅ Login successful!")
        print(f"   User: {email}")
        print(f"   Root: {credentials['baseFolderUUID']}")
        
        keys = [k for k in credentials['masterKeys'].split('|') if k]
        print(f"   Master Keys: {len(keys)}")
        
        return credentials

    def get_auth_details(self) -> Dict[str, Any]:
        """
        Get saved credentials with validation
        Matches Internxt get_auth_details pattern
        """
        credentials = self.config.read_credentials()
        
        if not credentials:
            raise ValueError("MissingCredentialsError: No valid credentials found. Please login.")
        
        # Validate required fields
        required_fields = ['email', 'apiKey', 'masterKeys', 'baseFolderUUID']
        missing_fields = [f for f in required_fields if f not in credentials or not credentials[f]]
        
        if missing_fields:
            raise ValueError(f"MissingCredentialsError: Credentials missing required fields: {', '.join(missing_fields)}")
        
        # Set API auth
        self.api.set_auth(credentials.get('apiKey'))
        
        return credentials

    def get_credentials(self) -> Dict[str, Any]:
        """
        Alias for get_auth_details - for backwards compatibility
        """
        return self.get_auth_details()

    def logout(self) -> None:
        """
        Logout and clear credentials
        Matches Internxt pattern
        """
        self.config.clear_credentials()
        self.api.set_auth(None)
        print("    ✅ Local credentials cleared.")

    def whoami(self) -> Optional[Dict[str, Any]]:
        """
        Get current user info
        Matches Internxt pattern
        """
        try:
            credentials = self.get_auth_details()
            return {
                'email': credentials.get('email', ''),
                'userId': credentials.get('userId', ''),
                'rootFolderId': credentials.get('baseFolderUUID', ''),
            }
        except ValueError:
            return None

    def validate_session(self) -> bool:
        """
        Validate that current session is still valid
        Useful for long-running processes
        """
        try:
            credentials = self.get_auth_details()
            
            # Try to fetch base folder UUID to validate API key
            self.api.get_base_folder_uuid()
            
            return True
        except Exception as e:
            print(f"    ⚠️  Session validation failed: {e}")
            return False

    def refresh_session(self) -> Dict[str, Any]:
        """
        Refresh session (Filen uses long-lived API keys, so this is a no-op)
        Included for API compatibility with Internxt pattern
        
        Note: Filen doesn't have token refresh like Internxt.
        If the API key becomes invalid, user must login again.
        """
        try:
            credentials = self.get_auth_details()
            
            # Validate the session is still good
            if not self.validate_session():
                raise ValueError("Session is no longer valid. Please login again.")
            
            # Update last refresh time
            credentials['lastRefreshAt'] = datetime.now(timezone.utc).isoformat()
            self.config.save_credentials(credentials)
            
            return credentials
        except Exception as e:
            raise Exception(f"Session refresh failed: {e}. Please login again.") from e


# Global instance
auth_service = AuthService()