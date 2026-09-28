"""
Complete Natural Language Query Engine for Hermes CLI.
Executes the full pipeline:
User Natural Language -> Gemini Intent Understanding -> Structured Intent Validation ->
Service Identification -> Resource Resolution -> OAuth2 Permission Check ->
Google Workspace API -> Authorized Data -> Data Processing -> Gemini Response/Presentation -> Output.
"""

from __future__ import annotations
import json
import logging
import re
from typing import Dict, Any, List, Optional, Tuple, Union
from datetime import datetime

import click
from colorama import Fore, Style

from .intent_schema import (
    StructuredIntent,
    validate_structured_intent,
    ALLOWED_SERVICES,
    ALLOWED_OPERATIONS,
    WRITE_OPERATIONS,
    TOOL_TO_SERVICE_OP,
    SERVICE_OP_TO_TOOL,
)
from .tool_registry import (
    ToolDefinition,
    ToolRegistry,
    ToolValidator,
    ToolExecutor,
    ToolExecutionResult,
    get_default_registry,
)
from .date_parser import NaturalDateParser, get_user_timezone
from ..auth.oauth import OAuthManager, AuthenticationError, ALL_SCOPES
from ..utils.formatters import (
    format_output,
    print_error,
    print_info,
    print_success,
    print_warning,
    print_header,
    truncate_text,
)
from ..services.resource_resolver import (
    GlobalResourceResolver,
    ResourceNotFoundError,
    AmbiguousResourceNameError,
)
from ..services.calendar import CalendarService
from ..services.gmail import GmailService
from ..services.drive import DriveService
from ..services.sheets import SheetsService
from ..services.docs import DocsService
from ..services.tasks import TasksService
from ..services.meet import MeetService
from ..services.forms import FormsService
from ..services.chat import ChatService
from ..services.people import PeopleService

logger = logging.getLogger(__name__)


class ConversationContext:
    """Manages short-term conversation context for follow-up queries."""

    def __init__(self):
        self.last_intent: Optional[StructuredIntent] = None
        self.last_service: Optional[str] = None
        self.last_data: Optional[List[Dict[str, Any]]] = None
        self.last_query: Optional[str] = None
        self.history: List[Dict[str, Any]] = []

    def update(self, intent: StructuredIntent, data: Any, query: str):
        self.last_intent = intent
        self.last_service = intent.service
        if isinstance(data, list):
            self.last_data = data
        elif isinstance(data, dict):
            self.last_data = [data]
        else:
            self.last_data = None
        self.last_query = query
        self.history.append({
            'query': query,
            'service': intent.service,
            'operation': intent.operation,
            'timestamp': datetime.now().isoformat(),
        })
        if len(self.history) > 10:
            self.history = self.history[-10:]

    def clear(self):
        self.last_intent = None
        self.last_service = None
        self.last_data = None
        self.last_query = None
        self.history.clear()


