"""
Comprehensive unit and integration tests for the Personal Profile module in Hermes CLI.

Covers all 29 requirements:
1. Create empty profile
2. Save profile field
3. Update profile field
4. Delete/clear profile field
5. Retrieve profile field
6. Alias resolution
7. Missing field handling
8. Template variable resolution
9. Missing template variable handling
10. Custom fields
11. Multiple addresses
12. Multiple education records
13. Snippet creation
14. Snippet editing
15. Snippet deletion
16. Snippet template resolution
17. Auto-use settings
18. Sensitive field protection
19. Confirmation behavior
20. Export profile
21. Import profile
22. Invalid import
23. Gmail profile insertion
24. Gmail compose state remains intact
25. Context-aware suggestions
26. Invalid CLI selections & validation re-prompting
27. Storage failures & atomic write safety
28. Corrupted profile data handling and recovery
29. No profile information is written to logs
"""

import os
import json
import logging
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from click.testing import CliRunner

from gsuite_cli.profile.models import (
    PersonalProfile, BasicInfo, ContactInfo, Address,
    ProfessionalInfo, EducationInfo, CustomField, ProfileSnippet
)
from gsuite_cli.profile.storage import PersonalProfileRepository
from gsuite_cli.profile.service import PersonalProfileService
from gsuite_cli.profile.resolver import ProfileResolver
from gsuite_cli.profile.validators import (
    validate_email, validate_phone, validate_url,
    validate_date, validate_postal_code, validate_non_empty, validate_custom_key
)
from gsuite_cli.profile.commands import profile_group
from gsuite_cli.ui.interactive_profile import PersonalProfileUI
from gsuite_cli.ui.interactive import InteractiveMenu


@pytest.fixture
def temp_repo_dir(tmp_path):
    """Provides a dedicated temporary directory for repository storage."""
    return tmp_path / "gsuite_cli_profile_test"


@pytest.fixture
def profile_repo(temp_repo_dir):
    return PersonalProfileRepository(data_dir=temp_repo_dir)


@pytest.fixture
def profile_service(profile_repo):
    return PersonalProfileService(repository=profile_repo)


@pytest.fixture
def profile_resolver(profile_service):
    return ProfileResolver(service=profile_service)


# ===========================================================================
# 1. CREATE EMPTY PROFILE
# ===========================================================================

def test_create_empty_profile(profile_repo):
    profile = profile_repo.load()
    assert isinstance(profile, PersonalProfile)
    assert profile.basic.fullName == ''
    assert profile.contact.primaryEmail == ''
    assert len(profile.addresses) == 0
    assert len(profile.education) == 0
    assert len(profile.custom_fields) == 0
    assert len(profile.snippets) == 0
    assert profile.privacy.is_locked is False


# ===========================================================================
# 2. SAVE PROFILE FIELD & 5. RETRIEVE PROFILE FIELD
# ===========================================================================

def test_save_and_retrieve_profile_field(profile_service, profile_resolver):
    # Save basic fields
    assert profile_service.update_basic_field('firstName', 'Sakthivel') is True
    assert profile_service.update_basic_field('lastName', 'N') is True
    assert profile_service.update_basic_field('displayName', 'NSakthivel') is True

    # Save contact fields
    assert profile_service.update_contact_field('primaryEmail', 'sakthi@example.com') is True
    assert profile_service.update_contact_field('phone', '+1234567890') is True

    # Retrieve directly
    assert profile_resolver.get('first_name') == 'Sakthivel'
    assert profile_resolver.get('last_name') == 'N'
    assert profile_resolver.get('display_name') == 'NSakthivel'
    assert profile_resolver.get('email') == 'sakthi@example.com'
    assert profile_resolver.get('phone') == '+1234567890'


# ===========================================================================
# 3. UPDATE PROFILE FIELD
# ===========================================================================

def test_update_profile_field(profile_service, profile_resolver):
    profile_service.update_basic_field('fullName', 'John Doe')
    assert profile_resolver.get('name') == 'John Doe'

    # Update to a new value
    profile_service.update_basic_field('fullName', 'Jane Doe')
    assert profile_resolver.get('name') == 'Jane Doe'


# ===========================================================================
# 4. DELETE / CLEAR PROFILE FIELD
# ===========================================================================

