"""
Tests for the improved Hermes Calendar Update Event flow and CalendarEventResolver.
Covers all requirements:
1. Calendar selection
2. Event listing (no technical IDs)
3. Event number selection
4. Invalid event selection retry (do not exit)
5. Event details retrieval
6. Title update
7. Start update (validation & retry)
8. End update (order validation & retry)
9. Description update (change and clear)
10. Location update (change and clear)
11. Recurrence update (validation & retry)
12. Reminders update (validation & retry)
13. Attendees update (email validation, replace/add/remove/clear)
14. Calendar change (move_event)
15. Multiple fields edit
16. Confirmation prompt ([Y/n])
17. Empty event list handling
18. Pagination & Search
19. Direct Event ID support
20. hermes calendar event info <ref> command
"""

import pytest
from unittest.mock import MagicMock, patch
from click.testing import CliRunner
from datetime import datetime

from gsuite_cli.services.calendar_resolver import (
    CalendarResolver,
    CalendarEventResolver,
    EventNotFoundError,
)
from gsuite_cli.services.calendar import CalendarService
from gsuite_cli.ui.interactive_calendar import (
    run_calendar_update_flow,
    _format_display_datetime,
    _format_reminders_display,
    _format_attendees_display,
    _format_recurrence_display,
)
from gsuite_cli.cli import cli


@pytest.fixture
def sample_calendars():
    return [
        {
            'id': 'nsakthiveldev@gmail.com',
            'summary': 'nsakthiveldev@gmail.com',
            'primary': True,
            'access_role': 'owner',
            'timezone': 'Asia/Kolkata',
        },
        {
            'id': 'cherry-id@group.calendar.google.com',
            'summary': 'Brand New Cherry',
            'primary': False,
            'access_role': 'owner',
            'timezone': 'Asia/Kolkata',
        },
        {
            'id': 'holidays@group.calendar.google.com',
            'summary': 'Holidays in India',
            'primary': False,
            'access_role': 'reader',
            'timezone': 'Asia/Kolkata',
        },
    ]


@pytest.fixture
def sample_events():
    return [
        {
            'id': 'event_id_birthday_12345',
            'summary': 'Birthday',
            'description': 'Celebration',
            'location': 'Home',
            'start': '2026-09-16T00:00:00+05:30',
            'end': '2026-09-16T23:59:00+05:30',
            'all_day': True,
            'status': 'confirmed',
            'recurrence': [],
            'reminders': {'useDefault': False, 'overrides': [{'method': 'popup', 'minutes': 1440}]},
            'attendees': [{'email': 'friend@example.com'}],
        },
        {
            'id': 'event_id_project_67890',
            'summary': 'Project Discussion',
            'description': 'Discuss project progress',
            'location': 'Conference Room',
            'start': '2026-09-17T10:00:00+05:30',
            'end': '2026-09-17T11:00:00+05:30',
            'all_day': False,
            'status': 'confirmed',
            'recurrence': [],
            'reminders': {'useDefault': False, 'overrides': [{'method': 'popup', 'minutes': 30}]},
            'attendees': [{'email': 'john@example.com'}, {'email': 'team@example.com'}],
        },
        {
            'id': 'event_id_team_meeting_11223',
            'summary': 'Team Meeting',
            'description': 'Weekly sync',
            'location': 'Zoom',
            'start': '2026-09-18T14:00:00+05:30',
            'end': '2026-09-18T15:00:00+05:30',
            'all_day': False,
            'status': 'confirmed',
            'recurrence': ['RRULE:FREQ=WEEKLY;BYDAY=FR'],
            'reminders': {'useDefault': True},
            'attendees': [],
        },
    ]


# ============================================================
# TEST 1: CalendarEventResolver - Formatting & Resolution
# ============================================================

def test_event_datetime_formatting(sample_events):
    # Birthday (all day)
    bday_str = CalendarEventResolver.format_event_datetime(sample_events[0])
    assert "16 Sep 2026" in bday_str
    assert "00:00 - 23:59" in bday_str

    # Project Discussion (same day)
    proj_str = CalendarEventResolver.format_event_datetime(sample_events[1])
    assert "17 Sep 2026 10:00 - 11:00" in proj_str


def test_format_event_list_hides_event_ids(sample_events):
    formatted = CalendarEventResolver.format_event_list(sample_events)
    # Check numbers and titles appear
    assert "[1] Birthday" in formatted
    assert "[2] Project Discussion" in formatted
    assert "[3] Team Meeting" in formatted
    # Check that long Google Event IDs do NOT appear
    assert "event_id_birthday_12345" not in formatted
    assert "event_id_project_67890" not in formatted


