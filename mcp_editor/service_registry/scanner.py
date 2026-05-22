"""
MCP Service Scanner - Multi-language code analyzer for @mcp_service decorators.

This module scans Python and JavaScript source code to find functions decorated
with @mcp_service (Python) or @McpService (JavaScript), extracts their signatures
and metadata, and exports them to JSON format.

Supported languages:
- Python (.py): Uses built-in ast module
- JavaScript (.js, .mjs): Uses esprima parser
- TypeScript (.ts): Uses esprima parser (basic support)

Core functionality:
- Language detection based on file extension
- AST parsing for each language
- Function signature extraction (parameters, types, defaults)
- Decorator metadata extraction (server_name, tool_name, etc.)
- JSON export for web editor consumption

This module serves as the main entry point and re-exports functionality from:
- scanner_base: Common utilities (Language, detect_language, etc.)
- scanner_python: Python-specific scanning (MCPServiceExtractor, etc.)
- scanner_javascript: JavaScript-specific scanning (JSDoc, esprima, etc.)
"""

from __future__ import annotations

import ast
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# =============================================================================
# Re-exports from scanner_base
# =============================================================================
from .base import (
    Language,
    DEFAULT_SKIP_PARTS,
    detect_language,
    _should_skip,
    _is_class_type,
    _parse_type_info,
)

# =============================================================================
# Re-exports from scanner_python
# =============================================================================
from .python.scanner import (
    extract_decorator_metadata,
    _annotation_to_str,
    _default_to_value,
    _extract_parameters,
    signature_from_parameters,
    MCPServiceExtractor,
    find_mcp_services_in_python_file,
)

# =============================================================================
# Re-exports from scanner_javascript
# =============================================================================
from .javascript.scanner import (
    ESPRIMA_AVAILABLE,
    JSDOC_TYPE_MAP,
    _map_jsdoc_type,
    _extract_js_decorator_metadata,
    _extract_js_parameters,
    _js_signature_from_parameters,
    find_mcp_services_in_js_file,
    _parse_jsdoc_block,
    _find_function_after_jsdoc,
    find_jsdoc_mcp_services_in_js_file,
    _parse_js_literal,
    _process_js_node,
    _check_js_mcp_service,
)

# Type extractor modules
from .python import types as extract_types
from .javascript import types as extract_types_js


# =============================================================================
# Public API - Re-export all for backward compatibility
# =============================================================================
__all__ = [
    # From scanner_base
    "Language",
    "DEFAULT_SKIP_PARTS",
    "detect_language",
    "_should_skip",
    "_is_class_type",
    "_parse_type_info",
    # From scanner_python
    "extract_decorator_metadata",
    "_annotation_to_str",
    "_default_to_value",
    "_extract_parameters",
    "signature_from_parameters",
    "MCPServiceExtractor",
    "find_mcp_services_in_python_file",
    # From scanner_javascript
    "ESPRIMA_AVAILABLE",
    "JSDOC_TYPE_MAP",
    "_map_jsdoc_type",
    "_extract_js_decorator_metadata",
    "_extract_js_parameters",
    "_js_signature_from_parameters",
    "find_mcp_services_in_js_file",
    "_parse_jsdoc_block",
    "_find_function_after_jsdoc",
    "find_jsdoc_mcp_services_in_js_file",
    "_parse_js_literal",
    "_process_js_node",
    "_check_js_mcp_service",
    # Main functions defined in this module
    "find_mcp_services_in_file",
    "scan_codebase_for_mcp_services",
    "get_signatures_by_name",
    "get_services_map",
    # Import tracking functions
    "_parse_imports",
    "_resolve_module_to_file",
    "resolve_class_file",
    "collect_referenced_types",
    "export_types_property",
    # Main export function
    "export_services_to_json",
]


# =============================================================================
# Unified File Scanner
# =============================================================================

def find_mcp_services_in_file(file_path: str) -> Dict[str, Dict[str, Any]]:
    """Find all @mcp_service decorated functions in a file (Python or JavaScript)."""
    path = Path(file_path)
    language = detect_language(path)

    if language == Language.PYTHON:
        return find_mcp_services_in_python_file(file_path)
    elif language in (Language.JAVASCRIPT, Language.TYPESCRIPT):
        return find_mcp_services_in_js_file(file_path)
    else:
        return {}


