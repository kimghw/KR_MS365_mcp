"""Metadata manager for CRUD operations.

mode 1(`MS365_MULTI_USER=1`)에서는 `owner_key` 가 필수이고 저장소는 사용자별
`db/metadata.db` 의 `OwnedSQLiteStorage` 하나뿐이다. JSON 저장소(전체 파일 덮어쓰기,
소유자 구분 없음)는 생성 시점에 `config_error` 로 거부한다(spec/spec_멀티유저.md ②-7.3).
"""

from typing import List, Dict, Any, Optional
import logging

from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.security_policy import multi_user_enabled

from .storage import MetadataStorage, OwnedSQLiteStorage, SQLiteStorage, JSONStorage

logger = logging.getLogger(__name__)


class MetadataManager:
    """Manage metadata operations."""

    def __init__(self, settings: Optional[Any] = None, *, owner_key: Optional[str] = None):
        """Initialize metadata manager.

        Args:
            settings: Settings object with configuration
            owner_key: 소유자 user_key. 주어지면 소유자 격리 저장소를 쓴다(mode 1 필수).
        """
        self.settings = settings
        self.owner_key = owner_key

        # Initialize storage based on settings
        if settings:
            storage_type = settings.get('metadata_storage', 'sqlite')
            storage_path = settings.get('metadata_path')
        else:
            storage_type = 'sqlite'
            storage_path = None

        if multi_user_enabled():
            if storage_type != 'sqlite':
                raise SecurityError(
                    ErrorCode.CONFIG_ERROR,
                    "멀티유저 모드에서는 SQLite metadata 저장소만 쓸 수 있습니다 (JSON 저장소 거부).",
                )
            if not owner_key or not storage_path:
                raise SecurityError(
                    ErrorCode.CONFIG_ERROR,
                    "멀티유저 metadata 저장소에는 소유자와 사용자 DB 경로가 필요합니다.",
                )

        if owner_key:
            if storage_type != 'sqlite':
                raise SecurityError(ErrorCode.CONFIG_ERROR, "소유자 격리 저장소는 SQLite 만 지원합니다.")
            self.storage: MetadataStorage = OwnedSQLiteStorage(storage_path, owner_key)
        elif storage_type == 'json':
            self.storage = JSONStorage(storage_path or 'metadata.json')
        else:
            self.storage = SQLiteStorage(storage_path or 'metadata.db')

        logger.info("Initialized %s metadata storage", storage_type)

    def save(self, file_url: str, keywords: List[str],
             additional_metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Save metadata for a file.

        Args:
            file_url: File URL or path
            keywords: List of keywords
            additional_metadata: Optional additional metadata

        Returns:
            True if successful
        """
        metadata = additional_metadata or {}

        # Add default metadata
        metadata['source'] = 'file' if not file_url.startswith('http') else 'url'

        return self.storage.save(file_url, keywords, metadata)

    def get(self, file_url: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a file.

        Args:
            file_url: File URL or path

        Returns:
            Metadata dictionary or None
        """
        return self.storage.get(file_url)

    def search(self, **search_criteria) -> List[Dict[str, Any]]:
        """Search metadata.

        Args:
            **search_criteria: Search criteria (keyword, file_url, etc.)

        Returns:
            List of matching metadata entries
        """
        return self.storage.search(**search_criteria)

    def delete(self, file_url: str) -> bool:
        """Delete metadata for a file.

        Args:
            file_url: File URL or path

        Returns:
            True if successful
        """
        return self.storage.delete(file_url)

    def update_keywords(self, file_url: str, keywords: List[str]) -> bool:
        """Update keywords for a file.

        Args:
            file_url: File URL or path
            keywords: New list of keywords

        Returns:
            True if successful
        """
        existing = self.get(file_url)
        if existing:
            return self.save(
                file_url,
                keywords,
                existing.get('metadata', {})
            )
        return False

    def add_keywords(self, file_url: str, new_keywords: List[str]) -> bool:
        """Add keywords to existing metadata.

        Args:
            file_url: File URL or path
            new_keywords: Keywords to add

        Returns:
            True if successful
        """
        existing = self.get(file_url)
        if existing:
            current_keywords = existing.get('keywords', [])
            # Add only unique keywords
            updated_keywords = list(set(current_keywords + new_keywords))
            return self.save(
                file_url,
                updated_keywords,
                existing.get('metadata', {})
            )
        return False

    def bulk_save(self, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Save multiple metadata entries.

        Args:
            entries: List of entries with file_url, keywords, metadata

        Returns:
            Summary of operation results
        """
        results = {
            'successful': 0,
            'failed': 0,
            'errors': []
        }

        for entry in entries:
            try:
                if self.save(
                    entry['file_url'],
                    entry.get('keywords', []),
                    entry.get('metadata', {})
                ):
                    results['successful'] += 1
                else:
                    results['failed'] += 1
                    results['errors'].append(f"Failed to save: {entry['file_url']}")
            except Exception as e:
                results['failed'] += 1
                results['errors'].append(f"Error with {entry['file_url']}: {type(e).__name__}")

        return results