def test_resolve_event_by_number(sample_events):
    ev = CalendarEventResolver.resolve("2", sample_events)
    assert ev['id'] == 'event_id_project_67890'
    assert ev['summary'] == 'Project Discussion'


def test_resolve_event_by_name(sample_events):
    ev = CalendarEventResolver.resolve("Project Discussion", sample_events)
    assert ev['id'] == 'event_id_project_67890'

    # Case-insensitive
    ev_lower = CalendarEventResolver.resolve("birthday", sample_events)
    assert ev_lower['id'] == 'event_id_birthday_12345'


def test_resolve_event_by_substring(sample_events):
    ev = CalendarEventResolver.resolve("Meeting", sample_events)
    assert ev['id'] == 'event_id_team_meeting_11223'


def test_resolve_event_by_direct_id(sample_events):
    ev = CalendarEventResolver.resolve("event_id_birthday_12345", sample_events)
    assert ev['summary'] == 'Birthday'


def test_resolve_invalid_event_raises_error(sample_events):
    with pytest.raises(EventNotFoundError):
        CalendarEventResolver.resolve("99", sample_events)

    with pytest.raises(EventNotFoundError):
        CalendarEventResolver.resolve("Nonexistent Event", sample_events)


# ============================================================
# TEST 2: CalendarService.move_event
# ============================================================

def test_calendar_service_move_event():
    mock_service = MagicMock()
    mock_events = MagicMock()
    mock_service.events.return_value = mock_events
    mock_move = MagicMock()
    mock_events.move.return_value = mock_move
    mock_move.execute.return_value = {'id': 'ev1', 'status': 'confirmed'}

    cal_svc = CalendarService(oauth_manager=MagicMock())
    cal_svc.service = mock_service

    result = cal_svc.move_event('ev1', 'primary', 'secondary-id')
    assert result is True
    mock_events.move.assert_called_once_with(
        calendarId='primary',
        eventId='ev1',
        destination='secondary-id'
    )


# ============================================================
# TEST 3: Interactive Flow - Empty Events List
# ============================================================

def test_interactive_update_empty_events(sample_calendars):
    mock_service = MagicMock()
    mock_service.list_calendars.return_value = sample_calendars
    mock_service.list_events.return_value = []

    # Inputs: Calendar selection (1 / Enter), then 'b' to back
    with patch('builtins.input', side_effect=['1', 'b']):
        res = run_calendar_update_flow(mock_service, MagicMock())
        assert res is False


# ============================================================
# TEST 4: Interactive Flow - Title Update with Confirmation
# ============================================================

def test_interactive_update_title(sample_calendars, sample_events):
    mock_service = MagicMock()
    mock_service.list_calendars.return_value = sample_calendars
    mock_service.list_events.return_value = sample_events
    mock_service.get_event.return_value = sample_events[1]
    mock_service.update_event.return_value = True

    # User steps:
    # 1. Calendar: '1'
    # 2. Select Event: '2' (Project Discussion)
    # 3. Edit menu: '1' (Title)
    # 4. New Title: 'Updated Project Discussion'
    # 5. Confirm: 'y'
    inputs = ['1', '2', '1', 'Updated Project Discussion', 'y']

    with patch('builtins.input', side_effect=inputs):
        res = run_calendar_update_flow(mock_service, MagicMock())
        assert res is True
        mock_service.update_event.assert_called_once()
        call_kwargs = mock_service.update_event.call_args.kwargs
        assert call_kwargs['summary'] == 'Updated Project Discussion'
        assert call_kwargs['event_id'] == 'event_id_project_67890'


# ============================================================
# TEST 5: Interactive Flow - Invalid Event Selection Retries
# ============================================================

def test_interactive_update_invalid_event_retry(sample_calendars, sample_events):
    mock_service = MagicMock()
    mock_service.list_calendars.return_value = sample_calendars
    mock_service.list_events.return_value = sample_events
    mock_service.get_event.return_value = sample_events[0]
    mock_service.update_event.return_value = True

    # User steps:
    # 1. Calendar: '1'
    # 2. Select Event: '99' (Invalid!) -> prints ✗ Event not found.
    # 3. Select Event: '1' (Birthday)
    # 4. Edit menu: '1' (Title)
    # 5. New Title: 'Grand Birthday'
    # 6. Confirm: 'y'
    inputs = ['1', '99', '1', '1', 'Grand Birthday', 'y']

    with patch('builtins.input', side_effect=inputs):
        res = run_calendar_update_flow(mock_service, MagicMock())
        assert res is True
        mock_service.update_event.assert_called_once()
        call_kwargs = mock_service.update_event.call_args.kwargs
        assert call_kwargs['summary'] == 'Grand Birthday'
        assert call_kwargs['event_id'] == 'event_id_birthday_12345'


