"""
Unit tests for the Gmail module.

All tests mock the Google API service object — no live API calls are made.
Run with:  pytest tests/test_gmail.py -v
"""

from __future__ import annotations

import base64
import sys
import types
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from unittest.mock import MagicMock, patch, call, mock_open

import pytest
from click.testing import CliRunner
from googleapiclient.errors import HttpError

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_http_error(status: int, reason: str = "error") -> HttpError:
    resp = MagicMock()
    resp.status = status
    resp.reason = reason
    return HttpError(resp=resp, content=reason.encode())


def _b64(text: str) -> str:
    """Return URL-safe base64 encoding of *text*."""
    return base64.urlsafe_b64encode(text.encode()).decode()


def _msg_payload(plain: str = "Hello", html: str = "") -> dict:
    """Build a minimal Gmail message payload with plain-text (and optional HTML) parts."""
    parts = [
        {
            "mimeType": "text/plain",
            "body": {"data": _b64(plain)},
            "filename": "",
        }
    ]
    if html:
        parts.append(
            {
                "mimeType": "text/html",
                "body": {"data": _b64(html)},
                "filename": "",
            }
        )
    return {"mimeType": "multipart/mixed", "parts": parts}


def _raw_message(
    msg_id: str = "msg1",
    thread_id: str = "thread1",
    subject: str = "Test Subject",
    from_: str = "alice@example.com",
    to_: str = "bob@example.com",
    body_plain: str = "Hello",
    label_ids: list | None = None,
) -> dict:
    return {
        "id": msg_id,
        "threadId": thread_id,
        "snippet": body_plain[:50],
        "sizeEstimate": len(body_plain),
        "labelIds": label_ids or ["INBOX"],
        "payload": {
            **_msg_payload(body_plain),
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": from_},
                {"name": "To", "value": to_},
                {"name": "Date", "value": "Mon, 06 Aug 2026 10:00:00 +0000"},
                {"name": "Message-ID", "value": "<msg1@example.com>"},
                {"name": "References", "value": ""},
            ],
        },
    }


@pytest.fixture()
def mock_oauth():
    """OAuthManager that returns a pre-built mock Gmail service."""
    oauth = MagicMock()
    return oauth


@pytest.fixture()
def mock_service():
    """A fully-mocked googleapiclient Gmail service object."""
    svc = MagicMock()
    # Provide a chainable execute() for common call patterns
    svc.users.return_value = svc
    svc.messages.return_value = svc
    svc.drafts.return_value = svc
    svc.labels.return_value = svc
    svc.threads.return_value = svc
    svc.settings.return_value = svc
    svc.filters.return_value = svc
    return svc


@pytest.fixture()
def gmail_svc(mock_oauth, mock_service):
    """GmailService with the Google API client replaced by mock_service."""
    from gsuite_cli.services.gmail import GmailService

    with patch.object(mock_oauth, "build_service", return_value=mock_service):
        svc = GmailService(mock_oauth)
    # Inject mock directly in case build_service was already called in __init__
    svc.service = mock_service
    return svc


# ---------------------------------------------------------------------------
# GmailService.list_messages
# ---------------------------------------------------------------------------


class TestListMessages:
    def test_returns_messages_with_details(self, gmail_svc, mock_service):
        """list_messages fetches metadata for each id returned by the list call."""
        mock_service.list.return_value.execute.return_value = {
            "messages": [{"id": "msg1"}, {"id": "msg2"}]
        }
        raw1 = _raw_message("msg1", subject="Alpha")
        raw2 = _raw_message("msg2", subject="Beta")
        # get() is called once per message id
        mock_service.get.return_value.execute.side_effect = [raw1, raw2]

        result = gmail_svc.list_messages(query="in:inbox", max_results=10)

        assert len(result) == 2
        assert result[0]["subject"] == "Alpha"
        assert result[1]["subject"] == "Beta"
        # Verify the API was called with the query
        mock_service.list.assert_called_once_with(
            userId="me", maxResults=10, q="in:inbox"
        )

    def test_empty_list_returns_empty(self, gmail_svc, mock_service):
        mock_service.list.return_value.execute.return_value = {"messages": []}
        result = gmail_svc.list_messages()
        assert result == []

    def test_list_http_error_403_returns_empty(self, gmail_svc, mock_service):
        mock_service.list.return_value.execute.side_effect = _make_http_error(403)
        result = gmail_svc.list_messages()
        assert result == []

    def test_list_http_error_500_returns_empty(self, gmail_svc, mock_service):
        mock_service.list.return_value.execute.side_effect = _make_http_error(500)
        result = gmail_svc.list_messages()
        assert result == []

    def test_list_with_label_ids(self, gmail_svc, mock_service):
        mock_service.list.return_value.execute.return_value = {"messages": []}
        gmail_svc.list_messages(label_ids=["UNREAD"])
        call_kwargs = mock_service.list.call_args.kwargs
        assert call_kwargs["labelIds"] == ["UNREAD"]


# ---------------------------------------------------------------------------
# GmailService.get_message
# ---------------------------------------------------------------------------


class TestGetMessage:
    def test_returns_formatted_message(self, gmail_svc, mock_service):
        mock_service.get.return_value.execute.return_value = _raw_message(
            "msg1", body_plain="Hi there"
        )
        msg = gmail_svc.get_message("msg1")

        assert msg is not None
        assert msg["id"] == "msg1"
        assert msg["subject"] == "Test Subject"
        assert msg["from"] == "alice@example.com"
        assert "Hi there" in msg["body"]

    def test_extracts_attachments(self, gmail_svc, mock_service):
        payload = {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "Subject", "value": "With attachment"},
                {"name": "From", "value": "a@b.com"},
                {"name": "To", "value": "c@d.com"},
                {"name": "Date", "value": "Mon, 06 Aug 2026 10:00:00 +0000"},
                {"name": "Message-ID", "value": "<x@y>"},
                {"name": "References", "value": ""},
            ],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("body")}, "filename": ""},
                {
                    "mimeType": "application/pdf",
                    "filename": "report.pdf",
                    "body": {"attachmentId": "att1", "size": 1024},
                },
            ],
        }
        mock_service.get.return_value.execute.return_value = {
            "id": "msg2",
            "threadId": "t2",
            "snippet": "body",
            "sizeEstimate": 100,
            "labelIds": ["INBOX"],
            "payload": payload,
        }
        msg = gmail_svc.get_message("msg2")
        assert len(msg["attachments"]) == 1
        assert msg["attachments"][0]["filename"] == "report.pdf"
        assert msg["attachments"][0]["attachment_id"] == "att1"

    def test_returns_none_on_http_error(self, gmail_svc, mock_service):
        mock_service.get.return_value.execute.side_effect = _make_http_error(404)
        assert gmail_svc.get_message("missing") is None

    def test_no_cache_bypasses_cache(self, gmail_svc, mock_service):
        """Calling with no_cache=True should always hit the API."""
        mock_service.get.return_value.execute.return_value = _raw_message("msg1")
        gmail_svc.get_message("msg1", no_cache=False)  # warms cache
        gmail_svc.get_message("msg1", no_cache=True)   # must call API again
        assert mock_service.get.call_count >= 2


# ---------------------------------------------------------------------------
# GmailService.send_message
# ---------------------------------------------------------------------------


