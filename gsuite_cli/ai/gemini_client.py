"""
Gemini AI Client wrapper
"""

from google import genai
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)

class GeminiClient:
    """Wrapper for Google Gemini API using modern SDK"""
    
    def __init__(self, api_key: str, model_name: str = 'gemini-3.6-flash', temperature: float = 0.7, max_output_tokens: int = 2048):
        self.is_available = False
        self.api_key = api_key
        self.model_name = model_name
        
        if not api_key:
            logger.warning("Gemini API key not provided. AI features will be disabled.")
            self.client = None
            return

        try:
            self.client = genai.Client(api_key=api_key)
            self.config = {
                'temperature': temperature,
                'max_output_tokens': max_output_tokens,
            }
            self.is_available = True
            logger.info(f"Initialized Gemini client with model: {model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client: {e}")
            self.client = None

    def generate_content(self, prompt: str) -> Optional[str]:
        """Generate content from a prompt"""
        if not self.is_available or not self.client:
            logger.warning("Gemini client not initialized or unavailable")
            return None
        
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=self.config
            )
            return response.text
        except Exception as e:
            logger.error(f"Error generating content: {e}")
            return None

    def get_chat_session(self, history: List[Dict[str, Any]] = None):
        """Start a chat session"""
        if not self.is_available or not self.client:
            return None
        # In the new SDK, chat is managed via sessions
        return self.client.chats.create(
            model=self.model_name,
            history=[{'role': h['role'], 'parts': [{'text': h['parts'][0]['text']}]} for h in (history or [])],
            config=self.config
        )
