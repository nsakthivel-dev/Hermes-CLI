"""
AI command implementations
"""

import click
import logging
import re
from colorama import Fore, Style
from typing import Dict, Any, List, Optional

from ..auth.oauth import OAuthManager
from ..services.calendar import CalendarService
from ..services.gmail import GmailService
from ..services.profile_resolver import ProfileResolver, PersonalProfileService, PersonalProfileRepository
from ..utils.formatters import (
    print_success, print_info, print_error, format_output, print_header, validate_email
)
from .nlp import NaturalLanguageProcessor
from .summarizer import EmailSummarizer
from .analytics import AIAnalytics
from .chatbot import AIChatBot

logger = logging.getLogger(__name__)


def _extract_prompt_overrides(prompt: str) -> Dict[str, str]:
    """Extract explicit details provided by the user in the prompt to override profile defaults."""
    overrides = {}
    m = re.search(
        r'(?:my\s+manager\s+is\s+|manager\s+is\s+|reporting\s+to\s+manager\s+|reporting\s+to\s+)([A-Za-z]+)',
        prompt,
        re.IGNORECASE
    )
    if m:
        overrides['manager_name'] = m.group(1).strip()

    d = re.search(r'(?:for\s+)?(\d+\s+days?)', prompt, re.IGNORECASE)
    if d:
        overrides['duration'] = d.group(1).strip()

    return overrides


@click.group()
def ai():
    """AI-powered commands and features"""
    pass


@ai.command('ask')
@click.argument('query', required=True)
@click.option('--execute', is_flag=True, help='Execute the suggested command')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']))
@click.pass_context
def ai_ask(ctx, query, execute, format):
    """Ask AI in natural language and get command suggestions"""
    config_manager = ctx.obj.get('config_manager')
    nlp = NaturalLanguageProcessor(config_manager)
    
    print_header("🤖 AI Command Assistant")
    print(f"Query: {query}")
    print()
    
    # Parse the natural language query
    parsed = nlp.parse_command(query)
    
    print_section("Intent Analysis")
    print(f"Intent: {parsed['intent']}")
    print(f"Confidence: {parsed['confidence'] * 100}%")
    
    if parsed['entities']:
        print("Entities found:")
        for entity_type, value in parsed['entities'].items():
            if isinstance(value, list):
                print(f"  {entity_type}: {', '.join(str(v) for v in value)}")
            else:
                print(f"  {entity_type}: {value}")
    
    print()
    
    # Suggest command
    suggested_command = nlp.suggest_command(query)
    print_section("Suggested Command")
    print(f"$ {suggested_command}")
    
    # Execute if requested
    if execute and not suggested_command.startswith('#'):
        print()
        print_section("Executing Command")
        try:
            # This is a simplified execution - in production, you'd want proper command routing
            if 'calendar' in suggested_command:
                # Execute calendar command
                service = CalendarService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))
                events = service.list_events()
                if events:
                    formatted_events = []
                    for event in events[:10]:  # Limit to 10 for demo
                        formatted_events.append({
                            'ID': event['id'][:15] + '...',
                            'Title': event['summary'][:30],
                            'Start': event['start'][:10],
                            'End': event['end'][:10]
                        })
                    output = format_output(formatted_events, format_type=format)
                    print(output)
                else:
                    print_info("No events found")
            
            elif 'gmail' in suggested_command:
                # Execute gmail command
                service = GmailService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))
                emails = service.list_messages(max_results=10)
                if emails:
                    formatted_emails = []
                    for email in emails:
                        formatted_emails.append({
                            'ID': email['id'][:15] + '...',
                            'From': email['from'][:30],
                            'Subject': email['subject'][:40],
                            'Date': email['date'][:10],
                            'Snippet': email['snippet'][:50] + '...'
                        })
                    output = format_output(formatted_emails, format_type=format)
                    print(output)
                else:
                    print_info("No emails found")
            
            print_success("Command executed successfully!")
            
        except Exception as e:
            print_error(f"Error executing command: {e}")


