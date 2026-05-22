"""Metadata storage implementations."""

import json
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class MetadataStorage(ABC):
    """Abstract base class for metadata storage."""

    @abstractmethod
    def save(self, file_url: str, keywords: List[str],
             metadata: Dict[str, Any]) -> bool:
        """Save metadata.

        Args:
            file_url: File URL or path
            keywords: List of keywords
            metadata: Additional metadata

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    def get(self, file_url: str) -> Optional[Dict[str, Any]]:
        """Get metadata for file.

        Args:
            file_url: File URL or path

        Returns:
            Metadata dictionary or None
        """
        pass

    @abstractmethod
    def search(self, **criteria) -> List[Dict[str, Any]]:
        """Search metadata.

        Args:
            **criteria: Search criteria

        Returns:
            List of matching metadata entries
        """
        pass

    @abstractmethod
    def delete(self, file_url: str) -> bool:
        """Delete metadata.

        Args:
            file_url: File URL or path

        Returns:
            True if successful
        """
        pass


class SQLiteStorage(MetadataStorage):
    """SQLite-based metadata storage."""

    def __init__(self, db_path: str = 'metadata.db'):
        """Initialize SQLite storage.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS metadata (
                file_url TEXT PRIMARY KEY,
                keywords TEXT,
                metadata TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_keywords
            ON metadata (keywords)
        ''')

        conn.commit()
        conn.close()

    def save(self, file_url: str, keywords: List[str],
             metadata: Dict[str, Any]) -> bool:
        """Save metadata to SQLite."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            now = datetime.now().isoformat()
            keywords_str = ','.join(keywords)
            metadata_str = json.dumps(metadata)

            cursor.execute('''
                INSERT OR REPLACE INTO metadata
                (file_url, keywords, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (file_url, keywords_str, metadata_str, now, now))

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            logger.error(f"Failed to save metadata: {e}")
            return False

    def get(self, file_url: str) -> Optional[Dict[str, Any]]:
        """Get metadata from SQLite."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                SELECT keywords, metadata, created_at, updated_at
                FROM metadata
                WHERE file_url = ?
            ''', (file_url,))

            row = cursor.fetchone()
            conn.close()

            if row:
                return {
                    'file_url': file_url,
                    'keywords': row[0].split(',') if row[0] else [],
                    'metadata': json.loads(row[1]),
                    'created_at': row[2],
                    'updated_at': row[3]
                }

            return None

        except Exception as e:
            logger.error(f"Failed to get metadata: {e}")
            return None

    def search(self, **criteria) -> List[Dict[str, Any]]:
        """Search metadata in SQLite."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            query = 'SELECT * FROM metadata WHERE 1=1'
            params = []

            if 'keyword' in criteria:
                query += ' AND keywords LIKE ?'
                params.append(f'%{criteria["keyword"]}%')

            if 'file_url' in criteria:
                query += ' AND file_url LIKE ?'
                params.append(f'%{criteria["file_url"]}%')

            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()

            results = []
            for row in rows:
                results.append({
                    'file_url': row[0],
                    'keywords': row[1].split(',') if row[1] else [],
                    'metadata': json.loads(row[2]),
                    'created_at': row[3],
                    'updated_at': row[4]
                })

            return results

        except Exception as e:
            logger.error(f"Failed to search metadata: {e}")
            return []

    def delete(self, file_url: str) -> bool:
        """Delete metadata from SQLite."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('DELETE FROM metadata WHERE file_url = ?', (file_url,))
            affected = cursor.rowcount

            conn.commit()
            conn.close()

            return affected > 0

        except Exception as e:
            logger.error(f"Failed to delete metadata: {e}")
            return False


class JSONStorage(MetadataStorage):
    """JSON file-based metadata storage."""

    def __init__(self, json_path: str = 'metadata.json'):
        """Initialize JSON storage.

        Args:
            json_path: Path to JSON file
        """
        self.json_path = Path(json_path)
        self._load_data()

    def _load_data(self):
        """Load data from JSON file."""
        if self.json_path.exists():
            try:
                with open(self.json_path, 'r') as f:
                    self.data = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load JSON data: {e}")
                self.data = {}
        else:
            self.data = {}

    def _save_data(self):
        """Save data to JSON file."""
        try:
            with open(self.json_path, 'w') as f:
                json.dump(self.data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save JSON data: {e}")
            return False

    def save(self, file_url: str, keywords: List[str],
             metadata: Dict[str, Any]) -> bool:
        """Save metadata to JSON."""
        self.data[file_url] = {
            'keywords': keywords,
            'metadata': metadata,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        return self._save_data()

    def get(self, file_url: str) -> Optional[Dict[str, Any]]:
        """Get metadata from JSON."""
        if file_url in self.data:
            result = self.data[file_url].copy()
            result['file_url'] = file_url
            return result
        return None

    def search(self, **criteria) -> List[Dict[str, Any]]:
        """Search metadata in JSON."""
        results = []

        for file_url, data in self.data.items():
            match = True

            if 'keyword' in criteria:
                if criteria['keyword'] not in ','.join(data.get('keywords', [])):
                    match = False

            if 'file_url' in criteria:
                if criteria['file_url'] not in file_url:
                    match = False

            if match:
                result = data.copy()
                result['file_url'] = file_url
                results.append(result)

        return results

    def delete(self, file_url: str) -> bool:
        """Delete metadata from JSON."""
        if file_url in self.data:
            del self.data[file_url]
            return self._save_data()
        return False