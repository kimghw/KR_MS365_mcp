"""
OneNote DB Service
섹션과 페이지 정보를 데이터베이스에 저장하고 관리
최근 접근한 아이템 추적

소유자 격리 (spec/spec_멀티유저.md ②-7.3):
- 모든 SELECT/UPDATE/DELETE/UPSERT 에 `owner_key = ?` 조건이 붙는다.
- mode 0: 소유자 = 호출마다 넘어오는 `user_id`(이메일). DB 는 `database/onenote.db`.
- mode 1: 소유자 = 생성 시 고정한 principal 의 `user_key`. DB 는 사용자별 `db/onenote.db`.
  호출자가 다른 `user_id` 를 넘겨도 소유자는 바뀌지 않는다(그 값은 표시용 `user_id` 열에만 들어간다).
- 스키마 생성·구버전 이전은 `storage_schema.ensure_schema()` 가 담당한다.
"""

import json
import sqlite3
import os
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Union

from mcp_common.security_policy import assert_legacy_store_not_frozen, multi_user_enabled

from .storage_schema import ensure_schema

logger = logging.getLogger(__name__)

PathLike = Union[str, "os.PathLike[str]"]


def _err(exc: BaseException) -> str:
    """로그용 오류 표기 — 값·제목·ID 가 섞일 수 있는 메시지 원문 대신 종류만."""
    name = getattr(exc, "sqlite_errorname", None)
    return f"{type(exc).__name__}({name})" if name else type(exc).__name__


def _public(row: sqlite3.Row) -> Dict[str, Any]:
    """조회 결과 dict — 내부 소유자 키는 응답에 싣지 않는다."""
    item = dict(row)
    item.pop("owner_key", None)
    return item


