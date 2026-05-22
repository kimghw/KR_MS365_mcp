"""Base converter interface for all file converters."""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pathlib import Path


class BaseConverter(ABC):
    """Abstract base class for all file converters."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize converter with optional configuration.

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}

    @abstractmethod
    def convert(self, file_path: str) -> str:
        """Convert file to text.

        Args:
            file_path: Path to the file to convert

        Returns:
            Extracted text content

        Raises:
            ValueError: If file path is invalid
            NotImplementedError: If file type is not supported
        """
        pass

    @abstractmethod
    def supports(self, file_path: str) -> bool:
        """Check if this converter supports the given file.

        Args:
            file_path: Path to the file to check

        Returns:
            True if the converter can handle this file type
        """
        pass

    def get_metadata(self, file_path: str) -> Dict[str, Any]:
        """Extract metadata from file.

        Args:
            file_path: Path to the file

        Returns:
            Dictionary containing file metadata
        """
        path = Path(file_path)
        return {
            'filename': path.name,
            'extension': path.suffix,
            'size': path.stat().st_size if path.exists() else 0,
            'converter': self.__class__.__name__
        }