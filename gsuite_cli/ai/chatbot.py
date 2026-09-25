"""
AI Chatbot service for GSuite CLI - Gemini Powered (v3)
"""

import logging
from typing import Optional
from google import genai

logger = logging.getLogger(__name__)

class AIChatBot:
    """Chatbot service powered by Google Gemini (New SDK)"""
    
    def __init__(self, gemini_key: str = '', model_name: str = 'gemini-3.6-flash'):
        self.gemini_key = gemini_key
        self.model_name = model_name
        self._client = None
    
    @property
    def client(self):
        """Lazy initialization of the Gemini client"""
        if self._client is None and self.gemini_key:
            self._client = genai.Client(api_key=self.gemini_key)
        return self._client
    
    def chat(self, message: str) -> str:
        """Send a message to Gemini and get a response using the new SDK"""
        if not self.gemini_key:
            return "❌ Gemini API key not configured. Set it with 'hermes config set ai.gemini_api_key YOUR_KEY'"
        
        try:
            if not self.client:
                return "❌ Failed to initialize Gemini client."
                
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=message
            )
            
            if response and response.text:
                return response.text
            return "❌ No response from Gemini"
            
        except Exception as e:
            logger.error(f"Gemini SDK error: {e}")
            # If the specific v3 preview model isn't available, try a fallback if it makes sense, 
            # but usually for a preview user, we want to show the specific error.
            return f"❌ Gemini AI Error: {str(e)}"
