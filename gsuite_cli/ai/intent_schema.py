"""
Intent schema, allowlist definitions, and validation rules for the Gemini NLQ pipeline.
Enforces strict security validation so that arbitrary or unverified operations cannot be executed.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Allowlist Definitions
# ---------------------------------------------------------------------------

ALLOWED_SERVICES: Set[str] = {
    'gmail',
    'calendar',
    'drive',
    'sheets',
    'docs',
    'meet',
    'forms',
    'tasks',
    'chat',
    'people',
}

ALLOWED_OPERATIONS: Dict[str, Set[str]] = {
    'gmail': {
        'list_messages',
        'get_message',
        'send_message',
        'trash_message',
        'delete_message',
        'summarize_messages',
        'get_profile',
        'composite_daily_attention',
    },
    'calendar': {
        'list_events',
        'get_event',
        'create_event',
        'delete_event',
        'list_calendars',
        'get_today_events',
        'get_tomorrow_events',
        'get_upcoming_events',
        'composite_calendar_tasks',
    },
    'drive': {
        'list_files',
        'search_files',
        'get_file',
        'trash_file',
        'delete_file',
    },
    'sheets': {
        'list_spreadsheets',
        'get_spreadsheet',
        'read_range',
        'get_sheet_data',
        'write_range',
        'append_rows',
    },
    'docs': {
        'list_documents',
        'get_document',
        'get_document_text',
        'create_document',
    },
    'meet': {
        'list_spaces',
        'get_space',
        'create_space',
        'end_active_conference',
    },
    'forms': {
        'list_forms',
        'get_form',
        'list_responses',
        'create_form',
    },
    'tasks': {
        'list_task_lists',
        'list_tasks',
        'get_task',
        'create_task',
        'complete_task',
        'delete_task',
    },
    'chat': {
        'list_spaces',
        'get_space',
        'list_messages',
        'send_message',
    },
    'people': {
        'list_contacts',
        'search_contacts',
    },
}

WRITE_OPERATIONS: Set[str] = {
    'send_message',
    'trash_message',
    'delete_message',
    'create_event',
    'delete_event',
    'trash_file',
    'delete_file',
    'write_range',
    'append_rows',
    'create_document',
    'create_space',
    'end_active_conference',
    'create_form',
    'create_task',
    'complete_task',
    'delete_task',
}

ALLOWED_PARAMETER_KEYS: Set[str] = {
    'query',
    'max_results',
    'limit',
    'page_size',
    'time_range',
    'time_min',
    'time_max',
    'resource_name',
    'resource_id',
    'calendar_id',
    'spreadsheet_id',
    'sheet_name',
    'range',
    'document_id',
    'space_id',
    'tasklist_id',
    'task_id',
    'event_id',
    'message_id',
    'file_id',
    'to',
    'subject',
    'body',
    'text',
    'title',
    'description',
    'start_time',
    'end_time',
    'date',
    'due',
    'header_row',
    'fields',
    'label',
    'status',
    'summarize',
}


# Mapping from internal tool name to (service, operation)
TOOL_TO_SERVICE_OP: Dict[str, Tuple[str, str]] = {
    'gmail_list': ('gmail', 'list_messages'),
    'gmail_get': ('gmail', 'get_message'),
    'gmail_search': ('gmail', 'list_messages'),
    'gmail_read': ('gmail', 'get_message'),
    'gmail_drafts': ('gmail', 'list_messages'),
    'gmail_labels': ('gmail', 'list_messages'),
    'gmail_send': ('gmail', 'send_message'),
    'gmail_reply': ('gmail', 'send_message'),
    'gmail_trash': ('gmail', 'trash_message'),
    'gmail_delete': ('gmail', 'delete_message'),
    'calendar_list': ('calendar', 'list_events'),
    'calendar_get': ('calendar', 'get_event'),
    'calendar_search': ('calendar', 'list_events'),
    'calendar_create': ('calendar', 'create_event'),
    'calendar_update': ('calendar', 'create_event'),
    'calendar_delete': ('calendar', 'delete_event'),
    'drive_list': ('drive', 'list_files'),
    'drive_search': ('drive', 'search_files'),
    'drive_get': ('drive', 'get_file'),
    'drive_trash': ('drive', 'trash_file'),
    'drive_delete': ('drive', 'delete_file'),
    'sheets_list': ('sheets', 'list_spreadsheets'),
    'sheets_get': ('sheets', 'get_spreadsheet'),
    'sheets_read': ('sheets', 'read_range'),
    'sheets_search': ('sheets', 'list_spreadsheets'),
    'sheets_write': ('sheets', 'write_range'),
    'sheets_append': ('sheets', 'append_rows'),
    'sheets_clear': ('sheets', 'write_range'),
    'docs_list': ('docs', 'list_documents'),
    'docs_get': ('docs', 'get_document_text'),
    'docs_create': ('docs', 'create_document'),
    'tasks_list': ('tasks', 'list_tasks'),
    'tasks_get': ('tasks', 'get_task'),
    'tasks_add': ('tasks', 'create_task'),
    'tasks_complete': ('tasks', 'complete_task'),
    'tasks_delete': ('tasks', 'delete_task'),
    'meet_list': ('meet', 'list_spaces'),
    'meet_get': ('meet', 'get_space'),
    'meet_create': ('meet', 'create_space'),
    'forms_list': ('forms', 'list_forms'),
    'forms_get': ('forms', 'get_form'),
    'forms_responses': ('forms', 'list_responses'),
    'forms_create': ('forms', 'create_form'),
    'chat_spaces': ('chat', 'list_spaces'),
    'chat_messages': ('chat', 'list_messages'),
    'chat_send': ('chat', 'send_message'),
    'people_contacts': ('people', 'list_contacts'),
    'people_search': ('people', 'search_contacts'),
}

SERVICE_OP_TO_TOOL: Dict[Tuple[str, str], str] = {
    ('gmail', 'list_messages'): 'gmail_list',
    ('gmail', 'get_message'): 'gmail_get',
    ('gmail', 'send_message'): 'gmail_send',
    ('gmail', 'trash_message'): 'gmail_trash',
    ('gmail', 'delete_message'): 'gmail_delete',
    ('calendar', 'list_events'): 'calendar_list',
    ('calendar', 'get_today_events'): 'calendar_list',
    ('calendar', 'get_tomorrow_events'): 'calendar_list',
    ('calendar', 'get_upcoming_events'): 'calendar_list',
    ('calendar', 'get_event'): 'calendar_get',
    ('calendar', 'create_event'): 'calendar_create',
    ('calendar', 'delete_event'): 'calendar_delete',
    ('drive', 'list_files'): 'drive_list',
    ('drive', 'search_files'): 'drive_search',
    ('drive', 'get_file'): 'drive_get',
    ('drive', 'trash_file'): 'drive_trash',
    ('drive', 'delete_file'): 'drive_delete',
    ('sheets', 'list_spreadsheets'): 'sheets_list',
    ('sheets', 'get_spreadsheet'): 'sheets_get',
    ('sheets', 'read_range'): 'sheets_read',
    ('sheets', 'get_sheet_data'): 'sheets_read',
    ('sheets', 'write_range'): 'sheets_write',
    ('sheets', 'append_rows'): 'sheets_append',
    ('docs', 'list_documents'): 'docs_list',
    ('docs', 'get_document'): 'docs_get',
    ('docs', 'get_document_text'): 'docs_get',
    ('docs', 'create_document'): 'docs_create',
    ('tasks', 'list_tasks'): 'tasks_list',
    ('tasks', 'list_task_lists'): 'tasks_list',
    ('tasks', 'get_task'): 'tasks_get',
    ('tasks', 'create_task'): 'tasks_add',
    ('tasks', 'complete_task'): 'tasks_complete',
    ('tasks', 'delete_task'): 'tasks_delete',
    ('meet', 'list_spaces'): 'meet_list',
    ('meet', 'get_space'): 'meet_get',
    ('meet', 'create_space'): 'meet_create',
    ('forms', 'list_forms'): 'forms_list',
    ('forms', 'get_form'): 'forms_get',
    ('forms', 'list_responses'): 'forms_responses',
    ('forms', 'create_form'): 'forms_create',
    ('chat', 'list_spaces'): 'chat_spaces',
    ('chat', 'get_space'): 'chat_spaces',
    ('chat', 'list_messages'): 'chat_messages',
    ('chat', 'send_message'): 'chat_send',
    ('people', 'list_contacts'): 'people_contacts',
    ('people', 'search_contacts'): 'people_search',
}


# ---------------------------------------------------------------------------
# Structured Intent Data Structure
# ---------------------------------------------------------------------------

@dataclass
class StructuredIntent:
    """Strict representation of interpreted user intent and tool selection."""
    intent: str
    service: str
    operation: str
    tool: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None
    entities: Dict[str, Any] = field(default_factory=dict)
    parameters: Dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False
    confidence: float = 1.0
    original_query: str = ""
    is_valid: bool = True
    error_message: Optional[str] = None

    def __post_init__(self):
        if not self.tool and (self.service, self.operation) in SERVICE_OP_TO_TOOL:
            self.tool = SERVICE_OP_TO_TOOL[(self.service, self.operation)]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'intent': self.intent,
            'service': self.service,
            'operation': self.operation,
            'tool': self.tool,
            'tools': self.tools,
            'entities': self.entities,
            'parameters': self.parameters,
            'requires_confirmation': self.requires_confirmation,
            'confidence': round(self.confidence, 2),
        }


# ---------------------------------------------------------------------------
# Strict Validation Engine
# ---------------------------------------------------------------------------

class IntentValidationError(Exception):
    """Raised when structured intent fails security or schema validation."""
    pass


def validate_structured_intent(raw: Dict[str, Any], original_query: str = "") -> StructuredIntent:
    """
    Validate every field of the Gemini or fallback intent response against allowlists.
    Rejects unknown services, unauthorized operations, shell command injection, etc.
    """
    if not isinstance(raw, dict):
        return StructuredIntent(
            intent='unknown',
            service='unknown',
            operation='unknown',
            confidence=0.0,
            original_query=original_query,
            is_valid=False,
            error_message="Invalid intent payload structure (expected dict)."
        )

    # Support tool field if given directly by Gemini
    tool = raw.get('tool')
    tools = raw.get('tools')

    service = str(raw.get('service', '')).strip().lower()
    operation = str(raw.get('operation', '')).strip().lower()
    intent = str(raw.get('intent', 'unknown')).strip().lower()

    # Translate tool name into service and operation if provided
    if tool and tool in TOOL_TO_SERVICE_OP:
        s, op = TOOL_TO_SERVICE_OP[tool]
        if not service or service == 'unknown':
            service = s
        if not operation or operation == 'unknown':
            operation = op
        if intent == 'unknown':
            intent = 'list' if 'list' in tool or 'search' in tool else ('get' if 'get' in tool or 'read' in tool else 'action')

    # Translate multi-tools
    if tools and isinstance(tools, list):
        if not service or service == 'unknown':
            service = 'composite'
        if not operation or operation == 'unknown':
            operation = 'multi_tool'
        intent = 'composite'

    entities = raw.get('entities', {})
    parameters = raw.get('parameters') or raw.get('arguments', {})
    try:
        confidence = float(raw.get('confidence', 0.8))
    except (ValueError, TypeError):
        confidence = 0.5

    # Check for prompt injection / shell execution attempts
    combined_check = f"{service} {operation} {intent} {parameters} {tool} {tools}"
    suspicious_patterns = [
        r'[;&|`$]', r'\bexec\b', r'\bsystem\b', r'\bsh\b', r'\bbash\b',
        r'\bcmd\b', r'\bpowershell\b', r'\brm\s+-rf\b', r'\bdel\s+/f\b',
        r'token\.json', r'credentials\.json', r'client_secret', r'refresh_token',
    ]
    import re
    for pat in suspicious_patterns:
        if re.search(pat, combined_check, re.IGNORECASE):
            logger.warning(f"Suspicious pattern detected in intent: {pat}")
            return StructuredIntent(
                intent='unknown',
                service='unknown',
                operation='unknown',
                confidence=0.0,
                original_query=original_query,
                is_valid=False,
                error_message="Security violation: intent contains disallowed patterns."
            )

    # If multi-tools specified, validate all of them
    if tools and isinstance(tools, list):
        for sub_tool in tools:
            st_name = sub_tool.get('tool')
            if st_name and st_name not in TOOL_TO_SERVICE_OP:
                return StructuredIntent(
                    intent=intent,
                    service=service,
                    operation=operation,
                    confidence=confidence,
                    original_query=original_query,
                    is_valid=False,
                    error_message=f"Tool '{st_name}' is not supported in Hermes."
                )
        return StructuredIntent(
            intent=intent,
            service='composite',
            operation='multi_tool',
            tool=None,
            tools=tools,
            entities=entities,
            parameters=parameters,
            requires_confirmation=False,
            confidence=confidence,
            original_query=original_query,
            is_valid=True,
        )

    # 1. Validate service
    if service not in ALLOWED_SERVICES and service != 'composite':
        return StructuredIntent(
            intent=intent,
            service=service,
            operation=operation,
            confidence=confidence,
            original_query=original_query,
            is_valid=False,
            error_message=f"Service '{service}' is not supported in Hermes."
        )

    # 2. Validate operation
    allowed_ops = ALLOWED_OPERATIONS.get(service, set())
    if service != 'composite' and operation not in allowed_ops:
        return StructuredIntent(
            intent=intent,
            service=service,
            operation=operation,
            confidence=confidence,
            original_query=original_query,
            is_valid=False,
            error_message=f"Operation '{operation}' is not supported for service '{service}'."
        )

    # 3. Sanitize and validate parameters
    safe_params: Dict[str, Any] = {}
    if isinstance(parameters, dict):
        for k, v in parameters.items():
            clean_k = str(k).strip().lower()
            if clean_k in ALLOWED_PARAMETER_KEYS:
                safe_params[clean_k] = v

    # 4. Sanitize entities
    safe_entities: Dict[str, Any] = {}
    if isinstance(entities, dict):
        for k, v in entities.items():
            clean_k = str(k).strip().lower()
            safe_entities[clean_k] = v

    # 5. Check if operation requires confirmation
    requires_conf = operation in WRITE_OPERATIONS or bool(raw.get('requires_confirmation', False))

    # 6. Check confidence
    if confidence < 0.4:
        return StructuredIntent(
            intent=intent,
            service=service,
            operation=operation,
            entities=safe_entities,
            parameters=safe_params,
            requires_confirmation=requires_conf,
            confidence=confidence,
            original_query=original_query,
            is_valid=False,
            error_message="Confidence is too low to safely execute the request."
        )

    return StructuredIntent(
        intent=intent,
        service=service,
        operation=operation,
        tool=tool,
        tools=tools,
        entities=safe_entities,
        parameters=safe_params,
        requires_confirmation=requires_conf,
        confidence=confidence,
        original_query=original_query,
        is_valid=True,
    )

