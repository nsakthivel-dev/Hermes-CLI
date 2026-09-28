"""
Comprehensive test suite for Hermes Natural Language Query system.
Tests intent parsing, validation, service routing, resource resolution,
date/time understanding, confirmation, large-data handling, output formatting,
follow-up context, and error handling with mocks.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock
import pytest
from click.testing import CliRunner

from gsuite_cli.ai.intent_schema import (
    StructuredIntent,
    validate_structured_intent,
    ALLOWED_SERVICES,
    ALLOWED_OPERATIONS,
    WRITE_OPERATIONS,
)
from gsuite_cli.ai.date_parser import NaturalDateParser
from gsuite_cli.ai.query_engine import NaturalQueryEngine, ConversationContext
from gsuite_cli.ai.nlp import NaturalLanguageProcessor
from gsuite_cli.ai.commands import ai
from gsuite_cli.services.resource_resolver import AmbiguousResourceNameError, ResourceNotFoundError
from gsuite_cli.auth.oauth import AuthenticationError


# ===========================================================================
# 1. Intent Schema & Validation Tests
# ===========================================================================

def test_validate_structured_intent_valid():
    raw = {
        "intent": "list",
        "service": "gmail",
        "operation": "list_messages",
        "entities": {"status": "unread"},
        "parameters": {"query": "is:unread", "max_results": 20},
        "requires_confirmation": False,
        "confidence": 0.95
    }
    validated = validate_structured_intent(raw, "Show my unread emails")
    assert validated.is_valid is True
    assert validated.service == "gmail"
    assert validated.operation == "list_messages"
    assert validated.parameters["query"] == "is:unread"
    assert validated.requires_confirmation is False
    assert validated.confidence == 0.95


def test_validate_structured_intent_rejects_unknown_service():
    raw = {
        "intent": "execute",
        "service": "unknown_cloud_service",
        "operation": "destroy",
        "parameters": {},
        "confidence": 0.9
    }
    validated = validate_structured_intent(raw)
    assert validated.is_valid is False
    assert "not supported in Hermes" in validated.error_message


def test_validate_structured_intent_rejects_arbitrary_operation():
    raw = {
        "intent": "execute",
        "service": "gmail",
        "operation": "arbitrary_custom_exec",
        "parameters": {},
        "confidence": 0.9
    }
    validated = validate_structured_intent(raw)
    assert validated.is_valid is False
    assert "not supported for service 'gmail'" in validated.error_message


def test_validate_structured_intent_rejects_command_injection():
    raw = {
        "intent": "list",
        "service": "gmail",
        "operation": "list_messages",
        "parameters": {"query": "test; rm -rf /; echo hack"},
        "confidence": 0.95
    }
    validated = validate_structured_intent(raw)
    assert validated.is_valid is False
    assert "Security violation" in validated.error_message


def test_validate_structured_intent_low_confidence():
    raw = {
        "intent": "list",
        "service": "gmail",
        "operation": "list_messages",
        "parameters": {},
        "confidence": 0.2
    }
    validated = validate_structured_intent(raw)
    assert validated.is_valid is False
    assert "Confidence is too low" in validated.error_message


def test_validate_structured_intent_enforces_confirmation_on_write():
    raw = {
        "intent": "delete",
        "service": "gmail",
        "operation": "delete_message",
        "parameters": {"message_id": "12345"},
        "requires_confirmation": False,  # Model tries to set false
        "confidence": 0.95
    }
    validated = validate_structured_intent(raw)
    assert validated.is_valid is True
    # Hermes must override and require confirmation
    assert validated.requires_confirmation is True


# ===========================================================================
# 2. Date and Time Understanding Tests
# ===========================================================================

def test_date_parser_relative_expressions():
    parser = NaturalDateParser()
    now = parser.now()

    # today
    bounds = parser.parse_range("today")
    assert bounds is not None
    start, end = bounds
    assert start.date() == now.date()
    assert end.date() == now.date()
    assert start.hour == 0 and start.minute == 0
    assert end.hour == 23 and end.minute == 59

    # tomorrow
    bounds = parser.parse_range("what meetings do i have tomorrow?")
    assert bounds is not None
    start, end = bounds
    assert start.date() == (now + timedelta(days=1)).date()

    # yesterday
    bounds = parser.parse_range("emails from yesterday")
    assert bounds is not None
    start, end = bounds
    assert start.date() == (now - timedelta(days=1)).date()

    # this week
    bounds = parser.parse_range("meetings for this week")
    assert bounds is not None
    start, end = bounds
    assert start <= now
    assert end >= now

    # last 7 days
    bounds = parser.parse_range("files modified in last 7 days")
    assert bounds is not None
    start, end = bounds
    assert (end - start).days >= 6


def test_date_parser_specific_day():
    parser = NaturalDateParser()
    bounds = parser.parse_range("Friday")
    assert bounds is not None
    start, end = bounds
    assert start.weekday() == 4  # Friday


# ===========================================================================
# 3. NLP Intent Interpretation & Service Identification
# ===========================================================================

def test_nlp_intent_identification_all_services():
    nlp = NaturalLanguageProcessor()

    # Gmail
    p = nlp.parse_command("Show my unread emails")
    assert p['service'] == 'gmail'
    assert p['operation'] == 'list_messages'

    # Calendar
    p = nlp.parse_command("What meetings do I have today?")
    assert p['service'] == 'calendar'
    assert p['operation'] == 'list_events'

    # Drive
    p = nlp.parse_command("Find my recent files in drive")
    assert p['service'] in ('drive', 'docs')

    # Sheets
    p = nlp.parse_command("Find the spreadsheet named Q3 Financials")
    assert p['service'] == 'sheets'
    assert p['operation'] == 'list_spreadsheets'

    # Tasks
    p = nlp.parse_command("Show my pending tasks")
    assert p['service'] == 'tasks'
    assert p['operation'] == 'list_tasks'

    # Chat
    p = nlp.parse_command("Show my chat spaces")
    assert p['service'] == 'chat'

    # People
    p = nlp.parse_command("Show my contacts")
    assert p['service'] == 'people'


# ===========================================================================
# 4. Query Engine End-to-End Pipeline Tests with Mocks
# ===========================================================================

@pytest.fixture
def mock_oauth_manager():
    mgr = MagicMock()
    mgr.is_authenticated.return_value = True
    return mgr


@pytest.fixture
def mock_cache_manager():
    cache = MagicMock()
    cache.get.return_value = None
    return cache


def test_query_engine_gmail_unread_emails(mock_oauth_manager, mock_cache_manager):
    engine = NaturalQueryEngine(mock_oauth_manager, cache_manager=mock_cache_manager)

    mock_gmail = MagicMock()
    mock_gmail.list_messages.return_value = [
        {
            'id': 'msg1234567890abcdef',
            'from': 'alice@example.com',
            'subject': 'Project Status Update',
            'date': '2026-09-28 10:00:00',
            'snippet': 'Here is the weekly update...',
        }
    ]
    engine._services['gmail'] = mock_gmail

    result = engine.execute_query("Show my unread emails", output_format='table')
    assert result['status'] == 'success'
    assert result['intent']['service'] == 'gmail'
    assert result['intent']['operation'] == 'list_messages'
    assert len(result['data']) == 1
    assert 'Project Status Update' in result['output']
    mock_gmail.list_messages.assert_called_once()


def test_query_engine_calendar_meetings_today(mock_oauth_manager, mock_cache_manager):
    engine = NaturalQueryEngine(mock_oauth_manager, cache_manager=mock_cache_manager)

    mock_cal = MagicMock()
    mock_cal.get_today_events.return_value = [
        {
            'id': 'event123',
            'summary': 'Sprint Review',
            'start': '2026-09-28T14:00:00',
            'location': 'Meeting Room 1',
            'status': 'confirmed',
        }
    ]
    engine._services['calendar'] = mock_cal

    result = engine.execute_query("What meetings do I have today?", output_format='table')
    assert result['status'] == 'success'
    assert result['intent']['service'] == 'calendar'
    assert len(result['data']) == 1
    assert 'Sprint Review' in result['output']


def test_query_engine_sheets_read_data(mock_oauth_manager, mock_cache_manager):
    engine = NaturalQueryEngine(mock_oauth_manager, cache_manager=mock_cache_manager)

    mock_sheets = MagicMock()
    mock_sheets.list_spreadsheets.return_value = [
        {'name': 'Q3 Financials', 'id': 'sheet_id_q3_123', 'modified_time': '2026-09-20'}
    ]
    mock_sheets.read_range.return_value = [
        {'Quarter': 'Q3', 'Revenue': '$1,500,000', 'Expenses': '$800,000'}
    ]
    engine._services['sheets'] = mock_sheets

    result = engine.execute_query("Show the data from my Q3 Financials spreadsheet", output_format='table')
    assert result['status'] == 'success'
    assert result['intent']['service'] == 'sheets'
    mock_sheets.read_range.assert_called_with('sheet_id_q3_123', 'A1:Z50')


def test_query_engine_sheets_ambiguous_resolution(mock_oauth_manager, mock_cache_manager):
    engine = NaturalQueryEngine(mock_oauth_manager, cache_manager=mock_cache_manager)

    mock_sheets = MagicMock()
    mock_sheets.list_spreadsheets.return_value = [
        {'name': 'Q3 Financials North America', 'id': 'id_na'},
        {'name': 'Q3 Financials Europe', 'id': 'id_eu'},
    ]
    engine._services['sheets'] = mock_sheets

    result = engine.execute_query("Show the data from my Q3 Financials spreadsheet", output_format='table')
    # Should catch ambiguous match cleanly without crashing
    assert result['status'] == 'error'
    assert 'multiple spreadsheets' in result['message'].lower()


def test_query_engine_tasks_pending(mock_oauth_manager, mock_cache_manager):
    engine = NaturalQueryEngine(mock_oauth_manager, cache_manager=mock_cache_manager)

    mock_tasks = MagicMock()
    mock_tasks.list_task_lists.return_value = {'items': [{'id': 'tl_default', 'title': 'My Tasks'}]}
    mock_tasks.list_tasks.return_value = {
        'items': [
            {'id': 't1', 'title': 'Submit report', 'status': 'needsAction', 'due': '2026-09-29T12:00:00.000Z'},
            {'id': 't2', 'title': 'Old done task', 'status': 'completed'},
        ]
    }
    engine._services['tasks'] = mock_tasks

    result = engine.execute_query("Show my pending tasks", output_format='table')
    assert result['status'] == 'success'
    assert result['intent']['service'] == 'tasks'
    assert len(result['data']) == 1  # Only pending
    assert result['data'][0]['Title'] == 'Submit report'


def test_query_engine_composite_calendar_tasks(mock_oauth_manager, mock_cache_manager):
    engine = NaturalQueryEngine(mock_oauth_manager, cache_manager=mock_cache_manager)

    mock_cal = MagicMock()
    mock_cal.get_upcoming_events.return_value = [
        {'summary': 'Roadmap Sync', 'start': '2026-09-29T10:00:00', 'location': ''}
    ]
    mock_tasks = MagicMock()
    mock_tasks.list_task_lists.return_value = {'items': [{'id': 'tl_1'}]}
    mock_tasks.list_tasks.return_value = {
        'items': [{'title': 'Prepare slide deck', 'status': 'needsAction', 'due': '2026-09-29'}]
    }
    engine._services['calendar'] = mock_cal
    engine._services['tasks'] = mock_tasks

    result = engine.execute_query("Show my upcoming meetings and related tasks", output_format='table')
    assert result['status'] == 'success'
    assert 'Roadmap Sync' in result['output']
    assert 'Prepare slide deck' in result['output']


def test_query_engine_people_contacts(mock_oauth_manager, mock_cache_manager):
    engine = NaturalQueryEngine(mock_oauth_manager, cache_manager=mock_cache_manager)

    mock_people = MagicMock()
    mock_people.list_contacts.return_value = [
        {'name': 'Bob Smith', 'email': 'bob@example.com', 'phone': '1234567890', 'organization': 'Google'}
    ]
    engine._services['people'] = mock_people

    result = engine.execute_query("Show my contacts", output_format='table')
    assert result['status'] == 'success'
    assert 'Bob Smith' in result['output']


def test_query_engine_unauthenticated_error():
    oauth_mgr = MagicMock()
    oauth_mgr.is_authenticated.return_value = False
    engine = NaturalQueryEngine(oauth_mgr)

    with pytest.raises(AuthenticationError):
        engine.execute_query("Show my unread emails")


def test_query_engine_confirmation_required_write_operation(mock_oauth_manager):
    engine = NaturalQueryEngine(mock_oauth_manager)

    mock_cal = MagicMock()
    engine._services['calendar'] = mock_cal

    # When user cancels confirmation:
    result = engine.execute_query(
        "Create a meeting with Bob tomorrow at 10 AM",
        confirmation_override=False,
    )
    assert result['status'] == 'cancelled'
    assert mock_cal.create_event.call_count == 0


def test_query_engine_json_output_format(mock_oauth_manager, mock_cache_manager):
    engine = NaturalQueryEngine(mock_oauth_manager, cache_manager=mock_cache_manager)

    mock_gmail = MagicMock()
    mock_gmail.list_messages.return_value = [
        {'id': '123', 'from': 'team@github.com', 'subject': 'PR merged', 'date': '2026-09-28', 'snippet': 'Done'}
    ]
    engine._services['gmail'] = mock_gmail

    result = engine.execute_query("Show my unread emails", output_format='json')
    assert result['status'] == 'success'
    # Output must be pure valid JSON
    parsed = json.loads(result['output'])
    assert 'intent' in parsed
    assert 'data' in parsed
    assert parsed['intent']['service'] == 'gmail'


def test_query_engine_follow_up_context(mock_oauth_manager, mock_cache_manager):
    context = ConversationContext()
    engine = NaturalQueryEngine(mock_oauth_manager, cache_manager=mock_cache_manager, context=context)

    mock_cal = MagicMock()
    mock_cal.get_tomorrow_events.return_value = [
        {'id': 'e1', 'summary': 'Design team sync', 'start': '2026-09-29T11:00:00'},
        {'id': 'e2', 'summary': 'Finance review', 'start': '2026-09-29T15:00:00'},
    ]
    engine._services['calendar'] = mock_cal

    # Query 1: Tomorrow's meetings
    res1 = engine.execute_query("Show my meetings tomorrow.", output_format='table')
    assert res1['status'] == 'success'
    assert len(context.last_data) == 2

    # Query 2: Contextual follow-up: "Which one is with the design team?"
    res2 = engine.execute_query("Which one is with the design team?", output_format='table')
    assert res2['status'] == 'success'
    assert len(res2['data']) == 1
    assert 'Design team sync' in res2['output']


# ===========================================================================
# 5. CLI Command Integration Tests (`hermes ai ask`)
# ===========================================================================

def test_cli_ai_ask_table_format():
    runner = CliRunner()
    mock_oauth = MagicMock()
    mock_oauth.is_authenticated.return_value = True

    mock_gmail = MagicMock()
    mock_gmail.list_messages.return_value = [
        {'id': 'msg_001', 'from': 'alerts@google.com', 'subject': 'Security notice', 'date': '2026-09-28', 'snippet': 'Notice'}
    ]

    with patch('gsuite_cli.ai.query_engine.GmailService', return_value=mock_gmail):
        result = runner.invoke(ai, ['ask', 'Show my unread emails'], obj={'oauth_manager': mock_oauth, 'config_manager': None, 'cache_manager': None})
        assert result.exit_code == 0
        assert 'Security notice' in result.output


def test_cli_ai_ask_json_format():
    runner = CliRunner()
    mock_oauth = MagicMock()
    mock_oauth.is_authenticated.return_value = True

    mock_cal = MagicMock()
    mock_cal.get_today_events.return_value = [
        {'id': 'e1', 'summary': 'Team Standup', 'start': '2026-09-28T09:00:00'}
    ]

    with patch('gsuite_cli.ai.query_engine.CalendarService', return_value=mock_cal):
        result = runner.invoke(ai, ['ask', 'What meetings do I have today?', '--format', 'json'], obj={'oauth_manager': mock_oauth, 'config_manager': None, 'cache_manager': None})
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data['intent']['service'] == 'calendar'
        assert data['data'][0]['Title'] == 'Team Standup'


def test_cli_ai_ask_suggest_only():
    runner = CliRunner()
    result = runner.invoke(ai, ['ask', 'Show my unread emails', '--suggest-only'], obj={'oauth_manager': None, 'config_manager': None, 'cache_manager': None})
    assert result.exit_code == 0
    assert 'Suggested Command' in result.output
    assert 'hermes gmail' in result.output


def test_scenario_meetings_this_week(mock_oauth_manager):
    engine = NaturalQueryEngine(mock_oauth_manager)
    mock_cal = MagicMock()
    mock_cal.list_events.return_value = [
        {'id': 'e1', 'summary': 'Weekly Architecture Review', 'start': '2026-09-30T10:00:00', 'location': 'Conf Room'}
    ]
    engine._services['calendar'] = mock_cal

    result = engine.execute_query("Show my meetings for this week", output_format='table')
    assert result['status'] == 'success'
    assert 'Weekly Architecture Review' in result['output']
    mock_cal.list_events.assert_called_once()


def test_scenario_find_spreadsheet_named(mock_oauth_manager):
    engine = NaturalQueryEngine(mock_oauth_manager)
    mock_sheets = MagicMock()
    mock_sheets.list_spreadsheets.return_value = [
        {'id': 'sheet1', 'name': 'Q3 Financials', 'modified_time': '2026-09-20'},
        {'id': 'sheet2', 'name': 'Annual Budget', 'modified_time': '2026-09-15'},
    ]
    engine._services['sheets'] = mock_sheets

    result = engine.execute_query("Find the spreadsheet named Q3 Financials", output_format='table')
    assert result['status'] == 'success'
    assert 'Q3 Financials' in result['output']


def test_scenario_summarize_unread_emails(mock_oauth_manager):
    engine = NaturalQueryEngine(mock_oauth_manager)
    mock_gmail = MagicMock()
    mock_gmail.list_messages.return_value = [
        {'id': 'm1', 'from': 'boss@company.com', 'subject': 'Urgent: Client demo', 'date': '2026-09-28', 'snippet': 'Please prepare'}
    ]
    engine._services['gmail'] = mock_gmail

    result = engine.execute_query("Summarize my unread emails", output_format='table')
    assert result['status'] == 'success'
    assert result['intent']['operation'] == 'summarize_messages'
    assert len(result['data']) == 1


def test_scenario_recent_files_drive(mock_oauth_manager):
    engine = NaturalQueryEngine(mock_oauth_manager)
    mock_drive = MagicMock()
    mock_drive.service.files().list().execute.return_value = {
        'files': [
            {'id': 'f1', 'name': 'Architecture Spec.pdf', 'mimeType': 'application/pdf', 'modifiedTime': '2026-09-28T12:00:00Z'}
        ]
    }
    engine._services['drive'] = mock_drive

    result = engine.execute_query("Find the files I modified recently", output_format='table')
    assert result['status'] == 'success'
    assert 'Architecture Spec.pdf' in result['output']


def test_scenario_what_requires_my_attention(mock_oauth_manager):
    engine = NaturalQueryEngine(mock_oauth_manager)
    mock_cal = MagicMock()
    mock_cal.get_today_events.return_value = [
        {'summary': 'Security Audit', 'start': '2026-09-28T15:00:00'}
    ]
    mock_gmail = MagicMock()
    mock_gmail.list_messages.return_value = [
        {'from': 'security@company.com', 'subject': 'CVE Alert', 'date': '2026-09-28'}
    ]
    mock_tasks = MagicMock()
    mock_tasks.list_task_lists.return_value = {'items': [{'id': 'tl_1'}]}
    mock_tasks.list_tasks.return_value = {
        'items': [{'title': 'Patch cluster', 'status': 'needsAction', 'due': '2026-09-28'}]
    }
    engine._services['calendar'] = mock_cal
    engine._services['gmail'] = mock_gmail
    engine._services['tasks'] = mock_tasks

    result = engine.execute_query("What requires my attention today?", output_format='table')
    assert result['status'] == 'success'
    assert 'Security Audit' in result['output']
    assert 'CVE Alert' in result['output']
    assert 'Patch cluster' in result['output']


def test_large_data_handling_preview(mock_oauth_manager):
    engine = NaturalQueryEngine(mock_oauth_manager)
    mock_sheets = MagicMock()
    mock_sheets.list_spreadsheets.return_value = [
        {'id': 's_big', 'name': 'Big Dataset'}
    ]
    # 80 rows
    big_rows = [{'Row': f'Item {i}', 'Value': i * 10} for i in range(80)]
    mock_sheets.read_range.return_value = big_rows
    engine._services['sheets'] = mock_sheets

    result = engine.execute_query("Show the data from my Big Dataset spreadsheet", output_format='table')
    assert result['status'] == 'success'
    # Check that preview notice is included
    assert '50 of 80 rows' in result['output']


def test_csv_format_output(mock_oauth_manager):
    engine = NaturalQueryEngine(mock_oauth_manager)
    mock_tasks = MagicMock()
    mock_tasks.list_task_lists.return_value = {'items': [{'id': 'tl_1'}]}
    mock_tasks.list_tasks.return_value = {
        'items': [{'title': 'Write unit tests', 'status': 'needsAction', 'due': '2026-09-30'}]
    }
    engine._services['tasks'] = mock_tasks

    result = engine.execute_query("Show my pending tasks", output_format='csv')
    assert result['status'] == 'success'
    assert 'Write unit tests' in result['output']
    assert ',' in result['output']


def test_chat_service_spaces(mock_oauth_manager):
    engine = NaturalQueryEngine(mock_oauth_manager)
    mock_chat = MagicMock()
    mock_chat.list_spaces.return_value = [
        {'displayName': 'Engineering', 'name': 'spaces/eng123'}
    ]
    engine._services['chat'] = mock_chat

    result = engine.execute_query("Show my chat spaces", output_format='table')
    assert result['status'] == 'success'
    assert 'Engineering' in result['output']


def test_docs_service_list(mock_oauth_manager):
    engine = NaturalQueryEngine(mock_oauth_manager)
    mock_docs = MagicMock()
    mock_docs.list_documents.return_value = [
        {'name': 'Design Document', 'id': 'doc_123', 'modified_time': '2026-09-28'}
    ]
    engine._services['docs'] = mock_docs

    result = engine.execute_query("Find my project documents", output_format='table')
    assert result['status'] == 'success'
    assert 'Design Document' in result['output']


def test_cli_ai_chat_interactive():
    runner = CliRunner()
    mock_oauth = MagicMock()
    mock_oauth.is_authenticated.return_value = True

    mock_gmail = MagicMock()
    mock_gmail.list_messages.return_value = [
        {'id': 'm1', 'from': 'team@company.com', 'subject': 'Standup Notes', 'date': '2026-09-28', 'snippet': 'Notes'}
    ]

    with patch('gsuite_cli.ai.query_engine.GmailService', return_value=mock_gmail):
        # Simulate typing query, then /clear, then exit
        inputs = "Show my unread emails\n/clear\nexit\n"
        result = runner.invoke(
            ai,
            ['chat'],
            input=inputs,
            obj={'oauth_manager': mock_oauth, 'config_manager': None, 'cache_manager': None}
        )
        assert result.exit_code == 0
        assert 'Standup Notes' in result.output
        assert 'Conversation context cleared' in result.output
        assert 'Ending chat session' in result.output