def scan_codebase_for_mcp_services(
    base_dir: str,
    server_name: Optional[str] = None,
    exclude_examples: bool = True,
    skip_parts: tuple[str, ...] = DEFAULT_SKIP_PARTS,
    languages: Optional[List[str]] = None,
    include_jsdoc_pattern: bool = True,
) -> Dict[str, Dict[str, Any]]:
    """Scan a codebase recursively for @mcp_service decorated functions.

    Args:
        base_dir: Base directory to scan
        server_name: Optional filter by server name
        exclude_examples: Skip example files
        skip_parts: Directory parts to skip
        languages: List of languages to scan ("python", "javascript", "typescript")
                   If None, scans all supported languages
        include_jsdoc_pattern: Also scan for JSDoc @mcp_service comments in JS files

    Returns:
        Dictionary of service name to service info
    """
    all_services: Dict[str, Dict[str, Any]] = {}

    # Determine which file extensions to scan
    extensions = []
    if languages is None:
        # Scan all supported languages
        extensions = [".py", ".js", ".mjs", ".ts", ".tsx"]
    else:
        if "python" in languages:
            extensions.append(".py")
        if "javascript" in languages:
            extensions.extend([".js", ".mjs"])
        if "typescript" in languages:
            extensions.extend([".ts", ".tsx"])

    # Scan files for each extension
    for ext in extensions:
        pattern = f"*{ext}"
        for source_file in Path(base_dir).rglob(pattern):
            if _should_skip(source_file, skip_parts):
                continue
            if exclude_examples and "example" in str(source_file).lower():
                continue

            file_str = str(source_file)

            # For Python: Use AST-based decorator scanning
            if ext == ".py":
                services = find_mcp_services_in_python_file(file_str)
            # For JavaScript/TypeScript: Use JSDoc scanning
            elif ext in (".js", ".mjs", ".ts", ".tsx"):
                services = {}
                # JSDoc pattern scanning (primary method for JS)
                if include_jsdoc_pattern:
                    jsdoc_services = find_jsdoc_mcp_services_in_js_file(file_str)
                    services.update(jsdoc_services)
                # Also try esprima decorator-based scanning (if available)
                esprima_services = find_mcp_services_in_js_file(file_str)
                # Merge, preferring JSDoc if both exist
                for name, info in esprima_services.items():
                    if name not in services:
                        services[name] = info
            else:
                services = {}

            if server_name:
                services = {
                    name: info for name, info in services.items()
                    if info.get("metadata", {}).get("server_name") == server_name
                }

            all_services.update(services)

    return all_services


def get_signatures_by_name(base_dir: str, server_name: Optional[str] = None) -> Dict[str, str]:
    """Return {service_name: signature_string} map."""
    services = scan_codebase_for_mcp_services(base_dir, server_name)
    return {name: info["signature"] for name, info in services.items()}


