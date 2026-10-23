"""Application settings and configuration.

mode 0 (기본): DEFAULTS → 환경변수(`MCP_ATTACHMENT_*`) → 홈/CWD config 파일 → 생성자 config
순서로 덮어쓴다(기존 동작).

mode 1 (`MS365_MULTI_USER=1`, spec/spec_멀티유저.md ②-7.4):
    - 경로 키(`PATH_KEYS`)는 **사용자 경로로 고정**된다 — output → `files/output/`,
      temp → `files/tmp/`, 다운로드 → `files/downloads/file_handler/`,
      metadata → `db/metadata.db`(SQLite 고정), 로그 파일 없음.
    - 경로를 바꾸려는 환경변수·홈/CWD config 파일·config 인자는 **조용히 무시하지 않고**
      오류다. 기동 시 `validate_multi_user_config()` 가 `StartupConfigError` 로 서버를 막고,
      서비스 생성 시 `Settings` 가 `config_error` 로 한 번 더 막는다.
    - 자원 상한(`limits.LIMIT_DEFAULTS` 의 키)은 기본값이 천장이다 — 낮출 수만 있다.
    - 디렉터리를 만들지 않는다(서비스 풀의 `ensure_user_dirs` 가 만든다).
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

from mcp_common.security_contracts import ErrorCode, SecurityError, StartupConfigError
from mcp_common.security_policy import multi_user_enabled

from ..limits import LIMIT_DEFAULTS, pin_limits

#: mode 1 에서 사용자 경로로 고정되는 키 — 다른 출처로 바꿀 수 없다.
PATH_KEYS = (
    'temp_dir',
    'output_dir',
    'onedrive_temp_dir',
    'download_dir',
    'metadata_path',
    'log_file',
)

#: 경로 키에 대응하는 환경변수 (mode 1 에서 값이 있으면 기동 거부)
PATH_ENV = (
    'MCP_ATTACHMENT_TEMP_DIR',
    'MCP_ATTACHMENT_OUTPUT_DIR',
    'MCP_ATTACHMENT_METADATA_PATH',
    'MCP_ATTACHMENT_LOG_FILE',
)
STORAGE_ENV = 'MCP_ATTACHMENT_METADATA_STORAGE'

# 운영자 메시지에도 절대경로(서비스 계정 홈)를 싣지 않도록 표시용 이름을 따로 둔다
_CONFIG_LABELS = ('~/.mcp_file_handler/config.json', './config.json', './mcp_file_handler.json')


def config_file_candidates() -> List[Path]:
    """mode 0 이 읽는 홈/CWD config 파일 후보 (먼저 발견된 1개를 쓴다)."""
    return [
        Path.home() / '.mcp_file_handler' / 'config.json',
        Path('./config.json'),
        Path('./mcp_file_handler.json'),
    ]


def _mapping_problems(source: str, data: Any) -> List[str]:
    if not isinstance(data, dict):
        return [f"{source} 는 JSON 객체여야 합니다."]
    problems: List[str] = []
    bad = sorted(key for key in data if key in PATH_KEYS)
    if bad:
        problems.append(f"{source} 가 경로 설정({', '.join(bad)})을 바꿉니다.")
    storage = data.get('metadata_storage', 'sqlite')
    if str(storage).strip().lower() != 'sqlite':
        problems.append(f"{source} 의 metadata_storage 는 sqlite 여야 합니다.")
    return problems


def multi_user_config_problems(config: Optional[Dict[str, Any]] = None) -> List[str]:
    """mode 1 과 충돌하는 FileHandler 설정 목록 (경로 확장·JSON 저장소)."""
    problems: List[str] = []
    for env in PATH_ENV:
        if os.environ.get(env, '').strip():
            problems.append(f"{env} 는 멀티유저 모드와 함께 쓸 수 없습니다 (설정 해제 필요).")
    storage = os.environ.get(STORAGE_ENV, '').strip().lower()
    if storage and storage != 'sqlite':
        problems.append(f"{STORAGE_ENV}={storage} - 멀티유저 모드는 SQLite 저장소만 허용합니다.")
    for label, path in zip(_CONFIG_LABELS, config_file_candidates()):
        if not path.exists():
            continue
        source = f"FileHandler config 파일({label})"
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:  # 내용을 알 수 없으면 경로 키가 없다고 가정하지 않는다
            problems.append(f"{source} 을 해석할 수 없습니다.")
            continue
        problems.extend(_mapping_problems(source, data))
    if config:
        problems.extend(_mapping_problems("FileHandler config 인자", config))
    return problems


def validate_multi_user_config() -> None:
    """mode 1 기동 검사. 위반이 있으면 `StartupConfigError` — 서버를 띄우지 않는다 (F07)."""
    if not multi_user_enabled():
        return
    problems = multi_user_config_problems()
    if problems:
        raise StartupConfigError(
            "[file_handler] 멀티유저 기동 거부:\n- " + "\n- ".join(problems)
        )


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

        # Resource limits (max_workers 포함) — 단위·적용 지점은 mcp_file_handler/limits.py (R09)
        **LIMIT_DEFAULTS,

        # Processing
        'parallel_processing': False,
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None, *, paths: Any = None):
        """Initialize settings.

        Args:
            config: Optional configuration dictionary
            paths: mode 1 의 `UserPaths` (필수). mode 0 에서는 쓰지 않는다.
        """
        self.config = self.DEFAULTS.copy()

        if multi_user_enabled():
            self._init_multi_user(config, paths)
            return

        # Load from environment variables
        self._load_from_env()

        # Load from config file if exists
        self._load_from_file()

        # Override with provided config
        if config:
            self.config.update(config)

        # Ensure directories exist
        self._create_directories()

    def _init_multi_user(self, config: Optional[Dict[str, Any]], paths: Any) -> None:
        if paths is None:
            raise SecurityError(ErrorCode.CONFIG_ERROR, "멀티유저 설정에는 사용자 경로가 필요합니다.")
        problems = multi_user_config_problems(config)
        if problems:
            raise SecurityError(
                ErrorCode.CONFIG_ERROR, "FileHandler 멀티유저 설정 위반: " + " ".join(problems)
            )
        # 위 검사를 통과했으므로 아래 출처에는 경로 키가 없다 — 경로 외 설정만 반영된다.
        self._load_from_env()
        self._load_from_file()
        if config:
            self.config.update(config)
        self.config.update({
            'temp_dir': str(paths.tmp),
            'onedrive_temp_dir': str(paths.tmp),
            'output_dir': str(paths.output),
            'download_dir': str(paths.downloads_for('file_handler')),
            'metadata_storage': 'sqlite',
            'metadata_path': str(paths.metadata_db),
            'log_file': None,
        })
        # 자원 상한은 기본값이 천장이다 — 환경변수·config 로 낮출 수는 있어도 넓힐 수 없다 (R09)
        pin_limits(self.config)

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
            'MCP_ATTACHMENT_MAX_TOTAL_SIZE': 'max_total_size',
            'MCP_ATTACHMENT_MAX_DOWNLOAD_FILES': 'max_download_files',
            'MCP_ATTACHMENT_MAX_FOLDER_DEPTH': 'max_folder_depth',
            'MCP_ATTACHMENT_MAX_OUTPUT_CHARS': 'max_output_chars',
            'MCP_ATTACHMENT_CONVERSION_TIMEOUT': 'conversion_timeout',
            'MCP_ATTACHMENT_MAX_WORKERS': 'max_workers'
        }

        for env_var, config_key in env_mappings.items():
            value = os.environ.get(env_var)
            if value:
                # Convert numeric values
                if config_key in LIMIT_DEFAULTS:
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
        for config_path in config_file_candidates():
            if config_path.exists():
                try:
                    with open(config_path, 'r') as f:
                        file_config = json.load(f)
                        self.config.update(file_config)
                        break
                except Exception:
                    # mode 0 기존 동작. mode 1 은 multi_user_config_problems() 가 먼저 거부한다.
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
