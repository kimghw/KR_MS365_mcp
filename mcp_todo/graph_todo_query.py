"""
Graph To Do Query - Microsoft To Do API 호출 레이어

역할:
    - 토큰 획득 (TokenProviderProtocol 활용)
    - URL 빌드 및 HTTP 호출 (GET/POST/PATCH/DELETE)
    - todoTaskList / todoTask CRUD

Endpoint 베이스: https://graph.microsoft.com/v1.0/users/{user_email}/todo (mode 0)
              https://graph.microsoft.com/v1.0/me/todo (mode 1 — 토큰 주인 고정)

멀티유저(spec/spec_멀티유저.md ②-7.6):
    - 토큰 공급자는 사용자 고정 객체를 주입받는다. 쿼리는 공급자를 소유하지 않으므로
      `close()` 에서 닫지 않는다(mode 0 의 공용 AuthManager 도 마찬가지).
    - URL builder 는 이메일에 따라 바뀌는 공유 상태를 두지 않는다.
    - 로그에는 이메일·오류 본문을 남기지 않는다.

호출자 ID·오류 노출(spec/spec_멀티유저.md ②-7.5 G01, ②-9) — 두 모드 공통:
    - `list_id`·`task_id` 는 `mcp_common.graph_paths.graph_segment()` 로 경로 성분 **하나**로
      인코딩한다(`..`·`%2E%2E` 같은 dot-segment 는 `SecurityError(not_found)` 로 거부).
    - 실패 응답에는 고정 메시지 + `graph_error_summary()`(상태 코드·검증된 `error.code`)만
      싣는다. Graph 오류 본문 원문·예외 문자열은 돌려주지 않는다.

redirect·nextLink (②-7.5, R08) — 두 모드 공통:
    - bearer 를 단 요청은 redirect 를 따라가지 않는다(`BEARER_KW`). 3xx 는 오류 요약으로 돌려준다.
    - `@odata.nextLink` 이어 조회는 `fetch_next_link()` 로만 한다 — 본인 `/v1.0/me/todo/...` 또는
      본인 `/users/{id}/todo/...`, dot-segment 없음. 그 밖은 `path_not_allowed`.
"""

import json
import logging

import aiohttp
from typing import Dict, Any, List, Optional, TYPE_CHECKING, Union
from urllib.parse import quote

from mcp_common.graph_paths import graph_error_summary, graph_segment
from mcp_common.security_contracts import SecurityError
from mcp_common.security_policy import multi_user_enabled

from mcp_common.graph_url_policy import BEARER_KW, check_next_link, is_redirect

if TYPE_CHECKING:
    from core.protocols import TokenProviderProtocol

from .todo_types import (
    TaskListCreateParams,
    TaskCreateParams,
    TaskUpdateParams,
)

logger = logging.getLogger(__name__)

#: 전송 단계 예외(연결 실패·타임아웃 등)의 공개 메시지 — 예외 원문은 응답에 싣지 않는다
_TRANSPORT_ERROR_MESSAGE = "Graph 요청 중 오류가 발생했습니다."
_REDIRECT_REFUSED_MESSAGE = "Graph redirect 응답은 따라가지 않습니다."

#: `fetch_next_link()` 가 이어서 조회해도 되는 리소스(소문자) — To Do 범위 밖은 거부
_NEXT_LINK_RESOURCES = frozenset({"todo"})


def _graph_failure(status: int, body_text: str, request_url: str) -> Dict[str, Any]:
    """Graph 비정상 응답 → 공개용 최소 정보(상태 코드·`error.code`). 본문 원문은 싣지 않는다."""
    try:
        parsed = json.loads(body_text) if body_text else None
    except ValueError:
        parsed = None
    summary = graph_error_summary(status, parsed)
    logger.warning(
        "Graph 요청 실패: status=%s code=%s", status, summary.get("graph_error_code", "-")
    )
    return {
        "status": "error",
        "error": _REDIRECT_REFUSED_MESSAGE if is_redirect(status) else f"Request failed with status {status}",
        **summary,
        "request_url": request_url,
    }


def _transport_failure(exc: BaseException, request_url: str) -> Dict[str, Any]:
    """전송 예외 → 고정 메시지. 예외 타입만 로그에 남긴다."""
    logger.warning("Graph 요청 오류: %s", type(exc).__name__)
    return {"status": "error", "error": _TRANSPORT_ERROR_MESSAGE, "request_url": request_url}


def _user_segment(user_email: str) -> str:
    """mode 0 의 `/users/{email}` 성분. 단일 성분 검증 후 `@` 만 그대로 둔다."""
    graph_segment(user_email)  # 빈 값·`.`·`..`·제어문자 거부
    return quote(str(user_email), safe="@")


