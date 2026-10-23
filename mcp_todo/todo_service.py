"""
Todo Service - GraphTodoClient Facade

MCP 도구가 호출하는 진입점.
- user_email 기본값 처리 (mode 0: mcp_common 의 결정적 사용자 선택 정책,
  mode 1: 요청 principal 의 연결 계정만 — spec/spec_멀티유저.md ②-5.3)
- list_id_or_name 해석 (wellknownListName / displayName)

멀티유저에서는 서비스 풀이 사용자별로 만들고, 생성 시 받은 사용자 고정 `token_provider`
를 GraphClient 로 넘긴다. 공용 AuthManager 를 끌어오지 않는다.
"""

import importlib
from typing import Dict, Any, List, Optional

from mcp_common.principal import MISSING, assert_user_email, require_principal
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.security_policy import multi_user_enabled

from .graph_todo_client import GraphTodoClient
from mcp_common.input_bounds import check_list_size, check_top
from .todo_types import (
    DateTimeTimeZone,
    ItemBody,
    TaskListCreateParams,
    TaskCreateParams,
    TaskUpdateParams,
)
from mcp_common.user_resolver import resolve_user_email


#: 서비스 경계 상한 (R02) — = todo.yaml categories maxItems. `top` 은 input_bounds.MAX_TOP.
MAX_CATEGORIES = 50


def get_default_user_email() -> Optional[str]:
    """기본 사용자 이메일 조회 (mcp_common 정책에 위임). **mode 0 전용.**"""
    return resolve_user_email()


def _to_datetime_timezone(
    value: Optional[Any], default_tz: str = "Korea Standard Time"
) -> Optional[DateTimeTimeZone]:
    """문자열 or dict → DateTimeTimeZone."""
    if value is None:
        return None
    if isinstance(value, DateTimeTimeZone):
        return value
    if isinstance(value, dict):
        return DateTimeTimeZone(
            dateTime=value.get("dateTime") or value.get("date_time", ""),
            timeZone=value.get("timeZone") or value.get("time_zone", default_tz),
        )
    # ISO 8601 string
    return DateTimeTimeZone(dateTime=str(value), timeZone=default_tz)


def _to_item_body(
    value: Optional[Any], default_content_type: str = "text"
) -> Optional[ItemBody]:
    """문자열 or dict → ItemBody."""
    if value is None:
        return None
    if isinstance(value, ItemBody):
        return value
    if isinstance(value, dict):
        return ItemBody(
            content=value.get("content", ""),
            contentType=value.get("contentType")
            or value.get("content_type")
            or default_content_type,
        )
    return ItemBody(content=str(value), contentType=default_content_type)


def _list_not_found_soft(
    resolved: Dict[str, Any], user_email: str
) -> Optional[Dict[str, Any]]:
    """resolve_list_id 결과를 상위 도구 응답으로 변환.

    - status == "success": None 반환 (호출측이 계속 진행)
    - status == "not_found": soft(success:True, found:False) + 사용 가능한 리스트 안내
    - 그 외(토큰 실패 등 진짜 오류): 원본을 그대로 반환해 하드 실패로 유지
    """
    status = resolved.get("status")
    if status == "success":
        return None
    if status == "not_found":
        return {
            "success": True,
            "found": False,
            "requested": resolved.get("requested"),
            "available_lists": resolved.get("available_lists", []),
            "message": resolved.get("message"),
            "user": user_email,
        }
    return resolved


