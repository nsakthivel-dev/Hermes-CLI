"""
Unit tests for Google Tasks Service, Universal CLI commands, and aliases.
All tests mock Google Tasks API calls (no real credentials needed).
"""

import pytest
from unittest.mock import MagicMock, patch
from click.testing import CliRunner

from gsuite_cli.services.tasks import TasksService
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
def tasks_service(mock_oauth_manager):
    return TasksService(mock_oauth_manager)


# =============================================================================
# Service Layer Unit Tests
# =============================================================================

class TestTasksService:
    def test_test_connection_success(self, tasks_service):
        tasks_service.service.tasklists().list.return_value.execute.return_value = {
            'items': [{'id': 'list-1', 'title': 'My Tasks'}]
        }
        res = tasks_service.test_connection()
        assert res['status'] == 'success'
        assert res['tasklists_count'] == 1

    def test_list_task_lists(self, tasks_service):
        tasks_service.service.tasklists().list.return_value.execute.return_value = {
            'items': [{'id': 'tl-1', 'title': 'Work'}, {'id': 'tl-2', 'title': 'Personal'}]
        }
        res = tasks_service.list_task_lists()
        assert len(res['items']) == 2
        assert res['items'][0]['title'] == 'Work'

    def test_get_task_list(self, tasks_service):
        tasks_service.service.tasklists().get.return_value.execute.return_value = {
            'id': 'tl-1', 'title': 'Work'
        }
        tl = tasks_service.get_task_list('tl-1')
        assert tl['id'] == 'tl-1'
        assert tl['title'] == 'Work'

    def test_create_task_list(self, tasks_service):
        tasks_service.service.tasklists().insert.return_value.execute.return_value = {
            'id': 'new-tl', 'title': 'Sprint 42'
        }
        tl = tasks_service.create_task_list('Sprint 42')
        assert tl['id'] == 'new-tl'

    def test_update_task_list(self, tasks_service):
        tasks_service.service.tasklists().patch.return_value.execute.return_value = {
            'id': 'tl-1', 'title': 'Updated Title'
        }
        tl = tasks_service.update_task_list('tl-1', 'Updated Title')
        assert tl['title'] == 'Updated Title'

    def test_delete_task_list(self, tasks_service):
        tasks_service.service.tasklists().delete.return_value.execute.return_value = {}
        ok = tasks_service.delete_task_list('tl-1')
        assert ok is True

    def test_list_tasks(self, tasks_service):
        tasks_service.service.tasks().list.return_value.execute.return_value = {
            'items': [{'id': 'task-1', 'title': 'Fix bug', 'status': 'needsAction'}]
        }
        res = tasks_service.list_tasks()
        assert len(res['items']) == 1
        assert res['items'][0]['title'] == 'Fix bug'

    def test_get_task(self, tasks_service):
        tasks_service.service.tasks().get.return_value.execute.return_value = {
            'id': 'task-1', 'title': 'Fix bug', 'status': 'needsAction', 'notes': 'High priority'
        }
        t = tasks_service.get_task('task-1')
        assert t['id'] == 'task-1'
        assert t['notes'] == 'High priority'

    def test_create_task(self, tasks_service):
        tasks_service.service.tasks().insert.return_value.execute.return_value = {
            'id': 'new-task', 'title': 'Deploy to prod'
        }
        t = tasks_service.create_task('Deploy to prod', notes='Use CI/CD pipeline')
        assert t['id'] == 'new-task'

    def test_update_task(self, tasks_service):
        tasks_service.service.tasks().patch.return_value.execute.return_value = {
            'id': 'task-1', 'title': 'Deploy to staging'
        }
        t = tasks_service.update_task('task-1', title='Deploy to staging')
        assert t['title'] == 'Deploy to staging'

    def test_complete_and_uncomplete_task(self, tasks_service):
        tasks_service.service.tasks().patch.return_value.execute.return_value = {
            'id': 'task-1', 'status': 'completed'
        }
        t = tasks_service.complete_task('task-1')
        assert t['status'] == 'completed'

        tasks_service.service.tasks().patch.return_value.execute.return_value = {
            'id': 'task-1', 'status': 'needsAction'
        }
        t = tasks_service.uncomplete_task('task-1')
        assert t['status'] == 'needsAction'

    def test_delete_task(self, tasks_service):
        tasks_service.service.tasks().delete.return_value.execute.return_value = {}
        ok = tasks_service.delete_task('task-1')
        assert ok is True

    def test_move_task(self, tasks_service):
        tasks_service.service.tasks().move.return_value.execute.return_value = {
            'id': 'task-1', 'parent': 'parent-task'
        }
        t = tasks_service.move_task('task-1', parent='parent-task')
        assert t['id'] == 'task-1'

    def test_clear_completed(self, tasks_service):
        tasks_service.service.tasks().clear.return_value.execute.return_value = {}
        ok = tasks_service.clear_completed('tl-1')
        assert ok is True


# =============================================================================
# Universal Hermes CLI Commands Tests
# =============================================================================

