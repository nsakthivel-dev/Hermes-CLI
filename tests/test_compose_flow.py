import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch, mock_open


def _make_menu():
    from gsuite_cli.ui.interactive import InteractiveMenu
    menu = InteractiveMenu.__new__(InteractiveMenu)
    menu.options = {}
    return menu


class TestValidateEmailAddress:
    def setup_method(self):
        self.menu = _make_menu()

    def test_valid_simple(self):
        assert self.menu._validate_email_address("user@example.com") is True

    def test_valid_with_dot(self):
        assert self.menu._validate_email_address("first.last@sub.domain.org") is True

    def test_invalid_no_at(self):
        assert self.menu._validate_email_address("notanemail") is False

    def test_invalid_no_domain(self):
        assert self.menu._validate_email_address("user@") is False

    def test_invalid_spaces(self):
        assert self.menu._validate_email_address("user @example.com") is False


class TestValidateEmailList:
    def setup_method(self):
        self.menu = _make_menu()

    def test_single_valid(self):
        ok, bad = self.menu._validate_email_list("a@b.com")
        assert ok is True and bad == ""

    def test_multiple_valid(self):
        ok, bad = self.menu._validate_email_list("a@b.com, c@d.org")
        assert ok is True

    def test_one_invalid(self):
        ok, bad = self.menu._validate_email_list("a@b.com, not-an-email")
        assert ok is False
        assert bad == "not-an-email"

    def test_empty_string(self):
        ok, bad = self.menu._validate_email_list("")
        assert ok is True


class TestFormatFileSize:
    def setup_method(self):
        self.menu = _make_menu()

    def test_bytes(self):
        assert self.menu._format_file_size(512) == "512 B"

    def test_kilobytes(self):
        assert "KB" in self.menu._format_file_size(2048)

    def test_megabytes(self):
        assert "MB" in self.menu._format_file_size(2 * 1024 * 1024)


