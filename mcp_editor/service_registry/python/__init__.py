"""Python language support for service registry.

This package provides Python-specific implementations for:
- Service scanning (@mcp_service decorator detection)
- Type extraction (Pydantic BaseModel, dataclass)
- Interface-compliant adapters for the registry system
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
from .decorator import mcp_service, MCP_SERVICE_REGISTRY

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
    # Interface-based exports
    "PythonServiceScanner",
    "PythonTypeExtractor",
    "PythonTypeExporter",
]
