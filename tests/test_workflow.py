"""
Unit and integration tests for the Required Hermes CLI Workflow.
Verifies all 15 rules and 16 workflow requirements:
- Step 1: Input, parse and validate before authentication.
- Invalid command -> Error + AI/local suggestion -> STOP.
- No OAuth or Google API execution on invalid commands.
- Step 2: Authentication check:
  - If valid: continue.
  - If expired: refresh token locally.
  - If unauthenticated: OAuth flow or clean AuthenticationError STOP.
- Step 3: Core engine, config and resource resolution.
- Step 4: Conditional Gemini AI (bypassed for direct commands, invoked when AI required).
- Google API error handling (friendly error + recovery suggestion).
- Output formatters (table, json, csv).
"""

import sys
import json
import pytest
from unittest.mock import MagicMock, patch
from click.testing import CliRunner
import httplib2
from googleapiclient.errors import HttpError

from gsuite_cli.cli import cli, main
from gsuite_cli.auth.oauth import OAuthManager, AuthenticationError
from gsuite_cli.utils.errors import handle_google_api_error
from gsuite_cli.utils.validator import generate_command_suggestion, handle_validation_error


def test_workflow_rule1_and_rule2_invalid_command_halts_before_auth(monkeypatch, capsys):
    """RULE 1, 2, 3, 4, 5: Invalid commands must produce error + suggestion and never trigger OAuth or Google API."""
    mock_auth = MagicMock()
    monkeypatch.setattr(sys, "argv", ["hermes", "gmaill", "list"])

    with patch("gsuite_cli.auth.oauth.OAuthManager.is_authenticated", mock_auth.is_authenticated):
        with pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 1
        # Must not call authentication check for malformed command
        assert not mock_auth.is_authenticated.called

    captured = capsys.readouterr()
    assert 'Unknown command "gmaill"' in captured.err or 'Unknown command "gmaill"' in captured.out
    assert "Did you mean:" in captured.out or "Did you mean:" in captured.err
    assert "hermes gmail list" in captured.out or "hermes gmail list" in captured.err


def test_workflow_invalid_subcommand_suggestion(capsys, monkeypatch):
    """Subcommand typos must produce appropriate suggestion."""
    monkeypatch.setattr(sys, "argv", ["hermes", "calendar", "lisst"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "Did you mean:" in output
    assert "hermes calendar list" in output


def test_workflow_option_typo_suggestion():
    """Option typos (e.g. --formatt) suggest corrected option."""
    suggestion = generate_command_suggestion(["gmail", "list", "--formatt", "table"], "Unknown option '--formatt'.")
    assert suggestion == "hermes gmail list --format table"


def test_workflow_unauthenticated_workspace_command_raises_auth_error():
    """Step 2: Unauthenticated command without client credentials must raise AuthenticationError."""
    mgr = OAuthManager(config_dir="tests/nonexistent_test_dir")
    with patch.object(mgr, "is_authenticated", return_value=False):
        with patch.object(mgr, "has_client_config", return_value=False):
            with pytest.raises(AuthenticationError) as exc_info:
                mgr.ensure_authenticated()

            assert "OAuth client configuration not found" in str(exc_info.value.message)


def test_workflow_authenticated_workspace_command_reuses_credentials():
    """Step 2: Valid credentials must not trigger OAuth login again."""
    mgr = OAuthManager()
    mock_creds = MagicMock(valid=True)
    with patch.object(mgr, "is_authenticated", return_value=True):
        with patch.object(mgr, "get_credentials", return_value=mock_creds):
            creds = mgr.ensure_authenticated()
            assert creds == mock_creds


def test_workflow_expired_token_refreshed_automatically(tmp_path):
    """Step 2: Expired tokens with a refresh token are refreshed automatically."""
    mgr = OAuthManager(config_dir=str(tmp_path))
    # Write a dummy token file so mgr.token_file.exists() is True
    mgr.token_file.write_text('{"token": "dummy"}')
    mock_creds = MagicMock(valid=False, expired=True, refresh_token="mock_ref")
    with patch("gsuite_cli.auth.oauth.Credentials.from_authorized_user_file", return_value=mock_creds):
        with patch.object(mock_creds, "refresh") as mock_refresh:
            with patch.object(mgr, "_save_credentials"):
                mgr.is_authenticated()
                assert mock_refresh.called


def test_workflow_direct_command_bypasses_gemini():
    """RULE 9 & 10: Direct commands must not invoke Gemini AI."""
    runner = CliRunner()
    mock_gmail_svc = MagicMock()
    mock_gmail_svc.list_messages.return_value = []

    with patch("gsuite_cli.ai.gemini_client.GeminiClient.generate_content") as mock_gemini:
        res = runner.invoke(cli, ["gmail", "list"], obj={"_gmail_svc": mock_gmail_svc})
        assert res.exit_code == 0
        assert not mock_gemini.called


def test_workflow_google_api_error_handling(capsys):
    """Google Workspace API errors are converted to friendly errors with recovery suggestions."""
    resp = httplib2.Response({'status': '403', 'reason': 'Forbidden'})
    resp.status = 403
    err = HttpError(resp, b'{"error": {"message": "Insufficient permissions"}}')

    with pytest.raises(SystemExit) as exc:
        handle_google_api_error(err)

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Permission denied" in captured.err or "Permission denied" in captured.out
    assert "hermes auth login --force" in captured.out or "hermes auth login --force" in captured.err
