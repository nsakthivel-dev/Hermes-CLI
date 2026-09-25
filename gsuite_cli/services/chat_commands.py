"""
Google Chat Click command group and universal handlers for Hermes CLI.
"""

from __future__ import annotations

import logging
from typing import Optional

import click
from colorama import Fore, Style

from .chat import ChatService
from ..utils.formatters import (
    format_output,
    print_error,
    print_info,
    print_success,
    print_header,
    print_section,
    print_key_value_pairs,
)

logger = logging.getLogger(__name__)


def _svc(ctx: click.Context) -> ChatService:
    """Build or retrieve a ChatService from the Click context."""
    if ctx.obj and '_chat_svc' in ctx.obj:
        return ctx.obj['_chat_svc']
    return ChatService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))


# ---------------------------------------------------------------------------
# Dedicated `chat` Command Group
# ---------------------------------------------------------------------------

@click.group('chat')
def chat_group():
    """Google Chat commands"""
    pass


@chat_group.command('spaces')
@click.argument('space_id', required=False)
@click.option('--page-size', default=20, type=int, help='Maximum spaces to return')
@click.option('--format', 'output_format', type=click.Choice(['table', 'json']), default='table')
@click.pass_context
def chat_spaces(ctx: click.Context, space_id: Optional[str], page_size: int, output_format: str):
    """List joined chat spaces or inspect a single space"""
    service = _svc(ctx)
    if space_id:
        from .resource_resolver import GlobalResourceResolver, ResourceResolutionError
        all_spaces = service.list_spaces(page_size=100).get('spaces', [])
        # Try resolver (number/name/alias), then fall back to direct ID lookup
        actual_id = space_id
        try:
            resolved = GlobalResourceResolver.resolve(
                space_id, all_spaces,
                resource_type='chat_space', title_key='displayName', id_key='name'
            )
            actual_id = resolved.get('name', space_id) if resolved else space_id
        except ResourceResolutionError:
            # Not found by resolver — try direct ID as-is or prefixed with 'spaces/'
            actual_id = space_id if space_id.startswith('spaces/') else f'spaces/{space_id}'
        space = service.get_space(actual_id)
        if not space:
            return
        if output_format == 'json':
            print(format_output(space, 'json'))
        else:
            print_header("💬 Chat Space Details")
            print_key_value_pairs({
                'Name': space.get('name', ''),
                'Display Name': space.get('displayName', 'Untitled Space'),
                'Type': space.get('spaceType', space.get('type', '')),
                'Description': space.get('spaceDetails', {}).get('description', 'N/A'),
            })
    else:
        res = service.list_spaces(page_size=page_size)
        spaces = res.get('spaces', [])
        if not spaces:
            print_info("No chat spaces found.")
            return
        if output_format == 'json':
            print(format_output(spaces, 'json'))
        else:
            headers = ['Space Name', 'Display Name', 'Type']
            rows = [
                {
                    'Space Name': s.get('name', ''),
                    'Display Name': s.get('displayName', 'Direct/Group'),
                    'Type': s.get('spaceType', s.get('type', ''))
                }
                for s in spaces
            ]
            print(format_output(rows, 'table', headers=headers))


@chat_group.command('info')
@click.argument('reference', required=False)
@click.pass_context
def chat_info(ctx: click.Context, reference: Optional[str]):
    """View details of a chat space (supports human reference or interactive)"""
    if not reference:
        from ..ui.human_flows import run_chat_spaces_flow
        service = _svc(ctx)
        run_chat_spaces_flow(service)
        return
    service = _svc(ctx)
    spaces = service.list_spaces(page_size=100).get('spaces', [])
    from .resource_resolver import GlobalResourceResolver, ResourceResolutionError
    try:
        resolved = GlobalResourceResolver.resolve(
            reference, spaces,
            resource_type='chat_space', title_key='displayName', id_key='name'
        )
    except ResourceResolutionError:
        print_error(f"Chat space not found for reference: {reference}")
        return
    print_header("\U0001f4ac Chat Space Details")
    print_key_value_pairs({
        'Name': resolved.get('name', ''),
        'Display Name': resolved.get('displayName', 'Untitled Space'),
        'Type': resolved.get('spaceType', resolved.get('type', '')),
        'Description': resolved.get('spaceDetails', {}).get('description', 'N/A'),
    })



@chat_group.command('alias')
@click.argument('reference')
@click.argument('alias_name')
@click.pass_context
def chat_alias(ctx: click.Context, reference: str, alias_name: str):
    """Set a friendly alias for a chat space"""
    service = _svc(ctx)
    spaces = service.list_spaces(page_size=100).get('spaces', [])
    from .resource_resolver import GlobalResourceResolver, ResourceResolutionError
    try:
        resolved = GlobalResourceResolver.resolve(
            reference, spaces,
            resource_type='chat_space', title_key='displayName', id_key='name'
        )
    except ResourceResolutionError:
        print_error(f"Chat space '{reference}' not found.")
        return
    target_id = resolved.get('name', '')
    GlobalResourceResolver.set_alias('chat_space', alias_name, target_id)
    print_success(f"Alias '{alias_name}' created for space '{resolved.get('displayName', target_id)}'")


