"""
Unit and integration tests for AI Email Composer and Personal Profile integration.
Validates all 20 requirements:
1. AI composer detects relevant profile fields based on context.
2. ProfileResolver is used as the single interface.
3. AI Composer does not directly access profile storage.
4. Existing profile values replace placeholders.
5. Missing optional fields are omitted cleanly.
6. Missing required information is handled correctly.
7. No profile data is invented.
8. User-provided information overrides profile values.
9. Sensitive information respects privacy settings.
10. Only relevant profile fields are passed to AI (no profile dumping).
11. Complete profile is never blindly passed to AI.
12. Existing Gmail compose still works.
13. Edit still works.
14. Discard still works.
15. Send still works.
16. Profile changes are not caused by email editing.
17. Existing AI compose behavior continues working when Personal Profile is empty.
18. AI Composer works when ProfileResolver returns no data.
19. AI Composer works when only partial profile data exists.
20. Placeholder generation is prevented when profile data is available.
"""

import json
from unittest.mock import MagicMock, patch
import pytest
from click.testing import CliRunner

from gsuite_cli.profile.models import (
    PersonalProfile, BasicInfo, ContactInfo,
    ProfessionalInfo, EducationInfo, CustomField
)
from gsuite_cli.profile.storage import PersonalProfileRepository
from gsuite_cli.profile.service import PersonalProfileService
from gsuite_cli.profile.resolver import ProfileResolver
from gsuite_cli.ai.nlp import NaturalLanguageProcessor
from gsuite_cli.ai.commands import ai, _extract_prompt_overrides


@pytest.fixture
def mock_repo_dir(tmp_path):
    return tmp_path / "gsuite_cli_ai_test"


@pytest.fixture
def populated_profile_repo(mock_repo_dir):
    repo = PersonalProfileRepository(data_dir=mock_repo_dir)
    profile = PersonalProfile(
        basic=BasicInfo(fullName="NSakthivel", firstName="NSakthivel"),
        contact=ContactInfo(primaryEmail="sakthi@example.com", phone="9876543210"),
        professional=ProfessionalInfo(
            jobTitle="Software Developer",
            company="Acme Corp",
            skills=["Python", "Cloud", "CLI"],
            github="https://github.com/sakthi"
        ),
        education=[EducationInfo(
            institution="PSG Tech",
            degree="B.Tech",
            department="Computer Science",
            studentId="REG12345"
        )],
        custom_fields=[
            CustomField(key="employee_id", displayName="Employee ID", value="EMP1024", sensitivity=True),
            CustomField(key="manager_name", displayName="Manager", value="John", sensitivity=False)
        ]
    )
    repo.save(profile)
    return repo


@pytest.fixture
def empty_profile_repo(mock_repo_dir):
    repo = PersonalProfileRepository(data_dir=mock_repo_dir)
    repo.save(PersonalProfile())
    return repo


# ===========================================================================
# 1. AI COMPOSER DETECTS RELEVANT PROFILE FIELDS
# ===========================================================================

def test_detect_relevant_fields_sick_leave():
    resolver = ProfileResolver()
    ctx = resolver.get_context_fields("write a mail to hr for fever leave")
    assert ctx['intent'] == 'leave_request'
    assert 'name' in ctx['required_fields']
    assert set(ctx['optional_fields']) == {'job_title', 'employee_id', 'manager_name', 'phone', 'company'}


def test_detect_relevant_fields_job_application():
    resolver = ProfileResolver()
    ctx = resolver.get_context_fields("write a mail applying for software developer job")
    assert ctx['intent'] == 'job_application'
    assert 'degree' in ctx['optional_fields']
    assert 'skills' in ctx['optional_fields']
    assert 'github' in ctx['optional_fields']
    assert 'employee_id' not in ctx['optional_fields']


def test_detect_relevant_fields_college_request():
    resolver = ProfileResolver()
    ctx = resolver.get_context_fields("write a mail to my HOD requesting leave")
    assert ctx['intent'] == 'college_request'
    assert 'student_id' in ctx['optional_fields']
    assert 'college' in ctx['optional_fields']
    assert 'job_title' not in ctx['optional_fields']


