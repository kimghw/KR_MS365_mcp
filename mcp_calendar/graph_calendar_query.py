"""
Graph Calendar Query - Calendar API 호출 레이어
인증 처리 및 Graph API 호출을 담당

역할:
    - 인증 처리 (AuthManager 활용)
    - URL로 Graph API 호출
    - 이벤트 CRUD 작업
    - Free/Busy 조회

멀티유저(spec/spec_멀티유저.md ②-7.6):
    - 토큰 공급자는 사용자 고정 객체를 주입받는다. 쿼리는 공급자를 소유하지 않으므로
      `close()` 에서 닫지 않는다(mode 0 의 공용 AuthManager 도 마찬가지).
    - URL builder 는 이메일에 따라 바뀌는 공유 상태를 두지 않는다. mode 1 은 인스턴스
      고정 `/me` builder, mode 0 은 호출마다 새 builder(`/users/{email}`).
    - 로그에는 이메일·오류 본문을 남기지 않는다.

호출자 ID·오류 노출(spec/spec_멀티유저.md ②-7.5 G01, ②-9) — 두 모드 공통:
    - `event_id` 등 호출자가 준 ID 는 `mcp_common.graph_paths.graph_segment()` 로 경로 성분
      **하나**로 인코딩한다. `..`·`/` 로 다른 사용자 경로(`/users/B/...`)로 빠져나갈 수 없고,
      잘못된 ID 는 `SecurityError(not_found)` 로 그대로 올라간다.
    - 실패 응답에는 고정 메시지 + `graph_error_summary()`(상태 코드·검증된 `error.code`)만
      싣는다. Graph 오류 본문 원문·예외 문자열은 돌려주지 않는다.

redirect·nextLink (②-7.5, R08) — 두 모드 공통:
    - bearer 를 단 요청은 redirect 를 따라가지 않는다(`BEARER_KW`). 3xx 는 오류 요약으로 돌려준다.
    - `@odata.nextLink` 이어 조회는 `fetch_next_link()` 로만 한다 — 본인 `/v1.0/me/...` 또는
      본인 `/users/{id}/...` 의 캘린더 리소스, dot-segment 없음. 그 밖은 `path_not_allowed`.
"""

import asyncio
import aiohttp
import json
import logging
import sys
import os
from typing import Dict, Any, List, Optional, Union, TYPE_CHECKING
from datetime import datetime
import re
from urllib.parse import quote

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_common.graph_paths import graph_error_summary, graph_segment
from mcp_common.security_contracts import SecurityError
from mcp_common.security_policy import multi_user_enabled

from mcp_common.graph_url_policy import BEARER_KW, check_next_link, is_redirect

if TYPE_CHECKING:
    from core.protocols import TokenProviderProtocol
from .calendar_types import (
    EventFilterParams,
    EventSelectParams,
    EventCreateParams,
    EventUpdateParams,
    ScheduleRequest,
    build_event_filter_query,
    build_event_select_query,
)

logger = logging.getLogger(__name__)

#: 전송 단계 예외(연결 실패·타임아웃 등)의 공개 메시지 — 예외 원문은 응답에 싣지 않는다
_TRANSPORT_ERROR_MESSAGE = "Graph 요청 중 오류가 발생했습니다."
_REDIRECT_REFUSED_MESSAGE = "Graph redirect 응답은 따라가지 않습니다."

#: `fetch_next_link()` 가 이어서 조회해도 되는 리소스(소문자) — 캘린더 범위 밖(messages 등)은 거부
_NEXT_LINK_RESOURCES = frozenset({"events", "calendar", "calendars", "calendarview"})


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


# calendarView 의 startDateTime/endDateTime 은 오프셋이 없으면 Graph 가 UTC 로 해석한다
# (Prefer: outlook.timezone 헤더와 무관). 생성 쪽 기본 시간대가 "Korea Standard Time" 이므로
# 조회도 같은 기준(+09:00)을 기본으로 맞춘다.
DEFAULT_UTC_OFFSET = "+09:00"
_HAS_OFFSET = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")