@chat_group.command('messages')
@click.argument('space_id')
@click.option('--page-size', default=25, type=int, help='Maximum messages to return')
@click.option('--format', 'output_format', type=click.Choice(['table', 'json']), default='table')
@click.pass_context
def chat_messages(ctx: click.Context, space_id: str, page_size: int, output_format: str):
    """List recent messages in a space"""
    service = _svc(ctx)
    res = service.list_messages(space_id, page_size=page_size)
    msgs = res.get('messages', [])
    if not msgs:
        print_info(f"No messages found in space {space_id}.")
        return
    if output_format == 'json':
        print(format_output(msgs, 'json'))
    else:
        headers = ['Message ID', 'Sender', 'Text', 'Created At']
        rows = [
            {
                'Message ID': m.get('name', '').split('/')[-1],
                'Sender': m.get('sender', {}).get('displayName', 'Unknown'),
                'Text': m.get('text', '')[:60],
                'Created At': m.get('createTime', '')[:19]
            }
            for m in msgs
        ]
        print(format_output(rows, 'table', headers=headers))


@chat_group.command('send')
@click.argument('space_id')
@click.option('--message', '-m', help='Message content to send')
@click.option('--thread-key', help='Optional thread key to associate message')
@click.pass_context
def chat_send(ctx: click.Context, space_id: str, message: Optional[str], thread_key: Optional[str]):
    """Send a message to a chat space (supports interactive input)"""
    if not message:
        message = click.prompt("Message")
    if not message.strip():
        print_error("Message text cannot be empty.")
        return
    service = _svc(ctx)
    created = service.send_message(space_id, message, thread_key=thread_key)
    if created:
        print_success(f"Message sent successfully! (ID: {created.get('name', '')})")


@chat_group.command('reply')
@click.argument('message_id')
@click.option('--message', '-m', help='Reply message text')
@click.option('--space-id', help='Space ID if message_id is not fully qualified')
@click.pass_context
def chat_reply(ctx: click.Context, message_id: str, message: Optional[str], space_id: Optional[str]):
    """Reply to a message in its thread (supports interactive input)"""
    if not message:
        message = click.prompt("Reply text")
    if not message.strip():
        print_error("Reply text cannot be empty.")
        return
    service = _svc(ctx)
    replied = service.reply_message(message_id, message, space_id=space_id)
    if replied:
        print_success(f"Reply posted successfully! (ID: {replied.get('name', '')})")


@chat_group.command('edit')
@click.argument('message_id', required=False)
@click.option('--message', '-m', help='New message content')
@click.option('--space-id', help='Space ID if message_id is not fully qualified')
@click.pass_context
def chat_edit(ctx: click.Context, message_id: Optional[str], message: Optional[str], space_id: Optional[str]):
    """Edit an existing message"""
    if not message_id:
        from ..ui.human_flows import run_chat_messages_flow
        service = _svc(ctx)
        run_chat_messages_flow(service)
        return
    if not message:
        message = click.prompt("Updated message text")
    service = _svc(ctx)
    edited = service.edit_message(message_id, message, space_id=space_id)
    if edited:
        print_success(f"Message updated successfully! (ID: {edited.get('name', '')})")


@chat_group.command('delete')
@click.argument('message_id', required=False)
@click.option('--space-id', help='Space ID if message_id is not fully qualified')
@click.option('--yes', '-y', is_flag=True, help='Confirm deletion without prompting')
@click.pass_context
def chat_delete(ctx: click.Context, message_id: Optional[str], space_id: Optional[str], yes: bool):
    """Delete a chat message"""
    if not message_id:
        from ..ui.human_flows import run_chat_message_delete_flow
        service = _svc(ctx)
        run_chat_message_delete_flow(service)
        return
    if not yes:
        from .resource_resolver import GlobalResourceResolver
        if not GlobalResourceResolver.confirm_action(f"Delete message {message_id}?", default_yes=False):
            print_info("Operation cancelled.")
            return
    service = _svc(ctx)
    ok = service.delete_message(message_id, space_id=space_id)
    if ok:
        print_success(f"Message {message_id} deleted successfully.")


@chat_group.command('members')
@click.argument('space_id')
@click.option('--page-size', default=50, type=int, help='Maximum members to return')
@click.option('--format', 'output_format', type=click.Choice(['table', 'json']), default='table')
@click.pass_context
def chat_members(ctx: click.Context, space_id: str, page_size: int, output_format: str):
    """List members of a chat space"""
    service = _svc(ctx)
    res = service.list_members(space_id, page_size=page_size)
    mems = res.get('memberships', [])
    if not mems:
        print_info(f"No members found for space {space_id}.")
        return
    if output_format == 'json':
        print(format_output(mems, 'json'))
    else:
        headers = ['Member ID', 'Display Name', 'Role', 'Type']
        rows = [
            {
                'Member ID': m.get('name', '').split('/')[-1],
                'Display Name': m.get('member', {}).get('displayName', 'N/A'),
                'Role': m.get('role', 'MEMBER'),
                'Type': m.get('member', {}).get('type', 'HUMAN')
            }
            for m in mems
        ]
        print(format_output(rows, 'table', headers=headers))


