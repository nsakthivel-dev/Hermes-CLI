"""
Unit tests for Booking Orchestration layer.

Tests coordinate Calendar and Meet services with mocked responses.
Run with: pytest tests/test_booking.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import pytest
from click.testing import CliRunner

from gsuite_cli.services.booking import BookingService
from gsuite_cli.services.calendar import CalendarService
from gsuite_cli.services.meet import MeetService
from gsuite_cli.config.manager import ConfigManager


@pytest.fixture
def mock_calendar_service():
    svc = MagicMock(spec=CalendarService)
    svc.oauth_manager = MagicMock()
    return svc


@pytest.fixture
def mock_meet_service():
    svc = MagicMock(spec=MeetService)
    return svc


@pytest.fixture
def booking_service(tmp_path, mock_calendar_service, mock_meet_service):
    cfg = MagicMock(spec=ConfigManager)
    cfg.data_dir = tmp_path
    return BookingService(
        config_manager=cfg,
        calendar_service=mock_calendar_service,
        meet_service=mock_meet_service
    )


class TestBookingOrchestration:
    def test_quick_meeting_with_online_meet(self, booking_service, mock_calendar_service, mock_meet_service):
        mock_meet_service.create_space.return_value = {
            'name': 'spaces/abc123',
            'meeting_uri': 'https://meet.google.com/abc-defg-hij',
            'meeting_code': 'abc-defg-hij',
        }
        mock_calendar_service.create_event.return_value = 'event_12345'
        
        start = datetime(2026, 9, 6, 14, 0)
        res = booking_service.quick_meeting(
            title="Team Sync",
            start_time=start,
            duration_minutes=45,
            attendees=["team@example.com"],
            is_online=True
        )
        
        assert res['success'] is True
        assert res['event_id'] == 'event_12345'
        assert res['meet_uri'] == 'https://meet.google.com/abc-defg-hij'
        assert mock_meet_service.create_space.called
        assert mock_calendar_service.create_event.called
        
        call_kwargs = mock_calendar_service.create_event.call_args.kwargs
        assert call_kwargs['summary'] == 'Team Sync'
        assert call_kwargs['meet_link'] == 'https://meet.google.com/abc-defg-hij'
        assert 'https://meet.google.com/abc-defg-hij' in call_kwargs['description']

    def test_quick_meeting_without_online_meet(self, booking_service, mock_calendar_service, mock_meet_service):
        mock_calendar_service.create_event.return_value = 'event_in_person'
        
        start = datetime(2026, 9, 6, 11, 0)
        res = booking_service.quick_meeting(
            title="Coffee Chat",
            start_time=start,
            duration_minutes=30,
            location="Cafe Central",
            is_online=False
        )
        
        assert res['success'] is True
        assert res['event_id'] == 'event_in_person'
        assert res['meet_uri'] == ''
        assert not mock_meet_service.create_space.called

    def test_quick_meeting_handles_meet_service_failure(self, booking_service, mock_calendar_service, mock_meet_service):
        mock_meet_service.create_space.side_effect = Exception("Meet API Error")
        mock_calendar_service.create_event.return_value = 'event_fallback'
        
        start = datetime(2026, 9, 6, 16, 0)
        res = booking_service.quick_meeting(
            title="Design Review",
            start_time=start,
            is_online=True
        )
        
        # Calendar event is still created gracefully with create_meet fallback flag
        assert res['success'] is True
        assert res['event_id'] == 'event_fallback'

    def test_schedule_meeting(self, booking_service, mock_calendar_service, mock_meet_service):
        mock_meet_service.create_space.return_value = {
            'meeting_uri': 'https://meet.google.com/sched-123',
            'meeting_code': 'sched-123'
        }
        mock_calendar_service.create_event.return_value = 'sched_event_1'
        
        start = datetime(2026, 9, 7, 15, 0)
        end = datetime(2026, 9, 7, 16, 0)
        res = booking_service.schedule_meeting(
            title="Quarterly Review",
            start_time=start,
            end_time=end,
            attendees=["exec@example.com"],
            is_online=True
        )
        
        assert res['success'] is True
        assert res['duration_minutes'] == 60
        assert res['event_id'] == 'sched_event_1'

    def test_find_available_time(self, booking_service, mock_calendar_service):
        # Mock busy time: 10:00 to 11:30 and 13:00 to 14:00
        mock_calendar_service.get_free_busy.return_value = {
            'calendars': {
                'primary': {
                    'busy': [
                        {'start': '2026-09-08T10:00:00Z', 'end': '2026-09-08T11:30:00Z'},
                        {'start': '2026-09-08T13:00:00Z', 'end': '2026-09-08T14:00:00Z'},
                    ]
                }
            }
        }
        
        slots = booking_service.find_available_time(
            target_date="2026-09-08",
            start_hour=9,
            end_hour=15,
            duration_minutes=30,
            time_zone="UTC"
        )
        
        assert len(slots) > 0
        # 09:00 - 09:30 should be free
        assert slots[0]['start_formatted'] == '09:00 AM'
        assert slots[0]['end_formatted'] == '09:30 AM'
        
        # 10:00 - 10:30 should NOT be free
        for s in slots:
            assert s['start_formatted'] != '10:00 AM'
            assert s['start_formatted'] != '10:30 AM'
            assert s['start_formatted'] != '11:00 AM'
            assert s['start_formatted'] != '01:00 PM'

    def test_reschedule_meeting_preserves_meet(self, booking_service, mock_calendar_service):
        mock_calendar_service.get_event.return_value = {
            'id': 'ev_to_resched',
            'summary': '1:1 Catchup',
            'start': '2026-09-06T10:00:00Z',
            'end': '2026-09-06T10:30:00Z',
            'meet_link': 'https://meet.google.com/existing-meet',
            'time_zone': 'UTC',
        }
        mock_calendar_service.update_event.return_value = True
        
        new_start = datetime(2026, 9, 6, 14, 0)
        res = booking_service.reschedule_meeting('ev_to_resched', new_start=new_start, duration_minutes=30)
        
        assert res['success'] is True
        assert res['meet_link'] == 'https://meet.google.com/existing-meet'
        assert mock_calendar_service.update_event.called

    def test_cancel_meeting(self, booking_service, mock_calendar_service):
        mock_calendar_service.delete_event.return_value = True
        success = booking_service.cancel_meeting('ev_delete_me')
        assert success is True
        mock_calendar_service.delete_event.assert_called_with(event_id='ev_delete_me', calendar_id='primary')


class TestBookingCLICommands:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    @pytest.fixture
    def cli_context(self):
        from gsuite_cli.config.manager import ConfigManager
        oauth = MagicMock()
        oauth.is_authenticated.return_value = True
        return {
            'oauth_manager': oauth,
            'config_manager': ConfigManager(),
            'cache_manager': None,
        }

    def test_cli_booking_quick(self, runner, cli_context):
        from gsuite_cli.cli import booking_quick
        with patch.object(BookingService, 'quick_meeting') as mock_qm:
            mock_qm.return_value = {
                'success': True,
                'event_id': 'quick_1',
                'title': 'Test Quick',
                'start': '2026-09-06T14:00:00',
                'end': '2026-09-06T14:30:00',
                'meet_uri': 'https://meet.google.com/quick-link',
                'attendees': ['dev@example.com']
            }
            result = runner.invoke(
                booking_quick,
                ['--title', 'Test Quick', '--start', '2026-09-06 14:00', '--duration', '30'],
                obj=cli_context
            )
            assert result.exit_code == 0
            assert "Meeting created successfully" in result.output
            assert "https://meet.google.com/quick-link" in result.output

    def test_cli_booking_availability(self, runner, cli_context):
        from gsuite_cli.cli import booking_availability
        with patch.object(BookingService, 'find_available_time') as mock_fat:
            mock_fat.return_value = [
                {'display': '10:00 AM - 10:30 AM', 'start': '10:00', 'end': '10:30'},
                {'display': '11:00 AM - 11:30 AM', 'start': '11:00', 'end': '11:30'},
            ]
            result = runner.invoke(
                booking_availability,
                ['--date', '2026-09-08', '--duration', '30'],
                obj=cli_context
            )
            assert result.exit_code == 0
            assert "AVAILABLE TIME SLOTS" in result.output
            assert "10:00 AM - 10:30 AM" in result.output

    def test_cli_booking_cancel(self, runner, cli_context):
        from gsuite_cli.cli import booking_cancel
        with patch.object(BookingService, 'cancel_meeting') as mock_cancel:
            mock_cancel.return_value = True
            result = runner.invoke(
                booking_cancel,
                ['ev123', '--yes'],
                obj=cli_context
            )
            assert result.exit_code == 0
            assert "cancelled and removed" in result.output
