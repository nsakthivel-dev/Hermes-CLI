"""
Advanced Google Sheets service with AI-powered analytics and automation
"""

import logging
from typing import List, Dict, Any, Optional
import json
import re
from datetime import datetime

from googleapiclient.errors import HttpError

from ..auth.oauth import OAuthManager
from ..utils.formatters import print_error, print_success, print_info
from ..utils.cache import ServiceCache

logger = logging.getLogger(__name__)


class AdvancedSheetsService:
    """Advanced Sheets service with AI-powered analytics and automation"""
    
    def __init__(self, oauth_manager: OAuthManager, cache_manager=None):
        self.oauth_manager = oauth_manager
        self.sheets_service = None
        self.drive_service = None
        self.cache = ServiceCache('sheets_advanced', cache_manager) if cache_manager else None
        self._initialize_services()
    
    def _initialize_services(self) -> bool:
        """Initialize the Sheets and Drive services"""
        try:
            self.sheets_service = self.oauth_manager.build_service('sheets', 'v4')
            self.drive_service = self.oauth_manager.build_service('drive', 'v3')
            return self.sheets_service is not None and self.drive_service is not None
        except Exception as e:
            logger.error(f"Failed to initialize Sheets services: {e}")
            return False
    
    def create_smart_spreadsheet(self, title: str, template_type: str = 'blank', 
                                data: List[List[Any]] = None) -> Optional[str]:
        """Create spreadsheet with AI-powered templates"""
        if not self.sheets_service or not self.drive_service:
            return None
        
        try:
            # Create spreadsheet
            spreadsheet = {
                'properties': {
                    'title': title,
                    'locale': 'en_US',
                    'timeZone': 'America/New_York'
                }
            }
            
            # Add template-specific sheets and data
            if template_type != 'blank':
                spreadsheet['sheets'] = self._get_template_sheets(template_type, data)
            
            result = self.sheets_service.spreadsheets().create(
                body=spreadsheet,
                fields='spreadsheetId'
            ).execute()
            
            spreadsheet_id = result.get('spreadsheetId')
            
            # Add template data if provided
            if template_type != 'blank' and data:
                self._populate_template_data(spreadsheet_id, template_type, data)
            
            print_success(f"Smart spreadsheet '{title}' created from {template_type} template")
            print_info(f"Spreadsheet ID: {spreadsheet_id}")
            
            return spreadsheet_id
        except HttpError as e:
            logger.error(f"Failed to create smart spreadsheet: {e}")
            print_error(f"Failed to create spreadsheet: {e}")
            return None
    
    def _get_template_sheets(self, template_type: str, data: List[List[Any]] = None) -> List[Dict]:
        """Get template-specific sheet configurations"""
        templates = {
            'budget': [{
                'properties': {
                    'title': 'Monthly Budget',
                    'gridProperties': {
                        'rowCount': 100,
                        'columnCount': 6
                    }
                }
            }],
            'project': [{
                'properties': {
                    'title': 'Project Tracker',
                    'gridProperties': {
                        'rowCount': 200,
                        'columnCount': 8
                    }
                }
            }],
            'inventory': [{
                'properties': {
                    'title': 'Inventory Management',
                    'gridProperties': {
                        'rowCount': 500,
                        'columnCount': 10
                    }
                }
            }],
            'sales': [{
                'properties': {
                    'title': 'Sales Dashboard',
                    'gridProperties': {
                        'rowCount': 100,
                        'columnCount': 7
                    }
                }
            }],
            'timesheet': [{
                'properties': {
                    'title': 'Timesheet',
                    'gridProperties': {
                        'rowCount': 200,
                        'columnCount': 6
                    }
                }
            }]
        }
        
        return templates.get(template_type, [{
            'properties': {
                'title': 'Sheet1',
                'gridProperties': {
                    'rowCount': 100,
                    'columnCount': 26
                }
            }
        }])
    
    def _populate_template_data(self, spreadsheet_id: str, template_type: str, data: List[List[Any]]):
        """Populate template with initial data"""
        try:
            template_data = {
                'budget': [
                    ['Category', 'Budgeted', 'Actual', 'Difference', 'Notes'],
                    ['Housing', 1500, 1450, 50, 'Rent payment'],
                    ['Food', 600, 550, 50, 'Groceries'],
                    ['Transportation', 400, 350, 50, 'Gas and maintenance'],
                    ['Utilities', 200, 180, 20, 'Electric, water, internet'],
                    ['Entertainment', 300, 250, 50, 'Movies, dining out'],
                    ['Savings', 1000, 1000, 0, 'Emergency fund'],
                    ['Total', '=SUM(B2:B7)', '=SUM(C2:C7)', '=B8-C8', '']
                ],
                'project': [
                    ['Task Name', 'Assigned To', 'Start Date', 'Due Date', 'Status', 'Priority', 'Progress', 'Notes'],
                    ['Project Setup', 'John Doe', '2024-01-01', '2024-01-05', 'Completed', 'High', '100%', 'Initial setup complete'],
                    ['Design Phase', 'Jane Smith', '2024-01-06', '2024-01-15', 'In Progress', 'High', '60%', 'Mockups in progress'],
                    ['Development', 'Mike Johnson', '2024-01-16', '2024-02-15', 'Not Started', 'High', '0%', 'Waiting for design'],
                    ['Testing', 'Sarah Wilson', '2024-02-16', '2024-02-28', 'Not Started', 'Medium', '0%', ''],
                    ['Deployment', 'Tom Brown', '2024-03-01', '2024-03-05', 'Not Started', 'High', '0%', '']
                ],
                'inventory': [
                    ['Product ID', 'Product Name', 'Category', 'Current Stock', 'Min Stock', 'Max Stock', 'Unit Price', 'Total Value', 'Supplier', 'Last Updated'],
                    ['PRD001', 'Laptop Computer', 'Electronics', 25, 10, 50, 999.99, 24999.75, 'TechSupplier', '2024-01-15'],
                    ['PRD002', 'Office Chair', 'Furniture', 15, 5, 30, 299.99, 4499.85, 'FurnitureCo', '2024-01-14'],
                    ['PRD003', 'Wireless Mouse', 'Electronics', 50, 20, 100, 29.99, 1499.50, 'TechSupplier', '2024-01-13']
                ],
                'sales': [
                    ['Date', 'Product', 'Customer', 'Quantity', 'Unit Price', 'Total', 'Sales Rep'],
                    ['2024-01-01', 'Laptop', 'ABC Corp', 2, 999.99, 1999.98, 'John'],
                    ['2024-01-02', 'Mouse', 'XYZ Inc', 5, 29.99, 149.95, 'Jane'],
                    ['2024-01-03', 'Chair', 'DEF Ltd', 3, 299.99, 899.97, 'Mike']
                ],
                'timesheet': [
                    ['Date', 'Employee', 'Project', 'Task', 'Hours', 'Notes'],
                    ['2024-01-01', 'John Doe', 'Project A', 'Development', 8, 'Frontend work'],
                    ['2024-01-01', 'Jane Smith', 'Project B', 'Design', 6, 'UI mockups'],
                    ['2024-01-02', 'John Doe', 'Project A', 'Testing', 4, 'Bug fixes']
                ]
            }
            
            # Use template data or provided data
            data_to_use = template_data.get(template_type, data)
            
            if data_to_use:
                range_name = f"'{template_data[template_type][0][0]}'!A1"
                
                body = {
                    'values': data_to_use
                }
                
                self.sheets_service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    valueInputOption='USER_ENTERED',
                    body=body
                ).execute()
                
        except Exception as e:
            logger.error(f"Failed to populate template data: {e}")
    
    def analyze_spreadsheet_data(self, spreadsheet_id: str, range_name: str = 'A1:Z1000') -> Dict[str, Any]:
        """Analyze spreadsheet data with AI insights"""
        if not self.sheets_service:
            return {}
        
        try:
            # Get data
            result = self.sheets_service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=range_name
            ).execute()
            
            values = result.get('values', [])
            
            if not values:
                return {'error': 'No data found in spreadsheet'}
            
            # Analyze data
            analysis = self._perform_data_analysis(values)
            
            return analysis
        except HttpError as e:
            logger.error(f"Failed to analyze spreadsheet: {e}")
            return {'error': str(e)}
    
    def _perform_data_analysis(self, values: List[List[Any]]) -> Dict[str, Any]:
        """Perform AI-powered data analysis"""
        if not values:
            return {}
        
        analysis = {
            'total_rows': len(values),
            'total_columns': len(values[0]) if values else 0,
            'data_types': {},
            'statistics': {},
            'insights': [],
            'recommendations': [],
            'data_quality': {}
        }
        
        # Analyze each column
        for col_idx in range(len(values[0])):
            column_data = [row[col_idx] if col_idx < len(row) else '' for row in values]
            
            # Determine data type
            data_type = self._detect_column_type(column_data)
            analysis['data_types'][f'Column_{col_idx + 1}'] = data_type
            
            # Calculate statistics based on data type
            if data_type == 'numeric':
                stats = self._calculate_numeric_stats(column_data)
                analysis['statistics'][f'Column_{col_idx + 1}'] = stats
            elif data_type == 'text':
                stats = self._calculate_text_stats(column_data)
                analysis['statistics'][f'Column_{col_idx + 1}'] = stats
        
        # Generate insights
        analysis['insights'] = self._generate_data_insights(values, analysis)
        analysis['recommendations'] = self._generate_data_recommendations(analysis)
        analysis['data_quality'] = self._assess_data_quality(values)
        
        return analysis
    
    def _detect_column_type(self, column_data: List[Any]) -> str:
        """Detect the data type of a column"""
        if not column_data:
            return 'empty'
        
        # Skip header row for type detection
        data_rows = column_data[1:] if len(column_data) > 1 else column_data
        
        numeric_count = 0
        date_count = 0
        text_count = 0
        
        for value in data_rows:
            if not value or value.strip() == '':
                continue
            
            # Check if numeric
            try:
                float(str(value).replace(',', '').replace('$', ''))
                numeric_count += 1
                continue
            except:
                pass
            
            # Check if date
            if self._is_date(str(value)):
                date_count += 1
                continue
            
            text_count += 1
        
        total = len([v for v in data_rows if v and v.strip() != ''])
        
        if numeric_count / total > 0.7:
            return 'numeric'
        elif date_count / total > 0.7:
            return 'date'
        else:
            return 'text'
    
    def _is_date(self, value: str) -> bool:
        """Check if value is a date"""
        date_patterns = [
            r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
            r'\d{2}/\d{2}/\d{4}',  # MM/DD/YYYY
            r'\d{1,2}-\d{1,2}-\d{4}'  # M-D-YYYY
        ]
        
        for pattern in date_patterns:
            if re.match(pattern, value):
                return True
        return False
    
    def _calculate_numeric_stats(self, column_data: List[Any]) -> Dict[str, Any]:
        """Calculate statistics for numeric column"""
        # Convert to numeric values
        numeric_values = []
        for value in column_data[1:]:  # Skip header
            if value and value.strip():
                try:
                    num = float(str(value).replace(',', '').replace('$', ''))
                    numeric_values.append(num)
                except:
                    continue
        
        if not numeric_values:
            return {'type': 'numeric', 'count': 0}
        
        return {
            'type': 'numeric',
            'count': len(numeric_values),
            'sum': sum(numeric_values),
            'mean': sum(numeric_values) / len(numeric_values),
            'min': min(numeric_values),
            'max': max(numeric_values),
            'median': sorted(numeric_values)[len(numeric_values) // 2]
        }
    
    def _calculate_text_stats(self, column_data: List[Any]) -> Dict[str, Any]:
        """Calculate statistics for text column"""
        text_values = [str(v) for v in column_data[1:] if v and v.strip()]
        
        if not text_values:
            return {'type': 'text', 'count': 0}
        
        # Most common values
        from collections import Counter
        counter = Counter(text_values)
        most_common = counter.most_common(5)
        
        return {
            'type': 'text',
            'count': len(text_values),
            'unique_values': len(set(text_values)),
            'most_common': most_common,
            'avg_length': sum(len(v) for v in text_values) / len(text_values)
        }
    
    def _generate_data_insights(self, values: List[List[Any]], analysis: Dict) -> List[str]:
        """Generate AI-powered data insights"""
        insights = []
        
        # Data size insights
        total_rows = analysis['total_rows']
        if total_rows > 1000:
            insights.append(f"📊 Large dataset with {total_rows} rows")
        elif total_rows < 50:
            insights.append(f"💡 Small dataset with {total_rows} rows")
        
        # Column insights
        total_columns = analysis['total_columns']
        insights.append(f"📈 Dataset has {total_columns} columns")
        
        # Data type distribution
        type_counts = {}
        for col_type in analysis['data_types'].values():
            type_counts[col_type] = type_counts.get(col_type, 0) + 1
        
        if type_counts.get('numeric', 0) > total_columns / 2:
            insights.append("🔢 Dataset is primarily numeric - good for statistical analysis")
        
        # Numeric insights
        numeric_columns = [k for k, v in analysis['data_types'].items() if v == 'numeric']
        for col in numeric_columns:
            stats = analysis['statistics'].get(col, {})
            if stats.get('count', 0) > 0:
                mean = stats.get('mean', 0)
                if mean > 1000:
                    insights.append(f"💰 {col} has high average values ({mean:.2f})")
        
        return insights
    
    def _generate_data_recommendations(self, analysis: Dict) -> List[str]:
        """Generate AI-powered data recommendations"""
        recommendations = []
        
        # Data quality recommendations
        quality = analysis.get('data_quality', {})
        
        if quality.get('missing_data_percentage', 0) > 20:
            recommendations.append("⚠️ High percentage of missing data - consider data cleaning")
        
        if quality.get('duplicate_rows', 0) > 0:
            recommendations.append("🔄 Duplicate rows found - consider removing duplicates")
        
        # Analysis recommendations
        numeric_columns = [k for k, v in analysis['data_types'].items() if v == 'numeric']
        
        if len(numeric_columns) >= 2:
            recommendations.append("📊 Multiple numeric columns - consider correlation analysis")
        
        if analysis['total_rows'] > 100:
            recommendations.append("📈 Large dataset - consider creating summary views")
        
        # General recommendations
        recommendations.extend([
            "🎯 Use pivot tables for better data summarization",
            "📊 Consider creating charts for data visualization",
            "🔍 Regular data validation improves accuracy"
        ])
        
        return recommendations[:5]
    
    def _assess_data_quality(self, values: List[List[Any]]) -> Dict[str, Any]:
        """Assess data quality metrics"""
        if not values:
            return {}
        
        total_cells = sum(len(row) for row in values)
        empty_cells = sum(1 for row in values for cell in row if not cell or str(cell).strip() == '')
        
        # Check for duplicate rows
        row_strings = ['|'.join(str(cell) for cell in row) for row in values]
        unique_rows = len(set(row_strings))
        duplicate_rows = len(values) - unique_rows
        
        return {
            'total_cells': total_cells,
            'empty_cells': empty_cells,
            'missing_data_percentage': (empty_cells / total_cells * 100) if total_cells > 0 else 0,
            'duplicate_rows': duplicate_rows,
            'data_completeness': ((total_cells - empty_cells) / total_cells * 100) if total_cells > 0 else 0
        }
    
    def create_automated_report(self, spreadsheet_id: str, report_type: str = 'summary') -> bool:
        """Create automated report from spreadsheet data"""
        if not self.sheets_service:
            return False
        
        try:
            # Get data analysis
            analysis = self.analyze_spreadsheet_data(spreadsheet_id)
            
            if 'error' in analysis:
                print_error(f"Cannot create report: {analysis['error']}")
                return False
            
            # Create report sheet
            requests = [{
                'addSheet': {
                    'properties': {
                        'title': f'AI Report - {report_type}',
                        'gridProperties': {
                            'rowCount': 100,
                            'columnCount': 3
                        }
                    }
                }
            }]
            
            self.sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': requests}
            ).execute()
            
            # Add report content
            report_data = self._generate_report_content(analysis, report_type)
            
            range_name = f"'AI Report - {report_type}'!A1"
            
            body = {
                'values': report_data
            }
            
            self.sheets_service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption='USER_ENTERED',
                body=body
            ).execute()
            
            print_success(f"AI-generated '{report_type}' report created")
            return True
        except HttpError as e:
            logger.error(f"Failed to create automated report: {e}")
            print_error(f"Failed to create report: {e}")
            return False
    
    def _generate_report_content(self, analysis: Dict, report_type: str) -> List[List[Any]]:
        """Generate report content based on analysis"""
        if report_type == 'summary':
            return [
                ['AI Data Analysis Report', '', ''],
                ['', '', ''],
                ['Dataset Overview', '', ''],
                ['Total Rows', str(analysis['total_rows']), ''],
                ['Total Columns', str(analysis['total_columns']), ''],
                ['Data Completeness', f"{analysis.get('data_quality', {}).get('data_completeness', 0):.1f}%", ''],
                ['', '', ''],
                ['Key Insights', '', ''],
            ] + [[insight, '', ''] for insight in analysis.get('insights', [])] + [
                ['', '', ''],
                ['Recommendations', '', ''],
            ] + [[rec, '', ''] for rec in analysis.get('recommendations', [])]
        
        elif report_type == 'detailed':
            content = [
                ['Detailed Data Analysis Report', '', ''],
                ['Generated:', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '', ''],
                ['', '', ''],
                ['Column Analysis', '', ''],
                ['Column', 'Type', 'Statistics'],
            ]
            
            for col, col_type in analysis.get('data_types', {}).items():
                stats = analysis.get('statistics', {}).get(col, {})
                stats_str = str(stats.get('count', 0)) + ' values'
                content.append([col, col_type, stats_str])
            
            return content
        
        else:
            return [['Report type not supported', '', '']]
    
    def apply_smart_formatting(self, spreadsheet_id: str, range_name: str = 'A1:Z1000') -> bool:
        """Apply smart formatting to spreadsheet"""
        if not self.sheets_service:
            return False
        
        try:
            # Get data to analyze for formatting
            result = self.sheets_service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=range_name
            ).execute()
            
            values = result.get('values', [])
            if not values:
                return False
            
            # Create formatting requests
            requests = []
            
            # Format header row
            if values:
                header_range = f"{range_name.split(':')[0]}:{chr(65 + len(values[0]) - 1)}1"
                requests.append({
                    'repeatCell': {
                        'range': {
                            'sheetId': 0,
                            'startRowIndex': 0,
                            'endRowIndex': 1,
                            'startColumnIndex': 0,
                            'endColumnIndex': len(values[0])
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'backgroundColor': {
                                    'red': 0.8,
                                    'green': 0.8,
                                    'blue': 0.8
                                },
                                'textFormat': {
                                    'bold': True
                                }
                            }
                        },
                        'fields': 'userEnteredFormat(backgroundColor,textFormat)'
                    }
                })
            
            # Apply alternating row colors
            for i in range(1, len(values), 2):
                requests.append({
                    'repeatCell': {
                        'range': {
                            'sheetId': 0,
                            'startRowIndex': i,
                            'endRowIndex': i + 1,
                            'startColumnIndex': 0,
                            'endColumnIndex': len(values[0]) if values else 0
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'backgroundColor': {
                                    'red': 0.95,
                                    'green': 0.95,
                                    'blue': 0.95
                                }
                            }
                        },
                        'fields': 'userEnteredFormat(backgroundColor)'
                    }
                })
            
            # Auto-resize columns
            for col_idx in range(len(values[0]) if values else 0):
                requests.append({
                    'updateDimensionProperties': {
                        'range': {
                            'sheetId': 0,
                            'dimension': 'COLUMNS',
                            'startIndex': col_idx,
                            'endIndex': col_idx + 1
                        },
                        'properties': {
                            'pixelSize': 100
                        },
                        'fields': 'pixelSize'
                    }
                })
            
            # Execute formatting
            self.sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': requests}
            ).execute()
            
            print_success("Smart formatting applied to spreadsheet")
            return True
        except HttpError as e:
            logger.error(f"Failed to apply formatting: {e}")
            print_error(f"Failed to apply formatting: {e}")
            return False
