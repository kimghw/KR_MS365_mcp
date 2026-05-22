"""
JavaScript Type Extractor Adapter.

This module provides an adapter that wraps the existing JavaScript type
extraction implementation to conform to the AbstractTypeExtractor interface.

Supports:
- Sequelize models
- JSDoc type annotations
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
    extract_sequelize_models_from_file,
    scan_js_project_types,
    map_sequelize_to_json_type,
    export_js_types_property,
)


class JavaScriptTypeExtractor(AbstractTypeExtractor):
    """JavaScript implementation of the type extractor.

    This adapter wraps the existing JavaScript type extraction functions
    to provide an interface-compliant implementation.
    """

    @property
    def language(self) -> str:
        return "javascript"

    @property
    def supported_extensions(self) -> List[str]:
        return [".js", ".mjs", ".ts", ".tsx"]

    @property
    def supported_type_kinds(self) -> List[str]:
        return ["sequelize_model", "interface", "jsdoc_type"]

    def extract_types_from_file(self, file_path: str) -> Dict[str, TypeInfo]:
        """Extract all type definitions from a JavaScript file.

        Currently supports Sequelize model extraction.

        Args:
            file_path: Path to the JavaScript source file

        Returns:
            Dictionary mapping type names to TypeInfo
        """
        try:
            # Use existing implementation for Sequelize models
            legacy_result = extract_sequelize_models_from_file(file_path)

            # Convert to new format
            result = {}
            for model_name, model_info in legacy_result.items():
                properties = self._convert_properties(model_info.get("properties", {}))

                type_info = TypeInfo(
                    name=model_name,
                    file=file_path,
                    line=model_info.get("line", 0),
                    properties=properties,
                    type_kind="sequelize_model",
                    language="javascript",
                )
                result[model_name] = type_info

            return result

        except Exception as e:
            print(f"Error extracting types from JavaScript file {file_path}: {e}")
            return {}

    def extract_single_type(self, file_path: str, type_name: str) -> Optional[TypeInfo]:
        """Extract a specific type definition from a JavaScript file.

        Args:
            file_path: Path to the JavaScript source file
            type_name: Name of the model/type to extract

        Returns:
            TypeInfo or None if not found
        """
        try:
            all_types = self.extract_types_from_file(file_path)
            return all_types.get(type_name)
        except Exception:
            return None

    def map_type_to_json_schema(self, source_type: str) -> str:
        """Map a JavaScript/Sequelize type to JSON Schema type.

        Args:
            source_type: Sequelize type string (e.g., "STRING", "INTEGER")

        Returns:
            JSON Schema type string
        """
        return map_sequelize_to_json_type(source_type)

    def _convert_properties(self, legacy_properties: Dict[str, Any]) -> List[PropertyInfo]:
        """Convert legacy property format to PropertyInfo list.

        Args:
            legacy_properties: Dictionary of property name -> property info

        Returns:
            List of PropertyInfo objects
        """
        result = []

        # Handle both dict and list formats
        if isinstance(legacy_properties, dict):
            for prop_name, prop_info in legacy_properties.items():
                if isinstance(prop_info, dict):
                    result.append(PropertyInfo(
                        name=prop_name,
                        type=prop_info.get("type", "any"),
                        description=prop_info.get("description", ""),
                        is_optional=prop_info.get("allowNull", True),
                        default=prop_info.get("defaultValue"),
                        db_field=prop_info.get("field"),
                    ))
                else:
                    # Simple type string
                    result.append(PropertyInfo(
                        name=prop_name,
                        type=str(prop_info),
                    ))
        elif isinstance(legacy_properties, list):
            for prop in legacy_properties:
                if isinstance(prop, dict):
                    result.append(PropertyInfo(
                        name=prop.get("name", ""),
                        type=prop.get("type", "any"),
                        description=prop.get("description", ""),
                        is_optional=prop.get("is_optional", True),
                        default=prop.get("default"),
                    ))

        return result

    def should_scan_file(self, file_path: str) -> bool:
        """Determine if a JavaScript file should be scanned for types.

        Looks for common type-related patterns in the file path,
        especially Sequelize model directories.

        Args:
            file_path: Path to check

        Returns:
            True if file should be scanned
        """
        file_str = str(file_path).lower()
        keywords = ("models", "types", "schema", "entities", "sequelize")
        return any(keyword in file_str for keyword in keywords)


class JavaScriptTypeExporter:
    """Handles project-wide type scanning and export for JavaScript.

    This is a separate class as it doesn't need to implement
    the full AbstractTypeExtractor interface.
    """

    def __init__(self):
        self.extractor = JavaScriptTypeExtractor()

    def scan_project(
        self,
        base_dir: str,
        skip_dirs: tuple = ("node_modules", ".git", "__pycache__", "dist", "build")
    ) -> Dict[str, Any]:
        """Scan entire project for JavaScript type definitions.

        Args:
            base_dir: Root directory to scan
            skip_dirs: Directory names to skip

        Returns:
            Dictionary with 'models' and 'all_properties'
        """
        return scan_js_project_types(base_dir, skip_dirs)

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
        return export_js_types_property(base_dir, server_name, output_dir)


def get_extractor() -> JavaScriptTypeExtractor:
    """Factory function to get a JavaScript type extractor instance.

    Returns:
        JavaScriptTypeExtractor instance
    """
    return JavaScriptTypeExtractor()


def get_exporter() -> JavaScriptTypeExporter:
    """Factory function to get a JavaScript type exporter instance.

    Returns:
        JavaScriptTypeExporter instance
    """
    return JavaScriptTypeExporter()
