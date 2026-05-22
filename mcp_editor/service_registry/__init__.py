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

Adding a New Language:
    1. Create a new package: service_registry/{language}/
    2. Implement AbstractServiceScanner in scanner_adapter.py
    3. Implement AbstractTypeExtractor in types_adapter.py
    4. Register in __init__.py using ScannerRegistry.register()
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

# Backward compatibility aliases
from .python.decorator import mcp_service, MCP_SERVICE_REGISTRY

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
]
