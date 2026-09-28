"""
Command Validator and AI/Local Suggestion Generator for Hermes CLI.
Implements Step 1 of the required workflow:
- Input parsing and structural validation
- Interception of validation errors before authentication
- Generation of AI or deterministic local command suggestions
- Formatted output:
    Error: Unknown command "gmaill".

    Did you mean:
        hermes gmail list
"""

import os
import sys
import difflib
import logging
from typing import List, Optional, Dict

import click
from colorama import Fore, Style

from .formatters import print_error, print_info
from ..config.manager import ConfigManager
from ..ai.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# Common synonyms and typos for Hermes commands
SYNONYMS: Dict[str, str] = {
    'gmaill': 'gmail',
    'mail': 'gmail',
    'email': 'gmail',
    'emails': 'gmail',
    'inbox': 'gmail list',
    'cal': 'calendar',
    'calender': 'calendar',
    'event': 'calendar',
    'events': 'calendar',
    'doc': 'docs',
    'document': 'docs',
    'documents': 'docs',
    'sheet': 'sheets',
    'spreadsheet': 'sheets',
    'spreadsheets': 'sheets',
    'task': 'tasks',
    'todo': 'tasks',
    'todos': 'tasks',
    'meeting': 'meet',
    'meetings': 'meet',
    'file': 'drive',
    'files': 'drive',
    'login': 'auth login',
    'logout': 'auth logout',
}

TOP_LEVEL_COMMANDS = [
    'gmail', 'calendar', 'drive', 'sheets', 'docs', 'meet', 'tasks',
    'forms', 'chat', 'people', 'bigquery', 'reminders', 'booking',
    'ai', 'auth', 'config', 'cache', 'alias', 'profile', 'personal-profile',
    'interactive', 'welcome', 'test', 'today', 'unread', 'inbox', 'next',
    'status', 'list', 'ls', 'get', 'create', 'add', 'update', 'edit',
    'delete', 'rm', 'remove', 'search', 'read', 'write', 'append',
    'insert', 'copy', 'cp', 'move', 'mv', 'upload', 'download', 'trash',
    'restore', 'clear', 'complete', 'uncomplete', 'run', 'send', 'reply',
    'react', 'unreact', 'suspend', 'unsuspend', 'info', 'activity'
]

SUBCOMMAND_MAP: Dict[str, List[str]] = {
    'gmail': ['list', 'get', 'send', 'read', 'reply', 'forward', 'draft', 'drafts', 'label', 'labels', 'threads', 'mark', 'filters', 'search', 'alert', 'digest', 'escalate', 'schedule-summary', 'profile'],
    'calendar': ['list', 'list-events', 'create', 'create-event', 'update', 'delete', 'search', 'instances', 'create-calendar', 'list-calendars', 'aliases', 'watch'],
    'drive': ['list', 'get', 'download', 'upload', 'create', 'edit', 'delete', 'copy', 'move', 'rename', 'trash', 'restore', 'search', 'share', 'empty-trash', 'import'],
    'sheets': ['list', 'read', 'write', 'create', 'append', 'clear', 'tabs', 'add-tab', 'delete-tab', 'rename-tab'],
    'docs': ['list', 'read', 'create', 'update', 'append', 'insert', 'search'],
    'tasks': ['lists', 'list', 'create', 'edit', 'delete', 'complete', 'clear'],
    'meet': ['create', 'join', 'details', 'active', 'list', 'participants', 'recordings', 'transcripts', 'end'],
    'forms': ['list', 'info', 'responses', 'create', 'edit'],
    'chat': ['spaces', 'messages', 'send', 'delete', 'react', 'unreact', 'search', 'members'],
    'auth': ['login', 'logout', 'status', 'check'],
    'config': ['show', 'set', 'get', 'reset', 'path', 'export', 'import'],
    'cache': ['stats', 'clear', 'info', 'clean', 'get', 'set', 'delete'],
    'ai': ['ask', 'chat', 'summarize', 'draft', 'analytics', 'insights'],
}

