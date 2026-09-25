"""
Validation utilities for Google Calendar inputs in Hermes CLI.
Provides robust per-field validation and error messages.
"""

from datetime import datetime
from typing import Tuple, Optional, List


def validate_datetime(dt_str: Optional[str]) -> Tuple[bool, Optional[datetime], Optional[str]]:
    """
    Validate and parse datetime in 'YYYY-MM-DD HH:MM' format.
    Ensures date syntax and calendar logic (month, day, leap year, hours, minutes).
    """
    if not dt_str:
        return False, None, "Invalid datetime format. Use: YYYY-MM-DD HH:MM"

    clean_str = dt_str.strip()
    # Check length to reject date-only strings like "2026-09-16"
    if len(clean_str) != 16:
        return False, None, "Invalid datetime format. Use: YYYY-MM-DD HH:MM"

    try:
        parsed_dt = datetime.strptime(clean_str, '%Y-%m-%d %H:%M')
        return True, parsed_dt, None
    except ValueError:
        return False, None, "Invalid datetime format. Use: YYYY-MM-DD HH:MM"


def validate_start_end_order(start_dt: datetime, end_dt: datetime) -> Tuple[bool, Optional[str]]:
    """
    Validate that end datetime is strictly after start datetime.
    """
    if end_dt <= start_dt:
        return False, "End time must be after the start time."
    return True, None


def validate_title(title: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Validate that title is non-empty.
    """
    if not title or not title.strip():
        return False, "Title cannot be empty."
    return True, None


def validate_recurrence_choice(choice: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Validate recurrence option choice: n, d, w, m, r.
    """
    clean = (choice or "").strip().lower()
    if clean not in ('n', 'd', 'w', 'm', 'r'):
        return False, "Invalid recurrence option. Choose n, d, w, m, or r."
    return True, None


def validate_weekdays(weekdays_str: Optional[str]) -> Tuple[bool, Optional[List[str]], Optional[str]]:
    """
    Validate weekly recurrence weekdays string, e.g. 'mon-fri' or 'mon,wed,fri'.
    """
    if not weekdays_str or not weekdays_str.strip():
        return False, None, "Invalid weekday format. Use e.g. mon-fri or mon,wed,fri."

    valid_days = {'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'}
    order = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    raw_tokens = [t.strip().lower() for t in weekdays_str.split(',') if t.strip()]

    result = []
    for token in raw_tokens:
        if '-' in token:
            parts = token.split('-')
            if len(parts) == 2 and parts[0] in valid_days and parts[1] in valid_days:
                s_idx = order.index(parts[0])
                e_idx = order.index(parts[1])
                if s_idx <= e_idx:
                    result.extend(order[s_idx:e_idx + 1])
                else:
                    return False, None, "Invalid weekday range. Start day must be before end day."
            else:
                return False, None, "Invalid weekday format. Use e.g. mon-fri or mon,wed,fri."
        elif token in valid_days:
            result.append(token)
        else:
            return False, None, f"Invalid weekday '{token}'. Valid options: mon, tue, wed, thu, fri, sat, sun."

    if not result:
        return False, None, "Invalid weekday format. Use e.g. mon-fri or mon,wed,fri."

    return True, list(dict.fromkeys(result)), None


def validate_month_day(day_str: Optional[str]) -> Tuple[bool, Optional[int], Optional[str]]:
    """
    Validate day of month for monthly recurrence (1-31).
    """
    if not day_str:
        return False, None, "Day of month must be between 1 and 31."
    clean = day_str.strip()
    try:
        day_num = int(clean)
        if 1 <= day_num <= 31:
            return True, day_num, None
        return False, None, "Day of month must be between 1 and 31."
    except ValueError:
        return False, None, "Day of month must be between 1 and 31."


def validate_rrule(rule_str: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Validate RRULE string (requires FREQ=).
    """
    clean = (rule_str or "").strip().upper()
    if not clean or "FREQ=" not in clean:
        return False, "Invalid RRULE format. Example: FREQ=WEEKLY;BYDAY=MO,WE,FR"
    return True, None


def validate_end_condition(ec_str: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Validate recurrence end condition choice: n, u, c.
    """
    clean = (ec_str or "").strip().lower()
    if clean not in ('n', 'u', 'c'):
        return False, "Invalid end condition. Choose n, u, or c."
    return True, None


def validate_until_date(until_str: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Validate until date format (YYYY-MM-DD).
    """
    if not until_str:
        return False, "Invalid date format. Use YYYY-MM-DD."
    clean = until_str.strip()
    try:
        datetime.strptime(clean, '%Y-%m-%d')
        return True, None
    except ValueError:
        return False, "Invalid date format. Use YYYY-MM-DD."


def validate_occurrence_count(count_str: Optional[str]) -> Tuple[bool, Optional[int], Optional[str]]:
    """
    Validate number of occurrences (positive integer > 0).
    """
    if not count_str:
        return False, None, "Number of occurrences must be a positive integer."
    clean = count_str.strip()
    try:
        count = int(clean)
        if count > 0:
            return True, count, None
        return False, None, "Number of occurrences must be a positive integer."
    except ValueError:
        return False, None, "Number of occurrences must be a positive integer."


def validate_reminders(reminders_str: Optional[str]) -> Tuple[bool, Optional[List[str]], Optional[str]]:
    """
    Validate comma-separated reminders (e.g. 30m, 1h, 1d).
    """
    if not reminders_str or not reminders_str.strip():
        return False, None, "Invalid reminder format. Use values such as 30m, 1h, or 1d."

    tokens = [t.strip().lower() for t in reminders_str.split(',') if t.strip()]
    if not tokens:
        return False, None, "Invalid reminder format. Use values such as 30m, 1h, or 1d."

    valid_units = ('m', 'h', 'd')
    validated_tokens = []

    for tok in tokens:
        if len(tok) < 2:
            return False, None, "Invalid reminder format. Use values such as 30m, 1h, or 1d."
        unit = tok[-1]
        amount_part = tok[:-1]
        if unit not in valid_units or not amount_part.isdigit() or int(amount_part) <= 0:
            return False, None, "Invalid reminder format. Use values such as 30m, 1h, or 1d."
        validated_tokens.append(tok)

    return True, validated_tokens, None


def validate_notification_channels(channels_str: Optional[str]) -> Tuple[bool, Optional[List[str]], Optional[str]]:
    """
    Validate notification channels: accepts c (cli), d (desktop), e (email), or blank (cli).
    """
    if not channels_str or not channels_str.strip():
        return True, ['cli'], None

    clean = channels_str.strip().lower()
    valid_flags = {'c', 'd', 'e'}
    recognized = []

    for char in clean:
        if char in (',', ' '):
            continue
        if char not in valid_flags:
            return False, None, "Invalid notification channel. Choose c, d, e, or press Enter for cli."
        if char not in recognized:
            recognized.append(char)

    if not recognized:
        return True, ['cli'], None

    return True, recognized, None
