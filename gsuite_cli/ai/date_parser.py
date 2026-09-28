"""
Date and time understanding utilities for natural language query parsing.
Resolves natural expressions to deterministic date/time bounds in the user's timezone.
"""

from __future__ import annotations
import re
from datetime import datetime, timedelta, time
from typing import Optional, Tuple, Dict, Any, Union
from dateutil import tz, parser as dt_parser


def get_user_timezone(config_manager: Optional[Any] = None) -> tz.tzfile:
    """Get the user's configured timezone, falling back to local or UTC."""
    tz_str = None
    if config_manager:
        try:
            tz_str = config_manager.get('calendar.default_timezone')
        except Exception:
            pass
    if not tz_str:
        try:
            from ..config import hermes_config
            tz_str = hermes_config.get('calendar.default_timezone')
        except Exception:
            pass

    if tz_str:
        user_tz = tz.gettz(tz_str)
        if user_tz:
            return user_tz

    return tz.tzlocal() or tz.UTC


class NaturalDateParser:
    """Parses natural language date and time expressions into deterministic bounds."""

    WEEKDAY_MAP = {
        'monday': 0, 'mon': 0,
        'tuesday': 1, 'tue': 1,
        'wednesday': 2, 'wed': 2,
        'thursday': 3, 'thu': 3,
        'friday': 4, 'fri': 4,
        'saturday': 5, 'sat': 5,
        'sunday': 6, 'sun': 6,
    }

    def __init__(self, timezone: Optional[Any] = None):
        self.tzinfo = timezone or tz.tzlocal() or tz.UTC

    def now(self) -> datetime:
        """Return current datetime in the configured timezone."""
        return datetime.now(self.tzinfo)

    def parse_range(self, text: str) -> Optional[Tuple[datetime, datetime]]:
        """
        Parse natural language text into a (start_dt, end_dt) tuple.
        Returns None if no matching date expression is found.
        """
        return self._parse_range_impl(text)

    def parse_date_range(self, text: str) -> Optional[Tuple[datetime, datetime]]:
        """Alias for parse_range."""
        return self.parse_range(text)

    def _parse_range_impl(self, text: str) -> Optional[Tuple[datetime, datetime]]:
        if not text:
            return None
        text_lower = text.strip().lower().replace('_', ' ')
        now = self.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

        # 1. "today"
        if re.search(r'\btoday\b', text_lower):
            # check if morning/afternoon/evening
            if 'morning' in text_lower:
                return (today_start.replace(hour=8), today_start.replace(hour=12))
            if 'afternoon' in text_lower:
                return (today_start.replace(hour=12), today_start.replace(hour=17))
            if 'evening' in text_lower:
                return (today_start.replace(hour=17), today_start.replace(hour=21))
            return (today_start, today_end)

        # 2. "tomorrow"
        if re.search(r'\btomorrow\b', text_lower):
            tomorrow_start = today_start + timedelta(days=1)
            tomorrow_end = today_end + timedelta(days=1)
            if 'morning' in text_lower:
                return (tomorrow_start.replace(hour=8), tomorrow_start.replace(hour=12))
            if 'afternoon' in text_lower:
                return (tomorrow_start.replace(hour=12), tomorrow_start.replace(hour=17))
            if 'evening' in text_lower:
                return (tomorrow_start.replace(hour=17), tomorrow_start.replace(hour=21))
            m_time = re.search(r'at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', text_lower)
            if m_time:
                hour = int(m_time.group(1))
                minute = int(m_time.group(2) or 0)
                meridiem = m_time.group(3)
                if meridiem == 'pm' and hour < 12:
                    hour += 12
                elif meridiem == 'am' and hour == 12:
                    hour = 0
                target_dt = tomorrow_start.replace(hour=hour, minute=minute)
                return (target_dt, target_dt + timedelta(hours=1))
            return (tomorrow_start, tomorrow_end)

        # 3. "yesterday"
        if re.search(r'\byesterday\b', text_lower):
            yesterday_start = today_start - timedelta(days=1)
            yesterday_end = today_end - timedelta(days=1)
            return (yesterday_start, yesterday_end)

        # 4. "this week"
        if re.search(r'\bthis week\b', text_lower):
            # Monday of this week to Sunday end
            week_start = today_start - timedelta(days=now.weekday())
            week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59, microseconds=999999)
            return (week_start, week_end)

        # 5. "next week"
        if re.search(r'\bnext week\b', text_lower):
            week_start = today_start - timedelta(days=now.weekday()) + timedelta(days=7)
            week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59, microseconds=999999)
            return (week_start, week_end)

        # 6. "last week"
        if re.search(r'\blast week\b', text_lower):
            week_start = today_start - timedelta(days=now.weekday()) - timedelta(days=7)
            week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59, microseconds=999999)
            return (week_start, week_end)

        # 7. "last 7 days" / "past 7 days"
        if re.search(r'\b(?:last|past)\s+7\s+days\b', text_lower):
            start = now - timedelta(days=7)
            return (start, now)

        # 8. "last 30 days" / "past 30 days"
        if re.search(r'\b(?:last|past)\s+30\s+days\b', text_lower):
            start = now - timedelta(days=30)
            return (start, now)

        # 9. "this month"
        if re.search(r'\bthis month\b', text_lower):
            month_start = today_start.replace(day=1)
            # Find next month start then subtract 1 second
            if month_start.month == 12:
                next_month = month_start.replace(year=month_start.year + 1, month=1)
            else:
                next_month = month_start.replace(month=month_start.month + 1)
            month_end = next_month - timedelta(microseconds=1)
            return (month_start, month_end)

        # 10. "next month"
        if re.search(r'\bnext month\b', text_lower):
            if today_start.month == 12:
                next_start = today_start.replace(year=today_start.year + 1, month=1, day=1)
            else:
                next_start = today_start.replace(month=today_start.month + 1, day=1)
            if next_start.month == 12:
                after_next = next_start.replace(year=next_start.year + 1, month=1)
            else:
                after_next = next_start.replace(month=next_start.month + 1)
            next_end = after_next - timedelta(microseconds=1)
            return (next_start, next_end)

        # 11. "last month"
        if re.search(r'\blast month\b', text_lower):
            if today_start.month == 1:
                last_start = today_start.replace(year=today_start.year - 1, month=12, day=1)
            else:
                last_start = today_start.replace(month=today_start.month - 1, day=1)
            curr_month_start = today_start.replace(day=1)
            last_end = curr_month_start - timedelta(microseconds=1)
            return (last_start, last_end)

        # 12. Specific weekday (e.g., "Friday", "next Monday at 10 AM", "on Tuesday")
        weekday_pattern = r'\b(?:(next|this|on)\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\b'
        m_day = re.search(weekday_pattern, text_lower)
        if m_day:
            prefix = m_day.group(1) or 'this'
            day_name = m_day.group(2)
            target_weekday = self.WEEKDAY_MAP[day_name]
            current_weekday = now.weekday()

            days_ahead = (target_weekday - current_weekday) % 7
            if prefix == 'next' or days_ahead == 0:
                days_ahead = days_ahead + 7 if days_ahead <= 0 else days_ahead
                if prefix == 'next' and days_ahead < 7:
                    days_ahead += 7

            target_date_start = today_start + timedelta(days=days_ahead)
            target_date_end = today_end + timedelta(days=days_ahead)

            # Check if specific time specified, e.g. "at 10 am"
            m_time = re.search(r'at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', text_lower)
            if m_time:
                hour = int(m_time.group(1))
                minute = int(m_time.group(2) or 0)
                meridiem = m_time.group(3)
                if meridiem == 'pm' and hour < 12:
                    hour += 12
                elif meridiem == 'am' and hour == 12:
                    hour = 0
                exact_start = target_date_start.replace(hour=hour, minute=minute)
                return (exact_start, exact_start + timedelta(hours=1))

            return (target_date_start, target_date_end)

        # 13. Try general date parsing via dateutil
        try:
            parsed = dt_parser.parse(text, fuzzy=True, default=today_start)
            if parsed:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=self.tzinfo)
                return (parsed, parsed + timedelta(hours=1))
        except Exception:
            pass

        return None

    def to_iso_bounds(self, time_range_str: str) -> Dict[str, str]:
        """Convert natural range string to ISO/RFC3339 time_min and time_max strings."""
        bounds = self.parse_range(time_range_str)
        if not bounds:
            return {}
        start_dt, end_dt = bounds
        return {
            'time_min': start_dt.isoformat(),
            'time_max': end_dt.isoformat(),
            'start_dt': start_dt,
            'end_dt': end_dt,
        }
