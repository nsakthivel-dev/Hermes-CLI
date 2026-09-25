"""
Google Meet service integration
"""

import logging
import re
import webbrowser
from typing import List, Dict, Any, Optional

from googleapiclient.errors import HttpError

from ..auth.oauth import OAuthManager
from ..utils.formatters import print_error, print_info, print_success

logger = logging.getLogger(__name__)


class MeetService:
    """Google Meet API service wrapper"""
    
    def __init__(self, oauth_manager: OAuthManager, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.cache_manager = cache_manager
        self.service = None
        self._initialize_service()
    
    def _initialize_service(self) -> bool:
        """Initialize the Meet service"""
        try:
            self.service = self.oauth_manager.build_service('meet', 'v2')
            return self.service is not None
        except Exception as e:
            logger.error(f"Failed to initialize Meet service: {e}")
            return False

    # =========================================================================
    # Helpers & URL / Code Normalization
    # =========================================================================

    @staticmethod
    def extract_meeting_code(input_str: str) -> str:
        """
        Extract a clean meeting code from URL, space name, or raw meeting code.
        
        Examples:
            'https://meet.google.com/abc-defg-hij' -> 'abc-defg-hij'
            'meet.google.com/abc-defg-hij' -> 'abc-defg-hij'
            'spaces/abc-defg-hij' -> 'abc-defg-hij'
            'abc-defg-hij' -> 'abc-defg-hij'
        """
        if not input_str:
            return ''
        
        cleaned = input_str.strip()
        # Remove query parameters or trailing slashes
        if '?' in cleaned:
            cleaned = cleaned.split('?')[0]
        cleaned = cleaned.rstrip('/')
        
        # Regex for standard Google Meet format (3-4-3 letters)
        match = re.search(r'([a-z]{3}-[a-z]{4}-[a-z]{3})', cleaned, re.IGNORECASE)
        if match:
            return match.group(1).lower()
        
        # If URL, get last component
        if '/' in cleaned:
            parts = [p for p in cleaned.split('/') if p]
            if parts:
                return parts[-1]
        
        return cleaned

    @staticmethod
    def get_meeting_url(code_or_url: str) -> str:
        """
        Ensure a valid Google Meet URL is returned from code or URL.
        """
        if not code_or_url:
            return ''
        code_or_url = code_or_url.strip()
        if code_or_url.startswith('http://') or code_or_url.startswith('https://'):
            return code_or_url
        
        code = MeetService.extract_meeting_code(code_or_url)
        return f"https://meet.google.com/{code}"

    def join_meeting(self, code_or_url: str) -> Dict[str, Any]:
        """
        Launch default web browser to join a meeting.
        
        Returns:
            Dict with success flag and meeting URL
        """
        url = self.get_meeting_url(code_or_url)
        if not url or url == "https://meet.google.com/":
            return {'success': False, 'error': 'Invalid meeting code or URL', 'url': ''}
        
        try:
            opened = webbrowser.open(url)
            logger.info(f"Opening meeting in browser: {url}")
            return {'success': opened, 'url': url}
        except Exception as e:
            logger.error(f"Failed to open meeting in browser: {e}")
            return {'success': False, 'error': str(e), 'url': url}

    def test_connection(self) -> Dict[str, Any]:
        """
        Verify Google Meet API connectivity and authentication status.
        """
        if not self.service:
            initialized = self._initialize_service()
            if not initialized:
                return {
                    'connected': False,
                    'authenticated': False,
                    'error': 'Failed to initialize Google Meet API client'
                }
        
        auth_info = self.oauth_manager.get_auth_info()
        try:
            # Check connection with a minimal conference records list request
            self.service.conferenceRecords().list(pageSize=1).execute()
            return {
                'connected': True,
                'authenticated': auth_info.get('authenticated', False),
                'scopes': auth_info.get('scopes', []),
                'token_expiry': auth_info.get('token_expiry'),
                'api_version': 'v2'
            }
        except HttpError as e:
            logger.error(f"Meet API connection check returned HttpError: {e}")
            return {
                'connected': False,
                'authenticated': auth_info.get('authenticated', False),
                'error': f"HTTP {e.resp.status}: {e.reason}"
            }
        except Exception as e:
            logger.error(f"Meet API connection check failed: {e}")
            return {
                'connected': False,
                'authenticated': auth_info.get('authenticated', False),
                'error': str(e)
            }

    # =========================================================================
    # Meeting Spaces
    # =========================================================================

    def create_space(self, config: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Create a new meeting space.
        
        Args:
            config: Optional space configuration dict (e.g. {'accessType': 'RESTRICTED' | 'OPEN' | 'TRUSTED'})
            
        Returns:
            Dict with space info including meeting URL, code, and name, or None on failure
        """
        if not self.service:
            if not self._initialize_service():
                return None
        
        try:
            body: Dict[str, Any] = {}
            if config:
                body['config'] = config
            
            space = self.service.spaces().create(body=body).execute()
            
            formatted_space = {
                'name': space.get('name', ''),
                'meeting_uri': space.get('meetingUri', ''),
                'meeting_code': space.get('meetingCode', ''),
                'config': space.get('config', {}),
                'active_conference': space.get('activeConference', {}),
            }
            
            logger.info(f"Created meeting space: {formatted_space['name']}")
            return formatted_space
        except HttpError as e:
            message = str(e)
            if "updateAccessType is not available to the user" in message or "accessType" in message:
                logger.warning("Meet accessType configuration not available, retrying without config")
                print_info("Selected meeting visibility is not available for this account. Using default meeting settings.")
                try:
                    space = self.service.spaces().create(body={}).execute()
                    
                    formatted_space = {
                        'name': space.get('name', ''),
                        'meeting_uri': space.get('meetingUri', ''),
                        'meeting_code': space.get('meetingCode', ''),
                        'config': space.get('config', {}),
                        'active_conference': space.get('activeConference', {}),
                    }
                    
                    logger.info(f"Created meeting space without custom config: {formatted_space['name']}")
                    return formatted_space
                except HttpError as e2:
                    logger.error(f"Failed to create meeting space without config: {e2}")
                    print_error(f"Failed to create meeting space: {e2}")
                    return None
            else:
                logger.error(f"Failed to create meeting space: {e}")
                print_error(f"Failed to create meeting space: {e}")
                return None

    def get_space(self, space_name: str) -> Optional[Dict[str, Any]]:
        """
        Get details of a specific meeting space.
        
        Args:
            space_name: Resource name (e.g. 'spaces/abc123' or 'abc123' or meeting code)
            
        Returns:
            Dict with space details or None on failure
        """
        if not self.service:
            if not self._initialize_service():
                return None
        
        try:
            name = space_name.strip()
            if not name.startswith('spaces/'):
                name = f'spaces/{name}'
            
            space = self.service.spaces().get(name=name).execute()
            
            formatted_space = {
                'name': space.get('name', ''),
                'meeting_uri': space.get('meetingUri', ''),
                'meeting_code': space.get('meetingCode', ''),
                'config': space.get('config', {}),
                'active_conference': space.get('activeConference', {}),
            }
            
            return formatted_space
        except HttpError as e:
            logger.error(f"Failed to get meeting space {space_name}: {e}")
            print_error(f"Failed to get meeting space: {e}")
            return None

    def update_space(self, space_name: str, config: Dict[str, Any], 
                     update_mask: str = "config.accessType") -> Optional[Dict[str, Any]]:
        """
        Update configuration of an existing meeting space.
        
        Args:
            space_name: Resource name ('spaces/...')
            config: New configuration dict (e.g. {'accessType': 'OPEN'})
            update_mask: Field mask to update (e.g. 'config.accessType')
        """
        if not self.service:
            if not self._initialize_service():
                return None
        
        try:
            name = space_name.strip()
            if not name.startswith('spaces/'):
                name = f'spaces/{name}'
            
            body = {'config': config}
            space = self.service.spaces().patch(
                name=name,
                updateMask=update_mask,
                body=body
            ).execute()
            
            return {
                'name': space.get('name', ''),
                'meeting_uri': space.get('meetingUri', ''),
                'meeting_code': space.get('meetingCode', ''),
                'config': space.get('config', {}),
                'active_conference': space.get('activeConference', {}),
            }
        except HttpError as e:
            logger.error(f"Failed to update meeting space {space_name}: {e}")
            print_error(f"Failed to update meeting space: {e}")
            return None

    def end_active_conference(self, space_name: str) -> bool:
        """
        End the active conference in a space.
        
        Args:
            space_name: The resource name of the space (e.g., 'spaces/abc123')
            
        Returns:
            True if successful, False otherwise
        """
        if not self.service:
            if not self._initialize_service():
                return False
        
        try:
            name = space_name.strip()
            if not name.startswith('spaces/'):
                name = f'spaces/{name}'
            
            self.service.spaces().endActiveConference(
                name=name,
                body={}
            ).execute()
            
            logger.info(f"Ended active conference in space: {name}")
            return True
        except HttpError as e:
            logger.error(f"Failed to end active conference in {space_name}: {e}")
            print_error(f"Failed to end active conference: {e}")
            return False

    # =========================================================================
    # Conference Records & History
    # =========================================================================

    def list_conference_records(self, max_results: int = 25, 
                                 filter_str: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List conference records (past/current meetings) with pagination handling.
        
        Args:
            max_results: Maximum records to return
            filter_str: Optional filter string
            
        Returns:
            List of conference record dicts
        """
        if not self.service:
            if not self._initialize_service():
                return []
        
        try:
            formatted_records: List[Dict[str, Any]] = []
            page_token = None
            
            while len(formatted_records) < max_results:
                page_size = min(max_results - len(formatted_records), 100)
                params: Dict[str, Any] = {'pageSize': page_size}
                if filter_str:
                    params['filter'] = filter_str
                if page_token:
                    params['pageToken'] = page_token
                
                result = self.service.conferenceRecords().list(**params).execute()
                records = result.get('conferenceRecords', [])
                if not isinstance(records, list) or not records:
                    break
                
                for record in records:
                    formatted_records.append({
                        'name': record.get('name', ''),
                        'start_time': record.get('startTime', ''),
                        'end_time': record.get('endTime', ''),
                        'expire_time': record.get('expireTime', ''),
                        'space': record.get('space', ''),
                    })
                    if len(formatted_records) >= max_results:
                        break
                
                token = result.get('nextPageToken')
                if isinstance(token, str) and token:
                    page_token = token
                else:
                    break
            
            return formatted_records
        except HttpError as e:
            logger.error(f"Failed to list conference records: {e}")
            print_error(f"Failed to list conference records: {e}")
            return []

    def get_conference_record(self, record_name: str) -> Optional[Dict[str, Any]]:
        """
        Get details of a specific conference record.
        """
        if not self.service:
            if not self._initialize_service():
                return None
        
        try:
            name = record_name.strip()
            if not name.startswith('conferenceRecords/'):
                name = f'conferenceRecords/{name}'
            
            record = self.service.conferenceRecords().get(name=name).execute()
            
            return {
                'name': record.get('name', ''),
                'start_time': record.get('startTime', ''),
                'end_time': record.get('endTime', ''),
                'expire_time': record.get('expireTime', ''),
                'space': record.get('space', ''),
            }
        except HttpError as e:
            logger.error(f"Failed to get conference record {record_name}: {e}")
            print_error(f"Failed to get conference record: {e}")
            return None

    def get_active_conferences(self, max_results: int = 25) -> List[Dict[str, Any]]:
        """
        Get currently ongoing/active conferences (no end time recorded yet).
        """
        records = self.list_conference_records(max_results=max_results)
        active = []
        for r in records:
            if not r.get('end_time'):
                active.append(r)
        return active

    def get_recent_conferences(self, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        Convenience method to retrieve most recent conferences.
        """
        return self.list_conference_records(max_results=max_results)

    # =========================================================================
    # Participants
    # =========================================================================

    def list_participants(self, conference_record_name: str, 
                          max_results: int = 50) -> List[Dict[str, Any]]:
        """
        List participants for a given conference record.
        
        Args:
            conference_record_name: Resource name ('conferenceRecords/abc')
            max_results: Maximum participants to return
        """
        if not self.service:
            if not self._initialize_service():
                return []
        
        try:
            parent = conference_record_name.strip()
            if not parent.startswith('conferenceRecords/'):
                parent = f'conferenceRecords/{parent}'
            
            participants: List[Dict[str, Any]] = []
            page_token = None
            
            while len(participants) < max_results:
                page_size = min(max_results - len(participants), 100)
                params: Dict[str, Any] = {'parent': parent, 'pageSize': page_size}
                if page_token:
                    params['pageToken'] = page_token
                
                result = self.service.conferenceRecords().participants().list(**params).execute()
                items = result.get('participants', [])
                if not isinstance(items, list) or not items:
                    break
                
                for item in items:
                    display_name = 'Unknown'
                    user_id = ''
                    if 'signedinUser' in item:
                        display_name = item['signedinUser'].get('displayName') or item['signedinUser'].get('user', 'User')
                        user_id = item['signedinUser'].get('user', '')
                    elif 'anonymousUser' in item:
                        display_name = item['anonymousUser'].get('displayName', 'Anonymous')
                    elif 'phoneUser' in item:
                        display_name = item['phoneUser'].get('displayName', 'Phone Call-In')
                    
                    participants.append({
                        'name': item.get('name', ''),
                        'display_name': display_name,
                        'user_id': user_id,
                        'earliest_start_time': item.get('earliestStartTime', ''),
                        'latest_end_time': item.get('latestEndTime', ''),
                    })
                    if len(participants) >= max_results:
                        break
                
                token = result.get('nextPageToken')
                if isinstance(token, str) and token:
                    page_token = token
                else:
                    break
            
            return participants
        except HttpError as e:
            logger.error(f"Failed to list participants for {conference_record_name}: {e}")
            print_error(f"Failed to list participants: {e}")
            return []

    def get_participant(self, participant_name: str) -> Optional[Dict[str, Any]]:
        """
        Get details for a specific participant.
        """
        if not self.service:
            if not self._initialize_service():
                return None
        
        try:
            name = participant_name.strip()
            item = self.service.conferenceRecords().participants().get(name=name).execute()
            display_name = 'Unknown'
            user_id = ''
            if 'signedinUser' in item:
                display_name = item['signedinUser'].get('displayName') or item['signedinUser'].get('user', 'User')
                user_id = item['signedinUser'].get('user', '')
            elif 'anonymousUser' in item:
                display_name = item['anonymousUser'].get('displayName', 'Anonymous')
            elif 'phoneUser' in item:
                display_name = item['phoneUser'].get('displayName', 'Phone Call-In')
            
            return {
                'name': item.get('name', ''),
                'display_name': display_name,
                'user_id': user_id,
                'earliest_start_time': item.get('earliestStartTime', ''),
                'latest_end_time': item.get('latestEndTime', ''),
            }
        except HttpError as e:
            logger.error(f"Failed to get participant {participant_name}: {e}")
            print_error(f"Failed to get participant: {e}")
            return None

    def list_participant_sessions(self, participant_name: str, 
                                  max_results: int = 50) -> List[Dict[str, Any]]:
        """
        List join/leave sessions for a participant.
        """
        if not self.service:
            if not self._initialize_service():
                return []
        
        try:
            parent = participant_name.strip()
            sessions: List[Dict[str, Any]] = []
            page_token = None
            
            while len(sessions) < max_results:
                page_size = min(max_results - len(sessions), 100)
                params: Dict[str, Any] = {'parent': parent, 'pageSize': page_size}
                if page_token:
                    params['pageToken'] = page_token
                
                result = self.service.conferenceRecords().participants().participantSessions().list(**params).execute()
                items = result.get('participantSessions', [])
                if not isinstance(items, list) or not items:
                    break
                
                for item in items:
                    sessions.append({
                        'name': item.get('name', ''),
                        'start_time': item.get('startTime', ''),
                        'end_time': item.get('endTime', ''),
                    })
                    if len(sessions) >= max_results:
                        break
                
                token = result.get('nextPageToken')
                if isinstance(token, str) and token:
                    page_token = token
                else:
                    break
            
            return sessions
        except HttpError as e:
            logger.error(f"Failed to list participant sessions for {participant_name}: {e}")
            print_error(f"Failed to list participant sessions: {e}")
            return []

    # =========================================================================
    # Recordings
    # =========================================================================

    def list_recordings(self, conference_record_name: str, 
                        max_results: int = 50) -> List[Dict[str, Any]]:
        """
        List recording metadata for a conference record.
        """
        if not self.service:
            if not self._initialize_service():
                return []
        
        try:
            parent = conference_record_name.strip()
            if not parent.startswith('conferenceRecords/'):
                parent = f'conferenceRecords/{parent}'
            
            recordings: List[Dict[str, Any]] = []
            page_token = None
            
            while len(recordings) < max_results:
                page_size = min(max_results - len(recordings), 100)
                params: Dict[str, Any] = {'parent': parent, 'pageSize': page_size}
                if page_token:
                    params['pageToken'] = page_token
                
                result = self.service.conferenceRecords().recordings().list(**params).execute()
                items = result.get('recordings', [])
                if not isinstance(items, list) or not items:
                    break
                
                for item in items:
                    drive_file = ''
                    export_uri = ''
                    drive_dest = item.get('driveDestination', {})
                    if drive_dest:
                        drive_file = drive_dest.get('file', '')
                        export_uri = drive_dest.get('exportUri', '')
                    
                    recordings.append({
                        'name': item.get('name', ''),
                        'state': item.get('state', ''),
                        'start_time': item.get('startTime', ''),
                        'end_time': item.get('endTime', ''),
                        'drive_file': drive_file,
                        'export_uri': export_uri,
                    })
                    if len(recordings) >= max_results:
                        break
                
                token = result.get('nextPageToken')
                if isinstance(token, str) and token:
                    page_token = token
                else:
                    break
            
            return recordings
        except HttpError as e:
            logger.error(f"Failed to list recordings for {conference_record_name}: {e}")
            print_error(f"Failed to list recordings: {e}")
            return []

    def get_recording(self, recording_name: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata for a specific recording.
        """
        if not self.service:
            if not self._initialize_service():
                return None
        
        try:
            name = recording_name.strip()
            item = self.service.conferenceRecords().recordings().get(name=name).execute()
            drive_file = ''
            export_uri = ''
            drive_dest = item.get('driveDestination', {})
            if drive_dest:
                drive_file = drive_dest.get('file', '')
                export_uri = drive_dest.get('exportUri', '')
            
            return {
                'name': item.get('name', ''),
                'state': item.get('state', ''),
                'start_time': item.get('startTime', ''),
                'end_time': item.get('endTime', ''),
                'drive_file': drive_file,
                'export_uri': export_uri,
            }
        except HttpError as e:
            logger.error(f"Failed to get recording {recording_name}: {e}")
            print_error(f"Failed to get recording: {e}")
            return None

    # =========================================================================
    # Transcripts
    # =========================================================================

    def list_transcripts(self, conference_record_name: str, 
                         max_results: int = 50) -> List[Dict[str, Any]]:
        """
        List transcripts for a conference record.
        """
        if not self.service:
            if not self._initialize_service():
                return []
        
        try:
            parent = conference_record_name.strip()
            if not parent.startswith('conferenceRecords/'):
                parent = f'conferenceRecords/{parent}'
            
            transcripts: List[Dict[str, Any]] = []
            page_token = None
            
            while len(transcripts) < max_results:
                page_size = min(max_results - len(transcripts), 100)
                params: Dict[str, Any] = {'parent': parent, 'pageSize': page_size}
                if page_token:
                    params['pageToken'] = page_token
                
                result = self.service.conferenceRecords().transcripts().list(**params).execute()
                items = result.get('transcripts', [])
                if not isinstance(items, list) or not items:
                    break
                
                for item in items:
                    docs_doc = ''
                    export_uri = ''
                    docs_dest = item.get('docsDestination', {})
                    if docs_dest:
                        docs_doc = docs_dest.get('document', '')
                        export_uri = docs_dest.get('exportUri', '')
                    
                    transcripts.append({
                        'name': item.get('name', ''),
                        'state': item.get('state', ''),
                        'start_time': item.get('startTime', ''),
                        'end_time': item.get('endTime', ''),
                        'docs_document': docs_doc,
                        'export_uri': export_uri,
                    })
                    if len(transcripts) >= max_results:
                        break
                
                token = result.get('nextPageToken')
                if isinstance(token, str) and token:
                    page_token = token
                else:
                    break
            
            return transcripts
        except HttpError as e:
            logger.error(f"Failed to list transcripts for {conference_record_name}: {e}")
            print_error(f"Failed to list transcripts: {e}")
            return []

    def get_transcript(self, transcript_name: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata for a specific transcript.
        """
        if not self.service:
            if not self._initialize_service():
                return None
        
        try:
            name = transcript_name.strip()
            item = self.service.conferenceRecords().transcripts().get(name=name).execute()
            docs_doc = ''
            export_uri = ''
            docs_dest = item.get('docsDestination', {})
            if docs_dest:
                docs_doc = docs_dest.get('document', '')
                export_uri = docs_dest.get('exportUri', '')
            
            return {
                'name': item.get('name', ''),
                'state': item.get('state', ''),
                'start_time': item.get('startTime', ''),
                'end_time': item.get('endTime', ''),
                'docs_document': docs_doc,
                'export_uri': export_uri,
            }
        except HttpError as e:
            logger.error(f"Failed to get transcript {transcript_name}: {e}")
            print_error(f"Failed to get transcript: {e}")
            return None

    def list_transcript_entries(self, transcript_name: str, 
                                max_results: int = 100) -> List[Dict[str, Any]]:
        """
        List text entries for a transcript.
        """
        if not self.service:
            if not self._initialize_service():
                return []
        
        try:
            parent = transcript_name.strip()
            entries: List[Dict[str, Any]] = []
            page_token = None
            
            while len(entries) < max_results:
                page_size = min(max_results - len(entries), 100)
                params: Dict[str, Any] = {'parent': parent, 'pageSize': page_size}
                if page_token:
                    params['pageToken'] = page_token
                
                result = self.service.conferenceRecords().transcripts().entries().list(**params).execute()
                items = result.get('transcriptEntries', [])
                if not isinstance(items, list) or not items:
                    break
                
                for item in items:
                    entries.append({
                        'name': item.get('name', ''),
                        'participant': item.get('participant', ''),
                        'text': item.get('text', ''),
                        'language_code': item.get('languageCode', ''),
                        'start_time': item.get('startTime', ''),
                        'end_time': item.get('endTime', ''),
                    })
                    if len(entries) >= max_results:
                        break
                
                token = result.get('nextPageToken')
                if isinstance(token, str) and token:
                    page_token = token
                else:
                    break
            
            return entries
        except HttpError as e:
            logger.error(f"Failed to list transcript entries for {transcript_name}: {e}")
            print_error(f"Failed to list transcript entries: {e}")
            return []
