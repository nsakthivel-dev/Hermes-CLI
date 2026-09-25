"""
Tests for Human-Friendly Interactive Flows across all 15 Google Workspace API modules:
- Calendar (delete, update)
- Meet (spaces, end conference)
- Gmail (messages, delete)
- Drive (files, delete, rename)
- Tasks (lists, items, delete)
- Chat (spaces, delete message)
- Docs (documents)
- Sheets (spreadsheets)
- Workspace Events (subscriptions, delete)
- Apps Script (projects)
- Admin SDK (users, suspend)
- Cloud Identity (groups)
- Cloud Search (queries)
- Forms (forms)
- Drive Activity (activity feed)
"""

import pytest
from unittest.mock import MagicMock, patch

from gsuite_cli.ui.human_flows import (
    run_calendar_delete_flow,
    run_calendar_update_flow,
    run_meet_spaces_flow,
    run_meet_end_flow,
    run_gmail_messages_flow,
    run_gmail_delete_flow,
    run_drive_files_flow,
    run_drive_delete_flow,
    run_drive_rename_flow,
    run_tasks_lists_flow,
    run_tasks_items_flow,
    run_task_delete_flow,
    run_chat_spaces_flow,
    run_chat_message_delete_flow,
    run_docs_flow,
    run_sheets_flow,
    run_events_subscription_flow,
    run_events_delete_flow,
    run_script_projects_flow,
    run_admin_users_flow,
    run_admin_user_suspend_flow,
    run_identity_groups_flow,
    run_cloud_search_flow,
    run_forms_flow,
    run_drive_activity_flow,
)


# 1. Calendar delete flow
def test_calendar_delete_flow_confirmed():
    cal_svc = MagicMock()
    cal_svc.list_calendars.return_value = [{"id": "primary", "summary": "Personal"}]
    cal_svc.list_events.return_value = [{"id": "ev_1", "summary": "Project Sync", "start": {}, "end": {}}]
    cal_svc.delete_event.return_value = True

    with patch("builtins.input", side_effect=["1", "1"]), \
         patch("click.prompt", side_effect=["1", "1"]), \
         patch("gsuite_cli.services.resource_resolver.GlobalResourceResolver.confirm_action", return_value=True):
        res = run_calendar_delete_flow(cal_svc)
        assert res is True
        cal_svc.delete_event.assert_called_once_with("ev_1", calendar_id="primary")


# 2. Calendar update flow
def test_calendar_update_flow_confirmed():
    cal_svc = MagicMock()
    cal_svc.list_calendars.return_value = [{"id": "primary", "summary": "Personal"}]
    cal_svc.list_events.return_value = [{
        "id": "ev_1",
        "summary": "Project Sync",
        "start": {"dateTime": "2026-09-20T10:00:00Z"},
        "end": {"dateTime": "2026-09-20T11:00:00Z"},
    }]
    cal_svc.update_event.return_value = {"id": "ev_1", "summary": "Updated Sync"}

    with patch("builtins.input", side_effect=["1", "1", "1", "Updated Sync", "y"]), \
         patch("click.prompt", side_effect=["1", "1", "1", "Updated Sync", "y"]):
        res = run_calendar_update_flow(cal_svc)
        assert res is True
        cal_svc.update_event.assert_called_once()


# 3. Meet flow
def test_meet_flow_view():
    meet_svc = MagicMock()
    meet_svc.list_spaces.return_value = [{"name": "spaces/xyz123", "meetingUri": "https://meet.google.com/xyz-1234-abc", "meetingCode": "xyz-1234-abc"}]

    with patch("builtins.input", return_value="1"), \
         patch("click.prompt", return_value="1"):
        res = run_meet_spaces_flow(meet_svc)
        assert res is not None
        assert res["name"] == "spaces/xyz123"


def test_meet_flow_end():
    meet_svc = MagicMock()
    meet_svc.list_spaces.return_value = [{"name": "spaces/xyz123", "meetingUri": "https://meet.google.com/xyz-1234-abc"}]
    meet_svc.end_active_conference.return_value = True

    with patch("builtins.input", return_value="1"), \
         patch("click.prompt", return_value="1"), \
         patch("gsuite_cli.services.resource_resolver.GlobalResourceResolver.confirm_action", return_value=True):
        res = run_meet_end_flow(meet_svc)
        assert res is True
        meet_svc.end_active_conference.assert_called_once_with("spaces/xyz123")


