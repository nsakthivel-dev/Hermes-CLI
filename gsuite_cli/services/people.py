"""
Google People API service integration for Hermes CLI
"""

import logging
from typing import List, Dict, Any, Optional
from googleapiclient.errors import HttpError

from ..auth.oauth import OAuthManager, AuthenticationError
from ..utils.formatters import print_error, print_info
from ..utils.cache import ServiceCache

logger = logging.getLogger(__name__)


class PeopleService:
    """Google People API service wrapper"""

    def __init__(self, oauth_manager: OAuthManager, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.cache_manager = cache_manager
        self.service = None
        self.cache = ServiceCache('people', cache_manager) if cache_manager else None
        self._initialize_service()

    def _initialize_service(self) -> bool:
        """Initialize the Google People service client"""
        try:
            self.service = self.oauth_manager.build_service('people', 'v1')
            return self.service is not None
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Failed to initialize People service: {e}")
            return False

    def list_contacts(self, page_size: int = 50) -> List[Dict[str, Any]]:
        """List contacts from user's Google Contacts"""
        if not self.service:
            if not self._initialize_service():
                return []

        if self.cache:
            cached_data = self.cache.get('list_contacts', page_size)
            if cached_data is not None:
                return cached_data

        try:
            results = self.service.people().connections().list(
                resourceName='people/me',
                pageSize=page_size,
                personFields='names,emailAddresses,phoneNumbers,organizations'
            ).execute()

            connections = results.get('connections', [])
            formatted = []
            for person in connections:
                names = person.get('names', [])
                emails = person.get('emailAddresses', [])
                phones = person.get('phoneNumbers', [])
                orgs = person.get('organizations', [])

                name = names[0].get('displayName') if names else 'Unknown'
                email = emails[0].get('value') if emails else ''
                phone = phones[0].get('value') if phones else ''
                org = orgs[0].get('name') if orgs else ''

                formatted.append({
                    'resource_name': person.get('resourceName', ''),
                    'name': name,
                    'email': email,
                    'phone': phone,
                    'organization': org,
                })

            if self.cache:
                self.cache.set('list_contacts', formatted, 300, page_size)

            return formatted
        except HttpError as e:
            logger.error(f"Failed to list contacts: {e}")
            print_error(f"Failed to list contacts: {e}")
            return []

    def search_contacts(self, query: str, page_size: int = 20) -> List[Dict[str, Any]]:
        """Search contacts by query string"""
        if not self.service:
            if not self._initialize_service():
                return []

        try:
            results = self.service.people().searchContacts(
                query=query,
                pageSize=page_size,
                readMask='names,emailAddresses,phoneNumbers,organizations'
            ).execute()

            items = results.get('results', [])
            formatted = []
            for item in items:
                person = item.get('person', {})
                names = person.get('names', [])
                emails = person.get('emailAddresses', [])
                phones = person.get('phoneNumbers', [])
                orgs = person.get('organizations', [])

                name = names[0].get('displayName') if names else 'Unknown'
                email = emails[0].get('value') if emails else ''
                phone = phones[0].get('value') if phones else ''
                org = orgs[0].get('name') if orgs else ''

                formatted.append({
                    'resource_name': person.get('resourceName', ''),
                    'name': name,
                    'email': email,
                    'phone': phone,
                    'organization': org,
                })
            return formatted
        except HttpError as e:
            logger.error(f"Failed to search contacts: {e}")
            return []