class TodoService:
    """Microsoft To Do Facade for MCP tools."""

    def __init__(self, token_provider: Optional[Any] = None, paths: Optional[Any] = None):
        """
        Args:
            token_provider: 사용자 고정 토큰 공급자(멀티유저 factory 가 주입). None 이면
                mode 0 의 공용 AuthManager 를 쓴다 — mode 1 에서는 GraphClient 생성이 실패한다.
            paths: 사용자 저장 경로. Todo 는 개인 DB·파일을 쓰지 않는다.
        """
        self._token_provider = token_provider
        self._paths = paths
        # 이 서비스가 묶인 사용자. 요청 principal 과 다르면 거부한다(방어 심층).
        self._owner_key: Optional[str] = getattr(token_provider, "user_key", None)
        self._client: Optional[GraphTodoClient] = None
        self._initialized: bool = False

    async def initialize(self) -> bool:
        if self._initialized:
            return True
        self._client = GraphTodoClient(token_provider=self._token_provider)
        if await self._client.initialize():
            self._initialized = True
            return True
        return False

    def _ensure_initialized(self):
        if not self._initialized or not self._client:
            raise RuntimeError("TodoService not initialized. Call initialize() first.")

    def _resolve_user_email(self, user_email: Optional[str]) -> Optional[str]:
        """호출 대상 계정.

        - mode 1: 요청 principal 의 연결 계정만 (생략 → 본인, 다른 값 → `identity_mismatch`).
          다른 사용자에게 묶인 서비스로 들어온 요청도 거부한다.
        - mode 0: 명시값 → `get_default_user_email()`.
        """
        if multi_user_enabled():
            email = assert_user_email(MISSING if user_email is None else user_email)
            if self._owner_key is not None and require_principal().user_key != self._owner_key:
                raise SecurityError(ErrorCode.IDENTITY_MISMATCH)
            return email
        if user_email:
            return user_email
        return get_default_user_email()

    # ============================================================
    # Task lists
    # ============================================================

    async def todo_lists_view(
        self, user_email: Optional[str] = None, top: int = 50
    ) -> Dict[str, Any]:
        """모든 task list 조회."""
        self._ensure_initialized()
        top = check_top(top)
        user_email = self._resolve_user_email(user_email)
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found"}
        result = await self._client.list_task_lists(user_email=user_email, top=top)
        if result.get("status") == "success":
            result["user"] = user_email
            result["lists"] = result.pop("value", [])
        return result

    async def todo_list_create(
        self, user_email: Optional[str] = None, display_name: str = ""
    ) -> Dict[str, Any]:
        """새 task list 생성."""
        self._ensure_initialized()
        user_email = self._resolve_user_email(user_email)
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found"}
        if not display_name:
            return {"status": "error", "error": "display_name is required"}
        params = TaskListCreateParams(displayName=display_name)
        result = await self._client.create_task_list(user_email=user_email, params=params)
        if result.get("status") == "success":
            result["user"] = user_email
        return result

    async def todo_list_delete(
        self,
        user_email: Optional[str] = None,
        list_id_or_name: str = "",
    ) -> Dict[str, Any]:
        """task list 삭제. list_id 또는 displayName/wellknownListName 허용."""
        self._ensure_initialized()
        user_email = self._resolve_user_email(user_email)
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found"}
        if not list_id_or_name:
            return {"status": "error", "error": "list_id_or_name is required"}
        resolved = await self._client.resolve_list_id(
            user_email=user_email, list_id_or_name=list_id_or_name
        )
        early = _list_not_found_soft(resolved, user_email)
        if early is not None:
            return early
        list_id = resolved["list_id"]
        result = await self._client.delete_task_list(user_email=user_email, list_id=list_id)
        if result.get("status") == "success":
            result["user"] = user_email
        return result

    # ============================================================
    # Tasks
    # ============================================================

    async def todo_tasks_view(
        self,
        user_email: Optional[str] = None,
        list_id_or_name: Optional[str] = None,
        status_filter: Optional[str] = None,
        top: int = 50,
        orderby: Optional[str] = None,
    ) -> Dict[str, Any]:
        """list 내 task 조회. list_id_or_name이 비어있으면 기본 리스트 사용."""
        self._ensure_initialized()
        top = check_top(top)
        user_email = self._resolve_user_email(user_email)
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found"}

        resolved = await self._client.resolve_list_id(
            user_email=user_email, list_id_or_name=list_id_or_name
        )
        early = _list_not_found_soft(resolved, user_email)
        if early is not None:
            return early
        list_id = resolved["list_id"]

        filter_query = None
        if status_filter:
            filter_query = f"status eq '{status_filter}'"

        result = await self._client.list_tasks(
            user_email=user_email,
            list_id=list_id,
            filter_query=filter_query,
            order_by=orderby or "createdDateTime desc",
            top=top,
        )
        if result.get("status") == "success":
            result["user"] = user_email
            result["list_id"] = list_id
            result["tasks"] = result.pop("value", [])
        return result

    async def todo_task_get(
        self,
        user_email: Optional[str] = None,
        list_id_or_name: Optional[str] = None,
        task_id: str = "",
    ) -> Dict[str, Any]:
        """단일 task 조회."""
        self._ensure_initialized()
        user_email = self._resolve_user_email(user_email)
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found"}
        if not task_id:
            return {"status": "error", "error": "task_id is required"}

        resolved = await self._client.resolve_list_id(
            user_email=user_email, list_id_or_name=list_id_or_name
        )
        early = _list_not_found_soft(resolved, user_email)
        if early is not None:
            return early
        list_id = resolved["list_id"]

        result = await self._client.get_task(
            user_email=user_email, list_id=list_id, task_id=task_id
        )
        if result.get("status") == "success":
            result["user"] = user_email
        return result

    async def todo_task_create(
        self,
        user_email: Optional[str] = None,
        list_id_or_name: Optional[str] = None,
        title: str = "",
        body: Optional[str] = None,
        importance: Optional[str] = None,
        due_datetime: Optional[str] = None,
        reminder_datetime: Optional[str] = None,
        categories: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """새 task 생성."""
        self._ensure_initialized()
        check_list_size(categories, "categories", MAX_CATEGORIES)
        user_email = self._resolve_user_email(user_email)
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found"}
        if not title:
            return {"status": "error", "error": "title is required"}

        resolved = await self._client.resolve_list_id(
            user_email=user_email, list_id_or_name=list_id_or_name
        )
        early = _list_not_found_soft(resolved, user_email)
        if early is not None:
            return early
        list_id = resolved["list_id"]

        params = TaskCreateParams(
            title=title,
            body=_to_item_body(body) if body else None,
            importance=importance,
            dueDateTime=_to_datetime_timezone(due_datetime),
            reminderDateTime=_to_datetime_timezone(reminder_datetime),
            isReminderOn=True if reminder_datetime else None,
            categories=categories,
        )
        result = await self._client.create_task(
            user_email=user_email, list_id=list_id, params=params
        )
        if result.get("status") == "success":
            result["user"] = user_email
            result["list_id"] = list_id
        return result

    async def todo_task_update(
        self,
        user_email: Optional[str] = None,
        list_id_or_name: Optional[str] = None,
        task_id: str = "",
        title: Optional[str] = None,
        body: Optional[str] = None,
        importance: Optional[str] = None,
        status: Optional[str] = None,
        due_datetime: Optional[str] = None,
        reminder_datetime: Optional[str] = None,
        categories: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """task 수정 (None인 필드는 무시)."""
        self._ensure_initialized()
        check_list_size(categories, "categories", MAX_CATEGORIES)
        user_email = self._resolve_user_email(user_email)
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found"}
        if not task_id:
            return {"status": "error", "error": "task_id is required"}

        resolved = await self._client.resolve_list_id(
            user_email=user_email, list_id_or_name=list_id_or_name
        )
        early = _list_not_found_soft(resolved, user_email)
        if early is not None:
            return early
        list_id = resolved["list_id"]

        params = TaskUpdateParams(
            title=title,
            body=_to_item_body(body) if body is not None else None,
            importance=importance,
            status=status,
            dueDateTime=_to_datetime_timezone(due_datetime) if due_datetime else None,
            reminderDateTime=_to_datetime_timezone(reminder_datetime)
            if reminder_datetime
            else None,
            categories=categories,
        )
        result = await self._client.update_task(
            user_email=user_email, list_id=list_id, task_id=task_id, params=params
        )
        if result.get("status") == "success":
            result["user"] = user_email
            result["list_id"] = list_id
        return result

    async def todo_task_delete(
        self,
        user_email: Optional[str] = None,
        list_id_or_name: Optional[str] = None,
        task_id: str = "",
    ) -> Dict[str, Any]:
        """task 삭제."""
        self._ensure_initialized()
        user_email = self._resolve_user_email(user_email)
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found"}
        if not task_id:
            return {"status": "error", "error": "task_id is required"}

        resolved = await self._client.resolve_list_id(
            user_email=user_email, list_id_or_name=list_id_or_name
        )
        early = _list_not_found_soft(resolved, user_email)
        if early is not None:
            return early
        list_id = resolved["list_id"]

        result = await self._client.delete_task(
            user_email=user_email, list_id=list_id, task_id=task_id
        )
        if result.get("status") == "success":
            result["user"] = user_email
            result["list_id"] = list_id
        return result

    async def close(self):
        """자신이 만든 GraphClient 만 닫는다. 토큰 공급자는 닫지 않는다."""
        if self._client:
            await self._client.close()
            self._client = None
        self._initialized = False


# ----------------------------------------------------------------------
# 호환 export — `from mcp_todo.todo_service import todo_service` (R15)
# ----------------------------------------------------------------------
# 모듈 수준 싱글톤(`todo_service = TodoService()`)은 import 시점에 만들지 않는다 — 전역 개인
# 서비스 인스턴스는 mode 0 의 handlers.py 한 곳에서만 만든다(②-2.4). 기존 Python 연동 코드를
# 위해 같은 이름을 **지연 속성**(PEP 562)으로 남긴다: mode 0 에서는 handlers 의 legacy 인스턴스
# 바로 그 객체, mode 1 에서는 `LegacyAuthDisabledError`(StartupConfigError 하위).
_LEGACY_ATTR = "todo_service"


def _legacy_singleton() -> "TodoService":
    if multi_user_enabled():
        try:
            from session.mode_guard import LegacyAuthDisabledError as _Disabled
        except ImportError:  # session 패키지가 없는 번들
            from mcp_common.security_contracts import StartupConfigError as _Disabled
        raise _Disabled(
            "todo_service 모듈 싱글톤은 단일 운영자(mode 0) 전용입니다. 멀티유저 모드에서는 "
            "서비스 풀의 사용자별 인스턴스(mcp_common.service_context.service_for)를 쓰세요."
        )
    handlers = importlib.import_module("mcp_todo.mcp_server.handlers")
    return getattr(handlers, _LEGACY_ATTR)


def __getattr__(name: str):
    if name == _LEGACY_ATTR:
        return _legacy_singleton()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | {_LEGACY_ATTR})


# `import *` 계약 — 공개 이름 전부 + mode 0 에서는 legacy 싱글톤(R15 2차). 지연 속성은
# `__all__` 에 적혀 있어야 `import *` 가 `__getattr__` 로 꺼내 간다. mode 1 은 넣지 않아
# `from mcp_todo.todo_service import *` 가 아무것도 만들지 않는다(모드는 기동 시 고정).
__all__ = [_name for _name in list(globals()) if not _name.startswith("_")]
if not multi_user_enabled():
    __all__.append(_LEGACY_ATTR)
