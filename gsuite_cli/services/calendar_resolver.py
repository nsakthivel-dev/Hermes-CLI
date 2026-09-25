"""
Calendar Resource Resolver and Selector for Hermes CLI.
Provides human-friendly calendar selection and resolution.
Priority: NUMBER -> ALIAS -> EXACT/CASE-INSENSITIVE NAME -> REAL CALENDAR ID.
"""

import sys
from typing import Dict, List, Any, Optional, Tuple
from colorama import Fore, Style

from ..utils.formatters import print_error, print_info, print_success, print_warning, clear_screen
from .resource_resolver import GlobalResourceResolver, ResourceResolutionError, ResourceNotFoundError


class CalendarResolutionError(Exception):
    """Base exception for calendar resolution errors."""
    pass


class CalendarNotFoundError(CalendarResolutionError):
    """Raised when an entered calendar cannot be resolved."""
    def __init__(self, input_val: str, available_calendars: Optional[List[Dict[str, Any]]] = None):
        self.input_val = input_val
        self.available_calendars = available_calendars or []
        super().__init__(f"Calendar not found: {input_val}")


class AmbiguousCalendarNameError(CalendarResolutionError):
    """Raised when multiple calendars share the same name."""
    def __init__(self, name: str, matching_calendars: List[Dict[str, Any]]):
        self.name = name
        self.matching_calendars = matching_calendars
        super().__init__(f"Multiple calendars found with name '{name}'")


class AliasDeletedError(CalendarResolutionError):
    """Raised when an alias references a calendar that no longer exists."""
    def __init__(self, alias: str, available_calendars: Optional[List[Dict[str, Any]]] = None):
        self.alias = alias
        self.available_calendars = available_calendars or []
        super().__init__(f"Alias '{alias}' points to a calendar that is no longer available.")


class EventNotFoundError(CalendarResolutionError):
    """Raised when an entered event cannot be resolved."""
    def __init__(self, input_val: str, available_events: Optional[List[Dict[str, Any]]] = None):
        self.input_val = input_val
        self.available_events = available_events or []
        super().__init__(f"Event not found: {input_val}")


class AmbiguousEventNameError(CalendarResolutionError):
    """Raised when multiple events match the same query."""
    def __init__(self, name: str, matching_events: List[Dict[str, Any]]):
        self.name = name
        self.matching_events = matching_events
        super().__init__(f"Multiple events found matching '{name}'")


