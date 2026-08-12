"""Python language support for service registry.

This package provides Python-specific implementations for:
- Service scanning (@mcp_service decorator detection)
- Type extraction (Pydantic BaseModel, dataclass)
- Interface-compliant adapters for the registry system

@mcp_service 데코레이터의 **권장 import 경로**가 여기다:

    from mcp_editor.service_registry.python import mcp_service

패키지 최상위(`mcp_editor.service_registry`)에서도 같은 객체를 re-export 하지만,
그쪽은 JavaScript 스캐너까지 함께 로드하므로 서비스 런타임에서는 이 경로가 가볍다.
자세한 내용(폐기된 경로, import 실패를 삼키면 안 되는 이유)은
`mcp_editor/service_registry/__init__.py` 의 docstring 참고.
"""

# Legacy exports (backward compatibility)
from .scanner import (
    MCPServiceExtractor,
    extract_decorator_metadata,
    find_mcp_services_in_python_file,
    signature_from_parameters,
)
from .types import (
    extract_class_properties,
    extract_single_class,
    scan_py_project_types,
    map_python_to_json_type,
    export_py_types_property,
)
from .decorator import (
    mcp_service,
    MCP_SERVICE_REGISTRY,
    get_mcp_service_info,
    list_mcp_services,
    generate_inputschema_from_service,
)

# New interface-based exports
from .scanner_adapter import PythonServiceScanner
from .types_adapter import PythonTypeExtractor, PythonTypeExporter

__all__ = [
    # Legacy exports
    "MCPServiceExtractor",
    "extract_decorator_metadata",
    "find_mcp_services_in_python_file",
    "signature_from_parameters",
    "extract_class_properties",
    "extract_single_class",
    "scan_py_project_types",
    "map_python_to_json_type",
    "export_py_types_property",
    "mcp_service",
    "MCP_SERVICE_REGISTRY",
    "get_mcp_service_info",
    "list_mcp_services",
    "generate_inputschema_from_service",
    # Interface-based exports
    "PythonServiceScanner",
    "PythonTypeExtractor",
    "PythonTypeExporter",
]
