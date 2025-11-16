# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - cloud.py
#  Cloud storage integration
#  Devon • 2025‑05‑09
# ──────────────────────────────────────────────────────────────────────────────

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime
import threading
import queue
from typing import Dict, List, Optional
# Optional imports (for cloud storage)
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    requests = None

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False
    Credentials = None
    InstalledAppFlow = None
    Request = None
    build = None
    MediaFileUpload = None

try:
    import dropbox
    from dropbox.exceptions import ApiError
    DROPBOX_AVAILABLE = True
except ImportError:
    DROPBOX_AVAILABLE = False
    dropbox = None
    ApiError = None

try:
    from cryptography.fernet import Fernet
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False
    Fernet = None

try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False
    keyring = None
import time

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from . import config
from corefiles.error_handler import error_handler

class CredentialManager:
    """Manages secure storage and retrieval of cloud service credentials."""
    
    def __init__(self):
        self.encryption_key = self._get_or_create_key()
        self.cipher_suite = Fernet(self.encryption_key)
        
    def _get_or_create_key(self) -> bytes:
        """Get existing encryption key or create a new one."""
        key = keyring.get_password("CleanHouse", "encryption_key")
        if not key:
            key = Fernet.generate_key()
            keyring.set_password("CleanHouse", "encryption_key", key.decode())
        return key if isinstance(key, bytes) else key.encode()
    
    def store_credentials(self, service: str, credentials: Dict) -> None:
        """Store encrypted credentials for a service."""
        encrypted_data = self.cipher_suite.encrypt(json.dumps(credentials).encode())
        keyring.set_password(f"CleanHouse_{service}", "credentials", encrypted_data.decode())
    
    def get_credentials(self, service: str) -> Optional[Dict]:
        """Retrieve and decrypt credentials for a service."""
        encrypted_data = keyring.get_password(f"CleanHouse_{service}", "credentials")
        if not encrypted_data:
            return None
        try:
            decrypted_data = self.cipher_suite.decrypt(encrypted_data.encode())
            return json.loads(decrypted_data)
        except Exception as e:
            logging.error(f"Failed to decrypt credentials for {service}: {e}")
            return None

