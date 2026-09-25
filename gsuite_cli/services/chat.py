"""
Google Chat service integration for Hermes CLI
"""

import logging
from typing import List, Dict, Any, Optional
from googleapiclient.errors import HttpError

from ..auth.oauth import OAuthManager
from ..utils.formatters import print_error, print_info, print_success

logger = logging.getLogger(__name__)


class ChatService:
    """Google Chat API service wrapper"""

    def __init__(self, oauth_manager: OAuthManager, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.cache_manager = cache_manager
        self.service = None
        self._initialize_service()

    def _initialize_service(self) -> bool:
        """Initialize the Google Chat service client"""
        try:
            self.service = self.oauth_manager.build_service('chat', 'v1')
            return self.service is not None
        except Exception as e:
            logger.error(f"Failed to initialize Chat service: {e}")
            return False

    # =========================================================================
    # Helpers & Normalization
    # =========================================================================

    @staticmethod
    def normalize_space_name(space_id: str) -> str:
        """Ensure space ID has the 'spaces/' prefix"""
        if not space_id:
            return ""
        space_id = str(space_id).strip()
        if not space_id.startswith("spaces/"):
            return f"spaces/{space_id}"
        return space_id

    @staticmethod
    def normalize_message_name(message_id: str, space_id: Optional[str] = None) -> str:
        """
        Ensure message ID is fully qualified as 'spaces/<SPACE_ID>/messages/<MSG_ID>'
        """
        if not message_id:
            return ""
        message_id = str(message_id).strip()
        if "/" in message_id:
            return message_id
        if space_id:
            space_norm = ChatService.normalize_space_name(space_id)
            return f"{space_norm}/messages/{message_id}"
        return message_id

    # =========================================================================
    # Connection & Status
    # =========================================================================

    def test_connection(self) -> Dict[str, Any]:
        """Test API connectivity and verify authentication"""
        if not self.service:
            if not self._initialize_service():
                return {"status": "error", "message": "Failed to initialize Chat API service"}
        try:
            # Attempt a minimal read
            response = self.service.spaces().list(pageSize=1).execute()
            spaces_count = len(response.get('spaces', []))
            return {
                "status": "success",
                "message": "Successfully connected to Google Chat API",
                "spaces_found": spaces_count,
            }
        except HttpError as e:
            logger.error(f"Google Chat API error during test: {e}")
            return {"status": "error", "message": str(e), "code": getattr(e, 'resp', {}).get('status')}
        except Exception as e:
            logger.error(f"Error testing Chat API connection: {e}")
            return {"status": "error", "message": str(e)}

    def get_profile(self) -> Dict[str, Any]:
        """Get profile and auth status for Google Chat"""
        auth_info = self.oauth_manager.get_auth_info()
        connection = self.test_connection()
        return {
            "authenticated": auth_info.get("authenticated", False),
            "token_expiry": auth_info.get("token_expiry"),
            "connection_status": connection.get("status"),
            "service": "Google Chat API v1",
        }

    # =========================================================================
    # Spaces Management
    # =========================================================================

    def list_spaces(self, page_size: int = 50, page_token: Optional[str] = None) -> Dict[str, Any]:
        """List spaces that the user belongs to"""
        if not self.service:
            return {"spaces": [], "nextPageToken": None}
        try:
            params = {"pageSize": min(page_size, 100)}
            if page_token:
                params["pageToken"] = page_token
            result = self.service.spaces().list(**params).execute()
            return {
                "spaces": result.get("spaces", []),
                "nextPageToken": result.get("nextPageToken"),
            }
        except HttpError as e:
            logger.error(f"Failed to list chat spaces: {e}")
            print_error(f"Chat API error: {e}")
            return {"spaces": [], "nextPageToken": None, "error": str(e)}

    def get_space(self, space_name: str) -> Optional[Dict[str, Any]]:
        """Get details of a specific chat space"""
        if not self.service:
            return None
        norm_name = self.normalize_space_name(space_name)
        try:
            return self.service.spaces().get(name=norm_name).execute()
        except HttpError as e:
            logger.error(f"Failed to get chat space {norm_name}: {e}")
            print_error(f"Chat space not found: {norm_name}")
            return None

    def create_space(
        self,
        display_name: str,
        space_type: str = "SPACE",
        description: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Create a new chat space"""
        if not self.service:
            return None
        try:
            body: Dict[str, Any] = {
                "displayName": display_name,
                "spaceType": space_type.upper(),
            }
            if description:
                body["spaceDetails"] = {"description": description}
            return self.service.spaces().create(body=body).execute()
        except HttpError as e:
            logger.error(f"Failed to create chat space '{display_name}': {e}")
            print_error(f"Failed to create space: {e}")
            return None

    # =========================================================================
    # Messages & Threads
    # =========================================================================

    def list_messages(
        self,
        space_name: str,
        page_size: int = 25,
        page_token: Optional[str] = None,
        filter_str: Optional[str] = None
    ) -> Dict[str, Any]:
        """List messages in a chat space"""
        if not self.service:
            return {"messages": [], "nextPageToken": None}
        norm_space = self.normalize_space_name(space_name)
        try:
            params = {
                "parent": norm_space,
                "pageSize": min(page_size, 100),
            }
            if page_token:
                params["pageToken"] = page_token
            if filter_str:
                params["filter"] = filter_str
            result = self.service.spaces().messages().list(**params).execute()
            return {
                "messages": result.get("messages", []),
                "nextPageToken": result.get("nextPageToken"),
            }
        except HttpError as e:
            logger.error(f"Failed to list messages in {norm_space}: {e}")
            print_error(f"Chat messages error: {e}")
            return {"messages": [], "nextPageToken": None, "error": str(e)}

    def get_message(self, message_name: str, space_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get a single chat message by full name or ID"""
        if not self.service:
            return None
        norm_name = self.normalize_message_name(message_name, space_id)
        try:
            return self.service.spaces().messages().get(name=norm_name).execute()
        except HttpError as e:
            logger.error(f"Failed to get message {norm_name}: {e}")
            print_error(f"Message not found: {norm_name}")
            return None

    def send_message(
        self,
        space_name: str,
        text: str,
        thread_key: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Post a new message in a space, optionally in a thread"""
        if not self.service:
            return None
        norm_space = self.normalize_space_name(space_name)
        try:
            body: Dict[str, Any] = {"text": text}
            params: Dict[str, Any] = {"parent": norm_space, "body": body}
            if thread_key:
                body["thread"] = {"threadKey": thread_key}
                params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
            return self.service.spaces().messages().create(**params).execute()
        except HttpError as e:
            logger.error(f"Failed to send message to {norm_space}: {e}")
            print_error(f"Failed to send message: {e}")
            return None

    def reply_message(
        self,
        message_name: str,
        text: str,
        space_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Reply to an existing message or thread"""
        norm_msg = self.normalize_message_name(message_name, space_id)
        # Fetch parent message to obtain its thread
        parent_msg = self.get_message(norm_msg)
        if not parent_msg:
            print_error(f"Cannot reply: parent message {norm_msg} could not be retrieved")
            return None
        
        space_parent = norm_msg.split("/messages/")[0] if "/messages/" in norm_msg else ""
        thread_info = parent_msg.get("thread", {})
        thread_name = thread_info.get("name")

        try:
            body: Dict[str, Any] = {"text": text}
            if thread_name:
                body["thread"] = {"name": thread_name}
            params: Dict[str, Any] = {
                "parent": space_parent,
                "body": body,
                "messageReplyOption": "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
            }
            return self.service.spaces().messages().create(**params).execute()
        except HttpError as e:
            logger.error(f"Failed to reply to message {norm_msg}: {e}")
            print_error(f"Failed to reply: {e}")
            return None

    def edit_message(
        self,
        message_name: str,
        text: str,
        space_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Edit an existing message text"""
        if not self.service:
            return None
        norm_name = self.normalize_message_name(message_name, space_id)
        try:
            body = {"text": text}
            return self.service.spaces().messages().patch(
                name=norm_name,
                updateMask="text",
                body=body
            ).execute()
        except HttpError as e:
            logger.error(f"Failed to edit message {norm_name}: {e}")
            print_error(f"Failed to edit message: {e}")
            return None

    def delete_message(self, message_name: str, space_id: Optional[str] = None) -> bool:
        """Delete a message from a chat space"""
        if not self.service:
            return False
        norm_name = self.normalize_message_name(message_name, space_id)
        try:
            self.service.spaces().messages().delete(name=norm_name).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to delete message {norm_name}: {e}")
            print_error(f"Failed to delete message: {e}")
            return False

    def search_messages(
        self,
        query: str,
        space_name: Optional[str] = None,
        max_results: int = 25
    ) -> List[Dict[str, Any]]:
        """
        Search messages across one or more spaces matching a query.
        """
        matches = []
        q_lower = query.lower()
        spaces_to_check = []

        if space_name:
            spaces_to_check = [self.normalize_space_name(space_name)]
        else:
            space_list = self.list_spaces(page_size=10)
            spaces_to_check = [s["name"] for s in space_list.get("spaces", []) if "name" in s]

        for s_name in spaces_to_check:
            res = self.list_messages(s_name, page_size=50)
            for msg in res.get("messages", []):
                msg_text = msg.get("text", "")
                if q_lower in msg_text.lower():
                    matches.append(msg)
                    if len(matches) >= max_results:
                        return matches
        return matches

    def list_threads(self, space_name: str, page_size: int = 25) -> List[Dict[str, Any]]:
        """List distinct threads in a space with latest message summary"""
        res = self.list_messages(space_name, page_size=page_size * 2)
        messages = res.get("messages", [])
        threads_dict: Dict[str, Dict[str, Any]] = {}
        for m in messages:
            th = m.get("thread", {})
            th_name = th.get("name", "unthreaded")
            if th_name not in threads_dict:
                threads_dict[th_name] = {
                    "thread": th_name,
                    "first_message": m.get("text", ""),
                    "sender": m.get("sender", {}).get("displayName", "Unknown"),
                    "created": m.get("createTime"),
                    "message_count": 1,
                }
            else:
                threads_dict[th_name]["message_count"] += 1
        return list(threads_dict.values())[:page_size]

    # =========================================================================
    # Memberships
    # =========================================================================

    def list_members(
        self,
        space_name: str,
        page_size: int = 50,
        page_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """List members in a space"""
        if not self.service:
            return {"memberships": [], "nextPageToken": None}
        norm_space = self.normalize_space_name(space_name)
        try:
            params = {
                "parent": norm_space,
                "pageSize": min(page_size, 100),
            }
            if page_token:
                params["pageToken"] = page_token
            result = self.service.spaces().members().list(**params).execute()
            return {
                "memberships": result.get("memberships", []),
                "nextPageToken": result.get("nextPageToken"),
            }
        except HttpError as e:
            logger.error(f"Failed to list members in {norm_space}: {e}")
            print_error(f"Chat members error: {e}")
            return {"memberships": [], "nextPageToken": None, "error": str(e)}

    def add_member(
        self,
        space_name: str,
        user_name_or_email: str,
        role: str = "ROLE_MEMBER"
    ) -> Optional[Dict[str, Any]]:
        """Add a member to a space"""
        if not self.service:
            return None
        norm_space = self.normalize_space_name(space_name)
        user_norm = user_name_or_email.strip()
        if not user_norm.startswith("users/"):
            user_norm = f"users/{user_norm}"
        try:
            body = {
                "role": role.upper(),
                "member": {
                    "name": user_norm,
                    "type": "HUMAN"
                }
            }
            return self.service.spaces().members().create(
                parent=norm_space,
                body=body
            ).execute()
        except HttpError as e:
            logger.error(f"Failed to add member {user_norm} to {norm_space}: {e}")
            print_error(f"Failed to add member: {e}")
            return None

    def remove_member(self, space_name: str, member_name: str) -> bool:
        """Remove a member from a space"""
        if not self.service:
            return False
        norm_space = self.normalize_space_name(space_name)
        norm_mem = member_name.strip()
        if not norm_mem.startswith("spaces/"):
            norm_mem = f"{norm_space}/members/{norm_mem}"
        try:
            self.service.spaces().members().delete(name=norm_mem).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to remove member {norm_mem}: {e}")
            print_error(f"Failed to remove member: {e}")
            return False

    # =========================================================================
    # Reactions
    # =========================================================================

    def create_reaction(
        self,
        message_name: str,
        emoji: str,
        space_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Add an emoji reaction to a message"""
        if not self.service:
            return None
        norm_msg = self.normalize_message_name(message_name, space_id)
        try:
            body = {
                "emoji": {
                    "unicode": emoji
                }
            }
            return self.service.spaces().messages().reactions().create(
                parent=norm_msg,
                body=body
            ).execute()
        except HttpError as e:
            logger.error(f"Failed to react to message {norm_msg}: {e}")
            print_error(f"Failed to add reaction: {e}")
            return None

    def delete_reaction(self, reaction_name: str) -> bool:
        """Delete an emoji reaction by name"""
        if not self.service:
            return False
        try:
            self.service.spaces().messages().reactions().delete(name=reaction_name).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to delete reaction {reaction_name}: {e}")
            print_error(f"Failed to delete reaction: {e}")
            return False
