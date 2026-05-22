"""
Scanner and Type Extractor Registry.

This module provides a registry pattern for managing language-specific
scanners and type extractors. New languages can be added by:
1. Implementing the abstract interfaces
2. Registering with the appropriate registry

Usage:
    # Register a new scanner
    from service_registry.registry import ScannerRegistry
    from service_registry.go.scanner import GoServiceScanner

    ScannerRegistry.register(GoServiceScanner)

    # Get scanner for a file
    scanner = ScannerRegistry.get_for_file("main.go")
    if scanner:
        services = scanner.scan_file("main.go")

    # Scan with all registered scanners
    all_services = ScannerRegistry.scan_file("service.py")
"""

from pathlib import Path
from typing import Dict, List, Optional, Type

from .interfaces import (
    AbstractServiceScanner,
    AbstractTypeExtractor,
    ServiceInfo,
    TypeInfo,
)


class ScannerRegistry:
    """Registry for language-specific service scanners.

    This class maintains a collection of scanner implementations
    and provides methods to find appropriate scanners for files.

    Class Attributes:
        _scanners: Dictionary mapping language names to scanner classes
        _instances: Cached scanner instances
    """

    _scanners: Dict[str, Type[AbstractServiceScanner]] = {}
    _instances: Dict[str, AbstractServiceScanner] = {}

    @classmethod
    def register(cls, scanner_class: Type[AbstractServiceScanner]) -> None:
        """Register a scanner class.

        Args:
            scanner_class: Scanner class to register

        Example:
            ScannerRegistry.register(PythonServiceScanner)
        """
        # Create temporary instance to get language
        temp_instance = scanner_class()
        language = temp_instance.language
        cls._scanners[language] = scanner_class
        # Clear cached instance if exists
        if language in cls._instances:
            del cls._instances[language]

    @classmethod
    def unregister(cls, language: str) -> bool:
        """Unregister a scanner by language.

        Args:
            language: Language identifier to unregister

        Returns:
            True if scanner was unregistered, False if not found
        """
        if language in cls._scanners:
            del cls._scanners[language]
            if language in cls._instances:
                del cls._instances[language]
            return True
        return False

    @classmethod
    def get(cls, language: str) -> Optional[AbstractServiceScanner]:
        """Get scanner instance for a language.

        Args:
            language: Language identifier (e.g., 'python', 'javascript')

        Returns:
            Scanner instance or None if not registered
        """
        if language not in cls._scanners:
            return None

        # Use cached instance if available
        if language not in cls._instances:
            cls._instances[language] = cls._scanners[language]()

        return cls._instances[language]

    @classmethod
    def get_for_file(cls, file_path: str) -> Optional[AbstractServiceScanner]:
        """Get appropriate scanner for a file based on extension.

        Args:
            file_path: Path to the file

        Returns:
            Scanner instance that can handle the file, or None
        """
        ext = Path(file_path).suffix.lower()

        for language, scanner_class in cls._scanners.items():
            if language not in cls._instances:
                cls._instances[language] = scanner_class()

            scanner = cls._instances[language]
            if ext in scanner.supported_extensions:
                return scanner

        return None

    @classmethod
    def get_all(cls) -> Dict[str, AbstractServiceScanner]:
        """Get all registered scanner instances.

        Returns:
            Dictionary mapping language names to scanner instances
        """
        result = {}
        for language, scanner_class in cls._scanners.items():
            if language not in cls._instances:
                cls._instances[language] = scanner_class()
            result[language] = cls._instances[language]
        return result

    @classmethod
    def get_languages(cls) -> List[str]:
        """Get list of registered language names.

        Returns:
            List of registered language identifiers
        """
        return list(cls._scanners.keys())

    @classmethod
    def scan_file(cls, file_path: str) -> Dict[str, ServiceInfo]:
        """Scan a file using the appropriate scanner.

        Args:
            file_path: Path to the source file

        Returns:
            Dictionary mapping service names to ServiceInfo,
            empty dict if no scanner found or file can't be parsed
        """
        scanner = cls.get_for_file(file_path)
        if scanner:
            try:
                return scanner.scan_file(file_path)
            except Exception:
                return {}
        return {}

    @classmethod
    def clear(cls) -> None:
        """Clear all registered scanners. Useful for testing."""
        cls._scanners.clear()
        cls._instances.clear()


