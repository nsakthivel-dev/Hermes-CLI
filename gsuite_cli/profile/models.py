"""
Data models for Personal Profile module.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime
import uuid


@dataclass
class BasicInfo:
    """Basic personal information"""
    fullName: str = ''
    firstName: str = ''
    lastName: str = ''
    displayName: str = ''
    dateOfBirth: str = ''  # Optional, sensitive


@dataclass
class ContactInfo:
    """Contact information"""
    primaryEmail: str = ''
    personalEmail: str = ''
    workEmail: str = ''
    phone: str = ''        # Sensitive
    alternatePhone: str = ''


@dataclass
class Address:
    """Address record supporting multiple locations (Home, College, Work, Other)"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    label: str = 'Home'
    street: str = ''
    city: str = ''
    state: str = ''
    country: str = ''
    postalCode: str = ''

    def to_formatted_string(self) -> str:
        """Format address as a readable string."""
        parts = [self.street, self.city, self.state, self.postalCode, self.country]
        return ", ".join(p.strip() for p in parts if p and p.strip())


@dataclass
class ProfessionalInfo:
    """Professional information"""
    jobTitle: str = ''
    company: str = ''
    department: str = ''
    experience: str = ''
    skills: List[str] = field(default_factory=list)
    github: str = ''
    linkedin: str = ''
    portfolio: str = ''
    website: str = ''


@dataclass
class EducationInfo:
    """Education record supporting multiple institutions"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    institution: str = ''
    degree: str = ''
    department: str = ''
    university: str = ''
    year: str = ''
    studentId: str = ''  # Sensitive


@dataclass
class CustomField:
    """User-defined custom field"""
    key: str = ''
    displayName: str = ''
    value: str = ''
    sensitivity: bool = False
    autoUse: bool = True


@dataclass
class ProfileSnippet:
    """Reusable text template snippet with profile variables"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ''
    content: str = ''
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class PrivacySettings:
    """Privacy and security configuration for Personal Profile"""
    auto_use_fields: Dict[str, bool] = field(default_factory=lambda: {
        'name': True,
        'email': True,
        'college': True,
        'degree': True,
        'github': True,
        'linkedin': True,
        'portfolio': True,
        'phone': False,
        'address': False,
        'studentId': False,
        'dateOfBirth': False,
    })
    sensitive_fields: List[str] = field(default_factory=lambda: [
        'phone',
        'alternatePhone',
        'address',
        'dateOfBirth',
        'studentId',
    ])
    require_confirmation: bool = True
    is_locked: bool = False


@dataclass
class PersonalProfile:
    """Root Personal Profile entity containing all categories"""
    basic: BasicInfo = field(default_factory=BasicInfo)
    contact: ContactInfo = field(default_factory=ContactInfo)
    addresses: List[Address] = field(default_factory=list)
    professional: ProfessionalInfo = field(default_factory=ProfessionalInfo)
    education: List[EducationInfo] = field(default_factory=list)
    custom_fields: List[CustomField] = field(default_factory=list)
    snippets: List[ProfileSnippet] = field(default_factory=list)
    privacy: PrivacySettings = field(default_factory=PrivacySettings)

    def to_dict(self) -> Dict[str, Any]:
        """Convert entire profile to serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PersonalProfile':
        """Construct PersonalProfile from dictionary safely."""
        if not isinstance(data, dict):
            return cls()

        basic_data = data.get('basic', {})
        basic = BasicInfo(**{k: v for k, v in basic_data.items() if k in BasicInfo.__dataclass_fields__}) if isinstance(basic_data, dict) else BasicInfo()

        contact_data = data.get('contact', {})
        contact = ContactInfo(**{k: v for k, v in contact_data.items() if k in ContactInfo.__dataclass_fields__}) if isinstance(contact_data, dict) else ContactInfo()

        addresses = []
        for a in data.get('addresses', []):
            if isinstance(a, dict):
                addresses.append(Address(**{k: v for k, v in a.items() if k in Address.__dataclass_fields__}))

        prof_data = data.get('professional', {})
        if isinstance(prof_data, dict):
            prof_filtered = {k: v for k, v in prof_data.items() if k in ProfessionalInfo.__dataclass_fields__}
            if isinstance(prof_filtered.get('skills'), str):
                prof_filtered['skills'] = [s.strip() for s in prof_filtered['skills'].split(',') if s.strip()]
            professional = ProfessionalInfo(**prof_filtered)
        else:
            professional = ProfessionalInfo()

        education = []
        for e in data.get('education', []):
            if isinstance(e, dict):
                education.append(EducationInfo(**{k: v for k, v in e.items() if k in EducationInfo.__dataclass_fields__}))

        custom_fields = []
        for c in data.get('custom_fields', []):
            if isinstance(c, dict):
                custom_fields.append(CustomField(**{k: v for k, v in c.items() if k in CustomField.__dataclass_fields__}))

        snippets = []
        for s in data.get('snippets', []):
            if isinstance(s, dict):
                snippets.append(ProfileSnippet(**{k: v for k, v in s.items() if k in ProfileSnippet.__dataclass_fields__}))

        priv_data = data.get('privacy', {})
        privacy = PrivacySettings(**{k: v for k, v in priv_data.items() if k in PrivacySettings.__dataclass_fields__}) if isinstance(priv_data, dict) else PrivacySettings()

        return cls(
            basic=basic,
            contact=contact,
            addresses=addresses,
            professional=professional,
            education=education,
            custom_fields=custom_fields,
            snippets=snippets,
            privacy=privacy,
        )
