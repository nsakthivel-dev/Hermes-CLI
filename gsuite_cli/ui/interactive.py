"""
Interactive CLI UI and menu system
"""

import os
import time
import sys
import shutil
import subprocess
import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Any, Optional
import click
from colorama import init, Fore, Style, Back
from ..config.manager import ConfigManager
from ..services.reminders import ReminderService
from ..services.calendar import CalendarService
from ..services.calendar_resolver import CalendarResolver
from ..auth.oauth import OAuthManager
from ..utils.formatters import print_error
from ..services.calendar_validators import (
    validate_datetime,
    validate_start_end_order,
    validate_title,
    validate_recurrence_choice,
    validate_weekdays,
    validate_month_day,
    validate_rrule,
    validate_end_condition,
    validate_until_date,
    validate_occurrence_count,
    validate_reminders,
    validate_notification_channels,
)

init(autoreset=True)


class InteractiveMenu:
    """Interactive CLI menu system with beautiful UI"""
    
    def __init__(self):
        self.options = {
            '1': {
                'name': '📅 Calendar',
                'description': 'Manage events and schedules',
                'color': Fore.CYAN,
                'commands': [
                    'list',
                    'create',
                    'update',
                    'delete',
                    'search',
                    'create-calendar',
                    'list-calendars',
                    'instances',
                    'booking-create',
                    'booking-book',
                    'booking-revoke',
                    'reminders-run',
                ]
            },
            '2': {
                'name': '📧 Gmail',
                'description': 'Read and send emails',
                'color': Fore.WHITE,
                'commands': ['list', 'search', 'compose', 'read', 'reply', 'forward', 'drafts', 'labels', 'threads', 'profile']
            },
            '3': {
                'name': '📊 Sheets',
                'description': 'Manage spreadsheets',
                'color': Fore.GREEN,
                'commands': ['list', 'read', 'write', 'create']
            },
            '4': {
                'name': '📄 Docs',
                'description': 'Manage documents',
                'color': Fore.YELLOW,
                'commands': ['list', 'create', 'read', 'update', 'search']
            },
            '5': {
                'name': '🎥 Meet',
                'description': 'Create and manage meetings',
                'color': Fore.LIGHTRED_EX,
                'commands': ['create', 'join', 'details', 'active', 'list', 'participants', 'recordings', 'transcripts', 'end']
            },
            '6': {
                'name': '🤖 AI Assistant',
                'description': 'AI-powered features',
                'color': Fore.MAGENTA,
                'commands': ['chat', 'ask', 'summarize', 'analytics', 'insights']
            },
            '7': {
                'name': '👤 Personal Profile',
                'description': 'Manage your reusable personal information',
                'color': Fore.LIGHTCYAN_EX,
                'commands': ['profile']
            },
            '8': {
                'name': '⚙️  Settings',
                'description': 'Configure and manage',
                'color': Fore.WHITE,
                'commands': ['config', 'cache', 'auth', 'login', 'logout']
            },
            '9': {
                'name': '📈 Analytics',
                'description': 'View productivity insights',
                'color': Fore.RED,
                'commands': ['productivity', 'usage', 'performance']
            },
            '10': {
                'name': '📋 Forms',
                'description': 'Create and edit forms, view responses',
                'color': Fore.LIGHTGREEN_EX,
                'commands': ['list', 'info', 'responses', 'create', 'edit']
            },
            '11': {
                'name': '👥 People',
                'description': 'View your contacts and colleagues',
                'color': Fore.LIGHTBLUE_EX,
                'commands': ['list']
            },
            '12': {
                'name': '📁 Drive',
                'description': 'Browse and search Drive files',
                'color': Fore.LIGHTCYAN_EX,
                'commands': ['list', 'edit', 'share', 'create', 'import']
            },
            '13': {
                'name': '✅ Tasks',
                'description': 'View and manage your tasks',
                'color': Fore.LIGHTWHITE_EX,
                'commands': ['lists', 'list', 'create', 'edit', 'delete']
            },
            '14': {
                'name': '🗄 BigQuery',
                'description': 'Run queries on BigQuery datasets',
                'color': Fore.LIGHTMAGENTA_EX,
                'commands': ['query']
            },
            '15': {
                'name': '🧪 Test',
                'description': 'Test all connections',
                'color': Fore.BLUE,
                'commands': ['connection']
            },
            '16': {
                'name': '💬 Chat',
                'description': 'Send messages and manage spaces',
                'color': Fore.CYAN,
                'commands': ['spaces', 'messages', 'send', 'reply', 'edit', 'delete', 'members', 'react', 'search', 'threads', 'test-connection']
            },
            '17': {
                'name': '🔔 Events',
                'description': 'Workspace event subscriptions',
                'color': Fore.LIGHTYELLOW_EX,
                'commands': ['list', 'create', 'delete', 'status']
            },
            '18': {
                'name': '📜 Apps Script',
                'description': 'Manage script projects and deployments',
                'color': Fore.LIGHTBLUE_EX,
                'commands': ['list', 'create', 'run', 'versions', 'deployments', 'status']
            },
            '19': {
                'name': '🛡️  Admin SDK',
                'description': 'Manage users, groups, devices and domains',
                'color': Fore.LIGHTRED_EX,
                'commands': ['users', 'groups', 'devices', 'domains', 'suspend', 'status']
            },
            '20': {
                'name': '🆔 Cloud Identity',
                'description': 'Manage identity groups, members, and devices',
                'color': Fore.LIGHTCYAN_EX,
                'commands': ['groups', 'search', 'members', 'devices', 'status']
            },
            '21': {
                'name': '🔍 Cloud Search',
                'description': 'Search workspace resources and documents',
                'color': Fore.LIGHTGREEN_EX,
                'commands': ['search', 'status']
            },
            '22': {
                'name': '📈 Drive Activity',
                'description': 'Audit and activity history for Drive',
                'color': Fore.YELLOW,
                'commands': ['list', 'search', 'status']
            },
            '23': {
                'name': '🔄 Refresh',
                'description': 'Refresh all local data',
                'color': Fore.LIGHTCYAN_EX,
                'commands': ['confirm']
            },
        }
        self.menu_order = list(self.options.keys())
    
    def get_width(self) -> int:
        """Get current terminal width"""
        return shutil.get_terminal_size((80, 20)).columns

    def get_display_width(self, text: str) -> int:
        """Estimate display width of text, accounting for double-width emojis"""
        # A very simple heuristic: count characters, adding 1 for common emojis in this app
        emojis = ["📅", "📧", "📊", "📄", "🎥", "🤖", "⚙️", "📈", "❓", "🎯", "🚀", "👋", "⚡", "💚", "✅", "❌", "💡", "🧪", "🔄"]
        width = len(text)
        for emoji in emojis:
            width += text.count(emoji)
        return width

    def draw_box(self, content: List[str], color=Fore.CYAN, padding: int = 2):
        """Draw a centered box with content"""
        term_width = self.get_width()
        
        # Calculate max width needed for content
        max_content_width = 0
        for line in content:
            max_content_width = max(max_content_width, self.get_display_width(line))
        
        box_width = min(term_width - 4, max_content_width + (padding * 2) + 2)
        if box_width < 10: box_width = 10 # Minimum width
        
        # Center the box
        offset = (term_width - box_width) // 2
        margin = " " * offset
        
        print(margin + color + Style.BRIGHT + "╔" + "═" * (box_width - 2) + "╗")
        for line in content:
            display_width = self.get_display_width(line)
            
            # Handle potential overflow
            if display_width > box_width - 2:
                # Truncate if too long (simple char truncation for now)
                line = line[:box_width - 5] + "..."
                display_width = self.get_display_width(line)
            
            inner_padding = (box_width - 2 - display_width) // 2
            right_padding = box_width - 2 - display_width - inner_padding
            
            print(margin + color + Style.BRIGHT + "║" + " " * inner_padding + line + " " * right_padding + "║")
        print(margin + color + Style.BRIGHT + "╚" + "═" * (box_width - 2) + "╝")

    def show_welcome(self):
        """Show dynamic welcome screen"""
        self.clear_screen()
        width = self.get_width()
        
        logo_lines = [
            "██╗  ██╗███████╗██████╗ ███╗   ███╗███████╗███████╗",
            "██║  ██║██╔════╝██╔══██╗████╗ ████║██╔════╝██╔════╝",
            "███████║█████╗  ██████╔╝██╔████╔██║█████╗  ███████╗",
            "██╔══██║██╔══╝  ██╔══██╗██║╚██╔╝██║██╔══╝  ╚════██║",
            "██║  ██║███████╗██║  ██║██║ ╚═╝ ██║███████╗███████║",
            "╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝╚══════╝",
            "",
            "🚀 AI-POWERED WORKSPACE CLI 🚀"
        ]
        
        for line in logo_lines:
            display_width = self.get_display_width(line)
            offset = max(0, (width - display_width) // 2)
            print(Fore.CYAN + Style.BRIGHT + " " * offset + line)
        
        print()
        tagline = "🤖 AI-Powered • ⚡ Lightning Fast • 📊 Productivity Focused"
        print(Fore.GREEN + Style.BRIGHT + tagline.center(width))
        print()
        
        self.show_quick_stats()
        print()
        self.loading_animation("Loading your workspace".center(width), 1)

    def show_quick_stats(self):
        """Show quick statistics in a centered box"""
        stats = [
            "📊 Productivity Score: 85/100",
            "📧 Unread Emails: 5",
            "📅 Today's Events: 3",
            "🤖 AI Insights Available"
        ]
        self.draw_box(stats, color=Fore.CYAN)

    def show_main_menu(self):
        """Show main interactive menu with dynamic centering"""
        self.clear_screen()
        width = self.get_width()
        
        self.draw_box(["🎯 MAIN MENU"], padding=10)
        print()
        
        max_opt_len = 0
        for key in self.menu_order:
            option = self.options[key]
            line_len = len(f"[{key}] {option['name']}  {option['description']}")
            max_opt_len = max(max_opt_len, line_len)
        
        max_opt_len_formatted = 0
        for key in self.menu_order:
            option = self.options[key]
            name_display_width = self.get_display_width(option['name'])
            padding_needed = max(0, 15 - len(option['name']))
            total_name_width = name_display_width + padding_needed
            
            current_len = 4 + total_name_width + self.get_display_width(option['description'])
            max_opt_len_formatted = max(max_opt_len_formatted, current_len)

        offset = (width - max_opt_len_formatted) // 2
        margin = " " * offset
        
        for key in self.menu_order:
            option = self.options[key]
            option_num = f"{Fore.WHITE + Style.BRIGHT}[{key}]{Style.RESET_ALL} "
            option_name = option['color'] + Style.BRIGHT + f"{option['name']:<15}"
            option_desc = Fore.WHITE + option['description']
            print(margin + option_num + option_name + option_desc)
        
        print()
        print(margin + Fore.RED + Style.BRIGHT + "  [0] Exit")
        print()
        print(margin + Fore.CYAN + "  Choose an option [1-15, 0]: ", end="")
    
    def show_service_menu(self, service_key: str):
        """Show service-specific menu with dynamic layout"""
        if service_key == '1':
            self.show_calendar_main_menu()
            return
        if service_key not in self.options:
            return
        service = self.options[service_key]
        self.clear_screen()
        width = self.get_width()
        self.draw_box([f"{service['name']} MENU"], color=service['color'], padding=10)
        print()
        content_width = max(len(service['description']), 30)
        offset = (width - content_width) // 2
        margin = " " * offset
        print(margin + Fore.WHITE + Style.BRIGHT + service['description'])
        print()
        for i, command in enumerate(service['commands'], 1):
            print(margin + f"  {Fore.WHITE + Style.BRIGHT}[{i}]{Style.RESET_ALL} {service['color']}{command.capitalize()}")
        print()
        print(margin + Fore.WHITE + "  [b] Back to Main Menu")
        print(margin + Fore.RED + "  [0] Exit")
        print()
        print(margin + Fore.CYAN + "  Choose an option: ", end="")
    
    def get_user_choice(self) -> str:
        """Get user input with validation"""
        try:
            choice = input().strip().lower()
            return choice
        except (KeyboardInterrupt, EOFError):
            return '0'
    
    def handle_service_choice(self, service_key: str, command_num: str):
        """Handle service-specific command choice"""
        if service_key not in self.options:
            return
        
        service = self.options[service_key]
        commands = service['commands']
        
        try:
            cmd_index = int(command_num) - 1
            if 0 <= cmd_index < len(commands):
                command = commands[cmd_index]
                self.execute_command(service_key, command)
            else:
                self.show_error("Invalid command number")
        except ValueError:
            self.show_error("Please enter a valid number")
    
    def execute_command(self, service_key: str, command: str):
        """Execute the selected command"""
        self.clear_screen()
        
        # Command header
        service = self.options[service_key]
        print(Fore.CYAN + Style.BRIGHT + f"🚀 Executing: {service['name']} - {command.capitalize()}")
        print(Fore.CYAN + "=" * 60)
        print()
        
        # Map to actual CLI commands
        cli_exe = 'hermes'
        command_map = {
            '1': {  # Calendar
                'list': f'{cli_exe} calendar list-events',
                'create': f'{cli_exe} calendar create-event',
                'update': f'{cli_exe} calendar update',
                'delete': f'{cli_exe} calendar delete',
                'search': f'{cli_exe} calendar search',
                'create-calendar': f'{cli_exe} calendar create-calendar',
                'list-calendars': f'{cli_exe} calendar list',
                'instances': f'{cli_exe} calendar instances',
                'booking-create': f'{cli_exe} booking create',
                'booking-book': f'{cli_exe} booking book',
                'booking-revoke': f'{cli_exe} booking revoke',
                'reminders-run': f'{cli_exe} reminders run',
            },
            '2': {  # Gmail
                'list': f'{cli_exe} gmail list',
                'send': f'{cli_exe} gmail send',
                'search': f'{cli_exe} gmail search',
                'get': f'{cli_exe} gmail get',
                'read': f'{cli_exe} gmail read',
                'reply': f'{cli_exe} gmail reply',
                'forward': f'{cli_exe} gmail forward',
                'drafts': f'{cli_exe} gmail drafts',
                'labels': f'{cli_exe} gmail labels',
                'threads': f'{cli_exe} gmail threads',
                'mark': f'{cli_exe} gmail mark',
                'profile': f'{cli_exe} gmail profile',
            },
            '3': {  # Sheets
                'list': f'{cli_exe} sheets list',
                'read': f'{cli_exe} sheets read',
                'write': f'{cli_exe} sheets write',
                'create': f'{cli_exe} sheets create'
            },
            '4': {  # Docs
                'list': f'{cli_exe} docs list',
                'create': f'{cli_exe} docs create',
                'read': f'{cli_exe} docs get',
                'update': f'{cli_exe} docs update',
                'search': f'{cli_exe} docs search --help'
            },
            '5': {  # Meet
                'create': f'{cli_exe} meet create',
                'join': f'{cli_exe} meet join',
                'details': f'{cli_exe} meet details',
                'active': f'{cli_exe} meet active',
                'list': f'{cli_exe} meet list',
                'history': f'{cli_exe} meet history',
                'participants': f'{cli_exe} meet participants',
                'recordings': f'{cli_exe} meet recordings',
                'transcripts': f'{cli_exe} meet transcripts',
                'get': f'{cli_exe} meet get',
                'info': f'{cli_exe} meet info',
                'end': f'{cli_exe} meet end'
            },
            '6': {  # AI
                'chat': f'{cli_exe} ai chat',
                'ask': f'{cli_exe} ai ask --help',
                'summarize': f'{cli_exe} ai summarize',
                'analytics': f'{cli_exe} ai analytics',
                'insights': f'{cli_exe} ai insights'
            },
            '7': {  # Personal Profile
                'show': f'{cli_exe} personal-profile show',
                'profile': f'{cli_exe} personal-profile show',
            },
            '8': {  # Settings
                'config': f'{cli_exe} config list',
                'cache': f'{cli_exe} cache status',
                'auth': f'{cli_exe} auth status',
                'login': f'{cli_exe} auth login',
                'logout': f'{cli_exe} auth logout'
            },
            '9': {  # Analytics
                'productivity': f'{cli_exe} ai analytics',
                'usage': f'{cli_exe} cache stats',
                'performance': f'{cli_exe} cache status'
            },
            '10': {  # Forms
                'list': f'{cli_exe} forms list',
                'info': f'{cli_exe} forms info',
                'responses': f'{cli_exe} forms responses',
                'create': f'{cli_exe} forms create',
                'edit': f'{cli_exe} forms edit'
            },
            '11': {  # People
                'list': f'{cli_exe} people list'
            },
            '12': {  # Drive
                'list': f'{cli_exe} drive list',
                'edit': f'{cli_exe} drive edit',
                'share': f'{cli_exe} drive share',
                'create': f'{cli_exe} drive create',
                'import': f'{cli_exe} drive import'
            },
            '13': {  # Tasks
                'lists': f'{cli_exe} tasks lists',
                'list': f'{cli_exe} tasks list',
                'create': f'{cli_exe} tasks create-list',
                'edit': f'{cli_exe} tasks edit-list',
                'delete': f'{cli_exe} tasks delete-list'
            },
            '14': {  # BigQuery
                'query': f'{cli_exe} bigquery query'
            },
            '15': {  # Test
                'connection': f'{cli_exe} test connection'
            },
            '16': {  # Chat
                'spaces': f'{cli_exe} chat spaces',
                'messages': f'{cli_exe} chat messages',
                'send': f'{cli_exe} chat send',
                'reply': f'{cli_exe} chat reply',
                'edit': f'{cli_exe} chat edit',
                'delete': f'{cli_exe} chat delete',
                'members': f'{cli_exe} chat members',
                'react': f'{cli_exe} chat react',
                'search': f'{cli_exe} chat search',
                'threads': f'{cli_exe} chat threads',
                'test-connection': f'{cli_exe} chat test-connection',
            },
            '17': {  # Events
                'list': f'{cli_exe} list events',
                'create': f'{cli_exe} create event-subscription',
                'delete': f'{cli_exe} delete event-subscription',
                'status': f'{cli_exe} status events',
            },
            '18': {  # Apps Script
                'list': f'{cli_exe} list scripts',
                'create': f'{cli_exe} create script',
                'run': f'{cli_exe} run script',
                'versions': f'{cli_exe} list script-versions',
                'deployments': f'{cli_exe} list script-deployments',
                'status': f'{cli_exe} status apps-script',
            },
            '19': {  # Admin SDK
                'users': f'{cli_exe} list admin-users',
                'groups': f'{cli_exe} list admin-groups',
                'devices': f'{cli_exe} list admin-devices',
                'domains': f'{cli_exe} list admin-domains',
                'suspend': f'{cli_exe} suspend admin-user',
                'status': f'{cli_exe} status admin',
            },
            '20': {  # Cloud Identity
                'groups': f'{cli_exe} list identity-groups',
                'search': f'{cli_exe} search identity-groups',
                'members': f'{cli_exe} list identity-members',
                'devices': f'{cli_exe} list identity-devices',
                'status': f'{cli_exe} status identity',
            },
            '21': {  # Cloud Search
                'search': f'{cli_exe} search cloud-search',
                'status': f'{cli_exe} status cloud-search',
            },
            '22': {  # Drive Activity
                'list': f'{cli_exe} list drive-activity',
                'search': f'{cli_exe} search drive-activity',
                'status': f'{cli_exe} status drive-activity',
            },
            '23': {  # Refresh (cache clear)
                'confirm': f'{cli_exe} cache clear --confirm'
            }
        }
        
        if service_key in command_map and command in command_map[service_key]:
            cli_command = command_map[service_key][command]
            
            # Calendar create with recurrence and reminders
            if service_key == '1' and command == 'create':
                try:
                    cal_service = CalendarService(OAuthManager())
                    cfg_mgr = ConfigManager()
                    calendar_id = CalendarResolver.prompt_selection(cal_service, cfg_mgr)
                except Exception:
                    print(Fore.CYAN + "Calendar ID: ", end="")
                    calendar_id = input().strip() or 'primary'
                if not calendar_id:
                    self.show_error("Calendar ID is required")
                    return
                while True:
                    print(Fore.CYAN + "Title: ", end="")
                    title = input().strip()
                    is_valid, err_msg = validate_title(title)
                    if is_valid:
                        break
                    print()
                    print_error(err_msg)
                    print()

                start_dt = None
                while True:
                    print(Fore.CYAN + "Start (YYYY-MM-DD HH:MM): ", end="")
                    start = input().strip()
                    is_valid, parsed_dt, err_msg = validate_datetime(start)
                    if is_valid:
                        start_dt = parsed_dt
                        break
                    print()
                    print_error(err_msg)
                    print()

                end_dt = None
                while True:
                    print(Fore.CYAN + "End   (YYYY-MM-DD HH:MM): ", end="")
                    end = input().strip()
                    is_valid, parsed_dt, err_msg = validate_datetime(end)
                    if not is_valid:
                        print()
                        print_error(err_msg)
                        print()
                        continue
                    is_order_valid, order_err = validate_start_end_order(start_dt, parsed_dt)
                    if not is_order_valid:
                        print()
                        print_error(order_err)
                        print()
                        continue
                    end_dt = parsed_dt
                    break

                print(Fore.CYAN + "Description (optional): ", end="")
                description = input().strip()
                print(Fore.CYAN + "Location (optional): ", end="")
                location = input().strip()

                rec_flags = []
                until_count_flags = []
                while True:
                    print(Fore.CYAN + "Recurrence [n=none, d=daily, w=weekly, m=monthly, r=RRULE]: ", end="")
                    r_choice = input().strip().lower()
                    is_valid, err_msg = validate_recurrence_choice(r_choice)
                    if is_valid:
                        break
                    print()
                    print_error(err_msg)
                    print()

                if r_choice == 'd':
                    rec_flags.append('--daily')
                elif r_choice == 'w':
                    rec_flags.append('--weekly')
                    while True:
                        print(Fore.CYAN + "Weekdays (e.g. mon-fri or mon,wed,fri): ", end="")
                        weekdays_input = input().strip()
                        is_valid, parsed_days, err_msg = validate_weekdays(weekdays_input)
                        if is_valid:
                            for part in parsed_days:
                                rec_flags.append(f'--weekday "{part}"')
                            break
                        print()
                        print_error(err_msg)
                        print()
                elif r_choice == 'm':
                    rec_flags.append('--monthly')
                    while True:
                        print(Fore.CYAN + "Day of month (1-31): ", end="")
                        day_input = input().strip()
                        is_valid, day_num, err_msg = validate_month_day(day_input)
                        if is_valid:
                            rec_flags.append(f'--day {day_num}')
                            break
                        print()
                        print_error(err_msg)
                        print()
                elif r_choice == 'r':
                    while True:
                        print(Fore.CYAN + "RRULE (e.g. FREQ=WEEKLY;BYDAY=MO,WE,FR): ", end="")
                        rule_input = input().strip()
                        is_valid, err_msg = validate_rrule(rule_input)
                        if is_valid:
                            rec_flags.append(f'--rrule "{rule_input}"')
                            break
                        print()
                        print_error(err_msg)
                        print()

                if r_choice in ['d', 'w', 'm', 'r']:
                    while True:
                        print(Fore.CYAN + "End condition [n=none, u=until date, c=count]: ", end="")
                        ec = input().strip().lower()
                        is_valid, err_msg = validate_end_condition(ec)
                        if is_valid:
                            break
                        print()
                        print_error(err_msg)
                        print()

                    if ec == 'u':
                        while True:
                            print(Fore.CYAN + "Until date (YYYY-MM-DD): ", end="")
                            until_input = input().strip()
                            is_valid, err_msg = validate_until_date(until_input)
                            if is_valid:
                                until_count_flags.append(f'--until {until_input}')
                                break
                            print()
                            print_error(err_msg)
                            print()
                    elif ec == 'c':
                        while True:
                            print(Fore.CYAN + "Number of occurrences: ", end="")
                            count_input = input().strip()
                            is_valid, count_num, err_msg = validate_occurrence_count(count_input)
                            if is_valid:
                                until_count_flags.append(f'--count {count_num}')
                                break
                            print()
                            print_error(err_msg)
                            print()

                while True:
                    print(Fore.CYAN + "Add reminders? (y/N): ", end="")
                    add_reminders = input().strip().lower()
                    if add_reminders in ['', 'n', 'no', 'y', 'yes']:
                        break
                    print()
                    print_error("Invalid choice. Enter y or n.")
                    print()

                reminder_flags = []
                notify_flags = []
                if add_reminders in ['y', 'yes']:
                    while True:
                        print(Fore.CYAN + "Reminders (comma separated, e.g. 30m,1h,1d): ", end="")
                        raw_rem = input().strip()
                        is_valid, parsed_rem, err_msg = validate_reminders(raw_rem)
                        if is_valid:
                            for val in parsed_rem:
                                reminder_flags.append(f'--remind {val}')
                            break
                        print()
                        print_error(err_msg)
                        print()

                    while True:
                        print(Fore.CYAN + "Notification channels [c=cli, d=desktop, e=email, blank=cli]: ", end="")
                        ch = input().strip().lower()
                        is_valid, parsed_channels, err_msg = validate_notification_channels(ch)
                        if is_valid:
                            if 'd' in parsed_channels:
                                notify_flags.append('--notify desktop')
                            if 'e' in parsed_channels:
                                notify_flags.append('--notify email')
                            if 'c' in parsed_channels or not parsed_channels:
                                notify_flags.append('--notify cli')
                            break
                        print()
                        print_error(err_msg)
                        print()

                parts = [
                    cli_command,
                    f'--title "{title}"',
                    f'--start "{start}"',
                    f'--end "{end}"',
                ]
                if description:
                    parts.append(f'--description "{description}"')
                if location:
                    parts.append(f'--location "{location}"')
                parts.extend(rec_flags)
                parts.extend(until_count_flags)
                parts.append('--timezone "Asia/Kolkata"')
                parts.extend(reminder_flags)
                parts.extend(notify_flags)
                parts.append('--no-extra-prompts')
                parts.append(f'--calendar-id "{calendar_id}"')
                cli_command = " ".join(parts)

            # Calendar update with dynamic event selection and validation
            elif service_key == '1' and command == 'update':
                from .interactive_calendar import run_calendar_update_flow
                try:
                    cal_service = CalendarService(OAuthManager())
                except Exception:
                    cal_service = None
                try:
                    cfg_mgr = ConfigManager()
                except Exception:
                    cfg_mgr = None
                run_calendar_update_flow(cal_service, cfg_mgr)
                print()
                print(Fore.CYAN + "Press Enter to continue...", end="")
                input()
                return

            # Calendar delete with dynamic event selection, details and confirmation
            elif service_key == '1' and command == 'delete':
                from .human_flows import run_calendar_delete_flow
                try:
                    cal_service = CalendarService(OAuthManager())
                    cfg_mgr = ConfigManager()
                except Exception:
                    cal_service = None
                    cfg_mgr = None
                run_calendar_delete_flow(cal_service, cfg_mgr)
                print()
                print(Fore.CYAN + "Press Enter to continue...", end="")
                input()
                return

            # Meet details / end
            elif service_key == '5' and command in ('details', 'end'):
                from .human_flows import run_meet_spaces_flow, run_meet_end_flow
                from ..services.meet import MeetService
                try:
                    meet_service = MeetService(OAuthManager())
                    cfg_mgr = ConfigManager()
                except Exception:
                    meet_service = None
                    cfg_mgr = None
                if command == 'end':
                    run_meet_end_flow(meet_service, cfg_mgr)
                else:
                    run_meet_spaces_flow(meet_service, cfg_mgr)
                print()
                print(Fore.CYAN + "Press Enter to continue...", end="")
                input()
                return

            # Gmail delete / read
            elif service_key == '2' and command in ('delete', 'read', 'get'):
                from .human_flows import run_gmail_messages_flow, run_gmail_delete_flow
                from ..services.gmail import GmailService
                try:
                    gmail_service = GmailService(OAuthManager())
                    cfg_mgr = ConfigManager()
                except Exception:
                    gmail_service = None
                    cfg_mgr = None
                if command == 'delete':
                    run_gmail_delete_flow(gmail_service, cfg_mgr)
                else:
                    run_gmail_messages_flow(gmail_service, cfg_mgr)
                print()
                print(Fore.CYAN + "Press Enter to continue...", end="")
                input()
                return

            # Drive edit / rename
            elif service_key == '11' and command in ('edit', 'delete'):
                from .human_flows import run_drive_rename_flow, run_drive_delete_flow
                from ..services.drive import DriveService
                try:
                    drive_service = DriveService(OAuthManager())
                    cfg_mgr = ConfigManager()
                except Exception:
                    drive_service = None
                    cfg_mgr = None
                if command == 'edit':
                    run_drive_rename_flow(drive_service, cfg_mgr)
                else:
                    run_drive_delete_flow(drive_service, cfg_mgr)
                print()
                print(Fore.CYAN + "Press Enter to continue...", end="")
                input()
                return

            # Tasks edit / delete
            elif service_key == '12' and command in ('edit', 'delete'):
                from .human_flows import run_task_update_flow, run_task_delete_flow
                from ..services.tasks import TasksService
                try:
                    tasks_service = TasksService(OAuthManager())
                    cfg_mgr = ConfigManager()
                except Exception:
                    tasks_service = None
                    cfg_mgr = None
                if command == 'delete':
                    run_task_delete_flow(tasks_service, cfg_mgr)
                else:
                    run_task_update_flow(tasks_service, cfg_mgr)
                print()
                print(Fore.CYAN + "Press Enter to continue...", end="")
                input()
                return

            # Chat delete / edit
            elif service_key == '15' and command in ('delete', 'edit'):
                from .human_flows import run_chat_message_delete_flow
                from ..services.chat import ChatService
                try:
                    chat_service = ChatService(OAuthManager())
                    cfg_mgr = ConfigManager()
                except Exception:
                    chat_service = None
                    cfg_mgr = None
                if command == 'delete':
                    run_chat_message_delete_flow(chat_service, cfg_mgr)
                    print()
                    print(Fore.CYAN + "Press Enter to continue...", end="")
                    input()
                    return

            # Workspace events delete
            elif service_key == '16' and command == 'delete':
                from .human_flows import run_events_delete_flow
                from ..services.workspace_events import WorkspaceEventsService
                try:
                    events_service = WorkspaceEventsService(OAuthManager())
                    cfg_mgr = ConfigManager()
                except Exception:
                    events_service = None
                    cfg_mgr = None
                run_events_delete_flow(events_service, cfg_mgr)
                print()
                print(Fore.CYAN + "Press Enter to continue...", end="")
                input()
                return

            # Admin suspend
            elif service_key == '18' and command == 'suspend':
                from .human_flows import run_admin_user_suspend_flow
                from ..services.admin import AdminService
                try:
                    admin_service = AdminService(OAuthManager())
                    cfg_mgr = ConfigManager()
                except Exception:
                    admin_service = None
                    cfg_mgr = None
                run_admin_user_suspend_flow(admin_service, cfg_mgr)
                print()
                print(Fore.CYAN + "Press Enter to continue...", end="")
                input()
                return
            
            # Calendar instances
            elif service_key == '1' and command == 'instances':
                print(Fore.CYAN + "Recurring Event ID: ", end="")
                event_id = input().strip()
                if not event_id:
                    self.show_error("Event ID is required")
                    return
                print(Fore.CYAN + "Start date (YYYY-MM-DD, blank = none): ", end="")
                time_min = input().strip()
                print(Fore.CYAN + "End date   (YYYY-MM-DD, blank = none): ", end="")
                time_max = input().strip()
                try:
                    cal_service = CalendarService(OAuthManager())
                    cfg_mgr = ConfigManager()
                    calendar_id = CalendarResolver.prompt_selection(cal_service, cfg_mgr)
                except Exception:
                    print(Fore.CYAN + "Calendar ID (blank = primary): ", end="")
                    calendar_id = input().strip() or 'primary'
                parts = [cli_command, event_id]
                if calendar_id:
                    parts.append(f'--calendar-id "{calendar_id}"')
                if time_min:
                    parts.append(f'--time-min {time_min}')
                if time_max:
                    parts.append(f'--time-max {time_max}')
                cli_command = " ".join(parts)
            
            # Booking link creation
            elif service_key == '1' and command == 'booking-create':
                print(Fore.CYAN + "Duration (e.g. 30m or 1h): ", end="")
                duration = input().strip()
                if not duration:
                    self.show_error("Duration is required")
                    return
                print(Fore.CYAN + "Availability (e.g. mon-fri 09:00-17:00): ", end="")
                availability = input().strip()
                if not availability:
                    self.show_error("Availability is required")
                    return
                print(Fore.CYAN + "Buffer (e.g. 15m, blank=0m): ", end="")
                buffer_value = input().strip() or "0m"
                print(Fore.CYAN + "Expiration date (YYYY-MM-DD, blank = none): ", end="")
                expires = input().strip()
                print(Fore.CYAN + "Max bookings per day (blank = unlimited): ", end="")
                max_per_day = input().strip()
                print(Fore.CYAN + "Timezone (blank = default): ", end="")
                timezone = input().strip()
                try:
                    cal_service = CalendarService(OAuthManager())
                    cfg_mgr = ConfigManager()
                    calendar_id = CalendarResolver.prompt_selection(cal_service, cfg_mgr)
                except Exception:
                    print(Fore.CYAN + "Calendar ID (blank = primary): ", end="")
                    calendar_id = input().strip() or 'primary'
                parts = [cli_command, f'--duration {duration}', f'--availability "{availability}"']
                if buffer_value:
                    parts.append(f'--buffer {buffer_value}')
                if expires:
                    parts.append(f'--expires {expires}')
                if max_per_day:
                    parts.append(f'--max-per-day {max_per_day}')
                if timezone:
                    parts.append(f'--timezone "{timezone}"')
                if calendar_id:
                    parts.append(f'--calendar-id "{calendar_id}"')
                cli_command = " ".join(parts)
            
            # Booking book
            elif service_key == '1' and command == 'booking-book':
                print(Fore.CYAN + "Booking token: ", end="")
                token = input().strip()
                if not token:
                    self.show_error("Token is required")
                    return
                print(Fore.CYAN + "Start (e.g. 2026-03-25 14:00 in booking timezone): ", end="")
                start_str = input().strip()
                if not start_str:
                    self.show_error("Start time is required")
                    return
                cli_command = f'{cli_command} {token} --start "{start_str}"'
            
            # Booking revoke
            elif service_key == '1' and command == 'booking-revoke':
                print(Fore.CYAN + "Booking token: ", end="")
                token = input().strip()
                if not token:
                    self.show_error("Token is required")
                    return
                cli_command = f'{cli_command} {token}'
            
            # Reminders scheduler
            elif service_key == '1' and command == 'reminders-run':
                print(Fore.CYAN + "Run once or continuously? [o/c]: ", end="")
                mode = input().strip().lower()
                if mode == 'c':
                    print(Fore.CYAN + "Interval in seconds (default 60): ", end="")
                    interval = input().strip() or "60"
                    cli_command = f'{cli_command} --interval {interval}'
                else:
                    cli_command = f'{cli_command} --once'
            
            elif service_key == '1' and command == 'delete':
                print(Fore.CYAN + "Event ID: ", end="")
                event_id = input().strip()
                if not event_id:
                    self.show_error("Event ID is required")
                    return
                try:
                    cal_service = CalendarService(OAuthManager())
                    cfg_mgr = ConfigManager()
                    calendar_id = CalendarResolver.prompt_selection(cal_service, cfg_mgr)
                except Exception:
                    print(Fore.CYAN + "Calendar ID: ", end="")
                    calendar_id = input().strip() or 'primary'
                if not calendar_id:
                    self.show_error("Calendar ID is required")
                    return
                cli_command = f'{cli_command} {event_id} --calendar-id "{calendar_id}"'
            
            elif service_key == '4' and command == 'update':
                print(Fore.CYAN + "Enter ID: ", end="")
                item_id = input().strip()
                if not item_id:
                    self.show_error("ID is required")
                    return
                print(Fore.CYAN + "Enter content: ", end="")
                content = input().strip()
                if not content:
                    self.show_error("Content is required")
                    return
                print(Fore.CYAN + "Append instead of replace? (y/N): ", end="")
                choice = input().strip().lower()
                append_flag = "--append" if choice in ["y", "yes"] else ""
                cli_command = f'{cli_command} {item_id} --content "{content}"'
                if append_flag:
                    cli_command = f"{cli_command} {append_flag}"
            
            elif service_key == '12' and command in ['list', 'edit', 'delete']:
                print(Fore.CYAN + "Enter List ID: ", end="")
                item_id = input().strip()
                if not item_id:
                    self.show_error("ID is required")
                    return
                cli_command = f"{cli_command} {item_id}"
            
            elif command in ['get', 'update', 'delete'] or (service_key == '4' and command == 'read'):
                print(Fore.CYAN + "Enter ID: ", end="")
                item_id = input().strip()
                if item_id:
                    cli_command = f"{cli_command} {item_id}"
                else:
                    self.show_error("ID is required")
                    return
            
            # If command is 'send', prompt for fields
            elif command == 'send':
                print(Fore.CYAN + "To: ", end="")
                to = input().strip()
                print(Fore.CYAN + "Subject: ", end="")
                subject = input().strip()
                print(Fore.CYAN + "Body: ", end="")
                body = input().strip()
                
                if to and subject and body:
                    cli_command = f'{cli_command} --to "{to}" --subject "{subject}" --body "{body}"'
                else:
                    self.show_error("To, Subject, and Body are all required")
                    return
            
            # If command is 'search', prompt for query
            elif command == 'search':
                print(Fore.CYAN + "Enter search query: ", end="")
                query = input().strip()
                if query:
                    cli_command = f'{cli_command} "{query}"'
                else:
                    self.show_error("Search query is required")
                    return
            
            # If BigQuery query, prompt for project and SQL
            elif service_key == '15' and command == 'query':
                print(Fore.CYAN + "Enter BigQuery project ID: ", end="")
                project_id = input().strip()
                print(Fore.CYAN + "Enter SQL query: ", end="")
                sql = input().strip()
                if project_id and sql:
                    cli_command = f'{cli_command} "{project_id}" "{sql}"'
                else:
                    self.show_error("Project ID and SQL query are required")
                    return

            if service_key == '2' and command == 'profile':
                try:
                    subprocess.call(cli_command, shell=True)
                except Exception as e:
                    print(Fore.RED + f"❌ Error: {e}")
                return

            print(Fore.WHITE + f"💡 Running: {cli_command}")
            print()
            
            # Execute the command
            try:
                # Use subprocess.call with shell=True but don't wrap in extra quotes
                # as python_exe is already quoted.
                subprocess.call(cli_command, shell=True)
            except Exception as e:
                print(Fore.RED + f"❌ Error: {e}")
        else:
            print(Fore.RED + "❌ Command not implemented yet")
        
        print()
        print(Fore.CYAN + "Press Enter to continue...", end="")
        input()

    def execute_command_direct(self, cli_command: str, custom_title: str = None):
        """Execute a command directly without mapping"""
        self.clear_screen()
        if custom_title:
            print(Fore.BLACK + Style.BRIGHT + f"🚀 {custom_title}")
        print("=" * 60)
        print()
        
        print(Fore.WHITE + f"💡 Running: {cli_command}")
        print()
        
        try:
            subprocess.call(cli_command, shell=True)
        except Exception as e:
            print(Fore.RED + f"❌ Error: {e}")
            
        print()
        print(Fore.CYAN + "Press Enter to continue...", end="")
        input()
    
    def show_calendar_main_menu(self):
        service = self.options['1']
        self.clear_screen()
        width = self.get_width()
        self.draw_box([f"{service['name']} MENU"], color=service['color'], padding=10)
        print()
        lines = [
            "Manage calendar features",
            "",
            "[1] Events",
            "[2] Calendars",
            "[3] Booking",
            "[4] System",
            "",
            "[b] Back to MAIN MENU",
            "[0] Exit",
        ]
        max_len = max(len(line) for line in lines)
        offset = (width - max_len) // 2
        margin = " " * max(0, offset)
        for line in lines:
            print(margin + Fore.WHITE + Style.BRIGHT + line)
    
    def handle_calendar_menu(self):
        while True:
            self.show_calendar_main_menu()
            print()
            width = self.get_width()
            prompt = "Choose an option [0-4, b]: "
            offset = (width - len(prompt)) // 2
            margin = " " * max(0, offset)
            print(margin + Fore.CYAN + prompt, end="")
            choice = self.get_user_choice()
            if choice == '0':
                self.show_goodbye()
                sys.exit(0)
            elif choice == 'b':
                break
            elif choice == '1':
                self.handle_calendar_events_menu()
            elif choice == '2':
                self.handle_calendar_calendars_menu()
            elif choice == '3':
                self.handle_calendar_booking_menu()
            elif choice == '4':
                self.handle_calendar_system_menu()
            else:
                self.show_error("Invalid choice. Please select 0-4 or b.")

    def show_calendar_events_menu(self):
        self.clear_screen()
        width = self.get_width()
        self.draw_box(["Events MENU"], color=Fore.CYAN, padding=10)
        print()
        lines = [
            "Manage events",
            "",
            "[1] Today's events",
            "[2] Tomorrow's events",
            "[3] Upcoming events",
            "[4] List all events",
            "[5] Events by date",
            "[6] Events by date range",
            "[7] Search events",
            "[8] View event details",
            "[9] Create event",
            "[10] Edit event",
            "[11] Delete event",
            "[12] View recurring instances",
            "",
            "[b] Back to Calendar Main Menu",
            "[0] Exit",
        ]
        max_len = max(len(line) for line in lines)
        offset = (width - max_len) // 2
        margin = " " * max(0, offset)
        for line in lines:
            print(margin + Fore.WHITE + Style.BRIGHT + line)

    def handle_calendar_events_menu(self):
        while True:
            self.show_calendar_events_menu()
            print()
            width = self.get_width()
            prompt = "Choose an option [0-12, b]: "
            offset = (width - len(prompt)) // 2
            margin = " " * max(0, offset)
            print(margin + Fore.CYAN + prompt, end="")
            choice = self.get_user_choice()
            if choice == '0':
                self.show_goodbye()
                sys.exit(0)
            elif choice == 'b':
                break
            elif choice == '1':
                self.execute_command_direct('hermes calendar today', "Today's Events")
            elif choice == '2':
                self.execute_command_direct('hermes calendar tomorrow', "Tomorrow's Events")
            elif choice == '3':
                self.execute_command_direct('hermes calendar upcoming', "Upcoming Events")
            elif choice == '4':
                self.execute_command('1', 'list')
            elif choice == '5':
                print(Fore.CYAN + "Enter date (YYYY-MM-DD): ", end="")
                dt_str = input().strip()
                if dt_str:
                    self.execute_command_direct(f'hermes calendar by-date --date "{dt_str}"', f"Events for {dt_str}")
                else:
                    self.show_error("Date is required")
            elif choice == '6':
                print(Fore.CYAN + "Enter start date (YYYY-MM-DD): ", end="")
                s_str = input().strip()
                print(Fore.CYAN + "Enter end date (YYYY-MM-DD): ", end="")
                e_str = input().strip()
                if s_str and e_str:
                    self.execute_command_direct(f'hermes calendar by-range --start-date "{s_str}" --end-date "{e_str}"', f"Events ({s_str} to {e_str})")
                else:
                    self.show_error("Both start and end dates are required")
            elif choice == '7':
                self.execute_command('1', 'search')
            elif choice == '8':
                print(Fore.CYAN + "Enter event ID: ", end="")
                eid = input().strip()
                if eid:
                    self.execute_command_direct(f'hermes calendar get "{eid}"', "View Event Details")
                else:
                    self.show_error("Event ID is required")
            elif choice == '9':
                self.execute_command('1', 'create')
            elif choice == '10':
                self.execute_command('1', 'update')
            elif choice == '11':
                self.execute_command('1', 'delete')
            elif choice == '12':
                self.execute_command('1', 'instances')
            else:
                self.show_error("Invalid choice.")

    def show_calendar_calendars_menu(self):
        self.clear_screen()
        width = self.get_width()
        self.draw_box(["Calendars MENU"], color=Fore.CYAN, padding=10)
        print()
        lines = [
            "Manage calendars",
            "",
            "[1] List calendars",
            "[2] View calendar details",
            "[3] Switch active / default calendar",
            "[4] Create calendar",
            "[5] Update calendar",
            "[6] Delete calendar",
            "",
            "[b] Back to Calendar Main Menu",
            "[0] Exit",
        ]
        max_len = max(len(line) for line in lines)
        offset = (width - max_len) // 2
        margin = " " * max(0, offset)
        for line in lines:
            print(margin + Fore.WHITE + Style.BRIGHT + line)

    def handle_calendar_calendars_menu(self):
        config_manager = ConfigManager()
        while True:
            self.show_calendar_calendars_menu()
            print()
            width = self.get_width()
            prompt = "Choose an option [0-6, b]: "
            offset = (width - len(prompt)) // 2
            margin = " " * max(0, offset)
            print(margin + Fore.CYAN + prompt, end="")
            choice = self.get_user_choice()
            if choice == '0':
                self.show_goodbye()
                sys.exit(0)
            elif choice == 'b':
                break
            elif choice == '1':
                self.execute_command('1', 'list-calendars')
            elif choice == '2':
                try:
                    cal_service = CalendarService(OAuthManager())
                    cal_id = CalendarResolver.prompt_selection(cal_service, config_manager)
                except Exception:
                    print(Fore.CYAN + "Enter calendar ID (blank = primary): ", end="")
                    cal_id = input().strip() or "primary"
                self.execute_command_direct(f'hermes calendar info "{cal_id}"', f"Calendar Details ({cal_id})")
            elif choice == '3':
                try:
                    cal_service = CalendarService(OAuthManager())
                    cal_id = CalendarResolver.prompt_selection(cal_service, config_manager)
                except Exception:
                    print(Fore.CYAN + "Enter calendar ID to set as default: ", end="")
                    cal_id = input().strip()
                if not cal_id:
                    self.show_error("Calendar ID is required")
                else:
                    if config_manager.set('calendar.default_calendar', cal_id):
                        if config_manager.save_config():
                            self.show_success(f"Active calendar set to {cal_id}")
                    else:
                        self.show_error("Failed to update configuration")
            elif choice == '4':
                self.execute_command('1', 'create-calendar')
            elif choice == '5':
                try:
                    cal_service = CalendarService(OAuthManager())
                    cal_id = CalendarResolver.prompt_selection(cal_service, config_manager)
                except Exception:
                    print(Fore.CYAN + "Enter calendar ID: ", end="")
                    cal_id = input().strip()
                if not cal_id:
                    self.show_error("Calendar ID is required")
                    continue
                print(Fore.CYAN + "New name / summary (blank to skip): ", end="")
                summary = input().strip()
                print(Fore.CYAN + "New description (blank to skip): ", end="")
                desc = input().strip()
                cmd = f'hermes calendar update-calendar "{cal_id}"'
                if summary:
                    cmd += f' --summary "{summary}"'
                if desc:
                    cmd += f' --description "{desc}"'
                self.execute_command_direct(cmd, f"Update Calendar ({cal_id})")
            elif choice == '6':
                try:
                    cal_service = CalendarService(OAuthManager())
                    cal_id = CalendarResolver.prompt_selection(cal_service, config_manager)
                except Exception:
                    print(Fore.CYAN + "Enter calendar ID to delete: ", end="")
                    cal_id = input().strip()
                if not cal_id:
                    self.show_error("Calendar ID is required")
                else:
                    self.execute_command_direct(f'hermes calendar delete "{cal_id}"', "Delete calendar")
            else:
                self.show_error("Invalid choice.")

    def show_calendar_booking_menu(self):
        self.clear_screen()
        width = self.get_width()
        self.draw_box(["Booking MENU"], color=Fore.CYAN, padding=10)
        print()
        lines = [
            "Meeting & Booking Orchestrator",
            "",
            "[1] Quick meeting (with Google Meet)",
            "[2] Schedule meeting (guided flow)",
            "[3] Find available time (Free/Busy)",
            "[4] Reschedule meeting",
            "[5] Cancel meeting",
            "[6] Manage booking links (tokens)",
            "",
            "[b] Back to Calendar Main Menu",
            "[0] Exit",
        ]
        max_len = max(len(line) for line in lines)
        offset = (width - max_len) // 2
        margin = " " * max(0, offset)
        for line in lines:
            print(margin + Fore.WHITE + Style.BRIGHT + line)

    def _show_active_booking_links(self):
        config_manager = ConfigManager()
        db_path = config_manager.data_dir / "bookings.db"
        if not db_path.exists():
            print()
            print(Fore.YELLOW + "No booking links database found.")
            time.sleep(2)
            return
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT token, duration_minutes, availability, buffer_minutes,
                       expires_at, max_per_day, time_zone, calendar_id, created_at, revoked
                FROM booking_links
                WHERE revoked = 0
                ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()
        finally:
            conn.close()
        print()
        if not rows:
            print(Fore.YELLOW + "No active booking links.")
            time.sleep(2)
            return
        print(Fore.CYAN + Style.BRIGHT + "Active booking links:")
        for row in rows:
            token, duration, availability, buffer_minutes, expires_at, max_per_day, time_zone, calendar_id, created_at, _ = row
            desc = f"token={token} calendar={calendar_id} tz={time_zone} duration={duration}m buffer={buffer_minutes}m"
            if max_per_day:
                desc += f" max/day={max_per_day}"
            if expires_at:
                desc += f" expires={expires_at}"
            print(Fore.WHITE + "- " + desc)
        print()
        print(Fore.CYAN + "Press Enter to continue...", end="")
        input()

    def handle_calendar_booking_menu(self):
        while True:
            self.show_calendar_booking_menu()
            print()
            width = self.get_width()
            prompt = "Choose an option [0-6, b]: "
            offset = (width - len(prompt)) // 2
            margin = " " * max(0, offset)
            print(margin + Fore.CYAN + prompt, end="")
            choice = self.get_user_choice()
            if choice == '0':
                self.show_goodbye()
                sys.exit(0)
            elif choice == 'b':
                break
            elif choice == '1':
                print(Fore.CYAN + "Meeting title: ", end="")
                title = input().strip() or "Quick Meeting"
                print(Fore.CYAN + "Start time (YYYY-MM-DD HH:MM): ", end="")
                start_str = input().strip()
                if not start_str:
                    self.show_error("Start time is required")
                    continue
                print(Fore.CYAN + "Duration in minutes (default: 30): ", end="")
                dur_str = input().strip() or "30"
                print(Fore.CYAN + "Generate Google Meet link? [Y/n]: ", end="")
                online_str = input().strip().lower()
                online_flag = "--online" if online_str not in ['n', 'no'] else "--no-online"
                print(Fore.CYAN + "Attendees (comma-separated, blank for none): ", end="")
                att_input = input().strip()
                att_args = ""
                if att_input:
                    for a in att_input.split(','):
                        a = a.strip()
                        if a:
                            att_args += f' --attendee "{a}"'
                cmd = f'hermes booking quick --title "{title}" --start "{start_str}" --duration {dur_str} {online_flag} {att_args}'.strip()
                self.execute_command_direct(cmd, "Quick Meeting")
            elif choice == '2':
                print(Fore.CYAN + "Meeting title: ", end="")
                title = input().strip()
                if not title:
                    self.show_error("Title is required")
                    continue
                print(Fore.CYAN + "Start time (YYYY-MM-DD HH:MM): ", end="")
                start_str = input().strip()
                if not start_str:
                    self.show_error("Start time is required")
                    continue
                print(Fore.CYAN + "Duration in minutes (default: 30): ", end="")
                dur_str = input().strip() or "30"
                print(Fore.CYAN + "Description: ", end="")
                desc = input().strip()
                print(Fore.CYAN + "Include Google Meet link? [Y/n]: ", end="")
                online_str = input().strip().lower()
                online_flag = "--online" if online_str not in ['n', 'no'] else "--no-online"
                print(Fore.CYAN + "Attendees (comma-separated): ", end="")
                att_input = input().strip()
                att_args = ""
                if att_input:
                    for a in att_input.split(','):
                        a = a.strip()
                        if a:
                            att_args += f' --attendee "{a}"'
                cmd = f'hermes booking schedule --title "{title}" --start "{start_str}" --duration {dur_str} --description "{desc}" {online_flag} {att_args}'.strip()
                self.execute_command_direct(cmd, "Schedule Meeting")
            elif choice == '3':
                print(Fore.CYAN + "Target date (YYYY-MM-DD): ", end="")
                date_str = input().strip()
                if not date_str:
                    self.show_error("Date is required")
                    continue
                print(Fore.CYAN + "Duration in minutes (default: 30): ", end="")
                dur_str = input().strip() or "30"
                cmd = f'hermes booking availability --date "{date_str}" --duration {dur_str}'
                self.execute_command_direct(cmd, f"Find Available Time ({date_str})")
            elif choice == '4':
                print(Fore.CYAN + "Enter event ID to reschedule: ", end="")
                event_id = input().strip()
                if not event_id:
                    self.show_error("Event ID is required")
                    continue
                print(Fore.CYAN + "New start time (YYYY-MM-DD HH:MM): ", end="")
                start_str = input().strip()
                if not start_str:
                    self.show_error("Start time is required")
                    continue
                cmd = f'hermes booking reschedule "{event_id}" --start "{start_str}"'
                self.execute_command_direct(cmd, f"Reschedule Meeting ({event_id})")
            elif choice == '5':
                print(Fore.CYAN + "Enter event ID to cancel: ", end="")
                event_id = input().strip()
                if not event_id:
                    self.show_error("Event ID is required")
                    continue
                cmd = f'hermes booking cancel "{event_id}"'
                self.execute_command_direct(cmd, f"Cancel Meeting ({event_id})")
            elif choice == '6':
                self.handle_legacy_booking_links_menu()
            else:
                self.show_error("Invalid choice.")

    def handle_legacy_booking_links_menu(self):
        while True:
            self.clear_screen()
            width = self.get_width()
            self.draw_box(["Booking Links (Tokens)"], color=Fore.CYAN, padding=10)
            print()
            lines = [
                "Manage token-based booking links",
                "",
                "[1] Create booking link",
                "[2] Book via token",
                "[3] Revoke booking link",
                "[4] List active booking links",
                "",
                "[b] Back to Booking Menu",
            ]
            max_len = max(len(line) for line in lines)
            offset = (width - max_len) // 2
            margin = " " * max(0, offset)
            for line in lines:
                print(margin + Fore.WHITE + Style.BRIGHT + line)
            print()
            prompt = "Choose an option [1-4, b]: "
            offset = (width - len(prompt)) // 2
            margin = " " * max(0, offset)
            print(margin + Fore.CYAN + prompt, end="")
            choice = self.get_user_choice()
            if choice == 'b':
                break
            elif choice == '1':
                self.execute_command('1', 'booking-create')
            elif choice == '2':
                self.execute_command('1', 'booking-book')
            elif choice == '3':
                self.execute_command('1', 'booking-revoke')
            elif choice == '4':
                self._show_active_booking_links()

    def show_calendar_system_menu(self):
        self.clear_screen()
        width = self.get_width()
        self.draw_box(["System MENU"], color=Fore.CYAN, padding=10)
        print()
        lines = [
            "Calendar System & Connection",
            "",
            "[1] Authentication & account status",
            "[2] Calendar API connection test",
            "[3] Current default calendar & timezone",
            "[4] Refresh / Clear cache",
            "[5] Re-authenticate (login)",
            "[6] Disconnect (logout)",
            "[7] Reminder tools",
            "",
            "[b] Back to Calendar Main Menu",
            "[0] Exit",
        ]
        max_len = max(len(line) for line in lines)
        offset = (width - max_len) // 2
        margin = " " * max(0, offset)
        for line in lines:
            print(margin + Fore.WHITE + Style.BRIGHT + line)

    def _show_pending_reminders(self):
        config_manager = ConfigManager()
        service = ReminderService(config_manager)
        now = datetime.utcnow()
        pending = service.get_due_reminders(now=now, limit=50)
        print()
        if not pending:
            print(Fore.YELLOW + "No pending reminders ready to send.")
            time.sleep(2)
            return
        print(Fore.CYAN + Style.BRIGHT + "Pending reminders:")
        for r in pending:
            desc = f"id={r['id']} event={r['event_id']} calendar={r['calendar_id']} at={r['scheduled_at']} offset={r['offset_minutes']}m"
            channels = []
            if r['notify_cli']:
                channels.append("cli")
            if r['notify_desktop']:
                channels.append("desktop")
            if r['notify_email']:
                channels.append("email")
            if channels:
                desc += " channels=" + "/".join(channels)
            print(Fore.WHITE + "- " + desc)
        print()
        print(Fore.CYAN + "Press Enter to continue...", end="")
        input()

    def handle_calendar_system_menu(self):
        config_manager = ConfigManager()
        while True:
            self.show_calendar_system_menu()
            print()
            width = self.get_width()
            prompt = "Choose an option [0-7, b]: "
            offset = (width - len(prompt)) // 2
            margin = " " * max(0, offset)
            print(margin + Fore.CYAN + prompt, end="")
            choice = self.get_user_choice()
            if choice == '0':
                self.show_goodbye()
                sys.exit(0)
            elif choice == 'b':
                break
            elif choice == '1':
                self.execute_command_direct('hermes auth status', "Authentication Status")
            elif choice == '2':
                self.execute_command_direct('hermes calendar test-connection', "Calendar API Connection Test")
            elif choice == '3':
                def_cal = config_manager.get('calendar.default_calendar', 'primary')
                tz_cfg = config_manager.get('timezone', 'system default')
                self.clear_screen()
                self.draw_box(["Calendar System Info"], color=Fore.CYAN, padding=6)
                print()
                print(f"  {Fore.CYAN}Default Calendar:{Style.RESET_ALL} {def_cal}")
                print(f"  {Fore.CYAN}Configured Timezone:{Style.RESET_ALL} {tz_cfg}")
                print()
                print(Fore.CYAN + "Press Enter to continue...", end="")
                input()
            elif choice == '4':
                self.execute_command_direct('hermes cache clear --confirm', "Refresh & Clear Cache")
            elif choice == '5':
                self.execute_command_direct('hermes auth login', "Re-authenticate")
            elif choice == '6':
                self.execute_command_direct('hermes auth logout', "Disconnect Account")
            elif choice == '7':
                self.handle_reminders_submenu()
            else:
                self.show_error("Invalid choice.")

    def handle_reminders_submenu(self):
        while True:
            self.clear_screen()
            width = self.get_width()
            self.draw_box(["Reminders"], color=Fore.CYAN, padding=10)
            print()
            lines = [
                "[1] Run reminders (once)",
                "[2] Run reminders (continuous)",
                "[3] Show pending reminders",
                "",
                "[b] Back to System Menu",
            ]
            max_len = max(len(line) for line in lines)
            offset = (width - max_len) // 2
            margin = " " * max(0, offset)
            for line in lines:
                print(margin + Fore.WHITE + Style.BRIGHT + line)
            print()
            prompt = "Choose an option [1-3, b]: "
            offset = (width - len(prompt)) // 2
            margin = " " * max(0, offset)
            print(margin + Fore.CYAN + prompt, end="")
            choice = self.get_user_choice()
            if choice == 'b':
                break
            elif choice == '1':
                self.execute_command_direct('hermes reminders run --once', "Run reminders (once)")
            elif choice == '2':
                self.execute_command_direct('hermes reminders run', "Run reminders (continuous)")
            elif choice == '3':
                self._show_pending_reminders()

    # =========================================================================
    # Gmail Interactive Menus
    # =========================================================================

    def show_gmail_main_menu(self):
        self.clear_screen()
        width = self.get_width()
        self.draw_box(["Gmail MENU"], color=Fore.WHITE, padding=10)
        print()
        lines = [
            "Manage Gmail features",
            "",
            "[1] Inbox",
            "[2] Search emails",
            "[3] Compose email",
            "[4] Threads / Conversations",
            "[5] Labels",
            "[6] Drafts",
            "[7] System & Account",
            "",
            "[b] Back to Main Menu",
            "[0] Exit",
        ]
        max_len = max(len(line) for line in lines)
        offset = (width - max_len) // 2
        margin = " " * max(0, offset)
        for line in lines:
            print(margin + Fore.WHITE + Style.BRIGHT + line)

    def handle_gmail_menu(self):
        while True:
            self.show_gmail_main_menu()
            print()
            width = self.get_width()
            prompt = "Choose an option [0-7, b]: "
            offset = (width - len(prompt)) // 2
            margin = " " * max(0, offset)
            print(margin + Fore.CYAN + prompt, end="")
            choice = self.get_user_choice()
            if choice == '0':
                self.show_goodbye()
                sys.exit(0)
            elif choice == 'b':
                break
            elif choice == '1':
                self.handle_gmail_inbox_menu()
            elif choice == '2':
                print(Fore.CYAN + "Enter search query (e.g. from:someone, is:unread, subject:meeting): ", end="")
                query = input().strip()
                if query:
                    self.execute_command_direct(f'hermes gmail list --query "{query}"', f"Search: {query}")
            elif choice == '3':
                self._interactive_compose()
            elif choice == '4':
                self.handle_gmail_threads_menu()
            elif choice == '5':
                self.handle_gmail_labels_menu()
            elif choice == '6':
                self.handle_gmail_drafts_menu()
            elif choice == '7':
                self.handle_gmail_system_menu()
            else:
                self.show_error("Invalid choice. Please select 0-7 or b.")

    def handle_gmail_inbox_menu(self):
        while True:
            self.clear_screen()
            width = self.get_width()
            self.draw_box(["Inbox MENU"], color=Fore.CYAN, padding=10)
            print()
            lines = [
                "Inbox operations",
                "",
                "[1] Latest emails",
                "[2] Unread emails",
                "[3] Starred emails",
                "[4] Open / view email",
                "[5] Mark email as read",
                "[6] Mark email as unread",
                "[7] Star email",
                "[8] Unstar email",
                "[9] Archive email",
                "[10] Move email to trash",
                "[11] Reply to email",
                "[12] Forward email",
                "",
                "[b] Back to Gmail Menu",
                "[0] Exit",
            ]
            max_len = max(len(line) for line in lines)
            offset = (width - max_len) // 2
            margin = " " * max(0, offset)
            for line in lines:
                print(margin + Fore.WHITE + Style.BRIGHT + line)
            print()
            prompt = "Choose an option [1-12, b]: "
            offset = (width - len(prompt)) // 2
            margin = " " * max(0, offset)
            print(margin + Fore.CYAN + prompt, end="")
            choice = self.get_user_choice()
            if choice == '0':
                self.show_goodbye()
                sys.exit(0)
            elif choice == 'b':
                break
            elif choice == '1':
                self.execute_command_direct('hermes gmail list', "Latest Emails")
            elif choice == '2':
                self.execute_command_direct('hermes gmail list --query "is:unread"', "Unread Emails")
            elif choice == '3':
                self.execute_command_direct('hermes gmail list --query "is:starred"', "Starred Emails")
            elif choice == '4':
                print(Fore.CYAN + "Enter message ID to view: ", end="")
                msg_id = input().strip()
                if msg_id:
                    self.execute_command_direct(f'hermes gmail get "{msg_id}"', "View Email")
            elif choice == '5':
                print(Fore.CYAN + "Enter message ID to mark as read: ", end="")
                msg_id = input().strip()
                if msg_id:
                    self.execute_command_direct(f'hermes gmail mark "{msg_id}" --read', "Mark Read")
            elif choice == '6':
                print(Fore.CYAN + "Enter message ID to mark as unread: ", end="")
                msg_id = input().strip()
                if msg_id:
                    self.execute_command_direct(f'hermes gmail mark "{msg_id}" --unread', "Mark Unread")
            elif choice == '7':
                print(Fore.CYAN + "Enter message ID to star: ", end="")
                msg_id = input().strip()
                if msg_id:
                    self.execute_command_direct(f'hermes gmail mark "{msg_id}" --star', "Star Email")
            elif choice == '8':
                print(Fore.CYAN + "Enter message ID to unstar: ", end="")
                msg_id = input().strip()
                if msg_id:
                    self.execute_command_direct(f'hermes gmail mark "{msg_id}" --unstar', "Unstar Email")
            elif choice == '9':
                print(Fore.CYAN + "Enter message ID to archive: ", end="")
                msg_id = input().strip()
                if msg_id:
                    self.execute_command_direct(f'hermes gmail mark "{msg_id}" --archive', "Archive Email")
            elif choice == '10':
                print(Fore.CYAN + "Enter message ID to move to trash: ", end="")
                msg_id = input().strip()
                if msg_id:
                    self.execute_command_direct(f'hermes gmail mark "{msg_id}" --trash', "Trash Email")
            elif choice == '11':
                print(Fore.CYAN + "Enter message ID to reply to: ", end="")
                msg_id = input().strip()
                if msg_id:
                    print(Fore.CYAN + "Enter reply body: ", end="")
                    body = input().strip()
                    if body:
                        self.execute_command_direct(f'hermes gmail reply "{msg_id}" --body "{body}"', "Reply Email")
            elif choice == '12':
                print(Fore.CYAN + "Enter message ID to forward: ", end="")
                msg_id = input().strip()
                if msg_id:
                    print(Fore.CYAN + "Forward to email address: ", end="")
                    to_addr = input().strip()
                    if to_addr:
                        self.execute_command_direct(f'hermes gmail forward "{msg_id}" --to "{to_addr}"', "Forward Email")

    # -------------------------------------------------------------------------
    # Compose helpers
    # -------------------------------------------------------------------------

    def _get_editor(self) -> str:
        """Return the editor command to use, falling back to notepad.exe on Windows."""
        import os
        # 1. Hermes config editor setting
        try:
            cfg = ConfigManager()
            editor = cfg.get('editor', None)
            if editor:
                return editor
        except Exception:
            pass
        # 2. EDITOR env var
        editor = os.environ.get('EDITOR', '').strip()
        if editor:
            return editor
        # 3. Windows Notepad fallback
        return 'notepad.exe'

    def _open_editor_for_body(self, tmp_path: str) -> bool:
        """Open the editor with tmp_path, wait for it to close. Returns True on success."""
        import subprocess as _sp
        editor = self._get_editor()
        print(Fore.CYAN + "\nOpening email body editor...")
        print(Fore.GREEN + "✓ Editor opened.")
        print(Fore.WHITE + "\nWrite your email, save the file, and close the editor.")
        print(Fore.CYAN + "Waiting for editor...\n")
        try:
            _sp.call([editor, tmp_path])
            return True
        except FileNotFoundError:
            # Try shell=True as a last resort (handles paths with spaces on Windows)
            try:
                _sp.call(f'"{editor}" "{tmp_path}"', shell=True)
                return True
            except Exception as exc:
                self.show_error(f"Could not launch editor '{editor}': {exc}")
                return False
        except Exception as exc:
            self.show_error(f"Could not launch editor: {exc}")
            return False

    def _validate_email_address(self, addr: str) -> bool:
        """Simple RFC-5322 style email validation."""
        import re
        pattern = r'^[^@\s]+@[^@\s]+\.[^@\s]+$'
        return bool(re.match(pattern, addr.strip()))

    def _validate_email_list(self, addr_string: str) -> tuple:
        """Validate a comma-separated list of email addresses.
        Returns (is_valid: bool, invalid_addr: str)."""
        addrs = [a.strip() for a in addr_string.split(',') if a.strip()]
        for addr in addrs:
            if not self._validate_email_address(addr):
                return False, addr
        return True, ''

    def _format_file_size(self, size_bytes: int) -> str:
        """Return a human-readable file size string."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"

    def _collect_attachments(self, attachments: list, prompt_label: str = "Attachment (optional)") -> list:
        """Interactive attachment collection loop. Returns updated attachments list."""
        import os
        while True:
            print(Fore.CYAN + f"\n{prompt_label}:")
            print(Fore.WHITE + "> ", end="")
            raw = input().strip()
            # Strip surrounding quotes if the user typed them
            if raw.startswith('"') and raw.endswith('"'):
                raw = raw[1:-1]
            if not raw:
                # User pressed Enter — skip/done
                break
            path = os.path.normpath(os.path.abspath(raw))
            if not os.path.exists(path):
                print(Fore.RED + Style.BRIGHT + "✗ File not found.")
                continue
            if not os.path.isfile(path):
                print(Fore.RED + Style.BRIGHT + "✗ Path is not a file (it may be a directory).")
                continue
            if not os.access(path, os.R_OK):
                print(Fore.RED + Style.BRIGHT + "✗ File is not readable.")
                continue
            # Duplicate check using canonical path
            if path in [a['path'] for a in attachments]:
                print(Fore.RED + Style.BRIGHT + "✗ File is already attached.")
                print(Fore.CYAN + "Add another attachment? [y/N]: ", end="")
                again = input().strip().lower()
                if again == 'y':
                    prompt_label = "Attachment"
                    continue
                break
            size = os.path.getsize(path)
            name = os.path.basename(path)
            attachments.append({'path': path, 'name': name, 'size': size})
            print(Fore.GREEN + Style.BRIGHT + f"✓ Attachment added: {name}")
            print(Fore.CYAN + "Add another attachment? [y/N]: ", end="")
            again = input().strip().lower()
            if again != 'y':
                break
            prompt_label = "Attachment"
        return attachments

    def _show_review(self, to: str, subject: str, cc: str, bcc: str,
                     attachments: list, body: str):
        """Print the email review panel."""
        print(Fore.CYAN + Style.BRIGHT + "\n✉️ Email Review")
        print(Fore.CYAN + "=" * 50)
        print(Fore.YELLOW + f"\nTo:\n{to}")
        print(Fore.YELLOW + f"\nSubject:\n{subject}")
        print(Fore.YELLOW + f"\nCc:\n{cc if cc else '-'}")
        print(Fore.YELLOW + f"\nBcc:\n{bcc if bcc else '-'}")
        if attachments:
            print(Fore.YELLOW + "\nAttachments:")
            for i, att in enumerate(attachments, 1):
                size_str = self._format_file_size(att['size'])
                print(Fore.WHITE + f"  [{i}] {att['name']:<40} {size_str}")
        else:
            print(Fore.YELLOW + "\nAttachments:\n  (none)")
        print(Fore.YELLOW + "\nBody:")
        print(Fore.WHITE + "-" * 50)
        print(Fore.WHITE + body)
        print(Fore.WHITE + "-" * 50)

    # -------------------------------------------------------------------------
    # Main compose flow
    # -------------------------------------------------------------------------

    def _interactive_compose(self):
        import os, tempfile

        self.clear_screen()
        print(Fore.CYAN + Style.BRIGHT + "✉️ Compose Email")
        print(Fore.CYAN + "=" * 50)

        # ── Step 1: To ────────────────────────────────────────────────────────
        while True:
            print(Fore.CYAN + "\nTo: ", end="")
            to = input().strip()
            if not to:
                self.show_error("Recipient 'To' is required.")
                return
            valid, bad = self._validate_email_list(to)
            if not valid:
                print(Fore.RED + Style.BRIGHT + f"✗ Invalid email address: {bad}")
                continue
            break

        # ── Step 2: Subject ───────────────────────────────────────────────────
        print(Fore.CYAN + "\nSubject: ", end="")
        subject = input().strip()

        # ── Step 3: Body editor ───────────────────────────────────────────────
        tmp_file = None
        try:
            # Create temp file in OS temp dir
            fd, tmp_path = tempfile.mkstemp(prefix='hermes_email_body_', suffix='.txt')
            os.close(fd)

            body = ''
            while True:
                ok = self._open_editor_for_body(tmp_path)
                if not ok:
                    self.show_error("Editor failed to open. Cancelling compose.")
                    return

                try:
                    with open(tmp_path, 'r', encoding='utf-8', errors='replace') as f:
                        body = f.read()
                except Exception as exc:
                    self.show_error(f"Could not read body file: {exc}")
                    return

                body = body.strip()
                if not body:
                    print(Fore.RED + Style.BRIGHT + "\n✗ Email body cannot be empty.")
                    print(Fore.CYAN + "Reopen editor to write the body? [y/N]: ", end="")
                    retry = input().strip().lower()
                    if retry == 'y':
                        # Clear the temp file so it's clean on reopen
                        open(tmp_path, 'w').close()
                        continue
                    else:
                        print_info("Compose cancelled.")
                        return
                break

            print(Fore.GREEN + Style.BRIGHT + "\n✓ Email body loaded.")

            # ── Step 3b: Profile Assistance & Suggestions ──────────────────────
            try:
                from .interactive_profile import PersonalProfileUI
                profile_ui = PersonalProfileUI(self)
                body = profile_ui.handle_compose_profile_assistance(subject, body, tmp_path)
            except Exception:
                pass

            # ── Step 4: Attachments ───────────────────────────────────────────
            attachments: list = []
            attachments = self._collect_attachments(attachments)

            # ── Step 5: Cc ────────────────────────────────────────────────────
            cc = ''
            while True:
                print(Fore.CYAN + "\nCc (optional):")
                print(Fore.WHITE + "> ", end="")
                cc_raw = input().strip()
                if not cc_raw:
                    break
                valid, bad = self._validate_email_list(cc_raw)
                if not valid:
                    print(Fore.RED + Style.BRIGHT + f"✗ Invalid email address: {bad}")
                    continue
                cc = cc_raw
                break

            # ── Step 6: Bcc ───────────────────────────────────────────────────
            bcc = ''
            while True:
                print(Fore.CYAN + "\nBcc (optional):")
                print(Fore.WHITE + "> ", end="")
                bcc_raw = input().strip()
                if not bcc_raw:
                    break
                valid, bad = self._validate_email_list(bcc_raw)
                if not valid:
                    print(Fore.RED + Style.BRIGHT + f"✗ Invalid email address: {bad}")
                    continue
                bcc = bcc_raw
                break

            # ── Review / Edit / Send loop ─────────────────────────────────────
            while True:
                self.clear_screen()
                self._show_review(to, subject, cc, bcc, attachments, body)
                print()
                print(Fore.CYAN + "Send this email? [y/N]: ", end="")
                confirm = input().strip().lower()

                if confirm == 'y':
                    self._do_send(to, subject, cc, bcc, attachments, body)
                    return

                # Show correction menu
                print()
                print(Fore.CYAN + Style.BRIGHT + "Email Review")
                print(Fore.CYAN + "=" * 50)
                print(Fore.WHITE + "[1] Edit To")
                print(Fore.WHITE + "[2] Edit Subject")
                print(Fore.WHITE + "[3] Edit Body")
                print(Fore.WHITE + "[4] Edit Attachments")
                print(Fore.WHITE + "[5] Edit Cc")
                print(Fore.WHITE + "[6] Edit Bcc")
                print(Fore.WHITE + "[7] Review Again")
                print(Fore.WHITE + "[8] Send")
                print(Fore.WHITE + "[9] Insert Profile Information / Snippet")
                print(Fore.WHITE + "[b] Cancel")
                print()
                print(Fore.CYAN + "Select: ", end="")
                edit_choice = input().strip().lower()

                if edit_choice == '1':
                    # Edit To
                    while True:
                        print(Fore.CYAN + "\nTo: ", end="")
                        new_to = input().strip()
                        if not new_to:
                            print(Fore.RED + Style.BRIGHT + "✗ To cannot be empty.")
                            continue
                        valid, bad = self._validate_email_list(new_to)
                        if not valid:
                            print(Fore.RED + Style.BRIGHT + f"✗ Invalid email address: {bad}")
                            continue
                        to = new_to
                        break

                elif edit_choice == '2':
                    # Edit Subject
                    print(Fore.CYAN + "\nSubject: ", end="")
                    new_sub = input().strip()
                    if new_sub:
                        subject = new_sub

                elif edit_choice == '3':
                    # Edit Body — reopen editor with existing content
                    try:
                        with open(tmp_path, 'w', encoding='utf-8') as f:
                            f.write(body)
                    except Exception:
                        pass
                    ok = self._open_editor_for_body(tmp_path)
                    if ok:
                        try:
                            with open(tmp_path, 'r', encoding='utf-8', errors='replace') as f:
                                new_body = f.read().strip()
                            if new_body:
                                body = new_body
                                print(Fore.GREEN + Style.BRIGHT + "\n✓ Email body updated.")
                                time.sleep(1)
                            else:
                                print(Fore.YELLOW + "\n⚠ Empty body ignored; previous body retained.")
                                time.sleep(1.5)
                        except Exception as exc:
                            self.show_error(f"Could not read body: {exc}")

                elif edit_choice == '4':
                    # Edit Attachments
                    self._edit_attachments_menu(attachments)

                elif edit_choice == '5':
                    # Edit Cc
                    while True:
                        print(Fore.CYAN + "\nCc (optional):")
                        print(Fore.WHITE + "> ", end="")
                        cc_raw = input().strip()
                        if not cc_raw:
                            cc = ''
                            break
                        valid, bad = self._validate_email_list(cc_raw)
                        if not valid:
                            print(Fore.RED + Style.BRIGHT + f"✗ Invalid email address: {bad}")
                            continue
                        cc = cc_raw
                        break

                elif edit_choice == '6':
                    # Edit Bcc
                    while True:
                        print(Fore.CYAN + "\nBcc (optional):")
                        print(Fore.WHITE + "> ", end="")
                        bcc_raw = input().strip()
                        if not bcc_raw:
                            bcc = ''
                            break
                        valid, bad = self._validate_email_list(bcc_raw)
                        if not valid:
                            print(Fore.RED + Style.BRIGHT + f"✗ Invalid email address: {bad}")
                            continue
                        bcc = bcc_raw
                        break

                elif edit_choice == '7':
                    # Review Again — loop back
                    continue

                elif edit_choice == '8':
                    self._do_send(to, subject, cc, bcc, attachments, body)
                    return

                elif edit_choice == '9':
                    try:
                        from .interactive_profile import PersonalProfileUI
                        profile_ui = PersonalProfileUI(self)
                        body = profile_ui.handle_compose_profile_assistance(subject, body, tmp_path)
                    except Exception:
                        pass

                elif edit_choice == 'b':
                    print_info("Compose cancelled.")
                    time.sleep(1)
                    return

        finally:
            # Always clean up the temporary body file
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    def _edit_attachments_menu(self, attachments: list):
        """Interactive sub-menu to add/remove attachments."""
        import os
        while True:
            print()
            print(Fore.CYAN + Style.BRIGHT + "Attachments")
            print(Fore.CYAN + "-" * 40)
            if attachments:
                for i, att in enumerate(attachments, 1):
                    size_str = self._format_file_size(att['size'])
                    print(Fore.WHITE + f"  [{i}] {att['name']:<40} {size_str}")
            else:
                print(Fore.WHITE + "  (no attachments)")
            print()
            print(Fore.WHITE + "[a] Add attachment")
            print(Fore.WHITE + "[r] Remove attachment")
            print(Fore.WHITE + "[d] Done")
            print(Fore.WHITE + "[b] Back")
            print()
            print(Fore.CYAN + "Select: ", end="")
            choice = input().strip().lower()

            if choice == 'a':
                self._collect_attachments(attachments, prompt_label="Attachment")
            elif choice == 'r':
                if not attachments:
                    print(Fore.YELLOW + "No attachments to remove.")
                    time.sleep(1)
                    continue
                print(Fore.CYAN + "\nRemove attachment (enter number): ")
                print(Fore.WHITE + "> ", end="")
                idx_raw = input().strip()
                try:
                    idx = int(idx_raw) - 1
                    if 0 <= idx < len(attachments):
                        removed = attachments.pop(idx)
                        print(Fore.GREEN + Style.BRIGHT + f"✓ Removed: {removed['name']}")
                        time.sleep(1)
                    else:
                        print(Fore.RED + Style.BRIGHT + "✗ Invalid number.")
                        time.sleep(1)
                except ValueError:
                    print(Fore.RED + Style.BRIGHT + "✗ Please enter a valid number.")
                    time.sleep(1)
            elif choice in ('d', 'b'):
                break

    def _do_send(self, to: str, subject: str, cc: str, bcc: str,
                 attachments: list, body: str):
        """Validate size, build MIME message, and send via existing GmailService."""
        import os

        # Gmail API hard limit ~35 MB raw (25 MB post-encoding)
        MAX_SIZE_BYTES = 25 * 1024 * 1024

        # Check total attachment size
        total_att_size = sum(a['size'] for a in attachments)
        # Rough estimate: base64 encoding adds ~33% overhead
        estimated_total = len(body.encode('utf-8')) + int(total_att_size * 1.34)
        if estimated_total > MAX_SIZE_BYTES:
            print(Fore.RED + Style.BRIGHT + "\n✗ Email exceeds the maximum allowed message size (25 MB).")
            print(Fore.YELLOW + "Please remove some attachments and try again.")
            time.sleep(2)
            return

        # Build attachment path list for GmailService
        attach_paths = [a['path'] for a in attachments] if attachments else None

        print(Fore.CYAN + "\nSending email...")

        try:
            from ..services.gmail import GmailService
            from ..auth.oauth import OAuthManager

            oauth = OAuthManager()
            svc = GmailService(oauth)

            msg_id = svc.send_message(
                to=to,
                subject=subject,
                body=body,
                cc=cc if cc else None,
                bcc=bcc if bcc else None,
                attachments=attach_paths,
            )
            if msg_id:
                print(Fore.GREEN + Style.BRIGHT + f"\n✅ Email sent successfully! (id: {msg_id})")
            else:
                print(Fore.RED + Style.BRIGHT + "\n✗ Failed to send email. Please check your connection and try again.")
        except Exception as exc:
            print(Fore.RED + Style.BRIGHT + f"\n✗ Error sending email: {exc}")

        time.sleep(2)

    def handle_gmail_threads_menu(self):
        while True:
            self.clear_screen()
            width = self.get_width()
            self.draw_box(["Threads MENU"], color=Fore.CYAN, padding=8)
            print()
            lines = [
                "Conversation threads",
                "",
                "[1] List recent threads",
                "[2] View conversation thread",
                "",
                "[b] Back to Gmail Menu",
                "[0] Exit",
            ]
            max_len = max(len(line) for line in lines)
            offset = (width - max_len) // 2
            margin = " " * max(0, offset)
            for line in lines:
                print(margin + Fore.WHITE + Style.BRIGHT + line)
            print()
            prompt = "Choose an option [1-2, b]: "
            offset = (width - len(prompt)) // 2
            margin = " " * max(0, offset)
            print(margin + Fore.CYAN + prompt, end="")
            choice = self.get_user_choice()
            if choice == '0':
                self.show_goodbye()
                sys.exit(0)
            elif choice == 'b':
                break
            elif choice == '1':
                self.execute_command_direct('hermes gmail threads', "Recent Threads")
            elif choice == '2':
                print(Fore.CYAN + "Enter thread ID: ", end="")
                tid = input().strip()
                if tid:
                    self.execute_command_direct(f'hermes gmail thread "{tid}"', "View Thread")

    def handle_gmail_labels_menu(self):
        try:
            from ..services.gmail import GmailService
            from ..auth.oauth import OAuthManager
            from .interactive_labels import run_labels_menu
            service = GmailService(OAuthManager())
            run_labels_menu(service)
        except Exception as exc:
            self.show_error(f"Error accessing Gmail labels: {exc}")

    def handle_gmail_drafts_menu(self):
        while True:
            self.clear_screen()
            width = self.get_width()
            self.draw_box(["Drafts MENU"], color=Fore.CYAN, padding=8)
            print()
            lines = [
                "Drafts management",
                "",
                "[1] List drafts",
                "[2] Create new draft",
                "",
                "[b] Back to Gmail Menu",
                "[0] Exit",
            ]
            max_len = max(len(line) for line in lines)
            offset = (width - max_len) // 2
            margin = " " * max(0, offset)
            for line in lines:
                print(margin + Fore.WHITE + Style.BRIGHT + line)
            print()
            prompt = "Choose an option [1-2, b]: "
            offset = (width - len(prompt)) // 2
            margin = " " * max(0, offset)
            print(margin + Fore.CYAN + prompt, end="")
            choice = self.get_user_choice()
            if choice == '0':
                self.show_goodbye()
                sys.exit(0)
            elif choice == 'b':
                break
            elif choice == '1':
                self.execute_command_direct('hermes gmail drafts', "List Drafts")
            elif choice == '2':
                print(Fore.CYAN + "To: ", end="")
                to = input().strip()
                print(Fore.CYAN + "Subject: ", end="")
                subj = input().strip()
                print(Fore.CYAN + "Body: ", end="")
                body = input().strip()
                if to and subj:
                    self.execute_command_direct(f'hermes gmail draft --to "{to}" --subject "{subj}" --body "{body}"', "Save Draft")

    def handle_gmail_system_menu(self):
        while True:
            self.clear_screen()
            width = self.get_width()
            self.draw_box(["Gmail System MENU"], color=Fore.CYAN, padding=6)
            print()
            lines = [
                "System and Account configuration",
                "",
                "[1] View Gmail profile & account",
                "[2] Test Gmail API connection",
                "[3] View authentication status",
                "",
                "[b] Back to Gmail Menu",
                "[0] Exit",
            ]
            max_len = max(len(line) for line in lines)
            offset = (width - max_len) // 2
            margin = " " * max(0, offset)
            for line in lines:
                print(margin + Fore.WHITE + Style.BRIGHT + line)
            print()
            prompt = "Choose an option [1-3, b]: "
            offset = (width - len(prompt)) // 2
            margin = " " * max(0, offset)
            print(margin + Fore.CYAN + prompt, end="")
            choice = self.get_user_choice()
            if choice == '0':
                self.show_goodbye()
                sys.exit(0)
            elif choice == 'b':
                break
            elif choice == '1':
                try:
                    subprocess.call('hermes gmail profile', shell=True)
                except Exception as e:
                    print(Fore.RED + f"❌ Error: {e}")
            elif choice == '2':
                self.execute_command_direct('hermes gmail test-connection', "Test Connection")
            elif choice == '3':
                self.execute_command_direct('hermes auth status', "Auth Status")

    def show_meet_main_menu(self):
        self.clear_screen()
        width = self.get_width()
        self.draw_box(["Google Meet MENU"], color=Fore.LIGHTRED_EX, padding=8)
        print()
        lines = [
            "Manage and join Google Meet video conferences",
            "",
            "[1] Create meeting space",
            "[2] Join / open meeting in browser",
            "[3] Inspect meeting details",
            "[4] Active / ongoing meetings",
            "[5] Conference history",
            "[6] Conference participants",
            "[7] Conference recordings",
            "[8] Conference transcripts",
            "[9] End active conference",
            "[10] Test Meet API connection",
            "",
            "[b] Back to Main Menu",
            "[0] Exit",
        ]
        max_len = max(len(line) for line in lines)
        offset = (width - max_len) // 2
        margin = " " * max(0, offset)
        for line in lines:
            print(margin + Fore.WHITE + Style.BRIGHT + line)

    def handle_meet_menu(self):
        while True:
            self.show_meet_main_menu()
            print()
            width = self.get_width()
            prompt = "Choose an option [0-10, b]: "
            offset = (width - len(prompt)) // 2
            margin = " " * max(0, offset)
            print(margin + Fore.CYAN + prompt, end="")
            choice = self.get_user_choice()
            if choice == '0':
                self.show_goodbye()
                sys.exit(0)
            elif choice == 'b':
                break
            elif choice == '1':
                print(Fore.CYAN + "Meeting type [private/public] (default: private): ", end="")
                mtype = input().strip().lower() or "private"
                self.execute_command_direct(f'hermes meet create --type {mtype}', "Create Meeting Space")
            elif choice == '2':
                print(Fore.CYAN + "Enter meeting code or URL: ", end="")
                meeting = input().strip()
                if meeting:
                    self.execute_command_direct(f'hermes meet join "{meeting}"', "Join Meeting")
            elif choice == '3':
                print(Fore.CYAN + "Enter meeting code, URL, or space name: ", end="")
                meeting = input().strip()
                if meeting:
                    self.execute_command_direct(f'hermes meet details "{meeting}"', "Meeting Details")
            elif choice == '4':
                self.execute_command_direct('hermes meet active', "Active Meetings")
            elif choice == '5':
                self.execute_command_direct('hermes meet list', "Conference History")
            elif choice == '6':
                print(Fore.CYAN + "Enter conference record name (e.g. conferenceRecords/xyz): ", end="")
                record = input().strip()
                if record:
                    self.execute_command_direct(f'hermes meet participants "{record}"', "Participants")
            elif choice == '7':
                print(Fore.CYAN + "Enter conference record name (e.g. conferenceRecords/xyz): ", end="")
                record = input().strip()
                if record:
                    self.execute_command_direct(f'hermes meet recordings "{record}"', "Recordings")
            elif choice == '8':
                print(Fore.CYAN + "Enter conference record name (e.g. conferenceRecords/xyz): ", end="")
                record = input().strip()
                if record:
                    self.execute_command_direct(f'hermes meet transcripts "{record}"', "Transcripts")
            elif choice == '9':
                print(Fore.CYAN + "Enter space name to end (e.g. spaces/xyz): ", end="")
                space = input().strip()
                if space:
                    self.execute_command_direct(f'hermes meet end "{space}" --yes', "End Active Conference")
            elif choice == '10':
                self.execute_command_direct('hermes meet test-connection', "Test Meet API Connection")
            else:
                self.show_error("Invalid choice. Please select 0-10 or b.")

    def show_chat_main_menu(self):
        self.clear_screen()
        width = self.get_width()
        self.draw_box(["Google Chat MENU"], color=Fore.CYAN, padding=8)
        print()
        lines = [
            "Manage Google Chat spaces, messages, members, and reactions",
            "",
            "[1] List chat spaces",
            "[2] Inspect space details",
            "[3] List messages in space",
            "[4] Send message",
            "[5] Reply to message",
            "[6] Edit message",
            "[7] Delete message",
            "[8] List space members",
            "[9] Add member to space",
            "[10] Remove member from space",
            "[11] Add emoji reaction",
            "[12] Remove emoji reaction",
            "[13] Search messages",
            "[14] List threads in space",
            "[15] Test Chat API connection",
            "",
            "[b] Back to Main Menu",
            "[0] Exit",
        ]
        max_len = max(len(line) for line in lines)
        offset = (width - max_len) // 2
        margin = " " * max(0, offset)
        for line in lines:
            print(margin + Fore.WHITE + Style.BRIGHT + line)

    def handle_chat_menu(self):
        while True:
            self.show_chat_main_menu()
            print()
            width = self.get_width()
            prompt = "Choose an option [0-15, b]: "
            offset = (width - len(prompt)) // 2
            margin = " " * max(0, offset)
            print(margin + Fore.CYAN + prompt, end="")
            choice = self.get_user_choice()
            if choice == '0':
                self.show_goodbye()
                sys.exit(0)
            elif choice == 'b':
                break
            elif choice == '1':
                self.execute_command_direct('hermes chat spaces', "List Chat Spaces")
            elif choice == '2':
                print(Fore.CYAN + "Enter space name or ID (e.g. spaces/xyz): ", end="")
                space_id = input().strip()
                if space_id:
                    self.execute_command_direct(f'hermes chat spaces "{space_id}"', "Space Details")
            elif choice == '3':
                print(Fore.CYAN + "Enter space name or ID (e.g. spaces/xyz): ", end="")
                space_id = input().strip()
                if space_id:
                    self.execute_command_direct(f'hermes chat messages "{space_id}"', "Space Messages")
            elif choice == '4':
                print(Fore.CYAN + "Enter space name or ID: ", end="")
                space_id = input().strip()
                print(Fore.CYAN + "Enter message: ", end="")
                msg = input().strip()
                if space_id and msg:
                    self.execute_command_direct(f'hermes chat send "{space_id}" -m "{msg}"', "Send Message")
            elif choice == '5':
                print(Fore.CYAN + "Enter message name or ID: ", end="")
                msg_id = input().strip()
                print(Fore.CYAN + "Enter reply: ", end="")
                reply = input().strip()
                if msg_id and reply:
                    self.execute_command_direct(f'hermes chat reply "{msg_id}" -m "{reply}"', "Reply to Message")
            elif choice == '6':
                print(Fore.CYAN + "Enter message name or ID to edit: ", end="")
                msg_id = input().strip()
                print(Fore.CYAN + "Enter updated text: ", end="")
                new_text = input().strip()
                if msg_id and new_text:
                    self.execute_command_direct(f'hermes chat edit "{msg_id}" -m "{new_text}"', "Edit Message")
            elif choice == '7':
                print(Fore.CYAN + "Enter message name or ID to delete: ", end="")
                msg_id = input().strip()
                if msg_id:
                    self.execute_command_direct(f'hermes chat delete "{msg_id}" --yes', "Delete Message")
            elif choice == '8':
                print(Fore.CYAN + "Enter space name or ID: ", end="")
                space_id = input().strip()
                if space_id:
                    self.execute_command_direct(f'hermes chat members "{space_id}"', "Space Members")
            elif choice == '9':
                print(Fore.CYAN + "Enter space name or ID: ", end="")
                space_id = input().strip()
                print(Fore.CYAN + "Enter user ID or email: ", end="")
                user = input().strip()
                if space_id and user:
                    self.execute_command_direct(f'hermes chat add-member "{space_id}" "{user}"', "Add Member")
            elif choice == '10':
                print(Fore.CYAN + "Enter space name or ID: ", end="")
                space_id = input().strip()
                print(Fore.CYAN + "Enter member ID or resource name: ", end="")
                mem = input().strip()
                if space_id and mem:
                    self.execute_command_direct(f'hermes chat remove-member "{space_id}" "{mem}" --yes', "Remove Member")
            elif choice == '11':
                print(Fore.CYAN + "Enter message name or ID: ", end="")
                msg_id = input().strip()
                print(Fore.CYAN + "Enter emoji (e.g. 👍, ❤️): ", end="")
                emoji = input().strip() or "👍"
                if msg_id:
                    self.execute_command_direct(f'hermes chat react "{msg_id}" "{emoji}"', "Add Reaction")
            elif choice == '12':
                print(Fore.CYAN + "Enter reaction resource name to remove: ", end="")
                rx_name = input().strip()
                if rx_name:
                    self.execute_command_direct(f'hermes chat unreact "{rx_name}"', "Remove Reaction")
            elif choice == '13':
                print(Fore.CYAN + "Enter search query: ", end="")
                query = input().strip()
                if query:
                    self.execute_command_direct(f'hermes chat search "{query}"', "Search Chat Messages")
            elif choice == '14':
                print(Fore.CYAN + "Enter space name or ID: ", end="")
                space_id = input().strip()
                if space_id:
                    self.execute_command_direct(f'hermes chat threads "{space_id}"', "Chat Threads")
            elif choice == '15':
                self.execute_command_direct('hermes chat test-connection', "Test Chat API Connection")
            else:
                self.show_error("Invalid choice. Please select 0-15 or b.")

    def show_error(self, message: str):
        """Show error message"""
        print()
        print(Fore.RED + Style.BRIGHT + f"❌ {message}")
        time.sleep(2)
    
    def show_success(self, message: str):
        """Show success message"""
        print()
        print(Fore.GREEN + Style.BRIGHT + f"✅ {message}")
        time.sleep(2)
    
    def loading_animation(self, text: str, duration: int):
        """Show loading animation"""
        print(Fore.CYAN + Style.BRIGHT + f"{text}", end="")
        
        for i in range(duration * 2):
            time.sleep(0.5)
            print(".", end="", flush=True)
        
        print(" " + Fore.GREEN + Style.BRIGHT + "✓")
        time.sleep(0.5)
    
    def clear_screen(self):
        """Clear the terminal screen"""
        from ..utils.formatters import clear_screen
        clear_screen()
    
    def run(self):
        """Run the interactive menu system"""
        try:
            self.show_welcome()
            time.sleep(2)
            
            while True:
                self.show_main_menu()
                choice = self.get_user_choice()
                
                if choice == '0':
                    self.show_goodbye()
                    break
                elif choice == '7':
                    self.handle_profile_menu()
                elif choice in ('15', '16'):
                    self.handle_chat_menu()
                elif choice in ('22', '23'):
                    self.execute_command_direct('hermes cache clear --confirm', "🔄 Refreshing Data")
                elif choice in self.options:
                    self.handle_service_menu(choice)
                else:
                    self.show_error(f"Invalid choice. Please select 0-{len(self.options)}.")
        
        except KeyboardInterrupt:
            self.show_goodbye()
    
    def handle_profile_menu(self):
        """Handle Personal Profile interactive menu"""
        from .interactive_profile import PersonalProfileUI
        ui = PersonalProfileUI(self)
        ui.handle_profile_menu()

    def handle_service_menu(self, service_key: str):
        """Handle service-specific menu"""
        if service_key == '1':
            self.handle_calendar_menu()
            return
        if service_key == '2':
            self.handle_gmail_menu()
            return
        if service_key == '5':
            self.handle_meet_menu()
            return
        if service_key == '7':
            self.handle_profile_menu()
            return
        if service_key in ('15', '16'):
            self.handle_chat_menu()
            return
        while True:
            self.show_service_menu(service_key)
            choice = self.get_user_choice()
            if choice == '0':
                self.show_goodbye()
                sys.exit(0)
            elif choice == 'b':
                break
            else:
                self.handle_service_choice(service_key, choice)
    
    def show_goodbye(self):
        """Show goodbye message with dynamic box"""
        self.clear_screen()
        width = self.get_width()
        
        goodbye_content = [
            "👋 Thank you for using GSuite CLI!",
            "",
            "🚀 Your AI-Powered Productivity Assistant",
            "",
            "📊 Productivity Score: 85/100",
            "⚡ Cache Hit Rate: 92%",
            "🤖 AI Commands Used: 47",
            "",
            "💚 Stay productive!"
        ]
        
        print()
        self.draw_box(goodbye_content, color=Fore.GREEN, padding=5)
        print()


def start_interactive_mode():
    """Start the interactive CLI mode"""
    menu = InteractiveMenu()
    menu.run()


if __name__ == "__main__":
    start_interactive_mode()