class TestSendMessage:
    def test_sends_plain_message(self, gmail_svc, mock_service):
        mock_service.send.return_value.execute.return_value = {"id": "sent1"}
        result = gmail_svc.send_message(
            to="bob@example.com", subject="Hi", body="Hello Bob"
        )
        assert result == "sent1"
        mock_service.send.assert_called_once()

    def test_send_with_cc(self, gmail_svc, mock_service):
        mock_service.send.return_value.execute.return_value = {"id": "sent2"}
        gmail_svc.send_message(
            to="bob@example.com", subject="Hi", body="text", cc="cc@example.com"
        )
        # Verify encoded raw contains CC header
        body_arg = mock_service.send.call_args.kwargs.get("body") or \
                   mock_service.send.call_args.args[0] if mock_service.send.call_args.args else \
                   mock_service.send.call_args[1].get("body", {})
        raw = body_arg.get("raw", "")
        decoded = base64.urlsafe_b64decode(raw).decode()
        assert "cc@example.com" in decoded

    def test_returns_none_on_invalid_email(self, gmail_svc, mock_service):
        result = gmail_svc.send_message(to="not-an-email", subject="x", body="y")
        assert result is None
        mock_service.send.assert_not_called()

    def test_returns_none_on_http_error(self, gmail_svc, mock_service):
        mock_service.send.return_value.execute.side_effect = _make_http_error(500)
        result = gmail_svc.send_message(
            to="bob@example.com", subject="Hi", body="text"
        )
        assert result is None

    def test_send_with_attachment(self, gmail_svc, mock_service, tmp_path):
        """Attachments are read from local paths and encoded correctly."""
        att = tmp_path / "report.txt"
        att.write_text("log data")
        mock_service.send.return_value.execute.return_value = {"id": "sent3"}
        result = gmail_svc.send_message(
            to="bob@example.com", subject="Log", body="See attached",
            attachments=[str(att)],
        )
        assert result == "sent3"
        raw = mock_service.send.call_args.kwargs["body"]["raw"]
        decoded = base64.urlsafe_b64decode(raw).decode(errors="replace")
        assert "report.txt" in decoded


# ---------------------------------------------------------------------------
# GmailService.reply_message
# ---------------------------------------------------------------------------


class TestReplyMessage:
    def _setup_original(self, mock_service, msg_id="orig1"):
        mock_service.get.return_value.execute.return_value = _raw_message(
            msg_id,
            thread_id="thread99",
            subject="Original subject",
            from_="alice@example.com",
        )
        mock_service.send.return_value.execute.return_value = {"id": "reply1"}

    def test_reply_sets_in_reply_to(self, gmail_svc, mock_service):
        self._setup_original(mock_service)
        sent_id = gmail_svc.reply_message("orig1", body="Got it, thanks!")
        assert sent_id == "reply1"
        raw = mock_service.send.call_args.kwargs["body"]["raw"]
        decoded = base64.urlsafe_b64decode(raw).decode(errors="replace")
        assert "In-Reply-To" in decoded
        assert "<msg1@example.com>" in decoded

    def test_reply_preserves_thread_id(self, gmail_svc, mock_service):
        self._setup_original(mock_service)
        gmail_svc.reply_message("orig1", body="Ack")
        body_arg = mock_service.send.call_args.kwargs["body"]
        assert body_arg.get("threadId") == "thread99"

    def test_reply_prefixes_re(self, gmail_svc, mock_service):
        self._setup_original(mock_service)
        gmail_svc.reply_message("orig1", body="Re body")
        raw = mock_service.send.call_args.kwargs["body"]["raw"]
        decoded = base64.urlsafe_b64decode(raw).decode(errors="replace")
        assert "Re: Original subject" in decoded

    def test_reply_returns_none_on_missing_original(self, gmail_svc, mock_service):
        mock_service.get.return_value.execute.side_effect = _make_http_error(404)
        result = gmail_svc.reply_message("missing", body="text")
        assert result is None

    def test_reply_returns_none_on_send_error(self, gmail_svc, mock_service):
        self._setup_original(mock_service)
        mock_service.send.return_value.execute.side_effect = _make_http_error(500)
        result = gmail_svc.reply_message("orig1", body="text")
        assert result is None


# ---------------------------------------------------------------------------
# GmailService.create_draft
# ---------------------------------------------------------------------------


class TestCreateDraft:
    def test_creates_draft_successfully(self, gmail_svc, mock_service):
        mock_service.create.return_value.execute.return_value = {"id": "draft1"}
        draft_id = gmail_svc.create_draft(
            to="bob@example.com", subject="Draft subject", body="Draft body"
        )
        assert draft_id == "draft1"
        mock_service.create.assert_called_once()

    def test_draft_body_contains_subject(self, gmail_svc, mock_service):
        mock_service.create.return_value.execute.return_value = {"id": "draft2"}
        gmail_svc.create_draft(to="a@b.com", subject="My Draft", body="content")
        call_body = mock_service.create.call_args.kwargs["body"]
        raw = call_body["message"]["raw"]
        decoded = base64.urlsafe_b64decode(raw).decode(errors="replace")
        assert "My Draft" in decoded

    def test_returns_none_on_http_error(self, gmail_svc, mock_service):
        mock_service.create.return_value.execute.side_effect = _make_http_error(403)
        result = gmail_svc.create_draft(to="a@b.com", subject="x", body="y")
        assert result is None


# ---------------------------------------------------------------------------
# GmailService.modify_labels  (and mark helpers)
# ---------------------------------------------------------------------------


class TestModifyLabels:
    def _setup_labels(self, mock_service, existing=None):
        """Stub the labels.list call with *existing* label dicts."""
        existing = existing or []
        mock_service.list.return_value.execute.return_value = {"labels": existing}
        mock_service.modify.return_value.execute.return_value = {}

    def test_add_system_label_by_name(self, gmail_svc, mock_service):
        self._setup_labels(mock_service)
        ok = gmail_svc.modify_labels("msg1", add_labels=["STARRED"])
        assert ok is True
        body = mock_service.modify.call_args.kwargs["body"]
        assert "STARRED" in body["addLabelIds"]

    def test_remove_inbox_archives(self, gmail_svc, mock_service):
        self._setup_labels(mock_service)
        ok = gmail_svc.archive_message("msg1")
        assert ok is True
        body = mock_service.modify.call_args.kwargs["body"]
        assert "INBOX" in body["removeLabelIds"]

    def test_creates_user_label_when_missing(self, gmail_svc, mock_service):
        # labels.list returns empty; labels.create returns new label
        mock_service.list.return_value.execute.return_value = {"labels": []}
        mock_service.create.return_value.execute.return_value = {
            "id": "Label_new", "name": "MyLabel"
        }
        mock_service.modify.return_value.execute.return_value = {}
        ok = gmail_svc.modify_labels("msg1", add_labels=["MyLabel"])
        assert ok is True
        # labels.create should have been called once
        mock_service.create.assert_called_once()

    def test_reuses_existing_user_label(self, gmail_svc, mock_service):
        existing = [{"id": "Label_123", "name": "ExistingLabel"}]
        self._setup_labels(mock_service, existing)
        gmail_svc.modify_labels("msg1", add_labels=["ExistingLabel"])
        # Should NOT call labels.create
        mock_service.create.assert_not_called()
        body = mock_service.modify.call_args.kwargs["body"]
        assert "Label_123" in body["addLabelIds"]

    def test_mark_as_read(self, gmail_svc, mock_service):
        self._setup_labels(mock_service)
        ok = gmail_svc.mark_as_read("msg1")
        assert ok is True
        body = mock_service.modify.call_args.kwargs["body"]
        assert "UNREAD" in body["removeLabelIds"]

    def test_mark_as_unread(self, gmail_svc, mock_service):
        self._setup_labels(mock_service)
        ok = gmail_svc.mark_as_unread("msg1")
        assert ok is True
        body = mock_service.modify.call_args.kwargs["body"]
        assert "UNREAD" in body["addLabelIds"]

    def test_trash_message(self, gmail_svc, mock_service):
        mock_service.trash.return_value.execute.return_value = {}
        ok = gmail_svc.trash_message("msg1")
        assert ok is True
        mock_service.trash.assert_called_once_with(userId="me", id="msg1")

    def test_trash_http_error_returns_false(self, gmail_svc, mock_service):
        mock_service.trash.return_value.execute.side_effect = _make_http_error(500)
        assert gmail_svc.trash_message("msg1") is False

    def test_modify_http_error_returns_false(self, gmail_svc, mock_service):
        mock_service.list.return_value.execute.return_value = {"labels": []}
        mock_service.modify.return_value.execute.side_effect = _make_http_error(500)
        assert gmail_svc.modify_labels("msg1", add_labels=["STARRED"]) is False


# ---------------------------------------------------------------------------
# GmailService  — filters
# ---------------------------------------------------------------------------


