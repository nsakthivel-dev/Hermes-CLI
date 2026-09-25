"""
ProfileResolver: Centralized resolver for profile fields, aliases, template variables,
context-aware suggestions, and auto-use permissions.
"""

import re
import logging
from typing import Dict, Any, List, Optional

from .service import PersonalProfileService
from .models import PersonalProfile

logger = logging.getLogger(__name__)


class ProfileResolver:
    """
    Centralized resolver that provides deterministic alias resolution,
    template variable substitution, keyword suggestions, and privacy checks.
    Hermes modules should always access profile information via ProfileResolver.
    """

    def __init__(self, service: Optional[PersonalProfileService] = None):
        self.service = service or PersonalProfileService()

    @property
    def profile(self) -> PersonalProfile:
        return self.service.get_profile()

    # ── Deterministic Field Mapping ────────────────────────────────────────────

    def _normalize_key(self, key: str) -> str:
        """Normalize key: lowercase, strip, replace spaces/dashes with underscores."""
        return re.sub(r'[\s\-]+', '_', key.strip().lower())

    def _resolve_canonical_key(self, field_name: str) -> str:
        """Map aliases to canonical internal path."""
        k = self._normalize_key(field_name)

        alias_map = {
            # Name
            'name': 'basic.fullName',
            'full_name': 'basic.fullName',
            'fullname': 'basic.fullName',
            'first_name': 'basic.firstName',
            'firstname': 'basic.firstName',
            'last_name': 'basic.lastName',
            'lastname': 'basic.lastName',
            'display_name': 'basic.displayName',
            'displayname': 'basic.displayName',
            'dob': 'basic.dateOfBirth',
            'date_of_birth': 'basic.dateOfBirth',
            'birthday': 'basic.dateOfBirth',
            'birthdate': 'basic.dateOfBirth',

            # Email
            'email': 'contact.primaryEmail',
            'primary_email': 'contact.primaryEmail',
            'email_address': 'contact.primaryEmail',
            'personal_email': 'contact.personalEmail',
            'work_email': 'contact.workEmail',

            # Phone
            'phone': 'contact.phone',
            'phone_number': 'contact.phone',
            'mobile': 'contact.phone',
            'mobile_number': 'contact.phone',
            'contact_number': 'contact.phone',
            'alternate_phone': 'contact.alternatePhone',
            'alt_phone': 'contact.alternatePhone',

            # Online / Links
            'github': 'professional.github',
            'github_url': 'professional.github',
            'github_profile': 'professional.github',
            'github_link': 'professional.github',
            'linkedin': 'professional.linkedin',
            'linkedin_url': 'professional.linkedin',
            'linkedin_profile': 'professional.linkedin',
            'linkedin_link': 'professional.linkedin',
            'portfolio': 'professional.portfolio',
            'portfolio_url': 'professional.portfolio',
            'portfolio_link': 'professional.portfolio',
            'website': 'professional.website',
            'personal_website': 'professional.website',
            'site': 'professional.website',

            # Professional
            'job_title': 'professional.jobTitle',
            'jobtitle': 'professional.jobTitle',
            'title': 'professional.jobTitle',
            'role': 'professional.jobTitle',
            'designation': 'professional.jobTitle',
            'company': 'professional.company',
            'organization': 'professional.company',
            'employer': 'professional.company',
            'experience': 'professional.experience',
            'skills': 'professional.skills',
            'skillset': 'professional.skills',
            'employee_id': 'employee_id',
            'employeeid': 'employee_id',
            'emp_id': 'employee_id',
            'empid': 'employee_id',
            'manager': 'manager_name',
            'manager_name': 'manager_name',
            'reporting_manager': 'manager_name',

            # Education
            'college': 'education.institution',
            'institution': 'education.institution',
            'school': 'education.institution',
            'university': 'education.university',
            'degree': 'education.degree',
            'qualification': 'education.degree',
            'student_id': 'education.studentId',
            'studentid': 'education.studentId',
            'roll_number': 'education.studentId',
            'roll_no': 'education.studentId',

            # Address
            'address': 'address.primary',
            'home_address': 'address.home',
            'college_address': 'address.college',
            'work_address': 'address.work',
        }

        if k in alias_map:
            return alias_map[k]

        # Check Department: if in professional or education
        if k in ('department', 'dept'):
            if self.profile.professional.department:
                return 'professional.department'
            return 'education.department'

        return k

    # ── Retrieval API ──────────────────────────────────────────────────────────

    def get(self, field_name: str, default: Any = None) -> Any:
        """
        Get resolved value for a field or alias.
        Returns value or default if not configured/empty.
        """
        canonical = self._resolve_canonical_key(field_name)
        p = self.profile

        val = None
        if canonical == 'basic.fullName':
            val = p.basic.fullName or (f"{p.basic.firstName} {p.basic.lastName}".strip() if (p.basic.firstName or p.basic.lastName) else None)
        elif canonical == 'basic.firstName':
            val = p.basic.firstName
        elif canonical == 'basic.lastName':
            val = p.basic.lastName
        elif canonical == 'basic.displayName':
            val = p.basic.displayName or p.basic.fullName
        elif canonical == 'basic.dateOfBirth':
            val = p.basic.dateOfBirth
        elif canonical == 'contact.primaryEmail':
            val = p.contact.primaryEmail
        elif canonical == 'contact.personalEmail':
            val = p.contact.personalEmail
        elif canonical == 'contact.workEmail':
            val = p.contact.workEmail
        elif canonical == 'contact.phone':
            val = p.contact.phone
        elif canonical == 'contact.alternatePhone':
            val = p.contact.alternatePhone
        elif canonical == 'professional.github':
            val = p.professional.github
        elif canonical == 'professional.linkedin':
            val = p.professional.linkedin
        elif canonical == 'professional.portfolio':
            val = p.professional.portfolio
        elif canonical == 'professional.website':
            val = p.professional.website
        elif canonical == 'professional.jobTitle':
            val = p.professional.jobTitle
        elif canonical == 'professional.company':
            val = p.professional.company
        elif canonical == 'professional.department':
            val = p.professional.department
        elif canonical == 'professional.experience':
            val = p.professional.experience
        elif canonical == 'professional.skills':
            val = ", ".join(p.professional.skills) if p.professional.skills else None
        elif canonical == 'education.institution':
            val = p.education[0].institution if p.education else None
        elif canonical == 'education.university':
            if p.education:
                val = p.education[0].university or p.education[0].institution
        elif canonical == 'education.degree':
            val = p.education[0].degree if p.education else None
        elif canonical == 'education.department':
            val = p.education[0].department if p.education else None
        elif canonical == 'education.studentId':
            val = p.education[0].studentId if p.education else None
        elif canonical == 'address.primary':
            val = p.addresses[0].to_formatted_string() if p.addresses else None
        elif canonical == 'address.home':
            addr = next((a for a in p.addresses if a.label.lower() == 'home'), None)
            val = addr.to_formatted_string() if addr else (p.addresses[0].to_formatted_string() if p.addresses else None)
        elif canonical == 'address.college':
            addr = next((a for a in p.addresses if a.label.lower() == 'college'), None)
            val = addr.to_formatted_string() if addr else None
        elif canonical == 'address.work':
            addr = next((a for a in p.addresses if a.label.lower() == 'work'), None)
            val = addr.to_formatted_string() if addr else None
        else:
            # Check custom fields
            norm_target = self._normalize_key(field_name)
            target_group = {norm_target}
            if norm_target in ('employee_id', 'employeeid', 'emp_id', 'empid'):
                target_group = {'employee_id', 'employeeid', 'emp_id', 'empid'}
            elif norm_target in ('manager_name', 'manager', 'reporting_manager'):
                target_group = {'manager_name', 'manager', 'reporting_manager'}

            for c in p.custom_fields:
                ck = self._normalize_key(c.key)
                cd = self._normalize_key(c.displayName)
                if ck in target_group or cd in target_group:
                    val = c.value
                    break

        if val is None or val == '':
            return default
        return val

    def has(self, field_name: str) -> bool:
        """Check if a field is configured and non-empty."""
        val = self.get(field_name)
        return bool(val)

    def getMany(self, fields: List[str]) -> Dict[str, Any]:
        """Get resolved values for multiple fields."""
        return {f: self.get(f) for f in fields}

    # ── Template Variables ─────────────────────────────────────────────────────

    def resolveTemplate(self, text: str, on_missing: str = 'placeholder', missing_placeholder: Optional[str] = None) -> str:
        """
        Interpolate profile variables like {{name}} or {{college}}.
        If a variable is missing, it is NOT silently emptied:
        - If on_missing == 'placeholder', replaced with:
          missing_placeholder or 'Profile information unavailable: <field>'
        - If on_missing == 'keep', left as {{field}}
        - If on_missing == 'empty', replaced with ''
        """
        if not text:
            return ""

        pattern = r'\{\{\s*([a-zA-Z0-9_\-\s]+)\s*\}\}'

        def replacer(match: re.Match) -> str:
            var_name = match.group(1).strip()
            val = self.get(var_name)
            if val:
                return str(val)

            if on_missing == 'placeholder':
                return missing_placeholder or f"Profile information unavailable: {var_name}"
            elif on_missing == 'keep':
                return match.group(0)
            elif on_missing == 'empty':
                return ""
            return match.group(0)

        return re.sub(pattern, replacer, text)

    # ── Context-Aware Suggestions ──────────────────────────────────────────────

    def getSuggestions(self, context: str) -> List[Dict[str, Any]]:
        """
        Deterministic keyword matching against context (e.g. email subject/body).
        Only returns fields that actually have configured values.
        """
        if not context:
            return []

        lower_ctx = context.lower()

        # Keyword mapping rules
        rules = [
            (['internship', 'job', 'application', 'apply', 'hiring', 'interview', 'opening'], [
                'name', 'college', 'degree', 'department', 'github', 'portfolio', 'linkedin', 'phone'
            ]),
            (['resume', 'cv', 'profile'], [
                'name', 'email', 'phone', 'degree', 'college', 'skills', 'github', 'linkedin', 'portfolio'
            ]),
            (['portfolio', 'showcase', 'project', 'projects', 'code', 'repo'], [
                'name', 'portfolio', 'github', 'website', 'skills'
            ]),
            (['introduction', 'intro', 'about me', 'pleased to meet', 'hello'], [
                'name', 'company', 'job_title', 'college', 'degree', 'email'
            ]),
            (['contact', 'reach me', 'connect', 'phone', 'call', 'touch'], [
                'name', 'email', 'phone', 'linkedin', 'website'
            ]),
        ]

        candidate_fields = []
        for keywords, fields in rules:
            if any(kw in lower_ctx for kw in keywords):
                for f in fields:
                    if f not in candidate_fields:
                        candidate_fields.append(f)

        # Filter only fields with values and gather metadata
        results = []
        for f in candidate_fields:
            val = self.get(f)
            if val:
                results.append({
                    'field': f,
                    'display_name': f.replace('_', ' ').capitalize(),
                    'value': str(val),
                    'is_sensitive': self.isSensitive(f),
                    'can_auto_use': self.canAutoUse(f),
                })

        return results

    # ── Privacy & Sensitivity Checks ───────────────────────────────────────────

    def isSensitive(self, field_name: str) -> bool:
        """Check if field is marked sensitive."""
        k = self._normalize_key(field_name)
        p = self.profile

        # Built-in sensitive fields
        if k in ('phone', 'mobile', 'alternate_phone', 'dob', 'date_of_birth', 'studentid', 'student_id', 'address', 'employee_id', 'employeeid', 'emp_id', 'empid'):
            return True

        for sens in p.privacy.sensitive_fields:
            if self._normalize_key(sens) == k:
                return True

        # Check custom field sensitivity
        for c in p.custom_fields:
            if (self._normalize_key(c.key) == k or self._normalize_key(c.displayName) == k) and c.sensitivity:
                return True

        return False

    def canAutoUse(self, field_name: str) -> bool:
        """Check if field is permitted for automatic use."""
        p = self.profile
        k = self._normalize_key(field_name)

        # If field is sensitive and require_confirmation is True, cannot auto-use without prompt
        if self.isSensitive(field_name) and p.privacy.require_confirmation:
            return False

        # Check custom field setting
        for c in p.custom_fields:
            if self._normalize_key(c.key) == k or self._normalize_key(c.displayName) == k:
                return c.autoUse

        # Check privacy auto_use_fields map
        # Check alias keys
        for perm_key, allowed in p.privacy.auto_use_fields.items():
            if self._normalize_key(perm_key) == k:
                return allowed

        # Default to True for non-sensitive, False for sensitive
        return not self.isSensitive(field_name)

    def mask_value(self, field_name: str, value: Any) -> str:
        """
        Return masked representation for sensitive fields, or raw string for non-sensitive.
        E.g. phone: ******3210, employee_id: ****1234
        """
        if value is None:
            return ""
        val_str = str(value).strip()
        if not self.isSensitive(field_name):
            return val_str

        if len(val_str) <= 4:
            return "****"
        return f"{'*' * (len(val_str) - 4)}{val_str[-4:]}"

    def get_context_fields(self, context: str) -> Dict[str, Any]:
        """
        Context-aware identification of relevant required and optional fields
        based on email intent and instructions.
        """
        if not context:
            return {
                'intent': 'general',
                'required_fields': ['name'],
                'optional_fields': [],
                'all_fields': ['name'],
            }

        lower_ctx = context.lower()

        # Check College / HOD request
        if any(w in lower_ctx for w in ['hod', 'dean', 'professor', 'principal', 'student', 'college', 'semester', 'university', 'register number', 'roll number']) and not any(w in lower_ctx for w in ['job', 'apply', 'interview', 'hiring']):
            return {
                'intent': 'college_request',
                'required_fields': ['name'],
                'optional_fields': ['department', 'student_id', 'college', 'year'],
                'all_fields': ['name', 'department', 'student_id', 'college', 'year'],
            }

        # Check Sick / Fever / Vacation / Casual Leave (Work or general)
        if any(w in lower_ctx for w in ['sick', 'fever', 'leave', 'medical', 'ill', 'unwell', 'doctor', 'hospital', 'vacation', 'pto', 'absence', 'time off']):
            return {
                'intent': 'leave_request',
                'required_fields': ['name'],
                'optional_fields': ['job_title', 'employee_id', 'manager_name', 'phone', 'company'],
                'all_fields': ['name', 'job_title', 'employee_id', 'manager_name', 'phone', 'company'],
            }

        # Check Job Application
        if any(w in lower_ctx for w in ['job', 'apply', 'applying', 'application', 'developer', 'engineer', 'resume', 'cv', 'hiring', 'interview', 'internship', 'position', 'role']):
            return {
                'intent': 'job_application',
                'required_fields': ['name'],
                'optional_fields': ['degree', 'college', 'department', 'skills', 'github', 'portfolio', 'phone', 'email'],
                'all_fields': ['name', 'degree', 'college', 'department', 'skills', 'github', 'portfolio', 'phone', 'email'],
            }

        # Check Meeting / Client
        if any(w in lower_ctx for w in ['meeting', 'client', 'discuss', 'demo', 'appointment', 'consultation', 'sync']):
            return {
                'intent': 'meeting_request',
                'required_fields': ['name'],
                'optional_fields': ['job_title', 'company', 'email', 'phone'],
                'all_fields': ['name', 'job_title', 'company', 'email', 'phone'],
            }

        # General / Thank you / Other
        return {
            'intent': 'general',
            'required_fields': ['name'],
            'optional_fields': [],
            'all_fields': ['name'],
        }
