"""
Todo Service - GraphTodoClient Facade

MCP 도구가 호출하는 진입점.
- user_email 기본값 처리 (auth.db에서 첫 사용자)
- list_id_or_name 해석 (wellknownListName / displayName)
"""

from typing import Dict, Any, List, Optional

from .graph_todo_client import GraphTodoClient
from .todo_types import (
    DateTimeTimeZone,
    ItemBody,
    TaskListCreateParams,
    TaskCreateParams,
    TaskUpdateParams,
)


def get_default_user_email() -> Optional[str]:
    """auth.db에서 첫 번째 사용자 이메일 조회."""
    try:
        from session.auth_database import AuthDatabase
        db = AuthDatabase()
        users = db.list_users()
        if users:
            return users[0].get("user_email") or users[0].get("email")
    except Exception:
        pass
    return None


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


class TodoService:
    """Microsoft To Do Facade for MCP tools."""

    def __init__(self):
        self._client: Optional[GraphTodoClient] = None
        self._initialized: bool = False

    async def initialize(self) -> bool:
        if self._initialized:
            return True
        self._client = GraphTodoClient()
        if await self._client.initialize():
            self._initialized = True
            return True
        return False

    def _ensure_initialized(self):
        if not self._initialized or not self._client:
            raise RuntimeError("TodoService not initialized. Call initialize() first.")

    def _resolve_user_email(self, user_email: Optional[str]) -> Optional[str]:
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
        if resolved.get("status") != "success":
            return resolved
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
        user_email = self._resolve_user_email(user_email)
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found"}

        resolved = await self._client.resolve_list_id(
            user_email=user_email, list_id_or_name=list_id_or_name
        )
        if resolved.get("status") != "success":
            return resolved
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
        if resolved.get("status") != "success":
            return resolved
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
        user_email = self._resolve_user_email(user_email)
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found"}
        if not title:
            return {"status": "error", "error": "title is required"}

        resolved = await self._client.resolve_list_id(
            user_email=user_email, list_id_or_name=list_id_or_name
        )
        if resolved.get("status") != "success":
            return resolved
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
        user_email = self._resolve_user_email(user_email)
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found"}
        if not task_id:
            return {"status": "error", "error": "task_id is required"}

        resolved = await self._client.resolve_list_id(
            user_email=user_email, list_id_or_name=list_id_or_name
        )
        if resolved.get("status") != "success":
            return resolved
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
        if resolved.get("status") != "success":
            return resolved
        list_id = resolved["list_id"]

        result = await self._client.delete_task(
            user_email=user_email, list_id=list_id, task_id=task_id
        )
        if result.get("status") == "success":
            result["user"] = user_email
            result["list_id"] = list_id
        return result

    async def close(self):
        if self._client:
            await self._client.close()
        self._initialized = False


todo_service = TodoService()
