"""
Google Calendar service integration
"""

import logging
import re
import uuid
from typing import List, Dict, Any, Optional, Union
from datetime import datetime, timedelta, date

from dateutil import parser as date_parser
from dateutil import tz
from googleapiclient.errors import HttpError

from ..auth.oauth import OAuthManager
from ..utils.formatters import print_error, print_info
from ..utils.cache import ServiceCache, cached

logger = logging.getLogger(__name__)


class CalendarService:
    """Google Calendar API service wrapper"""
    
    def __init__(self, oauth_manager: OAuthManager, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.service = None
        self.cache = ServiceCache('calendar', cache_manager) if cache_manager else None
        self._initialize_service()
    
    def _initialize_service(self) -> bool:
        """Initialize the Calendar service"""
        try:
            self.service = self.oauth_manager.build_service('calendar', 'v3')
            return self.service is not None
        except Exception as e:
            logger.error(f"Failed to initialize Calendar service: {e}")
            return False

    def test_connection(self) -> Dict[str, Any]:
        """Test Calendar API connection and return status"""
        if not self.service:
            return {'connected': False, 'error': 'Service not initialized'}
        try:
            res = self.service.calendarList().list(maxResults=1).execute()
            return {'connected': True, 'count': len(res.get('items', []))}
        except Exception as e:
            return {'connected': False, 'error': str(e)}

    def _get_tz(self, timezone_str: Optional[str] = None):
        """Get tzinfo object safely"""
        if timezone_str:
            tzinfo = tz.gettz(timezone_str)
            if tzinfo:
                return tzinfo
        return tz.tzlocal() or tz.UTC

    def _extract_meet_link(self, event: Dict[str, Any]) -> str:
        """Extract Google Meet link if present from event metadata"""
        if not event:
            return ''
        if event.get('hangoutLink'):
            return event['hangoutLink']
        conf = event.get('conferenceData', {})
        for ep in conf.get('entryPoints', []):
            uri = ep.get('uri', '')
            if 'meet.google.com' in uri or ep.get('entryPointType') == 'video':
                return uri
        loc = event.get('location', '')
        if 'meet.google.com/' in loc:
            for word in loc.split():
                if 'meet.google.com/' in word:
                    return word.strip('()<>[],."\'')
        desc = event.get('description', '')
        if 'meet.google.com/' in desc:
            for word in desc.split():
                if 'meet.google.com/' in word:
                    return word.strip('()<>[],."\'')
        return ''

    def _validate_email(self, email: str) -> bool:
        """Basic email format validation"""
        if not email or not isinstance(email, str):
            return False
        pattern = r'^[^@\s]+@[^@\s]+\.[^@\s]+$'
        return bool(re.match(pattern, email.strip()))

    def _format_datetime(self, dt_dict: Union[Dict[str, Any], str, None]) -> str:
        """Format datetime dictionary or string to string"""
        if not dt_dict:
            return ''
        if isinstance(dt_dict, str):
            return dt_dict
        if 'dateTime' in dt_dict:
            return dt_dict['dateTime']
        elif 'date' in dt_dict:
            return dt_dict['date']
        return ''

    @cached('calendar.list', ttl=300)
    def list_calendars(self, max_results: int = 100) -> List[Dict[str, Any]]:
        """List all calendars with full metadata and pagination"""
        if not self.service:
            return []
        
        # Try cache first
        if self.cache:
            cached_result = self.cache.get('list_calendars')
            if cached_result is not None:
                return cached_result
        
        try:
            calendars = []
            page_token = None
            
            while True:
                params = {'maxResults': min(max_results - len(calendars), 100)}
                if page_token:
                    params['pageToken'] = page_token
                
                result = self.service.calendarList().list(**params).execute()
                items = result.get('items', [])
                if not isinstance(items, list):
                    items = []
                
                for calendar in items:
                    calendars.append({
                        'id': calendar.get('id'),
                        'summary': calendar.get('summary', 'Untitled'),
                        'description': calendar.get('description', ''),
                        'timezone': calendar.get('timeZone', 'UTC'),
                        'location': calendar.get('location', ''),
                        'primary': calendar.get('primary', False),
                        'access_role': calendar.get('accessRole', 'reader'),
                    })
                    if len(calendars) >= max_results:
                        break
                
                page_token = result.get('nextPageToken')
                if not isinstance(page_token, str) or not page_token or len(calendars) >= max_results:
                    break
            
            # Cache the result
            if self.cache:
                self.cache.set('list_calendars', calendars)
            
            return calendars
        except HttpError as e:
            logger.error(f"Failed to list calendars: {e}")
            print_error(f"Failed to list calendars: {e}")
            return []

    def get_calendar(self, calendar_id: str = 'primary') -> Optional[Dict[str, Any]]:
        """Get details of a specific calendar"""
        if not self.service:
            return None
        try:
            cal = self.service.calendarList().get(calendarId=calendar_id).execute()
            return {
                'id': cal.get('id'),
                'summary': cal.get('summary', 'Untitled'),
                'description': cal.get('description', ''),
                'timezone': cal.get('timeZone', 'UTC'),
                'location': cal.get('location', ''),
                'access_role': cal.get('accessRole', 'reader'),
                'primary': cal.get('primary', False),
            }
        except HttpError:
            try:
                cal = self.service.calendars().get(calendarId=calendar_id).execute()
                return {
                    'id': cal.get('id'),
                    'summary': cal.get('summary', 'Untitled'),
                    'description': cal.get('description', ''),
                    'timezone': cal.get('timeZone', 'UTC'),
                    'location': cal.get('location', ''),
                    'access_role': 'owner',
                    'primary': cal.get('id') == 'primary' or calendar_id == 'primary',
                }
            except HttpError as e2:
                logger.error(f"Failed to get calendar {calendar_id}: {e2}")
                print_error(f"Failed to get calendar: {e2}")
                return None

    def create_calendar(self, summary: str, description: str = '', time_zone: str = 'UTC') -> Optional[Dict[str, Any]]:
        """Create a new secondary calendar"""
        if not self.service:
            return None
        try:
            calendar = {
                'summary': summary,
                'description': description,
                'timeZone': time_zone
            }
            created_calendar = self.service.calendars().insert(body=calendar).execute()
            if self.cache:
                self.cache.invalidate('list_calendars')
            logger.info(f"Created calendar: {created_calendar.get('id')}")
            return created_calendar
        except HttpError as e:
            logger.error(f"Failed to create calendar: {e}")
            print_error(f"Failed to create calendar: {e}")
            return None

    def update_calendar(self, 
                        calendar_id: str, 
                        summary: Optional[str] = None, 
                        description: Optional[str] = None, 
                        time_zone: Optional[str] = None,
                        location: Optional[str] = None) -> bool:
        """Update secondary calendar metadata"""
        if not self.service:
            return False
        try:
            body = {}
            if summary is not None:
                body['summary'] = summary
            if description is not None:
                body['description'] = description
            if time_zone is not None:
                body['timeZone'] = time_zone
            if location is not None:
                body['location'] = location
            self.service.calendars().patch(calendarId=calendar_id, body=body).execute()
            if self.cache:
                self.cache.invalidate('list_calendars')
            logger.info(f"Updated calendar: {calendar_id}")
            return True
        except HttpError as e:
            logger.error(f"Failed to update calendar {calendar_id}: {e}")
            print_error(f"Failed to update calendar: {e}")
            return False

    def delete_calendar(self, calendar_id: str) -> bool:
        """Delete a calendar"""
        if not self.service:
            return False
        try:
            calendars = self.list_calendars()
            calendar = None
            for cal in calendars:
                if cal.get('id') == calendar_id:
                    calendar = cal
                    break
            if not calendar:
                # Try getting directly
                calendar = self.get_calendar(calendar_id)
            if not calendar:
                print_error("Calendar not found")
                return False
            if calendar.get('primary') or calendar_id == 'primary':
                print_error("Cannot delete primary calendar")
                return False
            
            access_role = calendar.get('access_role')
            if access_role == 'owner':
                self.service.calendars().delete(calendarId=calendar_id).execute()
            else:
                self.service.calendarList().delete(calendarId=calendar_id).execute()
            
            if self.cache:
                self.cache.invalidate('list_calendars')
            logger.info(f"Deleted calendar: {calendar_id}")
            return True
        except HttpError as e:
            logger.error(f"Failed to delete calendar {calendar_id}: {e}")
            print_error(f"Failed to delete calendar: {e}")
            return False

    def list_events(self, 
                    calendar_id: str = 'primary',
                    time_min: Optional[datetime] = None,
                    time_max: Optional[datetime] = None,
                    max_results: int = 50,
                    query: Optional[str] = None,
                    page_token: Optional[str] = None) -> List[Dict[str, Any]]:
        """List events from a calendar with pagination and rich details"""
        if not self.service:
            return []
        
        cache_args = (calendar_id, time_min, time_max, max_results, query, page_token)
        if self.cache:
            cached_result = self.cache.get('list_events', *cache_args)
            if cached_result is not None:
                return cached_result
        
        try:
            params = {
                'calendarId': calendar_id,
                'maxResults': min(max_results, 250),
                'singleEvents': True,
                'orderBy': 'startTime'
            }
            
            if time_min:
                params['timeMin'] = time_min.isoformat() if time_min.tzinfo else time_min.isoformat() + 'Z'
            if time_max:
                params['timeMax'] = time_max.isoformat() if time_max.tzinfo else time_max.isoformat() + 'Z'
            if query:
                params['q'] = query
            if page_token:
                params['pageToken'] = page_token
            
            result = self.service.events().list(**params).execute()
            events = result.get('items', [])
            
            formatted_events = []
            for event in events:
                start_dict = event.get('start', {})
                end_dict = event.get('end', {})
                is_all_day = 'date' in start_dict and 'dateTime' not in start_dict
                meet_link = self._extract_meet_link(event)
                
                attendees_raw = event.get('attendees', [])
                attendees_list = []
                for att in attendees_raw:
                    attendees_list.append({
                        'email': att.get('email', ''),
                        'displayName': att.get('displayName', att.get('email', '')),
                        'responseStatus': att.get('responseStatus', 'needsAction'),
                        'organizer': att.get('organizer', False),
                    })
                
                formatted_event = {
                    'id': event.get('id'),
                    'summary': event.get('summary', 'No title'),
                    'description': event.get('description', ''),
                    'location': event.get('location', ''),
                    'start': self._format_datetime(start_dict),
                    'end': self._format_datetime(end_dict),
                    'all_day': is_all_day,
                    'status': event.get('status'),
                    'created': self._format_datetime(event.get('created')),
                    'updated': self._format_datetime(event.get('updated')),
                    'meet_link': meet_link,
                    'attendees': attendees_list,
                    'organizer': event.get('organizer', {}),
                    'recurrence': event.get('recurrence', []),
                    'reminders': event.get('reminders', {}),
                    'html_link': event.get('htmlLink', ''),
                    'calendar_id': calendar_id,
                }
                formatted_events.append(formatted_event)
            
            if self.cache:
                self.cache.set('list_events', formatted_events, 180, *cache_args)
            
            return formatted_events
        except HttpError as e:
            logger.error(f"Failed to list events: {e}")
            print_error(f"Failed to list events: {e}")
            return []

    def get_today_events(self, calendar_id: str = 'primary', timezone_str: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get events for today strictly within 00:00:00 to 23:59:59"""
        tzone = self._get_tz(timezone_str)
        now = datetime.now(tzone)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        return self.list_events(calendar_id=calendar_id, time_min=start_of_day, time_max=end_of_day)

    def get_tomorrow_events(self, calendar_id: str = 'primary', timezone_str: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get events for tomorrow strictly within 00:00:00 to 23:59:59"""
        tzone = self._get_tz(timezone_str)
        tomorrow = datetime.now(tzone) + timedelta(days=1)
        start_of_day = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = tomorrow.replace(hour=23, minute=59, second=59, microsecond=999999)
        return self.list_events(calendar_id=calendar_id, time_min=start_of_day, time_max=end_of_day)

    def get_upcoming_events(self, calendar_id: str = 'primary', limit: int = 10, time_min: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Get nearest upcoming events starting from now or time_min, ordered nearest first"""
        if time_min is None:
            time_min = datetime.now(tz.tzlocal() or tz.UTC)
        return self.list_events(calendar_id=calendar_id, time_min=time_min, max_results=limit)

    def get_events_by_date(self, target_date: Union[str, date, datetime], calendar_id: str = 'primary', timezone_str: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get events for a specific target date"""
        tzone = self._get_tz(timezone_str)
        if isinstance(target_date, str):
            dt = date_parser.parse(target_date)
        elif isinstance(target_date, datetime):
            dt = target_date
        else:
            dt = datetime.combine(target_date, datetime.min.time())
        
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tzone)
        else:
            dt = dt.astimezone(tzone)
        
        start_of_day = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        return self.list_events(calendar_id=calendar_id, time_min=start_of_day, time_max=end_of_day)

    def get_events_by_date_range(self, 
                                start_date: Union[str, date, datetime], 
                                end_date: Union[str, date, datetime], 
                                calendar_id: str = 'primary', 
                                timezone_str: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get events across a date range"""
        tzone = self._get_tz(timezone_str)
        if isinstance(start_date, str):
            s_dt = date_parser.parse(start_date)
        elif isinstance(start_date, datetime):
            s_dt = start_date
        else:
            s_dt = datetime.combine(start_date, datetime.min.time())
        if s_dt.tzinfo is None:
            s_dt = s_dt.replace(tzinfo=tzone)
        else:
            s_dt = s_dt.astimezone(tzone)

        if isinstance(end_date, str):
            e_dt = date_parser.parse(end_date)
        elif isinstance(end_date, datetime):
            e_dt = end_date
        else:
            e_dt = datetime.combine(end_date, datetime.max.time())
        if e_dt.tzinfo is None:
            e_dt = e_dt.replace(tzinfo=tzone)
        else:
            e_dt = e_dt.astimezone(tzone)

        start_of_range = s_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_range = e_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        return self.list_events(calendar_id=calendar_id, time_min=start_of_range, time_max=end_of_range)

    def get_event(self, event_id: str, calendar_id: str = 'primary') -> Optional[Dict[str, Any]]:
        """Get full details of a specific event"""
        if not self.service:
            return None
        
        cache_args = (calendar_id, event_id)
        if self.cache:
            cached_result = self.cache.get('get_event', *cache_args)
            if cached_result is not None:
                return cached_result
        
        try:
            result = self.service.events().get(
                calendarId=calendar_id,
                eventId=event_id
            ).execute()
            
            start_dict = result.get('start', {})
            end_dict = result.get('end', {})
            is_all_day = 'date' in start_dict and 'dateTime' not in start_dict
            meet_link = self._extract_meet_link(result)
            
            attendees_raw = result.get('attendees', [])
            attendees_list = []
            for att in attendees_raw:
                attendees_list.append({
                    'email': att.get('email', ''),
                    'displayName': att.get('displayName', att.get('email', '')),
                    'responseStatus': att.get('responseStatus', 'needsAction'),
                    'organizer': att.get('organizer', False),
                    'optional': att.get('optional', False),
                })
            
            formatted_event = {
                'id': result.get('id'),
                'summary': result.get('summary', 'No title'),
                'description': result.get('description', ''),
                'location': result.get('location', ''),
                'start': self._format_datetime(start_dict),
                'end': self._format_datetime(end_dict),
                'start_raw': start_dict,
                'end_raw': end_dict,
                'all_day': is_all_day,
                'time_zone': start_dict.get('timeZone') or end_dict.get('timeZone') or 'UTC',
                'status': result.get('status', 'confirmed'),
                'created': self._format_datetime(result.get('created')),
                'updated': self._format_datetime(result.get('updated')),
                'meet_link': meet_link,
                'attendees': attendees_list,
                'organizer': result.get('organizer', {}),
                'creator': result.get('creator', {}),
                'recurrence': result.get('recurrence', []),
                'reminders': result.get('reminders', {}),
                'html_link': result.get('htmlLink', ''),
                'calendar_id': calendar_id,
            }
            
            if self.cache:
                self.cache.set('get_event', formatted_event, *cache_args)
            
            return formatted_event
        except HttpError as e:
            logger.error(f"Failed to get event {event_id}: {e}")
            print_error(f"Failed to get event: {e}")
            return None

    def create_event(self, 
                    calendar_id: str = 'primary',
                    summary: str = '',
                    start_time: Optional[datetime] = None,
                    end_time: Optional[datetime] = None,
                    description: str = '',
                    location: str = '',
                    attendees: Optional[List[Union[str, Dict[str, str]]]] = None,
                    time_zone: str = 'UTC',
                    recurrence: Optional[List[str]] = None,
                    reminders_minutes: Optional[List[int]] = None,
                    reminders_custom: Optional[List[Dict[str, Any]]] = None,
                    meet_link: Optional[str] = None,
                    create_meet: bool = False) -> Optional[str]:
        """Create a new event with full option support"""
        if not self.service:
            return None
        
        try:
            event_body: Dict[str, Any] = {
                'summary': summary or 'Untitled Event',
                'description': description or '',
                'location': location or '',
            }
            
            if meet_link:
                if not event_body['location']:
                    event_body['location'] = meet_link
                if meet_link not in event_body['description']:
                    if event_body['description']:
                        event_body['description'] += f"\n\nGoogle Meet: {meet_link}"
                    else:
                        event_body['description'] = f"Google Meet: {meet_link}"
            
            if start_time:
                event_body['start'] = {
                    'dateTime': start_time.isoformat() if start_time.tzinfo else start_time.isoformat(),
                    'timeZone': time_zone
                }
            if end_time:
                event_body['end'] = {
                    'dateTime': end_time.isoformat() if end_time.tzinfo else end_time.isoformat(),
                    'timeZone': time_zone
                }

            if attendees:
                validated_attendees = []
                for att in attendees:
                    if isinstance(att, str):
                        email = att.strip()
                        if self._validate_email(email):
                            validated_attendees.append({'email': email})
                    elif isinstance(att, dict) and 'email' in att:
                        email = att['email'].strip()
                        if self._validate_email(email):
                            validated_attendees.append(att)
                if validated_attendees:
                    event_body['attendees'] = validated_attendees

            if recurrence:
                event_body['recurrence'] = recurrence

            # Reminder handling
            if reminders_custom:
                event_body['reminders'] = {
                    'useDefault': False,
                    'overrides': reminders_custom
                }
            elif reminders_minutes is not None:
                overrides = []
                seen = set()
                for minutes in sorted(reminders_minutes):
                    value = int(minutes)
                    if value < 0 or value in seen:
                        continue
                    seen.add(value)
                    overrides.append({
                        'method': 'popup',
                        'minutes': value,
                    })
                if overrides:
                    event_body['reminders'] = {
                        'useDefault': False,
                        'overrides': overrides,
                    }

            insert_kwargs: Dict[str, Any] = {
                'calendarId': calendar_id,
                'body': event_body
            }

            if create_meet:
                event_body['conferenceData'] = {
                    'createRequest': {
                        'requestId': str(uuid.uuid4()),
                        'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                    }
                }
                insert_kwargs['conferenceDataVersion'] = 1

            result = self.service.events().insert(**insert_kwargs).execute()
            event_id = result.get('id')
            
            if self.cache:
                self.cache.invalidate('list_events')
            
            logger.info(f"Created event: {event_id}")
            return event_id
        except HttpError as e:
            logger.error(f"Failed to create event: {e}")
            print_error(f"Failed to create event: {e}")
            return None

    def update_event(self, 
                    event_id: str,
                    calendar_id: str = 'primary',
                    summary: Optional[str] = None,
                    start_time: Optional[datetime] = None,
                    end_time: Optional[datetime] = None,
                    description: Optional[str] = None,
                    location: Optional[str] = None,
                    time_zone: Optional[str] = None,
                    recurrence: Optional[List[str]] = None,
                    attendees: Optional[List[Union[str, Dict[str, str]]]] = None,
                    reminders_minutes: Optional[List[int]] = None,
                    reminders_custom: Optional[List[Dict[str, Any]]] = None,
                    meet_link: Optional[str] = None) -> bool:
        """Update an existing event with partial updates"""
        if not self.service:
            return False
        
        try:
            event = self.service.events().get(
                calendarId=calendar_id,
                eventId=event_id
            ).execute()
            
            # Update fields selectively
            if summary is not None:
                event['summary'] = summary
            if description is not None:
                event['description'] = description
            if location is not None:
                event['location'] = location
            if meet_link:
                if not event.get('location'):
                    event['location'] = meet_link
                desc = event.get('description', '')
                if meet_link not in desc:
                    event['description'] = (desc + f"\n\nGoogle Meet: {meet_link}").strip()
            
            tz_val = time_zone
            if not tz_val:
                if isinstance(event.get('start'), dict):
                    tz_val = event['start'].get('timeZone', 'UTC')
                else:
                    tz_val = 'UTC'
            
            if start_time:
                event['start'] = {
                    'dateTime': start_time.isoformat() if start_time.tzinfo else start_time.isoformat(),
                    'timeZone': tz_val
                }
            if end_time:
                event['end'] = {
                    'dateTime': end_time.isoformat() if end_time.tzinfo else end_time.isoformat(),
                    'timeZone': tz_val
                }
            if recurrence is not None:
                if recurrence:
                    event['recurrence'] = recurrence
                else:
                    event.pop('recurrence', None)
            
            if attendees is not None:
                validated_attendees = []
                for att in attendees:
                    if isinstance(att, str):
                        email = att.strip()
                        if self._validate_email(email):
                            validated_attendees.append({'email': email})
                    elif isinstance(att, dict) and 'email' in att:
                        email = att['email'].strip()
                        if self._validate_email(email):
                            validated_attendees.append(att)
                event['attendees'] = validated_attendees

            if reminders_custom is not None:
                event['reminders'] = {
                    'useDefault': False,
                    'overrides': reminders_custom
                }
            elif reminders_minutes is not None:
                overrides = []
                seen = set()
                for minutes in sorted(reminders_minutes):
                    value = int(minutes)
                    if value < 0 or value in seen:
                        continue
                    seen.add(value)
                    overrides.append({
                        'method': 'popup',
                        'minutes': value,
                    })
                event['reminders'] = {
                    'useDefault': False,
                    'overrides': overrides,
                }
            
            self.service.events().update(
                calendarId=calendar_id,
                eventId=event_id,
                body=event
            ).execute()
            
            if self.cache:
                self.cache.invalidate('list_events')
                self.cache.invalidate('get_event', calendar_id, event_id)
            
            logger.info(f"Updated event: {event_id}")
            return True
        except HttpError as e:
            logger.error(f"Failed to update event {event_id}: {e}")
            print_error(f"Failed to update event: {e}")
            return False

    def delete_event(self, event_id: str, calendar_id: str = 'primary') -> bool:
        """Delete an event"""
        if not self.service:
            return False
        
        try:
            self.service.events().delete(
                calendarId=calendar_id,
                eventId=event_id
            ).execute()
            
            if self.cache:
                self.cache.invalidate('list_events')
                self.cache.invalidate('get_event', calendar_id, event_id)
            
            logger.info(f"Deleted event: {event_id}")
            return True
        except HttpError as e:
            logger.error(f"Failed to delete event {event_id}: {e}")
            print_error(f"Failed to delete event: {e}")
            return False

    def move_event(self, event_id: str, source_calendar_id: str, destination_calendar_id: str) -> bool:
        """Move an event to another calendar"""
        if not self.service:
            return False
        
        try:
            self.service.events().move(
                calendarId=source_calendar_id,
                eventId=event_id,
                destination=destination_calendar_id
            ).execute()
            
            if self.cache:
                self.cache.invalidate('list_events')
                self.cache.invalidate('get_event', source_calendar_id, event_id)
                self.cache.invalidate('get_event', destination_calendar_id, event_id)
            
            logger.info(f"Moved event {event_id} from {source_calendar_id} to {destination_calendar_id}")
            return True
        except HttpError as e:
            logger.error(f"Failed to move event {event_id}: {e}")
            print_error(f"Failed to move event: {e}")
            return False

    def search_events(self, 
                     query: str,
                     calendar_id: str = 'primary',
                     time_min: Optional[datetime] = None,
                     time_max: Optional[datetime] = None,
                     max_results: int = 50) -> List[Dict[str, Any]]:
        """Search events by query string"""
        return self.list_events(
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            max_results=max_results,
            query=query
        )

    def list_event_instances(self,
                             event_id: str,
                             calendar_id: str = 'primary',
                             time_min: Optional[datetime] = None,
                             time_max: Optional[datetime] = None,
                             max_results: int = 250) -> List[Dict[str, Any]]:
        """List instances of a recurring event"""
        if not self.service:
            return []
        try:
            params = {
                'calendarId': calendar_id,
                'eventId': event_id,
                'maxResults': max_results,
                'singleEvents': True,
                'orderBy': 'startTime'
            }
            if time_min:
                params['timeMin'] = time_min.isoformat() + 'Z'
            if time_max:
                params['timeMax'] = time_max.isoformat() + 'Z'
            result = self.service.events().instances(**params).execute()
            items = result.get('items', [])
            instances = []
            for item in items:
                instances.append({
                    'id': item.get('id'),
                    'summary': item.get('summary', 'No title'),
                    'start': self._format_datetime(item.get('start', {})),
                    'end': self._format_datetime(item.get('end', {})),
                    'status': item.get('status'),
                    'recurring_event_id': item.get('recurringEventId'),
                    'meet_link': self._extract_meet_link(item),
                })
            return instances
        except HttpError as e:
            logger.error(f"Failed to list instances for event {event_id}: {e}")
            print_error(f"Failed to list event instances: {e}")
            return []

    def get_free_busy(self, 
                     time_min: datetime,
                     time_max: datetime,
                     calendar_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Get free/busy information for calendars"""
        if not self.service:
            return {}
        
        if calendar_ids is None:
            calendar_ids = ['primary']
        
        try:
            body = {
                'timeMin': time_min.isoformat() if time_min.tzinfo else time_min.isoformat() + 'Z',
                'timeMax': time_max.isoformat() if time_max.tzinfo else time_max.isoformat() + 'Z',
                'items': [{'id': cal_id} for cal_id in calendar_ids]
            }
            
            result = self.service.freebusy().query(body=body).execute()
            return result
        except HttpError as e:
            logger.error(f"Failed to get free/busy: {e}")
            print_error(f"Failed to get free/busy: {e}")
            return {}