@chat_group.command('add-member')
@click.argument('space_id')
@click.argument('user')
@click.option('--role', default='ROLE_MEMBER', type=click.Choice(['ROLE_MEMBER', 'ROLE_MANAGER']), help='Member role')
@click.pass_context
def chat_add_member(ctx: click.Context, space_id: str, user: str, role: str):
    """Add a member to a chat space"""
    service = _svc(ctx)
    res = service.add_member(space_id, user, role=role)
    if res:
        print_success(f"User {user} added to space {space_id} with role {role}.")


@chat_group.command('remove-member')
@click.argument('space_id')
@click.argument('user')
@click.option('--yes', '-y', is_flag=True, help='Confirm removal without prompting')
@click.pass_context
def chat_remove_member(ctx: click.Context, space_id: str, user: str, yes: bool):
    """Remove a member from a chat space"""
    if not yes:
        click.confirm(f"Remove member {user} from space {space_id}?", abort=True)
    service = _svc(ctx)
    ok = service.remove_member(space_id, user)
    if ok:
        print_success(f"Member {user} removed from space {space_id}.")


@chat_group.command('react')
@click.argument('message_id')
@click.argument('emoji')
@click.option('--space-id', help='Space ID if message_id is not fully qualified')
@click.pass_context
def chat_react(ctx: click.Context, message_id: str, emoji: str, space_id: Optional[str]):
    """Add an emoji reaction to a chat message"""
    service = _svc(ctx)
    res = service.create_reaction(message_id, emoji, space_id=space_id)
    if res:
        print_success(f"Reaction '{emoji}' added to message {message_id}.")


@chat_group.command('unreact')
@click.argument('reaction_name')
@click.pass_context
def chat_unreact(ctx: click.Context, reaction_name: str):
    """Delete an emoji reaction by its resource name"""
    service = _svc(ctx)
    ok = service.delete_reaction(reaction_name)
    if ok:
        print_success(f"Reaction {reaction_name} removed.")


@chat_group.command('search')
@click.argument('query')
@click.option('--space-id', help='Limit search to a specific space')
@click.option('--limit', default=25, type=int, help='Maximum matches to return')
@click.option('--format', 'output_format', type=click.Choice(['table', 'json']), default='table')
@click.pass_context
def chat_search(ctx: click.Context, query: str, space_id: Optional[str], limit: int, output_format: str):
    """Search for messages matching a query"""
    service = _svc(ctx)
    matches = service.search_messages(query, space_name=space_id, max_results=limit)
    if not matches:
        print_info(f"No messages found matching '{query}'.")
        return
    if output_format == 'json':
        print(format_output(matches, 'json'))
    else:
        headers = ['Message ID', 'Sender', 'Text', 'Created At']
        rows = [
            {
                'Message ID': m.get('name', '').split('/')[-1],
                'Sender': m.get('sender', {}).get('displayName', 'Unknown'),
                'Text': m.get('text', '')[:60],
                'Created At': m.get('createTime', '')[:19]
            }
            for m in matches
        ]
        print(format_output(rows, 'table', headers=headers))


@chat_group.command('threads')
@click.argument('space_id')
@click.option('--limit', default=20, type=int, help='Maximum threads to return')
@click.option('--format', 'output_format', type=click.Choice(['table', 'json']), default='table')
@click.pass_context
def chat_threads(ctx: click.Context, space_id: str, limit: int, output_format: str):
    """List threads in a space"""
    service = _svc(ctx)
    threads = service.list_threads(space_id, page_size=limit)
    if not threads:
        print_info(f"No threads found in space {space_id}.")
        return
    if output_format == 'json':
        print(format_output(threads, 'json'))
    else:
        headers = ['Thread ID', 'Sender', 'Initial Message', 'Messages']
        rows = [
            {
                'Thread ID': th.get('thread', '').split('/')[-1],
                'Sender': th.get('sender', 'Unknown'),
                'Initial Message': th.get('first_message', '')[:40],
                'Messages': str(th.get('message_count', 1))
            }
            for th in threads
        ]
        print(format_output(rows, 'table', headers=headers))


@chat_group.command('test-connection')
@click.pass_context
def chat_test_connection(ctx: click.Context):
    """Test connection to Google Chat API"""
    service = _svc(ctx)
    res = service.test_connection()
    if res.get('status') == 'success':
        print_success(f"{res.get('message')} (Accessible Spaces: {res.get('spaces_found', 0)})")
    else:
        print_error(f"Connection test failed: {res.get('message')}")


@chat_group.command('status')
@click.pass_context
def chat_status(ctx: click.Context):
    """View Google Chat service authentication and status"""
    service = _svc(ctx)
    profile = service.get_profile()
    print_header("💬 Google Chat API Status")
    print_key_value_pairs({
        'Service': profile.get('service'),
        'Authenticated': 'Yes' if profile.get('authenticated') else 'No',
        'Token Expiry': profile.get('token_expiry') or 'N/A',
        'Connection': profile.get('connection_status') or 'Unknown',
    })