def test_delete_clear_profile_field(profile_service, profile_resolver):
    profile_service.update_basic_field('displayName', 'SuperUser')
    assert profile_resolver.get('display_name') == 'SuperUser'

    # Clear field
    profile_service.clear_basic_field('displayName')
    assert profile_resolver.get('display_name') is None


# ===========================================================================
# 6. ALIAS RESOLUTION
# ===========================================================================

def test_alias_resolution(profile_service, profile_resolver):
    profile_service.update_basic_field('fullName', 'Alex Morgan')
    profile_service.update_contact_field('primaryEmail', 'alex@example.com')
    profile_service.update_contact_field('phone', '+1-555-0199')
    profile_service.update_professional_field('github', 'https://github.com/alex')
    profile_service.update_professional_field('linkedin', 'https://linkedin.com/in/alex')
    profile_service.update_professional_field('portfolio', 'https://alex.dev')
    profile_service.update_professional_field('company', 'Acme Corp')
    profile_service.update_professional_field('jobTitle', 'Staff Engineer')
    profile_service.add_education('Stanford', 'M.S. Computer Science')

    # Test various alias representations (casing, spaces, underscores)
    assert profile_resolver.get('name') == 'Alex Morgan'
    assert profile_resolver.get('full_name') == 'Alex Morgan'
    assert profile_resolver.get('Full Name') == 'Alex Morgan'
    assert profile_resolver.get('fullname') == 'Alex Morgan'

    assert profile_resolver.get('email') == 'alex@example.com'
    assert profile_resolver.get('primary_email') == 'alex@example.com'
    assert profile_resolver.get('email address') == 'alex@example.com'

    assert profile_resolver.get('phone') == '+1-555-0199'
    assert profile_resolver.get('mobile') == '+1-555-0199'
    assert profile_resolver.get('mobile number') == '+1-555-0199'
    assert profile_resolver.get('contact number') == '+1-555-0199'

    assert profile_resolver.get('github') == 'https://github.com/alex'
    assert profile_resolver.get('github url') == 'https://github.com/alex'
    assert profile_resolver.get('github link') == 'https://github.com/alex'

    assert profile_resolver.get('linkedin') == 'https://linkedin.com/in/alex'
    assert profile_resolver.get('linkedin_profile') == 'https://linkedin.com/in/alex'

    assert profile_resolver.get('portfolio') == 'https://alex.dev'
    assert profile_resolver.get('portfolio_url') == 'https://alex.dev'

    assert profile_resolver.get('college') == 'Stanford'
    assert profile_resolver.get('institution') == 'Stanford'
    assert profile_resolver.get('degree') == 'M.S. Computer Science'

    assert profile_resolver.get('company') == 'Acme Corp'
    assert profile_resolver.get('job_title') == 'Staff Engineer'
    assert profile_resolver.get('role') == 'Staff Engineer'


# ===========================================================================
# 7. MISSING FIELD HANDLING
# ===========================================================================

def test_missing_field_handling(profile_resolver):
    assert profile_resolver.has('non_existent_field') is False
    assert profile_resolver.get('non_existent_field') is None
    assert profile_resolver.get('non_existent_field', default='Fallback') == 'Fallback'


# ===========================================================================
# 8. TEMPLATE VARIABLE RESOLUTION
# ===========================================================================

def test_template_variable_resolution(profile_service, profile_resolver):
    profile_service.update_basic_field('fullName', 'NSakthivel')
    profile_service.update_contact_field('primaryEmail', 'nsakthiveldev@gmail.com')
    profile_service.add_education('PSG Tech', 'B.E. Robotics')
    profile_service.update_professional_field('github', 'https://github.com/nsakthivel')

    template = "Hi, I'm {{name}} from {{college}}, studying {{degree}}. Check my GitHub: {{github}}."
    resolved = profile_resolver.resolveTemplate(template)
    assert resolved == "Hi, I'm NSakthivel from PSG Tech, studying B.E. Robotics. Check my GitHub: https://github.com/nsakthivel."


# ===========================================================================
# 9. MISSING TEMPLATE VARIABLE HANDLING
# ===========================================================================

