"""
사용자 선택 정책 (SSOT).

기존 문제:
  - 일부 서버는 YAML 스키마 default 로 특정 이메일을 박아두고 transport 가 그걸 주입 →
    DB 기반 선택을 우회하고, 공개 스키마에 개인 주소가 노출됨
  - 다른 서버는 auth.db 의 "첫 사용자"를 쓰는데 정렬이 updated_at DESC 라
    토큰이 갱신될 때마다 암묵적으로 대상이 바뀜

정책:
  1. 요청 인자로 명시된 이메일이 있으면 그것을 쓴다.
  2. 없으면 MS365_DEFAULT_USER_EMAIL 환경변수.
  3. 그래도 없으면 auth.db 에서 결정적(deterministic)으로 고른다:
     유효 토큰 보유자 우선 → 이메일 사전순. updated_at 순서에 의존하지 않는다.
  4. 사용자가 하나도 없으면 None.
"""

import logging
import os
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ENV_DEFAULT_USER = "MS365_DEFAULT_USER_EMAIL"


def _extract_email(user: Dict[str, Any]) -> Optional[str]:
    for key in ("user_email", "email", "userPrincipalName", "mail"):
        value = user.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


class UserResolver:
    """요청/세션 단위 사용자 결정. 프로세스당 하나를 공유해서 쓴다."""

    def __init__(self, auth_database: Any = None, *, cache: bool = True):
        self._db = auth_database
        self._cache_enabled = cache
        self._cached_default: Optional[str] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def _get_db(self) -> Any:
        if self._db is None:
            from session.auth_database import AuthDatabase

            self._db = AuthDatabase()
        return self._db

    def _list_users(self) -> List[Dict[str, Any]]:
        try:
            users = self._get_db().list_users() or []
        except Exception as exc:  # DB 부재/손상 시에도 서버는 떠 있어야 한다
            logger.warning("auth.db user lookup failed: %s", exc)
            return []
        return [u for u in users if isinstance(u, dict)]

    # ------------------------------------------------------------------
    def default_email(self, *, refresh: bool = False) -> Optional[str]:
        """인자 없이 호출됐을 때 쓸 기본 사용자."""
        env_default = os.environ.get(ENV_DEFAULT_USER)
        if env_default and env_default.strip():
            return env_default.strip()

        with self._lock:
            # 캐시하지 않는다. auth.db 조회는 로컬 sqlite 한 번이라 저렴한 반면,
            # 캐시하면 계정 추가/삭제/재인증 후 프로세스를 재시작할 때까지
            # 사라진 계정을 계속 돌려주게 된다(stale).
            candidates = []
            for user in self._list_users():
                email = _extract_email(user)
                if not email:
                    continue
                candidates.append((email.lower(), email))

            if not candidates:
                return None

            # 정렬 키는 이메일 사전순 **하나뿐**이다.
            # has_valid_token 을 1순위로 두면 access token 만료(보통 1시간)만으로
            # 대상 계정이 뒤집혀, 같은 무인자 호출이 다른 사서함을 읽게 된다.
            candidates.sort()
            chosen = candidates[0][1]
            if len(candidates) > 1:
                logger.info(
                    "No user_email supplied; deterministically selected %s out of %d accounts. "
                    "Set MS365_DEFAULT_USER_EMAIL or pass user_email explicitly to pin it.",
                    chosen,
                    len(candidates),
                )
            return chosen

    def resolve(self, explicit: Optional[str] = None, *, required: bool = False) -> Optional[str]:
        """명시값 우선, 없으면 기본 사용자."""
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()

        resolved = self.default_email()
        if resolved is None and required:
            from mcp_common.errors import ToolExecutionError

            raise ToolExecutionError(
                {
                    "status": "error",
                    "error": "no_authenticated_user",
                    "message": (
                        "user_email 이 지정되지 않았고 auth.db 에 인증된 사용자도 없습니다. "
                        "인자로 user_email 을 넘기거나 인증을 먼저 완료하세요."
                    ),
                }
            )
        return resolved

    def invalidate(self) -> None:
        with self._lock:
            self._cached_default = None


_default_resolver: Optional[UserResolver] = None
_resolver_lock = threading.Lock()


def get_default_resolver() -> UserResolver:
    global _default_resolver
    with _resolver_lock:
        if _default_resolver is None:
            _default_resolver = UserResolver()
        return _default_resolver


def resolve_user_email(explicit: Optional[str] = None, *, required: bool = False) -> Optional[str]:
    """모듈 레벨 단축 함수 — 서버 핸들러에서 바로 쓰기 위한 진입점."""
    return get_default_resolver().resolve(explicit, required=required)
