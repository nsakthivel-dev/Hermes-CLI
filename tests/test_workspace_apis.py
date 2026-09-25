"""
Unit tests for Google Workspace APIs (Docs, Sheets, Events, Apps Script,
Admin SDK, Cloud Identity, Cloud Search, Forms, Drive Activity)
and their Universal CLI commands.
All tests mock Google API client calls (no real credentials needed).
"""

import pytest
from unittest.mock import MagicMock, patch
from click.testing import CliRunner

from gsuite_cli.services.docs import DocsService
from gsuite_cli.services.sheets import SheetsService
from gsuite_cli.services.workspace_events import WorkspaceEventsService
from gsuite_cli.services.apps_script import AppsScriptService
from gsuite_cli.services.admin import AdminService
from gsuite_cli.services.cloud_identity import CloudIdentityService
from gsuite_cli.services.cloud_search import CloudSearchService
from gsuite_cli.services.forms import FormsService
from gsuite_cli.services.drive_activity import DriveActivityService
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


# =============================================================================
# 1. Google Docs Extended Tests
# =============================================================================

class TestDocsExtended:
    def test_docs_test_connection(self, mock_oauth_manager):
        svc = DocsService(mock_oauth_manager)
        svc.drive_service.files().list.return_value.execute.return_value = {'files': [{'id': 'doc-1'}]}
        res = svc.test_connection()
        assert res['status'] == 'success'

    def test_docs_get_profile(self, mock_oauth_manager):
        svc = DocsService(mock_oauth_manager)
        svc.drive_service.about().get.return_value.execute.return_value = {
            'user': {'displayName': 'Alice Developer', 'emailAddress': 'alice@example.com'}
        }
        prof = svc.get_profile()
        assert prof['authenticated'] is True
        assert prof['email'] == 'alice@example.com'

    def test_docs_delete_document(self, mock_oauth_manager):
        svc = DocsService(mock_oauth_manager)
        svc.drive_service.files().delete.return_value.execute.return_value = {}
        assert svc.delete_document('doc-123') is True

    def test_universal_docs_commands(self):
        mock_svc = MagicMock()
        mock_svc.create_document.return_value = {'documentId': 'new-doc-id', 'title': 'Design Doc'}
        mock_svc.get_document.return_value = {'documentId': 'doc-1', 'title': 'Design Doc', 'body': {}}
        mock_svc.append_text.return_value = True
        mock_svc.insert_text.return_value = True
        mock_svc.delete_document.return_value = True
        mock_svc.test_connection.return_value = {'status': 'success', 'message': 'Connected to Docs'}
        mock_svc.get_profile.return_value = {'authenticated': True, 'email': 'dev@example.com'}

        runner = CliRunner()
        # create
        r_create = runner.invoke(cli, ['create', 'docs', '--title', 'Design Doc'], obj={'_docs_svc': mock_svc})
        assert r_create.exit_code == 0
        assert 'new-doc-id' in r_create.output

        # read
        r_read = runner.invoke(cli, ['read', 'docs', 'doc-1'], obj={'_docs_svc': mock_svc})
        assert r_read.exit_code == 0

        # append
        r_app = runner.invoke(cli, ['append', 'docs', 'doc-1', '--text', 'Footer text'], obj={'_docs_svc': mock_svc})
        assert r_app.exit_code == 0
        assert 'Text appended' in r_app.output

        # insert
        r_ins = runner.invoke(cli, ['insert', 'docs', 'doc-1', '--text', 'Header text', '--index', '1'], obj={'_docs_svc': mock_svc})
        assert r_ins.exit_code == 0
        assert 'Text inserted' in r_ins.output

        # status
        r_stat = runner.invoke(cli, ['status', 'docs'], obj={'_docs_svc': mock_svc})
        assert r_stat.exit_code == 0
        assert 'Google Docs API v1 Status' in r_stat.output

        # profile
        r_prof = runner.invoke(cli, ['profile', 'docs'], obj={'_docs_svc': mock_svc})
        assert r_prof.exit_code == 0
        assert 'Docs Profile' in r_prof.output


# =============================================================================
# 2. Google Sheets Extended Tests
# =============================================================================

