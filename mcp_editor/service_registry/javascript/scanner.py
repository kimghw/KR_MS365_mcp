"""
JavaScript/TypeScript Scanner for MCP Services.

This module provides JavaScript-specific scanning capabilities for @McpService
decorators and JSDoc @mcp_service patterns.

Supported patterns:
- Decorator-based: @McpService({ serverName: "...", ... })
- JSDoc-based: /** @mcp_service @server_name ... */

Dependencies:
- esprima: Optional JavaScript parser for decorator-based scanning
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# JavaScript parser (optional - graceful fallback if not installed)
try:
    import esprima
    ESPRIMA_AVAILABLE = True
except ImportError:
    ESPRIMA_AVAILABLE = False
    esprima = None


__all__ = [
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
]


# =============================================================================
# JSDoc Type Mapping
# =============================================================================

# JSDoc type to JSON Schema type mapping
JSDOC_TYPE_MAP = {
    "string": "string",
    "String": "string",
    "number": "number",
    "Number": "number",
    "integer": "integer",
    "int": "integer",
    "boolean": "boolean",
    "Boolean": "boolean",
    "bool": "boolean",
    "object": "object",
    "Object": "object",
    "array": "array",
    "Array": "array",
    "any": "any",
    "*": "any",
    "null": "null",
    "undefined": "null",
    "void": "null",
    "function": "object",
    "Function": "object",
}


def _map_jsdoc_type(jsdoc_type: str) -> str:
    """Map JSDoc type to JSON Schema type."""
    # Handle Array<T> or T[]
    if jsdoc_type.startswith("Array<") or jsdoc_type.endswith("[]"):
        return "array"
    # Handle generic types like Object<K,V>
    if "<" in jsdoc_type:
        base_type = jsdoc_type.split("<")[0]
        return JSDOC_TYPE_MAP.get(base_type, "object")
    # Known types return mapped value, unknown types (custom classes) return "object"
    return JSDOC_TYPE_MAP.get(jsdoc_type, "object")


# =============================================================================
# JavaScript Decorator Parser
# =============================================================================

def _extract_js_decorator_metadata(decorator_node: dict) -> Dict[str, Any]:
    """Extract metadata from JavaScript decorator call.

    Handles patterns like:
    - @McpService({ serverName: "outlook", description: "..." })
    - @mcp_service({ server_name: "outlook" })
    """
    metadata: Dict[str, Any] = {}

    if not decorator_node:
        return metadata

    # Get the arguments of the decorator call
    arguments = decorator_node.get("arguments", [])
    if not arguments:
        return metadata

    # First argument should be an object expression
    first_arg = arguments[0]
    if first_arg.get("type") != "ObjectExpression":
        return metadata

    # Extract properties from the object
    for prop in first_arg.get("properties", []):
        if prop.get("type") != "Property":
            continue

        key = prop.get("key", {})
        value = prop.get("value", {})

        # Get property name
        key_name = key.get("name") or key.get("value")
        if not key_name:
            continue

        # Convert camelCase to snake_case for consistency
        snake_key = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', key_name).lower()

        # Get property value
        if value.get("type") == "Literal":
            metadata[snake_key] = value.get("value")
        elif value.get("type") == "ArrayExpression":
            elements = value.get("elements", [])
            metadata[snake_key] = [
                el.get("value") for el in elements
                if el.get("type") == "Literal"
            ]

    return metadata


def _extract_js_parameters(func_node: dict) -> List[Dict[str, Any]]:
    """Extract parameters from JavaScript function node."""
    params: List[Dict[str, Any]] = []

    js_params = func_node.get("params", [])

    for param in js_params:
        param_info = {
            "name": None,
            "type": None,
            "is_optional": False,
            "default": None,
            "has_default": False,
        }

        # Handle different parameter types
        if param.get("type") == "Identifier":
            param_info["name"] = param.get("name")
        elif param.get("type") == "AssignmentPattern":
            # Parameter with default value
            left = param.get("left", {})
            right = param.get("right", {})
            param_info["name"] = left.get("name")
            param_info["has_default"] = True
            param_info["is_optional"] = True
            if right.get("type") == "Literal":
                param_info["default"] = right.get("value")
        elif param.get("type") == "RestElement":
            # ...args
            argument = param.get("argument", {})
            param_info["name"] = f"...{argument.get('name', 'args')}"
            param_info["is_optional"] = True

        if param_info["name"]:
            params.append(param_info)

    return params


def _js_signature_from_parameters(params: List[Dict[str, Any]]) -> str:
    """Build signature string from JavaScript parameters."""
    parts: List[str] = []
    for param in params:
        name = param.get("name", "")
        if not name:
            continue

        param_str = name
        if param.get("has_default"):
            default = param.get("default")
            if isinstance(default, str):
                param_str += f' = "{default}"'
            elif default is not None:
                param_str += f" = {default}"
            else:
                param_str += " = null"

        parts.append(param_str)

    return ", ".join(parts)


def _parse_js_literal(value_str: str) -> Any:
    """Parse a JavaScript literal value to Python."""
    value_str = value_str.strip()
    if value_str == "true":
        return True
    elif value_str == "false":
        return False
    elif value_str == "null":
        return None
    elif value_str.startswith(("'", '"')):
        return value_str[1:-1]
    elif value_str.isdigit():
        return int(value_str)
    elif re.match(r"^\d+\.\d+$", value_str):
        return float(value_str)
    return value_str


# =============================================================================
# Decorator-based Scanner (esprima)
# =============================================================================

def find_mcp_services_in_js_file(file_path: str) -> Dict[str, Dict[str, Any]]:
    """Find all @McpService or @mcp_service decorated functions in JavaScript/TypeScript file."""
    if not ESPRIMA_AVAILABLE:
        print(f"Warning: esprima not installed, skipping JS file: {file_path}")
        return {}

    services: Dict[str, Dict[str, Any]] = {}

    try:
        content = Path(file_path).read_text(encoding="utf-8")

        # Parse with esprima
        tree = esprima.parseScript(content, {"tolerant": True, "loc": True})

        # Find decorated functions
        for node in tree.body:
            _process_js_node(node, file_path, services)

    except Exception as exc:
        print(f"Error parsing JS file {file_path}: {exc}")

    return services


def _process_js_node(node: dict, file_path: str, services: Dict[str, Dict[str, Any]], class_name: str = None):
    """Process a JavaScript AST node to find MCP services."""
    node_type = node.get("type") if isinstance(node, dict) else getattr(node, "type", None)

    # Convert esprima node to dict if needed
    if hasattr(node, "toDict"):
        node = node.toDict()
    elif not isinstance(node, dict):
        node = vars(node) if hasattr(node, "__dict__") else {}

    # Handle class declarations
    if node_type == "ClassDeclaration":
        class_name = node.get("id", {}).get("name")
        body = node.get("body", {}).get("body", [])
        for item in body:
            _process_js_node(item, file_path, services, class_name)
        return

    # Handle method definitions in classes
    if node_type == "MethodDefinition":
        decorators = node.get("decorators", [])
        func_node = node.get("value", {})
        func_name = node.get("key", {}).get("name")
        _check_js_mcp_service(decorators, func_node, func_name, file_path, services, class_name)
        return

    # Handle function declarations
    if node_type == "FunctionDeclaration":
        # Check for decorators (experimental syntax)
        decorators = node.get("decorators", [])
        func_name = node.get("id", {}).get("name")
        _check_js_mcp_service(decorators, node, func_name, file_path, services, class_name)
        return

    # Handle exported functions
    if node_type == "ExportNamedDeclaration":
        declaration = node.get("declaration", {})
        if declaration:
            _process_js_node(declaration, file_path, services, class_name)
        return

    # Handle variable declarations (arrow functions)
    if node_type == "VariableDeclaration":
        for decl in node.get("declarations", []):
            init = decl.get("init", {})
            if init and init.get("type") in ("ArrowFunctionExpression", "FunctionExpression"):
                func_name = decl.get("id", {}).get("name")
                decorators = node.get("decorators", [])
                _check_js_mcp_service(decorators, init, func_name, file_path, services, class_name)


def _check_js_mcp_service(decorators: list, func_node: dict, func_name: str,
                           file_path: str, services: Dict[str, Dict[str, Any]],
                           class_name: str = None):
    """Check if function has MCP service decorator and extract info."""
    if not func_name:
        return

    # Look for @McpService or @mcp_service decorator
    mcp_decorator = None
    for dec in decorators or []:
        dec_name = None
        if dec.get("type") == "Identifier":
            dec_name = dec.get("name")
        elif dec.get("type") == "CallExpression":
            callee = dec.get("callee", {})
            dec_name = callee.get("name")

        if dec_name in ("McpService", "mcp_service", "McpTool"):
            mcp_decorator = dec
            break

    if not mcp_decorator:
        return

    # Extract metadata
    if mcp_decorator.get("type") == "CallExpression":
        metadata = _extract_js_decorator_metadata(mcp_decorator)
    else:
        metadata = {}

    # Extract parameters
    params = _extract_js_parameters(func_node)
    signature = _js_signature_from_parameters(params)

    # Get line number
    loc = func_node.get("loc", {})
    line = loc.get("start", {}).get("line", 0) if loc else 0

    service_info = {
        "function_name": func_name,
        "metadata": metadata,
        "signature": signature,
        "parameters": params,
        "is_async": func_node.get("async", False),
        "file": str(file_path),
        "line": line,
        "language": "javascript",
    }

    if class_name:
        service_info["class"] = class_name
        service_info["instance"] = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', class_name).lower()
        service_info["module"] = Path(file_path).stem
        service_info["method"] = func_name

    services[func_name] = service_info


# =============================================================================
# JSDoc-based Scanner
# =============================================================================

def _parse_jsdoc_block(jsdoc_block: str) -> Dict[str, Any]:
    """Parse a JSDoc comment block and extract MCP service metadata.

    Parses tags like:
        @mcp_service
        @server_name asset_management
        @tool_name get_crew_list
        @service_name getCrew
        @description 전체 선원 정보 조회
        @category crew_query
        @tags query,search,filter
        @param {Array<number>} [shipIds] - 선박 ID 목록
        @param {string} where - 검색 조건
        @returns {Array<Object>} 선원 목록

    Returns:
        Dictionary with metadata and parameters
    """
    result = {
        "is_mcp_service": False,
        "metadata": {},
        "parameters": [],
        "returns": None,
    }

    # Check if this is an MCP service
    if "@mcp_service" not in jsdoc_block:
        return result

    result["is_mcp_service"] = True

    # Extract simple tags (single value)
    simple_tags = ["server_name", "tool_name", "service_name", "description", "category"]
    for tag in simple_tags:
        pattern = rf"@{tag}\s+(.+?)(?=\n\s*\*\s*@|\n\s*\*/|\Z)"
        match = re.search(pattern, jsdoc_block, re.DOTALL)
        if match:
            value = match.group(1).strip()
            # Clean up multi-line values
            value = re.sub(r"\n\s*\*\s*", " ", value).strip()
            result["metadata"][tag] = value

    # Extract tags (comma-separated)
    tags_match = re.search(r"@tags\s+(.+?)(?=\n\s*\*\s*@|\n\s*\*/|\Z)", jsdoc_block)
    if tags_match:
        tags_str = tags_match.group(1).strip()
        result["metadata"]["tags"] = [t.strip() for t in tags_str.split(",")]

    # Extract parameters: @param {type} [name] or @param {type} [obj.prop] - description
    # Pattern handles: {type}, name or [name] or obj.prop or [obj.prop], and optional description
    param_pattern = r"@param\s+\{([^}]+)\}\s+(\[?[\w.]+\]?)\s*(?:-\s*(.+?))?(?=\n\s*\*\s*@|\n\s*\*/|\Z)"

    # First pass: collect all parameters and nested properties
    raw_params = []
    for match in re.finditer(param_pattern, jsdoc_block, re.DOTALL):
        param_type = match.group(1).strip()
        param_name = match.group(2).strip()
        param_desc = match.group(3).strip() if match.group(3) else ""

        # Clean up description
        param_desc = re.sub(r"\n\s*\*\s*", " ", param_desc).strip()

        # Check if optional (wrapped in [])
        is_optional = param_name.startswith("[") and param_name.endswith("]")
        if is_optional:
            param_name = param_name[1:-1]  # Remove brackets

        raw_params.append({
            "name": param_name,
            "type": _map_jsdoc_type(param_type),
            "jsdoc_type": param_type,
            "is_optional": is_optional,
            "description": param_desc,
            "default": None,
            "has_default": False,
        })

    # Second pass: organize nested properties under parent objects
    param_map = {}  # name -> param dict
    for param in raw_params:
        name = param["name"]
        if "." in name:
            # Nested property: obj.prop or obj.prop.subprop
            parts = name.split(".")
            parent_name = parts[0]
            prop_name = ".".join(parts[1:])

            # Ensure parent exists in param_map
            if parent_name not in param_map:
                # Find parent in raw_params or create placeholder
                parent_param = next((p for p in raw_params if p["name"] == parent_name), None)
                if parent_param:
                    param_map[parent_name] = parent_param.copy()
                else:
                    param_map[parent_name] = {
                        "name": parent_name,
                        "type": "object",
                        "jsdoc_type": "Object",
                        "is_optional": False,
                        "description": "",
                        "default": None,
                        "has_default": False,
                    }

            # Initialize properties dict if not exists
            if "properties" not in param_map[parent_name]:
                param_map[parent_name]["properties"] = {}

            # Add nested property
            param_map[parent_name]["properties"][prop_name] = {
                "type": param["type"],
                "jsdoc_type": param["jsdoc_type"],
                "description": param["description"],
                "is_optional": param["is_optional"],
            }
        else:
            # Top-level parameter
            if name not in param_map:
                param_map[name] = param

    # Add organized parameters to result
    for param in param_map.values():
        result["parameters"].append(param)

    # Extract return type
    returns_match = re.search(r"@returns?\s+\{([^}]+)\}\s*(.+)?(?=\n\s*\*\s*@|\n\s*\*/|\Z)", jsdoc_block)
    if returns_match:
        result["returns"] = {
            "type": _map_jsdoc_type(returns_match.group(1).strip()),
            "jsdoc_type": returns_match.group(1).strip(),
            "description": returns_match.group(2).strip() if returns_match.group(2) else "",
        }

    return result


def _find_function_after_jsdoc(content: str, jsdoc_end_pos: int) -> Optional[Dict[str, Any]]:
    """Find the function definition that follows a JSDoc block.

    Handles patterns like:
        - crewService.getCrew = async (params = {}) => {
        - async function updateUserLicense(id, updateData) {
        - const getCrew = async function(params) {
        - exports.getCrew = async (params) => {

    Returns:
        Dictionary with function info or None
    """
    # Get the text after JSDoc (limit search to next 500 chars)
    after_jsdoc = content[jsdoc_end_pos:jsdoc_end_pos + 500]

    # Skip whitespace
    after_jsdoc_stripped = after_jsdoc.lstrip()
    skip_len = len(after_jsdoc) - len(after_jsdoc_stripped)
    func_start_pos = jsdoc_end_pos + skip_len

    # Pattern 1: obj.method = async (params) => { or obj.method = async function(params) {
    pattern1 = r"^(\w+)\.(\w+)\s*=\s*(async\s+)?(?:function\s*)?\(([^)]*)\)\s*(?:=>)?\s*\{"
    match = re.match(pattern1, after_jsdoc_stripped)
    if match:
        return {
            "object": match.group(1),
            "function_name": match.group(2),
            "is_async": bool(match.group(3)),
            "params_str": match.group(4),
            "line": content[:func_start_pos].count('\n') + 1,
        }

    # Pattern 2: async function name(params) { or function name(params) {
    pattern2 = r"^(async\s+)?function\s+(\w+)\s*\(([^)]*)\)\s*\{"
    match = re.match(pattern2, after_jsdoc_stripped)
    if match:
        return {
            "object": None,
            "function_name": match.group(2),
            "is_async": bool(match.group(1)),
            "params_str": match.group(3),
            "line": content[:func_start_pos].count('\n') + 1,
        }

    # Pattern 3: const/let/var name = async (params) => { or = async function(params) {
    pattern3 = r"^(?:const|let|var)\s+(\w+)\s*=\s*(async\s+)?(?:function\s*)?\(([^)]*)\)\s*(?:=>)?\s*\{"
    match = re.match(pattern3, after_jsdoc_stripped)
    if match:
        return {
            "object": None,
            "function_name": match.group(1),
            "is_async": bool(match.group(2)),
            "params_str": match.group(3),
            "line": content[:func_start_pos].count('\n') + 1,
        }

    # Pattern 4: exports.name = async (params) => {
    pattern4 = r"^exports\.(\w+)\s*=\s*(async\s+)?(?:function\s*)?\(([^)]*)\)\s*(?:=>)?\s*\{"
    match = re.match(pattern4, after_jsdoc_stripped)
    if match:
        return {
            "object": "exports",
            "function_name": match.group(1),
            "is_async": bool(match.group(2)),
            "params_str": match.group(3),
            "line": content[:func_start_pos].count('\n') + 1,
        }

    return None


def find_jsdoc_mcp_services_in_js_file(file_path: str) -> Dict[str, Dict[str, Any]]:
    """Find all @mcp_service JSDoc-decorated functions in a JavaScript file.

    Parses JSDoc blocks like:
        /**
         * @mcp_service
         * @server_name asset_management
         * @tool_name get_crew_list
         * @description 전체 선원 정보 조회
         * @param {Array<number>} [shipIds] - 선박 ID 목록
         */
        crewService.getCrew = async (params = {}) => { ... }

    Returns:
        Dictionary of service name to service info
    """
    services: Dict[str, Dict[str, Any]] = {}

    try:
        content = Path(file_path).read_text(encoding="utf-8")

        # Find all JSDoc blocks
        jsdoc_pattern = r"/\*\*[\s\S]*?\*/"

        for match in re.finditer(jsdoc_pattern, content):
            jsdoc_block = match.group()
            jsdoc_end_pos = match.end()

            # Parse JSDoc block
            parsed = _parse_jsdoc_block(jsdoc_block)

            if not parsed["is_mcp_service"]:
                continue

            # Find the function that follows this JSDoc
            func_info = _find_function_after_jsdoc(content, jsdoc_end_pos)

            if not func_info:
                # JSDoc block found but no function after it
                continue

            # Use service_name from metadata, or function_name as fallback
            service_name = parsed["metadata"].get("service_name", func_info["function_name"])
            tool_name = parsed["metadata"].get("tool_name", func_info["function_name"])

            # Build signature from parameters
            signature = ", ".join([
                f"{p['name']}: {p.get('jsdoc_type', 'any')}"
                for p in parsed["parameters"]
            ])

            services[service_name] = {
                "function_name": func_info["function_name"],
                "service_name": service_name,
                "metadata": {
                    "tool_name": tool_name,
                    "server_name": parsed["metadata"].get("server_name"),
                    "description": parsed["metadata"].get("description", ""),
                    "category": parsed["metadata"].get("category"),
                    "tags": parsed["metadata"].get("tags", []),
                },
                "signature": signature,
                "parameters": parsed["parameters"],
                "returns": parsed.get("returns"),
                "is_async": func_info["is_async"],
                "file": str(file_path),
                "line": func_info["line"],
                "language": "javascript",
                "pattern": "jsdoc",
            }

            # Add object info if method of an object
            if func_info.get("object"):
                services[service_name]["object"] = func_info["object"]

    except Exception as exc:
        print(f"Error scanning JS file for JSDoc @mcp_service: {file_path}: {exc}")

    return services