def test_detect_relevant_fields_meeting():
    resolver = ProfileResolver()
    ctx = resolver.get_context_fields("write a mail to client requesting a meeting")
    assert ctx['intent'] == 'meeting_request'
    assert 'company' in ctx['optional_fields']
    assert 'student_id' not in ctx['optional_fields']


def test_detect_relevant_fields_thank_you():
    resolver = ProfileResolver()
    ctx = resolver.get_context_fields("write a short thank-you email")
    assert ctx['intent'] == 'general'
    assert ctx['required_fields'] == ['name']
    assert ctx['optional_fields'] == []


# ===========================================================================
# 2. PROFILE RESOLVER IS USED AS SINGLE INTERFACE
# ===========================================================================

def test_profile_resolver_retrieval(populated_profile_repo):
    service = PersonalProfileService(repository=populated_profile_repo)
    resolver = ProfileResolver(service=service)

    assert resolver.get('name') == "NSakthivel"
    assert resolver.get('job_title') == "Software Developer"
    assert resolver.get('employee_id') == "EMP1024"
    assert resolver.get('manager_name') == "John"
    assert resolver.get('phone') == "9876543210"
    assert resolver.get('non_existent') is None


# ===========================================================================
# 3. AI COMPOSER DOES NOT DIRECTLY ACCESS PROFILE STORAGE
# ===========================================================================

def test_ai_composer_uses_profile_resolver_mock():
    runner = CliRunner()
    with patch('gsuite_cli.ai.commands.ProfileResolver') as MockResolver, \
         patch('gsuite_cli.ai.commands.NaturalLanguageProcessor') as MockNLP:
        
        mock_res_instance = MockResolver.return_value
        mock_res_instance.get_context_fields.return_value = {
            'intent': 'general',
            'required_fields': ['name'],
            'optional_fields': [],
            'all_fields': ['name'],
        }
        mock_res_instance.get.return_value = 'Sakthi'
        mock_res_instance.canAutoUse.return_value = True

        mock_nlp = MockNLP.return_value
        mock_nlp.draft_email.return_value = {
            'subject': 'Thanks',
            'body': 'Thank you! Sincerely, Sakthi'
        }

        result = runner.invoke(ai, ['compose', 'write a thank you mail'], input='discard\n')
        assert result.exit_code == 0
        # Verify ProfileResolver methods were called
        mock_res_instance.get_context_fields.assert_called_once()
        mock_res_instance.get.assert_called_with('name')


# ===========================================================================
# 4. EXISTING PROFILE VALUES REPLACE PLACEHOLDERS
# ===========================================================================

def test_profile_values_replace_placeholders():
    nlp = NaturalLanguageProcessor()
    raw_draft = {
        'subject': 'Leave Application - [Your Name]',
        'body': 'Dear HR,\n\nI am on leave. Reached at [Your Phone Number]. Supervisor is [Manager\'s Name].\n\n[Your Name]\n[Your Job Title]\n[Your Employee ID]'
    }
    profile_ctx = {
        'name': 'NSakthivel',
        'job_title': 'Software Developer',
        'employee_id': 'EMP1024',
        'manager_name': 'John',
        'phone': '9876543210',
    }
    sanitized = nlp._sanitize_draft(raw_draft, profile_context=profile_ctx)

    assert '[Your Name]' not in sanitized['subject']
    assert 'NSakthivel' in sanitized['subject']
    assert '[Your Name]' not in sanitized['body']
    assert '[Your Phone Number]' not in sanitized['body']
    assert '[Manager\'s Name]' not in sanitized['body']
    assert '[Your Job Title]' not in sanitized['body']
    assert '[Your Employee ID]' not in sanitized['body']
    assert 'NSakthivel' in sanitized['body']
    assert 'Software Developer' in sanitized['body']
    assert 'EMP1024' in sanitized['body']
    assert 'John' in sanitized['body']


# ===========================================================================
# 5. MISSING OPTIONAL FIELDS ARE OMITTED
# ===========================================================================

