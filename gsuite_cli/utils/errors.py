"""
Error definitions and separated error handlers for Hermes CLI.
Enforces the 7 distinct error categories required by Hermes CLI workflow:
1. Command validation errors
2. Authentication errors
3. Configuration errors
4. AI/NLP errors
5. Google API errors
6. Cache errors
7. Resource resolution errors
"""

import sys
import logging
from typing import Optional
from colorama import Fore, Style
from googleapiclient.errors import HttpError

from .formatters import print_error, print_info, print_warning

logger = logging.getLogger(__name__)


class HermesCLIError(Exception):
    """Base exception for all Hermes CLI domain errors."""
    def __init__(self, message: str, details: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.details = details


class CommandValidationError(HermesCLIError):
    """Raised when command syntax, subcommands, or arguments fail validation."""
    pass


class AuthenticationError(HermesCLIError):
    """Raised when authentication check fails or valid credentials cannot be obtained."""
    pass


class ConfigurationError(HermesCLIError):
    """Raised when configuration loading, schema, or values are invalid."""
    pass


class AINLPError(HermesCLIError):
    """Raised when Gemini AI processing or NLP interpretation fails."""
    pass


class GoogleAPIError(HermesCLIError):
    """Raised when Google Workspace API operations fail."""
    pass


class CacheError(HermesCLIError):
    """Raised when disk cache operations fail."""
    pass


def handle_authentication_error(err: AuthenticationError) -> None:
    """Handle Step 2 authentication errors cleanly and stop safely."""
    print_error(f"Authentication Error: {err.message}")
    if err.details:
        print_info(err.details)
    else:
        print_info("To authenticate with your Google account, run: hermes auth login")
    sys.exit(1)


def handle_google_api_error(err: HttpError) -> None:
    """
    Handle Google Workspace API errors with friendly explanation
    and appropriate recovery/suggestion.
    """
    status_code = getattr(err, 'resp', {}).status if hasattr(err, 'resp') else None
    
    # Extract friendly reason
    reason = ""
    try:
        if hasattr(err, 'error_details') and err.error_details:
            reason = str(err.error_details)
        elif hasattr(err, '_get_reason'):
            reason = err._get_reason().strip()
        else:
            reason = str(err).strip()
    except Exception:
        reason = str(err)

    if status_code == 401:
        print_error("Google API Error: Authentication token is invalid or expired.")
        print_info("Recovery Suggestion: Run 'hermes auth login --force' to re-authenticate with Google.")
    elif status_code == 403:
        print_error(f"Google API Error: Permission denied ({reason or 'Forbidden'}).")
        print_info("Recovery Suggestion: Your Google account may lack required permissions or scopes.")
        print_info("Run 'hermes auth login --force' to grant all required Google Workspace scopes.")
    elif status_code == 404:
        print_error(f"Google API Error: Resource not found ({reason or 'Not Found'}).")
        print_info("Recovery Suggestion: Verify the resource ID or search available resources with 'hermes <service> list'.")
    elif status_code == 429:
        print_error("Google API Error: Rate limit or API quota exceeded.")
        print_info("Recovery Suggestion: Please wait a moment before retrying the command.")
    elif status_code in (500, 502, 503, 504):
        print_error(f"Google API Error: Service temporarily unavailable (HTTP {status_code}).")
        print_info("Recovery Suggestion: Google's servers may be undergoing maintenance. Please retry in a few moments.")
    else:
        status_str = f" (HTTP {status_code})" if status_code else ""
        print_error(f"Google API Error{status_str}: {reason or 'Operation failed'}")
        print_info("Recovery Suggestion: Check command parameters or run with '--debug' for detailed logs.")

    sys.exit(1)


def handle_configuration_error(err: ConfigurationError) -> None:
    """Handle configuration errors."""
    print_error(f"Configuration Error: {err.message}")
    if err.details:
        print_info(err.details)
    print_info("View current configuration with 'hermes config show' or update settings using 'hermes config set'.")
    sys.exit(1)


def handle_ai_error(err: AINLPError) -> None:
    """Handle Gemini AI and NLP errors."""
    print_error(f"AI Error: {err.message}")
    if err.details:
        print_info(err.details)
    print_info("Suggestion: Check that your Gemini API key is configured with 'hermes config set ai.gemini_api_key <KEY>' or set the GEMINI_API_KEY environment variable.")
    sys.exit(1)


def handle_resource_resolution_error(err: Exception) -> None:
    """Handle resource resolution errors from GlobalResourceResolver or CalendarResolver."""
    msg = str(err)
    print_error(f"Resource Resolution Error: {msg}")
    print_info("Suggestion: Check available resources by listing them (e.g. 'hermes <service> list') or specify the exact technical ID.")
    sys.exit(1)


def handle_cache_error(err: CacheError) -> None:
    """Handle cache management errors."""
    print_error(f"Cache Error: {err.message}")
    if err.details:
        print_info(err.details)
    print_info("Suggestion: Run 'hermes cache clear' to reset local cache entries.")
    sys.exit(1)
