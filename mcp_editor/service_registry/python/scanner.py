"""
Python-specific MCP Service Scanner.

This module provides Python-specific functionality for scanning @mcp_service
decorated functions using the built-in ast module.

Functions:
- extract_decorator_metadata: Extract metadata from @mcp_service decorator call
- _annotation_to_str: Convert AST annotation to string
- _default_to_value: Convert AST default value to JSON-serializable value
- _extract_parameters: Extract parameter info from function definition
- signature_from_parameters: Build signature string from parameters
- find_mcp_services_in_python_file: Find all @mcp_service decorated functions

Classes:
- MCPServiceExtractor: AST NodeVisitor for extracting MCP services
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..base import Language, _is_class_type, _parse_type_info

__all__ = [
    "extract_decorator_metadata",
    "_annotation_to_str",
    "_default_to_value",
    "_extract_parameters",
    "signature_from_parameters",
    "MCPServiceExtractor",
    "find_mcp_services_in_python_file",
]


def extract_decorator_metadata(decorator: ast.Call) -> Dict[str, Any]:
    """Extract metadata from @mcp_service decorator call."""
    metadata: Dict[str, Any] = {}

    for keyword in decorator.keywords:
        if isinstance(keyword.value, ast.Constant):
            metadata[keyword.arg] = keyword.value.value
        elif isinstance(keyword.value, ast.List):
            values: List[Any] = []
            for element in keyword.value.elts:
                if isinstance(element, ast.Constant):
                    values.append(element.value)
            metadata[keyword.arg] = values
        elif isinstance(keyword.value, ast.Name):
            metadata[keyword.arg] = keyword.value.id

    return metadata


def _annotation_to_str(annotation: Optional[ast.AST]) -> Optional[str]:
    if annotation is None:
        return None
    try:
        return ast.unparse(annotation)
    except Exception:
        return None


def _default_to_value(node: ast.AST) -> Any:
    """Convert an AST default value to a JSON-serializable value or string."""
    if isinstance(node, ast.Constant):
        return node.value
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _extract_parameters(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> List[Dict[str, Any]]:
    """Extract parameter info from a function definition.

    Returns parameters with unified structure:
    - name: parameter name
    - type: JSON Schema compatible type (object for classes, or base type)
    - class_name: original class name if type is a custom class (optional field)
    - is_optional: True if type was Optional[...] or has default value
    - default: default value if any
    - has_default: True if parameter has a default value
    """
    args = func_node.args
    params: List[Dict[str, Any]] = []

    # Regular arguments
    defaults_offset = len(args.args) - len(args.defaults)
    for i, arg in enumerate(args.args):
        if arg.arg == "self":
            continue
        default_idx = i - defaults_offset
        has_default = default_idx >= 0
        default_val = None
        if has_default and default_idx < len(args.defaults):
            default_val = _default_to_value(args.defaults[default_idx])

        # Parse type to extract base_type, class_name, and is_optional
        raw_type = _annotation_to_str(arg.annotation)
        type_info = _parse_type_info(raw_type)

        # Parameter is optional if type is Optional[...] or has a default value
        is_optional = type_info["is_optional"] or has_default

        # Build param dict with class_name right after type (if exists)
        param_dict = {"name": arg.arg, "type": type_info["base_type"]}
        if type_info["class_name"]:
            param_dict["class_name"] = type_info["class_name"]
        param_dict["is_optional"] = is_optional
        param_dict["default"] = default_val
        param_dict["has_default"] = has_default

        params.append(param_dict)

    # *args
    if args.vararg:
        vararg_type = _annotation_to_str(args.vararg.annotation)
        vararg_type_info = _parse_type_info(vararg_type)
        vararg_dict = {"name": f"*{args.vararg.arg}", "type": vararg_type_info["base_type"]}
        if vararg_type_info["class_name"]:
            vararg_dict["class_name"] = vararg_type_info["class_name"]
        vararg_dict["is_optional"] = True  # *args is always optional
        vararg_dict["default"] = None
        vararg_dict["has_default"] = False
        params.append(vararg_dict)

    # **kwargs
    if args.kwarg:
        kwarg_type = _annotation_to_str(args.kwarg.annotation)
        kwarg_type_info = _parse_type_info(kwarg_type)
        kwarg_dict = {"name": f"**{args.kwarg.arg}", "type": kwarg_type_info["base_type"]}
        if kwarg_type_info["class_name"]:
            kwarg_dict["class_name"] = kwarg_type_info["class_name"]
        kwarg_dict["is_optional"] = True  # **kwargs is always optional
        kwarg_dict["default"] = None
        kwarg_dict["has_default"] = False
        params.append(kwarg_dict)

    return params


def signature_from_parameters(params: List[Dict[str, Any]]) -> str:
    """Build a signature string like 'param: str, other: int = 1' from param metadata.

    Uses is_optional to determine if type should be wrapped in Optional[...].
    Uses class_name for display if available (to show original Python class name).
    """
    parts: List[str] = []
    for param in params:
        name = param.get("name", "")
        if not name or name == "self":
            continue

        param_str = name
        # Use class_name for display if available, otherwise use type
        type_str = param.get("class_name") or param.get("type")
        is_optional = param.get("is_optional", False)
        default = param.get("default")
        has_default = param.get("has_default", False)

        if type_str:
            # Wrap in Optional if is_optional but don't double-wrap
            if is_optional and not type_str.startswith("Optional["):
                param_str += f": Optional[{type_str}]"
            else:
                param_str += f": {type_str}"

        if has_default:
            if (
                isinstance(default, str)
                and not default.startswith(("'", '"'))
                and " " not in default
                and not default.startswith("[")
            ):  # noqa: E501
                param_str += f' = "{default}"'
            elif default is not None:
                param_str += f" = {default}"
            else:
                param_str += " = None"

        parts.append(param_str)

    return ", ".join(parts)


class MCPServiceExtractor(ast.NodeVisitor):
    """Extract MCP services with class context."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.services: Dict[str, Dict[str, Any]] = {}
        self.current_class = None

    def visit_ClassDef(self, node):
        """Track current class context."""
        old_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = old_class

    def visit_FunctionDef(self, node):
        """Process function definitions."""
        self._process_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        """Process async function definitions."""
        self._process_function(node)
        self.generic_visit(node)

    def _process_function(self, node):
        """Extract MCP service info from function."""
        for decorator in node.decorator_list:
            is_mcp_service = False
            metadata: Dict[str, Any] = {}

            if isinstance(decorator, ast.Name) and decorator.id == "mcp_service":
                is_mcp_service = True
            elif (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Name)
                and decorator.func.id == "mcp_service"
            ):
                is_mcp_service = True
                metadata = extract_decorator_metadata(decorator)

            if not is_mcp_service:
                continue

            params = _extract_parameters(node)
            signature = signature_from_parameters(params)

            service_info = {
                "function_name": node.name,
                "metadata": metadata,
                "signature": signature,
                "parameters": params,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "file": str(self.file_path),
                "line": node.lineno,
                "language": "python",
            }

            # Add class info if function is a method
            if self.current_class:
                service_info["class"] = self.current_class
                # Convert class name to snake_case for instance name
                service_info["instance"] = self._to_snake_case(self.current_class)
                service_info["module"] = Path(self.file_path).stem
                service_info["method"] = node.name

            self.services[node.name] = service_info
            break

    def _to_snake_case(self, name: str) -> str:
        """Convert CamelCase to snake_case."""
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def find_mcp_services_in_python_file(file_path: str) -> Dict[str, Dict[str, Any]]:
    """Find all @mcp_service decorated functions in a Python file."""
    try:
        content = Path(file_path).read_text(encoding="utf-8")
        tree = ast.parse(content)

        extractor = MCPServiceExtractor(file_path)
        extractor.visit(tree)

        return extractor.services
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Error parsing {file_path}: {exc}")
        return {}
