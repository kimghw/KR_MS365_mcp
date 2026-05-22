"""
MCP OneNote Module
Microsoft Graph API를 사용한 OneNote 서비스 (mcp_outlook 구조 참조)
"""

from .onenote_service import OneNoteService
from .onenote_read import OneNoteReader
from .onenote_write import OneNoteWriter
from .onenote_delete import OneNoteDeleter
from .onenote_agent import OneNoteAgent
from .graph_onenote_client import GraphOneNoteClient
from .onenote_db_service import OneNoteDBService
from .onenote_types import (
    NotebookInfo,
    SectionInfo,
    PageInfo,
    PageContent,
    SummaryInfo,
    CreateSectionRequest,
    CreatePageRequest,
    UpdatePageRequest,
    SyncResult,
    ReadAction,
    WriteAction,
    PageAction,
)
from .onenote_agent import (
    parse_html_to_paragraphs,
    html_to_plain_text,
    compute_content_hash,
    load_config,
    is_sdk_available,
)

__all__ = [
    # Service (Facade)
    "OneNoteService",
    # CRUD Modules
    "OneNoteReader",
    "OneNoteWriter",
    "OneNoteDeleter",
    # Agent
    "OneNoteAgent",
    # Client
    "GraphOneNoteClient",
    # DB Service
    "OneNoteDBService",
    # Agent utilities
    "parse_html_to_paragraphs",
    "html_to_plain_text",
    "compute_content_hash",
    "load_config",
    "is_sdk_available",
    # Types
    "NotebookInfo",
    "SectionInfo",
    "PageInfo",
    "PageContent",
    "SummaryInfo",
    "CreateSectionRequest",
    "CreatePageRequest",
    "UpdatePageRequest",
    "SyncResult",
    "ReadAction",
    "WriteAction",
    "PageAction",
]

__version__ = "1.1.0"
