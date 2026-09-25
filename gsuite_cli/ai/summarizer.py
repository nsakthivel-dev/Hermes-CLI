"""
AI-powered email and content summarization
"""

import re
import logging
from typing import List, Dict, Any, Optional
from collections import Counter
import math
import json

from .gemini_client import GeminiClient

logger = logging.getLogger(__name__)


class EmailSummarizer:
    """AI-powered email summarization and smart reply generation"""
    
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
        
        self.urgency_keywords = {
            'urgent', 'asap', 'immediately', 'emergency', 'critical', 'important',
            'deadline', 'overdue', 'action required', 'response needed', 'urgent action'
        }
        
        self.positive_keywords = {
            'great', 'excellent', 'amazing', 'wonderful', 'fantastic', 'perfect',
            'love', 'awesome', 'brilliant', 'outstanding', 'superb'
        }
        
        self.negative_keywords = {
            'problem', 'issue', 'error', 'bug', 'failed', 'broken', 'wrong',
            'terrible', 'awful', 'horrible', 'disappointed', 'frustrated'
        }
    
    def summarize_email(self, email: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate AI summary for a single email
        
        Args:
            email: Email dictionary with subject, body, from, etc.
            
        Returns:
            Dictionary with summary, sentiment, urgency, and smart replies
        """
        # Try Gemini first
        if self.gemini_client and self.gemini_client.is_available:
            try:
                result = self._summarize_email_with_gemini(email)
                if result:
                    return result
            except Exception as e:
                logger.error(f"Gemini summarization failed: {e}")

        subject = email.get('subject', '')
        body = email.get('snippet', '') or email.get('body', '')
        sender = email.get('from', '')
        
        # Extract key information
        key_points = self._extract_key_points(subject, body)
        sentiment = self._analyze_sentiment(subject, body)
        urgency = self._assess_urgency(subject, body)
        action_items = self._extract_action_items(body)
        
        # Generate smart replies
        smart_replies = self._generate_smart_replies(sentiment, urgency, action_items)
        
        return {
            'summary': self._generate_summary(key_points, sentiment),
            'sentiment': sentiment,
            'urgency': urgency,
            'action_items': action_items,
            'smart_replies': smart_replies,
            'key_points': key_points
        }

    def _summarize_email_with_gemini(self, email: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Summarize email using Gemini"""
        subject = email.get('subject', '')
        body = email.get('snippet', '') or email.get('body', '')
        sender = email.get('from', '')
        
        prompt = f'''
        Summarize the following email for me.
        From: {sender}
        Subject: {subject}
        Body: {body}
        
        Return ONLY a JSON object with:
        - summary: concise summary string
        - sentiment: float -1.0 (negative) to 1.0 (positive)
        - urgency: float 0.0 (low) to 1.0 (high)
        - action_items: list of action strings
        - smart_replies: list of 3 suggested replies
        - key_points: list of key points
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
    
    def summarize_multiple_emails(self, emails: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate summary for multiple emails
        
        Args:
            emails: List of email dictionaries
            
        Returns:
            Comprehensive summary with trends and insights
        """
        if not emails:
            return {'summary': 'No emails to summarize', 'insights': []}
            
        # Try Gemini first
        if self.gemini_client and self.gemini_client.is_available:
            try:
                result = self._summarize_multiple_emails_with_gemini(emails)
                if result:
                    return result
            except Exception as e:
                logger.error(f"Gemini multi-summarization failed: {e}")
        
        # Analyze individual emails
        email_summaries = [self.summarize_email(email) for email in emails]
        
        # Aggregate insights
        total_emails = len(emails)
        urgent_count = sum(1 for s in email_summaries if s['urgency'] > 0.7)
        positive_count = sum(1 for s in email_summaries if s['sentiment'] > 0.3)
        negative_count = sum(1 for s in email_summaries if s['sentiment'] < -0.3)
        
        # Extract themes
        all_subjects = [email.get('subject', '') for email in emails]
        themes = self._extract_themes(all_subjects)
        
        # Sender analysis
        senders = [email.get('from', '') for email in emails]
        sender_counts = Counter(senders)
        top_senders = sender_counts.most_common(5)
        
        return {
            'summary': f"You have {total_emails} emails. {urgent_count} are urgent. "
                     f"{'Positive tone dominates.' if positive_count > negative_count else 'Mixed or negative tone.'}",
            'total_emails': total_emails,
            'urgent_emails': urgent_count,
            'sentiment_breakdown': {
                'positive': positive_count,
                'negative': negative_count,
                'neutral': total_emails - positive_count - negative_count
            },
            'themes': themes,
            'top_senders': top_senders,
            'insights': self._generate_insights(email_summaries)
        }

    def _summarize_multiple_emails_with_gemini(self, emails: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Summarize multiple emails using Gemini"""
        # Prepare email text (limit to 20 emails to avoid token limits)
        email_texts = []
        for i, email in enumerate(emails[:20]):
            email_texts.append(f"Email {i+1}: From: {email.get('from')}, Subject: {email.get('subject')}, Body: {email.get('snippet')}")
        
        prompt = f'''
        Analyze the following {len(email_texts)} emails and provide a comprehensive summary.
        
        {chr(10).join(email_texts)}
        
        Return ONLY a JSON object with:
        - summary: overall summary string describing key themes and urgent items
        - total_emails: integer count
        - urgent_emails: integer count of urgent emails
        - sentiment_breakdown: {{ "positive": int, "negative": int, "neutral": int }}
        - themes: list of common themes/keywords
        - top_senders: list of [sender, count] lists
        - insights: list of key insights or action items derived from the group
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
    
    def _extract_key_points(self, subject: str, body: str) -> List[str]:
        """Extract key points from email content"""
        key_points = []
        
        # Add subject as key point if meaningful
        if len(subject) > 10 and not subject.lower().startswith('re:'):
            key_points.append(subject)
        
        # Extract sentences with important keywords
        sentences = re.split(r'[.!?]+', body)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 20 and self._is_important_sentence(sentence):
                key_points.append(sentence)
        
        return key_points[:3]  # Return top 3 key points
    
    def _is_important_sentence(self, sentence: str) -> bool:
        """Check if sentence contains important information"""
        sentence_lower = sentence.lower()
        
        # Check for urgency indicators
        if any(keyword in sentence_lower for keyword in self.urgency_keywords):
            return True
        
        # Check for action items
        if any(word in sentence_lower for word in ['please', 'need to', 'must', 'should', 'required']):
            return True
        
        # Check for numbers (dates, amounts, etc.)
        if re.search(r'\d+', sentence):
            return True
        
        # Check for proper nouns (capitalized words)
        if len(re.findall(r'\b[A-Z][a-z]+\b', sentence)) >= 2:
            return True
        
        return False
    
    def _analyze_sentiment(self, subject: str, body: str) -> float:
        """Analyze sentiment of email content"""
        text = (subject + ' ' + body).lower()
        
        positive_score = sum(1 for word in self.positive_keywords if word in text)
        negative_score = sum(1 for word in self.negative_keywords if word in text)
        
        # Normalize to -1 to 1 range
        total_score = positive_score - negative_score
        max_possible = max(positive_score + negative_score, 1)
        
        return round(total_score / max_possible, 2)
    
    def _assess_urgency(self, subject: str, body: str) -> float:
        """Assess urgency level of email"""
        text = (subject + ' ' + body).lower()
        
        urgency_score = 0
        
        # Check for urgency keywords
        for keyword in self.urgency_keywords:
            if keyword in text:
                urgency_score += 1
        
        # Check for time-sensitive phrases
        if any(phrase in text for phrase in ['asap', 'as soon as possible', 'immediately']):
            urgency_score += 2
        
        if any(phrase in text for phrase in ['deadline', 'due date', 'overdue']):
            urgency_score += 2
        
        # Check for question marks (indicates response needed)
        urgency_score += text.count('?') * 0.5
        
        # Normalize to 0-1 range
        return round(min(urgency_score / 5, 1.0), 2)
    
    def _extract_action_items(self, body: str) -> List[str]:
        """Extract action items from email body"""
        action_items = []
        
        sentences = re.split(r'[.!?]+', body)
        for sentence in sentences:
            sentence = sentence.strip()
            
            # Check for action indicators
            if any(indicator in sentence.lower() for indicator in 
                   ['please', 'need to', 'must', 'should', 'required', 'action']):
                if len(sentence) > 15:
                    action_items.append(sentence)
        
        return action_items[:3]  # Return top 3 action items
    
    def _generate_smart_replies(self, sentiment: float, urgency: float, action_items: List[str]) -> List[str]:
        """Generate smart reply suggestions"""
        replies = []
        
        if urgency > 0.7:
            replies.append("I'll look into this right away.")
            replies.append("Thanks for bringing this to my attention. I'll respond shortly.")
        elif sentiment > 0.3:
            replies.append("That's great news! Thank you for sharing.")
            replies.append("Wonderful! I appreciate this update.")
        elif sentiment < -0.3:
            replies.append("I understand your concern. Let me help resolve this.")
            replies.append("Thanks for letting me know. I'll address this issue.")
        else:
            replies.append("Thank you for the information.")
            replies.append("Got it. I'll review this and follow up if needed.")
        
        if action_items:
            replies.append("I'll take care of the action items mentioned.")
        
        return replies[:3]  # Return top 3 replies
    
    def _generate_summary(self, key_points: List[str], sentiment: float) -> str:
        """Generate a concise summary"""
        if not key_points:
            return "No significant content to summarize."
        
        summary = key_points[0]
        if len(key_points) > 1:
            summary += f" Also: {key_points[1]}"
        
        # Add sentiment context
        if sentiment > 0.3:
            summary += " (Positive tone)"
        elif sentiment < -0.3:
            summary += " (Negative tone)"
        
        return summary
    
    def _extract_themes(self, subjects: List[str]) -> List[str]:
        """Extract common themes from email subjects"""
        # Simple keyword extraction from subjects
        all_words = []
        for subject in subjects:
            words = re.findall(r'\b\w+\b', subject.lower())
            all_words.extend([word for word in words if len(word) > 3])
        
        word_counts = Counter(all_words)
        common_words = [word for word, count in word_counts.most_common(5) 
                      if count > 1 and word not in {'this', 'that', 'with', 'from', 'your'}]
        
        return common_words
    
    def _generate_insights(self, email_summaries: List[Dict[str, Any]]) -> List[str]:
        """Generate insights from email analysis"""
        insights = []
        
        total = len(email_summaries)
        if total == 0:
            return insights
        
        urgent_count = sum(1 for s in email_summaries if s['urgency'] > 0.7)
        if urgent_count > 0:
            insights.append(f"{urgent_count} emails require immediate attention")
        
        action_count = sum(len(s['action_items']) for s in email_summaries)
        if action_count > 0:
            insights.append(f"{action_count} action items across all emails")
        
        avg_sentiment = sum(s['sentiment'] for s in email_summaries) / total
        if avg_sentiment > 0.3:
            insights.append("Overall positive sentiment in communications")
        elif avg_sentiment < -0.3:
            insights.append("Overall negative sentiment - may need attention")
        
        return insights
