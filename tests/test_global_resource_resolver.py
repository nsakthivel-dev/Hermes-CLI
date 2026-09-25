"""
Tests for GlobalResourceResolver:
- Number (1..N) selection
- Alias resolution
- Exact title/name match
- Substring search / match
- Direct ID fallback
- Ambiguity handling
- Alias setting, listing, deleting
- prompt_selection with pagination, search, and retry
- execute_delete_flow with confirmation
- execute_update_flow with field editing, change preview, and confirmation
"""

import pytest
from unittest.mock import MagicMock, patch

from gsuite_cli.services.resource_resolver import (
    GlobalResourceResolver,
    ResourceResolutionError,
    ResourceNotFoundError,
    AmbiguousResourceError,
)


@pytest.fixture(autouse=True)
def clean_aliases():
    """Reset aliases in memory before and after tests."""
    GlobalResourceResolver._aliases = {}
    yield
    GlobalResourceResolver._aliases = {}


SAMPLE_RESOURCES = [
    {"id": "ev_101", "summary": "Team Standup", "description": "Daily standup meeting"},
    {"id": "ev_102", "summary": "Project Discussion", "description": "Quarterly planning"},
    {"id": "ev_103", "summary": "Client Call", "description": "Review sprint deliverable"},
    {"id": "ev_104", "summary": "Team Retrospective", "description": "Sprint retro"},
]


def test_resolve_by_number():
    # 1-indexed number selection
    resolved = GlobalResourceResolver.resolve(SAMPLE_RESOURCES, "1", title_key="summary")
    assert resolved["id"] == "ev_101"

    resolved = GlobalResourceResolver.resolve(SAMPLE_RESOURCES, "3", title_key="summary")
    assert resolved["id"] == "ev_103"


def test_resolve_by_exact_title():
    resolved = GlobalResourceResolver.resolve(SAMPLE_RESOURCES, "Project Discussion", title_key="summary")
    assert resolved["id"] == "ev_102"

    # Case insensitive exact match
    resolved = GlobalResourceResolver.resolve(SAMPLE_RESOURCES, "project discussion", title_key="summary")
    assert resolved["id"] == "ev_102"


def test_resolve_by_substring():
    # 'standup' matches 'Team Standup'
    resolved = GlobalResourceResolver.resolve(SAMPLE_RESOURCES, "standup", title_key="summary")
    assert resolved["id"] == "ev_101"


def test_resolve_by_direct_id():
    resolved = GlobalResourceResolver.resolve(SAMPLE_RESOURCES, "ev_104", title_key="summary")
    assert resolved["id"] == "ev_104"


def test_resolve_by_alias():
    GlobalResourceResolver.set_alias("event", "retro", "ev_104")
    resolved = GlobalResourceResolver.resolve(SAMPLE_RESOURCES, "retro", resource_type="event", title_key="summary")
    assert resolved["id"] == "ev_104"


def test_alias_management():
    GlobalResourceResolver.set_alias("calendar", "work", "cal_work_123")
    assert GlobalResourceResolver.get_aliases("calendar") == {"work": "cal_work_123"}
    assert GlobalResourceResolver.resolve_alias("calendar", "work") == "cal_work_123"

    GlobalResourceResolver.remove_alias("calendar", "work")
    assert GlobalResourceResolver.resolve_alias("calendar", "work") is None


def test_ambiguous_title_raises_or_prompts():
    # 'Team' matches 'Team Standup' and 'Team Retrospective'
    with pytest.raises(AmbiguousResourceError) as exc_info:
        GlobalResourceResolver.resolve(SAMPLE_RESOURCES, "Team", title_key="summary", allow_prompt=False)
    assert len(exc_info.value.matches) == 2


def test_ambiguous_title_interactive_choice():
    with patch("click.prompt", return_value="2"):
        resolved = GlobalResourceResolver.resolve(SAMPLE_RESOURCES, "Team", title_key="summary", allow_prompt=True)
        assert resolved["id"] == "ev_104"


