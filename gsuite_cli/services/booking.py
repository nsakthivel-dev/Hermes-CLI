import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dateutil import parser as date_parser
from dateutil import tz

from ..config.manager import ConfigManager
from ..utils.formatters import print_error, print_info, print_success
from .calendar import CalendarService
from .reminders import ReminderService


@dataclass
class BookingLink:
    token: str
    duration_minutes: int
    availability: Dict[str, Any]
    buffer_minutes: int
    expires_at: Optional[str]
    max_per_day: Optional[int]
    time_zone: str
    calendar_id: str
    revoked: bool


import logging

logger = logging.getLogger(__name__)


class BookingService:
    def __init__(self, config_manager: ConfigManager, calendar_service: CalendarService, meet_service: Optional[Any] = None):
        self.config_manager = config_manager
        self.calendar_service = calendar_service
        if meet_service is not None:
            self.meet_service = meet_service
        else:
            try:
                from .meet import MeetService
                self.meet_service = MeetService(calendar_service.oauth_manager)
            except Exception:
                self.meet_service = None
        data_dir: Path = config_manager.data_dir
        self.db_path = data_dir / "bookings.db"
        self._ensure_schema()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self):
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS booking_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token TEXT NOT NULL UNIQUE,
                    duration_minutes INTEGER NOT NULL,
                    availability TEXT NOT NULL,
                    buffer_minutes INTEGER NOT NULL,
                    expires_at TEXT,
                    max_per_day INTEGER,
                    time_zone TEXT NOT NULL,
                    calendar_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    rate_window_start TEXT,
                    rate_window_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS booking_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    booking_token TEXT NOT NULL,
                    calendar_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    start TEXT NOT NULL,
                    end TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_booking_events_unique
                ON booking_events(calendar_id, start)
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _parse_availability(self, availability: str) -> Dict[str, Any]:
        text = availability.strip().lower()
        parts = text.split()
        if len(parts) != 2:
            raise ValueError("Availability must be in format 'days HH:MM-HH:MM', e.g. 'mon-fri 09:00-17:00'")
        days_part, time_part = parts
        if '-' in days_part and ',' not in days_part:
            start_day, end_day = days_part.split('-', 1)
            ordered = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
            if start_day not in ordered or end_day not in ordered:
                raise ValueError("Invalid days in availability")
            start_index = ordered.index(start_day)
            end_index = ordered.index(end_day)
            if start_index > end_index:
                raise ValueError("Day range in availability must be increasing, e.g. mon-fri")
            days = ordered[start_index:end_index + 1]
        else:
            days = [d.strip() for d in days_part.split(',') if d.strip()]
        weekday_map = {
            'mon': 0,
            'tue': 1,
            'wed': 2,
            'thu': 3,
            'fri': 4,
            'sat': 5,
            'sun': 6,
        }
        allowed_weekdays = []
        for d in days:
            if d not in weekday_map:
                raise ValueError(f"Invalid day in availability: {d}")
            if weekday_map[d] not in allowed_weekdays:
                allowed_weekdays.append(weekday_map[d])
        if '-' not in time_part:
            raise ValueError("Time range in availability must be HH:MM-HH:MM")
        start_str, end_str = time_part.split('-', 1)
        datetime.strptime(start_str, "%H:%M")
        datetime.strptime(end_str, "%H:%M")
        return {
            "weekdays": allowed_weekdays,
            "start_time": start_str,
            "end_time": end_str,
        }

    def create_link(
        self,
        duration_minutes: int,
        availability: str,
        buffer_minutes: int,
        expires_at: Optional[str],
        max_per_day: Optional[int],
        time_zone: str,
        calendar_id: str,
    ) -> BookingLink:
        if duration_minutes <= 0:
            raise ValueError("Duration must be positive")
        if buffer_minutes < 0:
            raise ValueError("Buffer must not be negative")
        if max_per_day is not None and max_per_day <= 0:
            raise ValueError("Max bookings per day must be positive")
        availability_obj = self._parse_availability(availability)
        expires_value = None
        if expires_at:
            try:
                expires_dt = datetime.strptime(expires_at, "%Y-%m-%d")
                expires_value = expires_dt.isoformat()
            except ValueError:
                raise ValueError("Expiration date must be in format YYYY-MM-DD")
        token = secrets.token_urlsafe(16)
        now = datetime.utcnow().isoformat()
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO booking_links (
                    token,
                    duration_minutes,
                    availability,
                    buffer_minutes,
                    expires_at,
                    max_per_day,
                    time_zone,
                    calendar_id,
                    created_at,
                    revoked,
                    rate_window_start,
                    rate_window_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, 0)
                """,
                (
                    token,
                    int(duration_minutes),
                    json.dumps(availability_obj),
                    int(buffer_minutes),
                    expires_value,
                    max_per_day,
                    time_zone,
                    calendar_id,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return BookingLink(
            token=token,
            duration_minutes=duration_minutes,
            availability=availability_obj,
            buffer_minutes=buffer_minutes,
            expires_at=expires_value,
            max_per_day=max_per_day,
            time_zone=time_zone,
            calendar_id=calendar_id,
            revoked=False,
        )

    def get_link(self, token: str) -> Optional[BookingLink]:
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT token, duration_minutes, availability, buffer_minutes,
                       expires_at, max_per_day, time_zone, calendar_id, revoked
                FROM booking_links
                WHERE token = ?
                """,
                (token,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return BookingLink(
                token=row[0],
                duration_minutes=row[1],
                availability=json.loads(row[2]),
                buffer_minutes=row[3],
                expires_at=row[4],
                max_per_day=row[5],
                time_zone=row[6],
                calendar_id=row[7],
                revoked=bool(row[8]),
            )
        finally:
            conn.close()

    def revoke_link(self, token: str) -> bool:
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE booking_links SET revoked = 1 WHERE token = ?", (token,)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def _check_rate_limit(self, token: str, max_requests: int = 30, window_seconds: int = 60) -> bool:
        now = datetime.utcnow()
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT rate_window_start, rate_window_count
                FROM booking_links
                WHERE token = ?
                """,
                (token,),
            )
            row = cur.fetchone()
            if not row:
                return False
            window_start_str, count = row
            if window_start_str:
                window_start = date_parser.parse(window_start_str)
                if (now - window_start).total_seconds() <= window_seconds:
                    if count >= max_requests:
                        return False
                    new_count = count + 1
                    cur.execute(
                        """
                        UPDATE booking_links
                        SET rate_window_count = ?
                        WHERE token = ?
                        """,
                        (new_count, token),
                    )
                    conn.commit()
                    return True
            cur.execute(
                """
                UPDATE booking_links
                SET rate_window_start = ?, rate_window_count = 1
                WHERE token = ?
                """,
                (now.isoformat(), token),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def _validate_slot(self, link: BookingLink, start_local: datetime) -> Tuple[bool, Optional[str]]:
        if link.expires_at:
            expires_dt = date_parser.parse(link.expires_at)
            if start_local > expires_dt:
                return False, "Booking link is expired for the requested time"
        availability = link.availability
        weekdays = availability.get("weekdays", [])
        start_time_str = availability.get("start_time")
        end_time_str = availability.get("end_time")
        if start_local.weekday() not in weekdays:
            return False, "Requested day is outside allowed availability"
        start_time = datetime.strptime(start_time_str, "%H:%M").time()
        end_time = datetime.strptime(end_time_str, "%H:%M").time()
        if not (start_time <= start_local.time() < end_time):
            return False, "Requested time is outside allowed availability window"
        return True, None

    def _check_daily_limit(self, link: BookingLink, day_start_utc: datetime, day_end_utc: datetime) -> bool:
        if link.max_per_day is None:
            return True
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT COUNT(*)
                FROM booking_events
                WHERE booking_token = ?
                  AND start >= ?
                  AND start < ?
                """,
                (link.token, day_start_utc.isoformat(), day_end_utc.isoformat()),
            )
            count_row = cur.fetchone()
            current = count_row[0] if count_row else 0
            return current < link.max_per_day
        finally:
            conn.close()

    def book(self, token: str, start_str: str) -> Optional[str]:
        link = self.get_link(token)
        if not link:
            print_error("Booking link not found")
            return None
        if link.revoked:
            print_error("Booking link has been revoked")
            return None
        if not self._check_rate_limit(token):
            print_error("Too many booking attempts. Please try again later.")
            return None
        tzinfo = tz.gettz(link.time_zone)
        if tzinfo is None:
            print_error(f"Unknown timezone: {link.time_zone}")
            return None
        try:
            requested = date_parser.parse(start_str)
        except Exception:
            print_error("Invalid start datetime format. Use a parsable datetime like '2026-03-25 14:00'")
            return None
        if requested.tzinfo is None:
            requested = requested.replace(tzinfo=tzinfo)
        else:
            requested = requested.astimezone(tzinfo)
        valid, reason = self._validate_slot(link, requested)
        if not valid:
            print_error(reason or "Requested time is not valid for this booking link")
            return None
        duration = timedelta(minutes=link.duration_minutes)
        start_local = requested
        end_local = requested + duration
        buffer_delta = timedelta(minutes=link.buffer_minutes)
        from dateutil import tz as tz_module

        start_utc = start_local.astimezone(tz_module.UTC)
        end_utc = end_local.astimezone(tz_module.UTC)
        fb_start = (start_utc - buffer_delta)
        fb_end = (end_utc + buffer_delta)
        if not self._check_daily_limit(link, fb_start.replace(hour=0, minute=0, second=0, microsecond=0), fb_start.replace(hour=23, minute=59, second=59, microsecond=0)):
            print_error("Maximum number of bookings for this day has been reached")
            return None
        busy = self.calendar_service.get_free_busy(
            time_min=fb_start,
            time_max=fb_end,
            calendar_ids=[link.calendar_id],
        )
        cal_busy = busy.get("calendars", {}).get(link.calendar_id, {})
        if cal_busy.get("busy"):
            print_error("Requested time conflicts with an existing event")
            return None
        conn = self._get_connection()
        event_id = None
        try:
            conn.isolation_level = None
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute(
                """
                SELECT 1 FROM booking_events
                WHERE calendar_id = ?
                  AND start = ?
                """,
                (link.calendar_id, start_utc.isoformat()),
            )
            if cur.fetchone():
                print_error("Requested time has just been booked by someone else")
                cur.execute("ROLLBACK")
                return None
            event_id = self.calendar_service.create_event(
                calendar_id=link.calendar_id,
                summary="Booked meeting",
                start_time=start_utc,
                end_time=end_utc,
                description=f"Booking from link {link.token}",
                location="",
                time_zone=link.time_zone,
            )
            if not event_id:
                cur.execute("ROLLBACK")
                print_error("Failed to create calendar event for booking")
                return None
            now = datetime.utcnow().isoformat()
            cur.execute(
                """
                INSERT INTO booking_events (
                    booking_token,
                    calendar_id,
                    event_id,
                    start,
                    end,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    link.token,
                    link.calendar_id,
                    event_id,
                    start_utc.isoformat(),
                    end_utc.isoformat(),
                    now,
                ),
            )
            cur.execute("COMMIT")
        except sqlite3.IntegrityError:
            print_error("Requested time has just been booked by someone else")
            try:
                cur.execute("ROLLBACK")
            except Exception:
                pass
            return None
        except Exception as e:
            try:
                cur.execute("ROLLBACK")
            except Exception:
                pass
            print_error(f"Failed to finalize booking: {e}")
            return None
        finally:
            conn.close()
        try:
            reminder_service = ReminderService(self.config_manager)
            reminder_service.schedule_reminders(
                event={
                    "id": event_id,
                    "start": start_utc.isoformat(),
                },
                calendar_id=link.calendar_id,
                offsets_minutes=[30],
                notify_cli=True,
                notify_desktop=False,
                notify_email=False,
            )
        except Exception:
            pass
        print_success("Booking confirmed")
        print_info(f"Event ID: {event_id}")
        return event_id

    def quick_meeting(self,
                      title: str,
                      start_time: datetime,
                      duration_minutes: int = 30,
                      attendees: Optional[List[str]] = None,
                      description: str = "",
                      location: str = "",
                      is_online: bool = False,
                      calendar_id: str = "primary",
                      time_zone: str = "UTC") -> Dict[str, Any]:
        """
        Quick meeting creation coordinating Calendar and Meet services.
        """
        end_time = start_time + timedelta(minutes=duration_minutes)
        meet_uri = ""
        meet_code = ""

        if is_online and self.meet_service:
            try:
                space = self.meet_service.create_space()
                if space:
                    meet_uri = space.get('meeting_uri', '')
                    meet_code = space.get('meeting_code', '')
            except Exception as e:
                logger.error(f"Failed to create Google Meet space: {e}")
                print_error(f"Failed to create Google Meet space: {e}")

        event_desc = description
        event_loc = location
        if meet_uri:
            if not event_loc:
                event_loc = meet_uri
            elif meet_uri not in event_loc:
                event_loc = f"{event_loc} ({meet_uri})"
            
            meet_info_text = f"Google Meet: {meet_uri}\nMeeting Code: {meet_code}".strip()
            if event_desc:
                event_desc = f"{event_desc}\n\n{meet_info_text}"
            else:
                event_desc = meet_info_text

        event_id = self.calendar_service.create_event(
            calendar_id=calendar_id,
            summary=title,
            start_time=start_time,
            end_time=end_time,
            description=event_desc,
            location=event_loc,
            attendees=attendees,
            time_zone=time_zone,
            meet_link=meet_uri if meet_uri else None,
            create_meet=(is_online and not meet_uri)
        )

        if not event_id:
            return {
                'success': False,
                'error': 'Failed to create calendar event',
            }

        return {
            'success': True,
            'event_id': event_id,
            'title': title,
            'start': start_time.isoformat(),
            'end': end_time.isoformat(),
            'duration_minutes': duration_minutes,
            'meet_uri': meet_uri,
            'meet_code': meet_code,
            'is_online': is_online,
            'attendees': attendees or [],
            'location': event_loc,
            'calendar_id': calendar_id,
        }

    def schedule_meeting(self,
                         title: str,
                         start_time: datetime,
                         end_time: Optional[datetime] = None,
                         duration_minutes: Optional[int] = None,
                         attendees: Optional[List[str]] = None,
                         description: str = "",
                         location: str = "",
                         is_online: bool = False,
                         calendar_id: str = "primary",
                         time_zone: str = "UTC") -> Dict[str, Any]:
        """
        Guided or parameterized meeting scheduler coordinating Calendar and Meet.
        """
        if end_time is None:
            dur = duration_minutes or 30
            end_time = start_time + timedelta(minutes=dur)
        else:
            dur = int((end_time - start_time).total_seconds() // 60)
        
        return self.quick_meeting(
            title=title,
            start_time=start_time,
            duration_minutes=dur,
            attendees=attendees,
            description=description,
            location=location,
            is_online=is_online,
            calendar_id=calendar_id,
            time_zone=time_zone
        )

    def find_available_time(self,
                            target_date: Any,
                            start_hour: int = 9,
                            end_hour: int = 17,
                            duration_minutes: int = 30,
                            calendar_ids: Optional[List[str]] = None,
                            time_zone: str = "UTC") -> List[Dict[str, Any]]:
        """
        Find available time slots on target_date between start_hour and end_hour
        using actual Google Calendar free/busy information.
        """
        tzinfo = tz.gettz(time_zone) or tz.tzlocal() or tz.UTC
        if isinstance(target_date, str):
            dt = date_parser.parse(target_date)
        elif isinstance(target_date, datetime):
            dt = target_date
        else:
            dt = datetime.combine(target_date, datetime.min.time())

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tzinfo)
        else:
            dt = dt.astimezone(tzinfo)

        window_start = dt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        window_end = dt.replace(hour=end_hour, minute=0, second=0, microsecond=0)

        cal_ids = calendar_ids or ["primary"]
        
        # Query freebusy
        start_utc = window_start.astimezone(tz.UTC)
        end_utc = window_end.astimezone(tz.UTC)

        freebusy = self.calendar_service.get_free_busy(
            time_min=start_utc,
            time_max=end_utc,
            calendar_ids=cal_ids
        )

        busy_intervals = []
        calendars = freebusy.get("calendars", {})
        for cal_id, cal_data in calendars.items():
            for b in cal_data.get("busy", []):
                try:
                    b_start = date_parser.parse(b["start"]).astimezone(tzinfo)
                    b_end = date_parser.parse(b["end"]).astimezone(tzinfo)
                    busy_intervals.append((b_start, b_end))
                except Exception:
                    continue

        busy_intervals.sort(key=lambda x: x[0])

        available_slots = []
        curr = window_start
        slot_delta = timedelta(minutes=duration_minutes)

        while curr + slot_delta <= window_end:
            slot_end = curr + slot_delta
            overlap = False
            for b_start, b_end in busy_intervals:
                if max(curr, b_start) < min(slot_end, b_end):
                    overlap = True
                    curr = b_end
                    break
            if not overlap:
                available_slots.append({
                    'start': curr.isoformat(),
                    'end': slot_end.isoformat(),
                    'start_formatted': curr.strftime('%I:%M %p'),
                    'end_formatted': slot_end.strftime('%I:%M %p'),
                    'display': f"{curr.strftime('%I:%M %p')} - {slot_end.strftime('%I:%M %p')}",
                    'date': curr.strftime('%Y-%m-%d'),
                    'time_zone': time_zone,
                })
                step = min(slot_delta, timedelta(minutes=30))
                curr += step

        return available_slots

    def reschedule_meeting(self,
                           event_id: str,
                           new_start: datetime,
                           new_end: Optional[datetime] = None,
                           duration_minutes: Optional[int] = None,
                           calendar_id: str = "primary",
                           time_zone: Optional[str] = None) -> Dict[str, Any]:
        """
        Reschedule an existing meeting, preserving Google Meet link and details.
        """
        event = self.calendar_service.get_event(event_id, calendar_id=calendar_id)
        if not event:
            return {'success': False, 'error': f'Event {event_id} not found'}
        
        if new_end is None:
            if duration_minutes:
                new_end = new_start + timedelta(minutes=duration_minutes)
            else:
                try:
                    old_start = date_parser.parse(event['start'])
                    old_end = date_parser.parse(event['end'])
                    dur = old_end - old_start
                    new_end = new_start + dur
                except Exception:
                    new_end = new_start + timedelta(minutes=30)
        
        tz_to_use = time_zone or event.get('time_zone', 'UTC')
        success = self.calendar_service.update_event(
            event_id=event_id,
            calendar_id=calendar_id,
            start_time=new_start,
            end_time=new_end,
            time_zone=tz_to_use
        )
        
        if not success:
            return {'success': False, 'error': 'Failed to update event timing'}
        
        return {
            'success': True,
            'event_id': event_id,
            'title': event.get('summary', ''),
            'start': new_start.isoformat(),
            'end': new_end.isoformat(),
            'meet_link': event.get('meet_link', ''),
            'calendar_id': calendar_id,
        }

    def cancel_meeting(self, event_id: str, calendar_id: str = "primary") -> bool:
        """
        Cancel a meeting by deleting the calendar event and cleaning up any local records.
        """
        success = self.calendar_service.delete_event(event_id=event_id, calendar_id=calendar_id)
        if success:
            try:
                conn = self._get_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM booking_events WHERE event_id = ? AND calendar_id = ?", (event_id, calendar_id))
                    conn.commit()
                finally:
                    conn.close()
            except Exception:
                pass
        return success