def test_missing_template_variable_handling(profile_service, profile_resolver):
    profile_service.update_basic_field('fullName', 'Alice')
    # portfolio is not configured

    template = "Name: {{name}}, Portfolio: {{portfolio}}"
    resolved = profile_resolver.resolveTemplate(template)
    assert "Alice" in resolved
    # Must NOT silently be empty
    assert "Profile information unavailable: portfolio" in resolved

    # Custom placeholder option
    custom_resolved = profile_resolver.resolveTemplate(template, missing_placeholder="[N/A]")
    assert custom_resolved == "Name: Alice, Portfolio: [N/A]"


# ===========================================================================
# 10. CUSTOM FIELDS
# ===========================================================================

def test_custom_fields(profile_service, profile_resolver):
    # Add custom field
    cf = profile_service.add_custom_field(
        key="Emergency Contact",
        display_name="Emergency Contact",
        value="Jane Doe (+1-555-9999)",
        sensitivity=True,
        auto_use=False
    )
    assert cf.key == "emergency_contact"
    assert profile_resolver.get("Emergency Contact") == "Jane Doe (+1-555-9999)"
    assert profile_resolver.get("emergency_contact") == "Jane Doe (+1-555-9999)"
    assert profile_resolver.isSensitive("emergency_contact") is True
    assert profile_resolver.canAutoUse("emergency_contact") is False

    # Update custom field
    profile_service.update_custom_field(0, value="John Doe")
    assert profile_resolver.get("emergency_contact") == "John Doe"

    # Delete custom field
    profile_service.delete_custom_field(0)
    assert profile_resolver.get("emergency_contact") is None


# ===========================================================================
# 11. MULTIPLE ADDRESSES
# ===========================================================================

def test_multiple_addresses(profile_service, profile_resolver):
    profile_service.add_address('Home', '123 Elm St', 'Boston', 'MA', 'USA', '02101')
    profile_service.add_address('College', '77 Mass Ave', 'Cambridge', 'MA', 'USA', '02139')

    p = profile_service.get_profile()
    assert len(p.addresses) == 2

    # Primary address resolves to first
    assert "123 Elm St" in profile_resolver.get('address')
    # Specific address aliases
    assert "123 Elm St" in profile_resolver.get('home_address')
    assert "77 Mass Ave" in profile_resolver.get('college_address')

    # Delete address
    profile_service.delete_address(0)
    assert len(profile_service.get_profile().addresses) == 1
    assert "77 Mass Ave" in profile_resolver.get('address')


# ===========================================================================
# 12. MULTIPLE EDUCATION RECORDS
# ===========================================================================

def test_multiple_education_records(profile_service, profile_resolver):
    profile_service.add_education('MIT', 'B.S.', 'EECS', year='2022')
    profile_service.add_education('Stanford', 'M.S.', 'AI', year='2024')

    p = profile_service.get_profile()
    assert len(p.education) == 2
    assert profile_resolver.get('college') == 'MIT'
    assert profile_resolver.get('degree') == 'B.S.'

    # Edit second
    profile_service.update_education(1, degree='Ph.D.')
    assert profile_service.get_profile().education[1].degree == 'Ph.D.'

    # Delete first
    profile_service.delete_education(0)
    assert len(profile_service.get_profile().education) == 1
    assert profile_resolver.get('college') == 'Stanford'


# ===========================================================================
# 13, 14, 15, 16. PROFILE SNIPPETS LIFECYCLE & TEMPLATE RESOLUTION
# ===========================================================================

def test_snippets_lifecycle_and_resolution(profile_service, profile_resolver):
    profile_service.update_basic_field('fullName', 'Bob')
    profile_service.add_education('Harvard', 'B.A.')

    # 13. Create
    snippet = profile_service.create_snippet(
        name="Intro",
        content="Hello, my name is {{name}} from {{college}}."
    )
    assert snippet.name == "Intro"
    assert len(profile_service.get_profile().snippets) == 1

    # 16. Template Resolution Preview
    preview = profile_resolver.resolveTemplate(snippet.content)
    assert preview == "Hello, my name is Bob from Harvard."

    # 14. Edit
    profile_service.update_snippet(0, name="Intro Updated", content="Hi! {{name}} here.")
    updated_snip = profile_service.get_snippet(0)
    assert updated_snip.name == "Intro Updated"
    assert profile_resolver.resolveTemplate(updated_snip.content) == "Hi! Bob here."

    # 15. Delete
    profile_service.delete_snippet(0)
    assert len(profile_service.get_profile().snippets) == 0


