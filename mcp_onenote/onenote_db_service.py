"""
OneNote DB Service
섹션과 페이지 정보를 데이터베이스에 저장하고 관리
최근 접근한 아이템 추적
"""

import json
import sqlite3
import os
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class OneNoteDBService:
    """OneNote 데이터베이스 서비스 (통합 테이블)"""

    def __init__(self, db_path: str = "database/onenote.db"):
        """
        데이터베이스 초기화

        Args:
            db_path: 데이터베이스 파일 경로
        """
        # Resolve to an absolute path
        resolved_path = os.path.expanduser(db_path)
        if not os.path.isabs(resolved_path):
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            resolved_path = os.path.join(base_dir, resolved_path)

        self.db_path = resolved_path
        os.makedirs(os.path.dirname(resolved_path), exist_ok=True)
        self._ensure_tables()
        logger.info("OneNoteDBService initialized")

    def _ensure_tables(self):
        """OneNote 관련 테이블 생성"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.executescript("""
                -- OneNote 통합 아이템 테이블
                CREATE TABLE IF NOT EXISTS onenote_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    item_type TEXT NOT NULL CHECK(item_type IN ('section', 'page')),
                    item_id TEXT NOT NULL UNIQUE,
                    item_name TEXT NOT NULL,
                    notebook_id TEXT,
                    notebook_name TEXT,
                    section_id TEXT,
                    section_name TEXT,
                    web_url TEXT,
                    last_accessed TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, item_type, item_name)
                );

                -- 인덱스 생성
                CREATE INDEX IF NOT EXISTS idx_onenote_items_user_type
                    ON onenote_items(user_id, item_type);
                CREATE INDEX IF NOT EXISTS idx_onenote_items_section
                    ON onenote_items(section_id, item_type);
                CREATE INDEX IF NOT EXISTS idx_onenote_items_last_accessed
                    ON onenote_items(user_id, item_type, last_accessed DESC);
            """)
            cursor.executescript("""
                -- OneNote 페이지 요약 테이블
                CREATE TABLE IF NOT EXISTS onenote_page_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    page_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    page_title TEXT,
                    summary TEXT,
                    paragraph_summaries TEXT,
                    keywords TEXT,
                    content_hash TEXT,
                    summarized_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_page_summaries_user
                    ON onenote_page_summaries(user_id);
                CREATE INDEX IF NOT EXISTS idx_page_summaries_page
                    ON onenote_page_summaries(page_id);
            """)

            # 기존 테이블 마이그레이션: parent_id/parent_name → section_id/section_name
            cursor.execute("PRAGMA table_info(onenote_items)")
            columns = [row[1] for row in cursor.fetchall()]
            if "parent_id" in columns:
                cursor.execute("ALTER TABLE onenote_items RENAME COLUMN parent_id TO section_id")
                cursor.execute("ALTER TABLE onenote_items RENAME COLUMN parent_name TO section_name")
            if "web_url" not in columns:
                cursor.execute("ALTER TABLE onenote_items ADD COLUMN web_url TEXT")
            if "notebook_id" not in columns:
                cursor.execute("ALTER TABLE onenote_items ADD COLUMN notebook_id TEXT")
                cursor.execute("ALTER TABLE onenote_items ADD COLUMN notebook_name TEXT")
            # 페이지 변경 이력 테이블
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS onenote_page_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    page_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    content_snippet TEXT,
                    target TEXT,
                    content_hash TEXT,
                    previous_hash TEXT,
                    change_summary TEXT,
                    change_keywords TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_page_changes_page
                    ON onenote_page_changes(page_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_page_changes_user
                    ON onenote_page_changes(user_id, created_at DESC);
            """)

            conn.commit()
            logger.info("onenote_items 테이블 확인/생성 완료")
        except Exception as e:
            logger.error(f"[ERROR] 테이블 초기화 실패: {e}")
            raise
        finally:
            conn.close()

    # ========================================================================
    # 통합 아이템 관리
    # ========================================================================

    def save_item(
        self,
        user_id: str,
        item_type: str,
        item_id: str,
        item_name: str,
        notebook_id: Optional[str] = None,
        notebook_name: Optional[str] = None,
        section_id: Optional[str] = None,
        section_name: Optional[str] = None,
        web_url: Optional[str] = None,
        update_accessed: bool = False,
    ) -> bool:
        """
        아이템 저장 (섹션 또는 페이지)

        Args:
            user_id: 사용자 ID (이메일)
            item_type: 'section' 또는 'page'
            item_id: 아이템 ID (section_id 또는 page_id)
            item_name: 아이템 이름
            notebook_id: 소속 노트북 ID
            notebook_name: 소속 노트북 이름
            section_id: 소속 섹션 ID
            section_name: 소속 섹션 이름
            web_url: 웹 브라우저 URL
            update_accessed: True면 last_accessed 업데이트

        Returns:
            성공 여부
        """
        if item_type not in ('section', 'page'):
            raise ValueError(f"Invalid item_type: {item_type}")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            last_accessed = now if update_accessed else None

            cursor.execute("""
                INSERT INTO onenote_items (user_id, item_type, item_id, item_name, notebook_id, notebook_name, section_id, section_name, web_url, last_accessed, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    item_name = excluded.item_name,
                    notebook_id = COALESCE(excluded.notebook_id, notebook_id),
                    notebook_name = COALESCE(excluded.notebook_name, notebook_name),
                    section_id = COALESCE(excluded.section_id, section_id),
                    section_name = COALESCE(excluded.section_name, section_name),
                    web_url = COALESCE(excluded.web_url, web_url),
                    last_accessed = CASE WHEN ? = 1 THEN ? ELSE last_accessed END,
                    updated_at = ?
            """, (
                user_id, item_type, item_id, item_name, notebook_id, notebook_name, section_id, section_name, web_url, last_accessed, now,
                1 if update_accessed else 0, now, now
            ))
            conn.commit()

            logger.info(f"{item_type} 저장 완료: {item_name}")
            return True

        except Exception as e:
            logger.error(f"[ERROR] {item_type} 저장 실패: {e}")
            return False
        finally:
            conn.close()

    def get_item_by_name(
        self,
        user_id: str,
        item_type: str,
        item_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        이름으로 아이템 조회

        Args:
            user_id: 사용자 ID
            item_type: 'section' 또는 'page'
            item_name: 아이템 이름

        Returns:
            아이템 정보 또는 None
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM onenote_items
                WHERE user_id = ? AND item_type = ? AND item_name = ?
                ORDER BY updated_at DESC
                LIMIT 1
            """, (user_id, item_type, item_name))

            row = cursor.fetchone()
            return dict(row) if row else None

        except Exception as e:
            logger.error(f"[ERROR] {item_type} 조회 실패: {e}")
            return None
        finally:
            conn.close()

    def get_recent_items(
        self,
        user_id: str,
        item_type: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        최근 접근한 아이템 목록

        Args:
            user_id: 사용자 ID
            item_type: 'section' 또는 'page'
            limit: 조회할 개수

        Returns:
            아이템 목록
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM onenote_items
                WHERE user_id = ? AND item_type = ? AND last_accessed IS NOT NULL
                ORDER BY last_accessed DESC
                LIMIT ?
            """, (user_id, item_type, limit))

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"[ERROR] 최근 {item_type} 조회 실패: {e}")
            return []
        finally:
            conn.close()

    def list_items(
        self,
        user_id: str,
        item_type: Optional[str] = None,
        section_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        아이템 목록 조회

        Args:
            user_id: 사용자 ID
            item_type: 'section' 또는 'page' (None이면 전체)
            section_id: 섹션 ID 필터

        Returns:
            아이템 목록
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()

            conditions = ["user_id = ?"]
            params = [user_id]

            if item_type:
                conditions.append("item_type = ?")
                params.append(item_type)

            if section_id:
                conditions.append("section_id = ?")
                params.append(section_id)

            where_clause = " AND ".join(conditions)

            cursor.execute(f"""
                SELECT * FROM onenote_items
                WHERE {where_clause}
                ORDER BY updated_at DESC
            """, tuple(params))

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"[ERROR] 아이템 목록 조회 실패: {e}")
            return []
        finally:
            conn.close()

    def delete_item(self, user_id: str, item_id: str) -> bool:
        """
        아이템 삭제

        Args:
            user_id: 사용자 ID
            item_id: 아이템 ID

        Returns:
            성공 여부
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM onenote_items
                WHERE user_id = ? AND item_id = ?
            """, (user_id, item_id))
            conn.commit()

            if cursor.rowcount > 0:
                logger.info(f"아이템 삭제 완료: {item_id}")
                return True
            return False

        except Exception as e:
            logger.error(f"[ERROR] 아이템 삭제 실패: {e}")
            return False
        finally:
            conn.close()

    # ========================================================================
    # 동기화 기능
    # ========================================================================

    async def sync_sections_to_db(
        self,
        user_id: str,
        sections: List[Dict[str, Any]],
        notebook_id: Optional[str] = None,
        notebook_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        섹션 목록을 DB에 동기화

        Args:
            user_id: 사용자 ID
            sections: Graph API에서 조회한 섹션 목록
            notebook_id: 노트북 ID
            notebook_name: 노트북 이름

        Returns:
            동기화 결과
        """
        synced_count = 0

        for section in sections:
            s_id = section.get("id")
            s_name = section.get("displayName") or section.get("display_name", "")

            if self.save_item(
                user_id=user_id,
                item_type="section",
                item_id=s_id,
                item_name=s_name,
            ):
                synced_count += 1

        logger.info(f"섹션 동기화 완료: {synced_count}개")
        return {"success": True, "synced": synced_count}

    async def sync_pages_to_db(
        self,
        user_id: str,
        pages: List[Dict[str, Any]],
        section_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        페이지 목록을 DB에 동기화

        Args:
            user_id: 사용자 ID
            pages: Graph API에서 조회한 페이지 목록
            section_id: 섹션 ID

        Returns:
            동기화 결과
        """
        synced_count = 0

        for page in pages:
            page_id = page.get("id")
            page_title = page.get("title", "")
            web_url = page.get("web_url")
            p_section_id = page.get("parent_section_id") or section_id
            p_section_name = page.get("parent_section_name")
            p_notebook_id = page.get("notebook_id")
            p_notebook_name = page.get("notebook_name")

            if self.save_item(
                user_id=user_id,
                item_type="page",
                item_id=page_id,
                item_name=page_title,
                notebook_id=p_notebook_id,
                notebook_name=p_notebook_name,
                section_id=p_section_id,
                section_name=p_section_name,
                web_url=web_url,
            ):
                synced_count += 1

        logger.info(f"페이지 동기화 완료: {synced_count}개")
        return {"success": True, "synced": synced_count}

    # ========================================================================
    # 페이지 요약 관리
    # ========================================================================

    def save_summary(
        self,
        page_id: str,
        user_id: str,
        page_title: str,
        summary: str,
        paragraph_summaries: List[Dict[str, Any]],
        keywords: List[str],
        content_hash: str,
    ) -> bool:
        """페이지 요약 저장/갱신"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute("""
                INSERT INTO onenote_page_summaries
                    (page_id, user_id, page_title, summary, paragraph_summaries, keywords, content_hash, summarized_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(page_id) DO UPDATE SET
                    page_title = excluded.page_title,
                    summary = excluded.summary,
                    paragraph_summaries = excluded.paragraph_summaries,
                    keywords = excluded.keywords,
                    content_hash = excluded.content_hash,
                    summarized_at = excluded.summarized_at,
                    updated_at = excluded.updated_at
            """, (
                page_id, user_id, page_title,
                summary,
                json.dumps(paragraph_summaries, ensure_ascii=False),
                json.dumps(keywords, ensure_ascii=False),
                content_hash, now, now,
            ))
            conn.commit()
            logger.info(f"요약 저장 완료: {page_title}")
            return True
        except Exception as e:
            logger.error(f"[ERROR] 요약 저장 실패: {e}")
            return False
        finally:
            conn.close()

    def get_summary(self, page_id: str) -> Optional[Dict[str, Any]]:
        """페이지 요약 조회"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM onenote_page_summaries WHERE page_id = ?",
                (page_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            result = dict(row)
            if result.get("paragraph_summaries"):
                result["paragraph_summaries"] = json.loads(result["paragraph_summaries"])
            if result.get("keywords"):
                result["keywords"] = json.loads(result["keywords"])
            return result
        except Exception as e:
            logger.error(f"[ERROR] 요약 조회 실패: {e}")
            return None
        finally:
            conn.close()

    def list_summaries(self, user_id: str) -> List[Dict[str, Any]]:
        """사용자의 요약된 페이지 목록 조회"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT page_id, user_id, page_title, content_hash, summarized_at, updated_at
                FROM onenote_page_summaries
                WHERE user_id = ?
                ORDER BY summarized_at DESC
            """, (user_id,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"[ERROR] 요약 목록 조회 실패: {e}")
            return []
        finally:
            conn.close()

    def delete_summary(self, page_id: str) -> bool:
        """페이지 요약 삭제"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM onenote_page_summaries WHERE page_id = ?",
                (page_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"[ERROR] 요약 삭제 실패: {e}")
            return False
        finally:
            conn.close()

    # ========================================================================
    # 하위 호환성 메서드 (섹션/페이지 별도 API)
    # ========================================================================

    def save_section(
        self,
        user_id: str,
        notebook_id: str,
        section_id: str,
        section_name: str,
        notebook_name: Optional[str] = None,
        update_accessed: bool = False,
    ) -> bool:
        """섹션 저장 (하위 호환)"""
        return self.save_item(
            user_id=user_id,
            item_type="section",
            item_id=section_id,
            item_name=section_name,
            update_accessed=update_accessed,
        )

    def get_section(self, user_id: str, section_name: str) -> Optional[Dict[str, Any]]:
        """섹션 조회 (하위 호환)"""
        item = self.get_item_by_name(user_id, "section", section_name)
        if item:
            return {
                "section_id": item["item_id"],
                "section_name": item["item_name"],
                "user_id": item["user_id"],
                "last_accessed": item.get("last_accessed"),
            }
        return None

    def get_recent_section(self, user_id: str, limit: int = 1) -> Optional[Dict[str, Any]]:
        """최근 섹션 조회 (하위 호환)"""
        items = self.get_recent_items(user_id, "section", limit)
        if not items:
            return None if limit == 1 else []

        mapped = [{
            "section_id": item["item_id"],
            "section_name": item["item_name"],
            "user_id": item["user_id"],
            "last_accessed": item.get("last_accessed"),
        } for item in items]

        return mapped[0] if limit == 1 else mapped

    def save_page(
        self,
        user_id: str,
        section_id: str,
        page_id: str,
        page_title: str,
        update_accessed: bool = False,
    ) -> bool:
        """페이지 저장 (하위 호환)"""
        return self.save_item(
            user_id=user_id,
            item_type="page",
            item_id=page_id,
            item_name=page_title,
            section_id=section_id,
            update_accessed=update_accessed,
        )

    def get_page(self, user_id: str, page_title: str) -> Optional[Dict[str, Any]]:
        """페이지 조회 (하위 호환)"""
        item = self.get_item_by_name(user_id, "page", page_title)
        if item:
            return {
                "page_id": item["item_id"],
                "page_title": item["item_name"],
                "section_id": item.get("section_id"),
                "user_id": item["user_id"],
                "last_accessed": item.get("last_accessed"),
            }
        return None

    def get_recent_page(self, user_id: str, limit: int = 1) -> Optional[Dict[str, Any]]:
        """최근 페이지 조회 (하위 호환)"""
        items = self.get_recent_items(user_id, "page", limit)
        if not items:
            return None if limit == 1 else []

        mapped = [{
            "page_id": item["item_id"],
            "page_title": item["item_name"],
            "section_id": item.get("section_id"),
            "user_id": item["user_id"],
            "last_accessed": item.get("last_accessed"),
        } for item in items]

        return mapped[0] if limit == 1 else mapped

    # ========================================================================
    # 페이지 변경 이력 관리
    # ========================================================================

    def save_page_change(
        self,
        page_id: str,
        user_id: str,
        action: str,
        content_snippet: Optional[str] = None,
        target: Optional[str] = None,
        content_hash: Optional[str] = None,
        previous_hash: Optional[str] = None,
        change_summary: Optional[str] = None,
        change_keywords: Optional[List[str]] = None,
    ) -> bool:
        """페이지 변경 이력 저장"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            snippet = content_snippet[:2000] if content_snippet else None
            cursor.execute("""
                INSERT INTO onenote_page_changes
                    (page_id, user_id, action, content_snippet, target,
                     content_hash, previous_hash, change_summary, change_keywords, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                page_id, user_id, action, snippet, target,
                content_hash, previous_hash, change_summary,
                json.dumps(change_keywords, ensure_ascii=False) if change_keywords else None,
                now,
            ))
            conn.commit()
            logger.info(f"변경 이력 저장: {page_id} ({action})")
            return True
        except Exception as e:
            logger.error(f"[ERROR] 변경 이력 저장 실패: {e}")
            return False
        finally:
            conn.close()

    def get_page_changes(
        self,
        page_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """페이지 변경 이력 조회 (최신순)"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM onenote_page_changes
                WHERE page_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (page_id, limit))
            rows = cursor.fetchall()
            results = []
            for row in rows:
                item = dict(row)
                if item.get("change_keywords"):
                    item["change_keywords"] = json.loads(item["change_keywords"])
                results.append(item)
            return results
        except Exception as e:
            logger.error(f"[ERROR] 변경 이력 조회 실패: {e}")
            return []
        finally:
            conn.close()

    def get_user_changes(
        self,
        user_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """사용자별 변경 이력 조회 (최신순)"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM onenote_page_changes
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (user_id, limit))
            rows = cursor.fetchall()
            results = []
            for row in rows:
                item = dict(row)
                if item.get("change_keywords"):
                    item["change_keywords"] = json.loads(item["change_keywords"])
                results.append(item)
            return results
        except Exception as e:
            logger.error(f"[ERROR] 사용자 변경 이력 조회 실패: {e}")
            return []
        finally:
            conn.close()