# 4. Gmail flow
def test_gmail_flow_delete():
    gmail_svc = MagicMock()
    gmail_svc.list_messages.return_value = [{"id": "msg_001", "snippet": "Billing statement", "subject": "Statement"}]
    gmail_svc.get_message.return_value = {"id": "msg_001", "subject": "Statement", "snippet": "Billing"}
    gmail_svc.delete_message.return_value = True

    with patch("builtins.input", return_value="1"), \
         patch("click.prompt", return_value="1"), \
         patch("gsuite_cli.services.resource_resolver.GlobalResourceResolver.confirm_action", return_value=True):
        res = run_gmail_delete_flow(gmail_svc)
        assert res is True
        gmail_svc.delete_message.assert_called_once_with("msg_001")


# 5. Drive flow
def test_drive_flow_delete():
    drive_svc = MagicMock()
    drive_svc.list_files.return_value = [{"id": "file_123", "name": "Report.pdf", "mimeType": "application/pdf"}]
    drive_svc.delete_file.return_value = True

    with patch("builtins.input", return_value="1"), \
         patch("click.prompt", return_value="1"), \
         patch("gsuite_cli.services.resource_resolver.GlobalResourceResolver.confirm_action", return_value=True):
        res = run_drive_delete_flow(drive_svc)
        assert res is True
        drive_svc.delete_file.assert_called_once_with("file_123")


def test_drive_flow_rename():
    drive_svc = MagicMock()
    drive_svc.list_files.return_value = [{"id": "file_123", "name": "Report.pdf", "mimeType": "application/pdf"}]
    drive_svc.rename_file.return_value = {"id": "file_123", "name": "Final_Report.pdf"}

    with patch("builtins.input", side_effect=["1", "Final_Report.pdf"]), \
         patch("click.prompt", side_effect=["1", "Final_Report.pdf"]), \
         patch("gsuite_cli.services.resource_resolver.GlobalResourceResolver.confirm_action", return_value=True):
        res = run_drive_rename_flow(drive_svc)
        assert res is True
        drive_svc.rename_file.assert_called_once_with("file_123", "Final_Report.pdf")


# 6. Tasks flow
def test_tasks_flow_delete():
    tasks_svc = MagicMock()
    tasks_svc.list_task_lists.return_value = [{"id": "list_1", "title": "My Tasks"}]
    tasks_svc.list_tasks.return_value = [{"id": "task_1", "title": "Submit expense"}]
    tasks_svc.delete_task.return_value = True

    with patch("builtins.input", side_effect=["1", "1"]), \
         patch("click.prompt", side_effect=["1", "1"]), \
         patch("gsuite_cli.services.resource_resolver.GlobalResourceResolver.confirm_action", return_value=True):
        res = run_task_delete_flow(tasks_svc)
        assert res is True
        tasks_svc.delete_task.assert_called_once_with(tasklist_id="list_1", task_id="task_1")


# 7. Chat flow
def test_chat_flow_delete_message():
    chat_svc = MagicMock()
    chat_svc.list_spaces.return_value = {"spaces": [{"name": "spaces/ABC", "displayName": "Dev Team"}]}
    chat_svc.list_messages.return_value = {"messages": [{"name": "spaces/ABC/messages/msg_1", "text": "Hello world"}]}
    chat_svc.delete_message.return_value = True

    with patch("builtins.input", side_effect=["1", "1"]), \
         patch("click.prompt", side_effect=["1", "1"]), \
         patch("gsuite_cli.services.resource_resolver.GlobalResourceResolver.confirm_action", return_value=True):
        res = run_chat_message_delete_flow(chat_svc)
        assert res is True
        chat_svc.delete_message.assert_called_once_with("spaces/ABC/messages/msg_1")


# 8. Docs flow
def test_docs_flow_view():
    drive_svc = MagicMock()
    drive_svc.list_files.return_value = [{"id": "doc_1", "name": "Design Doc", "mimeType": "application/vnd.google-apps.document"}]
    docs_svc = MagicMock()
    docs_svc.get_document.return_value = {"title": "Design Doc", "documentId": "doc_1", "body": {"content": []}}

    with patch("builtins.input", return_value="1"), \
         patch("click.prompt", return_value="1"):
        res = run_docs_flow(docs_svc, drive_svc)
        assert res is not None
        assert res.get("id") == "doc_1"


