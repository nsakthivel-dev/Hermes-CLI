"""
Unit tests for Google Chat Service, CLI commands, and Universal Hermes dispatchers.
All tests mock Google API client calls (no real credentials needed).
"""

import pytest
from unittest.mock import MagicMock, patch
from click.testing import CliRunner

from gsuite_cli.services.chat import ChatService
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
    }
    return manager


@pytest.fixture
def chat_service(mock_oauth_manager):
    return ChatService(mock_oauth_manager)


# =============================================================================
# Helper & Normalization Tests
# =============================================================================

class TestChatHelpers:
    def test_normalize_space_name(self):
        assert ChatService.normalize_space_name("spaces/ABC123XYZ") == "spaces/ABC123XYZ"
        assert ChatService.normalize_space_name("ABC123XYZ") == "spaces/ABC123XYZ"
        assert ChatService.normalize_space_name("") == ""

    def test_normalize_message_name(self):
        assert ChatService.normalize_message_name("spaces/S1/messages/M1") == "spaces/S1/messages/M1"
        assert ChatService.normalize_message_name("M1", space_id="S1") == "spaces/S1/messages/M1"
        assert ChatService.normalize_message_name("M1", space_id="spaces/S1") == "spaces/S1/messages/M1"
        assert ChatService.normalize_message_name("") == ""


# =============================================================================
# Chat Service Layer Tests
# =============================================================================

