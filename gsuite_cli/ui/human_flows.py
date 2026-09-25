"""
Human-friendly resource interaction workflows for Hermes CLI.
Implements LIST -> SELECT -> VIEW -> ACTION across all 15 Google Workspace API modules.
"""

from __future__ import annotations
import sys
from typing import Dict, List, Any, Optional, Callable, Tuple
from colorama import Fore, Style

from ..services.resource_resolver import (
    GlobalResourceResolver,
    ResourceResolutionError,
    ResourceNotFoundError,
    AmbiguousResourceNameError,
)
from ..utils.formatters import (
    print_error,
    print_info,
    print_success,
    print_warning,
    print_header,
    print_key_value_pairs,
)
from .interactive_calendar import run_calendar_update_flow


# ===========================================================================
# 1. CALENDAR FLOWS
# ===========================================================================

def run_calendar_delete_flow(
    cal_service: Any,
    config_manager: Optional[Any] = None,
    calendar_ref: Optional[str] = None,
    event_ref: Optional[str] = None
) -> bool:
    """
    Human-friendly Calendar Event Delete Flow:
    Select Calendar -> List Events -> Select Event -> View Details -> Confirm [y/N] -> Delete
    """
    from ..services.calendar_resolver import CalendarResolver, CalendarEventResolver

    calendars = CalendarResolver.get_calendars(cal_service)
    if calendar_ref:
        try:
            calendar_id = CalendarResolver.resolve(calendar_ref, calendars, config_manager)
        except Exception:
            calendar_id = calendar_ref
    else:
        calendar_id = CalendarResolver.prompt_selection(cal_service, config_manager)
        if not calendar_id:
            return False

    events = cal_service.list_events(calendar_id=calendar_id)
    if not events:
        print()
        print_info("No events found in this calendar.")
        return False

    if event_ref:
        try:
            selected_event = CalendarEventResolver.resolve(event_ref, events, cal_service, calendar_id)
        except Exception:
            print_error(f"Event not found: {event_ref}")
            return False
    else:
        selected_event = GlobalResourceResolver.prompt_selection(
            events,
            resource_name="Event",
            module="calendar",
            config_manager=config_manager,
            title_fn=lambda ev: ev.get('summary') or 'Untitled Event',
            subtitle_fn=lambda ev: CalendarEventResolver.format_event_datetime(ev),
            id_fn=lambda ev: ev.get('id', ''),
        )
        if not selected_event:
            return False

    def _show_event_details(ev: Dict[str, Any]):
        title = ev.get('summary') or 'Untitled Event'
        dt_str = CalendarEventResolver.format_event_datetime(ev)
        desc = ev.get('description', 'None')
        loc = ev.get('location', 'None')
        print(f"Title       : {title}")
        print(f"Date/Time   : {dt_str}")
        print(f"Description : {desc}")
        print(f"Location    : {loc}")

    def _delete_event(ev: Dict[str, Any]) -> bool:
        ev_id = ev.get('id', '')
        return bool(cal_service.delete_event(ev_id, calendar_id=calendar_id))

    return GlobalResourceResolver.execute_delete_flow(
        selected_event,
        display_details_fn=_show_event_details,
        delete_fn=_delete_event,
        resource_name="Event"
    )