class TestUniversalTasksCommands:
    @pytest.fixture
    def mock_tasks_service(self):
        svc = MagicMock()
        svc.test_connection.return_value = {'status': 'success', 'message': 'Connected to Tasks', 'tasklists_count': 2}
        svc.list_tasks.return_value = {
            'items': [{'id': 't1', 'title': 'Write unit tests', 'status': 'needsAction', 'due': '2026-09-10T00:00:00Z'}]
        }
        svc.get_task.return_value = {
            'id': 't1', 'title': 'Write unit tests', 'status': 'needsAction', 'due': '2026-09-10T00:00:00Z', 'notes': 'Tasks module'
        }
        svc.list_task_lists.return_value = {
            'items': [{'id': 'tl1', 'title': 'Sprint 1', 'updated': '2026-09-01T12:00:00Z'}]
        }
        svc.get_task_list.return_value = {'id': 'tl1', 'title': 'Sprint 1'}
        svc.create_task.return_value = {'id': 'new-t', 'title': 'New Task'}
        svc.create_task_list.return_value = {'id': 'new-tl', 'title': 'New List'}
        svc.update_task.return_value = {'id': 't1', 'title': 'Updated Title'}
        svc.update_task_list.return_value = {'id': 'tl1', 'title': 'Updated List'}
        svc.complete_task.return_value = {'id': 't1', 'status': 'completed'}
        svc.uncomplete_task.return_value = {'id': 't1', 'status': 'needsAction'}
        svc.delete_task.return_value = True
        svc.delete_task_list.return_value = True
        svc.move_task.return_value = {'id': 't1', 'parent': 'p1'}
        svc.clear_completed.return_value = True
        return svc

    def test_universal_list_tasks(self, mock_tasks_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['list', 'tasks'], obj={'_tasks_svc': mock_tasks_service})
        assert res.exit_code == 0
        assert 'Write unit tests' in res.output

    def test_universal_list_task_single(self, mock_tasks_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['list', 'tasks', 't1'], obj={'_tasks_svc': mock_tasks_service})
        assert res.exit_code == 0
        assert 'Write unit tests' in res.output

    def test_universal_list_task_lists(self, mock_tasks_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['list', 'task-lists'], obj={'_tasks_svc': mock_tasks_service})
        assert res.exit_code == 0
        assert 'Sprint 1' in res.output

    def test_universal_create_task(self, mock_tasks_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['create', 'tasks', '--title', 'New Task'], obj={'_tasks_svc': mock_tasks_service})
        assert res.exit_code == 0
        assert 'Task created' in res.output

    def test_universal_create_task_list(self, mock_tasks_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['create', 'task-list', '--title', 'New List'], obj={'_tasks_svc': mock_tasks_service})
        assert res.exit_code == 0
        assert 'Task list created' in res.output

    def test_universal_update_task(self, mock_tasks_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['update', 'tasks', 't1', '--title', 'Updated Title'], obj={'_tasks_svc': mock_tasks_service})
        assert res.exit_code == 0
        assert 'Task t1 updated' in res.output

    def test_universal_edit_task(self, mock_tasks_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['edit', 'tasks', 't1', '--title', 'Updated Title'], obj={'_tasks_svc': mock_tasks_service})
        assert res.exit_code == 0
        assert 'Task t1 updated' in res.output

    def test_universal_complete_task(self, mock_tasks_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['complete', 'tasks', 't1'], obj={'_tasks_svc': mock_tasks_service})
        assert res.exit_code == 0
        assert 'completed' in res.output

    def test_universal_uncomplete_task(self, mock_tasks_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['uncomplete', 'tasks', 't1'], obj={'_tasks_svc': mock_tasks_service})
        assert res.exit_code == 0
        assert 'reopened' in res.output

    def test_universal_delete_task(self, mock_tasks_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['delete', 'tasks', 't1', '--yes'], obj={'_tasks_svc': mock_tasks_service})
        assert res.exit_code == 0
        assert 'deleted' in res.output

    def test_universal_delete_task_list(self, mock_tasks_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['delete', 'task-list', 'tl1', '--yes'], obj={'_tasks_svc': mock_tasks_service})
        assert res.exit_code == 0
        assert 'deleted' in res.output

    def test_universal_move_task(self, mock_tasks_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['move', 'tasks', 't1', 'parent-123'], obj={'_tasks_svc': mock_tasks_service})
        assert res.exit_code == 0
        assert 'Task t1 moved' in res.output

    def test_universal_clear_tasks(self, mock_tasks_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['clear', 'tasks', 'tl1'], obj={'_tasks_svc': mock_tasks_service})
        assert res.exit_code == 0
        assert 'Completed tasks cleared' in res.output

    def test_universal_search_tasks(self, mock_tasks_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['search', 'tasks', 'unit'], obj={'_tasks_svc': mock_tasks_service})
        assert res.exit_code == 0
        assert 'Write unit tests' in res.output

    def test_universal_status_tasks(self, mock_tasks_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['status', 'tasks'], obj={'_tasks_svc': mock_tasks_service})
        assert res.exit_code == 0
        assert 'Google Tasks API v1 Status' in res.output

    def test_universal_aliases_tasks(self, mock_tasks_service):
        runner = CliRunner()
        # ls alias
        res_ls = runner.invoke(cli, ['ls', 'tasks'], obj={'_tasks_svc': mock_tasks_service})
        assert res_ls.exit_code == 0
        assert 'Write unit tests' in res_ls.output

        # get alias
        res_get = runner.invoke(cli, ['get', 'tasks', 't1'], obj={'_tasks_svc': mock_tasks_service})
        assert res_get.exit_code == 0
        assert 'Write unit tests' in res_get.output

        # rm alias
        res_rm = runner.invoke(cli, ['rm', 'tasks', 't1', '--yes'], obj={'_tasks_svc': mock_tasks_service})
        assert res_rm.exit_code == 0
        assert 'deleted' in res_rm.output
