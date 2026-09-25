"""
Main CLI entry point for GSuite CLI
"""

import logging
import sys
from pathlib import Path
from datetime import datetime, timedelta
from dateutil import tz
import time

import click
from colorama import init, Fore, Style
from googleapiclient.http import MediaFileUpload

from . import __version__
from .auth.oauth import OAuthManager
from .utils.formatters import setup_logging, print_success, print_error, print_info, print_warning, format_output, print_header, print_section, print_key_value_pairs, format_email_body
from .services.calendar import CalendarService
from .services.calendar_resolver import CalendarResolver, CalendarEventResolver, CalendarResolutionError
from .services.gmail import GmailService
from .services.sheets import SheetsService
from .services.docs import DocsService
from .services.docs_advanced import AdvancedDocsService
from .services.meet import MeetService
from .services.calendar_advanced import AdvancedCalendarService
from .services.gmail_advanced import AdvancedGmailService
from .services.sheets_advanced import AdvancedSheetsService
from .services.gmail_commands import (
    gmail_reply,
    gmail_draft,
    gmail_label,
    gmail_mark,
    gmail_filters,
    gmail_alert,
    gmail_digest,
    gmail_escalate,
    gmail_schedule_summary,
)
from .config.manager import ConfigManager
from .utils.cache import CacheManager, get_global_cache, configure_cache
from .ai import ai as ai_commands
from .services.diagnostics import DiagnosticsService
from .services.forms import FormsService
from .services.reminders import ReminderService
from .services.booking import BookingService
from .services.chat import ChatService
from .services.chat_commands import chat_group, _svc as _get_chat_service
from .ui.interactive import start_interactive_mode


def _parse_weekdays(weekday_values):
    mapping = {
        'mon': 'MO',
        'tue': 'TU',
        'wed': 'WE',
        'thu': 'TH',
        'fri': 'FR',
        'sat': 'SA',
        'sun': 'SU',
    }
    result = []
    for value in weekday_values:
        parts = []
        if '-' in value:
            tokens = value.split('-')
            if len(tokens) == 2:
                start = tokens[0].lower()
                end = tokens[1].lower()
                order = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
                if start in order and end in order:
                    start_index = order.index(start)
                    end_index = order.index(end)
                    if start_index <= end_index:
                        parts = order[start_index:end_index + 1]
        else:
            parts = [value.lower()]
        for part in parts:
            if part in mapping and mapping[part] not in result:
                result.append(mapping[part])
    return result


def _build_recurrence(daily, weekly, monthly, weekdays, month_day, rrule_str, until_str, count):
    modes = [flag for flag in [daily, weekly, monthly, bool(rrule_str)] if flag]
    if len(modes) > 1:
        return None, "Specify only one of --daily, --weekly, --monthly, or --rrule"
    if not any(modes):
        return None, None
    if rrule_str and (until_str or count):
        return None, "Cannot combine --rrule with --until or --count"
    if rrule_str:
        rule = rrule_str.strip()
        if not rule.upper().startswith("RRULE:"):
            rule = "RRULE:" + rule
        return [rule], None
    if daily:
        freq = "DAILY"
    elif weekly:
        freq = "WEEKLY"
    else:
        freq = "MONTHLY"
    parts = [f"FREQ={freq}"]
    if weekly:
        bydays = _parse_weekdays(weekdays)
        if bydays:
            parts.append("BYDAY=" + ",".join(bydays))
    if monthly and month_day:
        parts.append(f"BYMONTHDAY={month_day}")
    if until_str:
        try:
            until_date = datetime.strptime(until_str, "%Y-%m-%d")
            until_value = until_date.strftime("%Y%m%dT000000Z")
            parts.append(f"UNTIL={until_value}")
        except ValueError:
            return None, "Invalid --until format. Use YYYY-MM-DD"
    if count is not None:
        if count <= 0:
            return None, "--count must be positive"
        parts.append(f"COUNT={count}")
    rule = "RRULE:" + ";".join(parts)
    return [rule], None


def _parse_reminder_offset(value: str):
    value = value.strip().lower()
    if not value:
        return None
    unit = value[-1]
    number_part = value[:-1]
    if unit not in ('m', 'h', 'd'):
        return None
    try:
        amount = int(number_part)
    except ValueError:
        return None
    if amount <= 0:
        return None
    if unit == 'm':
        return amount
    if unit == 'h':
        return amount * 60
    return amount * 60 * 24

# Initialize colorama for cross-platform colored output
init(autoreset=True)

# Global OAuth manager instance
oauth_manager = OAuthManager()


@click.group()
@click.version_option(version=__version__, prog_name="hermes")
@click.option('--debug', is_flag=True, help='Enable debug logging')
@click.option('--config-dir', type=click.Path(), help='Custom configuration directory')
@click.option('--no-cache', is_flag=True, help='Disable caching')
@click.pass_context
def cli(ctx, debug, config_dir, no_cache):
    """
    GSuite CLI - Advanced CLI tool for Google Workspace services
    
    Manage your Google Calendar, Gmail, Sheets, Drive, and Tasks from the command line.
    """
    # Setup logging
    setup_logging(debug)
    
    # Initialize context
    ctx.ensure_object(dict)
    ctx.obj['debug'] = debug
    if 'oauth_manager' not in ctx.obj:
        ctx.obj['oauth_manager'] = OAuthManager(config_dir) if config_dir else oauth_manager
    if 'config_manager' not in ctx.obj:
        ctx.obj['config_manager'] = ConfigManager(config_dir)
    
    # Configure cache based on settings
    config = ctx.obj['config_manager'].config
    if no_cache or not config.cache_enabled:
        configure_cache(enabled=False)
        ctx.obj['cache_manager'] = None
    else:
        cache_manager = CacheManager(
            cache_dir=config.cache_dir,
            default_ttl=config.cache_ttl
        )
        configure_cache(ttl=config.cache_ttl, cache_dir=config.cache_dir, enabled=True)
        ctx.obj['cache_manager'] = cache_manager
    
    # Update debug mode from config if not specified in command line
    if not debug and ctx.obj['config_manager'].get('debug_mode'):
        setup_logging(True)
    
    # Check authentication status
    if not ctx.obj['oauth_manager'].is_authenticated():
        print_info("Not authenticated. Run 'hermes auth login' (or 'python -m gsuite_cli.cli auth login') to get started.")


@cli.group()
def auth():
    """Authentication commands"""
    pass


@auth.command()
@click.option('--service', '-s', help='Specific service to authenticate (e.g. drive, gmail, chat, calendar, tasks)')
@click.option('--force', '-f', is_flag=True, help='Force re-authentication even if already authenticated')
@click.pass_context
def login(ctx, service=None, force=False):
    """Authenticate with Google Workspace"""
    oauth_mgr = ctx.obj['oauth_manager']

    from .auth.oauth import SCOPES
    scopes = None
    if service:
        svc_clean = service.lower().replace('-', '_')
        if svc_clean in SCOPES:
            scopes = SCOPES[svc_clean]
        elif svc_clean in ('docs', 'document', 'doc'):
            scopes = SCOPES['documents']
        elif svc_clean in ('scripts', 'script'):
            scopes = SCOPES['apps_script']
        else:
            print_error(f"Unknown service: {service}")
            return

    # Check whether the user is already authenticated
    if not force and oauth_mgr.is_authenticated():
        if scopes:
            auth_info = oauth_mgr.get_auth_info()
            granted = set(auth_info.get('scopes', []))
            if set(scopes).issubset(granted):
                print_success("✓ Already authenticated with required permissions!")
                print_info("Run 'hermes auth status' for details, or 'hermes auth login --force' to re-authenticate.")
                return
        else:
            print_success("✓ Already authenticated!")
            print_info("Run 'hermes auth status' for details, or 'hermes auth login --force' to re-authenticate.")
            return

    print_info("Starting authentication process...")
    
    # Check if credentials configuration is available
    if not oauth_mgr.has_client_config():
        print_error("OAuth client configuration not found!")
        print_info("Please follow these steps:")
        print_info("1. Go to Google Cloud Console: https://console.cloud.google.com/")
        print_info("2. Create a new project or select an existing one")
        print_info("3. Enable APIs: Gmail, Calendar, Sheets, Drive, Docs, Tasks, Meet, Forms, Chat")
        print_info("4. Configure the OAuth Consent Screen (User Type: External, status: Testing)")
        print_info("5. Create OAuth 2.0 Client ID credentials (Application type: Desktop app)")
        print_info("6. Download the JSON file and save it as:")
        print_info(f"   {oauth_mgr.credentials_file}")
        print_info("   Or set environment variable: HERMES_GOOGLE_CLIENT_SECRET=<path_to_credentials.json>")
        return

    # Attempt authentication
    creds = oauth_mgr.get_credentials(scopes=scopes)
    if creds:
        print_success("Authentication successful!")
        if creds.expiry:
            print_info(f"Token expires: {creds.expiry}")
    else:
        print_error("Authentication failed!")


@auth.command()
@click.pass_context
def logout(ctx):
    """Revoke authentication"""
    if ctx.obj['oauth_manager'].revoke_credentials():
        print_success("Successfully logged out. Local credentials revoked.")
    else:
        print_error("No active authentication found")


@auth.command()
@click.pass_context
def status(ctx):
    """Check authentication status"""
    auth_info = ctx.obj['oauth_manager'].get_auth_info()
    
    if auth_info.get('authenticated'):
        print_success("✓ Authenticated")
        print_info(f"Valid: {auth_info.get('valid', 'Unknown')}")
        print_info(f"Expired: {auth_info.get('expired', 'Unknown')}")
        if auth_info.get('token_expiry'):
            print_info(f"Expires: {auth_info['token_expiry']}")
        print_info(f"Has refresh token: {auth_info.get('refresh_token', False)}")
    else:
        print_error("✗ Not authenticated")
        if 'error' in auth_info:
            print_error(f"Error: {auth_info['error']}")


@auth.command('chat')
@click.pass_context
def auth_chat(ctx):
    """Verify or test Google Chat API authentication"""
    from .services.chat_commands import chat_test_connection
    ctx.invoke(chat_test_connection)


def _make_auth_test_cmd(svc_key, svc_label):
    @click.pass_context
    def _cmd(ctx):
        from .auth.oauth import ensure_authenticated
        try:
            ensure_authenticated(svc_key)
            print_success(f"Authentication verified for {svc_label}.")
        except Exception as e:
            print_error(f"Authentication failed for {svc_label}: {e}")
    _cmd.__doc__ = f"Verify or test {svc_label} authentication"
    return _cmd


for _r_key, (_r_svc, _r_name) in {
    'drive': ('drive', 'Google Drive API'),
    'tasks': ('tasks', 'Google Tasks API'),
    'docs': ('docs', 'Google Docs API'),
    'sheets': ('sheets', 'Google Sheets API'),
    'events': ('events', 'Google Workspace Events API'),
    'apps-script': ('apps_script', 'Google Apps Script API'),
    'scripts': ('apps_script', 'Google Apps Script API'),
    'admin': ('admin', 'Google Admin SDK'),
    'identity': ('cloud_identity', 'Google Cloud Identity API'),
    'cloud-search': ('cloud_search', 'Google Cloud Search API'),
    'forms': ('forms', 'Google Forms API'),
    'drive-activity': ('drive_activity', 'Google Drive Activity API'),
}.items():
    auth.command(_r_key)(_make_auth_test_cmd(_r_svc, _r_name))


@cli.group()
def calendar():
    """Google Calendar commands"""
    pass


def _resolve_calendar_id(raw_id, ctx, default='primary'):
    if not raw_id:
        return default
    try:
        service = CalendarService(ctx.obj['oauth_manager'])
        config_manager = ctx.obj.get('config_manager')
        calendars = CalendarResolver.get_calendars(service)
        return CalendarResolver.resolve(raw_id, calendars, config_manager)
    except Exception:
        return raw_id


@calendar.command('info')
@click.argument('target', default='1', required=False)
@click.pass_context
def calendar_info(ctx, target):
    """View technical information for a calendar: hermes calendar info <TARGET>"""
    service = CalendarService(ctx.obj['oauth_manager'])
    config_manager = ctx.obj.get('config_manager')
    cal = CalendarResolver.get_calendar_info(target, service, config_manager)
    if not cal:
        print_error(f"Calendar '{target}' not found.")
        return
    print(Fore.WHITE + Style.BRIGHT + "Calendar Information")
    print(Fore.CYAN + "────────────────────────────")
    print()
    print(f"{'Name':<10}: {cal.get('summary', 'Untitled')}")
    print(f"{'ID':<10}: {cal.get('id', '')}")
    print(f"{'Primary':<10}: {'Yes' if cal.get('primary') else 'No'}")
    print(f"{'Role':<10}: {cal.get('access_role', 'reader')}")
    print(f"{'Time Zone':<10}: {cal.get('timezone', cal.get('timeZone', 'UTC'))}")


@calendar.command('alias')
@click.argument('target')
@click.argument('alias_name')
@click.pass_context
def calendar_set_alias(ctx, target, alias_name):
    """Create a calendar alias: hermes calendar alias <TARGET> <ALIAS>"""
    service = CalendarService(ctx.obj['oauth_manager'])
    config_manager = ctx.obj.get('config_manager')
    if not config_manager:
        print_error("Configuration manager not available.")
        return
    success, msg = CalendarResolver.set_alias(target, alias_name, service, config_manager)
    if success:
        print_success(f"Alias created: {msg}")
    else:
        print_error(f"Failed to create alias: {msg}")


@calendar.command('aliases')
@click.pass_context
def calendar_list_aliases(ctx):
    """List calendar aliases: hermes calendar aliases"""
    service = CalendarService(ctx.obj['oauth_manager'])
    config_manager = ctx.obj.get('config_manager')
    if not config_manager:
        print_error("Configuration manager not available.")
        return
    aliases = CalendarResolver.get_aliases(service, config_manager)
    if not aliases:
        print_info("No calendar aliases defined.")
        return
    print(Fore.WHITE + Style.BRIGHT + "Calendar Aliases\n")
    max_alias_len = max(len(a[0]) for a in aliases)
    width = max(max_alias_len + 2, 10)
    for alias_name, cal_name, _ in aliases:
        print(f"{alias_name:<{width}} → {cal_name}")


@calendar.command('list')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def calendar_list(ctx, format):
    """List calendars"""
    cache_manager = ctx.obj.get('cache_manager')
    service = CalendarService(ctx.obj['oauth_manager'], cache_manager)
    calendars = service.list_calendars()
    if not calendars:
        print_info("No calendars found")
        return
    formatted = []
    for cal in calendars:
        formatted.append(
            {
                'ID': cal['id'],
                'Summary': cal['summary'],
                'Description': cal['description'],
                'Primary': cal['primary'],
                'Role': cal['access_role'],
            }
        )
    output = format_output(formatted, format_type=format)
    print(output)


@calendar.command('list-events')
@click.argument('calendar_id_arg', required=False)
@click.option('--calendar-id', 'calendar_id_opt', default=None, help='Calendar ID')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def calendar_list_events(ctx, calendar_id_arg, calendar_id_opt, format):
    """List calendar events"""
    cache_manager = ctx.obj.get('cache_manager')
    service = CalendarService(ctx.obj['oauth_manager'], cache_manager)
    raw_id = calendar_id_opt or calendar_id_arg
    events = []
    if raw_id:
        calendar_id = _resolve_calendar_id(raw_id.strip(), ctx, default='primary')
        events = service.list_events(calendar_id=calendar_id)
    else:
        calendars = service.list_calendars()
        for cal in calendars:
            cal_events = service.list_events(calendar_id=cal['id'])
            events.extend(cal_events)
    if not events:
        print_info("No events found")
        return
    formatted_events = []
    for event in events:
        formatted_events.append(
            {
                'ID': event['id'],
                'Title': event['summary'][:24] + ('...' if len(event['summary']) > 24 else ''),
                'Start': event['start'][:16],
                'End': event['end'][:16],
                'Location': event['location'][:14] + ('...' if len(event['location']) > 14 else ''),
                'Description': event['description'][:24] + ('...' if len(event['description']) > 24 else ''),
            }
        )
    output = format_output(formatted_events, format_type=format)
    print(output)


@calendar.command('get')
@click.argument('event_id')
@click.option('--calendar-id', default='primary', help='Calendar ID (default: primary)')
@click.option('--format', default='text', type=click.Choice(['text', 'json']), help='Output format')
@click.pass_context
def calendar_get(ctx, event_id, calendar_id, format):
    """Get full details of a specific event"""
    calendar_id = _resolve_calendar_id(calendar_id, ctx, default='primary')
    service = CalendarService(ctx.obj['oauth_manager'])
    
    # Try resolving event_id in case it is a displayed number, title match, or direct ID
    events = service.list_events(calendar_id=calendar_id, max_results=100)
    try:
        resolved_event = CalendarEventResolver.resolve(event_id, events, service, calendar_id)
        real_event_id = resolved_event.get('id', event_id)
    except Exception:
        real_event_id = event_id

    event = service.get_event(real_event_id, calendar_id=calendar_id)
    
    if not event:
        print_error(f"Event '{event_id}' not found")
        return
    
    if format == 'json':
        import json
        print(json.dumps(event, indent=2, default=str))
        return
    
    print_header(f"📅 Event: {event['summary']}")
    pairs = [
        ("Event ID", event['id']),
        ("Title", event['summary']),
        ("Start", event['start']),
        ("End", event['end']),
        ("Timezone", event.get('time_zone', 'UTC')),
        ("Status", event.get('status', 'confirmed')),
        ("Location", event.get('location') or 'None'),
    ]
    if event.get('meet_link'):
        pairs.append(("Google Meet", f"🎥 {event['meet_link']}"))
    if event.get('description'):
        pairs.append(("Description", event['description']))
    
    org = event.get('organizer', {})
    if org:
        org_str = org.get('displayName') or org.get('email', '')
        if org_str:
            pairs.append(("Organizer", org_str))
    
    attendees = event.get('attendees', [])
    if attendees:
        att_strs = []
        for a in attendees:
            status_icon = "✓" if a.get('responseStatus') == 'accepted' else ("?" if a.get('responseStatus') == 'tentative' else "•")
            att_strs.append(f"{status_icon} {a.get('email')} ({a.get('responseStatus', 'needsAction')})")
        pairs.append(("Attendees", f"{len(attendees)} total:\n  " + "\n  ".join(att_strs)))
    
    if event.get('recurrence'):
        pairs.append(("Recurrence", ", ".join(event['recurrence'])))
    
    reminders = event.get('reminders', {})
    if reminders.get('useDefault'):
        pairs.append(("Reminders", "Using calendar defaults"))
    elif reminders.get('overrides'):
        ov_strs = [f"{o.get('minutes')}m via {o.get('method')}" for o in reminders['overrides']]
        pairs.append(("Reminders", ", ".join(ov_strs)))
    
    print_key_value_pairs(dict(pairs))


@calendar.group('event')
def calendar_event_group():
    """Event operations: hermes calendar event <COMMAND>"""
    pass


@calendar_event_group.command('info')
@click.argument('event_reference')
@click.option('--calendar-id', default='primary', help='Calendar ID (default: primary)')
@click.option('--format', default='text', type=click.Choice(['text', 'json']), help='Output format')
@click.pass_context
def calendar_event_info(ctx, event_reference, calendar_id, format):
    """View complete event information: hermes calendar event info <EVENT-REFERENCE>"""
    ctx.invoke(calendar_get, event_id=event_reference, calendar_id=calendar_id, format=format)


@calendar.command('event-info')
@click.argument('event_reference')
@click.option('--calendar-id', default='primary', help='Calendar ID (default: primary)')
@click.option('--format', default='text', type=click.Choice(['text', 'json']), help='Output format')
@click.pass_context
def calendar_event_info_alias(ctx, event_reference, calendar_id, format):
    """View complete event information: hermes calendar event-info <EVENT-REFERENCE>"""
    ctx.invoke(calendar_get, event_id=event_reference, calendar_id=calendar_id, format=format)


@calendar.command('today')
@click.option('--calendar-id', default='primary', help='Calendar ID (default: primary)')
@click.option('--timezone', 'timezone_str', default=None, help='Timezone (e.g. America/New_York)')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def calendar_today(ctx, calendar_id, timezone_str, format):
    """List today's events"""
    calendar_id = _resolve_calendar_id(calendar_id, ctx, default='primary')
    service = CalendarService(ctx.obj['oauth_manager'])
    events = service.get_today_events(calendar_id=calendar_id, timezone_str=timezone_str)
    
    if not events:
        print_info("No events scheduled for today.")
        return
    
    print_header(f"📅 TODAY'S EVENTS ({len(events)})")
    formatted = []
    for ev in events:
        start_display = ev['start'][11:16] if 'T' in ev['start'] else ev['start']
        meet_str = "🎥 Meet" if ev.get('meet_link') else ""
        formatted.append({
            'Time': start_display,
            'Title': ev['summary'],
            'Location': ev.get('location', '')[:20],
            'Online': meet_str,
            'ID': ev['id']
        })
    print(format_output(formatted, format_type=format))


@calendar.command('tomorrow')
@click.option('--calendar-id', default='primary', help='Calendar ID (default: primary)')
@click.option('--timezone', 'timezone_str', default=None, help='Timezone (e.g. America/New_York)')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def calendar_tomorrow(ctx, calendar_id, timezone_str, format):
    """List tomorrow's events"""
    calendar_id = _resolve_calendar_id(calendar_id, ctx, default='primary')
    service = CalendarService(ctx.obj['oauth_manager'])
    events = service.get_tomorrow_events(calendar_id=calendar_id, timezone_str=timezone_str)
    
    if not events:
        print_info("No events scheduled for tomorrow.")
        return
    
    print_header(f"📅 TOMORROW'S EVENTS ({len(events)})")
    formatted = []
    for ev in events:
        start_display = ev['start'][11:16] if 'T' in ev['start'] else ev['start']
        meet_str = "🎥 Meet" if ev.get('meet_link') else ""
        formatted.append({
            'Time': start_display,
            'Title': ev['summary'],
            'Location': ev.get('location', '')[:20],
            'Online': meet_str,
            'ID': ev['id']
        })
    print(format_output(formatted, format_type=format))


@calendar.command('upcoming')
@click.option('--limit', default=10, type=int, help='Maximum events to show (default: 10)')
@click.option('--calendar-id', default='primary', help='Calendar ID (default: primary)')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def calendar_upcoming(ctx, limit, calendar_id, format):
    """List upcoming events (nearest first)"""
    calendar_id = _resolve_calendar_id(calendar_id, ctx, default='primary')
    service = CalendarService(ctx.obj['oauth_manager'])
    events = service.get_upcoming_events(calendar_id=calendar_id, limit=limit)
    
    if not events:
        print_info("No upcoming events found.")
        return
    
    print_header(f"📅 UPCOMING EVENTS ({len(events)})")
    formatted = []
    for ev in events:
        start_display = ev['start'][:16].replace('T', ' ')
        meet_str = "🎥 Meet" if ev.get('meet_link') else ""
        formatted.append({
            'Start': start_display,
            'Title': ev['summary'][:30],
            'Location': ev.get('location', '')[:18],
            'Online': meet_str,
            'ID': ev['id']
        })
    print(format_output(formatted, format_type=format))


@calendar.command('by-date')
@click.option('--date', 'target_date', required=True, help='Date (YYYY-MM-DD)')
@click.option('--calendar-id', default='primary', help='Calendar ID (default: primary)')
@click.option('--timezone', 'timezone_str', default=None, help='Timezone')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def calendar_by_date(ctx, target_date, calendar_id, timezone_str, format):
    """List events for a specific date"""
    calendar_id = _resolve_calendar_id(calendar_id, ctx, default='primary')
    service = CalendarService(ctx.obj['oauth_manager'])
    events = service.get_events_by_date(target_date=target_date, calendar_id=calendar_id, timezone_str=timezone_str)
    
    if not events:
        print_info(f"No events found for {target_date}.")
        return
    
    print_header(f"📅 EVENTS FOR {target_date} ({len(events)})")
    formatted = []
    for ev in events:
        start_display = ev['start'][11:16] if 'T' in ev['start'] else ev['start']
        formatted.append({
            'Time': start_display,
            'Title': ev['summary'][:30],
            'Location': ev.get('location', '')[:20],
            'Online': "🎥 Meet" if ev.get('meet_link') else "",
            'ID': ev['id']
        })
    print(format_output(formatted, format_type=format))


@calendar.command('by-range')
@click.option('--start-date', required=True, help='Start date (YYYY-MM-DD)')
@click.option('--end-date', required=True, help='End date (YYYY-MM-DD)')
@click.option('--calendar-id', default='primary', help='Calendar ID (default: primary)')
@click.option('--timezone', 'timezone_str', default=None, help='Timezone')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def calendar_by_range(ctx, start_date, end_date, calendar_id, timezone_str, format):
    """List events across a date range"""
    calendar_id = _resolve_calendar_id(calendar_id, ctx, default='primary')
    service = CalendarService(ctx.obj['oauth_manager'])
    events = service.get_events_by_date_range(start_date=start_date, end_date=end_date, calendar_id=calendar_id, timezone_str=timezone_str)
    
    if not events:
        print_info(f"No events found between {start_date} and {end_date}.")
        return
    
    print_header(f"📅 EVENTS ({start_date} to {end_date})")
    formatted = []
    for ev in events:
        formatted.append({
            'Start': ev['start'][:16].replace('T', ' '),
            'Title': ev['summary'][:30],
            'Location': ev.get('location', '')[:20],
            'Online': "🎥 Meet" if ev.get('meet_link') else "",
            'ID': ev['id']
        })
    print(format_output(formatted, format_type=format))


@calendar.command('view-calendar')
@click.argument('calendar_id', default='primary')
@click.pass_context
def calendar_view_calendar(ctx, calendar_id):
    """View details of a specific calendar"""
    calendar_id = _resolve_calendar_id(calendar_id, ctx, default='primary')
    service = CalendarService(ctx.obj['oauth_manager'])
    cal = service.get_calendar(calendar_id)
    if not cal:
        print_error(f"Calendar '{calendar_id}' not found.")
        return
    print_header(f"📅 Calendar: {cal.get('summary')}")
    print_key_value_pairs(dict([
        ("Calendar ID", cal.get('id')),
        ("Name", cal.get('summary')),
        ("Description", cal.get('description') or 'None'),
        ("Timezone", cal.get('timezone')),
        ("Location", cal.get('location') or 'None'),
        ("Access Role", cal.get('access_role', 'reader')),
        ("Primary", "Yes" if cal.get('primary') else "No"),
    ]))


