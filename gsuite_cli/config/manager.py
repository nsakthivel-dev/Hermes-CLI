"""
Configuration manager for GSuite CLI settings
"""

import os
import json
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, Union, List
from dataclasses import dataclass, asdict, field

from ..utils.formatters import print_info, print_error, print_success

@dataclass
class CalendarConfig:
    """Calendar-specific configuration"""
    default_calendar: str = 'primary'
    default_timezone: str = 'UTC'
    default_event_duration: int = 60  # minutes
    date_format: str = '%Y-%m-%d %H:%M'
    show_declined_events: bool = False
    aliases: Dict[str, str] = field(default_factory=dict)

@dataclass
class GmailConfig:
    """Gmail-specific configuration"""
    default_max_results: int = 50
    show_snippets: bool = True
    auto_mark_read: bool = False
    default_format: str = 'table'
    signature: str = ''

@dataclass
class SheetsConfig:
    """Sheets-specific configuration"""
    default_range: str = 'A1:Z100'
    default_header_row: int = 1
    auto_trim: bool = True
    csv_delimiter: str = ','
    default_format: str = 'table'

@dataclass
class AIConfig:
    """AI configuration"""
    gemini_api_key: str = ''
    model_name: str = 'gemini-3.6-flash'
    ai_enabled: bool = True

    def __post_init__(self):
        if not self.gemini_api_key:
            self.gemini_api_key = os.environ.get('HERMES_GEMINI_API_KEY') or os.environ.get('GEMINI_API_KEY', '')


@dataclass
class NotificationConfig:
    """Notification configuration"""
    smtp_server: str = ''
    smtp_port: int = 587
    smtp_username: str = ''
    smtp_password: str = ''
    use_tls: bool = True
    from_email: str = ''
    cli_enabled: bool = True
    desktop_enabled: bool = True
    email_enabled: bool = False


@dataclass
class UIConfig:
    """UI/UX configuration"""
    default_output_format: str = 'table'
    table_style: str = 'grid'
    show_progress_bars: bool = True
    color_output: bool = True
    compact_mode: bool = False
    timestamp_format: str = '%Y-%m-%d %H:%M:%S'

@dataclass
class AppConfig:
    """Main application configuration"""
    calendar: CalendarConfig
    gmail: GmailConfig
    sheets: SheetsConfig
    ui: UIConfig
    ai: AIConfig
    notifications: NotificationConfig
    debug_mode: bool = False
    cache_enabled: bool = True
    cache_ttl: int = 300  # seconds
    cache_dir: Optional[str] = None  # Use default
    
    def __post_init__(self):
        """Ensure nested config objects are properly initialized"""
        if not isinstance(self.calendar, CalendarConfig):
            self.calendar = CalendarConfig(**self.calendar)
        if not isinstance(self.gmail, GmailConfig):
            self.gmail = GmailConfig(**self.gmail)
        if not isinstance(self.sheets, SheetsConfig):
            self.sheets = SheetsConfig(**self.sheets)
        if not isinstance(self.ui, UIConfig):
            self.ui = UIConfig(**self.ui)
        if not isinstance(self.ai, AIConfig):
            self.ai = AIConfig(**self.ai)
        if not isinstance(self.notifications, NotificationConfig):
            self.notifications = NotificationConfig(**self.notifications)


