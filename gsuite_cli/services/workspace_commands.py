"""
Universal command dispatchers and helper getters for all Google Workspace APIs in Hermes CLI.
"""

from __future__ import annotations
import logging
from typing import Optional, Dict, Any, List

import click
from colorama import Fore, Style

from .drive import DriveService
from .tasks import TasksService
from .docs import DocsService
from .sheets import SheetsService
from .workspace_events import WorkspaceEventsService
from .apps_script import AppsScriptService
from .admin import AdminService
from .cloud_identity import CloudIdentityService
from .cloud_search import CloudSearchService
from .forms import FormsService
from .drive_activity import DriveActivityService
from .chat import ChatService
from ..utils.formatters import (
    format_output,
    print_error,
    print_info,
    print_success,
    print_header,
    print_key_value_pairs,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Service Getters (supporting mock injection via ctx.obj)
# ---------------------------------------------------------------------------

def get_drive_service(ctx: click.Context) -> DriveService:
    if ctx.obj and '_drive_svc' in ctx.obj:
        return ctx.obj['_drive_svc']
    return DriveService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))

def get_tasks_service(ctx: click.Context) -> TasksService:
    if ctx.obj and '_tasks_svc' in ctx.obj:
        return ctx.obj['_tasks_svc']
    return TasksService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))

def get_docs_service(ctx: click.Context) -> DocsService:
    if ctx.obj and '_docs_svc' in ctx.obj:
        return ctx.obj['_docs_svc']
    return DocsService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))

def get_sheets_service(ctx: click.Context) -> SheetsService:
    if ctx.obj and '_sheets_svc' in ctx.obj:
        return ctx.obj['_sheets_svc']
    return SheetsService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))

def get_events_service(ctx: click.Context) -> WorkspaceEventsService:
    if ctx.obj and '_events_svc' in ctx.obj:
        return ctx.obj['_events_svc']
    return WorkspaceEventsService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))

def get_apps_script_service(ctx: click.Context) -> AppsScriptService:
    if ctx.obj and '_script_svc' in ctx.obj:
        return ctx.obj['_script_svc']
    return AppsScriptService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))

def get_admin_service(ctx: click.Context) -> AdminService:
    if ctx.obj and '_admin_svc' in ctx.obj:
        return ctx.obj['_admin_svc']
    return AdminService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))

def get_cloud_identity_service(ctx: click.Context) -> CloudIdentityService:
    if ctx.obj and '_identity_svc' in ctx.obj:
        return ctx.obj['_identity_svc']
    return CloudIdentityService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))

def get_cloud_search_service(ctx: click.Context) -> CloudSearchService:
    if ctx.obj and '_cloud_search_svc' in ctx.obj:
        return ctx.obj['_cloud_search_svc']
    return CloudSearchService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))

def get_forms_service(ctx: click.Context) -> FormsService:
    if ctx.obj and '_forms_svc' in ctx.obj:
        return ctx.obj['_forms_svc']
    return FormsService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))

def get_drive_activity_service(ctx: click.Context) -> DriveActivityService:
    if ctx.obj and '_activity_svc' in ctx.obj:
        return ctx.obj['_activity_svc']
    return DriveActivityService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))

def get_chat_service(ctx: click.Context) -> ChatService:
    if ctx.obj and '_chat_svc' in ctx.obj:
        return ctx.obj['_chat_svc']
    return ChatService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))
