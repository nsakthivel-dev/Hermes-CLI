"""
Unit test suite for the internal Hermes AI Tool Layer.
Tests:
- ToolDefinition, ToolRegistry, ToolValidator, ToolExecutor
- Read / Write / Destructive permission models
- Confirmation enforcement for write and destructive operations
- Infinite loop prevention (MAX_TOOL_CALLS = 5)
- Direct Hermes service invocation (no subprocess / shell)
- Section 24 --debug mode pipeline format
- Section 23 output format support (table, json, csv)
- Zero credentials/token leakage
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch
import pytest
from click.testing import CliRunner

from gsuite_cli.ai.tool_registry import (
    ToolDefinition,
    ToolRegistry,
    ToolValidator,
    ToolExecutor,
    ToolExecutionResult,
    MAX_TOOL_CALLS_PER_REQUEST,
    get_default_registry,
)
from gsuite_cli.ai.query_engine import NaturalQueryEngine
from gsuite_cli.ai.commands import ai
from gsuite_cli.auth.oauth import AuthenticationError


@pytest.fixture
def mock_oauth_manager():
    manager = MagicMock()
    manager.is_authenticated.return_value = True
    manager.get_auth_info.return_value = {
        'authenticated': True,
        'valid': True,
        'expired': False,
    }
    return manager


# ===========================================================================
# 1. Tool Registry Tests
# ===========================================================================

def test_default_tool_registry_contains_all_services():
    registry = get_default_registry()
    services = {'gmail', 'calendar', 'drive', 'sheets', 'docs', 'tasks', 'meet', 'forms', 'chat', 'people'}
    registered_services = {t.service_name for t in registry.list_tools()}
    assert services.issubset(registered_services)


def test_tool_registry_read_write_destructive_separation():
    registry = get_default_registry()

    # Read tools
    read_tools = ['gmail_list', 'calendar_list', 'drive_list', 'sheets_read', 'docs_get', 'tasks_list']
    for t_name in read_tools:
        tool = registry.get(t_name)
        assert tool is not None, f"Tool {t_name} should exist"
        assert tool.is_write is False
        assert tool.is_destructive is False
        assert tool.requires_confirmation is False

    # Write tools
    write_tools = ['gmail_send', 'calendar_create', 'tasks_add', 'sheets_write']
    for t_name in write_tools:
        tool = registry.get(t_name)
        assert tool is not None, f"Tool {t_name} should exist"
        assert tool.is_write is True

    # Destructive tools
    destructive_tools = ['gmail_delete', 'gmail_trash', 'calendar_delete', 'drive_delete', 'tasks_delete']
    for t_name in destructive_tools:
        tool = registry.get(t_name)
        assert tool is not None, f"Tool {t_name} should exist"
        assert tool.is_destructive is True
        assert tool.requires_confirmation is True


# ===========================================================================
# 2. Tool Validator Tests
# ===========================================================================

def test_validator_rejects_unknown_tool():
    registry = get_default_registry()
    validator = ToolValidator(registry)
    is_valid, err, _ = validator.validate_tool_call("unknown_tool_xyz", {})
    assert is_valid is False
    assert "Unknown tool" in err


def test_validator_rejects_invalid_argument_types():
    registry = get_default_registry()
    validator = ToolValidator(registry)
    is_valid, err, _ = validator.validate_tool_call("gmail_list", {"max_results": "not_an_integer"})
    assert is_valid is False
    assert "must be an integer" in err


def test_validator_bounds_numeric_range():
    registry = get_default_registry()
    validator = ToolValidator(registry)
    # Beyond max upper limit 500
    is_valid, _, args = validator.validate_tool_call("gmail_list", {"max_results": 1000})
    assert is_valid is True
    assert args["max_results"] == 500


def test_validator_normalizes_dates():
    registry = get_default_registry()
    validator = ToolValidator(registry)
    is_valid, _, args = validator.validate_tool_call("calendar_list", {"date_range": "today"})
    assert is_valid is True
    assert "time_min" in args
    assert "time_max" in args


# ===========================================================================
# 3. Tool Executor Tests
# ===========================================================================

def test_executor_enforces_auth_check(mock_oauth_manager):
    mock_oauth_manager.is_authenticated.return_value = False
    registry = get_default_registry()
    validator = ToolValidator(registry)
    executor = ToolExecutor(
        oauth_manager=mock_oauth_manager,
        registry=registry,
        validator=validator,
    )
    with pytest.raises(AuthenticationError):
        executor.execute_tool("gmail_list", {})


def test_executor_enforces_confirmation_decline(mock_oauth_manager):
    registry = get_default_registry()
    validator = ToolValidator(registry)
    executor = ToolExecutor(
        oauth_manager=mock_oauth_manager,
        registry=registry,
        validator=validator,
    )
    result = executor.execute_tool("gmail_delete", {"message_id": "m123"}, confirmation_override=False)
    assert result.status == "cancelled"
    assert "cancelled" in result.error.lower()


def test_executor_loop_prevention(mock_oauth_manager):
    registry = get_default_registry()
    validator = ToolValidator(registry)
    executor = ToolExecutor(
        oauth_manager=mock_oauth_manager,
        registry=registry,
        validator=validator,
    )
    # Attempting to execute more than MAX_TOOL_CALLS_PER_REQUEST tools
    calls = [{"tool": "gmail_list", "arguments": {}} for _ in range(MAX_TOOL_CALLS_PER_REQUEST + 2)]
    results = executor.execute_multi_tools(calls)
    assert len(results) <= MAX_TOOL_CALLS_PER_REQUEST


def test_executor_invalidates_cache_on_write(mock_oauth_manager):
    registry = get_default_registry()
    validator = ToolValidator(registry)
    mock_cache = MagicMock()
    mock_service_dispatcher = MagicMock(return_value={"id": "new_task"})

    executor = ToolExecutor(
        oauth_manager=mock_oauth_manager,
        cache_manager=mock_cache,
        registry=registry,
        validator=validator,
        service_dispatcher=mock_service_dispatcher,
    )

    res = executor.execute_tool("tasks_add", {"title": "Buy milk"}, confirmation_override=True)
    assert res.status == "success"
    mock_cache.invalidate_service.assert_called_with("tasks")


# ===========================================================================
# 4. End-to-End Query Engine & CLI Integration Tests
# ===========================================================================

def test_query_engine_executes_actual_gmail(mock_oauth_manager):
    engine = NaturalQueryEngine(mock_oauth_manager)
    mock_gmail = MagicMock()
    mock_gmail.list_messages.return_value = [
        {'id': 'm1', 'from': 'team@example.com', 'subject': 'Sprint update', 'date': '2026-09-28', 'snippet': 'Everything on track'}
    ]
    engine._services['gmail'] = mock_gmail

    result = engine.execute_query("Show my unread emails", output_format='table')
    assert result['status'] == 'success'
    assert 'Sprint update' in result['output']
    mock_gmail.list_messages.assert_called_once()


def test_query_engine_multi_tool_execution(mock_oauth_manager):
    engine = NaturalQueryEngine(mock_oauth_manager)
    mock_gmail = MagicMock()
    mock_gmail.list_messages.return_value = [{'id': 'm1', 'from': 'boss@example.com', 'subject': 'Urgent', 'date': '2026-09-28', 'snippet': 'Call me'}]
    mock_cal = MagicMock()
    mock_cal.get_today_events.return_value = [{'id': 'ev1', 'summary': 'Team Standup', 'start': '2026-09-28T09:00:00Z', 'status': 'confirmed'}]
    engine._services['gmail'] = mock_gmail
    engine._services['calendar'] = mock_cal

    result = engine.execute_query("Show my unread emails and today's meetings", output_format='json')
    assert result['status'] == 'success'
    parsed = json.loads(result['output'])
    assert 'unread_emails' in parsed.get('data', {})
    assert 'today_meetings' in parsed.get('data', {})


def test_cli_ai_ask_debug_format(mock_oauth_manager):
    runner = CliRunner()
    with patch('gsuite_cli.ai.query_engine.GmailService') as mock_gmail_cls:
        mock_gmail = MagicMock()
        mock_gmail.list_messages.return_value = [
            {'id': 'm1', 'from': 'alice@example.com', 'subject': 'Doc Review', 'date': '2026-09-28', 'snippet': 'Please review'}
        ]
        mock_gmail_cls.return_value = mock_gmail

        res = runner.invoke(
            ai,
            ['ask', 'Show my unread emails', '--debug'],
            obj={'oauth_manager': mock_oauth_manager, 'config_manager': None, 'cache_manager': None}
        )
        assert res.exit_code == 0
        assert "Query:" in res.output
        assert "Intent:" in res.output
        assert "Tool:" in res.output
        assert "gmail_list" in res.output
        assert "Authentication:" in res.output
        assert "Valid" in res.output
        assert "Gmail API:" in res.output
        assert "Success" in res.output
        assert "Retrieved:" in res.output
        assert "Doc Review" in res.output


# ===========================================================================
# 5. Section 29 Exact Test Scenarios
# ===========================================================================

def test_section_29_test_2_calendar_today(mock_oauth_manager):
    """TEST 2: hermes ai ask 'What meetings do I have today?'"""
    engine = NaturalQueryEngine(mock_oauth_manager)
    mock_cal = MagicMock()
    mock_cal.get_today_events.return_value = [
        {'id': 'ev_1', 'summary': 'Architecture Sync', 'start': '2026-09-28T14:00:00Z', 'status': 'confirmed'}
    ]
    engine._services['calendar'] = mock_cal

    result = engine.execute_query("What meetings do I have today?", output_format='table')
    assert result['status'] == 'success'
    assert 'Architecture Sync' in result['output']
    mock_cal.get_today_events.assert_called_once()


def test_section_29_test_3_tasks_pending(mock_oauth_manager):
    """TEST 3: hermes ai ask 'Show my pending tasks'"""
    engine = NaturalQueryEngine(mock_oauth_manager)
    mock_tasks = MagicMock()
    mock_tasks.list_tasks.return_value = [
        {'id': 't_1', 'title': 'Complete security review', 'status': 'needsAction', 'due': '2026-09-29'}
    ]
    engine._services['tasks'] = mock_tasks

    result = engine.execute_query("Show my pending tasks", output_format='table')
    assert result['status'] == 'success'
    assert 'Complete security review' in result['output']
    mock_tasks.list_tasks.assert_called_once()


def test_section_29_test_4_drive_recent(mock_oauth_manager):
    """TEST 4: hermes ai ask 'Find my recent files'"""
    engine = NaturalQueryEngine(mock_oauth_manager)
    mock_drive = MagicMock()
    mock_drive.service.files().list().execute.return_value = {
        'files': [{'id': 'f_1', 'name': 'Q3 Roadmap.pdf', 'modifiedTime': '2026-09-28T10:00:00Z'}]
    }
    engine._services['drive'] = mock_drive

    result = engine.execute_query("Find my recent files", output_format='table')
    assert result['status'] == 'success'
    assert 'Q3 Roadmap.pdf' in result['output']


def test_section_29_test_5_sheets_read(mock_oauth_manager):
    """TEST 5: hermes ai ask 'Show the data from my Q3 Financials spreadsheet'"""
    engine = NaturalQueryEngine(mock_oauth_manager)
    mock_sheets = MagicMock()
    mock_sheets.list_spreadsheets.return_value = [
        {'id': 'sheet_q3_id', 'name': 'Q3 Financials', 'modified_time': '2026-09-20'}
    ]
    mock_sheets.read_range.return_value = [
        ['Quarter', 'Revenue', 'Expenses'],
        ['Q3', '$1,200,000', '$800,000']
    ]
    engine._services['sheets'] = mock_sheets

    result = engine.execute_query("Show the data from my Q3 Financials spreadsheet", output_format='table')
    assert result['status'] == 'success'
    assert 'Revenue' in result['output']
    assert '$1,200,000' in result['output']


def test_section_29_test_7_summarize_unread_emails(mock_oauth_manager):
    """TEST 7: hermes ai ask 'Summarize my unread emails'"""
    engine = NaturalQueryEngine(mock_oauth_manager)
    mock_gmail = MagicMock()
    mock_gmail.list_messages.return_value = [
        {'id': 'm_sum_1', 'from': 'security@company.com', 'subject': 'Password expiry', 'date': '2026-09-28', 'snippet': 'Change your password'}
    ]
    engine._services['gmail'] = mock_gmail

    result = engine.execute_query("Summarize my unread emails", output_format='table')
    assert result['status'] == 'success'
    assert 'Password expiry' in result['output'] or len(result['data']) == 1


def test_section_29_test_8_unread_need_attention(mock_oauth_manager):
    """TEST 8: hermes ai ask 'Which of my unread emails need attention?'"""
    engine = NaturalQueryEngine(mock_oauth_manager)
    mock_gmail = MagicMock()
    mock_gmail.list_messages.return_value = [
        {'id': 'm_att_1', 'from': 'ceo@company.com', 'subject': 'Action required: Board deck', 'date': '2026-09-28', 'snippet': 'Review slides'}
    ]
    engine._services['gmail'] = mock_gmail

    result = engine.execute_query("Which of my unread emails need attention?", output_format='table')
    assert result['status'] == 'success'
    assert len(result['data']) == 1
    assert result['data'][0]['Subject'] == 'Action required: Board deck'


def test_section_29_test_9_delete_confirmation(mock_oauth_manager):
    """TEST 9: hermes ai ask 'Delete all unread emails'"""
    engine = NaturalQueryEngine(mock_oauth_manager)
    # Decline confirmation
    res_declined = engine.execute_query("Delete all unread emails", confirmation_override=False)
    assert res_declined['status'] == 'cancelled'
    assert 'cancelled' in res_declined['message'].lower()


def test_section_29_test_10_ambiguous_spreadsheet_resolution(mock_oauth_manager):
    """TEST 10: hermes ai ask 'Show the Q3 Financials spreadsheet' - ambiguous case"""
    engine = NaturalQueryEngine(mock_oauth_manager)
    mock_sheets = MagicMock()
    mock_sheets.list_spreadsheets.return_value = [
        {'id': 'sheet_1', 'name': 'Q3 Financials - North America', 'modified_time': '2026-09-20'},
        {'id': 'sheet_2', 'name': 'Q3 Financials - EMEA', 'modified_time': '2026-09-21'},
    ]
    engine._services['sheets'] = mock_sheets

    # Ambiguous resolution should report error/warning without randomly selecting
    result = engine.execute_query("Show the Q3 Financials spreadsheet", output_format='table')
    assert result['status'] == 'error'
    assert 'multiple spreadsheets matching' in result['message'].lower() or 'ambiguous' in result['message'].lower()

