"""
Unit tests for Google Meet Service and CLI commands
All tests mock external Google APIs (no real credentials needed).
"""

import pytest
from unittest.mock import MagicMock, patch
from click.testing import CliRunner
from googleapiclient.errors import HttpError

from gsuite_cli.services.meet import MeetService
from gsuite_cli.cli import cli


@pytest.fixture
def mock_oauth_manager():
    manager = MagicMock()
    mock_service = MagicMock()
    manager.build_service.return_value = mock_service
    manager.get_auth_info.return_value = {
        'authenticated': True,
        'valid': True,
        'expired': False,
        'token_expiry': '2026-12-31T23:59:59Z',
        'scopes': ['https://www.googleapis.com/auth/meetings.space.created'],
    }
    return manager


@pytest.fixture
def meet_service(mock_oauth_manager):
    return MeetService(mock_oauth_manager)


# =============================================================================
# Helper & Normalization Tests
# =============================================================================

class TestMeetHelpers:
    def test_extract_meeting_code_from_url(self):
        url = "https://meet.google.com/abc-defg-hij"
        assert MeetService.extract_meeting_code(url) == "abc-defg-hij"

    def test_extract_meeting_code_from_url_with_params(self):
        url = "https://meet.google.com/abc-defg-hij?authuser=0"
        assert MeetService.extract_meeting_code(url) == "abc-defg-hij"

    def test_extract_meeting_code_from_spaces_name(self):
        name = "spaces/abc-defg-hij"
        assert MeetService.extract_meeting_code(name) == "abc-defg-hij"

    def test_extract_meeting_code_raw(self):
        code = "abc-defg-hij"
        assert MeetService.extract_meeting_code(code) == "abc-defg-hij"

    def test_get_meeting_url(self):
        assert MeetService.get_meeting_url("abc-defg-hij") == "https://meet.google.com/abc-defg-hij"
        assert MeetService.get_meeting_url("https://meet.google.com/abc-defg-hij") == "https://meet.google.com/abc-defg-hij"

    @patch("webbrowser.open")
    def test_join_meeting_opens_browser(self, mock_browser_open, meet_service):
        mock_browser_open.return_value = True
        result = meet_service.join_meeting("abc-defg-hij")
        assert result["success"] is True
        assert result["url"] == "https://meet.google.com/abc-defg-hij"
        mock_browser_open.assert_called_once_with("https://meet.google.com/abc-defg-hij")

    def test_join_meeting_invalid_input(self, meet_service):
        result = meet_service.join_meeting("")
        assert result["success"] is False
        assert "Invalid" in result["error"]

    def test_test_connection_success(self, meet_service):
        meet_service.service.conferenceRecords().list().execute.return_value = {'conferenceRecords': []}
        result = meet_service.test_connection()
        assert result['connected'] is True
        assert result['authenticated'] is True
        assert result['api_version'] == 'v2'


# =============================================================================
# Space Management Tests
# =============================================================================

