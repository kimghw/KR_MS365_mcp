"""MCP Attachment Processing Module.

A comprehensive file conversion and management system that supports:
- Multiple file formats (PDF, DOCX, HWP, Excel, Images)
- OneDrive integration
- OCR capabilities
- Metadata management
- MCP server integration
"""

__version__ = "1.0.0"

from .file_manager import FileManager
from .base_converter import BaseConverter
from .converters import (
    PDFConverter,
    DOCXConverter,
    HWPConverter,
    ExcelConverter,
    OCRConverter
)
from .metadata import MetadataManager, MetadataStorage
from .onedrive import OneDriveClient, OneDriveDownloader, OneDriveProcessor
from .utils import FileDetector, setup_logger
from .config import Settings
# Remove MCPAttachmentServer import to avoid circular import
# from .mcp_server import MCPAttachmentServer

__all__ = [
    # Main entry point
    'FileManager',

    # Converters
    'BaseConverter',
    'PDFConverter',
    'DOCXConverter',
    'HWPConverter',
    'ExcelConverter',
    'OCRConverter',

    # Metadata
    'MetadataManager',
    'MetadataStorage',

    # OneDrive
    'OneDriveClient',
    'OneDriveDownloader',
    'OneDriveProcessor',

    # Utils
    'FileDetector',
    'setup_logger',

    # Config
    'Settings',

    # MCP Server
    # 'MCPAttachmentServer'  # Removed to avoid circular import
]