COMMON_OPTIONS = ['--format', '--debug', '--config-dir', '--no-cache', '--help', '--version']


def _try_gemini_suggestion(raw_args: List[str], error_msg: str, config_manager: Optional[ConfigManager] = None) -> Optional[str]:
    """Attempt to obtain an AI command suggestion from Gemini."""
    try:
        cfg = config_manager or ConfigManager()
        ai_cfg = cfg.get('ai')
        api_key = (ai_cfg.gemini_api_key if ai_cfg else None) or os.environ.get('HERMES_GEMINI_API_KEY') or os.environ.get('GEMINI_API_KEY')
        if not api_key:
            return None

        model_name = getattr(ai_cfg, 'model_name', 'gemini-3.6-flash') if ai_cfg else 'gemini-3.6-flash'
        client = GeminiClient(api_key=api_key, model_name=model_name)
        if not client.is_available:
            return None

        prompt = (
            f"The user entered an invalid command for the 'hermes' Google Workspace CLI tool:\n"
            f"Command: hermes {' '.join(raw_args)}\n"
            f"Validation error: {error_msg}\n\n"
            f"Available Hermes top commands: gmail, calendar, drive, sheets, docs, meet, tasks, forms, chat, ai, auth, config, cache, list, create, search, send, reply.\n"
            f"Provide ONLY the single corrected command starting with 'hermes' (e.g. 'hermes gmail list'). "
            f"Do not include explanation, markdown formatting, or multiple choices."
        )

        response = client.generate_content(prompt)
        if response:
            clean = response.strip().strip('`').strip()
            # If response looks like a hermes command
            if clean.startswith('hermes ') and '\n' not in clean:
                return clean
    except Exception as e:
        logger.debug(f"Gemini suggestion failed: {e}")
    return None


def _local_suggestion(raw_args: List[str], error_msg: str) -> Optional[str]:
    """
    Deterministic rule-based fallback suggestion when Gemini AI is not available.
    Handles command typos, subcommand corrections, option typos, and natural language.
    """
    if not raw_args:
        return "hermes --help"

    tokens = list(raw_args)

    # Separate any leading global options (like --debug)
    prefix_flags = []
    cmd_tokens = []
    for token in tokens:
        if token.startswith('-') and not cmd_tokens:
            prefix_flags.append(token)
        else:
            cmd_tokens.append(token)

    if not cmd_tokens:
        return "hermes --help"

    first = cmd_tokens[0].lower()

    # Case 1: First token is in synonyms
    if first in SYNONYMS:
        corrected_first = SYNONYMS[first]
        if ' ' in corrected_first:
            # Multi-token replacement (e.g. 'inbox' -> 'gmail list')
            parts = corrected_first.split()
            cmd_tokens = parts + cmd_tokens[1:]
        else:
            cmd_tokens[0] = corrected_first
        return "hermes " + " ".join(prefix_flags + cmd_tokens)

    # Case 2: First token is a close match to top-level command
    if first not in TOP_LEVEL_COMMANDS:
        matches = difflib.get_close_matches(first, TOP_LEVEL_COMMANDS, n=1, cutoff=0.5)
        if matches:
            cmd_tokens[0] = matches[0]
            return "hermes " + " ".join(prefix_flags + cmd_tokens)

    # Case 3: First token is valid group, but subcommand has a typo
    if first in SUBCOMMAND_MAP and len(cmd_tokens) > 1:
        valid_subs = SUBCOMMAND_MAP[first]
        sub = cmd_tokens[1].lower()
        if not sub.startswith('-') and sub not in valid_subs:
            # Special case: 'hermes calendar event list' -> 'hermes calendar list-events'
            if first == 'calendar' and sub in ('event', 'events'):
                if len(cmd_tokens) > 2 and cmd_tokens[2] == 'list':
                    cmd_tokens = [first, 'list-events'] + cmd_tokens[3:]
                    return "hermes " + " ".join(prefix_flags + cmd_tokens)
                elif len(cmd_tokens) > 2 and cmd_tokens[2] == 'create':
                    cmd_tokens = [first, 'create-event'] + cmd_tokens[3:]
                    return "hermes " + " ".join(prefix_flags + cmd_tokens)
                else:
                    cmd_tokens[1] = 'list-events'
                    return "hermes " + " ".join(prefix_flags + cmd_tokens)

            sub_matches = difflib.get_close_matches(sub, valid_subs, n=1, cutoff=0.5)
            if sub_matches:
                cmd_tokens[1] = sub_matches[0]
                return "hermes " + " ".join(prefix_flags + cmd_tokens)

    # Case 4: Option typo (e.g. --formatt -> --format)
    corrected_tokens = []
    option_corrected = False
    for t in cmd_tokens:
        if t.startswith('--') and '=' not in t:
            # Check for common option match
            opt_matches = difflib.get_close_matches(t, COMMON_OPTIONS, n=1, cutoff=0.7)
            if opt_matches and opt_matches[0] != t:
                corrected_tokens.append(opt_matches[0])
                option_corrected = True
                continue
        corrected_tokens.append(t)

    if option_corrected:
        return "hermes " + " ".join(prefix_flags + corrected_tokens)

    # Case 5: Natural language request without 'hermes ai ask'
    # Try NLP suggest_command
    try:
        from ..ai.nlp import NaturalLanguageProcessor
        nlp = NaturalLanguageProcessor()
        suggested = nlp.suggest_command(" ".join(cmd_tokens))
        if suggested and not suggested.startswith('#'):
            return suggested
    except Exception:
        pass

    return None