class TestFilters:
    def test_list_filters_returns_formatted(self, gmail_svc, mock_service):
        mock_service.list.return_value.execute.return_value = {
            "filter": [
                {
                    "id": "flt1",
                    "criteria": {"from": "boss@example.com", "subject": "report"},
                    "action": {"addLabelIds": ["STARRED"], "removeLabelIds": ["INBOX"]},
                }
            ]
        }
        filters = gmail_svc.list_filters()
        assert len(filters) == 1
        assert filters[0]["id"] == "flt1"
        assert filters[0]["from"] == "boss@example.com"
        assert "STARRED" in filters[0]["add_labels"]

    def test_list_filters_empty(self, gmail_svc, mock_service):
        mock_service.list.return_value.execute.return_value = {"filter": []}
        assert gmail_svc.list_filters() == []

    def test_list_filters_http_error(self, gmail_svc, mock_service):
        mock_service.list.return_value.execute.side_effect = _make_http_error(403)
        assert gmail_svc.list_filters() == []

    def test_create_filter_basic(self, gmail_svc, mock_service):
        # labels.list returns empty (no user labels to resolve)
        mock_service.list.return_value.execute.return_value = {"labels": []}
        mock_service.create.return_value.execute.return_value = {"id": "flt_new"}
        fid = gmail_svc.create_filter(from_addr="spam@bad.com", archive=True)
        assert fid == "flt_new"
        call_body = mock_service.create.call_args.kwargs["body"]
        assert call_body["criteria"]["from"] == "spam@bad.com"
        assert "INBOX" in call_body["action"]["removeLabelIds"]

    def test_create_filter_mark_read(self, gmail_svc, mock_service):
        mock_service.list.return_value.execute.return_value = {"labels": []}
        mock_service.create.return_value.execute.return_value = {"id": "flt2"}
        gmail_svc.create_filter(subject="newsletter", mark_read=True)
        call_body = mock_service.create.call_args.kwargs["body"]
        assert "UNREAD" in call_body["action"]["removeLabelIds"]

    def test_create_filter_returns_none_on_error(self, gmail_svc, mock_service):
        mock_service.list.return_value.execute.return_value = {"labels": []}
        mock_service.create.return_value.execute.side_effect = _make_http_error(400)
        result = gmail_svc.create_filter(from_addr="x@x.com")
        assert result is None

    def test_delete_filter(self, gmail_svc, mock_service):
        mock_service.delete.return_value.execute.return_value = None
        ok = gmail_svc.delete_filter("flt1")
        assert ok is True
        mock_service.delete.assert_called_once_with(userId="me", id="flt1")

    def test_delete_filter_http_error(self, gmail_svc, mock_service):
        mock_service.delete.return_value.execute.side_effect = _make_http_error(404)
        assert gmail_svc.delete_filter("flt_missing") is False


# ---------------------------------------------------------------------------
# GmailService.list_messages_since
# ---------------------------------------------------------------------------


class TestListMessagesSince:
    def test_builds_after_query(self, gmail_svc, mock_service):
        mock_service.list.return_value.execute.return_value = {"messages": []}
        gmail_svc.list_messages_since(hours=24, query="label:alerts")
        q_arg = mock_service.list.call_args.kwargs["q"]
        # Must start with 'after:<epoch>' and include the extra query
        assert q_arg.startswith("after:")
        assert "label:alerts" in q_arg

    def test_respects_max_results(self, gmail_svc, mock_service):
        mock_service.list.return_value.execute.return_value = {"messages": []}
        gmail_svc.list_messages_since(hours=1, max_results=5)
        assert mock_service.list.call_args.kwargs["maxResults"] == 5


# ---------------------------------------------------------------------------
# Click CLI commands  (via CliRunner, service mocked at the service layer)
# ---------------------------------------------------------------------------


def _cli_ctx_obj(mock_service):
    """Build a minimal ctx.obj dict wiring a mocked GmailService."""
    from gsuite_cli.services.gmail import GmailService

    oauth = MagicMock()
    oauth.build_service.return_value = mock_service
    svc = GmailService(oauth)
    svc.service = mock_service
    return {"oauth_manager": oauth, "cache_manager": None, "_gmail_svc": svc}


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def cli_svc(mock_service):
    """Return (ctx_obj, mock_service) pair for CLI tests."""
    return _cli_ctx_obj(mock_service), mock_service


