"""
Google Admin SDK Directory API service integration for Hermes CLI
"""

import logging
from typing import List, Dict, Any, Optional
from googleapiclient.errors import HttpError

from ..auth.oauth import OAuthManager
from ..utils.formatters import print_error, print_info, print_success

logger = logging.getLogger(__name__)


class AdminService:
    """Google Admin SDK Directory API service wrapper"""

    def __init__(self, oauth_manager: OAuthManager, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.cache_manager = cache_manager
        self.service = None
        self._initialize_service()

    def _initialize_service(self) -> bool:
        """Initialize Google Admin SDK Directory API service client"""
        try:
            self.service = self.oauth_manager.build_service('admin', 'directory_v1')
            return self.service is not None
        except Exception as e:
            logger.error(f"Failed to initialize Admin Directory service: {e}")
            return False

    def test_connection(self) -> Dict[str, Any]:
        """Test API connection to Google Admin SDK"""
        if not self.service:
            if not self._initialize_service():
                return {"status": "error", "message": "Failed to initialize Admin SDK service"}
        try:
            res = self.service.users().list(customer='my_customer', maxResults=1).execute()
            return {
                "status": "success",
                "message": "Successfully connected to Google Admin SDK API",
                "users_found": len(res.get("users", []))
            }
        except HttpError as e:
            logger.warning(f"Admin SDK connection test warning: {e}")
            if e.resp.status == 403:
                return {"status": "error", "message": "Account does not have administrator privileges for Directory API"}
            return {"status": "error", "message": str(e)}
        except Exception as e:
            logger.error(f"Error testing Admin SDK connection: {e}")
            return {"status": "error", "message": str(e)}

    # =========================================================================
    # Users Management
    # =========================================================================

    def list_users(self, query: Optional[str] = None, max_results: int = 50, page_token: Optional[str] = None) -> Dict[str, Any]:
        """List users in the domain"""
        if not self.service:
            return {"users": [], "nextPageToken": None}
        try:
            params: Dict[str, Any] = {
                "customer": "my_customer",
                "maxResults": min(max_results, 100)
            }
            if query:
                params["query"] = query
            if page_token:
                params["pageToken"] = page_token
            res = self.service.users().list(**params).execute()
            return {
                "users": res.get("users", []),
                "nextPageToken": res.get("nextPageToken")
            }
        except HttpError as e:
            logger.error(f"Failed to list admin users: {e}")
            print_error(f"Admin SDK error: {e}")
            return {"users": [], "nextPageToken": None, "error": str(e)}

    def get_user(self, user_key: str) -> Optional[Dict[str, Any]]:
        """Get user details by email or unique ID"""
        if not self.service:
            return None
        try:
            return self.service.users().get(userKey=user_key).execute()
        except HttpError as e:
            logger.error(f"Failed to get admin user {user_key}: {e}")
            print_error(f"Admin user not found: {user_key}")
            return None

    def search_users(self, query: str, max_results: int = 25) -> List[Dict[str, Any]]:
        """Search users matching query"""
        res = self.list_users(query=query, max_results=max_results)
        return res.get("users", [])

    def create_user(self, primary_email: str, given_name: str, family_name: str, password: str) -> Optional[Dict[str, Any]]:
        """Create a new domain user"""
        if not self.service:
            return None
        try:
            body = {
                "primaryEmail": primary_email,
                "name": {
                    "givenName": given_name,
                    "familyName": family_name
                },
                "password": password
            }
            return self.service.users().insert(body=body).execute()
        except HttpError as e:
            logger.error(f"Failed to create user {primary_email}: {e}")
            print_error(f"Failed to create user: {e}")
            return None

    def update_user(self, user_key: str, given_name: Optional[str] = None, family_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Update user name details"""
        if not self.service:
            return None
        try:
            body: Dict[str, Any] = {}
            if given_name or family_name:
                body["name"] = {}
                if given_name:
                    body["name"]["givenName"] = given_name
                if family_name:
                    body["name"]["familyName"] = family_name
            return self.service.users().patch(userKey=user_key, body=body).execute()
        except HttpError as e:
            logger.error(f"Failed to update user {user_key}: {e}")
            print_error(f"Failed to update user: {e}")
            return None

    def suspend_user(self, user_key: str, suspend: bool = True) -> bool:
        """Suspend or unsuspend user"""
        if not self.service:
            return False
        try:
            if hasattr(self.service.users(), 'update'):
                try:
                    self.service.users().update(userKey=user_key, body={"suspended": suspend}).execute()
                    return True
                except Exception:
                    pass
            self.service.users().patch(userKey=user_key, body={"suspended": suspend}).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to set user suspension state {user_key}: {e}")
            print_error(f"Failed to change user suspension: {e}")
            return False

    def unsuspend_user(self, user_key: str) -> bool:
        """Unsuspend user account"""
        return self.suspend_user(user_key, suspend=False)

    def delete_user(self, user_key: str) -> bool:
        """Delete user account"""
        if not self.service:
            return False
        try:
            self.service.users().delete(userKey=user_key).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to delete user {user_key}: {e}")
            print_error(f"Failed to delete user: {e}")
            return False

    # =========================================================================
    # Groups Management
    # =========================================================================

    def list_groups(self, max_results: int = 50, page_token: Optional[str] = None) -> Dict[str, Any]:
        """List groups in the domain"""
        if not self.service:
            return {"groups": [], "nextPageToken": None}
        try:
            res = self.service.groups().list(customer="my_customer", maxResults=min(max_results, 100), pageToken=page_token).execute()
            return {
                "groups": res.get("groups", []),
                "nextPageToken": res.get("nextPageToken")
            }
        except HttpError as e:
            logger.error(f"Failed to list admin groups: {e}")
            return {"groups": [], "nextPageToken": None, "error": str(e)}

    def get_group(self, group_key: str) -> Optional[Dict[str, Any]]:
        """Get group details"""
        if not self.service:
            return None
        try:
            return self.service.groups().get(groupKey=group_key).execute()
        except HttpError as e:
            logger.error(f"Failed to get group {group_key}: {e}")
            return None

    def create_group(self, email: str, name: str, description: str = "") -> Optional[Dict[str, Any]]:
        """Create a new group"""
        if not self.service:
            return None
        try:
            body = {"email": email, "name": name, "description": description}
            return self.service.groups().insert(body=body).execute()
        except HttpError as e:
            logger.error(f"Failed to create group {email}: {e}")
            print_error(f"Failed to create group: {e}")
            return None

    def delete_group(self, group_key: str) -> bool:
        """Delete a group"""
        if not self.service:
            return False
        try:
            self.service.groups().delete(groupKey=group_key).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to delete group {group_key}: {e}")
            print_error(f"Failed to delete group: {e}")
            return False

    def add_group_member(self, group_key: str, email: str, role: str = "MEMBER") -> Optional[Dict[str, Any]]:
        """Add member to group"""
        if not self.service:
            return None
        try:
            body = {"email": email, "role": role}
            return self.service.members().insert(groupKey=group_key, body=body).execute()
        except HttpError as e:
            logger.error(f"Failed to add member {email} to group {group_key}: {e}")
            print_error(f"Failed to add member: {e}")
            return None

    def remove_group_member(self, group_key: str, email: str) -> bool:
        """Remove member from group"""
        if not self.service:
            return False
        try:
            self.service.members().delete(groupKey=group_key, memberKey=email).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to remove member {email} from group {group_key}: {e}")
            print_error(f"Failed to remove member: {e}")
            return False

    # =========================================================================
    # Devices & Domains
    # =========================================================================

    def list_devices(self, max_results: int = 50) -> List[Dict[str, Any]]:
        """List ChromeOS devices"""
        if not self.service:
            return []
        try:
            res = self.service.chromeosdevices().list(customerId="my_customer", maxResults=min(max_results, 100)).execute()
            return res.get("chromeosdevices", [])
        except HttpError as e:
            logger.error(f"Failed to list devices: {e}")
            return []

    def list_domains(self) -> List[Dict[str, Any]]:
        """List domains"""
        if not self.service:
            return []
        try:
            res = self.service.domains().list(customer="my_customer").execute()
            return res.get("domains", [])
        except HttpError as e:
            logger.error(f"Failed to list domains: {e}")
            return []
