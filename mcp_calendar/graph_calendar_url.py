"""
Graph Calendar URL Builder - URL 빌더 통합 모듈
filter URL 생성을 담당

Classes:
    - CalendarFilterBuilder: $filter URL 파라미터 빌더
    - GraphCalendarUrlBuilder: 통합 URL 빌더
"""

from typing import Optional, List, Dict, Any
from datetime import datetime


class CalendarFilterBuilder:
    """
    Graph API $filter URL 파라미터 빌더

    캘린더 이벤트 필터링 조건을 OData $filter 쿼리로 변환
    """

    def __init__(self, user_id: str = "me"):
        """
        Initialize filter builder

        Args:
            user_id: User ID or "me" for current user
        """
        self.user_id = user_id
        self._filters: List[str] = []

    def reset(self) -> "CalendarFilterBuilder":
        """필터 초기화"""
        self._filters = []
        return self

    def start_after(self, date: datetime) -> "CalendarFilterBuilder":
        """
        시작 시간 이후 이벤트 필터

        Args:
            date: 시작 기준 날짜/시간 (datetime 객체)

        Returns:
            self (메서드 체이닝용)
        """
        self._filters.append(f"start/dateTime ge '{date.strftime('%Y-%m-%dT%H:%M:%SZ')}'")
        return self

    def end_before(self, date: datetime) -> "CalendarFilterBuilder":
        """
        종료 시간 이전 이벤트 필터

        Args:
            date: 종료 기준 날짜/시간 (datetime 객체)

        Returns:
            self (메서드 체이닝용)
        """
        self._filters.append(f"end/dateTime le '{date.strftime('%Y-%m-%dT%H:%M:%SZ')}'")
        return self

    def subject_contains(self, text: str) -> "CalendarFilterBuilder":
        """
        제목에 텍스트 포함 필터

        Args:
            text: 검색할 텍스트

        Returns:
            self (메서드 체이닝용)
        """
        self._filters.append(f"contains(subject, '{text}')")
        return self

    def organizer(self, email: str) -> "CalendarFilterBuilder":
        """
        특정 주최자 필터

        Args:
            email: 주최자 이메일

        Returns:
            self (메서드 체이닝용)
        """
        self._filters.append(f"organizer/emailAddress/address eq '{email}'")
        return self

    def is_cancelled(self, value: bool = True) -> "CalendarFilterBuilder":
        """
        취소된 이벤트 필터

        Args:
            value: True면 취소된 이벤트, False면 취소되지 않은 이벤트

        Returns:
            self (메서드 체이닝용)
        """
        self._filters.append(f"isCancelled eq {str(value).lower()}")
        return self

    def importance(self, value: str) -> "CalendarFilterBuilder":
        """
        중요도 필터

        Args:
            value: 중요도 (low, normal, high)

        Returns:
            self (메서드 체이닝용)
        """
        self._filters.append(f"importance eq '{value}'")
        return self

    def show_as(self, value: str) -> "CalendarFilterBuilder":
        """
        상태 표시 필터

        Args:
            value: 상태 (free, tentative, busy, oof, workingElsewhere, unknown)

        Returns:
            self (메서드 체이닝용)
        """
        self._filters.append(f"showAs eq '{value}'")
        return self

    def is_all_day(self, value: bool = True) -> "CalendarFilterBuilder":
        """
        종일 이벤트 필터

        Args:
            value: True면 종일 이벤트, False면 일반 이벤트

        Returns:
            self (메서드 체이닝용)
        """
        self._filters.append(f"isAllDay eq {str(value).lower()}")
        return self

    def is_online_meeting(self, value: bool = True) -> "CalendarFilterBuilder":
        """
        온라인 미팅 필터

        Args:
            value: True면 온라인 미팅, False면 오프라인 미팅

        Returns:
            self (메서드 체이닝용)
        """
        self._filters.append(f"isOnlineMeeting eq {str(value).lower()}")
        return self

    def add_raw(self, filter_string: str) -> "CalendarFilterBuilder":
        """
        직접 필터 문자열 추가

        Args:
            filter_string: OData 필터 문자열

        Returns:
            self (메서드 체이닝용)
        """
        self._filters.append(filter_string)
        return self

    def build(self) -> str:
        """
        필터 쿼리 문자열 생성

        Returns:
            $filter 쿼리 문자열 (빈 경우 빈 문자열)
        """
        return " and ".join(self._filters) if self._filters else ""

    def build_from_dict(self, params: Dict[str, Any]) -> str:
        """
        딕셔너리에서 필터 쿼리 생성

        Args:
            params: 필터 파라미터 딕셔너리
                - start_after: datetime - 시작 시간 이후
                - end_before: datetime - 종료 시간 이전
                - subject: str - 제목 포함 텍스트
                - organizer: str - 주최자 이메일
                - is_cancelled: bool - 취소 여부
                - importance: str - 중요도 (low, normal, high)
                - show_as: str - 상태 표시
                - is_all_day: bool - 종일 이벤트 여부
                - is_online_meeting: bool - 온라인 미팅 여부

        Returns:
            $filter 쿼리 문자열
        """
        self.reset()

        if params.get("start_after"):
            self.start_after(params["start_after"])

        if params.get("end_before"):
            self.end_before(params["end_before"])

        if params.get("subject"):
            self.subject_contains(params["subject"])

        if params.get("organizer"):
            self.organizer(params["organizer"])

        if params.get("is_cancelled") is not None:
            self.is_cancelled(params["is_cancelled"])

        if params.get("importance"):
            self.importance(params["importance"])

        if params.get("show_as"):
            self.show_as(params["show_as"])

        if params.get("is_all_day") is not None:
            self.is_all_day(params["is_all_day"])

        if params.get("is_online_meeting") is not None:
            self.is_online_meeting(params["is_online_meeting"])

        return self.build()