class TestSheetsExtended:
    def test_sheets_test_connection(self, mock_oauth_manager):
        svc = SheetsService(mock_oauth_manager)
        svc.drive_service.files().list.return_value.execute.return_value = {'files': [{'id': 'sheet-1'}]}
        res = svc.test_connection()
        assert res['status'] == 'success'

    def test_sheets_get_profile(self, mock_oauth_manager):
        svc = SheetsService(mock_oauth_manager)
        svc.drive_service.about().get.return_value.execute.return_value = {
            'user': {'displayName': 'Bob Analyst', 'emailAddress': 'bob@example.com'}
        }
        prof = svc.get_profile()
        assert prof['authenticated'] is True
        assert prof['email'] == 'bob@example.com'

    def test_sheets_delete_spreadsheet(self, mock_oauth_manager):
        svc = SheetsService(mock_oauth_manager)
        svc.drive_service.files().delete.return_value.execute.return_value = {}
        assert svc.delete_spreadsheet('sheet-123') is True

    def test_sheet_tabs_management(self, mock_oauth_manager):
        svc = SheetsService(mock_oauth_manager)
        svc.sheets_service.spreadsheets().get.return_value.execute.return_value = {
            'sheets': [{'properties': {'sheetId': 0, 'title': 'Sheet1', 'index': 0}}]
        }
        tabs = svc.list_sheet_tabs('sheet-123')
        assert len(tabs) == 1
        assert tabs[0]['title'] == 'Sheet1'

        svc.sheets_service.spreadsheets().batchUpdate.return_value.execute.return_value = {}
        assert svc.delete_sheet_tab('sheet-123', 0) is True
        assert svc.rename_sheet_tab('sheet-123', 0, 'Summary') is True

    def test_universal_sheets_commands(self):
        mock_svc = MagicMock()
        mock_svc.create_spreadsheet.return_value = {'spreadsheetId': 'new-sheet-id', 'spreadsheetUrl': 'https://sheets.google.com/123'}
        mock_svc.read_range.return_value = [['Name', 'Score'], ['Alice', '100']]
        mock_svc.write_range.return_value = True
        mock_svc.append_row.return_value = True
        mock_svc.clear_range.return_value = True
        mock_svc.list_sheet_tabs.return_value = [{'tab_id': 0, 'title': 'Q1', 'index': 0}]
        mock_svc.add_sheet_tab.return_value = {'properties': {'sheetId': 1, 'title': 'Q2'}}
        mock_svc.delete_sheet_tab.return_value = True
        mock_svc.rename_sheet_tab.return_value = True
        mock_svc.delete_spreadsheet.return_value = True
        mock_svc.test_connection.return_value = {'status': 'success', 'message': 'Connected to Sheets'}
        mock_svc.get_profile.return_value = {'authenticated': True, 'email': 'dev@example.com'}

        runner = CliRunner()
        # create
        r_create = runner.invoke(cli, ['create', 'sheets', '--title', 'Budget 2026'], obj={'_sheets_svc': mock_svc})
        assert r_create.exit_code == 0
        assert 'new-sheet-id' in r_create.output

        # read
        r_read = runner.invoke(cli, ['read', 'sheets', 'sheet-1', 'A1:B2'], obj={'_sheets_svc': mock_svc})
        assert r_read.exit_code == 0
        assert 'Alice' in r_read.output

        # write
        r_write = runner.invoke(cli, ['write', 'sheets', 'sheet-1', 'A1:B1', '--values', 'Col1,Col2'], obj={'_sheets_svc': mock_svc})
        assert r_write.exit_code == 0
        assert 'Range updated successfully' in r_write.output

        # append
        r_app = runner.invoke(cli, ['append', 'sheets', 'sheet-1', 'A:B', '--values', 'Val1,Val2'], obj={'_sheets_svc': mock_svc})
        assert r_app.exit_code == 0
        assert 'Row appended' in r_app.output

        # clear
        r_clear = runner.invoke(cli, ['clear', 'sheets', 'sheet-1', 'A1:B10'], obj={'_sheets_svc': mock_svc})
        assert r_clear.exit_code == 0
        assert 'cleared' in r_clear.output

        # list sheet-tabs
        r_tabs = runner.invoke(cli, ['list', 'sheet-tabs', 'sheet-1'], obj={'_sheets_svc': mock_svc})
        assert r_tabs.exit_code == 0
        assert 'Q1' in r_tabs.output

        # create sheet-tab
        r_newtab = runner.invoke(cli, ['create', 'sheet-tab', 'sheet-1', '--title', 'Q2'], obj={'_sheets_svc': mock_svc})
        assert r_newtab.exit_code == 0
        assert 'Tab created' in r_newtab.output

        # delete sheet-tab
        r_deltab = runner.invoke(cli, ['delete', 'sheet-tab', 'sheet-1', '1', '--yes'], obj={'_sheets_svc': mock_svc})
        assert r_deltab.exit_code == 0
        assert 'deleted' in r_deltab.output

        # rename sheet-tab
        r_rentab = runner.invoke(cli, ['rename', 'sheet-tab', 'sheet-1', '0', 'NewQ1'], obj={'_sheets_svc': mock_svc})
        assert r_rentab.exit_code == 0
        assert 'renamed to NewQ1' in r_rentab.output

        # status
        r_stat = runner.invoke(cli, ['status', 'sheets'], obj={'_sheets_svc': mock_svc})
        assert r_stat.exit_code == 0
        assert 'Google Sheets API v4 Status' in r_stat.output

        # profile
        r_prof = runner.invoke(cli, ['profile', 'sheets'], obj={'_sheets_svc': mock_svc})
        assert r_prof.exit_code == 0
        assert 'Sheets Profile' in r_prof.output