@calendar.command('update-calendar')
@click.argument('calendar_id')
@click.option('--summary', help='New calendar name/summary')
@click.option('--description', help='New calendar description')
@click.option('--timezone', help='New calendar timezone')
@click.option('--location', help='New calendar location')
@click.pass_context
def calendar_update_calendar(ctx, calendar_id, summary, description, timezone, location):
    """Update calendar metadata"""
    calendar_id = _resolve_calendar_id(calendar_id, ctx, default='primary')
    service = CalendarService(ctx.obj['oauth_manager'])
    success = service.update_calendar(
        calendar_id=calendar_id,
        summary=summary,
        description=description,
        time_zone=timezone,
        location=location
    )
    if success:
        print_success(f"Calendar '{calendar_id}' updated successfully.")
    else:
        print_error(f"Failed to update calendar '{calendar_id}'.")


@calendar.command('test-connection')
@click.pass_context
def calendar_test_connection(ctx):
    """Test connection to Google Calendar API"""
    service = CalendarService(ctx.obj['oauth_manager'])
    res = service.test_connection()
    if res.get('connected'):
        print_success("✓ Calendar API connection test successful!")
        print_info(f"Available calendars check: {res.get('count', 0)} returned")
    else:
        print_error("✗ Calendar API connection failed.")
        print_error(f"Details: {res.get('error')}")


@calendar.command('instances')
@click.argument('event_id')
@click.option('--calendar-id', default='primary', help='Calendar ID (default: primary)')
@click.option('--time-min', help='Start of range (YYYY-MM-DD)')
@click.option('--time-max', help='End of range (YYYY-MM-DD)')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def calendar_instances(ctx, event_id, calendar_id, time_min, time_max, format):
    """List instances of a recurring event"""
    calendar_id = _resolve_calendar_id(calendar_id, ctx, default='primary')
    time_min_dt = None
    time_max_dt = None
    if time_min:
        try:
            time_min_dt = datetime.strptime(time_min, '%Y-%m-%d')
        except ValueError:
            print_error("Invalid --time-min format. Use YYYY-MM-DD")
            return
    if time_max:
        try:
            time_max_dt = datetime.strptime(time_max, '%Y-%m-%d')
        except ValueError:
            print_error("Invalid --time-max format. Use YYYY-MM-DD")
            return
    service = CalendarService(ctx.obj['oauth_manager'])
    instances = service.list_event_instances(
        event_id=event_id,
        calendar_id=calendar_id,
        time_min=time_min_dt,
        time_max=time_max_dt
    )
    if not instances:
        print_info("No instances found")
        return
    formatted_instances = []
    for inst in instances:
        formatted_instances.append({
            'ID': inst['id'],
            'Summary': inst['summary'],
            'Start': inst['start'][:16],
            'End': inst['end'][:16],
            'Status': inst['status'],
        })
    output = format_output(formatted_instances, format_type=format)
    print(output)


@calendar.command('create-event')
@click.argument('calendar_id_arg', required=False)
@click.option('--title', help='Event title')
@click.option('--start', help='Start time (YYYY-MM-DD HH:MM)')
@click.option('--end', help='End time (YYYY-MM-DD HH:MM)')
@click.option('--description', default='', help='Event description')
@click.option('--location', default='', help='Event location')
@click.option('--daily', is_flag=True, help='Create a daily recurring event')
@click.option('--weekly', is_flag=True, help='Create a weekly recurring event')
@click.option('--monthly', is_flag=True, help='Create a monthly recurring event')
@click.option('--weekday', multiple=True, help='Weekdays for weekly recurrence, e.g. mon-fri or mon tue')
@click.option('--day', type=int, help='Day of month for monthly recurrence')
@click.option('--rrule', 'rrule_str', help='Custom RRULE (RFC 5545)')
@click.option('--until', 'until_str', help='Recurrence end date (YYYY-MM-DD)')
@click.option('--count', type=int, help='Number of occurrences for recurrence')
@click.option('--timezone', 'timezone_str', help='Event timezone, e.g. Europe/Berlin')
@click.option('--remind', 'remind_offsets', multiple=True, help='Reminder offsets before start, e.g. 30m, 1h, 1d')
@click.option('--notify', 'notify_types', multiple=True, type=click.Choice(['cli', 'desktop', 'email']), help='Notification channels for reminders')
@click.option('--no-extra-prompts', is_flag=True, help='Skip extra prompts for description and location')
@click.option('--calendar-id', 'calendar_id_opt', default=None, help='Calendar ID (default: primary)')
@click.pass_context
def calendar_create(ctx, calendar_id_arg, title, start, end, description, location, daily, weekly, monthly, weekday, day, rrule_str, until_str, count, timezone_str, remind_offsets, notify_types, no_extra_prompts, calendar_id_opt):
    """Create a new event"""
    if not title:
        title = click.prompt("Event Title")
    
    if not start:
        start = click.prompt("Start time (YYYY-MM-DD HH:MM)")
        
    if not end:
        # Suggest 1 hour duration by default
        try:
            start_dt = datetime.strptime(start, '%Y-%m-%d %H:%M')
            default_end = (start_dt + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')
            end = click.prompt("End time (YYYY-MM-DD HH:MM)", default=default_end)
        except ValueError:
            end = click.prompt("End time (YYYY-MM-DD HH:MM)")
    
    if not description and not no_extra_prompts and click.confirm("Add description?", default=False):
        description = click.prompt("Description")
        
    if not location and not no_extra_prompts and click.confirm("Add location?", default=False):
        location = click.prompt("Location")
    
    try:
        start_time = datetime.strptime(start, '%Y-%m-%d %H:%M')
        end_time = datetime.strptime(end, '%Y-%m-%d %H:%M')
        if end_time <= start_time:
            print_error("End time must be after start time.")
            return
    except ValueError:
        print_error("Invalid datetime format. Use: YYYY-MM-DD HH:MM")
        return
    recurrence, recurrence_error = _build_recurrence(daily, weekly, monthly, weekday, day, rrule_str, until_str, count)
    if recurrence_error:
        print_error(recurrence_error)
        return
    config_manager = ctx.obj.get('config_manager')
    default_timezone = 'UTC'
    if config_manager:
        default_timezone = config_manager.get('calendar.default_timezone', 'UTC')
    timezone_value = timezone_str or default_timezone
    raw_id = calendar_id_opt or calendar_id_arg
    calendar_id = _resolve_calendar_id(raw_id.strip() if raw_id else 'primary', ctx, default='primary')
    service = CalendarService(ctx.obj['oauth_manager'])

    minutes_list = []
    notify_cli = False
    notify_desktop = False
    notify_email = False
    if remind_offsets and config_manager:
        for raw in remind_offsets:
            minutes = _parse_reminder_offset(raw)
            if minutes is None:
                print_warning(f"Ignoring invalid reminder offset: {raw}")
                continue
            if minutes not in minutes_list:
                minutes_list.append(minutes)
        if minutes_list:
            channels = list(notify_types) if notify_types else []
            notify_cli = not channels or 'cli' in channels
            notify_desktop = 'desktop' in channels
            notify_email = 'email' in channels
    if recurrence:
        time_min = start_time
        time_max = None
        if until_str:
            try:
                until_date = datetime.strptime(until_str, '%Y-%m-%d')
                time_max = until_date + timedelta(days=1)
            except ValueError:
                time_max = None
        elif count and count > 1:
            duration = end_time - start_time
            if daily:
                time_max = start_time + timedelta(days=count - 1) + duration
            elif weekly:
                time_max = start_time + timedelta(weeks=count - 1) + duration
        if not time_max:
            time_max = start_time + timedelta(days=7)
        busy_info = service.get_free_busy(time_min, time_max, [calendar_id])
        calendars_busy = busy_info.get('calendars', {})
        if calendars_busy:
            busy_periods = calendars_busy.get(calendar_id, {}).get('busy', [])
            if busy_periods:
                print_warning("Conflicts detected with existing events during the recurrence range")
    event_id = service.create_event(
        calendar_id=calendar_id,
        summary=title,
        start_time=start_time,
        end_time=end_time,
        description=description,
        location=location,
        time_zone=timezone_value,
        recurrence=recurrence,
        reminders_minutes=minutes_list or None,
    )
    
    if event_id:
        event = service.get_event(event_id, calendar_id=calendar_id)
        if event:
            config_manager = ctx.obj.get('config_manager')
            if minutes_list and config_manager:
                reminder_service = ReminderService(config_manager)
                reminder_service.schedule_reminders(
                    event=event,
                    calendar_id=calendar_id,
                    offsets_minutes=minutes_list,
                    notify_cli=notify_cli,
                    notify_desktop=notify_desktop,
                    notify_email=notify_email,
                )
            print_success(f"Event created: {event.get('id')}")
            print(f"Title: {event.get('summary')}")
            print(f"Start: {event.get('start')}")
            print(f"End: {event.get('end')}")
        else:
            print_success(f"Event created successfully (ID: {event_id})")
    else:
        print_error("Failed to create event")


@calendar.command('update')
@click.argument('event_id', required=False)
@click.option('--title', help='New event title')
@click.option('--start', help='New start time (YYYY-MM-DD HH:MM)')
@click.option('--end', help='New end time (YYYY-MM-DD HH:MM)')
@click.option('--description', help='New event description')
@click.option('--location', help='New event location')
@click.option('--daily', is_flag=True, help='Change to daily recurring event')
@click.option('--weekly', is_flag=True, help='Change to weekly recurring event')
@click.option('--monthly', is_flag=True, help='Change to monthly recurring event')
@click.option('--weekday', multiple=True, help='Weekdays for weekly recurrence, e.g. mon-fri or mon tue')
@click.option('--day', type=int, help='Day of month for monthly recurrence')
@click.option('--rrule', 'rrule_str', help='Custom RRULE (RFC 5545)')
@click.option('--until', 'until_str', help='Recurrence end date (YYYY-MM-DD)')
@click.option('--count', type=int, help='Number of occurrences for recurrence')
@click.option('--timezone', 'timezone_str', help='Event timezone, e.g. Europe/Berlin')
@click.option('--no-recurrence', is_flag=True, help='Remove recurrence from the event')
@click.option('--remind', 'remind_offsets', multiple=True, help='Additional reminders before start, e.g. 30m, 1h, 1d')
@click.option('--notify', 'notify_types', multiple=True, type=click.Choice(['cli', 'desktop', 'email']), help='Notification channels for reminders')
@click.option('--calendar-id', default='primary', help='Calendar ID (default: primary)')
@click.pass_context
def calendar_update(ctx, event_id, title, start, end, description, location, daily, weekly, monthly, weekday, day, rrule_str, until_str, count, timezone_str, no_recurrence, remind_offsets, notify_types, calendar_id):
    """Update an existing event"""
    from datetime import datetime
    
    if not event_id:
        from .ui.interactive_calendar import run_calendar_update_flow
        service = CalendarService(ctx.obj['oauth_manager'])
        config_manager = ctx.obj.get('config_manager')
        run_calendar_update_flow(service, config_manager)
        return
        
    calendar_id = _resolve_calendar_id(calendar_id, ctx, default='primary')
    service = CalendarService(ctx.obj['oauth_manager'])
    
    # Resolve event_id in case it is a displayed number, title match, or direct ID
    events = service.list_events(calendar_id=calendar_id, max_results=100)
    try:
        resolved_event = CalendarEventResolver.resolve(event_id, events, service, calendar_id)
        real_event_id = resolved_event.get('id', event_id)
    except Exception:
        real_event_id = event_id

    event = service.get_event(real_event_id, calendar_id)
    if not event:
        print_error(f"Event '{event_id}' not found")
        return
    event_id = real_event_id

    print_info(f"Updating event: {event.get('summary')}")
    
    # Interactive mode if no options provided
    if not any([title, start, end, description, location]):
        if click.confirm(f"Update title? (Current: {event.get('summary')})", default=False):
            title = click.prompt("New Title")
        
        if click.confirm(f"Update start time? (Current: {event.get('start')})", default=False):
            start = click.prompt("New Start time (YYYY-MM-DD HH:MM)")
            
        if click.confirm(f"Update end time? (Current: {event.get('end')})", default=False):
            end = click.prompt("New End time (YYYY-MM-DD HH:MM)")
            
        if click.confirm(f"Update description?", default=False):
            description = click.prompt("New Description")
            
        if click.confirm(f"Update location?", default=False):
            location = click.prompt("New Location")

    start_time = None
    if start:
        try:
            start_time = datetime.strptime(start, '%Y-%m-%d %H:%M')
        except ValueError:
            print_error("Invalid start time format. Use: YYYY-MM-DD HH:MM")
            return
    end_time = None
    if end:
        try:
            end_time = datetime.strptime(end, '%Y-%m-%d %H:%M')
        except ValueError:
            print_error("Invalid end time format. Use: YYYY-MM-DD HH:MM")
            return
    if start_time and end_time and end_time <= start_time:
        print_error("End time must be after start time.")
        return
    recurrence = None
    if no_recurrence:
        recurrence = []
    else:
        recurrence, recurrence_error = _build_recurrence(daily, weekly, monthly, weekday, day, rrule_str, until_str, count)
        if recurrence_error:
            print_error(recurrence_error)
            return
    config_manager = ctx.obj.get('config_manager')
    timezone_value = None
    if timezone_str:
        timezone_value = timezone_str
    elif config_manager:
        timezone_value = config_manager.get('calendar.default_timezone', 'UTC')
    success = service.update_event(
        event_id=event_id,
        calendar_id=calendar_id,
        summary=title,
        start_time=start_time,
        end_time=end_time,
        description=description,
        location=location,
        time_zone=timezone_value,
        recurrence=recurrence
    )
    
    if success:
        if remind_offsets and config_manager:
            updated_event = service.get_event(event_id, calendar_id)
            if updated_event:
                minutes_list = []
                for raw in remind_offsets:
                    minutes = _parse_reminder_offset(raw)
                    if minutes is None:
                        print_warning(f"Ignoring invalid reminder offset: {raw}")
                        continue
                    if minutes not in minutes_list:
                        minutes_list.append(minutes)
                if minutes_list:
                    channels = list(notify_types) if notify_types else []
                    notify_cli = not channels or 'cli' in channels
                    notify_desktop = 'desktop' in channels
                    notify_email = 'email' in channels
                    reminder_service = ReminderService(config_manager)
                    reminder_service.schedule_reminders(
                        event=updated_event,
                        calendar_id=calendar_id,
                        offsets_minutes=minutes_list,
                        notify_cli=notify_cli,
                        notify_desktop=notify_desktop,
                        notify_email=notify_email
                    )
        print_success(f"Event updated: {event_id}")
    else:
        print_error("Failed to update event")


@calendar.command('delete')
@click.argument('event_id', required=False)
@click.option('--calendar-id', default='primary', help='Calendar ID (default: primary)')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation')
@click.pass_context
def calendar_delete(ctx, event_id, calendar_id, yes):
    """Delete an event or calendar: hermes calendar delete [REF]"""
    from .ui.human_flows import run_calendar_delete_flow
    from .services.calendar_resolver import CalendarEventResolver
    calendar_id = _resolve_calendar_id(calendar_id, ctx, default='primary')
    cache_manager = ctx.obj.get('cache_manager')
    service = CalendarService(ctx.obj['oauth_manager'], cache_manager)
    cfg_mgr = ctx.obj.get('config_manager')

    if not event_id:
        run_calendar_delete_flow(service, cfg_mgr, calendar_ref=calendar_id)
        return

    calendars = service.list_calendars()
    is_calendar = any(cal.get('id') == event_id for cal in calendars)

    if is_calendar:
        if not yes and not click.confirm(f"Are you sure you want to delete calendar '{event_id}'?", default=False):
            print_info("Deletion cancelled")
            return

        success = service.delete_calendar(event_id)
        if success:
            print_success(f"Calendar deleted: {event_id}")
        else:
            print_error("Failed to delete calendar")
        return

    # Resolve event reference (number, title, ID)
    events = service.list_events(calendar_id=calendar_id, max_results=100)
    try:
        resolved = CalendarEventResolver.resolve(event_id, events, service, calendar_id)
        real_event_id = resolved.get('id', event_id)
        summary = resolved.get('summary', 'Unknown Event')
    except Exception:
        real_event_id = event_id
        summary = event_id
    
    if not yes and not click.confirm(f"Are you sure you want to delete event '{summary}'?", default=False):
        print_info("Deletion cancelled")
        return

    success = service.delete_event(real_event_id, calendar_id)
    
    if success:
        print_success(f"Event deleted: {real_event_id}")
    else:
        print_error("Failed to delete event")


@calendar.command('search')
@click.argument('query')
@click.option('--calendar-id', default='primary', help='Calendar ID (default: primary')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def calendar_search(ctx, query, calendar_id, format):
    """Search events"""
    calendar_id = _resolve_calendar_id(calendar_id, ctx, default='primary')
    cache_manager = ctx.obj.get('cache_manager')
    service = CalendarService(ctx.obj['oauth_manager'], cache_manager)
    events = service.search_events(query, calendar_id)
    
    if not events:
        print_info(f"No events found for: {query}")
        return
    
    # Format events for display
    formatted_events = []
    for event in events:
        formatted_events.append({
            'ID': event['id'],
            'Title': event['summary'][:30] + ('...' if len(event['summary']) > 30 else ''),
            'Start': event['start'][:16],
            'End': event['end'][:16],
            'Description': event['description'][:30] + ('...' if len(event['description']) > 30 else ''),
        })
    
    output = format_output(formatted_events, format_type=format)
    print(output)


calendar.add_command(calendar_create, name='create')
calendar.add_command(calendar_list_events, name='events')


@calendar.command('insights')
@click.option('--days', default=7, help='Number of days to analyze')
@click.pass_context
def calendar_insights(ctx, days):
    """Get AI-powered calendar insights"""
    cache_manager = ctx.obj.get('cache_manager')
    service = AdvancedCalendarService(ctx.obj['oauth_manager'], cache_manager)
    
    insights = service.get_smart_schedule_insights(days)
    
    if not insights:
        print_info("No calendar insights available")
        return
    
    print_header("🧠 AI Calendar Insights")
    print_key_value_pairs({
        'Total Events': str(insights.get('total_events', 0)),
        'Busiest Day': insights.get('busiest_day', 'N/A'),
        'Peak Hour': f"{insights.get('peak_hour', 'N/A')}:00" if insights.get('peak_hour') else 'N/A',
        'Meeting Density': f"{insights.get('meeting_density', 0)} events/day",
        'Focus Time Available': f"{insights.get('focus_time_available', 0)} hours",
        'Total Meeting Hours': f"{insights.get('total_meeting_hours', 0)} hours"
    })
    
    if insights.get('recommendations'):
        print_section("AI Recommendations")
        for i, rec in enumerate(insights['recommendations'], 1):
            print(f"{i}. {rec}")


@calendar.command('smart-create')
@click.argument('title')
@click.option('--description', default='', help='Event description')
@click.option('--duration', default=60, help='Duration in minutes')
@click.option('--attendees', help='Comma-separated list of attendee emails')
@click.option('--no-optimal', is_flag=True, help='Skip optimal time finding')
@click.pass_context
def calendar_smart_create(ctx, title, description, duration, attendees, no_optimal):
    """Create event with AI-powered time suggestions"""
    cache_manager = ctx.obj.get('cache_manager')
    service = AdvancedCalendarService(ctx.obj['oauth_manager'], cache_manager)
    
    attendee_list = [email.strip() for email in attendees.split(',')] if attendees else None
    
    event_id = service.create_smart_event(
        title=title,
        description=description,
        duration_minutes=duration,
        attendees=attendee_list,
        find_optimal_time=not no_optimal
    )
    
    if event_id:
        print_success(f"Smart event created successfully")
        print_info(f"Event ID: {event_id}")
    else:
        print_error("Failed to create smart event")


@calendar.command('analytics')
@click.option('--days', default=30, help='Number of days to analyze')
@click.pass_context
def calendar_analytics(ctx, days):
    """Get comprehensive calendar analytics"""
    cache_manager = ctx.obj.get('cache_manager')
    service = AdvancedCalendarService(ctx.obj['oauth_manager'], cache_manager)
    
    analytics = service.get_calendar_analytics(days)
    
    if not analytics:
        print_info("No calendar analytics available")
        return
    
    print_header("📊 Calendar Analytics")
    print_key_value_pairs({
        'Total Events': str(analytics.get('total_events', 0)),
        'Period Days': str(analytics.get('period_days', 0)),
        'Total Hours': f"{analytics.get('total_hours', 0)} hours",
        'Avg Events/Day': f"{analytics.get('avg_events_per_day', 0)}",
        'Avg Hours/Day': f"{analytics.get('avg_hours_per_day', 0)}",
        'Recurring Events': str(analytics.get('recurring_events', 0)),
        'Events with Attendees': str(analytics.get('events_with_attendees', 0)),
        'Productivity Score': f"{analytics.get('productivity_score', 0)}/100"
    })
    
    if analytics.get('insights'):
        print_section("AI Insights")
        for insight in analytics['insights']:
            print(f"💡 {insight}")


@cli.group()
def reminders():
    """Reminder scheduler commands"""
    pass


@reminders.command('run')
@click.option('--once', is_flag=True, help='Process due reminders once and exit')
@click.option('--interval', default=60, show_default=True, help='Polling interval in seconds when not using --once')
@click.option('--max', 'max_items', default=50, show_default=True, help='Maximum reminders to process per iteration')
@click.pass_context
def reminders_run(ctx, once, interval, max_items):
    """Run reminder dispatcher (for cron or background use)"""
    config_manager = ctx.obj['config_manager']
    reminder_service = ReminderService(config_manager)
    calendar_service = CalendarService(ctx.obj['oauth_manager'])

    def _process():
        now = datetime.utcnow()
        due = reminder_service.get_due_reminders(now=now, limit=max_items)
        if not due:
            return
        for item in due:
            event = calendar_service.get_event(
                event_id=item['event_id'],
                calendar_id=item['calendar_id'],
            )
            if not event:
                reminder_service.mark_failed(item['id'], "Event not found")
                continue
            summary = event.get('summary', 'No title')
            reminder_service.dispatch_reminder(item, summary)

    if once:
        _process()
    else:
        try:
            while True:
                _process()
                time.sleep(interval)
        except KeyboardInterrupt:
            pass


@cli.group()
def booking():
    """Booking link commands"""
    pass


@booking.command('create')
@click.option('--duration', required=True, help='Duration per meeting, e.g. 30m or 1h')
@click.option('--availability', required=True, help='Availability window, e.g. \"mon-fri 09:00-17:00\"')
@click.option('--buffer', default='0m', show_default=True, help='Buffer time between bookings, e.g. 15m')
@click.option('--expires', 'expires_str', help='Expiration date (YYYY-MM-DD)')
@click.option('--max-per-day', type=int, help='Maximum bookings per day')
@click.option('--timezone', 'timezone_str', help='Timezone, e.g. Europe/Berlin')
@click.option('--calendar-id', default='primary', help='Calendar ID (default: primary)')
@click.pass_context
def booking_create(ctx, duration, availability, buffer, expires_str, max_per_day, timezone_str, calendar_id):
    """Create a secure booking link"""
    duration_minutes = _parse_reminder_offset(duration)
    if duration_minutes is None:
        print_error("Invalid --duration. Use values like 30m or 1h")
        return
    buffer_minutes = _parse_reminder_offset(buffer)
    if buffer_minutes is None:
        print_error("Invalid --buffer. Use values like 15m or 30m")
        return
    config_manager = ctx.obj['config_manager']
    config = config_manager.config
    tz_value = timezone_str or config.calendar.default_timezone
    calendar_id_value = calendar_id or config.calendar.default_calendar
    calendar_service = CalendarService(ctx.obj['oauth_manager'])
    booking_service = BookingService(config_manager, calendar_service)
    try:
        link = booking_service.create_link(
            duration_minutes=duration_minutes,
            availability=availability,
            buffer_minutes=buffer_minutes,
            expires_at=expires_str,
            max_per_day=max_per_day,
            time_zone=tz_value,
            calendar_id=calendar_id_value,
        )
    except ValueError as e:
        print_error(str(e))
        return
    print_success("Booking link created")
    print_info(f"Token: {link.token}")
    print_info(f"Shareable command: hermes booking book --token {link.token} --start \"YYYY-MM-DD HH:MM\"")


@booking.command('book')
@click.argument('token')
@click.option('--start', 'start_str', required=True, help='Requested start time (e.g. 2026-03-25 14:00) in booking timezone')
@click.pass_context
def booking_book(ctx, token, start_str):
    """Book a meeting using a booking link token"""
    config_manager = ctx.obj['config_manager']
    calendar_service = CalendarService(ctx.obj['oauth_manager'])
    booking_service = BookingService(config_manager, calendar_service)
    booking_service.book(token=token, start_str=start_str)


@booking.command('revoke')
@click.argument('token')
@click.pass_context
def booking_revoke(ctx, token):
    """Revoke a booking link"""
    config_manager = ctx.obj['config_manager']
    calendar_service = CalendarService(ctx.obj['oauth_manager'])
    booking_service = BookingService(config_manager, calendar_service)
    if booking_service.revoke_link(token):
        print_success("Booking link revoked")
    else:
        print_error("Booking link not found")


@booking.command('quick')
@click.option('--title', default='Quick Meeting', help='Meeting title')
@click.option('--start', 'start_str', required=True, help='Start time (e.g. "2026-09-06 14:00")')
@click.option('--duration', default=30, type=int, help='Meeting duration in minutes (default: 30)')
@click.option('--attendee', 'attendees', multiple=True, help='Attendee email address')
@click.option('--description', default='', help='Meeting description')
@click.option('--location', default='', help='Meeting location')
@click.option('--online/--no-online', default=True, help='Generate Google Meet link (default: true)')
@click.option('--calendar-id', default='primary', help='Calendar ID (default: primary)')
@click.option('--timezone', 'timezone_str', default='UTC', help='Timezone')
@click.pass_context
def booking_quick(ctx, title, start_str, duration, attendees, description, location, online, calendar_id, timezone_str):
    """Quickly schedule a meeting with optional Google Meet link"""
    config_manager = ctx.obj['config_manager']
    calendar_service = CalendarService(ctx.obj['oauth_manager'])
    booking_service = BookingService(config_manager, calendar_service)
    
    try:
        from dateutil import parser as date_parser
        start_dt = date_parser.parse(start_str)
    except Exception:
        print_error("Invalid start time format. Use YYYY-MM-DD HH:MM")
        return
    
    res = booking_service.quick_meeting(
        title=title,
        start_time=start_dt,
        duration_minutes=duration,
        attendees=list(attendees) if attendees else None,
        description=description,
        location=location,
        is_online=online,
        calendar_id=calendar_id,
        time_zone=timezone_str
    )
    
    if res.get('success'):
        print_success(f"✓ Meeting created successfully!")
        print_header(f"📅 {res['title']}")
        pairs = [
            ("Event ID", res['event_id']),
            ("Start", res['start']),
            ("End", res['end']),
            ("Duration", f"{duration} minutes"),
            ("Calendar", calendar_id),
        ]
        if res.get('meet_uri'):
            pairs.append(("Google Meet", f"🎥 {res['meet_uri']}"))
            pairs.append(("Meeting Code", res.get('meet_code', '')))
        if res.get('attendees'):
            pairs.append(("Attendees", ", ".join(res['attendees'])))
        print_key_value_pairs(dict(pairs))
    else:
        print_error(f"Failed to create meeting: {res.get('error')}")


@booking.command('schedule')
@click.option('--title', required=True, help='Meeting title')
@click.option('--start', 'start_str', required=True, help='Start time (e.g. "2026-09-06 14:00")')
@click.option('--end', 'end_str', default=None, help='End time (optional)')
@click.option('--duration', default=30, type=int, help='Duration in minutes if end not specified')
@click.option('--attendee', 'attendees', multiple=True, help='Attendee email address')
@click.option('--description', default='', help='Meeting description')
@click.option('--location', default='', help='Location')
@click.option('--online/--no-online', default=True, help='Include Google Meet')
@click.option('--calendar-id', default='primary', help='Calendar ID')
@click.option('--timezone', 'timezone_str', default='UTC', help='Timezone')
@click.pass_context
def booking_schedule(ctx, title, start_str, end_str, duration, attendees, description, location, online, calendar_id, timezone_str):
    """Schedule a meeting with attendees and online meeting support"""
    config_manager = ctx.obj['config_manager']
    calendar_service = CalendarService(ctx.obj['oauth_manager'])
    booking_service = BookingService(config_manager, calendar_service)
    
    try:
        from dateutil import parser as date_parser
        start_dt = date_parser.parse(start_str)
        end_dt = date_parser.parse(end_str) if end_str else None
    except Exception:
        print_error("Invalid datetime format. Use YYYY-MM-DD HH:MM")
        return
    
    res = booking_service.schedule_meeting(
        title=title,
        start_time=start_dt,
        end_time=end_dt,
        duration_minutes=duration,
        attendees=list(attendees) if attendees else None,
        description=description,
        location=location,
        is_online=online,
        calendar_id=calendar_id,
        time_zone=timezone_str
    )
    
    if res.get('success'):
        print_success(f"✓ Meeting scheduled: {res['title']}")
        if res.get('meet_uri'):
            print_info(f"Google Meet Link: {res['meet_uri']}")
    else:
        print_error(f"Failed to schedule meeting: {res.get('error')}")


@booking.command('availability')
@click.option('--date', 'date_str', required=True, help='Target date (YYYY-MM-DD)')
@click.option('--start-hour', default=9, type=int, help='Earliest hour (0-23, default: 9)')
@click.option('--end-hour', default=17, type=int, help='Latest hour (0-23, default: 17)')
@click.option('--duration', default=30, type=int, help='Meeting duration in minutes (default: 30)')
@click.option('--calendar-id', 'calendar_ids', multiple=True, help='Calendar ID(s) to check')
@click.option('--timezone', 'timezone_str', default='UTC', help='Timezone')
@click.pass_context
def booking_availability(ctx, date_str, start_hour, end_hour, duration, calendar_ids, timezone_str):
    """Find available time slots using actual Google Calendar free/busy data"""
    config_manager = ctx.obj['config_manager']
    calendar_service = CalendarService(ctx.obj['oauth_manager'])
    booking_service = BookingService(config_manager, calendar_service)
    
    cal_list = list(calendar_ids) if calendar_ids else ['primary']
    slots = booking_service.find_available_time(
        target_date=date_str,
        start_hour=start_hour,
        end_hour=end_hour,
        duration_minutes=duration,
        calendar_ids=cal_list,
        time_zone=timezone_str
    )
    
    if not slots:
        print_warning(f"No available {duration}-minute slots found between {start_hour}:00 and {end_hour}:00 on {date_str}.")
        return
    
    print_header(f"📅 AVAILABLE TIME SLOTS ON {date_str} ({len(slots)} found)")
    for i, s in enumerate(slots, 1):
        print(f"  [{i}] {s['display']}")


@booking.command('reschedule')
@click.argument('event_id')
@click.option('--start', 'start_str', required=True, help='New start time (e.g. "2026-09-06 15:00")')
@click.option('--end', 'end_str', default=None, help='New end time (optional)')
@click.option('--duration', default=None, type=int, help='New duration in minutes (optional)')
@click.option('--calendar-id', default='primary', help='Calendar ID')
@click.option('--timezone', 'timezone_str', default=None, help='Timezone')
@click.pass_context
def booking_reschedule(ctx, event_id, start_str, end_str, duration, calendar_id, timezone_str):
    """Reschedule an existing meeting, preserving Google Meet link"""
    config_manager = ctx.obj['config_manager']
    calendar_service = CalendarService(ctx.obj['oauth_manager'])
    booking_service = BookingService(config_manager, calendar_service)
    
    try:
        from dateutil import parser as date_parser
        start_dt = date_parser.parse(start_str)
        end_dt = date_parser.parse(end_str) if end_str else None
    except Exception:
        print_error("Invalid datetime format. Use YYYY-MM-DD HH:MM")
        return
    
    res = booking_service.reschedule_meeting(
        event_id=event_id,
        new_start=start_dt,
        new_end=end_dt,
        duration_minutes=duration,
        calendar_id=calendar_id,
        time_zone=timezone_str
    )
    
    if res.get('success'):
        print_success(f"✓ Meeting rescheduled successfully!")
        print_info(f"New timing: {res['start']} -> {res['end']}")
        if res.get('meet_link'):
            print_info(f"Google Meet: {res['meet_link']}")
    else:
        print_error(f"Failed to reschedule meeting: {res.get('error')}")


@booking.command('cancel')
@click.argument('event_id')
@click.option('--calendar-id', default='primary', help='Calendar ID')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
@click.pass_context
def booking_cancel(ctx, event_id, calendar_id, yes):
    """Cancel a meeting and delete it from Google Calendar"""
    if not yes:
        if not click.confirm(f"Are you sure you want to cancel and delete meeting '{event_id}'?"):
            print_info("Cancelled.")
            return
    
    config_manager = ctx.obj['config_manager']
    calendar_service = CalendarService(ctx.obj['oauth_manager'])
    booking_service = BookingService(config_manager, calendar_service)
    
    if booking_service.cancel_meeting(event_id, calendar_id=calendar_id):
        print_success(f"✓ Meeting '{event_id}' cancelled and removed from calendar.")
    else:
        print_error(f"Failed to cancel meeting '{event_id}'.")


@cli.command('today')
@click.option('--calendar-id', default='primary', help='Calendar ID (default: primary)')
@click.pass_context
def cli_today(ctx, calendar_id):
    """Developer Quick Action: Show today's schedule and next event"""
    service = CalendarService(ctx.obj['oauth_manager'])
    events = service.get_today_events(calendar_id=calendar_id)
    
    now = datetime.now(tz.tzlocal() or tz.UTC)
    print_header("📅 TODAY'S SCHEDULE")
    
    if not events:
        print_info("No events scheduled for today.")
        return
    
    next_event = None
    next_diff_mins = None
    
    for ev in events:
        start_str = ev['start']
        time_part = start_str[11:16] if 'T' in start_str else "All Day"
        meet_tag = f" (🎥 {ev['meet_link']})" if ev.get('meet_link') else ""
        print(f"  {Fore.CYAN}{time_part:<8}{Style.RESET_ALL} {ev['summary']}{Fore.LIGHTBLUE_EX}{meet_tag}{Style.RESET_ALL}")
        
        if 'T' in start_str:
            try:
                from dateutil import parser as date_parser
                ev_dt = date_parser.parse(start_str)
                if ev_dt.tzinfo is None:
                    ev_dt = ev_dt.replace(tzinfo=tz.tzlocal() or tz.UTC)
                diff = (ev_dt - now).total_seconds() / 60
                if diff > 0 and (next_diff_mins is None or diff < next_diff_mins):
                    next_diff_mins = diff
                    next_event = ev
            except Exception:
                pass
    
    print()
    if next_event:
        print(f"{Fore.GREEN}▶ NEXT EVENT:{Style.RESET_ALL} {next_event['summary']} (Starts in {int(next_diff_mins)} minutes)")
        if next_event.get('meet_link'):
            print(f"  {Fore.LIGHTCYAN_EX}Meet Link: {next_event['meet_link']}{Style.RESET_ALL}")


@cli.command('next')
@click.option('--calendar-id', default='primary', help='Calendar ID (default: primary)')
@click.pass_context
def cli_next(ctx, calendar_id):
    """Developer Quick Action: Show the immediate next event and countdown"""
    service = CalendarService(ctx.obj['oauth_manager'])
    upcoming = service.get_upcoming_events(calendar_id=calendar_id, limit=5)
    
    now = datetime.now(tz.tzlocal() or tz.UTC)
    next_ev = None
    diff_mins = None
    
    for ev in upcoming:
        if 'T' in ev['start']:
            try:
                from dateutil import parser as date_parser
                ev_dt = date_parser.parse(ev['start'])
                if ev_dt.tzinfo is None:
                    ev_dt = ev_dt.replace(tzinfo=tz.tzlocal() or tz.UTC)
                diff = (ev_dt - now).total_seconds() / 60
                if diff >= -5:
                    next_ev = ev
                    diff_mins = diff
                    break
            except Exception:
                continue
    
    if not next_ev:
        print_info("No upcoming events found.")
        return
    
    print_header("▶ NEXT EVENT")
    print(f"{Fore.WHITE + Style.BRIGHT}{next_ev['summary']}{Style.RESET_ALL}")
    start_fmt = next_ev['start'][:16].replace('T', ' ')
    print(f"Time: {start_fmt}")
    
    if diff_mins is not None:
        if diff_mins > 0:
            print(f"{Fore.GREEN}Starts in {int(diff_mins)} minutes{Style.RESET_ALL}")
        elif diff_mins >= -5:
            print(f"{Fore.YELLOW}Happening now! (Started {int(-diff_mins)} minutes ago){Style.RESET_ALL}")
    
    if next_ev.get('location'):
        print(f"Location: {next_ev['location']}")
    if next_ev.get('meet_link'):
        print(f"{Fore.LIGHTCYAN_EX}🎥 Google Meet Available: {next_ev['meet_link']}{Style.RESET_ALL}")
    if next_ev.get('attendees'):
        print(f"👥 {len(next_ev['attendees'])} attendees")


@calendar.command('create-calendar')
@click.option('--summary', help='Calendar summary/title')
@click.option('--description', default='', help='Calendar description')
@click.option('--timezone', default='UTC', help='Timezone (default: UTC)')
@click.pass_context
def calendar_create_calendar(ctx, summary, description, timezone):
    """Create a new secondary calendar"""
    if not summary:
        summary = click.prompt("Calendar Name")
        
    if not description and click.confirm("Add description?", default=False):
        description = click.prompt("Description")

    service = CalendarService(ctx.obj['oauth_manager'])
    calendar = service.create_calendar(summary, description, timezone)
    
    if calendar:
        print_success(f"Created calendar: {calendar.get('id')}")
        print(f"Summary: {calendar.get('summary')}")
        print(f"Description: {calendar.get('description')}")
        print(f"Timezone: {calendar.get('timeZone')}")
    else:
        print_error("Failed to create calendar")


@calendar.command('create')
@click.option('--summary', help='Calendar summary/title')
@click.option('--description', default='', help='Calendar description')
@click.option('--timezone', default='UTC', help='Timezone (default: UTC)')
@click.pass_context
def calendar_create_simple(ctx, summary, description, timezone):
    """Create a new secondary calendar"""
    if not summary:
        summary = click.prompt("Calendar Name")
        
    if not description and click.confirm("Add description?", default=False):
        description = click.prompt("Description")

    service = CalendarService(ctx.obj['oauth_manager'])
    calendar = service.create_calendar(summary, description, timezone)
    
    if calendar:
        print_success(f"Created calendar: {calendar.get('id')}")
        print(f"Summary: {calendar.get('summary')}")
        print(f"Description: {calendar.get('description')}")
        print(f"Timezone: {calendar.get('timeZone')}")
    else:
        print_error("Failed to create calendar")


@calendar.command('list-calendars')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def calendar_list_calendars(ctx, format):
    """List all calendars"""
    cache_manager = ctx.obj.get('cache_manager')
    service = CalendarService(ctx.obj['oauth_manager'], cache_manager)
    calendars = service.list_calendars()
    
    if not calendars:
        print_info("No calendars found")
        return
    
    formatted_calendars = []
    for cal in calendars:
        formatted_calendars.append({
            'ID': cal['id'],
            'Summary': cal['summary'],
            'Description': cal['description'],
            'Primary': cal['primary'],
            'Role': cal['access_role']
        })
    
    output = format_output(formatted_calendars, format_type=format)
    print(output)


@cli.group()
def gmail():
    """Gmail commands"""
    pass


@gmail.command('list')
@click.option('--query', default='', help='Search query (Gmail search syntax)')
@click.option('--max-results', default=50, help='Maximum number of messages')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def gmail_list(ctx, query, max_results, format):
    """List email messages"""
    service = GmailService(ctx.obj['oauth_manager'])
    messages = service.list_messages(query=query, max_results=max_results)
    
    if not messages:
        print_info("No messages found")
        return
    
    formatted_messages = []
    for message in messages:
        formatted_messages.append({
            'ID': message['id'],
            'From': message['from'],
            'Subject': message['subject'][:28] + ('...' if len(message['subject']) > 28 else ''),
            'Date': message['date'][:11],
            'Snippet': message['snippet'][:30] + ('...' if len(message['snippet']) > 30 else ''),
        })
    
    output = format_output(formatted_messages, format_type=format, tablefmt='simple')
    print(output)


@gmail.command('get')
@click.argument('message_id')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def gmail_get(ctx, message_id, format):
    """Get a specific email message"""
    service = GmailService(ctx.obj['oauth_manager'])
    message = service.get_message(message_id)
    
    if not message:
        print_error("Message not found")
        return
    
    if format == 'json':
        print(format_output([message], format_type='json'))
    else:
        print(f"{Fore.WHITE}From:{Style.RESET_ALL} {message['from']}")
        print(f"{Fore.WHITE}To:{Style.RESET_ALL} {message['to']}")
        print(f"{Fore.WHITE}Subject:{Style.RESET_ALL} {message['subject']}")
        print(f"{Fore.WHITE}Date:{Style.RESET_ALL} {message['date']}")
        print(f"{Fore.WHITE}Labels:{Style.RESET_ALL} {', '.join(message['label_ids'])}")
        print("-" * 50)
        print(format_email_body(message['body']))


@gmail.command('send')
@click.option('--to', required=True, help='Recipient email address')
@click.option('--subject', required=True, help='Email subject')
@click.option('--body', required=True, help='Email body (plain text)')
@click.option('--cc', help='CC recipient')
@click.option('--bcc', help='BCC recipient')
@click.option('--html', help='HTML body (optional)')
@click.option('--attach', multiple=True, help='File attachments (can be used multiple times)')
@click.pass_context
def gmail_send(ctx, to, subject, body, cc, bcc, html, attach):
    """Send an email"""
    service = GmailService(ctx.obj['oauth_manager'])
    
    attachments = list(attach) if attach else None
    message_id = service.send_message(
        to=to,
        subject=subject,
        body=body,
        cc=cc,
        bcc=bcc,
        html_body=html,
        attachments=attachments
    )
    
    if message_id:
        print_success(f"Message sent: {message_id}")
    else:
        print_error("Failed to send message")


@gmail.command('search')
@click.argument('query')
@click.option('--max-results', default=50, help='Maximum number of messages')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def gmail_search(ctx, query, max_results, format):
    """Search messages using Gmail search syntax"""
    service = GmailService(ctx.obj['oauth_manager'])
    messages = service.search_messages(query, max_results=max_results)
    
    if not messages:
        print_info("No messages found")
        return
    
    formatted_messages = []
    for message in messages:
        formatted_messages.append({
            'ID': message['id'],
            'From': message['from'],
            'Subject': message['subject'][:28] + ('...' if len(message['subject']) > 28 else ''),
            'Date': message['date'][:11],
            'Snippet': message['snippet'][:30] + ('...' if len(message['snippet']) > 30 else ''),
        })
    
    output = format_output(formatted_messages, format_type=format, tablefmt='simple')
    print(output)


@gmail.command('delete')
@click.argument('message_id', required=False)
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation')
@click.pass_context
def gmail_delete(ctx, message_id=None, yes=False):
    """Delete a message: hermes gmail delete [REF]"""
    from .services.gmail_commands import _svc as _gmail_svc
    service = _gmail_svc(ctx) if (ctx.obj and '_gmail_svc' in ctx.obj) else GmailService(ctx.obj['oauth_manager'])
    cfg = ctx.obj.get('config_manager')
    if not message_id:
        from .ui.human_flows import run_gmail_delete_flow
        run_gmail_delete_flow(service, cfg)
        return

    msgs = service.list_messages(max_results=20)
    msg_list = msgs.get('messages', []) if isinstance(msgs, dict) else msgs
    from .services.resource_resolver import GlobalResourceResolver
    try:
        resolved = GlobalResourceResolver.resolve(message_id, msg_list, module='gmail', resource_type='Message', config_manager=cfg)
        real_id = resolved.get('id', message_id)
    except Exception:
        real_id = message_id

    if not yes and not click.confirm(f"Are you sure you want to delete message {real_id}?", default=False):
        print_info("Deletion cancelled")
        return

    success = service.delete_message(real_id)
    if success:
        print_success(f"Message deleted: {real_id}")
    else:
        print_error("Failed to delete message")


@gmail.command('info')
@click.argument('msg_ref', required=False)
@click.pass_context
def gmail_info(ctx, msg_ref=None):
    """View message details: hermes gmail info [REF]"""
    from .ui.human_flows import run_gmail_messages_flow
    from .services.gmail_commands import _svc as _gmail_svc
    service = _gmail_svc(ctx) if (ctx.obj and '_gmail_svc' in ctx.obj) else GmailService(ctx.obj['oauth_manager'])
    run_gmail_messages_flow(service, ctx.obj.get('config_manager'), msg_ref=msg_ref)


@gmail.command('alias')
@click.argument('target')
@click.argument('alias_name')
@click.pass_context
def gmail_alias(ctx, target, alias_name):
    """Create alias for a message: hermes gmail alias <TARGET> <ALIAS>"""
    from .services.resource_resolver import GlobalResourceResolver
    from .services.gmail_commands import _svc as _gmail_svc
    service = _gmail_svc(ctx) if (ctx.obj and '_gmail_svc' in ctx.obj) else GmailService(ctx.obj['oauth_manager'])
    msgs = service.list_messages(max_results=20)
    msg_list = msgs.get('messages', []) if isinstance(msgs, dict) else msgs
    cfg = ctx.obj.get('config_manager')
    ok, msg = GlobalResourceResolver.set_alias('gmail', target, alias_name, msg_list, cfg, resource_type="Message")
    if ok:
        print_success(f"Alias created: {msg}")
    else:
        print_error(f"Failed to create alias: {msg}")


@gmail.command('read')
@click.argument('message_id')
@click.pass_context
def gmail_read(ctx, message_id):
    """Mark message as read"""
    service = GmailService(ctx.obj['oauth_manager'])
    success = service.mark_as_read(message_id)
    
    if success:
        print_success(f"Message marked as read: {message_id}")
    else:
        print_error("Failed to mark message as read")


@gmail.command('unread')
@click.argument('message_id')
@click.pass_context
def gmail_unread(ctx, message_id):
    """Mark message as unread"""
    service = GmailService(ctx.obj['oauth_manager'])
    success = service.mark_as_unread(message_id)
    
    if success:
        print_success(f"Message marked as unread: {message_id}")
    else:
        print_error("Failed to mark message as unread")


@gmail.command('labels')
@click.option('--format', default=None, type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def gmail_labels(ctx, format):
    """List Gmail labels or launch interactive Labels menu"""
    if ctx.obj and '_gmail_svc' in ctx.obj:
        service = ctx.obj['_gmail_svc']
    else:
        service = GmailService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))

    if format:
        labels = service.get_labels()
        if not labels:
            print_info("No labels found")
            return

        # Format labels for display
        formatted_labels = []
        for label in labels:
            formatted_labels.append({
                'Name': label.get('name', ''),
                'Type': label.get('type', ''),
                'Total': label.get('messages_total', 0),
                'Unread': label.get('messages_unread', 0),
            })

        output = format_output(formatted_labels, format_type=format)
        print(output)
    else:
        from .ui.interactive_labels import run_labels_menu
        run_labels_menu(service)



