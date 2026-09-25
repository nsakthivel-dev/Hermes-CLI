"""
Google Drive Activity API service integration for Hermes CLI
"""

import logging
from typing import List, Dict, Any, Optional
from googleapiclient.errors import HttpError

from ..auth.oauth import OAuthManager
from ..utils.formatters import print_error, print_info, print_success

logger = logging.getLogger(__name__)


class DriveActivityService:
    """Google Drive Activity API service wrapper"""

    def __init__(self, oauth_manager: OAuthManager, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.cache_manager = cache_manager
        self.service = None
        self._initialize_service()

    def _initialize_service(self) -> bool:
        """Initialize Drive Activity API service client (v2)"""
        try:
            self.service = self.oauth_manager.build_service('driveactivity', 'v2')
            return self.service is not None
        except Exception as e:
            logger.error(f"Failed to initialize Drive Activity service: {e}")
            return False

    def test_connection(self) -> Dict[str, Any]:
        """Test API connection to Google Drive Activity API"""
        if not self.service:
            if not self._initialize_service():
                return {"status": "error", "message": "Failed to initialize Drive Activity service"}
        try:
            body = {"pageSize": 1}
            res = self.service.activity().query(body=body).execute()
            return {
                "status": "success",
                "message": "Successfully connected to Google Drive Activity API",
                "activities_found": len(res.get("activities", []))
            }
        except Exception as e:
            logger.error(f"Error testing Drive Activity connection: {e}")
            return {"status": "error", "message": str(e)}

    def query_activity(
        self,
        item_name: Optional[str] = None,
        page_size: int = 25,
        page_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Query drive activity for a specific file or user/drive root"""
        if not self.service:
            return {"activities": [], "nextPageToken": None}
        try:
            body: Dict[str, Any] = {"pageSize": min(page_size, 50)}
            if item_name:
                norm_item = item_name.strip()
                if not norm_item.startswith("items/"):
                    norm_item = f"items/{norm_item}"
                body["itemName"] = norm_item
            if page_token:
                body["pageToken"] = page_token
            res = self.service.activity().query(body=body).execute()
            return {
                "activities": res.get("activities", []),
                "nextPageToken": res.get("nextPageToken")
            }
        except HttpError as e:
            logger.error(f"Failed to query Drive Activity: {e}")
            print_error(f"Drive Activity error: {e}")
            return {"activities": [], "nextPageToken": None, "error": str(e)}
