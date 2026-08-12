"""
Service Registry - Multi-language MCP service scanner and configuration generator.

This package provides functionality for:
- Scanning Python and JavaScript code for @mcp_service decorators
- Extracting type information from source code
- Generating editor configuration files
- Managing MCP service metadata
- Interface-based extensibility for adding new languages

Structure:
- interfaces.py: Abstract base classes and dataclasses for extensibility
- registry.py: Scanner and TypeExtractor registries (factory pattern)
- base.py: Common utilities (Language enum, detect_language, etc.)
- scanner.py: Unified scanner with re-exports from language-specific modules
- config_generator.py: Editor configuration generator
- meta_registry.py: Service metadata registry
- python/: Python-specific modules
    - scanner.py: Python AST scanner
    - scanner_adapter.py: Interface-compliant adapter
    - types.py: Python type extraction
    - types_adapter.py: Interface-compliant adapter
    - decorator.py: @mcp_service decorator
- javascript/: JavaScript-specific modules
    - scanner.py: JS/JSDoc scanner
    - scanner_adapter.py: Interface-compliant adapter
    - types.py: Sequelize type extraction
    - types_adapter.py: Interface-compliant adapter

- schema_normalize.py: 도구 정의(ToolSpec) 스키마 정규화 (SSOT)

Adding a New Language:
    1. Create a new package: service_registry/{language}/
    2. Implement AbstractServiceScanner in scanner_adapter.py
    3. Implement AbstractTypeExtractor in types_adapter.py
    4. Register in __init__.py using ScannerRegistry.register()


================================================================================
@mcp_service 데코레이터 정식(canonical) import 경로
================================================================================
도메인 서비스(mcp_outlook, mcp_calendar, mcp_teams, mcp_onedrive, mcp_onenote,
mcp_todo, mcp_file_handler ...)는 아래 **둘 중 하나**를 쓴다. 둘 다 동일한
객체를 가리킨다.

    # 권장 (짧은 경로 · 파이썬 모듈만 로드해서 가볍다)
    from mcp_editor.service_registry.python import mcp_service

    # 전체 경로 (구현 모듈을 직접 지정)
    from mcp_editor.service_registry.python.decorator import mcp_service

패키지 최상위에서도 re-export 하므로 다음도 동작한다. 다만 이 경로는
JavaScript 스캐너까지 함께 로드하므로 서비스 런타임에서는 권장하지 않는다.

    from mcp_editor.service_registry import mcp_service

폐기된 경로 (더 이상 존재하지 않는다 — 쓰면 ImportError):

    from mcp_editor.mcp_service_registry.mcp_service_decorator import mcp_service

  주의: `mcp_editor/mcp_service_registry/` 는 **패키지가 아니라 데이터 출력
  디렉터리**다 (registry_<server>.json 이 저장되는 곳). 이름이 비슷해서
  혼동하기 쉽지만 import 대상이 아니다.

--------------------------------------------------------------------------------
import 실패를 절대 조용히 삼키지 말 것
--------------------------------------------------------------------------------
과거에 도메인 서비스들이 아래처럼 ImportError 를 no-op 데코레이터로 대체했다:

    try:
        from <구경로> import mcp_service
    except ImportError:
        def mcp_service(*a, **kw):        # <-- 이렇게 하지 마라
            return lambda f: f

이러면 데코레이터가 조용히 사라져서 MCP_SERVICE_REGISTRY 가 비고, 그 결과
생성기가 도구를 하나도 찾지 못한 채 "성공"으로 끝난다. 실패가 생성 시점이
아니라 한참 뒤 런타임에 드러난다.

import 이 실패하면 그대로 터뜨리거나, 최소한 원인을 보존해서 다시 던져라:

    try:
        from mcp_editor.service_registry.python import mcp_service
    except ImportError as exc:
        raise ImportError(
            "mcp_editor.service_registry.python.mcp_service 를 import 하지 못했습니다. "
            "프로젝트 루트가 sys.path 에 있는지 확인하세요."
        ) from exc
"""

# =============================================================================
# Interfaces and Registry (new extensibility system)
# =============================================================================
from .interfaces import (
    # Data classes
    ParameterInfo,
    ServiceInfo,
    PropertyInfo,
    TypeInfo,
    # Abstract base classes
    AbstractServiceScanner,
    AbstractTypeExtractor,
    AbstractTypeExporter,
)
from .registry import (
    ScannerRegistry,
    TypeExtractorRegistry,
    register_all_default_scanners,
    register_all_default_extractors,
)

