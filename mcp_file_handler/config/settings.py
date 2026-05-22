"""Application settings and configuration."""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional


class Settings:
    """Application settings manager."""

    # Default settings
    DEFAULTS = {
        # Paths
        'temp_dir': '/tmp/mcp_file_handler',
        'output_dir': './output',

        # Metadata storage
        'metadata_storage': 'sqlite',  # 'sqlite' or 'json'
        'metadata_path': 'metadata.db',

        # OCR settings
        'ocr_lang': 'eng',  # Tesseract language
        'ocr_preprocess': True,  # Preprocess images for better OCR

        # OneDrive settings
        'onedrive_temp_dir': '/tmp/onedrive_downloads',
        'onedrive_recursive': True,

        # Logging
        'log_level': 'INFO',
        'log_file': None,

        # Conversion settings
        'pdf_use_ocr': False,  # Use OCR for scanned PDFs
        'excel_include_formulas': False,  # Include formulas in Excel extraction

        # File size limits (in MB)
        'max_file_size': 100,
        'max_total_size': 500,

        # Processing
        'parallel_processing': False,
        'max_workers': 4
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize settings.

        Args:
            config: Optional configuration dictionary
        """
        self.config = self.DEFAULTS.copy()

        # Load from environment variables
        self._load_from_env()

        # Load from config file if exists
        self._load_from_file()

        # Override with provided config
        if config:
            self.config.update(config)

        # Ensure directories exist
        self._create_directories()

    def _load_from_env(self):
        """Load settings from environment variables."""
        env_mappings = {
            'MCP_ATTACHMENT_TEMP_DIR': 'temp_dir',
            'MCP_ATTACHMENT_OUTPUT_DIR': 'output_dir',
            'MCP_ATTACHMENT_METADATA_STORAGE': 'metadata_storage',
            'MCP_ATTACHMENT_METADATA_PATH': 'metadata_path',
            'MCP_ATTACHMENT_OCR_LANG': 'ocr_lang',
            'MCP_ATTACHMENT_LOG_LEVEL': 'log_level',
            'MCP_ATTACHMENT_LOG_FILE': 'log_file',
            'MCP_ATTACHMENT_MAX_FILE_SIZE': 'max_file_size',
            'MCP_ATTACHMENT_MAX_WORKERS': 'max_workers'
        }

        for env_var, config_key in env_mappings.items():
            value = os.environ.get(env_var)
            if value:
                # Convert numeric values
                if config_key in ['max_file_size', 'max_total_size', 'max_workers']:
                    try:
                        value = int(value)
                    except ValueError:
                        continue
                # Convert boolean values
                elif config_key in ['ocr_preprocess', 'pdf_use_ocr',
                                     'excel_include_formulas', 'parallel_processing',
                                     'onedrive_recursive']:
                    value = value.lower() in ['true', '1', 'yes']

                self.config[config_key] = value

    def _load_from_file(self):
        """Load settings from config file."""
        config_paths = [
            Path.home() / '.mcp_file_handler' / 'config.json',
            Path('./config.json'),
            Path('./mcp_file_handler.json')
        ]

        for config_path in config_paths:
            if config_path.exists():
                try:
                    with open(config_path, 'r') as f:
                        file_config = json.load(f)
                        self.config.update(file_config)
                        break
                except Exception:
                    pass

    def _create_directories(self):
        """Create necessary directories."""
        dirs_to_create = [
            self.config['temp_dir'],
            self.config['output_dir'],
            self.config['onedrive_temp_dir']
        ]

        for dir_path in dirs_to_create:
            if dir_path:
                Path(dir_path).mkdir(parents=True, exist_ok=True)

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value
        """
        return self.config.get(key, default)

    def set(self, key: str, value: Any):
        """Set configuration value.

        Args:
            key: Configuration key
            value: Configuration value
        """
        self.config[key] = value

    def update(self, config: Dict[str, Any]):
        """Update multiple configuration values.

        Args:
            config: Dictionary of configuration values
        """
        self.config.update(config)

    def save_to_file(self, file_path: str):
        """Save configuration to file.

        Args:
            file_path: Path to save configuration
        """
        with open(file_path, 'w') as f:
            json.dump(self.config, f, indent=2)

    def validate(self) -> Dict[str, Any]:
        """Validate configuration.

        Returns:
            Validation results with warnings and errors
        """
        results = {
            'valid': True,
            'warnings': [],
            'errors': []
        }

        # Check file size limits
        if self.config['max_file_size'] <= 0:
            results['errors'].append('max_file_size must be positive')
            results['valid'] = False

        # Check storage type
        if self.config['metadata_storage'] not in ['sqlite', 'json']:
            results['errors'].append('metadata_storage must be sqlite or json')
            results['valid'] = False

        # Check log level
        valid_log_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if self.config['log_level'].upper() not in valid_log_levels:
            results['warnings'].append(f'Invalid log_level, using INFO')
            self.config['log_level'] = 'INFO'

        # Check OCR language
        if not self.config['ocr_lang']:
            results['warnings'].append('No OCR language specified, using English')
            self.config['ocr_lang'] = 'eng'

        return results

    def __getitem__(self, key: str) -> Any:
        """Get configuration value using subscript notation.

        Args:
            key: Configuration key

        Returns:
            Configuration value
        """
        return self.config[key]

    def __setitem__(self, key: str, value: Any):
        """Set configuration value using subscript notation.

        Args:
            key: Configuration key
            value: Configuration value
        """
        self.config[key] = value