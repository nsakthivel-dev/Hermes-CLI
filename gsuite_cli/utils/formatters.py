"""
Formatting and output utilities
"""

import os
import logging
import sys
import json
import csv
import re
import html
from io import StringIO
from typing import List, Dict, Any, Optional
from datetime import datetime

from colorama import Fore, Style
from tabulate import tabulate

_CLEAR_SCREEN_COUNT = 0


def clear_screen() -> None:
    """Clear the terminal screen cross-platform (Windows, Linux, macOS)."""
    global _CLEAR_SCREEN_COUNT
    _CLEAR_SCREEN_COUNT += 1
    if os.environ.get('HERMES_NO_CLEAR') == '1':
        return
    try:
        if os.name == 'nt':
            os.system('cls')
        else:
            os.system('clear')
    except Exception:
        pass


def get_clear_screen_count() -> int:
    """Get the number of times clear_screen() has been called."""
    return _CLEAR_SCREEN_COUNT


def reset_clear_screen_count() -> None:
    """Reset the clear_screen() counter."""
    global _CLEAR_SCREEN_COUNT
    _CLEAR_SCREEN_COUNT = 0



if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def _safe_print(text: str, file=None) -> None:
    if file is None:
        file = sys.stdout
    try:
        import click
        click.echo(text, file=file)
    except Exception:
        try:
            print(text, file=file)
        except UnicodeEncodeError:
            try:
                encoding = getattr(file, 'encoding', None) or 'ascii'
                encoded = text.encode(encoding, errors='replace').decode(encoding)
                print(encoded, file=file)
            except Exception:
                print(text.encode('ascii', errors='replace').decode('ascii'), file=file)


def setup_logging(debug: bool = False) -> None:
    """Setup logging configuration"""
    level = logging.DEBUG if debug else logging.WARNING
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def print_success(message: str) -> None:
    """Print success message in green"""
    _safe_print(f"{Fore.GREEN}✓ {message}{Style.RESET_ALL}")


def print_error(message: str) -> None:
    """Print error message in red"""
    _safe_print(f"{Fore.RED}✗ {message}{Style.RESET_ALL}", file=sys.stderr)


def print_info(message: str) -> None:
    """Print info message in cyan"""
    _safe_print(f"{Fore.CYAN}ℹ {message}{Style.RESET_ALL}")


def print_warning(message: str) -> None:
    """Print warning message in red"""
    _safe_print(f"{Fore.RED}⚠ {message}{Style.RESET_ALL}")


def print_header(message: str) -> None:
    """Print header message in white"""
    _safe_print(f"{Fore.WHITE}{Style.BRIGHT}━━━ {message} ━━━{Style.RESET_ALL}")


def print_section(title: str) -> None:
    """Print section title in cyan"""
    print(f"\n{Fore.CYAN}{Style.BRIGHT}▶ {title}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'─' * (len(title) + 4)}{Style.RESET_ALL}")




def format_output(data: List[Dict[str, Any]], 
                 format_type: str = 'table',
                 headers: Optional[List[str]] = None,
                 tablefmt: str = 'grid') -> str:
    """
    Format data for output
    
    Args:
        data: List of dictionaries to format
        format_type: Output format ('table', 'json', 'csv')
        headers: Column headers for table format
        tablefmt: Table format for tabulate
        
    Returns:
        Formatted string
    """
    if not data:
        return "No data found"
    
    if format_type == 'json':
        return json.dumps(data, indent=2, default=str)
    
    elif format_type == 'csv':
        if not data:
            return ""
        
        output = StringIO()
        if headers:
            writer = csv.DictWriter(output, fieldnames=headers)
            writer.writeheader()
        else:
            writer = csv.DictWriter(output, fieldnames=data[0].keys())
            writer.writeheader()
        
        for row in data:
            writer.writerow(row)
        
        return output.getvalue().strip()
    
    elif format_type == 'table':
        if not data:
            return "No data found"
        
        if headers:
            # Extract only the specified columns
            table_data = []
            for row in data:
                table_row = [row.get(header, '') for header in headers]
                table_data.append(table_row)
            return tabulate(table_data, headers=headers, tablefmt=tablefmt)
        else:
            # Use all keys as headers
            headers = list(data[0].keys())
            table_data = []
            for row in data:
                table_row = [row.get(header, '') for header in headers]
                table_data.append(table_row)
            return tabulate(table_data, headers=headers, tablefmt=tablefmt)
    
    else:
        raise ValueError(f"Unsupported format type: {format_type}")


def format_datetime(dt: datetime, format_str: str = '%Y-%m-%d %H:%M:%S') -> str:
    """Format datetime object to string"""
    if isinstance(dt, str):
        return dt
    return dt.strftime(format_str) if dt else ''


def truncate_text(text: str, max_length: int = 50) -> str:
    """Truncate text to specified length"""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + '...'


