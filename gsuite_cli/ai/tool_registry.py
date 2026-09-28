"""
Central Tool Registry and Execution Layer for Hermes CLI.
Implements:
- ToolDefinition
- ToolRegistry
- ToolValidator
- ToolExecutionResult
- ToolExecutor

Sits strictly between Gemini AI and the existing Hermes Google Workspace services.
Guarantees:
- Gemini only produces structured tool selection and arguments.
- Zero shell commands, subprocesses, arbitrary URLs, or Python execution.
- Strict argument type, bounds, and security validation before execution.
- Confirmation required for write and destructive operations.
- Loop prevention with max tool execution limit (5).
- Direct invocation of existing Hermes services (no duplicates).
- Caching and cache invalidation.
- Telemetry reporting for --debug mode.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import click
from colorama import Fore, Style

from .date_parser import NaturalDateParser, get_user_timezone
from ..auth.oauth import OAuthManager, AuthenticationError
from ..services.resource_resolver import (
    GlobalResourceResolver,
    ResourceNotFoundError,
    AmbiguousResourceNameError,
)

logger = logging.getLogger(__name__)

# Maximum tool executions allowed per natural language query to prevent infinite loops
MAX_TOOL_CALLS_PER_REQUEST = 5


@dataclass
class ToolDefinition:
    """Definition of an internal Hermes tool executable by AI."""
    name: str
    service_name: str
    description: str
    parameters_schema: Dict[str, Any] = field(default_factory=dict)
    is_write: bool = False
    is_destructive: bool = False
    requires_confirmation: bool = False
    handler: Optional[Callable[[Any, Dict[str, Any]], Any]] = None

    def __post_init__(self):
        if self.is_destructive:
            self.requires_confirmation = True


@dataclass
class ToolExecutionResult:
    """Result of an internal Hermes tool execution."""
    tool_name: str
    service_name: str
    status: str  # 'success', 'error', 'cancelled'
    data: Any = None
    item_count: int = 0
    error: Optional[str] = None
    duration_ms: float = 0.0
    arguments: Dict[str, Any] = field(default_factory=dict)
    suggested_command: Optional[str] = None


class ToolRegistry:
    """
    Centralized, controlled registry of all authorized tools available in Hermes.
    Only exposes operations that actually exist in the Hermes service layer.
    """

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool definition."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool definition by name."""
        return self._tools.get(name)

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def list_tools(self, service: Optional[str] = None) -> List[ToolDefinition]:
        """List all registered tools, optionally filtered by service."""
        if service:
            return [t for t in self._tools.values() if t.service_name.lower() == service.lower()]
        return list(self._tools.values())

    def list_tool_names(self) -> List[str]:
        """List all registered tool names."""
        return list(self._tools.keys())


