"""
Python Service Scanner Adapter.

This module provides an adapter that wraps the existing Python scanner
implementation to conform to the AbstractServiceScanner interface.

The adapter pattern allows gradual migration from the legacy implementation
to the new interface-based design without breaking existing code.
"""

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..interfaces import (
    AbstractServiceScanner,
    ParameterInfo,
    ServiceInfo,
)

# Import existing implementation
from .scanner import (
    MCPServiceExtractor,
    find_mcp_services_in_python_file,
    extract_decorator_metadata as _extract_decorator_metadata,
    _extract_parameters,
    signature_from_parameters,
)


class PythonServiceScanner(AbstractServiceScanner):
    """Python implementation of the service scanner using AST.

    This adapter wraps the existing MCPServiceExtractor and related
    functions to provide an interface-compliant implementation.
    """

    @property
    def language(self) -> str:
        return "python"

    @property
    def supported_extensions(self) -> List[str]:
        return [".py"]

    def scan_file(self, file_path: str) -> Dict[str, ServiceInfo]:
        """Scan a Python file for @mcp_service decorated functions.

        Args:
            file_path: Path to the Python source file

        Returns:
            Dictionary mapping service names to ServiceInfo
        """
        try:
            # Use existing implementation
            legacy_result = find_mcp_services_in_python_file(file_path)

            # Convert to new format
            result = {}
            for func_name, func_info in legacy_result.items():
                # Convert parameters
                parameters = []
                for param in func_info.get("parameters", []):
                    parameters.append(ParameterInfo(
                        name=param.get("name", ""),
                        type=param.get("type", "Any"),
                        is_optional=param.get("is_optional", False),
                        default=param.get("default"),
                        has_default=param.get("has_default", False),
                        class_name=param.get("class_name"),
                        description=param.get("description", ""),
                        properties=param.get("properties"),
                    ))

                # Build ServiceInfo
                handler = func_info.get("handler", {})
                service_info = ServiceInfo(
                    function_name=func_name,
                    signature=func_info.get("signature", ""),
                    parameters=parameters,
                    metadata=func_info.get("metadata", {}),
                    is_async=handler.get("is_async", False),
                    file=handler.get("file", file_path),
                    line=handler.get("line", 0),
                    language="python",
                    class_name=handler.get("class_name"),
                    instance=handler.get("instance"),
                    method=handler.get("method"),
                    pattern="decorator",
                )
                result[func_name] = service_info

            return result

        except Exception as e:
            # Log error but don't crash
            print(f"Error scanning Python file {file_path}: {e}")
            return {}

    def extract_parameters(self, node: ast.FunctionDef) -> List[ParameterInfo]:
        """Extract parameters from a Python function AST node.

        Args:
            node: ast.FunctionDef node

        Returns:
            List of ParameterInfo
        """
        try:
            # Use existing implementation
            legacy_params = _extract_parameters(node)

            # Convert to new format
            result = []
            for param in legacy_params:
                result.append(ParameterInfo(
                    name=param.get("name", ""),
                    type=param.get("type", "Any"),
                    is_optional=param.get("is_optional", False),
                    default=param.get("default"),
                    has_default=param.get("has_default", False),
                    class_name=param.get("class_name"),
                ))

            return result

        except Exception:
            return []

    def extract_decorator_metadata(self, decorator: ast.Call) -> Dict[str, Any]:
        """Extract metadata from a @mcp_service decorator.

        Args:
            decorator: ast.Call node representing the decorator

        Returns:
            Dictionary with metadata like server_name, tool_name, etc.
        """
        try:
            return _extract_decorator_metadata(decorator)
        except Exception:
            return {}

    def build_signature(self, parameters: List[ParameterInfo]) -> str:
        """Build signature string from parameters.

        Uses the existing signature_from_parameters function after
        converting ParameterInfo to the legacy dict format.

        Args:
            parameters: List of ParameterInfo

        Returns:
            Signature string
        """
        # Convert to legacy format
        legacy_params = [
            {
                "name": p.name,
                "type": p.type,
                "is_optional": p.is_optional,
                "default": p.default,
                "has_default": p.has_default,
                "class_name": p.class_name,
            }
            for p in parameters
        ]

        return signature_from_parameters(legacy_params)


def get_scanner() -> PythonServiceScanner:
    """Factory function to get a Python scanner instance.

    Returns:
        PythonServiceScanner instance
    """
    return PythonServiceScanner()
