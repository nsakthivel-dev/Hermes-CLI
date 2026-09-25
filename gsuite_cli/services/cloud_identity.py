"""
Google Cloud Identity API service integration for Hermes CLI
"""

import logging
from typing import List, Dict, Any, Optional
from googleapiclient.errors import HttpError

from ..auth.oauth import OAuthManager
from ..utils.formatters import print_error, print_info, print_success

logger = logging.getLogger(__name__)


class CloudIdentityService:
    """Google Cloud Identity API service wrapper"""

    def __init__(self, oauth_manager: OAuthManager, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.cache_manager = cache_manager
        self.service = None
        self._initialize_service()

    def _initialize_service(self) -> bool:
        """Initialize Cloud Identity API service client (v1)"""
        try:
            self.service = self.oauth_manager.build_service('cloudidentity', 'v1')
            return self.service is not None
        except Exception as e:
            logger.error(f"Failed to initialize Cloud Identity service: {e}")
            return False

    def test_connection(self) -> Dict[str, Any]:
        """Test Cloud Identity API connection"""
        if not self.service:
            if not self._initialize_service():
                return {"status": "error", "message": "Failed to initialize Cloud Identity service"}
        try:
            res = self.service.groups().search(pageSize=1).execute()
            return {
                "status": "success",
                "message": "Successfully connected to Google Cloud Identity API",
                "groups_count": len(res.get("groups", []))
            }
        except Exception as e:
            logger.error(f"Error testing Cloud Identity connection: {e}")
            return {"status": "error", "message": str(e)}

    # =========================================================================
    # Groups
    # =========================================================================

    def list_groups(self, page_size: int = 50, page_token: Optional[str] = None) -> Dict[str, Any]:
        """Search/list identity groups"""
        if not self.service:
            return {"groups": [], "nextPageToken": None}
        try:
            res = self.service.groups().search(pageSize=min(page_size, 100), pageToken=page_token).execute()
            return {
                "groups": res.get("groups", []),
                "nextPageToken": res.get("nextPageToken")
            }
        except HttpError as e:
            logger.error(f"Failed to list identity groups: {e}")
            print_error(f"Cloud Identity API error: {e}")
            return {"groups": [], "nextPageToken": None, "error": str(e)}

    def get_group(self, group_name: str) -> Optional[Dict[str, Any]]:
        """Get group details by name (e.g. groups/123)"""
        if not self.service:
            return None
        norm_name = group_name.strip()
        if not norm_name.startswith("groups/"):
            norm_name = f"groups/{norm_name}"
        try:
            return self.service.groups().get(name=norm_name).execute()
        except HttpError as e:
            logger.error(f"Failed to get identity group {norm_name}: {e}")
            print_error(f"Identity group not found: {norm_name}")
            return None

    def search_groups(self, query: str, page_size: int = 25) -> Dict[str, Any]:
        """Search identity groups with query"""
        if not self.service:
            return {"groups": []}
        try:
            q = f"displayName:'{query}'"
            res = self.service.groups().search(query=q, pageSize=page_size).execute()
            return res if isinstance(res, dict) else {"groups": res}
        except HttpError as e:
            logger.error(f"Failed to search identity groups: {e}")
            return {"groups": []}

    def create_group(self, display_name: str, email: str, description: str = "") -> Optional[Dict[str, Any]]:
        """Create a Cloud Identity group"""
        if not self.service:
            return None
        try:
            body = {
                "displayName": display_name,
                "description": description,
                "groupKey": {"id": email},
                "labels": {"cloudidentity.googleapis.com/groups.discussion_forum": ""}
            }
            return self.service.groups().create(body=body).execute()
        except HttpError as e:
            logger.error(f"Failed to create identity group: {e}")
            print_error(f"Failed to create group: {e}")
            return None

    def delete_group(self, group_name: str) -> bool:
        """Delete an identity group"""
        if not self.service:
            return False
        norm_name = group_name.strip()
        if not norm_name.startswith("groups/"):
            norm_name = f"groups/{norm_name}"
        try:
            self.service.groups().delete(name=norm_name).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to delete identity group {norm_name}: {e}")
            print_error(f"Failed to delete group: {e}")
            return False

    # =========================================================================
    # Memberships
    # =========================================================================

    def list_members(self, group_name: str, page_size: int = 50) -> Dict[str, Any]:
        """List members of an identity group"""
        if not self.service:
            return {"memberships": []}
        norm_name = group_name.strip()
        if not norm_name.startswith("groups/"):
            norm_name = f"groups/{norm_name}"
        try:
            res = self.service.groups().memberships().list(parent=norm_name, pageSize=page_size).execute()
            return res if isinstance(res, dict) else {"memberships": res}
        except HttpError as e:
            logger.error(f"Failed to list members in {norm_name}: {e}")
            return {"memberships": []}

    def add_member(self, group_name: str, user_email: str, role: str = "MEMBER") -> Optional[Dict[str, Any]]:
        """Add member to group"""
        if not self.service:
            return None
        norm_name = group_name.strip()
        if not norm_name.startswith("groups/"):
            norm_name = f"groups/{norm_name}"
        try:
            body = {
                "preferredMemberKey": {"id": user_email},
                "roles": [{"name": role}]
            }
            return self.service.groups().memberships().create(parent=norm_name, body=body).execute()
        except HttpError as e:
            logger.error(f"Failed to add member {user_email} to {norm_name}: {e}")
            print_error(f"Failed to add member: {e}")
            return None

    def remove_member(self, membership_name: str) -> bool:
        """Remove member by full membership name"""
        if not self.service:
            return False
        try:
            self.service.groups().memberships().delete(name=membership_name).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to remove member {membership_name}: {e}")
            print_error(f"Failed to remove member: {e}")
            return False

    # =========================================================================
    # Devices
    # =========================================================================

    def list_devices(self, page_size: int = 50) -> List[Dict[str, Any]]:
        """List managed devices in Cloud Identity"""
        if not self.service:
            return []
        try:
            res = self.service.devices().list(pageSize=min(page_size, 100)).execute()
            return res.get("devices", [])
        except HttpError as e:
            logger.error(f"Failed to list identity devices: {e}")
            return []
