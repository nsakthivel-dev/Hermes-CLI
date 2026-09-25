"""
Google Tasks service integration for Hermes CLI
"""

import logging
from typing import List, Dict, Any, Optional
from googleapiclient.errors import HttpError

from ..auth.oauth import OAuthManager
from ..utils.formatters import print_error, print_info, print_success

logger = logging.getLogger(__name__)


class TasksService:
    """Google Tasks API service wrapper"""

    def __init__(self, oauth_manager: OAuthManager, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.cache_manager = cache_manager
        self.service = None
        self._initialize_service()

    def _initialize_service(self) -> bool:
        """Initialize Google Tasks service client (v1)"""
        try:
            self.service = self.oauth_manager.build_service('tasks', 'v1')
            return self.service is not None
        except Exception as e:
            logger.error(f"Failed to initialize Tasks service: {e}")
            return False

    def test_connection(self) -> Dict[str, Any]:
        """Test connection to Google Tasks API"""
        if not self.service:
            if not self._initialize_service():
                return {"status": "error", "message": "Failed to initialize Tasks API service"}
        try:
            res = self.service.tasklists().list(maxResults=1).execute()
            return {
                "status": "success",
                "message": "Successfully connected to Google Tasks API",
                "tasklists_count": len(res.get("items", []))
            }
        except Exception as e:
            logger.error(f"Error testing Tasks API connection: {e}")
            return {"status": "error", "message": str(e)}

    # =========================================================================
    # Task Lists Management
    # =========================================================================

    def list_task_lists(self, max_results: int = 50, page_token: Optional[str] = None) -> Dict[str, Any]:
        """List all task lists"""
        if not self.service:
            return {"items": [], "nextPageToken": None}
        try:
            res = self.service.tasklists().list(maxResults=max_results, pageToken=page_token).execute()
            return {
                "items": res.get("items", []),
                "nextPageToken": res.get("nextPageToken")
            }
        except HttpError as e:
            logger.error(f"Failed to list task lists: {e}")
            print_error(f"Tasks API error: {e}")
            return {"items": [], "nextPageToken": None, "error": str(e)}

    def get_task_list(self, task_list_id: str = "@default") -> Optional[Dict[str, Any]]:
        """Get details of a task list"""
        if not self.service:
            return None
        try:
            return self.service.tasklists().get(tasklist=task_list_id).execute()
        except HttpError as e:
            logger.error(f"Failed to get task list {task_list_id}: {e}")
            print_error(f"Task list not found: {task_list_id}")
            return None

    def create_task_list(self, title: str) -> Optional[Dict[str, Any]]:
        """Create a new task list"""
        if not self.service:
            return None
        try:
            return self.service.tasklists().insert(body={"title": title}).execute()
        except HttpError as e:
            logger.error(f"Failed to create task list {title}: {e}")
            print_error(f"Failed to create task list: {e}")
            return None

    def update_task_list(self, task_list_id: str, title: str) -> Optional[Dict[str, Any]]:
        """Update a task list's title"""
        if not self.service:
            return None
        try:
            return self.service.tasklists().patch(tasklist=task_list_id, body={"title": title}).execute()
        except HttpError as e:
            logger.error(f"Failed to update task list {task_list_id}: {e}")
            print_error(f"Failed to update task list: {e}")
            return None

    def delete_task_list(self, task_list_id: str) -> bool:
        """Delete a task list"""
        if not self.service:
            return False
        try:
            self.service.tasklists().delete(tasklist=task_list_id).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to delete task list {task_list_id}: {e}")
            print_error(f"Failed to delete task list: {e}")
            return False

    # =========================================================================
    # Tasks Management
    # =========================================================================

    def list_tasks(
        self,
        task_list_id: str = "@default",
        show_completed: bool = True,
        show_hidden: bool = False,
        max_results: int = 50,
        page_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """List tasks within a task list"""
        if not self.service:
            return {"items": [], "nextPageToken": None}
        try:
            res = self.service.tasks().list(
                tasklist=task_list_id,
                showCompleted=show_completed,
                showHidden=show_hidden,
                maxResults=max_results,
                pageToken=page_token
            ).execute()
            return {
                "items": res.get("items", []),
                "nextPageToken": res.get("nextPageToken")
            }
        except HttpError as e:
            logger.error(f"Failed to list tasks in {task_list_id}: {e}")
            print_error(f"Tasks error: {e}")
            return {"items": [], "nextPageToken": None, "error": str(e)}

    def get_task(self, task_id: str, task_list_id: str = "@default") -> Optional[Dict[str, Any]]:
        """Get a single task by ID"""
        if not self.service:
            return None
        try:
            return self.service.tasks().get(tasklist=task_list_id, task=task_id).execute()
        except HttpError as e:
            logger.error(f"Failed to get task {task_id}: {e}")
            print_error(f"Task not found: {task_id}")
            return None

    def create_task(
        self,
        title: str,
        notes: Optional[str] = None,
        due: Optional[str] = None,
        task_list_id: str = "@default",
        parent: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Create a new task"""
        if not self.service:
            return None
        try:
            body: Dict[str, Any] = {"title": title}
            if notes:
                body["notes"] = notes
            if due:
                body["due"] = due
            kwargs = {"tasklist": task_list_id, "body": body}
            if parent:
                kwargs["parent"] = parent
            return self.service.tasks().insert(**kwargs).execute()
        except HttpError as e:
            logger.error(f"Failed to create task {title}: {e}")
            print_error(f"Failed to create task: {e}")
            return None

    def update_task(
        self,
        task_id: str,
        title: Optional[str] = None,
        notes: Optional[str] = None,
        due: Optional[str] = None,
        status: Optional[str] = None,
        task_list_id: str = "@default"
    ) -> Optional[Dict[str, Any]]:
        """Update an existing task"""
        if not self.service:
            return None
        try:
            body: Dict[str, Any] = {}
            if title is not None:
                body["title"] = title
            if notes is not None:
                body["notes"] = notes
            if due is not None:
                body["due"] = due
            if status is not None:
                body["status"] = status
            return self.service.tasks().patch(tasklist=task_list_id, task=task_id, body=body).execute()
        except HttpError as e:
            logger.error(f"Failed to update task {task_id}: {e}")
            print_error(f"Failed to update task: {e}")
            return None

    def complete_task(self, task_id: str, task_list_id: str = "@default") -> Optional[Dict[str, Any]]:
        """Mark task as completed"""
        return self.update_task(task_id, status="completed", task_list_id=task_list_id)

    def uncomplete_task(self, task_id: str, task_list_id: str = "@default") -> Optional[Dict[str, Any]]:
        """Reopen a completed task"""
        return self.update_task(task_id, status="needsAction", task_list_id=task_list_id)

    def delete_task(self, task_id: str, task_list_id: str = "@default") -> bool:
        """Delete a task"""
        if not self.service:
            return False
        try:
            self.service.tasks().delete(tasklist=task_list_id, task=task_id).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to delete task {task_id}: {e}")
            print_error(f"Failed to delete task: {e}")
            return False

    def move_task(self, task_id: str, parent: Optional[str] = None, previous: Optional[str] = None, task_list_id: str = "@default") -> Optional[Dict[str, Any]]:
        """Move a task position or reparent"""
        if not self.service:
            return None
        try:
            kwargs: Dict[str, Any] = {"tasklist": task_list_id, "task": task_id}
            if parent:
                kwargs["parent"] = parent
            if previous:
                kwargs["previous"] = previous
            return self.service.tasks().move(**kwargs).execute()
        except HttpError as e:
            logger.error(f"Failed to move task {task_id}: {e}")
            print_error(f"Failed to move task: {e}")
            return None

    def clear_completed(self, task_list_id: str = "@default") -> bool:
        """Clear all completed tasks from a list"""
        if not self.service:
            return False
        try:
            self.service.tasks().clear(tasklist=task_list_id).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to clear completed tasks in {task_list_id}: {e}")
            print_error(f"Failed to clear tasks: {e}")
            return False