def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format"""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.1f} {size_names[i]}"


def format_number(value: Any) -> str:
    """Format a numeric value with thousands separators, or return '-'."""
    if value is None:
        return '-'
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value) if value else '-'



def parse_date_range(date_str: str) -> tuple:
    """
    Parse date range string into start and end dates
    
    Supports formats:
    - "today"
    - "yesterday"
    - "this week"
    - "last week"
    - "this month"
    - "last month"
    - "YYYY-MM-DD"
    - "YYYY-MM-DD,YYYY-MM-DD" (start,end)
    """
    from datetime import timedelta, date
    
    today = date.today()
    
    if date_str.lower() == 'today':
        return today, today
    
    elif date_str.lower() == 'yesterday':
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    
    elif date_str.lower() == 'this week':
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return start, end
    
    elif date_str.lower() == 'last week':
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=6)
        return start, end
    
    elif date_str.lower() == 'this month':
        start = today.replace(day=1)
        if today.month == 12:
            end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
        return start, end
    
    elif date_str.lower() == 'last month':
        if today.month == 1:
            start = today.replace(year=today.year - 1, month=12, day=1)
            end = today.replace(day=1) - timedelta(days=1)
        else:
            start = today.replace(month=today.month - 1, day=1)
            end = today.replace(day=1) - timedelta(days=1)
        return start, end
    
    elif ',' in date_str:
        # Start and end dates provided
        start_str, end_str = date_str.split(',', 1)
        start = datetime.strptime(start_str.strip(), '%Y-%m-%d').date()
        end = datetime.strptime(end_str.strip(), '%Y-%m-%d').date()
        return start, end
    
    else:
        # Single date
        single_date = datetime.strptime(date_str.strip(), '%Y-%m-%d').date()
        return single_date, single_date


def validate_email(email: str) -> bool:
    """Basic email validation"""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def get_progress_bar(current: int, total: int, width: int = 50) -> str:
    """Generate a simple progress bar"""
    if total == 0:
        return '[' + '=' * width + ']'
    
    filled = int(width * current / total)
    bar = '=' * filled + '-' * (width - filled)
    return f'[{bar}] {current}/{total} ({current/total*100:.1f}%)'


def print_table_with_headers(data: List[Dict[str, Any]], 
                           title: str = "",
                           max_col_width: int = 30,
                           tablefmt: str = 'grid') -> None:
    """Print a formatted table with optional title"""
    if not data:
        print_info("No data to display")
        return
    
    if title:
        print_header(title)
    
    # Truncate long values for better display
    truncated_data = []
    for row in data:
        truncated_row = {}
        for key, value in row.items():
            if isinstance(value, str) and len(value) > max_col_width:
                truncated_row[key] = truncate_text(value, max_col_width)
            else:
                truncated_row[key] = value
        truncated_data.append(truncated_row)
    
    output = format_output(truncated_data, format_type='table', tablefmt=tablefmt)
    print(output)


def format_email_body(body: str) -> str:
    if not body:
        return ""
    
    url_pattern = r'(https?://\S+)'
    
    # First, convert HTML links to "text (url)" form
    def link_replacer(match):
        href = match.group(1)
        text = match.group(2)
        text = re.sub(r'\s+', ' ', text).strip()
        if not text:
            text = href
        colored_href = f"{Fore.MAGENTA}{href}{Style.RESET_ALL}"
        return f"{text} ({colored_href})"
    
    link_pattern = re.compile(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
    processed = re.sub(link_pattern, link_replacer, body)
    
    # Strip remaining HTML tags
    processed = re.sub(r'<[^>]+>', '', processed)
    
    # Decode HTML entities
    processed = html.unescape(processed)
    
    # Normalize whitespace and remove empty lines
    lines = []
    for line in processed.splitlines():
        line = line.strip()
        if line:
            lines.append(line)
    processed = "\n".join(lines)
    
    # Finally, color any bare URLs that are still present
    def color_urls(text: str) -> str:
        def repl(match):
            url = match.group(1)
            return f"{Fore.MAGENTA}{url}{Style.RESET_ALL}"
        return re.sub(url_pattern, repl, text)
    
    return color_urls(processed)


def print_key_value_pairs(data: Dict[str, Any], title: str = "") -> None:
    """Print key-value pairs in a formatted way"""
    if title:
        print_section(title)
    
    for key, value in data.items():
        if isinstance(value, dict):
            print(f"{Fore.CYAN}{key}:{Style.RESET_ALL}")
            for sub_key, sub_value in value.items():
                print(f"  {sub_key}: {sub_value}")
        else:
            print(f"{Fore.CYAN}{key}:{Style.RESET_ALL} {value}")


def format_list_with_bullets(items: List[str], bullet: str = "•") -> str:
    """Format a list with bullets"""
    if not items:
        return "No items"
    
    return "\n".join(f"{bullet} {item}" for item in items)


def print_compact_list(items: List[str], columns: int = 3) -> None:
    """Print a list in compact columns"""
    if not items:
        return
    
    # Calculate column width
    max_width = max(len(item) for item in items)
    col_width = max_width + 4
    
    # Print in columns
    for i, item in enumerate(items):
        if i > 0 and i % columns == 0:
            print()
        print(f"{item:<{col_width}}", end='')
    print()