def test_prompt_selection_direct_number():
    with patch("click.prompt", return_value="2"):
        selected = GlobalResourceResolver.prompt_selection(
            SAMPLE_RESOURCES,
            title_key="summary",
            resource_name="Event"
        )
        assert selected["id"] == "ev_102"


def test_prompt_selection_search_filter():
    # User types 's' for search, searches 'Client', then selects '1'
    with patch("click.prompt", side_effect=["s", "Client", "1"]):
        selected = GlobalResourceResolver.prompt_selection(
            SAMPLE_RESOURCES,
            title_key="summary",
            resource_name="Event"
        )
        assert selected["id"] == "ev_103"


def test_prompt_selection_retry_on_invalid_input():
    # User types '99' (invalid), then '1' (valid)
    with patch("click.prompt", side_effect=["99", "1"]):
        selected = GlobalResourceResolver.prompt_selection(
            SAMPLE_RESOURCES,
            title_key="summary",
            resource_name="Event"
        )
        assert selected["id"] == "ev_101"


def test_prompt_selection_cancel_back():
    with patch("click.prompt", return_value="b"):
        selected = GlobalResourceResolver.prompt_selection(
            SAMPLE_RESOURCES,
            title_key="summary",
            resource_name="Event"
        )
        assert selected is None


def test_delete_flow_confirmed():
    target = SAMPLE_RESOURCES[0]
    delete_fn = MagicMock()

    with patch("gsuite_cli.services.resource_resolver.GlobalResourceResolver.confirm_action", return_value=True):
        res = GlobalResourceResolver.execute_delete_flow(
            resource=target,
            delete_fn=delete_fn,
            resource_name="Event",
            details={"Title": target["summary"], "ID": target["id"]}
        )
        assert res is True
        delete_fn.assert_called_once_with(target)


def test_delete_flow_aborted_by_user():
    target = SAMPLE_RESOURCES[0]
    delete_fn = MagicMock()

    with patch("gsuite_cli.services.resource_resolver.GlobalResourceResolver.confirm_action", return_value=False):
        res = GlobalResourceResolver.execute_delete_flow(
            resource=target,
            delete_fn=delete_fn,
            resource_name="Event",
            details={"Title": target["summary"]}
        )
        assert res is False
        delete_fn.assert_not_called()


def test_update_flow_single_field_confirmed():
    target = {"id": "ev_101", "summary": "Team Standup", "description": "Daily sync"}
    update_fn = MagicMock()
    fields = [
        {"name": "summary", "label": "Title", "current": target["summary"]},
        {"name": "description", "label": "Description", "current": target["description"]},
    ]

    # Select field 1 (Title) -> enter new title "Daily Scrum" -> confirm [Y/n]
    with patch("click.prompt", side_effect=["1", "Daily Scrum"]), \
         patch("gsuite_cli.services.resource_resolver.GlobalResourceResolver.confirm_action", return_value=True):
        res = GlobalResourceResolver.execute_update_flow(
            resource=target,
            fields=fields,
            update_fn=update_fn,
            resource_name="Event"
        )
        assert res is True
        update_fn.assert_called_once_with(target, {"summary": "Daily Scrum"})


def test_update_flow_cancel_on_confirmation():
    target = {"id": "ev_101", "summary": "Team Standup"}
    update_fn = MagicMock()
    fields = [
        {"name": "summary", "label": "Title", "current": target["summary"]}
    ]

    with patch("click.prompt", side_effect=["1", "New Title"]), \
         patch("gsuite_cli.services.resource_resolver.GlobalResourceResolver.confirm_action", return_value=False):
        res = GlobalResourceResolver.execute_update_flow(
            resource=target,
            fields=fields,
            update_fn=update_fn,
            resource_name="Event"
        )
        assert res is False
        update_fn.assert_not_called()
