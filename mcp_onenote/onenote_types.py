"""
OneNote Types
OneNote 관련 타입 정의 (mcp_outlook/outlook_types.py 구조 참조)
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum


class PageAction(str, Enum):
    """페이지 편집 액션"""
    APPEND = "append"
    PREPEND = "prepend"
    INSERT = "insert"
    REPLACE = "replace"
    CLEAN = "clean"


class SectionAction(str, Enum):
    """섹션 관리 액션"""
    CREATE_SECTION = "create_section"
    LIST_SECTIONS = "list_sections"
    LIST_PAGES = "list_pages"


class ContentAction(str, Enum):
    """컨텐츠 관리 액션"""
    GET = "get"
    CREATE = "create"
    DELETE = "delete"


class ReadAction(str, Enum):
    """조회 액션 (read_onenote 툴용)"""
    LIST_PAGES = "list_pages"
    LIST_SECTIONS = "list_sections"
    SEARCH = "search"
    GET_CONTENT = "get_content"
    GET_SUMMARY = "get_summary"


class WriteAction(str, Enum):
    """생성/수정 액션 (write_onenote 툴용)"""
    APPEND = "append"
    CREATE_PAGE = "create_page"
    CREATE_SECTION = "create_section"


@dataclass
class NotebookInfo:
    """노트북 정보"""
    id: str
    display_name: str
    created_datetime: Optional[str] = None
    last_modified_datetime: Optional[str] = None
    is_default: bool = False
    user_role: Optional[str] = None
    is_shared: bool = False
    sections_url: Optional[str] = None
    section_groups_url: Optional[str] = None
    links: Optional[Dict[str, Any]] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NotebookInfo":
        return cls(
            id=data.get("id", ""),
            display_name=data.get("displayName", ""),
            created_datetime=data.get("createdDateTime"),
            last_modified_datetime=data.get("lastModifiedDateTime"),
            is_default=data.get("isDefault", False),
            user_role=data.get("userRole"),
            is_shared=data.get("isShared", False),
            sections_url=data.get("sectionsUrl"),
            section_groups_url=data.get("sectionGroupsUrl"),
            links=data.get("links"),
        )


@dataclass
class SectionInfo:
    """섹션 정보"""
    id: str
    display_name: str
    created_datetime: Optional[str] = None
    last_modified_datetime: Optional[str] = None
    is_default: bool = False
    parent_notebook_id: Optional[str] = None
    parent_notebook_name: Optional[str] = None
    pages_url: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SectionInfo":
        parent_notebook = data.get("parentNotebook", {})
        return cls(
            id=data.get("id", ""),
            display_name=data.get("displayName", ""),
            created_datetime=data.get("createdDateTime"),
            last_modified_datetime=data.get("lastModifiedDateTime"),
            is_default=data.get("isDefault", False),
            parent_notebook_id=parent_notebook.get("id"),
            parent_notebook_name=parent_notebook.get("displayName"),
            pages_url=data.get("pagesUrl"),
        )


@dataclass
class PageInfo:
    """페이지 정보"""
    id: str
    title: str
    created_datetime: Optional[str] = None
    last_modified_datetime: Optional[str] = None
    level: int = 0
    order: int = 0
    content_url: Optional[str] = None
    parent_section_id: Optional[str] = None
    parent_section_name: Optional[str] = None
    notebook_id: Optional[str] = None
    notebook_name: Optional[str] = None
    web_url: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PageInfo":
        parent_section = data.get("parentSection", {}) or {}
        parent_notebook = parent_section.get("parentNotebook", {}) or {}
        links = data.get("links", {}) or {}
        web_url = links.get("oneNoteWebUrl", {}).get("href") if links else None
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            created_datetime=data.get("createdDateTime"),
            last_modified_datetime=data.get("lastModifiedDateTime"),
            level=data.get("level", 0),
            order=data.get("order", 0),
            content_url=data.get("contentUrl"),
            parent_section_id=parent_section.get("id"),
            parent_section_name=parent_section.get("displayName"),
            notebook_id=parent_notebook.get("id"),
            notebook_name=parent_notebook.get("displayName"),
            web_url=web_url,
        )


@dataclass
class PageContent:
    """페이지 컨텐츠"""
    page_id: str
    title: str
    content: str  # HTML content
    created_datetime: Optional[str] = None
    last_modified_datetime: Optional[str] = None


@dataclass
class CreateSectionRequest:
    """섹션 생성 요청"""
    notebook_id: str
    section_name: str


@dataclass
class CreatePageRequest:
    """페이지 생성 요청"""
    section_id: str
    title: str
    content: str  # HTML content


@dataclass
class UpdatePageRequest:
    """페이지 업데이트 요청"""
    page_id: str
    action: PageAction = PageAction.APPEND
    content: Optional[str] = None
    target: Optional[str] = None
    position: str = "after"
    keep_title: bool = True


@dataclass
class SummaryInfo:
    """페이지 요약 정보"""
    page_id: str
    user_id: str
    page_title: Optional[str] = None
    summary: Optional[str] = None
    paragraph_summaries: Optional[List[Dict[str, Any]]] = None
    keywords: Optional[List[str]] = None
    content_hash: Optional[str] = None
    summarized_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class SyncResult:
    """동기화 결과"""
    success: bool
    sections_synced: int = 0
    pages_synced: int = 0
    sections_deleted: int = 0
    pages_deleted: int = 0
    error: Optional[str] = None


# Build functions for query construction
def build_onenote_filter_query(
    section_name: Optional[str] = None,
    page_title: Optional[str] = None,
) -> Optional[str]:
    """
    OneNote 필터 쿼리 생성

    Args:
        section_name: 섹션 이름 필터
        page_title: 페이지 제목 필터

    Returns:
        OData 필터 쿼리 문자열 또는 None
    """
    filters = []

    if section_name:
        filters.append(f"displayName eq '{section_name}'")

    if page_title:
        filters.append(f"title eq '{page_title}'")

    return " and ".join(filters) if filters else None


def build_onenote_select_query(
    fields: Optional[List[str]] = None,
) -> Optional[str]:
    """
    OneNote 선택 쿼리 생성

    Args:
        fields: 선택할 필드 목록

    Returns:
        OData 선택 쿼리 문자열 또는 None
    """
    if not fields:
        return None

    return ",".join(fields)
