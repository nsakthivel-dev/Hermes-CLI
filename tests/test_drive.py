"""
Unit tests for Google Drive Service, Universal CLI commands, and aliases.
All tests mock Google Drive API client calls (no real credentials required).
"""

import os
import io
import pytest
from unittest.mock import MagicMock, patch, mock_open
from click.testing import CliRunner

from gsuite_cli.services.drive import DriveService
from gsuite_cli.cli import cli


@pytest.fixture
def mock_oauth_manager():
    manager = MagicMock()
    mock_service = MagicMock()
    manager.build_service.return_value = mock_service
    manager.get_auth_info.return_value = {
        'authenticated': True,
        'valid': True,
        'expired': False,
        'token_expiry': '2026-12-31T23:59:59Z',
    }
    return manager


@pytest.fixture
def drive_service(mock_oauth_manager):
    return DriveService(mock_oauth_manager)


# =============================================================================
# Service Layer Unit Tests
# =============================================================================

class TestDriveService:
    def test_test_connection_success(self, drive_service):
        drive_service.service.files().list.return_value.execute.return_value = {
            'files': [{'id': 'file-1', 'name': 'Doc 1'}]
        }
        res = drive_service.test_connection()
        assert res['status'] == 'success'
        assert res['files_count'] == 1

    def test_get_profile(self, drive_service):
        drive_service.service.about().get.return_value.execute.return_value = {
            'user': {'displayName': 'Dev User', 'emailAddress': 'dev@example.com'},
            'storageQuota': {'limit': '15000000000', 'usage': '5000000000'}
        }
        prof = drive_service.get_profile()
        assert prof['authenticated'] is True
        assert prof['email'] == 'dev@example.com'
        assert prof['user'] == 'Dev User'

    def test_list_files(self, drive_service):
        drive_service.service.files().list.return_value.execute.return_value = {
            'files': [{'id': 'f1', 'name': 'Project Plan.docx', 'mimeType': 'application/vnd.google-apps.document'}]
        }
        files = drive_service.list_files()
        assert len(files['files']) == 1
        assert files['files'][0]['id'] == 'f1'

    def test_list_folders(self, drive_service):
        drive_service.service.files().list.return_value.execute.return_value = {
            'files': [{'id': 'folder-1', 'name': 'Reports', 'mimeType': 'application/vnd.google-apps.folder'}]
        }
        folders = drive_service.list_folders()
        assert len(folders) == 1
        assert folders[0]['id'] == 'folder-1'

    def test_list_shared(self, drive_service):
        drive_service.service.files().list.return_value.execute.return_value = {
            'files': [{'id': 'shared-1', 'name': 'Team Sync'}]
        }
        shared = drive_service.list_shared()
        assert len(shared) == 1
        assert shared[0]['id'] == 'shared-1'

    def test_get_file(self, drive_service):
        drive_service.service.files().get.return_value.execute.return_value = {
            'id': 'f1',
            'name': 'Readme.md',
            'mimeType': 'text/plain'
        }
        file_obj = drive_service.get_file('f1')
        assert file_obj['id'] == 'f1'
        assert file_obj['name'] == 'Readme.md'

    def test_create_file(self, drive_service):
        drive_service.service.files().create.return_value.execute.return_value = {
            'id': 'new-file-id',
            'name': 'notes.txt'
        }
        created = drive_service.create_file('notes.txt', content='Hello World')
        assert created['id'] == 'new-file-id'

    def test_create_folder(self, drive_service):
        drive_service.service.files().create.return_value.execute.return_value = {
            'id': 'new-folder-id',
            'name': 'DocsFolder',
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = drive_service.create_folder('DocsFolder')
        assert folder['id'] == 'new-folder-id'

    @patch('os.path.exists', return_value=True)
    @patch('os.path.basename', return_value='upload.pdf')
    def test_upload_file(self, mock_basename, mock_exists, drive_service):
        with patch('gsuite_cli.services.drive.MediaFileUpload') as mock_media:
            drive_service.service.files().create.return_value.execute.return_value = {
                'id': 'uploaded-id',
                'name': 'upload.pdf'
            }
            res = drive_service.upload_file('dummy/upload.pdf')
            assert res['id'] == 'uploaded-id'

    def test_download_file(self, drive_service):
        drive_service.service.files().get_media.return_value = MagicMock()
        with patch('gsuite_cli.services.drive.MediaIoBaseDownload') as mock_downloader:
            mock_inst = MagicMock()
            mock_inst.next_chunk.return_value = (None, True)
            mock_downloader.return_value = mock_inst
            with patch('builtins.open', mock_open()):
                ok = drive_service.download_file('f1', 'dest.bin')
                assert ok is True

    def test_copy_file(self, drive_service):
        drive_service.service.files().copy.return_value.execute.return_value = {
            'id': 'copied-id',
            'name': 'Copy of doc'
        }
        copied = drive_service.copy_file('orig-id', new_name='Copy of doc')
        assert copied['id'] == 'copied-id'

    def test_move_file(self, drive_service):
        drive_service.service.files().get.return_value.execute.return_value = {
            'parents': ['old-parent']
        }
        drive_service.service.files().update.return_value.execute.return_value = {
            'id': 'moved-id',
            'parents': ['new-parent']
        }
        moved = drive_service.move_file('moved-id', 'new-parent')
        assert moved['id'] == 'moved-id'

    def test_rename_file(self, drive_service):
        drive_service.service.files().update.return_value.execute.return_value = {
            'id': 'renamed-id',
            'name': 'new_name.txt'
        }
        renamed = drive_service.rename_file('renamed-id', 'new_name.txt')
        assert renamed['name'] == 'new_name.txt'

    def test_trash_and_restore_file(self, drive_service):
        drive_service.service.files().update.return_value.execute.return_value = {
            'id': 'trashed-id',
            'trashed': True
        }
        trashed = drive_service.trash_file('trashed-id')
        assert trashed is True

        drive_service.service.files().update.return_value.execute.return_value = {
            'id': 'trashed-id',
            'trashed': False
        }
        restored = drive_service.restore_file('trashed-id')
        assert restored is True

    def test_delete_file(self, drive_service):
        drive_service.service.files().delete.return_value.execute.return_value = {}
        assert drive_service.delete_file('del-id') is True

    def test_permissions(self, drive_service):
        drive_service.service.permissions().list.return_value.execute.return_value = {
            'permissions': [{'id': 'perm-1', 'role': 'writer', 'type': 'user'}]
        }
        perms = drive_service.list_permissions('f1')
        assert len(perms) == 1
        assert perms[0]['id'] == 'perm-1'

        drive_service.service.permissions().create.return_value.execute.return_value = {
            'id': 'new-perm',
            'role': 'reader'
        }
        created = drive_service.add_permission('f1', role='reader', email='user@test.com')
        assert created['id'] == 'new-perm'

        drive_service.service.permissions().delete.return_value.execute.return_value = {}
        assert drive_service.remove_permission('f1', 'new-perm') is True

    def test_comments(self, drive_service):
        drive_service.service.comments().list.return_value.execute.return_value = {
            'comments': [{'id': 'comm-1', 'content': 'Looks good'}]
        }
        comments = drive_service.list_comments('f1')
        assert len(comments) == 1
        assert comments[0]['id'] == 'comm-1'

    def test_revisions(self, drive_service):
        drive_service.service.revisions().list.return_value.execute.return_value = {
            'revisions': [{'id': 'rev-1', 'modifiedTime': '2026-09-01T12:00:00Z'}]
        }
        revs = drive_service.list_revisions('f1')
        assert len(revs) == 1
        assert revs[0]['id'] == 'rev-1'

    def test_search_files(self, drive_service):
        drive_service.service.files().list.return_value.execute.return_value = {
            'files': [{'id': 'res-1', 'name': 'Search Result'}]
        }
        res = drive_service.search_files('quarterly')
        assert len(res) == 1
        assert res[0]['id'] == 'res-1'


# =============================================================================
# Universal Hermes CLI Commands Tests
# =============================================================================

class TestUniversalDriveCommands:
    @pytest.fixture
    def mock_drive_service(self):
        svc = MagicMock()
        svc.test_connection.return_value = {'status': 'success', 'message': 'Connected to Drive'}
        svc.get_profile.return_value = {'authenticated': True, 'email': 'dev@example.com', 'user_name': 'Dev User'}
        svc.list_files.return_value = {'files': [{'id': 'f1', 'name': 'Doc.txt', 'mimeType': 'text/plain', 'size': '1024', 'modifiedTime': '2026-09-01'}]}
        svc.get_file.return_value = {'id': 'f1', 'name': 'Doc.txt', 'mimeType': 'text/plain', 'size': '1024', 'modifiedTime': '2026-09-01', 'createdTime': '2026-08-01', 'trashed': False}
        svc.list_folders.return_value = {'files': [{'id': 'folder-1', 'name': 'Folder A', 'mimeType': 'application/vnd.google-apps.folder', 'modifiedTime': '2026-09-01'}]}
        svc.list_shared.return_value = {'files': [{'id': 'shared-1', 'name': 'Shared Doc', 'mimeType': 'text/plain', 'modifiedTime': '2026-09-01'}]}
        svc.create_file.return_value = {'id': 'new-f1', 'name': 'Created.txt'}
        svc.create_folder.return_value = {'id': 'new-fol1', 'name': 'New Folder'}
        svc.upload_file.return_value = {'id': 'up-1', 'name': 'test.pdf'}
        svc.download_file.return_value = True
        svc.rename_file.return_value = {'id': 'f1', 'name': 'Renamed.txt'}
        svc.move_file.return_value = {'id': 'f1', 'parents': ['folder-2']}
        svc.copy_file.return_value = {'id': 'copy-1', 'name': 'Copy of Doc'}
        svc.trash_file.return_value = {'id': 'f1', 'trashed': True}
        svc.restore_file.return_value = {'id': 'f1', 'trashed': False}
        svc.delete_file.return_value = True
        svc.list_permissions.return_value = [{'id': 'p1', 'role': 'writer', 'type': 'user', 'emailAddress': 'colleague@example.com'}]
        svc.add_permission.return_value = {'id': 'p2', 'role': 'reader'}
        svc.remove_permission.return_value = True
        svc.list_comments.return_value = [{'id': 'c1', 'author': {'displayName': 'Alice'}, 'content': 'Nice doc', 'createdTime': '2026-09-01'}]
        svc.list_revisions.return_value = [{'id': 'r1', 'modifiedTime': '2026-09-01', 'keepForever': False}]
        svc.search_files.return_value = {'files': [{'id': 'f1', 'name': 'Doc.txt', 'mimeType': 'text/plain', 'modifiedTime': '2026-09-01'}]}
        return svc

    def test_universal_list_drive(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['list', 'drive'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'Doc.txt' in res.output

    def test_universal_list_drive_single(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['list', 'drive', 'f1'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'Doc.txt' in res.output

    def test_universal_list_drive_files(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['list', 'drive-files'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'Doc.txt' in res.output

    def test_universal_list_drive_folders(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['list', 'drive-folders'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'Folder A' in res.output

    def test_universal_list_drive_shared(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['list', 'drive-shared'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'Shared Doc' in res.output

    def test_universal_create_drive_file(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['create', 'drive-file', '--title', 'Created.txt'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'File created' in res.output

    def test_universal_create_drive_folder(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['create', 'drive-folder', '--title', 'New Folder'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'Folder created' in res.output

    def test_universal_upload_drive(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['upload', 'drive', 'dummy/path/test.pdf'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'File uploaded' in res.output

    def test_universal_download_drive(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['download', 'drive', 'f1', '--dest', 'out.bin'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'downloaded successfully' in res.output

    def test_universal_rename_drive(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['rename', 'drive', 'f1', 'Renamed.txt'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'renamed to' in res.output

    def test_universal_move_drive(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['move', 'drive', 'f1', 'folder-2'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'moved to folder' in res.output

    def test_universal_copy_drive(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['copy', 'drive', 'f1', '--title', 'Copy of Doc'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'copied successfully' in res.output

    def test_universal_trash_drive(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['trash', 'drive', 'f1'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'moved to trash' in res.output

    def test_universal_restore_drive(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['restore', 'drive', 'f1'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'restored from trash' in res.output

    def test_universal_delete_drive(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['delete', 'drive', 'f1', '--yes'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'permanently deleted' in res.output

    def test_universal_list_permissions(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['list', 'drive-permissions', 'f1'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'writer' in res.output

    def test_universal_add_permission(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['add', 'drive-permission', 'f1', 'user@example.com', '--role', 'reader'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'Permission added' in res.output

    def test_universal_remove_permission(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['remove', 'drive-permission', 'f1', 'p1', '--yes'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'Permission p1 removed' in res.output

    def test_universal_list_comments(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['list', 'drive-comments', 'f1'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'Nice doc' in res.output

    def test_universal_list_revisions(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['list', 'drive-revisions', 'f1'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'r1' in res.output

    def test_universal_search_drive(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['search', 'drive', 'Doc'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'Doc.txt' in res.output

    def test_universal_status_drive(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['status', 'drive'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'Google Drive API v3 Status' in res.output

    def test_universal_profile_drive(self, mock_drive_service):
        runner = CliRunner()
        res = runner.invoke(cli, ['profile', 'drive'], obj={'_drive_svc': mock_drive_service})
        assert res.exit_code == 0
        assert 'Drive Profile & Quota' in res.output

    def test_universal_aliases_drive(self, mock_drive_service):
        runner = CliRunner()
        # ls alias
        res_ls = runner.invoke(cli, ['ls', 'drive'], obj={'_drive_svc': mock_drive_service})
        assert res_ls.exit_code == 0
        assert 'Doc.txt' in res_ls.output

        # get alias
        res_get = runner.invoke(cli, ['get', 'drive', 'f1'], obj={'_drive_svc': mock_drive_service})
        assert res_get.exit_code == 0
        assert 'Doc.txt' in res_get.output

        # cp alias
        res_cp = runner.invoke(cli, ['cp', 'drive', 'f1', '--title', 'Copy of Doc'], obj={'_drive_svc': mock_drive_service})
        assert res_cp.exit_code == 0

        # mv alias
        res_mv = runner.invoke(cli, ['mv', 'drive', 'f1', 'folder-2'], obj={'_drive_svc': mock_drive_service})
        assert res_mv.exit_code == 0

        # rm alias
        res_rm = runner.invoke(cli, ['rm', 'drive', 'f1', '--yes'], obj={'_drive_svc': mock_drive_service})
        assert res_rm.exit_code == 0