def _with_offset(dt: str) -> str:
    dt = dt.strip()
    return dt if _HAS_OFFSET.search(dt) else dt + DEFAULT_UTC_OFFSET


class GraphCalendarUrlBuilder:
    """
    Graph API Calendar URL 빌더
    Calendar 관련 엔드포인트 URL 생성
    """

    BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(self, user_email: str = "me"):
        """
        Initialize URL builder

        Args:
            user_email: User email or "me" for current user (토큰 주인 — `/me/...`)
        """
        self.user_email = user_email

    @property
    def user_root(self) -> str:
        """사용자 루트. "me" 는 Graph 정식 별칭 `/me` 로 쓴다(`/users/me` 가 아니다)."""
        if self.user_email == "me":
            return f"{self.BASE_URL}/me"
        return f"{self.BASE_URL}/users/{_user_segment(self.user_email)}"

    @property
    def events_url(self) -> str:
        """이벤트 기본 URL"""
        return f"{self.user_root}/events"

    @property
    def calendar_url(self) -> str:
        """캘린더 기본 URL"""
        return f"{self.user_root}/calendar"

    @property
    def calendar_view_url(self) -> str:
        """캘린더 뷰 URL (반복 일정 인스턴스 포함)"""
        return f"{self.calendar_url}/calendarView"

    @property
    def get_schedule_url(self) -> str:
        """Free/Busy 조회 URL"""
        return f"{self.calendar_url}/getSchedule"

    def build_events_url(
        self,
        filter_query: Optional[str] = None,
        select_fields: Optional[List[str]] = None,
        order_by: Optional[str] = None,
        top: Optional[int] = None,
        skip: Optional[int] = None,
    ) -> str:
        """
        이벤트 목록 URL 생성

        Args:
            filter_query: $filter 쿼리 문자열
            select_fields: 선택할 필드 목록
            order_by: 정렬 순서
            top: 최대 결과 수
            skip: 건너뛸 결과 수

        Returns:
            완전한 URL
        """
        url = self.events_url
        params = []

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

    def build_calendar_view_url(
        self,
        start_datetime: str,
        end_datetime: str,
        select_fields: Optional[List[str]] = None,
        order_by: Optional[str] = None,
        top: Optional[int] = None,
        skip: Optional[int] = None,
    ) -> str:
        """
        CalendarView URL 생성 (반복 일정 인스턴스 포함)

        Args:
            start_datetime: 시작 날짜/시간 (ISO 8601)
            end_datetime: 종료 날짜/시간 (ISO 8601)
            select_fields: 선택할 필드 목록
            order_by: 정렬 순서
            top: 최대 결과 수
            skip: 건너뛸 결과 수

        Returns:
            완전한 URL
        """
        url = self.calendar_view_url
        # `+09:00` 의 `+` 는 쿼리에서 공백으로 읽히므로 반드시 퍼센트 인코딩
        params = [
            f"startDateTime={quote(_with_offset(start_datetime), safe='')}",
            f"endDateTime={quote(_with_offset(end_datetime), safe='')}",
        ]

        if select_fields:
            params.append(f"$select={','.join(select_fields)}")

        if order_by:
            params.append(f"$orderby={order_by}")

        if top is not None:
            params.append(f"$top={top}")

        if skip is not None:
            params.append(f"$skip={skip}")

        url += "?" + "&".join(params)
        return url

    def event_url(self, event_id: str) -> str:
        """단일 이벤트 URL. `event_id` 는 경로 성분 하나로 인코딩한다(경로 탈출 불가, G01)."""
        return f"{self.events_url}/{graph_segment(event_id)}"

    def build_event_url(
        self,
        event_id: str,
        select_fields: Optional[List[str]] = None,
    ) -> str:
        """
        단일 이벤트 URL 생성

        Args:
            event_id: 이벤트 ID
            select_fields: 선택할 필드 목록

        Returns:
            완전한 URL
        """
        url = self.event_url(event_id)
        params = []

        if select_fields:
            params.append(f"$select={','.join(select_fields)}")

        if params:
            url += "?" + "&".join(params)

        return url


