"""
Unit and integration tests for full-page screen transitions in Hermes CLI.

Tests:
1. Centralized cross-platform terminal clear utility (Windows/Linux/macOS, HERMES_NO_CLEAR support, call counting).
2. Screen transitions in interactive menus (Menu -> Submenu).
3. Search screen transitions (Search -> Search Results).
4. Results to Details transitions (Search Results -> Email Details).
5. Back navigation screen transitions (Details -> [b] -> Search Results -> [b] -> Menu).
6. Inline error handling without screen clearing (empty input, invalid options).
7. Application state preservation during screen transitions.
8. GlobalResourceResolver page transitions and inline error handling.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
import pytest
from click.testing import CliRunner

from gsuite_cli.utils.formatters import (
    clear_screen,
    get_clear_screen_count,
    reset_clear_screen_count,
)
from gsuite_cli.services.resource_resolver import GlobalResourceResolver


# ===========================================================================
# 1. TEST TERMINAL CLEAR UTILITY
# ===========================================================================

class TestClearScreenUtility:
    """Test the centralized cross-platform terminal clear utility."""

    def test_clear_screen_invokes_os_system_windows(self):
        """On Windows (nt), clear_screen should invoke 'cls'."""
        reset_clear_screen_count()
        with patch("os.name", "nt"), patch("os.system") as mock_system:
            clear_screen()
            mock_system.assert_called_once_with("cls")
            assert get_clear_screen_count() == 1

    def test_clear_screen_invokes_os_system_posix(self):
        """On Linux/macOS (posix), clear_screen should invoke 'clear'."""
        reset_clear_screen_count()
        with patch("os.name", "posix"), patch("os.system") as mock_system:
            clear_screen()
            mock_system.assert_called_once_with("clear")
            assert get_clear_screen_count() == 1

    def test_clear_screen_suppression_via_env_var(self):
        """HERMES_NO_CLEAR=1 suppresses os.system call while tracking invocation."""
        reset_clear_screen_count()
        with patch.dict(os.environ, {"HERMES_NO_CLEAR": "1"}), patch("os.system") as mock_system:
            clear_screen()
            mock_system.assert_not_called()
            # Still increments tracking counter
            assert get_clear_screen_count() == 1

    def test_reset_clear_screen_count(self):
        """reset_clear_screen_count should reset the counter to zero."""
        clear_screen()
        assert get_clear_screen_count() >= 1
        reset_clear_screen_count()
        assert get_clear_screen_count() == 0


# ===========================================================================
# 2. TEST GMAIL LABELS WORKFLOW SCREEN TRANSITIONS
# ===========================================================================

class TestGmailLabelsScreenTransitions:
    """Test that interactive Gmail Labels navigation transitions pages cleanly."""

    def _setup_labels_and_messages(self, mock_service):
        labels_data = [
            {"id": "INBOX", "name": "INBOX", "type": "system"},
            {"id": "SENT", "name": "SENT", "type": "system"},
            {"id": "STARRED", "name": "STARRED", "type": "system"},
            {"id": "IMPORTANT", "name": "IMPORTANT", "type": "system"},
            {"id": "Label_work", "name": "Work", "type": "user"},
            {"id": "Label_proj", "name": "Projects", "type": "user"},
        ]

        labels_mock = MagicMock()
        messages_mock = MagicMock()

        mock_service.users.return_value = mock_service
        mock_service.labels.return_value = labels_mock
        mock_service.messages.return_value = messages_mock

        labels_mock.list.return_value.execute.return_value = {"labels": labels_data}

        # Raw message
        msg1 = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "Test email snippet",
            "labelIds": ["INBOX", "Label_proj"],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Project Roadmap 2026"},
                    {"name": "From", "value": "Alice <alice@example.com>"},
                    {"name": "To", "value": "me@example.com"},
                    {"name": "Date", "value": "Thu, 10 Sep 2026 09:00:00 +0000"},
                ]
            },
        }
        messages_mock.list.return_value.execute.return_value = {"messages": [{"id": "msg1"}]}
        messages_mock.get.return_value.execute.return_value = msg1
        messages_mock.modify.return_value.execute.return_value = {
            "id": "msg1",
            "labelIds": ["INBOX", "Label_proj", "Label_work"],
        }
        return labels_data, msg1, labels_mock, messages_mock

    def _get_ctx_and_mocks(self):
        from gsuite_cli.services.gmail import GmailService

        mock_service = MagicMock()
        labels_data, msg1, labels_mock, messages_mock = self._setup_labels_and_messages(mock_service)
        oauth = MagicMock()
        oauth.build_service.return_value = mock_service
        svc = GmailService(oauth)
        svc.service = mock_service
        ctx_obj = {"oauth_manager": oauth, "cache_manager": None, "_gmail_svc": svc}
        return ctx_obj, mock_service, messages_mock

    def test_labels_menu_transitions_to_list_screen(self):
        """Selecting [1] List labels transitions to new screen and calls clear_screen."""
        from gsuite_cli.cli import cli

        ctx_obj, mock_service, _ = self._get_ctx_and_mocks()
        runner = CliRunner()

        reset_clear_screen_count()
        # [1] List labels -> [b] Back from list -> [b] Back from menu
        result = runner.invoke(cli, ["gmail", "labels"], obj=ctx_obj, input="1\nb\nb\n")
        assert result.exit_code == 0
        assert "Gmail Labels" in result.output
        # clear_screen was called for the menu, for the list screen, and upon returning
        assert get_clear_screen_count() >= 3

    def test_invalid_menu_choice_reprompts_inline_without_clearing(self):
        """Entering invalid menu options re-prompts inline without triggering clear_screen."""
        from gsuite_cli.cli import cli

        ctx_obj, mock_service, _ = self._get_ctx_and_mocks()
        runner = CliRunner()

        reset_clear_screen_count()
        # Menu displayed (1 clear) -> Invalid choice '99' (reprompt inline, 0 clear) -> 'b' exit
        result = runner.invoke(cli, ["gmail", "labels"], obj=ctx_obj, input="99\nb\n")
        assert result.exit_code == 0
        assert "✗ Invalid selection." in result.output
        # Only the initial menu display called clear_screen
        assert get_clear_screen_count() == 1

    def test_empty_search_query_reprompts_inline_without_clearing(self):
        """Empty search query in Apply Label flow re-prompts inline on the same page."""
        from gsuite_cli.cli import cli

        ctx_obj, mock_service, _ = self._get_ctx_and_mocks()
        runner = CliRunner()

        reset_clear_screen_count()
        # Menu (1) -> [2] Apply Label (2) -> "" (empty query: reprompt inline, 0 clear) -> "b" -> "b"
        result = runner.invoke(cli, ["gmail", "labels"], obj=ctx_obj, input="2\n   \nb\nb\n")
        assert result.exit_code == 0
        assert "✗ Search query cannot be empty." in result.output
        # Check clears: menu display (1), search screen display (2), menu display on return (3)
        assert get_clear_screen_count() == 3

    def test_full_apply_label_step_transitions_and_state_preservation(self):
        """Complete workflow: Search -> Results -> Email Details -> Apply Label -> Confirm -> Success.

        Verifies each step triggers a screen transition and message state is fully preserved.
        """
        from gsuite_cli.cli import cli

        ctx_obj, mock_service, messages_mock = self._get_ctx_and_mocks()
        runner = CliRunner()

        reset_clear_screen_count()
        # [2] Apply Label -> "Roadmap" (search) -> [1] Select email -> [1] Apply Label ->
        # [1] Select Work -> [y] Confirm -> [b] Back to exit menu
        inputs = "2\nRoadmap\n1\n1\n1\ny\nb\n"
        result = runner.invoke(cli, ["gmail", "labels"], obj=ctx_obj, input=inputs)
        assert result.exit_code == 0

        # Verify screens were displayed
        assert "Apply Label" in result.output
        assert "Search Results" in result.output
        assert "Project Roadmap 2026" in result.output
        assert "Select Label" in result.output
        assert "✓ Label \"Work\" applied to the email." in result.output

        # Verify state preservation: modify API called
        messages_mock.modify.assert_called()

        # Verify multiple screen transitions occurred
        assert get_clear_screen_count() >= 6

    def test_back_navigation_transitions_cleanly(self):
        """Navigating back at each level triggers a screen clear and re-renders parent."""
        from gsuite_cli.cli import cli

        ctx_obj, mock_service, _ = self._get_ctx_and_mocks()
        runner = CliRunner()

        reset_clear_screen_count()
        # [2] Apply Label -> "Roadmap" -> [1] Select email -> [b] Back from email view ->
        # [b] Back from search prompt -> [b] Back from menu
        inputs = "2\nRoadmap\n1\nb\nb\nb\n"
        result = runner.invoke(cli, ["gmail", "labels"], obj=ctx_obj, input=inputs)
        assert result.exit_code == 0
        # Each back navigation must have triggered clear_screen
        assert get_clear_screen_count() >= 5


# ===========================================================================
# 3. TEST GLOBAL RESOURCE RESOLVER SCREEN TRANSITIONS
# ===========================================================================

class TestGlobalResourceResolverScreenTransitions:
    """Test GlobalResourceResolver page transitions and inline validation."""

    def test_prompt_selection_clears_screen_on_pagination_and_search(self):
        """Navigating pages [n]/[p] or searching [s] triggers page transitions."""
        items = [
            {"id": f"item_{i}", "name": f"Item {i}"}
            for i in range(1, 15)
        ]

        reset_clear_screen_count()
        # Input sequence:
        # [n] -> Next page (clears screen)
        # [p] -> Prev page (clears screen)
        # [1] -> Select first item
        inputs = iter(["n", "p", "1"])
        with patch("click.prompt", side_effect=lambda *args, **kwargs: next(inputs)):
            selected = GlobalResourceResolver.prompt_selection(
                items,
                resource_name="Document",
                page_size=5
            )

        assert selected is not None
        assert selected["id"] == "item_1"
        # 1. Initial page display
        # 2. Next page display
        # 3. Previous page display
        assert get_clear_screen_count() == 3

    def test_prompt_selection_reprompts_inline_on_invalid_input(self):
        """Invalid resource input re-prompts inline without clearing the screen."""
        items = [
            {"id": f"item_{i}", "name": f"Document {i}"}
            for i in range(1, 5)
        ]

        reset_clear_screen_count()
        # Input: 99 (not found, reprompts inline without clear) -> 1 (selects item 1)
        inputs = iter(["99", "1"])
        with patch("click.prompt", side_effect=lambda *args, **kwargs: next(inputs)):
            selected = GlobalResourceResolver.prompt_selection(
                items,
                resource_name="Document",
                page_size=5
            )

        assert selected is not None
        assert selected["id"] == "item_1"
        # Only the initial page display called clear_screen
        assert get_clear_screen_count() == 1

    def test_execute_delete_flow_clears_screen_before_details(self):
        """execute_delete_flow clears the terminal screen before rendering details."""
        item = {"id": "doc_101", "name": "Financial Report 2026"}
        delete_mock = MagicMock(return_value=True)

        reset_clear_screen_count()
        with patch("click.prompt", return_value="y"):
            success = GlobalResourceResolver.execute_delete_flow(
                resource=item,
                delete_fn=delete_mock,
                resource_name="Document"
            )

        assert success is True
        assert delete_mock.called
        # clear_screen was called before rendering details
        assert get_clear_screen_count() >= 1

    def test_execute_update_flow_clears_screen_on_transitions(self):
        """execute_update_flow clears screen before details and review changes."""
        item = {"id": "doc_101", "title": "Old Title"}
        update_mock = MagicMock(return_value=True)
        fields = [{"name": "title", "label": "Title", "current": "Old Title"}]

        reset_clear_screen_count()
        # Inputs:
        # 1. Select field [1]
        # 2. Enter new title: "New Title"
        # 3. Confirm update: "y"
        inputs = iter(["1", "New Title", "y"])
        with patch("click.prompt", side_effect=lambda *args, **kwargs: next(inputs)):
            success = GlobalResourceResolver.execute_update_flow(
                resource=item,
                fields=fields,
                update_fn=update_mock,
                resource_name="Document"
            )

        assert success is True
        # Details screen (1) + Review Changes screen (2)
        assert get_clear_screen_count() >= 2