class TestGetEditor:
    def setup_method(self):
        self.menu = _make_menu()

    def test_falls_back_to_notepad(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("gsuite_cli.ui.interactive.ConfigManager") as MockCfg:
                MockCfg.return_value.get.return_value = None
                editor = self.menu._get_editor()
        assert editor == "notepad.exe"

    def test_reads_editor_env_var(self):
        with patch.dict(os.environ, {"EDITOR": "vim"}, clear=False):
            with patch("gsuite_cli.ui.interactive.ConfigManager") as MockCfg:
                MockCfg.return_value.get.return_value = None
                editor = self.menu._get_editor()
        assert editor == "vim"

    def test_reads_hermes_config(self):
        with patch("gsuite_cli.ui.interactive.ConfigManager") as MockCfg:
            MockCfg.return_value.get.return_value = "code"
            editor = self.menu._get_editor()
        assert editor == "code"


class TestOpenEditorForBody:
    def setup_method(self):
        self.menu = _make_menu()

    def test_successful_launch(self):
        with patch("subprocess.call", return_value=0):
            with patch.object(self.menu, "_get_editor", return_value="notepad.exe"):
                result = self.menu._open_editor_for_body("C:\\tmp\\body.txt")
        assert result is True

    def test_file_not_found_falls_back_to_shell(self):
        with patch("subprocess.call", side_effect=[FileNotFoundError, 0]) as mock_call:
            with patch.object(self.menu, "_get_editor", return_value="notepad.exe"):
                result = self.menu._open_editor_for_body("C:\\tmp\\body.txt")
        assert result is True
        assert mock_call.call_count == 2

    def test_editor_exception_returns_false(self):
        with patch("subprocess.call", side_effect=Exception("broken")):
            with patch.object(self.menu, "_get_editor", return_value="badeditor"):
                with patch.object(self.menu, "show_error"):
                    result = self.menu._open_editor_for_body("C:\\tmp\\body.txt")
        assert result is False


class TestCollectAttachments:
    def setup_method(self):
        self.menu = _make_menu()

    def test_skip_on_empty_enter(self):
        with patch("builtins.input", return_value=""):
            result = self.menu._collect_attachments([])
        assert result == []

    def test_valid_attachment_added(self, tmp_path):
        test_file = tmp_path / "resume.pdf"
        test_file.write_bytes(b"PDF content")
        inputs = iter([str(test_file), "n"])
        with patch("builtins.input", side_effect=inputs):
            result = self.menu._collect_attachments([])
        assert len(result) == 1
        assert result[0]["name"] == "resume.pdf"

    def test_invalid_path_retries(self):
        inputs = iter(["/nonexistent/file.pdf", ""])
        with patch("builtins.input", side_effect=inputs):
            result = self.menu._collect_attachments([])
        assert result == []

    def test_duplicate_attachment_rejected(self, tmp_path):
        test_file = tmp_path / "report.pdf"
        test_file.write_bytes(b"data")
        canon = os.path.normpath(os.path.abspath(str(test_file)))
        existing = [{"path": canon, "name": "report.pdf", "size": 4}]
        inputs = iter([str(test_file), "n"])
        with patch("builtins.input", side_effect=inputs):
            result = self.menu._collect_attachments(existing)
        assert len(result) == 1

    def test_multiple_attachments(self, tmp_path):
        f1 = tmp_path / "a.pdf"
        f2 = tmp_path / "b.pdf"
        f1.write_bytes(b"aaa")
        f2.write_bytes(b"bbb")
        inputs = iter([str(f1), "y", str(f2), "n"])
        with patch("builtins.input", side_effect=inputs):
            result = self.menu._collect_attachments([])
        assert len(result) == 2

    def test_attachment_with_spaces_in_filename(self, tmp_path):
        f = tmp_path / "My Resume 2026.pdf"
        f.write_bytes(b"content")
        inputs = iter([str(f), "n"])
        with patch("builtins.input", side_effect=inputs):
            result = self.menu._collect_attachments([])
        assert result[0]["name"] == "My Resume 2026.pdf"

    def test_quoted_path_stripped(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_bytes(b"hello")
        quoted = '"' + str(f) + '"'
        inputs = iter([quoted, "n"])
        with patch("builtins.input", side_effect=inputs):
            result = self.menu._collect_attachments([])
        assert len(result) == 1


class TestEditAttachmentsMenu:
    def setup_method(self):
        self.menu = _make_menu()

    def test_remove_attachment(self):
        attachments = [
            {"path": "/a.pdf", "name": "a.pdf", "size": 100},
            {"path": "/b.pdf", "name": "b.pdf", "size": 200},
        ]
        inputs = iter(["r", "2", "d"])
        with patch("builtins.input", side_effect=inputs):
            with patch("time.sleep"):
                self.menu._edit_attachments_menu(attachments)
        assert len(attachments) == 1
        assert attachments[0]["name"] == "a.pdf"

    def test_done_exits(self):
        inputs = iter(["d"])
        with patch("builtins.input", side_effect=inputs):
            self.menu._edit_attachments_menu([])

    def test_invalid_remove_index(self):
        attachments = [{"path": "/a.pdf", "name": "a.pdf", "size": 10}]
        inputs = iter(["r", "99", "d"])
        with patch("builtins.input", side_effect=inputs):
            with patch("time.sleep"):
                self.menu._edit_attachments_menu(attachments)
        assert len(attachments) == 1


class TestDoSend:
    def setup_method(self):
        self.menu = _make_menu()

    def test_exceeds_size_limit(self):
        big = [{"path": "/big.zip", "name": "big.zip", "size": 26 * 1024 * 1024}]
        with patch("builtins.print") as mock_print:
            with patch("time.sleep"):
                self.menu._do_send("a@b.com", "Subject", "", "", big, "body")
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        assert "maximum allowed message size" in printed

    def test_api_failure_shows_error(self):
        mock_svc = MagicMock()
        mock_svc.send_message.return_value = None
        with patch("gsuite_cli.services.gmail.GmailService", return_value=mock_svc):
            with patch("gsuite_cli.auth.oauth.OAuthManager"):
                with patch("builtins.print") as mock_print:
                    with patch("time.sleep"):
                        self.menu._do_send("a@b.com", "Subj", "", "", [], "body text")
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        assert "Failed to send" in printed

    def test_successful_send(self):
        mock_svc = MagicMock()
        mock_svc.send_message.return_value = "msg-123"
        with patch("gsuite_cli.services.gmail.GmailService", return_value=mock_svc):
            with patch("gsuite_cli.auth.oauth.OAuthManager"):
                with patch("builtins.print") as mock_print:
                    with patch("time.sleep"):
                        self.menu._do_send("a@b.com", "Subj", "", "", [], "Hello!")
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        assert "msg-123" in printed

    def test_exception_during_send(self):
        with patch("gsuite_cli.auth.oauth.OAuthManager", side_effect=Exception("auth fail")):
            with patch("builtins.print") as mock_print:
                with patch("time.sleep"):
                    self.menu._do_send("a@b.com", "Subj", "", "", [], "body")
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        assert "Error" in printed

    def test_send_passes_correct_args(self):
        mock_svc = MagicMock()
        mock_svc.send_message.return_value = "msg-999"
        with patch("gsuite_cli.services.gmail.GmailService", return_value=mock_svc):
            with patch("gsuite_cli.auth.oauth.OAuthManager"):
                attachments = [{"path": "/resume.pdf", "name": "resume.pdf", "size": 100}]
                with patch("builtins.print"):
                    with patch("time.sleep"):
                        self.menu._do_send("a@b.com", "Hi", "cc@b.com", "bcc@b.com", attachments, "body")
                mock_svc.send_message.assert_called_once_with(
                    to="a@b.com",
                    subject="Hi",
                    body="body",
                    cc="cc@b.com",
                    bcc="bcc@b.com",
                    attachments=["/resume.pdf"],
                )


class TestInteractiveComposeCancel:
    def setup_method(self):
        self.menu = _make_menu()

    def test_cancel_on_empty_to(self):
        with patch("builtins.input", return_value=""):
            with patch.object(self.menu, "clear_screen"):
                with patch.object(self.menu, "show_error") as mock_err:
                    self.menu._interactive_compose()
        mock_err.assert_called_once()

    def test_invalid_to_then_cancel(self):
        inputs = iter(["not-an-email", ""])
        with patch("builtins.input", side_effect=inputs):
            with patch.object(self.menu, "clear_screen"):
                with patch.object(self.menu, "show_error"):
                    self.menu._interactive_compose()


class TestCcBcc:
    def setup_method(self):
        self.menu = _make_menu()

    def test_multiple_cc_accepted(self):
        ok, bad = self.menu._validate_email_list("a@b.com, c@d.com, e@f.org")
        assert ok is True

    def test_multiple_bcc_accepted(self):
        ok, bad = self.menu._validate_email_list("bcc1@a.com, bcc2@b.com")
        assert ok is True

    def test_invalid_cc_rejected(self):
        ok, bad = self.menu._validate_email_list("good@email.com, bad-email")
        assert ok is False
        assert bad == "bad-email"


class TestLargeAttachmentSizeCheck:
    def setup_method(self):
        self.menu = _make_menu()

    def test_large_attachment_blocked(self):
        big = [{"path": "/huge.zip", "name": "huge.zip", "size": 30 * 1024 * 1024}]
        with patch("builtins.print") as p:
            with patch("time.sleep"):
                self.menu._do_send("a@b.com", "S", "", "", big, "body")
        out = " ".join(str(c) for c in p.call_args_list)
        assert "maximum allowed" in out

    def test_normal_attachment_not_blocked(self):
        normal = [{"path": "/small.pdf", "name": "small.pdf", "size": 100 * 1024}]
        mock_svc = MagicMock()
        mock_svc.send_message.return_value = "ok-id"
        with patch("gsuite_cli.services.gmail.GmailService", return_value=mock_svc):
            with patch("gsuite_cli.auth.oauth.OAuthManager"):
                with patch("builtins.print"):
                    with patch("time.sleep"):
                        self.menu._do_send("a@b.com", "S", "", "", normal, "body")
        mock_svc.send_message.assert_called_once()
