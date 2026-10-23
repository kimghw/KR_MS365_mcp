"""
Teams DB Manager
Teams 채팅 정보의 데이터베이스 관리
한글 이름 저장 및 채팅 목록 동기화

소유자 격리 (spec/spec_멀티유저.md ②-7.3):
- 모든 SELECT/UPDATE/UPSERT 에 `owner_key = ?` 조건이 붙는다.
- mode 0: 소유자 = 호출마다 넘어오는 `user_id`(이메일). DB 는 기존 `database/auth.db`.
- mode 1: 소유자 = 생성 시 고정한 principal 의 `user_key`. DB 는 사용자별 `db/teams.db`
  (auth.db 경로는 거부한다). 넘어온 `user_id` 는 표시용 열과 1:1 상대방 판별에만 쓴다.
- 스키마 생성·구버전 이전은 `storage_schema.ensure_schema()` 가 담당한다.
"""

import json
import sqlite3
import os
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Union

from mcp_common.security_policy import multi_user_enabled

from .storage_schema import ensure_schema, is_auth_db_path

logger = logging.getLogger(__name__)

PathLike = Union[str, "os.PathLike[str]"]


def _err(exc: BaseException) -> str:
    """로그·응답용 오류 표기 — 메시지 원문 대신 종류만."""
    name = getattr(exc, "sqlite_errorname", None)
    return f"{type(exc).__name__}({name})" if name else type(exc).__name__


def _public(row: sqlite3.Row) -> Dict[str, Any]:
    item = dict(row)
    item.pop("owner_key", None)
    return item


