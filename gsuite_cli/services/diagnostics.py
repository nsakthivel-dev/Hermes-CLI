"""
Diagnostic service for verifying connections to Google Workspace and AI services
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from ..auth.oauth import OAuthManager
from .gmail import GmailService
from .calendar import CalendarService
from .sheets import SheetsService
from .meet import MeetService
from .forms import FormsService
from ..ai.gemini_client import GeminiClient
from ..utils.formatters import print_success, print_error, print_info, print_header, print_section

logger = logging.getLogger(__name__)

class DiagnosticsService:
    """Service for running diagnostic tests on GSuite connections"""
    
    def __init__(self, oauth_manager: OAuthManager, config_manager=None, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.config_manager = config_manager
        self.cache_manager = cache_manager

    def run_all_tests(self) -> Dict[str, bool]:
        """Run all connection tests"""
        results = {}
        
        print_header("🔍 GSuite Connection Diagnostics")
        
        # 1. AI Connection Test
        results['ai'] = self.test_ai()
        
        # 2. Gmail Connection Test
        results['gmail'] = self.test_gmail()
        
        # 3. Calendar Connection Test
        results['calendar'] = self.test_calendar()
        
        # 4. Sheets Connection Test
        results['sheets'] = self.test_sheets()
        
        # 5. Docs Connection Test
        results['docs'] = self.test_docs()
        
        results['meet'] = self.test_meet()
        results['forms'] = self.test_forms()
        
        print("\n" + "="*40)
        overall = all(results.values())
        if overall:
            print_success("✅ All connections are working perfectly!")
        else:
            print_error("❌ Some connection issues were detected.")
        
        return results

    def test_ai(self) -> bool:
        """Test Gemini AI connection"""
        print_section("🤖 Testing AI Connection")
        try:
            if not self.config_manager:
                print_error("Config manager not available")
                return False
                
            ai_config = self.config_manager.get('ai')
            if not ai_config or not ai_config.gemini_api_key:
                print_error("Gemini API key not configured")
                return False
            
            client = GeminiClient(
                api_key=ai_config.gemini_api_key,
                model_name=ai_config.model_name
            )
            
            response = client.generate_content("Respond with 'Connection OK' and nothing else.")
            if response and "Connection OK" in response:
                print_success(f"Gemini AI: Connection successful ({ai_config.model_name})")
                return True
            else:
                print_error(f"Gemini AI: Unexpected response: {response}")
                return False
        except Exception as e:
            print_error(f"Gemini AI: {str(e)}")
            return False

    def test_gmail(self) -> bool:
        """Test Gmail connection (list and send to self)"""
        print_section("📧 Testing Gmail Connection")
        try:
            service = GmailService(self.oauth_manager, self.cache_manager)
            
            # Test List
            messages = service.list_messages(max_results=1)
            print_success(f"Gmail List: Successfully retrieved messages")
            
            # Test Send/Draft
            print_info("Testing mail creation...")
            
            # Get user email to avoid validation issues with 'me'
            try:
                profile = service.service.users().getProfile(userId='me').execute()
                user_email = profile.get('emailAddress')
            except:
                user_email = 'me' # Fallback, but might fail validation

            success = service.send_message(
                to=user_email,
                subject='Hermes Connection Test',
                body=f'Connection test completed at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
            )
            if success:
                print_success(f"Gmail Send: Successfully sent test mail to {user_email}")
                return True
            else:
                print_error("Gmail Send: Failed to send test mail")
                return False
                
        except Exception as e:
            print_error(f"Gmail Failure: {str(e)}")
            return False

    def test_calendar(self) -> bool:
        """Test Calendar connection (list and create)"""
        print_section("📅 Testing Calendar Connection")
        try:
            service = CalendarService(self.oauth_manager, self.cache_manager)
            
            # Test List
            events = service.list_events(max_results=1)
            print_success(f"Calendar List: Successfully retrieved events")
            
            # Test Create
            print_info("Testing event creation...")
            start_time = datetime.now() + timedelta(days=7)
            end_time = start_time + timedelta(hours=1)
            
            event_id = service.create_event(
                summary="Hermes Connection Test Event",
                description="This is an automated connection test event.",
                start_time=start_time,
                end_time=end_time
            )
            
            if event_id:
                print_success(f"Calendar Create: Successfully created test event (ID: {event_id})")
                
                # Immediately delete the test event to stay clean
                service.delete_event(event_id)
                print_info("Cleaned up: Deleted test event")
                return True
            else:
                print_error("Calendar Create: Failed to create test event (returned None)")
                return False
                
        except Exception as e:
            print_error(f"Calendar Failure: {str(e)}")
            return False

    def test_sheets(self) -> bool:
        """Test Sheets connection"""
        print_section("📊 Testing Sheets Connection")
        try:
            service = SheetsService(self.oauth_manager, self.cache_manager)
            spreadsheets = service.list_spreadsheets()
            print_success(f"Sheets List: Successfully retrieved {len(spreadsheets)} spreadsheets")
            return True
        except Exception as e:
            print_error(f"Sheets Failure: {str(e)}")
            return False

    def test_docs(self) -> bool:
        """Test Docs connection (list and create)"""
        print_section("📄 Testing Docs Connection")
        try:
            from .docs import DocsService
            service = DocsService(self.oauth_manager, self.cache_manager)
            
            # Test List
            docs = service.list_documents(max_results=1)
            print_success(f"Docs List: Successfully retrieved documents")
            
            # Test Create
            print_info("Testing document creation...")
            title = f"Hermes Connection Test Doc - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            document_id = service.create_document(title, "This is an automated connection test document.")
            
            if document_id:
                print_success(f"Docs Create: Successfully created test document (ID: {document_id})")
                
                # Immediately delete the test document to stay clean
                service.delete_document(document_id)
                print_info("Cleaned up: Deleted test document")
                return True
            else:
                print_error("Docs Create: Failed to create test document (returned None)")
                return False
                
        except Exception as e:
            print_error(f"Docs Failure: {str(e)}")
            if "not enabled" in str(e).lower() or "not been used" in str(e).lower():
                print_info("💡 Tip: Ensure the 'Google Docs API' is enabled in your Google Cloud Console.")
            return False

    def test_meet(self) -> bool:
        """Test Meet connection (create and end)"""
        print_section("🎥 Testing Meet Connection")
        try:
            service = MeetService(self.oauth_manager, self.cache_manager)
            
            # Test Create (Instant Meeting)
            print_info("Testing meeting space creation...")
            
            # Simple instant meeting config
            space = service.create_space()
            
            if space:
                print_success(f"Meet Create: Successfully created meeting space")
                print_info(f"  Name: {space['name']}")
                print_info(f"  URL: {space['meeting_uri']}")
                
                # Immediately end the meeting to stay clean (though it just ends the active conference, not deletes space)
                # Spaces can't be deleted via API v2 yet, they expire automatically
                service.end_active_conference(space['name'])
                return True
            else:
                print_error("Meet Create: Failed to create meeting space (returned None)")
                return False
                
        except Exception as e:
            print_error(f"Meet Failure: {str(e)}")
            if "not enabled" in str(e).lower() or "not been used" in str(e).lower():
                print_info("💡 Tip: Ensure the 'Google Meet API' is enabled in your Google Cloud Console.")
            return False

    def test_forms(self) -> bool:
        print_section("📋 Testing Forms Connection")
        try:
            service = FormsService(self.oauth_manager, self.cache_manager)
            forms = service.list_forms(max_results=1)
            print_success(f"Forms List: Successfully retrieved {len(forms)} forms")
            return True
        except Exception as e:
            print_error(f"Forms Failure: {str(e)}")
            if "not enabled" in str(e).lower() or "has not been used" in str(e).lower():
                print_info("💡 Tip: Ensure the 'Google Forms API' is enabled in your Google Cloud Console.")
            return False
