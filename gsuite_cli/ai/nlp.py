"""
Natural Language Processing for AI commands
"""

import re
import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
import json

from .gemini_client import GeminiClient

logger = logging.getLogger(__name__)


class NaturalLanguageProcessor:
    """AI-powered natural language command processor"""
    
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
        
        self.intent_patterns = {
            'calendar_search': [
                r'(?i)(show|find|search|list).*calendar',
                r'(?i)(meetings?|events?|appointments?)',
                r'(?i)what.*(?:do|have|scheduled)',
                r'(?i)(today|tomorrow|this week|next week)',
            ],
            'email_search': [
                r'(?i)(show|find|search|list).*email',
                r'(?i)(emails?|messages?|inbox)',
                r'(?i)(unread|important|urgent)',
                r'(?i)from (.+)',
                r'(?i)subject (.+)',
            ],
            'email_send': [
                r'(?i)(send|write|compose).*email',
                r'(?i)email (.+)',
                r'(?i)(tell|message) (.+)',
            ],
            'calendar_create': [
                r'(?i)(create|schedule|set up|book).*meeting',
                r'(?i)(add|make).*appointment',
                r'(?i)(schedule|book).*call',
            ],
            'analytics': [
                r'(?i)(analytics|insights|summary|report)',
                r'(?i)(how many|how much|statistics)',
                r'(?i)(productivity|performance)',
            ],
            'summarize': [
                r'(?i)(summarize|summary|recap)',
                r'(?i)(what happened|catch me up)',
                r'(?i)(brief|overview)',
            ],
            'docs_search': [
                r'(?i)(find|search|look for).*document',
                r'(?i)(docs?|documents?|files?)',
                r'(?i)open.*document',
            ],
            'docs_create': [
                r'(?i)(create|make|write).*document',
                r'(?i)(new|start).*document',
                r'(?i)document.*about',
            ]
        }
        
        self.time_patterns = {
            'today': lambda: datetime.now().date(),
            'tomorrow': lambda: datetime.now().date() + timedelta(days=1),
            'yesterday': lambda: datetime.now().date() - timedelta(days=1),
            'this week': lambda: self._get_week_start(),
            'next week': lambda: self._get_week_start() + timedelta(days=7),
            'last week': lambda: self._get_week_start() - timedelta(days=7),
        }
    
    def _get_week_start(self) -> datetime.date:
        """Get start of current week (Monday)"""
        today = datetime.now().date()
        return today - timedelta(days=today.weekday())
    
    def parse_command(self, query: str) -> Dict[str, Any]:
        """
        Parse natural language command into structured intent
        
        Args:
            query: Natural language query
            
        Returns:
            Dict with intent, entities, and parameters
        """
        query = query.strip()
        
        # Try Gemini first if available
        if self.gemini_client and self.gemini_client.is_available:
            try:
                result = self._parse_with_gemini(query)
                if result:
                    result['original_query'] = query
                    return result
            except Exception as e:
                logger.error(f"Gemini parsing failed, falling back to regex: {e}")
        
        # Fallback to regex
        # Detect intent
        intent = self._detect_intent(query)
        
        # Extract entities
        entities = self._extract_entities(query)
        
        # Generate parameters
        params = self._generate_parameters(intent, entities, query)
        
        return {
            'intent': intent,
            'entities': entities,
            'params': params,
            'original_query': query,
            'confidence': self._calculate_confidence(intent, entities)
        }

    def _parse_with_gemini(self, query: str) -> Optional[Dict[str, Any]]:
        """Parse command using Gemini AI"""
        prompt = f'''
        Analyze the following command for a GSuite CLI tool.
        Command: "{query}"
        
        Available intents:
        - calendar_search (finding events)
        - email_search (finding emails)
        - email_send (sending emails)
        - calendar_create (creating events)
        - analytics (productivity stats)
        - summarize (summarizing content)
        - docs_search (finding docs)
        - docs_create (creating docs)
        
        Current date: {datetime.now().strftime('%Y-%m-%d')}
        
        Return ONLY a JSON object with:
        - intent: one of the above or 'unknown'
        - entities: dict of extracted entities
        - params: dict of parameters derived from entities (e.g. for calendar_search: time_min, time_max, query; for email_send: to, subject, body)
        - confidence: float between 0 and 1
        '''
        
        response = self.gemini_client.generate_content(prompt)
        if not response:
            return None
            
        try:
            # Clean up response to ensure it's valid JSON
            text = response.replace('```json', '').replace('```', '').strip()
            start_idx = text.find('{')
            end_idx = text.rfind('}') + 1
            if start_idx != -1 and end_idx != -1:
                return json.loads(text[start_idx:end_idx])
        except Exception as e:
            logger.error(f"Error parsing Gemini response: {e}")
            return None
        return None

    def draft_email(
        self,
        prompt: str,
        profile_context: Optional[Dict[str, Any]] = None,
        email_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Draft an email based on a natural language prompt and optional approved profile context.
        
        Args:
            prompt: User-provided drafting instructions
            profile_context: Approved profile information (name, job_title, etc.)
            email_context: Context metadata (intent, recipient, etc.)
            
        Returns:
            Dict with subject and body, or None
        """
        if not self.gemini_client or not self.gemini_client.is_available:
            return None

        profile_section = ""
        if profile_context:
            profile_lines = []
            for k, v in profile_context.items():
                if v:
                    clean_k = k.replace('_', ' ').title()
                    profile_lines.append(f"- {clean_k}: {v}")
            if profile_lines:
                profile_section = (
                    "Approved Profile Information (Use this information naturally where appropriate):\n"
                    + "\n".join(profile_lines)
                )

        context_section = ""
        if email_context:
            ctx_lines = []
            for k, v in email_context.items():
                if v:
                    clean_k = k.replace('_', ' ').title()
                    ctx_lines.append(f"- {clean_k}: {v}")
            if ctx_lines:
                context_section = "Email Context:\n" + "\n".join(ctx_lines)

        full_prompt = f'''
Draft a formal or appropriate email based on the following instructions:
"{prompt}"

{context_section}

{profile_section}

CRITICAL RULES:
1. Use the provided Approved Profile Information naturally (e.g., in the body or signature).
2. DO NOT create or use bracketed placeholders such as [Your Name], [Your Phone Number], [Your Job Title], [Your Employee ID], [Manager's Name], [Company Name], [Start Date], [End Date], [Number], etc.
3. If an optional detail (such as employee ID, phone number, manager name, or specific leave dates) is not provided in the Approved Profile Information or the User Instructions, DO NOT invent fake data and DO NOT create placeholders. Simply adapt the phrasing to flow naturally without that detail or omit it entirely.
4. If personal information was NOT provided in the Approved Profile Information, do not invent or hallucinate it.
5. User instructions in the request always take priority over profile defaults.
6. Return ONLY a JSON object with:
- subject: a professional subject line
- body: the complete email message body
'''
        
        response = self.gemini_client.generate_content(full_prompt)
        if not response:
            return None
            
        try:
            text = response.replace('```json', '').replace('```', '').strip()
            start_idx = text.find('{')
            end_idx = text.rfind('}') + 1
            if start_idx != -1 and end_idx != -1:
                raw_draft = json.loads(text[start_idx:end_idx])
                return self._sanitize_draft(raw_draft, profile_context)
        except Exception as e:
            logger.error(f"Error parsing Gemini draft response: {e}")
            return None
        return None

    def _sanitize_draft(self, draft: Dict[str, Any], profile_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Ensure no unreplaced placeholders remain in the subject or body.
        If a placeholder matches available profile info, replace it.
        If missing, clean up or omit the placeholder.
        """
        if not draft:
            return draft

        subject = draft.get('subject', '')
        body = draft.get('body', '')
        profile = profile_context or {}

        # Replacements map for known placeholders
        substitutions = {
            r'\[(?:Your\s+)?Name\]': profile.get('name'),
            r'\[(?:Your\s+)?Full\s*Name\]': profile.get('name'),
            r'\[(?:Your\s+)?Job\s*Title\]': profile.get('job_title'),
            r'\[(?:Your\s+)?Title\]': profile.get('job_title'),
            r'\[(?:Your\s+)?Role\]': profile.get('job_title'),
            r'\[(?:Your\s+)?Phone(?:\s*Number)?\]': profile.get('phone'),
            r'\[(?:Your\s+)?Employee\s*ID\]': profile.get('employee_id'),
            r'\[(?:Your\s+)?Emp\s*ID\]': profile.get('employee_id'),
            r'\[(?:Your\s+)?Manager(?:\'s)?\s*Name\]': profile.get('manager_name'),
            r'\[(?:Your\s+)?Manager\]': profile.get('manager_name'),
            r'\[(?:Your\s+)?Company(?:\s*Name)?\]': profile.get('company'),
            r'\[(?:Your\s+)?College(?:\s*Name)?\]': profile.get('college'),
            r'\[(?:Your\s+)?University(?:\s*Name)?\]': profile.get('college'),
            r'\[(?:Your\s+)?Department\]': profile.get('department'),
            r'\[(?:Your\s+)?Student\s*ID\]': profile.get('student_id'),
            r'\[(?:Your\s+)?Roll\s*No(?:\.)?\]': profile.get('student_id'),
            r'\[(?:Your\s+)?Degree\]': profile.get('degree'),
            r'\[(?:Your\s+)?Skills\]': profile.get('skills'),
            r'\[(?:Your\s+)?Email(?:\s*Address)?\]': profile.get('email'),
        }

        for pattern, val in substitutions.items():
            if val:
                subject = re.sub(pattern, str(val), subject, flags=re.IGNORECASE)
                body = re.sub(pattern, str(val), body, flags=re.IGNORECASE)

        # For any lines that just consist of a missing placeholder (e.g. signature lines)
        cleaned_lines = []
        for line in body.split('\n'):
            stripped = line.strip()
            if re.fullmatch(r'\[[A-Za-z\s\'_-]+\]', stripped):
                continue
            cleaned_lines.append(line)
        body = '\n'.join(cleaned_lines)

        # For remaining placeholders in text, clean up or strip
        body = re.sub(r'via\s+phone\s+at\s+\[.*?\]\.', '', body, flags=re.IGNORECASE)
        body = re.sub(r'at\s+\[.*?\]\.', '.', body, flags=re.IGNORECASE)
        body = re.sub(r'\[(?:Your\s+)?[A-Za-z\s\'_-]+\]', '', body)
        subject = re.sub(r'\s*-\s*\[(?:Your\s+)?[A-Za-z\s\'_-]+\]', '', subject)
        subject = re.sub(r'\[(?:Your\s+)?[A-Za-z\s\'_-]+\]', '', subject)

        # Clean up double spaces or trailing punctuation artifacts
        body = re.sub(r'[ \t]+', ' ', body)
        body = re.sub(r'\n{3,}', '\n\n', body).strip()
        subject = re.sub(r'[ \t]+', ' ', subject).strip()

        draft['subject'] = subject
        draft['body'] = body
        return draft
    
    def _detect_intent(self, query: str) -> str:
        """Detect the primary intent from the query"""
        for intent, patterns in self.intent_patterns.items():
            for pattern in patterns:
                if re.search(pattern, query):
                    return intent
        return 'unknown'
    
    def _extract_entities(self, query: str) -> Dict[str, Any]:
        """Extract entities like dates, people, keywords"""
        entities = {}
        
        # Time/date entities
        for time_phrase, time_func in self.time_patterns.items():
            if time_phrase in query.lower():
                entities['time'] = {
                    'type': 'date',
                    'value': time_func(),
                    'phrase': time_phrase
                }
                break
        
        # Email entities
        email_pattern = r'(\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b)'
        emails = re.findall(email_pattern, query)
        if emails:
            entities['emails'] = emails
        
        # Person names (simple pattern)
        person_pattern = r'\b([A-Z][a-z]+ [A-Z][a-z]+)\b'
        people = re.findall(person_pattern, query)
        if people:
            entities['people'] = people
        
        # Keywords
        keywords = self._extract_keywords(query)
        if keywords:
            entities['keywords'] = keywords
        
        return entities
    
    def _extract_keywords(self, query: str) -> List[str]:
        """Extract important keywords from query"""
        # Remove common words and extract remaining words
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'have',
            'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should',
            'show', 'find', 'search', 'list', 'get', 'tell', 'me', 'what', 'when',
            'where', 'who', 'why', 'how', 'my', 'your', 'our', 'their'
        }
        
        words = re.findall(r'\b\w+\b', query.lower())
        keywords = [word for word in words if word not in stop_words and len(word) > 2]
        
        return keywords[:10]  # Limit to top 10 keywords
    
    def _generate_parameters(self, intent: str, entities: Dict[str, Any], query: str) -> Dict[str, Any]:
        """Generate specific parameters based on intent and entities"""
        params = {}
        
        if intent == 'calendar_search':
            params.update(self._calendar_search_params(entities, query))
        elif intent == 'email_search':
            params.update(self._email_search_params(entities, query))
        elif intent == 'email_send':
            params.update(self._email_send_params(entities, query))
        elif intent == 'calendar_create':
            params.update(self._calendar_create_params(entities, query))
        elif intent == 'analytics':
            params.update(self._analytics_params(entities, query))
        elif intent == 'summarize':
            params.update(self._summarize_params(entities, query))
        
        return params
    
    def _calendar_search_params(self, entities: Dict[str, Any], query: str) -> Dict[str, Any]:
        """Generate calendar search parameters"""
        params = {}
        
        if 'time' in entities:
            time_entity = entities['time']
            if time_entity['type'] == 'date':
                params['time_min'] = time_entity['value']
                if time_entity['phrase'] == 'today':
                    params['time_max'] = time_entity['value'] + timedelta(days=1)
                elif time_entity['phrase'] == 'tomorrow':
                    params['time_max'] = time_entity['value'] + timedelta(days=1)
        
        if 'keywords' in entities:
            params['query'] = ' '.join(entities['keywords'])
        
        return params
    
    def _email_search_params(self, entities: Dict[str, Any], query: str) -> Dict[str, Any]:
        """Generate email search parameters"""
        params = {}
        
        # Check for specific search patterns
        if 'unread' in query.lower():
            params['query'] = 'is:unread'
        elif 'urgent' in query.lower() or 'important' in query.lower():
            params['query'] = 'is:important OR urgent'
        elif 'from' in query.lower():
            from_match = re.search(r'from\s+(.+?)(?:\s|$)', query, re.IGNORECASE)
            if from_match:
                params['query'] = f'from:{from_match.group(1)}'
        elif 'subject' in query.lower():
            subject_match = re.search(r'subject\s+(.+?)(?:\s|$)', query, re.IGNORECASE)
            if subject_match:
                params['query'] = f'subject:{subject_match.group(1)}'
        elif 'keywords' in entities:
            params['query'] = ' '.join(entities['keywords'])
        
        return params
    
    def _email_send_params(self, entities: Dict[str, Any], query: str) -> Dict[str, Any]:
        """Generate email send parameters"""
        params = {}
        
        if 'emails' in entities:
            params['to'] = entities['emails'][0]
        
        # Extract message content
        message_match = re.search(r'(?:email|tell|message)\s+(.+?)\s+(?:that|saying)', query, re.IGNORECASE)
        if message_match:
            params['body'] = message_match.group(1)
        
        # Extract subject
        subject_match = re.search(r'subject\s+(.+?)(?:\s|$)', query, re.IGNORECASE)
        if subject_match:
            params['subject'] = subject_match.group(1)
        
        return params
    
    def _calendar_create_params(self, entities: Dict[str, Any], query: str) -> Dict[str, Any]:
        """Generate calendar create parameters"""
        params = {}
        
        # Extract title
        title_match = re.search(r'(?:meeting|appointment|call)\s+(?:with\s+)?(.+?)(?:\s+(?:at|on|for|tomorrow|today)|$)', query, re.IGNORECASE)
        if title_match:
            params['title'] = title_match.group(1).strip()
        
        # Extract time
        time_match = re.search(r'(?:at|on)\s+(\d{1,2}:\d{2}\s*(?:am|pm)?)', query, re.IGNORECASE)
        if time_match:
            time_str = time_match.group(1)
            try:
                time_obj = datetime.strptime(time_str, '%I:%M %p').time()
                today = datetime.now().date()
                params['start_time'] = datetime.combine(today, time_obj)
                params['end_time'] = params['start_time'] + timedelta(hours=1)
            except ValueError:
                pass
        
        return params
    
    def _analytics_params(self, entities: Dict[str, Any], query: str) -> Dict[str, Any]:
        """Generate analytics parameters"""
        params = {}
        
        if 'productivity' in query.lower():
            params['type'] = 'productivity'
        elif 'email' in query.lower():
            params['type'] = 'email'
        elif 'calendar' in query.lower():
            params['type'] = 'calendar'
        else:
            params['type'] = 'overview'
        
        return params
    
    def _summarize_params(self, entities: Dict[str, Any], query: str) -> Dict[str, Any]:
        """Generate summary parameters"""
        params = {}
        
        if 'today' in query.lower():
            params['period'] = 'today'
        elif 'week' in query.lower():
            params['period'] = 'week'
        else:
            params['period'] = 'recent'
        
        return params
    
    def _calculate_confidence(self, intent: str, entities: Dict[str, Any]) -> float:
        """Calculate confidence score for the parsing"""
        base_confidence = 0.5 if intent != 'unknown' else 0.2
        
        # Boost confidence based on entities found
        entity_boost = len(entities) * 0.1
        
        # Boost confidence for specific intents
        if intent in ['calendar_search', 'email_search']:
            base_confidence += 0.2
        
        confidence = min(base_confidence + entity_boost, 1.0)
        return round(confidence, 2)
    
    def suggest_command(self, query: str) -> str:
        """Suggest the actual CLI command based on natural language"""
        parsed = self.parse_command(query)
        
        if parsed['intent'] == 'calendar_search':
            return self._suggest_calendar_command(parsed)
        elif parsed['intent'] == 'email_search':
            return self._suggest_email_command(parsed)
        elif parsed['intent'] == 'email_send':
            return self._suggest_email_send_command(parsed)
        elif parsed['intent'] == 'calendar_create':
            return self._suggest_calendar_create_command(parsed)
        elif parsed['intent'] == 'analytics':
            return self._suggest_analytics_command(parsed)
        elif parsed['intent'] == 'summarize':
            return self._suggest_summary_command(parsed)
        elif parsed['intent'] == 'docs_search':
            return self._suggest_docs_search_command(parsed)
        elif parsed['intent'] == 'docs_create':
            return self._suggest_docs_create_command(parsed)
        else:
            return f"# Could not understand: {query}"
    
    def _suggest_calendar_command(self, parsed: Dict[str, Any]) -> str:
        """Suggest calendar command"""
        cmd_parts = ['hermes', 'calendar', 'list']
        
        params = parsed['params']
        if 'query' in params:
            cmd_parts.extend(['--search', f'"{params["query"]}"'])
        
        return ' '.join(cmd_parts)
    
    def _suggest_email_command(self, parsed: Dict[str, Any]) -> str:
        """Suggest email command"""
        cmd_parts = ['hermes', 'gmail', 'list']
        
        params = parsed['params']
        if 'query' in params:
            cmd_parts.extend(['--query', f'"{params["query"]}"'])
        
        return ' '.join(cmd_parts)
    
    def _suggest_email_send_command(self, parsed: Dict[str, Any]) -> str:
        """Suggest email send command"""
        cmd_parts = ['hermes', 'gmail', 'send']
        
        params = parsed['params']
        if 'to' in params:
            cmd_parts.extend(['--to', params['to']])
        if 'subject' in params:
            cmd_parts.extend(['--subject', f'"{params["subject"]}"'])
        if 'body' in params:
            cmd_parts.extend(['--body', f'"{params["body"]}"'])
        
        return ' '.join(cmd_parts)
    
    def _suggest_calendar_create_command(self, parsed: Dict[str, Any]) -> str:
        """Suggest calendar create command"""
        cmd_parts = ['hermes', 'calendar', 'create']
        
        params = parsed['params']
        if 'title' in params:
            cmd_parts.extend(['--title', f'"{params["title"]}"'])
        if 'start_time' in params:
            cmd_parts.extend(['--start', params['start_time'].strftime('%Y-%m-%d %H:%M')])
        if 'end_time' in params:
            cmd_parts.extend(['--end', params['end_time'].strftime('%Y-%m-%d %H:%M')])
        
        return ' '.join(cmd_parts)
    
    def _suggest_analytics_command(self, parsed: Dict[str, Any]) -> str:
        """Suggest analytics command"""
        cmd_parts = ['hermes', 'ai', 'analytics']
        
        params = parsed['params']
        if 'type' in params:
            cmd_parts.append(params['type'])
        
        return ' '.join(cmd_parts)
    
    def _suggest_summary_command(self, parsed: Dict[str, Any]) -> str:
        """Suggest summary command"""
        cmd_parts = ['hermes', 'ai', 'summarize']
        
        params = parsed['params']
        if 'period' in params:
            cmd_parts.append(params['period'])
        
        return ' '.join(cmd_parts)
    
    def _suggest_docs_search_command(self, parsed: Dict[str, Any]) -> str:
        """Suggest docs search command"""
        cmd_parts = ['hermes', 'docs', 'search']
        
        params = parsed['params']
        if 'keywords' in params:
            cmd_parts.append(' '.join(params['keywords']))
        
        return ' '.join(cmd_parts)
    
    def _suggest_docs_create_command(self, parsed: Dict[str, Any]) -> str:
        """Suggest docs create command"""
        cmd_parts = ['hermes', 'docs', 'create']
        
        params = parsed['params']
        if 'keywords' in params:
            cmd_parts.append('"'.join(params['keywords']))
        
        return ' '.join(cmd_parts)