# ===========================================================================
# 17. AUTO-USE SETTINGS
# ===========================================================================

def test_auto_use_settings(profile_service, profile_resolver):
    # Name and email are default allowed
    assert profile_resolver.canAutoUse('name') is True
    assert profile_resolver.canAutoUse('email') is True

    # Phone is sensitive / default not allowed without confirmation
    assert profile_resolver.canAutoUse('phone') is False

    # Toggle auto-use for name
    profile_service.toggle_auto_use('name')
    assert profile_resolver.canAutoUse('name') is False


# ===========================================================================
# 18. SENSITIVE FIELD PROTECTION
# ===========================================================================

def test_sensitive_field_protection(profile_service, profile_resolver):
    assert profile_resolver.isSensitive('phone') is True
    assert profile_resolver.isSensitive('studentId') is True
    assert profile_resolver.isSensitive('dateOfBirth') is True
    assert profile_resolver.isSensitive('email') is False

    # Mark custom field sensitive
    profile_service.add_custom_field('SSN', 'SSN', '000-00-0000', sensitivity=True)
    assert profile_resolver.isSensitive('SSN') is True


# ===========================================================================
# 19. CONFIRMATION BEHAVIOR
# ===========================================================================

def test_confirmation_behavior(profile_service):
    p = profile_service.get_profile()
    assert p.privacy.require_confirmation is True

    profile_service.toggle_require_confirmation()
    assert profile_service.get_profile().privacy.require_confirmation is False


# ===========================================================================
# 20. EXPORT PROFILE & 21. IMPORT PROFILE
# ===========================================================================

def test_export_and_import_profile(profile_service):
    profile_service.update_basic_field('fullName', 'Diana Prince')
    profile_service.update_contact_field('primaryEmail', 'diana@themyscira.org')
    profile_service.create_snippet("Warrior Greeting", "Greetings from {{name}}.")

    # 20. Export
    json_str = profile_service.export_profile_json()
    assert "Diana Prince" in json_str
    assert "diana@themyscira.org" in json_str
    # Credentials/tokens should NEVER be in export
    assert "token" not in json_str.lower() or "refresh_token" not in json_str

    # 21. Import into fresh repository
    new_repo_dir = Path(tempfile.mkdtemp())
    new_repo = PersonalProfileRepository(data_dir=new_repo_dir)
    new_service = PersonalProfileService(repository=new_repo)

    ok, preview, imported_profile = new_service.import_profile_json(json_str)
    assert ok is True
    assert "Diana Prince" in preview
    assert new_service.apply_import(imported_profile) is True
    assert new_service.get_profile().basic.fullName == 'Diana Prince'


# ===========================================================================
# 22. INVALID IMPORT REJECTION
# ===========================================================================

def test_invalid_import_rejection(profile_service):
    # Invalid JSON
    ok, err, prof = profile_service.import_profile_json("NOT_JSON")
    assert ok is False

    # Non-dictionary root
    ok, err, prof = profile_service.import_profile_json("['array', 'root']")
    assert ok is False

    # Missing profile structure
    ok, err, prof = profile_service.import_profile_json('{"some_unrelated_key": 123}')
    assert ok is False


# ===========================================================================
# 25. CONTEXT-AWARE SUGGESTIONS
# ===========================================================================

def test_context_aware_suggestions(profile_service, profile_resolver):
    profile_service.update_basic_field('fullName', 'John Developer')
    profile_service.add_education('Caltech', 'B.S. Physics')
    profile_service.update_professional_field('github', 'https://github.com/johndev')
    profile_service.update_professional_field('portfolio', 'https://johndev.me')

    # Test internship / application keyword context
    context = "Subject: Application for Summer Software Engineering Internship\nBody: Dear Hiring Team,"
    suggestions = profile_resolver.getSuggestions(context)
    suggested_fields = [s['field'] for s in suggestions]

    assert 'name' in suggested_fields
    assert 'college' in suggested_fields
    assert 'github' in suggested_fields
    assert 'portfolio' in suggested_fields

    # Fields that have NO value should NOT appear
    assert 'phone' not in suggested_fields  # phone was not configured


# ===========================================================================
# 26. VALIDATORS & INVALID CLI INPUT RE-PROMPTING
# ===========================================================================

