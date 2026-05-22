"""
MCP OneDrive Module
Microsoft Graph API를 사용한 OneDrive 서비스 (mcp_outlook 구조 참조)
"""

from .onedrive_service import OneDriveService
from .graph_onedrive_client import GraphOneDriveClient
from .onedrive_types import (
    FileInfo,
    FolderInfo,
    DriveItem,
    ReadFileRequest,
    WriteFileRequest,
    DeleteFileRequest,
    CreateFolderRequest,
)

__all__ = [
    # Service
    "OneDriveService",
    # Client
    "GraphOneDriveClient",
    # Types
    "FileInfo",
    "FolderInfo",
    "DriveItem",
    "ReadFileRequest",
    "WriteFileRequest",
    "DeleteFileRequest",
    "CreateFolderRequest",
]

__version__ = "1.0.0"
