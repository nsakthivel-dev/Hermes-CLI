"""
Advanced Gmail service with AI-powered email management
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import re
from collections import Counter

from googleapiclient.errors import HttpError

from ..auth.oauth import OAuthManager
from ..utils.formatters import print_error, print_success, print_info
from ..utils.cache import ServiceCache

logger = logging.getLogger(__name__)


class AdvancedGmailService:
    """Advanced Gmail service with AI-powered email management"""
    
    def __init__(self, oauth_manager: OAuthManager, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.service = None
        self.cache = ServiceCache('gmail_advanced', cache_manager) if cache_manager else None
        self._initialize_service()
        
        # Email categories for AI classification
        self.email_categories = {
            'urgent': ['urgent', 'asap', 'immediately', 'emergency', 'critical', 'important'],
            'work': ['project', 'meeting', 'deadline', 'report', 'client', 'business'],
            'personal': ['family', 'friend', 'personal', 'birthday', 'invitation'],
            'newsletter': ['unsubscribe', 'newsletter', 'promotion', 'sale', 'offer'],
            'notification': ['notification', 'alert', 'reminder', 'update']
        }
    
    def _initialize_service(self) -> bool:
        """Initialize the Gmail service"""
        try:
            self.service = self.oauth_manager.build_service('gmail', 'v1')
            return self.service is not None
        except Exception as e:
            logger.error(f"Failed to initialize Gmail service: {e}")
            return False
    
    def get_ai_email_insights(self, max_emails: int = 100) -> Dict[str, Any]:
        """Get AI-powered email insights"""
        if not self.service:
            return {}
        
        # Try cache first
        if self.cache:
            cached_result = self.cache.get('ai_email_insights', max_emails)
            if cached_result is not None:
                return cached_result
        
        try:
            # Get recent emails
            messages_result = self.service.users().messages().list(
                userId='me',
                maxResults=max_emails,
                labelIds=['INBOX']
            ).execute()
            
            messages = messages_result.get('messages', [])
            
            # Analyze emails
            insights = self._analyze_emails_for_insights(messages)
            
            # Cache the result
            if self.cache:
                self.cache.set('ai_email_insights', insights, 300, max_emails)
            
            return insights
        except HttpError as e:
            logger.error(f"Failed to get email insights: {e}")
            return {}
    
    def _analyze_emails_for_insights(self, messages: List[Dict]) -> Dict[str, Any]:
        """Analyze emails for AI insights"""
        if not messages:
            return {
                'total_emails': 0,
                'insights': ['No emails found for analysis'],
                'categories': {},
                'recommendations': []
            }
        
        # Fetch full email details
        emails_data = []
        for message in messages[:50]:  # Limit to 50 for detailed analysis
            try:
                msg = self.service.users().messages().get(
                    userId='me',
                    id=message['id'],
                    format='metadata',
                    metadataHeaders=['From', 'Subject', 'Date', 'To']
                ).execute()
                emails_data.append(msg)
            except:
                continue
        
        # Analyze patterns
        analysis = {
            'total_emails': len(messages),
            'analyzed_emails': len(emails_data),
            'categories': {},
            'sender_patterns': {},
            'time_patterns': {},
            'subject_patterns': {},
            'urgency_level': 0,
            'response_required': 0,
            'insights': [],
            'recommendations': []
        }
        
        for email in emails_data:
            # Extract headers
            headers = {h['name']: h['value'] for h in email.get('payload', {}).get('headers', [])}
            
            subject = headers.get('Subject', '').lower()
            sender = headers.get('From', '')
            date_str = headers.get('Date', '')
            
            # Categorize email
            category = self._categorize_email(subject)
            analysis['categories'][category] = analysis['categories'].get(category, 0) + 1
            
            # Sender patterns
            sender_domain = self._extract_domain(sender)
            analysis['sender_patterns'][sender_domain] = analysis['sender_patterns'].get(sender_domain, 0) + 1
            
            # Time patterns
            if date_str:
                hour = self._extract_hour(date_str)
                if hour is not None:
                    analysis['time_patterns'][hour] = analysis['time_patterns'].get(hour, 0) + 1
            
            # Check urgency
            if self._is_urgent_email(subject):
                analysis['urgency_level'] += 1
            
            # Check if response required
            if self._requires_response(subject):
                analysis['response_required'] += 1
        
        # Generate insights
        analysis['insights'] = self._generate_email_insights(analysis)
        analysis['recommendations'] = self._generate_email_recommendations(analysis)
        
        return analysis
    
    def _categorize_email(self, subject: str) -> str:
        """Categorize email based on subject"""
        for category, keywords in self.email_categories.items():
            if any(keyword in subject for keyword in keywords):
                return category
        return 'general'
    
    def _extract_domain(self, email: str) -> str:
        """Extract domain from email address"""
        match = re.search(r'@([^>]+)', email)
        return match.group(1) if match else 'unknown'
    
    def _extract_hour(self, date_str: str) -> Optional[int]:
        """Extract hour from date string"""
        try:
            # Simple parsing - in production, use proper date parsing
            if ':' in date_str:
                time_part = date_str.split(' ')[4] if len(date_str.split(' ')) > 4 else '00:00:00'
                hour = int(time_part.split(':')[0])
                return hour
        except:
            pass
        return None
    
    def _is_urgent_email(self, subject: str) -> bool:
        """Check if email is urgent"""
        urgent_keywords = ['urgent', 'asap', 'immediately', 'emergency', 'critical']
        return any(keyword in subject for keyword in urgent_keywords)
    
    def _requires_response(self, subject: str) -> bool:
        """Check if email requires response"""
        response_keywords = ['question', 'please', 'request', 'needed', 'required', 'action']
        return any(keyword in subject for keyword in response_keywords)
    
    def _generate_email_insights(self, analysis: Dict) -> List[str]:
        """Generate AI-powered email insights"""
        insights = []
        
        # Volume insights
        total = analysis['total_emails']
        if total > 100:
            insights.append(f"📊 High email volume: {total} emails in recent period")
        elif total < 20:
            insights.append(f"💡 Low email volume: {total} emails - good inbox health")
        
        # Category insights
        categories = analysis['categories']
        if categories.get('urgent', 0) > 5:
            insights.append(f"🚨 {categories['urgent']} urgent emails need attention")
        
        if categories.get('newsletter', 0) > total * 0.3:
            insights.append("📧 High newsletter volume - consider unsubscribing")
        
        # Sender patterns
        senders = analysis['sender_patterns']
        if senders:
            top_sender = max(senders.items(), key=lambda x: x[1])
            if top_sender[1] > total * 0.2:
                insights.append(f"👤 {top_sender[0]} is your primary communication partner")
        
        # Time patterns
        time_patterns = analysis['time_patterns']
        if time_patterns:
            peak_hour = max(time_patterns.items(), key=lambda x: x[1])
            insights.append(f"⏰ Peak email activity around {peak_hour[0]}:00")
        
        # Response requirements
        if analysis['response_required'] > 10:
            insights.append(f"📝 {analysis['response_required']} emails likely need responses")
        
        return insights
    
    def _generate_email_recommendations(self, analysis: Dict) -> List[str]:
        """Generate AI-powered email recommendations"""
        recommendations = []
        
        categories = analysis['categories']
        total = analysis['total_emails']
        
        # Urgency recommendations
        if analysis['urgency_level'] > 0:
            recommendations.append("🚨 Prioritize urgent emails first")
        
        # Category-based recommendations
        if categories.get('newsletter', 0) > 5:
            recommendations.append("📧 Consider unsubscribing from newsletters you don't read")
        
        if categories.get('personal', 0) > categories.get('work', 0):
            recommendations.append("👥 Good work-life balance in email communication")
        
        # Response recommendations
        if analysis['response_required'] > total * 0.5:
            recommendations.append("📝 High response requirement - schedule email processing time")
        
        # General productivity recommendations
        recommendations.extend([
            "🎯 Use AI to prioritize important emails",
            "📊 Regular email reviews improve productivity",
            "🤖 Set up automated filters for better organization"
        ])
        
        return recommendations[:5]  # Return top 5 recommendations
    
    def smart_email_search(self, query: str, category: str = None, 
                          sender: str = None, date_range: int = None) -> List[Dict[str, Any]]:
        """Smart email search with AI-powered filters"""
        if not self.service:
            return []
        
        try:
            # Build search query
            search_terms = []
            
            if query:
                search_terms.append(query)
            
            if category and category in self.email_categories:
                # Add category keywords to search
                keywords = self.email_categories[category]
                search_terms.extend(keywords)
            
            if sender:
                search_terms.append(f"from:{sender}")
            
            if date_range:
                # Add date filter (newer than X days)
                search_terms.append(f"newer_than:{date_range}d")
            
            search_query = ' '.join(search_terms)
            
            # Execute search
            messages_result = self.service.users().messages().list(
                userId='me',
                q=search_query,
                maxResults=50
            ).execute()
            
            messages = messages_result.get('messages', [])
            
            # Fetch detailed results
            results = []
            for message in messages[:20]:  # Limit to 20 results
                try:
                    msg = self.service.users().messages().get(
                        userId='me',
                        id=message['id'],
                        format='metadata',
                        metadataHeaders=['From', 'Subject', 'Date', 'To', 'Snippet']
                    ).execute()
                    
                    # Extract relevant information
                    headers = {h['name']: h['value'] for h in msg.get('payload', {}).get('headers', [])}
                    snippet = msg.get('snippet', '')
                    
                    result = {
                        'id': message['id'],
                        'from': headers.get('From', ''),
                        'subject': headers.get('Subject', ''),
                        'date': headers.get('Date', ''),
                        'snippet': snippet,
                        'category': self._categorize_email(headers.get('Subject', '').lower()),
                        'urgency': 'high' if self._is_urgent_email(headers.get('Subject', '').lower()) else 'normal'
                    }
                    results.append(result)
                    
                except:
                    continue
            
            return results
        except HttpError as e:
            logger.error(f"Failed to search emails: {e}")
            return []
    
    def generate_smart_reply(self, message_id: str) -> Dict[str, Any]:
        """Generate AI-powered smart replies for an email"""
        if not self.service:
            return {}
        
        try:
            # Get email content
            msg = self.service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            
            # Extract content
            subject = ''
            body = ''
            sender = ''
            
            headers = {h['name']: h['value'] for h in msg.get('payload', {}).get('headers', [])}
            subject = headers.get('Subject', '')
            sender = headers.get('From', '')
            
            # Extract body text
            payload = msg.get('payload', {})
            if 'parts' in payload:
                for part in payload['parts']:
                    if part.get('mimeType') == 'text/plain':
                        data = part.get('body', {}).get('data', '')
                        if data:
                            import base64
                            body = base64.urlsafe_b64decode(data).decode('utf-8')
                            break
            else:
                data = payload.get('body', {}).get('data', '')
                if data:
                    import base64
                    body = base64.urlsafe_b64decode(data).decode('utf-8')
            
            # Generate smart replies
            smart_replies = self._generate_smart_replies(subject, body, sender)
            
            return {
                'message_id': message_id,
                'subject': subject,
                'sender': sender,
                'smart_replies': smart_replies,
                'tone_analysis': self._analyze_email_tone(subject + ' ' + body),
                'action_items': self._extract_action_items(body)
            }
        except HttpError as e:
            logger.error(f"Failed to generate smart reply: {e}")
            return {}
    
    def _generate_smart_replies(self, subject: str, body: str, sender: str) -> List[str]:
        """Generate AI-powered smart replies"""
        replies = []
        
        subject_lower = subject.lower()
        body_lower = body.lower()
        
        # Check for urgency
        if any(keyword in subject_lower + body_lower for keyword in ['urgent', 'asap', 'immediately']):
            replies.extend([
                "I'll look into this right away and get back to you shortly.",
                "Thank you for the urgent update. I'm prioritizing this now.",
                "Received and understood the urgency. I'm on it."
            ])
        
        # Check for questions
        elif '?' in body and any(keyword in body_lower for keyword in ['question', 'help', 'clarify']):
            replies.extend([
                "I'll review your questions and provide a detailed response.",
                "Thank you for your questions. Let me address each one.",
                "I need to look into this further. I'll respond with the answers."
            ])
        
        # Check for meeting requests
        elif any(keyword in subject_lower + body_lower for keyword in ['meeting', 'call', 'schedule', 'appointment']):
            replies.extend([
                "I'm available for this meeting. Please send the calendar invitation.",
                "Thank you for the meeting request. I'll check my schedule and confirm.",
                "I'd be happy to meet. Let me know what times work for you."
            ])
        
        # Check for gratitude
        elif any(keyword in body_lower for keyword in ['thank', 'appreciate', 'great', 'wonderful']):
            replies.extend([
                "You're welcome! Happy to help.",
                "Thank you! I'm glad I could assist.",
                "It was my pleasure. Don't hesitate to reach out again."
            ])
        
        # Check for documents/files
        elif any(keyword in body_lower for keyword in ['attachment', 'document', 'file', 'review']):
            replies.extend([
                "I've received the document and will review it shortly.",
                "Thank you for sending the file. I'll review and provide feedback.",
                "I've downloaded the attachment and will get back to you with my thoughts."
            ])
        
        # Default professional replies
        else:
            replies.extend([
                "Thank you for your message. I'll review and respond appropriately.",
                "Received. I'll get back to you after reviewing this.",
                "Thank you for reaching out. I'll respond soon."
            ])
        
        return replies[:3]  # Return top 3 replies
    
    def _analyze_email_tone(self, text: str) -> str:
        """Analyze email tone"""
        text_lower = text.lower()
        
        positive_words = ['great', 'excellent', 'wonderful', 'thank', 'appreciate', 'happy', 'pleased']
        negative_words = ['problem', 'issue', 'error', 'urgent', 'concern', 'difficult', 'unfortunately']
        neutral_words = ['information', 'update', 'fyi', 'note', 'regarding', 'about']
        
        positive_count = sum(1 for word in positive_words if word in text_lower)
        negative_count = sum(1 for word in negative_words if word in text_lower)
        neutral_count = sum(1 for word in neutral_words if word in text_lower)
        
        if negative_count > positive_count:
            return 'negative'
        elif positive_count > negative_count and positive_count > neutral_count:
            return 'positive'
        else:
            return 'neutral'
    
    def _extract_action_items(self, body: str) -> List[str]:
        """Extract action items from email body"""
        action_items = []
        
        # Look for action-oriented phrases
        sentences = body.split('.')
        for sentence in sentences:
            sentence = sentence.strip()
            if any(keyword in sentence.lower() for keyword in 
                   ['please', 'need to', 'should', 'must', 'required', 'action']):
                if len(sentence) > 10:
                    action_items.append(sentence)
        
        return action_items[:3]  # Return top 3 action items
    
    def create_smart_filter(self, filter_name: str, criteria: Dict[str, Any]) -> bool:
        """Create smart email filter with AI suggestions"""
        if not self.service:
            return False
        
        try:
            # Build filter criteria
            filter_criteria = {}
            
            if criteria.get('from'):
                filter_criteria['from'] = criteria['from']
            
            if criteria.get('subject'):
                filter_criteria['subject'] = criteria['subject']
            
            if criteria.get('has_words'):
                filter_criteria['hasTheWord'] = criteria['has_words']
            
            if criteria.get('no_words'):
                filter_criteria['doesNotHaveTheWord'] = criteria['no_words']
            
            # Add label action
            if criteria.get('label'):
                filter_criteria['addLabelIds'] = [criteria['label']]
            
            # Create filter
            self.service.users().settings().filters().create(
                userId='me',
                body={
                    'criteria': filter_criteria,
                    'action': {
                        'addLabelIds': criteria.get('labels', []),
                        'removeLabelIds': criteria.get('remove_labels', [])
                    }
                }
            ).execute()
            
            print_success(f"Smart filter '{filter_name}' created successfully")
            return True
        except HttpError as e:
            logger.error(f"Failed to create filter: {e}")
            print_error(f"Failed to create filter: {e}")
            return False