@ai.command('summarize')
@click.option('--period', default='recent', type=click.Choice(['today', 'week', 'recent']))
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']))
@click.pass_context
def ai_summarize(ctx, period, format):
    """AI-powered summary of your emails and calendar"""
    config_manager = ctx.obj.get('config_manager')
    summarizer = EmailSummarizer(config_manager)
    
    print_header("📊 AI Summary")
    print(f"Period: {period}")
    print()
    
    try:
        # Get emails
        gmail_service = GmailService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))
        emails = gmail_service.list_messages(max_results=20)
        
        if not emails:
            print_info("No emails found for summary")
            return
        
        # Generate summary
        summary = summarizer.summarize_multiple_emails(emails)
        
        print_section("Email Summary")
        print(f"📧 {summary['summary']}")
        
        if summary['themes']:
            print(f"🏷️  Themes: {', '.join(summary['themes'])}")
        
        if summary['urgent_emails'] > 0:
            print(f"⚠️  {summary['urgent_emails']} urgent emails")
        
        print()
        
        # Show insights
        if summary['insights']:
            print_section("AI Insights")
            for insight in summary['insights']:
                print(f"💡 {insight}")
            print()
        
        # Show top senders
        if summary['top_senders']:
            print_section("Top Communicators")
            for sender, count in summary['top_senders'][:5]:
                print(f"📨 {sender}: {count} emails")
            print()
        
        # Show sentiment breakdown
        if format == 'table':
            print_section("Sentiment Analysis")
            sentiment_data = []
            for sentiment_type, count in summary['sentiment_breakdown'].items():
                sentiment_data.append({
                    'Type': sentiment_type.capitalize(),
                    'Count': count,
                    'Percentage': round(count / summary['total_emails'] * 100, 1)
                })
            output = format_output(sentiment_data, format_type=format)
            print(output)
        
    except Exception as e:
        print_error(f"Error generating summary: {e}")


@ai.command('analytics')
@click.argument('type_', default='overview', type=click.Choice(['overview', 'productivity', 'email', 'calendar']))
@click.option('--period', default='week', type=click.Choice(['day', 'week', 'month']))
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']))
@click.pass_context
def ai_analytics(ctx, type_, period, format):
    """AI-powered productivity analytics"""
    config_manager = ctx.obj.get('config_manager')
    analytics = AIAnalytics(config_manager)
    
    print_header("📈 AI Analytics")
    print(f"Type: {type_}")
    print(f"Period: {period}")
    print()
    
    try:
        # Get data
        gmail_service = GmailService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))
        calendar_service = CalendarService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))
        
        emails = gmail_service.list_messages(max_results=50)
        events = calendar_service.list_events(max_results=50)
        
        # Generate analysis
        analysis = analytics.analyze_productivity(emails, events, period)
        
        if 'message' in analysis:
            print_info(analysis['message'])
            return
        
        # Show productivity score
        print_section("Productivity Score")
        score = analysis['productivity_score']
        score_emoji = "🏆" if score >= 80 else "✅" if score >= 60 else "⚠️" if score >= 40 else "❌"
        print(f"{score_emoji} {score}/100")
        print()
        
        # Show insights
        if analysis['insights']:
            print_section("AI Insights")
            for insight in analysis['insights']:
                print(f"💡 {insight}")
            print()
        
        # Show recommendations
        if analysis['recommendations']:
            print_section("Recommendations")
            for i, rec in enumerate(analysis['recommendations'], 1):
                print(f"{i}. {rec}")
            print()
        
        # Show detailed analysis based on type
        if type_ == 'email' and analysis['email_analysis']:
            print_section("Email Analysis")
            email_data = analysis['email_analysis']
            print(f"📧 Total emails: {email_data['total']}")
            print(f"📊 Emails per day: {email_data['emails_per_day']}")
            print(f"📈 Recent emails: {email_data['recent_emails']}")
            print()
        
        elif type_ == 'calendar' and analysis['calendar_analysis']:
            print_section("Calendar Analysis")
            calendar_data = analysis['calendar_analysis']
            print(f"📅 Total events: {calendar_data['total']}")
            print(f"🤝 Meetings: {calendar_data['meetings']}")
            print(f"🏠 Personal events: {calendar_data['personal']}")
            print()
        
        elif type_ == 'productivity':
            print_section("Time Analysis")
            time_data = analysis['time_analysis']
            if time_data['peak_hours']:
                print(f"⏰ Peak hours: {', '.join(time_data['peak_hours'])}")
            print()
        
        # Format detailed data if requested
        if format == 'json':
            print_section("Full Analysis Data")
            print(format_output([analysis], format_type='json'))
        
    except Exception as e:
        print_error(f"Error generating analytics: {e}")


