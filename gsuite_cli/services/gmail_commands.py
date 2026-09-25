"""
Gmail Click command group — all 12 subcommands for `hermes gmail`.

Normal-use commands
-------------------
  list      – List/search messages (DiskCache, 2-min TTL)
  read      – Display a full message (cached indefinitely)
  send      – Compose and send with optional attachments
  reply     – Reply in the same thread
  draft     – Save a draft (no send)
  label     – Apply/remove user labels
  mark      – Change read/unread/star/archive/trash state
  filters   – Subgroup: list / create / delete Gmail filters

DevOps automation commands
--------------------------
  alert            – Send a CI/CD pipeline alert email
  digest           – Fetch+email a summary of recent matching messages
  escalate         – Send a severity-tagged on-call escalation email
  schedule-summary – Print the cron snippet to run digest on a schedule
"""

from __future__ import annotations

import sys
import logging
from pathlib import Path
from typing import Optional

import click
from colorama import Fore, Style

from ..services.gmail import GmailService
from ..utils.formatters import (
    format_output,
    format_email_body,
    print_error,
    print_info,
    print_success,
    print_header,
    print_section,
    print_key_value_pairs,
    truncate_text,
)
from ..config import hermes_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _svc(ctx: click.Context) -> GmailService:
    """Build a GmailService from the Click context."""
    if ctx.obj and '_gmail_svc' in ctx.obj:
        return ctx.obj['_gmail_svc']
    return GmailService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))


def _bail(message: str, exit_code: int = 1) -> None:
    """Print an error and exit with *exit_code* (for script-detectable failures)."""
    print_error(message)
    sys.exit(exit_code)


def _severity_prefix(severity: str) -> str:
    """Map a severity string to a priority tag like [P1]."""
    mapping = {
        'p1': '[P1]', 'critical': '[P1]',
        'p2': '[P2]', 'high': '[P2]',
        'p3': '[P3]', 'medium': '[P3]',
        'p4': '[P4]', 'low': '[P4]',
    }
    return mapping.get(severity.lower(), f'[{severity.upper()}]')


