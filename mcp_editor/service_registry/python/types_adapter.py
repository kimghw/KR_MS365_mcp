"""
Python Type Extractor Adapter.

This module provides an adapter that wraps the existing Python type
extraction implementation to conform to the AbstractTypeExtractor interface.

Supports:
- Pydantic BaseModel classes
- Dataclasses
- TypedDict
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..interfaces import (
    AbstractTypeExtractor,
    PropertyInfo,
    TypeInfo,
)

# Import existing implementation
from .types import (
    extract_class_properties,
    extract_single_class,
    scan_py_project_types,
    map_python_to_json_type,
    export_py_types_property,
)


class PythonTypeExtractor(AbstractTypeExtractor):
    """Python implementation of the type extractor.

    This adapter wraps the existing Python type extraction functions
    to provide an interface-compliant implementation.
    """

    @property
    def language(self) -> str:
        return "python"

    @property
    def supported_extensions(self) -> List[str]:
        return [".py"]

    @property
    def supported_type_kinds(self) -> List[str]:
        return ["pydantic_model", "dataclass", "typed_dict"]

    def extract_types_from_file(self, file_path: str) -> Dict[str, TypeInfo]:
        """Extract all type definitions from a Python file.

        Args:
            file_path: Path to the Python source file

        Returns:
            Dictionary mapping type names to TypeInfo
        """
        try:
            # Use existing implementation
            legacy_result = extract_class_properties(file_path)

            # Convert to new format
            result = {}
            for class_name, class_info in legacy_result.items():
                properties = self._convert_properties(class_info.get("properties", []))

                type_info = TypeInfo(
                    name=class_name,
                    file=file_path,
                    line=class_info.get("line", 0),
                    properties=properties,
                    type_kind="pydantic_model",
                    language="python",
                )
                result[class_name] = type_info

            return result

        except Exception as e:
            print(f"Error extracting types from Python file {file_path}: {e}")
            return {}

    def extract_single_type(self, file_path: str, type_name: str) -> Optional[TypeInfo]:
        """Extract a specific type definition from a Python file.

        Args:
            file_path: Path to the Python source file
            type_name: Name of the class/type to extract

        Returns:
            TypeInfo or None if not found
        """
        try:
            # Use existing implementation
            legacy_result = extract_single_class(file_path, type_name)

            if not legacy_result:
                return None

            properties = self._convert_properties(legacy_result.get("properties", []))

            return TypeInfo(
                name=type_name,
                file=file_path,
                line=legacy_result.get("line", 0),
                properties=properties,
                type_kind="pydantic_model",
                language="python",
            )

        except Exception:
            return None

    def map_type_to_json_schema(self, source_type: str) -> str:
        """Map a Python type to JSON Schema type.

        Args:
            source_type: Python type string (e.g., "str", "int", "List[str]")

        Returns:
            JSON Schema type string
        """
        return map_python_to_json_type(source_type)

    def _convert_properties(self, legacy_properties: List[Dict[str, Any]]) -> List[PropertyInfo]:
        """Convert legacy property format to PropertyInfo list.

        Args:
            legacy_properties: List of property dictionaries

        Returns:
            List of PropertyInfo objects
        """
        result = []
        for prop in legacy_properties:
            result.append(PropertyInfo(
                name=prop.get("name", ""),
                type=prop.get("type", "Any"),
                description=prop.get("description", ""),
                is_optional=prop.get("is_optional", True),
                default=prop.get("default"),
                examples=prop.get("examples", []),
            ))
        return result

    def should_scan_file(self, file_path: str) -> bool:
        """Determine if a Python file should be scanned for types.

        Looks for common type-related patterns in the file path.

        Args:
            file_path: Path to check

        Returns:
            True if file should be scanned
        """
        file_str = str(file_path).lower()
        keywords = ("types", "models", "schema", "entities", "dto", "_types")
        return any(keyword in file_str for keyword in keywords)


class PythonTypeExporter:
    """Handles project-wide type scanning and export for Python.

    This is a separate class as it doesn't need to implement
    the full AbstractTypeExtractor interface.
    """

    def __init__(self):
        self.extractor = PythonTypeExtractor()

    def scan_project(
        self,
        base_dir: str,
        skip_dirs: tuple = ("node_modules", ".git", "__pycache__", "venv", ".venv")
    ) -> Dict[str, Any]:
        """Scan entire project for Python type definitions.

        Args:
            base_dir: Root directory to scan
            skip_dirs: Directory names to skip

        Returns:
            Dictionary with 'classes' and 'all_properties'
        """
        return scan_py_project_types(base_dir, skip_dirs)

    def export_types_property(
        self,
        base_dir: str,
        server_name: str,
        output_dir: str
    ) -> str:
        """Export types to types_property_{server_name}.json.

        Args:
            base_dir: Root directory to scan
            server_name: Server name for output file
            output_dir: Directory to write output file

        Returns:
            Path to the generated JSON file
        """
        return export_py_types_property(base_dir, server_name, output_dir)


def get_extractor() -> PythonTypeExtractor:
    """Factory function to get a Python type extractor instance.

    Returns:
        PythonTypeExtractor instance
    """
    return PythonTypeExtractor()


def get_exporter() -> PythonTypeExporter:
    """Factory function to get a Python type exporter instance.

    Returns:
        PythonTypeExporter instance
    """
    return PythonTypeExporter()