class TestChatService:
    def test_list_spaces(self, chat_service):
        mock_list = chat_service.service.spaces().list
        mock_list.return_value.execute.return_value = {
            'spaces': [
                {'name': 'spaces/AAA', 'displayName': 'Engineering', 'spaceType': 'SPACE'},
                {'name': 'spaces/BBB', 'displayName': 'General', 'spaceType': 'SPACE'},
            ]
        }
        res = chat_service.list_spaces()
        assert len(res['spaces']) == 2
        assert res['spaces'][0]['displayName'] == 'Engineering'

    def test_get_space(self, chat_service):
        mock_get = chat_service.service.spaces().get
        mock_get.return_value.execute.return_value = {
            'name': 'spaces/AAA',
            'displayName': 'Engineering',
            'spaceType': 'SPACE'
        }
        space = chat_service.get_space('AAA')
        assert space is not None
        assert space['displayName'] == 'Engineering'

    def test_create_space(self, chat_service):
        mock_create = chat_service.service.spaces().create
        mock_create.return_value.execute.return_value = {
            'name': 'spaces/NEW_SPACE',
            'displayName': 'Project Hermes',
            'spaceType': 'SPACE'
        }
        space = chat_service.create_space('Project Hermes', description='Hermes CLI project')
        assert space is not None
        assert space['name'] == 'spaces/NEW_SPACE'

    def test_list_messages(self, chat_service):
        mock_list = chat_service.service.spaces().messages().list
        mock_list.return_value.execute.return_value = {
            'messages': [
                {'name': 'spaces/AAA/messages/MSG1', 'text': 'Hello world!'},
                {'name': 'spaces/AAA/messages/MSG2', 'text': 'Deployment started.'},
            ]
        }
        res = chat_service.list_messages('AAA')
        assert len(res['messages']) == 2

    def test_get_message(self, chat_service):
        mock_get = chat_service.service.spaces().messages().get
        mock_get.return_value.execute.return_value = {
            'name': 'spaces/AAA/messages/MSG1',
            'text': 'Hello world!'
        }
        msg = chat_service.get_message('MSG1', space_id='AAA')
        assert msg is not None
        assert msg['text'] == 'Hello world!'

    def test_send_message(self, chat_service):
        mock_create = chat_service.service.spaces().messages().create
        mock_create.return_value.execute.return_value = {
            'name': 'spaces/AAA/messages/MSG99',
            'text': 'New release deployed'
        }
        msg = chat_service.send_message('AAA', 'New release deployed')
        assert msg is not None
        assert msg['name'] == 'spaces/AAA/messages/MSG99'

    def test_reply_message(self, chat_service):
        # mock parent message lookup
        mock_get = chat_service.service.spaces().messages().get
        mock_get.return_value.execute.return_value = {
            'name': 'spaces/AAA/messages/MSG1',
            'thread': {'name': 'spaces/AAA/threads/TH1'}
        }
        # mock reply creation
        mock_create = chat_service.service.spaces().messages().create
        mock_create.return_value.execute.return_value = {
            'name': 'spaces/AAA/messages/MSG2',
            'text': 'Acknowledged'
        }
        res = chat_service.reply_message('spaces/AAA/messages/MSG1', 'Acknowledged')
        assert res is not None
        assert res['name'] == 'spaces/AAA/messages/MSG2'

    def test_edit_message(self, chat_service):
        mock_patch = chat_service.service.spaces().messages().patch
        mock_patch.return_value.execute.return_value = {
            'name': 'spaces/AAA/messages/MSG1',
            'text': 'Edited message text'
        }
        msg = chat_service.edit_message('spaces/AAA/messages/MSG1', 'Edited message text')
        assert msg is not None
        assert msg['text'] == 'Edited message text'

    def test_delete_message(self, chat_service):
        mock_del = chat_service.service.spaces().messages().delete
        mock_del.return_value.execute.return_value = {}
        ok = chat_service.delete_message('spaces/AAA/messages/MSG1')
        assert ok is True

    def test_list_members(self, chat_service):
        mock_list = chat_service.service.spaces().members().list
        mock_list.return_value.execute.return_value = {
            'memberships': [
                {'name': 'spaces/AAA/members/MEM1', 'role': 'ROLE_MEMBER', 'member': {'displayName': 'Alice'}}
            ]
        }
        res = chat_service.list_members('AAA')
        assert len(res['memberships']) == 1

    def test_add_member(self, chat_service):
        mock_create = chat_service.service.spaces().members().create
        mock_create.return_value.execute.return_value = {
            'name': 'spaces/AAA/members/MEM2',
            'role': 'ROLE_MEMBER'
        }
        res = chat_service.add_member('AAA', 'bob@example.com')
        assert res is not None
        assert res['role'] == 'ROLE_MEMBER'

    def test_remove_member(self, chat_service):
        mock_del = chat_service.service.spaces().members().delete
        mock_del.return_value.execute.return_value = {}
        ok = chat_service.remove_member('AAA', 'MEM2')
        assert ok is True

    def test_create_reaction(self, chat_service):
        mock_create = chat_service.service.spaces().messages().reactions().create
        mock_create.return_value.execute.return_value = {
            'name': 'spaces/AAA/messages/MSG1/reactions/R1',
            'emoji': {'unicode': '👍'}
        }
        res = chat_service.create_reaction('spaces/AAA/messages/MSG1', '👍')
        assert res is not None

    def test_delete_reaction(self, chat_service):
        mock_del = chat_service.service.spaces().messages().reactions().delete
        mock_del.return_value.execute.return_value = {}
        ok = chat_service.delete_reaction('spaces/AAA/messages/MSG1/reactions/R1')
        assert ok is True

    def test_search_messages(self, chat_service):
        mock_list = chat_service.service.spaces().messages().list
        mock_list.return_value.execute.return_value = {
            'messages': [
                {'name': 'spaces/AAA/messages/M1', 'text': 'Found keyword in this message'},
                {'name': 'spaces/AAA/messages/M2', 'text': 'Other content'},
            ]
        }
        matches = chat_service.search_messages('keyword', space_name='AAA')
        assert len(matches) == 1
        assert 'keyword' in matches[0]['text']

    def test_test_connection_success(self, chat_service):
        mock_list = chat_service.service.spaces().list
        mock_list.return_value.execute.return_value = {'spaces': [{'name': 'spaces/A'}]}
        res = chat_service.test_connection()
        assert res['status'] == 'success'
        assert res['spaces_found'] == 1


# =============================================================================
# CLI Command Tests
# =============================================================================

