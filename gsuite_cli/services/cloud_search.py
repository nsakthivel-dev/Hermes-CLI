"""
Google Cloud Search API service integration for Hermes CLI
"""

import logging
from typing import List, Dict, Any, Optional
from googleapiclient.errors import HttpError

from ..auth.oauth import OAuthManager
from ..utils.formatters import print_error, print_info, print_success

logger = logging.getLogger(__name__)


class CloudSearchService:
    """Google Cloud Search API service wrapper"""

    def __init__(self, oauth_manager: OAuthManager, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.cache_manager = cache_manager
        self.service = None
        self._initialize_service()

    def _initialize_service(self) -> bool:
        """Initialize Cloud Search service client (v1)"""
        try:
            self.service = self.oauth_manager.build_service('cloudsearch', 'v1')
            return self.service is not None
        except Exception as e:
            logger.error(f"Failed to initialize Cloud Search service: {e}")
            return False

    def test_connection(self) -> Dict[str, Any]:
        """Test API connection to Google Cloud Search"""
        if not self.service:
            if not self._initialize_service():
                return {"status": "error", "message": "Failed to initialize Cloud Search service"}
        try:
            body = {"query": "test", "pageSize": 1}
            res = self.service.query().search(body=body).execute()
            return {
                "status": "success",
                "message": "Successfully connected to Google Cloud Search API",
                "results_count": len(res.get("results", []))
            }
        except HttpError as e:
            logger.warning(f"Cloud Search connection test warning: {e}")
            return {"status": "error", "message": str(e)}
        except Exception as e:
            logger.error(f"Error testing Cloud Search connection: {e}")
            return {"status": "error", "message": str(e)}

    def search(self, query: str, page_size: int = 25, page_token: Optional[str] = None) -> Dict[str, Any]:
        """Search organizational Google Workspace content"""
        if not self.service:
            return {"results": [], "nextPageToken": None}
        try:
            body: Dict[str, Any] = {
                "query": query,
                "pageSize": min(page_size, 100),
                "requestOptions": {
                    "searchApplicationId": "searchapplications/default"
                }
            }
            if page_token:
                body["pageToken"] = page_token
            res = self.service.query().search(body=body).execute()
            return {
                "results": res.get("results", []),
                "nextPageToken": res.get("nextPageToken")
            }
        except HttpError as e:
            logger.error(f"Failed to execute Cloud Search: {e}")
            print_error(f"Cloud Search error: {e}")
            return {"results": [], "nextPageToken": None, "error": str(e)}