@gmail.command('thread')
@click.argument('thread_id')
@click.pass_context
def gmail_thread(ctx, thread_id):
    """Get email thread"""
    service = GmailService(ctx.obj['oauth_manager'])
    thread = service.get_thread(thread_id)
    
    if not thread:
        print_error("Thread not found")
        return
    
    print(f"{Fore.WHITE}Thread ID:{Style.RESET_ALL} {thread['id']}")
    print(f"{Fore.WHITE}Messages:{Style.RESET_ALL} {len(thread['messages'])}")
    print("=" * 60)
    
    for i, message in enumerate(thread['messages'], 1):
        print(f"\n{Fore.WHITE}--- Message {i} ---{Style.RESET_ALL}")
        print(f"{Fore.WHITE}From:{Style.RESET_ALL} {message['from']}")
        print(f"{Fore.WHITE}To:{Style.RESET_ALL} {message['to']}")
        print(f"{Fore.WHITE}Subject:{Style.RESET_ALL} {message['subject']}")
        print(f"{Fore.WHITE}Date:{Style.RESET_ALL} {message['date']}")
        print("-" * 40)
        body_preview = message['body'][:500] + ('...' if len(message['body']) > 500 else '')
        print(format_email_body(body_preview))


def _get_gmail_service(ctx):
    if ctx.obj and '_gmail_svc' in ctx.obj:
        return ctx.obj['_gmail_svc']
    return GmailService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))


@gmail.command('forward')
@click.argument('message_id')
@click.option('--to', required=True, help='Recipient email address')
@click.option('--body', default='', help='Optional message body to prepend')
@click.pass_context
def gmail_forward(ctx, message_id, to, body):
    """Forward an email message"""
    service = _get_gmail_service(ctx)
    sent_id = service.forward_message(message_id=message_id, to=to, body=body)
    if sent_id:
        print_success(f"Message forwarded successfully (ID: {sent_id})")
    else:
        print_error("Failed to forward message")


@gmail.command('threads')
@click.option('--query', default='', help='Filter threads by query')
@click.option('--max-results', default=20, help='Maximum number of threads')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def gmail_threads(ctx, query, max_results, format):
    """List email thread conversations"""
    service = _get_gmail_service(ctx)
    threads = service.list_threads(query=query, max_results=max_results)
    if not threads:
        print_info("No threads found")
        return
    formatted = []
    for t in threads:
        snippet = t.get('snippet', '')
        if len(snippet) > 35:
            snippet = snippet[:35] + '...'
        formatted.append({
            'ID': t['id'],
            'Messages': len(t.get('messages', [])),
            'Snippet': snippet,
        })
    output = format_output(formatted, format_type=format)
    print(output)


@gmail.command('drafts')
@click.option('--max-results', default=20, help='Maximum number of drafts')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def gmail_drafts(ctx, max_results, format):
    """List email drafts"""
    service = _get_gmail_service(ctx)
    drafts = service.list_drafts(max_results=max_results)
    if not drafts:
        print_info("No drafts found")
        return
    formatted = []
    for d in drafts:
        subj = d.get('subject', '(No Subject)')
        if len(subj) > 30:
            subj = subj[:30] + '...'
        formatted.append({
            'Draft ID': d['id'],
            'To': d.get('to', ''),
            'Subject': subj,
        })
    output = format_output(formatted, format_type=format)
    print(output)


