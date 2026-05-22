"""
Calendar Service - GraphCalendarClient Facade
인자를 그대로 위임하고, 필요시 일부 값만 조정하는 서비스 레이어
"""

from typing import Dict, Any, Optional, List, Union

from .graph_calendar_client import GraphCalendarClient
from .calendar_types import (
    EventFilterParams,
    EventSelectParams,
    EventCreateParams,
    EventUpdateParams,
    DateTimeTimeZone,
    Attendee,
    ScheduleRequest,
    build_event_filter_query,
    build_event_select_query,
)

# mcp_service decorator is only needed for registry scanning, not runtime
try:
    from mcp_editor.mcp_service_registry.mcp_service_decorator import mcp_service
except ImportError:
    # Define a no-op decorator for runtime when mcp_editor is not available
    def mcp_service(**kwargs):
        def decorator(func):
            return func

        return decorator


def get_default_user_email() -> Optional[str]:
    """
    auth.db에서 첫 번째 사용자 이메일 조회

    user_email이 제공되지 않은 경우 기본값으로 사용

    Returns:
        첫 번째 사용자 이메일 또는 None
    """
    try:
        from session.auth_database import AuthDatabase
        db = AuthDatabase()
        users = db.list_users()
        if users:
            return users[0].get('user_email')
    except Exception:
        pass
    return None