# 9. Sheets flow
def test_sheets_flow_view():
    drive_svc = MagicMock()
    drive_svc.list_files.return_value = [{"id": "sheet_1", "name": "Budget 2026", "mimeType": "application/vnd.google-apps.spreadsheet"}]
    sheets_svc = MagicMock()
    sheets_svc.get_spreadsheet.return_value = {"spreadsheetId": "sheet_1", "properties": {"title": "Budget 2026"}, "sheets": []}

    with patch("builtins.input", return_value="1"), \
         patch("click.prompt", return_value="1"):
        res = run_sheets_flow(sheets_svc, drive_svc)
        assert res is not None
        assert res.get("id") == "sheet_1"


# 10. Workspace Events flow
def test_workspace_events_flow_delete():
    events_svc = MagicMock()
    events_svc.list_subscriptions.return_value = [{"name": "subscriptions/sub-123", "targetResource": "//chat.googleapis.com/spaces/ABC"}]
    events_svc.delete_subscription.return_value = True

    with patch("builtins.input", return_value="1"), \
         patch("click.prompt", return_value="1"), \
         patch("gsuite_cli.services.resource_resolver.GlobalResourceResolver.confirm_action", return_value=True):
        res = run_events_delete_flow(events_svc)
        assert res is True
        events_svc.delete_subscription.assert_called_once_with("subscriptions/sub-123")


# 11. Apps Script flow
def test_apps_script_flow_view():
    script_svc = MagicMock()
    script_svc.list_projects.return_value = [{"scriptId": "script_1", "title": "Webhook Sync"}]
    script_svc.get_project.return_value = {"scriptId": "script_1", "title": "Webhook Sync", "files": []}

    with patch("builtins.input", return_value="1"), \
         patch("click.prompt", return_value="1"):
        res = run_script_projects_flow(script_svc)
        assert res is not None


# 12. Admin SDK flow
def test_admin_sdk_flow_suspend():
    admin_svc = MagicMock()
    admin_svc.list_users.return_value = [{"primaryEmail": "alice@example.com", "name": {"fullName": "Alice Smith"}}]
    admin_svc.suspend_user.return_value = True

    with patch("builtins.input", return_value="1"), \
         patch("click.prompt", return_value="1"), \
         patch("gsuite_cli.services.resource_resolver.GlobalResourceResolver.confirm_action", return_value=True):
        res = run_admin_user_suspend_flow(admin_svc)
        assert res is True
        admin_svc.suspend_user.assert_called_once_with("alice@example.com", suspend=True)


# 13. Cloud Identity flow
def test_cloud_identity_flow_view():
    identity_svc = MagicMock()
    identity_svc.list_groups.return_value = [{"name": "groups/grp-1", "displayName": "Engineering"}]

    with patch("builtins.input", return_value="1"), \
         patch("click.prompt", return_value="1"):
        res = run_identity_groups_flow(identity_svc)
        assert res is not None
        identity_svc.list_groups.assert_called_once()


# 14. Cloud Search flow
def test_cloud_search_flow():
    search_svc = MagicMock()
    search_svc.search.return_value = [{"title": "Engineering Doc", "url": "https://drive.google.com/...", "snippet": "Architecture doc"}]

    with patch("builtins.input", return_value="1"), \
         patch("click.prompt", return_value="1"):
        res = run_cloud_search_flow(search_svc, query="engineering")
        assert res is not None
        search_svc.search.assert_called_once_with(query="engineering")


# 15. Forms flow
def test_forms_flow_view():
    drive_svc = MagicMock()
    drive_svc.list_files.return_value = [{"id": "form_1", "name": "Event Registration", "mimeType": "application/vnd.google-apps.form"}]
    forms_svc = MagicMock()
    forms_svc.get_form.return_value = {"formId": "form_1", "info": {"title": "Event Registration"}}

    with patch("builtins.input", return_value="1"), \
         patch("click.prompt", return_value="1"):
        res = run_forms_flow(forms_svc, drive_svc)
        assert res is not None
        assert res.get("id") == "form_1"


# 16. Drive Activity flow
def test_drive_activity_flow():
    activity_svc = MagicMock()
    activity_svc.query_activity.return_value = {
        "activities": [{"primaryActionDetail": {"edit": {}}, "timestamp": "2026-09-05T12:00:00Z", "targets": []}]
    }

    with patch("builtins.input", return_value="1"), \
         patch("click.prompt", return_value="1"):
        res = run_drive_activity_flow(activity_svc)
        assert res is not None
        activity_svc.query_activity.assert_called_once_with(page_size=10)