def get_services_map(base_dir: str, server_name: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Return {service_name: {signature, parameters, metadata, ...}} map."""
    return scan_codebase_for_mcp_services(base_dir, server_name)


# =============================================================================
# Import Tracking for Type Resolution
# =============================================================================

def _parse_imports(file_path: str) -> Dict[str, str]:
    """Parse import statements from a Python file.

    Returns:
        Dictionary mapping class/module names to their import source.
        e.g., {"FilterParams": "outlook_types", "Optional": "typing"}
    """
    imports: Dict[str, str] = {}

    try:
        content = Path(file_path).read_text(encoding="utf-8")
        tree = ast.parse(content)

        for node in ast.walk(tree):
            # from module import name1, name2
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    name = alias.asname or alias.name
                    imports[name] = module

            # import module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name
                    imports[name] = alias.name

    except Exception as exc:
        print(f"Warning: Could not parse imports from {file_path}: {exc}")

    return imports


def _resolve_module_to_file(module_name: str, source_file: str) -> Optional[str]:
    """Resolve a module name to an actual file path.

    Args:
        module_name: Module name (e.g., "outlook_types", ".types", "..common")
        source_file: The file that contains the import statement

    Returns:
        Absolute path to the module file, or None if not found
    """
    source_dir = Path(source_file).parent

    # Handle relative imports
    if module_name.startswith("."):
        # Count leading dots
        dots = 0
        for char in module_name:
            if char == ".":
                dots += 1
            else:
                break

        # Go up directories based on dot count
        relative_module = module_name[dots:]
        target_dir = source_dir
        for _ in range(dots - 1):
            target_dir = target_dir.parent

        # Convert module path to file path
        if relative_module:
            module_path = relative_module.replace(".", os.sep)
            candidate = target_dir / f"{module_path}.py"
        else:
            # Just dots, no module name after
            candidate = target_dir / "__init__.py"

        if candidate.exists():
            return str(candidate.resolve())
        return None

    # Handle absolute imports - search in same directory and parent directories
    module_path = module_name.replace(".", os.sep)

    # Check same directory
    candidate = source_dir / f"{module_path}.py"
    if candidate.exists():
        return str(candidate.resolve())

    # Check parent directory (common pattern: mcp_outlook/outlook_types.py)
    candidate = source_dir.parent / f"{module_path}.py"
    if candidate.exists():
        return str(candidate.resolve())

    # Check as package
    candidate = source_dir / module_path / "__init__.py"
    if candidate.exists():
        return str(candidate.resolve())

    return None


def resolve_class_file(class_name: str, source_file: str) -> Optional[str]:
    """Find the file where a class is defined.

    Args:
        class_name: Name of the class to find
        source_file: The file that imports/uses this class

    Returns:
        Absolute path to the file containing the class definition, or None
    """
    # First, check if class is defined in the same file
    try:
        content = Path(source_file).read_text(encoding="utf-8")
        tree = ast.parse(content)

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                return str(Path(source_file).resolve())
    except Exception:
        pass

    # Parse imports and find where the class comes from
    imports = _parse_imports(source_file)

    if class_name in imports:
        module_name = imports[class_name]
        resolved_file = _resolve_module_to_file(module_name, source_file)
        if resolved_file:
            return resolved_file

    return None


def collect_referenced_types(
    services: Dict[str, Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """Collect all referenced types from service parameters.

    Scans all services for parameters with class_name, resolves their
    source files, and extracts their properties.

    Args:
        services: Dictionary of service definitions from scan_codebase_for_mcp_services

    Returns:
        Dictionary of class name to type info:
        {
            "FilterParams": {
                "file": "/path/to/outlook_types.py",
                "line": 15,
                "properties": [...]
            }
        }
    """
    referenced_types: Dict[str, Dict[str, Any]] = {}
    processed_classes: Set[str] = set()

    for service_name, service_info in services.items():
        source_file = service_info.get("file", "")
        parameters = service_info.get("parameters", [])

        for param in parameters:
            class_name = param.get("class_name")
            if not class_name or class_name in processed_classes:
                continue

            processed_classes.add(class_name)

            # Find the file where this class is defined
            class_file = resolve_class_file(class_name, source_file)
            if not class_file:
                print(f"  Warning: Could not find definition for class '{class_name}'")
                continue

            # Extract class properties using extract_types module
            try:
                class_info = extract_types.extract_single_class(class_file, class_name)
                if class_info:
                    referenced_types[class_name] = class_info
                    print(f"  Extracted {len(class_info.get('properties', []))} properties from {class_name}")
            except Exception as exc:
                print(f"  Warning: Could not extract properties from '{class_name}': {exc}")

    return referenced_types


def export_types_property(
    referenced_types: Dict[str, Dict[str, Any]],
    server_name: str,
    output_dir: str
) -> str:
    """Export referenced types to types_property_{server_name}.json.

    Args:
        referenced_types: Dictionary from collect_referenced_types
        server_name: Server name for the output file
        output_dir: Output directory path

    Returns:
        Path to the generated file
    """
    # Build output structure compatible with existing API
    output = {
        "version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "server_name": server_name,
        "classes": [],
        "properties_by_class": {},
        "all_properties": []
    }

    for class_name, class_info in referenced_types.items():
        properties = class_info.get("properties", [])

        # Add to classes list
        output["classes"].append({
            "name": class_name,
            "file": class_info.get("file", ""),
            "line": class_info.get("line", 0),
            "property_count": len(properties)
        })

        # Add to properties_by_class
        output["properties_by_class"][class_name] = properties

        # Add to all_properties (flattened)
        for prop in properties:
            output["all_properties"].append({
                "name": prop.get("name", ""),
                "type": prop.get("type", "any"),
                "description": prop.get("description", ""),
                "class": class_name,
                "full_path": f"{class_name}.{prop.get('name', '')}",
                "examples": prop.get("examples", []),
                "default": prop.get("default")
            })

    # Save to file
    output_path = Path(output_dir) / f"types_property_{server_name}.json"
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    return str(output_path)


# =============================================================================
# Main Export Function
# =============================================================================

def export_services_to_json(base_dir: str, server_name: str, output_dir: str) -> Dict[str, Any]:
    """
    Export services to registry_{server_name}.json and types_property_{server_name}.json.

    This function generates both:
    1. registry_{server_name}.json - Service definitions
    2. types_property_{server_name}.json - Referenced type definitions

    Supports:
    - Python: @mcp_service decorators + BaseModel types
    - JavaScript: @McpService decorators, server.tool() pattern + Zod/Sequelize types

    Args:
        base_dir: Base directory to scan for services
        server_name: Server name for output files (used for file naming, not filtering for JS)
        output_dir: Directory to write output files

    Returns:
        Dictionary with paths and counts:
        {
            "registry": "/path/to/registry_xxx.json",
            "types_property": "/path/to/types_property_xxx.json",
            "service_count": 10,
            "type_count": 3
        }
    """
    # First scan without server_name filter to detect language
    all_services = scan_codebase_for_mcp_services(base_dir, server_name=None)

    # Detect if this is a JS project (server.tool pattern doesn't have server_name metadata)
    has_js_services = any(s.get("language") == "javascript" for s in all_services.values())
    has_py_services = any(s.get("language") == "python" for s in all_services.values())

    # For JS-only projects, don't filter by server_name (they don't have this metadata)
    if has_js_services and not has_py_services:
        services = all_services
    else:
        # For Python projects, filter by server_name as before
        services = scan_codebase_for_mcp_services(base_dir, server_name)
    services_items = sorted(services.items(), key=lambda item: (item[1]["file"], item[1]["line"]))

    # Detect primary language of the project
    languages_found = set(s.get("language", "python") for s in services.values())
    is_js_project = "javascript" in languages_found and "python" not in languages_found

    # Build registry format (used by web editor)
    registry_output = {
        "version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "server_name": server_name,
        "language": "javascript" if is_js_project else "python",
        "services": {}
    }

    for name, service in services_items:
        service_name = service.get("metadata", {}).get("service_name", name)
        registry_output["services"][service_name] = {
            "service_name": service_name,
            "handler": {
                "class_name": service.get("class"),
                "instance": service.get("instance"),
                "method": service.get("method", name),
                "is_async": service.get("is_async", True),
                "file": str(Path(service.get("file", "")).resolve()),
                "line": service.get("line", 0)
            },
            "signature": service.get("signature", ""),
            "parameters": service.get("parameters", []),
            "metadata": service.get("metadata", {}),
            "pattern": service.get("pattern"),  # "server.tool" for MCP SDK pattern
        }

    # Save registry file
    output_dir_path = Path(output_dir)
    registry_path = output_dir_path / f"registry_{server_name}.json"
    registry_path.write_text(json.dumps(registry_output, indent=2, ensure_ascii=False), encoding="utf-8")

    # Collect and export referenced types
    print(f"  Collecting referenced types...")
    types_property_path = ""
    type_count = 0

    if is_js_project:
        # JavaScript project: extract Sequelize models (type definitions)
        # Note: tool parameters are already included in the registry
        print(f"  Detected JavaScript project, scanning for Sequelize models...")
        try:
            types_property_path = extract_types_js.export_js_types_property(
                base_dir, server_name, output_dir
            )
            # Count types from the exported file
            if types_property_path and Path(types_property_path).exists():
                with open(types_property_path) as f:
                    js_types = json.load(f)
                    type_count = len(js_types.get("classes", []))
        except Exception as e:
            print(f"  Warning: JS type extraction failed: {e}")
    else:
        # Python project: extract BaseModel types
        referenced_types = collect_referenced_types(services)

        if referenced_types:
            types_property_path = export_types_property(referenced_types, server_name, output_dir)
            type_count = len(referenced_types)
            print(f"  Exported {type_count} types to {types_property_path}")
        else:
            print(f"  No referenced types found")

    return {
        "registry": str(registry_path),
        "types_property": types_property_path,
        "service_count": len(registry_output["services"]),
        "type_count": type_count,
        "language": "javascript" if is_js_project else "python",
    }
