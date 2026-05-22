"""
Graph To Do Query - Microsoft To Do API 호출 레이어

역할:
    - 토큰 획득 (TokenProviderProtocol 활용)
    - URL 빌드 및 HTTP 호출 (GET/POST/PATCH/DELETE)
    - todoTaskList / todoTask CRUD

Endpoint 베이스: https://graph.microsoft.com/v1.0/users/{user_email}/todo
"""

import aiohttp
from typing import Dict, Any, List, Optional, TYPE_CHECKING, Union
from urllib.parse import quote

if TYPE_CHECKING:
    from core.protocols import TokenProviderProtocol

from .todo_types import (
    TaskListCreateParams,
    TaskCreateParams,
    TaskUpdateParams,
)


class GraphTodoUrlBuilder:
    """Graph API To Do URL 빌더."""

    BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(self, user_email: str = "me"):
        self.user_email = user_email

    @property
    def _root(self) -> str:
        return f"{self.BASE_URL}/users/{self.user_email}/todo"

    @property
    def lists_url(self) -> str:
        return f"{self._root}/lists"

    def list_url(self, list_id: str) -> str:
        return f"{self.lists_url}/{quote(list_id, safe='')}"

    def tasks_url(self, list_id: str) -> str:
        return f"{self.list_url(list_id)}/tasks"

    def task_url(self, list_id: str, task_id: str) -> str:
        return f"{self.tasks_url(list_id)}/{quote(task_id, safe='')}"

    @staticmethod
    def with_query(
        url: str,
        filter_query: Optional[str] = None,
        select_fields: Optional[List[str]] = None,
        order_by: Optional[str] = None,
        top: Optional[int] = None,
        skip: Optional[int] = None,
    ) -> str:
        params: List[str] = []
        if filter_query:
            params.append(f"$filter={filter_query}")
        if select_fields:
            params.append(f"$select={','.join(select_fields)}")
        if order_by:
            params.append(f"$orderby={order_by}")
        if top is not None:
            params.append(f"$top={top}")
        if skip is not None:
            params.append(f"$skip={skip}")
        if params:
            url += "?" + "&".join(params)
        return url