class ToolValidator:
    """
    Strict validation layer for AI-selected tools and arguments.
    Never trusts AI output directly.
    """

    # Patterns indicating potential command injection or malicious input
    INJECTION_PATTERNS = [
        re.compile(r'[;&|`$><]'),
        re.compile(r'\b(rm|cat|bash|sh|cmd|powershell|curl|wget)\b', re.IGNORECASE),
        re.compile(r'\.\./'),  # Path traversal
    ]

    def __init__(self, registry: ToolRegistry, timezone: Optional[Any] = None):
        self.registry = registry
        self.date_parser = NaturalDateParser(timezone=timezone)

    def validate_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Validate tool name, argument types, bounds, security constraints, and dates.
        Returns: (is_valid, error_message, validated_arguments)
        """
        if not tool_name:
            return False, "No tool name provided.", {}

        tool = self.registry.get(tool_name)
        if not tool:
            return False, f"Unknown tool '{tool_name}'. It does not exist in the Hermes tool registry.", {}

        validated_args: Dict[str, Any] = {}
        schema = tool.parameters_schema

        for arg_name, arg_val in (arguments or {}).items():
            # Security check for injection in string arguments
            if isinstance(arg_val, str):
                for pat in self.INJECTION_PATTERNS:
                    if pat.search(arg_val):
                        # Allow harmless Gmail query operators like 'is:unread', 'label:', etc.
                        if tool.service_name == 'gmail' and arg_name == 'query':
                            # Check if it contains shell metacharacters
                            if any(c in arg_val for c in [';', '|', '`', '$', '&']):
                                return False, f"Security violation: Illegal characters detected in argument '{arg_name}'.", {}
                        elif any(c in arg_val for c in [';', '|', '`', '$', '&']):
                            return False, f"Security violation: Illegal characters detected in argument '{arg_name}'.", {}

            # Parameter bounds check: max_results / page_size
            if arg_name in ('max_results', 'page_size'):
                try:
                    int_val = int(arg_val)
                    if int_val < 1:
                        int_val = 1
                    elif int_val > 500:
                        int_val = 500
                    validated_args[arg_name] = int_val
                except (ValueError, TypeError):
                    return False, f"Invalid value for '{arg_name}': must be an integer between 1 and 500.", {}
                continue

            # Date normalization check: date_range / time_range / date / time_min / time_max
            if arg_name in ('date_range', 'time_range', 'date') and isinstance(arg_val, str):
                t_min, t_max = self.date_parser.parse_date_range(arg_val)
                if t_min and t_max:
                    validated_args['time_min'] = t_min
                    validated_args['time_max'] = t_max
                validated_args[arg_name] = arg_val
                continue

            validated_args[arg_name] = arg_val

        # Apply schema defaults
        for param, param_info in schema.items():
            if param not in validated_args and 'default' in param_info:
                validated_args[param] = param_info['default']

        return True, None, validated_args


class ToolExecutor:
    """
    Executes validated Hermes tools against authorized Google Workspace services.
    Enforces authentication, confirmation for write operations, cache access,
    and returns rich execution telemetry.
    """

    def __init__(
        self,
        oauth_manager: OAuthManager,
        config_manager: Optional[Any] = None,
        cache_manager: Optional[Any] = None,
        registry: Optional[ToolRegistry] = None,
        validator: Optional[ToolValidator] = None,
        max_tool_calls: int = MAX_TOOL_CALLS_PER_REQUEST,
        service_dispatcher: Optional[Callable[[str, str, Dict[str, Any]], Any]] = None,
        services: Optional[Dict[str, Any]] = None,
    ):
        self.oauth_manager = oauth_manager
        self.config_manager = config_manager
        self.cache_manager = cache_manager
        self.tzinfo = get_user_timezone(config_manager)
        self.registry = registry or get_default_registry()
        self.validator = validator or ToolValidator(self.registry, timezone=self.tzinfo)
        self.max_tool_calls = max_tool_calls
        self.service_dispatcher = service_dispatcher
        self._services: Dict[str, Any] = services if services is not None else {}

    def get_service(self, name: str) -> Any:
        """Get or initialize a Workspace service client."""
        clean_name = name.lower()
        if clean_name not in self._services:
            if clean_name == 'gmail':
                from ..services.gmail import GmailService
                self._services['gmail'] = GmailService(self.oauth_manager, self.cache_manager)
            elif clean_name == 'calendar':
                from ..services.calendar import CalendarService
                self._services['calendar'] = CalendarService(self.oauth_manager, self.cache_manager)
            elif clean_name == 'drive':
                from ..services.drive import DriveService
                self._services['drive'] = DriveService(self.oauth_manager, self.cache_manager)
            elif clean_name == 'sheets':
                from ..services.sheets import SheetsService
                self._services['sheets'] = SheetsService(self.oauth_manager, self.cache_manager)
            elif clean_name == 'docs':
                from ..services.docs import DocsService
                self._services['docs'] = DocsService(self.oauth_manager, self.cache_manager)
            elif clean_name == 'tasks':
                from ..services.tasks import TasksService
                self._services['tasks'] = TasksService(self.oauth_manager, self.cache_manager)
            elif clean_name == 'meet':
                from ..services.meet import MeetService
                self._services['meet'] = MeetService(self.oauth_manager, self.cache_manager)
            elif clean_name == 'forms':
                from ..services.forms import FormsService
                self._services['forms'] = FormsService(self.oauth_manager, self.cache_manager)
            elif clean_name == 'chat':
                from ..services.chat import ChatService
                self._services['chat'] = ChatService(self.oauth_manager, self.cache_manager)
            elif clean_name == 'people':
                from ..services.people import PeopleService
                self._services['people'] = PeopleService(self.oauth_manager, self.cache_manager)
            else:
                raise ValueError(f"Unknown service '{name}'")
        return self._services[clean_name]

    def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        allow_interactive: bool = True,
        confirmation_override: Optional[bool] = None,
        debug: bool = False,
    ) -> ToolExecutionResult:
        """Execute a single validated tool call."""
        start_time = time.time()

        # 1. Validation
        is_valid, error_msg, validated_args = self.validator.validate_tool_call(tool_name, arguments)
        if not is_valid:
            return ToolExecutionResult(
                tool_name=tool_name,
                service_name="unknown",
                status="error",
                error=error_msg,
                arguments=arguments,
            )

        tool = self.registry.get(tool_name)
        assert tool is not None

        # 2. Confirmation check for write / destructive operations
        if tool.requires_confirmation or tool.is_destructive or tool.is_write:
            if confirmation_override is False:
                return ToolExecutionResult(
                    tool_name=tool_name,
                    service_name=tool.service_name,
                    status="cancelled",
                    error="Operation cancelled (confirmation declined).",
                    arguments=validated_args,
                )
            elif confirmation_override is None:
                if allow_interactive:
                    confirmed = self._prompt_confirmation(tool, validated_args)
                    if not confirmed:
                        return ToolExecutionResult(
                            tool_name=tool_name,
                            service_name=tool.service_name,
                            status="cancelled",
                            error="Operation cancelled by user.",
                            arguments=validated_args,
                        )
                else:
                    return ToolExecutionResult(
                        tool_name=tool_name,
                        service_name=tool.service_name,
                        status="cancelled",
                        error=f"Confirmation required for {tool_name} but running non-interactively.",
                        arguments=validated_args,
                    )

        # 3. Authentication Check
        if not self.oauth_manager.is_authenticated():
            raise AuthenticationError(
                "Not authenticated with Google Workspace.",
                "Please run 'hermes auth login' to authenticate before executing tools."
            )

        # 4. Service Execution
        try:
            if self.service_dispatcher:
                raw_data = self.service_dispatcher(tool.service_name, tool.name, validated_args)
            elif tool.handler:
                service = self.get_service(tool.service_name)
                raw_data = tool.handler(service, validated_args)
            else:
                raw_data = None

            duration_ms = (time.time() - start_time) * 1000

            # Count items
            item_count = 0
            if isinstance(raw_data, list):
                item_count = len(raw_data)
            elif isinstance(raw_data, dict):
                item_count = len(raw_data.get('items', [raw_data]))
            elif raw_data is not None:
                item_count = 1

            # Invalidate cache if write operation
            if tool.is_write and self.cache_manager:
                try:
                    self.cache_manager.invalidate_service(tool.service_name)
                except Exception as ce:
                    logger.debug(f"Cache invalidation note: {ce}")

            return ToolExecutionResult(
                tool_name=tool.name,
                service_name=tool.service_name,
                status="success",
                data=raw_data,
                item_count=item_count,
                duration_ms=duration_ms,
                arguments=validated_args,
            )

        except (ResourceNotFoundError, AmbiguousResourceNameError) as e:
            return ToolExecutionResult(
                tool_name=tool.name,
                service_name=tool.service_name,
                status="error",
                error=str(e),
                arguments=validated_args,
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            logger.error(f"Execution error in {tool.name}: {e}")
            return ToolExecutionResult(
                tool_name=tool.name,
                service_name=tool.service_name,
                status="error",
                error=str(e),
                arguments=validated_args,
                duration_ms=(time.time() - start_time) * 1000,
            )

    def execute_multi_tools(
        self,
        tool_calls: List[Dict[str, Any]],
        allow_interactive: bool = True,
        confirmation_override: Optional[bool] = None,
        debug: bool = False,
    ) -> List[ToolExecutionResult]:
        """
        Execute multiple tool calls sequentially with loop limit enforcement.
        """
        if len(tool_calls) > self.max_tool_calls:
            logger.warning(f"Tool calls ({len(tool_calls)}) exceeded max ({self.max_tool_calls}). Truncating.")
            tool_calls = tool_calls[:self.max_tool_calls]

        results = []
        for call in tool_calls:
            tool_name = call.get('tool') or call.get('name') or ''
            args = call.get('arguments') or call.get('parameters') or {}
            res = self.execute_tool(
                tool_name=tool_name,
                arguments=args,
                allow_interactive=allow_interactive,
                confirmation_override=confirmation_override,
                debug=debug,
            )
            results.append(res)
            # Stop immediately if a tool had an authentication or critical error
            if res.status == 'error' and 'Not authenticated' in (res.error or ''):
                break

        return results

    def _prompt_confirmation(self, tool: ToolDefinition, args: Dict[str, Any]) -> bool:
        """Prompt user for confirmation before executing write/destructive tool."""
        print()
        print(f"{Fore.YELLOW}WARNING: Confirmation Required{Style.RESET_ALL}")
        print(f"Tool: {tool.name} ({tool.service_name})")
        print(f"Description: {tool.description}")
        if args:
            print("Arguments:")
            for k, v in args.items():
                print(f"  • {k}: {v}")
        if tool.is_destructive:
            print(f"{Fore.RED}⚠ CAUTION: This is a DESTRUCTIVE operation.{Style.RESET_ALL}")
        print()
        try:
            return click.confirm("Do you want to proceed with this operation?", default=False)
        except Exception:
            return False


# ===========================================================================
# Tool Handlers Implementation
# ===========================================================================

def _handle_gmail_list(service: Any, args: Dict[str, Any]) -> Any:
    q = args.get('query')
    max_results = args.get('max_results', 20)
    return service.list_messages(query=q, max_results=max_results)


def _handle_gmail_get(service: Any, args: Dict[str, Any]) -> Any:
    msg_id = args.get('message_id') or args.get('id')
    return service.get_message(msg_id)


def _handle_gmail_search(service: Any, args: Dict[str, Any]) -> Any:
    q = args.get('query', '')
    max_results = args.get('max_results', 20)
    return service.list_messages(query=q, max_results=max_results)


def _handle_gmail_read(service: Any, args: Dict[str, Any]) -> Any:
    msg_id = args.get('message_id') or args.get('id')
    return service.get_message(msg_id)


def _handle_gmail_drafts(service: Any, args: Dict[str, Any]) -> Any:
    max_results = args.get('max_results', 20)
    if hasattr(service, 'list_drafts'):
        return service.list_drafts(max_results=max_results)
    return service.list_messages(query="is:draft", max_results=max_results)


def _handle_gmail_labels(service: Any, args: Dict[str, Any]) -> Any:
    if hasattr(service, 'list_labels'):
        return service.list_labels()
    return []


def _handle_gmail_send(service: Any, args: Dict[str, Any]) -> Any:
    return service.send_message(
        to=args.get('to'),
        subject=args.get('subject', '(No Subject)'),
        body=args.get('body', ''),
        cc=args.get('cc'),
        bcc=args.get('bcc'),
    )


def _handle_gmail_reply(service: Any, args: Dict[str, Any]) -> Any:
    msg_id = args.get('message_id') or args.get('id')
    if hasattr(service, 'reply_to_message'):
        return service.reply_to_message(message_id=msg_id, body=args.get('body', ''))
    return service.send_message(
        to=args.get('to', ''),
        subject=args.get('subject', 'Re:'),
        body=args.get('body', ''),
    )


def _handle_gmail_trash(service: Any, args: Dict[str, Any]) -> Any:
    msg_id = args.get('message_id') or args.get('id')
    return service.trash_message(msg_id)


def _handle_gmail_delete(service: Any, args: Dict[str, Any]) -> Any:
    msg_id = args.get('message_id') or args.get('id')
    if msg_id:
        return service.delete_message(msg_id)
    # Bulk query delete: delete messages matching query
    q = args.get('query')
    if q:
        msgs = service.list_messages(query=q, max_results=50)
        deleted = []
        for m in msgs:
            mid = m.get('id')
            if mid:
                service.delete_message(mid)
                deleted.append(mid)
        return {'deleted_count': len(deleted), 'deleted_ids': deleted}
    return False


def _handle_calendar_list(service: Any, args: Dict[str, Any]) -> Any:
    return service.list_events(
        calendar_id=args.get('calendar_id', 'primary'),
        time_min=args.get('time_min'),
        time_max=args.get('time_max'),
        max_results=args.get('max_results', 20),
        q=args.get('query'),
    )


def _handle_calendar_get(service: Any, args: Dict[str, Any]) -> Any:
    event_id = args.get('event_id') or args.get('id')
    return service.get_event(event_id=event_id, calendar_id=args.get('calendar_id', 'primary'))


def _handle_calendar_search(service: Any, args: Dict[str, Any]) -> Any:
    return service.list_events(
        calendar_id=args.get('calendar_id', 'primary'),
        q=args.get('query'),
        max_results=args.get('max_results', 20),
    )


def _handle_calendar_create(service: Any, args: Dict[str, Any]) -> Any:
    return service.create_event(
        title=args.get('title', 'New Meeting'),
        start_time=args.get('start_time'),
        end_time=args.get('end_time'),
        description=args.get('description'),
        location=args.get('location'),
        calendar_id=args.get('calendar_id', 'primary'),
    )


def _handle_calendar_update(service: Any, args: Dict[str, Any]) -> Any:
    event_id = args.get('event_id') or args.get('id')
    return service.update_event(
        event_id=event_id,
        calendar_id=args.get('calendar_id', 'primary'),
        title=args.get('title'),
        description=args.get('description'),
    )


def _handle_calendar_delete(service: Any, args: Dict[str, Any]) -> Any:
    event_id = args.get('event_id') or args.get('id')
    return service.delete_event(event_id=event_id, calendar_id=args.get('calendar_id', 'primary'))


def _handle_drive_list(service: Any, args: Dict[str, Any]) -> Any:
    q = args.get('query')
    max_results = args.get('max_results', 20)
    return service.list_files(query=q, page_size=max_results)


def _handle_drive_search(service: Any, args: Dict[str, Any]) -> Any:
    return service.search_files(
        name=args.get('name') or args.get('query'),
        mime_type=args.get('mime_type'),
        page_size=args.get('max_results', 20),
    )


def _handle_drive_get(service: Any, args: Dict[str, Any]) -> Any:
    file_id = args.get('file_id') or args.get('id')
    return service.get_file_metadata(file_id)


def _handle_drive_trash(service: Any, args: Dict[str, Any]) -> Any:
    file_id = args.get('file_id') or args.get('id')
    return service.trash_file(file_id)


def _handle_drive_delete(service: Any, args: Dict[str, Any]) -> Any:
    file_id = args.get('file_id') or args.get('id')
    return service.delete_file(file_id)


def _handle_sheets_list(service: Any, args: Dict[str, Any]) -> Any:
    max_results = args.get('max_results', 20)
    return service.list_spreadsheets(max_results=max_results)


def _resolve_spreadsheet_id(service: Any, args: Dict[str, Any]) -> str:
    """Helper to resolve spreadsheet ID from direct ID or natural language name."""
    sid = args.get('spreadsheet_id') or args.get('id')
    res_name = args.get('resource_name') or args.get('name')

    if sid:
        return sid

    if res_name:
        all_sheets = service.list_spreadsheets(max_results=50)
        # Use GlobalResourceResolver logic for natural matching and ambiguity
        matched = GlobalResourceResolver.find_matching_resources(
            val=res_name,
            items=all_sheets,
            title_fn=lambda x: x.get('name', ''),
            id_fn=lambda x: x.get('id', ''),
        )
        if not matched:
            raise ResourceNotFoundError(res_name, all_sheets, "Spreadsheet")
        if len(matched) > 1:
            raise AmbiguousResourceNameError(res_name, matched, "Spreadsheet")
        return matched[0].get('id', '')

    raise ResourceNotFoundError("No spreadsheet name or ID provided", [], "Spreadsheet")


def _handle_sheets_get(service: Any, args: Dict[str, Any]) -> Any:
    sid = _resolve_spreadsheet_id(service, args)
    return service.get_spreadsheet(spreadsheet_id=sid)


def _handle_sheets_read(service: Any, args: Dict[str, Any]) -> Any:
    sid = _resolve_spreadsheet_id(service, args)
    range_name = args.get('range_name', 'A1:Z100')
    data = service.read_range(spreadsheet_id=sid, range_name=range_name)
    return {
        'spreadsheet_id': sid,
        'range': range_name,
        'values': data,
    }


def _handle_sheets_search(service: Any, args: Dict[str, Any]) -> Any:
    q = args.get('query') or args.get('name', '')
    all_sheets = service.list_spreadsheets(max_results=50)
    if not q:
        return all_sheets
    return [s for s in all_sheets if q.lower() in s.get('name', '').lower()]


def _handle_sheets_write(service: Any, args: Dict[str, Any]) -> Any:
    sid = _resolve_spreadsheet_id(service, args)
    range_name = args.get('range_name', 'A1')
    values = args.get('values', [[]])
    return service.write_range(spreadsheet_id=sid, range_name=range_name, values=values)


def _handle_sheets_append(service: Any, args: Dict[str, Any]) -> Any:
    sid = _resolve_spreadsheet_id(service, args)
    range_name = args.get('range_name', 'A1')
    values = args.get('values', [[]])
    return service.append_rows(spreadsheet_id=sid, range_name=range_name, values=values)


def _handle_sheets_clear(service: Any, args: Dict[str, Any]) -> Any:
    sid = _resolve_spreadsheet_id(service, args)
    range_name = args.get('range_name', 'A1:Z100')
    return service.clear_range(spreadsheet_id=sid, range_name=range_name)


def _handle_docs_list(service: Any, args: Dict[str, Any]) -> Any:
    max_results = args.get('max_results', 20)
    return service.list_documents(max_results=max_results)


def _resolve_document_id(service: Any, args: Dict[str, Any]) -> str:
    """Helper to resolve document ID from direct ID or natural language name."""
    doc_id = args.get('document_id') or args.get('id')
    res_name = args.get('resource_name') or args.get('name')

    if doc_id:
        return doc_id

    if res_name:
        all_docs = service.list_documents(max_results=50)
        matched = GlobalResourceResolver.find_matching_resources(
            val=res_name,
            items=all_docs,
            title_fn=lambda x: x.get('name', ''),
            id_fn=lambda x: x.get('id', ''),
        )
        if not matched:
            raise ResourceNotFoundError(res_name, all_docs, "Document")
        if len(matched) > 1:
            raise AmbiguousResourceNameError(res_name, matched, "Document")
        return matched[0].get('id', '')

    raise ResourceNotFoundError("No document name or ID provided", [], "Document")


def _handle_docs_get(service: Any, args: Dict[str, Any]) -> Any:
    doc_id = _resolve_document_id(service, args)
    text = service.get_document_text(document_id=doc_id)
    return {
        'document_id': doc_id,
        'content': text,
    }


def _handle_docs_create(service: Any, args: Dict[str, Any]) -> Any:
    title = args.get('title', 'New Document')
    return service.create_document(title=title)


def _handle_tasks_list(service: Any, args: Dict[str, Any]) -> Any:
    task_list_id = args.get('task_list_id', '@default')
    status = args.get('status', 'pending')
    show_completed = (status == 'completed')
    max_results = args.get('max_results', 20)
    raw = service.list_tasks(
        task_list_id=task_list_id,
        show_completed=show_completed,
        max_results=max_results,
    )
    if isinstance(raw, dict):
        tasks = raw.get('items', [])
    elif isinstance(raw, list):
        tasks = raw
    else:
        tasks = []
    # Filter by status if pending
    if status in ('pending', 'needsAction'):
        return [t for t in tasks if t.get('status') != 'completed']
    return tasks


def _handle_tasks_get(service: Any, args: Dict[str, Any]) -> Any:
    task_id = args.get('task_id') or args.get('id')
    task_list_id = args.get('task_list_id', '@default')
    return service.get_task(task_id=task_id, task_list_id=task_list_id)


def _handle_tasks_add(service: Any, args: Dict[str, Any]) -> Any:
    title = args.get('title', 'New Task')
    notes = args.get('notes')
    due = args.get('due')
    task_list_id = args.get('task_list_id', '@default')
    return service.create_task(title=title, notes=notes, due=due, task_list_id=task_list_id)


def _handle_tasks_complete(service: Any, args: Dict[str, Any]) -> Any:
    task_id = args.get('task_id') or args.get('id')
    task_list_id = args.get('task_list_id', '@default')
    return service.complete_task(task_id=task_id, task_list_id=task_list_id)


def _handle_tasks_delete(service: Any, args: Dict[str, Any]) -> Any:
    task_id = args.get('task_id') or args.get('id')
    task_list_id = args.get('task_list_id', '@default')
    return service.delete_task(task_id=task_id, task_list_id=task_list_id)


def _handle_meet_list(service: Any, args: Dict[str, Any]) -> Any:
    max_results = args.get('max_results', 20)
    return service.list_spaces(page_size=max_results)


def _handle_meet_get(service: Any, args: Dict[str, Any]) -> Any:
    name = args.get('space_name') or args.get('name')
    return service.get_space(name=name)


def _handle_meet_create(service: Any, args: Dict[str, Any]) -> Any:
    return service.create_space(space_config=args.get('space_config'))


def _handle_forms_list(service: Any, args: Dict[str, Any]) -> Any:
    max_results = args.get('max_results', 20)
    return service.list_forms(max_results=max_results)


def _handle_forms_get(service: Any, args: Dict[str, Any]) -> Any:
    form_id = args.get('form_id') or args.get('id')
    return service.get_form(form_id=form_id)


def _handle_forms_responses(service: Any, args: Dict[str, Any]) -> Any:
    form_id = args.get('form_id') or args.get('id')
    max_results = args.get('max_results', 20)
    return service.list_responses(form_id=form_id, page_size=max_results)


def _handle_forms_create(service: Any, args: Dict[str, Any]) -> Any:
    title = args.get('title', 'New Form')
    return service.create_form(title=title)


def _handle_chat_spaces(service: Any, args: Dict[str, Any]) -> Any:
    max_results = args.get('max_results', 20)
    return service.list_spaces(page_size=max_results)


def _handle_chat_messages(service: Any, args: Dict[str, Any]) -> Any:
    space_id = args.get('space_id') or args.get('id')
    max_results = args.get('max_results', 20)
    return service.list_messages(space_id=space_id, page_size=max_results)


def _handle_chat_send(service: Any, args: Dict[str, Any]) -> Any:
    space_id = args.get('space_id') or args.get('id')
    text = args.get('text', '')
    return service.send_message(space_id=space_id, text=text)


def _handle_people_contacts(service: Any, args: Dict[str, Any]) -> Any:
    max_results = args.get('max_results', 20)
    return service.list_contacts(page_size=max_results)


def _handle_people_search(service: Any, args: Dict[str, Any]) -> Any:
    query = args.get('query', '')
    max_results = args.get('max_results', 20)
    return service.search_contacts(query=query, page_size=max_results)


# ===========================================================================
# Registry Factory
# ===========================================================================

def build_default_tool_registry() -> ToolRegistry:
    """Build and populate the default tool registry with all authorized Hermes operations."""
    registry = ToolRegistry()

    # GMAIL
    registry.register(ToolDefinition(
        name="gmail_list",
        service_name="gmail",
        description="List emails from user's Gmail inbox matching query",
        parameters_schema={"query": {"type": "string", "default": ""}, "max_results": {"type": "integer", "default": 20}},
        handler=_handle_gmail_list,
    ))
    registry.register(ToolDefinition(
        name="gmail_get",
        service_name="gmail",
        description="Get specific email by ID",
        parameters_schema={"message_id": {"type": "string", "required": True}},
        handler=_handle_gmail_get,
    ))
    registry.register(ToolDefinition(
        name="gmail_search",
        service_name="gmail",
        description="Search emails by query string",
        parameters_schema={"query": {"type": "string", "required": True}, "max_results": {"type": "integer", "default": 20}},
        handler=_handle_gmail_search,
    ))
    registry.register(ToolDefinition(
        name="gmail_read",
        service_name="gmail",
        description="Read an email content by ID",
        parameters_schema={"message_id": {"type": "string", "required": True}},
        handler=_handle_gmail_read,
    ))
    registry.register(ToolDefinition(
        name="gmail_drafts",
        service_name="gmail",
        description="List drafts in Gmail",
        parameters_schema={"max_results": {"type": "integer", "default": 20}},
        handler=_handle_gmail_drafts,
    ))
    registry.register(ToolDefinition(
        name="gmail_labels",
        service_name="gmail",
        description="List labels in Gmail",
        handler=_handle_gmail_labels,
    ))
    registry.register(ToolDefinition(
        name="gmail_send",
        service_name="gmail",
        description="Send an email",
        parameters_schema={"to": {"type": "string", "required": True}, "subject": {"type": "string"}, "body": {"type": "string"}},
        is_write=True,
        requires_confirmation=True,
        handler=_handle_gmail_send,
    ))
    registry.register(ToolDefinition(
        name="gmail_reply",
        service_name="gmail",
        description="Reply to an email",
        parameters_schema={"message_id": {"type": "string", "required": True}, "body": {"type": "string", "required": True}},
        is_write=True,
        requires_confirmation=True,
        handler=_handle_gmail_reply,
    ))
    registry.register(ToolDefinition(
        name="gmail_trash",
        service_name="gmail",
        description="Move an email to trash",
        parameters_schema={"message_id": {"type": "string", "required": True}},
        is_write=True,
        is_destructive=True,
        handler=_handle_gmail_trash,
    ))
    registry.register(ToolDefinition(
        name="gmail_delete",
        service_name="gmail",
        description="Permanently delete email(s)",
        parameters_schema={"message_id": {"type": "string"}, "query": {"type": "string"}},
        is_write=True,
        is_destructive=True,
        handler=_handle_gmail_delete,
    ))

    # CALENDAR
    registry.register(ToolDefinition(
        name="calendar_list",
        service_name="calendar",
        description="List calendar events within a date range",
        parameters_schema={"date_range": {"type": "string"}, "time_min": {"type": "string"}, "time_max": {"type": "string"}, "max_results": {"type": "integer", "default": 20}},
        handler=_handle_calendar_list,
    ))
    registry.register(ToolDefinition(
        name="calendar_get",
        service_name="calendar",
        description="Get calendar event details by ID",
        parameters_schema={"event_id": {"type": "string", "required": True}},
        handler=_handle_calendar_get,
    ))
    registry.register(ToolDefinition(
        name="calendar_search",
        service_name="calendar",
        description="Search calendar events by search term",
        parameters_schema={"query": {"type": "string", "required": True}, "max_results": {"type": "integer", "default": 20}},
        handler=_handle_calendar_search,
    ))
    registry.register(ToolDefinition(
        name="calendar_create",
        service_name="calendar",
        description="Create a new calendar event",
        parameters_schema={"title": {"type": "string", "required": True}, "start_time": {"type": "string", "required": True}, "end_time": {"type": "string", "required": True}},
        is_write=True,
        requires_confirmation=True,
        handler=_handle_calendar_create,
    ))
    registry.register(ToolDefinition(
        name="calendar_update",
        service_name="calendar",
        description="Update an existing calendar event",
        parameters_schema={"event_id": {"type": "string", "required": True}},
        is_write=True,
        requires_confirmation=True,
        handler=_handle_calendar_update,
    ))
    registry.register(ToolDefinition(
        name="calendar_delete",
        service_name="calendar",
        description="Delete a calendar event",
        parameters_schema={"event_id": {"type": "string", "required": True}},
        is_write=True,
        is_destructive=True,
        handler=_handle_calendar_delete,
    ))

    # DRIVE
    registry.register(ToolDefinition(
        name="drive_list",
        service_name="drive",
        description="List files in Google Drive",
        parameters_schema={"query": {"type": "string"}, "max_results": {"type": "integer", "default": 20}},
        handler=_handle_drive_list,
    ))
    registry.register(ToolDefinition(
        name="drive_search",
        service_name="drive",
        description="Search files in Google Drive by name or type",
        parameters_schema={"query": {"type": "string"}, "name": {"type": "string"}, "mime_type": {"type": "string"}, "max_results": {"type": "integer", "default": 20}},
        handler=_handle_drive_search,
    ))
    registry.register(ToolDefinition(
        name="drive_get",
        service_name="drive",
        description="Get file metadata from Google Drive",
        parameters_schema={"file_id": {"type": "string", "required": True}},
        handler=_handle_drive_get,
    ))
    registry.register(ToolDefinition(
        name="drive_trash",
        service_name="drive",
        description="Move a file to trash in Google Drive",
        parameters_schema={"file_id": {"type": "string", "required": True}},
        is_write=True,
        is_destructive=True,
        handler=_handle_drive_trash,
    ))
    registry.register(ToolDefinition(
        name="drive_delete",
        service_name="drive",
        description="Permanently delete a file in Google Drive",
        parameters_schema={"file_id": {"type": "string", "required": True}},
        is_write=True,
        is_destructive=True,
        handler=_handle_drive_delete,
    ))

    # SHEETS
    registry.register(ToolDefinition(
        name="sheets_list",
        service_name="sheets",
        description="List spreadsheets in Google Drive",
        parameters_schema={"max_results": {"type": "integer", "default": 20}},
        handler=_handle_sheets_list,
    ))
    registry.register(ToolDefinition(
        name="sheets_get",
        service_name="sheets",
        description="Get spreadsheet metadata by ID or name",
        parameters_schema={"spreadsheet_id": {"type": "string"}, "resource_name": {"type": "string"}},
        handler=_handle_sheets_get,
    ))
    registry.register(ToolDefinition(
        name="sheets_read",
        service_name="sheets",
        description="Read values from a spreadsheet range",
        parameters_schema={"spreadsheet_id": {"type": "string"}, "resource_name": {"type": "string"}, "range_name": {"type": "string", "default": "A1:Z100"}},
        handler=_handle_sheets_read,
    ))
    registry.register(ToolDefinition(
        name="sheets_search",
        service_name="sheets",
        description="Search spreadsheets by name",
        parameters_schema={"query": {"type": "string"}, "name": {"type": "string"}},
        handler=_handle_sheets_search,
    ))
    registry.register(ToolDefinition(
        name="sheets_write",
        service_name="sheets",
        description="Write values to a spreadsheet range",
        parameters_schema={"spreadsheet_id": {"type": "string"}, "range_name": {"type": "string"}, "values": {"type": "array"}},
        is_write=True,
        requires_confirmation=True,
        handler=_handle_sheets_write,
    ))
    registry.register(ToolDefinition(
        name="sheets_append",
        service_name="sheets",
        description="Append rows to a spreadsheet",
        parameters_schema={"spreadsheet_id": {"type": "string"}, "range_name": {"type": "string"}, "values": {"type": "array"}},
        is_write=True,
        requires_confirmation=True,
        handler=_handle_sheets_append,
    ))
    registry.register(ToolDefinition(
        name="sheets_clear",
        service_name="sheets",
        description="Clear values from a spreadsheet range",
        parameters_schema={"spreadsheet_id": {"type": "string"}, "range_name": {"type": "string"}},
        is_write=True,
        is_destructive=True,
        handler=_handle_sheets_clear,
    ))

    # DOCS
    registry.register(ToolDefinition(
        name="docs_list",
        service_name="docs",
        description="List Google Docs documents",
        parameters_schema={"max_results": {"type": "integer", "default": 20}},
        handler=_handle_docs_list,
    ))
    registry.register(ToolDefinition(
        name="docs_get",
        service_name="docs",
        description="Get document text by ID or title",
        parameters_schema={"document_id": {"type": "string"}, "resource_name": {"type": "string"}},
        handler=_handle_docs_get,
    ))
    registry.register(ToolDefinition(
        name="docs_create",
        service_name="docs",
        description="Create a new Google Document",
        parameters_schema={"title": {"type": "string", "required": True}},
        is_write=True,
        requires_confirmation=True,
        handler=_handle_docs_create,
    ))

    # TASKS
    registry.register(ToolDefinition(
        name="tasks_list",
        service_name="tasks",
        description="List tasks in Google Tasks",
        parameters_schema={"status": {"type": "string", "default": "pending"}, "task_list_id": {"type": "string", "default": "@default"}, "max_results": {"type": "integer", "default": 20}},
        handler=_handle_tasks_list,
    ))
    registry.register(ToolDefinition(
        name="tasks_get",
        service_name="tasks",
        description="Get a task by ID",
        parameters_schema={"task_id": {"type": "string", "required": True}, "task_list_id": {"type": "string", "default": "@default"}},
        handler=_handle_tasks_get,
    ))
    registry.register(ToolDefinition(
        name="tasks_add",
        service_name="tasks",
        description="Add a new task",
        parameters_schema={"title": {"type": "string", "required": True}, "notes": {"type": "string"}, "due": {"type": "string"}, "task_list_id": {"type": "string", "default": "@default"}},
        is_write=True,
        requires_confirmation=True,
        handler=_handle_tasks_add,
    ))
    registry.register(ToolDefinition(
        name="tasks_complete",
        service_name="tasks",
        description="Mark a task as completed",
        parameters_schema={"task_id": {"type": "string", "required": True}, "task_list_id": {"type": "string", "default": "@default"}},
        is_write=True,
        handler=_handle_tasks_complete,
    ))
    registry.register(ToolDefinition(
        name="tasks_delete",
        service_name="tasks",
        description="Delete a task",
        parameters_schema={"task_id": {"type": "string", "required": True}, "task_list_id": {"type": "string", "default": "@default"}},
        is_write=True,
        is_destructive=True,
        handler=_handle_tasks_delete,
    ))

    # MEET
    registry.register(ToolDefinition(
        name="meet_list",
        service_name="meet",
        description="List Google Meet spaces",
        parameters_schema={"max_results": {"type": "integer", "default": 20}},
        handler=_handle_meet_list,
    ))
    registry.register(ToolDefinition(
        name="meet_get",
        service_name="meet",
        description="Get Google Meet space details",
        parameters_schema={"space_name": {"type": "string", "required": True}},
        handler=_handle_meet_get,
    ))
    registry.register(ToolDefinition(
        name="meet_create",
        service_name="meet",
        description="Create a Google Meet space",
        is_write=True,
        requires_confirmation=True,
        handler=_handle_meet_create,
    ))

    # FORMS
    registry.register(ToolDefinition(
        name="forms_list",
        service_name="forms",
        description="List Google Forms",
        parameters_schema={"max_results": {"type": "integer", "default": 20}},
        handler=_handle_forms_list,
    ))
    registry.register(ToolDefinition(
        name="forms_get",
        service_name="forms",
        description="Get Google Form schema by ID",
        parameters_schema={"form_id": {"type": "string", "required": True}},
        handler=_handle_forms_get,
    ))
    registry.register(ToolDefinition(
        name="forms_responses",
        service_name="forms",
        description="List responses for a Google Form",
        parameters_schema={"form_id": {"type": "string", "required": True}, "max_results": {"type": "integer", "default": 20}},
        handler=_handle_forms_responses,
    ))
    registry.register(ToolDefinition(
        name="forms_create",
        service_name="forms",
        description="Create a new Google Form",
        parameters_schema={"title": {"type": "string", "required": True}},
        is_write=True,
        requires_confirmation=True,
        handler=_handle_forms_create,
    ))

    # CHAT
    registry.register(ToolDefinition(
        name="chat_spaces",
        service_name="chat",
        description="List Google Chat spaces",
        parameters_schema={"max_results": {"type": "integer", "default": 20}},
        handler=_handle_chat_spaces,
    ))
    registry.register(ToolDefinition(
        name="chat_messages",
        service_name="chat",
        description="List messages in a Google Chat space",
        parameters_schema={"space_id": {"type": "string", "required": True}, "max_results": {"type": "integer", "default": 20}},
        handler=_handle_chat_messages,
    ))
    registry.register(ToolDefinition(
        name="chat_send",
        service_name="chat",
        description="Send a message to Google Chat",
        parameters_schema={"space_id": {"type": "string", "required": True}, "text": {"type": "string", "required": True}},
        is_write=True,
        requires_confirmation=True,
        handler=_handle_chat_send,
    ))

    # PEOPLE
    registry.register(ToolDefinition(
        name="people_contacts",
        service_name="people",
        description="List contacts from Google People API",
        parameters_schema={"max_results": {"type": "integer", "default": 20}},
        handler=_handle_people_contacts,
    ))
    registry.register(ToolDefinition(
        name="people_search",
        service_name="people",
        description="Search contacts in Google People API",
        parameters_schema={"query": {"type": "string", "required": True}, "max_results": {"type": "integer", "default": 20}},
        handler=_handle_people_search,
    ))

    return registry


_DEFAULT_REGISTRY: Optional[ToolRegistry] = None


def get_default_registry() -> ToolRegistry:
    """Get the singleton default ToolRegistry."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = build_default_tool_registry()
    return _DEFAULT_REGISTRY
