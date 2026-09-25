"""
AI-powered productivity analytics
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from collections import Counter, defaultdict
import json

from .gemini_client import GeminiClient

logger = logging.getLogger(__name__)


class AIAnalytics:
    """AI-powered productivity analytics and insights"""
    
    def __init__(self, config_manager=None):
        self.config_manager = config_manager
        self.gemini_client = None
        
        if config_manager:
            ai_config = config_manager.get('ai')
            if ai_config and ai_config.gemini_api_key:
                self.gemini_client = GeminiClient(
                    api_key=ai_config.gemini_api_key, 
                    model_name=ai_config.model_name
                )
        
        self.productivity_metrics = {
            'email_response_rate': 0.0,
            'meeting_frequency': 0.0,
            'peak_productivity_hours': [],
            'communication_patterns': {},
            'workload_trends': {}
        }
    
    def analyze_productivity(self, 
                           emails: List[Dict[str, Any]], 
                           events: List[Dict[str, Any]],
                           period: str = 'week') -> Dict[str, Any]:
        """
        Analyze productivity patterns from emails and calendar events
        
        Args:
            emails: List of email dictionaries
            events: List of calendar event dictionaries
            period: Analysis period ('day', 'week', 'month')
            
        Returns:
            Comprehensive productivity analysis
        """
        if not emails and not events:
            return {'message': 'No data available for analysis'}
        
        # Time-based analysis
        time_analysis = self._analyze_time_patterns(emails, events, period)
        
        # Email analysis
        email_analysis = self._analyze_email_patterns(emails, period)
        
        # Calendar analysis
        calendar_analysis = self._analyze_calendar_patterns(events, period)
        
        # Generate insights
        insights = self._generate_productivity_insights(
            time_analysis, email_analysis, calendar_analysis
        )
        
        # Calculate productivity score
        productivity_score = self._calculate_productivity_score(
            email_analysis, calendar_analysis, time_analysis
        )
        
        recommendations = self._generate_recommendations(insights)
        
        # Enhance with Gemini if available
        if self.gemini_client and self.gemini_client.is_available:
            try:
                gemini_analysis = self._analyze_with_gemini(
                    email_analysis, calendar_analysis, time_analysis, period
                )
                if gemini_analysis:
                    # Append Gemini insights and recommendations
                    if 'insights' in gemini_analysis:
                        insights.extend(gemini_analysis['insights'])
                    if 'recommendations' in gemini_analysis:
                        # Prioritize Gemini recommendations
                        recommendations = gemini_analysis['recommendations'] + recommendations
            except Exception as e:
                logger.error(f"Gemini analytics failed: {e}")
        
        return {
            'period': period,
            'productivity_score': productivity_score,
            'time_analysis': time_analysis,
            'email_analysis': email_analysis,
            'calendar_analysis': calendar_analysis,
            'insights': insights,
            'recommendations': recommendations[:5]  # Limit to top 5
        }

    def _analyze_with_gemini(self, 
                           email_stats: Dict[str, Any], 
                           calendar_stats: Dict[str, Any],
                           time_stats: Dict[str, Any], 
                           period: str) -> Optional[Dict[str, Any]]:
        """Analyze productivity stats using Gemini"""
        prompt = f'''
        Analyze the following productivity statistics for the {period}.
        
        Email Stats: {json.dumps(email_stats, default=str)}
        Calendar Stats: {json.dumps(calendar_stats, default=str)}
        Time Stats: {json.dumps(time_stats, default=str)}
        
        Return ONLY a JSON object with:
        - insights: list of deep insights about working habits and productivity
        - recommendations: list of specific, actionable recommendations to improve productivity
        '''
        
        response = self.gemini_client.generate_content(prompt)
        if not response:
            return None
            
        try:
            # Clean up response
            text = response.replace('```json', '').replace('```', '').strip()
            start_idx = text.find('{')
            end_idx = text.rfind('}') + 1
            if start_idx != -1 and end_idx != -1:
                return json.loads(text[start_idx:end_idx])
        except Exception as e:
            logger.error(f"Error parsing Gemini response: {e}")
            return None
        return None
    
    def _analyze_time_patterns(self, 
                              emails: List[Dict[str, Any]], 
                              events: List[Dict[str, Any]], 
                              period: str) -> Dict[str, Any]:
        """Analyze time-based patterns"""
        hour_activity = defaultdict(int)
        day_activity = defaultdict(int)
        
        # Analyze email timestamps
        for email in emails:
            date_str = email.get('date', '')
            if date_str:
                try:
                    # Parse date (simplified)
                    if 'T' in date_str:
                        datetime_part = date_str.split('T')[1]
                        hour = int(datetime_part.split(':')[0])
                    else:
                        hour = 12  # Default to noon if no time
                    
                    hour_activity[hour] += 1
                    day_activity['email'] += 1
                except:
                    continue
        
        # Analyze event times
        for event in events:
            start_str = event.get('start', '')
            if start_str:
                try:
                    if 'T' in start_str:
                        datetime_part = start_str.split('T')[1]
                        hour = int(datetime_part.split(':')[0])
                    else:
                        hour = 12  # Default to noon if no time
                    
                    hour_activity[hour] += 1
                    day_activity['events'] += 1
                except:
                    continue
        
        # Find peak hours
        if hour_activity:
            peak_hours = sorted(hour_activity.items(), key=lambda x: x[1], reverse=True)[:3]
            peak_hours = [f"{hour}:00" for hour, count in peak_hours]
        else:
            peak_hours = []
        
        return {
            'peak_hours': peak_hours,
            'hourly_distribution': dict(hour_activity),
            'daily_breakdown': dict(day_activity)
        }
    
    def _analyze_email_patterns(self, emails: List[Dict[str, Any]], period: str) -> Dict[str, Any]:
        """Analyze email communication patterns"""
        if not emails:
            return {'total': 0}
        
        total_emails = len(emails)
        
        # Sender analysis
        senders = [email.get('from', '') for email in emails]
        sender_counts = Counter(senders)
        top_senders = sender_counts.most_common(5)
        
        # Subject analysis
        subjects = [email.get('subject', '') for email in emails]
        subject_lengths = [len(s) for s in subjects if s]
        avg_subject_length = sum(subject_lengths) / len(subject_lengths) if subject_lengths else 0
        
        # Time-based patterns
        recent_emails = 0
        older_emails = 0
        
        for email in emails:
            date_str = email.get('date', '')
            if date_str:
                try:
                    # Simple date parsing
                    if '2026' in date_str:  # Current year
                        recent_emails += 1
                    else:
                        older_emails += 1
                except:
                    continue
        
        return {
            'total': total_emails,
            'top_senders': top_senders,
            'avg_subject_length': round(avg_subject_length, 1),
            'recent_emails': recent_emails,
            'older_emails': older_emails,
            'emails_per_day': round(total_emails / 7, 1) if period == 'week' else total_emails
        }
    
    def _analyze_calendar_patterns(self, events: List[Dict[str, Any]], period: str) -> Dict[str, Any]:
        """Analyze calendar event patterns"""
        if not events:
            return {'total': 0}
        
        total_events = len(events)
        
        # Event types by keywords
        meeting_events = 0
        personal_events = 0
        other_events = 0
        
        for event in events:
            title = event.get('summary', '').lower()
            if any(keyword in title for keyword in ['meeting', 'call', 'conference', 'sync']):
                meeting_events += 1
            elif any(keyword in title for keyword in ['birthday', 'personal', 'holiday']):
                personal_events += 1
            else:
                other_events += 1
        
        # Duration analysis (simplified)
        avg_duration_hours = 1.0  # Default assumption
        
        return {
            'total': total_events,
            'meetings': meeting_events,
            'personal': personal_events,
            'other': other_events,
            'avg_duration_hours': avg_duration_hours,
            'events_per_day': round(total_events / 7, 1) if period == 'week' else total_events
        }
    
    def _generate_productivity_insights(self, 
                                      time_analysis: Dict[str, Any],
                                      email_analysis: Dict[str, Any],
                                      calendar_analysis: Dict[str, Any]) -> List[str]:
        """Generate AI-powered insights from data"""
        insights = []
        
        # Email insights
        if email_analysis.get('total', 0) > 50:
            insights.append("High email volume - consider batching responses")
        
        if email_analysis.get('top_senders'):
            top_sender = email_analysis['top_senders'][0]
            insights.append(f"Most communication with {top_sender[0]} ({top_sender[1]} emails)")
        
        # Calendar insights
        if calendar_analysis.get('meetings', 0) > 10:
            insights.append("Heavy meeting schedule - ensure focus time")
        
        if calendar_analysis.get('personal', 0) > 5:
            insights.append("Good work-life balance with personal events")
        
        # Time insights
        if time_analysis.get('peak_hours'):
            peak_hour = time_analysis['peak_hours'][0]
            insights.append(f"Peak activity around {peak_hour}")
        
        # Communication patterns
        total_emails = email_analysis.get('total', 0)
        total_events = calendar_analysis.get('total', 0)
        
        if total_emails > total_events * 5:
            insights.append("Email-heavy communication pattern")
        elif total_events > total_emails * 2:
            insights.append("Meeting-heavy schedule")
        else:
            insights.append("Balanced communication approach")
        
        return insights
    
    def _calculate_productivity_score(self, 
                                    email_analysis: Dict[str, Any],
                                    calendar_analysis: Dict[str, Any],
                                    time_analysis: Dict[str, Any]) -> float:
        """Calculate overall productivity score (0-100)"""
        score = 50  # Base score
        
        # Email productivity factors
        email_total = email_analysis.get('total', 0)
        if 10 <= email_total <= 30:  # Optimal range
            score += 10
        elif email_total > 50:  # Too many emails
            score -= 10
        
        # Meeting productivity factors
        meetings = calendar_analysis.get('meetings', 0)
        if 5 <= meetings <= 15:  # Optimal range
            score += 10
        elif meetings > 20:  # Too many meetings
            score -= 15
        
        # Work-life balance
        personal_events = calendar_analysis.get('personal', 0)
        if personal_events > 0:
            score += 5
        
        # Time distribution
        peak_hours = time_analysis.get('peak_hours', [])
        if len(peak_hours) > 0:
            score += 5
        
        return max(0, min(100, score))
    
    def _generate_recommendations(self, insights: List[str]) -> List[str]:
        """Generate AI-powered recommendations"""
        recommendations = []
        
        insight_text = ' '.join(insights).lower()
        
        if 'high email volume' in insight_text:
            recommendations.append("Schedule specific email checking times (2-3x per day)")
            recommendations.append("Use email templates for common responses")
        
        if 'heavy meeting schedule' in insight_text:
            recommendations.append("Block focus time between meetings")
            recommendations.append("Evaluate if all meetings are necessary")
        
        if 'peak activity' in insight_text:
            recommendations.append("Schedule important tasks during peak hours")
        
        if 'email-heavy' in insight_text:
            recommendations.append("Consider more direct communication methods")
            recommendations.append("Use chat or calls for quick discussions")
        
        if 'meeting-heavy' in insight_text:
            recommendations.append("Send agendas in advance to reduce meeting time")
            recommendations.append("Consider async updates instead of meetings")
        
        if not recommendations:
            recommendations.append("Maintain current productivity patterns")
            recommendations.append("Continue balancing email and meeting communication")
        
        return recommendations[:5]  # Return top 5 recommendations
    
    def generate_weekly_report(self, 
                              emails: List[Dict[str, Any]], 
                              events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate comprehensive weekly productivity report"""
        analysis = self.analyze_productivity(emails, events, 'week')
        
        # Add weekly-specific metrics
        week_start = datetime.now() - timedelta(days=datetime.now().weekday())
        week_end = week_start + timedelta(days=6)
        
        return {
            'report_period': f"{week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}",
            'executive_summary': self._generate_executive_summary(analysis),
            'detailed_analysis': analysis,
            'achievements': self._extract_achievements(events),
            'challenges': self._identify_challenges(emails, events),
            'next_week_priorities': self._suggest_priorities(analysis)
        }
    
    def _generate_executive_summary(self, analysis: Dict[str, Any]) -> str:
        """Generate executive summary for weekly report"""
        score = analysis.get('productivity_score', 50)
        insights = analysis.get('insights', [])
        
        if score >= 80:
            performance = "excellent"
        elif score >= 60:
            performance = "good"
        elif score >= 40:
            performance = "moderate"
        else:
            performance = "needs improvement"
        
        summary = f"Weekly productivity was {performance} (score: {score}/100). "
        
        if insights:
            summary += f"Key insights: {insights[0].lower()}"
            if len(insights) > 1:
                summary += f". {insights[1].lower()}"
        
        return summary
    
    def _extract_achievements(self, events: List[Dict[str, Any]]) -> List[str]:
        """Extract achievements from calendar events"""
        achievements = []
        
        for event in events:
            title = event.get('summary', '').lower()
            if any(keyword in title for keyword in ['completed', 'finished', 'done', 'achieved']):
                achievements.append(event.get('summary', ''))
        
        return achievements[:3]  # Top 3 achievements
    
    def _identify_challenges(self, emails: List[Dict[str, Any]], events: List[Dict[str, Any]]) -> List[str]:
        """Identify challenges from emails and events"""
        challenges = []
        
        # Look for challenge indicators in emails
        for email in emails:
            subject = email.get('subject', '').lower()
            if any(keyword in subject for keyword in ['problem', 'issue', 'delay', 'urgent']):
                challenges.append(email.get('subject', ''))
        
        # Look for schedule conflicts
        if len(events) > 20:
            challenges.append("Heavy schedule with many commitments")
        
        return challenges[:3]  # Top 3 challenges
    
    def _suggest_priorities(self, analysis: Dict[str, Any]) -> List[str]:
        """Suggest priorities for next week"""
        priorities = []
        
        recommendations = analysis.get('recommendations', [])
        insights = analysis.get('insights', [])
        
        # Convert recommendations to priorities
        for rec in recommendations[:3]:
            if 'schedule' in rec.lower():
                priorities.append(f"Schedule: {rec}")
            elif 'consider' in rec.lower():
                priorities.append(f"Consider: {rec}")
            else:
                priorities.append(f"Action: {rec}")
        
        if not priorities:
            priorities.append("Maintain current productivity habits")
            priorities.append("Focus on high-impact activities")
        
        return priorities