def _parse_since(since: str) -> int:
    """Parse a duration string like '24h' or '7d' into hours (int)."""
    since = since.strip().lower()
    try:
        if since.endswith('h'):
            return int(since[:-1])
        if since.endswith('d'):
            return int(since[:-1]) * 24
        if since.endswith('m'):
            # treat minutes as rounded up to 1 hour minimum
            return max(1, int(since[:-1]) // 60)
        return int(since)   # bare number → hours
    except ValueError:
        raise click.BadParameter(
            f"Cannot parse duration '{since}'. Use formats like 24h, 7d, 90m."
        )


# ---------------------------------------------------------------------------
# 1. list
# ---------------------------------------------------------------------------

@click.command('list')
@click.option('--query', '-q', default='', help='Gmail search syntax query (maps to Gmail q parameter)')
@click.option('--label', default=None, help='Filter by label name or id')
@click.option('--unread', is_flag=True, help='Show only unread messages (adds is:unread to query)')
@click.option('--limit', default=50, show_default=True, help='Maximum messages to return')
@click.pass_context
def gmail_list(ctx, query, label, unread, limit):
    """List or search messages.

    Uses Gmail search syntax for --query (e.g. from:boss subject:report).
    Results are cached for 2 minutes to avoid redundant API calls.
    """
    svc = _svc(ctx)

    q_parts = []
    if query:
        q_parts.append(query)
    if unread:
        q_parts.append('is:unread')

    label_ids = [label] if label else None
    messages = svc.list_messages(
        query=' '.join(q_parts),
        max_results=limit,
        label_ids=label_ids,
    )

    if not messages:
        print_info('No messages found.')
        return

    rows = []
    for m in messages:
        rows.append({
            'ID': m['id'],
            'From': truncate_text(m.get('from', ''), 28),
            'Subject': truncate_text(m.get('subject', '(No subject)'), 38),
            'Date': (m.get('date') or '')[:16],
            'Snippet': truncate_text(m.get('snippet', ''), 40),
        })
    print(format_output(rows, format_type='table', tablefmt='simple'))


# ---------------------------------------------------------------------------
# 2. read
# ---------------------------------------------------------------------------

@click.command('read')
@click.argument('message_id')
@click.option('--no-cache', is_flag=True, help='Bypass the local message cache')
@click.pass_context
def gmail_read(ctx, message_id, no_cache):
    """Fetch and display a full message.

    Shows headers, plain-text body (HTML stripped as fallback), and attachment list.
    The full message body is cached indefinitely (immutable once sent) unless
    --no-cache is passed.
    """
    svc = _svc(ctx)
    msg = svc.get_message(message_id, format='full', no_cache=no_cache)
    if not msg:
        _bail(f'Message {message_id} not found.')

    print_header('Message')
    print_key_value_pairs({
        'From':    msg.get('from', ''),
        'To':      msg.get('to', ''),
        'CC':      msg.get('cc', '') or '—',
        'Subject': msg.get('subject', '(No subject)'),
        'Date':    msg.get('date', ''),
        'Labels':  ', '.join(msg.get('label_ids', [])) or '—',
    })

    print_section('Body')
    body_text = format_email_body(msg.get('body', ''))
    print(body_text if body_text.strip() else '(empty body)')

    attachments = msg.get('attachments', [])
    if attachments:
        print_section(f'Attachments ({len(attachments)})')
        att_rows = [
            {
                'Filename': a['filename'],
                'Type': a['mime_type'],
                'Size': f"{a['size']:,} B",
            }
            for a in attachments
        ]
        print(format_output(att_rows, format_type='table', tablefmt='simple'))


# ---------------------------------------------------------------------------
# 3. send
# ---------------------------------------------------------------------------

@click.command('send')
@click.option('--to', required=True, help='Recipient email address')
@click.option('--subject', required=True, help='Email subject')
@click.option('--body', required=True, help='Plain-text body')
@click.option('--cc', default=None, help='CC recipient')
@click.option('--attach', multiple=True, metavar='PATH',
              help='Path to attachment file (repeatable)')
@click.pass_context
def gmail_send(ctx, to, subject, body, cc, attach):
    """Compose and send a message.

    Supports file attachments (MIME multipart). Use --attach multiple times for
    multiple files.
    """
    svc = _svc(ctx)
    msg_id = svc.send_message(
        to=to, subject=subject, body=body,
        cc=cc, attachments=list(attach) or None,
    )
    if msg_id:
        print_success(f'Message sent (id: {msg_id})')
    else:
        _bail('Failed to send message.')


# ---------------------------------------------------------------------------
# 4. reply
# ---------------------------------------------------------------------------

@click.command('reply')
@click.argument('message_id')
@click.option('--body', required=True, help='Reply body (plain text)')
@click.option('--attach', multiple=True, metavar='PATH',
              help='Path to attachment file (repeatable)')
@click.pass_context
def gmail_reply(ctx, message_id, body, attach):
    """Reply to a message within the same thread.

    Preserves In-Reply-To, References, and threadId so the reply is grouped
    correctly in Gmail.
    """
    svc = _svc(ctx)
    sent_id = svc.reply_message(message_id, body=body, attachments=list(attach) or None)
    if sent_id:
        print_success(f'Reply sent (id: {sent_id})')
    else:
        _bail('Failed to send reply.')


# ---------------------------------------------------------------------------
# 5. draft
# ---------------------------------------------------------------------------

@click.command('draft')
@click.option('--to', required=True, help='Recipient email address')
@click.option('--subject', required=True, help='Email subject')
@click.option('--body', required=True, help='Plain-text body')
@click.option('--cc', default=None, help='CC recipient')
@click.pass_context
def gmail_draft(ctx, to, subject, body, cc):
    """Create a draft (does not send).

    The draft is saved via users.drafts.create and visible in the Gmail Drafts
    folder.
    """
    svc = _svc(ctx)
    draft_id = svc.create_draft(to=to, subject=subject, body=body, cc=cc)
    if draft_id:
        print_success(f'Draft saved (id: {draft_id})')
    else:
        _bail('Failed to create draft.')


# ---------------------------------------------------------------------------
# 6. label
# ---------------------------------------------------------------------------

@click.command('label')
@click.argument('message_id')
@click.option('--add', 'add_labels', multiple=True, metavar='LABEL',
              help='Label name to add (repeatable; created if absent)')
@click.option('--remove', 'remove_labels', multiple=True, metavar='LABEL',
              help='Label name to remove (repeatable)')
@click.pass_context
def gmail_label(ctx, message_id, add_labels, remove_labels):
    """Apply or remove labels on a message.

    User-defined labels are created automatically if they do not exist.
    System labels (INBOX, UNREAD, STARRED …) are accepted by name.

    Example: hermes gmail label <id> --add Bug --remove INBOX
    """
    if not add_labels and not remove_labels:
        raise click.UsageError('Specify at least one --add or --remove label.')

    svc = _svc(ctx)
    ok = svc.modify_labels(
        message_id,
        add_labels=list(add_labels) or None,
        remove_labels=list(remove_labels) or None,
    )
    if ok:
        parts = []
        if add_labels:
            parts.append(f"added: {', '.join(add_labels)}")
        if remove_labels:
            parts.append(f"removed: {', '.join(remove_labels)}")
        print_success(f"Labels updated — {'; '.join(parts)}")
    else:
        _bail('Failed to modify labels.')


# ---------------------------------------------------------------------------
# 7. mark
# ---------------------------------------------------------------------------

_MARK_ACTIONS = click.Choice(
    ['read', 'unread', 'star', 'unstar', 'archive', 'trash'],
    case_sensitive=False,
)


@click.command('mark')
@click.argument('message_id')
@click.option('--read',    'action', flag_value='read',    help='Mark as read')
@click.option('--unread',  'action', flag_value='unread',  help='Mark as unread')
@click.option('--star',    'action', flag_value='star',    help='Add STARRED label')
@click.option('--unstar',  'action', flag_value='unstar',  help='Remove STARRED label')
@click.option('--archive', 'action', flag_value='archive', help='Archive (remove from INBOX)')
@click.option('--trash',   'action', flag_value='trash',   help='Move to Trash')
@click.pass_context
def gmail_mark(ctx, message_id, action):
    """Change the read/unread/star/archive/trash state of a message.

    Exactly one action flag must be supplied.

    Example: hermes gmail mark <id> --archive
    """
    if not action:
        raise click.UsageError(
            'Specify exactly one of --read, --unread, --star, --unstar, --archive, --trash.'
        )

    svc = _svc(ctx)

    dispatch = {
        'read':    lambda: svc.mark_as_read(message_id),
        'unread':  lambda: svc.mark_as_unread(message_id),
        'star':    lambda: svc.mark_as_starred(message_id),
        'unstar':  lambda: svc.mark_as_unstarred(message_id),
        'archive': lambda: svc.archive_message(message_id),
        'trash':   lambda: svc.trash_message(message_id),
    }

    ok = dispatch[action]()
    if ok:
        print_success(f'Message {message_id}: {action}')
    else:
        _bail(f'Failed to {action} message {message_id}.')


# ---------------------------------------------------------------------------
# 8. filters  (sub-group)
# ---------------------------------------------------------------------------

@click.group('filters')
def gmail_filters():
    """Manage Gmail filters (list / create / delete)."""
    pass


@gmail_filters.command('list')
@click.pass_context
def filters_list(ctx):
    """List all Gmail filters."""
    svc = _svc(ctx)
    filters = svc.list_filters()
    if not filters:
        print_info('No filters found.')
        return
    rows = [
        {
            'ID':           f['id'],
            'From':         f.get('from', ''),
            'To':           f.get('to', ''),
            'Subject':      f.get('subject', ''),
            'Query':        f.get('query', ''),
            'Add labels':   f.get('add_labels', ''),
            'Remove labels':f.get('remove_labels', ''),
        }
        for f in filters
    ]
    print(format_output(rows, format_type='table', tablefmt='simple'))


@gmail_filters.command('create')
@click.option('--from', 'from_addr', default=None, help='Sender address to match')
@click.option('--to', 'to_addr', default=None, help='Recipient address to match')
@click.option('--subject', default=None, help='Subject text to match')
@click.option('--query', default=None, help='Gmail search query to match')
@click.option('--add-label', 'add_labels', multiple=True, metavar='LABEL',
              help='Label to apply (repeatable; created if absent)')
@click.option('--remove-label', 'remove_labels', multiple=True, metavar='LABEL',
              help='Label to remove (repeatable)')
@click.option('--mark-read', is_flag=True, help='Automatically mark as read')
@click.option('--archive', is_flag=True, help='Automatically archive (skip inbox)')
@click.pass_context
def filters_create(ctx, from_addr, to_addr, subject, query,
                   add_labels, remove_labels, mark_read, archive):
    """Create a new Gmail filter."""
    if not any([from_addr, to_addr, subject, query]):
        raise click.UsageError(
            'At least one of --from, --to, --subject, --query is required.'
        )
    svc = _svc(ctx)
    fid = svc.create_filter(
        from_addr=from_addr, to_addr=to_addr,
        subject=subject, query=query,
        add_labels=list(add_labels) or None,
        remove_labels=list(remove_labels) or None,
        mark_read=mark_read,
        archive=archive,
    )
    if fid:
        print_success(f'Filter created (id: {fid})')
    else:
        _bail('Failed to create filter.')


@gmail_filters.command('delete')
@click.argument('filter_id')
@click.pass_context
def filters_delete(ctx, filter_id):
    """Delete a Gmail filter by id."""
    svc = _svc(ctx)
    ok = svc.delete_filter(filter_id)
    if ok:
        print_success(f'Filter deleted: {filter_id}')
    else:
        _bail(f'Failed to delete filter {filter_id}.')


# ---------------------------------------------------------------------------
# 9. alert  (DevOps)
# ---------------------------------------------------------------------------

@click.command('alert')
@click.option('--status', required=True,
              type=click.Choice(['success', 'failure'], case_sensitive=False),
              help='Pipeline result')
@click.option('--pipeline', required=True, help='Pipeline / job name')
@click.option('--to', required=True, help='Recipient email address')
@click.option('--log-file', 'log_file', default=None,
              type=click.Path(exists=True, dir_okay=False),
              help='Path to a log file; last 50 lines are appended to the email')
@click.option('--log-lines', default=50, show_default=True,
              help='Number of tail lines to include from --log-file')
@click.pass_context
def gmail_alert(ctx, status, pipeline, to, log_file, log_lines):
    """Send a CI/CD pipeline alert email.

    Exit code is 0 on success, non-zero on failure so CI steps can detect it.

    Example (GitHub Actions)::

        - name: Notify
          run: hermes gmail alert --status failure --pipeline my-job --to ops@example.com
    """
    icon = '✅' if status == 'success' else '❌'
    subject = f'{icon} [{status.upper()}] Pipeline: {pipeline}'

    body_lines = [
        f'Pipeline alert from Hermes CLI',
        f'',
        f'Pipeline : {pipeline}',
        f'Status   : {status.upper()}',
        f'',
    ]

    if log_file:
        try:
            with open(log_file, 'r', encoding='utf-8', errors='replace') as fh:
                lines = fh.readlines()
            tail = lines[-log_lines:] if len(lines) > log_lines else lines
            body_lines.append(f'--- Last {len(tail)} lines of {Path(log_file).name} ---')
            body_lines.extend(line.rstrip() for line in tail)
        except OSError as exc:
            logger.warning('Could not read log file %s: %s', log_file, exc)
            body_lines.append(f'(Could not read log file: {exc})')

    body = '\n'.join(body_lines)
    svc = _svc(ctx)
    msg_id = svc.send_message(to=to, subject=subject, body=body)
    if msg_id:
        print_success(f'Alert sent (id: {msg_id})')
        sys.exit(0)
    else:
        # Explicit non-zero exit so CI step can detect failure
        _bail('Failed to send alert email.', exit_code=1)


# ---------------------------------------------------------------------------
# 10. digest  (DevOps)
# ---------------------------------------------------------------------------

@click.command('digest')
@click.option('--since', required=True,
              help='Lookback window (e.g. 24h, 7d, 90m)')
@click.option('--query', 'filter_query', default='',
              help='Gmail search query to filter messages')
@click.option('--to', required=True, help='Recipient email address')
@click.option('--gemini-summarize', is_flag=True,
              help='Summarize snippets via Gemini before composing the digest')
@click.pass_context
def gmail_digest(ctx, since, filter_query, to, gemini_summarize):
    """Fetch recent messages and email a digest.

    Use --gemini-summarize to pass message snippets through the existing Gemini
    integration before composing the email body.

    Example::

        hermes gmail digest --since 24h --query label:alerts --to ops@example.com
    """
    hours = _parse_since(since)
    svc = _svc(ctx)

    messages = svc.list_messages_since(hours=hours, query=filter_query, max_results=100)
    if not messages:
        print_info(f'No messages found in the last {since}.')
        return

    # Build email-friendly representation of each message
    email_dicts = [
        {
            'subject': m.get('subject', '(No subject)'),
            'from':    m.get('from', ''),
            'date':    (m.get('date') or '')[:16],
            'snippet': m.get('snippet', ''),
            'body':    m.get('snippet', ''),   # snippet is enough for summarization
        }
        for m in messages
    ]

    if gemini_summarize:
        # Reuse the existing EmailSummarizer — no duplicate Gemini call logic
        try:
            from ..ai.summarizer import EmailSummarizer
            config_manager = ctx.obj.get('config_manager')
            summarizer = EmailSummarizer(config_manager)
            result = summarizer.summarize_multiple_emails(email_dicts)
            ai_summary = result.get('summary', '')
        except Exception as exc:
            logger.warning('Gemini summarization failed, falling back: %s', exc)
            ai_summary = ''
    else:
        ai_summary = ''

    # Compose digest body
    subject = f'Hermes digest: last {since} — {len(messages)} messages'
    body_lines = [
        f'Hermes Email Digest',
        f'Period   : last {since}',
        f'Messages : {len(messages)}',
        f'Filter   : {filter_query or "(none)"}',
        '',
    ]
    if ai_summary:
        body_lines += ['--- AI Summary ---', ai_summary, '']

    body_lines.append('--- Message List ---')
    for m in messages:
        body_lines.append(
            f"[{(m.get('date') or '')[:16]}] "
            f"{truncate_text(m.get('from', ''), 30)} — "
            f"{truncate_text(m.get('subject', '(No subject)'), 60)}"
        )
        if m.get('snippet'):
            body_lines.append(f"  {truncate_text(m['snippet'], 100)}")
        body_lines.append('')

    msg_id = svc.send_message(to=to, subject=subject, body='\n'.join(body_lines))
    if msg_id:
        print_success(f'Digest sent to {to} (id: {msg_id}, {len(messages)} messages)')
    else:
        _bail('Failed to send digest.')


# ---------------------------------------------------------------------------
# 11. escalate  (DevOps)
# ---------------------------------------------------------------------------

@click.command('escalate')
@click.option('--to', required=True, help='Primary recipient email address')
@click.option('--severity', required=True,
              help='Severity level: p1/critical, p2/high, p3/medium, p4/low')
@click.option('--message', 'incident_message', required=True,
              help='Incident description')
@click.option('--cc-oncall', is_flag=True,
              help='CC the on-call contact read from ~/.hermes/config.yaml (oncall.email)')
@click.pass_context
def gmail_escalate(ctx, to, severity, incident_message, cc_oncall):
    """Send a severity-tagged on-call escalation email.

    The on-call address for --cc-oncall is read from oncall.email in
    ~/.hermes/config.yaml so it is never hard-coded.

    Example::

        hermes gmail escalate \\
            --to sre-lead@example.com \\
            --severity p1 \\
            --message "API gateway returning 503 for 10 minutes" \\
            --cc-oncall
    """
    prefix = _severity_prefix(severity)
    subject = f'{prefix} Incident: {incident_message[:80]}'

    cc: Optional[str] = None
    if cc_oncall:
        cc = hermes_config.get_oncall_email()
        if not cc:
            print_info(
                'No oncall.email set in ~/.hermes/config.yaml — skipping CC. '
                'Run: hermes config set oncall.email <address>'
            )

    body_lines = [
        'On-call escalation from Hermes CLI',
        '',
        f'Severity  : {severity.upper()}  ({prefix})',
        f'Summary   : {incident_message}',
        '',
        'Respond to this incident immediately.',
        'Update your incident tracker and notify affected stakeholders.',
    ]
    if cc:
        body_lines.append(f'\nOn-call CC: {cc}')

    svc = _svc(ctx)
    msg_id = svc.send_message(
        to=to, subject=subject, body='\n'.join(body_lines), cc=cc
    )
    if msg_id:
        print_success(f'Escalation sent (id: {msg_id})')
    else:
        _bail('Failed to send escalation email.', exit_code=1)


# ---------------------------------------------------------------------------
# 12. schedule-summary  (info-only, no scheduling logic)
# ---------------------------------------------------------------------------

@click.command('schedule-summary')
@click.option('--cron-hint', is_flag=True, default=True, is_eager=True,
              expose_value=False,
              help='Print scheduling snippets (default behaviour; flag kept for discoverability)')
@click.option('--since', default='24h', show_default=True,
              help='Lookback window to embed in the snippet')
@click.option('--query', 'filter_query', default='',
              help='Gmail search query to embed in the snippet')
@click.option('--to', default='<recipient@example.com>',
              help='Recipient to embed in the snippet')
def gmail_schedule_summary(since, filter_query, to):
    """Print cron / CI snippets to run `hermes gmail digest` on a schedule.

    Hermes itself does not manage cron jobs or CI schedules.  This command
    just prints copy-pasteable snippets so you can wire the digest into your
    existing scheduler.
    """
    q_flag = f' --query "{filter_query}"' if filter_query else ''
    digest_cmd = f'hermes gmail digest --since {since}{q_flag} --to {to}'

    print_header('Scheduling snippets for hermes gmail digest')

    print_section('Unix cron  (crontab -e)')
    print(f'  # Every day at 08:00')
    print(f'  0 8 * * * {digest_cmd}')
    print()
    print(f'  # Every Monday at 09:00 for a weekly digest (use --since 7d)')
    print(f'  0 9 * * 1 hermes gmail digest --since 7d{q_flag} --to {to}')

    print_section('GitHub Actions  (.github/workflows/digest.yml)')
    print(
        f'''  on:
    schedule:
      - cron: "0 8 * * *"   # daily 08:00 UTC
  jobs:
    digest:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - run: pip install gsuite-cli
        - run: {digest_cmd}'''
    )

    print_section('Jenkins  (Declarative Pipeline)')
    print(
        f'''  pipeline {{
    triggers {{ cron("0 8 * * *") }}
    stages {{
      stage("Digest") {{
        steps {{ sh "{digest_cmd}" }}
      }}
    }}
  }}'''
    )

    print_section('systemd timer  (digest.service + digest.timer)')
    print(
        f'''  # /etc/systemd/system/hermes-digest.service
  [Service]
  ExecStart={digest_cmd}

  # /etc/systemd/system/hermes-digest.timer
  [Timer]
  OnCalendar=*-*-* 08:00:00
  [Install]
  WantedBy=timers.target'''
    )

    print()
    print_info('Tip: add --gemini-summarize to any digest command for an AI-generated summary.')


# ---------------------------------------------------------------------------
# Public export: all top-level commands/groups to attach to the gmail group
# ---------------------------------------------------------------------------

GMAIL_COMMANDS = [
    gmail_list,
    gmail_read,
    gmail_send,
    gmail_reply,
    gmail_draft,
    gmail_label,
    gmail_mark,
    gmail_filters,     # sub-group
    gmail_alert,
    gmail_digest,
    gmail_escalate,
    gmail_schedule_summary,
]
