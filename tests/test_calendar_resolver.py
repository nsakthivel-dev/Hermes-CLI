"""
Tests for Calendar Resource Resolver and Selector.
Covers all 16 required test scenarios:
1. Number selection
2. Primary calendar default
3. Calendar name selection
4. Case-insensitive name matching
5. Alias selection
6. Creating aliases
7. Listing aliases
8. Duplicate names
9. Invalid number
10. Invalid alias
11. Invalid name
12. Direct Calendar ID
13. Deleted calendar behind an alias
14. Calendar API failure
15. Empty calendar list
16. Pagination handling
"""

import pytest
from unittest.mock import MagicMock, patch

from gsuite_cli.services.calendar_resolver import (
    CalendarResolver,
    CalendarResolutionError,
    CalendarNotFoundError,
    AmbiguousCalendarNameError,
    AliasDeletedError,
)


@pytest.fixture
def sample_calendars():
    return [
        {
            'id': 'cherry-id@group.calendar.google.com',
            'summary': 'Brand New Cherry',
            'description': 'Cherry project calendar',
            'primary': False,
            'access_role': 'owner',
            'timezone': 'Asia/Kolkata',
        },
        {
            'id': 'user@example.com',
            'summary': 'My Calendar',
            'description': 'Main calendar',
            'primary': True,
            'access_role': 'owner',
            'timezone': 'Asia/Kolkata',
        },
        {
            'id': 'en.indian#holiday@group.v.calendar.google.com',
            'summary': 'Holidays in India',
            'description': 'Indian national holidays',
            'primary': False,
            'access_role': 'reader',
            'timezone': 'Asia/Kolkata',
        },
    ]


@pytest.fixture
def mock_service(sample_calendars):
    service = MagicMock()
    service.list_calendars.return_value = list(sample_calendars)
    return service


@pytest.fixture
def mock_config_manager():
    mgr = MagicMock()
    store = {
        'calendar.aliases': {
            'work': 'cherry-id@group.calendar.google.com',
            'holidays': 'en.indian#holiday@group.v.calendar.google.com',
        }
    }

    def get(key, default=None):
        return store.get(key, default)

    def set_val(key, val):
        store[key] = val
        return True

    mgr.get.side_effect = get
    mgr.set.side_effect = set_val
    mgr.save_config.return_value = True
    return mgr


# ==============================================================================
# 1. Number Selection
# ==============================================================================
def test_number_selection(mock_service, mock_config_manager):
    calendars = CalendarResolver.get_calendars(mock_service)
    # [1] My Calendar (Primary)
    # [2] Brand New Cherry
    # [3] Holidays in India

    resolved_1 = CalendarResolver.resolve("1", calendars, mock_config_manager)
    assert resolved_1 == 'user@example.com'

    resolved_2 = CalendarResolver.resolve("2", calendars, mock_config_manager)
    assert resolved_2 == 'cherry-id@group.calendar.google.com'

    resolved_3 = CalendarResolver.resolve("3", calendars, mock_config_manager)
    assert resolved_3 == 'en.indian#holiday@group.v.calendar.google.com'


# ==============================================================================
# 2. Primary Calendar Default (e.g. ENTER)
# ==============================================================================
def test_primary_calendar_default(mock_service, mock_config_manager):
    calendars = CalendarResolver.get_calendars(mock_service)
    # Empty string simulates pressing ENTER
    resolved_empty = CalendarResolver.resolve("", calendars, mock_config_manager)
    assert resolved_empty == 'user@example.com'

    resolved_none = CalendarResolver.resolve(None, calendars, mock_config_manager)
    assert resolved_none == 'user@example.com'

    resolved_spaces = CalendarResolver.resolve("   ", calendars, mock_config_manager)
    assert resolved_spaces == 'user@example.com'


# ==============================================================================
# 3. Calendar Name Selection
# ==============================================================================
def test_calendar_name_selection(mock_service, mock_config_manager):
    calendars = CalendarResolver.get_calendars(mock_service)
    resolved = CalendarResolver.resolve("Brand New Cherry", calendars, mock_config_manager)
    assert resolved == 'cherry-id@group.calendar.google.com'

    resolved_holidays = CalendarResolver.resolve("Holidays in India", calendars, mock_config_manager)
    assert resolved_holidays == 'en.indian#holiday@group.v.calendar.google.com'