class GraphCalendarUrlBuilder:
    """
    Graph API 캘린더 URL 통합 빌더

    filter를 조합하여 완전한 URL 생성
    """

    BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(self, user_email: str = "me"):
        """
        Initialize URL builder

        Args:
            user_email: User email or "me" for current user
        """
        self.user_email = user_email
        self.filter_builder = CalendarFilterBuilder(user_email)

    def reset(self) -> "GraphCalendarUrlBuilder":
        """빌더 초기화"""
        self.filter_builder.reset()
        return self

    @property
    def events_url(self) -> str:
        """이벤트 기본 URL"""
        return f"{self.BASE_URL}/users/{self.user_email}/events"

    @property
    def calendar_view_url(self) -> str:
        """캘린더 뷰 기본 URL"""
        return f"{self.BASE_URL}/users/{self.user_email}/calendar/calendarView"

    def build_events_url(
        self,
        filter_query: Optional[str] = None,
        select_fields: Optional[List[str]] = None,
        order_by: Optional[str] = None,
        top: Optional[int] = None,
        skip: Optional[int] = None,
    ) -> str:
        """
        GET /me/events URL 생성

        $filter 기반으로 이벤트 목록을 조회하는 URL 생성

        Args:
            filter_query: $filter 쿼리 문자열
            select_fields: 선택할 필드 목록
            order_by: 정렬 순서 (예: "start/dateTime desc")
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
    ) -> str:
        """
        GET /me/calendar/calendarView URL 생성

        특정 기간의 캘린더 뷰를 조회하는 URL 생성
        startDateTime과 endDateTime은 필수 파라미터

        Args:
            start_datetime: 시작 날짜/시간 (ISO 8601 형식, 예: "2024-01-01T00:00:00Z")
            end_datetime: 종료 날짜/시간 (ISO 8601 형식, 예: "2024-01-31T23:59:59Z")
            select_fields: 선택할 필드 목록
            order_by: 정렬 순서 (예: "start/dateTime")
            top: 최대 결과 수

        Returns:
            완전한 URL

        Example:
            >>> builder = GraphCalendarUrlBuilder()
            >>> url = builder.build_calendar_view_url(
            ...     start_datetime="2024-01-01T00:00:00Z",
            ...     end_datetime="2024-01-31T23:59:59Z",
            ...     top=50
            ... )
        """
        url = self.calendar_view_url
        # startDateTime과 endDateTime은 필수 파라미터
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

        url += "?" + "&".join(params)

        return url

    def build_event_url(
        self,
        event_id: str,
        select_fields: Optional[List[str]] = None,
    ) -> str:
        """
        GET /me/events/{id} URL 생성

        단일 이벤트를 조회하는 URL 생성

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

    def build_get_schedule_url(self) -> str:
        """
        POST /me/calendar/getSchedule URL 생성

        사용자의 가용성 정보를 조회하는 URL 생성
        이 엔드포인트는 POST 요청으로 사용하며, 요청 본문에 조회할
        사용자 목록과 기간을 포함해야 함

        Returns:
            getSchedule 엔드포인트 URL

        Note:
            이 URL은 POST 요청과 함께 사용해야 하며, 요청 본문 예시:
            {
                "schedules": ["user1@example.com", "user2@example.com"],
                "startTime": {"dateTime": "2024-01-01T09:00:00", "timeZone": "UTC"},
                "endTime": {"dateTime": "2024-01-01T18:00:00", "timeZone": "UTC"},
                "availabilityViewInterval": 30
            }
        """
        return f"{self.BASE_URL}/users/{self.user_email}/calendar/getSchedule"


# 편의 함수들
def quick_event_filter(
    start_after: Optional[datetime] = None,
    end_before: Optional[datetime] = None,
    subject: Optional[str] = None,
    organizer: Optional[str] = None,
    is_cancelled: Optional[bool] = None,
    importance: Optional[str] = None,
    show_as: Optional[str] = None,
    is_all_day: Optional[bool] = None,
    is_online_meeting: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    빠른 이벤트 필터 파라미터 생성

    Args:
        start_after: 시작 시간 이후 (datetime 객체)
        end_before: 종료 시간 이전 (datetime 객체)
        subject: 제목 포함 텍스트
        organizer: 주최자 이메일
        is_cancelled: 취소 여부
        importance: 중요도 (low, normal, high)
        show_as: 상태 표시 (free, tentative, busy, oof, workingElsewhere, unknown)
        is_all_day: 종일 이벤트 여부
        is_online_meeting: 온라인 미팅 여부

    Returns:
        필터 파라미터 딕셔너리
    """
    params: Dict[str, Any] = {}

    if start_after is not None:
        params["start_after"] = start_after
    if end_before is not None:
        params["end_before"] = end_before
    if subject:
        params["subject"] = subject
    if organizer:
        params["organizer"] = organizer
    if is_cancelled is not None:
        params["is_cancelled"] = is_cancelled
    if importance:
        params["importance"] = importance
    if show_as:
        params["show_as"] = show_as
    if is_all_day is not None:
        params["is_all_day"] = is_all_day
    if is_online_meeting is not None:
        params["is_online_meeting"] = is_online_meeting

    return params


def build_filter_query(params: Dict[str, Any]) -> str:
    """
    딕셔너리에서 $filter 쿼리 생성 (편의 함수)

    Args:
        params: 필터 파라미터 딕셔너리

    Returns:
        $filter 쿼리 문자열
    """
    builder = CalendarFilterBuilder()
    return builder.build_from_dict(params)