# =============================================================================
# 3. Google Workspace Events API Tests
# =============================================================================

class TestWorkspaceEvents:
    def test_events_service(self, mock_oauth_manager):
        svc = WorkspaceEventsService(mock_oauth_manager)
        svc.service.subscriptions().list.return_value.execute.return_value = {
            'subscriptions': [{'name': 'subscriptions/sub-1', 'targetResource': '//chat.googleapis.com/spaces/AAA', 'state': 'ACTIVE'}]
        }
        res = svc.test_connection()
        assert res['status'] == 'success'

        subs = svc.list_subscriptions()
        assert len(subs['subscriptions']) == 1

        svc.service.subscriptions().get.return_value.execute.return_value = {
            'name': 'subscriptions/sub-1', 'state': 'ACTIVE'
        }
        sub = svc.get_subscription('subscriptions/sub-1')
        assert sub['name'] == 'subscriptions/sub-1'

        svc.service.subscriptions().create.return_value.execute.return_value = {
            'name': 'subscriptions/sub-2'
        }
        created = svc.create_subscription('//chat.googleapis.com/spaces/BBB', ['google.workspace.chat.message.v1.created'], 'projects/p/topics/t')
        assert created['name'] == 'subscriptions/sub-2'

        svc.service.subscriptions().delete.return_value.execute.return_value = {}
        assert svc.delete_subscription('subscriptions/sub-2') is True

    def test_universal_events_commands(self):
        mock_svc = MagicMock()
        mock_svc.list_subscriptions.return_value = {
            'subscriptions': [{'name': 'subscriptions/sub-1', 'targetResource': '//chat.googleapis.com/spaces/AAA', 'state': 'ACTIVE'}]
        }
        mock_svc.get_subscription.return_value = {'name': 'subscriptions/sub-1', 'state': 'ACTIVE'}
        mock_svc.create_subscription.return_value = {'name': 'subscriptions/new-sub'}
        mock_svc.delete_subscription.return_value = True
        mock_svc.test_connection.return_value = {'status': 'success', 'message': 'Connected to Events API'}

        runner = CliRunner()
        # list
        r_list = runner.invoke(cli, ['list', 'events'], obj={'_events_svc': mock_svc})
        assert r_list.exit_code == 0
        assert 'subscriptions/sub-1' in r_list.output

        # create
        r_create = runner.invoke(cli, ['create', 'event-subscription', '--target', '//chat.googleapis.com/spaces/AAA', '--topic', 'projects/p/topics/t'], obj={'_events_svc': mock_svc})
        assert r_create.exit_code == 0
        assert 'subscriptions/new-sub' in r_create.output

        # delete
        r_del = runner.invoke(cli, ['delete', 'event-subscription', 'subscriptions/new-sub', '--yes'], obj={'_events_svc': mock_svc})
        assert r_del.exit_code == 0
        assert 'deleted' in r_del.output

        # status
        r_stat = runner.invoke(cli, ['status', 'events'], obj={'_events_svc': mock_svc})
        assert r_stat.exit_code == 0
        assert 'Workspace Events' in r_stat.output


# =============================================================================
# 4. Google Apps Script API Tests
# =============================================================================

