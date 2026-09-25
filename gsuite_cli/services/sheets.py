"""
Google Sheets service integration
"""

import logging
from typing import List, Dict, Any, Optional, Union

from googleapiclient.errors import HttpError

from ..auth.oauth import OAuthManager
from ..utils.formatters import print_error
from ..utils.cache import ServiceCache

logger = logging.getLogger(__name__)


class SheetsService:
    """Google Sheets API service wrapper"""
    
    def __init__(self, oauth_manager: OAuthManager, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.service = None
        self.drive_service = None
        self.cache = ServiceCache('sheets', cache_manager) if cache_manager else None
        self._initialize_service()
    
    def _initialize_service(self) -> bool:
        """Initialize the Sheets and Drive services"""
        try:
            self.service = self.oauth_manager.build_service('sheets', 'v4')
            self.drive_service = self.oauth_manager.build_service('drive', 'v3')
            return self.service is not None and self.drive_service is not None
        except Exception as e:
            logger.error(f"Failed to initialize Sheets services: {e}")
            return False
    
    def list_spreadsheets(self, max_results: int = 50) -> List[Dict[str, Any]]:
        """List all spreadsheets using Drive API"""
        if not self.drive_service:
            return []
        
        # Try cache first
        if self.cache:
            cached_result = self.cache.get('list_spreadsheets', max_results)
            if cached_result is not None:
                return cached_result
        
        try:
            query = "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
            results = self.drive_service.files().list(
                q=query,
                pageSize=max_results,
                fields="files(id, name, webViewLink, createdTime, modifiedTime)"
            ).execute()
            
            files = results.get('files', [])
            
            formatted_spreadsheets = []
            for file in files:
                formatted_spreadsheets.append({
                    'id': file.get('id'),
                    'name': file.get('name'),
                    'url': file.get('webViewLink'),
                    'created_time': file.get('createdTime', ''),
                    'modified_time': file.get('modifiedTime', ''),
                })
            
            # Cache the result
            if self.cache:
                self.cache.set('list_spreadsheets', formatted_spreadsheets, 300, max_results)
            
            return formatted_spreadsheets
        except HttpError as e:
            logger.error(f"Failed to list spreadsheets: {e}")
            print_error(f"Failed to list spreadsheets: {e}")
            return []
    
    def get_spreadsheet(self, spreadsheet_id: str) -> Optional[Dict[str, Any]]:
        """Get spreadsheet metadata"""
        if not self.service:
            return None
        
        try:
            result = self.service.spreadsheets().get(
                spreadsheetId=spreadsheet_id,
                includeGridData=False
            ).execute()
            
            sheets = []
            for sheet in result.get('sheets', []):
                properties = sheet.get('properties', {})
                sheets.append({
                    'sheet_id': properties.get('sheetId'),
                    'title': properties.get('title'),
                    'index': properties.get('index'),
                    'sheet_type': properties.get('sheetType'),
                    'grid_properties': properties.get('gridProperties', {}),
                })
            
            return {
                'spreadsheet_id': result.get('spreadsheetId'),
                'properties': result.get('properties', {}),
                'sheets': sheets,
                'spreadsheet_url': result.get('spreadsheetUrl'),
            }
        except HttpError as e:
            logger.error(f"Failed to get spreadsheet {spreadsheet_id}: {e}")
            print_error(f"Failed to get spreadsheet: {e}")
            return None
    
    def read_range(self, 
                   spreadsheet_id: str, 
                   range_name: str,
                   value_render_option: str = 'FORMATTED_VALUE') -> List[List[Any]]:
        """Read a range of cells from a spreadsheet"""
        if not self.service:
            return []
        
        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueRenderOption=value_render_option
            ).execute()
            
            values = result.get('values', [])
            return values
        except HttpError as e:
            logger.error(f"Failed to read range {range_name}: {e}")
            print_error(f"Failed to read range: {e}")
            return []
    
    def write_range(self,
                    spreadsheet_id: str,
                    range_name: str,
                    values: List[List[Any]],
                    value_input_option: str = 'USER_ENTERED') -> bool:
        """Write values to a range of cells"""
        if not self.service:
            return False
        
        try:
            body = {
                'values': values
            }
            
            result = self.service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption=value_input_option,
                body=body
            ).execute()
            
            updated_rows = result.get('updatedRows')
            updated_columns = result.get('updatedColumns')
            updated_cells = result.get('updatedCells')
            
            logger.info(f"Updated {updated_cells} cells ({updated_rows} rows, {updated_columns} columns)")
            return True
        except HttpError as e:
            logger.error(f"Failed to write range {range_name}: {e}")
            print_error(f"Failed to write range: {e}")
            return False
    
    def append_rows(self,
                    spreadsheet_id: str,
                    range_name: str,
                    values: List[List[Any]],
                    value_input_option: str = 'USER_ENTERED') -> bool:
        """Append rows to a spreadsheet"""
        if not self.service:
            return False
        
        try:
            body = {
                'values': values
            }
            
            result = self.service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption=value_input_option,
                insertDataOption='INSERT_ROWS',
                body=body
            ).execute()
            
            updated_rows = result.get('updates', {}).get('updatedRows')
            logger.info(f"Appended {updated_rows} rows")
            return True
        except HttpError as e:
            logger.error(f"Failed to append rows to {range_name}: {e}")
            print_error(f"Failed to append rows: {e}")
            return False
    
    def clear_range(self,
                    spreadsheet_id: str,
                    range_name: str) -> bool:
        """Clear a range of cells"""
        if not self.service:
            return False
        
        try:
            result = self.service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                body={}
            ).execute()
            
            cleared_cells = result.get('clearedRange')
            logger.info(f"Cleared range: {cleared_cells}")
            return True
        except HttpError as e:
            logger.error(f"Failed to clear range {range_name}: {e}")
            print_error(f"Failed to clear range: {e}")
            return False
    
    def create_spreadsheet(self,
                          title: str,
                          sheets: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
        """Create a new spreadsheet"""
        if not self.service:
            return None
        
        try:
            spreadsheet_body = {
                'properties': {
                    'title': title
                }
            }
            
            if sheets:
                spreadsheet_body['sheets'] = sheets
            
            result = self.service.spreadsheets().create(
                body=spreadsheet_body
            ).execute()
            
            spreadsheet_id = result.get('spreadsheetId')
            logger.info(f"Created spreadsheet: {spreadsheet_id}")
            return spreadsheet_id
        except HttpError as e:
            logger.error(f"Failed to create spreadsheet: {e}")
            print_error(f"Failed to create spreadsheet: {e}")
            return None
    
    def add_sheet(self,
                  spreadsheet_id: str,
                  title: str) -> Optional[int]:
        """Add a new sheet to a spreadsheet"""
        if not self.service:
            return None
        
        try:
            body = {
                'requests': [
                    {
                        'addSheet': {
                            'properties': {
                                'title': title
                            }
                        }
                    }
                ]
            }
            
            result = self.service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body
            ).execute()
            
            sheet_id = result.get('replies', [{}])[0].get('addSheet', {}).get('properties', {}).get('sheetId')
            logger.info(f"Added sheet '{title}' with ID: {sheet_id}")
            return sheet_id
        except HttpError as e:
            logger.error(f"Failed to add sheet '{title}': {e}")
            print_error(f"Failed to add sheet: {e}")
            return None
    
    def delete_sheet(self,
                     spreadsheet_id: str,
                     sheet_id: int) -> bool:
        """Delete a sheet from a spreadsheet"""
        if not self.service:
            return False
        
        try:
            body = {
                'requests': [
                    {
                        'deleteSheet': {
                            'sheetId': sheet_id
                        }
                    }
                ]
            }
            
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body
            ).execute()
            
            logger.info(f"Deleted sheet with ID: {sheet_id}")
            return True
        except HttpError as e:
            logger.error(f"Failed to delete sheet {sheet_id}: {e}")
            print_error(f"Failed to delete sheet: {e}")
            return False
    
    def get_sheet_data(self,
                       spreadsheet_id: str,
                       sheet_name: str,
                       header_row: int = 1) -> List[Dict[str, Any]]:
        """Get sheet data as list of dictionaries (with headers)"""
        if not self.service:
            return []
        
        try:
            # Get headers
            header_range = f"'{sheet_name}'!A{header_row}:Z{header_row}"
            headers_result = self.service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=header_range
            ).execute()
            
            headers = headers_result.get('values', [[]])[0]
            if not headers:
                return []
            
            # Get data rows
            data_range = f"'{sheet_name}'!A{header_row + 1}"
            data_result = self.service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=data_range
            ).execute()
            
            rows = data_result.get('values', [])
            
            # Convert to list of dictionaries
            data = []
            for row in rows:
                row_dict = {}
                for i, value in enumerate(row):
                    if i < len(headers):
                        row_dict[headers[i]] = value
                data.append(row_dict)
            
            return data
        except HttpError as e:
            logger.error(f"Failed to get sheet data for '{sheet_name}': {e}")
            print_error(f"Failed to get sheet data: {e}")
            return []
    
    def batch_update(self,
                     spreadsheet_id: str,
                     requests: List[Dict[str, Any]]) -> bool:
        """Perform batch updates on a spreadsheet"""
        if not self.service:
            return False
        
        try:
            body = {
                'requests': requests
            }
            
            result = self.service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body
            ).execute()
            
            total_updates = len(result.get('replies', []))
            logger.info(f"Performed {total_updates} batch updates")
            return True
        except HttpError as e:
            logger.error(f"Failed to perform batch updates: {e}")
            print_error(f"Failed to perform batch updates: {e}")
            return False
    
    def format_range(self,
                     spreadsheet_id: str,
                     range_name: str,
                     format: Dict[str, Any]) -> bool:
        """Format a range of cells"""
        if not self.service:
            return False
        
        try:
            body = {
                'requests': [
                    {
                        'repeatCell': {
                            'range': {
                                'sheetId': format.get('sheetId', 0),
                                'startRowIndex': format.get('startRowIndex', 0),
                                'endRowIndex': format.get('endRowIndex', 1000),
                                'startColumnIndex': format.get('startColumnIndex', 0),
                                'endColumnIndex': format.get('endColumnIndex', 26),
                            },
                            'cell': {
                                'userEnteredFormat': format.get('userEnteredFormat', {})
                            },
                            'fields': 'userEnteredFormat'
                        }
                    }
                ]
            }
            
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body
            ).execute()
            
            logger.info(f"Formatted range: {range_name}")
            return True
        except HttpError as e:
            logger.error(f"Failed to format range {range_name}: {e}")
            print_error(f"Failed to format range: {e}")
            return False

    @property
    def sheets_service(self):
        return self.service

    def append_row(self, spreadsheet_id: str, values: List[Any], range_name: str = 'Sheet1') -> bool:
        """Append a single row of values"""
        return self.append_rows(spreadsheet_id, range_name, [values])

    def add_sheet_tab(self, spreadsheet_id: str, title: str) -> Optional[Dict[str, Any]]:
        """Add a new sheet/tab to a spreadsheet"""
        sheet_id = self.add_sheet(spreadsheet_id, title)
        if sheet_id is not None:
            return {'properties': {'sheetId': sheet_id, 'title': title}}
        return None

    def list_sheet_tabs(self, spreadsheet_id: str) -> List[Dict[str, Any]]:
        """List tabs/sheets inside a spreadsheet"""
        meta = self.get_spreadsheet(spreadsheet_id)
        if not meta:
            return []
        tabs = []
        for s in meta.get('sheets', []):
            prop = s.get('properties', s)
            tabs.append({
                'tab_id': prop.get('sheet_id', prop.get('sheetId')),
                'title': prop.get('title'),
                'index': prop.get('index')
            })
        return tabs

    def delete_sheet_tab(self, spreadsheet_id: str, tab_id: int) -> bool:
        """Delete a sheet/tab from a spreadsheet"""
        return self.batch_update(spreadsheet_id, [{'deleteSheet': {'sheetId': tab_id}}])

    def rename_sheet_tab(self, spreadsheet_id: str, tab_id: int, new_title: str) -> bool:
        """Rename a tab/sheet"""
        return self.batch_update(spreadsheet_id, [{
            'updateSheetProperties': {
                'properties': {'sheetId': tab_id, 'title': new_title},
                'fields': 'title'
            }
        }])

    def delete_spreadsheet(self, spreadsheet_id: str) -> bool:
        """Delete spreadsheet via Drive API"""
        drive = self.drive_service or self.oauth_manager.build_service('drive', 'v3')
        if not drive:
            return False
        try:
            drive.files().delete(fileId=spreadsheet_id).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to delete spreadsheet {spreadsheet_id}: {e}")
            return False

    def test_connection(self) -> Dict[str, Any]:
        """Test Sheets API connectivity"""
        if not self.service:
            if not self._initialize_service():
                return {"status": "error", "message": "Failed to initialize Sheets service"}
        try:
            drive = self.drive_service or self.oauth_manager.build_service('drive', 'v3')
            count = 0
            if drive:
                res = drive.files().list(
                    q="mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false",
                    pageSize=1,
                    fields="files(id, name)"
                ).execute()
                count = len(res.get("files", []))
            return {
                "status": "success",
                "message": "Successfully connected to Google Sheets API",
                "sheets_found": count
            }
        except Exception as e:
            logger.error(f"Error testing Sheets connection: {e}")
            return {"status": "error", "message": str(e)}

    def get_profile(self) -> Dict[str, Any]:
        """Get profile for Google Sheets service"""
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
            "service": "Google Sheets API v4",
            "connection_status": test_res.get("status"),
            "email": email
        }

