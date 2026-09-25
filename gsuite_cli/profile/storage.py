"""
Storage repository for Personal Profile with secure atomic persistence and corruption recovery.
"""

import os
import json
import logging
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from datetime import datetime

from ..config.manager import ConfigManager
from .models import PersonalProfile

logger = logging.getLogger(__name__)


class PersonalProfileRepository:
    """
    Handles secure, atomic persistence of Personal Profile data.
    Ensures that no profile contents are logged.
    """

    def __init__(self, config_manager: Optional[ConfigManager] = None, data_dir: Optional[Path] = None):
        if data_dir:
            self.data_dir = Path(data_dir)
        elif config_manager:
            self.data_dir = config_manager.data_dir
        else:
            self.data_dir = Path.home() / '.config' / 'gsuite-cli'

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.profile_file = self.data_dir / 'profile.json'

    def load(self) -> PersonalProfile:
        """
        Load profile from disk. If file does not exist, returns default profile.
        If file is corrupted, backs it up and returns default profile.
        """
        if not self.profile_file.exists():
            profile = PersonalProfile()
            self.save(profile)
            return profile

        try:
            with open(self.profile_file, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)

            if not isinstance(raw_data, dict):
                raise ValueError("Corrupted profile data: root must be a JSON object.")

            return PersonalProfile.from_dict(raw_data)
        except Exception as e:
            logger.error(f"PersonalProfileRepository: Failed to load profile file, backing up corrupted data. Error: {type(e).__name__}")
            # Backup corrupted file safely
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            corrupt_backup = self.data_dir / f"profile.json.corrupt.{timestamp}"
            try:
                if self.profile_file.exists():
                    os.replace(self.profile_file, corrupt_backup)
            except Exception:
                pass

            # Create and save clean default profile
            default_profile = PersonalProfile()
            self.save(default_profile)
            return default_profile

    def save(self, profile: PersonalProfile) -> bool:
        """
        Atomically save profile to disk using a temporary file.
        Sets secure permissions (0o600) on POSIX.
        """
        try:
            profile_dict = profile.to_dict()
            json_data = json.dumps(profile_dict, indent=2, ensure_ascii=False)

            # Atomic write: write to temp file in the same directory, then atomic rename/replace
            fd, tmp_path = tempfile.mkstemp(
                prefix='hermes_profile_',
                suffix='.tmp',
                dir=str(self.data_dir)
            )
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(json_data)

            # Secure file permissions on POSIX
            try:
                os.chmod(tmp_path, 0o600)
            except Exception:
                pass

            os.replace(tmp_path, self.profile_file)
            return True
        except Exception as e:
            logger.error(f"PersonalProfileRepository: Failed to save profile atomically. Error: {type(e).__name__}")
            return False

    def export_data(self) -> Dict[str, Any]:
        """
        Export profile as structured dictionary for file export.
        Excludes any sensitive system tokens/keys.
        """
        profile = self.load()
        return profile.to_dict()

    def import_data(self, data: Dict[str, Any]) -> Tuple[bool, str, Optional[PersonalProfile]]:
        """
        Validate and import profile data dictionary.
        Returns (success: bool, error_or_preview: str, profile: Optional[PersonalProfile])
        """
        if not isinstance(data, dict):
            return False, "Invalid profile data: Expected JSON object.", None

        # Validate minimal schema expectations
        valid_sections = {'basic', 'contact', 'addresses', 'professional', 'education', 'custom_fields', 'snippets', 'privacy'}
        if not any(s in data for s in valid_sections):
            return False, "Invalid profile structure: No recognized profile sections found.", None

        try:
            new_profile = PersonalProfile.from_dict(data)
            return True, "Profile structure validated successfully.", new_profile
        except Exception as e:
            return False, f"Failed to parse profile structure: {type(e).__name__}", None