class TestAppsScript:
    def test_apps_script_service(self, mock_oauth_manager):
        svc = AppsScriptService(mock_oauth_manager)
        svc.drive_service.files().list.return_value.execute.return_value = {
            'files': [{'id': 'script-1', 'name': 'Automation'}]
        }
        assert svc.test_connection()['status'] == 'success'

        svc.service.projects().create.return_value.execute.return_value = {
            'scriptId': 'new-script-id', 'title': 'Nightly Script'
        }
        p = svc.create_project('Nightly Script')
        assert p['scriptId'] == 'new-script-id'

        svc.service.scripts().run.return_value.execute.return_value = {
            'done': True, 'response': {'result': 'Sync complete'}
        }
        run_res = svc.run_script('script-1', 'syncData')
        assert run_res['status'] == 'success'

        svc.service.projects().versions().list.return_value.execute.return_value = {
            'versions': [{'versionNumber': 1, 'description': 'Initial'}]
        }
        assert len(svc.list_versions('script-1')['versions']) == 1

        svc.service.projects().deployments().list.return_value.execute.return_value = {
            'deployments': [{'deploymentId': 'dep-1'}]
        }
        assert len(svc.list_deployments('script-1')['deployments']) == 1

    def test_universal_apps_script_commands(self):
        mock_svc = MagicMock()
        mock_svc.list_projects.return_value = [{'id': 's1', 'name': 'BuildBot', 'modifiedTime': '2026-09-01'}]
        mock_svc.create_project.return_value = {'scriptId': 'new-s1', 'title': 'BuildBot'}
        mock_svc.run_script.return_value = {'status': 'success', 'result': 'Done'}
        mock_svc.list_versions.return_value = {'versions': [{'versionNumber': 1, 'description': 'v1', 'createTime': '2026-09-01'}]}
        mock_svc.create_version.return_value = {'versionNumber': 2, 'description': 'v2'}
        mock_svc.list_deployments.return_value = {'deployments': [{'deploymentId': 'dep-1', 'deploymentConfig': {'description': 'Prod', 'versionNumber': 1}}]}
        mock_svc.create_deployment.return_value = {'deploymentId': 'dep-2'}
        mock_svc.delete_deployment.return_value = True
        mock_svc.test_connection.return_value = {'status': 'success', 'message': 'Connected to Apps Script'}

        runner = CliRunner()
        # list scripts
        r_list = runner.invoke(cli, ['list', 'scripts'], obj={'_script_svc': mock_svc})
        assert r_list.exit_code == 0
        assert 'BuildBot' in r_list.output

        # create script
        r_create = runner.invoke(cli, ['create', 'script', '--title', 'BuildBot'], obj={'_script_svc': mock_svc})
        assert r_create.exit_code == 0
        assert 'new-s1' in r_create.output

        # run script
        r_run = runner.invoke(cli, ['run', 'script', 's1', '--function', 'main'], obj={'_script_svc': mock_svc})
        assert r_run.exit_code == 0
        assert 'Done' in r_run.output

        # status
        r_stat = runner.invoke(cli, ['status', 'apps-script'], obj={'_script_svc': mock_svc})
        assert r_stat.exit_code == 0
        assert 'Apps Script' in r_stat.output


# =============================================================================
# 5. Google Admin SDK API Tests
# =============================================================================

