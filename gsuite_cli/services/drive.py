"""
Google Drive service integration for Hermes CLI
"""

import os
import io
import logging
from typing import List, Dict, Any, Optional
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from ..auth.oauth import OAuthManager
from ..utils.formatters import print_error, print_info, print_success

logger = logging.getLogger(__name__)


class DriveService:
    """Google Drive API service wrapper"""

    def __init__(self, oauth_manager: OAuthManager, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.cache_manager = cache_manager
        self.service = None
        self._initialize_service()

    def _initialize_service(self) -> bool:
        """Initialize Google Drive service client (v3)"""
        try:
            self.service = self.oauth_manager.build_service('drive', 'v3')
            return self.service is not None
        except Exception as e:
            logger.error(f"Failed to initialize Drive service: {e}")
            return False

    def test_connection(self) -> Dict[str, Any]:
        """Test Drive API connection and credentials"""
        if not self.service:
            if not self._initialize_service():
                return {"status": "error", "message": "Failed to initialize Drive API service"}
        try:
            res = self.service.files().list(pageSize=1, fields="files(id, name)").execute()
            return {
                "status": "success",
                "message": "Successfully connected to Google Drive API",
                "files_count": len(res.get("files", []))
            }
        except Exception as e:
            logger.error(f"Error testing Drive API connection: {e}")
            return {"status": "error", "message": str(e)}

    def get_profile(self) -> Dict[str, Any]:
        """Get Drive storage and user profile details"""
        if not self.service:
            return {"authenticated": False}
        try:
            about = self.service.about().get(fields="user, storageQuota").execute()
            user = about.get("user", {})
            quota = about.get("storageQuota", {})
            return {
                "authenticated": True,
                "user": user.get("displayName"),
                "email": user.get("emailAddress"),
                "limit": quota.get("limit"),
                "usage": quota.get("usage"),
                "usage_in_drive": quota.get("usageInDrive"),
            }
        except Exception as e:
            logger.error(f"Failed to fetch Drive profile: {e}")
            return {"authenticated": False, "error": str(e)}

    # =========================================================================
    # Files & Folders Listing
    # =========================================================================

    def list_files(
        self,
        query: Optional[str] = None,
        page_size: int = 50,
        page_token: Optional[str] = None,
        trashed: bool = False
    ) -> Dict[str, Any]:
        """List files matching query or default active files"""
        if not self.service:
            return {"files": [], "nextPageToken": None}
        try:
            q_parts = [f"trashed = {str(trashed).lower()}"]
            if query:
                q_parts.append(query)
            q = " and ".join(q_parts)
            fields = "nextPageToken, files(id, name, mimeType, modifiedTime, size, parents, shared)"
            res = self.service.files().list(
                q=q,
                pageSize=min(page_size, 100),
                pageToken=page_token,
                fields=fields
            ).execute()
            return {
                "files": res.get("files", []),
                "nextPageToken": res.get("nextPageToken")
            }
        except HttpError as e:
            logger.error(f"Failed to list Drive files: {e}")
            print_error(f"Drive API error: {e}")
            return {"files": [], "nextPageToken": None, "error": str(e)}

    def get_file(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get file metadata by file ID"""
        if not self.service:
            return None
        try:
            fields = "id, name, mimeType, description, size, modifiedTime, createdTime, owners, parents, webViewLink, shared, permissions"
            return self.service.files().get(fileId=file_id, fields=fields).execute()
        except HttpError as e:
            logger.error(f"Failed to get file {file_id}: {e}")
            print_error(f"File not found: {file_id}")
            return None

    def search_files(self, query: str, page_size: int = 25) -> List[Dict[str, Any]]:
        """Search files by name or full text"""
        escaped = query.replace("'", "\\'")
        q = f"name contains '{escaped}' or fullText contains '{escaped}'"
        res = self.list_files(query=q, page_size=page_size)
        return res.get("files", [])

    def list_folders(self, page_size: int = 50) -> List[Dict[str, Any]]:
        """List folders in Google Drive"""
        q = "mimeType = 'application/vnd.google-apps.folder'"
        res = self.list_files(query=q, page_size=page_size)
        return res.get("files", [])

    def list_shared(self, page_size: int = 50) -> List[Dict[str, Any]]:
        """List files shared with the user"""
        q = "sharedWithMe = true"
        res = self.list_files(query=q, page_size=page_size)
        return res.get("files", [])

    # =========================================================================
    # File Operations: Create, Upload, Download, Copy, Move, Rename
    # =========================================================================

    def create_folder(self, name: str, parent_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Create a new folder"""
        if not self.service:
            return None
        try:
            metadata: Dict[str, Any] = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder"
            }
            if parent_id:
                metadata["parents"] = [parent_id]
            return self.service.files().create(body=metadata, fields="id, name, mimeType").execute()
        except HttpError as e:
            logger.error(f"Failed to create folder {name}: {e}")
            print_error(f"Failed to create folder: {e}")
            return None

    def create_file(
        self,
        name: str,
        mime_type: str = "text/plain",
        content: str = "",
        parent_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Create an empty or text file"""
        if not self.service:
            return None
        try:
            metadata: Dict[str, Any] = {"name": name, "mimeType": mime_type}
            if parent_id:
                metadata["parents"] = [parent_id]
            from googleapiclient.http import MediaInMemoryUpload
            media = MediaInMemoryUpload(content.encode('utf-8'), mimetype=mime_type, resumable=False)
            return self.service.files().create(body=metadata, media_body=media, fields="id, name, mimeType").execute()
        except HttpError as e:
            logger.error(f"Failed to create file {name}: {e}")
            print_error(f"Failed to create file: {e}")
            return None

    def upload_file(
        self,
        file_path: str,
        name: Optional[str] = None,
        folder_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Upload a local file to Google Drive"""
        if not self.service:
            return None
        if not os.path.exists(file_path):
            print_error(f"Local file not found: {file_path}")
            return None
        try:
            filename = name or os.path.basename(file_path)
            metadata: Dict[str, Any] = {"name": filename}
            if folder_id:
                metadata["parents"] = [folder_id]
            media = MediaFileUpload(file_path, resumable=True)
            return self.service.files().create(
                body=metadata,
                media_body=media,
                fields="id, name, mimeType, webViewLink"
            ).execute()
        except HttpError as e:
            logger.error(f"Failed to upload file {file_path}: {e}")
            print_error(f"Upload failed: {e}")
            return None

    def download_file(self, file_id: str, destination_path: str) -> bool:
        """Download a file from Google Drive to local disk"""
        if not self.service:
            return False
        try:
            request = self.service.files().get_media(fileId=file_id)
            with open(destination_path, "wb") as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
            return True
        except HttpError as e:
            logger.error(f"Failed to download file {file_id}: {e}")
            print_error(f"Download failed: {e}")
            return False

    def update_file(self, file_id: str, name: Optional[str] = None, description: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Update file metadata (name, description)"""
        if not self.service:
            return None
        try:
            body = {}
            if name:
                body["name"] = name
            if description is not None:
                body["description"] = description
            return self.service.files().update(fileId=file_id, body=body, fields="id, name, description").execute()
        except HttpError as e:
            logger.error(f"Failed to update file {file_id}: {e}")
            print_error(f"Update failed: {e}")
            return None

    def rename_file(self, file_id: str, new_name: str) -> Optional[Dict[str, Any]]:
        """Rename a file"""
        return self.update_file(file_id, name=new_name)

    def move_file(self, file_id: str, folder_id: str) -> Optional[Dict[str, Any]]:
        """Move file to another folder"""
        if not self.service:
            return None
        try:
            # Retrieve existing parents
            file_meta = self.service.files().get(fileId=file_id, fields="parents").execute()
            previous_parents = ",".join(file_meta.get("parents", []))
            return self.service.files().update(
                fileId=file_id,
                addParents=folder_id,
                removeParents=previous_parents,
                fields="id, name, parents"
            ).execute()
        except HttpError as e:
            logger.error(f"Failed to move file {file_id}: {e}")
            print_error(f"Move failed: {e}")
            return None

    def copy_file(self, file_id: str, new_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Create a copy of a file"""
        if not self.service:
            return None
        try:
            body = {}
            if new_name:
                body["name"] = new_name
            return self.service.files().copy(fileId=file_id, body=body, fields="id, name, mimeType").execute()
        except HttpError as e:
            logger.error(f"Failed to copy file {file_id}: {e}")
            print_error(f"Copy failed: {e}")
            return None

    def trash_file(self, file_id: str) -> bool:
        """Move file to trash"""
        if not self.service:
            return False
        try:
            self.service.files().update(fileId=file_id, body={"trashed": True}).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to trash file {file_id}: {e}")
            print_error(f"Trash failed: {e}")
            return False

    def restore_file(self, file_id: str) -> bool:
        """Restore file from trash"""
        if not self.service:
            return False
        try:
            self.service.files().update(fileId=file_id, body={"trashed": False}).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to restore file {file_id}: {e}")
            print_error(f"Restore failed: {e}")
            return False

    def delete_file(self, file_id: str) -> bool:
        """Permanently delete a file from Drive"""
        if not self.service:
            return False
        try:
            self.service.files().delete(fileId=file_id).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to permanently delete file {file_id}: {e}")
            print_error(f"Delete failed: {e}")
            return False

    # =========================================================================
    # Permissions, Comments & Revisions
    # =========================================================================

    def list_permissions(self, file_id: str) -> List[Dict[str, Any]]:
        """List permissions for a file"""
        if not self.service:
            return []
        try:
            res = self.service.permissions().list(fileId=file_id, fields="permissions(id, type, role, emailAddress, displayName)").execute()
            return res.get("permissions", [])
        except HttpError as e:
            logger.error(f"Failed to list permissions for {file_id}: {e}")
            print_error(f"Failed to list permissions: {e}")
            return []

    def add_permission(self, file_id: str, email: str, role: str = "reader", perm_type: str = "user") -> Optional[Dict[str, Any]]:
        """Add permission to a file"""
        if not self.service:
            return None
        try:
            body = {"role": role, "type": perm_type, "emailAddress": email}
            return self.service.permissions().create(fileId=file_id, body=body, fields="id, role, type, emailAddress").execute()
        except HttpError as e:
            logger.error(f"Failed to add permission on {file_id}: {e}")
            print_error(f"Failed to add permission: {e}")
            return None

    def remove_permission(self, file_id: str, permission_id: str) -> bool:
        """Remove a permission from a file"""
        if not self.service:
            return False
        try:
            self.service.permissions().delete(fileId=file_id, permissionId=permission_id).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to remove permission {permission_id} from {file_id}: {e}")
            print_error(f"Failed to remove permission: {e}")
            return False

    def list_comments(self, file_id: str) -> List[Dict[str, Any]]:
        """List comments on a file"""
        if not self.service:
            return []
        try:
            res = self.service.comments().list(fileId=file_id, fields="comments(id, content, author, createdTime, resolved)").execute()
            return res.get("comments", [])
        except HttpError as e:
            logger.error(f"Failed to list comments on {file_id}: {e}")
            return []

    def list_revisions(self, file_id: str) -> List[Dict[str, Any]]:
        """List file revisions"""
        if not self.service:
            return []
        try:
            res = self.service.revisions().list(fileId=file_id, fields="revisions(id, modifiedTime, lastModifyingUser, size)").execute()
            return res.get("revisions", [])
        except HttpError as e:
            logger.error(f"Failed to list revisions for {file_id}: {e}")
            return []
