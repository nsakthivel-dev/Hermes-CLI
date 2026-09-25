"""
Validation utilities for Personal Profile fields.
"""

import re
from datetime import datetime
from typing import Tuple


def validate_email(value: str) -> Tuple[bool, str]:
    """Validate email address format."""
    val = value.strip()
    if not val:
        return False, "Email address cannot be empty."
    pattern = r'^[^@\s]+@[^@\s]+\.[^@\s]+$'
    if not re.match(pattern, val):
        return False, "Invalid email format (example: user@example.com)."
    return True, ""


def validate_phone(value: str) -> Tuple[bool, str]:
    """Validate phone number format."""
    val = value.strip()
    if not val:
        return False, "Phone number cannot be empty."
    # Allow leading +, digits, spaces, hyphens, parentheses
    cleaned = re.sub(r'[\s\-\(\)\.]', '', val)
    if cleaned.startswith('+'):
        cleaned = cleaned[1:]
    if not cleaned.isdigit() or len(cleaned) < 7 or len(cleaned) > 15:
        return False, "Invalid phone number format (must contain 7-15 digits)."
    return True, ""


def validate_url(value: str) -> Tuple[bool, str]:
    """Validate URL format."""
    val = value.strip()
    if not val:
        return False, "URL cannot be empty."
    pattern = r'^(https?://)?([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(/.*)?$'
    if not re.match(pattern, val):
        return False, "Invalid URL format (example: https://github.com/username)."
    return True, ""


def validate_date(value: str) -> Tuple[bool, str]:
    """Validate date format (YYYY-MM-DD)."""
    val = value.strip()
    if not val:
        return False, "Date cannot be empty."
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%m/%d/%Y', '%Y/%m/%d'):
        try:
            datetime.strptime(val, fmt)
            return True, ""
        except ValueError:
            continue
    return False, "Invalid date format. Please use YYYY-MM-DD."


def validate_postal_code(value: str, country: str = '') -> Tuple[bool, str]:
    """Validate postal/ZIP code format."""
    val = value.strip()
    if not val:
        return False, "Postal code cannot be empty."
    # General alphanumeric 3 to 10 characters
    if not re.match(r'^[a-zA-Z0-9\s\-]{3,10}$', val):
        return False, "Invalid postal code format."
    return True, ""


def validate_non_empty(value: str, field_name: str = "Field") -> Tuple[bool, str]:
    """Validate that field is non-empty."""
    val = value.strip()
    if not val:
        return False, f"{field_name} cannot be empty."
    return True, ""


def validate_custom_key(key: str) -> Tuple[bool, str]:
    """Validate custom field key."""
    k = key.strip()
    if not k:
        return False, "Field name/key cannot be empty."
    if not re.match(r'^[a-zA-Z0-9_\-\s]+$', k):
        return False, "Field name can only contain letters, numbers, spaces, underscores, or hyphens."
    return True, ""