def run_calendar_info_flow(
    cal_service: Any,
    config_manager: Optional[Any] = None,
    calendar_ref: Optional[str] = None,
    event_ref: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Human-friendly Calendar Event Info Flow."""
    from ..services.calendar_resolver import CalendarResolver, CalendarEventResolver

    calendars = CalendarResolver.get_calendars(cal_service)
    if calendar_ref:
        try:
            calendar_id = CalendarResolver.resolve(calendar_ref, calendars, config_manager)
        except Exception:
            calendar_id = calendar_ref
    else:
        calendar_id = CalendarResolver.prompt_selection(cal_service, config_manager)
        if not calendar_id:
            return None

    events = cal_service.list_events(calendar_id=calendar_id)
    if not events:
        print_info("No events found in this calendar.")
        return None

    if event_ref:
        try:
            selected_event = CalendarEventResolver.resolve(event_ref, events, cal_service, calendar_id)
        except Exception:
            print_error(f"Event not found: {event_ref}")
            return None
    else:
        selected_event = GlobalResourceResolver.prompt_selection(
            events,
            resource_name="Event",
            module="calendar",
            config_manager=config_manager,
            title_fn=lambda ev: ev.get('summary') or 'Untitled Event',
            subtitle_fn=lambda ev: CalendarEventResolver.format_event_datetime(ev),
            id_fn=lambda ev: ev.get('id', ''),
        )
        if not selected_event:
            return None

    print()
    print(Fore.WHITE + Style.BRIGHT + "📅 Event Information")
    print(Fore.WHITE + "=" * 60)
    details = {
        'Title': selected_event.get('summary', 'Untitled'),
        'ID': selected_event.get('id', ''),
        'Start': selected_event.get('start', ''),
        'End': selected_event.get('end', ''),
        'Description': selected_event.get('description', 'None'),
        'Location': selected_event.get('location', 'None'),
        'Attendees': [a.get('email') for a in selected_event.get('attendees', []) if isinstance(a, dict)],
    }
    print_key_value_pairs(details)
    return selected_event


# ===========================================================================
# 2. MEET FLOWS
# ===========================================================================

def run_meet_spaces_flow(
    meet_service: Any,
    config_manager: Optional[Any] = None,
    space_ref: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Human-friendly Meet Space Selection & Details."""
    spaces = meet_service.list_spaces()
    if not spaces:
        print_info("No meeting spaces found.")
        return None

    if space_ref:
        try:
            selected_space = GlobalResourceResolver.resolve(
                space_ref, spaces, module="meet", resource_type="Meeting Space",
                config_manager=config_manager,
                title_fn=lambda s: s.get('meetingUri') or s.get('name', 'Untitled Space'),
                id_fn=lambda s: s.get('name', '')
            )
        except Exception as e:
            print_error(str(e))
            return None
    else:
        selected_space = GlobalResourceResolver.prompt_selection(
            spaces,
            resource_name="Meeting Space",
            module="meet",
            config_manager=config_manager,
            title_fn=lambda s: f"Meet Space ({s.get('meetingCode', s.get('name', 'Untitled'))})",
            subtitle_fn=lambda s: f"URI: {s.get('meetingUri', 'None')} | Access: {s.get('config', {}).get('accessType', 'DEFAULT') if isinstance(s.get('config'), dict) else 'DEFAULT'}",
            id_fn=lambda s: s.get('name', '')
        )
        if not selected_space:
            return None

    print()
    print(Fore.WHITE + Style.BRIGHT + "🎥 Meeting Space Details")
    print(Fore.WHITE + "=" * 60)
    details = {
        'Space Name': selected_space.get('name', ''),
        'Meeting Code': selected_space.get('meetingCode', 'None'),
        'Meeting URI': selected_space.get('meetingUri', 'None'),
        'Active Conference': selected_space.get('activeConference', 'None'),
    }
    print_key_value_pairs(details)
    return selected_space


def run_meet_end_flow(
    meet_service: Any,
    config_manager: Optional[Any] = None,
    space_ref: Optional[str] = None
) -> bool:
    """Human-friendly Meet End Active Conference Flow."""
    selected_space = run_meet_spaces_flow(meet_service, config_manager, space_ref)
    if not selected_space:
        return False

    space_name = selected_space.get('name', '')
    if not GlobalResourceResolver.confirm_action(f"End active conference for {space_name}?", default=False):
        print_info("Operation cancelled.")
        return False

    res = meet_service.end_active_conference(space_name)
    if res is not None:
        print_success(f"Conference ended successfully for {space_name}.")
        return True
    else:
        print_error("Failed to end conference or no active conference.")
        return False


# ===========================================================================
# 3. GMAIL FLOWS
# ===========================================================================

def run_gmail_messages_flow(
    gmail_service: Any,
    config_manager: Optional[Any] = None,
    query: Optional[str] = None,
    msg_ref: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Human-friendly Gmail message list, selection, and viewing."""
    res = gmail_service.list_messages(query=query, max_results=20)
    messages = res.get('messages', []) if isinstance(res, dict) else res
    if not messages:
        print_info("No messages found.")
        return None

    def _get_msg_title(m: Dict[str, Any]) -> str:
        headers = {h.get('name', '').lower(): h.get('value', '') for h in m.get('payload', {}).get('headers', []) if isinstance(h, dict)}
        subject = headers.get('subject') or m.get('snippet', 'No Subject')
        sender = headers.get('from', 'Unknown Sender')
        return f"{sender} - {subject}"

    def _get_msg_subtitle(m: Dict[str, Any]) -> str:
        snippet = m.get('snippet', '')
        return snippet[:80] + '...' if len(snippet) > 80 else snippet

    if msg_ref:
        try:
            selected_msg = GlobalResourceResolver.resolve(
                msg_ref, messages, module="gmail", resource_type="Message",
                config_manager=config_manager,
                title_fn=_get_msg_title,
                fetch_fn=lambda mid: gmail_service.get_message(mid)
            )
        except Exception as e:
            print_error(str(e))
            return None
    else:
        selected_msg = GlobalResourceResolver.prompt_selection(
            messages,
            resource_name="Message",
            module="gmail",
            config_manager=config_manager,
            title_fn=_get_msg_title,
            subtitle_fn=_get_msg_subtitle,
            id_fn=lambda m: m.get('id', ''),
            fetch_fn=lambda mid: gmail_service.get_message(mid)
        )
        if not selected_msg:
            return None

    # Fetch full message details if needed
    msg_id = selected_msg.get('id', '')
    if 'payload' not in selected_msg and msg_id:
        try:
            full_msg = gmail_service.get_message(msg_id)
            if full_msg:
                selected_msg = full_msg
        except Exception:
            pass

    headers = {h.get('name', '').lower(): h.get('value', '') for h in selected_msg.get('payload', {}).get('headers', []) if isinstance(h, dict)}
    print()
    print(Fore.WHITE + Style.BRIGHT + "📧 Message Details")
    print(Fore.WHITE + "=" * 60)
    details = {
        'From': headers.get('from', 'Unknown'),
        'To': headers.get('to', 'Unknown'),
        'Subject': headers.get('subject', 'No Subject'),
        'Date': headers.get('date', 'Unknown'),
        'Snippet': selected_msg.get('snippet', ''),
        'Message ID': selected_msg.get('id', ''),
    }
    print_key_value_pairs(details)
    return selected_msg


def run_gmail_delete_flow(
    gmail_service: Any,
    config_manager: Optional[Any] = None,
    msg_ref: Optional[str] = None
) -> bool:
    """Human-friendly Gmail message deletion flow."""
    selected_msg = run_gmail_messages_flow(gmail_service, config_manager, msg_ref=msg_ref)
    if not selected_msg:
        return False

    msg_id = selected_msg.get('id', '')
    if not GlobalResourceResolver.confirm_action(f"Permanently delete this message?", default=False):
        print_info("Operation cancelled.")
        return False

    success = bool(gmail_service.delete_message(msg_id))
    if success:
        print_success("Message deleted successfully.")
        return True
    else:
        print_error("Failed to delete message.")
        return False


# ===========================================================================
# 4. CHAT FLOWS
# ===========================================================================

def run_chat_spaces_flow(
    chat_service: Any,
    config_manager: Optional[Any] = None,
    space_ref: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Human-friendly Chat Space Selection."""
    res = chat_service.list_spaces()
    spaces = res.get('spaces', []) if isinstance(res, dict) else res
    if not spaces:
        print_info("No chat spaces found.")
        return None

    def _title(s: Dict[str, Any]) -> str:
        return s.get('displayName') or s.get('name', 'Untitled Space')

    def _sub(s: Dict[str, Any]) -> str:
        space_type = s.get('spaceType', s.get('type', 'SPACE'))
        return f"Type: {space_type}"

    if space_ref:
        try:
            return GlobalResourceResolver.resolve(
                space_ref, spaces, module="chat", resource_type="Space",
                config_manager=config_manager, title_fn=_title,
                id_fn=lambda s: s.get('name', '')
            )
        except Exception as e:
            print_error(str(e))
            return None
    else:
        selected = GlobalResourceResolver.prompt_selection(
            spaces,
            resource_name="Space",
            module="chat",
            config_manager=config_manager,
            title_fn=_title,
            subtitle_fn=_sub,
            id_fn=lambda s: s.get('name', '')
        )
        return selected


def run_chat_messages_flow(
    chat_service: Any,
    config_manager: Optional[Any] = None,
    space_ref: Optional[str] = None,
    msg_ref: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Human-friendly Chat Message Selection."""
    space = run_chat_spaces_flow(chat_service, config_manager, space_ref)
    if not space:
        return None

    space_name = space.get('name', '')
    res = chat_service.list_messages(space_name=space_name)
    messages = res.get('messages', []) if isinstance(res, dict) else res
    if not messages:
        print_info(f"No messages in space {space.get('displayName', space_name)}.")
        return None

    def _msg_title(m: Dict[str, Any]) -> str:
        sender = m.get('sender', {}).get('displayName', 'User') if isinstance(m.get('sender'), dict) else 'User'
        text = m.get('text', '')
        preview = text[:60] + ('...' if len(text) > 60 else '')
        return f"{sender}: {preview}"

    def _msg_sub(m: Dict[str, Any]) -> str:
        return f"Time: {m.get('createTime', 'Unknown')}"

    if msg_ref:
        try:
            return GlobalResourceResolver.resolve(
                msg_ref, messages, module="chat", resource_type="Message",
                config_manager=config_manager, title_fn=_msg_title,
                id_fn=lambda m: m.get('name', '')
            )
        except Exception as e:
            print_error(str(e))
            return None
    else:
        return GlobalResourceResolver.prompt_selection(
            messages,
            resource_name="Message",
            module="chat",
            config_manager=config_manager,
            title_fn=_msg_title,
            subtitle_fn=_msg_sub,
            id_fn=lambda m: m.get('name', '')
        )


def run_chat_message_delete_flow(
    chat_service: Any,
    config_manager: Optional[Any] = None,
    space_ref: Optional[str] = None,
    msg_ref: Optional[str] = None
) -> bool:
    """Human-friendly Chat message deletion flow."""
    msg = run_chat_messages_flow(chat_service, config_manager, space_ref, msg_ref)
    if not msg:
        return False

    msg_name = msg.get('name', '')
    print()
    print(Fore.WHITE + Style.BRIGHT + "Message Details")
    print(Fore.WHITE + "=" * 60)
    print(f"Author : {msg.get('sender', {}).get('displayName', 'User') if isinstance(msg.get('sender'), dict) else 'User'}")
    print(f"Text   : {msg.get('text', '')}")
    print(f"Time   : {msg.get('createTime', '')}")
    print()

    if not GlobalResourceResolver.confirm_action("Delete this message?", default=False):
        print_info("Operation cancelled.")
        return False

    success = bool(chat_service.delete_message(msg_name))
    if success:
        print_success("Message deleted successfully.")
        return True
    else:
        print_error("Failed to delete message.")
        return False


# ===========================================================================
# 5. DRIVE FLOWS
# ===========================================================================

def run_drive_files_flow(
    drive_service: Any,
    config_manager: Optional[Any] = None,
    query: Optional[str] = None,
    file_ref: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Human-friendly Drive File Selection & Details."""
    res = drive_service.list_files(query=query)
    files = res.get('files', []) if isinstance(res, dict) else res
    if not files:
        print_info("No files found in Google Drive.")
        return None

    def _title(f: Dict[str, Any]) -> str:
        return f.get('name', 'Untitled')

    def _sub(f: Dict[str, Any]) -> str:
        mime = f.get('mimeType', 'Unknown')
        size = f.get('size', 'N/A')
        return f"Type: {mime.split('.')[-1] if '.' in mime else mime} | Size: {size}"

    if file_ref:
        try:
            selected_file = GlobalResourceResolver.resolve(
                file_ref, files, module="drive", resource_type="File",
                config_manager=config_manager, title_fn=_title,
                fetch_fn=lambda fid: drive_service.get_file(fid)
            )
        except Exception as e:
            print_error(str(e))
            return None
    else:
        selected_file = GlobalResourceResolver.prompt_selection(
            files,
            resource_name="File",
            module="drive",
            config_manager=config_manager,
            title_fn=_title,
            subtitle_fn=_sub,
            id_fn=lambda f: f.get('id', ''),
            fetch_fn=lambda fid: drive_service.get_file(fid)
        )
        if not selected_file:
            return None

    print()
    print(Fore.WHITE + Style.BRIGHT + "📁 File Details")
    print(Fore.WHITE + "=" * 60)
    details = {
        'Name': selected_file.get('name', 'Untitled'),
        'ID': selected_file.get('id', ''),
        'MIME Type': selected_file.get('mimeType', 'Unknown'),
        'Size': selected_file.get('size', 'N/A'),
        'Modified': selected_file.get('modifiedTime', 'Unknown'),
        'Web Link': selected_file.get('webViewLink', 'None'),
    }
    print_key_value_pairs(details)
    return selected_file


def run_drive_delete_flow(
    drive_service: Any,
    config_manager: Optional[Any] = None,
    file_ref: Optional[str] = None
) -> bool:
    """Human-friendly Drive File Deletion."""
    selected_file = run_drive_files_flow(drive_service, config_manager, file_ref=file_ref)
    if not selected_file:
        return False

    file_id = selected_file.get('id', '')
    name = selected_file.get('name', 'File')
    if not GlobalResourceResolver.confirm_action(f"Permanently delete '{name}'?", default=False):
        print_info("Operation cancelled.")
        return False

    success = bool(drive_service.delete_file(file_id))
    if success:
        print_success(f"File '{name}' deleted successfully.")
        return True
    else:
        print_error(f"Failed to delete file '{name}'.")
        return False


def run_drive_rename_flow(
    drive_service: Any,
    config_manager: Optional[Any] = None,
    file_ref: Optional[str] = None
) -> bool:
    """Human-friendly Drive File Renaming."""
    selected_file = run_drive_files_flow(drive_service, config_manager, file_ref=file_ref)
    if not selected_file:
        return False

    file_id = selected_file.get('id', '')
    old_name = selected_file.get('name', '')

    try:
        import click
        new_name = click.prompt(f"Enter new name [{old_name}]", default=old_name, show_default=False).strip()
    except Exception:
        print(Fore.CYAN + f"Enter new name [{old_name}]: ", end="")
        new_name = input().strip()
    if not new_name or new_name == old_name:
        print_info("Name unchanged.")
        return False

    print()
    print(Fore.WHITE + Style.BRIGHT + "Review Changes:")
    print(Fore.WHITE + "=" * 60)
    print(Fore.RED + f"  - Current : {old_name}")
    print(Fore.GREEN + f"  + New     : {new_name}")
    print()

    if not GlobalResourceResolver.confirm_action("Apply this change?", default=True):
        print_info("Operation cancelled.")
        return False

    success = bool(drive_service.rename_file(file_id, new_name))
    if success:
        print_success(f"File renamed to '{new_name}'.")
        return True
    else:
        print_error("Failed to rename file.")
        return False


# ===========================================================================
# 6. TASKS FLOWS
# ===========================================================================

def run_tasks_lists_flow(
    tasks_service: Any,
    config_manager: Optional[Any] = None,
    list_ref: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Human-friendly Tasks List Selection."""
    res = tasks_service.list_task_lists()
    task_lists = res.get('items', []) if isinstance(res, dict) else res
    if not task_lists:
        print_info("No task lists found.")
        return None

    if list_ref:
        try:
            return GlobalResourceResolver.resolve(
                list_ref, task_lists, module="tasks", resource_type="Task List",
                config_manager=config_manager,
                title_fn=lambda l: l.get('title', 'Untitled List'),
                id_fn=lambda l: l.get('id', '')
            )
        except Exception as e:
            print_error(str(e))
            return None
    else:
        return GlobalResourceResolver.prompt_selection(
            task_lists,
            resource_name="Task List",
            module="tasks",
            config_manager=config_manager,
            title_fn=lambda l: l.get('title', 'Untitled List'),
            id_fn=lambda l: l.get('id', '')
        )


def run_tasks_items_flow(
    tasks_service: Any,
    config_manager: Optional[Any] = None,
    list_ref: Optional[str] = None,
    task_ref: Optional[str] = None
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Human-friendly Task Item Selection returning (task_list, task)."""
    t_list = run_tasks_lists_flow(tasks_service, config_manager, list_ref)
    if not t_list:
        return None

    list_id = t_list.get('id', '@default')
    res = tasks_service.list_tasks(tasklist_id=list_id)
    tasks = res.get('items', []) if isinstance(res, dict) else res
    if not tasks:
        print_info(f"No tasks found in list '{t_list.get('title', list_id)}'.")
        return None

    def _title(t: Dict[str, Any]) -> str:
        status_icon = "✓ " if t.get('status') == 'completed' else "○ "
        return status_icon + (t.get('title') or 'Untitled Task')

    def _sub(t: Dict[str, Any]) -> str:
        due = t.get('due', 'No due date')
        notes = t.get('notes', '')
        return f"Due: {due} | Notes: {notes[:40] if notes else 'None'}"

    if task_ref:
        try:
            task = GlobalResourceResolver.resolve(
                task_ref, tasks, module="tasks", resource_type="Task",
                config_manager=config_manager, title_fn=lambda t: t.get('title', ''),
                id_fn=lambda t: t.get('id', '')
            )
        except Exception as e:
            print_error(str(e))
            return None
    else:
        task = GlobalResourceResolver.prompt_selection(
            tasks,
            resource_name="Task",
            module="tasks",
            config_manager=config_manager,
            title_fn=_title,
            subtitle_fn=_sub,
            id_fn=lambda t: t.get('id', '')
        )
        if not task:
            return None

    print()
    print(Fore.WHITE + Style.BRIGHT + "✅ Task Details")
    print(Fore.WHITE + "=" * 60)
    details = {
        'Title': task.get('title', 'Untitled'),
        'ID': task.get('id', ''),
        'Status': task.get('status', 'needsAction'),
        'Due': task.get('due', 'None'),
        'Notes': task.get('notes', 'None'),
    }
    print_key_value_pairs(details)
    return t_list, task


def run_task_delete_flow(
    tasks_service: Any,
    config_manager: Optional[Any] = None,
    list_ref: Optional[str] = None,
    task_ref: Optional[str] = None
) -> bool:
    """Human-friendly Task Deletion Flow."""
    res = run_tasks_items_flow(tasks_service, config_manager, list_ref, task_ref)
    if not res:
        return False
    t_list, task = res
    list_id = t_list.get('id', '@default')
    task_id = task.get('id', '')

    if not GlobalResourceResolver.confirm_action(f"Delete task '{task.get('title', '')}'?", default=False):
        print_info("Operation cancelled.")
        return False

    success = bool(tasks_service.delete_task(tasklist_id=list_id, task_id=task_id))
    if success:
        print_success("Task deleted successfully.")
        return True
    else:
        print_error("Failed to delete task.")
        return False


def run_task_update_flow(
    tasks_service: Any,
    config_manager: Optional[Any] = None,
    list_ref: Optional[str] = None,
    task_ref: Optional[str] = None
) -> bool:
    """Human-friendly Task Update Flow (SELECT → VIEW → CHOOSE FIELD → EDIT → VALIDATE → CONFIRM → UPDATE)."""
    res = run_tasks_items_flow(tasks_service, config_manager, list_ref, task_ref)
    if not res:
        return False
    t_list, task = res
    list_id = t_list.get('id', '@default')
    task_id = task.get('id', '')

    fields = [
        {
            'label': 'Title',
            'key': 'title',
            'current': task.get('title', ''),
            'validator': lambda v: (True, v, '') if v.strip() else (False, None, 'Title cannot be empty.'),
        },
        {
            'label': 'Notes',
            'key': 'notes',
            'current': task.get('notes', ''),
        },
        {
            'label': 'Due Date (YYYY-MM-DD)',
            'key': 'due',
            'current': task.get('due', ''),
            'validator': lambda v: _validate_task_due(v),
        },
    ]

    def _display_task(t: Dict[str, Any]) -> None:
        print(f"Title  : {t.get('title', 'Untitled')}")
        print(f"Status : {t.get('status', 'needsAction')}")
        print(f"Due    : {t.get('due', 'None')}")
        print(f"Notes  : {t.get('notes', 'None')}")

    def _update_task(t: Dict[str, Any], changes: Dict[str, Any]) -> bool:
        try:
            tasks_service.update_task(tasklist_id=list_id, task_id=task_id, **changes)
            return True
        except Exception:
            return False

    return GlobalResourceResolver.execute_update_flow(
        resource=task,
        display_details_fn=_display_task,
        fields=fields,
        update_fn=_update_task,
        resource_name="Task"
    )


def _validate_task_due(value: str):
    """Validate ISO date string for task due field."""
    if not value.strip():
        return True, '', ''  # Allow clearing due date
    try:
        from datetime import datetime
        datetime.strptime(value.strip(), '%Y-%m-%d')
        return True, value.strip() + 'T00:00:00.000Z', ''
    except ValueError:
        return False, None, 'Invalid date format. Use YYYY-MM-DD.'


# ===========================================================================
# 7. DOCS FLOWS
# ===========================================================================

def run_docs_flow(
    docs_service: Any,
    drive_service: Optional[Any] = None,
    config_manager: Optional[Any] = None,
    doc_ref: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Human-friendly Google Docs Selection & Details."""
    docs = []
    if drive_service:
        try:
            res = drive_service.list_files(query="mimeType='application/vnd.google-apps.document'")
            docs = res.get('files', []) if isinstance(res, dict) else res
        except Exception:
            docs = []

    if not docs:
        print_info("No Google Docs documents found.")
        return None

    def _title(d: Dict[str, Any]) -> str:
        return d.get('name', d.get('title', 'Untitled Document'))

    if doc_ref:
        try:
            selected_doc = GlobalResourceResolver.resolve(
                doc_ref, docs, module="docs", resource_type="Document",
                config_manager=config_manager, title_fn=_title,
                fetch_fn=lambda did: docs_service.get_document(did)
            )
        except Exception as e:
            print_error(str(e))
            return None
    else:
        selected_doc = GlobalResourceResolver.prompt_selection(
            docs,
            resource_name="Document",
            module="docs",
            config_manager=config_manager,
            title_fn=_title,
            id_fn=lambda d: d.get('id', ''),
            fetch_fn=lambda did: docs_service.get_document(did)
        )
        if not selected_doc:
            return None

    doc_id = selected_doc.get('id', '')
    if docs_service and hasattr(docs_service, 'get_document'):
        try:
            full_doc = docs_service.get_document(doc_id)
            if isinstance(full_doc, dict):
                selected_doc = {**selected_doc, **full_doc}
        except Exception:
            pass
    print()
    print(Fore.WHITE + Style.BRIGHT + "📄 Document Details")
    print(Fore.WHITE + "=" * 60)
    details = {
        'Title': _title(selected_doc),
        'ID': doc_id,
        'MIME Type': selected_doc.get('mimeType', 'application/vnd.google-apps.document'),
    }
    print_key_value_pairs(details)
    return selected_doc


# ===========================================================================
# 8. SHEETS FLOWS
# ===========================================================================

def run_sheets_flow(
    sheets_service: Any,
    drive_service: Optional[Any] = None,
    config_manager: Optional[Any] = None,
    sheet_ref: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Human-friendly Google Sheets Selection & Details."""
    sheets = []
    if drive_service:
        try:
            res = drive_service.list_files(query="mimeType='application/vnd.google-apps.spreadsheet'")
            sheets = res.get('files', []) if isinstance(res, dict) else res
        except Exception:
            sheets = []

    if not sheets:
        print_info("No Google Spreadsheets found.")
        return None

    def _title(s: Dict[str, Any]) -> str:
        return s.get('name', s.get('title', 'Untitled Spreadsheet'))

    if sheet_ref:
        try:
            selected = GlobalResourceResolver.resolve(
                sheet_ref, sheets, module="sheets", resource_type="Spreadsheet",
                config_manager=config_manager, title_fn=_title,
                fetch_fn=lambda sid: sheets_service.get_spreadsheet(sid)
            )
        except Exception as e:
            print_error(str(e))
            return None
    else:
        selected = GlobalResourceResolver.prompt_selection(
            sheets,
            resource_name="Spreadsheet",
            module="sheets",
            config_manager=config_manager,
            title_fn=_title,
            id_fn=lambda s: s.get('id', ''),
            fetch_fn=lambda sid: sheets_service.get_spreadsheet(sid)
        )
        if not selected:
            return None

    sheet_id = selected.get('id', '')
    if sheets_service and hasattr(sheets_service, 'get_spreadsheet'):
        try:
            full_sheet = sheets_service.get_spreadsheet(sheet_id)
            if isinstance(full_sheet, dict):
                selected = {**selected, **full_sheet}
        except Exception:
            pass

    print()
    print(Fore.WHITE + Style.BRIGHT + "📊 Spreadsheet Details")
    print(Fore.WHITE + "=" * 60)
    details = {
        'Title': _title(selected),
        'ID': selected.get('id', ''),
        'MIME Type': selected.get('mimeType', 'application/vnd.google-apps.spreadsheet'),
    }
    print_key_value_pairs(details)
    return selected


# ===========================================================================
# 9. WORKSPACE EVENTS FLOWS
# ===========================================================================

def run_events_subscription_flow(
    events_service: Any,
    config_manager: Optional[Any] = None,
    sub_ref: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Human-friendly Workspace Events Subscription Selection."""
    res = events_service.list_subscriptions()
    subs = res.get('subscriptions', []) if isinstance(res, dict) else res
    if not subs:
        print_info("No event subscriptions found.")
        return None

    def _title(s: Dict[str, Any]) -> str:
        return s.get('name', 'Untitled Subscription')

    def _sub(s: Dict[str, Any]) -> str:
        target = s.get('targetResource', 'Unknown Target')
        state = s.get('state', 'ACTIVE')
        return f"Target: {target} | State: {state}"

    if sub_ref:
        try:
            return GlobalResourceResolver.resolve(
                sub_ref, subs, module="events", resource_type="Subscription",
                config_manager=config_manager, title_fn=_title,
                id_fn=lambda s: s.get('name', '')
            )
        except Exception as e:
            print_error(str(e))
            return None
    else:
        return GlobalResourceResolver.prompt_selection(
            subs,
            resource_name="Subscription",
            module="events",
            config_manager=config_manager,
            title_fn=_title,
            subtitle_fn=_sub,
            id_fn=lambda s: s.get('name', '')
        )


def run_events_delete_flow(
    events_service: Any,
    config_manager: Optional[Any] = None,
    sub_ref: Optional[str] = None
) -> bool:
    """Human-friendly Workspace Events Delete Subscription Flow."""
    selected_sub = run_events_subscription_flow(events_service, config_manager, sub_ref)
    if not selected_sub:
        return False

    sub_name = selected_sub.get('name', '')
    if not GlobalResourceResolver.confirm_action(f"Delete subscription '{sub_name}'?", default=False):
        print_info("Operation cancelled.")
        return False

    success = bool(events_service.delete_subscription(sub_name))
    if success:
        print_success("Subscription deleted successfully.")
        return True
    else:
        print_error("Failed to delete subscription.")
        return False


# ===========================================================================
# 10. APPS SCRIPT FLOWS
# ===========================================================================

def run_script_projects_flow(
    script_service: Any,
    drive_service: Optional[Any] = None,
    config_manager: Optional[Any] = None,
    script_ref: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Human-friendly Apps Script Project Selection."""
    scripts = []
    if drive_service:
        try:
            res = drive_service.list_files(query="mimeType='application/vnd.google-apps.script'")
            scripts = res.get('files', []) if isinstance(res, dict) else res
        except Exception:
            scripts = []
    elif hasattr(script_service, 'list_projects'):
        try:
            res = script_service.list_projects()
            scripts = res.get('projects', []) if isinstance(res, dict) else res
        except Exception:
            scripts = []

    if not scripts:
        print_info("No Apps Script projects found.")
        return None

    def _title(s: Dict[str, Any]) -> str:
        return s.get('name', s.get('title', 'Untitled Script'))

    if script_ref:
        try:
            selected = GlobalResourceResolver.resolve(
                script_ref, scripts, module="script", resource_type="Script Project",
                config_manager=config_manager, title_fn=_title,
                fetch_fn=lambda sid: script_service.get_project(sid)
            )
        except Exception as e:
            print_error(str(e))
            return None
    else:
        selected = GlobalResourceResolver.prompt_selection(
            scripts,
            resource_name="Script Project",
            module="script",
            config_manager=config_manager,
            title_fn=_title,
            id_fn=lambda s: s.get('id', s.get('scriptId', '')),
            fetch_fn=lambda sid: script_service.get_project(sid)
        )
    if selected and script_service and hasattr(script_service, 'get_project'):
        try:
            full_proj = script_service.get_project(selected.get('scriptId') or selected.get('id'))
            if isinstance(full_proj, dict):
                selected = {**selected, **full_proj}
        except Exception:
            pass
    return selected


# ===========================================================================
# 11. ADMIN SDK FLOWS
# ===========================================================================

def run_admin_users_flow(
    admin_service: Any,
    config_manager: Optional[Any] = None,
    user_ref: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Human-friendly Admin SDK User Selection."""
    res = admin_service.list_users()
    users = res.get('users', []) if isinstance(res, dict) else res
    if not users:
        print_info("No users found.")
        return None

    def _title(u: Dict[str, Any]) -> str:
        name = u.get('name', {}).get('fullName', '') if isinstance(u.get('name'), dict) else ''
        email = u.get('primaryEmail', '')
        return f"{name} ({email})" if name else email

    def _sub(u: Dict[str, Any]) -> str:
        suspended = "Suspended" if u.get('suspended') else "Active"
        role = "Admin" if u.get('isAdmin') else "User"
        return f"Status: {suspended} | Role: {role}"

    if user_ref:
        try:
            return GlobalResourceResolver.resolve(
                user_ref, users, module="admin", resource_type="User",
                config_manager=config_manager, title_fn=_title,
                id_fn=lambda u: u.get('primaryEmail', u.get('id', '')),
                fetch_fn=lambda uid: admin_service.get_user(uid)
            )
        except Exception as e:
            print_error(str(e))
            return None
    else:
        return GlobalResourceResolver.prompt_selection(
            users,
            resource_name="User",
            module="admin",
            config_manager=config_manager,
            title_fn=_title,
            subtitle_fn=_sub,
            id_fn=lambda u: u.get('primaryEmail', u.get('id', '')),
            fetch_fn=lambda uid: admin_service.get_user(uid)
        )


def run_admin_user_suspend_flow(
    admin_service: Any,
    config_manager: Optional[Any] = None,
    user_ref: Optional[str] = None
) -> bool:
    """Human-friendly Admin SDK User Suspend Flow."""
    user = run_admin_users_flow(admin_service, config_manager, user_ref)
    if not user:
        return False

    email = user.get('primaryEmail', '')
    is_suspended = user.get('suspended', False)
    new_state = not is_suspended
    action_word = "unsuspend" if is_suspended else "suspend"

    if not GlobalResourceResolver.confirm_action(f"Are you sure you want to {action_word} {email}?", default=False):
        print_info("Operation cancelled.")
        return False

    res = admin_service.suspend_user(email, suspend=new_state)
    if res:
        print_success(f"User {email} successfully {action_word}ed.")
        return True
    else:
        print_error(f"Failed to {action_word} user.")
        return False


# ===========================================================================
# 12. CLOUD IDENTITY FLOWS
# ===========================================================================

def run_identity_groups_flow(
    identity_service: Any,
    config_manager: Optional[Any] = None,
    group_ref: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Human-friendly Cloud Identity Group Selection."""
    res = identity_service.list_groups()
    groups = res.get('groups', []) if isinstance(res, dict) else res
    if not groups:
        print_info("No identity groups found.")
        return None

    def _title(g: Dict[str, Any]) -> str:
        return g.get('displayName') or g.get('name', 'Untitled Group')

    def _sub(g: Dict[str, Any]) -> str:
        desc = g.get('description', '')
        return desc[:60] if desc else 'No description'

    if group_ref:
        try:
            return GlobalResourceResolver.resolve(
                group_ref, groups, module="identity", resource_type="Identity Group",
                config_manager=config_manager, title_fn=_title,
                id_fn=lambda g: g.get('name', '')
            )
        except Exception as e:
            print_error(str(e))
            return None
    else:
        return GlobalResourceResolver.prompt_selection(
            groups,
            resource_name="Identity Group",
            module="identity",
            config_manager=config_manager,
            title_fn=_title,
            subtitle_fn=_sub,
            id_fn=lambda g: g.get('name', '')
        )


# ===========================================================================
# 13. CLOUD SEARCH FLOWS
# ===========================================================================

def run_cloud_search_flow(
    cloud_search_service: Any,
    query: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Human-friendly Cloud Search results browser."""
    if not query:
        try:
            import click
            query = click.prompt("Search Workspace", default="", show_default=False).strip()
        except Exception:
            print(Fore.CYAN + "Search Workspace: ", end="")
            query = input().strip()
        if not query:
            return None

    res = cloud_search_service.search(query=query)
    results = res.get('results', []) if isinstance(res, dict) else res
    if not results:
        print_info(f"No results found for '{query}'.")
        return None

    def _title(r: Dict[str, Any]) -> str:
        meta = r.get('metadata', {}) if isinstance(r.get('metadata'), dict) else {}
        return meta.get('title') or r.get('title', 'Untitled Result')

    def _sub(r: Dict[str, Any]) -> str:
        snippet = r.get('snippet', {}).get('snippet', '') if isinstance(r.get('snippet'), dict) else ''
        return snippet[:80] if snippet else 'No snippet'

    selected = GlobalResourceResolver.prompt_selection(
        results,
        resource_name="Search Result",
        title_fn=_title,
        subtitle_fn=_sub,
        id_fn=lambda r: r.get('url', r.get('title', ''))
    )
    if selected:
        print()
        print(Fore.WHITE + Style.BRIGHT + "🔍 Search Result Details")
        print(Fore.WHITE + "=" * 60)
        details = {
            'Title': _title(selected),
            'URL': selected.get('url', 'None'),
            'Snippet': selected.get('snippet', {}).get('snippet', 'None') if isinstance(selected.get('snippet'), dict) else 'None',
        }
        print_key_value_pairs(details)
    return selected


# ===========================================================================
# 14. FORMS FLOWS
# ===========================================================================

def run_forms_flow(
    forms_service: Any,
    drive_service: Optional[Any] = None,
    config_manager: Optional[Any] = None,
    form_ref: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Human-friendly Google Forms Selection & Details."""
    forms = []
    if drive_service:
        try:
            res = drive_service.list_files(query="mimeType='application/vnd.google-apps.form'")
            forms = res.get('files', []) if isinstance(res, dict) else res
        except Exception:
            forms = []

    if not forms:
        print_info("No Google Forms found.")
        return None

    def _title(f: Dict[str, Any]) -> str:
        return f.get('name', f.get('title', 'Untitled Form'))

    if form_ref:
        try:
            selected = GlobalResourceResolver.resolve(
                form_ref, forms, module="forms", resource_type="Form",
                config_manager=config_manager, title_fn=_title,
                fetch_fn=lambda fid: forms_service.get_form(fid)
            )
        except Exception as e:
            print_error(str(e))
            return None
    else:
        selected = GlobalResourceResolver.prompt_selection(
            forms,
            resource_name="Form",
            module="forms",
            config_manager=config_manager,
            title_fn=_title,
            id_fn=lambda f: f.get('id', ''),
            fetch_fn=lambda fid: forms_service.get_form(fid)
        )
        if not selected:
            return None

    form_id = selected.get('id', '')
    if forms_service and hasattr(forms_service, 'get_form'):
        try:
            full_form = forms_service.get_form(form_id)
            if isinstance(full_form, dict):
                selected = {**selected, **full_form}
        except Exception:
            pass

    print()
    print(Fore.WHITE + Style.BRIGHT + "📋 Form Details")
    print(Fore.WHITE + "=" * 60)
    details = {
        'Title': _title(selected),
        'ID': selected.get('id', ''),
        'MIME Type': selected.get('mimeType', 'application/vnd.google-apps.form'),
    }
    print_key_value_pairs(details)
    return selected


# ===========================================================================
# 15. DRIVE ACTIVITY FLOWS
# ===========================================================================

def run_drive_activity_flow(
    activity_service: Any,
    page_size: int = 10
) -> Optional[Dict[str, Any]]:
    """Human-friendly Drive Activity Results Browser."""
    if hasattr(activity_service, 'query_activity'):
        res = activity_service.query_activity(page_size=page_size)
    elif hasattr(activity_service, 'list_activities'):
        res = activity_service.list_activities(page_size=page_size)
    else:
        res = []
    activities = res.get('activities', []) if isinstance(res, dict) else res
    if not activities:
        print_info("No recent Drive activity found.")
        return None

    def _title(act: Dict[str, Any]) -> str:
        primary = act.get('primaryActionDetail', {})
        action_name = list(primary.keys())[0] if isinstance(primary, dict) and primary else 'Activity'
        targets = act.get('targets', [])
        target_name = targets[0].get('driveItem', {}).get('title', 'Item') if targets and isinstance(targets[0], dict) else 'Item'
        return f"{action_name.capitalize()}: {target_name}"

    def _sub(act: Dict[str, Any]) -> str:
        time_val = act.get('timestamp', act.get('timeRange', {}).get('endTime', 'Unknown time'))
        actors = act.get('actors', [])
        actor_name = actors[0].get('user', {}).get('knownUser', {}).get('personName', 'User') if actors and isinstance(actors[0], dict) else 'User'
        return f"By: {actor_name} | At: {time_val}"

    selected = GlobalResourceResolver.prompt_selection(
        activities,
        resource_name="Activity",
        title_fn=_title,
        subtitle_fn=_sub
    )
    if selected:
        print()
        print(Fore.WHITE + Style.BRIGHT + "📈 Drive Activity Details")
        print(Fore.WHITE + "=" * 60)
        primary = selected.get('primaryActionDetail', {})
        action_name = list(primary.keys())[0] if isinstance(primary, dict) and primary else 'Activity'
        details = {
            'Action': action_name,
            'Timestamp': selected.get('timestamp', 'Unknown'),
            'Targets': len(selected.get('targets', [])),
            'Actors': len(selected.get('actors', [])),
        }
        print_key_value_pairs(details)
    return selected