class ConfigManager:
    """Manages application configuration"""
    
    def __init__(self, config_dir: Optional[str] = None):
        self.config_dir = Path(config_dir) if config_dir else Path.home() / '.config' / 'gsuite-cli'
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self.config_file = self.config_dir / 'config.yaml'
        self.config_file_json = self.config_dir / 'config.json'
        
        self._config = None
        self._load_config()
    
    def _load_config(self) -> None:
        """Load configuration from file"""
        # Try YAML first, then JSON
        config_file = None
        config_data = None
        
        if self.config_file.exists():
            config_file = self.config_file
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config_data = yaml.safe_load(f)
            except Exception as e:
                print_error(f"Error reading YAML config: {e}")
        
        elif self.config_file_json.exists():
            config_file = self.config_file_json
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
            except Exception as e:
                print_error(f"Error reading JSON config: {e}")
        
        if config_data:
            try:
                # Helper to filter out unexpected keys for dataclasses
                def filter_dataclass_keys(cls, data):
                    if not isinstance(data, dict):
                        return data
                    valid_keys = cls.__dataclass_fields__.keys()
                    return {k: v for k, v in data.items() if k in valid_keys}

                # Ensure all required sections exist in config_data
                for section_name, cls in [
                    ('calendar', CalendarConfig), 
                    ('gmail', GmailConfig), 
                    ('sheets', SheetsConfig), 
                    ('ui', UIConfig), 
                    ('ai', AIConfig),
                    ('notifications', NotificationConfig)
                ]:
                    if section_name not in config_data:
                        config_data[section_name] = {}
                    else:
                        config_data[section_name] = filter_dataclass_keys(cls, config_data[section_name])
                
                # Filter top level AppConfig keys
                valid_app_keys = AppConfig.__dataclass_fields__.keys()
                filtered_app_data = {k: v for k, v in config_data.items() if k in valid_app_keys}
                
                self._config = AppConfig(**filtered_app_data)
                print_info(f"Loaded configuration from {config_file}")
            except Exception as e:
                print_error(f"Error parsing configuration: {e}")
                print_info("Using default configuration")
                self._config = self._get_default_config()
        else:
            print_info("No configuration file found, using defaults")
            self._config = self._get_default_config()
            self.save_config()
    
    def _get_default_config(self) -> AppConfig:
        """Get default configuration"""
        return AppConfig(
            calendar=CalendarConfig(),
            gmail=GmailConfig(),
            sheets=SheetsConfig(),
            ui=UIConfig(),
            ai=AIConfig(),
            notifications=NotificationConfig()
        )
    
    def save_config(self, format: str = 'yaml') -> bool:
        """Save configuration to file"""
        try:
            config_dict = asdict(self._config)
            
            if format.lower() == 'yaml':
                config_file = self.config_file
                with open(config_file, 'w', encoding='utf-8') as f:
                    yaml.dump(config_dict, f, default_flow_style=False, indent=2)
            else:
                config_file = self.config_file_json
                with open(config_file, 'w', encoding='utf-8') as f:
                    json.dump(config_dict, f, indent=2)
            
            print_success(f"Configuration saved to {config_file}")
            return True
        except Exception as e:
            print_error(f"Error saving configuration: {e}")
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value using dot notation"""
        try:
            keys = key.split('.')
            value = self._config
            
            for k in keys:
                if hasattr(value, k):
                    value = getattr(value, k)
                elif isinstance(value, dict) and k in value:
                    value = value[k]
                else:
                    value = default
                    break
            
            if key == 'ai.gemini_api_key' and not value:
                env_val = os.environ.get('HERMES_GEMINI_API_KEY') or os.environ.get('GEMINI_API_KEY', '')
                if env_val:
                    return env_val

            return value if value is not None else default
        except Exception:
            return default
    
    def set(self, key: str, value: Any) -> bool:
        """Set configuration value using dot notation"""
        try:
            keys = key.split('.')
            obj = self._config
            
            # Navigate to parent object
            for k in keys[:-1]:
                if hasattr(obj, k):
                    obj = getattr(obj, k)
                else:
                    print_error(f"Invalid configuration key: {key}")
                    return False
            
            # Set the value
            setattr(obj, keys[-1], value)
            return True
        except Exception as e:
            print_error(f"Error setting configuration: {e}")
            return False
    
    def get_all(self) -> Dict[str, Any]:
        """Get all configuration as dictionary"""
        return asdict(self._config)
    
    def reset_to_defaults(self) -> bool:
        """Reset configuration to defaults"""
        try:
            self._config = self._get_default_config()
            print_success("Configuration reset to defaults")
            return True
        except Exception as e:
            print_error(f"Error resetting configuration: {e}")
            return False
    
    def get_section(self, section: str) -> Optional[Dict[str, Any]]:
        """Get a configuration section"""
        if hasattr(self._config, section):
            return asdict(getattr(self._config, section))
        return None
    
    def export_config(self, file_path: str, format: str = 'yaml') -> bool:
        """Export configuration to specified file"""
        try:
            config_dict = asdict(self._config)
            export_path = Path(file_path)
            
            if format.lower() == 'yaml':
                with open(export_path, 'w', encoding='utf-8') as f:
                    yaml.dump(config_dict, f, default_flow_style=False, indent=2)
            else:
                with open(export_path, 'w', encoding='utf-8') as f:
                    json.dump(config_dict, f, indent=2)
            
            print_success(f"Configuration exported to {export_path}")
            return True
        except Exception as e:
            print_error(f"Error exporting configuration: {e}")
            return False
    
    def import_config(self, file_path: str) -> bool:
        """Import configuration from specified file"""
        try:
            import_path = Path(file_path)
            if not import_path.exists():
                print_error(f"File not found: {file_path}")
                return False
            
            if import_path.suffix.lower() in ['.yaml', '.yml']:
                with open(import_path, 'r', encoding='utf-8') as f:
                    config_data = yaml.safe_load(f)
            else:
                with open(import_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
            
            self._config = AppConfig(**config_data)
            print_success(f"Configuration imported from {import_path}")
            return True
        except Exception as e:
            print_error(f"Error importing configuration: {e}")
            return False
    
    @property
    def config(self) -> AppConfig:
        """Get the full configuration object"""
        return self._config
    
    @property
    def data_dir(self) -> Path:
        """Directory for persistent data such as databases"""
        return self.config_dir
    
    def validate_config(self) -> List[str]:
        """Validate configuration and return list of issues"""
        issues = []
        
        # Validate calendar config
        if self._config.calendar.default_event_duration <= 0:
            issues.append("calendar.default_event_duration must be positive")
        
        # Validate gmail config
        if self._config.gmail.default_max_results <= 0:
            issues.append("gmail.default_max_results must be positive")
        
        # Validate sheets config
        if self._config.sheets.default_header_row <= 0:
            issues.append("sheets.default_header_row must be positive")
        
        # Validate UI config
        valid_formats = ['table', 'json', 'csv']
        if self._config.ui.default_output_format not in valid_formats:
            issues.append(f"ui.default_output_format must be one of {valid_formats}")
        
        return issues