@ai.command('smart-reply')
@click.argument('email_id')
@click.option('--count', default=3, help='Number of smart replies to generate')
@click.pass_context
def ai_smart_reply(ctx, email_id, count):
    """Generate AI-powered smart replies for an email"""
    config_manager = ctx.obj.get('config_manager')
    summarizer = EmailSummarizer(config_manager)
    
    print_header("🤖 Smart Reply Generator")
    print(f"Email ID: {email_id}")
    print()
    
    try:
        # Get email
        gmail_service = GmailService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))
        email = gmail_service.get_message(email_id)
        
        if not email:
            print_error("Email not found")
            return
        
        # Generate summary and smart replies
        summary = summarizer.summarize_email(email)
        
        print_section("Email Summary")
        print(f"📝 {summary['summary']}")
        print(f"😊 Sentiment: {summary['sentiment']}")
        print(f"⚡ Urgency: {summary['urgency']}")
        print()
        
        if summary['action_items']:
            print_section("Action Items")
            for i, action in enumerate(summary['action_items'], 1):
                print(f"{i}. {action}")
            print()
        
        print_section("Smart Replies")
        for i, reply in enumerate(summary['smart_replies'][:count], 1):
            print(f"{i}. {reply}")
        
        print()
        print_info("Choose a reply or compose your own response")
        
    except Exception as e:
        print_error(f"Error generating smart replies: {e}")


@ai.command('insights')
@click.option('--format', default='table', type=click.Choice(['table', 'json', 'csv']))
@click.pass_context
def ai_insights(ctx, format):
    """Generate AI-powered insights from your data"""
    config_manager = ctx.obj.get('config_manager')
    analytics = AIAnalytics(config_manager)
    summarizer = EmailSummarizer(config_manager)
    
    print_header("🧠 AI Insights")
    print()
    
    try:
        # Get data
        gmail_service = GmailService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))
        calendar_service = CalendarService(ctx.obj['oauth_manager'], ctx.obj.get('cache_manager'))
        
        emails = gmail_service.list_messages(max_results=30)
        events = calendar_service.list_events(max_results=30)
        
        # Generate comprehensive insights
        productivity_analysis = analytics.analyze_productivity(emails, events, 'week')
        email_summary = summarizer.summarize_multiple_emails(emails)
        
        # Productivity insights
        print_section("📈 Productivity Insights")
        if 'insights' in productivity_analysis:
            for insight in productivity_analysis['insights']:
                print(f"💡 {insight}")
        print()
        
        # Communication insights
        print_section("💬 Communication Insights")
        if email_summary['top_senders']:
            top_sender = email_summary['top_senders'][0]
            print(f"👥 Most communication with: {top_sender[0]} ({top_sender[1]} emails)")
        
        if email_summary['themes']:
            print(f"🏷️  Common themes: {', '.join(email_summary['themes'][:3])}")
        
        if email_summary['urgent_emails'] > 0:
            print(f"⚠️  {email_summary['urgent_emails']} emails need immediate attention")
        print()
        
        # Recommendations
        if 'recommendations' in productivity_analysis:
            print_section("🎯 AI Recommendations")
            for i, rec in enumerate(productivity_analysis['recommendations'][:5], 1):
                print(f"{i}. {rec}")
        
    except Exception as e:
        print_error(f"Error generating insights: {e}")