class TeamsDBManager:
    """Teams 채팅 DB 관리"""

    def __init__(self, db_path: PathLike = "database/auth.db", *, owner_key: Optional[str] = None):
        """
        데이터베이스 초기화

        Args:
            db_path: 데이터베이스 파일 경로 (mode 0 기본값은 저장소 기준 database/auth.db)
            owner_key: 고정 소유자. mode 1 에서는 필수(principal.user_key) — 없거나 경로가
                auth.db 면 공용 저장소로 되돌아가지 않고 실패한다.
        """
        if owner_key is None and multi_user_enabled():
            raise RuntimeError("멀티유저 모드의 Teams DB 에는 owner_key 가 필요합니다")
        if owner_key is not None:
            if not isinstance(owner_key, str) or not owner_key:
                raise ValueError("owner_key 가 올바르지 않습니다")
            if is_auth_db_path(db_path):
                raise ValueError("사용자 전용 Teams DB 는 auth.db 에 둘 수 없습니다")

        resolved_path = os.path.expanduser(os.fspath(db_path))
        if not os.path.isabs(resolved_path):
            if owner_key is not None:
                raise ValueError("사용자 전용 Teams DB 경로는 절대경로여야 합니다")
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            resolved_path = os.path.join(base_dir, resolved_path)

        self.db_path = resolved_path
        self._owner_key = owner_key
        os.makedirs(os.path.dirname(resolved_path), exist_ok=True)
        self._ensure_tables()

    def _ensure_tables(self):
        """Teams 관련 테이블 생성 (mode 0 만 구버전 행을 user_id 로 이전)"""
        try:
            ensure_schema(self.db_path, legacy_backfill=self._owner_key is None)
            logger.info("Teams tables created successfully")
        except Exception as e:
            logger.error("[ERROR] Failed to create Teams tables: %s", _err(e))
            raise

    def _owner(self, user_id: Optional[str]) -> str:
        """이 호출의 소유자. 고정 소유자가 있으면 그것, 없으면(mode 0) user_id."""
        if self._owner_key is not None:
            return self._owner_key
        if not isinstance(user_id, str) or not user_id:
            # 소유자 조건 없는 SQL 을 만들지 않는다
            raise ValueError("user_id(소유자)가 필요합니다")
        return user_id

    def _contains_hangul(self, text: str) -> bool:
        """한글 포함 여부 확인"""
        try:
            return any("가" <= ch <= "힣" for ch in text)
        except Exception:
            return False

    async def find_chat_by_name(self, user_id: str, recipient_name: str) -> Optional[str]:
        """
        사용자 이름으로 chat_id 검색 (활성/비활성 모두 검색, 활성 우선)

        Returns:
            chat_id 또는 None
        """
        owner = self._owner(user_id)
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT chat_id FROM teams_chats
                WHERE owner_key = ?
                AND (
                    LOWER(peer_user_name) LIKE LOWER(?)
                    OR LOWER(topic) LIKE LOWER(?)
                    OR LOWER(topic_kr) LIKE LOWER(?)
                )
                ORDER BY
                    is_active DESC,
                    last_message_time DESC
                LIMIT 1
                """,
                (owner, f"%{recipient_name}%", f"%{recipient_name}%", f"%{recipient_name}%")
            )

            row = cursor.fetchone()
            if row:
                logger.debug("채팅 이름 검색: 일치")
                return row[0]
            # 정상적인 "검색 결과 없음"은 None 으로 돌려주고, 상위 서비스가
            # soft(success:True, found:False)로 변환한다.
            logger.debug("채팅 이름 검색: 일치 없음")
            return None

        except Exception as e:
            # DB 예외를 None(미검색)으로 위장하면 실패가 정상처럼 보인다.
            # 실제 예외는 전파해 상위에서 isError 로 드러낸다.
            logger.error("[ERROR] 채팅 검색 오류: %s", _err(e))
            raise
        finally:
            conn.close()

    async def save_korean_name(
        self,
        user_id: str,
        topic_kr: str,
        chat_id: Optional[str] = None,
        topic_en: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        채팅의 한글 이름을 저장 (소유자의 채팅만)

        Args:
            user_id: 사용자 ID (이메일)
            topic_kr: 한글 이름
            chat_id: 채팅 ID (선택)
            topic_en: 영문 이름 (선택, chat_id가 없을 때 검색용)
        """
        if not topic_kr:
            return {"success": False, "message": "한글 이름(topic_kr)이 필요합니다"}
        owner = self._owner(user_id)

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # chat_id가 없으면 topic_en으로 검색
            if not chat_id and topic_en:
                cursor.execute(
                    """
                    SELECT chat_id FROM teams_chats
                    WHERE owner_key = ?
                    AND is_active = TRUE
                    AND (
                        LOWER(peer_user_name) LIKE LOWER(?)
                        OR LOWER(topic) LIKE LOWER(?)
                    )
                    ORDER BY last_message_time DESC
                    LIMIT 1
                    """,
                    (owner, f"%{topic_en}%", f"%{topic_en}%")
                )

                row = cursor.fetchone()
                if row:
                    chat_id = row[0]
                else:
                    # 영문 이름으로 채팅을 못 찾은 것은 스키마상 합법적인 정상 상태다.
                    # 도구 실행 실패가 아니므로 soft(saved:False)로 안내한다.
                    return {
                        "success": True,
                        "saved": False,
                        "found": False,
                        "reason": "chat_not_found",
                        "message": f"영문 이름 '{topic_en}'으로 채팅을 찾을 수 없습니다",
                    }

            # chat_id로 한글 이름 업데이트
            if chat_id:
                cursor.execute(
                    """
                    UPDATE teams_chats
                    SET topic_kr = ?, updated_at = ?
                    WHERE owner_key = ? AND chat_id = ?
                    """,
                    (topic_kr, datetime.now(timezone.utc).isoformat(), owner, chat_id)
                )
                conn.commit()

                if cursor.rowcount > 0:
                    logger.info("한글 이름 저장 완료")
                    return {
                        "success": True,
                        "saved": True,
                        "message": f"한글 이름 '{topic_kr}' 저장 완료",
                        "chat_id": chat_id
                    }
                # rowcount 0 = 해당 chat 이 아직 (이 사용자의) DB 에 sync 되지 않음. 정상 상태이므로
                # soft(saved:False)로 안내한다(먼저 sync_chats 필요).
                return {
                    "success": True,
                    "saved": False,
                    "reason": "not_synced",
                    "chat_id": chat_id,
                    "message": f"chat_id '{chat_id}'가 DB에 없습니다. 먼저 채팅을 동기화(sync)하세요",
                }
            # chat_id/topic_en 둘 다 없음 = 입력 부족(validation). 실패로 유지.
            return {"success": False, "message": "chat_id 또는 topic_en이 필요합니다"}

        except Exception as e:
            logger.error("[ERROR] 한글 이름 저장 오류: %s", _err(e))
            return {"success": False, "message": f"오류 발생: {_err(e)}"}
        finally:
            conn.close()

    async def save_korean_names_batch(
        self,
        user_id: str,
        names: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """
        여러 채팅의 한글 이름을 한 번에 저장

        Args:
            user_id: 사용자 ID (이메일)
            names: [{"topic_en": "영문", "topic_kr": "한글"}, ...] 형식의 리스트

        Returns:
            {"success": True, "saved": 3, "failed": 1, "results": [...]}
        """
        results = []
        saved_count = 0
        failed_count = 0

        for item in names:
            topic_en = item.get("topic_en", "")
            topic_kr = item.get("topic_kr", "")

            if not topic_en or not topic_kr:
                results.append({
                    "topic_en": topic_en,
                    "topic_kr": topic_kr,
                    "success": False,
                    "saved": False,
                    "message": "topic_en과 topic_kr이 모두 필요합니다"
                })
                failed_count += 1
                continue

            result = await self.save_korean_name(user_id, topic_kr, None, topic_en)
            results.append({
                "topic_en": topic_en,
                "topic_kr": topic_kr,
                **result
            })

            # "저장됨" 여부는 success 가 아니라 saved 플래그로 센다. soft 전환 이후
            # 못 찾음/미동기화는 success:True 지만 saved:False 이므로 미저장으로 집계.
            if result.get("saved"):
                saved_count += 1
            else:
                failed_count += 1

        return {
            "success": True,
            "saved": saved_count,
            "failed": failed_count,
            "total": len(names),
            "results": results
        }

    @staticmethod
    def _member_email(member: Dict[str, Any]) -> str:
        return (
            member.get("email")
            or member.get("user_principal_name")
            or member.get("userPrincipalName")
            or ""
        )

    async def sync_chats_to_db(
        self, user_id: str, chats: List[Dict[str, Any]], deactivate_missing: bool = True
    ) -> Dict[str, Any]:
        """
        채팅 목록을 DB에 동기화 (소유자의 행만 갱신·비활성화)

        Args:
            user_id: 사용자 ID (이메일) — 1:1 채팅에서 본인을 가려내는 데에도 쓴다
            chats: Graph API에서 조회한 채팅 목록
            deactivate_missing: True 면 chats 에 없는 기존 채팅을 비활성화한다.
                chats 가 전체 목록일 때만 True 로 — 부분(첫 페이지) 목록으로 비활성화하면
                멀쩡한 채팅이 "삭제됨" 으로 바뀐다.
        """
        owner = self._owner(user_id)
        me = (user_id or "").lower()
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()

            # 현재 조회된 chat_id들
            current_chat_ids = {chat.get("id") for chat in chats}

            # 기존 DB의 활성 chat_id들 조회
            cursor.execute(
                "SELECT chat_id FROM teams_chats WHERE owner_key = ? AND is_active = TRUE",
                (owner,)
            )
            existing_chat_ids = {row[0] for row in cursor.fetchall()}

            # 삭제된 채팅 비활성화
            deleted_chat_ids = (existing_chat_ids - current_chat_ids) if deactivate_missing else set()
            for chat_id in deleted_chat_ids:
                cursor.execute(
                    "UPDATE teams_chats SET is_active = FALSE, updated_at = ? WHERE owner_key = ? AND chat_id = ?",
                    (now, owner, chat_id)
                )

            # 각 채팅 정보를 DB에 UPSERT
            for chat in chats:
                chat_id = chat.get("id")
                chat_type = chat.get("chatType") or chat.get("chat_type", "unknown")
                topic = chat.get("topic", "")

                # 멤버 정보 추출
                members = chat.get("members", [])
                member_count = len(members)
                members_json = json.dumps(members, ensure_ascii=False)

                # 1:1 채팅인 경우 상대방 정보 추출
                peer_user_name = None
                peer_user_email = None
                if chat_type == "oneOnOne" and len(members) >= 2:
                    # 멤버 배열 순서는 보장되지 않는다([상대, 본인] 도 옴) — 본인을 제외한 첫 멤버가 상대방
                    peer_member = next(
                        (m for m in members if self._member_email(m).lower() != me),
                        members[1],
                    )
                    # graph_teams_client가 UserInfo를 asdict로 직렬화하므로 snake_case 키 우선
                    peer_user_name = peer_member.get("display_name") or peer_member.get("displayName", "")
                    peer_user_email = self._member_email(peer_member)

                # 한글 이름(topic_kr) 추정
                topic_kr = None
                if chat_type == "oneOnOne" and peer_user_name:
                    if self._contains_hangul(peer_user_name):
                        topic_kr = peer_user_name
                if not topic_kr and topic:
                    if self._contains_hangul(topic):
                        topic_kr = topic

                # 마지막 메시지 정보
                # graph_teams_client가 ChatInfo를 snake_case 키로 직렬화하며,
                # last_message_preview는 이미 본문 content 문자열임
                last_message_preview = chat.get("last_message_preview") or ""
                last_message_time = chat.get("last_updated_datetime") or ""

                # DB에 UPSERT — 기준은 (owner_key, chat_id)
                cursor.execute(
                    """
                    INSERT INTO teams_chats (
                        owner_key, user_id, chat_id, chat_type, topic, topic_kr,
                        member_count, members_json, peer_user_name, peer_user_email,
                        last_message_preview, last_message_time,
                        created_at, updated_at, last_sync_at, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE)
                    ON CONFLICT(owner_key, chat_id) DO UPDATE SET
                        chat_type = excluded.chat_type,
                        topic = excluded.topic,
                        topic_kr = COALESCE(teams_chats.topic_kr, excluded.topic_kr),
                        member_count = excluded.member_count,
                        members_json = excluded.members_json,
                        peer_user_name = excluded.peer_user_name,
                        peer_user_email = excluded.peer_user_email,
                        last_message_preview = excluded.last_message_preview,
                        last_message_time = excluded.last_message_time,
                        updated_at = excluded.updated_at,
                        last_sync_at = excluded.last_sync_at,
                        is_active = TRUE
                    WHERE teams_chats.owner_key = excluded.owner_key
                    """,
                    (
                        owner, user_id or "", chat_id, chat_type, topic, topic_kr,
                        member_count, members_json, peer_user_name, peer_user_email,
                        last_message_preview, last_message_time,
                        now, now, now
                    )
                )

            conn.commit()
            logger.info("DB 동기화 완료: %d개 채팅, %d개 비활성화", len(chats), len(deleted_chat_ids))

            return {
                "success": True,
                "synced": len(chats),
                "deactivated": len(deleted_chat_ids),
            }

        except Exception as e:
            logger.error("[ERROR] DB 동기화 오류: %s", _err(e))
            conn.rollback()
            return {"success": False, "error": f"DB 동기화 오류: {_err(e)}"}
        finally:
            conn.close()

    async def get_chats_with_korean_names(self, user_id: str) -> List[Dict[str, Any]]:
        """사용자의 채팅 목록 조회 (한글 이름 포함)"""
        owner = self._owner(user_id)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM teams_chats
                WHERE owner_key = ? AND is_active = TRUE
                ORDER BY last_message_time DESC
                """,
                (owner,)
            )
            return [_public(row) for row in cursor.fetchall()]

        except Exception as e:
            logger.error("[ERROR] 채팅 목록 조회 오류: %s", _err(e))
            return []
        finally:
            conn.close()

    async def get_chats_without_korean_names(self, user_id: str) -> List[Dict[str, Any]]:
        """한글 이름이 없는 채팅 목록 조회"""
        owner = self._owner(user_id)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM teams_chats
                WHERE owner_key = ? AND is_active = TRUE
                AND (topic_kr IS NULL OR topic_kr = '')
                AND (peer_user_name IS NOT NULL AND peer_user_name != '')
                ORDER BY last_message_time DESC
                """,
                (owner,)
            )
            return [_public(row) for row in cursor.fetchall()]

        except Exception as e:
            logger.error("[ERROR] 채팅 목록 조회 오류: %s", _err(e))
            return []
        finally:
            conn.close()

    async def update_last_sent_at(self, user_id: str, chat_id: str) -> None:
        """메시지 전송 시간 업데이트 (소유자의 행만)"""
        owner = self._owner(user_id)
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                "UPDATE teams_chats SET last_sent_at = ?, updated_at = ? WHERE owner_key = ? AND chat_id = ?",
                (now, now, owner, chat_id)
            )
            conn.commit()
        except Exception as e:
            logger.warning("[WARN] DB 업데이트 실패 (무시): %s", _err(e))
        finally:
            conn.close()