class TestCLIList:
    def test_list_command_prints_table(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_list

        mock_service.list.return_value.execute.return_value = {
            "messages": [{"id": "m1"}]
        }
        mock_service.get.return_value.execute.return_value = _raw_message(
            "m1", subject="Hello World"
        )
        result = runner.invoke(gmail_list, [], obj=ctx_obj)
        assert result.exit_code == 0
        assert "Hello World" in result.output

    def test_list_unread_flag_appends_query(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_list

        mock_service.list.return_value.execute.return_value = {"messages": []}
        runner.invoke(gmail_list, ["--unread"], obj=ctx_obj)
        q = mock_service.list.call_args.kwargs["q"]
        assert "is:unread" in q

    def test_list_no_messages_prints_info(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_list

        mock_service.list.return_value.execute.return_value = {"messages": []}
        result = runner.invoke(gmail_list, [], obj=ctx_obj)
        assert result.exit_code == 0
        assert "No messages" in result.output


class TestCLIRead:
    def test_read_displays_headers_and_body(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_read

        mock_service.get.return_value.execute.return_value = _raw_message(
            "m1", body_plain="Read this carefully."
        )
        result = runner.invoke(gmail_read, ["m1"], obj=ctx_obj)
        assert result.exit_code == 0
        assert "alice@example.com" in result.output
        assert "Read this carefully." in result.output

    def test_read_missing_message_exits_nonzero(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_read

        mock_service.get.return_value.execute.side_effect = _make_http_error(404)
        result = runner.invoke(gmail_read, ["missing"], obj=ctx_obj)
        assert result.exit_code != 0


class TestCLISend:
    def test_send_success(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_send

        mock_service.send.return_value.execute.return_value = {"id": "sent1"}
        result = runner.invoke(
            gmail_send,
            ["--to", "bob@example.com", "--subject", "Hi", "--body", "Hello"],
            obj=ctx_obj,
        )
        assert result.exit_code == 0
        assert "sent" in result.output.lower()

    def test_send_failure_exits_nonzero(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_send

        mock_service.send.return_value.execute.side_effect = _make_http_error(500)
        result = runner.invoke(
            gmail_send,
            ["--to", "bob@example.com", "--subject", "Hi", "--body", "text"],
            obj=ctx_obj,
        )
        assert result.exit_code != 0


class TestCLIReply:
    def test_reply_success(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_reply

        mock_service.get.return_value.execute.return_value = _raw_message("m1")
        mock_service.send.return_value.execute.return_value = {"id": "r1"}
        result = runner.invoke(
            gmail_reply, ["m1", "--body", "Got it"], obj=ctx_obj
        )
        assert result.exit_code == 0
        assert "sent" in result.output.lower()

    def test_reply_failure_exits_nonzero(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_reply

        mock_service.get.return_value.execute.side_effect = _make_http_error(404)
        result = runner.invoke(
            gmail_reply, ["missing", "--body", "text"], obj=ctx_obj
        )
        assert result.exit_code != 0


class TestCLIDraft:
    def test_draft_success(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_draft

        mock_service.create.return_value.execute.return_value = {"id": "d1"}
        result = runner.invoke(
            gmail_draft,
            ["--to", "a@b.com", "--subject", "Draft", "--body", "body"],
            obj=ctx_obj,
        )
        assert result.exit_code == 0
        assert "draft" in result.output.lower()

    def test_draft_failure_exits_nonzero(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_draft

        mock_service.create.return_value.execute.side_effect = _make_http_error(500)
        result = runner.invoke(
            gmail_draft,
            ["--to", "a@b.com", "--subject", "x", "--body", "y"],
            obj=ctx_obj,
        )
        assert result.exit_code != 0


class TestCLILabel:
    def test_add_label(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_label

        mock_service.list.return_value.execute.return_value = {"labels": []}
        mock_service.create.return_value.execute.return_value = {
            "id": "Label_1", "name": "Bug"
        }
        mock_service.modify.return_value.execute.return_value = {}
        result = runner.invoke(gmail_label, ["m1", "--add", "Bug"], obj=ctx_obj)
        assert result.exit_code == 0
        assert "updated" in result.output.lower()

    def test_no_flags_shows_usage_error(self, runner, cli_svc):
        ctx_obj, _ = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_label

        result = runner.invoke(gmail_label, ["m1"], obj=ctx_obj)
        assert result.exit_code != 0


class TestCLIMark:
    @pytest.mark.parametrize("flag,label_key,label_val", [
        ("--read",    "removeLabelIds", "UNREAD"),
        ("--unread",  "addLabelIds",    "UNREAD"),
        ("--star",    "addLabelIds",    "STARRED"),
        ("--unstar",  "removeLabelIds", "STARRED"),
        ("--archive", "removeLabelIds", "INBOX"),
    ])
    def test_mark_flags_modify_correct_labels(
        self, runner, cli_svc, flag, label_key, label_val
    ):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_mark

        mock_service.list.return_value.execute.return_value = {"labels": []}
        mock_service.modify.return_value.execute.return_value = {}
        result = runner.invoke(gmail_mark, ["m1", flag], obj=ctx_obj)
        assert result.exit_code == 0
        body = mock_service.modify.call_args.kwargs["body"]
        assert label_val in body[label_key]

    def test_mark_trash(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_mark

        mock_service.trash.return_value.execute.return_value = {}
        result = runner.invoke(gmail_mark, ["m1", "--trash"], obj=ctx_obj)
        assert result.exit_code == 0
        mock_service.trash.assert_called_once()

    def test_mark_no_flag_shows_usage_error(self, runner, cli_svc):
        ctx_obj, _ = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_mark

        result = runner.invoke(gmail_mark, ["m1"], obj=ctx_obj)
        assert result.exit_code != 0


class TestCLIFilters:
    def test_filters_list_prints_table(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_filters

        mock_service.list.return_value.execute.return_value = {
            "filter": [
                {
                    "id": "f1",
                    "criteria": {"from": "spam@bad.com"},
                    "action": {"addLabelIds": [], "removeLabelIds": ["INBOX"]},
                }
            ]
        }
        result = runner.invoke(gmail_filters, ["list"], obj=ctx_obj)
        assert result.exit_code == 0
        assert "spam@bad.com" in result.output

    def test_filters_create_success(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_filters

        mock_service.list.return_value.execute.return_value = {"labels": []}
        mock_service.create.return_value.execute.return_value = {"id": "fnew"}
        result = runner.invoke(
            gmail_filters,
            ["create", "--from", "news@example.com", "--archive"],
            obj=ctx_obj,
        )
        assert result.exit_code == 0
        assert "created" in result.output.lower()

    def test_filters_create_requires_at_least_one_criteria(self, runner, cli_svc):
        ctx_obj, _ = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_filters

        result = runner.invoke(gmail_filters, ["create"], obj=ctx_obj)
        assert result.exit_code != 0

    def test_filters_delete_success(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_filters

        mock_service.delete.return_value.execute.return_value = None
        result = runner.invoke(gmail_filters, ["delete", "f1"], obj=ctx_obj)
        assert result.exit_code == 0
        assert "deleted" in result.output.lower()


# ---------------------------------------------------------------------------
# DevOps CLI commands
# ---------------------------------------------------------------------------


class TestCLIAlert:
    def test_alert_success_exits_zero(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_alert

        mock_service.send.return_value.execute.return_value = {"id": "a1"}
        result = runner.invoke(
            gmail_alert,
            [
                "--status", "success",
                "--pipeline", "deploy-prod",
                "--to", "ops@example.com",
            ],
            obj=ctx_obj,
        )
        assert result.exit_code == 0
        assert "sent" in result.output.lower()

    def test_alert_failure_sends_email_and_exits_nonzero(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_alert

        # Simulate Gmail API error so the alert itself fails to send
        mock_service.send.return_value.execute.side_effect = _make_http_error(500)
        result = runner.invoke(
            gmail_alert,
            [
                "--status", "failure",
                "--pipeline", "test-suite",
                "--to", "ops@example.com",
            ],
            obj=ctx_obj,
        )
        assert result.exit_code != 0

    def test_alert_with_log_file_appends_tail(self, runner, cli_svc, tmp_path):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_alert

        log = tmp_path / "build.log"
        log.write_text("\n".join(f"line {i}" for i in range(100)))
        mock_service.send.return_value.execute.return_value = {"id": "a2"}
        result = runner.invoke(
            gmail_alert,
            [
                "--status", "failure",
                "--pipeline", "ci",
                "--to", "ops@example.com",
                "--log-file", str(log),
                "--log-lines", "10",
            ],
            obj=ctx_obj,
        )
        assert result.exit_code == 0
        # The raw email body sent to the API must contain the last log lines
        raw = mock_service.send.call_args.kwargs["body"]["raw"]
        decoded = base64.urlsafe_b64decode(raw).decode(errors="replace")
        assert "line 99" in decoded


class TestCLIEscalate:
    def test_escalate_p1_subject(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_escalate

        mock_service.send.return_value.execute.return_value = {"id": "e1"}
        result = runner.invoke(
            gmail_escalate,
            [
                "--to", "sre@example.com",
                "--severity", "p1",
                "--message", "Database is down",
            ],
            obj=ctx_obj,
        )
        assert result.exit_code == 0
        raw = mock_service.send.call_args.kwargs["body"]["raw"]
        decoded = base64.urlsafe_b64decode(raw).decode(errors="replace")
        assert "[P1]" in decoded
        assert "Database is down" in decoded

    def test_escalate_cc_oncall_from_config(self, runner, cli_svc, tmp_path):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_escalate
        from gsuite_cli.config import hermes_config as hcfg

        cfg_path = tmp_path / "config.yaml"
        hcfg.save({"oncall": {"email": "oncall@example.com"}}, config_path=cfg_path)

        mock_service.send.return_value.execute.return_value = {"id": "e2"}
        with patch.object(hcfg, "get_oncall_email", return_value="oncall@example.com"):
            result = runner.invoke(
                gmail_escalate,
                [
                    "--to", "sre@example.com",
                    "--severity", "p2",
                    "--message", "High CPU",
                    "--cc-oncall",
                ],
                obj=ctx_obj,
            )
        assert result.exit_code == 0
        # CC header must be set in the outbound message
        raw = mock_service.send.call_args.kwargs["body"]["raw"]
        decoded = base64.urlsafe_b64decode(raw).decode(errors="replace")
        assert "oncall@example.com" in decoded

    def test_escalate_failure_exits_nonzero(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_escalate

        mock_service.send.return_value.execute.side_effect = _make_http_error(500)
        result = runner.invoke(
            gmail_escalate,
            ["--to", "x@x.com", "--severity", "p3", "--message", "Issue"],
            obj=ctx_obj,
        )
        assert result.exit_code != 0


class TestCLIDigest:
    def test_digest_sends_email(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_digest

        mock_service.list.return_value.execute.return_value = {
            "messages": [{"id": "m1"}]
        }
        mock_service.get.return_value.execute.return_value = _raw_message(
            "m1", subject="Alert: disk full"
        )
        mock_service.send.return_value.execute.return_value = {"id": "dg1"}
        result = runner.invoke(
            gmail_digest,
            ["--since", "24h", "--to", "ops@example.com"],
            obj=ctx_obj,
        )
        assert result.exit_code == 0
        assert "sent" in result.output.lower()

    def test_digest_no_messages_exits_zero_with_info(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.services.gmail_commands import gmail_digest

        mock_service.list.return_value.execute.return_value = {"messages": []}
        result = runner.invoke(
            gmail_digest,
            ["--since", "24h", "--to", "ops@example.com"],
            obj=ctx_obj,
        )
        assert result.exit_code == 0
        assert "No messages" in result.output


class TestCLIScheduleSummary:
    def test_prints_cron_snippets(self, runner):
        from gsuite_cli.services.gmail_commands import gmail_schedule_summary

        result = runner.invoke(
            gmail_schedule_summary,
            ["--since", "24h", "--to", "ops@example.com"],
        )
        assert result.exit_code == 0
        # Should print at least one scheduling format
        assert "cron" in result.output.lower() or "0 8" in result.output
        assert "hermes gmail digest" in result.output


# ---------------------------------------------------------------------------
# hermes_config helpers
# ---------------------------------------------------------------------------


class TestHermesConfig:
    def test_load_returns_empty_when_no_file(self, tmp_path):
        from gsuite_cli.config import hermes_config as hcfg

        data = hcfg.load(config_path=tmp_path / "nonexistent.yaml")
        assert data == {}

    def test_save_and_load_roundtrip(self, tmp_path):
        from gsuite_cli.config import hermes_config as hcfg

        path = tmp_path / "config.yaml"
        hcfg.save({"oncall": {"email": "oncall@example.com"}}, config_path=path)
        data = hcfg.load(config_path=path)
        assert data["oncall"]["email"] == "oncall@example.com"

    def test_get_dot_notation(self, tmp_path):
        from gsuite_cli.config import hermes_config as hcfg

        path = tmp_path / "config.yaml"
        hcfg.save({"oncall": {"email": "oc@example.com", "name": "SRE"}}, config_path=path)
        assert hcfg.get("oncall.email", config_path=path) == "oc@example.com"
        assert hcfg.get("oncall.name", config_path=path) == "SRE"
        assert hcfg.get("oncall.missing", default="fallback", config_path=path) == "fallback"

    def test_set_value_creates_nested_keys(self, tmp_path):
        from gsuite_cli.config import hermes_config as hcfg

        path = tmp_path / "config.yaml"
        hcfg.set_value("oncall.email", "new@example.com", config_path=path)
        assert hcfg.get("oncall.email", config_path=path) == "new@example.com"

    def test_get_oncall_email_none_when_unset(self, tmp_path):
        from gsuite_cli.config import hermes_config as hcfg

        result = hcfg.get_oncall_email(config_path=tmp_path / "missing.yaml")
        assert result is None

    def test_get_oncall_email_returns_value(self, tmp_path):
        from gsuite_cli.config import hermes_config as hcfg

        path = tmp_path / "config.yaml"
        hcfg.save({"oncall": {"email": "oc@example.com"}}, config_path=path)
        assert hcfg.get_oncall_email(config_path=path) == "oc@example.com"

    def test_get_oncall_name_defaults(self, tmp_path):
        from gsuite_cli.config import hermes_config as hcfg

        name = hcfg.get_oncall_name(config_path=tmp_path / "missing.yaml")
        assert name == "On-Call"


# ---------------------------------------------------------------------------
# Additional Gmail Tests (Prompt 3 Extended Coverage)
# ---------------------------------------------------------------------------

class TestGmailProfileAndConnection:
    def test_get_profile_success(self, gmail_svc, mock_service):
        mock_service.users().getProfile().execute.return_value = {
            "emailAddress": "dev@example.com",
            "messagesTotal": 125,
            "threadsTotal": 45,
            "historyId": "hist123",
        }
        profile = gmail_svc.get_profile()
        assert profile is not None
        assert profile["email_address"] == "dev@example.com"
        assert profile["messages_total"] == 125

    def test_test_connection_success(self, gmail_svc, mock_service, mock_oauth):
        mock_oauth.get_auth_info.return_value = {
            "authenticated": True,
            "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
            "token_expiry": "2026-12-31",
        }
        mock_service.users().getProfile().execute.return_value = {
            "emailAddress": "dev@example.com",
            "messagesTotal": 10,
        }
        result = gmail_svc.test_connection()
        assert result["connected"] is True
        assert result["email"] == "dev@example.com"


class TestGmailDraftsExtended:
    def test_list_and_get_draft(self, gmail_svc, mock_service):
        mock_service.drafts.return_value.list.return_value.execute.return_value = {
            "drafts": [{"id": "d1"}]
        }
        mock_service.drafts.return_value.get.return_value.execute.return_value = {
            "id": "d1",
            "message": {
                "id": "m1",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Draft Title"},
                        {"name": "To", "value": "target@example.com"},
                    ],
                    "body": {"data": _b64("Draft Body")},
                },
            },
        }
        drafts = gmail_svc.list_drafts()
        assert len(drafts) == 1
        assert drafts[0]["subject"] == "Draft Title"

    def test_send_draft(self, gmail_svc, mock_service):
        mock_service.drafts.return_value.send.return_value.execute.return_value = {
            "id": "msg-sent"
        }
        sent_id = gmail_svc.send_draft("d1")
        assert sent_id == "msg-sent"

    def test_delete_draft(self, gmail_svc, mock_service):
        mock_service.drafts.return_value.delete.return_value.execute.return_value = {}
        assert gmail_svc.delete_draft("d1") is True


class TestGmailLabelsAndThreadsExtended:
    def test_create_and_delete_label(self, gmail_svc, mock_service):
        mock_service.labels.return_value.create.return_value.execute.return_value = {
            "id": "Label_99",
            "name": "CustomLabel",
        }
        mock_service.labels.return_value.delete.return_value.execute.return_value = {}

        created = gmail_svc.create_label("CustomLabel")
        assert created["id"] == "Label_99"
        deleted = gmail_svc.delete_label("Label_99")
        assert deleted is True

    def test_list_threads(self, gmail_svc, mock_service):
        mock_service.threads.return_value.list.return_value.execute.return_value = {
            "threads": [{"id": "th1"}]
        }
        mock_service.threads.return_value.get.return_value.execute.return_value = {
            "id": "th1",
            "messages": [
                _raw_message("m1", subject="Thread Subj", body_plain="Msg 1")
            ],
        }
        threads = gmail_svc.list_threads()
        assert len(threads) == 1
        assert threads[0]["id"] == "th1"

    def test_forward_message(self, gmail_svc, mock_service):
        mock_service.get.return_value.execute.return_value = _raw_message(
            "m1", subject="Original Subj", body_plain="Orig Body"
        )
        mock_service.send.return_value.execute.return_value = {"id": "fwd-msg"}

        sent = gmail_svc.forward_message(
            message_id="m1",
            to="fwd@example.com",
            body="FYI see below",
        )
        assert sent == "fwd-msg"

    def test_untrash_message(self, gmail_svc, mock_service):
        mock_service.messages.return_value.untrash.return_value.execute.return_value = {}
        assert gmail_svc.untrash_message("m1") is True

    def test_mark_as_spam(self, gmail_svc, mock_service):
        mock_service.messages.return_value.modify.return_value.execute.return_value = {}
        assert gmail_svc.mark_as_spam("m1") is True


class TestGmailNewCLICommands:
    def test_cli_forward(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.cli import cli

        mock_service.get.return_value.execute.return_value = _raw_message("m1")
        mock_service.send.return_value.execute.return_value = {"id": "fwd1"}

        result = runner.invoke(
            cli,
            ["gmail", "forward", "m1", "--to", "someone@example.com"],
            obj=ctx_obj,
        )
        assert result.exit_code == 0
        assert "forwarded successfully" in result.output

    def test_cli_threads(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.cli import cli

        mock_service.threads.return_value.list.return_value.execute.return_value = {
            "threads": [{"id": "t100", "snippet": "Conversation text"}]
        }
        mock_service.threads.return_value.get.return_value.execute.return_value = {
            "id": "t100",
            "messages": [_raw_message("m1")],
        }

        result = runner.invoke(cli, ["gmail", "threads"], obj=ctx_obj)
        assert result.exit_code == 0
        assert "t100" in result.output

    def test_cli_profile(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.cli import cli

        mock_service.users().getProfile().execute.return_value = {
            "emailAddress": "testuser@gmail.com",
            "messagesTotal": 500,
            "threadsTotal": 200,
        }

        result = runner.invoke(cli, ["gmail", "profile"], obj=ctx_obj)
        assert result.exit_code == 0
        assert "testuser@gmail.com" in result.output
        assert "500" in result.output

    def test_cli_test_connection(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.cli import cli

        mock_service.users().getProfile().execute.return_value = {
            "emailAddress": "testuser@gmail.com",
            "messagesTotal": 500,
        }

        result = runner.invoke(cli, ["gmail", "test-connection"], obj=ctx_obj)
        assert result.exit_code == 0
        assert "connection successful" in result.output

    def test_cli_dev_unread(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.cli import cli

        mock_service.list.return_value.execute.return_value = {"messages": [{"id": "u1"}]}
        mock_service.get.return_value.execute.return_value = _raw_message("u1", subject="Urgent bug")

        result = runner.invoke(cli, ["unread"], obj=ctx_obj)
        assert result.exit_code == 0
        assert "Urgent bug" in result.output

    def test_cli_dev_inbox(self, runner, cli_svc):
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.cli import cli

        mock_service.list.return_value.execute.return_value = {"messages": [{"id": "i1"}]}
        mock_service.get.return_value.execute.return_value = _raw_message("i1", subject="Weekly report")

        result = runner.invoke(cli, ["inbox"], obj=ctx_obj)
        assert result.exit_code == 0
        assert "Weekly report" in result.output


class TestGmailProfileDashboard:
    def test_profile_full_success_and_formatting(self, runner, cli_svc):
        """Verify profile loads with account, mailbox, labels, connection stats and thousands separators."""
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.cli import cli

        # 1. Base profile
        mock_service.users().getProfile().execute.return_value = {
            "emailAddress": "nsakthiveldev@gmail.com",
            "messagesTotal": 2846,
            "threadsTotal": 2678,
            "historyId": "267776",
        }

        # 2. Account name via sendAs
        mock_service.users().settings().sendAs().list().execute.return_value = {
            "sendAs": [
                {
                    "sendAsEmail": "nsakthiveldev@gmail.com",
                    "displayName": "NSakthivel",
                    "isPrimary": True,
                }
            ]
        }

        # 3. Labels (8 system, 5 custom) with unread, drafts, starred counts
        mock_service.users().labels().list().execute.return_value = {
            "labels": [
                {"id": "INBOX", "type": "system"},
                {"id": "UNREAD", "type": "system", "messagesTotal": 124},
                {"id": "DRAFT", "type": "system", "messagesTotal": 7},
                {"id": "STARRED", "type": "system", "messagesTotal": 36},
                {"id": "SENT", "type": "system"},
                {"id": "SPAM", "type": "system"},
                {"id": "TRASH", "type": "system"},
                {"id": "IMPORTANT", "type": "system"},
                {"id": "Work", "type": "user"},
                {"id": "Personal", "type": "user"},
                {"id": "Projects", "type": "user"},
                {"id": "Finance", "type": "user"},
                {"id": "Archived", "type": "user"},
            ]
        }

        result = runner.invoke(cli, ["gmail", "profile"], obj=ctx_obj, input="b\n")
        assert result.exit_code == 0

        # Requirement 1: Profile loads
        assert "✉ Gmail Profile" in result.output
        assert "==================================================" in result.output

        # Requirement 2: Account name
        assert "NSakthivel" in result.output

        # Requirement 3: Email address
        assert "nsakthiveldev@gmail.com" in result.output

        # Requirement 4: Message count (formatted)
        assert "2,846" in result.output

        # Requirement 5: Thread count (formatted)
        assert "2,678" in result.output

        # Requirement 6: Unread count
        assert "124" in result.output

        # Requirement 7: Draft count
        assert "7" in result.output

        # Requirement 8: Starred count
        assert "36" in result.output

        # Requirement 9: System labels count
        assert "8" in result.output

        # Requirement 10: Custom labels count
        assert "5" in result.output

        # Requirement 11: API status shows Connected
        assert "✓ Connected" in result.output

        # Requirement 13: History ID displayed
        assert "267776" in result.output

        # Requirement 16: No OAuth tokens or secrets
        assert "token" not in result.output.lower() or "api status" in result.output.lower()
        assert "refresh_token" not in result.output
        assert "client_secret" not in result.output

        # Requirement 17 & 18: Navigation displayed
        assert "[b] Back" in result.output
        assert "[0] Exit" in result.output

    def test_profile_labels_via_get_call(self, runner, cli_svc):
        """Verify unread, drafts, and starred counts are fetched via labels.get when not in list."""
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.cli import cli

        mock_service.users().getProfile().execute.return_value = {
            "emailAddress": "test@example.com",
            "messagesTotal": 100,
            "threadsTotal": 50,
            "historyId": "9999",
        }
        mock_service.users().labels().list().execute.return_value = {
            "labels": [
                {"id": "UNREAD", "type": "system"},
                {"id": "DRAFT", "type": "system"},
                {"id": "STARRED", "type": "system"},
            ]
        }

        def fake_label_get(userId, id):
            mock_call = MagicMock()
            if id == "UNREAD":
                mock_call.execute.return_value = {"id": "UNREAD", "messagesTotal": 42}
            elif id == "DRAFT":
                mock_call.execute.return_value = {"id": "DRAFT", "messagesTotal": 5}
            elif id == "STARRED":
                mock_call.execute.return_value = {"id": "STARRED", "messagesTotal": 12}
            else:
                mock_call.execute.return_value = {}
            return mock_call

        mock_service.users().labels().get.side_effect = fake_label_get

        result = runner.invoke(cli, ["gmail", "profile"], obj=ctx_obj, input="b\n")
        assert result.exit_code == 0
        assert "42" in result.output
        assert "5" in result.output
        assert "12" in result.output

    def test_profile_auth_failure_status(self, runner, cli_svc):
        """Requirement 12: API status shows Authentication Required when auth fails."""
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.cli import cli
        from googleapiclient.errors import HttpError
        import httplib2

        resp = httplib2.Response({"status": 401})
        mock_service.users().getProfile().execute.side_effect = HttpError(resp, b"Invalid Credentials")

        result = runner.invoke(cli, ["gmail", "profile"], obj=ctx_obj, input="b\n")
        assert result.exit_code == 0
        assert "✗ Authentication Required" in result.output

    def test_profile_connection_failed_status(self, runner, cli_svc):
        """Requirement 12: API status shows Connection Failed when connection fails."""
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.cli import cli

        mock_service.users().getProfile().execute.side_effect = ConnectionError("Failed to establish a new connection")

        result = runner.invoke(cli, ["gmail", "profile"], obj=ctx_obj, input="b\n")
        assert result.exit_code == 0
        assert "✗ Connection Failed" in result.output

    def test_profile_missing_statistics_displayed_as_dash(self, runner, cli_svc):
        """Requirement 14: Missing statistics are displayed as '-' instead of crashing."""
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.cli import cli

        mock_service.users().getProfile().execute.return_value = {
            "emailAddress": "test@example.com",
            "messagesTotal": 1500,
            "threadsTotal": 800,
            "historyId": "",
        }
        # sendAs fails -> Name should be '-'
        mock_service.users().settings().sendAs().list().execute.side_effect = Exception("Settings forbidden")
        # labels list fails -> System/Custom labels and counts should be '-'
        mock_service.users().labels().list().execute.side_effect = Exception("Labels API error")
        mock_service.users().labels().get().execute.side_effect = Exception("Label get error")

        result = runner.invoke(cli, ["gmail", "profile"], obj=ctx_obj, input="b\n")
        assert result.exit_code == 0
        assert "1,500" in result.output
        assert "800" in result.output
        assert "-" in result.output

    def test_profile_exit_navigation(self, runner, cli_svc):
        """Requirement 18: [0] Exit exits properly with exit code 0."""
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.cli import cli

        mock_service.users().getProfile().execute.return_value = {
            "emailAddress": "exit@example.com",
            "messagesTotal": 10,
            "threadsTotal": 5,
        }

        result = runner.invoke(cli, ["gmail", "profile"], obj=ctx_obj, input="0\n")
        assert result.exit_code == 0

    def test_profile_back_navigation(self, runner, cli_svc):
        """Requirement 17: [b] Back returns properly with exit code 0."""
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.cli import cli

        mock_service.users().getProfile().execute.return_value = {
            "emailAddress": "back@example.com",
            "messagesTotal": 10,
            "threadsTotal": 5,
        }

        result = runner.invoke(cli, ["gmail", "profile"], obj=ctx_obj, input="b\n")
        assert result.exit_code == 0

    def test_profile_large_numbers_formatted(self, runner, cli_svc):
        """Requirement 15: Large numbers formatted with thousands separators."""
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.cli import cli

        mock_service.users().getProfile().execute.return_value = {
            "emailAddress": "dev@example.com",
            "messagesTotal": 12456,
            "threadsTotal": 8910,
        }
        mock_service.users().labels().list().execute.return_value = {
            "labels": [
                {"id": "UNREAD", "type": "system", "messagesTotal": 1000},
                {"id": "DRAFT", "type": "system", "messagesTotal": 500},
                {"id": "STARRED", "type": "system", "messagesTotal": 250},
            ]
        }

        result = runner.invoke(cli, ["gmail", "profile"], obj=ctx_obj, input="b\n")
        assert result.exit_code == 0
        assert "12,456" in result.output
        assert "8,910" in result.output
        assert "1,000" in result.output
        assert "500" in result.output


class TestGmailLabelsHumanFlows:
    """Comprehensive test suite for Gmail Labels SEARCH -> SELECT -> VIEW -> ACTION workflows."""

    def _setup_labels_and_messages(self, mock_service):
        labels_data = [
            {"id": "INBOX", "name": "INBOX", "type": "system"},
            {"id": "SENT", "name": "SENT", "type": "system"},
            {"id": "STARRED", "name": "STARRED", "type": "system"},
            {"id": "IMPORTANT", "name": "IMPORTANT", "type": "system"},
            {"id": "Label_work", "name": "Work", "type": "user"},
            {"id": "Label_proj", "name": "Projects", "type": "user"},
            {"id": "Label_coll", "name": "College", "type": "user"},
            {"id": "Label_pers", "name": "Personal", "type": "user"},
        ]

        labels_mock = MagicMock()
        messages_mock = MagicMock()

        mock_service.users.return_value = mock_service
        mock_service.labels.return_value = labels_mock
        mock_service.messages.return_value = messages_mock

        labels_mock.list.return_value.execute.return_value = {"labels": labels_data}
        labels_mock.create.return_value.execute.return_value = {"id": "Label_new", "name": "DevSprint"}
        labels_mock.patch.return_value.execute.return_value = {"id": "Label_proj", "name": "HermesProjects"}
        labels_mock.delete.return_value.execute.return_value = {}

        # Raw message
        msg1 = _raw_message(
            "msg1",
            subject="Hermes project update",
            from_="John Doe <john@example.com>",
            to_="nsakthiveldev@gmail.com",
            body_plain="Here is the latest update on Hermes CLI.",
            label_ids=["INBOX", "IMPORTANT", "Label_proj"],
        )
        messages_mock.list.return_value.execute.return_value = {"messages": [{"id": "msg1"}]}
        messages_mock.get.return_value.execute.return_value = msg1
        messages_mock.modify.return_value.execute.return_value = {
            "id": "msg1",
            "labelIds": ["INBOX", "IMPORTANT", "Label_work"],
        }
        return labels_data, msg1, labels_mock, messages_mock

    def test_labels_menu_renders_and_back_navigation(self, runner, cli_svc):
        """Test Labels MENU renders with expected options and navigates back cleanly."""
        ctx_obj, mock_service = cli_svc
        from gsuite_cli.cli import cli

        result = runner.invoke(cli, ["gmail", "labels"], obj=ctx_obj, input="b\n")
        assert result.exit_code == 0
        assert "Labels MENU" in result.output
        assert "[1] List all labels" in result.output
        assert "[2] Apply label to message" in result.output
        assert "[3] Remove label from message" in result.output
        assert "[b] Back to Gmail Menu" in result.output
        assert "[0] Exit" in result.output

    def test_list_all_labels_grouped_system_and_custom(self, runner, cli_svc):
        """Test [1] List all labels groups System and Custom labels and hides raw IDs."""
        ctx_obj, mock_service = cli_svc
        self._setup_labels_and_messages(mock_service)
        from gsuite_cli.cli import cli

        # Select 1 (List all labels), then b (Back), then b (Exit menu)
        result = runner.invoke(cli, ["gmail", "labels"], obj=ctx_obj, input="1\nb\nb\n")
        assert result.exit_code == 0
        assert "System Labels" in result.output
        assert "Custom Labels" in result.output
        assert "Inbox" in result.output
        assert "Sent" in result.output
        assert "Work" in result.output
        assert "Projects" in result.output
        # Verify raw internal label IDs are not displayed
        assert "Label_work" not in result.output
        assert "Label_proj" not in result.output

    def test_list_labels_select_custom_and_view_emails(self, runner, cli_svc):
        """Test selecting a label shows supported actions: View emails, Rename, Delete."""
        ctx_obj, mock_service = cli_svc
        self._setup_labels_and_messages(mock_service)
        from gsuite_cli.cli import cli

        # Select 1 (List labels) -> Select Custom label (6: Projects) -> 1 (View emails) -> b -> b -> b
        inputs = "1\n6\n1\nb\nb\nb\nb\n"
        result = runner.invoke(cli, ["gmail", "labels"], obj=ctx_obj, input=inputs)
        assert result.exit_code == 0
        assert "Projects" in result.output
        assert "Name       : Projects" in result.output
        assert "Type       : Custom" in result.output
        assert "[1] View emails" in result.output
        assert "[2] Rename label" in result.output
        assert "[3] Delete label" in result.output

    def test_list_labels_custom_rename_flow(self, runner, cli_svc):
        """Test renaming a custom label with confirmation."""
        ctx_obj, mock_service = cli_svc
        labels_data, msg1, labels_mock, messages_mock = self._setup_labels_and_messages(mock_service)
        from gsuite_cli.cli import cli

        # 1 (List) -> 6 (Projects) -> 2 (Rename) -> "HermesProjects" -> y (Confirm) -> b -> b -> b
        inputs = "1\n6\n2\nHermesProjects\ny\nb\nb\nb\n"
        result = runner.invoke(cli, ["gmail", "labels"], obj=ctx_obj, input=inputs)
        assert result.exit_code == 0
        assert "Rename Label" in result.output
        assert "Label renamed to \"HermesProjects\" successfully." in result.output
        labels_mock.patch.assert_called()

    def test_list_labels_custom_delete_flow(self, runner, cli_svc):
        """Test deleting a custom label with confirmation."""
        ctx_obj, mock_service = cli_svc
        labels_data, msg1, labels_mock, messages_mock = self._setup_labels_and_messages(mock_service)
        from gsuite_cli.cli import cli

        # 1 (List) -> 6 (Projects) -> 3 (Delete) -> y (Confirm) -> b -> b
        inputs = "1\n6\n3\ny\nb\nb\n"
        result = runner.invoke(cli, ["gmail", "labels"], obj=ctx_obj, input=inputs)
        assert result.exit_code == 0
        assert "Label \"Projects\" deleted successfully." in result.output
        labels_mock.delete.assert_called()

    def test_apply_label_search_select_view_apply_success(self, runner, cli_svc):
        """Test complete SEARCH -> SELECT -> VIEW -> APPLY flow without asking for Message ID."""
        ctx_obj, mock_service = cli_svc
        labels_data, msg1, labels_mock, messages_mock = self._setup_labels_and_messages(mock_service)
        from gsuite_cli.cli import cli

        # Workflow:
        # 2 (Apply label)
        # "project" (Search query)
        # 1 (Select email from numbered list)
        # 1 (Apply Label from email view)
        # 1 (Select Work label - not currently applied)
        # y (Confirm apply)
        # b (Back to exit menu)
        inputs = "2\nproject\n1\n1\n1\ny\nb\n"
        result = runner.invoke(cli, ["gmail", "labels"], obj=ctx_obj, input=inputs)
        assert result.exit_code == 0
        # Verify no Message ID prompt
        assert "Enter message ID:" not in result.output
        assert "Search email:" in result.output
        assert "Search Results" in result.output
        assert "Hermes project update" in result.output
        assert "Email" in result.output
        assert "From    : John Doe" in result.output
        assert "Current Labels" in result.output
        assert "Apply Label" in result.output
        assert "✓ Label \"Work\" applied to the email." in result.output
        messages_mock.modify.assert_called()

    def test_apply_label_already_applied_prevents_duplicate_api_call(self, runner, cli_svc):
        """Test selecting a label already applied shows notice and does not make duplicate API call."""
        ctx_obj, mock_service = cli_svc
        labels_data, msg1, labels_mock, messages_mock = self._setup_labels_and_messages(mock_service)
        messages_mock.modify.reset_mock()
        from gsuite_cli.cli import cli

        # Msg1 already has "Projects" (Label_proj)
        # Labels list: [1] Work, [2] Projects, [3] College, [4] Personal, [5] Starred, [6] Important, [7] Create New Label
        # Workflow:
        # 2 (Apply label) -> "project" -> 1 (Select msg) -> 1 (Apply Label) -> 2 (Select Projects) -> b -> b
        inputs = "2\nproject\n1\n1\n2\nb\nb\n"
        result = runner.invoke(cli, ["gmail", "labels"], obj=ctx_obj, input=inputs)
        assert result.exit_code == 0
        assert "already applied to this email" in result.output
        messages_mock.modify.assert_not_called()

    def test_apply_label_create_new_label_and_auto_apply(self, runner, cli_svc):
        """Test creating a new label inside Apply Label workflow automatically applies it."""
        ctx_obj, mock_service = cli_svc
        labels_data, msg1, labels_mock, messages_mock = self._setup_labels_and_messages(mock_service)
        from gsuite_cli.cli import cli

        # Labels: 1-4 custom, 5-6 system, 7 Create New Label
        # Inputs:
        # 2 (Apply label)
        # "project"
        # 1 (Select email)
        # 1 (Apply Label)
        # 7 (Create New Label)
        # "DevSprint" (New label name)
        # y (Confirm creation)
        # b (Back)
        inputs = "2\nproject\n1\n1\n7\nDevSprint\ny\nb\n"
        result = runner.invoke(cli, ["gmail", "labels"], obj=ctx_obj, input=inputs)
        assert result.exit_code == 0
        assert "Create New Label" in result.output
        assert "✓ Label \"DevSprint\" created." in result.output
        assert "✓ Label \"DevSprint\" applied to the email." in result.output
        labels_mock.create.assert_called()
        messages_mock.modify.assert_called()

    def test_apply_label_duplicate_name_offers_apply_existing(self, runner, cli_svc):
        """Test typing an existing label name warns user and allows applying existing label."""
        ctx_obj, mock_service = cli_svc
        labels_data, msg1, labels_mock, messages_mock = self._setup_labels_and_messages(mock_service)
        from gsuite_cli.cli import cli

        # Inputs:
        # 2 (Apply label) -> "project" -> 1 (email) -> 1 (Apply) -> 7 (Create New Label)
        # "Work" (already exists!)
        # 1 (Apply existing label)
        # y (Confirm apply)
        # b (Back)
        inputs = "2\nproject\n1\n1\n7\nWork\n1\ny\nb\n"
        result = runner.invoke(cli, ["gmail", "labels"], obj=ctx_obj, input=inputs)
        assert result.exit_code == 0
        assert "Label \"Work\" already exists." in result.output
        assert "[1] Apply existing label" in result.output
        assert "✓ Label \"Work\" applied to the email." in result.output

    def test_remove_label_only_shows_applied_labels_and_removes(self, runner, cli_svc):
        """Test [3] Remove label only shows labels currently applied and requires confirmation."""
        ctx_obj, mock_service = cli_svc
        labels_data, msg1, labels_mock, messages_mock = self._setup_labels_and_messages(mock_service)
        from gsuite_cli.cli import cli

        # Msg1 has labels: INBOX, IMPORTANT, Projects (Label_proj)
        # Inputs:
        # 3 (Remove label)
        # "project"
        # 1 (Select email)
        # 1 (Remove Label from email view)
        # Applied labels listed: Inbox, Important, Projects (1, 2, 3)
        # 3 (Select Projects)
        # y (Confirm removal)
        # b (Back)
        inputs = "3\nproject\n1\n1\n3\ny\nb\n"
        result = runner.invoke(cli, ["gmail", "labels"], obj=ctx_obj, input=inputs)
        assert result.exit_code == 0
        assert "Select Label to Remove" in result.output
        assert "Remove Label" in result.output
        assert "✓ Label \"Projects\" removed successfully." in result.output
        select_section = result.output.split("Select Label to Remove")[1].split("Remove Label")[0]
        assert "Work" not in select_section
        messages_mock.modify.assert_called()

    def test_remove_label_cancelled_confirmation(self, runner, cli_svc):
        """Test cancelling removal does not call modify API."""
        ctx_obj, mock_service = cli_svc
        labels_data, msg1, labels_mock, messages_mock = self._setup_labels_and_messages(mock_service)
        messages_mock.modify.reset_mock()
        from gsuite_cli.cli import cli

        # Inputs: 3 (Remove label) -> "project" -> 1 -> 1 -> 3 -> n (Decline confirm) -> b -> b -> b
        inputs = "3\nproject\n1\n1\n3\nn\nb\nb\nb\n"
        result = runner.invoke(cli, ["gmail", "labels"], obj=ctx_obj, input=inputs)
        assert result.exit_code == 0
        assert "Removal cancelled." in result.output
        messages_mock.modify.assert_not_called()

    def test_empty_search_results_handled_gracefully(self, runner, cli_svc):
        """Test search with 0 matches displays helpful message and Search Again/Back options."""
        ctx_obj, mock_service = cli_svc
        labels_data, msg1, labels_mock, messages_mock = self._setup_labels_and_messages(mock_service)
        messages_mock.list.return_value.execute.return_value = {"messages": []}
        from gsuite_cli.cli import cli

        # Inputs: 2 (Apply label) -> "nonexistent" -> b (Back) -> b (Exit)
        inputs = "2\nnonexistent\nb\nb\n"
        result = runner.invoke(cli, ["gmail", "labels"], obj=ctx_obj, input=inputs)
        assert result.exit_code == 0
        assert "No emails found for: nonexistent" in result.output
        assert "[1] Search Again" in result.output
        assert "[b] Back" in result.output

    def test_invalid_selection_reprompts_without_crash(self, runner, cli_svc):
        """Test entering an invalid option displays error and re-prompts without crashing."""
        ctx_obj, mock_service = cli_svc
        self._setup_labels_and_messages(mock_service)
        from gsuite_cli.cli import cli

        # In menu: 99 (invalid) -> b (exit)
        inputs = "99\nb\n"
        result = runner.invoke(cli, ["gmail", "labels"], obj=ctx_obj, input=inputs)
        assert result.exit_code == 0
        assert "✗ Invalid selection." in result.output

    def test_cli_labels_formatted_table_and_json(self, runner, cli_svc):
        """Test hermes gmail labels --format table/json outputs structured data for scripts."""
        ctx_obj, mock_service = cli_svc
        self._setup_labels_and_messages(mock_service)
        from gsuite_cli.cli import cli

        result = runner.invoke(cli, ["gmail", "labels", "--format", "json"], obj=ctx_obj)
        assert result.exit_code == 0
        assert "INBOX" in result.output
        assert "Work" in result.output

    def test_direct_label_command_remains_available(self, runner, cli_svc):
        """Test hermes gmail label <id> --add/--remove remains functional for advanced/direct use."""
        ctx_obj, mock_service = cli_svc
        labels_data, msg1, labels_mock, messages_mock = self._setup_labels_and_messages(mock_service)
        from gsuite_cli.cli import cli

        result = runner.invoke(
            cli,
            ["gmail", "label", "msg1", "--add", "Work", "--remove", "Projects"],
            obj=ctx_obj,
        )
        assert result.exit_code == 0
        assert "Labels updated" in result.output



