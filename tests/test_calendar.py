"""
Unit tests for Google Calendar module.

All tests mock Google API service calls — no live Google account or network requests required.
Run with: pytest tests/test_calendar.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import pytest
from click.testing import CliRunner
from googleapiclient.errors import HttpError

from gsuite_cli.services.calendar import CalendarService


def _make_http_error(status: int = 400, reason: str = "Error") -> HttpError:
    resp = MagicMock()
    resp.status = status
    resp.reason = reason
    return HttpError(resp=resp, content=reason.encode())


@pytest.fixture
def mock_oauth_manager():
    oauth = MagicMock()
    oauth.is_authenticated.return_value = True
    oauth.get_auth_info.return_value = {
        'authenticated': True,
        'valid': True,
        'expired': False,
        'token_expiry': '2026-12-31T23:59:59',
        'refresh_token': True,
    }
    return oauth


@pytest.fixture
def calendar_service(mock_oauth_manager):
    svc = CalendarService(mock_oauth_manager)
    svc.service = MagicMock()
    return svc


class TestCalendarServiceCalendars:
    def test_list_calendars(self, calendar_service):
        calendar_service.service.calendarList().list().execute.return_value = {
            'items': [
                {
                    'id': 'primary',
                    'summary': 'Primary Calendar',
                    'description': 'Main calendar',
                    'timeZone': 'UTC',
                    'primary': True,
                    'accessRole': 'owner',
                    'location': 'Earth',
                },
                {
                    'id': 'sec1@group.calendar.google.com',
                    'summary': 'Project Work',
                    'description': 'Work calendar',
                    'timeZone': 'America/New_York',
                    'primary': False,
                    'accessRole': 'writer',
                    'location': 'Office',
                }
            ]
        }
        calendars = calendar_service.list_calendars()
        assert len(calendars) == 2
        assert calendars[0]['id'] == 'primary'
        assert calendars[0]['primary'] is True
        assert calendars[1]['summary'] == 'Project Work'
        assert calendars[1]['timezone'] == 'America/New_York'

    def test_list_calendars_pagination(self, calendar_service):
        mock_list = calendar_service.service.calendarList().list
        mock_list.return_value.execute.side_effect = [
            {
                'items': [{'id': 'c1', 'summary': 'Cal 1', 'primary': False}],
                'nextPageToken': 'token123'
            },
            {
                'items': [{'id': 'c2', 'summary': 'Cal 2', 'primary': False}],
            }
        ]
        calendars = calendar_service.list_calendars(max_results=10)
        assert len(calendars) == 2
        assert calendars[0]['id'] == 'c1'
        assert calendars[1]['id'] == 'c2'

    def test_get_calendar_success(self, calendar_service):
        calendar_service.service.calendarList().get().execute.return_value = {
            'id': 'cal123',
            'summary': 'Test Calendar',
            'description': 'A test cal',
            'timeZone': 'UTC',
            'accessRole': 'owner',
            'primary': True
        }
        cal = calendar_service.get_calendar('cal123')
        assert cal is not None
        assert cal['summary'] == 'Test Calendar'
        assert cal['primary'] is True

    def test_get_calendar_not_found(self, calendar_service):
        calendar_service.service.calendarList().get().execute.side_effect = _make_http_error(404, "Not Found")
        calendar_service.service.calendars().get().execute.side_effect = _make_http_error(404, "Not Found")
        cal = calendar_service.get_calendar('nonexistent')
        assert cal is None

    def test_create_calendar(self, calendar_service):
        calendar_service.service.calendars().insert().execute.return_value = {
            'id': 'new_cal_id',
            'summary': 'New Calendar',
        }
        created = calendar_service.create_calendar(summary='New Calendar', time_zone='UTC')
        assert created is not None
        assert created['id'] == 'new_cal_id'

    def test_update_calendar(self, calendar_service):
        calendar_service.service.calendars().patch().execute.return_value = {
            'id': 'cal1',
            'summary': 'Updated Title',
        }
        success = calendar_service.update_calendar('cal1', summary='Updated Title')
        assert success is True
        calendar_service.service.calendars().patch.assert_called_with(
            calendarId='cal1',
            body={'summary': 'Updated Title'}
        )

    def test_delete_calendar(self, calendar_service):
        calendar_service.list_calendars = MagicMock(return_value=[{
            'id': 'sec_cal',
            'primary': False,
            'access_role': 'owner'
        }])
        success = calendar_service.delete_calendar('sec_cal')
        assert success is True
        calendar_service.service.calendars().delete.assert_called_with(calendarId='sec_cal')

    def test_delete_primary_calendar_rejected(self, calendar_service):
        calendar_service.list_calendars = MagicMock(return_value=[{
            'id': 'primary',
            'primary': True,
            'access_role': 'owner'
        }])
        success = calendar_service.delete_calendar('primary')
        assert success is False

    def test_connection_test(self, calendar_service):
        calendar_service.service.calendarList().list().execute.return_value = {'items': [{'id': 'primary'}]}
        res = calendar_service.test_connection()
        assert res['connected'] is True
        assert res['count'] == 1


class TestCalendarServiceEvents:
    def test_list_events_with_meet_extraction(self, calendar_service):
        calendar_service.service.events().list().execute.return_value = {
            'items': [
                {
                    'id': 'e1',
                    'summary': 'Sprint Review',
                    'start': {'dateTime': '2026-09-06T10:00:00Z'},
                    'end': {'dateTime': '2026-09-06T10:30:00Z'},
                    'hangoutLink': 'https://meet.google.com/abc-defg-hij',
                    'attendees': [
                        {'email': 'dev1@example.com', 'responseStatus': 'accepted'},
                        {'email': 'dev2@example.com', 'responseStatus': 'needsAction'},
                    ],
                }
            ]
        }
        events = calendar_service.list_events()
        assert len(events) == 1
        assert events[0]['id'] == 'e1'
        assert events[0]['meet_link'] == 'https://meet.google.com/abc-defg-hij'
        assert len(events[0]['attendees']) == 2
        assert events[0]['attendees'][0]['responseStatus'] == 'accepted'

    def test_get_event_rich_details(self, calendar_service):
        calendar_service.service.events().get().execute.return_value = {
            'id': 'e100',
            'summary': 'Architecture Sync',
            'description': 'Discussing system design',
            'location': 'Conference Room A',
            'start': {'dateTime': '2026-09-06T14:00:00Z', 'timeZone': 'UTC'},
            'end': {'dateTime': '2026-09-06T15:00:00Z', 'timeZone': 'UTC'},
            'status': 'confirmed',
            'conferenceData': {
                'entryPoints': [{'entryPointType': 'video', 'uri': 'https://meet.google.com/xyz-uvwx-rst'}]
            },
            'attendees': [
                {'email': 'architect@example.com', 'displayName': 'Lead Architect', 'responseStatus': 'accepted'}
            ],
            'recurrence': ['RRULE:FREQ=WEEKLY;BYDAY=MO'],
            'reminders': {
                'useDefault': False,
                'overrides': [{'method': 'popup', 'minutes': 15}]
            }
        }
        event = calendar_service.get_event('e100')
        assert event is not None
        assert event['summary'] == 'Architecture Sync'
        assert event['meet_link'] == 'https://meet.google.com/xyz-uvwx-rst'
        assert event['recurrence'] == ['RRULE:FREQ=WEEKLY;BYDAY=MO']
        assert len(event['reminders']['overrides']) == 1

    def test_today_events_queries_time_window(self, calendar_service):
        calendar_service.list_events = MagicMock(return_value=[{'id': 'today1', 'summary': 'Morning Standup', 'start': '2026-09-06T09:30:00Z'}])
        events = calendar_service.get_today_events()
        assert len(events) == 1
        assert events[0]['id'] == 'today1'
        assert calendar_service.list_events.called
        call_kwargs = calendar_service.list_events.call_args.kwargs
        assert 'time_min' in call_kwargs and 'time_max' in call_kwargs
        assert call_kwargs['time_min'] < call_kwargs['time_max']

    def test_tomorrow_events(self, calendar_service):
        calendar_service.list_events = MagicMock(return_value=[{'id': 'tmrw1', 'summary': 'Planning'}])
        events = calendar_service.get_tomorrow_events()
        assert len(events) == 1
        assert calendar_service.list_events.called

    def test_upcoming_events(self, calendar_service):
        calendar_service.list_events = MagicMock(return_value=[{'id': 'up1', 'summary': 'Upcoming 1'}])
        events = calendar_service.get_upcoming_events(limit=5)
        assert len(events) == 1
        call_kwargs = calendar_service.list_events.call_args.kwargs
        assert call_kwargs['max_results'] == 5

    def test_events_by_date_and_range(self, calendar_service):
        calendar_service.list_events = MagicMock(return_value=[{'id': 'd1'}])
        res1 = calendar_service.get_events_by_date('2026-09-10')
        assert len(res1) == 1
        res2 = calendar_service.get_events_by_date_range('2026-09-10', '2026-09-15')
        assert len(res2) == 1

    def test_create_event_with_options(self, calendar_service):
        calendar_service.service.events().insert().execute.return_value = {'id': 'created_ev_123'}
        start = datetime(2026, 9, 6, 10, 0)
        end = datetime(2026, 9, 6, 10, 30)
        
        event_id = calendar_service.create_event(
            summary='Sprint Planning',
            start_time=start,
            end_time=end,
            attendees=['user1@example.com', 'invalid-email', 'user2@example.com'],
            reminders_minutes=[10, 30],
            recurrence=['RRULE:FREQ=WEEKLY'],
            meet_link='https://meet.google.com/test-meet'
        )
        assert event_id == 'created_ev_123'
        
        insert_kwargs = calendar_service.service.events().insert.call_args.kwargs
        body = insert_kwargs['body']
        assert body['summary'] == 'Sprint Planning'
        # Invalid email filtered out
        assert len(body['attendees']) == 2
        assert body['attendees'][0]['email'] == 'user1@example.com'
        assert body['attendees'][1]['email'] == 'user2@example.com'
        assert len(body['reminders']['overrides']) == 2
        assert body['recurrence'] == ['RRULE:FREQ=WEEKLY']
        assert 'meet.google.com/test-meet' in body['description']

    def test_update_event_partial(self, calendar_service):
        calendar_service.service.events().get().execute.return_value = {
            'id': 'ev1',
            'summary': 'Old Title',
            'description': 'Old Desc',
            'location': 'Old Loc',
            'start': {'dateTime': '2026-09-06T10:00:00Z'},
            'end': {'dateTime': '2026-09-06T10:30:00Z'},
        }
        calendar_service.service.events().update().execute.return_value = {'id': 'ev1'}
        
        success = calendar_service.update_event('ev1', summary='New Title')
        assert success is True
        
        update_body = calendar_service.service.events().update.call_args.kwargs['body']
        assert update_body['summary'] == 'New Title'
        assert update_body['description'] == 'Old Desc'

    def test_delete_event(self, calendar_service):
        calendar_service.service.events().delete().execute.return_value = {}
        assert calendar_service.delete_event('ev1') is True

    def test_delete_event_not_found(self, calendar_service):
        calendar_service.service.events().delete().execute.side_effect = _make_http_error(404, "Not Found")
        assert calendar_service.delete_event('missing') is False

    def test_free_busy(self, calendar_service):
        calendar_service.service.freebusy().query().execute.return_value = {
            'calendars': {
                'primary': {
                    'busy': [{'start': '2026-09-06T11:00:00Z', 'end': '2026-09-06T12:00:00Z'}]
                }
            }
        }
        start = datetime(2026, 9, 6, 9, 0)
        end = datetime(2026, 9, 6, 17, 0)
        fb = calendar_service.get_free_busy(time_min=start, time_max=end)
        assert 'calendars' in fb
        assert len(fb['calendars']['primary']['busy']) == 1


class TestCalendarCLICommands:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    @pytest.fixture
    def cli_context(self, mock_oauth_manager):
        from gsuite_cli.config.manager import ConfigManager
        cfg = ConfigManager()
        return {
            'oauth_manager': mock_oauth_manager,
            'config_manager': cfg,
            'cache_manager': None,
        }

    def test_cli_calendar_today(self, runner, cli_context):
        from gsuite_cli.cli import calendar_today
        with patch.object(CalendarService, 'get_today_events') as mock_today:
            mock_today.return_value = [
                {'id': 'e1', 'summary': 'Morning Sync', 'start': '2026-09-06T09:30:00', 'location': '', 'meet_link': 'https://meet.google.com/test'}
            ]
            result = runner.invoke(calendar_today, obj=cli_context)
            assert result.exit_code == 0
            assert "Morning Sync" in result.output

    def test_cli_calendar_upcoming(self, runner, cli_context):
        from gsuite_cli.cli import calendar_upcoming
        with patch.object(CalendarService, 'get_upcoming_events') as mock_up:
            mock_up.return_value = [
                {'id': 'e2', 'summary': 'Sprint Demo', 'start': '2026-09-07T14:00:00', 'location': '', 'meet_link': ''}
            ]
            result = runner.invoke(calendar_upcoming, obj=cli_context)
            assert result.exit_code == 0
            assert "Sprint Demo" in result.output

    def test_cli_calendar_get_formatted(self, runner, cli_context):
        from gsuite_cli.cli import calendar_get
        with patch.object(CalendarService, 'get_event') as mock_get:
            mock_get.return_value = {
                'id': 'e10',
                'summary': 'Roadmap Review',
                'description': 'Q4 Strategy',
                'location': 'Room 101',
                'start': '2026-09-08 10:00',
                'end': '2026-09-08 11:00',
                'status': 'confirmed',
                'meet_link': 'https://meet.google.com/xyz',
                'attendees': [{'email': 'pm@example.com', 'responseStatus': 'accepted'}],
            }
            result = runner.invoke(calendar_get, ['e10'], obj=cli_context)
            assert result.exit_code == 0
            assert "Roadmap Review" in result.output
            assert "pm@example.com" in result.output

    def test_cli_today_quick_action(self, runner, cli_context):
        from gsuite_cli.cli import cli_today
        with patch.object(CalendarService, 'get_today_events') as mock_today:
            mock_today.return_value = [
                {'id': 'e1', 'summary': 'Standup', 'start': '2026-09-06T10:00:00', 'meet_link': ''}
            ]
            result = runner.invoke(cli_today, obj=cli_context)
            assert result.exit_code == 0
            assert "TODAY'S SCHEDULE" in result.output
            assert "Standup" in result.output

    def test_cli_next_quick_action(self, runner, cli_context):
        from gsuite_cli.cli import cli_next
        future_time = (datetime.now() + timedelta(hours=2)).isoformat()
        with patch.object(CalendarService, 'get_upcoming_events') as mock_up:
            mock_up.return_value = [
                {'id': 'e1', 'summary': 'Client Call', 'start': future_time, 'location': 'Online', 'meet_link': 'https://meet.google.com/call', 'attendees': []}
            ]
            result = runner.invoke(cli_next, obj=cli_context)
            assert result.exit_code == 0
            assert "NEXT EVENT" in result.output
            assert "Client Call" in result.output