class CalendarService:
    """
    GraphCalendarClient의 Facade

    - 동일 시그니처로 위임
    - 일부 값만 조정/하드코딩
    - MCP 도구를 위한 단순화된 인터페이스 제공
    """

    def __init__(self):
        self._client: Optional[GraphCalendarClient] = None
        self._initialized: bool = False

    async def initialize(self) -> bool:
        """서비스 초기화"""
        if self._initialized:
            return True

        self._client = GraphCalendarClient()

        if await self._client.initialize():
            self._initialized = True
            return True
        return False

    def _ensure_initialized(self):
        """초기화 확인"""
        if not self._initialized or not self._client:
            raise RuntimeError("CalendarService not initialized. Call initialize() first.")

    # ===== MCP 도구 메서드들 (Facade 메서드) =====

    @mcp_service(
        tool_name="handler_calendar_list_events",
        server_name="calendar",
        service_name="list_events",
        category="calendar",
        tags=["query", "events"],
        priority=5,
        description="캘린더 이벤트 목록 조회",
    )
    async def list_events(
        self,
        user_email: Optional[str] = None,
        filter_params: Optional[EventFilterParams] = None,
        select_params: Optional[EventSelectParams] = None,
        top: int = 50,
        orderby: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        캘린더 이벤트 목록 조회 - GraphCalendarClient.list_events 위임

        Args:
            user_email: 사용자 이메일 (None이면 기본 사용자 사용)
            filter_params: 필터링 파라미터
            select_params: 선택할 필드
            top: 최대 결과 수
            orderby: 정렬 순서

        Returns:
            이벤트 목록
        """
        self._ensure_initialized()

        # user_email이 None인 경우 기본 사용자 이메일 조회
        if not user_email:
            user_email = get_default_user_email()
            if not user_email:
                return {"error": "No user_email provided and no default user found in database"}

        # 기본 정렬 순서
        if orderby is None:
            orderby = "start/dateTime desc"

        result = await self._client.list_events(
            user_email=user_email,
            filter_params=filter_params,
            select_params=select_params,
            top=top,
            orderby=orderby,
        )

        # 반환 형식 변환
        if "value" in result:
            result["events"] = result.pop("value")
            result["success"] = True
            result["user"] = user_email

        return result

    @mcp_service(
        tool_name="handler_calendar_view",
        server_name="calendar",
        service_name="calendar_view",
        category="calendar",
        tags=["query", "view", "range"],
        priority=5,
        description="기간별 캘린더뷰 조회 (반복 일정 인스턴스 포함)",
    )
    async def calendar_view(
        self,
        user_email: Optional[str] = None,
        start_datetime: str = "",
        end_datetime: str = "",
        select_params: Optional[EventSelectParams] = None,
        top: int = 50,
        orderby: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        기간별 캘린더뷰 조회 - GraphCalendarClient.calendar_view 위임

        calendarView 엔드포인트를 사용하여 반복 일정의 인스턴스도 포함

        Args:
            user_email: 사용자 이메일 (None이면 기본 사용자 사용)
            start_datetime: 시작 날짜/시간 (ISO 8601)
            end_datetime: 종료 날짜/시간 (ISO 8601)
            select_params: 선택할 필드
            top: 최대 결과 수
            orderby: 정렬 순서

        Returns:
            이벤트 목록 (반복 일정 인스턴스 포함)
        """
        self._ensure_initialized()

        # user_email이 None인 경우 기본 사용자 이메일 조회
        if not user_email:
            user_email = get_default_user_email()
            if not user_email:
                return {"error": "No user_email provided and no default user found in database"}

        # 기본 정렬 순서
        if orderby is None:
            orderby = "start/dateTime asc"

        result = await self._client.list_calendar_view(
            user_email=user_email,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            select_params=select_params,
            top=top,
            orderby=orderby,
        )

        # 반환 형식 변환
        if "value" in result:
            result["events"] = result.pop("value")
            result["success"] = True
            result["user"] = user_email
            result["range"] = {
                "start": start_datetime,
                "end": end_datetime,
            }

        return result

    @mcp_service(
        tool_name="handler_calendar_get_event",
        server_name="calendar",
        service_name="get_event",
        category="calendar",
        tags=["query", "single", "event"],
        priority=5,
        description="특정 이벤트 상세 조회",
    )
    async def get_event(
        self,
        user_email: Optional[str] = None,
        event_id: str = "",
        select_params: Optional[EventSelectParams] = None,
    ) -> Dict[str, Any]:
        """
        특정 이벤트 상세 조회 - GraphCalendarClient.get_event 위임

        Args:
            user_email: 사용자 이메일 (None이면 기본 사용자 사용)
            event_id: 이벤트 ID
            select_params: 선택할 필드

        Returns:
            이벤트 상세 정보
        """
        self._ensure_initialized()

        # user_email이 None인 경우 기본 사용자 이메일 조회
        if not user_email:
            user_email = get_default_user_email()
            if not user_email:
                return {"error": "No user_email provided and no default user found in database"}

        result = await self._client.get_event(
            user_email=user_email,
            event_id=event_id,
            select_params=select_params,
        )

        if result and "id" in result:
            return {
                "success": True,
                "user": user_email,
                "event": result,
            }

        return result

    @mcp_service(
        tool_name="handler_calendar_create_event",
        server_name="calendar",
        service_name="create_event",
        category="calendar",
        tags=["create", "event", "mutation"],
        priority=5,
        description="새 캘린더 이벤트 생성",
    )
    async def create_event(
        self,
        user_email: Optional[str] = None,
        subject: str = "",
        start: Union[str, DateTimeTimeZone, Dict[str, str]] = "",
        end: Union[str, DateTimeTimeZone, Dict[str, str]] = "",
        body: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[List[Union[str, Attendee, Dict[str, Any]]]] = None,
        is_all_day: bool = False,
        is_online_meeting: bool = False,
        online_meeting_provider: Optional[str] = None,
        show_as: str = "busy",
        importance: str = "normal",
        sensitivity: str = "normal",
        categories: Optional[List[str]] = None,
        reminder_minutes_before_start: int = 15,
        is_reminder_on: bool = True,
        body_content_type: str = "html",
    ) -> Dict[str, Any]:
        """
        새 캘린더 이벤트 생성 - GraphCalendarClient.create_event 위임

        Args:
            user_email: 사용자 이메일 (None이면 기본 사용자 사용)
            subject: 이벤트 제목
            start: 시작 날짜/시간
            end: 종료 날짜/시간
            body: 이벤트 본문
            location: 장소
            attendees: 참석자 목록
            is_all_day: 종일 이벤트 여부
            is_online_meeting: 온라인 회의 생성 여부
            online_meeting_provider: 온라인 회의 제공자
            show_as: 상태 표시
            importance: 중요도
            sensitivity: 민감도
            categories: 카테고리
            reminder_minutes_before_start: 알림 시간 (분)
            is_reminder_on: 알림 사용 여부
            body_content_type: 본문 형식 (text/html)

        Returns:
            생성된 이벤트 정보
        """
        self._ensure_initialized()

        # user_email이 None인 경우 기본 사용자 이메일 조회
        if not user_email:
            user_email = get_default_user_email()
            if not user_email:
                return {"error": "No user_email provided and no default user found in database"}

        # start/end 타입 변환
        start_dt = self._convert_to_datetime_timezone(start)
        end_dt = self._convert_to_datetime_timezone(end)

        # attendees 타입 변환
        attendee_list = self._convert_attendees(attendees) if attendees else None

        # EventCreateParams 생성
        event_data = EventCreateParams(
            subject=subject,
            start=start_dt,
            end=end_dt,
            body=body,
            body_content_type=body_content_type,
            location=location,
            attendees=attendee_list,
            is_all_day=is_all_day,
            is_online_meeting=is_online_meeting,
            online_meeting_provider=online_meeting_provider,
            show_as=show_as,
            importance=importance,
            sensitivity=sensitivity,
            categories=categories,
            reminder_minutes_before_start=reminder_minutes_before_start,
            is_reminder_on=is_reminder_on,
        )

        result = await self._client.create_event(
            user_email=user_email,
            event_data=event_data,
        )

        if result and "id" in result:
            return {
                "success": True,
                "user": user_email,
                "event": result,
                "message": "Event created successfully",
            }

        return result

    def _convert_to_datetime_timezone(
        self, dt: Union[str, DateTimeTimeZone, Dict[str, str]]
    ) -> DateTimeTimeZone:
        """날짜/시간을 DateTimeTimeZone 객체로 변환"""
        if isinstance(dt, DateTimeTimeZone):
            return dt
        elif isinstance(dt, dict):
            return DateTimeTimeZone(
                dateTime=dt.get("dateTime", dt.get("date_time", "")),
                timeZone=dt.get("timeZone", dt.get("time_zone", "Korea Standard Time")),
            )
        else:
            # ISO 8601 문자열인 경우
            return DateTimeTimeZone(
                dateTime=dt,
                timeZone="Korea Standard Time",
            )

    def _convert_attendees(
        self, attendees: List[Union[str, Attendee, Dict[str, Any]]]
    ) -> List[Attendee]:
        """참석자 목록을 Attendee 객체 리스트로 변환"""
        result = []
        for attendee in attendees:
            if isinstance(attendee, Attendee):
                result.append(attendee)
            elif isinstance(attendee, dict):
                result.append(Attendee(
                    email_address=attendee.get("email_address", attendee.get("emailAddress", "")),
                    name=attendee.get("name"),
                    type=attendee.get("type", "required"),
                ))
            else:
                # 문자열(이메일 주소)인 경우
                result.append(Attendee(email_address=attendee))
        return result

    @mcp_service(
        tool_name="handler_calendar_update_event",
        server_name="calendar",
        service_name="update_event",
        category="calendar",
        tags=["update", "event", "mutation"],
        priority=5,
        description="캘린더 이벤트 수정",
    )
    async def update_event(
        self,
        user_email: Optional[str] = None,
        event_id: str = "",
        subject: Optional[str] = None,
        start: Optional[Union[str, DateTimeTimeZone, Dict[str, str]]] = None,
        end: Optional[Union[str, DateTimeTimeZone, Dict[str, str]]] = None,
        body: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[List[Union[str, Attendee, Dict[str, Any]]]] = None,
        is_all_day: Optional[bool] = None,
        is_online_meeting: Optional[bool] = None,
        online_meeting_provider: Optional[str] = None,
        show_as: Optional[str] = None,
        importance: Optional[str] = None,
        sensitivity: Optional[str] = None,
        categories: Optional[List[str]] = None,
        reminder_minutes_before_start: Optional[int] = None,
        is_reminder_on: Optional[bool] = None,
        body_content_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        캘린더 이벤트 수정 - GraphCalendarClient.update_event 위임

        Args:
            user_email: 사용자 이메일 (None이면 기본 사용자 사용)
            event_id: 이벤트 ID
            subject: 이벤트 제목 (수정할 경우)
            start: 시작 날짜/시간 (수정할 경우)
            end: 종료 날짜/시간 (수정할 경우)
            body: 이벤트 본문 (수정할 경우)
            location: 장소 (수정할 경우)
            attendees: 참석자 목록 (수정할 경우)
            is_all_day: 종일 이벤트 여부 (수정할 경우)
            is_online_meeting: 온라인 회의 생성 여부 (수정할 경우)
            online_meeting_provider: 온라인 회의 제공자 (수정할 경우)
            show_as: 상태 표시 (수정할 경우)
            importance: 중요도 (수정할 경우)
            sensitivity: 민감도 (수정할 경우)
            categories: 카테고리 (수정할 경우)
            reminder_minutes_before_start: 알림 시간 (수정할 경우)
            is_reminder_on: 알림 사용 여부 (수정할 경우)
            body_content_type: 본문 형식 (수정할 경우)

        Returns:
            수정된 이벤트 정보
        """
        self._ensure_initialized()

        # user_email이 None인 경우 기본 사용자 이메일 조회
        if not user_email:
            user_email = get_default_user_email()
            if not user_email:
                return {"error": "No user_email provided and no default user found in database"}

        # start/end 타입 변환 (None 허용)
        start_dt = self._convert_to_datetime_timezone(start) if start else None
        end_dt = self._convert_to_datetime_timezone(end) if end else None

        # attendees 타입 변환 (None 허용)
        attendee_list = self._convert_attendees(attendees) if attendees else None

        # EventUpdateParams 생성
        event_data = EventUpdateParams(
            subject=subject,
            start=start_dt,
            end=end_dt,
            body=body,
            body_content_type=body_content_type,
            location=location,
            attendees=attendee_list,
            is_all_day=is_all_day,
            is_online_meeting=is_online_meeting,
            online_meeting_provider=online_meeting_provider,
            show_as=show_as,
            importance=importance,
            sensitivity=sensitivity,
            categories=categories,
            reminder_minutes_before_start=reminder_minutes_before_start,
            is_reminder_on=is_reminder_on,
        )

        result = await self._client.update_event(
            user_email=user_email,
            event_id=event_id,
            event_data=event_data,
        )

        if result and "id" in result:
            return {
                "success": True,
                "user": user_email,
                "event": result,
                "message": "Event updated successfully",
            }

        return result

    @mcp_service(
        tool_name="handler_calendar_delete_event",
        server_name="calendar",
        service_name="delete_event",
        category="calendar",
        tags=["delete", "event", "mutation"],
        priority=5,
        description="캘린더 이벤트 삭제",
    )
    async def delete_event(
        self,
        user_email: Optional[str] = None,
        event_id: str = "",
    ) -> Dict[str, Any]:
        """
        캘린더 이벤트 삭제 - GraphCalendarClient.delete_event 위임

        Args:
            user_email: 사용자 이메일 (None이면 기본 사용자 사용)
            event_id: 이벤트 ID

        Returns:
            삭제 결과
        """
        self._ensure_initialized()

        # user_email이 None인 경우 기본 사용자 이메일 조회
        if not user_email:
            user_email = get_default_user_email()
            if not user_email:
                return {"error": "No user_email provided and no default user found in database"}

        result = await self._client.delete_event(
            user_email=user_email,
            event_id=event_id,
        )

        if result.get("success", False):
            return {
                "success": True,
                "user": user_email,
                "event_id": event_id,
                "message": "Event deleted successfully",
            }

        return result

    @mcp_service(
        tool_name="handler_calendar_get_schedule",
        server_name="calendar",
        service_name="get_schedule",
        category="calendar",
        tags=["query", "schedule", "availability", "freebusy"],
        priority=5,
        description="사용자 일정 가용성 조회 (Free/Busy)",
    )
    async def get_schedule(
        self,
        user_email: Optional[str] = None,
        schedules: Optional[List[str]] = None,
        start_time: Union[str, DateTimeTimeZone, Dict[str, str]] = "",
        end_time: Union[str, DateTimeTimeZone, Dict[str, str]] = "",
        availability_view_interval: int = 30,
    ) -> Dict[str, Any]:
        """
        사용자 일정 가용성 조회 - GraphCalendarClient.get_schedule 위임

        여러 사용자의 Free/Busy 정보를 한 번에 조회

        Args:
            user_email: 요청하는 사용자 이메일 (None이면 기본 사용자 사용)
            schedules: 조회할 사용자 이메일 리스트
            start_time: 조회 시작 시간
            end_time: 조회 종료 시간
            availability_view_interval: 가용성 뷰 간격 (분, 기본 30분)

        Returns:
            사용자별 일정 가용성 정보
        """
        self._ensure_initialized()

        # user_email이 None인 경우 기본 사용자 이메일 조회
        if not user_email:
            user_email = get_default_user_email()
            if not user_email:
                return {"error": "No user_email provided and no default user found in database"}

        # schedules가 None이면 빈 리스트로 초기화
        if schedules is None:
            schedules = []

        # start_time/end_time 타입 변환
        start_dt = self._convert_to_datetime_timezone(start_time)
        end_dt = self._convert_to_datetime_timezone(end_time)

        # ScheduleRequest 생성
        schedule_request = ScheduleRequest(
            schedules=schedules,
            startTime=start_dt,
            endTime=end_dt,
            availabilityViewInterval=availability_view_interval,
        )

        result = await self._client.get_schedule(
            user_email=user_email,
            schedule_request=schedule_request,
        )

        if "value" in result:
            return {
                "success": True,
                "user": user_email,
                "schedules": result["value"],
                "range": {
                    "start": start_dt.dateTime,
                    "end": end_dt.dateTime,
                },
            }

        return result

    async def close(self):
        """리소스 정리"""
        if self._client:
            await self._client.close()
        self._initialized = False


# 서비스 인스턴스 생성 (싱글톤)
calendar_service = CalendarService()
