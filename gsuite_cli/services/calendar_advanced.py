"""
Advanced Google Calendar service with AI-powered scheduling and insights
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import json

from googleapiclient.errors import HttpError

from ..auth.oauth import OAuthManager
from ..utils.formatters import print_error, print_success, print_info
from ..utils.cache import ServiceCache

logger = logging.getLogger(__name__)


class AdvancedCalendarService:
    """Advanced Calendar service with AI insights and smart scheduling"""
    
    def __init__(self, oauth_manager: OAuthManager, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.service = None
        self.cache = ServiceCache('calendar_advanced', cache_manager) if cache_manager else None
        self._initialize_service()
    
    def _initialize_service(self) -> bool:
        """Initialize the Calendar service"""
        try:
            self.service = self.oauth_manager.build_service('calendar', 'v3')
            return self.service is not None
        except Exception as e:
            logger.error(f"Failed to initialize Calendar service: {e}")
            return False
    
    def get_smart_schedule_insights(self, days: int = 7) -> Dict[str, Any]:
        """Get AI-powered schedule insights"""
        if not self.service:
            return {}
        
        # Try cache first
        if self.cache:
            cached_result = self.cache.get('smart_schedule_insights', days)
            if cached_result is not None:
                return cached_result
        
        try:
            # Get events for the specified period
            now = datetime.utcnow()
            time_min = now.isoformat() + 'Z'
            time_max = (now + timedelta(days=days)).isoformat() + 'Z'
            
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime',
                maxResults=100
            ).execute()
            
            events = events_result.get('items', [])
            
            # Analyze patterns
            insights = self._analyze_schedule_patterns(events, days)
            
            # Cache the result
            if self.cache:
                self.cache.set('smart_schedule_insights', insights, 300, days)
            
            return insights
        except HttpError as e:
            logger.error(f"Failed to get schedule insights: {e}")
            return {}
    
    def _analyze_schedule_patterns(self, events: List[Dict], days: int) -> Dict[str, Any]:
        """Analyze calendar patterns for insights"""
        if not events:
            return {
                'total_events': 0,
                'busiest_day': None,
                'meeting_density': 0,
                'focus_time_available': 0,
                'recommendations': ['No events found in the specified period']
            }
        
        # Analyze by day of week
        day_counts = {}
        hour_counts = {}
        meeting_types = {}
        total_duration = 0
        
        for event in events:
            start = event.get('start', {}).get('dateTime', event.get('start', {}).get('date'))
            if start:
                dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                day_name = dt.strftime('%A')
                hour = dt.hour
                
                day_counts[day_name] = day_counts.get(day_name, 0) + 1
                hour_counts[hour] = hour_counts.get(hour, 0) + 1
            
            # Categorize meeting types
            summary = event.get('summary', '').lower()
            if any(keyword in summary for keyword in ['meeting', 'call', 'sync']):
                meeting_types['meetings'] = meeting_types.get('meetings', 0) + 1
            elif any(keyword in summary for keyword in ['focus', 'work', 'deep']):
                meeting_types['focus'] = meeting_types.get('focus', 0) + 1
            else:
                meeting_types['other'] = meeting_types.get('other', 0) + 1
            
            # Calculate duration
            end = event.get('end', {}).get('dateTime', event.get('end', {}).get('date'))
            if start and end:
                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                duration = (end_dt - start_dt).total_seconds() / 3600  # hours
                total_duration += duration
        
        # Find patterns
        busiest_day = max(day_counts.items(), key=lambda x: x[1]) if day_counts else None
        peak_hour = max(hour_counts.items(), key=lambda x: x[1]) if hour_counts else None
        
        # Calculate metrics
        total_events = len(events)
        meeting_density = total_events / days
        focus_time_available = max(0, 8 * days - total_duration)  # Assuming 8h workday
        
        # Generate recommendations
        recommendations = self._generate_schedule_recommendations(
            day_counts, meeting_types, meeting_density, focus_time_available
        )
        
        return {
            'total_events': total_events,
            'busiest_day': busiest_day[0] if busiest_day else None,
            'peak_hour': peak_hour[0] if peak_hour else None,
            'meeting_density': round(meeting_density, 1),
            'total_meeting_hours': round(total_duration, 1),
            'focus_time_available': round(focus_time_available, 1),
            'meeting_types': meeting_types,
            'day_distribution': day_counts,
            'hour_distribution': hour_counts,
            'recommendations': recommendations
        }
    
    def _generate_schedule_recommendations(self, day_counts: Dict, meeting_types: Dict, 
                                         density: float, focus_time: float) -> List[str]:
        """Generate AI-powered schedule recommendations"""
        recommendations = []
        
        # Meeting density recommendations
        if density > 8:
            recommendations.append("🔥 High meeting density! Consider blocking focus time.")
        elif density < 3:
            recommendations.append("💡 Low meeting density - good for deep work.")
        
        # Focus time recommendations
        if focus_time < 10:
            recommendations.append("⚠️ Limited focus time available. Schedule deep work blocks.")
        elif focus_time > 30:
            recommendations.append("✅ Excellent focus time availability!")
        
        # Meeting type balance
        total_meetings = meeting_types.get('meetings', 0)
        focus_blocks = meeting_types.get('focus', 0)
        
        if total_meetings > focus_blocks * 3:
            recommendations.append("📊 Consider balancing meetings with focus blocks.")
        
        # Day-specific recommendations
        if day_counts:
            max_day = max(day_counts.values())
            avg_day = sum(day_counts.values()) / len(day_counts)
            
            if max_day > avg_day * 2:
                busiest = max(day_counts, key=day_counts.get)
                recommendations.append(f"📅 {busiest} is overloaded - consider moving some events.")
        
        # General productivity tips
        recommendations.extend([
            "🎯 Schedule important tasks during your peak hours",
            "🤝 Use AI to suggest optimal meeting times",
            "📊 Regular calendar reviews improve productivity"
        ])
        
        return recommendations[:6]  # Return top 6 recommendations
    
    def find_optimal_meeting_time(self, duration_minutes: int = 60, 
                                 attendees: List[str] = None,
                                 preferred_hours: tuple = (9, 17)) -> List[Dict[str, Any]]:
        """Find optimal meeting times using AI"""
        if not self.service:
            return []
        
        try:
            # Get free/busy information
            now = datetime.utcnow()
            time_min = now.isoformat() + 'Z'
            time_max = (now + timedelta(days=7)).isoformat() + 'Z'
            
            # Check availability for next 7 days
            available_slots = []
            
            for day_offset in range(7):
                check_date = now + timedelta(days=day_offset)
                
                # Check each hour in preferred range
                for hour in range(preferred_hours[0], preferred_hours[1]):
                    slot_start = check_date.replace(hour=hour, minute=0, second=0, microsecond=0)
                    slot_end = slot_start + timedelta(minutes=duration_minutes)
                    
                    # Check if slot is free
                    if self._is_time_slot_free(slot_start, slot_end):
                        available_slots.append({
                            'start_time': slot_start.isoformat(),
                            'end_time': slot_end.isoformat(),
                            'day_of_week': slot_start.strftime('%A'),
                            'confidence_score': self._calculate_slot_confidence(
                                slot_start, duration_minutes
                            )
                        })
            
            # Sort by confidence score
            available_slots.sort(key=lambda x: x['confidence_score'], reverse=True)
            
            return available_slots[:5]  # Return top 5 slots
        except HttpError as e:
            logger.error(f"Failed to find optimal meeting times: {e}")
            return []
    
    def _is_time_slot_free(self, start_time: datetime, end_time: datetime) -> bool:
        """Check if a time slot is free"""
        try:
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=start_time.isoformat() + 'Z',
                timeMax=end_time.isoformat() + 'Z',
                singleEvents=True
            ).execute()
            
            events = events_result.get('items', [])
            return len(events) == 0
        except:
            return False
    
    def _calculate_slot_confidence(self, start_time: datetime, duration: int) -> float:
        """Calculate confidence score for a time slot"""
        score = 0.5  # Base score
        
        # Prefer morning hours
        if 9 <= start_time.hour <= 11:
            score += 0.3
        elif 14 <= start_time.hour <= 16:
            score += 0.2
        
        # Prefer weekdays
        if start_time.weekday() < 5:
            score += 0.2
        
        # Avoid lunch time
        if 12 <= start_time.hour <= 13:
            score -= 0.2
        
        return max(0, min(1, score))
    
    def create_smart_event(self, title: str, description: str = "", 
                          duration_minutes: int = 60,
                          attendees: List[str] = None,
                          find_optimal_time: bool = True) -> Optional[str]:
        """Create event with AI-powered time suggestions"""
        if not self.service:
            return None
        
        try:
            event_data = {
                'summary': title,
                'description': description,
                'status': 'confirmed'
            }
            
            if find_optimal_time:
                optimal_slots = self.find_optimal_meeting_time(duration_minutes, attendees)
                if optimal_slots:
                    best_slot = optimal_slots[0]
                    event_data['start'] = {
                        'dateTime': best_slot['start_time'],
                        'timeZone': 'UTC'
                    }
                    event_data['end'] = {
                        'dateTime': best_slot['end_time'],
                        'timeZone': 'UTC'
                    }
                    
                    # Add AI suggestion to description
                    event_data['description'] += f"\n\n🤖 AI suggested this time slot (Confidence: {best_slot['confidence_score']:.1%})"
                else:
                    # Default to tomorrow at 10 AM if no optimal slot found
                    tomorrow = datetime.utcnow() + timedelta(days=1)
                    start_time = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
                    end_time = start_time + timedelta(minutes=duration_minutes)
                    
                    event_data['start'] = {
                        'dateTime': start_time.isoformat() + 'Z',
                        'timeZone': 'UTC'
                    }
                    event_data['end'] = {
                        'dateTime': end_time.isoformat() + 'Z',
                        'timeZone': 'UTC'
                    }
            
            # Add attendees if provided
            if attendees:
                event_data['attendees'] = [{'email': email} for email in attendees]
            
            event = self.service.events().insert(
                calendarId='primary',
                body=event_data,
                sendNotifications=True
            ).execute()
            
            event_id = event.get('id')
            
            # Invalidate cache
            if self.cache:
                self.cache.invalidate('smart_schedule_insights')
            
            print_success(f"Smart event created: {title}")
            if find_optimal_time and optimal_slots:
                print_info(f"🤖 AI suggested optimal time with {optimal_slots[0]['confidence_score']:.1%} confidence")
            
            return event_id
        except HttpError as e:
            logger.error(f"Failed to create smart event: {e}")
            print_error(f"Failed to create event: {e}")
            return None
    
    def get_calendar_analytics(self, period_days: int = 30) -> Dict[str, Any]:
        """Get comprehensive calendar analytics"""
        if not self.service:
            return {}
        
        # Try cache first
        if self.cache:
            cached_result = self.cache.get('calendar_analytics', period_days)
            if cached_result is not None:
                return cached_result
        
        try:
            now = datetime.utcnow()
            time_min = (now - timedelta(days=period_days)).isoformat() + 'Z'
            time_max = now.isoformat() + 'Z'
            
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime',
                maxResults=500
            ).execute()
            
            events = events_result.get('items', [])
            
            analytics = self._generate_calendar_analytics(events, period_days)
            
            # Cache the result
            if self.cache:
                self.cache.set('calendar_analytics', analytics, 600, period_days)
            
            return analytics
        except HttpError as e:
            logger.error(f"Failed to get calendar analytics: {e}")
            return {}
    
    def _generate_calendar_analytics(self, events: List[Dict], period_days: int) -> Dict[str, Any]:
        """Generate comprehensive calendar analytics"""
        if not events:
            return {
                'total_events': 0,
                'period_days': period_days,
                'insights': ['No events found in the specified period']
            }
        
        # Basic metrics
        total_events = len(events)
        total_duration = 0
        recurring_events = 0
        events_with_attendees = 0
        
        # Time analysis
        day_distribution = {}
        hour_distribution = {}
        month_distribution = {}
        
        # Event categories
        categories = {
            'meetings': 0,
            'appointments': 0,
            'focus_time': 0,
            'personal': 0,
            'other': 0
        }
        
        for event in events:
            start = event.get('start', {}).get('dateTime', event.get('start', {}).get('date'))
            end = event.get('end', {}).get('dateTime', event.get('end', {}).get('date'))
            
            if start:
                dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                day_name = dt.strftime('%A')
                hour = dt.hour
                month_name = dt.strftime('%B')
                
                day_distribution[day_name] = day_distribution.get(day_name, 0) + 1
                hour_distribution[hour] = hour_distribution.get(hour, 0) + 1
                month_distribution[month_name] = month_distribution.get(month_name, 0) + 1
            
            # Duration calculation
            if start and end:
                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                duration = (end_dt - start_dt).total_seconds() / 3600
                total_duration += duration
            
            # Event properties
            if event.get('recurrence'):
                recurring_events += 1
            
            if event.get('attendees'):
                events_with_attendees += 1
            
            # Categorize event
            summary = event.get('summary', '').lower()
            if any(keyword in summary for keyword in ['meeting', 'call', 'sync', 'standup']):
                categories['meetings'] += 1
            elif any(keyword in summary for keyword in ['appointment', 'doctor', 'interview']):
                categories['appointments'] += 1
            elif any(keyword in summary for keyword in ['focus', 'deep work', 'block']):
                categories['focus_time'] += 1
            elif any(keyword in summary for keyword in ['personal', 'birthday', 'holiday']):
                categories['personal'] += 1
            else:
                categories['other'] += 1
        
        # Generate insights
        insights = self._generate_calendar_insights(
            total_events, total_duration, recurring_events, 
            events_with_attendees, categories, day_distribution
        )
        
        return {
            'total_events': total_events,
            'period_days': period_days,
            'total_hours': round(total_duration, 1),
            'avg_events_per_day': round(total_events / period_days, 1),
            'avg_hours_per_day': round(total_duration / period_days, 1),
            'recurring_events': recurring_events,
            'events_with_attendees': events_with_attendees,
            'categories': categories,
            'day_distribution': day_distribution,
            'hour_distribution': hour_distribution,
            'month_distribution': month_distribution,
            'insights': insights,
            'productivity_score': self._calculate_productivity_score(categories, total_duration, period_days)
        }
    
    def _generate_calendar_insights(self, total_events: int, total_duration: float,
                                  recurring_events: int, events_with_attendees: int,
                                  categories: Dict, day_distribution: Dict) -> List[str]:
        """Generate AI-powered calendar insights"""
        insights = []
        
        # Meeting load insights
        avg_daily_hours = total_duration / 30  # Assuming 30-day period
        if avg_daily_hours > 6:
            insights.append("📊 High meeting load - consider blocking focus time")
        elif avg_daily_hours < 2:
            insights.append("💡 Light meeting schedule - good for deep work")
        
        # Recurring events
        if recurring_events > total_events * 0.5:
            insights.append("🔄 Many recurring events - review for optimization")
        
        # Collaboration patterns
        if events_with_attendees > total_events * 0.7:
            insights.append("🤝 Highly collaborative schedule")
        elif events_with_attendees < total_events * 0.3:
            insights.append("👤 Mostly individual work scheduled")
        
        # Category balance
        if categories['meetings'] > categories['focus_time'] * 3:
            insights.append("⚖️ Unbalanced schedule - add more focus blocks")
        
        # Day patterns
        if day_distribution:
            max_day = max(day_distribution.values())
            min_day = min(day_distribution.values())
            if max_day > min_day * 3:
                busiest = max(day_distribution, key=day_distribution.get)
                insights.append(f"📅 {busiest} is significantly busier than other days")
        
        return insights
    
    def _calculate_productivity_score(self, categories: Dict, total_hours: float, days: int) -> int:
        """Calculate calendar productivity score (0-100)"""
        score = 50  # Base score
        
        # Balance between meetings and focus time
        if categories['focus_time'] > 0:
            balance_ratio = categories['meetings'] / (categories['focus_time'] + categories['meetings'])
            if 0.3 <= balance_ratio <= 0.7:
                score += 20
            elif balance_ratio > 0.8:
                score -= 15
        
        # Meeting load
        avg_daily = total_hours / days
        if 3 <= avg_daily <= 5:
            score += 15
        elif avg_daily > 8:
            score -= 20
        
        # Recurring events optimization
        total_events = sum(categories.values())
        if total_events > 0:
            recurring_ratio = categories.get('recurring', 0) / total_events
            if 0.2 <= recurring_ratio <= 0.4:
                score += 10
            elif recurring_ratio > 0.6:
                score -= 10
        
        return max(0, min(100, score))