def test_missing_optional_fields_omitted():
    nlp = NaturalLanguageProcessor()
    raw_draft = {
        'subject': 'Leave Application',
        'body': 'Dear HR,\n\nI am unwell.\n\nSincerely,\n[Your Name]\n[Your Job Title]\n[Your Employee ID]'
    }
    profile_ctx = {
        'name': 'NSakthivel',
        # job_title and employee_id missing
    }
    sanitized = nlp._sanitize_draft(raw_draft, profile_context=profile_ctx)

    assert 'NSakthivel' in sanitized['body']
    assert '[Your Job Title]' not in sanitized['body']
    assert '[Your Employee ID]' not in sanitized['body']
    assert 'Software Developer' not in sanitized['body']


# ===========================================================================
# 6. MISSING REQUIRED INFORMATION HANDLED CORRECTLY
# ===========================================================================

def test_missing_required_handled_when_profile_empty():
    nlp = NaturalLanguageProcessor()
    raw_draft = {
        'subject': 'Leave Application - [Your Name]',
        'body': 'Dear HR,\n\nI am unwell and need rest.\n\nSincerely,\n[Your Name]'
    }
    # No profile data at all
    sanitized = nlp._sanitize_draft(raw_draft, profile_context={})
    assert '[Your Name]' not in sanitized['subject']
    assert '[Your Name]' not in sanitized['body']
    assert 'Sincerely,' in sanitized['body']


# ===========================================================================
# 7. NO PROFILE DATA IS INVENTED
# ===========================================================================

def test_prompt_instructs_gemini_not_to_invent_data():
    nlp = NaturalLanguageProcessor()
    nlp.gemini_client = MagicMock()
    nlp.gemini_client.is_available = True
    nlp.gemini_client.generate_content.return_value = '```json\n{"subject": "Sick Leave", "body": "I am sick."}\n```'

    nlp.draft_email("write a mail to hr for fever leave", profile_context={'name': 'NSakthivel'})

    call_args = nlp.gemini_client.generate_content.call_args[0][0]
    assert "DO NOT create or use bracketed placeholders" in call_args
    assert "DO NOT invent fake data" in call_args
    assert "NSakthivel" in call_args


# ===========================================================================
# 8. USER-PROVIDED INFORMATION OVERRIDES PROFILE VALUES
# ===========================================================================

def test_user_provided_info_overrides_profile():
    prompt = "write a leave mail to HR, my manager is John and I need leave for 2 days"
    overrides = _extract_prompt_overrides(prompt)
    assert overrides['manager_name'] == 'John'
    assert overrides['duration'] == '2 days'


# ===========================================================================
# 9. SENSITIVE INFORMATION RESPECTS PRIVACY SETTINGS
# ===========================================================================

def test_sensitive_info_privacy_masking(populated_profile_repo):
    service = PersonalProfileService(repository=populated_profile_repo)
    resolver = ProfileResolver(service=service)

    assert resolver.isSensitive('phone') is True
    assert resolver.isSensitive('employee_id') is True
    assert resolver.isSensitive('name') is False

    assert resolver.mask_value('phone', '9876543210') == '******3210'
    assert resolver.mask_value('employee_id', 'EMP1024') == '***1024'
    assert resolver.mask_value('name', 'NSakthivel') == 'NSakthivel'


def test_can_auto_use_respects_settings(populated_profile_repo):
    service = PersonalProfileService(repository=populated_profile_repo)
    resolver = ProfileResolver(service=service)

    # Phone is sensitive and require_confirmation is True by default
    assert resolver.canAutoUse('phone') is False
    assert resolver.canAutoUse('name') is True


# ===========================================================================
# 10. ONLY RELEVANT PROFILE FIELDS ARE PASSED TO AI
# 11. COMPLETE PROFILE IS NEVER BLINDLY PASSED TO AI
# ===========================================================================

def test_only_relevant_fields_passed_to_ai(populated_profile_repo):
    service = PersonalProfileService(repository=populated_profile_repo)
    resolver = ProfileResolver(service=service)

    # For a thank you mail, only 'name' should be retrieved and passed
    ctx = resolver.get_context_fields("write a short thank-you email")
    assert ctx['all_fields'] == ['name']

    # For sick leave, college / education / github / linkedin / address should NOT be retrieved
    leave_ctx = resolver.get_context_fields("write a mail to hr for fever leave")
    assert 'college' not in leave_ctx['all_fields']
    assert 'github' not in leave_ctx['all_fields']
    assert 'address' not in leave_ctx['all_fields']
    assert 'student_id' not in leave_ctx['all_fields']


