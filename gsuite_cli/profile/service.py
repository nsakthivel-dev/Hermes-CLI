"""
Service layer for Personal Profile business logic and management.
"""

import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from .models import (
    PersonalProfile, BasicInfo, ContactInfo, Address,
    ProfessionalInfo, EducationInfo, CustomField, ProfileSnippet, PrivacySettings
)
from .storage import PersonalProfileRepository

logger = logging.getLogger(__name__)


class PersonalProfileService:
    """
    Manages all domain operations on Personal Profile.
    Other modules interact with profile data via this service or ProfileResolver.
    """

    def __init__(self, repository: Optional[PersonalProfileRepository] = None):
        self.repository = repository or PersonalProfileRepository()
        self._profile: Optional[PersonalProfile] = None

    def get_profile(self, force_reload: bool = False) -> PersonalProfile:
        """Get the current profile, reloading from disk if needed."""
        if self._profile is None or force_reload:
            self._profile = self.repository.load()
        return self._profile

    def save_profile(self) -> bool:
        """Persist current profile to disk."""
        if self._profile is not None:
            return self.repository.save(self._profile)
        return False

    # ── Summary & Status ───────────────────────────────────────────────────────

    def get_summary_stats(self) -> Dict[str, Any]:
        """
        Get non-sensitive status summary for display on the main profile screen.
        Does NOT return sensitive values.
        """
        p = self.get_profile()
        name = p.basic.displayName or p.basic.fullName or "Not configured"
        email = p.contact.primaryEmail or "Not configured"

        # Count configured fields
        configured_count = 0
        for val in [p.basic.fullName, p.basic.firstName, p.basic.lastName, p.basic.displayName, p.basic.dateOfBirth]:
            if val and val.strip():
                configured_count += 1
        for val in [p.contact.primaryEmail, p.contact.personalEmail, p.contact.workEmail, p.contact.phone, p.contact.alternatePhone]:
            if val and val.strip():
                configured_count += 1
        for a in p.addresses:
            if a.to_formatted_string():
                configured_count += 1
        for val in [p.professional.jobTitle, p.professional.company, p.professional.department, p.professional.experience, p.professional.github, p.professional.linkedin, p.professional.portfolio, p.professional.website]:
            if val and val.strip():
                configured_count += 1
        if p.professional.skills:
            configured_count += 1
        for e in p.education:
            if e.institution or e.degree:
                configured_count += 1
        for c in p.custom_fields:
            if c.value and c.value.strip():
                configured_count += 1

        auto_use_enabled = any(p.privacy.auto_use_fields.values())

        return {
            'name': name,
            'email': email,
            'fields_count': configured_count,
            'snippets_count': len(p.snippets),
            'auto_use': "Enabled" if auto_use_enabled else "Disabled",
            'is_locked': p.privacy.is_locked,
        }

    # ── Basic Information ──────────────────────────────────────────────────────

    def update_basic_field(self, field_name: str, value: str) -> bool:
        p = self.get_profile()
        if p.privacy.is_locked:
            return False
        if hasattr(p.basic, field_name):
            setattr(p.basic, field_name, value.strip())
            # Sync fullName if first or last changed and fullName empty
            if field_name in ('firstName', 'lastName') and not p.basic.fullName:
                p.basic.fullName = f"{p.basic.firstName} {p.basic.lastName}".strip()
            return self.save_profile()
        return False

    def clear_basic_field(self, field_name: str) -> bool:
        return self.update_basic_field(field_name, '')

    # ── Contact Information ────────────────────────────────────────────────────

    def update_contact_field(self, field_name: str, value: str) -> bool:
        p = self.get_profile()
        if p.privacy.is_locked:
            return False
        if hasattr(p.contact, field_name):
            setattr(p.contact, field_name, value.strip())
            return self.save_profile()
        return False

    def clear_contact_field(self, field_name: str) -> bool:
        return self.update_contact_field(field_name, '')

    # ── Address Information ────────────────────────────────────────────────────

    def add_address(self, label: str, street: str, city: str, state: str, country: str, postal_code: str) -> Address:
        p = self.get_profile()
        addr = Address(
            label=label.strip() or 'Home',
            street=street.strip(),
            city=city.strip(),
            state=state.strip(),
            country=country.strip(),
            postalCode=postal_code.strip(),
        )
        p.addresses.append(addr)
        self.save_profile()
        return addr

    def update_address(self, index: int, **kwargs) -> bool:
        p = self.get_profile()
        if 0 <= index < len(p.addresses):
            addr = p.addresses[index]
            for k, v in kwargs.items():
                if hasattr(addr, k):
                    setattr(addr, k, v.strip() if isinstance(v, str) else v)
            return self.save_profile()
        return False

    def delete_address(self, index: int) -> bool:
        p = self.get_profile()
        if 0 <= index < len(p.addresses):
            p.addresses.pop(index)
            return self.save_profile()
        return False

    # ── Professional Information ───────────────────────────────────────────────

    def update_professional_field(self, field_name: str, value: Any) -> bool:
        p = self.get_profile()
        if p.privacy.is_locked:
            return False
        if field_name == 'skills':
            if isinstance(value, str):
                p.professional.skills = [s.strip() for s in value.split(',') if s.strip()]
            elif isinstance(value, list):
                p.professional.skills = [str(s).strip() for s in value if str(s).strip()]
            return self.save_profile()
        elif hasattr(p.professional, field_name):
            setattr(p.professional, field_name, str(value).strip())
            return self.save_profile()
        return False

    def clear_professional_field(self, field_name: str) -> bool:
        if field_name == 'skills':
            p = self.get_profile()
            p.professional.skills = []
            return self.save_profile()
        return self.update_professional_field(field_name, '')

    # ── Education Information ──────────────────────────────────────────────────

    def add_education(self, institution: str, degree: str, department: str = '', university: str = '', year: str = '', student_id: str = '') -> EducationInfo:
        p = self.get_profile()
        edu = EducationInfo(
            institution=institution.strip(),
            degree=degree.strip(),
            department=department.strip(),
            university=university.strip(),
            year=year.strip(),
            studentId=student_id.strip(),
        )
        p.education.append(edu)
        self.save_profile()
        return edu

    def update_education(self, index: int, **kwargs) -> bool:
        p = self.get_profile()
        if 0 <= index < len(p.education):
            edu = p.education[index]
            for k, v in kwargs.items():
                if hasattr(edu, k):
                    setattr(edu, k, v.strip() if isinstance(v, str) else v)
            return self.save_profile()
        return False

    def delete_education(self, index: int) -> bool:
        p = self.get_profile()
        if 0 <= index < len(p.education):
            p.education.pop(index)
            return self.save_profile()
        return False

    # ── Custom Fields ──────────────────────────────────────────────────────────

    def add_custom_field(self, key: str, display_name: str, value: str, sensitivity: bool = False, auto_use: bool = True) -> CustomField:
        p = self.get_profile()
        # Key normalization
        norm_key = key.strip().lower().replace(' ', '_')
        field = CustomField(
            key=norm_key,
            displayName=display_name.strip() or key.strip(),
            value=value.strip(),
            sensitivity=sensitivity,
            autoUse=auto_use,
        )
        # Check if already exists; if so, replace
        existing = next((c for c in p.custom_fields if c.key == norm_key), None)
        if existing:
            existing.displayName = field.displayName
            existing.value = field.value
            existing.sensitivity = field.sensitivity
            existing.autoUse = field.autoUse
        else:
            p.custom_fields.append(field)
        self.save_profile()
        return field

    def update_custom_field(self, index: int, **kwargs) -> bool:
        p = self.get_profile()
        if 0 <= index < len(p.custom_fields):
            cf = p.custom_fields[index]
            for k, v in kwargs.items():
                if hasattr(cf, k):
                    setattr(cf, k, v.strip() if isinstance(v, str) else v)
            return self.save_profile()
        return False

    def delete_custom_field(self, index: int) -> bool:
        p = self.get_profile()
        if 0 <= index < len(p.custom_fields):
            p.custom_fields.pop(index)
            return self.save_profile()
        return False

    # ── Snippets ───────────────────────────────────────────────────────────────

    def create_snippet(self, name: str, content: str) -> ProfileSnippet:
        p = self.get_profile()
        snippet = ProfileSnippet(
            name=name.strip(),
            content=content.strip(),
        )
        p.snippets.append(snippet)
        self.save_profile()
        return snippet

    def update_snippet(self, index: int, name: Optional[str] = None, content: Optional[str] = None) -> bool:
        p = self.get_profile()
        if 0 <= index < len(p.snippets):
            snip = p.snippets[index]
            if name is not None:
                snip.name = name.strip()
            if content is not None:
                snip.content = content.strip()
            snip.updated_at = datetime.now().isoformat()
            return self.save_profile()
        return False

    def delete_snippet(self, index: int) -> bool:
        p = self.get_profile()
        if 0 <= index < len(p.snippets):
            p.snippets.pop(index)
            return self.save_profile()
        return False

    def get_snippet(self, index: int) -> Optional[ProfileSnippet]:
        p = self.get_profile()
        if 0 <= index < len(p.snippets):
            return p.snippets[index]
        return None

    # ── Privacy & Security ─────────────────────────────────────────────────────

    def toggle_auto_use(self, field_key: str) -> bool:
        p = self.get_profile()
        current = p.privacy.auto_use_fields.get(field_key, True)
        p.privacy.auto_use_fields[field_key] = not current
        return self.save_profile()

    def set_sensitive(self, field_key: str, is_sensitive: bool) -> bool:
        p = self.get_profile()
        if is_sensitive and field_key not in p.privacy.sensitive_fields:
            p.privacy.sensitive_fields.append(field_key)
        elif not is_sensitive and field_key in p.privacy.sensitive_fields:
            p.privacy.sensitive_fields.remove(field_key)
        return self.save_profile()

    def toggle_require_confirmation(self) -> bool:
        p = self.get_profile()
        p.privacy.require_confirmation = not p.privacy.require_confirmation
        return self.save_profile()

    def toggle_lock(self) -> bool:
        p = self.get_profile()
        p.privacy.is_locked = not p.privacy.is_locked
        return self.save_profile()

    def is_locked(self) -> bool:
        return self.get_profile().privacy.is_locked

    # ── Export & Import & Reset ────────────────────────────────────────────────

    def export_profile_json(self) -> str:
        """Export profile as formatted JSON string."""
        data = self.repository.export_data()
        return json.dumps(data, indent=2, ensure_ascii=False)

    def import_profile_json(self, json_str: str) -> Tuple[bool, str, Optional[PersonalProfile]]:
        """
        Validate profile JSON string and return preview.
        Does NOT overwrite until caller confirms and calls apply_import.
        """
        try:
            parsed = json.loads(json_str)
            if not isinstance(parsed, dict):
                return False, "Invalid JSON: root must be an object.", None
            ok, msg, profile = self.repository.import_data(parsed)
            if not ok or not profile:
                return False, msg, None

            # Generate preview
            preview_lines = [
                f"Name: {profile.basic.fullName or profile.basic.displayName or 'Not set'}",
                f"Primary Email: {profile.contact.primaryEmail or 'Not set'}",
                f"Addresses: {len(profile.addresses)}",
                f"Education records: {len(profile.education)}",
                f"Custom fields: {len(profile.custom_fields)}",
                f"Snippets: {len(profile.snippets)}",
            ]
            preview = "\n".join(preview_lines)
            return True, preview, profile
        except Exception as e:
            return False, f"Failed to parse JSON: {type(e).__name__}", None

    def apply_import(self, profile: PersonalProfile) -> bool:
        """Persist imported profile after user confirmation."""
        self._profile = profile
        return self.repository.save(profile)

    def reset_profile(self) -> bool:
        """Reset profile data to clean empty state."""
        self._profile = PersonalProfile()
        return self.repository.save(self._profile)