class GraphTodoQuery:
    """Microsoft To Do Graph API 호출."""

    def __init__(self, token_provider: Optional["TokenProviderProtocol"] = None):
        if token_provider is None:
            from session.auth_manager import AuthManager
            token_provider = AuthManager()
        self.token_provider = token_provider
        self._url_builder: Optional[GraphTodoUrlBuilder] = None

    async def initialize(self) -> bool:
        return True

    async def _get_access_token(self, user_email: str) -> Optional[str]:
        try:
            return await self.token_provider.validate_and_refresh_token(user_email)
        except Exception as e:
            print(f"Token retrieval error for {user_email}: {e}")
            return None

    def _get_url_builder(self, user_email: str) -> GraphTodoUrlBuilder:
        if self._url_builder is None or self._url_builder.user_email != user_email:
            self._url_builder = GraphTodoUrlBuilder(user_email)
        return self._url_builder

    # ============================================================
    # HTTP helpers
    # ============================================================

    async def _fetch(self, access_token: str, url: str) -> Dict[str, Any]:
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                }
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        return {
                            "status": "success",
                            "data": await response.json(),
                            "request_url": url,
                        }
                    return {
                        "status": "error",
                        "error": f"Request failed with status {response.status}",
                        "error_detail": (await response.text())[:500],
                        "request_url": url,
                    }
        except Exception as e:
            return {"status": "error", "error": str(e), "request_url": url}

    async def _post(self, access_token: str, url: str, body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                }
                async with session.post(url, headers=headers, json=body) as response:
                    response_text = await response.text()
                    if response.status in (200, 201, 202):
                        try:
                            data = await response.json() if response_text else {}
                        except Exception:
                            data = {}
                        return {
                            "status": "success",
                            "data": data,
                            "request_url": url,
                        }
                    return {
                        "status": "error",
                        "error": f"Request failed with status {response.status}",
                        "error_detail": response_text[:500],
                        "request_url": url,
                    }
        except Exception as e:
            return {"status": "error", "error": str(e), "request_url": url}

    async def _patch(self, access_token: str, url: str, body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                }
                async with session.patch(url, headers=headers, json=body) as response:
                    response_text = await response.text()
                    if response.status in (200, 204):
                        try:
                            data = await response.json() if response_text else {}
                        except Exception:
                            data = {}
                        return {
                            "status": "success",
                            "data": data,
                            "request_url": url,
                        }
                    return {
                        "status": "error",
                        "error": f"Request failed with status {response.status}",
                        "error_detail": response_text[:500],
                        "request_url": url,
                    }
        except Exception as e:
            return {"status": "error", "error": str(e), "request_url": url}

    async def _delete(self, access_token: str, url: str) -> Dict[str, Any]:
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                }
                async with session.delete(url, headers=headers) as response:
                    if response.status in (200, 204):
                        return {
                            "status": "success",
                            "message": "Deleted",
                            "request_url": url,
                        }
                    return {
                        "status": "error",
                        "error": f"Request failed with status {response.status}",
                        "error_detail": (await response.text())[:500],
                        "request_url": url,
                    }
        except Exception as e:
            return {"status": "error", "error": str(e), "request_url": url}

    # ============================================================
    # Helper: 기본 리스트 ID 조회 (wellknownListName == "defaultList")
    # ============================================================

    async def resolve_list_id(
        self, user_email: str, list_id_or_name: Optional[str]
    ) -> Dict[str, Any]:
        """list_id 또는 displayName/wellknownListName으로 list_id 해석.

        list_id_or_name이 None이거나 빈 문자열이면 wellknownListName == 'defaultList' 사용.
        """
        if list_id_or_name and len(list_id_or_name) > 40 and "=" in list_id_or_name:
            # 이미 list_id 형태 (Graph 식별자는 길고 base64-ish + '=' 포함)
            return {"status": "success", "list_id": list_id_or_name}

        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"status": "error", "error": f"Failed to get access token for {user_email}"}

        url = self._get_url_builder(user_email).lists_url
        result = await self._fetch(access_token, url)
        if result["status"] != "success":
            return result

        items = result["data"].get("value", [])
        target = list_id_or_name or ""

        # 우선순위 1: wellknownListName 일치
        for item in items:
            if target and item.get("wellknownListName") == target:
                return {"status": "success", "list_id": item["id"]}

        # 우선순위 2: displayName 일치
        for item in items:
            if target and item.get("displayName") == target:
                return {"status": "success", "list_id": item["id"]}

        # 우선순위 3: target이 비어있으면 defaultList
        if not target:
            for item in items:
                if item.get("wellknownListName") == "defaultList":
                    return {"status": "success", "list_id": item["id"]}

        return {
            "status": "error",
            "error": f"Task list not found: {list_id_or_name!r}",
        }

    # ============================================================
    # todoTaskList CRUD
    # ============================================================

    async def list_task_lists(self, user_email: str, top: int = 50) -> Dict[str, Any]:
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"status": "error", "error": f"Failed to get access token for {user_email}"}

        url = GraphTodoUrlBuilder.with_query(
            self._get_url_builder(user_email).lists_url, top=top
        )
        result = await self._fetch(access_token, url)
        if result["status"] == "success":
            values = result["data"].get("value", [])
            return {
                "status": "success",
                "value": values,
                "total": len(values),
                "request_url": url,
            }
        return result

    async def create_task_list(
        self, user_email: str, params: TaskListCreateParams
    ) -> Dict[str, Any]:
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"status": "error", "error": f"Failed to get access token for {user_email}"}

        url = self._get_url_builder(user_email).lists_url
        body = {"displayName": params.displayName}
        result = await self._post(access_token, url, body)
        if result["status"] == "success":
            return {
                "status": "success",
                "list": result["data"],
                "message": "Task list created",
                "request_url": url,
            }
        return result

    async def delete_task_list(self, user_email: str, list_id: str) -> Dict[str, Any]:
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"status": "error", "error": f"Failed to get access token for {user_email}"}

        url = self._get_url_builder(user_email).list_url(list_id)
        result = await self._delete(access_token, url)
        if result["status"] == "success":
            return {
                "status": "success",
                "list_id": list_id,
                "message": "Task list deleted",
                "request_url": url,
            }
        return result

    # ============================================================
    # todoTask CRUD
    # ============================================================

    async def list_tasks(
        self,
        user_email: str,
        list_id: str,
        filter_query: Optional[str] = None,
        order_by: Optional[str] = "createdDateTime desc",
        top: int = 50,
    ) -> Dict[str, Any]:
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"status": "error", "error": f"Failed to get access token for {user_email}"}

        url = GraphTodoUrlBuilder.with_query(
            self._get_url_builder(user_email).tasks_url(list_id),
            filter_query=filter_query,
            order_by=order_by,
            top=top,
        )
        result = await self._fetch(access_token, url)
        if result["status"] == "success":
            tasks = result["data"].get("value", [])
            return {
                "status": "success",
                "value": tasks,
                "total": len(tasks),
                "request_url": url,
            }
        return result

    async def get_task(
        self, user_email: str, list_id: str, task_id: str
    ) -> Dict[str, Any]:
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"status": "error", "error": f"Failed to get access token for {user_email}"}

        url = self._get_url_builder(user_email).task_url(list_id, task_id)
        result = await self._fetch(access_token, url)
        if result["status"] == "success":
            return {
                "status": "success",
                "task": result["data"],
                "request_url": url,
            }
        return result

    async def create_task(
        self, user_email: str, list_id: str, params: TaskCreateParams
    ) -> Dict[str, Any]:
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"status": "error", "error": f"Failed to get access token for {user_email}"}

        url = self._get_url_builder(user_email).tasks_url(list_id)
        body = self._build_create_body(params)
        result = await self._post(access_token, url, body)
        if result["status"] == "success":
            return {
                "status": "success",
                "task": result["data"],
                "message": "Task created",
                "request_url": url,
            }
        return result

    async def update_task(
        self,
        user_email: str,
        list_id: str,
        task_id: str,
        params: TaskUpdateParams,
    ) -> Dict[str, Any]:
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"status": "error", "error": f"Failed to get access token for {user_email}"}

        url = self._get_url_builder(user_email).task_url(list_id, task_id)
        body = self._build_update_body(params)
        if not body:
            return {"status": "error", "error": "No fields to update"}
        result = await self._patch(access_token, url, body)
        if result["status"] == "success":
            return {
                "status": "success",
                "task": result["data"],
                "message": "Task updated",
                "request_url": url,
            }
        return result

    async def delete_task(
        self, user_email: str, list_id: str, task_id: str
    ) -> Dict[str, Any]:
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"status": "error", "error": f"Failed to get access token for {user_email}"}

        url = self._get_url_builder(user_email).task_url(list_id, task_id)
        result = await self._delete(access_token, url)
        if result["status"] == "success":
            return {
                "status": "success",
                "task_id": task_id,
                "message": "Task deleted",
                "request_url": url,
            }
        return result

    # ============================================================
    # Body builders
    # ============================================================

    @staticmethod
    def _build_create_body(params: TaskCreateParams) -> Dict[str, Any]:
        body: Dict[str, Any] = {"title": params.title}
        if params.body is not None:
            body["body"] = {
                "content": params.body.content,
                "contentType": params.body.contentType,
            }
        if params.importance is not None:
            body["importance"] = params.importance
        if params.status is not None:
            body["status"] = params.status
        if params.dueDateTime is not None:
            body["dueDateTime"] = {
                "dateTime": params.dueDateTime.dateTime,
                "timeZone": params.dueDateTime.timeZone,
            }
        if params.reminderDateTime is not None:
            body["reminderDateTime"] = {
                "dateTime": params.reminderDateTime.dateTime,
                "timeZone": params.reminderDateTime.timeZone,
            }
        if params.isReminderOn is not None:
            body["isReminderOn"] = params.isReminderOn
        if params.categories is not None:
            body["categories"] = params.categories
        return body

    @staticmethod
    def _build_update_body(params: TaskUpdateParams) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if params.title is not None:
            body["title"] = params.title
        if params.body is not None:
            body["body"] = {
                "content": params.body.content,
                "contentType": params.body.contentType,
            }
        if params.importance is not None:
            body["importance"] = params.importance
        if params.status is not None:
            body["status"] = params.status
        if params.dueDateTime is not None:
            body["dueDateTime"] = {
                "dateTime": params.dueDateTime.dateTime,
                "timeZone": params.dueDateTime.timeZone,
            }
        if params.reminderDateTime is not None:
            body["reminderDateTime"] = {
                "dateTime": params.reminderDateTime.dateTime,
                "timeZone": params.reminderDateTime.timeZone,
            }
        if params.isReminderOn is not None:
            body["isReminderOn"] = params.isReminderOn
        if params.categories is not None:
            body["categories"] = params.categories
        return body

    async def close(self):
        if self.token_provider and hasattr(self.token_provider, "close"):
            await self.token_provider.close()
