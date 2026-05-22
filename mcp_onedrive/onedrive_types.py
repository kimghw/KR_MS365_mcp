"""
OneDrive Types
OneDrive 관련 타입 정의 (mcp_outlook/outlook_types.py 구조 참조)
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum


class ItemType(str, Enum):
    """아이템 유형"""
    FILE = "file"
    FOLDER = "folder"
    UNKNOWN = "unknown"


class ConflictBehavior(str, Enum):
    """충돌 시 동작"""
    FAIL = "fail"
    REPLACE = "replace"
    RENAME = "rename"


@dataclass
class UserInfo:
    """사용자 정보"""
    id: str
    display_name: Optional[str] = None
    email: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserInfo":
        user = data.get("user", data)
        return cls(
            id=user.get("id", ""),
            display_name=user.get("displayName"),
            email=user.get("email"),
        )


@dataclass
class DriveInfo:
    """드라이브 정보"""
    id: str
    name: str
    drive_type: str = "personal"
    owner: Optional[UserInfo] = None
    quota_total: int = 0
    quota_used: int = 0
    quota_remaining: int = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DriveInfo":
        owner_data = data.get("owner", {})
        owner = UserInfo.from_dict(owner_data) if owner_data else None

        quota = data.get("quota", {})

        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            drive_type=data.get("driveType", "personal"),
            owner=owner,
            quota_total=quota.get("total", 0),
            quota_used=quota.get("used", 0),
            quota_remaining=quota.get("remaining", 0),
        )


@dataclass
class FileInfo:
    """파일 정보"""
    id: str
    name: str
    size: int = 0
    mime_type: Optional[str] = None
    created_datetime: Optional[str] = None
    last_modified_datetime: Optional[str] = None
    web_url: Optional[str] = None
    download_url: Optional[str] = None
    parent_path: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileInfo":
        file_info = data.get("file", {})
        parent_ref = data.get("parentReference", {})

        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            size=data.get("size", 0),
            mime_type=file_info.get("mimeType"),
            created_datetime=data.get("createdDateTime"),
            last_modified_datetime=data.get("lastModifiedDateTime"),
            web_url=data.get("webUrl"),
            download_url=data.get("@microsoft.graph.downloadUrl"),
            parent_path=parent_ref.get("path"),
        )


@dataclass
class FolderInfo:
    """폴더 정보"""
    id: str
    name: str
    child_count: int = 0
    created_datetime: Optional[str] = None
    last_modified_datetime: Optional[str] = None
    web_url: Optional[str] = None
    parent_path: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FolderInfo":
        folder_info = data.get("folder", {})
        parent_ref = data.get("parentReference", {})

        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            child_count=folder_info.get("childCount", 0),
            created_datetime=data.get("createdDateTime"),
            last_modified_datetime=data.get("lastModifiedDateTime"),
            web_url=data.get("webUrl"),
            parent_path=parent_ref.get("path"),
        )


@dataclass
class DriveItem:
    """드라이브 아이템 (파일 또는 폴더)"""
    id: str
    name: str
    item_type: ItemType = ItemType.UNKNOWN
    size: int = 0
    created_datetime: Optional[str] = None
    last_modified_datetime: Optional[str] = None
    web_url: Optional[str] = None
    download_url: Optional[str] = None
    parent_path: Optional[str] = None
    child_count: int = 0
    mime_type: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DriveItem":
        # Determine item type
        if "folder" in data:
            item_type = ItemType.FOLDER
            child_count = data.get("folder", {}).get("childCount", 0)
        elif "file" in data:
            item_type = ItemType.FILE
            child_count = 0
        else:
            item_type = ItemType.UNKNOWN
            child_count = 0

        file_info = data.get("file", {})
        parent_ref = data.get("parentReference", {})

        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            item_type=item_type,
            size=data.get("size", 0),
            created_datetime=data.get("createdDateTime"),
            last_modified_datetime=data.get("lastModifiedDateTime"),
            web_url=data.get("webUrl"),
            download_url=data.get("@microsoft.graph.downloadUrl"),
            parent_path=parent_ref.get("path"),
            child_count=child_count,
            mime_type=file_info.get("mimeType"),
        )

    def is_folder(self) -> bool:
        return self.item_type == ItemType.FOLDER

    def is_file(self) -> bool:
        return self.item_type == ItemType.FILE


@dataclass
class ReadFileRequest:
    """파일 읽기 요청"""
    file_path: str
    as_text: bool = True  # True면 텍스트로, False면 바이너리(base64)로 반환


@dataclass
class WriteFileRequest:
    """파일 쓰기 요청"""
    file_path: str
    content: str
    content_type: str = "text/plain"
    conflict_behavior: ConflictBehavior = ConflictBehavior.REPLACE


@dataclass
class DeleteFileRequest:
    """파일 삭제 요청"""
    file_path: str


@dataclass
class CreateFolderRequest:
    """폴더 생성 요청"""
    folder_name: str
    parent_path: Optional[str] = None  # None이면 루트


@dataclass
class ListFilesRequest:
    """파일 목록 조회 요청"""
    folder_path: Optional[str] = None  # None이면 루트
    search: Optional[str] = None
    limit: int = 50
    order_by: str = "name asc"


@dataclass
class SearchResult:
    """검색 결과"""
    items: List[DriveItem] = field(default_factory=list)
    total_count: int = 0
    next_link: Optional[str] = None