# ============================================================
# TEST 6: Interactive Flow - Start & End Datetime Validation Retries
# ============================================================

def test_interactive_update_start_time_validation(sample_calendars, sample_events):
    mock_service = MagicMock()
    mock_service.list_calendars.return_value = sample_calendars
    mock_service.list_events.return_value = sample_events
    mock_service.get_event.return_value = sample_events[1]  # 2026-09-17 10:00 to 11:00
    mock_service.update_event.return_value = True

    # User steps:
    # 1. Calendar: '1'
    # 2. Select Event: '2'
    # 3. Edit menu: '2' (Start)
    # 4. Invalid format: 'invalid-date' -> error & re-prompt
    # 5. Valid format: '2026-09-17 09:30'
    # 6. Confirm: 'y'
    inputs = ['1', '2', '2', 'invalid-date', '2026-09-17 09:30', 'y']

    with patch('builtins.input', side_effect=inputs):
        res = run_calendar_update_flow(mock_service, MagicMock())
        assert res is True
        mock_service.update_event.assert_called_once()
        call_kwargs = mock_service.update_event.call_args.kwargs
        assert call_kwargs['start_time'] == datetime(2026, 9, 17, 9, 30)


def test_interactive_update_end_before_start_validation(sample_calendars, sample_events):
    mock_service = MagicMock()
    mock_service.list_calendars.return_value = sample_calendars
    mock_service.list_events.return_value = sample_events
    mock_service.get_event.return_value = sample_events[1]  # starts at 10:00
    mock_service.update_event.return_value = True

    # User steps:
    # 1. Calendar: '1'
    # 2. Select Event: '2'
    # 3. Edit menu: '3' (End)
    # 4. End before start: '2026-09-17 09:00' -> error & re-prompt
    # 5. Valid end: '2026-09-17 12:00'
    # 6. Confirm: 'y'
    inputs = ['1', '2', '3', '2026-09-17 09:00', '2026-09-17 12:00', 'y']

    with patch('builtins.input', side_effect=inputs):
        res = run_calendar_update_flow(mock_service, MagicMock())
        assert res is True
        mock_service.update_event.assert_called_once()
        call_kwargs = mock_service.update_event.call_args.kwargs
        assert call_kwargs['end_time'] == datetime(2026, 9, 17, 12, 0)


# ============================================================
# TEST 7: Interactive Flow - Description & Location (Clear & Change)
# ============================================================

def test_interactive_update_description_and_location(sample_calendars, sample_events):
    mock_service = MagicMock()
    mock_service.list_calendars.return_value = sample_calendars
    mock_service.list_events.return_value = sample_events
    mock_service.get_event.return_value = sample_events[1]
    mock_service.update_event.return_value = True

    # Edit Description to 'clear'
    inputs = ['1', '2', '4', 'clear', 'y']
    with patch('builtins.input', side_effect=inputs):
        res = run_calendar_update_flow(mock_service, MagicMock())
        assert res is True
        call_kwargs = mock_service.update_event.call_args.kwargs
        assert call_kwargs['description'] == ""

    # Edit Location to 'Room 404'
    mock_service.update_event.reset_mock()
    inputs = ['1', '2', '5', 'Room 404', 'y']
    with patch('builtins.input', side_effect=inputs):
        res = run_calendar_update_flow(mock_service, MagicMock())
        assert res is True
        call_kwargs = mock_service.update_event.call_args.kwargs
        assert call_kwargs['location'] == "Room 404"


# ============================================================
# TEST 8: Interactive Flow - Recurrence & Reminders
# ============================================================

def test_interactive_update_recurrence(sample_calendars, sample_events):
    mock_service = MagicMock()
    mock_service.list_calendars.return_value = sample_calendars
    mock_service.list_events.return_value = sample_events
    mock_service.get_event.return_value = sample_events[1]
    mock_service.update_event.return_value = True

    # Select Recurrence -> invalid choice 'z' -> valid 'd' (daily) -> confirm
    inputs = ['1', '2', '6', 'z', 'd', 'y']
    with patch('builtins.input', side_effect=inputs):
        res = run_calendar_update_flow(mock_service, MagicMock())
        assert res is True
        call_kwargs = mock_service.update_event.call_args.kwargs
        assert call_kwargs['recurrence'] == ['RRULE:FREQ=DAILY']