# =============================================================================
# Legacy exports (backward compatibility)
# =============================================================================
from .base import Language, detect_language, DEFAULT_SKIP_PARTS
from .scanner import (
    # Python scanning
    MCPServiceExtractor,
    extract_decorator_metadata,
    find_mcp_services_in_python_file,
    signature_from_parameters,
    # JavaScript scanning
    ESPRIMA_AVAILABLE,
    JSDOC_TYPE_MAP,
    find_mcp_services_in_js_file,
    find_jsdoc_mcp_services_in_js_file,
    # Scanning utilities
    scan_codebase_for_mcp_services,
    get_services_map,
    export_services_to_json,
)

# Type extraction modules (for direct access)
from .python import types as extract_types
from .javascript import types as extract_types_js

# =============================================================================
# @mcp_service 데코레이터 공개 심볼 (정식 경로는 모듈 docstring 참고)
# =============================================================================
from .python.decorator import (
    mcp_service,
    MCP_SERVICE_REGISTRY,
    get_mcp_service_info,
    list_mcp_services,
    generate_inputschema_from_service,
)

# =============================================================================
# 도구 정의(ToolSpec) 스키마 정규화 (SSOT)
# =============================================================================
from .schema_normalize import (
    normalize_input_schema,
    normalize_required,
    normalize_tool_list,
    convert_boolean_schema_to_enabled_disabled,
    collect_boolean_params,
    convert_enabled_to_bool,
    convert_bool_to_enabled,
    coerce_boolean_enums_for_schema,
    ENABLED,
    DISABLED,
    ENABLED_DISABLED_ENUM,
    BOOL_DESCRIPTION_SUFFIX,
)

# =============================================================================
# Interface-based implementations
# =============================================================================
from .python.scanner_adapter import PythonServiceScanner
from .python.types_adapter import PythonTypeExtractor
from .javascript.scanner_adapter import JavaScriptServiceScanner
from .javascript.types_adapter import JavaScriptTypeExtractor

# =============================================================================
# Auto-register default scanners
# =============================================================================
def _init_registry():
    """Initialize the registry with default scanners."""
    try:
        ScannerRegistry.register(PythonServiceScanner)
    except Exception:
        pass
    try:
        ScannerRegistry.register(JavaScriptServiceScanner)
    except Exception:
        pass
    try:
        TypeExtractorRegistry.register(PythonTypeExtractor)
    except Exception:
        pass
    try:
        TypeExtractorRegistry.register(JavaScriptTypeExtractor)
    except Exception:
        pass

_init_registry()

__all__ = [
    # Interfaces and Data Classes
    "ParameterInfo",
    "ServiceInfo",
    "PropertyInfo",
    "TypeInfo",
    "AbstractServiceScanner",
    "AbstractTypeExtractor",
    "AbstractTypeExporter",
    # Registry
    "ScannerRegistry",
    "TypeExtractorRegistry",
    # Interface implementations
    "PythonServiceScanner",
    "PythonTypeExtractor",
    "JavaScriptServiceScanner",
    "JavaScriptTypeExtractor",
    # Core utilities
    "Language",
    "detect_language",
    "DEFAULT_SKIP_PARTS",
    # Python scanning (legacy)
    "MCPServiceExtractor",
    "extract_decorator_metadata",
    "find_mcp_services_in_python_file",
    "signature_from_parameters",
    # JavaScript scanning (legacy)
    "ESPRIMA_AVAILABLE",
    "JSDOC_TYPE_MAP",
    "find_mcp_services_in_js_file",
    "find_jsdoc_mcp_services_in_js_file",
    # High-level functions
    "scan_codebase_for_mcp_services",
    "get_services_map",
    "export_services_to_json",
    # Type extraction modules
    "extract_types",
    "extract_types_js",
    # Decorator
    "mcp_service",
    "MCP_SERVICE_REGISTRY",
    "get_mcp_service_info",
    "list_mcp_services",
    "generate_inputschema_from_service",
    # Schema normalization (SSOT)
    "normalize_input_schema",
    "normalize_required",
    "normalize_tool_list",
    "convert_boolean_schema_to_enabled_disabled",
    "collect_boolean_params",
    "convert_enabled_to_bool",
    "convert_bool_to_enabled",
    "coerce_boolean_enums_for_schema",
    "ENABLED",
    "DISABLED",
    "ENABLED_DISABLED_ENUM",
    "BOOL_DESCRIPTION_SUFFIX",
]