@gmail.command('profile')
@click.pass_context
def gmail_profile(ctx):
    """Display authenticated Gmail account profile dashboard"""
    service = _get_gmail_service(ctx)

    # ── Fetch all data via a single service call ──────────────────────────
    try:
        data = service.get_rich_profile()
    except Exception as exc:
        print_error(f"Failed to retrieve Gmail profile: {exc}")
        return

    from .utils.formatters import format_number

    if data.get('error') and not data.get('account', {}).get('email_address'):
        print_error(data['error'])

    SEP_MAJOR = "=" * 50
    SEP_MINOR = "-" * 50
    LABEL_W = 12          # fixed label column width (matches prompt spec)

    def _row(label: str, value: str) -> None:
        print(f"{Fore.CYAN}{label:<{LABEL_W}}{Style.RESET_ALL}: {value}")

    # ── Header ────────────────────────────────────────────────────────────
    print()
    print(Fore.WHITE + Style.BRIGHT + "✉ Gmail Profile")
    print(Fore.WHITE + SEP_MAJOR)

    # ── Account ───────────────────────────────────────────────────────────
    account = data.get('account', {})
    print()
    print(Fore.WHITE + Style.BRIGHT + "Account")
    print(Fore.WHITE + SEP_MINOR)
    display_name = account.get('display_name') or '-'
    email = account.get('email_address') or '-'
    _row("Name", display_name)
    _row("Email", email)

    # ── Mailbox ───────────────────────────────────────────────────────────
    mailbox = data.get('mailbox', {})
    print()
    print(Fore.WHITE + Style.BRIGHT + "Mailbox")
    print(Fore.WHITE + SEP_MINOR)
    _row("Messages", format_number(mailbox.get('messages_total')))
    _row("Threads",  format_number(mailbox.get('threads_total')))
    _row("Unread",   format_number(mailbox.get('unread')))
    _row("Drafts",   format_number(mailbox.get('drafts')))
    _row("Starred",  format_number(mailbox.get('starred')))

    # ── Labels ────────────────────────────────────────────────────────────
    labels = data.get('labels', {})
    print()
    print(Fore.WHITE + Style.BRIGHT + "Labels")
    print(Fore.WHITE + SEP_MINOR)
    _row("System", format_number(labels.get('system_count')))
    _row("Custom", format_number(labels.get('custom_count')))

    # ── Connection ────────────────────────────────────────────────────────
    conn = data.get('connection', {})
    api_status_raw = conn.get('api_status', 'connection_failed')
    if api_status_raw == 'connected':
        api_status_str = Fore.GREEN + "✓ Connected" + Style.RESET_ALL
    elif api_status_raw == 'auth_required':
        api_status_str = Fore.RED + "✗ Authentication Required" + Style.RESET_ALL
    else:
        api_status_str = Fore.RED + "✗ Connection Failed" + Style.RESET_ALL

    history_id = conn.get('history_id')
    history_id_str = str(history_id) if history_id else '-'

    print()
    print(Fore.WHITE + Style.BRIGHT + "Connection")
    print(Fore.WHITE + SEP_MINOR)
    print(f"{Fore.CYAN}{'API Status':<{LABEL_W}}{Style.RESET_ALL}: {api_status_str}")
    _row("History ID", history_id_str)

    # ── Footer / navigation ───────────────────────────────────────────────
    print()
    print(Fore.WHITE + SEP_MAJOR)
    print(Fore.WHITE + "[b] Back")
    print(Fore.WHITE + "[0] Exit")
    print()

    while True:
        try:
            choice = input("Select: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if choice == '0':
            import sys as _sys
            _sys.exit(0)
        elif choice in ('b', 'back'):
            break
        else:
            print(Fore.RED + "Invalid choice. Select [b] to go back or [0] to exit.")



@gmail.command('test-connection')
@click.pass_context
def gmail_test_connection(ctx):
    """Test connection to Gmail API"""
    service = _get_gmail_service(ctx)
    res = service.test_connection()
    if res.get('connected'):
        print_success("✓ Gmail API connection successful")
        print_key_value_pairs({
            'Account': res.get('email', 'Unknown'),
            'API Version': res.get('api_version', 'v1'),
            'Messages Total': str(res.get('messages_total', 0)),
            'Authenticated': 'Yes' if res.get('authenticated') else 'No',
        })
    else:
        print_error("✗ Gmail API connection failed")
        if 'error' in res:
            print_error(f"Error: {res['error']}")


# Mount subcommands from gmail_commands
gmail.add_command(gmail_reply, 'reply')
gmail.add_command(gmail_draft, 'draft')
gmail.add_command(gmail_label, 'label')
gmail.add_command(gmail_mark, 'mark')
gmail.add_command(gmail_filters, 'filters')
gmail.add_command(gmail_alert, 'alert')
gmail.add_command(gmail_digest, 'digest')
gmail.add_command(gmail_escalate, 'escalate')
gmail.add_command(gmail_schedule_summary, 'schedule-summary')


# Top-level developer quick shortcuts
@cli.command('unread')
@click.option('--max-results', default=10, help='Maximum number of unread emails to display')
@click.pass_context
def dev_unread(ctx, max_results):
    """Developer shortcut: View unread Gmail messages"""
    service = _get_gmail_service(ctx)
    messages = service.list_messages(query='is:unread', max_results=max_results)
    if not messages:
        print_success("✓ Inbox zero! No unread messages.")
        return
    print_header(f"📬 Unread Emails ({len(messages)})")
    formatted = []
    for m in messages:
        subj = m['subject'][:30] + ('...' if len(m['subject']) > 30 else '')
        sender = m['from'][:25] + ('...' if len(m['from']) > 25 else '')
        formatted.append({
            'ID': m['id'],
            'From': sender,
            'Subject': subj,
            'Date': m['date'][:16],
        })
    print(format_output(formatted, format_type='table'))


@cli.command('inbox')
@click.option('--max-results', default=10, help='Maximum number of inbox messages to display')
@click.pass_context
def dev_inbox(ctx, max_results):
    """Developer shortcut: View recent inbox messages"""
    service = _get_gmail_service(ctx)
    messages = service.list_messages(query='in:inbox', max_results=max_results)
    if not messages:
        print_info("Inbox is empty")
        return
    print_header(f"📥 Recent Inbox ({len(messages)})")
    formatted = []
    for m in messages:
        subj = m['subject'][:30] + ('...' if len(m['subject']) > 30 else '')
        sender = m['from'][:25] + ('...' if len(m['from']) > 25 else '')
        formatted.append({
            'ID': m['id'],
            'From': sender,
            'Subject': subj,
            'Date': m['date'][:16],
        })
    print(format_output(formatted, format_type='table'))


@cli.group()
def sheets():
    """Google Sheets commands"""
    pass


@sheets.command('list')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def sheets_list(ctx, format):
    """List all spreadsheets"""
    cache_manager = ctx.obj.get('cache_manager')
    service = SheetsService(ctx.obj['oauth_manager'], cache_manager)
    spreadsheets = service.list_spreadsheets()
    
    if not spreadsheets:
        print_info("No spreadsheets found")
        return
    
    # Format spreadsheets for display
    formatted_spreadsheets = []
    for spreadsheet in spreadsheets:
        formatted_spreadsheets.append({
            'ID': spreadsheet['id'][:15] + '...',
            'Name': spreadsheet['name'][:40] + ('...' if len(spreadsheet['name']) > 40 else ''),
            'Created': spreadsheet['created_time'][:10] if spreadsheet['created_time'] else '',
            'Modified': spreadsheet['modified_time'][:10] if spreadsheet['modified_time'] else '',
        })
    
    output = format_output(formatted_spreadsheets, format_type=format)
    print(output)


@sheets.command('get')
@click.argument('spreadsheet_id')
@click.option('--range', default='A1:Z100', help='Range to read (default: A1:Z100)')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def sheets_get(ctx, spreadsheet_id, range, format):
    """Read data from a spreadsheet"""
    cache_manager = ctx.obj.get('cache_manager')
    service = SheetsService(ctx.obj['oauth_manager'], cache_manager)
    values = service.read_range(spreadsheet_id, range)
    
    if not values:
        print_info("No data found in specified range")
        return
    
    if format == 'json':
        print(format_output([{'data': values}], format_type='json'))
    else:
        # Display as table
        output = format_output(values, format_type=format)
        print(output)


@sheets.command('read')
@click.option('--spreadsheet-id', help='Spreadsheet ID')
@click.option('--sheet-name', help='Sheet name')
@click.option('--header-row', default=1, help='Header row number (default: 1)')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def sheets_read(ctx, spreadsheet_id, sheet_name, header_row, format):
    """Read sheet data as structured data with headers"""
    if not spreadsheet_id:
        spreadsheet_id = click.prompt("Enter Spreadsheet ID")
    if not sheet_name:
        sheet_name = click.prompt("Enter Sheet Name")
        
    cache_manager = ctx.obj.get('cache_manager')
    service = SheetsService(ctx.obj['oauth_manager'], cache_manager)
    data = service.get_sheet_data(spreadsheet_id, sheet_name, header_row)
    
    if not data:
        print_info("No data found")
        return
    
    output = format_output(data, format_type=format)
    print(output)


@sheets.command('write')
@click.option('--spreadsheet-id', help='Spreadsheet ID')
@click.option('--range', help='Cell range (e.g., A1:B10)')
@click.option('--data-file', help='Source data file (CSV/JSON)')
@click.option('--input-format', default='csv', type=click.Choice(['csv', 'json']), help='Input file format')
@click.pass_context
def sheets_write(ctx, spreadsheet_id, range, data_file, input_format):
    """Write data to a spreadsheet range"""
    if not spreadsheet_id:
        spreadsheet_id = click.prompt("Enter Spreadsheet ID")
    if not range:
        range = click.prompt("Enter Range (e.g., A1:B10)")
    if not data_file:
        data_file = click.prompt("Enter Data File Path")
        
    import csv
    import json
    
    cache_manager = ctx.obj.get('cache_manager')
    service = SheetsService(ctx.obj['oauth_manager'], cache_manager)
    
    try:
        # Read data from file
        values = []
        if input_format == 'csv':
            with open(data_file, 'r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                values = list(reader)
        elif input_format == 'json':
            with open(data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    # Convert list of dicts to list of lists
                    headers = list(data[0].keys())
                    values = [headers]
                    for row in data:
                        values.append([row.get(h, '') for h in headers])
                else:
                    values = data
        
        success = service.write_range(spreadsheet_id, range, values)
        
        if success:
            print_success(f"Written {len(values)} rows to {range}")
        else:
            print_error("Failed to write data")
            
    except FileNotFoundError:
        print_error(f"File not found: {data_file}")
    except Exception as e:
        print_error(f"Error reading file: {e}")


@sheets.command('append')
@click.option('--spreadsheet-id', help='Spreadsheet ID')
@click.option('--range', help='Target range')
@click.option('--data-file', help='Source data file')
@click.option('--input-format', default='csv', type=click.Choice(['csv', 'json']), help='Input file format')
@click.pass_context
def sheets_append(ctx, spreadsheet_id, range, data_file, input_format):
    """Append rows to a spreadsheet"""
    if not spreadsheet_id:
        spreadsheet_id = click.prompt("Enter Spreadsheet ID")
    if not range:
        range = click.prompt("Enter Range")
    if not data_file:
        data_file = click.prompt("Enter Data File Path")
        
    import csv
    import json
    
    cache_manager = ctx.obj.get('cache_manager')
    service = SheetsService(ctx.obj['oauth_manager'], cache_manager)
    
    try:
        # Read data from file
        values = []
        if input_format == 'csv':
            with open(data_file, 'r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                values = list(reader)
        elif input_format == 'json':
            with open(data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    # Convert list of dicts to list of lists
                    headers = list(data[0].keys())
                    values = [headers]
                    for row in data:
                        values.append([row.get(h, '') for h in headers])
                else:
                    values = data
        
        success = service.append_rows(spreadsheet_id, range, values)
        
        if success:
            print_success(f"Appended {len(values)} rows to {range}")
        else:
            print_error("Failed to append data")
            
    except FileNotFoundError:
        print_error(f"File not found: {data_file}")
    except Exception as e:
        print_error(f"Error reading file: {e}")


@sheets.command('create')
@click.argument('title')
@click.pass_context
def sheets_create(ctx, title):
    """Create a new spreadsheet"""
    cache_manager = ctx.obj.get('cache_manager')
    service = SheetsService(ctx.obj['oauth_manager'], cache_manager)
    spreadsheet_id = service.create_spreadsheet(title)
    
    if spreadsheet_id:
        print_success(f"Created spreadsheet: {spreadsheet_id}")
        print(f"Title: {title}")
        print(f"URL: https://docs.google.com/spreadsheets/d/{spreadsheet_id}")
    else:
        print_error("Failed to create spreadsheet")


@sheets.command('add-sheet')
@click.argument('spreadsheet_id')
@click.argument('sheet_title')
@click.pass_context
def sheets_add_sheet(ctx, spreadsheet_id, sheet_title):
    """Add a new sheet to a spreadsheet"""
    cache_manager = ctx.obj.get('cache_manager')
    service = SheetsService(ctx.obj['oauth_manager'], cache_manager)
    sheet_id = service.add_sheet(spreadsheet_id, sheet_title)
    
    if sheet_id is not None:
        print_success(f"Added sheet '{sheet_title}' with ID: {sheet_id}")
    else:
        print_error("Failed to add sheet")


@sheets.command('clear')
@click.argument('spreadsheet_id')
@click.argument('range')
@click.pass_context
def sheets_clear(ctx, spreadsheet_id, range):
    """Clear a range of cells"""
    cache_manager = ctx.obj.get('cache_manager')
    service = SheetsService(ctx.obj['oauth_manager'], cache_manager)
    success = service.clear_range(spreadsheet_id, range)
    
    if success:
        print_success(f"Cleared range: {range}")
    else:
        print_error("Failed to clear range")


@sheets.command('info')
@click.argument('spreadsheet_id')
@click.pass_context
def sheets_info(ctx, spreadsheet_id):
    """Get spreadsheet information"""
    cache_manager = ctx.obj.get('cache_manager')
    service = SheetsService(ctx.obj['oauth_manager'], cache_manager)
    spreadsheet = service.get_spreadsheet(spreadsheet_id)
    
    if not spreadsheet:
        print_error("Spreadsheet not found")
        return
    
    print(f"Spreadsheet ID: {spreadsheet['spreadsheet_id']}")
    print(f"Title: {spreadsheet['properties'].get('title', 'Unknown')}")
    print(f"URL: {spreadsheet['spreadsheet_url']}")
    print(f"Sheets: {len(spreadsheet['sheets'])}")
    
    for sheet in spreadsheet['sheets']:
        print(f"\n  Sheet: {sheet['title']}")
        print(f"    ID: {sheet['sheet_id']}")
        print(f"    Index: {sheet['index']}")
        print(f"    Type: {sheet['sheet_type']}")
        grid_props = sheet.get('grid_properties', {})
        print(f"    Size: {grid_props.get('rowCount', '?')} x {grid_props.get('columnCount', '?')}")


@cli.group()
def drive():
    """Google Drive commands"""
    pass


@cli.group()
def tasks():
    """Google Tasks commands"""
    pass


@cli.group()
def people():
    """Google People API commands"""
    pass


@cli.group()
def bigquery():
    """Google BigQuery commands"""
    pass


@drive.command('list')
@click.option('--page-size', default=20, help='Maximum number of files to list')
@click.pass_context
def drive_list(ctx, page_size):
    """List files in Google Drive"""
    service = ctx.obj['oauth_manager'].build_service('drive', 'v3')
    if not service:
        print_error("Failed to initialize Drive service")
        return
    
    try:
        results = service.files().list(
            pageSize=page_size,
            fields="files(id, name, mimeType, modifiedTime, owners)"
        ).execute()
        files = results.get('files', [])
        
        if not files:
            print_info("No files found in Drive")
            return
        
        formatted_files = []
        for f in files:
            owners = ", ".join(o.get('displayName', 'Unknown') for o in f.get('owners', []))
            formatted_files.append({
                'ID': f.get('id'),
                'Name': f.get('name'),
                'Type': f.get('mimeType'),
                'Modified': f.get('modifiedTime', '')[:10],
                'Owner': owners,
            })
        
        output = format_output(formatted_files, format_type='table')
        print(output)
    except Exception as e:
        print_error(f"Failed to list Drive files: {e}")


@drive.command('edit')
@click.option('--file-id', prompt='File ID', help='ID of the Drive file to edit')
@click.option('--name', prompt='New name', help='New name for the file')
@click.pass_context
def drive_edit(ctx, file_id, name):
    """Rename a file in Google Drive"""
    service = ctx.obj['oauth_manager'].build_service('drive', 'v3')
    if not service:
        print_error("Failed to initialize Drive service")
        return
    try:
        result = service.files().update(
            fileId=file_id,
            body={'name': name},
            fields='id, name, webViewLink'
        ).execute()
        file_name = result.get('name', name)
        file_id = result.get('id', file_id)
        link = result.get('webViewLink', '')
        print_success(f"Renamed file: {file_name} ({file_id})")
        if link:
            print_info(f"Open in browser: {link}")
    except Exception as e:
        print_error(f"Failed to edit Drive file: {e}")


@drive.command('share')
@click.option('--file-id', prompt='File ID', help='ID of the Drive file to share')
@click.option('--email', prompt='Email', help='Email address to share with')
@click.option(
    '--role',
    type=click.Choice(['reader', 'commenter', 'writer', 'owner']),
    default='reader',
    show_default=True,
    prompt='Permission role'
)
@click.pass_context
def drive_share(ctx, file_id, email, role):
    """Share a Drive file with another user"""
    service = ctx.obj['oauth_manager'].build_service('drive', 'v3')
    if not service:
        print_error("Failed to initialize Drive service")
        return
    try:
        permission = {
            'type': 'user',
            'role': role,
            'emailAddress': email,
        }
        service.permissions().create(
            fileId=file_id,
            body=permission,
            sendNotificationEmail=True,
            fields='id'
        ).execute()
        print_success(f"Shared file {file_id} with {email} as {role}")
    except Exception as e:
        print_error(f"Failed to share Drive file: {e}")


@drive.command('create')
@click.option('--name', prompt='Folder name', help='Name of the folder to create')
@click.option(
    '--parent-id',
    default='',
    show_default=False,
    prompt='Parent folder ID (leave blank for My Drive)',
    help='Optional parent folder ID'
)
@click.pass_context
def drive_create(ctx, name, parent_id):
    """Create a folder in Google Drive"""
    service = ctx.obj['oauth_manager'].build_service('drive', 'v3')
    if not service:
        print_error("Failed to initialize Drive service")
        return
    try:
        metadata = {
            'name': name,
            'mimeType': 'application/vnd.google-apps.folder',
        }
        parent_id = parent_id.strip()
        if parent_id:
            metadata['parents'] = [parent_id]
        result = service.files().create(
            body=metadata,
            fields='id, name, webViewLink'
        ).execute()
        folder_name = result.get('name', name)
        folder_id = result.get('id')
        link = result.get('webViewLink', '')
        print_success(f"Created folder: {folder_name} ({folder_id})")
        if link:
            print_info(f"Open in browser: {link}")
    except Exception as e:
        print_error(f"Failed to create Drive folder: {e}")


@drive.command('import')
@click.option(
    '--file',
    'file_path',
    type=click.Path(exists=True, dir_okay=False),
    prompt='Local file path',
    help='Local file to upload to Drive'
)
@click.option('--name', default='', show_default=False, help='Name for the file in Drive')
@click.option(
    '--folder-id',
    default='',
    show_default=False,
    help='Optional Drive folder ID to upload into'
)
@click.pass_context
def drive_import(ctx, file_path, name, folder_id):
    """Upload a local file to Google Drive"""
    service = ctx.obj['oauth_manager'].build_service('drive', 'v3')
    if not service:
        print_error("Failed to initialize Drive service")
        return
    try:
        from pathlib import Path as _Path

        file_name = name or _Path(file_path).name
        metadata = {'name': file_name}
        folder_id = folder_id.strip()
        if folder_id:
            metadata['parents'] = [folder_id]
        media = MediaFileUpload(file_path, resumable=True)
        result = service.files().create(
            body=metadata,
            media_body=media,
            fields='id, name, webViewLink'
        ).execute()
        uploaded_name = result.get('name', file_name)
        file_id = result.get('id')
        link = result.get('webViewLink', '')
        print_success(f"Imported file to Drive: {uploaded_name} ({file_id})")
        if link:
            print_info(f"Open in browser: {link}")
    except Exception as e:
        print_error(f"Failed to import file to Drive: {e}")


@drive.command('info')
@click.argument('file_ref', required=False)
@click.pass_context
def drive_info(ctx, file_ref=None):
    """View file details: hermes drive info [REF]"""
    from .ui.human_flows import run_drive_files_flow
    svc = get_drive_service(ctx)
    run_drive_files_flow(svc, ctx.obj.get('config_manager'), file_ref=file_ref)


@drive.command('delete')
@click.argument('file_ref', required=False)
@click.pass_context
def drive_delete(ctx, file_ref=None):
    """Delete a file in Google Drive: hermes drive delete [REF]"""
    from .ui.human_flows import run_drive_delete_flow
    svc = get_drive_service(ctx)
    run_drive_delete_flow(svc, ctx.obj.get('config_manager'), file_ref=file_ref)


@drive.command('rename')
@click.argument('file_ref', required=False)
@click.pass_context
def drive_rename(ctx, file_ref=None):
    """Rename a file in Google Drive: hermes drive rename [REF]"""
    from .ui.human_flows import run_drive_rename_flow
    svc = get_drive_service(ctx)
    run_drive_rename_flow(svc, ctx.obj.get('config_manager'), file_ref=file_ref)


@drive.command('alias')
@click.argument('target')
@click.argument('alias_name')
@click.pass_context
def drive_alias(ctx, target, alias_name):
    """Create alias for a Drive file: hermes drive alias <TARGET> <ALIAS>"""
    from .services.resource_resolver import GlobalResourceResolver
    svc = get_drive_service(ctx)
    files = svc.list_files().get('files', [])
    cfg = ctx.obj.get('config_manager')
    ok, msg = GlobalResourceResolver.set_alias('drive', target, alias_name, files, cfg, resource_type="File")
    if ok:
        print_success(f"Alias created: {msg}")
    else:
        print_error(f"Failed to create alias: {msg}")


@tasks.command('lists')
@click.pass_context
def tasks_lists(ctx):
    """List task lists"""
    service = ctx.obj['oauth_manager'].build_service('tasks', 'v1')
    if not service:
        print_error("Failed to initialize Tasks service")
        return
    
    try:
        results = service.tasklists().list(maxResults=50).execute()
        lists = results.get('items', [])
        
        if not lists:
            print_info("No task lists found")
            return
        
        formatted_lists = []
        for lst in lists:
            formatted_lists.append({
                'ID': lst.get('id'),
                'Title': lst.get('title'),
                'Updated': lst.get('updated', '')[:10],
            })
        
        output = format_output(formatted_lists, format_type='table')
        print(output)
    except Exception as e:
        print_error(f"Failed to list task lists: {e}")


@tasks.command('list')
@click.argument('task_list_id', required=False)
@click.pass_context
def tasks_list(ctx, task_list_id):
    """List tasks in a task list"""
    service = ctx.obj['oauth_manager'].build_service('tasks', 'v1')
    if not service:
        print_error("Failed to initialize Tasks service")
        return
    
    try:
        if not task_list_id:
            lists_result = service.tasklists().list(maxResults=50).execute()
            items = lists_result.get('items', [])
            if not items:
                print_info("No task lists found")
                return
            formatted_lists = []
            for lst in items:
                formatted_lists.append({
                    'ID': lst.get('id'),
                    'Title': lst.get('title'),
                    'Updated': lst.get('updated', '')[:10],
                })
            output = format_output(formatted_lists, format_type='table')
            print(output)
            task_list_id = click.prompt("Enter Task List ID").strip()
            if not task_list_id:
                print_info("Task list ID is required")
                return
        
        results = service.tasks().list(tasklist=task_list_id, showCompleted=True).execute()
        tasks_items = results.get('items', [])
        
        if not tasks_items:
            print_info("No tasks found in this list")
            return
        
        formatted_tasks = []
        for t in tasks_items:
            formatted_tasks.append({
                'ID': t.get('id'),
                'Title': t.get('title'),
                'Status': t.get('status'),
                'Due': t.get('due', '')[:10],
            })
        
        output = format_output(formatted_tasks, format_type='table')
        print(output)
    except Exception as e:
        print_error(f"Failed to list tasks: {e}")


@tasks.command('create-list')
@click.option('--title', prompt='List title', help='Title of the task list')
@click.pass_context
def tasks_create_list(ctx, title):
    """Create a new task list"""
    service = ctx.obj['oauth_manager'].build_service('tasks', 'v1')
    if not service:
        print_error("Failed to initialize Tasks service")
        return
    
    try:
        body = {'title': title}
        result = service.tasklists().insert(body=body).execute()
        list_title = result.get('title', title)
        list_id = result.get('id')
        print_success(f"Created task list: {list_title}")
        print_info(f"List ID: {list_id}")
        
        from datetime import datetime
        
        while click.confirm("Add a task to this list?", default=True):
            task_title = click.prompt("Task title").strip()
            if not task_title:
                print_info("Task title is required")
                continue
            task_notes = click.prompt("Notes (optional)", default="", show_default=False)
            task_due = click.prompt("Due date (YYYY-MM-DD, leave blank for none)", default="", show_default=False)
            
            task_body = {'title': task_title}
            if task_notes:
                task_body['notes'] = task_notes
            if task_due:
                try:
                    due_date = datetime.strptime(task_due, "%Y-%m-%d").date()
                except ValueError:
                    print_error("Invalid due date. Please use YYYY-MM-DD with a real calendar date.")
                    continue
                task_body['due'] = f"{due_date.isoformat()}T00:00:00.000Z"
            
            try:
                created = service.tasks().insert(tasklist=list_id, body=task_body).execute()
                print_success(f"Added task: {created.get('title', task_title)}")
            except Exception as e:
                print_error(f"Failed to add task: {e}")
    except Exception as e:
        print_error(f"Failed to create task list: {e}")


@tasks.command('edit-list')
@click.argument('task_list_id')
@click.option('--title', prompt='New list name', help='New name for the task list')
@click.pass_context
def tasks_edit_list(ctx, task_list_id, title):
    """Rename an existing task list"""
    service = ctx.obj['oauth_manager'].build_service('tasks', 'v1')
    if not service:
        print_error("Failed to initialize Tasks service")
        return
    
    try:
        body = {'title': title}
        result = service.tasklists().patch(tasklist=task_list_id, body=body).execute()
        print_success(f"Renamed task list to: {result.get('title', title)}")
    except Exception as e:
        print_error(f"Failed to edit task list: {e}")


@tasks.command('delete-list')
@click.argument('task_list_id')
@click.option('--yes', is_flag=True, help='Skip confirmation')
@click.pass_context
def tasks_delete_list(ctx, task_list_id, yes):
    """Delete a task list and its tasks"""
    service = ctx.obj['oauth_manager'].build_service('tasks', 'v1')
    if not service:
        print_error("Failed to initialize Tasks service")
        return
    
    try:
        if not yes:
            click.confirm(f"Delete task list {task_list_id} and all its tasks?", abort=True)
        service.tasklists().delete(tasklist=task_list_id).execute()
        print_success(f"Deleted task list: {task_list_id}")
    except Exception as e:
        print_error(f"Failed to delete task list: {e}")


@tasks.command('create')
@click.option('--title', prompt='Task title', help='Title of the task')
@click.option('--notes', default='', show_default=False, prompt='Notes (optional)', help='Task notes')
@click.option('--due', default='', show_default=False, prompt='Due date (YYYY-MM-DD, leave blank for none)', help='Task due date')
@click.option('--task-list-id', default='', show_default=False, help='Task list ID (default: first list)')
@click.pass_context
def tasks_create(ctx, title, notes, due, task_list_id):
    """Create a new task"""
    service = ctx.obj['oauth_manager'].build_service('tasks', 'v1')
    if not service:
        print_error("Failed to initialize Tasks service")
        return
    
    try:
        if not task_list_id:
            lists_result = service.tasklists().list(maxResults=1).execute()
            items = lists_result.get('items', [])
            if not items:
                print_info("No task lists found")
                return
            task_list_id = items[0].get('id')
        
        body = {'title': title}
        if notes:
            body['notes'] = notes
        if due:
            body['due'] = f"{due}T00:00:00.000Z"
        
        result = service.tasks().insert(tasklist=task_list_id, body=body).execute()
        print_success(f"Created task: {result.get('title', title)}")
        print_info(f"Task ID: {result.get('id')}")
    except Exception as e:
        print_error(f"Failed to create task: {e}")


@tasks.command('view')
@click.option('--task-id', prompt='Task ID', help='ID of the task to view')
@click.option('--task-list-id', default='', show_default=False, help='Task list ID (default: first list)')
@click.pass_context
def tasks_view(ctx, task_id, task_list_id):
    """View a single task"""
    service = ctx.obj['oauth_manager'].build_service('tasks', 'v1')
    if not service:
        print_error("Failed to initialize Tasks service")
        return
    
    try:
        if not task_list_id:
            lists_result = service.tasklists().list(maxResults=1).execute()
            items = lists_result.get('items', [])
            if not items:
                print_info("No task lists found")
                return
            task_list_id = items[0].get('id')
        
        task = service.tasks().get(tasklist=task_list_id, task=task_id).execute()
        if not task:
            print_info("Task not found")
            return
        
        data = {
            'ID': task.get('id'),
            'Title': task.get('title'),
            'Status': task.get('status'),
            'Due': task.get('due', '')[:10],
            'Notes': task.get('notes', ''),
            'Updated': task.get('updated', '')[:19],
        }
        print_key_value_pairs(data, title="Task Details")
    except Exception as e:
        print_error(f"Failed to view task: {e}")


@tasks.command('edit')
@click.option('--task-id', prompt='Task ID', help='ID of the task to edit')
@click.option('--task-list-id', default='', show_default=False, help='Task list ID (default: first list)')
@click.pass_context
def tasks_edit(ctx, task_id, task_list_id):
    """Edit an existing task"""
    service = ctx.obj['oauth_manager'].build_service('tasks', 'v1')
    if not service:
        print_error("Failed to initialize Tasks service")
        return
    
    try:
        if not task_list_id:
            lists_result = service.tasklists().list(maxResults=1).execute()
            items = lists_result.get('items', [])
            if not items:
                print_info("No task lists found")
                return
            task_list_id = items[0].get('id')
        
        task = service.tasks().get(tasklist=task_list_id, task=task_id).execute()
        if not task:
            print_info("Task not found")
            return
        
        current_title = task.get('title', '')
        current_notes = task.get('notes', '')
        current_due = task.get('due', '')[:10]
        
        new_title = click.prompt("New title", default=current_title, show_default=bool(current_title))
        new_notes = click.prompt("New notes", default=current_notes, show_default=bool(current_notes))
        new_due = click.prompt("New due date (YYYY-MM-DD)", default=current_due, show_default=bool(current_due))
        
        body = {}
        if new_title != current_title:
            body['title'] = new_title
        if new_notes != current_notes:
            body['notes'] = new_notes
        if new_due and new_due != current_due:
            body['due'] = f"{new_due}T00:00:00.000Z"
        
        if not body:
            print_info("No changes made to the task")
            return
        
        updated = service.tasks().patch(tasklist=task_list_id, task=task_id, body=body).execute()
        print_success(f"Updated task: {updated.get('title', new_title)}")
    except Exception as e:
        print_error(f"Failed to edit task: {e}")


@tasks.command('info')
@click.argument('task_ref', required=False)
@click.option('--list-id', default=None, help='Task List ID')
@click.pass_context
def tasks_info(ctx, task_ref=None, list_id=None):
    """View task details: hermes tasks info [REF]"""
    from .ui.human_flows import run_tasks_items_flow
    svc = get_tasks_service(ctx)
    run_tasks_items_flow(svc, ctx.obj.get('config_manager'), list_ref=list_id, task_ref=task_ref)


@tasks.command('delete')
@click.argument('task_ref', required=False)
@click.option('--list-id', default=None, help='Task List ID')
@click.pass_context
def tasks_delete(ctx, task_ref=None, list_id=None):
    """Delete a task: hermes tasks delete [REF]"""
    from .ui.human_flows import run_task_delete_flow
    svc = get_tasks_service(ctx)
    run_task_delete_flow(svc, ctx.obj.get('config_manager'), list_ref=list_id, task_ref=task_ref)


@tasks.command('alias')
@click.argument('target')
@click.argument('alias_name')
@click.pass_context
def tasks_alias(ctx, target, alias_name):
    """Create alias for a task list: hermes tasks alias <TARGET> <ALIAS>"""
    from .services.resource_resolver import GlobalResourceResolver
    svc = get_tasks_service(ctx)
    lists = svc.list_task_lists().get('items', [])
    cfg = ctx.obj.get('config_manager')
    ok, msg = GlobalResourceResolver.set_alias('tasks', target, alias_name, lists, cfg, resource_type="Task List")
    if ok:
        print_success(f"Alias created: {msg}")
    else:
        print_error(f"Failed to create alias: {msg}")


@people.command('list')
@click.option('--page-size', default=20, help='Maximum number of contacts to list')
@click.pass_context
def people_list(ctx, page_size):
    """List your contacts from Google People API"""
    service = ctx.obj['oauth_manager'].build_service('people', 'v1')
    if not service:
        print_error("Failed to initialize People service")
        return
    
    try:
        results = service.people().connections().list(
            resourceName='people/me',
            pageSize=page_size,
            personFields='names,emailAddresses'
        ).execute()
        connections = results.get('connections', [])
        
        if not connections:
            print_info("No contacts found")
            return
        
        formatted_people = []
        for person in connections:
            names = person.get('names', [])
            emails = person.get('emailAddresses', [])
            name = names[0].get('displayName') if names else 'Unknown'
            email = emails[0].get('value') if emails else ''
            formatted_people.append({
                'Name': name,
                'Email': email,
            })
        
        output = format_output(formatted_people, format_type='table')
        print(output)
    except Exception as e:
        print_error(f"Failed to list contacts: {e}")


@bigquery.command('query')
@click.argument('project_id')
@click.argument('sql')
@click.pass_context
def bigquery_query(ctx, project_id, sql):
    """Run a SQL query against BigQuery"""
    service = ctx.obj['oauth_manager'].build_service('bigquery', 'v2')
    if not service:
        print_error("Failed to initialize BigQuery service")
        return
    
    try:
        query_body = {
            'query': sql,
            'useLegacySql': False,
        }
        query_job = service.jobs().query(projectId=project_id, body=query_body).execute()
        rows = query_job.get('rows', [])
        schema = query_job.get('schema', {}).get('fields', [])
        
        if not rows:
            print_info("Query returned no rows")
            return
        
        headers = [field['name'] for field in schema]
        formatted_rows = []
        for row in rows:
            values = [cell.get('v') for cell in row.get('f', [])]
            formatted_rows.append(dict(zip(headers, values)))
        
        output = format_output(formatted_rows, format_type='table')
        print(output)
    except Exception as e:
        print_error(f"Failed to run BigQuery query: {e}")


@cli.command('interactive')
@click.option('--no-welcome', is_flag=True, help='Skip welcome screen')
def interactive(no_welcome):
    """Start interactive mode with beautiful UI"""
    if not no_welcome:
        print_info("🚀 Starting GSuite CLI Interactive Mode...")
    
    try:
        start_interactive_mode()
    except KeyboardInterrupt:
        print_info("\n👋 Goodbye!")
    except Exception as e:
        print_error(f"Error starting interactive mode: {e}")


@cli.command()
@click.pass_context
def welcome(ctx):
    """Show welcome screen and start interactive mode"""
    interactive.callback(no_welcome=False)


@cli.group()
def docs():
    """Google Docs commands"""
    pass


@docs.command('list')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']))
@click.pass_context
def docs_list(ctx, format):
    """List all Google Docs"""
    cache_manager = ctx.obj.get('cache_manager')
    service = DocsService(ctx.obj['oauth_manager'], cache_manager)
    documents = service.list_documents()
    
    if not documents:
        print_info("No documents found")
        return
    
    # Format documents for display
    formatted_docs = []
    for doc in documents:
        formatted_docs.append({
            'ID': doc['id'],
            'Name': doc['name'][:30] + ('...' if len(doc['name']) > 30 else ''),
            'Created': doc['created'],
            'Modified': doc['modified'],
            'Shared': 'Yes' if doc['shared'] else 'No'
        })
    
    output = format_output(formatted_docs, format_type=format)
    print(output)


@docs.command('get')
@click.argument('document_id')
@click.option('--format', default='text', type=click.Choice(['text', 'json', 'csv']))
@click.pass_context
def docs_get(ctx, document_id, format):
    """Get document content"""
    cache_manager = ctx.obj.get('cache_manager')
    service = DocsService(ctx.obj['oauth_manager'], cache_manager)
    document = service.get_document(document_id)
    
    if not document:
        print_error("Document not found")
        return
    
    if format == 'text':
        print_header(f"📄 {document['name']}")
        print(f"Created: {document['created']}")
        print(f"Modified: {document['modified']}")
        print(f"Words: {document['word_count']}")
        print(f"Characters: {document['char_count']}")
        print()
        print_section("Content")
        print(document['content'][:1000] + ('...' if len(document['content']) > 1000 else ''))
    else:
        # Format as JSON/CSV
        formatted_data = [{
            'ID': document['id'],
            'Name': document['name'],
            'Created': document['created'],
            'Modified': document['modified'],
            'Word Count': document['word_count'],
            'Character Count': document['char_count'],
            'Content': document['content'][:500] + ('...' if len(document['content']) > 500 else '')
        }]
        output = format_output(formatted_data, format_type=format)
        print(output)


@docs.command('create')
@click.argument('title', required=False)
@click.option('--content', default='', help='Initial content for the document')
@click.pass_context
def docs_create(ctx, title, content):
    """Create a new document"""
    if not title:
        title = click.prompt("Document title")
    
    cache_manager = ctx.obj.get('cache_manager')
    service = DocsService(ctx.obj['oauth_manager'], cache_manager)
    try:
        document_id = service.create_document(title, content)
        
        if document_id:
            print_success(f"Document created: {title}")
            print_info(f"Document ID: {document_id}")
            print_info(f"URL: https://docs.google.com/document/d/{document_id}")
        else:
            # Service already prints specific error message
            pass
    except Exception as e:
        print_error(f"An unexpected error occurred: {e}")


@docs.command('update')
@click.argument('document_id')
@click.option('--content', required=True, help='Content to update the document with')
@click.option('--append', is_flag=True, help='Append content instead of replacing')
@click.pass_context
def docs_update(ctx, document_id, content, append):
    """Update document content"""
    cache_manager = ctx.obj.get('cache_manager')
    service = DocsService(ctx.obj['oauth_manager'], cache_manager)
    
    if append:
        success = service.append_to_document(document_id, content)
        action = "appended to"
    else:
        success = service.update_document(document_id, content)
        action = "updated"
    
    if success:
        print_success(f"Content {action} document")
    else:
        print_error(f"Failed to {action.rstrip('d')} document")


@docs.command('search')
@click.argument('query')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']))
@click.pass_context
def docs_search(ctx, query, format):
    """Search documents"""
    cache_manager = ctx.obj.get('cache_manager')
    service = DocsService(ctx.obj['oauth_manager'], cache_manager)
    documents = service.search_documents(query)
    
    if not documents:
        print_info(f"No documents found for: {query}")
        return
    
    # Format documents for display
    formatted_docs = []
    for doc in documents:
        formatted_docs.append({
            'ID': doc['id'][:15] + '...',
            'Name': doc['name'][:40] + ('...' if len(doc['name']) > 40 else ''),
            'Created': doc['created'],
            'Modified': doc['modified'],
            'Owner': doc['owners'][0] if doc['owners'] else 'Unknown'
        })
    
    output = format_output(formatted_docs, format_type=format)
    print(output)


@docs.command('info')
@click.argument('document_id')
@click.pass_context
def docs_info(ctx, document_id):
    """Get document information"""
    cache_manager = ctx.obj.get('cache_manager')
    service = DocsService(ctx.obj['oauth_manager'], cache_manager)
    info = service.get_document_info(document_id)
    
    if not info:
        print_error("Document not found")
        return
    
    print_header(f"📄 Document Information")
    print_key_value_pairs({
        'Name': info['name'],
        'ID': info['id'],
        'Created': info['created'],
        'Modified': info['modified'],
        'Size': info['size'],
        'Shared': 'Yes' if info['shared'] else 'No',
        'Permissions': str(info['permission_count']),
        'Web Link': info.get('web_view_link', 'N/A')
    })


@docs.command('template')
@click.argument('template_type')
@click.option('--title', help='Custom title for the document')
@click.option('--project-name', help='Project name (for project template)')
@click.pass_context
def docs_template(ctx, template_type, title, project_name):
    """Create document from template"""
    cache_manager = ctx.obj.get('cache_manager')
    service = AdvancedDocsService(ctx.obj['oauth_manager'], cache_manager)
    
    kwargs = {}
    if project_name:
        kwargs['project_name'] = project_name
    
    document_id = service.create_from_template(template_type, title, **kwargs)
    
    if not document_id:
        print_error("Failed to create document from template")


@docs.command('templates')
@click.pass_context
def docs_templates(ctx):
    """List available templates"""
    cache_manager = ctx.obj.get('cache_manager')
    service = AdvancedDocsService(ctx.obj['oauth_manager'], cache_manager)
    
    templates = service.list_templates()
    
    print_header("📋 Available Templates")
    for name, info in templates.items():
        print(f"\n{Fore.CYAN}{name}:")
        print(f"  {Fore.WHITE}Title: {info['title']}")
        print(f"  {Fore.WHITE}Description: {info['description']}")


@docs.command('read')
@click.argument('document_id')
@click.option('--format', default='text', type=click.Choice(['text', 'json', 'metadata']))
@click.pass_context
def docs_read(ctx, document_id, format):
    """Read document with advanced metadata"""
    cache_manager = ctx.obj.get('cache_manager')
    service = AdvancedDocsService(ctx.obj['oauth_manager'], cache_manager)
    
    if format == 'metadata':
        document = service.get_document_with_metadata(document_id)
    else:
        # Use basic service for simple text view
        basic_service = DocsService(ctx.obj['oauth_manager'], cache_manager)
        document = basic_service.get_document(document_id)
    
    if not document:
        print_error("Document not found")
        return
    
    if format == 'metadata':
        print_header(f"📄 {document['name']}")
        print_key_value_pairs({
            'ID': document['id'],
            'Created': document['created'],
            'Modified': document['modified'],
            'Size': document['size'],
            'Shared': 'Yes' if document['shared'] else 'No',
            'Web Link': document.get('web_view_link', 'N/A'),
            'Revisions': str(document.get('revisions_count', 0)),
            'Collaborators': str(len(document.get('collaborators', [])))
        })
        
        if 'analytics' in document:
            analytics = document['analytics']
            print_section("Document Analytics")
            print_key_value_pairs({
                'Words': str(analytics.get('word_count', 0)),
                'Characters': str(analytics.get('char_count', 0)),
                'Reading Time': f"{analytics.get('estimated_reading_time_minutes', 0)} min",
                'Complexity Score': f"{analytics.get('complexity_score', 0)}/100",
                'Content Type': analytics.get('content_type', 'Unknown')
            })
        
        if document.get('collaborators'):
            print_section("Collaborators")
            for collaborator in document['collaborators']:
                print(f"  👤 {collaborator['name']} ({collaborator['role']})")
        
    else:
        # Simple text view
        print_header(f"📄 {document['name']}")
        print(f"Words: {document.get('word_count', 0)} | Characters: {document.get('char_count', 0)}")
        print()
        print_section("Content")
        content = document.get('content', '')
        print(content[:1000] + ('...' if len(content) > 1000 else ''))


@docs.command('share')
@click.argument('document_id')
@click.argument('email')
@click.option('--role', default='reader', type=click.Choice(['reader', 'writer', 'commenter']))
@click.pass_context
def docs_share(ctx, document_id, email, role):
    """Share document with another user"""
    cache_manager = ctx.obj.get('cache_manager')
    service = AdvancedDocsService(ctx.obj['oauth_manager'], cache_manager)
    
    if service.share_document(document_id, email, role):
        print_success(f"Document shared with {email} as {role}")
    else:
        print_error("Failed to share document")


@docs.command('versions')
@click.argument('document_id')
@click.pass_context
def docs_versions(ctx, document_id):
    """Show document version history"""
    cache_manager = ctx.obj.get('cache_manager')
    service = AdvancedDocsService(ctx.obj['oauth_manager'], cache_manager)
    
    versions = service.get_document_versions(document_id)
    
    if not versions:
        print_info("No version history available")
        return
    
    print_header(f"📜 Version History")
    for version in versions:
        print(f"📅 {version['modified_time'][:19]}")
        print(f"   👤 {version['modifier']}")
        print(f"   📊 Size: {version['size']} bytes")
        print()


@docs.command('export')
@click.argument('document_id')
@click.option('--format', default='pdf', type=click.Choice(['pdf', 'docx', 'txt', 'html', 'rtf', 'odt']))
@click.option('--output', help='Output file path')
@click.pass_context
def docs_export(ctx, document_id, format, output):
    """Export document in various formats"""
    cache_manager = ctx.obj.get('cache_manager')
    service = AdvancedDocsService(ctx.obj['oauth_manager'], cache_manager)
    
    content = service.export_document_advanced(document_id, format)
    
    if not content:
        print_error("Failed to export document")
        return
    
    # Determine output path
    if not output:
        output = f"document_{document_id[:8]}.{format}"
    
    try:
        with open(output, 'w', encoding='utf-8') as f:
            f.write(content)
        print_success(f"Document exported to {output}")
    except Exception as e:
        print_error(f"Failed to save file: {e}")


@docs.command('duplicate')
@click.argument('document_id')
@click.option('--title', help='Title for the duplicated document')
@click.pass_context
def docs_duplicate(ctx, document_id, title):
    """Duplicate a document"""
    cache_manager = ctx.obj.get('cache_manager')
    service = AdvancedDocsService(ctx.obj['oauth_manager'], cache_manager)
    
    new_id = service.duplicate_document(document_id, title)
    
    if new_id:
        print_success(f"Document duplicated successfully")
        print_info(f"New document ID: {new_id}")
    else:
        print_error("Failed to duplicate document")


@docs.command('delete')
@click.argument('document_id')
@click.option('--confirm', is_flag=True, help='Skip confirmation prompt')
@click.pass_context
def docs_delete(ctx, document_id, confirm):
    """Delete a document"""
    if not confirm:
        click.confirm(f"Are you sure you want to delete document {document_id}?", abort=True)
    
    cache_manager = ctx.obj.get('cache_manager')
    service = DocsService(ctx.obj['oauth_manager'], cache_manager)
    
    if service.delete_document(document_id):
        print_success("Document deleted successfully")
    else:
        print_error("Failed to delete document")


@cli.group()
def forms():
    """Google Forms commands"""
    pass


@forms.command('list')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.option('--max-results', default=25, help='Maximum number of forms to list')
@click.pass_context
def forms_list(ctx, format, max_results):
    """List Google Forms in your Drive"""
    cache_manager = ctx.obj.get('cache_manager')
    service = FormsService(ctx.obj['oauth_manager'], cache_manager)
    forms = service.list_forms(max_results=max_results)
    
    if not forms:
        print_info("No forms found")
        return
    
    formatted_forms = []
    for f in forms:
        formatted_forms.append({
            'ID': f['id'],
            'Name': f['name'][:40] + ('...' if len(f['name']) > 40 else ''),
            'Owner': f['owner'],
            'Created': f['created'],
            'Modified': f['modified'],
        })
    
    output = format_output(formatted_forms, format_type=format)
    print(output)


@forms.command('info')
@click.argument('form_id')
@click.pass_context
def forms_info(ctx, form_id):
    """Show basic information about a form"""
    form_id = form_id.strip()
    cache_manager = ctx.obj.get('cache_manager')
    service = FormsService(ctx.obj['oauth_manager'], cache_manager)
    info = service.get_form(form_id)
    
    if not info:
        print_error("Form not found or Forms API not enabled")
        return
    
    print_header("📋 Form Information")
    print_key_value_pairs({
        'Title': info['title'],
        'ID': info['id'],
        'Document Title': info['document_title'],
        'Description': info['description'],
        'Items': str(info['item_count']),
        'Responder URL': info['responder_uri'],
        'Shuffle Questions': 'Yes' if info['shuffle_questions'] else 'No',
        'Is Quiz': 'Yes' if info['quiz'] else 'No',
    })


@forms.command('create')
@click.argument('title', required=False)
@click.option('--description', default='', help='Form description')
@click.pass_context
def forms_create(ctx, title, description):
    """Create a new Google Form"""
    if not title:
        title = click.prompt("Form title")
    
    cache_manager = ctx.obj.get('cache_manager')
    service = FormsService(ctx.obj['oauth_manager'], cache_manager)
    form = service.create_form(title, description)
    
    if not form:
        return
    
    print_success(f"Form created: {form['title']}")
    print_info(f"Form ID: {form['id']}")
    print_info(f"Edit URL: https://docs.google.com/forms/d/{form['id']}/edit")


@forms.command('edit')
@click.option('--form-id', help='Form ID to edit')
@click.option('--title', help='New form title')
@click.option('--description', help='New form description')
@click.pass_context
def forms_edit(ctx, form_id, title, description):
    """Edit form title/description and show edit URL"""
    if not form_id:
        form_id = click.prompt("Form ID")
    form_id = form_id.strip()
    
    cache_manager = ctx.obj.get('cache_manager')
    service = FormsService(ctx.obj['oauth_manager'], cache_manager)
    
    if not title and not description:
        print_info("No new title or description provided; showing current info.")
        info = service.get_form(form_id)
        if not info:
            print_error("Form not found")
            return
        print_header("📋 Current Form Information")
        print_key_value_pairs({
            'Title': info['title'],
            'Description': info['description'],
            'ID': info['id'],
        })
    else:
        updated = service.update_form_info(form_id, title=title, description=description)
        if not updated:
            return
        print_success("Form updated")
        print_key_value_pairs({
            'Title': updated['title'],
            'Description': updated['description'],
            'ID': updated['id'],
        })
    
    print_info(f"Edit URL: https://docs.google.com/forms/d/{form_id}/edit")


@forms.command('responses')
@click.argument('form_id')
@click.option('--max-results', default=50, help='Maximum number of responses to list')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def forms_responses(ctx, form_id, max_results, format):
    """List responses for a form"""
    form_id = form_id.strip()
    cache_manager = ctx.obj.get('cache_manager')
    service = FormsService(ctx.obj['oauth_manager'], cache_manager)
    responses = service.list_responses(form_id, max_results=max_results)
    
    if not responses:
        print_info("No responses found for this form")
        return
    
    formatted = []
    for r in responses:
        formatted.append({
            'Response ID': r['response_id'],
            'Email': r['respondent_email'],
            'Created': r['create_time'][:19] if r['create_time'] else '',
            'Last Submitted': r['last_submitted_time'][:19] if r['last_submitted_time'] else '',
            'Score': r['total_score'],
        })
    
    output = format_output(formatted, format_type=format)
    print(output)


@forms.command('response')
@click.argument('form_id')
@click.argument('response_id')
@click.pass_context
def forms_response(ctx, form_id, response_id):
    """Show a single response with answers"""
    form_id = form_id.strip()
    response_id = response_id.strip()
    cache_manager = ctx.obj.get('cache_manager')
    service = FormsService(ctx.obj['oauth_manager'], cache_manager)
    response = service.get_response(form_id, response_id)
    
    if not response:
        print_error("Response not found")
        return
    
    print_header("📨 Form Response")
    print_key_value_pairs({
        'Form ID': response['form_id'],
        'Response ID': response['response_id'],
        'Email': response['respondent_email'],
        'Created': response['create_time'],
        'Last Submitted': response['last_submitted_time'],
        'Score': response['total_score'],
    })
    
    if response['answers']:
        print_section("Answers")
        for question_id, value in response['answers'].items():
            print(f"{question_id}: {value}")


@cli.group()
def meet():
    """Google Meet commands"""
    pass


@meet.command('create')
@click.option('--type', 'meeting_type', type=click.Choice(['private', 'public'], case_sensitive=False), help='Meeting visibility type')
@click.pass_context
def meet_create(ctx, meeting_type):
    """Create a new meeting space"""
    if not meeting_type:
        meeting_type = click.prompt(
            "Meeting type",
            type=click.Choice(['private', 'public'], case_sensitive=False),
            default='private'
        )
    visibility = meeting_type.lower()
    
    if visibility == 'private':
        config = {'accessType': 'RESTRICTED'}
    else:
        config = {'accessType': 'OPEN'}
    
    service = MeetService(ctx.obj['oauth_manager'])
    space = service.create_space(config=config)
    
    if not space:
        print_error("Failed to create meeting space")
        return
    
    print_success("Meeting space created successfully!")
    print()
    print(f"  {Fore.CYAN}Meeting URL:{Style.RESET_ALL}  {space['meeting_uri']}")
    print(f"  {Fore.CYAN}Meeting Code:{Style.RESET_ALL} {space['meeting_code']}")
    print(f"  {Fore.CYAN}Space Name:{Style.RESET_ALL}   {space['name']}")


@meet.command('join')
@click.argument('meeting')
@click.pass_context
def meet_join(ctx, meeting):
    """Join / open a Google Meet in default browser"""
    service = MeetService(ctx.obj['oauth_manager'])
    meeting_url = service.get_meeting_url(meeting)
    
    print_info(f"Opening meeting in browser: {meeting_url}")
    result = service.join_meeting(meeting)
    if result.get('success'):
        print_success("Launched Google Meet!")
    else:
        print_error(f"Could not open browser: {result.get('error', 'Unknown error')}")
        print_info(f"Please open manually: {meeting_url}")


@meet.command('get')
@click.argument('space_name')
@click.pass_context
def meet_get(ctx, space_name):
    """Get meeting space details"""
    service = MeetService(ctx.obj['oauth_manager'])
    space = service.get_space(space_name)
    
    if not space:
        print_error("Meeting space not found")
        return
    
    print_header("🎥 Meeting Space Details")
    print_key_value_pairs({
        'Space Name': space['name'],
        'Meeting URL': space['meeting_uri'],
        'Meeting Code': space['meeting_code'],
    })
    
    if space.get('config'):
        print_section("Configuration")
        config = space['config']
        if 'accessType' in config:
            print(f"  Access Type: {config['accessType']}")
        if 'entryPointAccess' in config:
            print(f"  Entry Point Access: {config['entryPointAccess']}")


@meet.command('details')
@click.argument('meeting')
@click.pass_context
def meet_details(ctx, meeting):
    """Inspect meeting space or conference details"""
    service = MeetService(ctx.obj['oauth_manager'])
    
    # If meeting starts with conferenceRecords/, fetch conference record
    if meeting.startswith('conferenceRecords/'):
        record = service.get_conference_record(meeting)
        if not record:
            print_error(f"Conference record not found: {meeting}")
            return
        print_header("🎥 Conference Details")
        print_key_value_pairs({
            'Record Name': record['name'],
            'Space': record['space'],
            'Start Time': record['start_time'],
            'End Time': record['end_time'] or 'Active',
            'Expires': record['expire_time'],
        })
        return

    # Otherwise treat as space name, code, or URL
    code = service.extract_meeting_code(meeting)
    space_name = meeting if meeting.startswith('spaces/') else f'spaces/{code}'
    space = service.get_space(space_name)
    
    if not space:
        # Fallback: display inferred info
        url = service.get_meeting_url(meeting)
        print_header("🎥 Meeting Details")
        print_key_value_pairs({
            'Meeting Code': code or meeting,
            'Meeting URL': url,
            'Status': 'External or Unregistered Space',
        })
        return
    
    print_header("🎥 Meeting Space Details")
    details = {
        'Space Name': space['name'],
        'Meeting URL': space['meeting_uri'],
        'Meeting Code': space['meeting_code'],
    }
    if space.get('active_conference'):
        details['Active Conference'] = str(space['active_conference'])
    print_key_value_pairs(details)
    
    if space.get('config'):
        print_section("Configuration")
        config = space['config']
        for k, v in config.items():
            print(f"  {k}: {v}")


@meet.command('update')
@click.argument('space_name')
@click.option('--access-type', type=click.Choice(['RESTRICTED', 'OPEN', 'TRUSTED'], case_sensitive=False), required=True, help='New access type')
@click.pass_context
def meet_update(ctx, space_name, access_type):
    """Update meeting space configuration"""
    service = MeetService(ctx.obj['oauth_manager'])
    config = {'accessType': access_type.upper()}
    updated = service.update_space(space_name, config)
    if updated:
        print_success("Meeting space configuration updated!")
        print_key_value_pairs({
            'Space Name': updated['name'],
            'Meeting URL': updated['meeting_uri'],
            'Access Type': updated.get('config', {}).get('accessType', access_type.upper()),
        })
    else:
        print_error("Failed to update meeting space configuration")


@meet.command('list')
@click.option('--max-results', default=25, help='Maximum number of records (default: 25, max: 100)')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def meet_list(ctx, max_results, format):
    """List recent conference records (past/ongoing meetings)"""
    service = MeetService(ctx.obj['oauth_manager'])
    records = service.list_conference_records(max_results=max_results)
    
    if not records:
        print_info("No conference records found")
        return
    
    formatted_records = []
    for record in records:
        formatted_records.append({
            'Name': record['name'],
            'Space': record['space'],
            'Start': record['start_time'][:19] if record['start_time'] else '',
            'End': record['end_time'][:19] if record['end_time'] else 'Active',
        })
    
    output = format_output(formatted_records, format_type=format)
    print(output)


@meet.command('history')
@click.option('--max-results', default=25, help='Maximum number of records (default: 25, max: 100)')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def meet_history(ctx, max_results, format):
    """Alias for meet list to view meeting conference history"""
    ctx.invoke(meet_list, max_results=max_results, format=format)


@meet.command('active')
@click.option('--max-results', default=10, help='Maximum number of records to check')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def meet_active(ctx, max_results, format):
    """List currently active / ongoing conferences"""
    service = MeetService(ctx.obj['oauth_manager'])
    records = service.get_active_conferences(max_results=max_results)
    
    if not records:
        print_info("No active conferences found")
        return
    
    formatted_records = []
    for record in records:
        formatted_records.append({
            'Name': record['name'],
            'Space': record['space'],
            'Start': record['start_time'][:19] if record['start_time'] else '',
            'Status': 'Ongoing',
        })
    
    output = format_output(formatted_records, format_type=format)
    print(output)


@meet.command('info')
@click.argument('record_name', required=False)
@click.pass_context
def meet_info(ctx, record_name=None):
    """Get conference record or meeting space details: hermes meet info [REF]"""
    service = MeetService(ctx.obj['oauth_manager'])
    if not record_name:
        from .ui.human_flows import run_meet_spaces_flow
        run_meet_spaces_flow(service, ctx.obj.get('config_manager'))
        return
    record = service.get_conference_record(record_name)
    if not record:
        from .ui.human_flows import run_meet_spaces_flow
        run_meet_spaces_flow(service, ctx.obj.get('config_manager'), space_ref=record_name)
        return
    
    print_header("🎥 Conference Record Details")
    print_key_value_pairs({
        'Record Name': record['name'],
        'Space': record['space'],
        'Start Time': record['start_time'],
        'End Time': record['end_time'] or 'Active',
        'Expires': record['expire_time'],
    })


@meet.command('end')
@click.argument('space_ref', required=False)
@click.pass_context
def meet_end_cmd(ctx, space_ref=None):
    """End active conference for a meeting space: hermes meet end [REF]"""
    from .ui.human_flows import run_meet_end_flow
    service = MeetService(ctx.obj['oauth_manager'])
    run_meet_end_flow(service, ctx.obj.get('config_manager'), space_ref=space_ref)


@meet.command('alias')
@click.argument('target')
@click.argument('alias_name')
@click.pass_context
def meet_alias(ctx, target, alias_name):
    """Create alias for a meeting space: hermes meet alias <TARGET> <ALIAS>"""
    from .services.resource_resolver import GlobalResourceResolver
    service = MeetService(ctx.obj['oauth_manager'])
    spaces = service.list_spaces()
    cfg = ctx.obj.get('config_manager')
    ok, msg = GlobalResourceResolver.set_alias('meet', target, alias_name, spaces, cfg, resource_type="Meeting Space")
    if ok:
        print_success(f"Alias created: {msg}")
    else:
        print_error(f"Failed to create alias: {msg}")


@meet.command('participants')
@click.argument('record_name')
@click.option('--max-results', default=50, help='Maximum participants to return')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def meet_participants(ctx, record_name, max_results, format):
    """List participants for a conference record"""
    service = MeetService(ctx.obj['oauth_manager'])
    participants = service.list_participants(record_name, max_results=max_results)
    
    if not participants:
        print_info(f"No participants found for {record_name}")
        return
    
    formatted = []
    for p in participants:
        start_time = p['earliest_start_time'][:19] if p['earliest_start_time'] else 'Unknown'
        end_time = p['latest_end_time'][:19] if p['latest_end_time'] else 'Active'
        formatted.append({
            'Name': p['display_name'],
            'User ID': p['user_id'] or 'N/A',
            'Joined': start_time,
            'Left': end_time,
        })
    
    print_header(f"👥 Participants ({len(formatted)})")
    output = format_output(formatted, format_type=format)
    print(output)


@meet.command('recordings')
@click.argument('record_name')
@click.option('--max-results', default=50, help='Maximum recordings to return')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def meet_recordings(ctx, record_name, max_results, format):
    """List recordings for a conference record"""
    service = MeetService(ctx.obj['oauth_manager'])
    recordings = service.list_recordings(record_name, max_results=max_results)
    
    if not recordings:
        print_info(f"No recordings found for {record_name}")
        return
    
    formatted = []
    for r in recordings:
        formatted.append({
            'Name': r['name'],
            'State': r['state'] or 'Ready',
            'Start': r['start_time'][:19] if r['start_time'] else '',
            'Drive File': r['drive_file'] or r['export_uri'] or 'N/A',
        })
    
    print_header(f"📼 Recordings ({len(formatted)})")
    output = format_output(formatted, format_type=format)
    print(output)


@meet.command('transcripts')
@click.argument('record_name')
@click.option('--max-results', default=50, help='Maximum transcripts to return')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']), help='Output format')
@click.pass_context
def meet_transcripts(ctx, record_name, max_results, format):
    """List transcripts for a conference record"""
    service = MeetService(ctx.obj['oauth_manager'])
    transcripts = service.list_transcripts(record_name, max_results=max_results)
    
    if not transcripts:
        print_info(f"No transcripts found for {record_name}")
        return
    
    formatted = []
    for t in transcripts:
        formatted.append({
            'Name': t['name'],
            'State': t['state'] or 'Ready',
            'Start': t['start_time'][:19] if t['start_time'] else '',
            'Document': t['docs_document'] or t['export_uri'] or 'N/A',
        })
    
    print_header(f"📝 Transcripts ({len(formatted)})")
    output = format_output(formatted, format_type=format)
    print(output)


@meet.command('end')
@click.argument('space_name')
@click.option('--yes', is_flag=True, help='Skip confirmation')
@click.pass_context
def meet_end(ctx, space_name, yes):
    """End active conference in a space"""
    if not yes:
        click.confirm(f"End active conference in {space_name}?", abort=True)
    
    service = MeetService(ctx.obj['oauth_manager'])
    success = service.end_active_conference(space_name)
    
    if success:
        print_success("Active conference ended successfully")
    else:
        print_error("Failed to end active conference")


@meet.command('test-connection')
@click.pass_context
def meet_test_connection(ctx):
    """Test connection and permissions for Google Meet API"""
    service = MeetService(ctx.obj['oauth_manager'])
    result = service.test_connection()
    
    if result.get('connected'):
        print_success("✓ Google Meet API connection successful")
        print_key_value_pairs({
            'API Version': result.get('api_version', 'v2'),
            'Authenticated': 'Yes' if result.get('authenticated') else 'No',
            'Token Expiry': str(result.get('token_expiry', 'Unknown')),
        })
    else:
        print_error("✗ Google Meet API connection failed")
        if 'error' in result:
            print_error(f"Error: {result['error']}")


@cli.group()
def cache():
    """Cache management commands"""
    pass


@cache.command('status')
@click.pass_context
def cache_status(ctx):
    """Show cache status and statistics"""
    cache_manager = ctx.obj.get('cache_manager')
    
    if not cache_manager:
        print_info("Caching is disabled")
        return
    
    stats = cache_manager.get_stats()
    
    print_header("Cache Statistics")
    print(f"Total items: {stats['total_items']}")
    print(f"Cache size: {stats['cache_size_mb']} MB")
    print(f"Cache hits: {stats['hits']}")
    print(f"Cache misses: {stats['misses']}")
    print(f"Hit rate: {stats['hit_rate_percent']}%")
    print(f"Cache directory: {stats['cache_dir']}")


@cache.command('clear')
@click.option('--service', help='Clear cache for specific service only')
@click.option('--confirm', is_flag=True, help='Skip confirmation prompt')
@click.pass_context
def cache_clear(ctx, service, confirm):
    """Clear cache"""
    cache_manager = ctx.obj.get('cache_manager')
    
    if not cache_manager:
        print_info("Caching is disabled")
        return
    
    if not confirm:
        if service:
            click.confirm(f"Clear cache for '{service}' service?", abort=True)
        else:
            click.confirm("Clear all cache?", abort=True)
    
    if service:
        count = cache_manager.expire(service)
        print_success(f"Cleared {count} cache entries for '{service}'")
    else:
        cache_manager.clear()
        print_success("Cache cleared successfully")


@cache.command('stats')
@click.option('--service', help='Show stats for specific service')
@click.pass_context
def cache_stats(ctx, service):
    """Show detailed cache statistics"""
    cache_manager = ctx.obj.get('cache_manager')
    
    if not cache_manager:
        print_info("Caching is disabled")
        return
    
    stats = cache_manager.get_stats()
    
    if service:
        print_section(f"{service.upper()} Cache Stats")
    else:
        print_section("Global Cache Stats")
    
    print_key_value_pairs({
        'Total Items': stats['total_items'],
        'Cache Size (MB)': stats['cache_size_mb'],
        'Cache Hits': stats['hits'],
        'Cache Misses': stats['misses'],
        'Hit Rate (%)': stats['hit_rate_percent'],
        'Cache Sets': stats['sets'],
        'Cache Directory': stats['cache_dir']
    })


@cache.command('vacuum')
@click.pass_context
def cache_vacuum(ctx):
    """Vacuum cache to reclaim space"""
    cache_manager = ctx.obj.get('cache_manager')
    
    if not cache_manager:
        print_info("Caching is disabled")
        return
    
    if cache_manager.vacuum():
        print_success("Cache vacuumed successfully")
    else:
        print_error("Failed to vacuum cache")


@cache.command('configure')
@click.option('--ttl', type=int, help='Default TTL in seconds')
@click.option('--enable/--disable', default=None, help='Enable or disable cache')
@click.pass_context
def cache_configure(ctx, ttl, enable):
    """Configure cache settings"""
    config_manager = ctx.obj['config_manager']
    
    if ttl is not None:
        config_manager.set('cache_ttl', ttl)
        print_success(f"Cache TTL set to {ttl} seconds")
    
    if enable is not None:
        config_manager.set('cache_enabled', enable)
        status = "enabled" if enable else "disabled"
        print_success(f"Caching {status}")
    
    config_manager.save_config()
    
    # Show current settings
    print_section("Current Cache Settings")
    print(f"Enabled: {config_manager.get('cache_enabled')}")
    print(f"TTL: {config_manager.get('cache_ttl')} seconds")
    print(f"Cache Dir: {config_manager.get('cache_dir') or 'Default'}")


@cli.group()
def config():
    """Configuration management"""
    pass


@config.command('get')
@click.argument('key')
@click.pass_context
def config_get(ctx, key):
    """Get a configuration value"""
    config_manager = ctx.obj['config_manager']
    value = config_manager.get(key)
    
    if value is not None:
        print(f"{key}: {value}")
    else:
        print_error(f"Configuration key '{key}' not found")


@config.command('set')
@click.argument('key')
@click.argument('value')
@click.pass_context
def config_set(ctx, key, value):
    """Set a configuration value"""
    config_manager = ctx.obj['config_manager']
    
    # Try to parse as JSON for complex values
    try:
        import json
        if value.lower() in ['true', 'false']:
            parsed_value = value.lower() == 'true'
        elif value.isdigit():
            parsed_value = int(value)
        elif value.replace('.', '').isdigit():
            parsed_value = float(value)
        else:
            try:
                parsed_value = json.loads(value)
            except:
                parsed_value = value
    except:
        parsed_value = value
    
    if config_manager.set(key, parsed_value):
        config_manager.save_config()
        print_success(f"Set {key} = {parsed_value}")
    else:
        print_error(f"Failed to set {key}")


@config.command('list')
@click.option('--section', help='Show specific configuration section')
@click.pass_context
def config_list(ctx, section):
    """List configuration values"""
    config_manager = ctx.obj['config_manager']
    
    if section:
        config_data = config_manager.get_section(section)
        if config_data:
            print(f"\n{section.upper()} Configuration:")
            print("-" * 40)
            for key, value in config_data.items():
                print(f"  {key}: {value}")
        else:
            print_error(f"Section '{section}' not found")
    else:
        config_data = config_manager.get_all()
        print("\nGlobal Configuration:")
        print("-" * 40)
        
        for section_name, section_data in config_data.items():
            if isinstance(section_data, dict):
                print(f"\n{section_name.upper()}:")
                for key, value in section_data.items():
                    print(f"  {key}: {value}")
            else:
                print(f"  {section_name}: {section_data}")


@config.command('reset')
@click.confirmation_option(prompt='Are you sure you want to reset all configuration to defaults?')
@click.pass_context
def config_reset(ctx):
    """Reset configuration to defaults"""
    config_manager = ctx.obj['config_manager']
    
    if config_manager.reset_to_defaults():
        config_manager.save_config()
        print_success("Configuration reset to defaults")


@config.command('save')
@click.option('--format', default='yaml', type=click.Choice(['yaml', 'json']), help='File format')
@click.pass_context
def config_save(ctx, format):
    """Save current configuration"""
    config_manager = ctx.obj['config_manager']
    config_manager.save_config(format)


@config.command('export')
@click.argument('file_path')
@click.option('--format', default='yaml', type=click.Choice(['yaml', 'json']), help='File format')
@click.pass_context
def config_export(ctx, file_path, format):
    """Export configuration to file"""
    config_manager = ctx.obj['config_manager']
    config_manager.export_config(file_path, format)


@config.command('import')
@click.argument('file_path')
@click.pass_context
def config_import(ctx, file_path):
    """Import configuration from file"""
    config_manager = ctx.obj['config_manager']
    
    if config_manager.import_config(file_path):
        config_manager.save_config()


@config.command('validate')
@click.pass_context
def config_validate(ctx):
    """Validate configuration"""
    config_manager = ctx.obj['config_manager']
    issues = config_manager.validate_config()
    
    if not issues:
        print_success("Configuration is valid")
    else:
        print_error("Configuration issues found:")
        for issue in issues:
            print(f"  - {issue}")


@config.command('edit')
@click.pass_context
def config_edit(ctx):
    """Open configuration file in default editor"""
    import os
    import subprocess
    
    config_manager = ctx.obj['config_manager']
    config_file = config_manager.config_file
    
    if not config_file.exists():
        config_manager.save_config()
    
    editor = os.environ.get('EDITOR', 'nano')
    try:
        subprocess.call([editor, str(config_file)])
        print_info(f"Configuration file opened in {editor}")
        print_info("Run 'gs config validate' after editing to check for issues")
    except Exception as e:
        print_error(f"Failed to open editor: {e}")
        print_info(f"You can manually edit: {config_file}")

@cli.group()
def test():
    """Diagnostic and connection tests"""
    pass


@test.command('connection')
@click.pass_context
def test_connection(ctx):
    """Test all GSuite service connections"""
    cache_manager = ctx.obj.get('cache_manager')
    config_manager = ctx.obj.get('config_manager')
    service = DiagnosticsService(ctx.obj['oauth_manager'], config_manager, cache_manager)
    service.run_all_tests()


cli.add_command(ai_commands)
cli.add_command(chat_group, name='chat')
from .profile import profile_group
cli.add_command(profile_group, name='personal-profile')


# ===========================================================================
# Universal Hermes Command Ecosystem & Aliases
# ===========================================================================

from .services.workspace_commands import (
    get_drive_service,
    get_chat_service,
    get_tasks_service,
    get_docs_service,
    get_sheets_service,
    get_events_service,
    get_apps_script_service,
    get_admin_service,
    get_cloud_identity_service,
    get_cloud_search_service,
    get_forms_service,
    get_drive_activity_service,
)


@cli.command('list', context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
@click.argument('resource')
@click.argument('target_id', required=False)
@click.option('--format', 'output_format', type=click.Choice(['table', 'json']), default='table')
@click.pass_context
def universal_list(ctx, resource, target_id=None, output_format='table'):
    """Universal list command: hermes list <RESOURCE> [ID]"""
    res = resource.lower()
    
    # 1. Chat
    if res in ('chat', 'chat-space', 'chat-spaces', 'spaces'):
        from .services.chat_commands import chat_spaces
        ctx.invoke(chat_spaces, space_id=target_id, output_format=output_format)
    elif res in ('chat-messages', 'messages'):
        from .services.chat_commands import chat_messages
        if not target_id:
            target_id = click.prompt("Space ID")
        ctx.invoke(chat_messages, space_id=target_id, output_format=output_format)
    elif res in ('chat-members', 'members'):
        from .services.chat_commands import chat_members
        if not target_id:
            target_id = click.prompt("Space ID")
        ctx.invoke(chat_members, space_id=target_id, output_format=output_format)
    elif res in ('chat-threads', 'threads'):
        from .services.chat_commands import chat_threads
        if not target_id:
            target_id = click.prompt("Space ID")
        ctx.invoke(chat_threads, space_id=target_id, output_format=output_format)
    
    # 2. Drive
    elif res in ('drive', 'drive-files'):
        svc = get_drive_service(ctx)
        if target_id:
            f = svc.get_file(target_id)
            if f:
                if output_format == 'json':
                    format_output(f, 'json')
                else:
                    print_header("📁 Drive File Details")
                    print_key_value_pairs({
                        'ID': f.get('id'),
                        'Name': f.get('name'),
                        'MIME Type': f.get('mimeType'),
                        'Size': f.get('size', 'N/A'),
                        'Modified': f.get('modifiedTime', 'N/A')[:19],
                    })
        else:
            files_res = svc.list_files(page_size=30)
            flist = files_res.get('files', []) if isinstance(files_res, dict) else files_res
            if output_format == 'json':
                print(format_output(flist, 'json'))
            else:
                headers = ['File ID', 'Name', 'MIME Type', 'Modified']
                rows = [
                    {'File ID': f.get('id', ''), 'Name': f.get('name', '')[:35], 'MIME Type': f.get('mimeType', '').split('.')[-1], 'Modified': f.get('modifiedTime', '')[:10]}
                    for f in flist
                ]
                print(format_output(rows, 'table', headers=headers))
    elif res == 'drive-folders':
        svc = get_drive_service(ctx)
        folders = svc.list_folders(page_size=30)
        folders_list = folders.get('files', []) if isinstance(folders, dict) else folders
        if output_format == 'json':
            print(format_output(folders_list, 'json'))
        else:
            headers = ['Folder ID', 'Name', 'Modified']
            rows = [{'Folder ID': f.get('id', ''), 'Name': f.get('name', ''), 'Modified': f.get('modifiedTime', '')[:10]} for f in folders_list]
            print(format_output(rows, 'table', headers=headers))
    elif res == 'drive-shared':
        svc = get_drive_service(ctx)
        shared = svc.list_shared(page_size=30)
        shared_list = shared.get('files', []) if isinstance(shared, dict) else shared
        if output_format == 'json':
            print(format_output(shared_list, 'json'))
        else:
            headers = ['File ID', 'Name', 'Modified']
            rows = [{'File ID': f.get('id', ''), 'Name': f.get('name', ''), 'Modified': f.get('modifiedTime', '')[:10]} for f in shared_list]
            print(format_output(rows, 'table', headers=headers))
    elif res == 'drive-permissions':
        if not target_id:
            target_id = click.prompt("File ID")
        svc = get_drive_service(ctx)
        perms = svc.list_permissions(target_id)
        if output_format == 'json':
            print(format_output(perms, 'json'))
        else:
            headers = ['Permission ID', 'Role', 'Type', 'Email']
            rows = [{'Permission ID': p.get('id', ''), 'Role': p.get('role', ''), 'Type': p.get('type', ''), 'Email': p.get('emailAddress', 'N/A')} for p in perms]
            print(format_output(rows, 'table', headers=headers))
    elif res == 'drive-comments':
        if not target_id:
            target_id = click.prompt("File ID")
        svc = get_drive_service(ctx)
        comments = svc.list_comments(target_id)
        if output_format == 'json':
            print(format_output(comments, 'json'))
        else:
            headers = ['Comment ID', 'Author', 'Content', 'Created']
            rows = [{'Comment ID': c.get('id', ''), 'Author': c.get('author', {}).get('displayName', 'Unknown'), 'Content': c.get('content', '')[:40], 'Created': c.get('createdTime', '')[:10]} for c in comments]
            print(format_output(rows, 'table', headers=headers))
    elif res == 'drive-revisions':
        if not target_id:
            target_id = click.prompt("File ID")
        svc = get_drive_service(ctx)
        revs = svc.list_revisions(target_id)
        if output_format == 'json':
            print(format_output(revs, 'json'))
        else:
            headers = ['Revision ID', 'Modified Time', 'Size']
            rows = [{'Revision ID': r.get('id', ''), 'Modified Time': r.get('modifiedTime', '')[:19], 'Size': r.get('size', 'N/A')} for r in revs]
            print(format_output(rows, 'table', headers=headers))

    # 3. Tasks
    elif res in ('tasks', 'task'):
        svc = get_tasks_service(ctx)
        if target_id:
            t = svc.get_task(target_id)
            if t:
                if output_format == 'json':
                    print(format_output(t, 'json'))
                else:
                    print_header("✅ Task Details")
                    print_key_value_pairs({
                        'ID': t.get('id'),
                        'Title': t.get('title'),
                        'Status': t.get('status'),
                        'Due': t.get('due', 'None'),
                        'Notes': t.get('notes', 'None'),
                    })
        else:
            tasks_res = svc.list_tasks()
            items = tasks_res.get('items', []) if isinstance(tasks_res, dict) else tasks_res
            if output_format == 'json':
                print(format_output(items, 'json'))
            else:
                headers = ['Task ID', 'Title', 'Status', 'Due']
                rows = [{'Task ID': t.get('id', ''), 'Title': t.get('title', '')[:40], 'Status': t.get('status', ''), 'Due': t.get('due', 'None')[:10]} for t in items]
                print(format_output(rows, 'table', headers=headers))
    elif res == 'task-lists':
        svc = get_tasks_service(ctx)
        if target_id:
            tl = svc.get_task_list(target_id)
            if tl:
                print(format_output(tl, output_format))
        else:
            lists_res = svc.list_task_lists()
            items = lists_res.get('items', []) if isinstance(lists_res, dict) else lists_res
            if output_format == 'json':
                print(format_output(items, 'json'))
            else:
                headers = ['List ID', 'Title', 'Updated']
                rows = [{'List ID': l.get('id', ''), 'Title': l.get('title', ''), 'Updated': l.get('updated', '')[:10]} for l in items]
                print(format_output(rows, 'table', headers=headers))

    # 4. Docs
    elif res == 'docs':
        svc = get_docs_service(ctx)
        if target_id:
            doc = svc.get_document(target_id)
            if doc:
                if output_format == 'json':
                    print(format_output(doc, 'json'))
                else:
                    print_header(f"📄 {doc.get('name', 'Document')}")
                    print(doc.get('content', ''))
        else:
            docs = svc.list_documents()
            if output_format == 'json':
                print(format_output(docs, 'json'))
            else:
                headers = ['ID', 'Name', 'Modified']
                rows = [{'ID': d.get('id', ''), 'Name': d.get('name', ''), 'Modified': d.get('modified', '')[:10]} for d in docs]
                print(format_output(rows, 'table', headers=headers))

    # 5. Sheets
    elif res == 'sheets':
        svc = get_sheets_service(ctx)
        if target_id:
            ss = svc.get_spreadsheet(target_id)
            if ss:
                print(format_output(ss, output_format))
        else:
            sheets = svc.list_spreadsheets()
            if output_format == 'json':
                print(format_output(sheets, 'json'))
            else:
                headers = ['ID', 'Name', 'Modified']
                rows = [{'ID': s.get('id', ''), 'Name': s.get('name', ''), 'Modified': s.get('modified_time', '')[:10]} for s in sheets]
                print(format_output(rows, 'table', headers=headers))
    elif res == 'sheet-tabs':
        if not target_id:
            target_id = click.prompt("Spreadsheet ID")
        svc = get_sheets_service(ctx)
        tabs = svc.list_sheet_tabs(target_id)
        if output_format == 'json':
            print(format_output(tabs, 'json'))
        else:
            headers = ['Tab ID', 'Title', 'Index']
            rows = [{'Tab ID': str(t.get('tab_id', '')), 'Title': t.get('title', ''), 'Index': str(t.get('index', ''))} for t in tabs]
            print(format_output(rows, 'table', headers=headers))

    # 6. Workspace Events
    elif res in ('events', 'event-subscriptions'):
        svc = get_events_service(ctx)
        if target_id:
            sub = svc.get_subscription(target_id)
            if sub:
                print(format_output(sub, output_format))
        else:
            subs_res = svc.list_subscriptions()
            subs = subs_res.get('subscriptions', []) if isinstance(subs_res, dict) else subs_res
            if output_format == 'json':
                print(format_output(subs, 'json'))
            else:
                headers = ['Subscription Name', 'Target Resource', 'State']
                rows = [{'Subscription Name': s.get('name', ''), 'Target Resource': s.get('targetResource', ''), 'State': s.get('state', 'ACTIVE')} for s in subs]
                print(format_output(rows, 'table', headers=headers))

    # 7. Apps Script
    elif res in ('scripts', 'script'):
        svc = get_apps_script_service(ctx)
        if target_id:
            p = svc.get_project(target_id)
            if p:
                print(format_output(p, output_format))
        else:
            projects = svc.list_projects()
            if output_format == 'json':
                print(format_output(projects, 'json'))
            else:
                headers = ['Script ID', 'Title', 'Modified']
                rows = [{'Script ID': p.get('id', ''), 'Title': p.get('name', ''), 'Modified': p.get('modifiedTime', '')[:10]} for p in projects]
                print(format_output(rows, 'table', headers=headers))
    elif res == 'script-versions':
        if not target_id:
            target_id = click.prompt("Script ID")
        svc = get_apps_script_service(ctx)
        vers = svc.list_versions(target_id)
        vers_list = vers.get('versions', []) if isinstance(vers, dict) else vers
        if output_format == 'json':
            print(format_output(vers_list, 'json'))
        else:
            headers = ['Version Number', 'Description', 'Created']
            rows = [{'Version Number': str(v.get('versionNumber', '')), 'Description': v.get('description', ''), 'Created': v.get('createTime', '')[:19]} for v in vers_list]
            print(format_output(rows, 'table', headers=headers))
    elif res == 'script-deployments':
        if not target_id:
            target_id = click.prompt("Script ID")
        svc = get_apps_script_service(ctx)
        deps = svc.list_deployments(target_id)
        deps_list = deps.get('deployments', []) if isinstance(deps, dict) else deps
        if output_format == 'json':
            print(format_output(deps_list, 'json'))
        else:
            headers = ['Deployment ID', 'Description', 'Version']
            rows = [{'Deployment ID': d.get('deploymentId', ''), 'Description': d.get('deploymentConfig', {}).get('description', ''), 'Version': str(d.get('deploymentConfig', {}).get('versionNumber', ''))} for d in deps_list]
            print(format_output(rows, 'table', headers=headers))

    # 8. Admin SDK
    elif res == 'admin-users':
        svc = get_admin_service(ctx)
        if target_id:
            u = svc.get_user(target_id)
            if u:
                print(format_output(u, output_format))
        else:
            users_res = svc.list_users()
            users = users_res.get('users', []) if isinstance(users_res, dict) else users_res
            if output_format == 'json':
                print(format_output(users, 'json'))
            else:
                headers = ['Email', 'Name', 'Suspended']
                rows = [{'Email': u.get('primaryEmail', ''), 'Name': u.get('name', {}).get('fullName', ''), 'Suspended': 'Yes' if u.get('suspended') else 'No'} for u in users]
                print(format_output(rows, 'table', headers=headers))
    elif res == 'admin-groups':
        svc = get_admin_service(ctx)
        if target_id:
            g = svc.get_group(target_id)
            if g:
                print(format_output(g, output_format))
        else:
            groups_res = svc.list_groups()
            groups = groups_res.get('groups', []) if isinstance(groups_res, dict) else groups_res
            if output_format == 'json':
                print(format_output(groups, 'json'))
            else:
                headers = ['Email', 'Name', 'Direct Members']
                rows = [{'Email': g.get('email', ''), 'Name': g.get('name', ''), 'Direct Members': str(g.get('directMembersCount', ''))} for g in groups]
                print(format_output(rows, 'table', headers=headers))
    elif res == 'admin-devices':
        svc = get_admin_service(ctx)
        devs = svc.list_devices()
        devs_list = devs.get('devices', []) if isinstance(devs, dict) else devs
        print(format_output(devs_list, output_format))
    elif res == 'admin-domains':
        svc = get_admin_service(ctx)
        doms = svc.list_domains()
        doms_list = doms.get('domains', []) if isinstance(doms, dict) else doms
        print(format_output(doms_list, output_format))
    elif res in ('admin-roles', 'admin-audit'):
        print_info(f"Listing {resource} - requires super-admin audit scope.")

    # 9. Cloud Identity
    elif res == 'identity-groups':
        svc = get_cloud_identity_service(ctx)
        if target_id:
            g = svc.get_group(target_id)
            if g:
                print(format_output(g, output_format))
        else:
            groups_res = svc.list_groups()
            groups = groups_res.get('groups', []) if isinstance(groups_res, dict) else groups_res
            if output_format == 'json':
                print(format_output(groups, 'json'))
            else:
                headers = ['Name', 'Display Name', 'Description']
                rows = [{'Name': g.get('name', ''), 'Display Name': g.get('displayName', ''), 'Description': g.get('description', '')[:30]} for g in groups]
                print(format_output(rows, 'table', headers=headers))
    elif res == 'identity-members':
        if not target_id:
            target_id = click.prompt("Group Name or ID")
        svc = get_cloud_identity_service(ctx)
        mems = svc.list_members(target_id)
        mems_list = mems.get('memberships', []) if isinstance(mems, dict) else mems
        print(format_output(mems_list, output_format))
    elif res == 'identity-devices':
        svc = get_cloud_identity_service(ctx)
        devs = svc.list_devices()
        devs_list = devs.get('devices', []) if isinstance(devs, dict) else devs
        print(format_output(devs_list, output_format))

    # 10. Cloud Search
    elif res == 'cloud-search':
        svc = get_cloud_search_service(ctx)
        res_data = svc.search(target_id or "default")
        print(format_output(res_data.get('results', []), output_format))

    # 11. Forms
    elif res == 'forms':
        if target_id:
            ctx.invoke(forms_info, form_id=target_id)
        else:
            ctx.invoke(forms_list, format=output_format)
    elif res == 'form-items':
        if not target_id:
            target_id = click.prompt("Form ID")
        svc = get_forms_service(ctx)
        items = svc.list_form_items(target_id)
        print(format_output(items, output_format))
    elif res == 'form-responses':
        if not target_id:
            target_id = click.prompt("Form ID")
        ctx.invoke(forms_responses, form_id=target_id, format=output_format)

    # 12. Drive Activity
    elif res == 'drive-activity':
        svc = get_drive_activity_service(ctx)
        act = svc.query_activity(item_name=target_id)
        print(format_output(act.get('activities', []), output_format))

    # Existing: Gmail, Calendar, Meet
    elif res == 'gmail':
        if target_id:
            ctx.invoke(gmail_get, message_id=target_id, format=output_format)
        else:
            ctx.invoke(gmail_list, format=output_format)
    elif res == 'calendar':
        if target_id:
            ctx.invoke(calendar_get, event_id=target_id, format=output_format)
        else:
            ctx.invoke(calendar_list_events, format=output_format)
    elif res == 'meet':
        if target_id:
            ctx.invoke(meet_details, meeting=target_id)
        else:
            ctx.invoke(meet_list, format=output_format)
    else:
        print_error(f"Unknown resource for list: {resource}")


cli.add_command(universal_list, name='ls')
cli.add_command(universal_list, name='get')


@cli.command('search')
@click.argument('resource')
@click.argument('query')
@click.option('--limit', default=25, type=int, help='Maximum results')
@click.option('--format', 'output_format', type=click.Choice(['table', 'json']), default='table')
@click.pass_context
def universal_search(ctx, resource, query, limit=25, output_format='table'):
    """Universal search command: hermes search <RESOURCE> <QUERY>"""
    res = resource.lower()
    if res == 'chat':
        from .services.chat_commands import chat_search
        ctx.invoke(chat_search, query=query, limit=limit, output_format=output_format)
    elif res == 'drive':
        svc = get_drive_service(ctx)
        matches = svc.search_files(query, page_size=limit)
        matches_list = matches.get('files', []) if isinstance(matches, dict) else matches
        if output_format == 'json':
            print(format_output(matches_list, 'json'))
        else:
            headers = ['File ID', 'Name', 'MIME Type', 'Modified']
            rows = [{'File ID': f.get('id', ''), 'Name': f.get('name', '')[:35], 'MIME Type': f.get('mimeType', '').split('.')[-1], 'Modified': f.get('modifiedTime', '')[:10]} for f in matches_list]
            print(format_output(rows, 'table', headers=headers))
    elif res == 'tasks':
        svc = get_tasks_service(ctx)
        tasks_res = svc.list_tasks(max_results=limit)
        items = tasks_res.get('items', []) if isinstance(tasks_res, dict) else tasks_res
        matches = [t for t in items if query.lower() in t.get('title', '').lower()]
        print(format_output(matches, output_format))
    elif res == 'docs':
        svc = get_docs_service(ctx)
        matches = svc.search_documents(query)
        matches_list = matches.get('files', []) if isinstance(matches, dict) else matches
        print(format_output(matches_list, output_format))
    elif res == 'sheets':
        drive_svc = get_drive_service(ctx)
        matches = drive_svc.search_files(f"{query} and mimeType = 'application/vnd.google-apps.spreadsheet'", page_size=limit)
        matches_list = matches.get('files', []) if isinstance(matches, dict) else matches
        print(format_output(matches_list, output_format))
    elif res == 'cloud-search':
        svc = get_cloud_search_service(ctx)
        res_data = svc.search(query, page_size=limit)
        print(format_output(res_data.get('results', []), output_format))
    elif res == 'drive-activity':
        svc = get_drive_activity_service(ctx)
        act = svc.query_activity(page_size=limit)
        print(format_output(act.get('activities', []), output_format))
    elif res == 'admin-users':
        svc = get_admin_service(ctx)
        users = svc.search_users(query, max_results=limit)
        users_list = users.get('users', []) if isinstance(users, dict) else users
        print(format_output(users_list, output_format))
    elif res == 'identity-groups':
        svc = get_cloud_identity_service(ctx)
        groups = svc.search_groups(query, page_size=limit)
        groups_list = groups.get('groups', []) if isinstance(groups, dict) else groups
        print(format_output(groups_list, output_format))
    elif res == 'gmail':
        ctx.invoke(gmail_search, query=query, max_results=limit, format=output_format)
    elif res == 'calendar':
        ctx.invoke(calendar_search, query=query, format=output_format)
    else:
        print_error(f"Search not supported for resource: {resource}")


@cli.command('create')
@click.argument('resource')
@click.argument('target_id', required=False)
@click.option('--title', help='Title or display name')
@click.option('--message', '-m', help='Message body or content')
@click.option('--target', help='Target resource URI or ID')
@click.option('--topic', help='Cloud Pub/Sub topic')
@click.option('--email', help='User or group email')
@click.option('--given-name', help='Given name for user creation')
@click.option('--family-name', help='Family name for user creation')
@click.option('--password', help='Password for user creation')
@click.option('--version', 'version_num', type=int, help='Version number for deployment')
@click.pass_context
def universal_create(ctx, resource, target_id=None, title=None, message=None,
                     target=None, topic=None, email=None, given_name=None,
                     family_name=None, password=None, version_num=None):
    """Universal create command: hermes create <RESOURCE> [TARGET_ID]"""
    res = resource.lower()
    if res in ('chat-space', 'chat'):
        title = title or click.prompt("Space Display Name")
        from .services.chat_commands import _svc as _chat_svc
        service = _chat_svc(ctx)
        space = service.create_space(title)
        if space:
            print_success(f"Chat space created! ID: {space.get('name')}")
    elif res == 'chat-message':
        if not target_id:
            target_id = click.prompt("Space ID")
        from .services.chat_commands import chat_send
        ctx.invoke(chat_send, space_id=target_id, message=message)
    elif res in ('drive-folder', 'folder'):
        title = title or click.prompt("Folder Name")
        svc = get_drive_service(ctx)
        folder = svc.create_folder(title, parent_id=target_id)
        if folder:
            print_success(f"Folder created! ID: {folder.get('id')}")
    elif res in ('drive-file', 'file'):
        title = title or click.prompt("File Name")
        svc = get_drive_service(ctx)
        f = svc.create_file(title, content=message or "", parent_id=target_id)
        if f:
            print_success(f"File created! ID: {f.get('id')}")
    elif res in ('tasks', 'task'):
        title = title or click.prompt("Task Title")
        svc = get_tasks_service(ctx)
        t = svc.create_task(title, task_list_id=target_id or "@default")
        if t:
            print_success(f"Task created! ID: {t.get('id')}")
    elif res == 'task-list':
        title = title or click.prompt("Task List Title")
        svc = get_tasks_service(ctx)
        tl = svc.create_task_list(title)
        if tl:
            print_success(f"Task list created! ID: {tl.get('id')}")
    elif res == 'docs':
        svc = get_docs_service(ctx)
        doc = svc.create_document(title or "Untitled Document", content=message or "")
        if doc:
            doc_id = doc.get('documentId') if isinstance(doc, dict) else str(doc)
            print_success(f"Document created: {title or 'Untitled Document'}")
            print_info(f"Document ID: {doc_id}")
    elif res == 'sheets':
        svc = get_sheets_service(ctx)
        ss = svc.create_spreadsheet(title or "Untitled Spreadsheet")
        if ss:
            ss_id = ss.get('spreadsheetId') if isinstance(ss, dict) else str(ss)
            print_success(f"Spreadsheet created: {title or 'Untitled Spreadsheet'}")
            print_info(f"Spreadsheet ID: {ss_id}")
    elif res == 'sheet-tab':
        sheet_id = target_id or click.prompt("Spreadsheet ID")
        tab_title = title or click.prompt("Sheet Tab Title")
        svc = get_sheets_service(ctx)
        tab = svc.add_sheet_tab(sheet_id, tab_title)
        if tab:
            print_success(f"Tab created: {tab_title}")
    elif res == 'event-subscription':
        target_res = target or target_id or click.prompt("Target Resource (e.g. //chat.googleapis.com/spaces/xyz)")
        topic_name = topic or click.prompt("Cloud Pub/Sub Topic")
        svc = get_events_service(ctx)
        sub = svc.create_subscription(target_res, ["google.workspace.chat.message.v1.created"], topic_name)
        if sub:
            print_success(f"Event subscription created! Name: {sub.get('name')}")
    elif res in ('script', 'scripts'):
        script_title = title or click.prompt("Script Project Title")
        svc = get_apps_script_service(ctx)
        p = svc.create_project(script_title)
        if p:
            print_success(f"Script project created! ID: {p.get('scriptId')}")
    elif res == 'script-version':
        script_id = target_id or click.prompt("Script ID")
        svc = get_apps_script_service(ctx)
        v = svc.create_version(script_id, description=title or "")
        if v:
            print_success(f"Script version created: {v.get('versionNumber')}")
    elif res == 'script-deployment':
        script_id = target_id or click.prompt("Script ID")
        ver = version_num or int(click.prompt("Version Number", default="1"))
        svc = get_apps_script_service(ctx)
        dep = svc.create_deployment(script_id, ver, description=title or "")
        if dep:
            print_success(f"Deployment created! ID: {dep.get('deploymentId')}")
    elif res == 'admin-user':
        u_email = email or click.prompt("User Email")
        u_given = given_name or (title.split()[0] if title else click.prompt("Given Name"))
        u_family = family_name or (title.split()[-1] if title and len(title.split()) > 1 else click.prompt("Family Name"))
        u_pw = password or "HermesAdmin@123!"
        svc = get_admin_service(ctx)
        u = svc.create_user(u_email, u_given, u_family, u_pw)
        if u:
            print_success(f"Admin user created! ID: {u.get('id') or u.get('primaryEmail')}")
    elif res == 'admin-group':
        g_email = email or click.prompt("Group Email")
        g_name = title or click.prompt("Group Name")
        svc = get_admin_service(ctx)
        g = svc.create_group(g_email, g_name)
        if g:
            print_success(f"Admin group created! ID: {g.get('id') or g.get('email')}")
    elif res == 'identity-group':
        g_email = email or click.prompt("Group Email")
        g_name = title or click.prompt("Group Display Name")
        svc = get_cloud_identity_service(ctx)
        g = svc.create_group(g_name, g_email)
        if g:
            res_val = g.get('name') or g.get('response', {}).get('name') or 'Created'
            print_success(f"Identity group created! Name: {res_val}")
    elif res == 'forms':
        svc = get_forms_service(ctx)
        f = svc.create_form(title or "Untitled Form")
        if f:
            fid = f.get('formId') if isinstance(f, dict) else str(f)
            print_success(f"Form created! ID: {fid}")
    elif res == 'calendar':
        ctx.invoke(calendar_create_simple, summary=title)
    elif res == 'meet':
        ctx.invoke(meet_create)
    else:
        print_error(f"Create not supported for resource: {resource}")


@cli.command('update')
@click.argument('resource')
@click.argument('target_id')
@click.option('--title', help='New title or name')
@click.option('--description', help='New description')
@click.pass_context
def universal_update(ctx, resource, target_id, title=None, description=None):
    """Universal update command: hermes update <RESOURCE> <TARGET_ID>"""
    res = resource.lower()
    if res in ('drive', 'drive-file'):
        svc = get_drive_service(ctx)
        up = svc.update_file(target_id, name=title, description=description)
        if up:
            print_success(f"Drive file {target_id} updated successfully.")
    elif res in ('tasks', 'task'):
        svc = get_tasks_service(ctx)
        up = svc.update_task(target_id, title=title, notes=description)
        if up:
            print_success(f"Task {target_id} updated.")
    elif res == 'task-list':
        svc = get_tasks_service(ctx)
        up = svc.update_task_list(target_id, title=title or "Updated List")
        if up:
            print_success(f"Task list {target_id} updated.")
    elif res == 'docs':
        ctx.invoke(docs_update, document_id=target_id, content=description or "")
    elif res == 'admin-user':
        svc = get_admin_service(ctx)
        up = svc.update_user(target_id, given_name=title)
        if up:
            print_success(f"User {target_id} updated.")
    elif res == 'forms':
        ctx.invoke(forms_edit, form_id=target_id, title=title or "", description=description or "")
    elif res == 'calendar':
        ctx.invoke(calendar_update, event_id=target_id, title=title)
    else:
        print_error(f"Update not supported for resource: {resource}")


@cli.command('delete')
@click.argument('resource')
@click.argument('target_id', required=False)
@click.argument('extra_id', required=False)
@click.option('--yes', '-y', is_flag=True)
@click.pass_context
def universal_delete(ctx, resource, target_id=None, extra_id=None, yes=False):
    """Universal delete command: hermes delete <RESOURCE> [TARGET_REF]"""
    res = resource.lower()
    cfg = ctx.obj.get('config_manager')
    
    # If target_id is omitted, enter human-friendly interactive flow
    if not target_id:
        if res == 'calendar':
            from .ui.human_flows import run_calendar_delete_flow
            svc = CalendarService(ctx.obj['oauth_manager'])
            run_calendar_delete_flow(svc, cfg)
            return
        elif res == 'gmail':
            from .ui.human_flows import run_gmail_delete_flow
            from .services.gmail_commands import _svc as _gmail_svc
            svc = _gmail_svc(ctx)
            run_gmail_delete_flow(svc, cfg)
            return
        elif res in ('drive', 'drive-file', 'drive-folder'):
            from .ui.human_flows import run_drive_delete_flow
            svc = get_drive_service(ctx)
            run_drive_delete_flow(svc, cfg)
            return
        elif res in ('tasks', 'task'):
            from .ui.human_flows import run_task_delete_flow
            svc = get_tasks_service(ctx)
            run_task_delete_flow(svc, cfg)
            return
        elif res == 'chat':
            from .ui.human_flows import run_chat_message_delete_flow
            svc = get_chat_service(ctx)
            run_chat_message_delete_flow(svc, cfg)
            return
        elif res in ('events', 'event-subscription'):
            from .ui.human_flows import run_events_delete_flow
            svc = get_events_service(ctx)
            run_events_delete_flow(svc, cfg)
            return

    # If target_id is provided, resolve references where applicable
    if res in ('drive', 'drive-file', 'drive-folder') and target_id:
        svc = get_drive_service(ctx)
        from .services.resource_resolver import GlobalResourceResolver
        files = svc.list_files().get('files', [])
        try:
            resolved = GlobalResourceResolver.resolve(target_id, files, module='drive', resource_type='File', config_manager=cfg)
            target_id = resolved.get('id', target_id)
        except Exception:
            pass

    if res in ('tasks', 'task') and target_id:
        svc = get_tasks_service(ctx)
        from .services.resource_resolver import GlobalResourceResolver
        tasks_list = svc.list_tasks(tasklist_id='@default').get('items', [])
        try:
            resolved = GlobalResourceResolver.resolve(target_id, tasks_list, module='tasks', resource_type='Task', config_manager=cfg)
            target_id = resolved.get('id', target_id)
        except Exception:
            pass

    if not yes:
        click.confirm(f"Are you sure you want to delete {resource} {target_id}?", abort=True)
    if res == 'chat':
        from .services.chat_commands import chat_delete
        ctx.invoke(chat_delete, message_id=target_id, yes=True)
    elif res in ('drive', 'drive-file', 'drive-folder'):
        svc = get_drive_service(ctx)
        if svc.delete_file(target_id):
            print_success(f"Drive item {target_id} permanently deleted.")
    elif res in ('tasks', 'task'):
        svc = get_tasks_service(ctx)
        if svc.delete_task(target_id):
            print_success(f"Task {target_id} deleted.")
    elif res == 'task-list':
        svc = get_tasks_service(ctx)
        if svc.delete_task_list(target_id):
            print_success(f"Task list {target_id} deleted.")
    elif res == 'docs':
        svc = get_docs_service(ctx)
        if svc.delete_document(target_id):
            print_success(f"Document {target_id} deleted.")
    elif res == 'sheets':
        svc = get_sheets_service(ctx)
        if svc.delete_spreadsheet(target_id):
            print_success(f"Spreadsheet {target_id} deleted.")
    elif res == 'sheet-tab':
        svc = get_sheets_service(ctx)
        tab_id = int(extra_id or click.prompt("Tab ID"))
        if svc.delete_sheet_tab(target_id, tab_id):
            print_success(f"Sheet tab {tab_id} deleted.")
    elif res == 'event-subscription':
        svc = get_events_service(ctx)
        if svc.delete_subscription(target_id):
            print_success(f"Subscription {target_id} deleted.")
    elif res == 'script-deployment':
        svc = get_apps_script_service(ctx)
        dep_id = extra_id or click.prompt("Deployment ID")
        if svc.delete_deployment(target_id, dep_id):
            print_success(f"Deployment {dep_id} deleted.")
    elif res == 'form-item':
        svc = get_forms_service(ctx)
        item_id = extra_id or click.prompt("Item ID")
        if svc.delete_form_item(target_id, item_id):
            print_success(f"Form item {item_id} deleted.")
    elif res == 'admin-user':
        svc = get_admin_service(ctx)
        if svc.delete_user(target_id):
            print_success(f"User {target_id} deleted.")
    elif res == 'admin-group':
        svc = get_admin_service(ctx)
        if svc.delete_group(target_id):
            print_success(f"Group {target_id} deleted.")
    elif res == 'identity-group':
        svc = get_cloud_identity_service(ctx)
        if svc.delete_group(target_id):
            print_success(f"Identity group {target_id} deleted.")
    elif res == 'calendar':
        ctx.invoke(calendar_delete, event_id=target_id, yes=True)
    elif res == 'gmail':
        ctx.invoke(gmail_delete, message_id=target_id)
    else:
        print_error(f"Delete not supported for resource: {resource}")


@cli.command('info')
@click.argument('resource')
@click.argument('reference', required=False)
@click.pass_context
def universal_info(ctx, resource, reference=None):
    """View detailed information for any resource: hermes info <RESOURCE> [REF]"""
    res = resource.lower()
    cfg = ctx.obj.get('config_manager')
    if res in ('calendar', 'event'):
        from .ui.human_flows import run_calendar_info_flow
        svc = CalendarService(ctx.obj['oauth_manager'])
        run_calendar_info_flow(svc, cfg, event_ref=reference)
    elif res in ('meet', 'space'):
        from .ui.human_flows import run_meet_spaces_flow
        svc = MeetService(ctx.obj['oauth_manager'])
        run_meet_spaces_flow(svc, cfg, space_ref=reference)
    elif res in ('gmail', 'message', 'mail'):
        from .ui.human_flows import run_gmail_messages_flow
        from .services.gmail_commands import _svc as _gmail_svc
        svc = _gmail_svc(ctx)
        run_gmail_messages_flow(svc, cfg, msg_ref=reference)
    elif res in ('drive', 'file'):
        from .ui.human_flows import run_drive_files_flow
        svc = get_drive_service(ctx)
        run_drive_files_flow(svc, cfg, file_ref=reference)
    elif res in ('tasks', 'task'):
        from .ui.human_flows import run_tasks_items_flow
        svc = get_tasks_service(ctx)
        run_tasks_items_flow(svc, cfg, task_ref=reference)
    elif res == 'chat':
        from .ui.human_flows import run_chat_messages_flow
        svc = get_chat_service(ctx)
        run_chat_messages_flow(svc, cfg, msg_ref=reference)
    elif res == 'docs':
        from .ui.human_flows import run_docs_flow
        svc = get_docs_service(ctx)
        drive_svc = get_drive_service(ctx)
        run_docs_flow(svc, drive_svc, cfg, doc_ref=reference)
    elif res == 'sheets':
        from .ui.human_flows import run_sheets_flow
        svc = get_sheets_service(ctx)
        drive_svc = get_drive_service(ctx)
        run_sheets_flow(svc, drive_svc, cfg, sheet_ref=reference)
    elif res in ('events', 'event-subscription'):
        from .ui.human_flows import run_events_subscription_flow
        svc = get_events_service(ctx)
        run_events_subscription_flow(svc, cfg, sub_ref=reference)
    elif res in ('script', 'apps-script'):
        from .ui.human_flows import run_script_projects_flow
        svc = get_apps_script_service(ctx)
        drive_svc = get_drive_service(ctx)
        run_script_projects_flow(svc, drive_svc, cfg, script_ref=reference)
    elif res in ('admin', 'admin-user'):
        from .ui.human_flows import run_admin_users_flow
        svc = get_admin_service(ctx)
        run_admin_users_flow(svc, cfg, user_ref=reference)
    elif res in ('identity', 'identity-group'):
        from .ui.human_flows import run_identity_groups_flow
        svc = get_cloud_identity_service(ctx)
        run_identity_groups_flow(svc, cfg, group_ref=reference)
    elif res in ('search', 'cloud-search'):
        from .ui.human_flows import run_cloud_search_flow
        svc = get_cloud_search_service(ctx)
        run_cloud_search_flow(svc, query=reference)
    elif res == 'forms':
        from .ui.human_flows import run_forms_flow
        svc = get_forms_service(ctx)
        drive_svc = get_drive_service(ctx)
        run_forms_flow(svc, drive_svc, cfg, form_ref=reference)
    elif res in ('activity', 'drive-activity'):
        from .ui.human_flows import run_drive_activity_flow
        svc = get_drive_activity_service(ctx)
        run_drive_activity_flow(svc)
    else:
        print_error(f"Info not supported for resource: {resource}")


@cli.command('alias')
@click.argument('resource')
@click.argument('reference')
@click.argument('alias_name')
@click.pass_context
def universal_alias(ctx, resource, reference, alias_name):
    """Create a human-friendly alias: hermes alias <RESOURCE> <REF> <ALIAS_NAME>"""
    from .services.resource_resolver import GlobalResourceResolver
    res = resource.lower()
    cfg = ctx.obj.get('config_manager')
    if not cfg:
        print_error("Config manager unavailable.")
        return

    items = []
    res_name = resource.capitalize()
    if res in ('calendar', 'calendars'):
        from .services.calendar_resolver import CalendarResolver
        svc = CalendarService(ctx.obj['oauth_manager'])
        items = CalendarResolver.get_calendars(svc)
        res_name = "Calendar"
    elif res in ('drive', 'file', 'files'):
        svc = get_drive_service(ctx)
        items = svc.list_files().get('files', [])
        res_name = "File"
    elif res in ('tasks', 'task', 'tasklist'):
        svc = get_tasks_service(ctx)
        items = svc.list_task_lists().get('items', [])
        res_name = "Task List"
    elif res in ('chat', 'space', 'spaces'):
        svc = get_chat_service(ctx)
        items = svc.list_spaces().get('spaces', [])
        res_name = "Chat Space"
    elif res in ('meet', 'meeting'):
        svc = MeetService(ctx.obj['oauth_manager'])
        items = svc.list_spaces()
        res_name = "Meeting Space"
    elif res in ('gmail', 'message', 'messages'):
        from .services.gmail_commands import _svc as _gmail_svc
        svc = _gmail_svc(ctx)
        items = svc.list_messages(max_results=20).get('messages', [])
        res_name = "Message"

    ok, msg = GlobalResourceResolver.set_alias(res, reference, alias_name, items, cfg, resource_type=res_name)
    if ok:
        print_success(f"Alias created: {msg}")
    else:
        print_error(f"Failed to create alias: {msg}")


cli.add_command(universal_delete, name='rm')


# ---------------------------------------------------------------------------
# Specialized Action Verbs
# ---------------------------------------------------------------------------

@cli.command('upload')
@click.argument('resource')
@click.argument('file_path')
@click.option('--name', help='Remote filename in Drive')
@click.option('--folder', help='Parent folder ID')
@click.pass_context
def universal_upload(ctx, resource, file_path, name=None, folder=None):
    """Universal upload command: hermes upload drive <FILE_PATH>"""
    if resource.lower() == 'drive':
        svc = get_drive_service(ctx)
        uploaded = svc.upload_file(file_path, name=name, folder_id=folder)
        if uploaded:
            print_success(f"File uploaded! ID: {uploaded.get('id')}")
    else:
        print_error(f"Upload not supported for {resource}")


@cli.command('download')
@click.argument('resource')
@click.argument('file_id')
@click.argument('destination', required=False)
@click.option('--dest', help='Destination path')
@click.pass_context
def universal_download(ctx, resource, file_id, destination=None, dest=None):
    """Universal download command: hermes download drive <FILE_ID> [DEST]"""
    if resource.lower() == 'drive':
        svc = get_drive_service(ctx)
        target_path = dest or destination or f"download_{file_id}"
        if svc.download_file(file_id, target_path):
            print_success(f"File {file_id} downloaded successfully to {target_path}")
    else:
        print_error(f"Download not supported for {resource}")


@cli.command('rename')
@click.argument('resource')
@click.argument('target_id')
@click.argument('new_name')
@click.argument('extra_arg', required=False)
@click.pass_context
def universal_rename(ctx, resource, target_id, new_name, extra_arg=None):
    """Universal rename command: hermes rename drive <FILE_ID> <NEW_NAME>"""
    res = resource.lower()
    if res == 'drive':
        svc = get_drive_service(ctx)
        if svc.rename_file(target_id, new_name):
            print_success(f"Drive file renamed to {new_name}")
    elif res == 'sheet-tab':
        svc = get_sheets_service(ctx)
        tab_id = int(new_name)
        title = extra_arg or click.prompt("New Tab Name")
        if svc.rename_sheet_tab(target_id, tab_id, title):
            print_success(f"Sheet tab renamed to {title}")
    else:
        print_error(f"Rename not supported for {resource}")


@cli.command('move')
@click.argument('resource')
@click.argument('target_id')
@click.argument('destination_id')
@click.pass_context
def universal_move(ctx, resource, target_id, destination_id):
    """Universal move command: hermes move drive <FILE_ID> <FOLDER_ID>"""
    res = resource.lower()
    if res == 'drive':
        svc = get_drive_service(ctx)
        if svc.move_file(target_id, destination_id):
            print_success(f"File {target_id} moved to folder {destination_id}")
    elif res in ('tasks', 'task'):
        svc = get_tasks_service(ctx)
        if svc.move_task(target_id, parent=destination_id):
            print_success(f"Task {target_id} moved.")
    else:
        print_error(f"Move not supported for {resource}")


cli.add_command(universal_move, name='mv')


@cli.command('copy')
@click.argument('resource')
@click.argument('target_id')
@click.option('--name', help='New copy name')
@click.option('--title', help='New copy title')
@click.pass_context
def universal_copy(ctx, resource, target_id, name=None, title=None):
    """Universal copy command: hermes copy drive <FILE_ID>"""
    if resource.lower() == 'drive':
        svc = get_drive_service(ctx)
        copy_name = name or title
        copied = svc.copy_file(target_id, new_name=copy_name)
        if copied:
            print_success(f"File copied successfully! New ID: {copied.get('id')}")
    else:
        print_error(f"Copy not supported for {resource}")


cli.add_command(universal_copy, name='cp')


@cli.command('trash')
@click.argument('resource')
@click.argument('target_id')
@click.pass_context
def universal_trash(ctx, resource, target_id):
    """Universal trash command: hermes trash drive <FILE_ID>"""
    if resource.lower() == 'drive':
        svc = get_drive_service(ctx)
        if svc.trash_file(target_id):
            print_success(f"File {target_id} moved to trash.")
    else:
        print_error(f"Trash not supported for {resource}")


@cli.command('restore')
@click.argument('resource')
@click.argument('target_id')
@click.pass_context
def universal_restore(ctx, resource, target_id):
    """Universal restore command: hermes restore drive <FILE_ID>"""
    if resource.lower() == 'drive':
        svc = get_drive_service(ctx)
        if svc.restore_file(target_id):
            print_success(f"File {target_id} restored from trash.")
    else:
        print_error(f"Restore not supported for {resource}")


@cli.command('complete')
@click.argument('resource')
@click.argument('target_id')
@click.pass_context
def universal_complete(ctx, resource, target_id):
    """Universal complete command: hermes complete tasks <TASK_ID>"""
    if resource.lower() in ('tasks', 'task'):
        svc = get_tasks_service(ctx)
        if svc.complete_task(target_id):
            print_success(f"Task {target_id} marked as completed.")
    else:
        print_error(f"Complete not supported for {resource}")


@cli.command('uncomplete')
@click.argument('resource')
@click.argument('target_id')
@click.pass_context
def universal_uncomplete(ctx, resource, target_id):
    """Universal uncomplete command: hermes uncomplete tasks <TASK_ID>"""
    if resource.lower() in ('tasks', 'task'):
        svc = get_tasks_service(ctx)
        if svc.uncomplete_task(target_id):
            print_success(f"Task {target_id} reopened.")
    else:
        print_error(f"Uncomplete not supported for {resource}")


@cli.command('clear')
@click.argument('resource')
@click.argument('target_id', required=False)
@click.argument('extra_arg', required=False)
@click.pass_context
def universal_clear(ctx, resource, target_id=None, extra_arg=None):
    """Universal clear command: hermes clear tasks [LIST_ID] | hermes clear sheets <ID> <RANGE>"""
    res = resource.lower()
    if res in ('tasks', 'task'):
        svc = get_tasks_service(ctx)
        if svc.clear_completed(task_list_id=target_id or "@default"):
            print_success("Completed tasks cleared.")
    elif res == 'sheets':
        if not target_id:
            target_id = click.prompt("Spreadsheet ID")
        rng = extra_arg or click.prompt("Range to clear (e.g. Sheet1!A1:B10)")
        svc = get_sheets_service(ctx)
        if svc.clear_range(target_id, range_name=rng):
            print_success(f"Range {rng} cleared.")
    else:
        print_error(f"Clear not supported for {resource}")


@cli.command('read')
@click.argument('resource')
@click.argument('target_id')
@click.argument('range_str', required=False)
@click.pass_context
def universal_read(ctx, resource, target_id, range_str=None):
    """Universal read command: hermes read docs <ID> | hermes read sheets <ID> [RANGE]"""
    res = resource.lower()
    if res == 'docs':
        svc = get_docs_service(ctx)
        doc = svc.get_document(target_id)
        if doc:
            title = doc.get('title') or doc.get('name') or target_id
            print_header(f"📄 {title}")
            print(doc.get('content', ''))
    elif res == 'sheets':
        svc = get_sheets_service(ctx)
        data = svc.read_range(target_id, range_name=range_str or 'Sheet1!A1:Z100')
        if data:
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                if len(data) > 1:
                    headers = [str(c) for c in data[0]]
                    rows = [dict(zip(headers, [str(c) for c in row])) for row in data[1:]]
                    print(format_output(rows, format_type='table'))
                else:
                    rows = [{'Column ' + str(i+1): str(v) for i, v in enumerate(data[0])}]
                    print(format_output(rows, format_type='table'))
            else:
                print(format_output(data, format_type='table'))
    elif res == 'forms':
        svc = get_forms_service(ctx)
        form = svc.get_form(target_id)
        if form:
            print(format_output(form, format_type='table'))
    else:
        print_error(f"Read not supported for {resource}")


@cli.command('write')
@click.argument('resource')
@click.argument('target_id')
@click.argument('range_str')
@click.option('--data', help='Data to write')
@click.option('--values', help='Values to write (comma-separated)')
@click.pass_context
def universal_write(ctx, resource, target_id, range_str, data=None, values=None):
    """Universal write command: hermes write sheets <SPREADSHEET_ID> <RANGE>"""
    val_str = values or data or ""
    if resource.lower() == 'sheets':
        svc = get_sheets_service(ctx)
        vals = [[item.strip() for item in val_str.split(',')]] if val_str else [[""]]
        if svc.write_range(target_id, range_name=range_str, values=vals):
            print_success("Range updated successfully")
    else:
        print_error(f"Write not supported for {resource}")


@cli.command('append')
@click.argument('resource')
@click.argument('target_id')
@click.argument('content', required=False)
@click.option('--text', help='Text to append')
@click.option('--values', help='Values to append')
@click.pass_context
def universal_append(ctx, resource, target_id, content=None, text=None, values=None):
    """Universal append command: hermes append docs <ID> [TEXT] | sheets <ID> <RANGE>"""
    res = resource.lower()
    if res == 'docs':
        svc = get_docs_service(ctx)
        text_content = text or content or ""
        if svc.append_text(target_id, text_content):
            print_success("Text appended to document")
    elif res == 'sheets':
        svc = get_sheets_service(ctx)
        val_content = values or content or ""
        vals = [item.strip() for item in val_content.split(',')] if val_content else [""]
        rng = content if (values and content) else 'Sheet1'
        if svc.append_row(target_id, values=vals, range_name=rng):
            print_success("Row appended to spreadsheet")
    else:
        print_error(f"Append not supported for {resource}")


@cli.command('insert')
@click.argument('resource')
@click.argument('target_id')
@click.argument('content', required=False)
@click.option('--text', help='Text to insert')
@click.option('--index', default=1, type=int, help='Index position')
@click.pass_context
def universal_insert(ctx, resource, target_id, content=None, text=None, index=1):
    """Universal insert command: hermes insert docs <DOCUMENT_ID>"""
    text_content = text or content or ""
    if resource.lower() == 'docs':
        svc = get_docs_service(ctx)
        if svc.insert_text(target_id, text_content, index=index):
            print_success("Text inserted into document")
    else:
        print_error(f"Insert not supported for {resource}")


@cli.command('run')
@click.argument('resource')
@click.argument('script_id')
@click.argument('func_name', required=False)
@click.option('--function', help='Function name to execute')
@click.pass_context
def universal_run(ctx, resource, script_id, func_name=None, function=None):
    """Universal run command: hermes run script <SCRIPT_ID> [FUNCTION]"""
    if resource.lower() in ('script', 'scripts'):
        fn = function or func_name or "main"
        svc = get_apps_script_service(ctx)
        res = svc.run_script(script_id, fn)
        if res:
            res_val = res.get('result', res) if isinstance(res, dict) else res
            print_success(f"Script executed! Result: {res_val}")
    else:
        print_error(f"Run not supported for {resource}")


@cli.command('suspend')
@click.argument('resource')
@click.argument('target_id')
@click.pass_context
def universal_suspend(ctx, resource, target_id):
    """Universal suspend command: hermes suspend admin-user <USER_ID>"""
    if resource.lower() == 'admin-user':
        svc = get_admin_service(ctx)
        if svc.suspend_user(target_id, suspend=True):
            print_success(f"User {target_id} suspended.")
    else:
        print_error(f"Suspend not supported for {resource}")


@cli.command('unsuspend')
@click.argument('resource')
@click.argument('target_id')
@click.pass_context
def universal_unsuspend(ctx, resource, target_id):
    """Universal unsuspend command: hermes unsuspend admin-user <USER_ID>"""
    if resource.lower() == 'admin-user':
        svc = get_admin_service(ctx)
        if svc.suspend_user(target_id, suspend=False):
            print_success(f"User {target_id} unsuspended.")
    else:
        print_error(f"Unsuspend not supported for {resource}")


@cli.command('activity')
@click.argument('resource')
@click.argument('target_id')
@click.pass_context
def universal_activity(ctx, resource, target_id):
    """Universal activity command: hermes activity drive <FILE_ID>"""
    if resource.lower() == 'drive':
        svc = get_drive_activity_service(ctx)
        act = svc.query_activity(item_name=target_id)
        activities = act.get('activities', []) if isinstance(act, dict) else act
        print(format_output(activities, 'table'))
    else:
        print_error(f"Activity not supported for {resource}")


@cli.command('add')
@click.argument('resource')
@click.argument('target_id')
@click.argument('user')
@click.option('--role', default='ROLE_MEMBER')
@click.pass_context
def universal_add(ctx, resource, target_id, user, role='ROLE_MEMBER'):
    """Universal add command: hermes add <RESOURCE> <TARGET_ID> <USER>"""
    res = resource.lower()
    if res == 'chat-member':
        from .services.chat_commands import chat_add_member
        ctx.invoke(chat_add_member, space_id=target_id, user=user)
    elif res == 'drive-permission':
        svc = get_drive_service(ctx)
        if svc.add_permission(target_id, user, role=role.lower()):
            print_success(f"Permission added for {user} on file {target_id}")
    elif res == 'admin-group-member':
        svc = get_admin_service(ctx)
        if svc.add_group_member(target_id, user, role=role):
            print_success(f"User {user} added to group {target_id}")
    elif res == 'identity-member':
        svc = get_cloud_identity_service(ctx)
        if svc.add_member(target_id, user, role=role):
            print_success(f"User {user} added to identity group {target_id}")
    elif res == 'form-item':
        svc = get_forms_service(ctx)
        if svc.add_form_item(target_id, title=user):
            print_success(f"Form item added to {target_id}")
    else:
        print_error(f"Add not supported for resource: {resource}")


@cli.command('remove')
@click.argument('resource')
@click.argument('target_id')
@click.argument('user')
@click.option('--yes', '-y', is_flag=True)
@click.pass_context
def universal_remove(ctx, resource, target_id, user, yes=False):
    """Universal remove command: hermes remove <RESOURCE> <TARGET_ID> <USER>"""
    res = resource.lower()
    if res == 'chat-member':
        from .services.chat_commands import chat_remove_member
        ctx.invoke(chat_remove_member, space_id=target_id, user=user, yes=yes)
    elif res == 'drive-permission':
        svc = get_drive_service(ctx)
        if svc.remove_permission(target_id, user):
            print_success(f"Permission {user} removed from file {target_id}")
    elif res == 'admin-group-member':
        svc = get_admin_service(ctx)
        if svc.remove_group_member(target_id, user):
            print_success(f"User {user} removed from group {target_id}")
    elif res == 'identity-member':
        svc = get_cloud_identity_service(ctx)
        if svc.remove_member(user):
            print_success(f"Member {user} removed.")
    else:
        print_error(f"Remove not supported for resource: {resource}")


@cli.command('send')
@click.argument('resource')
@click.argument('target')
@click.option('--message', '-m', help='Message content')
@click.option('--thread-key', help='Thread key for chat')
@click.pass_context
def universal_send(ctx, resource, target, message=None, thread_key=None):
    """Universal send command: hermes send <RESOURCE> <TARGET> [-m MESSAGE]"""
    res = resource.lower()
    if res == 'chat':
        svc = get_chat_service(ctx)
        if not message:
            message = click.prompt("Message")
        created = svc.send_message(target, message, thread_key=thread_key)
        if created:
            print_success(f"Message sent successfully! (ID: {created.get('name', '')})")
    elif res == 'gmail':
        from .services.gmail_commands import gmail_send
        ctx.invoke(gmail_send, to=target, body=message)
    else:
        print_error(f"Send not supported for resource: {resource}")


@cli.command('reply')
@click.argument('resource')
@click.argument('target')
@click.option('--message', '-m', help='Reply message text')
@click.option('--space-id', help='Space ID if message is in chat')
@click.pass_context
def universal_reply(ctx, resource, target, message=None, space_id=None):
    """Universal reply command: hermes reply <RESOURCE> <TARGET> [-m MESSAGE]"""
    res = resource.lower()
    if res == 'chat':
        svc = get_chat_service(ctx)
        if not message:
            message = click.prompt("Reply text")
        replied = svc.reply_message(target, message, space_id=space_id)
        if replied:
            print_success(f"Reply posted successfully! (ID: {replied.get('name', '')})")
    else:
        print_error(f"Reply not supported for resource: {resource}")


@cli.command('edit')
@click.argument('resource')
@click.argument('target')
@click.option('--message', '-m', help='Updated message text')
@click.option('--title', help='Updated title')
@click.option('--notes', help='Updated notes')
@click.option('--space-id', help='Space ID if chat')
@click.pass_context
def universal_edit(ctx, resource, target, message=None, title=None, notes=None, space_id=None):
    """Universal edit command: hermes edit <RESOURCE> <TARGET> [OPTIONS]"""
    res = resource.lower()
    if res == 'chat':
        svc = get_chat_service(ctx)
        if not message:
            message = click.prompt("Updated message text")
        edited = svc.edit_message(target, message, space_id=space_id)
        if edited:
            print_success(f"Message updated successfully! (ID: {edited.get('name', '')})")
    elif res in ('task', 'tasks'):
        svc = get_tasks_service(ctx)
        updated = svc.update_task(target, title=title, notes=notes)
        if updated:
            print_success(f"Task {target} updated successfully.")
    else:
        print_error(f"Edit not supported for resource: {resource}")


@cli.command('react')
@click.argument('resource')
@click.argument('target')
@click.argument('emoji')
@click.option('--space-id', help='Space ID if chat')
@click.pass_context
def universal_react(ctx, resource, target, emoji, space_id=None):
    """Universal react command: hermes react <RESOURCE> <TARGET> <EMOJI>"""
    res = resource.lower()
    if res == 'chat':
        svc = get_chat_service(ctx)
        res_data = svc.create_reaction(target, emoji, space_id=space_id)
        if res_data:
            print_success(f"Reaction '{emoji}' added to message {target}.")
    else:
        print_error(f"React not supported for resource: {resource}")


@cli.command('unreact')
@click.argument('resource')
@click.argument('target')
@click.option('--space-id', help='Space ID if chat')
@click.pass_context
def universal_unreact(ctx, resource, target, space_id=None):
    """Universal unreact command: hermes unreact <RESOURCE> <TARGET>"""
    res = resource.lower()
    if res == 'chat':
        svc = get_chat_service(ctx)
        ok = svc.delete_reaction(target, space_id=space_id)
        if ok:
            print_success(f"Reaction {target} removed.")
    else:
        print_error(f"Unreact not supported for resource: {resource}")


@cli.command('status')
@click.argument('resource', required=False)
@click.pass_context
def top_status(ctx, resource=None):
    """Check authentication or service status: hermes status [RESOURCE]"""
    if not resource:
        ctx.invoke(status)
        return
    res = resource.lower()
    if res == 'chat':
        from .services.chat_commands import chat_status
        ctx.invoke(chat_status)
        return
    mapping = {
        'chat': (get_chat_service, 'Google Chat API v1'),
        'drive': (get_drive_service, 'Google Drive API v3'),
        'tasks': (get_tasks_service, 'Google Tasks API v1'),
        'docs': (get_docs_service, 'Google Docs API v1'),
        'sheets': (get_sheets_service, 'Google Sheets API v4'),
        'events': (get_events_service, 'Google Workspace Events API v1'),
        'apps-script': (get_apps_script_service, 'Google Apps Script API v1'),
        'admin': (get_admin_service, 'Google Admin SDK Directory API'),
        'identity': (get_cloud_identity_service, 'Google Cloud Identity API v1'),
        'cloud-search': (get_cloud_search_service, 'Google Cloud Search API v1'),
        'forms': (get_forms_service, 'Google Forms API v1'),
        'drive-activity': (get_drive_activity_service, 'Google Drive Activity API v2'),
    }
    if res in mapping:
        getter, label = mapping[res]
        svc = getter(ctx)
        test_res = svc.test_connection()
        print_header(f"📊 {label} Status")
        print_key_value_pairs({
            'Service': label,
            'Status': test_res.get('status', 'Unknown'),
            'Message': test_res.get('message', 'N/A')
        })
    else:
        print_error(f"Unknown service: {resource}")


@cli.command('profile')
@click.argument('resource', required=False)
@click.pass_context
def top_profile(ctx, resource=None):
    """View profile for a resource/service: hermes profile [RESOURCE]"""
    if not resource:
        ctx.invoke(top_status)
        return
    res = resource.lower()
    if res == 'chat':
        from .services.chat_commands import chat_status
        ctx.invoke(chat_status)
    elif res == 'gmail':
        from .services.gmail_commands import _svc as _gmail_svc
        svc = _gmail_svc(ctx)
        prof = svc.get_profile()
        print_header("📧 Gmail Profile")
        print_key_value_pairs(prof)
    elif res == 'drive':
        svc = get_drive_service(ctx)
        prof = svc.get_profile()
        print_header("📁 Drive Profile & Quota")
        print_key_value_pairs(prof)
    elif res == 'tasks':
        svc = get_tasks_service(ctx)
        lists = svc.list_task_lists()
        print_header("✅ Tasks Profile")
        print_key_value_pairs({'Accessible Task Lists': len(lists.get('items', []))})
    elif res == 'docs':
        svc = get_docs_service(ctx)
        prof = svc.get_profile()
        print_header("📄 Docs Profile")
        print_key_value_pairs(prof)
    elif res == 'sheets':
        svc = get_sheets_service(ctx)
        prof = svc.get_profile()
        print_header("📊 Sheets Profile")
        print_key_value_pairs(prof)
    elif res == 'forms':
        svc = get_forms_service(ctx)
        prof = svc.get_profile()
        print_header("📋 Forms Profile")
        print_key_value_pairs(prof)
    elif res in ('personal', 'user', 'me'):
        from .profile.commands import profile_show
        ctx.invoke(profile_show)
    else:
        ctx.invoke(top_status, resource=resource)




def main():
    """Main entry point"""
    try:
        cli()
    except KeyboardInterrupt:
        print_info("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        if '--debug' in sys.argv:
            logging.exception("Unexpected error")
        print_error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
