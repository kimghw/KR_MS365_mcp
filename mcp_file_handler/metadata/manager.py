"""Metadata manager for CRUD operations."""

from typing import List, Dict, Any, Optional
import logging

from .storage import MetadataStorage, SQLiteStorage, JSONStorage

logger = logging.getLogger(__name__)


class MetadataManager:
    """Manage metadata operations."""

    def __init__(self, settings: Optional[Any] = None):
        """Initialize metadata manager.

        Args:
            settings: Settings object with configuration
        """
        self.settings = settings

        # Initialize storage based on settings
        if settings:
            storage_type = settings.get('metadata_storage', 'sqlite')
            storage_path = settings.get('metadata_path')
        else:
            storage_type = 'sqlite'
            storage_path = None

        if storage_type == 'json':
            self.storage = JSONStorage(storage_path or 'metadata.json')
        else:
            self.storage = SQLiteStorage(storage_path or 'metadata.db')

        logger.info(f"Initialized {storage_type} metadata storage")

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
                results['errors'].append(f"Error with {entry['file_url']}: {e}")

        return results