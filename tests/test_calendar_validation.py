"""
Tests for Calendar Create Event interactive validation and error handling.
Validates:
1. Valid datetime parsing (YYYY-MM-DD HH:MM)
2. Invalid datetime formats (date-only, invalid syntax)
3. Invalid month (e.g. 13)
4. Invalid day (e.g. Feb 30)
5. Invalid hour (e.g. 24, 25)
6. Invalid minute (e.g. 60)
7. Invalid End datetime
8. End before Start logical validation
9. End equal to Start logical validation
10. Empty Title validation
11. Valid / Invalid recurrence choices (n, d, w, m, r)
12. Weekdays validation
13. Month day validation (1-31)
14. RRULE validation
15. End condition and until date / count validation
16. Valid / Invalid reminders validation (30m, 1h, 1d)
17. Valid / Invalid notification channels validation (c, d, e, blank)
18. Interactive retry loop simulation preserving previous inputs
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from gsuite_cli.services.calendar_validators import (
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
    validate_notification_channels,
)
from gsuite_cli.ui.interactive import InteractiveMenu


# ==============================================================================
# 1. Datetime Validation Tests
# ==============================================================================
def test_valid_datetime():
    valid_cases = [
        "2026-09-16 00:00",
        "2026-09-16 09:30",
        "2026-09-16 14:00",
        "2026-12-31 23:59",
    ]
    for s in valid_cases:
        is_valid, dt, err = validate_datetime(s)
        assert is_valid is True
        assert err is None
        assert isinstance(dt, datetime)


def test_invalid_datetime_date_only():
    is_valid, dt, err = validate_datetime("2026-09-16")
    assert is_valid is False
    assert dt is None
    assert "Invalid datetime format. Use: YYYY-MM-DD HH:MM" in err


def test_invalid_datetime_syntax():
    invalid_cases = [
        "2026/09/16 10:00",
        "16-09-2026 10:00",
        "2026-09-16T10:00",
        "abc",
        "10:00",
        "",
        None,
    ]
    for s in invalid_cases:
        is_valid, dt, err = validate_datetime(s)
        assert is_valid is False
        assert "Invalid datetime format. Use: YYYY-MM-DD HH:MM" in err


def test_invalid_datetime_components():
    # Invalid month (13)
    is_valid, _, err = validate_datetime("2026-13-16 10:00")
    assert is_valid is False
    assert "Invalid datetime format. Use: YYYY-MM-DD HH:MM" in err

    # Invalid day (Feb 30)
    is_valid, _, err = validate_datetime("2026-02-30 10:00")
    assert is_valid is False
    assert "Invalid datetime format. Use: YYYY-MM-DD HH:MM" in err

    # Invalid hour (25)
    is_valid, _, err = validate_datetime("2026-09-16 25:00")
    assert is_valid is False
    assert "Invalid datetime format. Use: YYYY-MM-DD HH:MM" in err

    # Invalid minute (60)
    is_valid, _, err = validate_datetime("2026-09-16 10:60")
    assert is_valid is False
    assert "Invalid datetime format. Use: YYYY-MM-DD HH:MM" in err


# ==============================================================================
# 2. Start / End Logical Validation Tests
# ==============================================================================
def test_start_end_order_valid():
    start = datetime(2026, 9, 16, 10, 0)
    end = datetime(2026, 9, 16, 11, 0)
    is_valid, err = validate_start_end_order(start, end)
    assert is_valid is True
    assert err is None


def test_start_end_order_invalid_end_before_start():
    start = datetime(2026, 9, 16, 15, 0)
    end = datetime(2026, 9, 16, 14, 0)
    is_valid, err = validate_start_end_order(start, end)
    assert is_valid is False
    assert "End time must be after the start time." in err


def test_start_end_order_invalid_equal():
    start = datetime(2026, 9, 16, 15, 0)
    end = datetime(2026, 9, 16, 15, 0)
    is_valid, err = validate_start_end_order(start, end)
    assert is_valid is False
    assert "End time must be after the start time." in err


# ==============================================================================
# 3. Title Validation Tests
# ==============================================================================
def test_title_validation():
    assert validate_title("Birthday")[0] is True
    assert validate_title("  Fazeela Birthday  ")[0] is True

    is_valid, err = validate_title("")
    assert is_valid is False
    assert "Title cannot be empty." in err

    is_valid, err = validate_title("   ")
    assert is_valid is False
    assert "Title cannot be empty." in err

    is_valid, err = validate_title(None)
    assert is_valid is False
    assert "Title cannot be empty." in err


# ==============================================================================
# 4. Recurrence Validation Tests
# ==============================================================================
def test_recurrence_choice_validation():
    for valid in ['n', 'd', 'w', 'm', 'r', 'N', 'D', 'W', 'M', 'R']:
        is_valid, err = validate_recurrence_choice(valid)
        assert is_valid is True
        assert err is None

    for invalid in ['x', 'weekly', 'none', '', None]:
        is_valid, err = validate_recurrence_choice(invalid)
        assert is_valid is False
        assert "Invalid recurrence option. Choose n, d, w, m, or r." in err


def test_weekdays_validation():
    is_valid, days, err = validate_weekdays("mon-fri")
    assert is_valid is True
    assert days == ['mon', 'tue', 'wed', 'thu', 'fri']

    is_valid, days, err = validate_weekdays("mon,wed,fri")
    assert is_valid is True
    assert days == ['mon', 'wed', 'fri']

    is_valid, _, err = validate_weekdays("invalid_day")
    assert is_valid is False

    is_valid, _, err = validate_weekdays("")
    assert is_valid is False


def test_month_day_validation():
    assert validate_month_day("1")[0] is True
    assert validate_month_day("15")[0] is True
    assert validate_month_day("31")[0] is True

    assert validate_month_day("0")[0] is False
    assert validate_month_day("32")[0] is False
    assert validate_month_day("abc")[0] is False


def test_rrule_validation():
    assert validate_rrule("FREQ=WEEKLY;BYDAY=MO,WE,FR")[0] is True
    assert validate_rrule("RRULE:FREQ=DAILY")[0] is True

    is_valid, err = validate_rrule("INVALID_RULE")
    assert is_valid is False
    assert "Invalid RRULE format." in err


def test_end_condition_validation():
    assert validate_end_condition("n")[0] is True
    assert validate_end_condition("u")[0] is True
    assert validate_end_condition("c")[0] is True

    assert validate_end_condition("x")[0] is False


def test_until_date_validation():
    assert validate_until_date("2026-12-31")[0] is True
    assert validate_until_date("2026-12-32")[0] is False
    assert validate_until_date("invalid")[0] is False


def test_occurrence_count_validation():
    assert validate_occurrence_count("5")[0] is True
    assert validate_occurrence_count("0")[0] is False
    assert validate_occurrence_count("-1")[0] is False
    assert validate_occurrence_count("abc")[0] is False


# ==============================================================================
# 5. Reminders & Channel Validation Tests
# ==============================================================================
def test_reminders_validation():
    valid_cases = ["30m", "1h", "1d", "30m,1h,1d", " 15m , 2h "]
    for r in valid_cases:
        is_valid, tokens, err = validate_reminders(r)
        assert is_valid is True
        assert err is None
        assert len(tokens) >= 1

    invalid_cases = ["abc", "xyz", "hello", "0m", "-5m", "30x", ""]
    for r in invalid_cases:
        is_valid, _, err = validate_reminders(r)
        assert is_valid is False
        assert "Invalid reminder format. Use values such as 30m, 1h, or 1d." in err


def test_notification_channels_validation():
    # Valid channels
    assert validate_notification_channels("")[0] is True
    assert validate_notification_channels("   ")[0] is True
    assert validate_notification_channels("c")[0] is True
    assert validate_notification_channels("d")[0] is True
    assert validate_notification_channels("e")[0] is True
    assert validate_notification_channels("c,d")[0] is True
    assert validate_notification_channels("c d e")[0] is True

    # Invalid channel
    is_valid, _, err = validate_notification_channels("x")
    assert is_valid is False
    assert "Invalid notification channel. Choose c, d, e, or press Enter for cli." in err

    is_valid, _, err = validate_notification_channels("c,x")
    assert is_valid is False


# ==============================================================================
# 6. Interactive Flow Simulation: Retry Loop & Input Preservation
# ==============================================================================
def test_interactive_create_flow_retry_on_invalid_datetime():
    """
    Simulates the exact user scenario:
    1. User selects Calendar [1] (or enters '1')
    2. User enters Title 'Birthday' (first empty, then 'Birthday')
    3. User enters invalid Start '2026-09-16' (date only), gets error, re-enters '2026-09-16 00:00'
    4. User enters invalid End '2026-09-16' (date only), gets error,
       enters End before Start '2026-09-15 10:00', gets error,
       then enters valid End '2026-09-16 23:59'
    5. Description: 'Fazeela Birthday'
    6. Location: ''
    7. Recurrence: first enters 'x' (invalid), gets error, then 'n'
    8. Reminders: 'y'
    9. Reminders input: first enters 'abc' (invalid), gets error, then '1d'
    10. Channels: first enters 'x' (invalid), gets error, then 'e'
    11. Final command executed successfully with validated inputs.
    """
    menu = InteractiveMenu()

    mock_cal_resolver = MagicMock()
    mock_cal_resolver.prompt_selection.return_value = 'primary'

    inputs = [
        # Title: empty, then valid
        "",
        "Birthday",
        # Start: date-only, then valid
        "2026-09-16",
        "2026-09-16 00:00",
        # End: date-only, then before start, then valid
        "2026-09-16",
        "2026-09-15 10:00",
        "2026-09-16 23:59",
        # Description
        "Fazeela Birthday",
        # Location
        "",
        # Recurrence: invalid 'x', then 'n'
        "x",
        "n",
        # Add reminders? 'y'
        "y",
        # Reminders: invalid 'abc', then '1d'
        "abc",
        "1d",
        # Channels: invalid 'x', then 'e'
        "x",
        "e",
        # Press enter to continue
        "",
    ]

    with patch('builtins.input', side_effect=inputs), \
         patch('gsuite_cli.ui.interactive.CalendarResolver.prompt_selection', return_value='primary'), \
         patch('subprocess.call') as mock_subproc, \
         patch.object(menu, 'clear_screen'):

        menu.execute_command('1', 'create')

        # Verify subprocess.call was called with the validated values!
        assert mock_subproc.called
        cmd = mock_subproc.call_args[0][0]
        assert '--title "Birthday"' in cmd
        assert '--start "2026-09-16 00:00"' in cmd
        assert '--end "2026-09-16 23:59"' in cmd
        assert '--description "Fazeela Birthday"' in cmd
        assert '--remind 1d' in cmd
        assert '--notify email' in cmd
        assert '--calendar-id "primary"' in cmd
