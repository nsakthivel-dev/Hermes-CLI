"""
Google Apps Script API service integration for Hermes CLI
"""

import logging
from typing import List, Dict, Any, Optional
from googleapiclient.errors import HttpError

from ..auth.oauth import OAuthManager
from ..utils.formatters import print_error, print_info, print_success

logger = logging.getLogger(__name__)


class AppsScriptService:
    """Google Apps Script API service wrapper"""

    def __init__(self, oauth_manager: OAuthManager, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.cache_manager = cache_manager
        self.service = None
        self.drive_service = None
        self._initialize_service()

    def _initialize_service(self) -> bool:
        """Initialize Google Apps Script service client (v1) and Drive client"""
        try:
            self.service = self.oauth_manager.build_service('script', 'v1')
            self.drive_service = self.oauth_manager.build_service('drive', 'v3')
            return self.service is not None
        except Exception as e:
            logger.error(f"Failed to initialize Apps Script service: {e}")
            return False

    def test_connection(self) -> Dict[str, Any]:
        """Test API connection to Google Apps Script"""
        if not self.service:
            if not self._initialize_service():
                return {"status": "error", "message": "Failed to initialize Apps Script service"}
        try:
            # Drive query for scripts
            if self.drive_service:
                res = self.drive_service.files().list(
                    q="mimeType = 'application/vnd.google-apps.script' and trashed = false",
                    pageSize=1,
                    fields="files(id, name)"
                ).execute()
                count = len(res.get("files", []))
            else:
                count = 0
            return {
                "status": "success",
                "message": "Successfully connected to Google Apps Script API",
                "scripts_found": count
            }
        except Exception as e:
            logger.error(f"Error testing Apps Script connection: {e}")
            return {"status": "error", "message": str(e)}

    # =========================================================================
    # Projects
    # =========================================================================

    def list_projects(self, page_size: int = 50) -> List[Dict[str, Any]]:
        """List script projects via Drive search"""
        if not self.drive_service:
            return []
        try:
            res = self.drive_service.files().list(
                q="mimeType = 'application/vnd.google-apps.script' and trashed = false",
                pageSize=min(page_size, 100),
                fields="files(id, name, modifiedTime, createdTime)"
            ).execute()
            return res.get("files", [])
        except HttpError as e:
            logger.error(f"Failed to list script projects: {e}")
            print_error(f"Failed to list script projects: {e}")
            return []

    def get_project(self, script_id: str) -> Optional[Dict[str, Any]]:
        """Get script project metadata and content"""
        if not self.service:
            return None
        try:
            meta = self.service.projects().get(scriptId=script_id).execute()
            content = self.service.projects().getContent(scriptId=script_id).execute()
            meta["files"] = content.get("files", [])
            return meta
        except HttpError as e:
            logger.error(f"Failed to get script project {script_id}: {e}")
            print_error(f"Script project not found: {script_id}")
            return None

    def create_project(self, title: str, parent_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Create a new Apps Script project"""
        if not self.service:
            return None
        try:
            body: Dict[str, Any] = {"title": title}
            if parent_id:
                body["parentId"] = parent_id
            return self.service.projects().create(body=body).execute()
        except HttpError as e:
            logger.error(f"Failed to create script project {title}: {e}")
            print_error(f"Failed to create script project: {e}")
            return None

    def update_content(self, script_id: str, files: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Update script project files/content"""
        if not self.service:
            return None
        try:
            body = {"files": files}
            return self.service.projects().updateContent(scriptId=script_id, body=body).execute()
        except HttpError as e:
            logger.error(f"Failed to update script content {script_id}: {e}")
            print_error(f"Failed to update script content: {e}")
            return None

    # =========================================================================
    # Execution
    # =========================================================================

    def run_script(self, script_id: str, function_name: str, parameters: Optional[List[Any]] = None) -> Dict[str, Any]:
        """Execute a function in a script project"""
        if not self.service:
            return {"error": "Service unavailable"}
        try:
            body: Dict[str, Any] = {
                "function": function_name,
                "parameters": parameters or [],
                "devMode": True
            }
            resp = self.service.scripts().run(scriptId=script_id, body=body).execute()
            if isinstance(resp, dict) and "status" not in resp:
                resp["status"] = "success" if not resp.get("error") else "error"
            return resp
        except HttpError as e:
            logger.error(f"Failed to execute script {script_id}: {e}")
            print_error(f"Script execution error: {e}")
            return {"status": "error", "error": str(e)}

    # =========================================================================
    # Versions & Deployments
    # =========================================================================

    def list_versions(self, script_id: str, page_size: int = 25) -> Dict[str, Any]:
        """List versions of a script project"""
        if not self.service:
            return {"versions": []}
        try:
            res = self.service.projects().versions().list(scriptId=script_id, pageSize=page_size).execute()
            return res if isinstance(res, dict) else {"versions": res}
        except HttpError as e:
            logger.error(f"Failed to list script versions for {script_id}: {e}")
            return {"versions": []}

    def create_version(self, script_id: str, description: str = "") -> Optional[Dict[str, Any]]:
        """Create a new version of a script project"""
        if not self.service:
            return None
        try:
            body = {"description": description}
            return self.service.projects().versions().create(scriptId=script_id, body=body).execute()
        except HttpError as e:
            logger.error(f"Failed to create version for {script_id}: {e}")
            print_error(f"Failed to create version: {e}")
            return None

    def list_deployments(self, script_id: str) -> Dict[str, Any]:
        """List deployments of a script project"""
        if not self.service:
            return {"deployments": []}
        try:
            res = self.service.projects().deployments().list(scriptId=script_id).execute()
            return res if isinstance(res, dict) else {"deployments": res}
        except HttpError as e:
            logger.error(f"Failed to list deployments for {script_id}: {e}")
            return {"deployments": []}

    def create_deployment(self, script_id: str, version_number: int, description: str = "") -> Optional[Dict[str, Any]]:
        """Create a deployment of a script version"""
        if not self.service:
            return None
        try:
            body = {
                "versionNumber": version_number,
                "description": description
            }
            return self.service.projects().deployments().create(scriptId=script_id, body=body).execute()
        except HttpError as e:
            logger.error(f"Failed to create deployment for {script_id}: {e}")
            print_error(f"Failed to create deployment: {e}")
            return None

    def delete_deployment(self, script_id: str, deployment_id: str) -> bool:
        """Delete a script deployment"""
        if not self.service:
            return False
        try:
            self.service.projects().deployments().delete(scriptId=script_id, deploymentId=deployment_id).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to delete deployment {deployment_id}: {e}")
            print_error(f"Failed to delete deployment: {e}")
            return False
