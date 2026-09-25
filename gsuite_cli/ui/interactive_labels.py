"""
Interactive Gmail Labels workflows for Hermes CLI.
Implements the human-friendly SEARCH -> SELECT -> VIEW -> ACTION pattern for:
- List all labels (view emails, rename, delete)
- Apply label to message (search email, view email, select existing or create new label, confirm, apply)
- Remove label from message (search email, view email, select from applied labels, confirm, remove)
"""

import sys
import re
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from colorama import Fore, Style

from ..utils.formatters import print_error, print_info, print_success, print_warning, clear_screen

SEP_MAJOR = "=" * 50
SEP_MINOR = "-" * 50

SYSTEM_LABEL_MAP: Dict[str, str] = {
    'INBOX': 'Inbox',
    'SENT': 'Sent',
    'DRAFT': 'Draft',
    'SPAM': 'Spam',
    'TRASH': 'Trash',
    'STARRED': 'Starred',
    'IMPORTANT': 'Important',
    'UNREAD': 'Unread',
    'CHAT': 'Chat',
    'CATEGORY_PERSONAL': 'Personal Category',
    'CATEGORY_SOCIAL': 'Social Category',
    'CATEGORY_PROMOTIONS': 'Promotions Category',
    'CATEGORY_UPDATES': 'Updates Category',
    'CATEGORY_FORUMS': 'Forums Category',
}


def _friendly_label_name(label_id: str, label_name: Optional[str] = None) -> str:
    """Return human-friendly name for a system or custom label."""
    upper_id = label_id.upper()
    if upper_id in SYSTEM_LABEL_MAP:
        return SYSTEM_LABEL_MAP[upper_id]
    if label_name:
        return label_name
    return label_id


def _format_sender(from_str: Optional[str]) -> str:
    """Extract display name or clean email address from From header."""
    if not from_str:
        return "Unknown Sender"
    from email.utils import parseaddr
    name, addr = parseaddr(from_str)
    return name if name else (addr or from_str)


def _format_message_date(date_str: Optional[str]) -> str:
    """Format RFC 2822 email date into human-readable string like 'Today, 10:30 AM' or 'Sep 5, 2026, 4:20 PM'."""
    if not date_str:
        return "Unknown date"
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        now = datetime.now(dt.tzinfo)
        today = now.date()
        msg_date = dt.date()
        time_str = dt.strftime("%I:%M %p").lstrip('0')
        if not time_str:
            time_str = dt.strftime("%I:%M %p")
        if msg_date == today:
            return f"Today, {time_str}"
        elif msg_date == today - timedelta(days=1):
            return f"Yesterday, {time_str}"
        elif msg_date.year == today.year:
            return f"{dt.strftime('%b %d')}, {time_str}"
        else:
            return f"{dt.strftime('%b %d, %Y')}, {time_str}"
    except Exception:
        return str(date_str)