@ai.command(name='compose')
@click.argument('prompt')
@click.option('--to', help='Recipient email address')
@click.pass_context
def ai_compose(ctx, prompt, to):
    """Draft an email with AI and send it interactively"""
    config_manager = ctx.obj.get('config_manager') if ctx and ctx.obj else None
    nlp = NaturalLanguageProcessor(config_manager)
    
    print_header("✉️ AI Email Composer")
    print_info(f"Drafting email for: {prompt}")
    
    # Use existing ProfileResolver via service
    service = PersonalProfileService(repository=PersonalProfileRepository(config_manager=config_manager))
    resolver = ProfileResolver(service=service)

    # 1. Detect required/optional profile fields based on context
    context_info = resolver.get_context_fields(prompt)
    intent = context_info.get('intent', 'general')
    candidate_fields = context_info.get('all_fields', ['name'])

    # 2. Extract explicit user-provided details in prompt (Priority 1)
    user_overrides = _extract_prompt_overrides(prompt)

    # 3. Retrieve available profile data via ProfileResolver
    available_fields = {}
    missing_fields = []
    needs_confirmation = []

    for f in candidate_fields:
        if f in user_overrides:
            available_fields[f] = user_overrides[f]
        else:
            val = resolver.get(f)
            if val:
                available_fields[f] = val
                if not resolver.canAutoUse(f):
                    needs_confirmation.append(f)
            else:
                missing_fields.append(f)

    approved_profile = dict(available_fields)

    # 4. User confirmation for sensitive fields requiring confirmation
    if needs_confirmation:
        click.echo("\nProfile Information")
        click.echo("-" * 50)
        click.echo("\nThis email can use:\n")
        idx = 1
        for f, val in available_fields.items():
            disp = f.replace('_', ' ').title()
            masked_val = resolver.mask_value(f, val)
            click.echo(f"[{idx}] {disp}: {masked_val}")
            idx += 1
        click.echo()

        try:
            confirm_use = click.confirm("Use selected information?", default=True)
            if not confirm_use:
                for f in needs_confirmation:
                    approved_profile.pop(f, None)
        except (click.Abort, EOFError):
            pass

    # 5. Dynamic information follow-up for missing dates/durations
    if intent == 'leave_request' and 'duration' not in user_overrides:
        has_dates = bool(re.search(r'\b(?:\d+\s+days?|starting|from|to|today|tomorrow|until|dates?)\b', prompt, re.IGNORECASE))
        if not has_dates:
            try:
                click.echo("\nLeave duration/date is not specified.\n")
                click.echo("  [1] Enter start and end dates")
                click.echo("  [2] Enter number of days")
                click.echo("  [3] Continue without dates")
                date_choice = click.prompt("Select option", type=click.Choice(['1', '2', '3']), default='3')
                if date_choice == '1':
                    s_date = click.prompt("  Start date", default="")
                    e_date = click.prompt("  End date", default="")
                    if s_date or e_date:
                        prompt += f" (Leave from {s_date} to {e_date})"
                elif date_choice == '2':
                    days = click.prompt("  Number of days", default="")
                    if days:
                        prompt += f" (Leave for {days})"
            except (click.Abort, EOFError):
                pass

    # 6. Profile usage transparency summary
    click.echo("\nℹ Using saved profile information:")
    for f in candidate_fields:
        disp = f.replace('_', ' ').title()
        if f in approved_profile:
            click.echo(f"   {Fore.GREEN}✓{Style.RESET_ALL} {disp}")
        else:
            click.echo(f"   {Fore.YELLOW}⚠{Style.RESET_ALL} {disp} not available")
    click.echo()

    email_context = {
        'intent': intent,
        'recipient': to or ('HR Team' if 'hr' in prompt.lower() else ''),
    }

    draft = nlp.draft_email(prompt, profile_context=approved_profile, email_context=email_context)
    if not draft:
        print_error("Failed to draft email with AI.")
        return
        
    subject = draft.get('subject', 'No Subject')
    body = draft.get('body', '')
    
    while True:
        print("\n" + "="*40)
        if to:
            print(f"TO: {to}")
        else:
            print("TO: [NOT SPECIFIED]")
        print(f"SUBJECT: {subject}")
        print("-" * 40)
        print(body)
        print("="*40)
        
        choice = click.prompt(
            "\nActions", 
            type=click.Choice(['send', 'edit', 'discard'], case_sensitive=False),
            default='send'
        )
        
        if choice == 'discard':
            print_info("Draft discarded.")
            break
            
        elif choice == 'edit':
            # Create a temporary template for editing
            template = f"TO: {to or ''}\nSUBJECT: {subject}\n\n{body}"
            edited_text = click.edit(template)
            
            if edited_text:
                # Basic parsing of the edited text
                lines = edited_text.split('\n')
                new_to = to
                new_subject = subject
                body_start = 0
                
                # Simple parser for the header-like lines
                header_parsed = False
                for i, line in enumerate(lines):
                    if line.startswith('TO: '):
                        new_to = line.replace('TO: ', '').strip()
                        body_start = i + 1
                    elif line.startswith('SUBJECT: '):
                        new_subject = line.replace('SUBJECT: ', '').strip()
                        body_start = i + 1
                    elif line.strip() == '':
                        body_start = i + 1
                        header_parsed = True
                        break
                
                to = new_to
                subject = new_subject
                body = '\n'.join(lines[body_start:]).strip()
            continue
            
        elif choice == 'send':
            if not to:
                to = click.prompt("Please enter recipient email address")
            
            if not validate_email(to):
                print_error(f"Invalid email address: {to}")
                if click.confirm("Edit email address?"):
                    to = None
                    continue
                break

            try:
                oauth_manager = ctx.obj.get('oauth_manager') if ctx and ctx.obj else None
                gmail = GmailService(oauth_manager)
                gmail.send_message(to=to, subject=subject, body=body)
                print_success(f"Email successfully sent to {to}!")
                break
            except Exception as e:
                print_error(f"Failed to send email: {e}")
                if click.confirm("Would you like to edit the draft and try again?"):
                    continue
                break