class OneNoteDBService:
    """OneNote 데이터베이스 서비스 (통합 테이블)"""

    def __init__(
        self,
        db_path: PathLike = "database/onenote.db",
        *,
        owner_key: Optional[str] = None,
    ):
        """
        데이터베이스 초기화

        Args:
            db_path: 데이터베이스 파일 경로 (mode 0 기본값은 저장소 기준 database/onenote.db)
            owner_key: 고정 소유자. mode 1 에서는 필수(principal.user_key)이며, 없으면
                공용 파일로 되돌아가지 않고 실패한다.
        """
        if owner_key is None and multi_user_enabled():
            raise RuntimeError("멀티유저 모드의 OneNote DB 에는 owner_key 가 필요합니다")
        if owner_key is not None and (not isinstance(owner_key, str) or not owner_key):
            raise ValueError("owner_key 가 올바르지 않습니다")

        resolved_path = os.path.expanduser(os.fspath(db_path))
        if not os.path.isabs(resolved_path):
            if owner_key is not None:
                raise ValueError("사용자 전용 OneNote DB 경로는 절대경로여야 합니다")
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            resolved_path = os.path.join(base_dir, resolved_path)

        self.db_path = resolved_path
        self._owner_key = owner_key
        if owner_key is None:
            # 멀티유저 이전 중에는 legacy 공용 DB 를 열지 않는다 (astra 재검토 R10)
            assert_legacy_store_not_frozen(resolved_path)
        os.makedirs(os.path.dirname(resolved_path), exist_ok=True)
        # mode 0(소유자 미고정)만 구버전 행을 user_id 로 이전한다
        ensure_schema(resolved_path, legacy_backfill=owner_key is None)
        logger.info("OneNoteDBService initialized")

    # ------------------------------------------------------------------
    def _owner(self, user_id: Optional[str]) -> str:
        """이 호출의 소유자. 고정 소유자가 있으면 그것, 없으면(mode 0) user_id."""
        if self._owner_key is not None:
            return self._owner_key
        if not isinstance(user_id, str) or not user_id:
            # 소유자 조건 없는 SQL 을 만들지 않는다
            raise ValueError("user_id(소유자)가 필요합니다")
        return user_id

    def _connect(self, rows: bool = False) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        if rows:
            conn.row_factory = sqlite3.Row
        return conn

    def _before_write(self) -> None:
        """쓰기 트랜잭션 직전의 이전(migration) 동결 재검사 (astra 3차 N06).

        생성자에서 한 번 본 것으로는 부족하다 — 이미 열려 있던 mode 0 writer 는 lock 이
        생긴 뒤에도 계속 쓸 수 있다. 쓰기마다 다시 본다(`exists()` 한 번이라 싸다).
        mode 1(소유자 고정)은 사용자 전용 DB 라 동결 대상이 아니다 — no-op.
        읽기는 막지 않는다.
        """
        if self._owner_key is None:
            assert_legacy_store_not_frozen(self.db_path)

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
        아이템 저장 (섹션 또는 페이지). 기준은 (owner_key, item_id).

        item_name 이 빈 문자열이면 기존 이름을 유지하고, None 인 메타 필드는 기존 값을 유지한다.

        Returns:
            성공 여부
        """
        if item_type not in ('section', 'page'):
            raise ValueError(f"Invalid item_type: {item_type}")
        owner = self._owner(user_id)
        self._before_write()

        conn = self._connect()
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            last_accessed = now if update_accessed else None

            cursor.execute("""
                INSERT INTO onenote_items (owner_key, user_id, item_type, item_id, item_name, notebook_id, notebook_name, section_id, section_name, web_url, last_accessed, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_key, item_id) DO UPDATE SET
                    item_name = CASE WHEN excluded.item_name = '' THEN item_name ELSE excluded.item_name END,
                    notebook_id = COALESCE(excluded.notebook_id, notebook_id),
                    notebook_name = COALESCE(excluded.notebook_name, notebook_name),
                    section_id = COALESCE(excluded.section_id, section_id),
                    section_name = COALESCE(excluded.section_name, section_name),
                    web_url = COALESCE(excluded.web_url, web_url),
                    last_accessed = CASE WHEN ? = 1 THEN ? ELSE last_accessed END,
                    updated_at = ?
                WHERE onenote_items.owner_key = excluded.owner_key
            """, (
                owner, user_id or "", item_type, item_id, item_name, notebook_id, notebook_name,
                section_id, section_name, web_url, last_accessed, now,
                1 if update_accessed else 0, now, now
            ))
            conn.commit()

            logger.debug("%s 저장 완료", item_type)
            return True

        except Exception as e:
            logger.error("[ERROR] %s 저장 실패: %s", item_type, _err(e))
            return False
        finally:
            conn.close()

    def get_item_by_name(
        self,
        user_id: str,
        item_type: str,
        item_name: str,
    ) -> Optional[Dict[str, Any]]:
        """이름으로 아이템 조회 (소유자 범위)"""
        owner = self._owner(user_id)
        conn = self._connect(rows=True)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM onenote_items
                WHERE owner_key = ? AND item_type = ? AND item_name = ?
                ORDER BY updated_at DESC
                LIMIT 1
            """, (owner, item_type, item_name))

            row = cursor.fetchone()
            return _public(row) if row else None

        except Exception as e:
            logger.error("[ERROR] %s 조회 실패: %s", item_type, _err(e))
            return None
        finally:
            conn.close()

    def get_recent_items(
        self,
        user_id: str,
        item_type: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """최근 접근한 아이템 목록 (소유자 범위)"""
        owner = self._owner(user_id)
        conn = self._connect(rows=True)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM onenote_items
                WHERE owner_key = ? AND item_type = ? AND last_accessed IS NOT NULL
                ORDER BY last_accessed DESC
                LIMIT ?
            """, (owner, item_type, limit))

            return [_public(row) for row in cursor.fetchall()]

        except Exception as e:
            logger.error("[ERROR] 최근 %s 조회 실패: %s", item_type, _err(e))
            return []
        finally:
            conn.close()

    def list_items(
        self,
        user_id: str,
        item_type: Optional[str] = None,
        section_id: Optional[str] = None,
        notebook_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        아이템 목록 조회 (소유자 범위)

        Args:
            user_id: 사용자 ID
            item_type: 'section' 또는 'page' (None이면 전체)
            section_id: 섹션 ID 필터
            notebook_id: 노트북 ID 필터
            date_from / date_to: last_accessed 범위 (포함, ISO 8601 문자열 비교 — NULL 은 '' 로 본다)
            limit: 최대 행 수 (None 이면 전체 — 동기화·정리처럼 전수 조회가 필요한 곳만)
        """
        owner = self._owner(user_id)
        conn = self._connect(rows=True)
        try:
            cursor = conn.cursor()

            conditions = ["owner_key = ?"]
            params: List[Any] = [owner]

            if item_type:
                conditions.append("item_type = ?")
                params.append(item_type)

            if section_id:
                conditions.append("section_id = ?")
                params.append(section_id)

            if notebook_id:
                conditions.append("notebook_id = ?")
                params.append(notebook_id)

            if date_from:
                conditions.append("COALESCE(last_accessed, '') >= ?")
                params.append(date_from)

            if date_to:
                conditions.append("COALESCE(last_accessed, '') <= ?")
                params.append(date_to)

            where_clause = " AND ".join(conditions)
            limit_clause = ""
            if limit is not None:
                limit_clause = "LIMIT ?"
                params.append(int(limit))

            cursor.execute(f"""
                SELECT * FROM onenote_items
                WHERE {where_clause}
                ORDER BY updated_at DESC
                {limit_clause}
            """, tuple(params))

            return [_public(row) for row in cursor.fetchall()]

        except Exception as e:
            # "결과 0건"은 정상적으로 빈 리스트를 반환한다. 여기 도달하면 실제 DB
            # 오류이므로 [] 로 위장하지 않고 예외를 전파해 상위에서 실패로 드러낸다.
            logger.error("[ERROR] 아이템 목록 조회 실패: %s", _err(e))
            raise
        finally:
            conn.close()

    def delete_item(self, user_id: str, item_id: str) -> bool:
        """아이템 삭제 (소유자 범위). 지운 행이 있으면 True."""
        owner = self._owner(user_id)
        self._before_write()
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM onenote_items
                WHERE owner_key = ? AND item_id = ?
            """, (owner, item_id))
            conn.commit()
            return cursor.rowcount > 0

        except Exception as e:
            logger.error("[ERROR] 아이템 삭제 실패: %s", _err(e))
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
        """섹션 목록을 DB에 동기화"""
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

        logger.info("섹션 동기화 완료: %d개", synced_count)
        return {"success": True, "synced": synced_count}

    async def sync_pages_to_db(
        self,
        user_id: str,
        pages: List[Dict[str, Any]],
        section_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """페이지 목록을 DB에 동기화"""
        synced_count = 0
        failed_count = 0

        for page in pages:
            if self.save_item(
                user_id=user_id,
                item_type="page",
                item_id=page.get("id"),
                item_name=page.get("title", ""),
                notebook_id=page.get("notebook_id"),
                notebook_name=page.get("notebook_name"),
                section_id=page.get("parent_section_id") or section_id,
                section_name=page.get("parent_section_name"),
                web_url=page.get("web_url"),
            ):
                synced_count += 1
            else:
                failed_count += 1

        total = len(pages)
        logger.info("페이지 동기화 완료: %d개 (실패 %d개)", synced_count, failed_count)

        # 부분 실패를 은폐하지 않는다. 전량 실패(하나도 저장 못 함)는 실제 실패로
        # 드러내고, 일부만 실패한 경우는 partial 플래그로 표시하되 성공으로 둔다.
        result: Dict[str, Any] = {
            "synced": synced_count,
            "failed": failed_count,
            "total": total,
        }
        if failed_count and synced_count == 0:
            result["success"] = False
            result["error"] = "sync_all_failed"
        else:
            result["success"] = True
            if failed_count:
                result["partial"] = True
        return result

    # ========================================================================
    # 페이지 요약 관리 — 전부 (owner_key, page_id) 범위
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
        """페이지 요약 저장/갱신 (같은 소유자의 행만 갱신)"""
        owner = self._owner(user_id)
        self._before_write()
        conn = self._connect()
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute("""
                INSERT INTO onenote_page_summaries
                    (owner_key, page_id, user_id, page_title, summary, paragraph_summaries, keywords, content_hash, summarized_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_key, page_id) DO UPDATE SET
                    page_title = excluded.page_title,
                    summary = excluded.summary,
                    paragraph_summaries = excluded.paragraph_summaries,
                    keywords = excluded.keywords,
                    content_hash = excluded.content_hash,
                    summarized_at = excluded.summarized_at,
                    updated_at = excluded.updated_at
                WHERE onenote_page_summaries.owner_key = excluded.owner_key
            """, (
                owner, page_id, user_id or "", page_title,
                summary,
                json.dumps(paragraph_summaries, ensure_ascii=False),
                json.dumps(keywords, ensure_ascii=False),
                content_hash, now, now,
            ))
            conn.commit()
            logger.debug("요약 저장 완료")
            return True
        except Exception as e:
            logger.error("[ERROR] 요약 저장 실패: %s", _err(e))
            return False
        finally:
            conn.close()

    def get_summary(self, page_id: str, *, user_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """페이지 요약 조회 — 소유자의 요약만. 다른 사용자의 page_id 는 None."""
        owner = self._owner(user_id)
        conn = self._connect(rows=True)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM onenote_page_summaries WHERE owner_key = ? AND page_id = ?",
                (owner, page_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            result = _public(row)
            if result.get("paragraph_summaries"):
                result["paragraph_summaries"] = json.loads(result["paragraph_summaries"])
            if result.get("keywords"):
                result["keywords"] = json.loads(result["keywords"])
            return result
        except Exception as e:
            logger.error("[ERROR] 요약 조회 실패: %s", _err(e))
            return None
        finally:
            conn.close()

    def list_summaries(self, user_id: str) -> List[Dict[str, Any]]:
        """사용자의 요약된 페이지 목록 조회"""
        owner = self._owner(user_id)
        conn = self._connect(rows=True)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT page_id, user_id, page_title, content_hash, summarized_at, updated_at
                FROM onenote_page_summaries
                WHERE owner_key = ?
                ORDER BY summarized_at DESC
            """, (owner,))
            return [_public(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("[ERROR] 요약 목록 조회 실패: %s", _err(e))
            return []
        finally:
            conn.close()

    def delete_summary(self, page_id: str, *, user_id: Optional[str]) -> bool:
        """페이지 요약 삭제 — 소유자의 요약만 지운다."""
        owner = self._owner(user_id)
        self._before_write()
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM onenote_page_summaries WHERE owner_key = ? AND page_id = ?",
                (owner, page_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error("[ERROR] 요약 삭제 실패: %s", _err(e))
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
    # 페이지 변경 이력 관리 — 전부 소유자 범위
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
        owner = self._owner(user_id)
        self._before_write()
        conn = self._connect()
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            snippet = content_snippet[:2000] if content_snippet else None
            cursor.execute("""
                INSERT INTO onenote_page_changes
                    (owner_key, page_id, user_id, action, content_snippet, target,
                     content_hash, previous_hash, change_summary, change_keywords, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                owner, page_id, user_id or "", action, snippet, target,
                content_hash, previous_hash, change_summary,
                json.dumps(change_keywords, ensure_ascii=False) if change_keywords else None,
                now,
            ))
            conn.commit()
            logger.debug("변경 이력 저장 (%s)", action)
            return True
        except Exception as e:
            logger.error("[ERROR] 변경 이력 저장 실패: %s", _err(e))
            return False
        finally:
            conn.close()

    @staticmethod
    def _change_rows(cursor: sqlite3.Cursor) -> List[Dict[str, Any]]:
        results = []
        for row in cursor.fetchall():
            item = _public(row)
            if item.get("change_keywords"):
                item["change_keywords"] = json.loads(item["change_keywords"])
            results.append(item)
        return results

    def get_page_changes(
        self,
        page_id: str,
        limit: int = 20,
        *,
        user_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        """페이지 변경 이력 조회 (최신순) — 소유자의 이력만"""
        owner = self._owner(user_id)
        conn = self._connect(rows=True)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM onenote_page_changes
                WHERE owner_key = ? AND page_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (owner, page_id, limit))
            return self._change_rows(cursor)
        except Exception as e:
            logger.error("[ERROR] 변경 이력 조회 실패: %s", _err(e))
            return []
        finally:
            conn.close()

    def get_user_changes(
        self,
        user_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """사용자별 변경 이력 조회 (최신순)"""
        owner = self._owner(user_id)
        conn = self._connect(rows=True)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM onenote_page_changes
                WHERE owner_key = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (owner, limit))
            return self._change_rows(cursor)
        except Exception as e:
            logger.error("[ERROR] 사용자 변경 이력 조회 실패: %s", _err(e))
            return []
        finally:
            conn.close()