class TestAdminSDK:
    def test_admin_service(self, mock_oauth_manager):
        svc = AdminService(mock_oauth_manager)
        svc.service.users().list.return_value.execute.return_value = {
            'users': [{'primaryEmail': 'admin@example.com', 'name': {'fullName': 'Admin User'}, 'suspended': False}]
        }
        assert svc.test_connection()['status'] == 'success'
        assert len(svc.list_users()['users']) == 1

        svc.service.users().update.return_value.execute.return_value = {'suspended': True}
        assert svc.suspend_user('admin@example.com') is True
        svc.service.users().update.return_value.execute.return_value = {'suspended': False}
        assert svc.unsuspend_user('admin@example.com') is True

        svc.service.groups().list.return_value.execute.return_value = {
            'groups': [{'email': 'devs@example.com', 'name': 'Developers'}]
        }
        assert len(svc.list_groups()['groups']) == 1

        svc.service.members().insert.return_value.execute.return_value = {'email': 'newdev@example.com'}
        assert svc.add_group_member('devs@example.com', 'newdev@example.com') is not None

        svc.service.members().delete.return_value.execute.return_value = {}
        assert svc.remove_group_member('devs@example.com', 'newdev@example.com') is True

    def test_universal_admin_commands(self):
        mock_svc = MagicMock()
        mock_svc.list_users.return_value = {'users': [{'primaryEmail': 'u1@example.com', 'name': {'fullName': 'User 1'}, 'suspended': False}]}
        mock_svc.create_user.return_value = {'primaryEmail': 'u2@example.com'}
        mock_svc.suspend_user.return_value = True
        mock_svc.unsuspend_user.return_value = True
        mock_svc.list_groups.return_value = {'groups': [{'email': 'g1@example.com', 'name': 'Group 1', 'directMembersCount': '5'}]}
        mock_svc.add_group_member.return_value = {'email': 'new@example.com'}
        mock_svc.remove_group_member.return_value = True
        mock_svc.list_devices.return_value = {'devices': []}
        mock_svc.list_domains.return_value = {'domains': []}
        mock_svc.test_connection.return_value = {'status': 'success', 'message': 'Connected to Admin SDK'}

        runner = CliRunner()
        # list admin-users
        r_users = runner.invoke(cli, ['list', 'admin-users'], obj={'_admin_svc': mock_svc})
        assert r_users.exit_code == 0
        assert 'u1@example.com' in r_users.output

        # suspend admin-user
        r_susp = runner.invoke(cli, ['suspend', 'admin-user', 'u1@example.com'], obj={'_admin_svc': mock_svc})
        assert r_susp.exit_code == 0
        assert 'suspended' in r_susp.output

        # unsuspend admin-user
        r_unsusp = runner.invoke(cli, ['unsuspend', 'admin-user', 'u1@example.com'], obj={'_admin_svc': mock_svc})
        assert r_unsusp.exit_code == 0
        assert 'unsuspended' in r_unsusp.output

        # list admin-groups
        r_groups = runner.invoke(cli, ['list', 'admin-groups'], obj={'_admin_svc': mock_svc})
        assert r_groups.exit_code == 0
        assert 'g1@example.com' in r_groups.output

        # add admin-group-member
        r_addm = runner.invoke(cli, ['add', 'admin-group-member', 'g1@example.com', 'new@example.com'], obj={'_admin_svc': mock_svc})
        assert r_addm.exit_code == 0
        assert 'added to group' in r_addm.output

        # remove admin-group-member
        r_remm = runner.invoke(cli, ['remove', 'admin-group-member', 'g1@example.com', 'new@example.com', '--yes'], obj={'_admin_svc': mock_svc})
        assert r_remm.exit_code == 0
        assert 'removed from group' in r_remm.output

        # status
        r_stat = runner.invoke(cli, ['status', 'admin'], obj={'_admin_svc': mock_svc})
        assert r_stat.exit_code == 0
        assert 'Admin SDK' in r_stat.output


# =============================================================================
# 6. Google Cloud Identity API Tests
# =============================================================================