@ai.command('chat')
@click.option('--model', help='Gemini model to use')
@click.pass_context
def ai_chat(ctx, model):
    """Start an interactive chat session with AI"""
    config_manager = ctx.obj.get('config_manager')
    api_key = config_manager.get('ai.gemini_api_key')
    config_model = config_manager.get('ai.model_name', 'gemini-3.6-flash')
    
    # Use provided model or fall back to config model
    model_to_use = model or config_model
    
    if not api_key:
        print_error("Gemini API key not configured.")
        print_info("Set it with: hermes config set ai.gemini_api_key YOUR_KEY")
        return

    chatbot = AIChatBot(gemini_key=api_key, model_name=model_to_use)
    
    print_header("💬 AI Chat Session")
    print_info(f"Model: {model_to_use}")
    print_info("Type 'exit', 'quit', or 'bye' to end the session.")
    print("-" * 40)
    
    while True:
        try:
            query = click.prompt(f"\n{Fore.CYAN}You")
            
            if query.lower() in ['exit', 'quit', 'bye']:
                print_info("Ending chat session. Goodbye!")
                break
            
            if not query.strip():
                continue
                
            print(f"\n{Fore.YELLOW}AI{Style.RESET_ALL}: ", end="", flush=True)
            response = chatbot.chat(query)
            print(response)
            
        except KeyboardInterrupt:
            print_info("\nEnding chat session. Goodbye!")
            break
        except Exception as e:
            print_error(f"Error: {e}")
            break


def print_section(title: str):
    """Print section header"""
    print(f"\n▶ {title}")
    print("-" * (len(title) + 3))