class GraphTodoUrlBuilder:
    """Graph API To Do URL 빌더."""

    BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(self, user_email: str = "me"):
        self.user_email = user_email

    @property
    def _root(self) -> str:
        # "me" 는 Graph 정식 별칭 `/me` 로 쓴다(`/users/me` 가 아니다)
        if self.user_email == "me":
            return f"{self.BASE_URL}/me/todo"
        return f"{self.BASE_URL}/users/{_user_segment(self.user_email)}/todo"

    @property
    def lists_url(self) -> str:
        return f"{self._root}/lists"

    def list_url(self, list_id: str) -> str:
        return f"{self.lists_url}/{graph_segment(list_id)}"

    def tasks_url(self, list_id: str) -> str:
        return f"{self.list_url(list_id)}/tasks"

    def task_url(self, list_id: str, task_id: str) -> str:
        return f"{self.tasks_url(list_id)}/{graph_segment(task_id)}"

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
        """
        Args:
            token_provider: 토큰 제공자. 멀티유저에서는 사용자 고정 공급자가 **필수**다.
                None 이면 mode 0 의 프로세스 공유 AuthManager 를 쓴다.
        """
        multi_user = multi_user_enabled()
        if token_provider is None:
            if multi_user:
                raise RuntimeError(
                    "GraphTodoQuery: 멀티유저 모드에서는 사용자 고정 token_provider 가 필요합니다"
                )
            # AuthManager 를 새로 만들면 per-email refresh lock 이 인스턴스별로 갈려
            # 무의미해진다. 프로세스 단일 인스턴스를 공유한다.
            from mcp_common.auth import get_shared_auth_manager
            token_provider = get_shared_auth_manager()
        self.token_provider = token_provider
        # mode 1: 토큰 주인(`/me`)에 고정된 불변 builder. mode 0: 호출마다 새로 만든다.
        self._fixed_url_builder: Optional[GraphTodoUrlBuilder] = (
            GraphTodoUrlBuilder("me") if multi_user else None
        )

    async def initialize(self) -> bool:
        return True

    async def _get_access_token(self, user_email: str) -> Optional[str]:
        try:
            return await self.token_provider.validate_and_refresh_token(user_email)
        except SecurityError:
            # 연결 없음·재인증 필요·계정 불일치는 고정 코드로 그대로 올린다.
            raise
        except Exception as e:
            logger.warning("Graph access token 조회 오류: %s", type(e).__name__)
            return None

    def _get_url_builder(self, user_email: str) -> GraphTodoUrlBuilder:
        """요청 간에 공유되는 가변 상태 없는 URL builder (mode 1 고정 `/me`, mode 0 매번 새로)."""
        if self._fixed_url_builder is not None:
            return self._fixed_url_builder
        return GraphTodoUrlBuilder(user_email)

    def _http_session(self) -> aiohttp.ClientSession:
        """요청마다 만드는 HTTP 세션(이 객체 소유, `async with` 로 닫힌다). 테스트 대체 지점."""
        return aiohttp.ClientSession()

    # ============================================================
    # HTTP helpers
    # ============================================================

    async def _fetch(self, access_token: str, url: str) -> Dict[str, Any]:
        try:
            async with self._http_session() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                }
                async with session.get(url, headers=headers, **BEARER_KW) as response:
                    if response.status == 200:
                        return {
                            "status": "success",
                            "data": await response.json(),
                            "request_url": url,
                        }
                    return _graph_failure(response.status, await response.text(), url)
        except Exception as e:
            return _transport_failure(e, url)

    async def _post(self, access_token: str, url: str, body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            async with self._http_session() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                }
                async with session.post(url, headers=headers, json=body, **BEARER_KW) as response:
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
                    return _graph_failure(response.status, response_text, url)
        except Exception as e:
            return _transport_failure(e, url)

    async def _patch(self, access_token: str, url: str, body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            async with self._http_session() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                }
                async with session.patch(url, headers=headers, json=body, **BEARER_KW) as response:
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
                    return _graph_failure(response.status, response_text, url)
        except Exception as e:
            return _transport_failure(e, url)

    async def _delete(self, access_token: str, url: str) -> Dict[str, Any]:
        try:
            async with self._http_session() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                }
                async with session.delete(url, headers=headers, **BEARER_KW) as response:
                    if response.status in (200, 204):
                        return {
                            "status": "success",
                            "message": "Deleted",
                            "request_url": url,
                        }
                    return _graph_failure(response.status, await response.text(), url)
        except Exception as e:
            return _transport_failure(e, url)

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

        # 리스트 이름 불일치는 LLM 이 가장 흔히 틀리는 입력이다. 하드 실패로 올리지
        # 않고 not_found 로 표시해, 상위 도구가 "사용 가능한 리스트 목록"과 함께
        # soft(success:True, found:False) 로 안내하도록 한다.
        return {
            "status": "not_found",
            "list_id": None,
            "requested": list_id_or_name,
            "available_lists": [
                {
                    "id": item.get("id"),
                    "displayName": item.get("displayName"),
                    "wellknownListName": item.get("wellknownListName"),
                }
                for item in items
            ],
            "message": f"Task list not found: {list_id_or_name!r}",
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
            # 갱신할 필드가 없는 것은 실패가 아니라 no-op 이다.
            return {"status": "success", "updated": False, "reason": "no_fields"}
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
    # 페이지 이어 조회 (@odata.nextLink)
    # ============================================================

    async def fetch_next_link(self, user_email: str, next_link: str) -> Dict[str, Any]:
        """Graph 가 돌려준 `@odata.nextLink` 를 **같은 사용자·To Do 범위에서만** GET 한다.

        정책(`check_next_link`)은 토큰 획득·HTTP 요청보다 먼저 판정한다. 다른 사용자
        (`/users/B/...`)·다른 리소스·dot-segment·Graph 밖 호스트는 `path_not_allowed`.
        이어 조회가 필요한 코드는 반드시 이 메서드를 쓴다 — `_fetch(next_link)` 직접 호출 금지.
        """
        url = check_next_link(next_link, user_email, resources=_NEXT_LINK_RESOURCES)
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"status": "error", "error": "Failed to get access token"}

        result = await self._fetch(access_token, url)
        if result["status"] == "success":
            data = result["data"]
            return {
                "status": "success",
                "value": data.get("value", []),
                "next_link": data.get("@odata.nextLink"),
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
        """토큰 공급자는 이 객체의 소유가 아니다 — 주입된 사용자 공급자든 mode 0 의 공용
        AuthManager 든 닫지 않는다(spec/spec_멀티유저.md ②-2.4). HTTP 세션은 요청마다
        열고 닫으므로 남는 자원이 없다.
        """
        return None
