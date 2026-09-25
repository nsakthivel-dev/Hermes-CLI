"""
Hermes-local runtime configuration (~/.hermes/config.yaml).

This file provides a lightweight read/write helper for the ~/.hermes/config.yaml
file that is separate from the GSuite-CLI config at ~/.config/gsuite-cli/.
The pattern is intentionally simple so that the Calendar and Sheets modules can
reuse it without pulling in the heavier ConfigManager.

Schema (all keys are optional; keys that Hermes reads are documented inline):

    oncall:
      email: oncall@example.com          # default on-call address
      name: "On-Call Team"               # display name (optional)
    gmail:
      digest_recipient: ops@example.com  # default digest recipient
      alert_from: hermes-bot@example.com # override From header for alerts
    calendar:
      default_timezone: Europe/Berlin
    sheets:
      default_spreadsheet: <id>
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

# Default location; can be overridden at call-site for testing.
DEFAULT_CONFIG_PATH = Path.home() / ".hermes" / "config.yaml"


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load(config_path: Optional[Path] = None) -> dict:
    """
    Load the Hermes config file.

    Returns an empty dict if the file does not yet exist so callers can always
    do safe dict-lookups without None-checks.
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        logger.debug("Loaded Hermes config from %s", path)
        return data
    except Exception as exc:
        logger.warning("Could not read Hermes config %s: %s", path, exc)
        return {}


def save(data: dict, config_path: Optional[Path] = None) -> bool:
    """
    Persist *data* to the Hermes config file.

    Creates ~/.hermes/ if it does not exist. Returns True on success.
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    try:
        _ensure_dir(path)
        with open(path, "w", encoding="utf-8") as fh:
            yaml.dump(data, fh, default_flow_style=False, allow_unicode=True, indent=2)
        logger.debug("Saved Hermes config to %s", path)
        return True
    except Exception as exc:
        logger.error("Could not write Hermes config %s: %s", path, exc)
        return False


def get(key: str, default: Any = None, config_path: Optional[Path] = None) -> Any:
    """
    Read a dot-notation key from the Hermes config file.

    Example::

        oncall_email = hermes_config.get("oncall.email", "fallback@example.com")
    """
    data = load(config_path)
    parts = key.split(".")
    value: Any = data
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return default
    return value


def set_value(key: str, value: Any, config_path: Optional[Path] = None) -> bool:
    """
    Write a dot-notation key into the Hermes config file.

    Intermediate dicts are created automatically. Returns True on success.

    Example::

        hermes_config.set_value("oncall.email", "newoncall@example.com")
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    data = load(path)
    parts = key.split(".")
    node = data
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value
    return save(data, path)


def get_oncall_email(config_path: Optional[Path] = None) -> Optional[str]:
    """Return the configured on-call email, or None if not set."""
    return get("oncall.email", None, config_path) or None


def get_oncall_name(config_path: Optional[Path] = None) -> str:
    """Return the configured on-call display name, defaulting to 'On-Call'."""
    return get("oncall.name", "On-Call", config_path)