class TestCloudIdentity:
    def test_cloud_identity_service(self, mock_oauth_manager):
        svc = CloudIdentityService(mock_oauth_manager)
        svc.service.groups().search.return_value.execute.return_value = {
            'groups': [{'name': 'groups/123', 'displayName': 'Security Team', 'description': 'SecOps'}]
        }
        assert svc.test_connection()['status'] == 'success'
        assert len(svc.search_groups('sec')['groups']) == 1

        svc.service.groups().create.return_value.execute.return_value = {
            'response': {'name': 'groups/new-sec'}
        }
        created = svc.create_group('SecOps', 'secops@example.com')
        assert created['response']['name'] == 'groups/new-sec'

        svc.service.groups().delete.return_value.execute.return_value = {}
        assert svc.delete_group('groups/new-sec') is True

        svc.service.groups().memberships().list.return_value.execute.return_value = {
            'memberships': [{'name': 'memberships/m1'}]
        }
        assert len(svc.list_members('groups/123')['memberships']) == 1

    def test_universal_cloud_identity_commands(self):
        mock_svc = MagicMock()
        mock_svc.list_groups.return_value = {'groups': [{'name': 'groups/g1', 'displayName': 'Core Team', 'description': 'Core dev'}]}
        mock_svc.search_groups.return_value = {'groups': [{'name': 'groups/g1', 'displayName': 'Core Team', 'description': 'Core dev'}]}
        mock_svc.create_group.return_value = {'response': {'name': 'groups/new-g1'}}
        mock_svc.list_members.return_value = {'memberships': [{'name': 'memberships/m1'}]}
        mock_svc.add_member.return_value = {'name': 'memberships/m2'}
        mock_svc.remove_member.return_value = True
        mock_svc.list_devices.return_value = {'devices': []}
        mock_svc.test_connection.return_value = {'status': 'success', 'message': 'Connected to Cloud Identity'}

        runner = CliRunner()
        # list identity-groups
        r_list = runner.invoke(cli, ['list', 'identity-groups'], obj={'_identity_svc': mock_svc})
        assert r_list.exit_code == 0
        assert 'Core Team' in r_list.output

        # search identity-groups
        r_search = runner.invoke(cli, ['search', 'identity-groups', 'Core'], obj={'_identity_svc': mock_svc})
        assert r_search.exit_code == 0
        assert 'Core Team' in r_search.output

        # create identity-group
        r_create = runner.invoke(cli, ['create', 'identity-group', '--title', 'Core Team', '--email', 'core@example.com'], obj={'_identity_svc': mock_svc})
        assert r_create.exit_code == 0
        assert 'Identity group created' in r_create.output

        # add identity-member
        r_add = runner.invoke(cli, ['add', 'identity-member', 'groups/g1', 'dev@example.com'], obj={'_identity_svc': mock_svc})
        assert r_add.exit_code == 0
        assert 'added to identity group' in r_add.output

        # remove identity-member
        r_rem = runner.invoke(cli, ['remove', 'identity-member', 'groups/g1', 'memberships/m1', '--yes'], obj={'_identity_svc': mock_svc})
        assert r_rem.exit_code == 0
        assert 'removed' in r_rem.output

        # status
        r_stat = runner.invoke(cli, ['status', 'identity'], obj={'_identity_svc': mock_svc})
        assert r_stat.exit_code == 0
        assert 'Cloud Identity' in r_stat.output


# =============================================================================
# 7. Google Cloud Search API Tests
# =============================================================================

class TestCloudSearch:
    def test_cloud_search_service(self, mock_oauth_manager):
        svc = CloudSearchService(mock_oauth_manager)
        svc.service.query().search.return_value.execute.return_value = {
            'results': [{'title': 'Project Architecture Doc', 'url': 'https://drive.google.com/doc/arch'}]
        }
        assert svc.test_connection()['status'] == 'success'
        res = svc.search('architecture')
        assert len(res['results']) == 1
        assert 'Architecture' in res['results'][0]['title']

    def test_universal_cloud_search_commands(self):
        mock_svc = MagicMock()
        mock_svc.search.return_value = {'results': [{'title': 'Sprint Review Meeting Notes', 'url': 'https://meet.google.com'}]}
        mock_svc.test_connection.return_value = {'status': 'success', 'message': 'Connected to Cloud Search'}

        runner = CliRunner()
        # search cloud-search
        r_search = runner.invoke(cli, ['search', 'cloud-search', 'meeting notes'], obj={'_cloud_search_svc': mock_svc})
        assert r_search.exit_code == 0
        assert 'Meeting Notes' in r_search.output

        # list cloud-search
        r_list = runner.invoke(cli, ['list', 'cloud-search'], obj={'_cloud_search_svc': mock_svc})
        assert r_list.exit_code == 0
        assert 'Meeting Notes' in r_list.output

        # status
        r_stat = runner.invoke(cli, ['status', 'cloud-search'], obj={'_cloud_search_svc': mock_svc})
        assert r_stat.exit_code == 0
        assert 'Cloud Search' in r_stat.output


# =============================================================================
# 8. Google Forms Extended Tests
# =============================================================================