# ===========================================================================
# 12. EXISTING GMAIL COMPOSE STILL WORKS
# 13. EDIT STILL WORKS
# 14. DISCARD STILL WORKS
# 15. SEND STILL WORKS
# 16. PROFILE CHANGES ARE NOT CAUSED BY EMAIL EDITING
# ===========================================================================

def test_compose_cli_discard(populated_profile_repo):
    runner = CliRunner()
    service = PersonalProfileService(repository=populated_profile_repo)

    with patch('gsuite_cli.ai.commands.PersonalProfileRepository', return_value=populated_profile_repo), \
         patch('gsuite_cli.ai.commands.NaturalLanguageProcessor') as MockNLP:
        
        mock_nlp = MockNLP.return_value
        mock_nlp.draft_email.return_value = {
            'subject': 'Sick Leave Application - Fever',
            'body': 'Dear HR,\n\nI am unwell.\n\nSincerely,\nNSakthivel'
        }

        # Select 'y' for confirmation if prompted, then 'discard'
        result = runner.invoke(ai, ['compose', 'write a mail to hr for fever leave', '--to', 'hr@example.com'], input='y\n3\ndiscard\n')
        assert result.exit_code == 0
        assert "Draft discarded." in result.output

    # Verify profile was NOT modified
    saved_profile = service.get_profile()
    assert saved_profile.basic.fullName == "NSakthivel"


def test_compose_cli_edit_flow_does_not_modify_profile(populated_profile_repo):
    runner = CliRunner()
    service = PersonalProfileService(repository=populated_profile_repo)

    with patch('gsuite_cli.ai.commands.PersonalProfileRepository', return_value=populated_profile_repo), \
         patch('gsuite_cli.ai.commands.NaturalLanguageProcessor') as MockNLP, \
         patch('click.edit') as mock_edit:
        
        mock_nlp = MockNLP.return_value
        mock_nlp.draft_email.return_value = {
            'subject': 'Sick Leave Application',
            'body': 'Dear HR,\n\nI am unwell.\n\nSincerely,\nNSakthivel'
        }
        # Simulate user editing the body from NSakthivel to Sakthi
        mock_edit.return_value = "TO: hr@example.com\nSUBJECT: Sick Leave Application\n\nDear HR,\n\nI am unwell.\n\nSincerely,\nSakthi"

        result = runner.invoke(ai, ['compose', 'write a mail to hr for fever leave', '--to', 'hr@example.com'], input='y\n3\nedit\ndiscard\n')
        assert result.exit_code == 0

    # Ensure profile remains completely unchanged
    saved_profile = service.get_profile()
    assert saved_profile.basic.fullName == "NSakthivel"


def test_compose_cli_send_flow(populated_profile_repo):
    runner = CliRunner()
    with patch('gsuite_cli.ai.commands.PersonalProfileRepository', return_value=populated_profile_repo), \
         patch('gsuite_cli.ai.commands.NaturalLanguageProcessor') as MockNLP, \
         patch('gsuite_cli.ai.commands.GmailService') as MockGmail:
        
        mock_nlp = MockNLP.return_value
        mock_nlp.draft_email.return_value = {
            'subject': 'Sick Leave Application - Fever',
            'body': 'Dear HR,\n\nI am unwell.\n\nSincerely,\nNSakthivel'
        }

        mock_gmail = MockGmail.return_value
        mock_gmail.send_message.return_value = {'id': 'msg_123'}

        result = runner.invoke(
            ai,
            ['compose', 'write a mail to hr for fever leave', '--to', 'hr@example.com'],
            input='y\n3\nsend\n',
            obj={'oauth_manager': MagicMock()}
        )
        assert result.exit_code == 0
        assert "Email successfully sent to hr@example.com!" in result.output
        mock_gmail.send_message.assert_called_once_with(
            to='hr@example.com',
            subject='Sick Leave Application - Fever',
            body='Dear HR,\n\nI am unwell.\n\nSincerely,\nNSakthivel'
        )