class TestChatCliCommands:
    @pytest.fixture
    def mock_service(self):
        svc = MagicMock()
        svc.list_spaces.return_value = {
            'spaces': [{'name': 'spaces/AAA', 'displayName': 'Dev Channel', 'spaceType': 'SPACE'}]
        }
        svc.get_space.return_value = {
            'name': 'spaces/AAA', 'displayName': 'Dev Channel', 'spaceType': 'SPACE', 'spaceDetails': {'description': 'Desc'}
        }
        svc.list_messages.return_value = {
            'messages': [{'name': 'spaces/AAA/messages/M1', 'text': 'Pipeline passed', 'createTime': '2026-09-05T12:00:00Z', 'sender': {'displayName': 'Bot'}}]
        }
        svc.send_message.return_value = {'name': 'spaces/AAA/messages/M2'}
        svc.reply_message.return_value = {'name': 'spaces/AAA/messages/M3'}
        svc.edit_message.return_value = {'name': 'spaces/AAA/messages/M1', 'text': 'Updated'}
        svc.delete_message.return_value = True
        svc.list_members.return_value = {
            'memberships': [{'name': 'spaces/AAA/members/U1', 'role': 'MEMBER', 'member': {'displayName': 'Alex', 'type': 'HUMAN'}}]
        }
        svc.add_member.return_value = {'name': 'spaces/AAA/members/U2', 'role': 'ROLE_MEMBER'}
        svc.remove_member.return_value = True
        svc.create_reaction.return_value = {'name': 'spaces/AAA/messages/M1/reactions/R1'}
        svc.delete_reaction.return_value = True
        svc.search_messages.return_value = [
            {'name': 'spaces/AAA/messages/M1', 'text': 'Pipeline passed', 'createTime': '2026-09-05T12:00:00Z', 'sender': {'displayName': 'Bot'}}
        ]
        svc.list_threads.return_value = [
            {'thread': 'spaces/AAA/threads/T1', 'sender': 'Bot', 'first_message': 'Pipeline passed', 'message_count': 1}
        ]
        svc.test_connection.return_value = {'status': 'success', 'message': 'Connected', 'spaces_found': 1}
        svc.get_profile.return_value = {'service': 'Google Chat API v1', 'authenticated': True, 'token_expiry': '2026-12-31', 'connection_status': 'success'}
        return svc

    def test_cli_chat_spaces_list(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['chat', 'spaces'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Dev Channel' in res.output

    def test_cli_chat_spaces_single(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['chat', 'spaces', 'AAA'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Dev Channel' in res.output

    def test_cli_chat_messages(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['chat', 'messages', 'AAA'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Pipeline passed' in res.output

    def test_cli_chat_send(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['chat', 'send', 'AAA', '-m', 'Hello there!'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Message sent successfully' in res.output

    def test_cli_chat_reply(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['chat', 'reply', 'M1', '-m', 'Acknowledged', '--space-id', 'AAA'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Reply posted successfully' in res.output

    def test_cli_chat_edit(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['chat', 'edit', 'M1', '-m', 'Updated text', '--space-id', 'AAA'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Message updated successfully' in res.output

    def test_cli_chat_delete(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['chat', 'delete', 'M1', '--space-id', 'AAA', '--yes'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'deleted successfully' in res.output

    def test_cli_chat_members(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['chat', 'members', 'AAA'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Alex' in res.output

    def test_cli_chat_add_member(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['chat', 'add-member', 'AAA', 'alex@example.com'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'added to space' in res.output

    def test_cli_chat_remove_member(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['chat', 'remove-member', 'AAA', 'U1', '--yes'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'removed from space' in res.output

    def test_cli_chat_react(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['chat', 'react', 'M1', '🚀', '--space-id', 'AAA'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Reaction \'🚀\' added' in res.output

    def test_cli_chat_unreact(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['chat', 'unreact', 'spaces/AAA/messages/M1/reactions/R1'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'removed' in res.output

    def test_cli_chat_search(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['chat', 'search', 'Pipeline', '--space-id', 'AAA'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Pipeline passed' in res.output

    def test_cli_chat_threads(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['chat', 'threads', 'AAA'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'T1' in res.output

    def test_cli_chat_test_connection(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['chat', 'test-connection'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Connected' in res.output

    def test_cli_chat_status(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['chat', 'status'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Google Chat API Status' in res.output


# =============================================================================
# Universal Hermes Command Dispatcher Tests
# =============================================================================

class TestUniversalChatCommands:
    @pytest.fixture
    def mock_service(self):
        svc = MagicMock()
        svc.list_spaces.return_value = {
            'spaces': [{'name': 'spaces/AAA', 'displayName': 'Dev Channel', 'spaceType': 'SPACE'}]
        }
        svc.get_space.return_value = {
            'name': 'spaces/AAA', 'displayName': 'Dev Channel', 'spaceType': 'SPACE'
        }
        svc.list_messages.return_value = {
            'messages': [{'name': 'spaces/AAA/messages/M1', 'text': 'Build successful', 'createTime': '2026-09-05T12:00:00Z', 'sender': {'displayName': 'Bot'}}]
        }
        svc.list_members.return_value = {
            'memberships': [{'name': 'spaces/AAA/members/U1', 'role': 'MEMBER', 'member': {'displayName': 'Jordan', 'type': 'HUMAN'}}]
        }
        svc.list_threads.return_value = [
            {'thread': 'spaces/AAA/threads/T1', 'sender': 'Bot', 'first_message': 'Build successful', 'message_count': 1}
        ]
        svc.search_messages.return_value = [
            {'name': 'spaces/AAA/messages/M1', 'text': 'Build successful', 'createTime': '2026-09-05T12:00:00Z', 'sender': {'displayName': 'Bot'}}
        ]
        svc.send_message.return_value = {'name': 'spaces/AAA/messages/M99'}
        svc.reply_message.return_value = {'name': 'spaces/AAA/messages/M100'}
        svc.create_space.return_value = {'name': 'spaces/NEW_SPACE'}
        svc.edit_message.return_value = {'name': 'spaces/AAA/messages/M1'}
        svc.delete_message.return_value = True
        svc.add_member.return_value = {'name': 'spaces/AAA/members/U3'}
        svc.remove_member.return_value = True
        svc.create_reaction.return_value = {'name': 'spaces/AAA/messages/M1/reactions/R1'}
        svc.delete_reaction.return_value = True
        svc.get_profile.return_value = {'service': 'Google Chat API v1', 'authenticated': True, 'token_expiry': '2026-12-31', 'connection_status': 'success'}
        return svc

    def test_universal_list_chat(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['list', 'chat'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Dev Channel' in res.output

    def test_universal_list_chat_spaces(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['list', 'chat-spaces'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Dev Channel' in res.output

    def test_universal_list_chat_messages(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['list', 'chat-messages', 'AAA'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Build successful' in res.output

    def test_universal_list_chat_members(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['list', 'chat-members', 'AAA'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Jordan' in res.output

    def test_universal_list_chat_threads(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['list', 'chat-threads', 'AAA'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'T1' in res.output

    def test_universal_search_chat(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['search', 'chat', 'Build'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Build successful' in res.output

    def test_universal_send_chat(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['send', 'chat', 'AAA', '-m', 'Deployed to prod'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Message sent successfully' in res.output

    def test_universal_reply_chat(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['reply', 'chat', 'M1', '-m', 'LGTM'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Reply posted successfully' in res.output

    def test_universal_create_chat_space(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['create', 'chat-space', '--title', 'Team Alpha'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Chat space created' in res.output

    def test_universal_edit_chat(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['edit', 'chat', 'M1', '-m', 'Edited content'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Message updated successfully' in res.output

    def test_universal_delete_chat(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['delete', 'chat', 'M1', '--yes'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'deleted successfully' in res.output

    def test_universal_add_chat_member(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['add', 'chat-member', 'AAA', 'newuser@example.com'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'added to space' in res.output

    def test_universal_remove_chat_member(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['remove', 'chat-member', 'AAA', 'U1', '--yes'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'removed from space' in res.output

    def test_universal_react_chat(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['react', 'chat', 'M1', '🔥'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Reaction \'🔥\' added' in res.output

    def test_universal_unreact_chat(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['unreact', 'chat', 'spaces/AAA/messages/M1/reactions/R1'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'removed' in res.output

    def test_universal_status_chat(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['status', 'chat'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Google Chat API Status' in res.output

    def test_universal_profile_chat(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['profile', 'chat'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Google Chat API Status' in res.output

    def test_universal_ls_alias(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['ls', 'chat'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'Dev Channel' in res.output

    def test_universal_rm_alias(self, mock_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['rm', 'chat', 'M1', '--yes'], obj={'_chat_svc': mock_service})
        assert res.exit_code == 0
        assert 'deleted successfully' in res.output
