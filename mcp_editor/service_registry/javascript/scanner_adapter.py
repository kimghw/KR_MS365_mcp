"""
JavaScript Service Scanner Adapter.

This module provides an adapter that wraps the existing JavaScript scanner
implementation to conform to the AbstractServiceScanner interface.

Supports both:
- Decorator-based: @McpService({ serverName: "...", ... })
- JSDoc-based: /** @mcp_service @server_name ... */
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..interfaces import (
    AbstractServiceScanner,
    ParameterInfo,
    ServiceInfo,
)

# Import existing implementation
from .scanner import (
    find_mcp_services_in_js_file,
    find_jsdoc_mcp_services_in_js_file,
    _extract_js_decorator_metadata,
    _extract_js_parameters,
    _js_signature_from_parameters,
    ESPRIMA_AVAILABLE,
)


class JavaScriptServiceScanner(AbstractServiceScanner):
    """JavaScript implementation of the service scanner.

    This adapter wraps the existing JavaScript scanning functions
    (both esprima-based and JSDoc regex-based) to provide an
    interface-compliant implementation.
    """

    @property
    def language(self) -> str:
        return "javascript"

    @property
    def supported_extensions(self) -> List[str]:
        return [".js", ".mjs", ".ts", ".tsx"]

    def scan_file(self, file_path: str) -> Dict[str, ServiceInfo]:
        """Scan a JavaScript file for MCP service definitions.

        Uses both decorator-based and JSDoc-based scanning.

        Args:
            file_path: Path to the JavaScript source file

        Returns:
            Dictionary mapping service names to ServiceInfo
        """
        result = {}

        try:
            # Try esprima-based scanning first (if available)
            if ESPRIMA_AVAILABLE:
                try:
                    esprima_result = find_mcp_services_in_js_file(file_path)
                    result.update(self._convert_legacy_result(esprima_result, file_path, "decorator"))
                except Exception:
                    pass

            # Always try JSDoc-based scanning (no external dependencies)
            try:
                jsdoc_result = find_jsdoc_mcp_services_in_js_file(file_path)
                # Only add JSDoc results if not already found by esprima
                for func_name, func_info in jsdoc_result.items():
                    if func_name not in result:
                        converted = self._convert_legacy_result({func_name: func_info}, file_path, "jsdoc")
                        result.update(converted)
            except Exception:
                pass

            return result

        except Exception as e:
            print(f"Error scanning JavaScript file {file_path}: {e}")
            return {}

    def _convert_legacy_result(
        self,
        legacy_result: Dict[str, Dict[str, Any]],
        file_path: str,
        pattern: str
    ) -> Dict[str, ServiceInfo]:
        """Convert legacy scan result to ServiceInfo format.

        Args:
            legacy_result: Result from legacy scanning function
            file_path: Source file path
            pattern: Detection pattern used

        Returns:
            Dictionary mapping service names to ServiceInfo
        """
        result = {}

        for func_name, func_info in legacy_result.items():
            # Convert parameters
            parameters = []
            for param in func_info.get("parameters", []):
                parameters.append(ParameterInfo(
                    name=param.get("name", ""),
                    type=param.get("type", "any"),
                    is_optional=param.get("is_optional", False),
                    default=param.get("default"),
                    has_default=param.get("has_default", False),
                    class_name=param.get("class_name"),
                    description=param.get("description", ""),
                    properties=param.get("properties"),
                ))

            # Extract metadata
            metadata = {}
            if "server_name" in func_info:
                metadata["server_name"] = func_info["server_name"]
            if "tool_name" in func_info:
                metadata["tool_name"] = func_info["tool_name"]
            if "description" in func_info:
                metadata["description"] = func_info["description"]
            if "metadata" in func_info:
                metadata.update(func_info["metadata"])

            # Build ServiceInfo
            handler = func_info.get("handler", {})
            service_info = ServiceInfo(
                function_name=func_name,
                signature=func_info.get("signature", ""),
                parameters=parameters,
                metadata=metadata,
                is_async=handler.get("is_async", func_info.get("is_async", False)),
                file=handler.get("file", file_path),
                line=handler.get("line", func_info.get("line", 0)),
                language="javascript",
                class_name=handler.get("class_name"),
                instance=handler.get("instance"),
                method=handler.get("method"),
                pattern=pattern,
            )
            result[func_name] = service_info

        return result

    def extract_parameters(self, node: dict) -> List[ParameterInfo]:
        """Extract parameters from a JavaScript function node.

        Args:
            node: Esprima AST node representing a function

        Returns:
            List of ParameterInfo
        """
        try:
            # Use existing implementation
            legacy_params = _extract_js_parameters(node)

            # Convert to new format
            result = []
            for param in legacy_params:
                result.append(ParameterInfo(
                    name=param.get("name", ""),
                    type=param.get("type", "any"),
                    is_optional=param.get("is_optional", False),
                    default=param.get("default"),
                    has_default=param.get("has_default", False),
                    class_name=param.get("class_name"),
                ))

            return result

        except Exception:
            return []

    def extract_decorator_metadata(self, decorator: dict) -> Dict[str, Any]:
        """Extract metadata from a JavaScript decorator node.

        Args:
            decorator: Esprima decorator/call expression node

        Returns:
            Dictionary with metadata
        """
        try:
            return _extract_js_decorator_metadata(decorator)
        except Exception:
            return {}

    def build_signature(self, parameters: List[ParameterInfo]) -> str:
        """Build signature string from parameters.

        Uses the existing JavaScript signature building function.

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

        return _js_signature_from_parameters(legacy_params)


def get_scanner() -> JavaScriptServiceScanner:
    """Factory function to get a JavaScript scanner instance.

    Returns:
        JavaScriptServiceScanner instance
    """
    return JavaScriptServiceScanner()