# ==============================================================================
# 4. Case-Insensitive Name Matching
# ==============================================================================
def test_case_insensitive_name_matching(mock_service, mock_config_manager):
    calendars = CalendarResolver.get_calendars(mock_service)
    assert CalendarResolver.resolve("brand new cherry", calendars, mock_config_manager) == 'cherry-id@group.calendar.google.com'
    assert CalendarResolver.resolve("BRAND NEW CHERRY", calendars, mock_config_manager) == 'cherry-id@group.calendar.google.com'
    assert CalendarResolver.resolve("  Brand New Cherry  ", calendars, mock_config_manager) == 'cherry-id@group.calendar.google.com'
    assert CalendarResolver.resolve("my calendar", calendars, mock_config_manager) == 'user@example.com'


# ==============================================================================
# 5. Alias Selection
# ==============================================================================
def test_alias_selection(mock_service, mock_config_manager):
    calendars = CalendarResolver.get_calendars(mock_service)
    assert CalendarResolver.resolve("work", calendars, mock_config_manager) == 'cherry-id@group.calendar.google.com'
    assert CalendarResolver.resolve("WORK", calendars, mock_config_manager) == 'cherry-id@group.calendar.google.com'
    assert CalendarResolver.resolve("holidays", calendars, mock_config_manager) == 'en.indian#holiday@group.v.calendar.google.com'


# ==============================================================================
# 6. Creating Aliases
# ==============================================================================
def test_creating_aliases(mock_service, mock_config_manager):
    success, msg = CalendarResolver.set_alias("2", "project", mock_service, mock_config_manager)
    assert success is True
    assert "project → Brand New Cherry" in msg

    # Verify it can be resolved via the newly created alias
    calendars = CalendarResolver.get_calendars(mock_service)
    assert CalendarResolver.resolve("project", calendars, mock_config_manager) == 'cherry-id@group.calendar.google.com'


# ==============================================================================
# 7. Listing Aliases
# ==============================================================================
def test_listing_aliases(mock_service, mock_config_manager):
    aliases = CalendarResolver.get_aliases(mock_service, mock_config_manager)
    alias_dict = {a[0]: a[1] for a in aliases}
    assert 'work' in alias_dict
    assert alias_dict['work'] == 'Brand New Cherry'
    assert 'holidays' in alias_dict
    assert alias_dict['holidays'] == 'Holidays in India'


# ==============================================================================
# 8. Duplicate Names Handling
# ==============================================================================
def test_duplicate_names():
    duplicate_calendars = [
        {'id': 'proj-1@group.calendar.google.com', 'summary': 'Project', 'primary': True},
        {'id': 'proj-2@group.calendar.google.com', 'summary': 'Project', 'primary': False},
    ]
    with pytest.raises(AmbiguousCalendarNameError) as exc_info:
        CalendarResolver.resolve("Project", duplicate_calendars, None)

    assert len(exc_info.value.matching_calendars) == 2
    # But selecting by number uniquely identifies it
    assert CalendarResolver.resolve("1", duplicate_calendars, None) == 'proj-1@group.calendar.google.com'
    assert CalendarResolver.resolve("2", duplicate_calendars, None) == 'proj-2@group.calendar.google.com'


# ==============================================================================
# 9. Invalid Number
# ==============================================================================
def test_invalid_number(mock_service, mock_config_manager):
    calendars = CalendarResolver.get_calendars(mock_service)
    with pytest.raises(CalendarNotFoundError):
        CalendarResolver.resolve("99", calendars, mock_config_manager)

    with pytest.raises(CalendarNotFoundError):
        CalendarResolver.resolve("0", calendars, mock_config_manager)


# ==============================================================================
# 10. Invalid Alias
# ==============================================================================
def test_invalid_alias(mock_service, mock_config_manager):
    calendars = CalendarResolver.get_calendars(mock_service)
    with pytest.raises(CalendarNotFoundError):
        CalendarResolver.resolve("nonexistent_alias", calendars, mock_config_manager)