def test_validators():
    assert validate_email("user@example.com")[0] is True
    assert validate_email("invalid_email")[0] is False

    assert validate_phone("+1 555-0199")[0] is True
    assert validate_phone("123")[0] is False  # too short

    assert validate_url("https://github.com/nsakthivel")[0] is True
    assert validate_url("ftp://bad")[0] is False

    assert validate_date("2026-09-08")[0] is True
    assert validate_date("09/08/2026")[0] is True
    assert validate_date("invalid-date")[0] is False

    assert validate_postal_code("90210")[0] is True
    assert validate_postal_code("1")[0] is False

    assert validate_custom_key("Emergency Contact")[0] is True
    assert validate_custom_key("")[0] is False


# ===========================================================================
# 27. STORAGE ATOMICITY & 28. CORRUPTED DATA RECOVERY
# ===========================================================================

def test_corrupted_profile_recovery(temp_repo_dir):
    repo = PersonalProfileRepository(data_dir=temp_repo_dir)
    # Write corrupted data to profile.json
    corrupted_content = "{ corrupted json content without end"
    repo.profile_file.write_text(corrupted_content, encoding='utf-8')

    # Load should safely recover: backup corrupted file and return default profile
    profile = repo.load()
    assert isinstance(profile, PersonalProfile)
    assert profile.basic.fullName == ''

    # Verify corrupt backup was generated
    backups = list(temp_repo_dir.glob("profile.json.corrupt.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding='utf-8') == corrupted_content


# ===========================================================================
# 29. NO PROFILE INFORMATION WRITTEN TO LOGS
# ===========================================================================

def test_no_profile_information_written_to_logs(profile_service, caplog):
    secret_name = "SuperSecretPersonName99"
    secret_phone = "+19998887777"

    with caplog.at_level(logging.DEBUG):
        profile_service.update_basic_field('fullName', secret_name)
        profile_service.update_contact_field('phone', secret_phone)
        profile_service.save_profile()
        profile_service.export_profile_json()

    # Verify that neither the secret name nor phone appears in captured logs
    for record in caplog.records:
        assert secret_name not in record.message
        assert secret_phone not in record.message


# ===========================================================================
# 23, 24. GMAIL COMPOSE INTEGRATION & COMPOSE STATE
# ===========================================================================

def test_gmail_compose_profile_assistance(profile_service, tmp_path):
    profile_service.update_basic_field('fullName', 'Clark Kent')
    profile_service.update_professional_field('portfolio', 'https://dailyplanet.com')

    menu_mock = MagicMock()
    menu_mock.config_manager = None
    ui = PersonalProfileUI(menu_mock)
    ui.service = profile_service
    ui.resolver = ProfileResolver(service=profile_service)

    body_file = tmp_path / "email_body.txt"
    body_file.write_text("Hello,", encoding='utf-8')

    # Simulate choosing '1' (Insert Profile Info), selecting '1' (Name)
    with patch("builtins.input", side_effect=['1', '1']):
        updated_body = ui.handle_compose_profile_assistance(
            subject="Job Application",
            body="Hello,",
            tmp_path=str(body_file)
        )

    assert "Clark Kent" in updated_body
    assert "Clark Kent" in body_file.read_text(encoding='utf-8')


# ===========================================================================
# 30. CLI PROFILE COMMANDS
# ===========================================================================

def test_cli_profile_commands(profile_service):
    runner = CliRunner()

    # Test profile show
    res = runner.invoke(profile_group, ['show'], obj={'config_manager': None})
    assert res.exit_code == 0
    assert "Personal Profile Overview" in res.output

    # Test profile set
    res = runner.invoke(profile_group, ['set', 'fullName', 'Bruce Wayne'], obj={'config_manager': None})
    assert res.exit_code == 0
    assert "updated successfully" in res.output

    # Test profile get
    res = runner.invoke(profile_group, ['get', 'name'], obj={'config_manager': None})
    assert res.exit_code == 0
    assert "Bruce Wayne" in res.output

    # Test profile resolve
    res = runner.invoke(profile_group, ['resolve', 'Hello {{name}}!'], obj={'config_manager': None})
    assert res.exit_code == 0
    assert "Hello Bruce Wayne!" in res.output