class TestMeetSpaces:
    def test_create_space_default(self, meet_service):
        meet_service.service.spaces().create().execute.return_value = {
            'name': 'spaces/space-123',
            'meetingUri': 'https://meet.google.com/abc-defg-hij',
            'meetingCode': 'abc-defg-hij',
            'config': {'accessType': 'RESTRICTED'}
        }
        space = meet_service.create_space(config={'accessType': 'RESTRICTED'})
        assert space is not None
        assert space['name'] == 'spaces/space-123'
        assert space['meeting_code'] == 'abc-defg-hij'
        assert space['meeting_uri'] == 'https://meet.google.com/abc-defg-hij'

    def test_create_space_fallback_on_access_type_error(self, meet_service):
        resp = MagicMock()
        resp.status = 400
        http_err = HttpError(resp, b"updateAccessType is not available to the user")
        
        # First call fails with HttpError, second call with empty body succeeds
        meet_service.service.spaces().create.return_value.execute.side_effect = [
            http_err,
            {
                'name': 'spaces/fallback-123',
                'meetingUri': 'https://meet.google.com/xyz-uvwx-rst',
                'meetingCode': 'xyz-uvwx-rst',
                'config': {}
            }
        ]
        
        space = meet_service.create_space(config={'accessType': 'RESTRICTED'})
        assert space is not None
        assert space['name'] == 'spaces/fallback-123'
        assert space['meeting_code'] == 'xyz-uvwx-rst'

    def test_get_space(self, meet_service):
        meet_service.service.spaces().get().execute.return_value = {
            'name': 'spaces/space-123',
            'meetingUri': 'https://meet.google.com/abc-defg-hij',
            'meetingCode': 'abc-defg-hij',
            'config': {'accessType': 'OPEN'}
        }
        space = meet_service.get_space('space-123')
        assert space is not None
        assert space['meeting_code'] == 'abc-defg-hij'
        meet_service.service.spaces().get.assert_called_with(name='spaces/space-123')

    def test_update_space(self, meet_service):
        meet_service.service.spaces().patch().execute.return_value = {
            'name': 'spaces/space-123',
            'meetingUri': 'https://meet.google.com/abc-defg-hij',
            'meetingCode': 'abc-defg-hij',
            'config': {'accessType': 'OPEN'}
        }
        updated = meet_service.update_space('space-123', {'accessType': 'OPEN'})
        assert updated is not None
        assert updated['config']['accessType'] == 'OPEN'
        meet_service.service.spaces().patch.assert_called_with(
            name='spaces/space-123',
            updateMask='config.accessType',
            body={'config': {'accessType': 'OPEN'}}
        )

    def test_end_active_conference(self, meet_service):
        meet_service.service.spaces().endActiveConference().execute.return_value = {}
        success = meet_service.end_active_conference('spaces/space-123')
        assert success is True
        meet_service.service.spaces().endActiveConference.assert_called_with(
            name='spaces/space-123',
            body={}
        )


# =============================================================================
# Conference Records, Participants, Recordings, Transcripts Tests
# =============================================================================