# ==============================================================================
# 11. Invalid Name
# ==============================================================================
def test_invalid_name(mock_service, mock_config_manager):
    calendars = CalendarResolver.get_calendars(mock_service)
    with pytest.raises(CalendarNotFoundError):
        CalendarResolver.resolve("Unknown Calendar XYZ", calendars, mock_config_manager)


# ==============================================================================
# 12. Direct Calendar ID
# ==============================================================================
def test_direct_calendar_id(mock_service, mock_config_manager):
    calendars = CalendarResolver.get_calendars(mock_service)
    direct_id = 'cherry-id@group.calendar.google.com'
    resolved = CalendarResolver.resolve(direct_id, calendars, mock_config_manager)
    assert resolved == direct_id

    # Test arbitrary valid Google Calendar ID format
    arbitrary_id = 'c_188abc123def@group.calendar.google.com'
    resolved_arb = CalendarResolver.resolve(arbitrary_id, calendars, mock_config_manager)
    assert resolved_arb == arbitrary_id


# ==============================================================================
# 13. Deleted Calendar Behind an Alias
# ==============================================================================
def test_deleted_calendar_behind_alias(mock_service):
    # Config has alias pointing to non-existent calendar
    cfg = MagicMock()
    cfg.get.return_value = {'ghost': 'deleted-calendar-id@group.calendar.google.com'}

    calendars = CalendarResolver.get_calendars(mock_service)
    with pytest.raises(AliasDeletedError) as exc_info:
        CalendarResolver.resolve("ghost", calendars, cfg)

    assert exc_info.value.alias == 'ghost'
    assert len(exc_info.value.available_calendars) == len(calendars)


# ==============================================================================
# 14. Calendar API Failure
# ==============================================================================
def test_calendar_api_failure(mock_config_manager):
    failing_service = MagicMock()
    failing_service.list_calendars.side_effect = Exception("API Unavailable: 503")

    # get_calendars catches and returns empty list
    calendars = CalendarResolver.get_calendars(failing_service)
    assert calendars == []

    # Fallback resolution for primary or direct ID
    assert CalendarResolver.resolve("", calendars, mock_config_manager) == 'primary'
    assert CalendarResolver.resolve("my-cal@group.calendar.google.com", calendars, mock_config_manager) == 'my-cal@group.calendar.google.com'


# ==============================================================================
# 15. Empty Calendar List
# ==============================================================================
def test_empty_calendar_list(mock_config_manager):
    empty_calendars = []
    # Default selection on empty list returns 'primary'
    assert CalendarResolver.resolve("", empty_calendars, mock_config_manager) == 'primary'
    assert CalendarResolver.resolve("primary", empty_calendars, mock_config_manager) == 'primary'

    # Non-ID on empty list raises CalendarNotFoundError
    with pytest.raises(CalendarNotFoundError):
        CalendarResolver.resolve("unknown", empty_calendars, mock_config_manager)


# ==============================================================================
# 16. Pagination Handling
# ==============================================================================
def test_pagination_handling():
    # Simulate a CalendarService where list_calendars retrieves 150 items across pages
    large_calendar_list = []
    for i in range(1, 151):
        large_calendar_list.append({
            'id': f'cal_{i}@group.calendar.google.com',
            'summary': f'Calendar {i}',
            'primary': (i == 42),  # Calendar 42 is primary
        })

    paginated_service = MagicMock()
    paginated_service.list_calendars.return_value = large_calendar_list

    calendars = CalendarResolver.get_calendars(paginated_service)
    assert len(calendars) == 150
    # Primary calendar (Calendar 42) must be sorted to position 0 ([1])
    assert calendars[0]['summary'] == 'Calendar 42'
    assert calendars[0]['primary'] is True

    # Resolving "1" returns Calendar 42
    assert CalendarResolver.resolve("1", calendars, None) == 'cal_42@group.calendar.google.com'
    # Resolving "150" returns the last calendar
    assert CalendarResolver.resolve("150", calendars, None) == calendars[149]['id']
    # Resolving by name works across all 150 items
    assert CalendarResolver.resolve("Calendar 100", calendars, None) == 'cal_100@group.calendar.google.com'


# ==============================================================================
# 17. Interactive Prompt Selection Tests
# ==============================================================================
def test_prompt_selection_default_enter(mock_service, mock_config_manager):
    with patch('builtins.input', return_value=""):
        cal_id = CalendarResolver.prompt_selection(mock_service, mock_config_manager)
        assert cal_id == 'user@example.com'