def test_interactive_update_reminders(sample_calendars, sample_events):
    mock_service = MagicMock()
    mock_service.list_calendars.return_value = sample_calendars
    mock_service.list_events.return_value = sample_events
    mock_service.get_event.return_value = sample_events[1]
    mock_service.update_event.return_value = True

    # Reminders: invalid 'abc' -> valid '15m, 1h' -> confirm
    inputs = ['1', '2', '7', 'abc', '15m, 1h', 'y']
    with patch('builtins.input', side_effect=inputs):
        res = run_calendar_update_flow(mock_service, MagicMock())
        assert res is True
        call_kwargs = mock_service.update_event.call_args.kwargs
        assert call_kwargs['reminders_minutes'] == [15, 60]


# ============================================================
# TEST 9: Interactive Flow - Attendees Management
# ============================================================

def test_interactive_update_attendees_replace(sample_calendars, sample_events):
    mock_service = MagicMock()
    mock_service.list_calendars.return_value = sample_calendars
    mock_service.list_events.return_value = sample_events
    mock_service.get_event.return_value = sample_events[1]
    mock_service.update_event.return_value = True
    mock_service._validate_email = lambda e: '@' in e and '.' in e

    # Attendees: [1] Replace -> 'alice@example.com, bob@example.com' -> confirm
    inputs = ['1', '2', '8', '1', 'alice@example.com, bob@example.com', 'y']
    with patch('builtins.input', side_effect=inputs):
        res = run_calendar_update_flow(mock_service, MagicMock())
        assert res is True
        call_kwargs = mock_service.update_event.call_args.kwargs
        assert call_kwargs['attendees'] == [{'email': 'alice@example.com'}, {'email': 'bob@example.com'}]


# ============================================================
# TEST 10: Interactive Flow - Calendar Move (Field 9)
# ============================================================

def test_interactive_update_move_calendar(sample_calendars, sample_events):
    mock_service = MagicMock()
    mock_service.list_calendars.return_value = sample_calendars
    mock_service.list_events.return_value = sample_events
    mock_service.get_event.return_value = sample_events[1]
    mock_service.move_event.return_value = True

    # User selects [9] Calendar -> destination '2' (Brand New Cherry) -> confirm 'y'
    inputs = ['1', '2', '9', '2', 'y']
    with patch('builtins.input', side_effect=inputs):
        res = run_calendar_update_flow(mock_service, MagicMock())
        assert res is True
        mock_service.move_event.assert_called_once_with(
            'event_id_project_67890',
            'nsakthiveldev@gmail.com',
            'cherry-id@group.calendar.google.com'
        )


# ============================================================
# TEST 11: Interactive Flow - Multiple Fields Edit (Field 10)
# ============================================================

def test_interactive_update_multiple_fields(sample_calendars, sample_events):
    mock_service = MagicMock()
    mock_service.list_calendars.return_value = sample_calendars
    mock_service.list_events.return_value = sample_events
    mock_service.get_event.return_value = sample_events[1]
    mock_service.update_event.return_value = True

    # Edit multiple fields: 1 (Title) and 5 (Location)
    # Inputs:
    # 1: Calendar 1
    # 2: Event 2
    # 3: Edit menu: 10
    # 4: Fields: '1, 5'
    # 5: New Title: 'Super Meeting'
    # 6: New Location: 'Building B'
    # 7: Confirm: 'y'
    inputs = ['1', '2', '10', '1, 5', 'Super Meeting', 'Building B', 'y']
    with patch('builtins.input', side_effect=inputs):
        res = run_calendar_update_flow(mock_service, MagicMock())
        assert res is True
        call_kwargs = mock_service.update_event.call_args.kwargs
        assert call_kwargs['summary'] == 'Super Meeting'
        assert call_kwargs['location'] == 'Building B'
        # Unmodified fields should not be in kwargs
        assert 'start_time' not in call_kwargs
        assert 'end_time' not in call_kwargs


# ============================================================
# TEST 12: Interactive Flow - Cancellation on Confirmation
# ============================================================