class CloudStorageManager:
    def __init__(self):
        self.upload_queue = queue.Queue()
        self.upload_thread = threading.Thread(target=self._upload_worker, daemon=True)
        self.upload_thread.start()
        self.cloud_init_errors = set()  # Track which errors have been logged
        self.credential_manager = CredentialManager()
        self.rate_limiter = RateLimiter()
        self._initialize_cloud_services()

    def _initialize_cloud_services(self):
        """Initialize cloud service connections with OAuth flow."""
        self.services = {}
        
        # Initialize Google Drive
        if config.CLOUD_SERVICES.get('gdrive', False):
            try:
                self.services['gdrive'] = self._init_google_drive()
                error_handler.reset_error('cloud_init', 'gdrive')
            except Exception as e:
                if 'gdrive' not in self.cloud_init_errors:
                    logging.error("Failed to initialize Google Drive", 
                                extra={'error_type': 'cloud_init', 'error_key': 'gdrive'})
                    self.cloud_init_errors.add('gdrive')
        else:
            logging.info("Google Drive integration is disabled.")

        # Initialize Dropbox
        if config.CLOUD_SERVICES.get('dropbox', False):
            try:
                self.services['dropbox'] = self._init_dropbox()
                error_handler.reset_error('cloud_init', 'dropbox')
            except Exception as e:
                if 'dropbox' not in self.cloud_init_errors:
                    logging.error("Failed to initialize Dropbox",
                                extra={'error_type': 'cloud_init', 'error_key': 'dropbox'})
                    self.cloud_init_errors.add('dropbox')
        else:
            logging.info("Dropbox integration is disabled.")

        # Initialize OneDrive
        if config.CLOUD_SERVICES.get('onedrive', False):
            try:
                self.services['onedrive'] = self._init_onedrive()
                error_handler.reset_error('cloud_init', 'onedrive')
            except Exception as e:
                if 'onedrive' not in self.cloud_init_errors:
                    logging.error("Failed to initialize OneDrive",
                                extra={'error_type': 'cloud_init', 'error_key': 'onedrive'})
                    self.cloud_init_errors.add('onedrive')
        else:
            logging.info("OneDrive integration is disabled.")

        # Initialize GitHub
        if config.CLOUD_SERVICES.get('github', False):
            try:
                self.services['github'] = self._init_github()
                error_handler.reset_error('cloud_init', 'github')
            except Exception as e:
                if 'github' not in self.cloud_init_errors:
                    logging.error("Failed to initialize GitHub",
                                extra={'error_type': 'cloud_init', 'error_key': 'github'})
                    self.cloud_init_errors.add('github')
        else:
            logging.info("GitHub integration is disabled.")

    def _init_google_drive(self):
        """Initialize Google Drive API with OAuth flow."""
        SCOPES = ['https://www.googleapis.com/auth/drive.file']
        
        # Try to get stored credentials
        creds_data = self.credential_manager.get_credentials('gdrive')
        if creds_data:
            creds = Credentials.from_authorized_user_info(creds_data)
            if creds and creds.valid:
                return build('drive', 'v3', credentials=creds)
        
        # If no valid credentials, start OAuth flow
        flow = InstalledAppFlow.from_client_secrets_file(
            'credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
        
        # Store credentials
        self.credential_manager.store_credentials('gdrive', {
            'token': creds.token,
            'refresh_token': creds.refresh_token,
            'token_uri': creds.token_uri,
            'client_id': creds.client_id,
            'client_secret': creds.client_secret,
            'scopes': creds.scopes
        })
        
        return build('drive', 'v3', credentials=creds)

    def _init_dropbox(self):
        """Initialize Dropbox API with OAuth flow."""
        # Try to get stored credentials
        creds_data = self.credential_manager.get_credentials('dropbox')
        if creds_data and 'access_token' in creds_data:
            return dropbox.Dropbox(creds_data['access_token'])
        
        # If no valid credentials, start OAuth flow
        app_key = os.getenv('DROPBOX_APP_KEY')
        app_secret = os.getenv('DROPBOX_APP_SECRET')
        
        if not app_key or not app_secret:
            raise ValueError("Dropbox app credentials not found")
        
        auth_flow = dropbox.DropboxOAuth2FlowNoRedirect(app_key, app_secret)
        authorize_url = auth_flow.start()
        
        print(f"Please visit this URL to authorize the application: {authorize_url}")
        auth_code = input("Enter the authorization code: ").strip()
        
        try:
            oauth_result = auth_flow.finish(auth_code)
            self.credential_manager.store_credentials('dropbox', {
                'access_token': oauth_result.access_token
            })
            return dropbox.Dropbox(oauth_result.access_token)
        except Exception as e:
            raise Exception(f"Failed to complete Dropbox OAuth flow: {e}")

    def _init_onedrive(self):
        """Initialize OneDrive using Microsoft Graph API with OAuth flow."""
        # Try to get stored credentials
        creds_data = self.credential_manager.get_credentials('onedrive')
        if creds_data and all(k in creds_data for k in ['client_id', 'client_secret', 'access_token']):
            return creds_data
        
        # If no valid credentials, start OAuth flow
        client_id = os.getenv('ONEDRIVE_CLIENT_ID')
        client_secret = os.getenv('ONEDRIVE_CLIENT_SECRET')
        
        if not client_id or not client_secret:
            raise ValueError("OneDrive credentials not found")
        
        # Implement Microsoft OAuth flow here
        # This is a placeholder for the actual OAuth implementation
        raise NotImplementedError("OneDrive OAuth flow not implemented")

    def _init_github(self):
        """Initialize GitHub API with OAuth flow."""
        # Try to get stored credentials
        creds_data = self.credential_manager.get_credentials('github')
        if creds_data and 'token' in creds_data:
            return {'token': creds_data['token']}
        
        # If no valid credentials, start OAuth flow
        client_id = os.getenv('GITHUB_CLIENT_ID')
        client_secret = os.getenv('GITHUB_CLIENT_SECRET')
        
        if not client_id or not client_secret:
            raise ValueError("GitHub credentials not found")
        
        # Implement GitHub OAuth flow here
        # This is a placeholder for the actual OAuth implementation
        raise NotImplementedError("GitHub OAuth flow not implemented")

    def _upload_worker(self):
        """Background worker for processing uploads with rate limiting."""
        while True:
            try:
                file_path, service_name = self.upload_queue.get()
                with self.rate_limiter.limit(service_name):
                    self._upload_file(file_path, service_name)
                self.upload_queue.task_done()
            except Exception as e:
                logging.error(f"Error in upload worker: {e}")

    def _upload_file(self, file_path: Path, service_name: str):
        """Upload a file to the specified cloud service with enhanced error handling."""
        try:
            if service_name == 'gdrive':
                self._upload_to_gdrive(file_path)
            elif service_name == 'dropbox':
                self._upload_to_dropbox(file_path)
            elif service_name == 'onedrive':
                self._upload_to_onedrive(file_path)
            elif service_name == 'github':
                self._upload_to_github(file_path)
        except Exception as e:
            logging.error(f"Failed to upload {file_path} to {service_name}: {e}")
            raise

    def _upload_to_gdrive(self, file_path: Path):
        """Upload a file to Google Drive root directory."""
        file_metadata = {'name': file_path.name}
        media = MediaFileUpload(str(file_path), resumable=True)
        
        # Check if file exists and delete it
        try:
            results = self.services['gdrive'].files().list(
                q=f"name='{file_path.name}' and trashed=false",
                fields="files(id)"
            ).execute()
            for file in results.get('files', []):
                self.services['gdrive'].files().delete(fileId=file['id']).execute()
        except Exception as e:
            logging.warning(f"Error checking for existing file in Google Drive: {e}")
        
        # Upload new file
        self.services['gdrive'].files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()

    def _upload_to_dropbox(self, file_path: Path):
        """Upload a file to Dropbox root directory."""
        with open(file_path, 'rb') as f:
            try:
                # Try to delete existing file first
                try:
                    self.services['dropbox'].files_delete_v2(f"/{file_path.name}")
                except ApiError as e:
                    if e.error.is_path() and e.error.get_path().is_not_found():
                        pass  # File doesn't exist, which is fine
                    else:
                        raise
                
                # Upload new file
                self.services['dropbox'].files_upload(
                    f.read(),
                    f"/{file_path.name}",
                    mode=dropbox.files.WriteMode.overwrite
                )
            except Exception as e:
                logging.error(f"Failed to upload to Dropbox: {e}")
                raise

    def _upload_to_onedrive(self, file_path: Path):
        """Upload a file to OneDrive root directory."""
        headers = {
            'Authorization': f"Bearer {self.services['onedrive']['access_token']}",
            'Content-Type': 'application/json'
        }
        
        # Check if file exists and delete it
        check_url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{file_path.name}"
        try:
            if not REQUESTS_AVAILABLE:
                raise ImportError("requests module required for cloud storage")
            response = requests.get(check_url, headers=headers)
            if response.status_code == 200:
                if REQUESTS_AVAILABLE:
                    requests.delete(check_url, headers=headers)
        except Exception as e:
            logging.warning(f"Error checking for existing file in OneDrive: {e}")
        
        # Upload new file
        upload_url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{file_path.name}:/content"
        with open(file_path, 'rb') as f:
            content = f.read()
        
        if not REQUESTS_AVAILABLE:
            raise ImportError("requests module required for cloud storage")
        upload_response = requests.put(
            upload_url,
            headers={'Content-Length': str(len(content))},
            data=content
        )
        
        if upload_response.status_code not in (200, 201):
            raise Exception(f"Failed to upload to OneDrive: {upload_response.text}")

    def _upload_to_github(self, file_path: Path):
        """Upload a file to GitHub repository root."""
        headers = {
            'Authorization': f"token {self.services['github']['token']}",
            'Accept': 'application/vnd.github.v3+json'
        }
        
        # Check if file exists and get its SHA
        url = f"https://api.github.com/repos/{config.GITHUB_REPO}/contents/{file_path.name}"
        try:
            if not REQUESTS_AVAILABLE:
                raise ImportError("requests module required for cloud storage")
            response = requests.get(url, headers=headers)
            sha = response.json().get('sha') if response.status_code == 200 else None
        except Exception as e:
            logging.warning(f"Error checking for existing file in GitHub: {e}")
            sha = None
        
        with open(file_path, 'rb') as f:
            content = f.read()
        
        data = {
            'message': f'Update {file_path.name}',
            'content': content.decode('utf-8')
        }
        if sha:
            data['sha'] = sha
        
        if not REQUESTS_AVAILABLE:
            raise ImportError("requests module required for cloud storage")
        response = requests.put(url, headers=headers, json=data)
        if response.status_code not in (200, 201):
            raise Exception(f"Failed to upload to GitHub: {response.text}")

    def queue_upload(self, file_path: Path, service_name: str):
        """Queue a file for upload to the specified cloud service."""
        self.upload_queue.put((file_path, service_name))

    def upload_baseline(self, baseline_file: Path):
        """Upload the integrity baseline to all cloud services."""
        for service in self.services.keys():
            self.queue_upload(baseline_file, service)

    def cleanup(self):
        """Clean up cloud storage resources."""
        # Wait for upload queue to empty
        self.upload_queue.join()

class RateLimiter:
    """Rate limiter for cloud service operations."""
    
    def __init__(self):
        self.limits = {
            'gdrive': {'calls': 1000, 'period': 3600},  # 1000 calls per hour
            'dropbox': {'calls': 800, 'period': 3600},  # 800 calls per hour
            'onedrive': {'calls': 600, 'period': 3600},  # 600 calls per hour
            'github': {'calls': 5000, 'period': 3600}   # 5000 calls per hour
        }
        self.calls = {service: [] for service in self.limits.keys()}
        self.lock = threading.Lock()
    
    def limit(self, service: str):
        """Context manager for rate limiting."""
        return RateLimitContext(self, service)

class RateLimitContext:
    """Context manager for rate limiting."""
    
    def __init__(self, limiter: RateLimiter, service: str):
        self.limiter = limiter
        self.service = service
    
    def __enter__(self):
        with self.limiter.lock:
            now = time.time()
            limit = self.limiter.limits[self.service]
            
            # Remove old calls
            self.limiter.calls[self.service] = [
                t for t in self.limiter.calls[self.service]
                if now - t < limit['period']
            ]
            
            # Check if we're over the limit
            if len(self.limiter.calls[self.service]) >= limit['calls']:
                oldest_call = self.limiter.calls[self.service][0]
                wait_time = limit['period'] - (now - oldest_call)
                if wait_time > 0:
                    time.sleep(wait_time)
            
            # Add new call
            self.limiter.calls[self.service].append(now)
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass 