import logging
from typing import List, Dict, Any, Optional

from googleapiclient.errors import HttpError

from ..auth.oauth import OAuthManager
from ..utils.formatters import print_error
from ..utils.cache import ServiceCache


logger = logging.getLogger(__name__)


class FormsService:
    def __init__(self, oauth_manager: OAuthManager, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.forms_service = None
        self.drive_service = None
        self.cache = ServiceCache('forms', cache_manager) if cache_manager else None
        self._initialize_services()

    @property
    def service(self):
        return self.forms_service

    @service.setter
    def service(self, val):
        self.forms_service = val

    def _initialize_services(self) -> bool:
        try:
            self.forms_service = self.oauth_manager.build_service('forms', 'v1')
            self.drive_service = self.oauth_manager.build_service('drive', 'v3')
            return self.forms_service is not None
        except Exception as e:
            logger.error(f"Failed to initialize Forms services: {e}")
            return False

    def create_form(self, title: str, description: str = "") -> Optional[Dict[str, Any]]:
        if not self.forms_service:
            return None

        body: Dict[str, Any] = {
            "info": {
                "title": title,
            }
        }

        if description:
            body["info"]["description"] = description

        try:
            form = self.forms_service.forms().create(body=body).execute()
            result = {
                "id": form.get("formId"),
                "title": form.get("info", {}).get("title", title),
                "document_title": form.get("info", {}).get("documentTitle", title),
            }
            return result
        except HttpError as e:
            logger.error(f"Failed to create form: {e}")
            print_error(f"Failed to create form: {e}")
            return None

    def list_forms(self, max_results: int = 50) -> List[Dict[str, Any]]:
        if not self.drive_service:
            return []

        if self.cache:
            cached_result = self.cache.get('list_forms', max_results)
            if cached_result is not None:
                return cached_result

        try:
            query = "mimeType='application/vnd.google-apps.form' and trashed=false"
            results = self.drive_service.files().list(
                q=query,
                pageSize=max_results,
                fields="files(id, name, createdTime, modifiedTime, owners)"
            ).execute()

            files = results.get('files', [])
            formatted_forms: List[Dict[str, Any]] = []

            for file in files:
                owners = file.get('owners', [])
                owner_name = owners[0].get('displayName', 'Unknown') if owners else 'Unknown'
                formatted_forms.append({
                    'id': file.get('id'),
                    'name': file.get('name'),
                    'created': file.get('createdTime', '')[:10],
                    'modified': file.get('modifiedTime', '')[:10],
                    'owner': owner_name,
                })

            if self.cache:
                self.cache.set('list_forms', formatted_forms, 300, max_results)

            return formatted_forms
        except HttpError as e:
            logger.error(f"Failed to list forms: {e}")
            print_error(f"Failed to list forms: {e}")
            return []

    def get_form(self, form_id: str) -> Optional[Dict[str, Any]]:
        if not self.forms_service:
            return None

        form_id = form_id.strip()

        if self.cache:
            cached_result = self.cache.get('get_form', form_id)
            if cached_result is not None:
                return cached_result

        try:
            form = self.forms_service.forms().get(formId=form_id).execute()
            info = form.get('info', {})
            settings = form.get('settings', {})
            items = form.get('items', [])

            formatted = {
                'id': form.get('formId', form_id),
                'title': info.get('title', ''),
                'document_title': info.get('documentTitle', ''),
                'description': info.get('description', ''),
                'item_count': len(items),
                'responder_uri': form.get('responderUri', ''),
                'shuffle_questions': settings.get('shuffleItems', False),
                'quiz': settings.get('quizSettings', {}).get('isQuiz', False),
            }

            if self.cache:
                self.cache.set('get_form', formatted, 600, form_id)

            return formatted
        except HttpError as e:
            logger.error(f"Failed to get form {form_id}: {e}")
            print_error(f"Failed to get form: {e}")
            return None

    def update_form_info(self, form_id: str, title: Optional[str] = None, description: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not self.forms_service:
            return None

        form_id = form_id.strip()

        info: Dict[str, Any] = {}
        update_fields = []

        if title is not None:
            info["title"] = title
            update_fields.append("title")

        if description is not None:
            info["description"] = description
            update_fields.append("description")

        if not update_fields:
            return self.get_form(form_id)

        body = {
            "requests": [
                {
                    "updateFormInfo": {
                        "info": info,
                        "updateMask": ",".join(update_fields),
                    }
                }
            ]
        }

        try:
            self.forms_service.forms().batchUpdate(formId=form_id, body=body).execute()
            if self.cache:
                self.cache.invalidate('get_form', form_id)
            return self.get_form(form_id)
        except HttpError as e:
            logger.error(f"Failed to update form {form_id}: {e}")
            print_error(f"Failed to update form: {e}")
            return None

    def list_responses(self, form_id: str, max_results: int = 50) -> List[Dict[str, Any]]:
        if not self.forms_service:
            return []

        form_id = form_id.strip()

        try:
            responses: List[Dict[str, Any]] = []
            page_size = max_results if max_results <= 5000 else 5000

            request = self.forms_service.forms().responses().list(
                formId=form_id,
                pageSize=page_size,
            )

            while request is not None and len(responses) < max_results:
                result = request.execute()
                for r in result.get('responses', []):
                    responses.append({
                        'response_id': r.get('responseId'),
                        'respondent_email': r.get('respondentEmail', ''),
                        'create_time': r.get('createTime'),
                        'last_submitted_time': r.get('lastSubmittedTime'),
                        'total_score': r.get('totalScore', 0),
                    })
                    if len(responses) >= max_results:
                        break

                if len(responses) >= max_results:
                    break

                request = self.forms_service.forms().responses().list_next(request, result)

            return responses
        except HttpError as e:
            logger.error(f"Failed to list responses for form {form_id}: {e}")
            print_error(f"Failed to list responses: {e}")
            return []

    def get_response(self, form_id: str, response_id: str) -> Optional[Dict[str, Any]]:
        if not self.forms_service:
            return None

        form_id = form_id.strip()
        response_id = response_id.strip()

        try:
            response = self.forms_service.forms().responses().get(
                formId=form_id,
                responseId=response_id,
            ).execute()

            answers = response.get('answers', {})
            summary_answers: Dict[str, Any] = {}

            for question_id, answer in answers.items():
                text_answers = answer.get('textAnswers', {}).get('answers', [])
                values = [a.get('value', '') for a in text_answers]
                summary_answers[question_id] = "; ".join(values)

            return {
                'form_id': response.get('formId', form_id),
                'response_id': response.get('responseId', response_id),
                'respondent_email': response.get('respondentEmail', ''),
                'create_time': response.get('createTime'),
                'last_submitted_time': response.get('lastSubmittedTime'),
                'total_score': response.get('totalScore', 0),
                'answers': summary_answers,
            }
        except HttpError as e:
            logger.error(f"Failed to get response {response_id} for form {form_id}: {e}")
            print_error(f"Failed to get response: {e}")
            return None

    def get_form(self, form_id: str) -> Optional[Dict[str, Any]]:
        """Get full form metadata and items"""
        if not self.forms_service:
            return None
        try:
            return self.forms_service.forms().get(formId=form_id).execute()
        except HttpError as e:
            logger.error(f"Failed to get form {form_id}: {e}")
            return None

    def list_form_items(self, form_id: str) -> List[Dict[str, Any]]:
        """List questions and items in a form"""
        form = self.get_form(form_id)
        if not form:
            return []
        items = []
        for idx, item in enumerate(form.get('items', [])):
            items.append({
                'index': idx,
                'item_id': item.get('itemId', str(idx)),
                'title': item.get('title', 'Untitled item'),
                'description': item.get('description', '')
            })
        return items

    def add_form_item(self, form_id: str, title: str, description: str = "") -> bool:
        """Add a simple question item to form"""
        if not self.forms_service:
            return False
        try:
            request_body = {
                "requests": [{
                    "createItem": {
                        "item": {
                            "title": title,
                            "description": description,
                            "questionItem": {
                                "question": {
                                    "required": False,
                                    "textQuestion": {}
                                }
                            }
                        },
                        "location": {"index": 0}
                    }
                }]
            }
            self.forms_service.forms().batchUpdate(formId=form_id, body=request_body).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to add form item on {form_id}: {e}")
            print_error(f"Failed to add item: {e}")
            return False

    def delete_form_item(self, form_id: str, index: int) -> bool:
        """Delete an item by its index"""
        if not self.forms_service:
            return False
        try:
            request_body = {
                "requests": [{
                    "deleteItem": {
                        "location": {"index": index}
                    }
                }]
            }
            self.forms_service.forms().batchUpdate(formId=form_id, body=request_body).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to delete form item {index} on {form_id}: {e}")
            return False

    def test_connection(self) -> Dict[str, Any]:
        """Test Forms API connectivity"""
        if not self.forms_service:
            if not self._initialize_services():
                return {"status": "error", "message": "Failed to initialize Forms service"}
        try:
            if self.drive_service:
                res = self.drive_service.files().list(
                    q="mimeType = 'application/vnd.google-apps.form' and trashed = false",
                    pageSize=1,
                    fields="files(id, name)"
                ).execute()
                count = len(res.get("files", []))
            else:
                count = 0
            return {
                "status": "success",
                "message": "Successfully connected to Google Forms API",
                "forms_found": count
            }
        except Exception as e:
            logger.error(f"Error testing Forms connection: {e}")
            return {"status": "error", "message": str(e)}

    def get_profile(self) -> Dict[str, Any]:
        """Get profile for Forms service"""
        test_res = self.test_connection()
        auth_info = self.oauth_manager.get_auth_info()
        return {
            "authenticated": auth_info.get("authenticated", False),
            "service": "Google Forms API v1",
            "connection_status": test_res.get("status")
        }

