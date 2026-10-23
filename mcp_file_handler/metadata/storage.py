"""Metadata storage implementations.

| 클래스 | 모드 | 키 | 비고 |
|--------|------|----|------|
| `SQLiteStorage` | mode 0 | `file_url` | legacy `metadata` 테이블 (소유자 열 없음) |
| `JSONStorage` | mode 0 | `file_url` | 전체 파일 덮어쓰기 — mode 1 에서는 생성 거부 |
| `OwnedSQLiteStorage` | mode 1 | `(owner_key, file_url)` | 사용자별 `db/metadata.db` 의 `file_metadata` 테이블 |

`OwnedSQLiteStorage` 는 DB 파일이 이미 사용자별로 분리돼 있어도 **모든 SQL 에 owner 조건을
붙인다**(spec/spec_멀티유저.md ②-7.3). 로그에는 file_url·경로·예외 원문을 싣지 않는다.
"""

import json
import sqlite3
from abc import ABC, abstractmethod
from contextlib import closing
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
import logging

from mcp_common.principal import is_valid_user_key
from mcp_common.security_policy import assert_legacy_store_not_frozen

logger = logging.getLogger(__name__)

# legacy(mode 0) 저장소는 멀티유저 이전 freeze 에 참여한다 (astra 2차 리뷰 N06):
# 생성 시점뿐 아니라 **쓰기마다** `.migration_lock` 을 다시 확인해, 기동 뒤에 생긴 잠금도
# writer 를 멈춘다. `assert_legacy_store_not_frozen` 은 mode 1 에서 no-op 이다.


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
        assert_legacy_store_not_frozen(db_path)
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
        assert_legacy_store_not_frozen(self.db_path)  # 쓰기 직전 재확인 (N06)
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
            logger.error("Failed to save metadata: %s", type(e).__name__)
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
            # 미존재는 위에서 None 으로 반환한다. 여기 도달하면 실제 DB 오류이므로
            # "결과 없음"으로 위장하지 않고 예외를 전파해 상위에서 실패로 드러낸다.
            logger.error("Failed to get metadata: %s", type(e).__name__)
            raise

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
            # "결과 0건"은 위에서 빈 리스트로 정상 반환한다. 여기 도달하면 실제 DB
            # 오류이므로 예외를 전파해 상위에서 실패(isError)로 드러낸다.
            logger.error("Failed to search metadata: %s", type(e).__name__)
            raise

    def delete(self, file_url: str) -> bool:
        """Delete metadata from SQLite."""
        assert_legacy_store_not_frozen(self.db_path)  # 쓰기 직전 재확인 (N06)
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('DELETE FROM metadata WHERE file_url = ?', (file_url,))
            affected = cursor.rowcount

            conn.commit()
            conn.close()

            return affected > 0

        except Exception as e:
            # 미존재(멱등 재삭제)는 affected==0 으로 정상 False 를 반환한다. 여기 도달하면
            # 실제 DB 오류이므로 예외를 전파해 상위에서 실패로 드러낸다.
            logger.error("Failed to delete metadata: %s", type(e).__name__)
            raise


class JSONStorage(MetadataStorage):
    """JSON file-based metadata storage."""

    def __init__(self, json_path: str = 'metadata.json'):
        """Initialize JSON storage.

        Args:
            json_path: Path to JSON file
        """
        self.json_path = Path(json_path)
        assert_legacy_store_not_frozen(self.json_path)
        self._load_data()

    def _load_data(self):
        """Load data from JSON file."""
        if self.json_path.exists():
            try:
                with open(self.json_path, 'r') as f:
                    self.data = json.load(f)
            except Exception as e:
                logger.error("Failed to load JSON data: %s", type(e).__name__)
                self.data = {}
        else:
            self.data = {}

    def _save_data(self):
        """Save data to JSON file."""
        assert_legacy_store_not_frozen(self.json_path)  # 쓰기 직전 재확인 (N06)
        try:
            with open(self.json_path, 'w') as f:
                json.dump(self.data, f, indent=2)
            return True
        except Exception as e:
            logger.error("Failed to save JSON data: %s", type(e).__name__)
            return False

    def save(self, file_url: str, keywords: List[str],
             metadata: Dict[str, Any]) -> bool:
        """Save metadata to JSON."""
        assert_legacy_store_not_frozen(self.json_path)  # 메모리 상태를 바꾸기 전에 확인 (N06)
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
        assert_legacy_store_not_frozen(self.json_path)  # 메모리 상태를 바꾸기 전에 확인 (N06)
        if file_url in self.data:
            del self.data[file_url]
            return self._save_data()
        return False

# ----------------------------------------------------------------------
# mode 1 — 사용자별 metadata.db (owner_key 격리)
# ----------------------------------------------------------------------
OWNED_TABLE = "file_metadata"