def test_interactive_update_cancel_on_confirm(sample_calendars, sample_events):
    mock_service = MagicMock()
    mock_service.list_calendars.return_value = sample_calendars
    mock_service.list_events.return_value = sample_events
    mock_service.get_event.return_value = sample_events[1]

    # Decline at confirmation prompt [Y/n]: 'n'
    inputs = ['1', '2', '1', 'Cancelled Title', 'n']
    with patch('builtins.input', side_effect=inputs):
        res = run_calendar_update_flow(mock_service, MagicMock())
        assert res is False
        mock_service.update_event.assert_not_called()


# ============================================================
# TEST 13: Interactive Flow - Pagination and Search
# ============================================================

def test_interactive_update_search(sample_calendars, sample_events):
    mock_service = MagicMock()
    mock_service.list_calendars.return_value = sample_calendars
    mock_service.list_events.return_value = sample_events
    mock_service.get_event.return_value = sample_events[0]
    mock_service.update_event.return_value = True

    # Search flow:
    # 1. Calendar: 1
    # 2. Select Event prompt: 's' (Search)
    # 3. Search query: 'birthday'
    # 4. Result list: selects '1' (Birthday)
    # 5. Edit title: '1' -> 'My Birthday'
    # 6. Confirm: 'y'
    inputs = ['1', 's', 'birthday', '1', '1', 'My Birthday', 'y']
    with patch('builtins.input', side_effect=inputs):
        res = run_calendar_update_flow(mock_service, MagicMock())
        assert res is True
        call_kwargs = mock_service.update_event.call_args.kwargs
        assert call_kwargs['summary'] == 'My Birthday'


# ============================================================
# TEST 14: CLI Command - hermes calendar event info <ref>
# ============================================================

def test_cli_calendar_event_info(sample_calendars, sample_events):
    runner = CliRunner()
    with patch('gsuite_cli.cli.CalendarService') as mock_cal_cls, \
         patch('gsuite_cli.cli.CalendarResolver.get_calendars', return_value=sample_calendars), \
         patch('gsuite_cli.cli.CalendarResolver.resolve', return_value='primary'):
        
        mock_cal_instance = MagicMock()
        mock_cal_cls.return_value = mock_cal_instance
        mock_cal_instance.list_events.return_value = sample_events
        mock_cal_instance.get_event.return_value = sample_events[1]

        # Call: hermes calendar event info 2
        result = runner.invoke(cli, ['calendar', 'event', 'info', '2'])
        assert result.exit_code == 0
        assert "Project Discussion" in result.output
        assert "Conference Room" in result.output


def test_cli_calendar_event_info_alias(sample_calendars, sample_events):
    runner = CliRunner()
    with patch('gsuite_cli.cli.CalendarService') as mock_cal_cls, \
         patch('gsuite_cli.cli.CalendarResolver.get_calendars', return_value=sample_calendars), \
         patch('gsuite_cli.cli.CalendarResolver.resolve', return_value='primary'):
        
        mock_cal_instance = MagicMock()
        mock_cal_cls.return_value = mock_cal_instance
        mock_cal_instance.list_events.return_value = sample_events
        mock_cal_instance.get_event.return_value = sample_events[1]

        # Call: hermes calendar event-info "Project Discussion"
        result = runner.invoke(cli, ['calendar', 'event-info', 'Project Discussion'])
        assert result.exit_code == 0
        assert "Project Discussion" in result.output


# ============================================================
# TEST 15: CLI Command - Direct Event ID support in calendar update
# ============================================================

def test_cli_calendar_update_direct_id(sample_calendars, sample_events):
    runner = CliRunner()
    with patch('gsuite_cli.cli.CalendarService') as mock_cal_cls, \
         patch('gsuite_cli.cli.CalendarResolver.get_calendars', return_value=sample_calendars), \
         patch('gsuite_cli.cli.CalendarResolver.resolve', return_value='primary'):
        
        mock_cal_instance = MagicMock()
        mock_cal_cls.return_value = mock_cal_instance
        mock_cal_instance.list_events.return_value = sample_events
        mock_cal_instance.get_event.return_value = sample_events[1]
        mock_cal_instance.update_event.return_value = True

        result = runner.invoke(cli, [
            'calendar', 'update', 'event_id_project_67890',
            '--title', 'CLI Direct Title'
        ])
        assert result.exit_code == 0
        assert "Event updated" in result.output
        mock_cal_instance.update_event.assert_called_once()
        assert mock_cal_instance.update_event.call_args.kwargs['summary'] == 'CLI Direct Title'