class GraphCalendarQuery:
    """
    Graph API Calendar 조회 클래스

    역할:
        - 인증 처리 (TokenProviderProtocol 활용)
        - URL로 Graph API 호출
        - 이벤트 CRUD 작업
        - Free/Busy 조회
    """

    def __init__(self, token_provider: Optional["TokenProviderProtocol"] = None):
        """
        Initialize Graph Calendar Query

        Args:
            token_provider: 토큰 제공자. 멀티유저에서는 사용자 고정 공급자가 **필수**다.
                None 이면 mode 0 의 프로세스 공유 AuthManager 를 쓴다.
        """
        multi_user = multi_user_enabled()
        if token_provider is None:
            if multi_user:
                raise RuntimeError(
                    "GraphCalendarQuery: 멀티유저 모드에서는 사용자 고정 token_provider 가 필요합니다"
                )
            # 하위 호환성: 프로세스 공유 AuthManager 사용
            # (인스턴스를 새로 만들면 per-email refresh lock 이 분리돼 무의미해진다)
            from mcp_common.auth import get_shared_auth_manager
            token_provider = get_shared_auth_manager()
        self.token_provider = token_provider
        # mode 1: 토큰 주인(`/me`)에 고정된 불변 builder. mode 0: 호출마다 새로 만든다.
        self._fixed_url_builder: Optional[GraphCalendarUrlBuilder] = (
            GraphCalendarUrlBuilder("me") if multi_user else None
        )

    async def initialize(self) -> bool:
        """
        Lightweight initializer to align with callers that expect async setup

        Returns:
            True if initialized successfully
        """
        # No initialization needed - tokens are fetched per-request
        return True

    async def _get_access_token(self, user_email: str) -> Optional[str]:
        """
        Get or refresh access token for a user
        Delegates to TokenProvider which handles caching and refresh

        Args:
            user_email: User email to get token for

        Returns:
            Access token or None if failed
        """
        try:
            # TokenProvider handles all token caching and refresh logic
            access_token = await self.token_provider.validate_and_refresh_token(user_email)

            if not access_token:
                logger.warning("Graph access token 을 얻지 못했습니다")

            return access_token

        except SecurityError:
            # 연결 없음·재인증 필요·계정 불일치는 고정 코드로 그대로 올린다.
            raise
        except Exception as e:
            logger.warning("Graph access token 조회 오류: %s", type(e).__name__)
            return None

    def _get_url_builder(self, user_email: str) -> GraphCalendarUrlBuilder:
        """
        URL 빌더 반환 — 요청 간에 공유되는 가변 상태가 없다.

        mode 1 은 인스턴스 고정 `/me` builder, mode 0 은 호출마다 `user_email` builder 를
        새로 만든다(전에는 마지막 이메일로 바뀌는 캐시 하나를 공유했다).

        Args:
            user_email: 사용자 이메일 (mode 0 경로 조각)

        Returns:
            GraphCalendarUrlBuilder 인스턴스
        """
        if self._fixed_url_builder is not None:
            return self._fixed_url_builder
        return GraphCalendarUrlBuilder(user_email)

    def _http_session(self) -> aiohttp.ClientSession:
        """요청마다 만드는 HTTP 세션(이 객체 소유, `async with` 로 닫힌다). 테스트 대체 지점."""
        return aiohttp.ClientSession()

    # ============================================================
    # HTTP 헬퍼 메서드
    # ============================================================

    async def _fetch_data(self, access_token: str, url: str) -> Dict[str, Any]:
        """
        GET 요청 헬퍼

        Args:
            access_token: 액세스 토큰
            url: 요청 URL

        Returns:
            응답 데이터
        """
        try:
            async with self._http_session() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                }
                async with session.get(url, headers=headers, **BEARER_KW) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "status": "success",
                            "data": data,
                            "request_url": url,
                        }
                    else:
                        error_text = await response.text()
                        return _graph_failure(response.status, error_text, url)
        except Exception as e:
            return _transport_failure(e, url)

    async def _post_data(
        self, access_token: str, url: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        POST 요청 헬퍼

        Args:
            access_token: 액세스 토큰
            url: 요청 URL
            data: 요청 본문 데이터

        Returns:
            응답 데이터
        """
        try:
            async with self._http_session() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                }
                async with session.post(url, headers=headers, json=data, **BEARER_KW) as response:
                    response_text = await response.text()

                    if response.status in [200, 201, 202]:
                        try:
                            response_data = await response.json() if response_text else {}
                        except Exception:
                            response_data = {}

                        return {
                            "status": "success",
                            "data": response_data,
                            "request_url": url,
                        }
                    else:
                        return _graph_failure(response.status, response_text, url)
        except Exception as e:
            return _transport_failure(e, url)

    async def _patch_data(
        self, access_token: str, url: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        PATCH 요청 헬퍼

        Args:
            access_token: 액세스 토큰
            url: 요청 URL
            data: 요청 본문 데이터

        Returns:
            응답 데이터
        """
        try:
            async with self._http_session() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                }
                async with session.patch(url, headers=headers, json=data, **BEARER_KW) as response:
                    response_text = await response.text()

                    if response.status in [200, 204]:
                        try:
                            response_data = (
                                await response.json() if response_text else {}
                            )
                        except Exception:
                            response_data = {}

                        return {
                            "status": "success",
                            "data": response_data,
                            "request_url": url,
                        }
                    else:
                        return _graph_failure(response.status, response_text, url)
        except Exception as e:
            return _transport_failure(e, url)

    async def _delete_data(self, access_token: str, url: str) -> Dict[str, Any]:
        """
        DELETE 요청 헬퍼

        Args:
            access_token: 액세스 토큰
            url: 요청 URL

        Returns:
            응답 데이터
        """
        try:
            async with self._http_session() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                }
                async with session.delete(url, headers=headers, **BEARER_KW) as response:
                    if response.status == 204:
                        return {
                            "status": "success",
                            "message": "Successfully deleted",
                            "request_url": url,
                        }
                    else:
                        error_text = await response.text()
                        return _graph_failure(response.status, error_text, url)
        except Exception as e:
            return _transport_failure(e, url)

    # ============================================================
    # Calendar API 메서드
    # ============================================================

    async def list_events(
        self,
        user_email: str,
        filter_params: Optional[Union[EventFilterParams, Dict]] = None,
        select_params: Optional[Union[EventSelectParams, List[str]]] = None,
        top: int = 50,
        orderby: Optional[str] = "start/dateTime",
    ) -> Dict[str, Any]:
        """
        이벤트 목록 조회 (GET /me/events)

        Args:
            user_email: 사용자 이메일
            filter_params: 필터 파라미터
            select_params: 선택 필드 파라미터
            top: 최대 결과 수 (기본 50)
            orderby: 정렬 순서 (기본: start/dateTime)

        Returns:
            이벤트 목록 결과
        """
        # Get access token
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {
                "status": "error",
                "error": f"Failed to get access token for {user_email}",
            }

        # Build filter query
        filter_query = None
        if filter_params:
            filter_query = build_event_filter_query(filter_params)

        # Build select fields
        select_fields = None
        if select_params:
            if isinstance(select_params, EventSelectParams):
                select_fields = select_params.get_selected_fields()
            elif isinstance(select_params, list):
                select_fields = select_params
            elif isinstance(select_params, dict):
                select_query = build_event_select_query(select_params)
                select_fields = select_query.split(",") if select_query else None

        # Build URL
        url_builder = self._get_url_builder(user_email)
        url = url_builder.build_events_url(
            filter_query=filter_query,
            select_fields=select_fields,
            order_by=orderby,
            top=top,
        )

        # Fetch data
        result = await self._fetch_data(access_token, url)

        if result["status"] == "success":
            events = result["data"].get("value", [])
            return {
                "status": "success",
                "value": events,
                "total": len(events),
                "@odata.count": len(events),
                "request_url": url,
            }

        return result

    async def list_calendar_view(
        self,
        user_email: str,
        start_datetime: str,
        end_datetime: str,
        select_params: Optional[Union[EventSelectParams, List[str]]] = None,
        top: int = 50,
        orderby: Optional[str] = "start/dateTime",
    ) -> Dict[str, Any]:
        """
        CalendarView 조회 (GET /me/calendar/calendarView)
        반복 일정의 인스턴스도 포함하여 조회

        Args:
            user_email: 사용자 이메일
            start_datetime: 시작 날짜/시간 (ISO 8601, 예: 2024-01-01T00:00:00)
            end_datetime: 종료 날짜/시간 (ISO 8601, 예: 2024-01-31T23:59:59)
            select_params: 선택 필드 파라미터
            top: 최대 결과 수 (기본 50)
            orderby: 정렬 순서 (기본: start/dateTime)

        Returns:
            이벤트 목록 결과 (반복 일정 인스턴스 포함)
        """
        # Get access token
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {
                "status": "error",
                "error": f"Failed to get access token for {user_email}",
            }

        # Build select fields
        select_fields = None
        if select_params:
            if isinstance(select_params, EventSelectParams):
                select_fields = select_params.get_selected_fields()
            elif isinstance(select_params, list):
                select_fields = select_params
            elif isinstance(select_params, dict):
                select_query = build_event_select_query(select_params)
                select_fields = select_query.split(",") if select_query else None

        # Build URL
        url_builder = self._get_url_builder(user_email)
        url = url_builder.build_calendar_view_url(
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            select_fields=select_fields,
            order_by=orderby,
            top=top,
        )

        # Fetch data
        result = await self._fetch_data(access_token, url)

        if result["status"] == "success":
            events = result["data"].get("value", [])
            return {
                "status": "success",
                "value": events,
                "total": len(events),
                "@odata.count": len(events),
                "start_datetime": start_datetime,
                "end_datetime": end_datetime,
                "request_url": url,
            }

        return result

    async def get_event(
        self,
        user_email: str,
        event_id: str,
        select_params: Optional[Union[EventSelectParams, List[str]]] = None,
    ) -> Dict[str, Any]:
        """
        단일 이벤트 조회 (GET /me/events/{id})

        Args:
            user_email: 사용자 이메일
            event_id: 이벤트 ID
            select_params: 선택 필드 파라미터

        Returns:
            이벤트 정보
        """
        # Get access token
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {
                "status": "error",
                "error": f"Failed to get access token for {user_email}",
            }

        # Build select fields
        select_fields = None
        if select_params:
            if isinstance(select_params, EventSelectParams):
                select_fields = select_params.get_selected_fields()
            elif isinstance(select_params, list):
                select_fields = select_params
            elif isinstance(select_params, dict):
                select_query = build_event_select_query(select_params)
                select_fields = select_query.split(",") if select_query else None

        # Build URL
        url_builder = self._get_url_builder(user_email)
        url = url_builder.build_event_url(event_id, select_fields)

        # Fetch data
        result = await self._fetch_data(access_token, url)

        if result["status"] == "success":
            return {
                "status": "success",
                "event": result["data"],
                "request_url": url,
            }

        return result

    async def create_event(
        self,
        user_email: str,
        event_data: Union[EventCreateParams, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        이벤트 생성 (POST /me/events)

        Args:
            user_email: 사용자 이메일
            event_data: 이벤트 생성 데이터

        Returns:
            생성된 이벤트 정보
        """
        # Get access token
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {
                "status": "error",
                "error": f"Failed to get access token for {user_email}",
            }

        # Convert EventCreateParams to Graph API format
        # (변환의 유일한 진입점은 모델의 to_graph_api_body — 여기서 다시 조립하지 않는다)
        if isinstance(event_data, EventCreateParams):
            request_body = event_data.to_graph_api_body()
        else:
            request_body = event_data

        # Build URL
        url_builder = self._get_url_builder(user_email)
        url = url_builder.events_url

        # Post data
        result = await self._post_data(access_token, url, request_body)

        if result["status"] == "success":
            return {
                "status": "success",
                "event": result["data"],
                "message": "Event created successfully",
                "request_url": url,
            }

        return result

    async def update_event(
        self,
        user_email: str,
        event_id: str,
        event_data: Union[EventUpdateParams, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        이벤트 수정 (PATCH /me/events/{id})

        Args:
            user_email: 사용자 이메일
            event_id: 이벤트 ID
            event_data: 이벤트 수정 데이터

        Returns:
            수정된 이벤트 정보
        """
        # Get access token
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {
                "status": "error",
                "error": f"Failed to get access token for {user_email}",
            }

        # Convert EventUpdateParams to Graph API format
        # (변환의 유일한 진입점은 모델의 to_graph_api_body — 여기서 다시 조립하지 않는다)
        if isinstance(event_data, EventUpdateParams):
            request_body = event_data.to_graph_api_body()
        else:
            request_body = event_data

        # Build URL
        url_builder = self._get_url_builder(user_email)
        url = url_builder.event_url(event_id)

        # Patch data
        result = await self._patch_data(access_token, url, request_body)

        if result["status"] == "success":
            return {
                "status": "success",
                "event": result["data"],
                "message": "Event updated successfully",
                "request_url": url,
            }

        return result

    async def delete_event(
        self,
        user_email: str,
        event_id: str,
    ) -> Dict[str, Any]:
        """
        이벤트 삭제 (DELETE /me/events/{id})

        Args:
            user_email: 사용자 이메일
            event_id: 이벤트 ID

        Returns:
            삭제 결과
        """
        # Get access token
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {
                "status": "error",
                "error": f"Failed to get access token for {user_email}",
            }

        # Build URL
        url_builder = self._get_url_builder(user_email)
        url = url_builder.event_url(event_id)

        # Delete data
        result = await self._delete_data(access_token, url)

        if result["status"] == "success":
            return {
                "status": "success",
                "event_id": event_id,
                "message": "Event deleted successfully",
                "request_url": url,
            }

        return result

    async def get_schedule(
        self,
        user_email: str,
        schedule_request: Union[ScheduleRequest, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Free/Busy 조회 (POST /me/calendar/getSchedule)

        Args:
            user_email: 사용자 이메일 (API 호출 주체)
            schedule_request: 스케줄 조회 요청

        Returns:
            스케줄 정보 (가용성 정보)
        """
        # Get access token
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {
                "status": "error",
                "error": f"Failed to get access token for {user_email}",
            }

        # Convert ScheduleRequest to Graph API format
        if isinstance(schedule_request, ScheduleRequest):
            request_body = self._build_schedule_request_body(schedule_request)
        else:
            request_body = schedule_request

        # Build URL
        url_builder = self._get_url_builder(user_email)
        url = url_builder.get_schedule_url

        # Post data
        result = await self._post_data(access_token, url, request_body)

        if result["status"] == "success":
            schedules = result["data"].get("value", [])
            return {
                "status": "success",
                "value": schedules,
                "total": len(schedules),
                "request_url": url,
            }

        return result

    # ============================================================
    # 페이지 이어 조회 (@odata.nextLink)
    # ============================================================

    async def fetch_next_link(self, user_email: str, next_link: str) -> Dict[str, Any]:
        """Graph 가 돌려준 `@odata.nextLink` 를 **같은 사용자·캘린더 범위에서만** GET 한다.

        정책(`check_next_link`)은 토큰 획득·HTTP 요청보다 먼저 판정한다. 다른 사용자
        (`/users/B/...`)·다른 리소스·dot-segment·Graph 밖 호스트는 `path_not_allowed`.
        이어 조회가 필요한 코드는 반드시 이 메서드를 쓴다 — `_fetch_data(next_link)` 직접 호출 금지.
        """
        url = check_next_link(next_link, user_email, resources=_NEXT_LINK_RESOURCES)
        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"status": "error", "error": "Failed to get access token"}

        result = await self._fetch_data(access_token, url)
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
    # 헬퍼 메서드 - Request Body 빌드
    # ============================================================

    # 이벤트 생성/수정 본문 조립은 EventCreateParams/EventUpdateParams.to_graph_api_body()
    # 하나만 쓴다. 여기에 있던 _build_event_request_body/_build_event_update_body 는
    # snake_case 필드를 읽는 두 번째 사본이라 camelCase 모델과 어긋나 삭제했다.

    def _build_schedule_request_body(self, params: ScheduleRequest) -> Dict[str, Any]:
        """
        ScheduleRequest를 Graph API 요청 본문으로 변환

        Args:
            params: 스케줄 조회 파라미터

        Returns:
            Graph API 요청 본문
        """
        body: Dict[str, Any] = {
            "schedules": params.schedules,
            "startTime": {
                "dateTime": params.startTime.dateTime,
                "timeZone": params.startTime.timeZone,
            },
            "endTime": {
                "dateTime": params.endTime.dateTime,
                "timeZone": params.endTime.timeZone,
            },
        }

        if params.availabilityViewInterval is not None:
            body["availabilityViewInterval"] = params.availabilityViewInterval

        return body

    # ============================================================
    # 리소스 정리
    # ============================================================

    async def close(self):
        """Clean up resources.

        토큰 공급자는 이 객체의 소유가 아니다 — 주입된 사용자 공급자든 mode 0 의 공용
        AuthManager 든 닫지 않는다(사용자 서비스 퇴거가 인증 자원을 닫던 경로 제거,
        spec/spec_멀티유저.md ②-2.4). HTTP 세션은 요청마다 열고 닫으므로 남는 자원이 없다.
        """
        return None


# ============================================================
# 편의 함수
# ============================================================


async def get_calendar_events(
    user_email: str,
    start_datetime: Optional[str] = None,
    end_datetime: Optional[str] = None,
    top: int = 50,
    token_provider: Optional["TokenProviderProtocol"] = None,
) -> Dict[str, Any]:
    """
    캘린더 이벤트 조회 편의 함수

    Args:
        user_email: 사용자 이메일
        start_datetime: 시작 날짜/시간 (ISO 8601)
        end_datetime: 종료 날짜/시간 (ISO 8601)
        top: 최대 결과 수
        token_provider: 토큰 공급자 (멀티유저에서는 필수)

    Returns:
        이벤트 목록
    """
    query = GraphCalendarQuery(token_provider=token_provider)

    try:
        if start_datetime and end_datetime:
            return await query.list_calendar_view(
                user_email=user_email,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                top=top,
            )
        else:
            return await query.list_events(user_email=user_email, top=top)
    finally:
        await query.close()


async def create_calendar_event(
    user_email: str,
    subject: str,
    start_datetime: str,
    end_datetime: str,
    time_zone: str = "Korea Standard Time",
    location: Optional[str] = None,
    body: Optional[str] = None,
    attendees: Optional[List[str]] = None,
    is_online_meeting: bool = False,
    token_provider: Optional["TokenProviderProtocol"] = None,
) -> Dict[str, Any]:
    """
    캘린더 이벤트 생성 편의 함수

    Args:
        user_email: 사용자 이메일
        subject: 이벤트 제목
        start_datetime: 시작 날짜/시간 (ISO 8601)
        end_datetime: 종료 날짜/시간 (ISO 8601)
        time_zone: 시간대 (기본: Korea Standard Time)
        location: 장소
        body: 본문
        attendees: 참석자 이메일 목록
        is_online_meeting: Teams 회의 생성 여부
        token_provider: 토큰 공급자 (멀티유저에서는 필수)

    Returns:
        생성된 이벤트 정보
    """
    from .calendar_types import DateTimeTimeZone, Attendee, EmailAddress, Location

    query = GraphCalendarQuery(token_provider=token_provider)

    try:
        event_params = EventCreateParams(
            subject=subject,
            start=DateTimeTimeZone(dateTime=start_datetime, timeZone=time_zone),
            end=DateTimeTimeZone(dateTime=end_datetime, timeZone=time_zone),
            location=Location(displayName=location) if location else None,
            body=body,
            attendees=[
                Attendee(emailAddress=EmailAddress(address=email)) for email in (attendees or [])
            ],
            isOnlineMeeting=is_online_meeting,
            onlineMeetingProvider="teamsForBusiness" if is_online_meeting else None,
        )

        return await query.create_event(user_email=user_email, event_data=event_params)
    finally:
        await query.close()
