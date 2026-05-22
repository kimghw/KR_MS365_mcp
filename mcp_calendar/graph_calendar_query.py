"""
Graph Calendar Query - Calendar API 호출 레이어
인증 처리 및 Graph API 호출을 담당

역할:
    - 인증 처리 (AuthManager 활용)
    - URL로 Graph API 호출
    - 이벤트 CRUD 작업
    - Free/Busy 조회
"""

import asyncio
import aiohttp
import sys
import os
from typing import Dict, Any, List, Optional, Union, TYPE_CHECKING
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
            user_email: User email or "me" for current user
        """
        self.user_email = user_email

    @property
    def events_url(self) -> str:
        """이벤트 기본 URL"""
        return f"{self.BASE_URL}/users/{self.user_email}/events"

    @property
    def calendar_url(self) -> str:
        """캘린더 기본 URL"""
        return f"{self.BASE_URL}/users/{self.user_email}/calendar"

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
        params = [
            f"startDateTime={start_datetime}",
            f"endDateTime={end_datetime}",
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
        url = f"{self.events_url}/{event_id}"
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
            token_provider: 토큰 제공자 (None이면 기본 AuthManager 사용)
        """
        if token_provider is None:
            # 하위 호환성: 기본 AuthManager 사용
            from session.auth_manager import AuthManager
            token_provider = AuthManager()
        self.token_provider = token_provider
        self._url_builder: Optional[GraphCalendarUrlBuilder] = None

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
                print(f"Failed to get access token for {user_email}")

            return access_token

        except Exception as e:
            print(f"Token retrieval error for {user_email}: {str(e)}")
            return None

    def _get_url_builder(self, user_email: str) -> GraphCalendarUrlBuilder:
        """
        URL 빌더 인스턴스 반환 (캐싱)

        Args:
            user_email: 사용자 이메일

        Returns:
            GraphCalendarUrlBuilder 인스턴스
        """
        if self._url_builder is None or self._url_builder.user_email != user_email:
            self._url_builder = GraphCalendarUrlBuilder(user_email)
        return self._url_builder

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
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                }
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "status": "success",
                            "data": data,
                            "request_url": url,
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "status": "error",
                            "error": f"Request failed with status {response.status}",
                            "error_detail": error_text[:500],
                            "request_url": url,
                        }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "request_url": url,
            }

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
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                }
                async with session.post(url, headers=headers, json=data) as response:
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
                        return {
                            "status": "error",
                            "error": f"Request failed with status {response.status}",
                            "error_detail": response_text[:500],
                            "request_url": url,
                        }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "request_url": url,
            }

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
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                }
                async with session.patch(url, headers=headers, json=data) as response:
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
                        return {
                            "status": "error",
                            "error": f"Request failed with status {response.status}",
                            "error_detail": response_text[:500],
                            "request_url": url,
                        }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "request_url": url,
            }

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
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                }
                async with session.delete(url, headers=headers) as response:
                    if response.status == 204:
                        return {
                            "status": "success",
                            "message": "Successfully deleted",
                            "request_url": url,
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "status": "error",
                            "error": f"Request failed with status {response.status}",
                            "error_detail": error_text[:500],
                            "request_url": url,
                        }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "request_url": url,
            }

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
        if isinstance(event_data, EventCreateParams):
            request_body = self._build_event_request_body(event_data)
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
        if isinstance(event_data, EventUpdateParams):
            request_body = self._build_event_update_body(event_data)
        else:
            request_body = event_data

        # Build URL
        url_builder = self._get_url_builder(user_email)
        url = f"{url_builder.events_url}/{event_id}"

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
        url = f"{url_builder.events_url}/{event_id}"

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
    # 헬퍼 메서드 - Request Body 빌드
    # ============================================================

    def _build_event_request_body(self, params: EventCreateParams) -> Dict[str, Any]:
        """
        EventCreateParams를 Graph API 요청 본문으로 변환

        Args:
            params: 이벤트 생성 파라미터

        Returns:
            Graph API 요청 본문
        """
        body: Dict[str, Any] = {
            "subject": params.subject,
            "start": {
                "dateTime": params.start.dateTime,
                "timeZone": params.start.timeZone,
            },
            "end": {
                "dateTime": params.end.dateTime,
                "timeZone": params.end.timeZone,
            },
        }

        # 본문
        if params.body:
            body["body"] = {
                "contentType": params.body_content_type,
                "content": params.body,
            }

        # 장소
        if params.location:
            body["location"] = {"displayName": params.location}

        # 참석자
        if params.attendees:
            body["attendees"] = [
                {
                    "emailAddress": {
                        "address": a.email_address,
                        "name": a.name or a.email_address,
                    },
                    "type": a.type,
                }
                for a in params.attendees
            ]

        # 종일 이벤트
        if params.is_all_day is not None:
            body["isAllDay"] = params.is_all_day

        # 온라인 회의
        if params.is_online_meeting is not None:
            body["isOnlineMeeting"] = params.is_online_meeting
        if params.online_meeting_provider:
            body["onlineMeetingProvider"] = params.online_meeting_provider

        # 상태 및 속성
        if params.show_as:
            body["showAs"] = params.show_as
        if params.importance:
            body["importance"] = params.importance
        if params.sensitivity:
            body["sensitivity"] = params.sensitivity

        # 카테고리
        if params.categories:
            body["categories"] = params.categories

        # 알림
        if params.reminder_minutes_before_start is not None:
            body["reminderMinutesBeforeStart"] = params.reminder_minutes_before_start
        if params.is_reminder_on is not None:
            body["isReminderOn"] = params.is_reminder_on

        return body

    def _build_event_update_body(self, params: EventUpdateParams) -> Dict[str, Any]:
        """
        EventUpdateParams를 Graph API 요청 본문으로 변환 (None이 아닌 필드만)

        Args:
            params: 이벤트 수정 파라미터

        Returns:
            Graph API 요청 본문
        """
        body: Dict[str, Any] = {}

        if params.subject is not None:
            body["subject"] = params.subject

        if params.start is not None:
            body["start"] = {
                "dateTime": params.start.dateTime,
                "timeZone": params.start.timeZone,
            }

        if params.end is not None:
            body["end"] = {
                "dateTime": params.end.dateTime,
                "timeZone": params.end.timeZone,
            }

        if params.body is not None:
            body["body"] = {
                "contentType": params.body_content_type or "html",
                "content": params.body,
            }

        if params.location is not None:
            body["location"] = {"displayName": params.location}

        if params.attendees is not None:
            body["attendees"] = [
                {
                    "emailAddress": {
                        "address": a.email_address,
                        "name": a.name or a.email_address,
                    },
                    "type": a.type,
                }
                for a in params.attendees
            ]

        if params.is_all_day is not None:
            body["isAllDay"] = params.is_all_day

        if params.is_online_meeting is not None:
            body["isOnlineMeeting"] = params.is_online_meeting
        if params.online_meeting_provider is not None:
            body["onlineMeetingProvider"] = params.online_meeting_provider

        if params.show_as is not None:
            body["showAs"] = params.show_as
        if params.importance is not None:
            body["importance"] = params.importance
        if params.sensitivity is not None:
            body["sensitivity"] = params.sensitivity

        if params.categories is not None:
            body["categories"] = params.categories

        if params.reminder_minutes_before_start is not None:
            body["reminderMinutesBeforeStart"] = params.reminder_minutes_before_start
        if params.is_reminder_on is not None:
            body["isReminderOn"] = params.is_reminder_on

        return body

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
        """Clean up resources"""
        if self.token_provider and hasattr(self.token_provider, 'close'):
            await self.token_provider.close()


