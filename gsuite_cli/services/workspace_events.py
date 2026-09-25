"""
Google Workspace Events API service integration for Hermes CLI
"""

import logging
from typing import List, Dict, Any, Optional
from googleapiclient.errors import HttpError

from ..auth.oauth import OAuthManager
from ..utils.formatters import print_error, print_info, print_success

logger = logging.getLogger(__name__)


class WorkspaceEventsService:
    """Google Workspace Events API service wrapper"""

    def __init__(self, oauth_manager: OAuthManager, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.cache_manager = cache_manager
        self.service = None
        self._initialize_service()

    def _initialize_service(self) -> bool:
        """Initialize Workspace Events API service client (v1)"""
        try:
            self.service = self.oauth_manager.build_service('workspaceevents', 'v1')
            return self.service is not None
        except Exception as e:
            logger.error(f"Failed to initialize Workspace Events service: {e}")
            return False

    def test_connection(self) -> Dict[str, Any]:
        """Test API connection to Workspace Events API"""
        if not self.service:
            if not self._initialize_service():
                return {"status": "error", "message": "Failed to initialize Workspace Events service"}
        try:
            res = self.service.subscriptions().list(pageSize=1).execute()
            return {
                "status": "success",
                "message": "Successfully connected to Google Workspace Events API",
                "subscriptions_found": len(res.get("subscriptions", []))
            }
        except Exception as e:
            logger.error(f"Error testing Workspace Events connection: {e}")
            return {"status": "error", "message": str(e)}

    def list_subscriptions(self, filter_str: Optional[str] = None, page_size: int = 50, page_token: Optional[str] = None) -> Dict[str, Any]:
        """List active event subscriptions"""
        if not self.service:
            return {"subscriptions": [], "nextPageToken": None}
        try:
            params: Dict[str, Any] = {"pageSize": min(page_size, 100)}
            if filter_str:
                params["filter"] = filter_str
            if page_token:
                params["pageToken"] = page_token
            res = self.service.subscriptions().list(**params).execute()
            return {
                "subscriptions": res.get("subscriptions", []),
                "nextPageToken": res.get("nextPageToken")
            }
        except HttpError as e:
            logger.error(f"Failed to list subscriptions: {e}")
            print_error(f"Workspace Events API error: {e}")
            return {"subscriptions": [], "nextPageToken": None, "error": str(e)}

    def get_subscription(self, subscription_name: str) -> Optional[Dict[str, Any]]:
        """Get details of an event subscription"""
        if not self.service:
            return None
        norm_name = subscription_name.strip()
        if not norm_name.startswith("subscriptions/"):
            norm_name = f"subscriptions/{norm_name}"
        try:
            return self.service.subscriptions().get(name=norm_name).execute()
        except HttpError as e:
            logger.error(f"Failed to get subscription {norm_name}: {e}")
            print_error(f"Subscription not found: {norm_name}")
            return None

    def create_subscription(
        self,
        target_resource: str,
        event_types: List[str],
        notification_endpoint: str
    ) -> Optional[Dict[str, Any]]:
        """Create a new event subscription"""
        if not self.service:
            return None
        try:
            body: Dict[str, Any] = {
                "targetResource": target_resource,
                "eventTypes": event_types,
                "notificationEndpoint": {
                    "pubsubTopic": notification_endpoint
                },
                "payloadOptions": {
                    "includeResource": True
                }
            }
            return self.service.subscriptions().create(body=body).execute()
        except HttpError as e:
            logger.error(f"Failed to create subscription: {e}")
            print_error(f"Failed to create subscription: {e}")
            return None

    def delete_subscription(self, subscription_name: str) -> bool:
        """Delete an event subscription"""
        if not self.service:
            return False
        norm_name = subscription_name.strip()
        if not norm_name.startswith("subscriptions/"):
            norm_name = f"subscriptions/{norm_name}"
        try:
            self.service.subscriptions().delete(name=norm_name).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to delete subscription {norm_name}: {e}")
            print_error(f"Failed to delete subscription: {e}")
            return False