OWNED_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {OWNED_TABLE} (
    owner_key  TEXT NOT NULL,
    file_url   TEXT NOT NULL,
    keywords   TEXT,
    metadata   TEXT,
    created_at TEXT,
    updated_at TEXT,
    PRIMARY KEY (owner_key, file_url)
);
CREATE INDEX IF NOT EXISTS idx_{OWNED_TABLE}_owner_keywords
    ON {OWNED_TABLE} (owner_key, keywords);
"""

#: SQLite 잠금 대기(초). 같은 사용자의 동시 요청(최대 8)이 서로 기다리게 한다.
_BUSY_TIMEOUT_SECONDS = 30.0


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=_BUSY_TIMEOUT_SECONDS)
    conn.execute(f"PRAGMA busy_timeout = {int(_BUSY_TIMEOUT_SECONDS * 1000)}")
    return conn


def init_owned_schema(db_path) -> None:
    """`file_metadata` 스키마를 만든다(멱등). 다른 사용자 DB 를 열지 않는다."""
    with closing(_connect(str(db_path))) as conn, conn:
        conn.executescript(OWNED_SCHEMA)


#: LIKE 이스케이프 문자 (`ESCAPE '!'`)
_LIKE_ESCAPE = "!"


def _like_pattern(value: Any) -> str:
    """LIKE 부분일치 패턴. 사용자 입력의 `%`·`_`·`!` 는 문자 그대로 비교한다."""
    text = (
        str(value)
        .replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", _LIKE_ESCAPE + "%")
        .replace("_", _LIKE_ESCAPE + "_")
    )
    return f"%{text}%"


class OwnedSQLiteStorage(MetadataStorage):
    """소유자 격리 SQLite 저장소. 모든 조회·갱신·삭제·upsert 가 `owner_key = ?` 를 포함한다."""

    def __init__(self, db_path, owner_key: str):
        if not is_valid_user_key(owner_key):
            raise ValueError("owner_key 형식이 올바르지 않습니다")
        self.db_path = str(db_path)
        self.owner_key = owner_key
        init_owned_schema(self.db_path)

    @staticmethod
    def _row(row) -> Dict[str, Any]:
        return {
            'file_url': row[0],
            'keywords': row[1].split(',') if row[1] else [],
            'metadata': json.loads(row[2]) if row[2] else {},
            'created_at': row[3],
            'updated_at': row[4],
        }

    def save(self, file_url: str, keywords: List[str],
             metadata: Dict[str, Any]) -> bool:
        now = datetime.now().isoformat()
        try:
            with closing(_connect(self.db_path)) as conn, conn:
                conn.execute(
                    f'''
                    INSERT INTO {OWNED_TABLE}
                        (owner_key, file_url, keywords, metadata, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(owner_key, file_url) DO UPDATE SET
                        keywords = excluded.keywords,
                        metadata = excluded.metadata,
                        updated_at = excluded.updated_at
                    ''',
                    (self.owner_key, file_url, ','.join(keywords or []),
                     json.dumps(metadata or {}), now, now),
                )
            return True
        except Exception as e:
            logger.error("Failed to save metadata: %s", type(e).__name__)
            return False

    def get(self, file_url: str) -> Optional[Dict[str, Any]]:
        with closing(_connect(self.db_path)) as conn:
            row = conn.execute(
                f'''
                SELECT file_url, keywords, metadata, created_at, updated_at
                FROM {OWNED_TABLE}
                WHERE owner_key = ? AND file_url = ?
                ''',
                (self.owner_key, file_url),
            ).fetchone()
        return self._row(row) if row else None

    def search(self, **criteria) -> List[Dict[str, Any]]:
        query = (
            f'SELECT file_url, keywords, metadata, created_at, updated_at '
            f'FROM {OWNED_TABLE} WHERE owner_key = ?'
        )
        params: List[Any] = [self.owner_key]
        if criteria.get('keyword') is not None:
            query += f" AND keywords LIKE ? ESCAPE '{_LIKE_ESCAPE}'"
            params.append(_like_pattern(criteria['keyword']))
        if criteria.get('file_url') is not None:
            query += f" AND file_url LIKE ? ESCAPE '{_LIKE_ESCAPE}'"
            params.append(_like_pattern(criteria['file_url']))
        query += ' ORDER BY file_url'
        with closing(_connect(self.db_path)) as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row(row) for row in rows]

    def delete(self, file_url: str) -> bool:
        with closing(_connect(self.db_path)) as conn, conn:
            cursor = conn.execute(
                f'DELETE FROM {OWNED_TABLE} WHERE owner_key = ? AND file_url = ?',
                (self.owner_key, file_url),
            )
            return cursor.rowcount > 0