def test_prompt_selection_number(mock_service, mock_config_manager):
    with patch('builtins.input', return_value="2"):
        cal_id = CalendarResolver.prompt_selection(mock_service, mock_config_manager)
        assert cal_id == 'cherry-id@group.calendar.google.com'


def test_prompt_selection_alias(mock_service, mock_config_manager):
    with patch('builtins.input', return_value="work"):
        cal_id = CalendarResolver.prompt_selection(mock_service, mock_config_manager)
        assert cal_id == 'cherry-id@group.calendar.google.com'


def test_prompt_selection_invalid_then_valid(mock_service, mock_config_manager):
    # First input is invalid "xyz", second input is valid "2"
    with patch('builtins.input', side_effect=["xyz", "2"]):
        cal_id = CalendarResolver.prompt_selection(mock_service, mock_config_manager)
        assert cal_id == 'cherry-id@group.calendar.google.com'


def test_prompt_selection_ambiguous_name(mock_config_manager):
    duplicate_service = MagicMock()
    duplicate_service.list_calendars.return_value = [
        {'id': 'proj-1@group.calendar.google.com', 'summary': 'Project', 'primary': True},
        {'id': 'proj-2@group.calendar.google.com', 'summary': 'Project', 'primary': False},
    ]
    # First enters "Project", then when prompted for number enters "2"
    with patch('builtins.input', side_effect=["Project", "2"]):
        cal_id = CalendarResolver.prompt_selection(duplicate_service, mock_config_manager)
        assert cal_id == 'proj-2@group.calendar.google.com'


def test_prompt_selection_deleted_alias_then_valid(mock_service):
    cfg = MagicMock()
    cfg.get.return_value = {'ghost': 'deleted-id@group.calendar.google.com'}
    # First enters "ghost" (points to deleted calendar), then enters "1"
    with patch('builtins.input', side_effect=["ghost", "1"]):
        cal_id = CalendarResolver.prompt_selection(mock_service, cfg)
        assert cal_id == 'user@example.com'


def test_prompt_selection_empty_calendars_fallback():
    empty_service = MagicMock()
    empty_service.list_calendars.return_value = []
    with patch('builtins.input', return_value="custom-cal-id"):
        cal_id = CalendarResolver.prompt_selection(empty_service, None)
        assert cal_id == "custom-cal-id"


# ==============================================================================
# 18. Calendar Info & CLI Command Tests
# ==============================================================================
def test_get_calendar_info(mock_service, mock_config_manager):
    info = CalendarResolver.get_calendar_info("2", mock_service, mock_config_manager)
    assert info is not None
    assert info['id'] == 'cherry-id@group.calendar.google.com'
    assert info['summary'] == 'Brand New Cherry'


def test_calendar_info_cli(mock_service, mock_config_manager):
    from click.testing import CliRunner
    from gsuite_cli.cli import calendar_info

    runner = CliRunner()
    with patch('gsuite_cli.cli.CalendarService', return_value=mock_service):
        ctx_obj = {
            'oauth_manager': MagicMock(),
            'config_manager': mock_config_manager,
        }
        res = runner.invoke(calendar_info, ['2'], obj=ctx_obj)
        assert res.exit_code == 0
        assert "Brand New Cherry" in res.output
        assert "cherry-id@group.calendar.google.com" in res.output


def test_calendar_alias_cli(mock_service, mock_config_manager):
    from click.testing import CliRunner
    from gsuite_cli.cli import calendar_set_alias, calendar_list_aliases

    runner = CliRunner()
    with patch('gsuite_cli.cli.CalendarService', return_value=mock_service):
        ctx_obj = {
            'oauth_manager': MagicMock(),
            'config_manager': mock_config_manager,
        }
        # Create alias
        res_create = runner.invoke(calendar_set_alias, ['2', 'team'], obj=ctx_obj)
        assert res_create.exit_code == 0
        assert "team → Brand New Cherry" in res_create.output

        # List aliases
        res_list = runner.invoke(calendar_list_aliases, [], obj=ctx_obj)
        assert res_list.exit_code == 0
        assert "team" in res_list.output