# ===========================================================================
# 17. EMPTY PERSONAL PROFILE CONTINUES WORKING
# 18. PROFILE RESOLVER RETURNS NO DATA
# ===========================================================================

def test_compose_cli_empty_profile(empty_profile_repo):
    runner = CliRunner()
    with patch('gsuite_cli.ai.commands.PersonalProfileRepository', return_value=empty_profile_repo), \
         patch('gsuite_cli.ai.commands.NaturalLanguageProcessor') as MockNLP:
        
        mock_nlp = MockNLP.return_value
        mock_nlp.draft_email.return_value = {
            'subject': 'Sick Leave Application - Fever',
            'body': 'Dear HR,\n\nI am unwell.\n\nSincerely,'
        }

        result = runner.invoke(ai, ['compose', 'write a mail to hr for fever leave', '--to', 'hr@example.com'], input='3\ndiscard\n')
        assert result.exit_code == 0
        assert "⚠ Name not available" in result.output
        assert "Draft discarded." in result.output


# ===========================================================================
# 19. PARTIAL PROFILE DATA
# ===========================================================================

def test_compose_cli_partial_profile(mock_repo_dir):
    partial_repo = PersonalProfileRepository(data_dir=mock_repo_dir)
    partial_repo.save(PersonalProfile(
        basic=BasicInfo(fullName="Sakthi"),
        # no job title, no employee id, no manager
    ))

    runner = CliRunner()
    with patch('gsuite_cli.ai.commands.PersonalProfileRepository', return_value=partial_repo), \
         patch('gsuite_cli.ai.commands.NaturalLanguageProcessor') as MockNLP:
        
        mock_nlp = MockNLP.return_value
        mock_nlp.draft_email.return_value = {
            'subject': 'Sick Leave Application',
            'body': 'Dear HR,\n\nI am unwell.\n\nSincerely,\nSakthi'
        }

        result = runner.invoke(ai, ['compose', 'write a mail to hr for fever leave', '--to', 'hr@example.com'], input='3\ndiscard\n')
        assert result.exit_code == 0
        assert "✓ Name" in result.output
        assert "⚠ Job Title not available" in result.output
        assert "⚠ Employee Id not available" in result.output


# ===========================================================================
# 20. PLACEHOLDER GENERATION PREVENTED WHEN PROFILE DATA IS AVAILABLE
# ===========================================================================

def test_placeholder_generation_prevented_in_full_flow(populated_profile_repo):
    runner = CliRunner()
    with patch('gsuite_cli.ai.commands.PersonalProfileRepository', return_value=populated_profile_repo), \
         patch('gsuite_cli.ai.commands.NaturalLanguageProcessor') as MockNLP:
        
        # Suppose LLM naively emitted placeholders
        def fake_draft(prompt, profile_context=None, email_context=None):
            nlp = NaturalLanguageProcessor()
            raw = {
                'subject': 'Sick Leave Application - Fever - [Your Name]',
                'body': (
                    "Dear HR Team,\n\n"
                    "I am unwell with a fever. Supervisor [Manager's Name] is notified. "
                    "Reach me at [Your Phone Number].\n\n"
                    "Sincerely,\n\n"
                    "[Your Name]\n"
                    "[Your Job Title]\n"
                    "[Your Employee ID]"
                )
            }
            return nlp._sanitize_draft(raw, profile_context)

        mock_nlp = MockNLP.return_value
        mock_nlp.draft_email.side_effect = fake_draft

        result = runner.invoke(ai, ['compose', 'write a mail to hr for fever leave', '--to', 'hr@example.com'], input='y\n3\ndiscard\n')
        assert result.exit_code == 0
        assert "[Your Name]" not in result.output
        assert "[Your Job Title]" not in result.output
        assert "[Your Phone Number]" not in result.output
        assert "[Manager's Name]" not in result.output
        assert "[Your Employee ID]" not in result.output
        assert "NSakthivel" in result.output
        assert "Software Developer" in result.output
        assert "EMP1024" in result.output
        assert "John" in result.output
