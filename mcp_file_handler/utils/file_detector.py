"""File type detection utility."""

from pathlib import Path
from typing import Optional, Type
import mimetypes
import logging

from ..base_converter import BaseConverter
from ..converters import (
    PDFConverter,
    DOCXConverter,
    HWPConverter,
    ExcelConverter,
    OCRConverter
)

logger = logging.getLogger(__name__)


class FileDetector:
    """Detect file types and return appropriate converter."""

    def __init__(self):
        """Initialize file detector with converter mappings."""
        self.converters = [
            PDFConverter(),
            DOCXConverter(),
            HWPConverter(),
            ExcelConverter(),
            OCRConverter()
        ]

    def detect_type(self, file_path: str) -> Optional[str]:
        """Detect file type using extension and mime type.

        Args:
            file_path: Path to the file

        Returns:
            File type string or None
        """
        path = Path(file_path)

        if not path.exists():
            logger.error("File does not exist")
            return None

        # First try by extension
        ext = path.suffix.lower()
        if ext == '.pdf':
            return 'pdf'
        elif ext in ['.docx', '.doc']:
            return 'docx'
        elif ext == '.hwp':
            return 'hwp'
        elif ext in ['.xlsx', '.xls', '.xlsm', '.xlsb']:
            return 'excel'
        elif ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.tif']:
            return 'image'

        # Try mime type detection
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type:
            if 'pdf' in mime_type:
                return 'pdf'
            elif 'word' in mime_type or 'document' in mime_type:
                return 'docx'
            elif 'excel' in mime_type or 'spreadsheet' in mime_type:
                return 'excel'
            elif mime_type.startswith('image/'):
                return 'image'

        logger.warning("Unknown file type (extension %s)", path.suffix.lower() or "-")
        return None

    def get_converter(self, file_path: str) -> Optional[BaseConverter]:
        """Get appropriate converter for file.

        Args:
            file_path: Path to the file

        Returns:
            Converter instance or None
        """
        for converter in self.converters:
            if converter.supports(file_path):
                logger.info("Using %s", converter.__class__.__name__)
                return converter

        logger.warning("No converter found (extension %s)", Path(file_path).suffix.lower() or "-")
        return None

    def is_url(self, path_or_url: str) -> bool:
        """Check if input is a URL.

        Args:
            path_or_url: Path or URL string

        Returns:
            True if it's a URL
        """
        return path_or_url.startswith(('http://', 'https://', 'onedrive:'))

    def is_onedrive_url(self, url: str) -> bool:
        """Check if URL is a OneDrive URL.

        Args:
            url: URL string

        Returns:
            True if it's a OneDrive URL
        """
        onedrive_domains = [
            'onedrive.live.com',
            '1drv.ms',
            'sharepoint.com',
            'office.com'
        ]
        return any(domain in url for domain in onedrive_domains)