# ============================================================
# 편의 함수
# ============================================================


async def get_calendar_events(
    user_email: str,
    start_datetime: Optional[str] = None,
    end_datetime: Optional[str] = None,
    top: int = 50,
) -> Dict[str, Any]:
    """
    캘린더 이벤트 조회 편의 함수

    Args:
        user_email: 사용자 이메일
        start_datetime: 시작 날짜/시간 (ISO 8601)
        end_datetime: 종료 날짜/시간 (ISO 8601)
        top: 최대 결과 수

    Returns:
        이벤트 목록
    """
    query = GraphCalendarQuery()

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

    Returns:
        생성된 이벤트 정보
    """
    from .calendar_types import DateTimeTimeZone, Attendee

    query = GraphCalendarQuery()

    try:
        event_params = EventCreateParams(
            subject=subject,
            start=DateTimeTimeZone(date_time=start_datetime, time_zone=time_zone),
            end=DateTimeTimeZone(date_time=end_datetime, time_zone=time_zone),
            location=location,
            body=body,
            attendees=[
                Attendee(email_address=email) for email in (attendees or [])
            ],
            is_online_meeting=is_online_meeting,
            online_meeting_provider="teamsForBusiness" if is_online_meeting else None,
        )

        return await query.create_event(user_email=user_email, event_data=event_params)
    finally:
        await query.close()
