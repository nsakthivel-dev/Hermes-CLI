"""
Gmail service integration
"""

import logging
import base64
import hashlib
import mimetypes
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.utils import parseaddr, formataddr
from email import encoders
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

from googleapiclient.errors import HttpError

from ..auth.oauth import OAuthManager
from ..utils.formatters import format_datetime, print_error, print_info, validate_email, truncate_text
from ..utils.cache import ServiceCache

logger = logging.getLogger(__name__)

# TTL constants (seconds)
_LIST_TTL = 120        # 2 min — short-lived list/search results
_MESSAGE_TTL = None    # indefinite — message bodies are immutable once sent


class GmailService:
    """Gmail API service wrapper"""
    
    def __init__(self, oauth_manager: OAuthManager, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.service = None
        self.cache = ServiceCache('gmail', cache_manager) if cache_manager else None
        self._initialize_service()
    
    def _initialize_service(self) -> bool:
        """Initialize the Gmail service"""
        try:
            self.service = self.oauth_manager.build_service('gmail', 'v1')
            return self.service is not None
        except Exception as e:
            logger.error(f"Failed to initialize Gmail service: {e}")
            return False
    
    def _list_cache_key(self, query: str, max_results: int, label_ids: Optional[List[str]]) -> str:
        """Stable cache key for list/search operations."""
        raw = f"{query}|{max_results}|{sorted(label_ids or [])}"
        return "list:" + hashlib.md5(raw.encode()).hexdigest()

    def list_messages(self, 
                     query: str = '',
                     max_results: int = 50,
                     label_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """List email messages with short-TTL caching."""
        if not self.service:
            return []

        # --- cache read ---
        if self.cache:
            ck = self._list_cache_key(query, max_results, label_ids)
            cached = self.cache.cache.get(ck)
            if cached is not None:
                logger.debug("Cache hit for list query: %s", query)
                return cached

        try:
            params = {
                'userId': 'me',
                'maxResults': max_results,
                'q': query
            }
            
            if label_ids:
                params['labelIds'] = label_ids
            
            result = self.service.users().messages().list(**params).execute()
            messages = result.get('messages', [])
            
            detailed_messages = []
            for message in messages:
                detail = self.get_message(message['id'], format='metadata')
                if detail:
                    detailed_messages.append(detail)

            # --- cache write (2-min TTL) ---
            if self.cache:
                self.cache.cache.set(ck, detailed_messages, expire=_LIST_TTL)

            return detailed_messages
        except HttpError as e:
            if e.resp.status == 403:
                logger.error(f"Permission denied: {e}")
                print_error("Permission denied (403). Your login session lacks Gmail access.")
                print_info("To fix this, go to Settings and select 'Logout', then 'Login' again.")
                print_info("Make sure to check all the permission boxes in your browser.")
            else:
                logger.error(f"Failed to list messages: {e}")
                print_error(f"Failed to list messages: {e}")
            return []
    
    def get_message(self, 
                   message_id: str, 
                   format: str = 'full',
                   no_cache: bool = False) -> Optional[Dict[str, Any]]:
        """Get a specific email message (full bodies cached indefinitely)."""
        if not self.service:
            return None

        # Full message bodies are immutable — cache them indefinitely unless
        # the caller explicitly opts out via no_cache=True.
        cache_key = f"msg:{message_id}:{format}"
        if self.cache and not no_cache and format == 'full':
            cached = self.cache.cache.get(cache_key)
            if cached is not None:
                logger.debug("Cache hit for message: %s", message_id)
                return cached

        try:
            message = self.service.users().messages().get(
                userId='me',
                id=message_id,
                format=format
            ).execute()
            
            # Extract headers
            headers = {}
            for header in message.get('payload', {}).get('headers', []):
                headers[header['name'].lower()] = header['value']
            
            # Extract body content
            body, attachments = self._extract_body_and_attachments(message.get('payload', {}))
            
            formatted_message = {
                'id': message.get('id'),
                'thread_id': message.get('threadId'),
                'subject': headers.get('subject', '(No subject)'),
                'from': headers.get('from', ''),
                'to': headers.get('to', ''),
                'cc': headers.get('cc', ''),
                'date': headers.get('date', ''),
                'message_id_header': headers.get('message-id', ''),
                'references': headers.get('references', ''),
                'snippet': message.get('snippet', ''),
                'body': body,
                'attachments': attachments,
                'label_ids': message.get('labelIds', []),
                'size_estimate': message.get('sizeEstimate', 0),
            }

            # Persist full bodies indefinitely
            if self.cache and format == 'full':
                self.cache.cache.set(cache_key, formatted_message)  # no expire = forever

            return formatted_message
        except HttpError as e:
            logger.error(f"Failed to get message {message_id}: {e}")
            print_error(f"Failed to get message: {e}")
            return None
    
    def _extract_body_and_attachments(self, payload: Dict[str, Any]) -> tuple:
        """Extract plain-text body and attachment metadata from a message payload.

        Returns:
            (body_str, attachments_list) where attachments_list is a list of
            dicts with keys: filename, mime_type, size, attachment_id.
        """
        plain_parts: List[str] = []
        html_parts: List[str] = []
        attachments: List[Dict[str, Any]] = []

        def _walk(part: Dict[str, Any]) -> None:
            mime = part.get('mimeType', '')
            body_obj = part.get('body', {})
            filename = part.get('filename', '')

            # Attachment (has filename or attachmentId with non-text MIME)
            attachment_id = body_obj.get('attachmentId')
            if filename or (attachment_id and not mime.startswith('text/')):
                attachments.append({
                    'filename': filename or '(unnamed)',
                    'mime_type': mime,
                    'size': body_obj.get('size', 0),
                    'attachment_id': attachment_id or '',
                })
                return

            if mime == 'text/plain':
                data = body_obj.get('data', '')
                if data:
                    plain_parts.append(
                        base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
                    )
            elif mime == 'text/html':
                data = body_obj.get('data', '')
                if data:
                    html_parts.append(
                        base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
                    )
            elif mime.startswith('multipart/'):
                for sub in part.get('parts', []):
                    _walk(sub)

        if 'parts' in payload:
            for part in payload['parts']:
                _walk(part)
        else:
            # Single-part message
            data = payload.get('body', {}).get('data', '')
            if data:
                plain_parts.append(
                    base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
                )

        body = '\n'.join(plain_parts) if plain_parts else '\n'.join(html_parts)
        return body, attachments

    # Keep the old name around so nothing in the existing codebase breaks.
    def _extract_body(self, payload: Dict[str, Any]) -> str:
        """Legacy helper — prefer _extract_body_and_attachments."""
        body, _ = self._extract_body_and_attachments(payload)
        return body
    
    def send_message(self, 
                    to: str,
                    subject: str,
                    body: str,
                    cc: Optional[str] = None,
                    bcc: Optional[str] = None,
                    attachments: Optional[List[str]] = None,
                    html_body: Optional[str] = None) -> Optional[str]:
        """Send an email"""
        if not self.service:
            return None
        
        # Validate email addresses
        if not validate_email(to):
            print_error(f"Invalid recipient email: {to}")
            return None
        
        if cc and not validate_email(cc):
            print_error(f"Invalid CC email: {cc}")
            return None
        
        if bcc and not validate_email(bcc):
            print_error(f"Invalid BCC email: {bcc}")
            return None
        
        try:
            message = MIMEMultipart()
            message['to'] = to
            message['subject'] = subject
            
            if cc:
                message['cc'] = cc
            if bcc:
                message['bcc'] = bcc
            
            # Add body
            if html_body:
                # HTML email
                message.attach(MIMEText(body, 'plain'))
                message.attach(MIMEText(html_body, 'html'))
            else:
                # Plain text email
                message.attach(MIMEText(body, 'plain'))
            
            # Add attachments
            if attachments:
                for file_path in attachments:
                    self._add_attachment(message, file_path)
            
            # Encode and send
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            result = self.service.users().messages().send(
                userId='me',
                body={'raw': raw_message}
            ).execute()
            
            message_id = result.get('id')
            logger.info(f"Message sent: {message_id}")
            return message_id
        except HttpError as e:
            logger.error(f"Failed to send message: {e}")
            print_error(f"Failed to send message: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to create message: {e}")
            print_error(f"Failed to create message: {e}")
            return None
    
    def _add_attachment(self, message: MIMEMultipart, file_path: str) -> bool:
        """Add attachment to email"""
        try:
            path = Path(file_path)
            if not path.exists():
                print_error(f"Attachment file not found: {file_path}")
                return False
            
            # Guess MIME type
            mime_type, _ = mimetypes.guess_type(file_path)
            if mime_type is None:
                mime_type = 'application/octet-stream'
            
            main_type, sub_type = mime_type.split('/', 1)
            
            with open(file_path, 'rb') as f:
                part = MIMEBase(main_type, sub_type)
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename="{path.name}"'
                )
                message.attach(part)
            
            return True
        except Exception as e:
            logger.error(f"Failed to add attachment {file_path}: {e}")
            print_error(f"Failed to add attachment: {e}")
            return False
    
    def search_messages(self, 
                       query: str,
                       max_results: int = 50) -> List[Dict[str, Any]]:
        """Search messages using Gmail search syntax"""
        return self.list_messages(query=query, max_results=max_results)
    
    def delete_message(self, message_id: str) -> bool:
        """Delete a message"""
        if not self.service:
            return False
        
        try:
            self.service.users().messages().delete(
                userId='me',
                id=message_id
            ).execute()
            
            logger.info(f"Message deleted: {message_id}")
            return True
        except HttpError as e:
            logger.error(f"Failed to delete message {message_id}: {e}")
            print_error(f"Failed to delete message: {e}")
            return False
    
    def batch_delete_messages(self, message_ids: List[str]) -> Dict[str, bool]:
        """Delete multiple messages"""
        results = {}
        for message_id in message_ids:
            results[message_id] = self.delete_message(message_id)
        return results
    
    def mark_as_read(self, message_id: str) -> bool:
        """Mark message as read"""
        if not self.service:
            return False
        
        try:
            self.service.users().messages().modify(
                userId='me',
                id=message_id,
                body={'removeLabelIds': ['UNREAD']}
            ).execute()
            
            logger.info(f"Message marked as read: {message_id}")
            return True
        except HttpError as e:
            logger.error(f"Failed to mark message as read {message_id}: {e}")
            print_error(f"Failed to mark message as read: {e}")
            return False
    
    def mark_as_unread(self, message_id: str) -> bool:
        """Mark message as unread"""
        if not self.service:
            return False
        
        try:
            self.service.users().messages().modify(
                userId='me',
                id=message_id,
                body={'addLabelIds': ['UNREAD']}
            ).execute()
            
            logger.info(f"Message marked as unread: {message_id}")
            return True
        except HttpError as e:
            logger.error(f"Failed to mark message as unread {message_id}: {e}")
            print_error(f"Failed to mark message as unread: {e}")
            return False
    
    def get_labels(self) -> List[Dict[str, Any]]:
        """Get all Gmail labels"""
        if not self.service:
            return []
        
        try:
            result = self.service.users().labels().list(userId='me').execute()
            labels = result.get('labels', [])
            
            formatted_labels = []
            for label in labels:
                formatted_labels.append({
                    'id': label.get('id'),
                    'name': label.get('name'),
                    'type': label.get('type'),
                    'messages_total': label.get('messagesTotal', 0),
                    'messages_unread': label.get('messagesUnread', 0),
                    'threads_total': label.get('threadsTotal', 0),
                    'threads_unread': label.get('threadsUnread', 0),
                })
            
            return formatted_labels
        except HttpError as e:
            logger.error(f"Failed to get labels: {e}")
            print_error(f"Failed to get labels: {e}")
            return []
    
    def get_thread(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """Get email thread"""
        if not self.service:
            return None
        
        try:
            thread = self.service.users().threads().get(
                userId='me',
                id=thread_id
            ).execute()
            
            messages = []
            for message in thread.get('messages', []):
                formatted_message = self.get_message(message['id'], format='full')
                if formatted_message:
                    messages.append(formatted_message)
            
            return {
                'id': thread.get('id'),
                'history_id': thread.get('historyId'),
                'messages': messages,
            }
        except HttpError as e:
            logger.error(f"Failed to get thread {thread_id}: {e}")
            print_error(f"Failed to get thread: {e}")
            return None

    # ------------------------------------------------------------------
    # Reply
    # ------------------------------------------------------------------

    def reply_message(
        self,
        message_id: str,
        body: str,
        attachments: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Reply within the same thread, preserving threading headers.

        Returns the new message id on success, or None on failure.
        """
        if not self.service:
            return None

        original = self.get_message(message_id)
        if not original:
            print_error(f"Cannot reply: message {message_id} not found.")
            return None

        thread_id = original['thread_id']
        to_addr = original['from']
        subject = original['subject']
        if not subject.lower().startswith('re:'):
            subject = 'Re: ' + subject

        orig_msg_id = original['message_id_header']
        orig_refs = original['references']

        # Build References chain
        references = f"{orig_refs} {orig_msg_id}".strip() if orig_refs else orig_msg_id

        msg = MIMEMultipart()
        msg['To'] = to_addr
        msg['Subject'] = subject
        if orig_msg_id:
            msg['In-Reply-To'] = orig_msg_id
        if references:
            msg['References'] = references

        msg.attach(MIMEText(body, 'plain'))
        if attachments:
            for path in attachments:
                self._add_attachment(msg, path)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        try:
            result = self.service.users().messages().send(
                userId='me',
                body={'raw': raw, 'threadId': thread_id}
            ).execute()
            sent_id = result.get('id')
            logger.info("Reply sent: %s", sent_id)
            return sent_id
        except HttpError as e:
            logger.error("Failed to send reply: %s", e)
            print_error(f"Failed to send reply: {e}")
            return None

    # ------------------------------------------------------------------
    # Draft
    # ------------------------------------------------------------------

    def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        attachments: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Create a draft message (does not send).

        Returns the draft id on success, or None on failure.
        """
        if not self.service:
            return None

        msg = MIMEMultipart()
        msg['To'] = to
        msg['Subject'] = subject
        if cc:
            msg['Cc'] = cc
        msg.attach(MIMEText(body, 'plain'))
        if attachments:
            for path in attachments:
                self._add_attachment(msg, path)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        try:
            result = self.service.users().drafts().create(
                userId='me',
                body={'message': {'raw': raw}}
            ).execute()
            draft_id = result.get('id')
            logger.info("Draft created: %s", draft_id)
            return draft_id
        except HttpError as e:
            logger.error("Failed to create draft: %s", e)
            print_error(f"Failed to create draft: {e}")
            return None

    # ------------------------------------------------------------------
    # Label management
    # ------------------------------------------------------------------

    def _get_or_create_label(self, label_name: str) -> Optional[str]:
        """Return the label id for *label_name*, creating it if necessary."""
        if not self.service:
            return None

        # Check existing labels first
        try:
            result = self.service.users().labels().list(userId='me').execute()
            for lbl in result.get('labels', []):
                if lbl.get('name', '').lower() == label_name.lower() or lbl.get('id', '') == label_name:
                    return lbl['id']
        except Exception as e:
            logger.error("Failed to list labels: %s", e)
            return None

        # Create the label
        try:
            new_label = self.service.users().labels().create(
                userId='me',
                body={'name': label_name, 'labelListVisibility': 'labelShow',
                      'messageListVisibility': 'show'}
            ).execute()
            logger.info("Created label '%s': %s", label_name, new_label.get('id'))
            return new_label.get('id')
        except Exception as e:
            logger.error("Failed to create label '%s': %s", label_name, e)
            print_error(f"Failed to create label '{label_name}': {e}")
            return None

    def modify_labels(
        self,
        message_id: str,
        add_labels: Optional[List[str]] = None,
        remove_labels: Optional[List[str]] = None,
    ) -> bool:
        """Add and/or remove label names on a message.

        User-defined label names are resolved (and created if absent) to their
        ids automatically. System labels (INBOX, UNREAD, STARRED …) can be
        passed by id directly.
        """
        if not self.service:
            return False

        SYSTEM_LABELS = {
            'INBOX', 'UNREAD', 'STARRED', 'IMPORTANT', 'SENT', 'DRAFT',
            'SPAM', 'TRASH', 'CATEGORY_PERSONAL', 'CATEGORY_SOCIAL',
            'CATEGORY_PROMOTIONS', 'CATEGORY_UPDATES', 'CATEGORY_FORUMS',
        }

        def _resolve_add(names: List[str]) -> List[str]:
            ids: List[str] = []
            for name in names:
                if name.upper() in SYSTEM_LABELS or name.upper().startswith('CATEGORY_'):
                    ids.append(name.upper())
                else:
                    label_id = self._get_or_create_label(name)
                    if label_id:
                        ids.append(label_id)
            return ids

        def _resolve_remove(names: List[str]) -> List[str]:
            ids: List[str] = []
            for name in names:
                if name.upper() in SYSTEM_LABELS or name.upper().startswith('CATEGORY_'):
                    ids.append(name.upper())
                else:
                    try:
                        result = self.service.users().labels().list(userId='me').execute()
                        found = False
                        for lbl in result.get('labels', []):
                            if lbl.get('name', '').lower() == name.lower() or lbl.get('id', '') == name:
                                ids.append(lbl['id'])
                                found = True
                                break
                        if not found:
                            ids.append(name)
                    except Exception:
                        ids.append(name)
            return ids

        add_ids = _resolve_add(add_labels or [])
        remove_ids = _resolve_remove(remove_labels or [])

        try:
            self.service.users().messages().modify(
                userId='me',
                id=message_id,
                body={
                    'addLabelIds': add_ids,
                    'removeLabelIds': remove_ids,
                }
            ).execute()
            logger.info("Labels modified on %s: +%s -%s", message_id, add_ids, remove_ids)
            return True
        except Exception as e:
            logger.error("Failed to modify labels on %s: %s", message_id, e)
            print_error(f"Failed to modify labels: {e}")
            return False


    # ------------------------------------------------------------------
    # Mark helpers  (read / unread / star / archive / trash)
    # ------------------------------------------------------------------

    def mark_as_starred(self, message_id: str) -> bool:
        return self.modify_labels(message_id, add_labels=['STARRED'])

    def mark_as_unstarred(self, message_id: str) -> bool:
        return self.modify_labels(message_id, remove_labels=['STARRED'])

    def archive_message(self, message_id: str) -> bool:
        """Archive by removing from INBOX."""
        return self.modify_labels(message_id, remove_labels=['INBOX'])

    def trash_message(self, message_id: str) -> bool:
        """Move to Trash."""
        if not self.service:
            return False
        try:
            self.service.users().messages().trash(
                userId='me', id=message_id
            ).execute()
            logger.info("Trashed message: %s", message_id)
            return True
        except HttpError as e:
            logger.error("Failed to trash message %s: %s", message_id, e)
            print_error(f"Failed to trash message: {e}")
            return False

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------

    def list_filters(self) -> List[Dict[str, Any]]:
        """Return all Gmail filters for the authenticated user."""
        if not self.service:
            return []
        try:
            result = self.service.users().settings().filters().list(userId='me').execute()
            filters = result.get('filter', [])
            formatted = []
            for f in filters:
                criteria = f.get('criteria', {})
                action = f.get('action', {})
                formatted.append({
                    'id': f.get('id', ''),
                    'from': criteria.get('from', ''),
                    'to': criteria.get('to', ''),
                    'subject': criteria.get('subject', ''),
                    'query': criteria.get('query', ''),
                    'add_labels': ', '.join(action.get('addLabelIds', [])),
                    'remove_labels': ', '.join(action.get('removeLabelIds', [])),
                })
            return formatted
        except HttpError as e:
            logger.error("Failed to list filters: %s", e)
            print_error(f"Failed to list filters: {e}")
            return []

    def create_filter(
        self,
        from_addr: Optional[str] = None,
        to_addr: Optional[str] = None,
        subject: Optional[str] = None,
        query: Optional[str] = None,
        add_labels: Optional[List[str]] = None,
        remove_labels: Optional[List[str]] = None,
        mark_read: bool = False,
        archive: bool = False,
    ) -> Optional[str]:
        """Create a Gmail filter and return its id."""
        if not self.service:
            return None

        criteria: Dict[str, Any] = {}
        if from_addr:
            criteria['from'] = from_addr
        if to_addr:
            criteria['to'] = to_addr
        if subject:
            criteria['subject'] = subject
        if query:
            criteria['query'] = query

        add_ids: List[str] = []
        remove_ids: List[str] = []
        for name in (add_labels or []):
            label_id = self._get_or_create_label(name)
            if label_id:
                add_ids.append(label_id)
        for name in (remove_labels or []):
            label_id = self._get_or_create_label(name)
            if label_id:
                remove_ids.append(label_id)
        if mark_read:
            remove_ids.append('UNREAD')
        if archive:
            remove_ids.append('INBOX')

        body: Dict[str, Any] = {'criteria': criteria, 'action': {}}
        if add_ids:
            body['action']['addLabelIds'] = add_ids
        if remove_ids:
            body['action']['removeLabelIds'] = remove_ids

        try:
            result = self.service.users().settings().filters().create(
                userId='me', body=body
            ).execute()
            fid = result.get('id')
            logger.info("Filter created: %s", fid)
            return fid
        except HttpError as e:
            logger.error("Failed to create filter: %s", e)
            print_error(f"Failed to create filter: {e}")
            return None

    def delete_filter(self, filter_id: str) -> bool:
        """Delete a Gmail filter by id."""
        if not self.service:
            return False
        try:
            self.service.users().settings().filters().delete(
                userId='me', id=filter_id
            ).execute()
            logger.info("Filter deleted: %s", filter_id)
            return True
        except HttpError as e:
            logger.error("Failed to delete filter %s: %s", filter_id, e)
            print_error(f"Failed to delete filter: {e}")
            return False

    # ------------------------------------------------------------------
    # Digest helpers
    # ------------------------------------------------------------------

    def list_messages_since(
        self,
        hours: int = 24,
        query: str = '',
        max_results: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return messages newer than *hours* hours, optionally filtered by *query*."""
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        # Gmail epoch filter uses integer seconds since Unix epoch
        epoch = int(cutoff.timestamp())
        q = f"after:{epoch}"
        if query:
            q = f"{q} {query}"
        return self.list_messages(query=q, max_results=max_results)

    # ------------------------------------------------------------------
    # Profile & Connection
    # ------------------------------------------------------------------

    def get_profile(self) -> Optional[Dict[str, Any]]:
        """Get the authenticated user's Gmail profile."""
        if not self.service:
            return None
        try:
            profile = self.service.users().getProfile(userId='me').execute()
            return {
                'email_address': profile.get('emailAddress', ''),
                'messages_total': profile.get('messagesTotal', 0),
                'threads_total': profile.get('threadsTotal', 0),
                'history_id': profile.get('historyId', ''),
            }
        except HttpError as e:
            logger.error("Failed to get Gmail profile: %s", e)
            print_error(f"Failed to get Gmail profile: {e}")
            return None

    def get_rich_profile(self) -> Dict[str, Any]:
        """Gather all data needed for the improved Gmail Profile dashboard.

        Returns a dict with:
          account   – email_address, display_name
          mailbox   – messages_total, threads_total, unread, drafts, starred
          labels    – system_count, custom_count
          connection – api_status, history_id
          error     – top-level failure message (only present on complete failure)
        """
        result: Dict[str, Any] = {
            'account': {'email_address': None, 'display_name': None},
            'mailbox': {
                'messages_total': None,
                'threads_total': None,
                'unread': None,
                'drafts': None,
                'starred': None,
            },
            'labels': {'system_count': None, 'custom_count': None},
            'connection': {'api_status': 'connection_failed', 'history_id': None},
        }

        # ── 1. Ensure service is initialized ──────────────────────────────────
        if not self.service:
            try:
                self._initialize_service()
            except Exception as exc:
                logger.warning("Failed to initialize Gmail service: %s", exc)

        if not self.service:
            is_auth = False
            try:
                if hasattr(self, 'oauth_manager') and self.oauth_manager:
                    is_auth = self.oauth_manager.is_authenticated()
            except Exception:
                pass
            status = 'connection_failed' if is_auth else 'auth_required'
            result['connection']['api_status'] = status
            result['error'] = 'Gmail API client not initialized'
            return result

        # ── 2. Primary profile request (lightweight API call) ─────────────────
        raw_profile = None
        try:
            raw_profile = self.service.users().getProfile(userId='me').execute()
        except Exception as exc:
            logger.warning("Failed to fetch Gmail base profile: %s", exc)
            err_str = str(exc).lower()
            status_code = getattr(getattr(exc, 'resp', None), 'status', None)
            if status_code in (401, 403) or any(k in err_str for k in ['auth', 'credential', 'token', 'permission', 'unauthorized', 'invalid_grant']):
                api_status = 'auth_required'
            else:
                api_status = 'connection_failed'
            result['connection']['api_status'] = api_status
            result['error'] = f"Failed to connect to Gmail API: {exc}"
            return result

        # Base profile succeeded -> Connected
        result['connection']['api_status'] = 'connected'
        history_id = raw_profile.get('historyId')
        result['connection']['history_id'] = history_id if history_id else None

        email_address = raw_profile.get('emailAddress')
        result['account']['email_address'] = email_address
        result['mailbox']['messages_total'] = raw_profile.get('messagesTotal')
        result['mailbox']['threads_total'] = raw_profile.get('threadsTotal')

        # ── 3. Account display name ───────────────────────────────────────────
        display_name = raw_profile.get('displayName') or raw_profile.get('name')
        if not display_name:
            try:
                settings_call = getattr(self.service.users(), 'settings', None)
                if settings_call:
                    send_as_res = self.service.users().settings().sendAs().list(userId='me').execute()
                    entries = send_as_res.get('sendAs', []) if isinstance(send_as_res, dict) else []
                    for entry in entries:
                        if entry.get('isPrimary') or entry.get('sendAsEmail') == email_address:
                            if entry.get('displayName'):
                                display_name = entry.get('displayName')
                                break
                    if not display_name and entries and entries[0].get('displayName'):
                        display_name = entries[0].get('displayName')
            except Exception as exc:
                logger.debug("Could not retrieve display name from sendAs settings: %s", exc)
        result['account']['display_name'] = display_name if display_name else None

        # ── 4. Labels and counts ──────────────────────────────────────────────
        unread = None
        drafts = None
        starred = None
        try:
            raw_labels_res = self.service.users().labels().list(userId='me').execute()
            raw_labels = raw_labels_res.get('labels', []) if isinstance(raw_labels_res, dict) else []
            s_count = 0
            c_count = 0
            for lbl in raw_labels:
                ltype = str(lbl.get('type', '')).upper()
                lid = str(lbl.get('id', '')).upper()
                if ltype == 'SYSTEM':
                    s_count += 1
                else:
                    c_count += 1

                if 'messagesTotal' in lbl:
                    if lid == 'UNREAD':
                        unread = lbl.get('messagesTotal')
                    elif lid == 'DRAFT':
                        drafts = lbl.get('messagesTotal')
                    elif lid == 'STARRED':
                        starred = lbl.get('messagesTotal')

            result['labels']['system_count'] = s_count
            result['labels']['custom_count'] = c_count
        except Exception as exc:
            logger.warning("Could not fetch labels list: %s", exc)
            result['labels']['system_count'] = None
            result['labels']['custom_count'] = None

        # If unread / drafts / starred were not provided in labels.list, fetch individually
        if unread is None:
            try:
                unread_lbl = self.service.users().labels().get(userId='me', id='UNREAD').execute()
                if isinstance(unread_lbl, dict) and 'messagesTotal' in unread_lbl:
                    unread = unread_lbl.get('messagesTotal')
            except Exception as exc:
                logger.debug("Could not fetch UNREAD label count: %s", exc)

        if drafts is None:
            try:
                drafts_lbl = self.service.users().labels().get(userId='me', id='DRAFT').execute()
                if isinstance(drafts_lbl, dict) and 'messagesTotal' in drafts_lbl:
                    drafts = drafts_lbl.get('messagesTotal')
            except Exception as exc:
                logger.debug("Could not fetch DRAFT label count: %s", exc)

        if starred is None:
            try:
                starred_lbl = self.service.users().labels().get(userId='me', id='STARRED').execute()
                if isinstance(starred_lbl, dict) and 'messagesTotal' in starred_lbl:
                    starred = starred_lbl.get('messagesTotal')
            except Exception as exc:
                logger.debug("Could not fetch STARRED label count: %s", exc)

        result['mailbox']['unread'] = unread
        result['mailbox']['drafts'] = drafts
        result['mailbox']['starred'] = starred

        return result


    def test_connection(self) -> Dict[str, Any]:
        """Verify Gmail API connectivity and authentication status."""
        if not self.service:
            initialized = self._initialize_service()
            if not initialized:
                return {
                    'connected': False,
                    'authenticated': False,
                    'error': 'Failed to initialize Gmail API client',
                }
        auth_info = self.oauth_manager.get_auth_info()
        profile = self.get_profile()
        if profile:
            return {
                'connected': True,
                'authenticated': auth_info.get('authenticated', False),
                'email': profile.get('email_address'),
                'messages_total': profile.get('messages_total'),
                'threads_total': profile.get('threads_total'),
                'scopes': auth_info.get('scopes', []),
                'token_expiry': auth_info.get('token_expiry'),
                'api_version': 'v1',
            }
        return {
            'connected': False,
            'authenticated': auth_info.get('authenticated', False),
            'error': 'Could not retrieve Gmail profile',
        }

    # ------------------------------------------------------------------
    # Drafts
    # ------------------------------------------------------------------

    def list_drafts(self, max_results: int = 50) -> List[Dict[str, Any]]:
        """List drafts in the mailbox."""
        if not self.service:
            return []
        try:
            res = self.service.users().drafts().list(userId='me', maxResults=max_results).execute()
            drafts = res.get('drafts', [])
            detailed = []
            for d in drafts:
                detail = self.get_draft(d['id'])
                if detail:
                    detailed.append(detail)
                else:
                    detailed.append({'id': d['id']})
            return detailed
        except HttpError as e:
            logger.error("Failed to list drafts: %s", e)
            print_error(f"Failed to list drafts: {e}")
            return []

    def get_draft(self, draft_id: str) -> Optional[Dict[str, Any]]:
        """Get details for a specific draft."""
        if not self.service:
            return None
        try:
            draft = self.service.users().drafts().get(userId='me', id=draft_id, format='full').execute()
            msg = draft.get('message', {})
            payload = msg.get('payload', {})
            headers = {h['name'].lower(): h['value'] for h in payload.get('headers', [])}
            body, attachments = self._extract_body_and_attachments(payload)
            return {
                'id': draft.get('id'),
                'message_id': msg.get('id'),
                'subject': headers.get('subject', '(No Subject)'),
                'to': headers.get('to', ''),
                'from': headers.get('from', ''),
                'date': headers.get('date', ''),
                'body': body or msg.get('snippet', ''),
                'attachments': attachments,
            }
        except HttpError as e:
            logger.error("Failed to get draft %s: %s", draft_id, e)
            return None

    def send_draft(self, draft_id: str) -> Optional[str]:
        """Send an existing draft."""
        if not self.service:
            return None
        try:
            sent = self.service.users().drafts().send(userId='me', body={'id': draft_id}).execute()
            logger.info("Draft sent: %s", sent.get('id'))
            return sent.get('id')
        except HttpError as e:
            logger.error("Failed to send draft %s: %s", draft_id, e)
            print_error(f"Failed to send draft: {e}")
            return None

    def delete_draft(self, draft_id: str) -> bool:
        """Delete an existing draft."""
        if not self.service:
            return False
        try:
            self.service.users().drafts().delete(userId='me', id=draft_id).execute()
            logger.info("Draft deleted: %s", draft_id)
            return True
        except HttpError as e:
            logger.error("Failed to delete draft %s: %s", draft_id, e)
            print_error(f"Failed to delete draft: {e}")
            return False

    # ------------------------------------------------------------------
    # User Labels & Message Forwarding
    # ------------------------------------------------------------------

    def create_label(self, name: str) -> Optional[Dict[str, Any]]:
        """Create a user label."""
        if not self.service:
            return None
        try:
            body = {
                'name': name,
                'labelListVisibility': 'labelShow',
                'messageListVisibility': 'show',
            }
            label = self.service.users().labels().create(userId='me', body=body).execute()
            logger.info("Created label: %s", name)
            return label
        except HttpError as e:
            logger.error("Failed to create label %s: %s", name, e)
            print_error(f"Failed to create label: {e}")
            return None

    def delete_label(self, label_id: str) -> bool:
        """Delete a label by ID."""
        if not self.service:
            return False
        try:
            self.service.users().labels().delete(userId='me', id=label_id).execute()
            logger.info("Deleted label: %s", label_id)
            return True
        except Exception as e:
            logger.error("Failed to delete label %s: %s", label_id, e)
            print_error(f"Failed to delete label: {e}")
            return False

    def rename_label(self, label_id: str, new_name: str) -> Optional[Dict[str, Any]]:
        """Rename an existing user label."""
        if not self.service:
            return None
        try:
            body = {'name': new_name}
            label = self.service.users().labels().patch(userId='me', id=label_id, body=body).execute()
            logger.info("Renamed label %s to %s", label_id, new_name)
            return label
        except Exception as e:
            logger.error("Failed to rename label %s to %s: %s", label_id, new_name, e)
            print_error(f"Failed to rename label: {e}")
            return None

    def get_label(self, label_id: str) -> Optional[Dict[str, Any]]:
        """Get details of a specific label."""
        if not self.service:
            return None
        try:
            lbl = self.service.users().labels().get(userId='me', id=label_id).execute()
            return {
                'id': lbl.get('id'),
                'name': lbl.get('name'),
                'type': lbl.get('type'),
                'messages_total': lbl.get('messagesTotal', 0),
                'messages_unread': lbl.get('messagesUnread', 0),
                'threads_total': lbl.get('threadsTotal', 0),
                'threads_unread': lbl.get('threadsUnread', 0),
            }
        except Exception as e:
            logger.error("Failed to get label %s: %s", label_id, e)
            return None


    def forward_message(
        self,
        message_id: str,
        to: str,
        body: str = '',
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
    ) -> Optional[str]:
        """Forward an existing email to a new recipient."""
        original = self.get_message(message_id, format='full')
        if not original:
            print_error(f"Cannot forward: original message {message_id} not found.")
            return None
        
        orig_subject = original.get('subject', 'No Subject')
        orig_from = original.get('from', '')
        orig_date = original.get('date', '')
        orig_to = original.get('to', '')
        orig_body = original.get('body', '')

        fwd_subject = orig_subject if orig_subject.lower().startswith('fwd:') else f"Fwd: {orig_subject}"
        fwd_body = (
            f"{body}\n\n"
            f"---------- Forwarded message ---------\n"
            f"From: {orig_from}\n"
            f"Date: {orig_date}\n"
            f"Subject: {orig_subject}\n"
            f"To: {orig_to}\n\n"
            f"{orig_body}"
        ) if body else (
            f"---------- Forwarded message ---------\n"
            f"From: {orig_from}\n"
            f"Date: {orig_date}\n"
            f"Subject: {orig_subject}\n"
            f"To: {orig_to}\n\n"
            f"{orig_body}"
        )

        return self.send_message(
            to=to,
            subject=fwd_subject,
            body=fwd_body,
            cc=cc,
            bcc=bcc,
        )

    def list_threads(
        self,
        query: str = '',
        max_results: int = 20,
        label_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """List thread conversations."""
        if not self.service:
            return []
        try:
            params = {
                'userId': 'me',
                'maxResults': max_results,
                'q': query,
            }
            if label_ids:
                params['labelIds'] = label_ids
            res = self.service.users().threads().list(**params).execute()
            threads = res.get('threads', [])
            detailed = []
            for t in threads:
                detail = self.get_thread(t['id'])
                if detail:
                    detailed.append(detail)
                else:
                    detailed.append({
                        'id': t['id'],
                        'snippet': t.get('snippet', ''),
                        'history_id': t.get('historyId', ''),
                        'messages': [],
                    })
            return detailed
        except HttpError as e:
            logger.error("Failed to list threads: %s", e)
            print_error(f"Failed to list threads: {e}")
            return []

    def untrash_message(self, message_id: str) -> bool:
        """Remove a message from trash."""
        if not self.service:
            return False
        try:
            self.service.users().messages().untrash(userId='me', id=message_id).execute()
            return True
        except HttpError as e:
            logger.error("Failed to untrash message %s: %s", message_id, e)
            print_error(f"Failed to untrash message: {e}")
            return False

    def mark_as_spam(self, message_id: str) -> bool:
        """Mark a message as SPAM."""
        return self.modify_labels(message_id, add_labels=['SPAM'], remove_labels=['INBOX'])
