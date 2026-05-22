"""
Tool Editor Web - Modular Package

이 패키지는 MCP Tool Editor Web 인터페이스의 핵심 모듈을 포함합니다.

모듈 구조:
- config: 설정 관리 (프로필, 경로)
- schema_utils: JSON 스키마 처리
- backup_utils: 백업 관리
- tool_loader: 도구 정의 로딩
- tool_saver: 도구 정의 저장
- service_registry: 서비스 레지스트리
- profile_management: 프로필 재사용/삭제
- routes/: Flask 라우트 모듈들
"""

from .config import (
    BASE_DIR,
    ROOT_DIR,
    CONFIG_PATH,
    DEFAULT_PROFILE,
    JINJA_DIR,
    JINJA_PYTHON_DIR,
    JINJA_JS_DIR,
    JINJA_COMMON_DIR,
    SERVER_TEMPLATES,
    DEFAULT_SERVER_TEMPLATE,
    GENERATOR_SCRIPT_PATH,
    EDITOR_CONFIG_TEMPLATE,
    EDITOR_CONFIG_GENERATOR,
    get_profile_config,
    list_profile_names,
    resolve_paths,
    ensure_dirs,
    discover_mcp_modules,
    load_generator_module,
)

from .schema_utils import (
    order_schema_fields,
    remove_defaults,
    clean_newlines_from_schema,
    ensure_target_params,
    convert_params_dict_to_list,
    convert_params_list_to_dict,
    is_all_none_defaults,
    prune_internal_properties,
)

from .backup_utils import (
    backup_file,
    cleanup_old_backups,
)

from .tool_loader import (
    load_tool_definitions,
    extract_service_factors,
    get_file_mtimes,
)

from .tool_saver import (
    save_tool_definitions,
)

from .service_registry import (
    SERVICE_SCAN_CACHE,
    load_services_for_server,
    scan_all_registries,
)

from .profile_management import (
    copy_yaml_templates,
    update_editor_config_for_reuse,
    create_server_project_folder,
    create_reused_profile,
    delete_mcp_profile,
)

from .tool_mover import ToolMover

__all__ = [
    # Config
    "BASE_DIR",
    "ROOT_DIR",
    "CONFIG_PATH",
    "DEFAULT_PROFILE",
    "JINJA_DIR",
    "JINJA_PYTHON_DIR",
    "JINJA_JS_DIR",
    "JINJA_COMMON_DIR",
    "SERVER_TEMPLATES",
    "DEFAULT_SERVER_TEMPLATE",
    "GENERATOR_SCRIPT_PATH",
    "EDITOR_CONFIG_TEMPLATE",
    "EDITOR_CONFIG_GENERATOR",
    "get_profile_config",
    "list_profile_names",
    "resolve_paths",
    "ensure_dirs",
    "discover_mcp_modules",
    "load_generator_module",
    # Schema utils
    "order_schema_fields",
    "remove_defaults",
    "clean_newlines_from_schema",
    "ensure_target_params",
    "convert_params_dict_to_list",
    "convert_params_list_to_dict",
    "is_all_none_defaults",
    "prune_internal_properties",
    # Backup utils
    "backup_file",
    "cleanup_old_backups",
    # Tool loader
    "load_tool_definitions",
    "extract_service_factors",
    "get_file_mtimes",
    # Tool saver
    "save_tool_definitions",
    # Service registry
    "SERVICE_SCAN_CACHE",
    "load_services_for_server",
    "scan_all_registries",
    # Profile management
    "copy_yaml_templates",
    "update_editor_config_for_reuse",
    "create_server_project_folder",
    "create_reused_profile",
    "delete_mcp_profile",
    # Tool mover
    "ToolMover",
]
