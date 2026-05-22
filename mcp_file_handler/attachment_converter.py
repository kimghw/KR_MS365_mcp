"""
Attachment Converter API
Provides compatibility layer for mail_to_text_converter.py
"""
from pathlib import Path
from typing import Optional, Dict, Any
import logging

from .file_manager import FileManager

logger = logging.getLogger(__name__)


class AttachmentAPI:
    """API for attachment file conversion"""

    def __init__(self):
        """Initialize the attachment API"""
        self.file_manager = FileManager()

    def convert_file(self, file_path: str) -> str:
        """
        Convert a file to text

        Args:
            file_path: Path to the file to convert

        Returns:
            Extracted text content
        """
        try:
            result = self.file_manager.process(file_path)
            if result.get('success'):
                return result.get('text', '')
            else:
                logger.error(f"Failed to convert {file_path}: {result.get('errors')}")
                return ''
        except Exception as e:
            logger.error(f"Error converting file {file_path}: {e}")
            return ''

    def process_attachment(self, attachment_path: str) -> Dict[str, Any]:
        """
        Process an attachment file

        Args:
            attachment_path: Path to the attachment

        Returns:
            Processing result dictionary
        """
        return self.file_manager.process(attachment_path)


class UnifiedAttachmentConverter:
    """Unified converter for all attachment types"""

    def __init__(self):
        """Initialize the unified converter"""
        self.file_manager = FileManager()

    def convert(self, file_path: str, output_format: str = 'text') -> Dict[str, Any]:
        """
        Convert file with specified output format

        Args:
            file_path: Path to the file
            output_format: Output format ('text' or 'json')

        Returns:
            Conversion result
        """
        result = self.file_manager.process(file_path, output_format=output_format)
        return result

    def supports(self, file_path: str) -> bool:
        """
        Check if file type is supported

        Args:
            file_path: Path to check

        Returns:
            True if supported
        """
        from .utils import FileDetector
        detector = FileDetector()
        converter = detector.get_converter(file_path)
        return converter is not None