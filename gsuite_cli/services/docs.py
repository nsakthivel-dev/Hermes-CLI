"""
Google Docs service integration
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from googleapiclient.errors import HttpError

from ..auth.oauth import OAuthManager
from ..utils.formatters import print_error
from ..utils.cache import ServiceCache

logger = logging.getLogger(__name__)


class DocsService:
    """Google Docs API service wrapper"""
    
    def __init__(self, oauth_manager: OAuthManager, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.docs_service = None
        self.drive_service = None
        self.cache = ServiceCache('docs', cache_manager) if cache_manager else None
        self._initialize_services()
    
    def _initialize_services(self) -> bool:
        """Initialize the Docs and Drive services"""
        try:
            self.docs_service = self.oauth_manager.build_service('docs', 'v1')
            self.drive_service = self.oauth_manager.build_service('drive', 'v3')
            return self.docs_service is not None and self.drive_service is not None
        except Exception as e:
            logger.error(f"Failed to initialize Docs services: {e}")
            return False
    
    def list_documents(self, max_results: int = 50) -> List[Dict[str, Any]]:
        """List all Google Docs"""
        if not self.drive_service:
            return []
        
        # Try cache first
        if self.cache:
            cached_result = self.cache.get('list_documents', max_results)
            if cached_result is not None:
                return cached_result
        
        try:
            # Query for Google Docs files
            query = "mimeType='application/vnd.google-apps.document' and trashed=false"
            results = self.drive_service.files().list(
                q=query,
                pageSize=max_results,
                fields="files(id, name, createdTime, modifiedTime, size, owners, permissions)"
            ).execute()
            
            files = results.get('files', [])
            
            formatted_docs = []
            for file in files:
                formatted_docs.append({
                    'id': file.get('id'),
                    'name': file.get('name'),
                    'created': file.get('createdTime', '')[:10],
                    'modified': file.get('modifiedTime', '')[:10],
                    'size': file.get('size', '0'),
                    'owners': [owner.get('displayName', 'Unknown') for owner in file.get('owners', [])],
                    'shared': len(file.get('permissions', [])) > 1
                })
            
            # Cache the result
            if self.cache:
                self.cache.set('list_documents', formatted_docs, 300, max_results)
            
            return formatted_docs
        except HttpError as e:
            logger.error(f"Failed to list documents: {e}")
            print_error(f"Failed to list documents: {e}")
            return []
    
    def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Get document content and metadata"""
        if not self.docs_service or not self.drive_service:
            return None
        
        # Try cache first
        if self.cache:
            cached_result = self.cache.get('get_document', document_id)
            if cached_result is not None:
                return cached_result
        
        try:
            # Get document content
            doc = self.docs_service.documents().get(documentId=document_id).execute()
            
            # Get file metadata
            file = self.drive_service.files().get(
                fileId=document_id,
                fields="name, createdTime, modifiedTime, size, owners, permissions"
            ).execute()
            
            # Extract text content
            content = self._extract_text_from_doc(doc)
            
            formatted_doc = {
                'id': document_id,
                'name': file.get('name'),
                'content': content,
                'created': file.get('createdTime'),
                'modified': file.get('modifiedTime'),
                'size': file.get('size', '0'),
                'owners': [owner.get('displayName', 'Unknown') for owner in file.get('owners', [])],
                'word_count': len(content.split()) if content else 0,
                'char_count': len(content),
                'paragraph_count': content.count('\n') + 1 if content else 0
            }
            
            # Cache the result
            if self.cache:
                self.cache.set('get_document', formatted_doc, 600, document_id)
            
            return formatted_doc
        except HttpError as e:
            logger.error(f"Failed to get document {document_id}: {e}")
            print_error(f"Failed to get document: {e}")
            return None
    
    def create_document(self, title: str, content: str = "") -> Optional[str]:
        """Create a new document"""
        if not self.docs_service or not self.drive_service:
            return None
        
        try:
            # Create document
            doc = self.docs_service.documents().create(body={
                'title': title
            }).execute()
            
            document_id = doc.get('documentId')
            
            # Add content if provided
            if content:
                self.update_document(document_id, content)
            
            # Invalidate cache
            if self.cache:
                self.cache.invalidate('list_documents')
            
            logger.info(f"Created document: {document_id}")
            return document_id
        except HttpError as e:
            error_details = str(e)
            if "not enabled" in error_details.lower():
                logger.error(f"Google Docs API not enabled: {e}")
                print_error("Google Docs API is not enabled in your Google Cloud Project.")
                print_info("Please enable it at: https://console.cloud.google.com/apis/library/docs.googleapis.com")
            else:
                logger.error(f"Failed to create document: {e}")
                print_error(f"Failed to create document: {e}")
            return None
    
    def update_document(self, document_id: str, content: str) -> bool:
        """Update document content"""
        if not self.docs_service:
            return False
        
        try:
            # Get current document structure
            doc = self.docs_service.documents().get(documentId=document_id).execute()
            
            # Clear existing content (keep first element which is usually the body)
            requests = []
            if len(doc.get('body', {}).get('content', [])) > 1:
                requests.append({
                    'deleteContentRange': {
                        'range': {
                            'startIndex': 1,
                            'endIndex': doc.get('body', {}).get('content', [])[-1].get('endIndex', -1)
                        }
                    }
                })
            
            # Insert new content
            requests.append({
                'insertText': {
                    'location': {
                        'index': 1
                    },
                    'text': content
                }
            })
            
            # Execute updates
            self.docs_service.documents().batchUpdate(
                documentId=document_id,
                body={'requests': requests}
            ).execute()
            
            # Invalidate cache
            if self.cache:
                self.cache.invalidate('get_document', document_id)
            
            logger.info(f"Updated document: {document_id}")
            return True
        except HttpError as e:
            logger.error(f"Failed to update document {document_id}: {e}")
            print_error(f"Failed to update document: {e}")
            return False
    
    def append_to_document(self, document_id: str, content: str) -> bool:
        """Append content to document"""
        if not self.docs_service:
            return False
        
        try:
            # Get document to find end index
            doc = self.docs_service.documents().get(documentId=document_id).execute()
            
            # Find the end index
            end_index = 1
            content_elements = doc.get('body', {}).get('content', [])
            if content_elements:
                end_index = content_elements[-1].get('endIndex', 1)
            
            # Append content
            requests = [{
                'insertText': {
                    'location': {
                        'index': end_index - 1  # -1 because we want to insert before the last newline
                    },
                    'text': '\n' + content
                }
            }]
            
            # Execute updates
            self.docs_service.documents().batchUpdate(
                documentId=document_id,
                body={'requests': requests}
            ).execute()
            
            # Invalidate cache
            if self.cache:
                self.cache.invalidate('get_document', document_id)
            
            logger.info(f"Appended content to document: {document_id}")
            return True
        except HttpError as e:
            logger.error(f"Failed to append to document {document_id}: {e}")
            print_error(f"Failed to append to document: {e}")
            return False

    def append_text(self, document_id: str, text: str) -> bool:
        """Append text to document (alias for append_to_document)"""
        return self.append_to_document(document_id, text)

    def insert_text(self, document_id: str, text: str, index: int = 1) -> bool:
        """Insert text into document at specified index"""
        if not self.docs_service:
            return False
        try:
            req = {
                'insertText': {
                    'location': {'index': index},
                    'text': text
                }
            }
            self.docs_service.documents().batchUpdate(
                documentId=document_id,
                body={'requests': [req]}
            ).execute()
            if self.cache:
                self.cache.invalidate('get_document', document_id)
            return True
        except HttpError as e:
            logger.error(f"Failed to insert text in doc {document_id}: {e}")
            print_error(f"Failed to insert text: {e}")
            return False
    
    def delete_document(self, document_id: str) -> bool:
        """Delete a document"""
        if not self.drive_service:
            return False
        
        try:
            self.drive_service.files().delete(fileId=document_id).execute()
            
            # Invalidate cache
            if self.cache:
                self.cache.invalidate('list_documents')
                self.cache.invalidate('get_document', document_id)
            
            logger.info(f"Deleted document: {document_id}")
            return True
        except HttpError as e:
            logger.error(f"Failed to delete document {document_id}: {e}")
            print_error(f"Failed to delete document: {e}")
            return False
    
    def search_documents(self, query: str, max_results: int = 20) -> List[Dict[str, Any]]:
        """Search documents by name or content"""
        if not self.drive_service:
            return []
        
        try:
            # Search in document names
            name_query = f"mimeType='application/vnd.google-apps.document' and name contains '{query}' and trashed=false"
            
            results = self.drive_service.files().list(
                q=name_query,
                pageSize=max_results,
                fields="files(id, name, createdTime, modifiedTime, size, owners)"
            ).execute()
            
            files = results.get('files', [])
            
            formatted_docs = []
            for file in files:
                formatted_docs.append({
                    'id': file.get('id'),
                    'name': file.get('name'),
                    'created': file.get('createdTime', '')[:10],
                    'modified': file.get('modifiedTime', '')[:10],
                    'size': file.get('size', '0'),
                    'owners': [owner.get('displayName', 'Unknown') for owner in file.get('owners', [])]
                })
            
            return formatted_docs
        except HttpError as e:
            logger.error(f"Failed to search documents: {e}")
            print_error(f"Failed to search documents: {e}")
            return []
    
    def get_document_info(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Get document metadata without content"""
        if not self.drive_service:
            return None
        
        try:
            file = self.drive_service.files().get(
                fileId=document_id,
                fields="name, createdTime, modifiedTime, size, owners, permissions, webViewLink"
            ).execute()
            
            return {
                'id': document_id,
                'name': file.get('name'),
                'created': file.get('createdTime'),
                'modified': file.get('modifiedTime'),
                'size': file.get('size', '0'),
                'owners': [owner.get('displayName', 'Unknown') for owner in file.get('owners', [])],
                'shared': len(file.get('permissions', [])) > 1,
                'web_view_link': file.get('webViewLink'),
                'permission_count': len(file.get('permissions', []))
            }
        except HttpError as e:
            logger.error(f"Failed to get document info {document_id}: {e}")
            print_error(f"Failed to get document info: {e}")
            return None
    
    def _extract_text_from_doc(self, doc: Dict[str, Any]) -> str:
        """Extract plain text from document structure"""
        content = []
        
        def extract_from_structural_elements(elements):
            for element in elements:
                if 'paragraph' in element:
                    paragraph = element['paragraph']
                    for para_element in paragraph.get('elements', []):
                        if 'textRun' in para_element:
                            content.append(para_element['textRun'].get('content', ''))
                elif 'table' in element:
                    # Extract text from table cells
                    table = element['table']
                    for row in table.get('tableRows', []):
                        for cell in row.get('tableCells', []):
                            for cell_element in cell.get('content', []):
                                extract_from_structural_elements([cell_element])
                elif 'sectionBreak' in element:
                    content.append('\n')
        
        # Extract from body content
        body_content = doc.get('body', {}).get('content', [])
        extract_from_structural_elements(body_content)
        
        return ''.join(content).strip()
    
    def export_document(self, document_id: str, format: str = 'text/plain') -> Optional[str]:
        """Export document in specified format"""
        if not self.drive_service:
            return None
        
        try:
            # Map format to MIME type
            mime_types = {
                'text/plain': 'text/plain',
                'text/html': 'text/html',
                'application/pdf': 'application/pdf',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            }
            
            mime_type = mime_types.get(format, 'text/plain')
            
            # Export document
            data = self.drive_service.files().export(
                fileId=document_id,
                mimeType=mime_type
            ).execute()
            
            if isinstance(data, bytes):
                return data.decode('utf-8')
            return data
        except HttpError as e:
            logger.error(f"Failed to export document {document_id}: {e}")
            print_error(f"Failed to export document: {e}")
            return None

    def delete_document(self, document_id: str) -> bool:
        """Delete document from Drive"""
        if not self.drive_service:
            return False
        try:
            self.drive_service.files().delete(fileId=document_id).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to delete document {document_id}: {e}")
            return False

    def test_connection(self) -> Dict[str, Any]:
        """Test connection to Google Docs API"""
        if not self.docs_service:
            if not self._initialize_services():
                return {"status": "error", "message": "Failed to initialize Docs service"}
        try:
            if self.drive_service:
                res = self.drive_service.files().list(
                    q="mimeType = 'application/vnd.google-apps.document' and trashed = false",
                    pageSize=1,
                    fields="files(id, name)"
                ).execute()
                count = len(res.get("files", []))
            else:
                count = 0
            return {
                "status": "success",
                "message": "Successfully connected to Google Docs API",
                "docs_found": count
            }
        except Exception as e:
            logger.error(f"Error testing Docs connection: {e}")
            return {"status": "error", "message": str(e)}

    def get_profile(self) -> Dict[str, Any]:
        """Get profile for Google Docs service"""
        test_res = self.test_connection()
        auth_info = self.oauth_manager.get_auth_info()
        email = 'Unknown'
        if self.drive_service:
            try:
                about = self.drive_service.about().get(fields='user').execute()
                email = about.get('user', {}).get('emailAddress', 'Unknown')
            except Exception:
                pass
        return {
            "authenticated": auth_info.get("authenticated", False),
            "service": "Google Docs API v1",
            "connection_status": test_res.get("status"),
            "email": email
        }