class CalendarResolver:
    """Reusable calendar resource resolver and interactive selector."""

    @staticmethod
    def get_calendars(calendar_service: Any) -> List[Dict[str, Any]]:
        """
        Fetch calendars from CalendarService and ensure the primary calendar is first (index 0).
        """
        try:
            calendars = calendar_service.list_calendars()
        except Exception as e:
            calendars = []

        if not calendars:
            return []

        # Find primary calendar index
        primary_idx = -1
        for idx, cal in enumerate(calendars):
            if cal.get('primary') or cal.get('id') == 'primary':
                primary_idx = idx
                break

        # Move primary calendar to the first position so [1] is always Primary
        if primary_idx > 0:
            primary_cal = calendars.pop(primary_idx)
            calendars.insert(0, primary_cal)

        return calendars

    @staticmethod
    def format_calendar_list(calendars: List[Dict[str, Any]]) -> str:
        """
        Format calendars for display according to Hermes CLI style:
        [1] My Calendar              (Primary)
        [2] Brand New Cherry
        [3] Holidays in India
        """
        lines = []
        for idx, cal in enumerate(calendars, 1):
            summary = cal.get('summary', 'Untitled')
            is_primary = cal.get('primary', False) or cal.get('id') == 'primary' or idx == 1
            primary_tag = "  (Primary)" if is_primary else ""
            lines.append(f"[{idx}] {summary:<25}{primary_tag}".rstrip())
        return "\n".join(lines)

    @staticmethod
    def resolve(
        input_str: Optional[str],
        calendars: List[Dict[str, Any]],
        config_manager: Optional[Any] = None
    ) -> str:
        """
        Resolve user input into a real Google Calendar ID.
        Priority:
        1. NUMBER (1..N)
        2. ALIAS
        3. EXACT CALENDAR NAME (case-insensitive, trimmed)
        4. CALENDAR ID
        """
        val = (input_str or "").strip()

        # 0. Empty input -> Default to primary calendar ([1])
        if not val:
            if calendars:
                # Find primary or return the first calendar
                for cal in calendars:
                    if cal.get('primary') or cal.get('id') == 'primary':
                        return cal['id']
                return calendars[0]['id']
            return 'primary'

        # 1. NUMBER Priority
        if val.isdigit():
            num = int(val)
            if 1 <= num <= len(calendars):
                return calendars[num - 1]['id']
            # If digit is out of range, check if it's an alias, name, or raw ID below;
            # if none matches, will raise CalendarNotFoundError.

        # 2. ALIAS Priority
        if config_manager:
            aliases = config_manager.get('calendar.aliases', {}) or {}
            target_alias = None
            for alias_key, target_id in aliases.items():
                if alias_key.lower() == val.lower():
                    target_alias = (alias_key, target_id)
                    break

            if target_alias:
                alias_name, target_id = target_alias
                # Validate if the aliased calendar still exists in the fetched list
                if calendars:
                    exists = any(
                        cal.get('id') == target_id or (target_id == 'primary' and cal.get('primary'))
                        for cal in calendars
                    )
                    if not exists:
                        raise AliasDeletedError(alias=alias_name, available_calendars=calendars)
                return target_id

        # 3. EXACT CALENDAR NAME (case-insensitive, trimmed)
        val_lower = val.lower()
        matching_calendars = [
            cal for cal in calendars
            if cal.get('summary', '').strip().lower() == val_lower
        ]

        if len(matching_calendars) == 1:
            return matching_calendars[0]['id']
        elif len(matching_calendars) > 1:
            raise AmbiguousCalendarNameError(name=val, matching_calendars=matching_calendars)

        # 4. CALENDAR ID Priority
        for cal in calendars:
            if cal.get('id') == val:
                return cal['id']

        if val == 'primary':
            return 'primary'

        # If it looks like a valid email / Google Calendar ID (@group.calendar.google.com or user email)
        if '@' in val:
            return val

        # If no calendar matched
        raise CalendarNotFoundError(input_val=val, available_calendars=calendars)

    @classmethod
    def prompt_selection(
        cls,
        calendar_service: Any,
        config_manager: Optional[Any] = None,
        prompt_label: str = "Calendar",
        default_index: int = 1
    ) -> str:
        """
        Display interactive calendar selection and resolve user input.
        Handles errors cleanly and re-prompts until a valid calendar is selected.
        """
        calendars = cls.get_calendars(calendar_service)

        if not calendars:
            # Fallback if no calendars found or offline
            try:
                import click
                cal_id = click.prompt(f"{prompt_label} ID", default="primary", show_default=False).strip()
            except Exception:
                print(Fore.CYAN + f"{prompt_label} ID: ", end="")
                cal_id = input().strip()
            return cal_id or 'primary'

        first_display = True

        while True:
            if first_display:
                clear_screen()
                print(Fore.WHITE + Style.BRIGHT + "Select Calendar:\n")
                print(cls.format_calendar_list(calendars))
                print()
                first_display = False

            prompt_str = f"{prompt_label} [{default_index}]"
            try:
                import click
                user_input = click.prompt(prompt_str, default=str(default_index), show_default=False)
            except Exception:
                print(Fore.CYAN + f"{prompt_str}: ", end="")
                user_input = input()

            try:
                resolved_id = cls.resolve(user_input, calendars, config_manager)
                return resolved_id

            except AmbiguousCalendarNameError as err:
                print()
                print(Fore.YELLOW + "Multiple calendars found:\n")
                # Format sublist with their actual indices in original calendars list
                for cal in err.matching_calendars:
                    idx = calendars.index(cal) + 1
                    summary = cal.get('summary', 'Untitled')
                    print(f"[{idx}] {summary}")
                print()
                # Re-prompt specifically for number
                try:
                    import click
                    disambig_input = click.prompt(prompt_label, default="1", show_default=False)
                except Exception:
                    print(Fore.CYAN + f"{prompt_label}: ", end="")
                    disambig_input = input()
                try:
                    disambig_id = cls.resolve(disambig_input, calendars, config_manager)
                    return disambig_id
                except CalendarResolutionError:
                    print(Fore.RED + "\n✗ Calendar not found.\n")
                    print(Fore.WHITE + Style.BRIGHT + "Available calendars:\n")
                    print(cls.format_calendar_list(calendars))
                    print()
                    continue

            except AliasDeletedError as err:
                print(Fore.RED + f"\n✗ Alias '{err.alias}' points to a calendar that is no longer available.\n")
                print(Fore.WHITE + Style.BRIGHT + "Available calendars:\n")
                print(cls.format_calendar_list(calendars))
                print()

            except CalendarNotFoundError:
                print(Fore.RED + "\n✗ Calendar not found.\n")
                print(Fore.WHITE + Style.BRIGHT + "Available calendars:\n")
                print(cls.format_calendar_list(calendars))
                print()

            except CalendarResolutionError as err:
                print(Fore.RED + f"\n✗ {err}\n")
                print(Fore.WHITE + Style.BRIGHT + "Available calendars:\n")
                print(cls.format_calendar_list(calendars))
                print()

    @classmethod
    def set_alias(
        cls,
        target: str,
        alias_name: str,
        calendar_service: Any,
        config_manager: Any
    ) -> Tuple[bool, str]:
        """
        Create a calendar alias: alias_name -> calendar_id.
        Target can be number, calendar name, or real Google Calendar ID.
        """
        calendars = cls.get_calendars(calendar_service)
        try:
            calendar_id = cls.resolve(target, calendars, config_manager)
        except CalendarResolutionError as e:
            return False, str(e)

        # Get summary for user feedback
        cal_name = calendar_id
        for cal in calendars:
            if cal.get('id') == calendar_id:
                cal_name = cal.get('summary', calendar_id)
                break

        clean_alias = alias_name.strip()
        if not clean_alias:
            return False, "Alias name cannot be empty."

        aliases = config_manager.get('calendar.aliases', {}) or {}
        # Ensure it's a dict
        if not isinstance(aliases, dict):
            aliases = {}

        aliases[clean_alias] = calendar_id
        if config_manager.set('calendar.aliases', aliases):
            config_manager.save_config()
            return True, f"{clean_alias} → {cal_name}"
        return False, "Failed to save configuration."

    @classmethod
    def get_aliases(
        cls,
        calendar_service: Any,
        config_manager: Any
    ) -> List[Tuple[str, str, str]]:
        """
        Retrieve all aliases formatted as (alias, calendar_name, calendar_id).
        """
        aliases = config_manager.get('calendar.aliases', {}) or {}
        if not aliases or not isinstance(aliases, dict):
            return []

        calendars = cls.get_calendars(calendar_service)
        cal_map = {cal['id']: cal.get('summary', cal['id']) for cal in calendars}

        results = []
        for alias_name, cal_id in aliases.items():
            name = cal_map.get(cal_id, cal_id)
            results.append((alias_name, name, cal_id))
        return results

    @classmethod
    def get_calendar_info(
        cls,
        target: str,
        calendar_service: Any,
        config_manager: Optional[Any] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve target to calendar details for 'hermes calendar info'.
        """
        calendars = cls.get_calendars(calendar_service)
        try:
            calendar_id = cls.resolve(target, calendars, config_manager)
        except CalendarResolutionError:
            calendar_id = target

        # Try to find in list
        for cal in calendars:
            if cal.get('id') == calendar_id:
                return cal

        # If not in list, fetch from API directly
        return calendar_service.get_calendar(calendar_id)


class CalendarEventResolver:
    """Reusable calendar event resolver, formatter, and interactive selector."""

    @staticmethod
    def format_event_datetime(event: Dict[str, Any]) -> str:
        """
        Format start and end time into human-friendly representation, e.g.:
        16 Sep 2026 00:00 - 23:59
        17 Sep 2026 10:00 - 11:00
        17 Sep 2026 10:00 - 18 Sep 2026 11:00
        """
        from datetime import datetime
        from dateutil import parser as date_parser

        start_str = event.get('start', '')
        end_str = event.get('end', '')
        is_all_day = event.get('all_day', False)

        if not start_str:
            return "Time not specified"

        start_dt = None
        end_dt = None

        if isinstance(start_str, str):
            try:
                start_dt = date_parser.parse(start_str)
            except Exception:
                pass
        elif isinstance(start_str, datetime):
            start_dt = start_str

        if isinstance(end_str, str) and end_str:
            try:
                end_dt = date_parser.parse(end_str)
            except Exception:
                pass
        elif isinstance(end_str, datetime):
            end_dt = end_str

        # Check for all-day event
        if is_all_day or (start_dt and 'T' not in str(start_str) and len(str(start_str).strip()) <= 10):
            if start_dt:
                date_part = start_dt.strftime("%d %b %Y")
                return f"{date_part} 00:00 - 23:59"
            return f"{start_str} 00:00 - 23:59"

        if start_dt and end_dt:
            if start_dt.date() == end_dt.date():
                date_part = start_dt.strftime("%d %b %Y")
                return f"{date_part} {start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}"
            else:
                return f"{start_dt.strftime('%d %b %Y %H:%M')} - {end_dt.strftime('%d %b %Y %H:%M')}"

        if start_dt:
            return start_dt.strftime("%d %b %Y %H:%M")

        return f"{start_str} - {end_str}".strip(" -")

    @classmethod
    def format_event_list(cls, events: List[Dict[str, Any]], start_index: int = 1) -> str:
        """
        Display a clean numbered list according to Hermes CLI style:
        [1] Birthday
            16 Sep 2026 00:00 - 23:59

        [2] Project Discussion
            17 Sep 2026 10:00 - 11:00
        """
        lines = []
        for idx, event in enumerate(events, start_index):
            title = event.get('summary') or 'Untitled Event'
            dt_str = cls.format_event_datetime(event)
            lines.append(f"[{idx}] {title}\n    {dt_str}")
        return "\n\n".join(lines)

    @classmethod
    def resolve(
        cls,
        input_str: Optional[str],
        events: List[Dict[str, Any]],
        calendar_service: Optional[Any] = None,
        calendar_id: str = 'primary',
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Resolve user input to a full event dictionary.
        Priority:
        1. NUMBER (1..N corresponding to displayed list or global 1-based index)
        2. EXACT EVENT TITLE (case-insensitive)
        3. SUBSTRING EVENT TITLE (case-insensitive, unique or closest)
        4. DIRECT GOOGLE EVENT ID (matches in list or fetched via service)
        """
        val = (input_str or "").strip()
        if not val:
            if events:
                return events[0]
            raise EventNotFoundError(val, events)

        # 1. NUMBER Priority
        if val.isdigit():
            num = int(val)
            # Local 1-based index relative to the passed list
            if 1 <= num <= len(events):
                return events[num - 1]
            # Check relative to offset if applicable (e.g. pagination)
            if offset > 0 and 1 <= (num - offset) <= len(events):
                return events[num - offset - 1]
            for ev in events:
                if ev.get('id') == val:
                    return ev
            raise EventNotFoundError(val, events)

        # 2. EXACT TITLE MATCH (case-insensitive)
        val_lower = val.lower()
        exact_matches = [
            ev for ev in events
            if (ev.get('summary') or '').strip().lower() == val_lower
        ]
        if exact_matches:
            return exact_matches[0]

        # 3. SUBSTRING MATCH (case-insensitive)
        sub_matches = [
            ev for ev in events
            if val_lower in (ev.get('summary') or '').lower()
        ]
        if sub_matches:
            return sub_matches[0]

        # 4. DIRECT GOOGLE EVENT ID MATCH
        for ev in events:
            if ev.get('id') == val:
                return ev

        # If direct event ID was passed and calendar_service is available, try fetching directly
        if calendar_service:
            try:
                fetched = calendar_service.get_event(val, calendar_id=calendar_id)
                if fetched:
                    return fetched
            except Exception:
                pass

        raise EventNotFoundError(val, events)

