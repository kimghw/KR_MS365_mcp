"""JavaScript language support for service registry.

This package provides JavaScript-specific implementations for:
- Service scanning (JSDoc @mcp_service, esprima decorator detection)
- Type extraction (Sequelize models)
- Interface-compliant adapters for the registry system
"""

# Legacy exports (backward compatibility)
from .scanner import (
    ESPRIMA_AVAILABLE,
    JSDOC_TYPE_MAP,
    find_mcp_services_in_js_file,
    find_jsdoc_mcp_services_in_js_file,
)
from .types import (
    scan_js_project_types,
    export_js_types_property,
    extract_sequelize_models_from_file,
    map_sequelize_to_json_type,
)

# New interface-based exports
from .scanner_adapter import JavaScriptServiceScanner
from .types_adapter import JavaScriptTypeExtractor, JavaScriptTypeExporter

__all__ = [
    # Legacy exports
    "ESPRIMA_AVAILABLE",
    "JSDOC_TYPE_MAP",
    "find_mcp_services_in_js_file",
    "find_jsdoc_mcp_services_in_js_file",
    "scan_js_project_types",
    "export_js_types_property",
    "extract_sequelize_models_from_file",
    "map_sequelize_to_json_type",
    # Interface-based exports
    "JavaScriptServiceScanner",
    "JavaScriptTypeExtractor",
    "JavaScriptTypeExporter",
]