class TestMeetConferences:
    def test_list_conference_records_pagination(self, meet_service):
        # Two pages of records
        meet_service.service.conferenceRecords().list.return_value.execute.side_effect = [
            {
                'conferenceRecords': [{'name': 'conferenceRecords/conf-1', 'startTime': '2026-09-01T10:00:00Z', 'endTime': '2026-09-01T11:00:00Z'}],
                'nextPageToken': 'token-page-2'
            },
            {
                'conferenceRecords': [{'name': 'conferenceRecords/conf-2', 'startTime': '2026-09-02T14:00:00Z', 'endTime': None}],
                'nextPageToken': None
            }
        ]
        records = meet_service.list_conference_records(max_results=10)
        assert len(records) == 2
        assert records[0]['name'] == 'conferenceRecords/conf-1'
        assert records[1]['name'] == 'conferenceRecords/conf-2'

    def test_get_conference_record(self, meet_service):
        meet_service.service.conferenceRecords().get().execute.return_value = {
            'name': 'conferenceRecords/conf-123',
            'startTime': '2026-09-01T10:00:00Z',
            'endTime': '2026-09-01T11:00:00Z',
            'space': 'spaces/space-123'
        }
        record = meet_service.get_conference_record('conf-123')
        assert record is not None
        assert record['space'] == 'spaces/space-123'

    def test_get_active_conferences(self, meet_service):
        meet_service.service.conferenceRecords().list.return_value.execute.return_value = {
            'conferenceRecords': [
                {'name': 'conferenceRecords/conf-1', 'startTime': '2026-09-01T10:00:00Z', 'endTime': '2026-09-01T11:00:00Z'},
                {'name': 'conferenceRecords/conf-active', 'startTime': '2026-09-02T14:00:00Z', 'endTime': ''}
            ]
        }
        active = meet_service.get_active_conferences()
        assert len(active) == 1
        assert active[0]['name'] == 'conferenceRecords/conf-active'

    def test_list_participants(self, meet_service):
        meet_service.service.conferenceRecords().participants().list.return_value.execute.return_value = {
            'participants': [
                {
                    'name': 'conferenceRecords/conf-1/participants/p1',
                    'signedinUser': {'displayName': 'Alice Developer', 'user': 'users/12345'},
                    'earliestStartTime': '2026-09-01T10:02:00Z',
                    'latestEndTime': '2026-09-01T10:55:00Z'
                },
                {
                    'name': 'conferenceRecords/conf-1/participants/p2',
                    'anonymousUser': {'displayName': 'Guest User'},
                    'earliestStartTime': '2026-09-01T10:05:00Z',
                    'latestEndTime': ''
                }
            ]
        }
        participants = meet_service.list_participants('conf-1')
        assert len(participants) == 2
        assert participants[0]['display_name'] == 'Alice Developer'
        assert participants[1]['display_name'] == 'Guest User'

    def test_get_participant(self, meet_service):
        meet_service.service.conferenceRecords().participants().get.return_value.execute.return_value = {
            'name': 'conferenceRecords/conf-1/participants/p1',
            'signedinUser': {'displayName': 'Alice Developer', 'user': 'users/12345'},
            'earliestStartTime': '2026-09-01T10:02:00Z',
            'latestEndTime': '2026-09-01T10:55:00Z'
        }
        p = meet_service.get_participant('conferenceRecords/conf-1/participants/p1')
        assert p is not None
        assert p['display_name'] == 'Alice Developer'

    def test_list_participant_sessions(self, meet_service):
        meet_service.service.conferenceRecords().participants().participantSessions().list.return_value.execute.return_value = {
            'participantSessions': [
                {'name': 'session-1', 'startTime': '2026-09-01T10:02:00Z', 'endTime': '2026-09-01T10:55:00Z'}
            ]
        }
        sessions = meet_service.list_participant_sessions('conferenceRecords/conf-1/participants/p1')
        assert len(sessions) == 1
        assert sessions[0]['name'] == 'session-1'

    def test_list_recordings(self, meet_service):
        meet_service.service.conferenceRecords().recordings().list.return_value.execute.return_value = {
            'recordings': [
                {
                    'name': 'conferenceRecords/conf-1/recordings/rec-1',
                    'state': 'FILE_GENERATED',
                    'startTime': '2026-09-01T10:05:00Z',
                    'endTime': '2026-09-01T10:50:00Z',
                    'driveDestination': {'file': 'files/drive-rec-123', 'exportUri': 'https://drive.google.com/file/d/123'}
                }
            ]
        }
        recs = meet_service.list_recordings('conf-1')
        assert len(recs) == 1
        assert recs[0]['state'] == 'FILE_GENERATED'
        assert recs[0]['drive_file'] == 'files/drive-rec-123'

    def test_get_recording(self, meet_service):
        meet_service.service.conferenceRecords().recordings().get.return_value.execute.return_value = {
            'name': 'conferenceRecords/conf-1/recordings/rec-1',
            'state': 'FILE_GENERATED',
            'startTime': '2026-09-01T10:05:00Z',
            'endTime': '2026-09-01T10:50:00Z',
            'driveDestination': {'file': 'files/drive-rec-123'}
        }
        rec = meet_service.get_recording('conferenceRecords/conf-1/recordings/rec-1')
        assert rec is not None
        assert rec['drive_file'] == 'files/drive-rec-123'

    def test_list_transcripts(self, meet_service):
        meet_service.service.conferenceRecords().transcripts().list.return_value.execute.return_value = {
            'transcripts': [
                {
                    'name': 'conferenceRecords/conf-1/transcripts/tr-1',
                    'state': 'FILE_GENERATED',
                    'startTime': '2026-09-01T10:05:00Z',
                    'endTime': '2026-09-01T10:50:00Z',
                    'docsDestination': {'document': 'docs/doc-123', 'exportUri': 'https://docs.google.com/doc/123'}
                }
            ]
        }
        trs = meet_service.list_transcripts('conf-1')
        assert len(trs) == 1
        assert trs[0]['docs_document'] == 'docs/doc-123'

    def test_get_transcript(self, meet_service):
        meet_service.service.conferenceRecords().transcripts().get.return_value.execute.return_value = {
            'name': 'conferenceRecords/conf-1/transcripts/tr-1',
            'state': 'FILE_GENERATED',
            'docsDestination': {'document': 'docs/doc-123'}
        }
        tr = meet_service.get_transcript('conferenceRecords/conf-1/transcripts/tr-1')
        assert tr is not None
        assert tr['docs_document'] == 'docs/doc-123'

    def test_list_transcript_entries(self, meet_service):
        meet_service.service.conferenceRecords().transcripts().entries().list.return_value.execute.return_value = {
            'transcriptEntries': [
                {
                    'name': 'conferenceRecords/conf-1/transcripts/tr-1/entries/e1',
                    'participant': 'Alice',
                    'text': 'Hello everyone, welcome to the sync!',
                    'languageCode': 'en',
                    'startTime': '2026-09-01T10:02:15Z',
                    'endTime': '2026-09-01T10:02:20Z'
                }
            ]
        }
        entries = meet_service.list_transcript_entries('conferenceRecords/conf-1/transcripts/tr-1')
        assert len(entries) == 1
        assert "Hello everyone" in entries[0]['text']


