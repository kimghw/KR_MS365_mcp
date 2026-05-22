"""
Graph Todo Client - To Do API 통합 클라이언트

GraphTodoQuery 위에 얇은 facade 레이어를 둬서 service에서 일관된 인터페이스로 사용.
"""

from typing import Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.protocols import TokenProviderProtocol

from .graph_todo_query import GraphTodoQuery
from .todo_types import (
    TaskListCreateParams,
    TaskCreateParams,
    TaskUpdateParams,
)


class GraphTodoClient:
    """Graph API To Do 통합 클라이언트."""

    def __init__(self, token_provider: Optional["TokenProviderProtocol"] = None):
        self.token_provider = token_provider
        self.todo_query: Optional[GraphTodoQuery] = None
        self._initialized: bool = False

    async def initialize(self) -> bool:
        if self._initialized:
            return True

        self.todo_query = GraphTodoQuery(token_provider=self.token_provider)
        if not await self.todo_query.initialize():
            print("Failed to initialize GraphTodoQuery")
            return False
        self._initialized = True
        return True

    def _ensure_initialized(self):
        if not self._initialized:
            raise RuntimeError("GraphTodoClient not initialized. Call initialize() first.")

    # ===== list 단위 =====

    async def list_task_lists(self, user_email: str, top: int = 50) -> Dict[str, Any]:
        self._ensure_initialized()
        return await self.todo_query.list_task_lists(user_email=user_email, top=top)

    async def create_task_list(
        self, user_email: str, params: TaskListCreateParams
    ) -> Dict[str, Any]:
        self._ensure_initialized()
        return await self.todo_query.create_task_list(user_email=user_email, params=params)

    async def delete_task_list(self, user_email: str, list_id: str) -> Dict[str, Any]:
        self._ensure_initialized()
        return await self.todo_query.delete_task_list(user_email=user_email, list_id=list_id)

    async def resolve_list_id(
        self, user_email: str, list_id_or_name: Optional[str]
    ) -> Dict[str, Any]:
        self._ensure_initialized()
        return await self.todo_query.resolve_list_id(
            user_email=user_email, list_id_or_name=list_id_or_name
        )

    # ===== task 단위 =====

    async def list_tasks(
        self,
        user_email: str,
        list_id: str,
        filter_query: Optional[str] = None,
        order_by: Optional[str] = "createdDateTime desc",
        top: int = 50,
    ) -> Dict[str, Any]:
        self._ensure_initialized()
        return await self.todo_query.list_tasks(
            user_email=user_email,
            list_id=list_id,
            filter_query=filter_query,
            order_by=order_by,
            top=top,
        )

    async def get_task(
        self, user_email: str, list_id: str, task_id: str
    ) -> Dict[str, Any]:
        self._ensure_initialized()
        return await self.todo_query.get_task(
            user_email=user_email, list_id=list_id, task_id=task_id
        )

    async def create_task(
        self, user_email: str, list_id: str, params: TaskCreateParams
    ) -> Dict[str, Any]:
        self._ensure_initialized()
        return await self.todo_query.create_task(
            user_email=user_email, list_id=list_id, params=params
        )

    async def update_task(
        self,
        user_email: str,
        list_id: str,
        task_id: str,
        params: TaskUpdateParams,
    ) -> Dict[str, Any]:
        self._ensure_initialized()
        return await self.todo_query.update_task(
            user_email=user_email, list_id=list_id, task_id=task_id, params=params
        )

    async def delete_task(
        self, user_email: str, list_id: str, task_id: str
    ) -> Dict[str, Any]:
        self._ensure_initialized()
        return await self.todo_query.delete_task(
            user_email=user_email, list_id=list_id, task_id=task_id
        )

    async def close(self):
        if self.todo_query:
            await self.todo_query.close()
        self._initialized = False