def generate_command_suggestion(raw_args: List[str], error_msg: str, config_manager: Optional[ConfigManager] = None) -> Optional[str]:
    """
    Generate a command suggestion using Gemini AI when available,
    falling back safely to deterministic rule-based suggestion.
    """
    # Try Gemini AI suggestion first
    ai_suggestion = _try_gemini_suggestion(raw_args, error_msg, config_manager)
    if ai_suggestion:
        return ai_suggestion

    # Safe deterministic local fallback
    return _local_suggestion(raw_args, error_msg)


def handle_validation_error(exc: click.ClickException, raw_args: List[str], config_manager: Optional[ConfigManager] = None) -> None:
    """
    Display a clean validation error and AI-generated or local suggestion.
    Halts execution immediately without triggering OAuth or calling Google APIs.
    """
    # Extract clean error message
    if isinstance(exc, click.exceptions.NoSuchCommand):
        cmd = getattr(exc, 'command_name', None) or 'unknown'
        error_msg = f'Unknown command "{cmd}".'
    elif isinstance(exc, click.exceptions.NoSuchOption):
        opt = getattr(exc, 'option_name', None) or 'unknown'
        error_msg = f'Unknown option "{opt}".'
    elif isinstance(exc, click.exceptions.BadParameter):
        param_name = getattr(exc.param, 'name', None) if getattr(exc, 'param', None) else "parameter"
        error_msg = f'Invalid value for "{param_name}": {exc.format_message().strip()}'
    elif isinstance(exc, click.exceptions.MissingParameter):
        param_name = getattr(exc.param, 'name', None) if getattr(exc, 'param', None) else "parameter"
        error_msg = f'Missing required parameter: {param_name}.'
    else:
        raw_msg = exc.format_message().strip()
        # Clean up any Click "Error: " prefix
        if raw_msg.lower().startswith('error:'):
            raw_msg = raw_msg[6:].strip()
        error_msg = raw_msg

    # Generate suggestion (Gemini AI or Local)
    suggestion = generate_command_suggestion(raw_args, error_msg, config_manager)

    # Format output according to required workflow:
    # Error: Unknown command "gmaill".
    #
    # Did you mean:
    #     hermes gmail list
    print(f"{Fore.RED}Error: {error_msg}{Style.RESET_ALL}\n")
    if suggestion:
        print(f"Did you mean:")
        print(f"    {suggestion}\n")