class TestFormsExtended:
    def test_forms_service_extended(self, mock_oauth_manager):
        svc = FormsService(mock_oauth_manager)
        svc.service.forms().get.return_value.execute.return_value = {
            'formId': 'form-123',
            'info': {'title': 'Customer Feedback'},
            'items': [{'itemId': 'i1', 'title': 'How was service?', 'questionItem': {}}]
        }
        assert svc.test_connection()['status'] == 'success'
        f = svc.get_form('form-123')
        assert f['formId'] == 'form-123'

        items = svc.list_form_items('form-123')
        assert len(items) == 1
        assert items[0]['title'] == 'How was service?'

        svc.service.forms().batchUpdate.return_value.execute.return_value = {'replies': [{}]}
        assert svc.add_form_item('form-123', 'Any other comments?') is not None
        assert svc.delete_form_item('form-123', 'i1') is True

    def test_universal_forms_commands(self):
        mock_svc = MagicMock()
        mock_svc.create_form.return_value = {'formId': 'new-f1', 'info': {'title': 'Survey'}}
        mock_svc.list_form_items.return_value = [{'itemId': 'i1', 'title': 'Rate us', 'questionItem': {}}]
        mock_svc.add_form_item.return_value = {'replies': [{}]}
        mock_svc.delete_form_item.return_value = True
        mock_svc.test_connection.return_value = {'status': 'success', 'message': 'Connected to Forms'}
        mock_svc.get_profile.return_value = {'service': 'Google Forms API v1'}

        runner = CliRunner()
        # create forms
        r_create = runner.invoke(cli, ['create', 'forms', '--title', 'Survey'], obj={'_forms_svc': mock_svc})
        assert r_create.exit_code == 0
        assert 'Form created' in r_create.output

        # list form-items
        r_items = runner.invoke(cli, ['list', 'form-items', 'new-f1'], obj={'_forms_svc': mock_svc})
        assert r_items.exit_code == 0
        assert 'Rate us' in r_items.output

        # add form-item
        r_add = runner.invoke(cli, ['add', 'form-item', 'new-f1', 'Feedback text'], obj={'_forms_svc': mock_svc})
        assert r_add.exit_code == 0
        assert 'Form item added' in r_add.output

        # delete form-item
        r_del = runner.invoke(cli, ['delete', 'form-item', 'new-f1', 'i1', '--yes'], obj={'_forms_svc': mock_svc})
        assert r_del.exit_code == 0
        assert 'deleted' in r_del.output

        # status
        r_stat = runner.invoke(cli, ['status', 'forms'], obj={'_forms_svc': mock_svc})
        assert r_stat.exit_code == 0
        assert 'Google Forms' in r_stat.output

        # profile
        r_prof = runner.invoke(cli, ['profile', 'forms'], obj={'_forms_svc': mock_svc})
        assert r_prof.exit_code == 0
        assert 'Forms Profile' in r_prof.output


# =============================================================================
# 9. Google Drive Activity API Tests
# =============================================================================

class TestDriveActivity:
    def test_drive_activity_service(self, mock_oauth_manager):
        svc = DriveActivityService(mock_oauth_manager)
        svc.service.activity().query.return_value.execute.return_value = {
            'activities': [
                {
                    'primaryActionDetail': {'edit': {}},
                    'actors': [{'user': {'knownUser': {'personName': 'people/123'}}}],
                    'timestamp': '2026-09-01T12:00:00Z',
                    'targets': [{'driveItem': {'name': 'items/file-123', 'title': 'Design Doc'}}]
                }
            ]
        }
        assert svc.test_connection()['status'] == 'success'
        res = svc.query_activity()
        assert len(res['activities']) == 1

    def test_universal_drive_activity_commands(self):
        mock_svc = MagicMock()
        mock_svc.query_activity.return_value = {
            'activities': [{'action': 'edit', 'time': '2026-09-01T12:00:00Z', 'title': 'Design Doc'}]
        }
        mock_svc.test_connection.return_value = {'status': 'success', 'message': 'Connected to Drive Activity'}

        runner = CliRunner()
        # list drive-activity
        r_list = runner.invoke(cli, ['list', 'drive-activity'], obj={'_activity_svc': mock_svc})
        assert r_list.exit_code == 0
        assert 'Design Doc' in r_list.output

        # search drive-activity
        r_search = runner.invoke(cli, ['search', 'drive-activity', 'Design'], obj={'_activity_svc': mock_svc})
        assert r_search.exit_code == 0
        assert 'Design Doc' in r_search.output

        # activity drive <ID>
        r_act = runner.invoke(cli, ['activity', 'drive', 'file-123'], obj={'_activity_svc': mock_svc})
        assert r_act.exit_code == 0
        assert 'Design Doc' in r_act.output

        # status drive-activity
        r_stat = runner.invoke(cli, ['status', 'drive-activity'], obj={'_activity_svc': mock_svc})
        assert r_stat.exit_code == 0
        assert 'Drive Activity' in r_stat.output
