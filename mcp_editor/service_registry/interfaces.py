"""
Abstract interfaces for language-agnostic MCP service scanning and type extraction.

This module defines the core abstractions that enable:
- Adding new language support by implementing interfaces
- Consistent data structures across languages (dataclasses)
- Registry-based scanner discovery
- Testable code through mock implementations

Usage:
    To add a new language (e.g., Go, Rust):
    1. Create a new package: service_registry/go/
    2. Implement AbstractServiceScanner and AbstractTypeExtractor
    3. Register implementations in __init__.py using ScannerRegistry
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# =============================================================================
# Data Transfer Objects (DTOs)
# =============================================================================

@dataclass
class ParameterInfo:
    """Unified parameter representation across all languages.

    Attributes:
        name: Parameter name
        type: Type string (e.g., "str", "int", "List[str]")
        is_optional: Whether the parameter is optional
        default: Default value if any
        has_default: Whether a default value exists
        class_name: Custom type/class name if applicable
        description: Parameter description from docstring/JSDoc
        properties: Nested properties for object types
    """
    name: str
    type: str
    is_optional: bool = False
    default: Any = None
    has_default: bool = False
    class_name: Optional[str] = None
    description: str = ""
    properties: Optional[Dict[str, Any]] = None


@dataclass
class ServiceInfo:
    """Unified service/function representation.

    Represents a function decorated with @mcp_service (Python)
    or annotated with @mcp_service JSDoc (JavaScript).

    Attributes:
        function_name: Name of the function
        signature: Full signature string
        parameters: List of ParameterInfo
        metadata: Decorator metadata (server_name, tool_name, etc.)
        is_async: Whether the function is async
        file: Source file path
        line: Line number in source file
        language: Language identifier (python, javascript, etc.)
        class_name: Containing class name if method
        instance: Instance variable name if method
        method: Method name if method
        pattern: Detection pattern used (decorator, jsdoc, server.tool)
    """
    function_name: str
    signature: str
    parameters: List[ParameterInfo]
    metadata: Dict[str, Any]
    is_async: bool
    file: str
    line: int
    language: str
    class_name: Optional[str] = None
    instance: Optional[str] = None
    method: Optional[str] = None
    pattern: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "function_name": self.function_name,
            "signature": self.signature,
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type,
                    "is_optional": p.is_optional,
                    "default": p.default,
                    "has_default": p.has_default,
                }
                for p in self.parameters
            ],
            "is_async": self.is_async,
            "file": self.file,
            "line": self.line,
            "language": self.language,
        }
        if self.class_name:
            result["class_name"] = self.class_name
        if self.instance:
            result["instance"] = self.instance
        if self.method:
            result["method"] = self.method
        if self.pattern:
            result["pattern"] = self.pattern
        if self.metadata:
            result["metadata"] = self.metadata
        return result


@dataclass
class PropertyInfo:
    """Unified property/field representation for types.

    Attributes:
        name: Property name
        type: Type string
        description: Property description
        is_optional: Whether the property is optional
        default: Default value if any
        examples: Example values
        db_field: Database field name for ORM mappings
    """
    name: str
    type: str
    description: str = ""
    is_optional: bool = True
    default: Any = None
    examples: List[Any] = field(default_factory=list)
    db_field: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "default": self.default,
        }
        if self.examples:
            result["examples"] = self.examples
        if self.db_field:
            result["db_field"] = self.db_field
        return result


@dataclass
class TypeInfo:
    """Unified type/model representation.

    Represents a class, interface, or model that can be used
    as a parameter type in MCP services.

    Attributes:
        name: Type/class name
        file: Source file path
        line: Line number in source file
        properties: List of PropertyInfo
        type_kind: Kind of type (pydantic_model, sequelize_model, interface, etc.)
        language: Language identifier
    """
    name: str
    file: str
    line: int
    properties: List[PropertyInfo]
    type_kind: str
    language: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "file": self.file,
            "line": self.line,
            "property_count": len(self.properties),
            "type_kind": self.type_kind,
            "language": self.language,
        }

    def properties_to_dict(self) -> Dict[str, Dict[str, Any]]:
        """Convert properties to dictionary format."""
        return {p.name: p.to_dict() for p in self.properties}


# =============================================================================
# Abstract Base Classes
# =============================================================================

class AbstractServiceScanner(ABC):
    """Abstract base class for language-specific service scanners.

    Implementations scan source files for MCP service definitions
    (decorated functions or annotated functions) and extract their
    metadata, parameters, and signatures.

    To implement:
        1. Define language property
        2. Define supported_extensions property
        3. Implement scan_file() to parse source and find services
        4. Implement extract_parameters() for function parameters
        5. Implement extract_decorator_metadata() for decorator info

    Example:
        class GoServiceScanner(AbstractServiceScanner):
            @property
            def language(self) -> str:
                return "go"

            @property
            def supported_extensions(self) -> List[str]:
                return [".go"]

            def scan_file(self, file_path: str) -> Dict[str, ServiceInfo]:
                # Parse Go file and find //mcp:service annotations
                ...
    """

    @property
    @abstractmethod
    def language(self) -> str:
        """Return the language identifier (e.g., 'python', 'javascript', 'go')."""
        pass

    @property
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """Return list of supported file extensions (e.g., ['.py'], ['.js', '.mjs'])."""
        pass

    @abstractmethod
    def scan_file(self, file_path: str) -> Dict[str, ServiceInfo]:
        """Scan a single file for MCP service definitions.

        Args:
            file_path: Path to the source file

        Returns:
            Dictionary mapping service names to ServiceInfo objects

        Raises:
            FileNotFoundError: If file doesn't exist
            SyntaxError: If file has syntax errors (optional, can return empty dict)
        """
        pass

    @abstractmethod
    def extract_parameters(self, node: Any) -> List[ParameterInfo]:
        """Extract parameters from a function/method node.

        Args:
            node: Language-specific AST node representing a function

        Returns:
            List of ParameterInfo objects representing function parameters
        """
        pass

    @abstractmethod
    def extract_decorator_metadata(self, decorator: Any) -> Dict[str, Any]:
        """Extract metadata from a decorator/annotation node.

        Args:
            decorator: Language-specific decorator/annotation node

        Returns:
            Dictionary containing metadata like:
            - server_name: str
            - tool_name: str
            - description: str
            - tags: List[str]
        """
        pass

    def build_signature(self, parameters: List[ParameterInfo]) -> str:
        """Build signature string from parameters.

        Default implementation creates Python-style signatures.
        Override for language-specific formatting.

        Args:
            parameters: List of ParameterInfo objects

        Returns:
            Signature string like "name: str, count: int = 0"
        """
        parts = []
        for param in parameters:
            if not param.name or param.name == "self":
                continue

            param_str = param.name
            type_str = param.class_name or param.type

            if type_str:
                if param.is_optional and not type_str.startswith("Optional["):
                    param_str += f": Optional[{type_str}]"
                else:
                    param_str += f": {type_str}"

            if param.has_default:
                if param.default is None:
                    param_str += " = None"
                elif isinstance(param.default, str):
                    param_str += f' = "{param.default}"'
                else:
                    param_str += f" = {param.default}"

            parts.append(param_str)

        return ", ".join(parts)

    def can_handle_file(self, file_path: str) -> bool:
        """Check if this scanner can handle the given file.

        Args:
            file_path: Path to check

        Returns:
            True if file extension matches supported_extensions
        """
        ext = Path(file_path).suffix.lower()
        return ext in self.supported_extensions


class AbstractTypeExtractor(ABC):
    """Abstract base class for language-specific type extractors.

    Implementations extract type definitions (classes, interfaces, models)
    from source files and convert them to a unified format.

    To implement:
        1. Define language property
        2. Define supported_type_kinds property
        3. Implement extract_types_from_file() to parse and extract types
        4. Implement extract_single_type() for specific type lookup
        5. Implement map_type_to_json_schema() for type conversion

    Example:
        class RustTypeExtractor(AbstractTypeExtractor):
            @property
            def language(self) -> str:
                return "rust"

            @property
            def supported_type_kinds(self) -> List[str]:
                return ["struct", "enum"]

            def extract_types_from_file(self, file_path: str) -> Dict[str, TypeInfo]:
                # Parse Rust file and extract struct/enum definitions
                ...
    """

    @property
    @abstractmethod
    def language(self) -> str:
        """Return the language identifier."""
        pass

    @property
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """Return list of supported file extensions."""
        pass

    @property
    @abstractmethod
    def supported_type_kinds(self) -> List[str]:
        """Return list of type kinds this extractor handles.

        Examples:
            ['pydantic_model', 'dataclass'] for Python
            ['sequelize_model', 'interface'] for JavaScript
            ['struct', 'enum'] for Rust
        """
        pass

    @abstractmethod
    def extract_types_from_file(self, file_path: str) -> Dict[str, TypeInfo]:
        """Extract all type definitions from a file.

        Args:
            file_path: Path to the source file

        Returns:
            Dictionary mapping type names to TypeInfo objects
        """
        pass

    @abstractmethod
    def extract_single_type(self, file_path: str, type_name: str) -> Optional[TypeInfo]:
        """Extract a specific type definition from a file.

        Args:
            file_path: Path to the source file
            type_name: Name of the type to extract

        Returns:
            TypeInfo or None if not found
        """
        pass

    @abstractmethod
    def map_type_to_json_schema(self, source_type: str) -> str:
        """Map a language-specific type to JSON Schema type.

        Args:
            source_type: Language-specific type string (e.g., "STRING", "int")

        Returns:
            JSON Schema type string (e.g., "string", "integer", "number", "boolean", "array", "object")
        """
        pass

    def should_scan_file(self, file_path: str) -> bool:
        """Determine if a file should be scanned for types.

        Default implementation looks for common type-related keywords in path.
        Override for language-specific patterns.

        Args:
            file_path: Path to check

        Returns:
            True if file should be scanned
        """
        file_str = str(file_path).lower()
        keywords = ("types", "models", "schema", "entities", "dto")
        return any(keyword in file_str for keyword in keywords)

    def can_handle_file(self, file_path: str) -> bool:
        """Check if this extractor can handle the given file.

        Args:
            file_path: Path to check

        Returns:
            True if file extension matches supported_extensions
        """
        ext = Path(file_path).suffix.lower()
        return ext in self.supported_extensions


class AbstractTypeExporter(ABC):
    """Abstract base class for exporting types to JSON format.

    Implementations scan projects and export type definitions
    to standardized JSON files for use by the web editor.
    """

    @property
    @abstractmethod
    def language(self) -> str:
        """Return the language identifier."""
        pass

    @abstractmethod
    def scan_project(
        self,
        base_dir: str,
        skip_dirs: tuple = ("node_modules", ".git", "__pycache__", "venv", ".venv")
    ) -> Dict[str, Any]:
        """Scan entire project for type definitions.

        Args:
            base_dir: Root directory to scan
            skip_dirs: Directory names to skip

        Returns:
            Dictionary with structure like:
            {
                "classes": {...} or "models": {...},
                "all_properties": [...]
            }
        """
        pass

    @abstractmethod
    def export_types_property(
        self,
        base_dir: str,
        server_name: str,
        output_dir: str
    ) -> str:
        """Export types to types_property_{server_name}.json.

        Args:
            base_dir: Root directory to scan
            server_name: Server name for the output file
            output_dir: Directory to write output file

        Returns:
            Path to the generated JSON file
        """
        pass


# =============================================================================
# Type Aliases for convenience
# =============================================================================

ServiceMap = Dict[str, ServiceInfo]
TypeMap = Dict[str, TypeInfo]