class TypeExtractorRegistry:
    """Registry for language-specific type extractors.

    Similar to ScannerRegistry but for type extraction.

    Class Attributes:
        _extractors: Dictionary mapping language names to extractor classes
        _instances: Cached extractor instances
    """

    _extractors: Dict[str, Type[AbstractTypeExtractor]] = {}
    _instances: Dict[str, AbstractTypeExtractor] = {}

    @classmethod
    def register(cls, extractor_class: Type[AbstractTypeExtractor]) -> None:
        """Register a type extractor class.

        Args:
            extractor_class: Type extractor class to register
        """
        temp_instance = extractor_class()
        language = temp_instance.language
        cls._extractors[language] = extractor_class
        if language in cls._instances:
            del cls._instances[language]

    @classmethod
    def unregister(cls, language: str) -> bool:
        """Unregister a type extractor by language.

        Args:
            language: Language identifier to unregister

        Returns:
            True if extractor was unregistered, False if not found
        """
        if language in cls._extractors:
            del cls._extractors[language]
            if language in cls._instances:
                del cls._instances[language]
            return True
        return False

    @classmethod
    def get(cls, language: str) -> Optional[AbstractTypeExtractor]:
        """Get type extractor instance for a language.

        Args:
            language: Language identifier

        Returns:
            Type extractor instance or None if not registered
        """
        if language not in cls._extractors:
            return None

        if language not in cls._instances:
            cls._instances[language] = cls._extractors[language]()

        return cls._instances[language]

    @classmethod
    def get_for_file(cls, file_path: str) -> Optional[AbstractTypeExtractor]:
        """Get appropriate type extractor for a file based on extension.

        Args:
            file_path: Path to the file

        Returns:
            Type extractor instance that can handle the file, or None
        """
        ext = Path(file_path).suffix.lower()

        for language, extractor_class in cls._extractors.items():
            if language not in cls._instances:
                cls._instances[language] = extractor_class()

            extractor = cls._instances[language]
            if ext in extractor.supported_extensions:
                return extractor

        return None

    @classmethod
    def get_all(cls) -> Dict[str, AbstractTypeExtractor]:
        """Get all registered type extractor instances.

        Returns:
            Dictionary mapping language names to extractor instances
        """
        result = {}
        for language, extractor_class in cls._extractors.items():
            if language not in cls._instances:
                cls._instances[language] = extractor_class()
            result[language] = cls._instances[language]
        return result

    @classmethod
    def get_languages(cls) -> List[str]:
        """Get list of registered language names.

        Returns:
            List of registered language identifiers
        """
        return list(cls._extractors.keys())

    @classmethod
    def extract_from_file(cls, file_path: str) -> Dict[str, TypeInfo]:
        """Extract types from a file using the appropriate extractor.

        Args:
            file_path: Path to the source file

        Returns:
            Dictionary mapping type names to TypeInfo,
            empty dict if no extractor found or file can't be parsed
        """
        extractor = cls.get_for_file(file_path)
        if extractor:
            try:
                return extractor.extract_types_from_file(file_path)
            except Exception:
                return {}
        return {}

    @classmethod
    def clear(cls) -> None:
        """Clear all registered extractors. Useful for testing."""
        cls._extractors.clear()
        cls._instances.clear()


def register_all_default_scanners() -> None:
    """Register all built-in language scanners.

    Call this function to register Python and JavaScript scanners.
    This is called automatically when importing the service_registry package.
    """
    try:
        from .python.scanner_adapter import PythonServiceScanner
        ScannerRegistry.register(PythonServiceScanner)
    except ImportError:
        pass

    try:
        from .javascript.scanner_adapter import JavaScriptServiceScanner
        ScannerRegistry.register(JavaScriptServiceScanner)
    except ImportError:
        pass


def register_all_default_extractors() -> None:
    """Register all built-in type extractors.

    Call this function to register Python and JavaScript type extractors.
    This is called automatically when importing the service_registry package.
    """
    try:
        from .python.types_adapter import PythonTypeExtractor
        TypeExtractorRegistry.register(PythonTypeExtractor)
    except ImportError:
        pass

    try:
        from .javascript.types_adapter import JavaScriptTypeExtractor
        TypeExtractorRegistry.register(JavaScriptTypeExtractor)
    except ImportError:
        pass
