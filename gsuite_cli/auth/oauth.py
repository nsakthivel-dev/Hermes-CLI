"""
OAuth 2.0 authentication handler for Google APIs
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from ..utils.formatters import print_error, print_info
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = {
    'calendar': ['https://www.googleapis.com/auth/calendar'],
    'gmail': [
        'https://www.googleapis.com/auth/gmail.modify',
        'https://www.googleapis.com/auth/gmail.settings.basic'
    ],
    'sheets': [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive.file'
    ],
    'drive': ['https://www.googleapis.com/auth/drive'],
    'tasks': ['https://www.googleapis.com/auth/tasks'],
    'documents': [
        'https://www.googleapis.com/auth/documents',
        'https://www.googleapis.com/auth/drive'
    ],
    'meet': [
        'https://www.googleapis.com/auth/meetings.space.created',
        'https://www.googleapis.com/auth/meetings.space.readonly',
        'https://www.googleapis.com/auth/meetings.space.settings',
        'https://www.googleapis.com/auth/meetings.conference.media.readonly',
    ],
    'forms': [
        'https://www.googleapis.com/auth/forms.body',
        'https://www.googleapis.com/auth/forms.responses.readonly'
    ],
    'chat': [
        'https://www.googleapis.com/auth/chat.spaces',
        'https://www.googleapis.com/auth/chat.spaces.readonly',
        'https://www.googleapis.com/auth/chat.messages',
        'https://www.googleapis.com/auth/chat.messages.readonly',
        'https://www.googleapis.com/auth/chat.memberships',
        'https://www.googleapis.com/auth/chat.memberships.readonly',
        'https://www.googleapis.com/auth/chat.messages.reactions',
        'https://www.googleapis.com/auth/chat.messages.reactions.readonly',
    ],
    'workspace_events': [
        'https://www.googleapis.com/auth/cloud-platform',
    ],
    'apps_script': [
        'https://www.googleapis.com/auth/script.projects',
        'https://www.googleapis.com/auth/script.deployments',
    ],
    'admin': [
        'https://www.googleapis.com/auth/admin.directory.user',
        'https://www.googleapis.com/auth/admin.directory.group',
        'https://www.googleapis.com/auth/admin.directory.device.chromeos',
    ],
    'cloud_identity': [
        'https://www.googleapis.com/auth/cloud-identity.groups',
    ],
    'cloud_search': [
        'https://www.googleapis.com/auth/cloud_search.query',
    ],
    'drive_activity': [
        'https://www.googleapis.com/auth/drive.activity.readonly',
    ],
    'people': [
        'https://www.googleapis.com/auth/contacts.readonly'
    ],
    'bigquery': [
        'https://www.googleapis.com/auth/bigquery'
    ],
}

# Combined scopes for all services
ALL_SCOPES = list(set(scope for scopes in SCOPES.values() for scope in scopes))


class OAuthManager:
    """Manages OAuth 2.0 authentication for Google APIs"""
    
    def __init__(self, config_dir: Optional[str] = None):
        self.config_dir = Path(config_dir) if config_dir else Path.home() / '.config' / 'gsuite-cli'
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.token_file = self.config_dir / 'token.json'
        self.credentials_file = self.config_dir / 'credentials.json'

    def get_client_config(self) -> Optional[tuple]:
        """
        Locates the OAuth 2.0 client configuration.
        Returns a tuple ('file', path_str) or ('config', dict), or None if not found.
        
        Checks in order:
        1. HERMES_GOOGLE_CLIENT_SECRET env var:
           - As an existing file path
           - As a JSON string containing client credentials
           - As a client_secret string paired with HERMES_GOOGLE_CLIENT_ID
        2. HERMES_CREDENTIALS_FILE or GOOGLE_APPLICATION_CREDENTIALS env var (if file exists)
        3. Local credentials file: ~/.config/gsuite-cli/credentials.json
        """
        # 1. HERMES_GOOGLE_CLIENT_SECRET env var
        secret_env = os.environ.get('HERMES_GOOGLE_CLIENT_SECRET')
        if secret_env:
            secret_env = secret_env.strip()
            # Check if it's a file path
            candidate_path = Path(secret_env)
            if candidate_path.is_file():
                return ('file', str(candidate_path.resolve()))
            # Check if it's a JSON string
            if secret_env.startswith('{') and secret_env.endswith('}'):
                try:
                    data = json.loads(secret_env)
                    return ('config', data)
                except Exception:
                    pass
            # Check if paired with client ID
            client_id = os.environ.get('HERMES_GOOGLE_CLIENT_ID')
            if client_id:
                client_config = {
                    "installed": {
                        "client_id": client_id.strip(),
                        "client_secret": secret_env,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://localhost"]
                    }
                }
                return ('config', client_config)

        # 2. HERMES_CREDENTIALS_FILE or GOOGLE_APPLICATION_CREDENTIALS
        for env_key in ('HERMES_CREDENTIALS_FILE', 'GOOGLE_APPLICATION_CREDENTIALS'):
            file_env = os.environ.get(env_key)
            if file_env and Path(file_env).is_file():
                return ('file', str(Path(file_env).resolve()))

        # 3. Default local credentials file in config directory
        if self.credentials_file.exists():
            return ('file', str(self.credentials_file))

        return None

    def has_client_config(self) -> bool:
        """Check whether OAuth client configuration is available"""
        return self.get_client_config() is not None
        
    def get_credentials(self, scopes: Optional[list] = None) -> Optional[Credentials]:
        """
        Get valid user credentials from storage or initiate OAuth flow
        
        Args:
            scopes: List of OAuth scopes. If None, uses all available scopes.
            
        Returns:
            Credentials object or None if authentication fails
        """
        scopes = scopes or ALL_SCOPES
        creds = None
        
        # Load existing credentials
        if self.token_file.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(self.token_file), scopes)
                logger.debug("Loaded existing credentials")
                
                # Verify that all requested scopes are actually present in the token
                # This fixes the 'insufficientPermissions' error when a user skips boxes in the UI
                if creds.valid and creds.scopes:
                    granted_scopes = set(creds.scopes)
                    requested_scopes = set(scopes)
                    if not requested_scopes.issubset(granted_scopes):
                        logger.info("Missing required scopes, initiating re-auth")
                        creds = None
            except Exception as e:
                logger.warning(f"Failed to load credentials: {e}")
                self.token_file.unlink(missing_ok=True)
        
        # If credentials are invalid, missing, or lack scopes, initiate OAuth flow
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    logger.debug("Refreshed expired credentials")
                    
                    # Re-verify scopes after refresh
                    granted_scopes = set(creds.scopes)
                    requested_scopes = set(scopes)
                    if not requested_scopes.issubset(granted_scopes):
                        logger.info("Refreshed token still missing scopes, re-authenticating")
                        creds = None
                except Exception as e:
                    logger.warning(f"Failed to refresh credentials: {e}")
                    creds = None
            
            if not creds:
                # Force local server to show the UI again
                creds = self._run_oauth_flow(scopes)
                if not creds:
                    return None
        
        # Save credentials for future use
        self._save_credentials(creds)
        return creds
    
    def _run_oauth_flow(self, scopes: list) -> Optional[Credentials]:
        """
        Run the OAuth 2.0 authorization flow
        
        Args:
            scopes: List of OAuth scopes
            
        Returns:
            Credentials object or None if user cancels
        """
        client_cfg = self.get_client_config()
        if not client_cfg:
            logger.error("OAuth client configuration not found.")
            logger.error(f"Please place credentials.json in: {self.credentials_file}")
            logger.error("Or set the HERMES_GOOGLE_CLIENT_SECRET environment variable.")
            return None
        
        cfg_type, cfg_value = client_cfg
        try:
            if cfg_type == 'file':
                flow = InstalledAppFlow.from_client_secrets_file(
                    cfg_value, scopes
                )
            else:
                flow = InstalledAppFlow.from_client_config(
                    cfg_value, scopes
                )
            # Force consent screen to ensure user can check missing boxes
            creds = flow.run_local_server(port=0, prompt='consent')
            logger.info("Authentication successful")
            return creds
        except Exception as e:
            logger.error(f"OAuth flow failed: {e}")
            return None
    
    def _save_credentials(self, creds: Credentials) -> None:
        """Save credentials to token file"""
        try:
            with open(self.token_file, 'w') as token:
                token.write(creds.to_json())
            logger.debug("Credentials saved successfully")
        except Exception as e:
            logger.error(f"Failed to save credentials: {e}")
    
    def revoke_credentials(self) -> bool:
        """Revoke stored credentials and delete local token file"""
        try:
            if self.token_file.exists():
                try:
                    creds = Credentials.from_authorized_user_file(str(self.token_file))
                    if creds and creds.token:
                        import requests
                        requests.post(
                            'https://oauth2.googleapis.com/revoke',
                            params={'token': creds.token},
                            headers={'content-type': 'application/x-www-form-urlencoded'},
                            timeout=5
                        )
                except Exception as e:
                    logger.debug(f"Online token revocation notice: {e}")
                
                self.token_file.unlink(missing_ok=True)
                logger.info("Credentials revoked successfully")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to revoke credentials: {e}")
            return False
    
    def is_authenticated(self) -> bool:
        """Check if user is authenticated"""
        if not self.token_file.exists():
            return False
        
        try:
            creds = Credentials.from_authorized_user_file(str(self.token_file), ALL_SCOPES)
            if not creds.valid and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    self._save_credentials(creds)
                except Exception:
                    return False
            return creds.valid
        except Exception:
            return False
    
    def get_auth_info(self) -> Dict[str, Any]:
        """Get authentication information"""
        if not self.is_authenticated():
            return {"authenticated": False}
        
        try:
            creds = Credentials.from_authorized_user_file(str(self.token_file), ALL_SCOPES)
            return {
                "authenticated": True,
                "valid": creds.valid,
                "expired": creds.expired,
                "token_expiry": creds.expiry.isoformat() if creds.expiry else None,
                "refresh_token": bool(creds.refresh_token),
                "scopes": creds.scopes or [],
            }
        except Exception as e:
            return {"authenticated": False, "error": str(e)}
    
    def build_service(self, service_name: str, version: str = 'v3'):
        creds = self.get_credentials(ALL_SCOPES)
        if not creds:
            return None
        
        try:
            kwargs = {
                'credentials': creds,
                'static_discovery': False,
            }
            if service_name == 'forms':
                kwargs['discoveryServiceUrl'] = 'https://forms.googleapis.com/$discovery/rest?version=v1'
                if not version or version == 'v3':
                    version = 'v1'
            elif service_name == 'admin':
                if not version or version == 'v3':
                    version = 'directory_v1'
            elif service_name in ('tasks', 'chat', 'docs', 'workspaceevents', 'script', 'cloudidentity', 'cloudsearch'):
                if not version or version == 'v3':
                    version = 'v1'
            elif service_name == 'sheets':
                if not version or version == 'v3':
                    version = 'v4'
            elif service_name in ('meet', 'driveactivity'):
                if not version or version == 'v3':
                    version = 'v2'
            service = build(service_name, version, **kwargs)
            logger.debug(f"Built {service_name} service client")
            return service
        except Exception as e:
            logger.error(f"Failed to build {service_name} service: {e}")
            # If we get a 403 or similar, the token might be bad despite our checks
            if "insufficient" in str(e).lower() or "permission" in str(e).lower():
                print_error(f"Authentication issue detected for {service_name}. Resetting token...")
                self.revoke_credentials()
            return None