class NaturalQueryEngine:
    """
    Central execution engine for natural language queries against Google Workspace.
    Hermes enforces all authorization, security, resource resolution, and validation.
    Gemini is used for semantic understanding and result summarization/analysis.
    """

    def __init__(
        self,
        oauth_manager: OAuthManager,
        config_manager: Optional[Any] = None,
        cache_manager: Optional[Any] = None,
        context: Optional[ConversationContext] = None,
    ):
        self.oauth_manager = oauth_manager
        self.config_manager = config_manager
        self.cache_manager = cache_manager
        self.context = context or ConversationContext()

        self.tzinfo = get_user_timezone(config_manager)
        self.date_parser = NaturalDateParser(timezone=self.tzinfo)

        # Service lazy instances
        self._services: Dict[str, Any] = {}

        # Internal Hermes Tool Registry & Execution Layer
        self.tool_registry = get_default_registry()
        self.tool_validator = ToolValidator(self.tool_registry, timezone=self.tzinfo)
        self.tool_executor = ToolExecutor(
            oauth_manager=self.oauth_manager,
            config_manager=self.config_manager,
            cache_manager=self.cache_manager,
            registry=self.tool_registry,
            validator=self.tool_validator,
            services=self._services,
            service_dispatcher=self._dispatch_tool_service,
        )

    def _dispatch_tool_service(self, service_name: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Dispatch tool execution to existing Hermes service handlers with parameter mapping."""
        if tool_name in TOOL_TO_SERVICE_OP:
            svc, op = TOOL_TO_SERVICE_OP[tool_name]
        else:
            svc = service_name
            op = tool_name.replace(f"{service_name}_", "")

        intent = StructuredIntent(
            intent='action',
            service=svc,
            operation=op,
            tool=tool_name,
            parameters=arguments,
            confidence=1.0,
        )
        return self._route_operation(intent)


    def get_service(self, name: str) -> Any:
        """Get or initialize a Workspace service client."""
        clean_name = name.lower()
        if clean_name not in self._services:
            if clean_name == 'gmail':
                self._services['gmail'] = GmailService(self.oauth_manager, self.cache_manager)
            elif clean_name == 'calendar':
                self._services['calendar'] = CalendarService(self.oauth_manager, self.cache_manager)
            elif clean_name == 'drive':
                self._services['drive'] = DriveService(self.oauth_manager, self.cache_manager)
            elif clean_name == 'sheets':
                self._services['sheets'] = SheetsService(self.oauth_manager, self.cache_manager)
            elif clean_name == 'docs':
                self._services['docs'] = DocsService(self.oauth_manager, self.cache_manager)
            elif clean_name == 'tasks':
                self._services['tasks'] = TasksService(self.oauth_manager, self.cache_manager)
            elif clean_name == 'meet':
                self._services['meet'] = MeetService(self.oauth_manager, self.cache_manager)
            elif clean_name == 'forms':
                self._services['forms'] = FormsService(self.oauth_manager, self.cache_manager)
            elif clean_name == 'chat':
                self._services['chat'] = ChatService(self.oauth_manager, self.cache_manager)
            elif clean_name == 'people':
                self._services['people'] = PeopleService(self.oauth_manager, self.cache_manager)
            else:
                raise ValueError(f"Unknown service '{name}'")
        return self._services[clean_name]

    # -----------------------------------------------------------------------
    # Step 1 & 2: Intent Understanding with Gemini + Deterministic Fallback
    # -----------------------------------------------------------------------

    def interpret_query(self, query: str) -> StructuredIntent:
        """
        Interpret natural language using Gemini or fallback to deterministic rules.
        Never passes credentials or tokens to Gemini.
        """
        # 1. Check for follow-up query against previous context
        if self.context.last_data and self._is_follow_up_query(query):
            follow_up_intent = self._handle_follow_up_intent(query)
            if follow_up_intent:
                return follow_up_intent

        # 2. Try Gemini interpretation if configured
        gemini_client = self._get_gemini_client()
        if gemini_client and gemini_client.is_available:
            try:
                raw_intent = self._gemini_parse(gemini_client, query)
                if raw_intent:
                    validated = validate_structured_intent(raw_intent, original_query=query)
                    if validated.is_valid and validated.confidence >= 0.5:
                        return validated
            except Exception as e:
                logger.warning(f"Gemini intent parsing failed, falling back to rules: {e}")

        # 3. Deterministic rule-based fallback
        fallback_raw = self._deterministic_parse(query)
        return validate_structured_intent(fallback_raw, original_query=query)

    def _get_gemini_client(self):
        """Retrieve GeminiClient if API key is present."""
        try:
            from .gemini_client import GeminiClient
            api_key = ''
            model_name = 'gemini-3.6-flash'
            if self.config_manager:
                ai_config = self.config_manager.get('ai')
                if ai_config and hasattr(ai_config, 'gemini_api_key'):
                    api_key = ai_config.gemini_api_key
                    model_name = getattr(ai_config, 'model_name', model_name)
                elif isinstance(ai_config, dict):
                    api_key = ai_config.get('gemini_api_key', '')
                    model_name = ai_config.get('model_name', model_name)
            if not api_key:
                import os
                api_key = os.environ.get('HERMES_GEMINI_API_KEY') or os.environ.get('GEMINI_API_KEY', '')
            if api_key:
                return GeminiClient(api_key=api_key, model_name=model_name)
        except Exception as e:
            logger.debug(f"Could not load GeminiClient: {e}")
        return None

    def _gemini_parse(self, gemini_client, query: str) -> Optional[Dict[str, Any]]:
        """Call Gemini for strict structured tool and parameter selection."""
        now_str = datetime.now(self.tzinfo).strftime('%Y-%m-%d %H:%M:%S %Z')
        prompt = f"""
You are the natural language tool selector and interpreter for Hermes CLI (Google Workspace).
Current Date/Time: {now_str}

User request: "{query}"

Available Hermes Tools:
GMAIL: gmail_list, gmail_get, gmail_search, gmail_read, gmail_drafts, gmail_labels, gmail_send, gmail_reply, gmail_trash, gmail_delete
CALENDAR: calendar_list, calendar_get, calendar_search, calendar_create, calendar_update, calendar_delete
DRIVE: drive_list, drive_search, drive_get, drive_trash, drive_delete
SHEETS: sheets_list, sheets_get, sheets_read, sheets_search, sheets_write, sheets_append, sheets_clear
DOCS: docs_list, docs_get, docs_create
TASKS: tasks_list, tasks_get, tasks_add, tasks_complete, tasks_delete
MEET: meet_list, meet_get, meet_create
FORMS: forms_list, forms_get, forms_responses, forms_create
CHAT: chat_spaces, chat_messages, chat_send
PEOPLE: people_contacts, people_search

CRITICAL RULES:
1. Do NOT execute anything. Return ONLY valid JSON matching this schema:
For single tool query:
{{
  "tool": "<registered_tool_name>",
  "arguments": {{
    "query": "<search_query_if_applicable>",
    "date_range": "<today|tomorrow|yesterday|this_week|next_week|last_7_days|etc>",
    "max_results": 20,
    "resource_name": "<resource_name_if_applicable>"
  }},
  "summarize": false,
  "requires_confirmation": false,
  "confidence": 0.95
}}

For multi-tool queries (e.g. "Show my unread emails and today's meetings"):
{{
  "tools": [
    {{"tool": "gmail_list", "arguments": {{"query": "is:unread", "max_results": 20}}}},
    {{"tool": "calendar_list", "arguments": {{"date_range": "today", "max_results": 20}}}}
  ],
  "summarize": false,
  "confidence": 0.95
}}

2. If modifying or deleting (send email, delete email, create meeting, clear sheet), set "requires_confirmation": true.
3. If asking for a summary or analytical reasoning ("summarize my emails", "which emails need attention", "what should I focus on"), set "summarize": true.
4. Output JSON ONLY.
"""
        response_text = gemini_client.generate_content(prompt)
        if not response_text:
            return None
        text = response_text.replace('```json', '').replace('```', '').strip()
        s = text.find('{')
        e = text.rfind('}') + 1
        if s != -1 and e != -1:
            return json.loads(text[s:e])
        return None

    def _is_follow_up_query(self, query: str) -> bool:
        """Detect if the query refers to previous results."""
        q = query.strip().lower()
        follow_up_patterns = [
            r'^(?:which|what)\s+(?:one|event|meeting|email|file|task)\b',
            r'^summarize\s+(?:them|it|these|those)\b',
            r'^(?:show|tell)\s+(?:me\s+)?more\s+about\b',
            r'^the\s+(?:first|second|third|last)\s+one\b',
            r'^create\s+(?:a\s+)?task\s+for\b',
        ]
        return any(re.search(pat, q) for pat in follow_up_patterns)

    def _handle_follow_up_intent(self, query: str) -> Optional[StructuredIntent]:
        """Resolve a follow-up query against previous context."""
        q = query.strip().lower()
        last_service = self.context.last_service
        last_data = self.context.last_data or []

        # "Summarize them" / "Summarize it"
        if re.search(r'\bsummarize\s+(?:them|it|these|those)\b', q):
            return StructuredIntent(
                intent='summarize',
                service=last_service or 'gmail',
                operation='summarize_messages' if last_service == 'gmail' else 'get_document_text',
                parameters={'summarize': True, 'use_cached_context': True},
                confidence=0.95,
                original_query=query,
            )

        # "Which one is with X"
        m_which = re.search(r'which\s+(?:one|event|meeting|email)\s+is\s+(?:with|about|from)?\s*(.+)', q)
        if m_which:
            target_term = m_which.group(1).strip().strip('?.')
            return StructuredIntent(
                intent='filter_context',
                service=last_service or 'calendar',
                operation='get_event' if last_service == 'calendar' else 'get_message',
                parameters={'filter_term': target_term, 'use_cached_context': True},
                confidence=0.92,
                original_query=query,
            )

        # "Create a task for the important ones"
        if 'create a task' in q or 'add task' in q:
            return StructuredIntent(
                intent='create',
                service='tasks',
                operation='create_task',
                parameters={'title': query, 'from_context': True},
                requires_confirmation=True,
                confidence=0.88,
                original_query=query,
            )

        return None

    def _deterministic_parse(self, query: str) -> Dict[str, Any]:
        """
        High-accuracy fallback parser for natural language Workspace queries.
        Works offline without Gemini API keys.
        """
        q = query.strip().lower()

        # Multi-service scenario: "Show my unread emails and today's meetings"
        if ('email' in q or 'mail' in q or 'unread' in q) and ('meeting' in q or 'calendar' in q):
            return {
                'intent': 'composite',
                'service': 'composite',
                'operation': 'multi_tool',
                'tools': [
                    {'tool': 'gmail_list', 'arguments': {'query': 'is:unread', 'max_results': 20}},
                    {'tool': 'calendar_list', 'arguments': {'date_range': 'today' if 'today' in q else 'upcoming', 'max_results': 20}},
                ],
                'confidence': 0.95,
            }

        # Multi-service scenario: Focus / Attention across emails, meetings and tasks
        if 'focus' in q or (('email' in q or 'mail' in q) and ('meeting' in q or 'calendar' in q) and ('task' in q or 'todo' in q)):
            return {
                'intent': 'composite',
                'service': 'composite',
                'operation': 'multi_tool',
                'tools': [
                    {'tool': 'gmail_list', 'arguments': {'query': 'is:unread', 'max_results': 20}},
                    {'tool': 'calendar_list', 'arguments': {'date_range': 'today', 'max_results': 20}},
                    {'tool': 'tasks_list', 'arguments': {'status': 'pending', 'max_results': 20}},
                ],
                'parameters': {'summarize': True, 'analysis_prompt': query},
                'confidence': 0.95,
            }

        # Multi-service scenario: "Show my upcoming meetings and related tasks"
        if ('meeting' in q or 'calendar' in q) and ('task' in q or 'todo' in q):
            return {
                'intent': 'composite',
                'service': 'calendar',
                'operation': 'composite_calendar_tasks',
                'parameters': {'time_range': 'upcoming'},
                'confidence': 0.90,
            }

        # Multi-service scenario: "What requires my attention today?"
        if 'attention' in q and ('today' in q or 'now' in q or 'pending' in q):
            return {
                'intent': 'composite',
                'service': 'gmail',
                'operation': 'composite_daily_attention',
                'parameters': {'time_range': 'today'},
                'confidence': 0.92,
            }

        # 1. GMAIL
        if any(w in q for w in ['email', 'emails', 'inbox', 'mail', 'messages', 'unread']):
            is_summary = any(w in q for w in ['summarize', 'summary', 'recap', 'brief'])
            is_delete = any(w in q for w in ['delete', 'trash', 'remove'])
            is_send = any(w in q for w in ['send', 'compose', 'write email'])
            is_attention = any(w in q for w in ['attention', 'important', 'urgent', 'priority'])

            # Delete all unread emails
            if is_delete and 'unread' in q:
                return {
                    'intent': 'delete',
                    'service': 'gmail',
                    'operation': 'delete_message',
                    'tool': 'gmail_delete',
                    'parameters': {'query': 'is:unread'},
                    'requires_confirmation': True,
                    'confidence': 0.95,
                }

            # Which of my unread emails need attention?
            if is_attention and 'unread' in q:
                return {
                    'intent': 'summarize',
                    'service': 'gmail',
                    'operation': 'summarize_messages',
                    'tool': 'gmail_list',
                    'parameters': {
                        'query': 'is:unread',
                        'summarize': True,
                        'analysis_prompt': 'Which of my unread emails need attention?',
                        'max_results': 20,
                    },
                    'confidence': 0.95,
                }

            # Extract from: sender
            m_from = re.search(r'from\s+([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}|[A-Za-z0-9._-]+)', q)
            sender = m_from.group(1) if m_from else None

            gmail_q_parts = []
            if 'unread' in q:
                gmail_q_parts.append('is:unread')
            if sender:
                gmail_q_parts.append(f'from:{sender}')
            if 'important' in q:
                gmail_q_parts.append('is:important')

            time_range = None
            if 'this week' in q:
                time_range = 'this_week'
            elif 'today' in q:
                time_range = 'today'
            elif 'yesterday' in q:
                time_range = 'yesterday'

            op = 'list_messages'
            tool_name = 'gmail_list'
            if is_summary:
                op = 'summarize_messages'
                tool_name = 'gmail_list'
            elif is_delete:
                op = 'trash_message'
                tool_name = 'gmail_trash'
            elif is_send:
                op = 'send_message'
                tool_name = 'gmail_send'

            return {
                'intent': 'summarize' if is_summary else ('delete' if is_delete else ('send' if is_send else 'list')),
                'service': 'gmail',
                'operation': op,
                'tool': tool_name,
                'parameters': {
                    'query': ' '.join(gmail_q_parts),
                    'time_range': time_range,
                    'max_results': 20,
                    'summarize': is_summary,
                },
                'requires_confirmation': is_delete or is_send,
                'confidence': 0.95,
            }

        # 2. CALENDAR
        if any(w in q for w in ['meeting', 'meetings', 'calendar', 'appointment', 'appointments', 'events', 'schedule']):
            is_create = any(w in q for w in ['create', 'schedule', 'book', 'add meeting', 'set up'])
            is_delete = any(w in q for w in ['delete', 'cancel', 'remove'])

            time_range = 'upcoming'
            if 'today' in q:
                time_range = 'today'
            elif 'tomorrow' in q:
                time_range = 'tomorrow'
            elif 'this week' in q:
                time_range = 'this_week'
            elif 'next week' in q:
                time_range = 'next_week'
            elif 'yesterday' in q:
                time_range = 'yesterday'

            op = 'list_events'
            tool_name = 'calendar_list'
            if is_create:
                op = 'create_event'
                tool_name = 'calendar_create'
            elif is_delete:
                op = 'delete_event'
                tool_name = 'calendar_delete'

            return {
                'intent': 'create' if is_create else ('delete' if is_delete else 'list'),
                'service': 'calendar',
                'operation': op,
                'tool': tool_name,
                'parameters': {
                    'time_range': time_range,
                    'date_range': time_range,
                    'max_results': 20,
                },
                'requires_confirmation': is_create or is_delete,
                'confidence': 0.95,
            }

        # 3. SHEETS
        if any(w in q for w in ['spreadsheet', 'spreadsheets', 'sheets', 'sheet', 'rows', 'tabular']):
            res_name = None
            m_named = re.search(r'(?:named|called)\s+["\']?([^"\']+)["\']?', query, re.IGNORECASE)
            if m_named:
                res_name = m_named.group(1).strip()
            else:
                m_from = re.search(r'(?:from|in|into)\s+(?:the\s+|my\s+)?([A-Za-z0-9_\s-]+?)\s+(?:spreadsheet|sheet)', query, re.IGNORECASE)
                if m_from:
                    res_name = m_from.group(1).strip()
                else:
                    m_other = re.search(r'(?:show|open|find|get)\s+(?:the\s+|my\s+)?([A-Za-z0-9_\s-]+?)\s+(?:spreadsheet|sheet)', query, re.IGNORECASE)
                    if m_other:
                        res_name = m_other.group(1).strip()

            is_data_req = any(re.search(rf'\b{w}\b', q) for w in ['data from', 'read', 'rows from', 'content of', 'values from', 'show the data'])
            is_find_req = any(re.search(rf'\b{w}\b', q) for w in ['find', 'search', 'which', 'locate'])
            if res_name:
                if is_find_req and not any(w in q for w in ['data from', 'rows from', 'values from']):
                    return {
                        'intent': 'list',
                        'service': 'sheets',
                        'operation': 'list_spreadsheets',
                        'tool': 'sheets_list',
                        'parameters': {'resource_name': res_name, 'max_results': 20},
                        'confidence': 0.95,
                    }
                elif is_data_req:
                    return {
                        'intent': 'read',
                        'service': 'sheets',
                        'operation': 'get_sheet_data',
                        'tool': 'sheets_read',
                        'parameters': {'resource_name': res_name, 'range': 'A1:Z50'},
                        'confidence': 0.95,
                    }
                else:
                    return {
                        'intent': 'get',
                        'service': 'sheets',
                        'operation': 'get_spreadsheet',
                        'tool': 'sheets_get',
                        'parameters': {'resource_name': res_name},
                        'confidence': 0.95,
                    }

            is_read = any(re.search(rf'\b{w}\b', q) for w in ['show', 'read', 'get', 'data', 'rows'])
            return {
                'intent': 'read' if is_read else 'list',
                'service': 'sheets',
                'operation': 'get_sheet_data' if is_read else 'list_spreadsheets',
                'tool': 'sheets_read' if is_read else 'sheets_list',
                'parameters': {
                    'resource_name': res_name,
                    'max_results': 20,
                },
                'confidence': 0.91,
            }

        # 4. TASKS
        if any(w in q for w in ['task', 'tasks', 'todo', 'todos', 'pending tasks']):
            is_create = any(w in q for w in ['create', 'add', 'new task'])
            is_complete = any(w in q for w in ['complete', 'finish', 'done'])
            return {
                'intent': 'create' if is_create else ('complete' if is_complete else 'list'),
                'service': 'tasks',
                'operation': 'create_task' if is_create else ('complete_task' if is_complete else 'list_tasks'),
                'tool': 'tasks_add' if is_create else ('tasks_complete' if is_complete else 'tasks_list'),
                'parameters': {
                    'status': 'needsAction',
                    'max_results': 20,
                },
                'requires_confirmation': is_create or is_complete,
                'confidence': 0.95,
            }

        # 5. DOCS
        if any(w in q for w in ['doc', 'docs', 'document', 'documents']):
            res_name = None
            m_named = re.search(r'(?:named|called)\s+["\']?([^"\']+)["\']?', query, re.IGNORECASE)
            if m_named:
                res_name = m_named.group(1).strip()
            return {
                'intent': 'list',
                'service': 'docs',
                'operation': 'list_documents',
                'tool': 'docs_list',
                'parameters': {
                    'resource_name': res_name,
                    'max_results': 20,
                },
                'confidence': 0.90,
            }

        # 6. DRIVE
        if any(w in q for w in ['file', 'files', 'drive', 'folder', 'modified recently', 'recent files']):
            return {
                'intent': 'list',
                'service': 'drive',
                'operation': 'list_files',
                'tool': 'drive_list',
                'parameters': {
                    'query': "trashed=false",
                    'max_results': 20,
                },
                'confidence': 0.92,
            }

        # 7. CHAT
        if any(w in q for w in ['chat', 'space', 'spaces']):
            return {
                'intent': 'list',
                'service': 'chat',
                'operation': 'list_spaces',
                'tool': 'chat_spaces',
                'parameters': {'max_results': 20},
                'confidence': 0.90,
            }

        # 8. PEOPLE / CONTACTS
        if any(w in q for w in ['contact', 'contacts', 'people']):
            return {
                'intent': 'list',
                'service': 'people',
                'operation': 'list_contacts',
                'tool': 'people_contacts',
                'parameters': {'page_size': 20},
                'confidence': 0.90,
            }

        # 9. MEET
        if 'meet' in q or 'meeting room' in q:
            return {
                'intent': 'list',
                'service': 'meet',
                'operation': 'list_spaces',
                'tool': 'meet_list',
                'parameters': {'max_results': 20},
                'confidence': 0.88,
            }

        # 10. FORMS
        if 'form' in q or 'forms' in q:
            return {
                'intent': 'list',
                'service': 'forms',
                'operation': 'list_forms',
                'tool': 'forms_list',
                'parameters': {'max_results': 20},
                'confidence': 0.88,
            }

        # Unknown intent
        return {
            'intent': 'unknown',
            'service': 'unknown',
            'operation': 'unknown',
            'confidence': 0.2,
        }

    # -----------------------------------------------------------------------
    # Step 3: Execution & Security Layer
    # -----------------------------------------------------------------------

    def execute_query(
        self,
        query: str,
        output_format: str = 'table',
        allow_interactive: bool = True,
        confirmation_override: Optional[bool] = None,
        debug: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute the natural language query end-to-end.
        Returns a dictionary with result metadata, data, and formatted string.
        """
        # Step 1: Interpret Intent
        intent = self.interpret_query(query)

        # Step 2: Validate Intent
        if not intent.is_valid:
            error_msg = intent.error_message or "Could not reliably understand your request."
            return {
                'status': 'error',
                'message': error_msg,
                'intent': intent.to_dict(),
                'data': None,
                'output': f"{Fore.RED}✗ {error_msg}{Style.RESET_ALL}",
            }

        # Step 3: Check confirmation for write / destructive operations
        if intent.requires_confirmation:
            if confirmation_override is False:
                return {
                    'status': 'cancelled',
                    'message': 'Operation cancelled (confirmation declined).',
                    'intent': intent.to_dict(),
                    'data': None,
                    'output': "Operation cancelled.",
                }
            elif confirmation_override is None and allow_interactive:
                confirmed = self._prompt_confirmation(intent)
                if not confirmed:
                    return {
                        'status': 'cancelled',
                        'message': 'Operation cancelled by user.',
                        'intent': intent.to_dict(),
                        'data': None,
                        'output': "Operation cancelled by user.",
                    }

        # Step 4: OAuth / Permissions Check
        if not self.oauth_manager.is_authenticated():
            raise AuthenticationError(
                "Not authenticated with Google Workspace.",
                "Please run 'hermes auth login' to authenticate before executing queries."
            )

        # Step 5: Execute authorized Workspace API operations via ToolExecutor
        tool_results: List[ToolExecutionResult] = []
        try:
            if intent.operation == 'composite_calendar_tasks':
                raw_data = self._exec_composite_calendar_tasks(intent.parameters)
                tool_results = [
                    ToolExecutionResult(tool_name='calendar_list', service_name='calendar', status='success', data=raw_data.get('upcoming_meetings', []), item_count=len(raw_data.get('upcoming_meetings', []))),
                    ToolExecutionResult(tool_name='tasks_list', service_name='tasks', status='success', data=raw_data.get('pending_tasks', []), item_count=len(raw_data.get('pending_tasks', []))),
                ]
            elif intent.operation == 'composite_daily_attention':
                raw_data = self._exec_composite_daily_attention(intent.parameters)
                tool_results = [
                    ToolExecutionResult(tool_name='calendar_list', service_name='calendar', status='success', data=raw_data.get('today_meetings', []), item_count=len(raw_data.get('today_meetings', []))),
                    ToolExecutionResult(tool_name='gmail_list', service_name='gmail', status='success', data=raw_data.get('unread_emails', []), item_count=len(raw_data.get('unread_emails', []))),
                    ToolExecutionResult(tool_name='tasks_list', service_name='tasks', status='success', data=raw_data.get('pending_tasks', []), item_count=len(raw_data.get('pending_tasks', []))),
                ]
            elif intent.intent == 'filter_context' and intent.parameters.get('use_cached_context'):
                raw_data = self._filter_context_data(intent.parameters.get('filter_term', ''))
                tool_results = [ToolExecutionResult(tool_name='filter_context', service_name=intent.service, status='success', data=raw_data, item_count=len(raw_data))]
            elif intent.tools:
                tool_results = self.tool_executor.execute_multi_tools(
                    intent.tools,
                    allow_interactive=allow_interactive,
                    confirmation_override=confirmation_override,
                    debug=debug,
                )
                for tr in tool_results:
                    if tr.status == 'cancelled':
                        return {
                            'status': 'cancelled',
                            'message': tr.error or 'Operation cancelled.',
                            'intent': intent.to_dict(),
                            'data': None,
                            'output': tr.error or 'Operation cancelled.',
                        }
                    if tr.status == 'error':
                        return {
                            'status': 'error',
                            'message': tr.error,
                            'intent': intent.to_dict(),
                            'data': None,
                            'output': f"{Fore.RED}✗ {tr.error}{Style.RESET_ALL}",
                        }
                raw_data = self._combine_multi_tool_results(tool_results)
            else:
                tool_name = intent.tool or SERVICE_OP_TO_TOOL.get((intent.service, intent.operation), f"{intent.service}_{intent.operation}")
                tool_res = self.tool_executor.execute_tool(
                    tool_name=tool_name,
                    arguments=intent.parameters,
                    allow_interactive=allow_interactive,
                    confirmation_override=confirmation_override,
                    debug=debug,
                )
                tool_results = [tool_res]
                if tool_res.status == 'cancelled':
                    return {
                        'status': 'cancelled',
                        'message': tool_res.error or 'Operation cancelled.',
                        'intent': intent.to_dict(),
                        'data': None,
                        'output': tool_res.error or 'Operation cancelled.',
                    }
                if tool_res.status == 'error':
                    return {
                        'status': 'error',
                        'message': tool_res.error,
                        'intent': intent.to_dict(),
                        'data': None,
                        'output': f"{Fore.RED}✗ {tool_res.error}{Style.RESET_ALL}",
                    }
                raw_data = tool_res.data
        except (ResourceNotFoundError, AmbiguousResourceNameError) as e:
            return {
                'status': 'error',
                'message': str(e),
                'intent': intent.to_dict(),
                'data': None,
                'output': f"{Fore.YELLOW}⚠ {e}{Style.RESET_ALL}",
            }
        except Exception as e:
            logger.error(f"Execution error for {intent.service}.{intent.operation}: {e}")
            return {
                'status': 'error',
                'message': str(e),
                'intent': intent.to_dict(),
                'data': None,
                'output': f"{Fore.RED}✗ API Operation Error: {e}{Style.RESET_ALL}",
            }

        # Step 6: Post-Processing & Gemini presentation (if requested)
        processed_data, summary_text = self._post_process(intent, raw_data, query)

        # Step 7: Update Conversation Context
        self.context.update(intent, raw_data, query)

        # Step 8: Format Output
        formatted_output = self._format_result(processed_data, summary_text, output_format, intent)

        # Step 9: Prepend Debug Trace if requested
        if debug:
            debug_header = self._format_debug_pipeline(query, intent, tool_results)
            if output_format == 'table':
                formatted_output = debug_header + "\n\n" + formatted_output

        return {
            'status': 'success',
            'intent': intent.to_dict(),
            'data': processed_data,
            'summary': summary_text,
            'output': formatted_output,
            'tool_results': [tr.__dict__ for tr in tool_results],
        }

    def _combine_multi_tool_results(self, results: List[ToolExecutionResult]) -> Dict[str, Any]:
        """Combine results from multiple tools into a coherent dictionary structure."""
        combined: Dict[str, Any] = {}
        for res in results:
            tname = res.tool_name
            if tname == 'gmail_list':
                combined['unread_emails'] = res.data or []
            elif tname == 'calendar_list':
                combined['today_meetings'] = res.data or []
            elif tname == 'tasks_list':
                combined['pending_tasks'] = res.data or []
            else:
                combined[tname] = res.data
        return combined

    def _format_debug_pipeline(
        self,
        query: str,
        intent: StructuredIntent,
        tool_results: List[ToolExecutionResult]
    ) -> str:
        """Format the internal AI/tool pipeline for --debug mode adhering to Hermes spec."""
        lines = [
            f"{Fore.WHITE}{Style.BRIGHT}Query:{Style.RESET_ALL}",
            query,
            "",
            f"{Fore.WHITE}{Style.BRIGHT}Intent:{Style.RESET_ALL}",
            intent.intent if intent.intent != 'unknown' else intent.operation,
            "",
        ]
        for tr in tool_results:
            lines.extend([
                f"{Fore.WHITE}{Style.BRIGHT}Tool:{Style.RESET_ALL}",
                tr.tool_name,
                "",
                f"{Fore.WHITE}{Style.BRIGHT}Arguments:{Style.RESET_ALL}",
            ])
            if tr.arguments:
                for k, v in tr.arguments.items():
                    if k not in ('summarize', 'analysis_prompt'):
                        lines.append(f"{k}={v}")
            else:
                lines.append("(none)")
            lines.extend([
                "",
                f"{Fore.WHITE}{Style.BRIGHT}Authentication:{Style.RESET_ALL}",
                "Valid",
                "",
                f"{Fore.WHITE}{Style.BRIGHT}Executing tool...{Style.RESET_ALL}",
                "",
                f"{Fore.WHITE}{Style.BRIGHT}{tr.service_name.capitalize()} API:{Style.RESET_ALL}",
                "Success" if tr.status == 'success' else f"Failed ({tr.error})",
                "",
                f"{Fore.WHITE}{Style.BRIGHT}Retrieved:{Style.RESET_ALL}",
                f"{tr.item_count} {'messages' if tr.service_name == 'gmail' else ('events' if tr.service_name == 'calendar' else 'items')}",
            ])
        return "\n".join(lines)


    # -----------------------------------------------------------------------
    # Service Operation Routing
    # -----------------------------------------------------------------------

    def _route_operation(self, intent: StructuredIntent) -> Any:
        """Route validated intent to the authorized Google Workspace service."""
        service_name = intent.service
        operation = intent.operation
        params = intent.parameters

        # Composite operations
        if operation == 'composite_calendar_tasks':
            return self._exec_composite_calendar_tasks(params)
        if operation == 'composite_daily_attention':
            return self._exec_composite_daily_attention(params)

        # Context follow-up filter
        if intent.intent == 'filter_context' and params.get('use_cached_context'):
            filter_term = params.get('filter_term', '').lower()
            return self._filter_context_data(filter_term)

        if service_name == 'gmail':
            return self._exec_gmail(operation, params)
        elif service_name == 'calendar':
            return self._exec_calendar(operation, params)
        elif service_name == 'drive':
            return self._exec_drive(operation, params)
        elif service_name == 'sheets':
            return self._exec_sheets(operation, params)
        elif service_name == 'docs':
            return self._exec_docs(operation, params)
        elif service_name == 'tasks':
            return self._exec_tasks(operation, params)
        elif service_name == 'meet':
            return self._exec_meet(operation, params)
        elif service_name == 'forms':
            return self._exec_forms(operation, params)
        elif service_name == 'chat':
            return self._exec_chat(operation, params)
        elif service_name == 'people':
            return self._exec_people(operation, params)
        else:
            raise ValueError(f"Unsupported service: {service_name}")

    # -----------------------------------------------------------------------
    # GMAIL Execution
    # -----------------------------------------------------------------------

    def _exec_gmail(self, operation: str, params: Dict[str, Any]) -> Any:
        svc: GmailService = self.get_service('gmail')

        if operation in ('list_messages', 'summarize_messages'):
            query_str = params.get('query', '')
            time_range = params.get('time_range')
            if time_range:
                bounds = self.date_parser.parse_range(time_range)
                if bounds:
                    start_dt, end_dt = bounds
                    after_str = start_dt.strftime('%Y/%m/%d')
                    before_str = (end_dt + timedelta(days=1)).strftime('%Y/%m/%d')
                    query_str = f"{query_str} after:{after_str} before:{before_str}".strip()

            max_results = int(params.get('max_results', 20))
            messages = svc.list_messages(query=query_str, max_results=max_results)
            # Normalize display fields
            formatted = []
            for m in messages:
                formatted.append({
                    'ID': m.get('id', '')[:16],
                    'From': m.get('from', '')[:30],
                    'Subject': m.get('subject', 'No subject')[:45],
                    'Date': str(m.get('date', ''))[:16],
                    'Snippet': truncate_text(m.get('snippet', ''), 60),
                })
            return formatted

        elif operation == 'get_message':
            msg_id = params.get('message_id')
            if not msg_id:
                return []
            return svc.get_message(msg_id)

        elif operation == 'send_message':
            to = params.get('to')
            subject = params.get('subject', '(No Subject)')
            body = params.get('body', '')
            res = svc.send_message(to=to, subject=subject, body=body)
            return {'status': 'sent', 'message_id': res.get('id')}

        elif operation in ('trash_message', 'delete_message'):
            msg_id = params.get('message_id')
            if msg_id:
                svc.trash_message(msg_id)
                return {'status': 'trashed', 'message_id': msg_id}
            return {'status': 'error', 'message': 'Missing message_id'}

        elif operation == 'get_profile':
            return svc.get_profile()

        return []

    # -----------------------------------------------------------------------
    # CALENDAR Execution
    # -----------------------------------------------------------------------

    def _exec_calendar(self, operation: str, params: Dict[str, Any]) -> Any:
        svc: CalendarService = self.get_service('calendar')
        cal_id = params.get('calendar_id', 'primary')

        if operation in ('list_events', 'get_today_events', 'get_tomorrow_events', 'get_upcoming_events'):
            time_range = params.get('time_range', 'upcoming')
            if operation == 'get_today_events' or time_range == 'today':
                events = svc.get_today_events(calendar_id=cal_id)
            elif operation == 'get_tomorrow_events' or time_range == 'tomorrow':
                events = svc.get_tomorrow_events(calendar_id=cal_id)
            elif time_range and time_range != 'upcoming':
                bounds = self.date_parser.parse_range(time_range)
                if bounds:
                    events = svc.list_events(calendar_id=cal_id, time_min=bounds[0], time_max=bounds[1])
                else:
                    events = svc.get_upcoming_events(calendar_id=cal_id, limit=int(params.get('max_results', 20)))
            else:
                events = svc.get_upcoming_events(calendar_id=cal_id, limit=int(params.get('max_results', 20)))

            formatted = []
            for ev in events:
                start_str = ev.get('start', '')
                if 'T' in start_str:
                    start_disp = start_str.replace('T', ' ')[:16]
                else:
                    start_disp = start_str[:10]
                formatted.append({
                    'Title': ev.get('summary', 'Untitled')[:35],
                    'Start': start_disp,
                    'Location': ev.get('location', '')[:25] or (ev.get('meet_link', '') and 'Google Meet') or '-',
                    'Status': ev.get('status', 'confirmed'),
                    'ID': ev.get('id', '')[:16],
                })
            return formatted

        elif operation == 'list_calendars':
            cals = svc.list_calendars()
            return [{'Summary': c.get('summary'), 'ID': c.get('id'), 'Primary': c.get('primary')} for c in cals]

        elif operation == 'create_event':
            summary = params.get('title') or params.get('summary', 'New Event')
            start = params.get('start_time') or datetime.now(self.tzinfo).isoformat()
            end = params.get('end_time')
            created = svc.create_event(summary=summary, start_time=start, end_time=end, calendar_id=cal_id)
            return {'status': 'created', 'event': created}

        elif operation == 'delete_event':
            event_id = params.get('event_id')
            if event_id:
                ok = svc.delete_event(event_id=event_id, calendar_id=cal_id)
                return {'status': 'deleted' if ok else 'failed', 'event_id': event_id}
            return {'status': 'error', 'message': 'Missing event_id'}

        return []

    # -----------------------------------------------------------------------
    # DRIVE Execution
    # -----------------------------------------------------------------------

    def _exec_drive(self, operation: str, params: Dict[str, Any]) -> Any:
        svc: DriveService = self.get_service('drive')

        if operation in ('list_files', 'search_files'):
            query = params.get('query', "trashed=false")
            max_results = int(params.get('max_results', 20))
            res = svc.service.files().list(
                q=query,
                pageSize=max_results,
                orderBy='modifiedTime desc',
                fields="files(id, name, mimeType, modifiedTime, webViewLink, size)"
            ).execute()
            files = res.get('files', [])
            formatted = []
            for f in files:
                mime = f.get('mimeType', '').replace('application/vnd.google-apps.', '')
                formatted.append({
                    'Name': f.get('name', 'Untitled')[:40],
                    'Type': mime[:15],
                    'Modified': f.get('modifiedTime', '')[:10],
                    'ID': f.get('id', '')[:16],
                })
            return formatted

        elif operation == 'get_file':
            fid = params.get('file_id')
            if fid:
                return svc.get_file_metadata(fid)
            return {}

        return []

    # -----------------------------------------------------------------------
    # SHEETS Execution & Resource Resolution
    # -----------------------------------------------------------------------

    def _exec_sheets(self, operation: str, params: Dict[str, Any]) -> Any:
        svc: SheetsService = self.get_service('sheets')

        if operation == 'list_spreadsheets':
            sheets = svc.list_spreadsheets(max_results=int(params.get('max_results', 20)))
            return [{'Name': s.get('name', 'Untitled'), 'ID': s.get('id'), 'Modified': s.get('modified_time', '')[:10]} for s in sheets]

        elif operation in ('get_sheet_data', 'read_range'):
            res_name = params.get('resource_name') or params.get('spreadsheet_id')
            spreadsheet_id = None

            if res_name:
                # 1. Resolve spreadsheet resource
                spreadsheets = svc.list_spreadsheets(max_results=100)
                try:
                    resolved = GlobalResourceResolver.resolve(
                        res_name,
                        items=spreadsheets,
                        module='sheets',
                        resource_type='Spreadsheet',
                        config_manager=self.config_manager,
                        allow_prompt=False,
                    )
                    spreadsheet_id = GlobalResourceResolver.get_resource_id(resolved)
                except AmbiguousResourceNameError as e:
                    # Propagate ambiguous selection
                    matches_str = "\n".join([f"  - {GlobalResourceResolver.get_resource_title(m)} (ID: {GlobalResourceResolver.get_resource_id(m)})" for m in e.matches])
                    raise AmbiguousResourceNameError(
                        e.name,
                        e.matches,
                        f"Found multiple spreadsheets matching '{e.name}':\n{matches_str}\nPlease specify the exact name or ID."
                    )
                except ResourceNotFoundError:
                    # Try treating res_name as direct spreadsheet ID
                    spreadsheet_id = res_name
            else:
                # Fallback to config default spreadsheet
                if self.config_manager:
                    spreadsheet_id = self.config_manager.get('sheets.default_spreadsheet')

            if not spreadsheet_id:
                return {'error': "Could not resolve spreadsheet. Please specify spreadsheet name or ID."}

            sheet_range = params.get('range', 'A1:Z50')
            sheet_name = params.get('sheet_name')
            if sheet_name:
                data = svc.get_sheet_data(spreadsheet_id, sheet_name=sheet_name)
            else:
                data = svc.read_range(spreadsheet_id, sheet_range)

            # Limit data preview for terminal if too large
            if isinstance(data, list) and len(data) > 50:
                return {
                    '_total_count': len(data),
                    '_preview_count': 50,
                    'data': data[:50],
                    '_notice': f"Showing preview of 50 of {len(data)} rows.",
                }
            return data

        elif operation == 'get_spreadsheet':
            res_name = params.get('resource_name') or params.get('spreadsheet_id')
            spreadsheet_id = None
            if res_name:
                spreadsheets = svc.list_spreadsheets(max_results=100)
                try:
                    resolved = GlobalResourceResolver.resolve(
                        res_name,
                        items=spreadsheets,
                        module='sheets',
                        resource_type='Spreadsheet',
                        config_manager=self.config_manager,
                        allow_prompt=False,
                    )
                    spreadsheet_id = GlobalResourceResolver.get_resource_id(resolved)
                except AmbiguousResourceNameError as e:
                    matches_str = "\n".join([f"  - {GlobalResourceResolver.get_resource_title(m)} (ID: {GlobalResourceResolver.get_resource_id(m)})" for m in e.matches])
                    raise AmbiguousResourceNameError(
                        e.name,
                        e.matches,
                        f"Found multiple spreadsheets matching '{e.name}':\n{matches_str}\nPlease specify the exact name or ID."
                    )
                except ResourceNotFoundError:
                    spreadsheet_id = res_name
            if not spreadsheet_id:
                return {'error': "Could not resolve spreadsheet. Please specify spreadsheet name or ID."}
            return svc.get_spreadsheet(spreadsheet_id)

        return []

    # -----------------------------------------------------------------------
    # DOCS Execution
    # -----------------------------------------------------------------------

    def _exec_docs(self, operation: str, params: Dict[str, Any]) -> Any:
        svc: DocsService = self.get_service('docs')

        if operation == 'list_documents':
            docs = svc.list_documents(max_results=int(params.get('max_results', 20)))
            return [{'Name': d.get('name', 'Untitled'), 'ID': d.get('id'), 'Modified': d.get('modified_time', '')[:10]} for d in docs]

        elif operation in ('get_document', 'get_document_text'):
            res_name = params.get('resource_name') or params.get('document_id')
            doc_id = res_name
            if res_name:
                docs = svc.list_documents(max_results=50)
                try:
                    resolved = GlobalResourceResolver.resolve(
                        res_name,
                        items=docs,
                        module='docs',
                        resource_type='Document',
                        config_manager=self.config_manager,
                        allow_prompt=False,
                    )
                    doc_id = GlobalResourceResolver.get_resource_id(resolved)
                except Exception:
                    pass
            if not doc_id:
                return {'error': 'Document not found'}
            text = svc.get_document_text(doc_id)
            return {'document_id': doc_id, 'text': text}

        return []

    # -----------------------------------------------------------------------
    # TASKS Execution
    # -----------------------------------------------------------------------

    def _exec_tasks(self, operation: str, params: Dict[str, Any]) -> Any:
        svc: TasksService = self.get_service('tasks')

        if operation == 'list_tasks':
            tl_id = params.get('task_list_id') or params.get('tasklist_id') or '@default'
            raw = svc.list_tasks(task_list_id=tl_id)
            if isinstance(raw, dict):
                tasks = raw.get('items', [])
            elif isinstance(raw, list):
                tasks = raw
            else:
                tasks = []

            formatted = []
            for t in tasks:
                if params.get('status') in ('needsAction', 'pending') and t.get('status') == 'completed':
                    continue
                due_str = t.get('due', '')[:10] if t.get('due') else '-'
                formatted.append({
                    'Title': t.get('title', 'Untitled')[:40],
                    'Status': 'Pending' if t.get('status') == 'needsAction' else 'Completed',
                    'Due': due_str,
                    'ID': t.get('id', '')[:16],
                })
            return formatted

        elif operation == 'create_task':
            tl_id = params.get('tasklist_id', '@default')
            title = params.get('title', 'New Task')
            created = svc.create_task(tasklist_id=tl_id, title=title)
            return {'status': 'created', 'task': created}

        elif operation == 'complete_task':
            task_id = params.get('task_id')
            if task_id:
                return svc.complete_task(tasklist_id='@default', task_id=task_id)
            return {'status': 'error', 'message': 'Missing task_id'}

        return []

    # -----------------------------------------------------------------------
    # MEET, FORMS, CHAT, PEOPLE Execution
    # -----------------------------------------------------------------------

    def _exec_meet(self, operation: str, params: Dict[str, Any]) -> Any:
        svc: MeetService = self.get_service('meet')
        if operation == 'list_spaces':
            res = svc.service.spaces().list().execute()
            return [{'Name': s.get('name'), 'MeetingURI': s.get('meetingUri')} for s in res.get('spaces', [])]
        elif operation == 'create_space':
            space = svc.create_space()
            return {'status': 'created', 'space': space}
        return []

    def _exec_forms(self, operation: str, params: Dict[str, Any]) -> Any:
        svc: FormsService = self.get_service('forms')
        if operation == 'list_forms':
            forms = svc.list_forms()
            return [{'Title': f.get('title', 'Untitled'), 'ID': f.get('id')} for f in forms]
        return []

    def _exec_chat(self, operation: str, params: Dict[str, Any]) -> Any:
        svc: ChatService = self.get_service('chat')
        if operation == 'list_spaces':
            spaces = svc.list_spaces()
            return [{'DisplayName': s.get('displayName', 'Untitled'), 'SpaceID': s.get('name')} for s in spaces]
        return []

    def _exec_people(self, operation: str, params: Dict[str, Any]) -> Any:
        svc: PeopleService = self.get_service('people')
        if operation == 'list_contacts':
            return svc.list_contacts(page_size=int(params.get('page_size', 20)))
        elif operation == 'search_contacts':
            q = params.get('query', '')
            return svc.search_contacts(query=q)
        return []

    # -----------------------------------------------------------------------
    # Composite Operations (Multi-Service Queries)
    # -----------------------------------------------------------------------

    def _exec_composite_calendar_tasks(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Combine upcoming calendar meetings and pending tasks."""
        cal_svc: CalendarService = self.get_service('calendar')
        tasks_svc: TasksService = self.get_service('tasks')

        events = cal_svc.get_upcoming_events(limit=10)
        formatted_events = [{
            'Meeting': ev.get('summary', 'Untitled')[:35],
            'Start': ev.get('start', '')[:16],
            'Location': ev.get('location', '')[:20] or 'Google Meet',
        } for ev in events]

        tl_res = tasks_svc.list_task_lists().get('items', [])
        tasks = []
        if tl_res:
            raw_tasks = tasks_svc.list_tasks(tasklist_id=tl_res[0].get('id')).get('items', [])
            tasks = [{
                'Task': t.get('title', 'Untitled')[:40],
                'Status': 'Pending' if t.get('status') == 'needsAction' else 'Completed',
                'Due': t.get('due', '')[:10] if t.get('due') else '-',
            } for t in raw_tasks if t.get('status') == 'needsAction']

        return {
            'upcoming_meetings': formatted_events,
            'pending_tasks': tasks,
        }

    def _exec_composite_daily_attention(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Collect today's events, unread emails, and pending tasks for daily attention."""
        cal_svc: CalendarService = self.get_service('calendar')
        gmail_svc: GmailService = self.get_service('gmail')
        tasks_svc: TasksService = self.get_service('tasks')

        today_events = cal_svc.get_today_events()
        unread_emails = gmail_svc.list_messages(query='is:unread', max_results=10)
        tl_res = tasks_svc.list_task_lists().get('items', [])
        tasks = []
        if tl_res:
            raw_tasks = tasks_svc.list_tasks(tasklist_id=tl_res[0].get('id')).get('items', [])
            tasks = [t for t in raw_tasks if t.get('status') == 'needsAction']

        return {
            'today_meetings': [{
                'Title': ev.get('summary', 'Untitled')[:30],
                'Start': ev.get('start', '')[:16],
            } for ev in today_events],
            'unread_emails': [{
                'From': em.get('from', '')[:30],
                'Subject': em.get('subject', '')[:40],
                'Date': em.get('date', '')[:16],
            } for em in unread_emails],
            'pending_tasks': [{
                'Title': t.get('title', 'Untitled')[:35],
                'Due': t.get('due', '')[:10] if t.get('due') else '-',
            } for t in tasks],
        }

    def _filter_context_data(self, filter_term: str) -> List[Dict[str, Any]]:
        """Filter previously retrieved context data by a term."""
        if not self.context.last_data:
            return []
        
        clean_term = filter_term.lower().strip()
        for prefix in ['the ', 'a ', 'an ']:
            if clean_term.startswith(prefix):
                clean_term = clean_term[len(prefix):].strip()

        words = [w for w in re.split(r'\s+', clean_term) if len(w) > 2]

        matches = []
        for item in self.context.last_data:
            str_repr = json.dumps(item).lower()
            if clean_term in str_repr or (words and all(w in str_repr for w in words)):
                matches.append(item)
        return matches

    # -----------------------------------------------------------------------
    # Confirmation Prompting
    # -----------------------------------------------------------------------

    def _prompt_confirmation(self, intent: StructuredIntent) -> bool:
        """Prompt user for explicit confirmation before executing write/destructive operations."""
        print()
        print_warning(f"ACTION REQUIRED: Operation '{intent.operation}' on {intent.service.upper()} will modify Workspace data.")
        if intent.parameters:
            print("Parameters:")
            for k, v in intent.parameters.items():
                print(f"  {k}: {v}")
        print()
        try:
            return click.confirm("Do you want to proceed with this operation?", default=False)
        except Exception:
            return False

    # -----------------------------------------------------------------------
    # Post-Processing & Gemini Response Generation (Summaries/Attention)
    # -----------------------------------------------------------------------

    def _post_process(self, intent: StructuredIntent, raw_data: Any, query: str) -> Tuple[Any, Optional[str]]:
        """
        If user requested summarization, priority, or attention analysis,
        use Gemini to synthesize the retrieved data into a grounded summary.
        Gemini is strictly grounded in the retrieved data.
        """
        is_summary_req = (
            intent.operation == 'summarize_messages'
            or intent.parameters.get('summarize') is True
            or intent.operation == 'composite_daily_attention'
            or 'summarize' in query.lower()
            or 'require my attention' in query.lower()
        )

        if not is_summary_req or not raw_data:
            return raw_data, None

        gemini_client = self._get_gemini_client()
        if not gemini_client or not gemini_client.is_available:
            # Deterministic summary fallback
            if isinstance(raw_data, list):
                return raw_data, f"Retrieved {len(raw_data)} items matching your request."
            return raw_data, "Retrieved workspace data."

        # Prepare bounded payload for Gemini (never exceed context limits)
        serialized_data = json.dumps(raw_data, default=str)
        if len(serialized_data) > 8000:
            serialized_data = serialized_data[:8000] + "... [truncated for context safety]"

        prompt = f"""
You are an AI assistant for Google Workspace (Hermes CLI).
User requested: "{query}"

Authorized Workspace data retrieved:
{serialized_data}

CRITICAL RULES:
1. Ground your response STRICTLY in the provided data. Do NOT invent emails, events, files, or facts.
2. If summarizing emails, identify:
   - Key urgent/important messages
   - Action items
   - Senders and subjects
3. If analyzing what requires attention, provide a prioritized breakdown of today's schedule, urgent emails, and pending tasks.
4. Keep the output professional, crisp, and formatted for a terminal console.
"""
        try:
            summary = gemini_client.generate_content(prompt)
            return raw_data, summary
        except Exception as e:
            logger.warning(f"Gemini summarization failed: {e}")
            return raw_data, None

    # -----------------------------------------------------------------------
    # Output Formatting
    # -----------------------------------------------------------------------

    def _format_result(
        self,
        data: Any,
        summary_text: Optional[str],
        output_format: str,
        intent: StructuredIntent
    ) -> str:
        """Format the output according to the requested format (table, json, csv)."""
        # Strict machine-readable JSON
        if output_format == 'json':
            payload: Dict[str, Any] = {
                'intent': intent.to_dict(),
                'data': data,
            }
            if summary_text:
                payload['summary'] = summary_text
            return json.dumps(payload, indent=2, default=str)

        # Standard CSV
        if output_format == 'csv':
            if isinstance(data, list) and data:
                if isinstance(data[0], list):
                    import io, csv
                    output = io.StringIO()
                    writer = csv.writer(output)
                    for row in data:
                        writer.writerow(row)
                    return output.getvalue().strip()
                return format_output(data, format_type='csv')
            elif isinstance(data, dict) and 'data' in data and isinstance(data['data'], list):
                return format_output(data['data'], format_type='csv')
            return ""

        # Default Table / Terminal Format
        parts = []

        # If Gemini generated an analytical summary or presentation
        if summary_text:
            parts.append(summary_text.strip())
            parts.append("")

        # Data presentation
        if isinstance(data, list):
            if data:
                if isinstance(data[0], list):
                    from tabulate import tabulate
                    if len(data) > 1:
                        parts.append(tabulate(data[1:], headers=data[0], tablefmt='grid'))
                    else:
                        parts.append(tabulate(data, tablefmt='grid'))
                else:
                    parts.append(format_output(data, format_type='table'))
            else:
                parts.append("No items found.")
        elif isinstance(data, dict):
            if 'upcoming_meetings' in data:
                meetings = data.get('upcoming_meetings', [])
                tasks = data.get('pending_tasks', [])
                if meetings:
                    parts.append(f"{Fore.WHITE}{Style.BRIGHT}📅 Upcoming Meetings ({len(meetings)}){Style.RESET_ALL}")
                    parts.append(format_output(meetings, format_type='table'))
                    parts.append("")
                if tasks:
                    parts.append(f"{Fore.WHITE}{Style.BRIGHT}✅ Pending Tasks ({len(tasks)}){Style.RESET_ALL}")
                    parts.append(format_output(tasks, format_type='table'))
            elif 'today_meetings' in data or 'unread_emails' in data:
                meetings = data.get('today_meetings', [])
                emails = data.get('unread_emails', [])
                tasks = data.get('pending_tasks', [])
                if meetings:
                    parts.append(f"{Fore.WHITE}{Style.BRIGHT}📅 Today's Meetings ({len(meetings)}){Style.RESET_ALL}")
                    parts.append(format_output(meetings, format_type='table'))
                    parts.append("")
                if emails:
                    parts.append(f"{Fore.WHITE}{Style.BRIGHT}📧 Unread Emails ({len(emails)}){Style.RESET_ALL}")
                    parts.append(format_output(emails, format_type='table'))
                    parts.append("")
                if tasks:
                    parts.append(f"{Fore.WHITE}{Style.BRIGHT}✅ Pending Tasks ({len(tasks)}){Style.RESET_ALL}")
                    parts.append(format_output(tasks, format_type='table'))
            elif 'data' in data and isinstance(data['data'], list):
                if '_notice' in data:
                    parts.append(f"{Fore.CYAN}{data['_notice']}{Style.RESET_ALL}\n")
                parts.append(format_output(data['data'], format_type='table'))
            else:
                formatted_kv = []
                for k, v in data.items():
                    if not str(k).startswith('_'):
                        formatted_kv.append({'Key': k, 'Value': str(v)})
                if formatted_kv:
                    parts.append(format_output(formatted_kv, format_type='table'))
        elif data is not None:
            parts.append(str(data))

        return "\n".join(parts)