# =============================================================================
# Meet CLI Commands Tests
# =============================================================================

class TestMeetCLI:
    @patch("gsuite_cli.services.meet.MeetService.create_space")
    def test_cli_meet_create(self, mock_create, mock_oauth_manager):
        mock_create.return_value = {
            'name': 'spaces/abc123xyz',
            'meeting_uri': 'https://meet.google.com/abc-defg-hij',
            'meeting_code': 'abc-defg-hij',
            'config': {'accessType': 'RESTRICTED'}
        }
        runner = CliRunner()
        result = runner.invoke(cli, ['meet', 'create', '--type', 'private'], obj={'oauth_manager': mock_oauth_manager})
        assert result.exit_code == 0
        assert "Meeting space created successfully" in result.output
        assert "abc-defg-hij" in result.output

    @patch("webbrowser.open")
    def test_cli_meet_join(self, mock_browser_open, mock_oauth_manager):
        mock_browser_open.return_value = True
        runner = CliRunner()
        result = runner.invoke(cli, ['meet', 'join', 'abc-defg-hij'], obj={'oauth_manager': mock_oauth_manager})
        assert result.exit_code == 0
        assert "Opening meeting in browser" in result.output
        assert "Launched Google Meet" in result.output

    @patch("gsuite_cli.services.meet.MeetService.get_space")
    def test_cli_meet_details_space(self, mock_get_space, mock_oauth_manager):
        mock_get_space.return_value = {
            'name': 'spaces/test-space',
            'meeting_uri': 'https://meet.google.com/abc-defg-hij',
            'meeting_code': 'abc-defg-hij',
            'config': {'accessType': 'OPEN'}
        }
        runner = CliRunner()
        result = runner.invoke(cli, ['meet', 'details', 'abc-defg-hij'], obj={'oauth_manager': mock_oauth_manager})
        assert result.exit_code == 0
        assert "Meeting Space Details" in result.output
        assert "abc-defg-hij" in result.output

    @patch("gsuite_cli.services.meet.MeetService.update_space")
    def test_cli_meet_update(self, mock_update, mock_oauth_manager):
        mock_update.return_value = {
            'name': 'spaces/test-space',
            'meeting_uri': 'https://meet.google.com/abc-defg-hij',
            'config': {'accessType': 'OPEN'}
        }
        runner = CliRunner()
        result = runner.invoke(cli, ['meet', 'update', 'test-space', '--access-type', 'OPEN'], obj={'oauth_manager': mock_oauth_manager})
        assert result.exit_code == 0
        assert "configuration updated" in result.output

    @patch("gsuite_cli.services.meet.MeetService.list_conference_records")
    def test_cli_meet_list(self, mock_list, mock_oauth_manager):
        mock_list.return_value = [
            {
                'name': 'conferenceRecords/conf-1',
                'space': 'spaces/sp-1',
                'start_time': '2026-09-01T10:00:00Z',
                'end_time': '2026-09-01T11:00:00Z'
            }
        ]
        runner = CliRunner()
        result = runner.invoke(cli, ['meet', 'list'], obj={'oauth_manager': mock_oauth_manager})
        assert result.exit_code == 0
        assert "conferenceRecords/conf-1" in result.output

    @patch("gsuite_cli.services.meet.MeetService.get_active_conferences")
    def test_cli_meet_active(self, mock_active, mock_oauth_manager):
        mock_active.return_value = [
            {
                'name': 'conferenceRecords/conf-live',
                'space': 'spaces/sp-1',
                'start_time': '2026-09-01T10:00:00Z',
                'end_time': ''
            }
        ]
        runner = CliRunner()
        result = runner.invoke(cli, ['meet', 'active'], obj={'oauth_manager': mock_oauth_manager})
        assert result.exit_code == 0
        assert "conferenceRecords/conf-live" in result.output

    @patch("gsuite_cli.services.meet.MeetService.list_participants")
    def test_cli_meet_participants(self, mock_parts, mock_oauth_manager):
        mock_parts.return_value = [
            {
                'name': 'p-1',
                'display_name': 'Bob Smith',
                'user_id': 'users/bob',
                'earliest_start_time': '2026-09-01T10:00:00Z',
                'latest_end_time': ''
            }
        ]
        runner = CliRunner()
        result = runner.invoke(cli, ['meet', 'participants', 'conf-1'], obj={'oauth_manager': mock_oauth_manager})
        assert result.exit_code == 0
        assert "Bob Smith" in result.output

    @patch("gsuite_cli.services.meet.MeetService.list_recordings")
    def test_cli_meet_recordings(self, mock_recs, mock_oauth_manager):
        mock_recs.return_value = [
            {
                'name': 'rec-1',
                'state': 'READY',
                'start_time': '2026-09-01T10:00:00Z',
                'drive_file': 'drive-file-123',
                'export_uri': ''
            }
        ]
        runner = CliRunner()
        result = runner.invoke(cli, ['meet', 'recordings', 'conf-1'], obj={'oauth_manager': mock_oauth_manager})
        assert result.exit_code == 0
        assert "rec-1" in result.output
        assert "drive-file-123" in result.output

    @patch("gsuite_cli.services.meet.MeetService.list_transcripts")
    def test_cli_meet_transcripts(self, mock_trans, mock_oauth_manager):
        mock_trans.return_value = [
            {
                'name': 'trans-1',
                'state': 'READY',
                'start_time': '2026-09-01T10:00:00Z',
                'docs_document': 'doc-123',
                'export_uri': ''
            }
        ]
        runner = CliRunner()
        result = runner.invoke(cli, ['meet', 'transcripts', 'conf-1'], obj={'oauth_manager': mock_oauth_manager})
        assert result.exit_code == 0
        assert "trans-1" in result.output
        assert "doc-123" in result.output

    @patch("gsuite_cli.services.meet.MeetService.end_active_conference")
    def test_cli_meet_end(self, mock_end, mock_oauth_manager):
        mock_end.return_value = True
        runner = CliRunner()
        result = runner.invoke(cli, ['meet', 'end', 'spaces/sp-1', '--yes'], obj={'oauth_manager': mock_oauth_manager})
        assert result.exit_code == 0
        assert "Active conference ended successfully" in result.output

    @patch("gsuite_cli.services.meet.MeetService.test_connection")
    def test_cli_meet_test_connection(self, mock_conn, mock_oauth_manager):
        mock_conn.return_value = {
            'connected': True,
            'authenticated': True,
            'api_version': 'v2',
            'token_expiry': '2026-12-31'
        }
        runner = CliRunner()
        result = runner.invoke(cli, ['meet', 'test-connection'], obj={'oauth_manager': mock_oauth_manager})
        assert result.exit_code == 0
        assert "Google Meet API connection successful" in result.output
