"""
Interactive Calendar Update workflow for Hermes CLI.
Implements the human-friendly calendar update experience:
Select Calendar -> List Events -> Select Event -> View Details -> Edit Field(s) -> Confirm -> Update.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from colorama import Fore, Style
from dateutil import parser as date_parser

from ..auth.oauth import OAuthManager
from ..config.manager import ConfigManager
from ..services.calendar import CalendarService
from ..services.calendar_resolver import (
    CalendarResolver,
    CalendarEventResolver,
    CalendarResolutionError,
    EventNotFoundError,
)
from ..services.calendar_validators import (
    validate_datetime,
    validate_start_end_order,
    validate_title,
    validate_recurrence_choice,
    validate_weekdays,
    validate_month_day,
    validate_rrule,
    validate_end_condition,
    validate_until_date,
    validate_occurrence_count,
    validate_reminders,
)
from ..utils.formatters import print_error, print_info, print_success, print_warning, clear_screen


def _format_display_datetime(dt_str: Optional[str]) -> str:
    """Format an ISO datetime or date into '17 Sep 2026 10:00'."""
    if not dt_str:
        return "None"
    try:
        dt = date_parser.parse(str(dt_str))
        if 'T' not in str(dt_str) and len(str(dt_str).strip()) <= 10:
            return dt.strftime("%d %b %Y")
        return dt.strftime("%d %b %Y %H:%M")
    except Exception:
        return str(dt_str)


def _format_reminders_display(reminders: Any) -> str:
    """Format reminders dict into human-readable string like '30m' or 'None'."""
    if not reminders or not isinstance(reminders, dict):
        return "None"
    if reminders.get('useDefault'):
        return "Default"
    overrides = reminders.get('overrides', [])
    if not overrides:
        return "None"
    parts = []
    for ov in overrides:
        mins = ov.get('minutes', 0)
        if mins >= 1440 and mins % 1440 == 0:
            parts.append(f"{mins // 1440}d")
        elif mins >= 60 and mins % 60 == 0:
            parts.append(f"{mins // 60}h")
        else:
            parts.append(f"{mins}m")
    return ", ".join(parts) if parts else "None"


def _format_attendees_display(attendees: Any) -> str:
    """Format attendees list into comma-separated emails or 'None'."""
    if not attendees or not isinstance(attendees, list):
        return "None"
    emails = []
    for att in attendees:
        if isinstance(att, dict):
            email = att.get('email', '').strip()
            if email:
                emails.append(email)
        elif isinstance(att, str) and att.strip():
            emails.append(att.strip())
    return ", ".join(emails) if emails else "None"


def _format_recurrence_display(recurrence: Any) -> str:
    """Format recurrence list into human string or 'None'."""
    if not recurrence or not isinstance(recurrence, list):
        return "None"
    rules = [r.replace('RRULE:', '') for r in recurrence if r]
    return ", ".join(rules) if rules else "None"


def run_calendar_update_flow(
    cal_service: Optional[CalendarService] = None,
    config_manager: Optional[ConfigManager] = None
) -> bool:
    """
    Main interactive Calendar Update flow.
    Returns True if an update was performed, False if cancelled or aborted.
    """
    if cal_service is None:
        try:
            cal_service = CalendarService(OAuthManager())
        except Exception as e:
            print_error(f"Failed to initialize Calendar service: {e}")
            return False

    if config_manager is None:
        try:
            config_manager = ConfigManager()
        except Exception:
            config_manager = None

    # ============================================================
    # 1. CALENDAR SELECTION
    # ============================================================
    calendars = CalendarResolver.get_calendars(cal_service)
    calendar_id = CalendarResolver.prompt_selection(cal_service, config_manager)
    if not calendar_id:
        calendar_id = 'primary'

    # Get calendar friendly name
    cal_name = calendar_id
    for cal in calendars:
        if cal.get('id') == calendar_id:
            cal_name = cal.get('summary', calendar_id)
            break

    # ============================================================
    # 2. RETRIEVE EVENTS
    # ============================================================
    try:
        events = cal_service.list_events(calendar_id=calendar_id, max_results=250)
    except Exception as e:
        print_error(f"Failed to retrieve events: {e}")
        return False

    # ============================================================
    # 3. EMPTY EVENT LIST
    # ============================================================
    if not events:
        print()
        print(Fore.YELLOW + "No events found.\n")
        print(Fore.WHITE + f"Calendar: {cal_name}\n")
        print(Fore.CYAN + "[b] Back: ", end="")
        input()
        return False

    # ============================================================
    # 4. EVENT LIST, PAGINATION, SEARCH & SELECTION
    # ============================================================
    page_size = 5
    current_page = 0
    search_query = None
    active_events = events

    selected_event = None

    while selected_event is None:
        clear_screen()
        # Filter if search query active
        if search_query:
            filtered = [
                ev for ev in events
                if search_query.lower() in (ev.get('summary') or '').lower()
                or search_query.lower() in (ev.get('description') or '').lower()
                or search_query.lower() in (ev.get('location') or '').lower()
            ]
            active_events = filtered
            if not active_events:
                print(Fore.YELLOW + f"\nNo events matching '{search_query}'. Showing all events.\n")
                search_query = None
                active_events = events
                current_page = 0

        total_pages = max(1, (len(active_events) + page_size - 1) // page_size)
        if current_page >= total_pages:
            current_page = max(0, total_pages - 1)

        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, len(active_events))
        page_events = active_events[start_idx:end_idx]

        print()
        if search_query:
            print(Fore.WHITE + Style.BRIGHT + f"Result for '{search_query}':\n")
        else:
            print(Fore.WHITE + Style.BRIGHT + "Select Event:\n")

        print(CalendarEventResolver.format_event_list(page_events, start_index=1))
        print()

        # Display pagination navigation if multiple pages or search active
        if total_pages > 1 or search_query:
            nav_options = []
            if current_page < total_pages - 1:
                nav_options.append("[n] Next page")
            if current_page > 0:
                nav_options.append("[p] Previous page")
            nav_options.append("[s] Search")
            if search_query:
                nav_options.append("[c] Clear search")
            nav_options.append("[b] Back")
            print(Fore.LIGHTBLACK_EX + "  ".join(nav_options))
            print()

        prompt_label = "Event [1]: "
        print(Fore.CYAN + prompt_label, end="")
        user_input = input().strip()

        # Handle navigation commands
        if user_input.lower() in ['b', 'back']:
            return False
        if user_input.lower() in ['n', 'next'] and current_page < total_pages - 1:
            current_page += 1
            continue
        if user_input.lower() in ['p', 'prev', 'previous'] and current_page > 0:
            current_page -= 1
            continue
        if user_input.lower() in ['s', 'search']:
            print(Fore.CYAN + "\nSearch event:\n> ", end="")
            s_input = input().strip()
            if s_input:
                search_query = s_input
                current_page = 0
            continue
        if user_input.lower() in ['c', 'clear'] and search_query:
            search_query = None
            active_events = events
            current_page = 0
            continue

        # If user pressed enter without input, default to [1] of current page
        lookup_input = user_input if user_input else "1"

        try:
            # First try resolving against current page events (number 1..page_size)
            resolved = CalendarEventResolver.resolve(
                lookup_input,
                page_events,
                cal_service,
                calendar_id=calendar_id
            )
            selected_event = resolved
        except EventNotFoundError:
            # If not in current page, try resolving against all active events or by direct ID
            try:
                resolved = CalendarEventResolver.resolve(
                    lookup_input,
                    events,
                    cal_service,
                    calendar_id=calendar_id
                )
                selected_event = resolved
            except EventNotFoundError:
                print(Fore.RED + "\n✗ Event not found.")
                continue

    # ============================================================
    # 5. RETRIEVE COMPLETE CURRENT EVENT DETAILS
    # ============================================================
    event_id = selected_event.get('id')
    try:
        full_event = cal_service.get_event(event_id, calendar_id=calendar_id) or selected_event
    except Exception:
        full_event = selected_event

    current_title = full_event.get('summary', 'Untitled Event')
    current_start = _format_display_datetime(full_event.get('start'))
    current_end = _format_display_datetime(full_event.get('end'))
    current_desc = full_event.get('description', '') or 'None'
    current_loc = full_event.get('location', '') or 'None'
    current_rec = _format_recurrence_display(full_event.get('recurrence'))
    current_rem = _format_reminders_display(full_event.get('reminders'))
    current_att = _format_attendees_display(full_event.get('attendees'))

    clear_screen()
    print()
    print(Fore.CYAN + Style.BRIGHT + "Event Selected")
    print(Fore.CYAN + "=" * 60)
    print()
    print(f"{'Title':<12}: {current_title}")
    print(f"{'Start':<12}: {current_start}")
    print(f"{'End':<12}: {current_end}")
    print(f"{'Description':<12}: {current_desc}")
    print(f"{'Location':<12}: {current_loc}")
    print(f"{'Recurrence':<12}: {current_rec}")
    print(f"{'Reminders':<12}: {current_rem}")
    print(f"{'Attendees':<12}: {current_att}")
    print()
    print(Fore.WHITE + Style.BRIGHT + "What do you want to edit?\n")
    print("[1] Title")
    print("[2] Start")
    print("[3] End")
    print("[4] Description")
    print("[5] Location")
    print("[6] Recurrence")
    print("[7] Reminders")
    print("[8] Attendees")
    print("[9] Calendar")
    print("[10] Multiple fields")
    print("[b] Back")
    print()

    while True:
        print(Fore.CYAN + "Select [1]: ", end="")
        choice_input = input().strip().lower()
        if not choice_input:
            choice_input = '1'

        if choice_input in ['b', 'back']:
            return False

        if choice_input in ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10']:
            break

        print(Fore.RED + "✗ Invalid choice. Select 1-10 or b.")

    # Determine which fields to edit
    fields_to_edit: List[str] = []
    if choice_input == '10':
        print()
        print(Fore.WHITE + Style.BRIGHT + "Select fields to edit:\n")
        print("[1] Title")
        print("[2] Start")
        print("[3] End")
        print("[4] Description")
        print("[5] Location")
        print("[6] Recurrence")
        print("[7] Reminders")
        print("[8] Attendees")
        print()

        while True:
            print(Fore.CYAN + "Enter fields separated by comma:\n> ", end="")
            m_input = input().strip()
            if not m_input:
                print(Fore.RED + "✗ Please enter at least one field number.")
                continue
            parts = [p.strip() for p in m_input.split(',') if p.strip()]
            valid = True
            for p in parts:
                if p not in ['1', '2', '3', '4', '5', '6', '7', '8']:
                    valid = False
                    break
            if valid and parts:
                fields_to_edit = parts
                break
            print(Fore.RED + "✗ Invalid selection. Enter numbers 1 to 8 separated by comma.")
    else:
        fields_to_edit = [choice_input]

    # Staged changes dictionary: field_name -> (old_val_str, new_val_str, kwargs_dict)
    updates_kwargs: Dict[str, Any] = {}
    changes_display: List[Tuple[str, str, str]] = []

    parsed_new_start_dt: Optional[datetime] = None
    parsed_new_end_dt: Optional[datetime] = None
    new_calendar_id: Optional[str] = None
    new_calendar_name: Optional[str] = None

    # Base start & end datetimes for comparison
    base_start_dt = None
    base_end_dt = None
    try:
        if full_event.get('start'):
            base_start_dt = date_parser.parse(str(full_event['start'])).replace(tzinfo=None)
    except Exception:
        pass
    try:
        if full_event.get('end'):
            base_end_dt = date_parser.parse(str(full_event['end'])).replace(tzinfo=None)
    except Exception:
        pass

    # ============================================================
    # 6. PROMPT & VALIDATE EACH FIELD
    # ============================================================
    for field in fields_to_edit:
        # Field 1: Title
        if field == '1':
            print()
            while True:
                print(Fore.CYAN + "New Title:\n> ", end="")
                new_title = input().strip()
                is_valid, err_msg = validate_title(new_title)
                if is_valid:
                    updates_kwargs['summary'] = new_title
                    changes_display.append(("Title", current_title, new_title))
                    break
                print(Fore.RED + f"\n✗ {err_msg}\n")

        # Field 2: Start
        elif field == '2':
            print()
            while True:
                print(Fore.CYAN + "Start (YYYY-MM-DD HH:MM):\n> ", end="")
                raw_start = input().strip()
                is_valid, parsed_dt, err_msg = validate_datetime(raw_start)
                if not is_valid:
                    print(Fore.RED + f"\n✗ {err_msg}\n")
                    continue

                # Check against end datetime if known
                end_cmp = parsed_new_end_dt or base_end_dt
                if end_cmp and parsed_dt >= end_cmp:
                    print(Fore.RED + "\n✗ Start time must be before end time.\n")
                    continue

                parsed_new_start_dt = parsed_dt
                updates_kwargs['start_time'] = parsed_dt
                new_start_str = parsed_dt.strftime("%d %b %Y %H:%M")
                changes_display.append(("Start", current_start, new_start_str))
                break

        # Field 3: End
        elif field == '3':
            print()
            while True:
                print(Fore.CYAN + "End (YYYY-MM-DD HH:MM):\n> ", end="")
                raw_end = input().strip()
                is_valid, parsed_dt, err_msg = validate_datetime(raw_end)
                if not is_valid:
                    print(Fore.RED + f"\n✗ {err_msg}\n")
                    continue

                # Check against start datetime
                start_cmp = parsed_new_start_dt or base_start_dt
                if start_cmp and parsed_dt <= start_cmp:
                    print(Fore.RED + "\n✗ End time must be after the start time.\n")
                    continue

                parsed_new_end_dt = parsed_dt
                updates_kwargs['end_time'] = parsed_dt
                new_end_str = parsed_dt.strftime("%d %b %Y %H:%M")
                changes_display.append(("End", current_end, new_end_str))
                break

        # Field 4: Description
        elif field == '4':
            print()
            print(Fore.WHITE + "Current Description:")
            print(current_desc)
            print()
            print(Fore.CYAN + "New Description (enter 'clear' to remove):\n> ", end="")
            new_desc = input().strip()
            if new_desc.lower() == 'clear':
                new_desc = ""
            updates_kwargs['description'] = new_desc
            changes_display.append(("Description", current_desc, new_desc or "None"))

        # Field 5: Location
        elif field == '5':
            print()
            print(Fore.WHITE + "Current Location:")
            print(current_loc)
            print()
            print(Fore.CYAN + "New Location (enter 'clear' to remove):\n> ", end="")
            new_loc = input().strip()
            if new_loc.lower() == 'clear':
                new_loc = ""
            updates_kwargs['location'] = new_loc
            changes_display.append(("Location", current_loc, new_loc or "None"))

        # Field 6: Recurrence
        elif field == '6':
            print()
            print(Fore.WHITE + f"Current Recurrence:\n{current_rec}\n")
            while True:
                print(Fore.CYAN + "Recurrence [n=none, d=daily, w=weekly, m=monthly, r=RRULE]:\n> ", end="")
                r_choice = input().strip().lower()
                is_valid, err_msg = validate_recurrence_choice(r_choice)
                if not is_valid:
                    print(Fore.RED + f"\n✗ {err_msg}\n")
                    continue

                rec_list = []
                rec_label = "None"

                if r_choice == 'n':
                    rec_list = []
                    rec_label = "None"
                elif r_choice == 'd':
                    rec_list = ["RRULE:FREQ=DAILY"]
                    rec_label = "Daily"
                elif r_choice == 'w':
                    while True:
                        print(Fore.CYAN + "Weekdays (e.g. mon-fri or mon,wed,fri):\n> ", end="")
                        raw_wd = input().strip()
                        wd_valid, bydays, wd_err = validate_weekdays(raw_wd)
                        if wd_valid:
                            rule = "RRULE:FREQ=WEEKLY"
                            if bydays:
                                rule += f";BYDAY={','.join(bydays)}"
                            rec_list = [rule]
                            rec_label = f"Weekly ({','.join(bydays) if bydays else 'all'})"
                            break
                        print(Fore.RED + f"\n✗ {wd_err}\n")
                elif r_choice == 'm':
                    while True:
                        print(Fore.CYAN + "Day of month (1-31):\n> ", end="")
                        raw_day = input().strip()
                        m_valid, day_num, m_err = validate_month_day(raw_day)
                        if m_valid:
                            rec_list = [f"RRULE:FREQ=MONTHLY;BYMONTHDAY={day_num}"]
                            rec_label = f"Monthly (day {day_num})"
                            break
                        print(Fore.RED + f"\n✗ {m_err}\n")
                elif r_choice == 'r':
                    while True:
                        print(Fore.CYAN + "RRULE (e.g. FREQ=WEEKLY;BYDAY=MO,WE,FR):\n> ", end="")
                        raw_r = input().strip()
                        r_valid, cleaned_r, r_err = validate_rrule(raw_r)
                        if r_valid:
                            rec_list = [f"RRULE:{cleaned_r}"]
                            rec_label = cleaned_r
                            break
                        print(Fore.RED + f"\n✗ {r_err}\n")

                updates_kwargs['recurrence'] = rec_list
                changes_display.append(("Recurrence", current_rec, rec_label))
                break

        # Field 7: Reminders
        elif field == '7':
            print()
            print(Fore.WHITE + f"Current Reminders:\n{current_rem}\n")
            while True:
                print(Fore.CYAN + "Reminders (comma separated, e.g. 30m,1h,1d or 'none'):\n> ", end="")
                raw_rem = input().strip()
                if raw_rem.lower() in ['none', 'clear', '']:
                    updates_kwargs['reminders_minutes'] = []
                    changes_display.append(("Reminders", current_rem, "None"))
                    break

                is_valid, parsed_offsets, err_msg = validate_reminders(raw_rem)
                if is_valid:
                    # Convert parsed offsets (e.g. '30m', '1h') to minutes integer list
                    minutes_list = []
                    for off in parsed_offsets:
                        unit = off[-1].lower()
                        num = int(off[:-1])
                        if unit == 'm':
                            minutes_list.append(num)
                        elif unit == 'h':
                            minutes_list.append(num * 60)
                        elif unit == 'd':
                            minutes_list.append(num * 1440)
                    updates_kwargs['reminders_minutes'] = minutes_list
                    changes_display.append(("Reminders", current_rem, ", ".join(parsed_offsets)))
                    break
                print(Fore.RED + f"\n✗ {err_msg}\n")

        # Field 8: Attendees
        elif field == '8':
            print()
            print(Fore.WHITE + f"Current Attendees:\n{current_att}\n")
            print(Fore.WHITE + Style.BRIGHT + "Attendee Action:")
            print("[1] Replace attendees")
            print("[2] Add attendee(s)")
            print("[3] Remove attendee(s)")
            print("[4] Clear attendees")
            print()

            while True:
                print(Fore.CYAN + "Choice [1]: ", end="")
                att_choice = input().strip()
                if not att_choice:
                    att_choice = '1'

                current_email_list = []
                for att in full_event.get('attendees', []):
                    if isinstance(att, dict) and att.get('email'):
                        current_email_list.append(att['email'].strip())
                    elif isinstance(att, str) and att.strip():
                        current_email_list.append(att.strip())

                if att_choice == '4':
                    updates_kwargs['attendees'] = []
                    changes_display.append(("Attendees", current_att, "None"))
                    break

                elif att_choice == '1':
                    print(Fore.CYAN + "\nNew Attendees (comma separated):\n> ", end="")
                    raw_att = input().strip()
                    if not raw_att:
                        updates_kwargs['attendees'] = []
                        changes_display.append(("Attendees", current_att, "None"))
                        break
                    emails = [e.strip() for e in raw_att.split(',') if e.strip()]
                    invalid_emails = [e for e in emails if not cal_service._validate_email(e)]
                    if invalid_emails:
                        print(Fore.RED + f"\n✗ Invalid email address(es): {', '.join(invalid_emails)}")
                        continue
                    updates_kwargs['attendees'] = [{'email': e} for e in emails]
                    changes_display.append(("Attendees", current_att, ", ".join(emails)))
                    break

                elif att_choice == '2':
                    print(Fore.CYAN + "\nAttendee(s) to add (comma separated):\n> ", end="")
                    raw_att = input().strip()
                    emails = [e.strip() for e in raw_att.split(',') if e.strip()]
                    invalid_emails = [e for e in emails if not cal_service._validate_email(e)]
                    if invalid_emails:
                        print(Fore.RED + f"\n✗ Invalid email address(es): {', '.join(invalid_emails)}")
                        continue
                    combined = list(current_email_list)
                    for e in emails:
                        if e not in combined:
                            combined.append(e)
                    updates_kwargs['attendees'] = [{'email': e} for e in combined]
                    changes_display.append(("Attendees", current_att, ", ".join(combined)))
                    break

                elif att_choice == '3':
                    print(Fore.CYAN + "\nAttendee(s) to remove (comma separated):\n> ", end="")
                    raw_att = input().strip()
                    to_remove = [e.strip().lower() for e in raw_att.split(',') if e.strip()]
                    remaining = [e for e in current_email_list if e.lower() not in to_remove]
                    updates_kwargs['attendees'] = [{'email': e} for e in remaining]
                    changes_display.append(("Attendees", current_att, ", ".join(remaining) if remaining else "None"))
                    break

                print(Fore.RED + "✗ Invalid choice. Select 1 to 4.")

        # Field 9: Calendar (Move event)
        elif field == '9':
            print()
            print(Fore.WHITE + Style.BRIGHT + "Select Destination Calendar:\n")
            print(CalendarResolver.format_calendar_list(calendars))
            print()
            while True:
                print(Fore.CYAN + "Calendar:\n> ", end="")
                target_cal_input = input().strip()
                try:
                    target_cal_id = CalendarResolver.resolve(target_cal_input, calendars, config_manager)
                    if target_cal_id == calendar_id:
                        print(Fore.YELLOW + "\nEvent is already in this calendar.")
                        break
                    new_calendar_id = target_cal_id
                    new_calendar_name = target_cal_id
                    for cal in calendars:
                        if cal.get('id') == target_cal_id:
                            new_calendar_name = cal.get('summary', target_cal_id)
                            break
                    changes_display.append(("Calendar", cal_name, new_calendar_name))
                    break
                except CalendarResolutionError as err:
                    print(Fore.RED + f"\n✗ {err}\n")

    # If no actual changes recorded
    if not changes_display:
        print_info("No changes made.")
        return False

    # ============================================================
    # 7. CONFIRM BEFORE UPDATE
    # ============================================================
    clear_screen()
    print()
    print(Fore.CYAN + Style.BRIGHT + "Event Update")
    print(Fore.CYAN + "=" * 60)
    print()
    print(Fore.WHITE + "Event:")
    print(current_title)
    print()
    print(Fore.WHITE + "Changes:\n")
    for field_name, old_v, new_v in changes_display:
        print(Fore.WHITE + Style.BRIGHT + f"{field_name}:")
        print(Fore.LIGHTBLACK_EX + f"{old_v}")
        print(Fore.CYAN + "→")
        print(Fore.GREEN + f"{new_v}\n")

    print(Fore.CYAN + "Update event? [Y/n]: ", end="")
    confirm = input().strip().lower()
    if confirm in ['n', 'no']:
        print()
        print_info("Update cancelled.")
        return False

    # ============================================================
    # 8. EXECUTE UPDATE
    # ============================================================
    current_cal_target = calendar_id

    # If moving calendar
    if new_calendar_id and new_calendar_id != calendar_id:
        move_ok = cal_service.move_event(event_id, calendar_id, new_calendar_id)
        if not move_ok:
            print_error("Failed to move event to the new calendar.")
            return False
        current_cal_target = new_calendar_id

    # If updating fields
    if updates_kwargs:
        success = cal_service.update_event(
            event_id=event_id,
            calendar_id=current_cal_target,
            **updates_kwargs
        )
        if not success:
            print_error("Failed to update event.")
            return False

    print()
    print_success("✓ Event updated successfully.")
    return True