def _prompt_input(prompt_text: str = "> ") -> str:
    """Read a stripped line from stdin, returning empty string on EOF/interrupt."""
    try:
        return input(prompt_text).strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def _prompt_confirm(prompt_text: str, default: bool = False) -> bool:
    """Prompt user with [y/N] or [Y/n] confirmation with re-prompt on invalid input."""
    default_str = "[Y/n]" if default else "[y/N]"
    while True:
        try:
            val = input(f"{prompt_text} {default_str}: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return default
        if not val:
            return default
        if val in ('y', 'yes'):
            return True
        if val in ('n', 'no'):
            return False
        print(Fore.RED + "Please enter 'y' or 'n'.")


# ===========================================================================
# 1. MAIN LABELS MENU
# ===========================================================================

def run_labels_menu(gmail_service: Any) -> None:
    """Display the main Labels MENU and route user choices."""
    while True:
        clear_screen()
        print()
        print(Fore.WHITE + Style.BRIGHT + "Labels MENU")
        print(Fore.WHITE + SEP_MAJOR)
        print()
        print(Fore.WHITE + "Manage Gmail labels")
        print()
        print(Fore.WHITE + "[1] List all labels")
        print(Fore.WHITE + "[2] Apply label to message")
        print(Fore.WHITE + "[3] Remove label from message")
        print()
        print(Fore.WHITE + "[b] Back to Gmail Menu")
        print(Fore.WHITE + "[0] Exit")
        print()

        while True:
            try:
                choice = input(Fore.CYAN + "Choose an option [1-3, b]: " + Style.RESET_ALL).strip().lower()
            except (EOFError, KeyboardInterrupt):
                return

            if choice in ('b', 'back'):
                return
            elif choice == '0':
                sys.exit(0)
            elif choice == '1':
                run_list_labels_flow(gmail_service)
                break
            elif choice == '2':
                run_apply_label_flow(gmail_service)
                break
            elif choice == '3':
                run_remove_label_flow(gmail_service)
                break
            else:
                print(Fore.RED + "✗ Invalid selection.")



# ===========================================================================
# 2. LIST ALL LABELS WORKFLOW
# ===========================================================================

def run_list_labels_flow(gmail_service: Any) -> None:
    """List system and custom labels; allow selecting a label to view emails, rename, or delete."""
    while True:
        try:
            raw_labels = gmail_service.get_labels()
        except Exception as exc:
            print_error(f"Failed to retrieve labels: {exc}")
            return

        if not raw_labels:
            print_info("No labels found.")
            return

        # Separate system vs custom labels
        system_labels: List[Dict[str, Any]] = []
        custom_labels: List[Dict[str, Any]] = []

        for lbl in raw_labels:
            ltype = str(lbl.get('type', '')).lower()
            lid = str(lbl.get('id', ''))
            if ltype == 'system' or lid.upper() in SYSTEM_LABEL_MAP:
                system_labels.append(lbl)
            else:
                custom_labels.append(lbl)

        # Build numbered selection mapping
        all_ordered: List[Tuple[Dict[str, Any], str]] = []  # (label, type_str)

        clear_screen()
        print()
        print(Fore.WHITE + Style.BRIGHT + "Gmail Labels")
        print(Fore.WHITE + SEP_MAJOR)

        idx = 1
        if system_labels:
            print()
            print(Fore.WHITE + Style.BRIGHT + "System Labels")
            print(Fore.WHITE + SEP_MINOR)
            for lbl in system_labels:
                display_name = _friendly_label_name(lbl.get('id', ''), lbl.get('name'))
                print(f"[{idx}] {display_name}")
                all_ordered.append((lbl, 'System'))
                idx += 1

        if custom_labels:
            print()
            print(Fore.WHITE + Style.BRIGHT + "Custom Labels")
            print(Fore.WHITE + SEP_MINOR)
            for lbl in custom_labels:
                display_name = lbl.get('name') or lbl.get('id', '')
                print(f"[{idx}] {display_name}")
                all_ordered.append((lbl, 'Custom'))
                idx += 1

        print()
        print(Fore.WHITE + "[b] Back")
        print()

        while True:
            try:
                choice = input(Fore.CYAN + "Select label: " + Style.RESET_ALL).strip().lower()
            except (EOFError, KeyboardInterrupt):
                return

            if choice in ('b', 'back'):
                return

            if choice.isdigit():
                sel_idx = int(choice)
                if 1 <= sel_idx <= len(all_ordered):
                    selected_lbl, lbl_type = all_ordered[sel_idx - 1]
                    _handle_selected_label_actions(gmail_service, selected_lbl, lbl_type)
                    break
                else:
                    print(Fore.RED + "✗ Invalid selection.")
            else:
                print(Fore.RED + "✗ Invalid selection.")


def _handle_selected_label_actions(gmail_service: Any, label: Dict[str, Any], label_type: str) -> None:
    """View details and perform supported actions for a selected label."""
    label_id = label.get('id', '')
    display_name = _friendly_label_name(label_id, label.get('name'))

    while True:
        clear_screen()
        print()
        print(Fore.WHITE + Style.BRIGHT + display_name)
        print(Fore.WHITE + SEP_MINOR)
        print(f"Name       : {display_name}")
        print(f"Type       : {label_type}")
        print()
        print(Fore.WHITE + "[1] View emails")
        if label_type == 'Custom':
            print(Fore.WHITE + "[2] Rename label")
            print(Fore.WHITE + "[3] Delete label")
        print()
        print(Fore.WHITE + "[b] Back")
        print()

        valid_opts = ['1', 'b', 'back']
        if label_type == 'Custom':
            valid_opts.extend(['2', '3'])

        while True:
            try:
                choice = input(Fore.CYAN + f"Choose an option [{'1-3' if label_type == 'Custom' else '1'}, b]: " + Style.RESET_ALL).strip().lower()
            except (EOFError, KeyboardInterrupt):
                return

            if choice in ('b', 'back'):
                return
            elif choice == '1':
                _view_emails_with_label(gmail_service, label_id, display_name)
                break
            elif choice == '2' and label_type == 'Custom':
                new_name = _rename_label_flow(gmail_service, label_id, display_name)
                if new_name:
                    display_name = new_name
                    label['name'] = new_name
                break
            elif choice == '3' and label_type == 'Custom':
                deleted = _delete_label_flow(gmail_service, label_id, display_name)
                if deleted:
                    return
                break
            else:
                print(Fore.RED + "✗ Invalid selection.")


def _view_emails_with_label(gmail_service: Any, label_id: str, display_name: str) -> None:
    """List emails with the given label and let user view email details."""
    query = f"label:{label_id}"
    try:
        res = gmail_service.list_messages(query=query, max_results=20)
        messages = res if isinstance(res, list) else res.get('messages', [])
    except Exception as exc:
        print_error(f"Failed to fetch emails: {exc}")
        return

    clear_screen()
    print()
    print(Fore.WHITE + Style.BRIGHT + f"Emails in {display_name}")
    print(Fore.WHITE + SEP_MINOR)
    print()

    if not messages:
        print(Fore.YELLOW + f"No emails found with label: {display_name}")
        print()
        print(Fore.WHITE + "[b] Back")
        print()
        _prompt_input(Fore.CYAN + "Press Enter or 'b' to return: " + Style.RESET_ALL)
        return

    for idx, msg in enumerate(messages, 1):
        sender = _format_sender(msg.get('from', ''))
        subject = msg.get('subject') or '(No Subject)'
        date_display = _format_message_date(msg.get('date', ''))
        print(f"[{idx}] {Fore.WHITE + Style.BRIGHT}{sender}{Style.RESET_ALL}")
        print(f"    {subject}")
        print(f"    {Fore.CYAN}{date_display}{Style.RESET_ALL}")
        print()

    print(Fore.WHITE + "[b] Back")
    print()

    while True:
        choice = _prompt_input(Fore.CYAN + f"Select email [1-{len(messages)}, b]: " + Style.RESET_ALL).lower()
        if choice in ('b', 'back', ''):
            return
        if choice.isdigit() and 1 <= int(choice) <= len(messages):
            sel_msg = messages[int(choice) - 1]
            _show_email_details_screen(gmail_service, sel_msg)
            return
        print(Fore.RED + "✗ Invalid selection.")


def _rename_label_flow(gmail_service: Any, label_id: str, current_name: str) -> Optional[str]:
    """Prompt user for new label name, validate, confirm, and update."""
    clear_screen()
    print()
    print(Fore.WHITE + Style.BRIGHT + "Rename Label")
    print(Fore.WHITE + SEP_MINOR)
    print(f"Current name: {current_name}")
    print("New label name:")
    new_name = _prompt_input("> ")
    if not new_name or new_name.lower() in ('b', 'back'):
        return None

    if new_name.lower() == current_name.lower():
        print_info("Label name unchanged.")
        return None

    # Check against existing labels
    try:
        existing_labels = gmail_service.get_labels()
        for lbl in existing_labels:
            if str(lbl.get('name', '')).lower() == new_name.lower():
                print_warning(f"Label '{new_name}' already exists.")
                return None
    except Exception:
        pass

    if not _prompt_confirm(f"Rename label \"{current_name}\" to \"{new_name}\"?", default=True):
        print_info("Rename cancelled.")
        return None

    res = gmail_service.rename_label(label_id, new_name)
    if res:
        print_success(f"✓ Label renamed to \"{new_name}\" successfully.")
        return new_name
    return None


def _delete_label_flow(gmail_service: Any, label_id: str, current_name: str) -> bool:
    """Prompt user for confirmation and delete a label."""
    clear_screen()
    print()
    print(Fore.WHITE + Style.BRIGHT + "Delete Label")
    print(Fore.WHITE + SEP_MINOR)
    print()
    if not _prompt_confirm(f"Delete label \"{current_name}\"? This will not delete the messages.", default=False):
        print_info("Deletion cancelled.")
        return False

    success = gmail_service.delete_label(label_id)
    if success:
        print_success(f"✓ Label \"{current_name}\" deleted successfully.")
        return True
    return False


# ===========================================================================
# 3. EMAIL SEARCH & SELECTION HELPERS
# ===========================================================================

def _search_and_select_email(gmail_service: Any, screen_title: str) -> Optional[Dict[str, Any]]:
    """Search for emails and let user select one by number with pagination support.

    Returns the selected message dictionary or None if user went back.
    """
    while True:
        clear_screen()
        print()
        print(Fore.WHITE + Style.BRIGHT + screen_title)
        print(Fore.WHITE + SEP_MINOR)
        print()

        while True:
            print("Search email:")
            query = _prompt_input("> ")

            if query.lower() in ('b', 'back'):
                return None
            if not query.strip():
                print(Fore.RED + "✗ Search query cannot be empty.")
                print()
                continue
            break

        # Perform search using Gmail syntax
        try:
            res = gmail_service.search_messages(query=query.strip(), max_results=30)
            messages = res if isinstance(res, list) else res.get('messages', [])
        except Exception as exc:
            print_error(f"Failed to search emails: {exc}")
            continue

        if not messages:
            clear_screen()
            print()
            print(Fore.WHITE + Style.BRIGHT + "Search Results")
            print(Fore.WHITE + SEP_MINOR)
            print()
            print(Fore.YELLOW + f"No emails found for: {query.strip()}")
            print()
            print(Fore.WHITE + "[1] Search Again")
            print(Fore.WHITE + "[b] Back")
            print()

            while True:
                choice = _prompt_input(Fore.CYAN + "Choose an option [1, b]: " + Style.RESET_ALL).lower()
                if choice in ('b', 'back'):
                    return None
                elif choice == '1':
                    break
                else:
                    print(Fore.RED + "✗ Invalid selection.")
            continue

        # Show paginated search results
        selected_msg = _paginate_and_select_message(messages)
        if selected_msg is not None:
            return selected_msg
        # If user pressed back in search results, loop to re-prompt search (which clears screen)


def _paginate_and_select_message(messages: List[Dict[str, Any]], page_size: int = 10) -> Optional[Dict[str, Any]]:
    """Display messages in pages and allow selecting by number or navigating with [n]/[p]."""
    total = len(messages)
    page = 0
    num_pages = (total + page_size - 1) // page_size

    while True:
        clear_screen()
        start_idx = page * page_size
        end_idx = min(start_idx + page_size, total)
        current_page_messages = messages[start_idx:end_idx]

        print()
        print(Fore.WHITE + Style.BRIGHT + "Search Results")
        print(Fore.WHITE + SEP_MINOR)
        print()

        for i, msg in enumerate(current_page_messages, start=start_idx + 1):
            sender = _format_sender(msg.get('from', ''))
            subject = msg.get('subject') or '(No Subject)'
            date_display = _format_message_date(msg.get('date', ''))
            print(f"[{i}] {Fore.WHITE + Style.BRIGHT}{sender}{Style.RESET_ALL}")
            print(f"    {subject}")
            print(f"    {Fore.CYAN}{date_display}{Style.RESET_ALL}")
            print()

        nav_hints = []
        if page > 0:
            nav_hints.append("[p] Previous page")
        if page < num_pages - 1:
            nav_hints.append("[n] Next page")
        nav_hints.append("[b] Back")

        for hint in nav_hints:
            print(Fore.WHITE + hint)
        print()

        range_str = f"1-{total}" if total > 1 else "1"
        prompt_str = f"Select email [{range_str}, b]: "

        while True:
            choice = _prompt_input(Fore.CYAN + prompt_str + Style.RESET_ALL).lower()

            if choice in ('b', 'back'):
                return None
            if choice == 'n' and page < num_pages - 1:
                page += 1
                break
            if choice == 'p' and page > 0:
                page -= 1
                break
            if choice.isdigit():
                val = int(choice)
                if 1 <= val <= total:
                    return messages[val - 1]
                else:
                    print(Fore.RED + "✗ Invalid selection.")
            else:
                print(Fore.RED + "✗ Invalid selection.")


def _show_email_details_screen(gmail_service: Any, message: Dict[str, Any]) -> None:
    """Read-only view of email details with current labels."""
    clear_screen()
    msg_id = message.get('id', '')
    if msg_id:
        try:
            full = gmail_service.get_message(msg_id, format='full')
            if full:
                message = full
        except Exception:
            pass

    sender = message.get('from', 'Unknown')
    to = message.get('to', 'Unknown')
    subject = message.get('subject') or '(No Subject)'
    date_display = _format_message_date(message.get('date', ''))
    label_ids = message.get('label_ids', [])

    friendly_labels = []
    for lid in label_ids:
        friendly_labels.append(_friendly_label_name(lid))

    print()
    print(Fore.WHITE + Style.BRIGHT + "Email")
    print(Fore.WHITE + SEP_MINOR)
    print()
    print(f"From    : {sender}")
    print(f"To      : {to}")
    print(f"Subject : {subject}")
    print(f"Date    : {date_display}")
    print()
    print(Fore.WHITE + Style.BRIGHT + "Current Labels")
    print(Fore.WHITE + SEP_MINOR)
    if friendly_labels:
        for fl in friendly_labels:
            print(fl)
    else:
        print("(None)")
    print()
    print(Fore.WHITE + SEP_MINOR)
    print()
    print(Fore.WHITE + "[b] Back")
    print()
    _prompt_input(Fore.CYAN + "Press Enter or 'b' to return: " + Style.RESET_ALL)


# ===========================================================================
# 4. APPLY LABEL WORKFLOW
# ===========================================================================

def run_apply_label_flow(gmail_service: Any) -> None:
    """Execute SEARCH -> SELECT -> VIEW -> APPLY/CREATE LABEL -> CONFIRM -> APPLY."""
    while True:
        selected_msg = _search_and_select_email(gmail_service, "Apply Label")
        if not selected_msg:
            return

        msg_id = selected_msg.get('id', '')
        # Fetch complete message headers to get accurate label list
        try:
            full_msg = gmail_service.get_message(msg_id, format='full')
            if full_msg:
                selected_msg = full_msg
        except Exception:
            pass

        # Step 3 — View Selected Email before applying label
        action_chosen = _show_email_view_for_apply(selected_msg)
        if not action_chosen:
            continue  # User pressed back, re-select from search or search again

        # Step 4 — Select Existing Label or Create New Label
        applied = _select_and_apply_label_flow(gmail_service, selected_msg)
        if applied:
            return  # Completed successfully


def _show_email_view_for_apply(message: Dict[str, Any]) -> bool:
    """Display selected email details and ask [1] Apply Label or [b] Back."""
    sender = message.get('from', 'Unknown')
    to = message.get('to', 'Unknown')
    subject = message.get('subject') or '(No Subject)'
    date_display = _format_message_date(message.get('date', ''))
    label_ids = message.get('label_ids', [])

    friendly_labels = []
    for lid in label_ids:
        friendly_labels.append(_friendly_label_name(lid))

    clear_screen()
    print()
    print(Fore.WHITE + Style.BRIGHT + "Email")
    print(Fore.WHITE + SEP_MINOR)
    print()
    print(f"From    : {sender}")
    print(f"To      : {to}")
    print(f"Subject : {subject}")
    print(f"Date    : {date_display}")
    print()
    print(Fore.WHITE + Style.BRIGHT + "Current Labels")
    print(Fore.WHITE + SEP_MINOR)
    if friendly_labels:
        for fl in friendly_labels:
            print(fl)
    else:
        print("(None)")
    print()
    print(Fore.WHITE + SEP_MINOR)
    print()
    print(Fore.WHITE + "[1] Apply Label")
    print(Fore.WHITE + "[b] Back")
    print()

    while True:
        choice = _prompt_input(Fore.CYAN + "Choose an option [1, b]: " + Style.RESET_ALL).lower()
        if choice in ('b', 'back'):
            return False
        if choice == '1':
            return True
        print(Fore.RED + "✗ Invalid selection.")


def _select_and_apply_label_flow(gmail_service: Any, message: Dict[str, Any]) -> bool:
    """Prompt user to choose an existing label or create a new label, confirm, and apply."""
    msg_id = message.get('id', '')
    subject = message.get('subject') or '(No Subject)'
    current_label_ids = set(message.get('label_ids', []))

    while True:
        try:
            raw_labels = gmail_service.get_labels()
        except Exception as exc:
            print_error(f"Failed to retrieve labels: {exc}")
            return False

        # Gather apply-able labels: Custom labels + key system labels (e.g. STARRED, IMPORTANT)
        available_labels: List[Tuple[str, str, str]] = []  # (id, name, display_name)
        existing_names: List[str] = []

        # System labels first (Starred, Important)
        for lbl in raw_labels:
            lid = lbl.get('id', '')
            lname = lbl.get('name', '')
            existing_names.append(lname or lid)

        # Custom labels
        for lbl in raw_labels:
            lid = lbl.get('id', '')
            lname = lbl.get('name', '')
            ltype = str(lbl.get('type', '')).lower()
            if ltype != 'system' and lid.upper() not in SYSTEM_LABEL_MAP:
                available_labels.append((lid, lname, lname))

        # Also add select system labels if present
        for sys_id in ['STARRED', 'IMPORTANT']:
            for lbl in raw_labels:
                if lbl.get('id', '').upper() == sys_id:
                    available_labels.append((sys_id, sys_id, SYSTEM_LABEL_MAP.get(sys_id, sys_id)))
                    break

        clear_screen()
        print()
        print(Fore.WHITE + Style.BRIGHT + "Select Label")
        print(Fore.WHITE + SEP_MINOR)
        print()

        idx = 1
        for lid, lname, disp in available_labels:
            print(f"[{idx}] {disp}")
            idx += 1

        create_new_idx = idx
        print(f"[{create_new_idx}] Create New Label")
        print()
        print(Fore.WHITE + "[b] Back")
        print()

        prompt_str = f"Select label [1-{create_new_idx}, b]: "
        while True:
            choice = _prompt_input(Fore.CYAN + prompt_str + Style.RESET_ALL).lower()

            if choice in ('b', 'back'):
                return False

            if choice.isdigit():
                val = int(choice)
                if 1 <= val < create_new_idx:
                    # Selected an existing label
                    sel_id, sel_name, sel_display = available_labels[val - 1]

                    # Check if already applied
                    if sel_id in current_label_ids or sel_name in current_label_ids or sel_display in current_label_ids:
                        clear_screen()
                        print()
                        print_success(f"✓ Label \"{sel_display}\" is already applied to this email.")
                        return False

                    # Confirm before apply
                    clear_screen()
                    print()
                    print(Fore.WHITE + Style.BRIGHT + "Apply Label")
                    print(Fore.WHITE + SEP_MINOR)
                    print()
                    print(f"Email : {subject}")
                    print(f"Label : {sel_display}")
                    print()

                    if not _prompt_confirm("Apply this label?", default=True):
                        print_info("Apply cancelled.")
                        break  # Return to label selection (outer loop clears screen)

                    # Perform apply
                    success = gmail_service.modify_labels(msg_id, add_labels=[sel_name or sel_id])
                    if success:
                        clear_screen()
                        print()
                        print_success(f"✓ Label \"{sel_display}\" applied to the email.")
                        return True
                    else:
                        print_error(f"Failed to apply label \"{sel_display}\".")
                        return False

                elif val == create_new_idx:
                    # Create New Label flow
                    created_name = _create_new_label_flow(gmail_service, existing_names, msg_id, subject)
                    if created_name:
                        return True
                    break  # Cancelled create, redisplay Select Label menu (outer loop clears screen)
                else:
                    print(Fore.RED + "✗ Invalid selection.")
            else:
                print(Fore.RED + "✗ Invalid selection.")


def _create_new_label_flow(
    gmail_service: Any,
    existing_names: List[str],
    msg_id: str,
    subject: str
) -> Optional[str]:
    """Prompt user for new label name, validate, handle duplicates, confirm, create, and apply."""
    while True:
        clear_screen()
        print()
        print(Fore.WHITE + Style.BRIGHT + "Create New Label")
        print(Fore.WHITE + SEP_MINOR)
        print()

        while True:
            print("Label name:")
            name_input = _prompt_input("> ")

            if name_input.lower() in ('b', 'back'):
                return None
            if not name_input.strip():
                print(Fore.RED + "✗ Label name cannot be empty.")
                print()
                continue
            break

        # Check duplicate
        duplicate_match = None
        for existing in existing_names:
            if existing.lower() == name_input.strip().lower():
                duplicate_match = existing
                break

        if duplicate_match:
            clear_screen()
            print()
            print_warning(f"Label \"{duplicate_match}\" already exists.")
            print()
            print(Fore.WHITE + "[1] Apply existing label")
            print(Fore.WHITE + "[2] Enter another name")
            print(Fore.WHITE + "[b] Back")
            print()

            while True:
                dup_choice = _prompt_input(Fore.CYAN + "Choose an option [1-2, b]: " + Style.RESET_ALL).lower()
                if dup_choice in ('b', 'back'):
                    return None
                elif dup_choice == '1':
                    # Apply the existing label directly
                    clear_screen()
                    print()
                    print(Fore.WHITE + Style.BRIGHT + "Apply Label")
                    print(Fore.WHITE + SEP_MINOR)
                    print()
                    print(f"Email : {subject}")
                    print(f"Label : {duplicate_match}")
                    print()
                    if _prompt_confirm("Apply this label?", default=True):
                        success = gmail_service.modify_labels(msg_id, add_labels=[duplicate_match])
                        if success:
                            clear_screen()
                            print()
                            print_success(f"✓ Label \"{duplicate_match}\" applied to the email.")
                            return duplicate_match
                    return None
                elif dup_choice == '2':
                    break  # Loop to re-prompt label name
                else:
                    print(Fore.RED + "✗ Invalid selection.")
            continue

        # Valid new label name -> Prompt confirmation
        clear_screen()
        print()
        print(Fore.WHITE + Style.BRIGHT + "Create New Label")
        print(Fore.WHITE + SEP_MINOR)
        print()
        print(f"Label name : {name_input.strip()}")
        print()
        if not _prompt_confirm(f"Create label \"{name_input.strip()}\"?", default=True):
            print_info("Label creation cancelled.")
            return None

        # 1. Create the label
        new_label = gmail_service.create_label(name_input.strip())
        if not new_label:
            print_error(f"Failed to create label \"{name_input.strip()}\".")
            return None

        clear_screen()
        print()
        print_success(f"✓ Label \"{name_input.strip()}\" created.")

        # 2. Automatically apply to email
        success = gmail_service.modify_labels(msg_id, add_labels=[name_input.strip()])
        if success:
            print_success(f"✓ Label \"{name_input.strip()}\" applied to the email.")
            return name_input.strip()
        else:
            print_error(f"Failed to apply newly created label \"{name_input.strip()}\" to email.")
            return None


# ===========================================================================
# 5. REMOVE LABEL WORKFLOW
# ===========================================================================

def run_remove_label_flow(gmail_service: Any) -> None:
    """Execute SEARCH -> SELECT EMAIL -> VIEW EMAIL -> SELECT LABEL TO REMOVE -> CONFIRM -> REMOVE."""
    while True:
        selected_msg = _search_and_select_email(gmail_service, "Remove Label")
        if not selected_msg:
            return

        msg_id = selected_msg.get('id', '')
        try:
            full_msg = gmail_service.get_message(msg_id, format='full')
            if full_msg:
                selected_msg = full_msg
        except Exception:
            pass

        # Step 3 — View Selected Email
        action_chosen = _show_email_view_for_remove(selected_msg)
        if not action_chosen:
            continue

        # Step 4 & 5 — Select Label to Remove, Confirm, Remove
        removed = _select_and_remove_label_flow(gmail_service, selected_msg)
        if removed:
            return


def _show_email_view_for_remove(message: Dict[str, Any]) -> bool:
    """Display selected email details and ask [1] Remove Label or [b] Back."""
    sender = message.get('from', 'Unknown')
    to = message.get('to', 'Unknown')
    subject = message.get('subject') or '(No Subject)'
    date_display = _format_message_date(message.get('date', ''))
    label_ids = message.get('label_ids', [])

    friendly_labels = []
    for lid in label_ids:
        friendly_labels.append(_friendly_label_name(lid))

    clear_screen()
    print()
    print(Fore.WHITE + Style.BRIGHT + "Email")
    print(Fore.WHITE + SEP_MINOR)
    print()
    print(f"From    : {sender}")
    print(f"To      : {to}")
    print(f"Subject : {subject}")
    print(f"Date    : {date_display}")
    print()
    print(Fore.WHITE + Style.BRIGHT + "Current Labels")
    print(Fore.WHITE + SEP_MINOR)
    if friendly_labels:
        for fl in friendly_labels:
            print(fl)
    else:
        print("(None)")
    print()
    print(Fore.WHITE + SEP_MINOR)
    print()
    print(Fore.WHITE + "[1] Remove Label")
    print(Fore.WHITE + "[b] Back")
    print()

    while True:
        choice = _prompt_input(Fore.CYAN + "Choose an option [1, b]: " + Style.RESET_ALL).lower()
        if choice in ('b', 'back'):
            return False
        if choice == '1':
            return True
        print(Fore.RED + "✗ Invalid selection.")


def _select_and_remove_label_flow(gmail_service: Any, message: Dict[str, Any]) -> bool:
    """Display ONLY labels currently applied to this message and remove the chosen one."""
    msg_id = message.get('id', '')
    subject = message.get('subject') or '(No Subject)'
    label_ids = message.get('label_ids', [])

    if not label_ids:
        clear_screen()
        print()
        print_info("No removable labels found on this email.")
        return False

    # Get all labels to resolve user label IDs to their actual names
    id_to_name: Dict[str, str] = {}
    try:
        raw_labels = gmail_service.get_labels()
        for lbl in raw_labels:
            lid = lbl.get('id', '')
            lname = lbl.get('name', '')
            id_to_name[lid] = lname
    except Exception:
        pass

    # Build list of applied labels to display
    removable: List[Tuple[str, str]] = []  # (identifier_to_remove, display_name)
    for lid in label_ids:
        disp = id_to_name.get(lid) or _friendly_label_name(lid)
        remove_val = id_to_name.get(lid) or lid
        removable.append((remove_val, disp))

    if not removable:
        clear_screen()
        print()
        print_info("No removable labels found on this email.")
        return False

    while True:
        clear_screen()
        print()
        print(Fore.WHITE + Style.BRIGHT + "Select Label to Remove")
        print(Fore.WHITE + SEP_MINOR)
        print()

        for idx, (ident, disp) in enumerate(removable, 1):
            print(f"[{idx}] {disp}")

        print()
        print(Fore.WHITE + "[b] Back")
        print()

        prompt_str = f"Select label [{f'1-{len(removable)}' if len(removable) > 1 else '1'}, b]: "
        while True:
            choice = _prompt_input(Fore.CYAN + prompt_str + Style.RESET_ALL).lower()

            if choice in ('b', 'back'):
                return False

            if choice.isdigit():
                val = int(choice)
                if 1 <= val <= len(removable):
                    ident_to_remove, disp_name = removable[val - 1]

                    # Step 5 — Confirm removal
                    clear_screen()
                    print()
                    print(Fore.WHITE + Style.BRIGHT + "Remove Label")
                    print(Fore.WHITE + SEP_MINOR)
                    print()
                    print(f"Email : {subject}")
                    print(f"Label : {disp_name}")
                    print()

                    if not _prompt_confirm("Remove this label?", default=False):
                        print_info("Removal cancelled.")
                        break  # Return to select label to remove (outer loop clears screen)

                    # Step 6 — Remove label
                    success = gmail_service.modify_labels(msg_id, remove_labels=[ident_to_remove])
                    if success:
                        clear_screen()
                        print()
                        print_success(f"✓ Label \"{disp_name}\" removed successfully.")
                        return True
                    else:
                        print_error(f"Failed to remove label \"{disp_name}\".")
                        return False
                else:
                    print(Fore.RED + "✗ Invalid selection.")
            else:
                print(Fore.RED + "✗ Invalid selection.")
