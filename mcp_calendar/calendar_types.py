"""
Microsoft Graph Calendar API 타입 정의
Pydantic 모델을 사용하여 런타임 유효성 검증과 문서화 제공
outlook_types.py 패턴을 따름
"""

from typing import Optional, List, Union, Literal, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


# ============================================================================
# 기본 타입 정의 (Graph API 구조체)
# ============================================================================


class DateTimeTimeZone(BaseModel):
    """날짜/시간 + 시간대 (Graph API dateTimeTimeZone 타입)

    이벤트의 start, end 등에 사용되는 날짜/시간 정보
    Graph API 필드명: dateTime, timeZone (camelCase)
    """

    model_config = ConfigDict(extra="ignore")

    dateTime: str = Field(
        ...,
        description="날짜와 시간 (ISO 8601 형식, 예: 2024-12-01T09:00:00)",
        examples=["2024-12-01T09:00:00", "2024-12-01T14:30:00"],
    )
    timeZone: str = Field(
        default="UTC",
        description="시간대 (IANA 또는 Windows 시간대)",
        examples=["UTC", "Asia/Seoul", "Korea Standard Time", "Pacific Standard Time"],
    )

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()


class EmailAddress(BaseModel):
    """이메일 주소 정보 (Graph API emailAddress 타입)"""

    model_config = ConfigDict(extra="ignore")

    address: str = Field(
        ...,
        description="이메일 주소",
        examples=["user@example.com"],
    )
    name: Optional[str] = Field(
        None,
        description="표시 이름",
        examples=["홍길동", "John Doe"],
    )

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()


class ResponseStatus(BaseModel):
    """참석자 응답 상태 (Graph API responseStatus 타입)"""

    model_config = ConfigDict(extra="ignore")

    response: Optional[
        Literal["none", "organizer", "tentativelyAccepted", "accepted", "declined", "notResponded"]
    ] = Field(
        None,
        description="응답 상태",
    )
    time: Optional[str] = Field(
        None,
        description="응답 시간 (ISO 8601 형식)",
    )

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()


class Attendee(BaseModel):
    """참석자 정보 (Graph API attendee 타입)

    Attributes:
        emailAddress: 참석자 이메일 주소 정보 (EmailAddress 객체)
        type: 참석자 유형 (required, optional, resource)
        status: 참석자 응답 상태 (ResponseStatus 객체)
    """

    model_config = ConfigDict(extra="ignore")

    emailAddress: EmailAddress = Field(
        ...,
        description="참석자 이메일 주소 정보",
    )
    type: Optional[Literal["required", "optional", "resource"]] = Field(
        "required",
        description="참석자 유형 (required: 필수, optional: 선택, resource: 리소스/회의실)",
    )
    status: Optional[ResponseStatus] = Field(
        None,
        description="참석자 응답 상태",
    )

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()


class PhysicalAddress(BaseModel):
    """물리적 주소 정보 (Graph API physicalAddress 타입)"""

    model_config = ConfigDict(extra="ignore")

    street: Optional[str] = Field(None, description="거리 주소")
    city: Optional[str] = Field(None, description="도시")
    state: Optional[str] = Field(None, description="주/도")
    countryOrRegion: Optional[str] = Field(None, description="국가 또는 지역")
    postalCode: Optional[str] = Field(None, description="우편번호")

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()


class GeoCoordinates(BaseModel):
    """지리적 좌표 (Graph API geoCoordinates 타입)"""

    model_config = ConfigDict(extra="ignore")

    latitude: Optional[float] = Field(None, description="위도")
    longitude: Optional[float] = Field(None, description="경도")
    altitude: Optional[float] = Field(None, description="고도")
    accuracy: Optional[float] = Field(None, description="정확도 (미터)")
    altitudeAccuracy: Optional[float] = Field(None, description="고도 정확도 (미터)")

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()


class Location(BaseModel):
    """장소 정보 (Graph API location 타입)

    Attributes:
        displayName: 장소 표시 이름
        locationType: 장소 유형 (conferenceRoom, homeAddress 등)
        address: 물리적 주소 정보
        coordinates: 지리적 좌표
        locationUri: 장소 URI
        locationEmailAddress: 장소 이메일 주소 (회의실 등)
        uniqueId: 장소 고유 ID
        uniqueIdType: 고유 ID 유형
    """

    model_config = ConfigDict(extra="ignore")

    displayName: Optional[str] = Field(
        None,
        description="장소 표시 이름",
        examples=["회의실 A", "본사 대회의실"],
    )
    locationType: Optional[
        Literal[
            "default",
            "conferenceRoom",
            "homeAddress",
            "businessAddress",
            "geoCoordinates",
            "streetAddress",
            "hotel",
            "restaurant",
            "localBusiness",
            "postalAddress",
        ]
    ] = Field(
        None,
        description="장소 유형",
    )
    locationUri: Optional[str] = Field(
        None,
        description="장소 URI",
    )
    address: Optional[PhysicalAddress] = Field(
        None,
        description="물리적 주소",
    )
    coordinates: Optional[GeoCoordinates] = Field(
        None,
        description="지리적 좌표",
    )
    locationEmailAddress: Optional[str] = Field(
        None,
        description="장소 이메일 주소 (회의실 등)",
    )
    uniqueId: Optional[str] = Field(
        None,
        description="장소 고유 ID",
    )
    uniqueIdType: Optional[Literal["unknown", "locationStore", "directory", "private", "bing"]] = Field(
        None,
        description="고유 ID 유형",
    )

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()


class ItemBody(BaseModel):
    """이벤트 본문 (Graph API itemBody 타입)"""

    model_config = ConfigDict(extra="ignore")

    contentType: Literal["text", "html"] = Field(
        "html",
        description="본문 콘텐츠 유형",
    )
    content: str = Field(
        ...,
        description="본문 내용",
    )

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()


class RecurrencePattern(BaseModel):
    """반복 패턴 (Graph API recurrencePattern 타입)"""

    model_config = ConfigDict(extra="ignore")

    type: Literal["daily", "weekly", "absoluteMonthly", "relativeMonthly", "absoluteYearly", "relativeYearly"] = Field(
        ...,
        description="반복 유형",
    )
    interval: int = Field(
        1,
        description="반복 간격",
    )
    daysOfWeek: Optional[
        List[Literal["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]]
    ] = Field(
        None,
        description="반복 요일 (주간 반복 시)",
    )
    dayOfMonth: Optional[int] = Field(
        None,
        description="반복 일 (월간 반복 시)",
    )
    month: Optional[int] = Field(
        None,
        description="반복 월 (연간 반복 시)",
    )
    firstDayOfWeek: Optional[
        Literal["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
    ] = Field(
        None,
        description="주의 첫 번째 요일",
    )
    index: Optional[Literal["first", "second", "third", "fourth", "last"]] = Field(
        None,
        description="상대적 반복 인덱스",
    )

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()


class RecurrenceRange(BaseModel):
    """반복 범위 (Graph API recurrenceRange 타입)"""

    model_config = ConfigDict(extra="ignore")

    type: Literal["endDate", "noEnd", "numbered"] = Field(
        ...,
        description="반복 범위 유형",
    )
    startDate: str = Field(
        ...,
        description="반복 시작 날짜 (YYYY-MM-DD)",
    )
    endDate: Optional[str] = Field(
        None,
        description="반복 종료 날짜 (YYYY-MM-DD, type이 endDate인 경우)",
    )
    numberOfOccurrences: Optional[int] = Field(
        None,
        description="반복 횟수 (type이 numbered인 경우)",
    )
    recurrenceTimeZone: Optional[str] = Field(
        None,
        description="반복 시간대",
    )

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()


class PatternedRecurrence(BaseModel):
    """패턴 반복 설정 (Graph API patternedRecurrence 타입)"""

    model_config = ConfigDict(extra="ignore")

    pattern: RecurrencePattern = Field(
        ...,
        description="반복 패턴",
    )
    range: RecurrenceRange = Field(
        ...,
        description="반복 범위",
    )

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()


class OnlineMeeting(BaseModel):
    """온라인 회의 정보 (Graph API onlineMeetingInfo 타입)"""

    model_config = ConfigDict(extra="ignore")

    joinUrl: Optional[str] = Field(None, description="회의 참가 URL")
    conferenceId: Optional[str] = Field(None, description="회의 ID")
    tollNumber: Optional[str] = Field(None, description="전화번호")

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()


# ============================================================================
# 이벤트 필터링/조회 파라미터
# ============================================================================


class EventFilterParams(BaseModel):
    """이벤트 필터링 파라미터 ($filter 쿼리용)

    Graph API 필드 매핑 (snake_case -> camelCase):
    - start_date_time -> start/dateTime
    - end_date_time -> end/dateTime
    - is_cancelled -> isCancelled
    - is_all_day -> isAllDay
    - show_as -> showAs
    - response_status -> responseStatus/response
    - is_online_meeting -> isOnlineMeeting
    """

    model_config = ConfigDict(extra="ignore")

    # 날짜/시간 범위
    start_date_time: Optional[str] = Field(
        None,
        description="조회 시작 날짜/시간 (ISO 8601 형식, start >= 이 값)",
        examples=["2024-12-01T00:00:00Z", "2024-12-01T09:00:00"],
    )
    end_date_time: Optional[str] = Field(
        None,
        description="조회 종료 날짜/시간 (ISO 8601 형식, end <= 이 값)",
        examples=["2024-12-31T23:59:59Z", "2024-12-31T18:00:00"],
    )

    # 제목 검색
    subject: Optional[Union[str, List[str]]] = Field(
        None,
        description="제목에 포함될 키워드 (단일 문자열 또는 리스트)",
        examples=["회의", ["프로젝트", "미팅"]],
    )
    subject_operator: Optional[Literal["or", "and"]] = Field(
        "or",
        description="제목 키워드 연결 방식 (or: 하나라도 포함, and: 모두 포함)",
    )

    # 주최자
    organizer_email: Optional[str] = Field(
        None,
        description="주최자 이메일 주소",
        examples=["organizer@example.com"],
    )

    # 이벤트 상태
    is_cancelled: Optional[bool] = Field(
        None,
        description="취소 여부 (true: 취소된 이벤트, false: 활성 이벤트)",
    )
    is_all_day: Optional[bool] = Field(
        None,
        description="종일 이벤트 여부",
    )
    is_online_meeting: Optional[bool] = Field(
        None,
        description="온라인 회의 여부",
    )

    # 이벤트 속성
    importance: Optional[Literal["low", "normal", "high"]] = Field(
        None,
        description="이벤트 중요도",
    )
    show_as: Optional[Literal["free", "tentative", "busy", "oof", "workingElsewhere", "unknown"]] = Field(
        None,
        description="일정 표시 상태 (free: 한가함, tentative: 미정, busy: 바쁨, oof: 자리 비움, workingElsewhere: 다른 곳에서 근무)",
    )
    response_status: Optional[
        Literal["none", "organizer", "tentativelyAccepted", "accepted", "declined", "notResponded"]
    ] = Field(
        None,
        description="응답 상태",
    )
    sensitivity: Optional[Literal["normal", "personal", "private", "confidential"]] = Field(
        None,
        description="민감도",
    )

    # 카테고리
    categories: Optional[List[str]] = Field(
        None,
        description="이벤트 카테고리 목록",
        examples=[["업무", "중요"]],
    )

    # ID 관련
    id: Optional[str] = Field(None, description="이벤트 ID")
    series_master_id: Optional[str] = Field(None, description="반복 이벤트 마스터 ID")

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()


class EventSelectParams(BaseModel):
    """이벤트 조회 시 선택할 필드 ($select 파라미터)

    각 필드를 True로 설정하면 해당 필드가 $select 쿼리에 포함됨
    """

    model_config = ConfigDict(extra="ignore")

    # 기본 정보
    id: Optional[bool] = Field(None, description="이벤트 고유 식별자")
    subject: Optional[bool] = Field(None, description="이벤트 제목")
    body: Optional[bool] = Field(None, description="이벤트 본문 (HTML 또는 텍스트)")
    bodyPreview: Optional[bool] = Field(None, description="이벤트 본문 미리보기 (최대 255자)")

    # 날짜/시간
    start: Optional[bool] = Field(None, description="시작 날짜/시간 (DateTimeTimeZone)")
    end: Optional[bool] = Field(None, description="종료 날짜/시간 (DateTimeTimeZone)")

    # 장소 및 참석자
    location: Optional[bool] = Field(None, description="장소 정보")
    locations: Optional[bool] = Field(None, description="장소 목록")
    organizer: Optional[bool] = Field(None, description="주최자 정보")
    attendees: Optional[bool] = Field(None, description="참석자 목록")

    # 이벤트 상태
    isAllDay: Optional[bool] = Field(None, description="종일 이벤트 여부")
    isCancelled: Optional[bool] = Field(None, description="취소 여부")
    isOnlineMeeting: Optional[bool] = Field(None, description="온라인 회의 여부")

    # 링크 및 URL
    onlineMeetingUrl: Optional[bool] = Field(None, description="온라인 회의 URL")
    webLink: Optional[bool] = Field(None, description="Outlook Web에서 이벤트를 열기 위한 URL")
    onlineMeeting: Optional[bool] = Field(None, description="온라인 회의 정보 (Teams 등)")

    # 속성
    importance: Optional[bool] = Field(None, description="중요도 (low, normal, high)")
    showAs: Optional[bool] = Field(None, description="일정 표시 상태")
    responseStatus: Optional[bool] = Field(None, description="응답 상태")
    sensitivity: Optional[bool] = Field(None, description="민감도")

    # 카테고리 및 첨부
    categories: Optional[bool] = Field(None, description="카테고리 목록")
    hasAttachments: Optional[bool] = Field(None, description="첨부파일 포함 여부")

    # 반복
    recurrence: Optional[bool] = Field(None, description="반복 설정")
    seriesMasterId: Optional[bool] = Field(None, description="반복 시리즈 마스터 ID")

    # 타임스탬프
    createdDateTime: Optional[bool] = Field(None, description="생성 날짜/시간")
    lastModifiedDateTime: Optional[bool] = Field(None, description="최종 수정 날짜/시간")

    # 기타
    type: Optional[bool] = Field(None, description="이벤트 유형 (singleInstance, occurrence, exception, seriesMaster)")
    changeKey: Optional[bool] = Field(None, description="버전 키")
    iCalUId: Optional[bool] = Field(None, description="iCalendar UID")
    reminderMinutesBeforeStart: Optional[bool] = Field(None, description="알림 시간 (시작 전 분)")
    isReminderOn: Optional[bool] = Field(None, description="알림 활성화 여부")
    responseRequested: Optional[bool] = Field(None, description="응답 요청 여부")
    originalStartTimeZone: Optional[bool] = Field(None, description="원래 시작 시간대")
    originalEndTimeZone: Optional[bool] = Field(None, description="원래 종료 시간대")
    isDraft: Optional[bool] = Field(None, description="초안 여부")
    isOrganizer: Optional[bool] = Field(None, description="주최자 여부")
    onlineMeetingProvider: Optional[bool] = Field(None, description="온라인 회의 제공자")

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()

    def get_selected_fields(self) -> List[str]:
        """True로 설정된 필드들의 Graph API 필드명 목록 반환"""
        selected = []
        for field_name in self.__class__.model_fields.keys():
            if getattr(self, field_name, None) is True:
                selected.append(field_name)
        return selected


# ============================================================================
# 이벤트 생성/수정 파라미터
# ============================================================================


class EventCreateParams(BaseModel):
    """이벤트 생성 파라미터

    Attributes:
        subject: 이벤트 제목 (필수)
        start: 시작 날짜/시간 (필수, DateTimeTimeZone)
        end: 종료 날짜/시간 (필수, DateTimeTimeZone)
        body: 이벤트 본문
        bodyContentType: 본문 유형 (text, html)
        location: 장소 정보
        attendees: 참석자 목록
        isAllDay: 종일 이벤트 여부
        isOnlineMeeting: 온라인 회의 여부
        importance: 중요도
        showAs: 일정 표시 상태
        categories: 카테고리 목록
        recurrence: 반복 설정
    """

    model_config = ConfigDict(extra="ignore")

    # 필수 필드
    subject: str = Field(
        ...,
        description="이벤트 제목",
        examples=["프로젝트 회의", "팀 미팅"],
    )
    start: DateTimeTimeZone = Field(
        ...,
        description="시작 날짜/시간",
    )
    end: DateTimeTimeZone = Field(
        ...,
        description="종료 날짜/시간",
    )

    # 본문
    body: Optional[str] = Field(
        None,
        description="이벤트 본문 내용",
    )
    bodyContentType: Optional[Literal["text", "html"]] = Field(
        "html",
        description="본문 콘텐츠 유형",
    )

    # 장소 및 참석자
    location: Optional[Location] = Field(
        None,
        description="장소 정보",
    )
    attendees: Optional[List[Attendee]] = Field(
        None,
        description="참석자 목록",
    )

    # 이벤트 속성
    isAllDay: Optional[bool] = Field(
        None,
        description="종일 이벤트 여부",
    )
    isOnlineMeeting: Optional[bool] = Field(
        None,
        description="온라인 회의 여부 (true로 설정 시 온라인 회의 자동 생성)",
    )
    onlineMeetingProvider: Optional[
        Literal["unknown", "teamsForBusiness", "skypeForBusiness", "skypeForConsumer"]
    ] = Field(
        None,
        description="온라인 회의 제공자",
    )

    # 상태 및 중요도
    importance: Optional[Literal["low", "normal", "high"]] = Field(
        None,
        description="중요도",
    )
    showAs: Optional[Literal["free", "tentative", "busy", "oof", "workingElsewhere"]] = Field(
        None,
        description="일정 표시 상태",
    )
    sensitivity: Optional[Literal["normal", "personal", "private", "confidential"]] = Field(
        None,
        description="민감도",
    )

    # 카테고리
    categories: Optional[List[str]] = Field(
        None,
        description="카테고리 목록",
    )

    # 반복 설정
    recurrence: Optional[PatternedRecurrence] = Field(
        None,
        description="반복 설정",
    )

    # 알림
    reminderMinutesBeforeStart: Optional[int] = Field(
        None,
        description="알림 시간 (시작 전 분)",
    )
    isReminderOn: Optional[bool] = Field(
        None,
        description="알림 활성화 여부",
    )

    # 응답 요청
    responseRequested: Optional[bool] = Field(
        None,
        description="참석자에게 응답 요청 여부",
    )

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()

    def to_graph_api_body(self) -> Dict[str, Any]:
        """Graph API 요청 본문으로 변환"""
        body = {
            "subject": self.subject,
            "start": self.start.model_dump(),
            "end": self.end.model_dump(),
        }

        # 본문 추가
        if self.body:
            body["body"] = {
                "contentType": self.bodyContentType or "html",
                "content": self.body,
            }

        # 장소 추가
        if self.location:
            body["location"] = self.location.model_dump(exclude_none=True)

        # 참석자 추가
        if self.attendees:
            body["attendees"] = [att.model_dump(exclude_none=True) for att in self.attendees]

        # 선택적 필드 추가
        optional_fields = [
            "isAllDay",
            "isOnlineMeeting",
            "onlineMeetingProvider",
            "importance",
            "showAs",
            "sensitivity",
            "categories",
            "reminderMinutesBeforeStart",
            "isReminderOn",
            "responseRequested",
        ]
        for field in optional_fields:
            value = getattr(self, field, None)
            if value is not None:
                body[field] = value

        # 반복 설정 추가
        if self.recurrence:
            body["recurrence"] = self.recurrence.model_dump(exclude_none=True)

        return body


class EventUpdateParams(BaseModel):
    """이벤트 수정 파라미터 (모두 Optional)"""

    model_config = ConfigDict(extra="ignore")

    # 제목
    subject: Optional[str] = Field(
        None,
        description="이벤트 제목",
    )

    # 날짜/시간
    start: Optional[DateTimeTimeZone] = Field(
        None,
        description="시작 날짜/시간",
    )
    end: Optional[DateTimeTimeZone] = Field(
        None,
        description="종료 날짜/시간",
    )

    # 본문
    body: Optional[str] = Field(
        None,
        description="이벤트 본문 내용",
    )
    bodyContentType: Optional[Literal["text", "html"]] = Field(
        None,
        description="본문 콘텐츠 유형",
    )

    # 장소 및 참석자
    location: Optional[Location] = Field(
        None,
        description="장소 정보",
    )
    attendees: Optional[List[Attendee]] = Field(
        None,
        description="참석자 목록",
    )

    # 이벤트 속성
    isAllDay: Optional[bool] = Field(
        None,
        description="종일 이벤트 여부",
    )
    isOnlineMeeting: Optional[bool] = Field(
        None,
        description="온라인 회의 여부",
    )

    # 상태 및 중요도
    importance: Optional[Literal["low", "normal", "high"]] = Field(
        None,
        description="중요도",
    )
    showAs: Optional[Literal["free", "tentative", "busy", "oof", "workingElsewhere"]] = Field(
        None,
        description="일정 표시 상태",
    )
    sensitivity: Optional[Literal["normal", "personal", "private", "confidential"]] = Field(
        None,
        description="민감도",
    )

    # 카테고리
    categories: Optional[List[str]] = Field(
        None,
        description="카테고리 목록",
    )

    # 반복 설정
    recurrence: Optional[PatternedRecurrence] = Field(
        None,
        description="반복 설정",
    )

    # 알림
    reminderMinutesBeforeStart: Optional[int] = Field(
        None,
        description="알림 시간 (시작 전 분)",
    )
    isReminderOn: Optional[bool] = Field(
        None,
        description="알림 활성화 여부",
    )

    # 응답 요청
    responseRequested: Optional[bool] = Field(
        None,
        description="참석자에게 응답 요청 여부",
    )

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()

    def to_graph_api_body(self) -> Dict[str, Any]:
        """Graph API 요청 본문으로 변환 (설정된 필드만 포함)"""
        body = {}

        if self.subject is not None:
            body["subject"] = self.subject

        if self.start is not None:
            body["start"] = self.start.model_dump()

        if self.end is not None:
            body["end"] = self.end.model_dump()

        # 본문 추가
        if self.body is not None:
            body["body"] = {
                "contentType": self.bodyContentType or "html",
                "content": self.body,
            }

        # 장소 추가
        if self.location is not None:
            body["location"] = self.location.model_dump(exclude_none=True)

        # 참석자 추가
        if self.attendees is not None:
            body["attendees"] = [att.model_dump(exclude_none=True) for att in self.attendees]

        # 선택적 필드 추가
        optional_fields = [
            "isAllDay",
            "isOnlineMeeting",
            "importance",
            "showAs",
            "sensitivity",
            "categories",
            "reminderMinutesBeforeStart",
            "isReminderOn",
            "responseRequested",
        ]
        for field in optional_fields:
            value = getattr(self, field, None)
            if value is not None:
                body[field] = value

        # 반복 설정 추가
        if self.recurrence is not None:
            body["recurrence"] = self.recurrence.model_dump(exclude_none=True)

        return body


# ============================================================================
# Free/Busy (일정 가용성) 요청
# ============================================================================


class ScheduleRequest(BaseModel):
    """Free/Busy 일정 가용성 요청 (getSchedule API용)

    Attributes:
        schedules: 조회할 사용자 이메일 주소 목록
        startTime: 조회 시작 날짜/시간 (DateTimeTimeZone)
        endTime: 조회 종료 날짜/시간 (DateTimeTimeZone)
        availabilityViewInterval: 가용성 보기 간격 (분 단위, 5-1440분)
    """

    model_config = ConfigDict(extra="ignore")

    schedules: List[str] = Field(
        ...,
        description="조회할 사용자 이메일 주소 목록",
        examples=[["user1@example.com", "user2@example.com"]],
    )
    startTime: DateTimeTimeZone = Field(
        ...,
        description="조회 시작 날짜/시간",
    )
    endTime: DateTimeTimeZone = Field(
        ...,
        description="조회 종료 날짜/시간",
    )
    availabilityViewInterval: Optional[int] = Field(
        30,
        ge=5,
        le=1440,
        description="가용성 보기 간격 (분 단위, 5-1440분)",
    )

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()

    def to_graph_api_body(self) -> Dict[str, Any]:
        """Graph API 요청 본문으로 변환"""
        body = {
            "schedules": self.schedules,
            "startTime": self.startTime.model_dump(),
            "endTime": self.endTime.model_dump(),
        }
        if self.availabilityViewInterval is not None:
            body["availabilityViewInterval"] = self.availabilityViewInterval
        return body


class ScheduleItem(BaseModel):
    """스케줄 항목"""

    model_config = ConfigDict(extra="ignore")

    status: str = Field(..., description="상태 (free, busy, tentative, oof 등)")
    start: Optional[DateTimeTimeZone] = Field(None, description="시작 시간")
    end: Optional[DateTimeTimeZone] = Field(None, description="종료 시간")
    subject: Optional[str] = Field(None, description="제목")
    location: Optional[str] = Field(None, description="장소")
    isPrivate: Optional[bool] = Field(None, description="비공개 여부")

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()


class ScheduleInformation(BaseModel):
    """사용자 스케줄 정보"""

    model_config = ConfigDict(extra="ignore")

    scheduleId: str = Field(..., description="사용자 이메일")
    availabilityView: str = Field(
        ..., description="가용성 뷰 (0=free, 1=tentative, 2=busy, 3=oof, 4=workingElsewhere)"
    )
    scheduleItems: Optional[List[ScheduleItem]] = Field(None, description="스케줄 항목들")
    workingHours: Optional[Dict[str, Any]] = Field(None, description="근무 시간")
    error: Optional[Dict[str, Any]] = Field(None, description="에러 정보")

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()


# ============================================================================
# 쿼리 빌더 함수
# ============================================================================


def build_event_filter_query(params: Union[EventFilterParams, Dict]) -> str:
    """EventFilterParams를 Graph API $filter 쿼리 문자열로 변환

    Args:
        params: EventFilterParams 객체 또는 딕셔너리

    Returns:
        $filter 쿼리 문자열

    Field Mapping (snake_case -> Graph API):
        - start_date_time -> start/dateTime ge '...'
        - end_date_time -> end/dateTime le '...'
        - is_cancelled -> isCancelled
        - is_all_day -> isAllDay
        - show_as -> showAs
        - response_status -> responseStatus/response
        - is_online_meeting -> isOnlineMeeting
        - organizer_email -> organizer/emailAddress/address

    Examples:
        >>> params = EventFilterParams(
        ...     start_date_time="2024-12-01T00:00:00Z",
        ...     subject="회의",
        ...     importance="high"
        ... )
        >>> build_event_filter_query(params)
        "start/dateTime ge '2024-12-01T00:00:00Z' and contains(subject, '회의') and importance eq 'high'"
    """
    filters = []

    # Pydantic 모델이면 dict로 변환
    if isinstance(params, EventFilterParams):
        params_dict = params.model_dump(exclude_none=True)
    else:
        params_dict = params

    # 날짜/시간 범위
    if params_dict.get("start_date_time"):
        filters.append(f"start/dateTime ge '{params_dict['start_date_time']}'")
    if params_dict.get("end_date_time"):
        filters.append(f"end/dateTime le '{params_dict['end_date_time']}'")

    # 제목 검색
    if params_dict.get("subject"):
        subject = params_dict["subject"]
        if isinstance(subject, list):
            operator = params_dict.get("subject_operator", "or")
            subject_filters = [f"contains(subject, '{kw}')" for kw in subject]
            if subject_filters:
                if operator == "and":
                    filters.extend(subject_filters)
                else:  # or
                    filters.append(f"({' or '.join(subject_filters)})")
        else:
            filters.append(f"contains(subject, '{subject}')")

    # 주최자
    if params_dict.get("organizer_email"):
        filters.append(f"organizer/emailAddress/address eq '{params_dict['organizer_email']}'")

    # 이벤트 상태 (snake_case -> camelCase 매핑)
    if params_dict.get("is_cancelled") is not None:
        filters.append(f"isCancelled eq {str(params_dict['is_cancelled']).lower()}")
    if params_dict.get("is_all_day") is not None:
        filters.append(f"isAllDay eq {str(params_dict['is_all_day']).lower()}")
    if params_dict.get("is_online_meeting") is not None:
        filters.append(f"isOnlineMeeting eq {str(params_dict['is_online_meeting']).lower()}")

    # 속성 (snake_case -> camelCase 매핑)
    if params_dict.get("importance"):
        filters.append(f"importance eq '{params_dict['importance']}'")
    if params_dict.get("show_as"):
        filters.append(f"showAs eq '{params_dict['show_as']}'")
    if params_dict.get("response_status"):
        filters.append(f"responseStatus/response eq '{params_dict['response_status']}'")
    if params_dict.get("sensitivity"):
        filters.append(f"sensitivity eq '{params_dict['sensitivity']}'")

    # 카테고리
    if params_dict.get("categories"):
        for category in params_dict["categories"]:
            filters.append(f"categories/any(c:c eq '{category}')")

    return " and ".join(filters)


def build_event_select_query(params: Union[EventSelectParams, Dict, List[str]]) -> str:
    """EventSelectParams를 Graph API $select 쿼리 문자열로 변환

    Args:
        params: EventSelectParams 객체, bool 플래그가 있는 dict, 또는 필드명 리스트

    Returns:
        $select 쿼리 문자열 (예: "id,subject,start,end,location")

    Examples:
        >>> params = EventSelectParams(id=True, subject=True, start=True, end=True)
        >>> build_event_select_query(params)
        'id,subject,start,end'

        >>> build_event_select_query({'id': True, 'subject': True})
        'id,subject'

        >>> build_event_select_query(['id', 'subject', 'start'])
        'id,subject,start'
    """
    # EventSelectParams인 경우 get_selected_fields 사용
    if isinstance(params, EventSelectParams):
        selected_fields = params.get_selected_fields()
        return ",".join(selected_fields) if selected_fields else ""

    # 리스트인 경우 직접 반환
    if isinstance(params, list):
        return ",".join(params) if params else ""

    # Dict인 경우
    # 하위 호환성: {'fields': [...]} 형태 지원
    if "fields" in params and isinstance(params.get("fields"), list):
        return ",".join(params["fields"]) if params["fields"] else ""

    # Bool 플래그 처리
    selected = []
    for key, value in params.items():
        if value is True:
            selected.append(key)

    return ",".join(selected) if selected else ""


# ============================================================================
# 헬퍼 함수
# ============================================================================


def create_date_time_timezone(date_time: str, time_zone: str = "UTC") -> DateTimeTimeZone:
    """DateTimeTimeZone 객체를 생성하는 헬퍼 함수

    Args:
        date_time: 날짜/시간 문자열 (ISO 8601 형식)
        time_zone: 시간대 (기본값: UTC)

    Returns:
        DateTimeTimeZone 객체
    """
    return DateTimeTimeZone(dateTime=date_time, timeZone=time_zone)


def create_attendee(
    email: str, name: Optional[str] = None, attendee_type: str = "required"
) -> Attendee:
    """Attendee 객체를 생성하는 헬퍼 함수

    Args:
        email: 참석자 이메일 주소
        name: 참석자 이름 (선택)
        attendee_type: 참석자 유형 (required, optional, resource)

    Returns:
        Attendee 객체
    """
    email_address = EmailAddress(address=email, name=name)
    return Attendee(emailAddress=email_address, type=attendee_type)


def create_location(display_name: str, location_type: str = "default") -> Location:
    """Location 객체를 생성하는 헬퍼 함수

    Args:
        display_name: 장소 이름
        location_type: 장소 유형

    Returns:
        Location 객체
    """
    return Location(displayName=display_name, locationType=location_type)


def create_event_filter_params(**kwargs) -> EventFilterParams:
    """EventFilterParams 객체를 생성하는 헬퍼 함수"""
    return EventFilterParams(**kwargs)


def create_event_select_params(**kwargs) -> EventSelectParams:
    """EventSelectParams 객체를 생성하는 헬퍼 함수"""
    return EventSelectParams(**kwargs)


def create_event_create_params(
    subject: str,
    start_datetime: str,
    end_datetime: str,
    time_zone: str = "UTC",
    **kwargs,
) -> EventCreateParams:
    """EventCreateParams 객체를 생성하는 헬퍼 함수

    Args:
        subject: 이벤트 제목
        start_datetime: 시작 날짜/시간 (ISO 8601)
        end_datetime: 종료 날짜/시간 (ISO 8601)
        time_zone: 시간대 (기본값: UTC)
        **kwargs: 추가 파라미터

    Returns:
        EventCreateParams 객체
    """
    return EventCreateParams(
        subject=subject,
        start=DateTimeTimeZone(dateTime=start_datetime, timeZone=time_zone),
        end=DateTimeTimeZone(dateTime=end_datetime, timeZone=time_zone),
        **kwargs,
    )


def create_schedule_request(
    schedules: List[str],
    start_datetime: str,
    end_datetime: str,
    time_zone: str = "UTC",
    interval: int = 30,
) -> ScheduleRequest:
    """ScheduleRequest 객체를 생성하는 헬퍼 함수

    Args:
        schedules: 조회할 사용자 이메일 목록
        start_datetime: 시작 날짜/시간 (ISO 8601)
        end_datetime: 종료 날짜/시간 (ISO 8601)
        time_zone: 시간대 (기본값: UTC)
        interval: 가용성 보기 간격 (분, 기본값: 30)

    Returns:
        ScheduleRequest 객체
    """
    return ScheduleRequest(
        schedules=schedules,
        startTime=DateTimeTimeZone(dateTime=start_datetime, timeZone=time_zone),
        endTime=DateTimeTimeZone(dateTime=end_datetime, timeZone=time_zone),
        availabilityViewInterval=interval,
    )


# ============================================================================
# 기본 select 필드 (일정 목록 조회 시 사용)
# ============================================================================

DEFAULT_EVENT_SELECT_FIELDS = [
    "id",
    "subject",
    "start",
    "end",
    "location",
    "organizer",
    "attendees",
    "isAllDay",
    "isCancelled",
    "isOnlineMeeting",
    "onlineMeetingUrl",
    "showAs",
    "importance",
    "webLink",
    "categories",
    "hasAttachments",
    "recurrence",
    "seriesMasterId",
    "createdDateTime",
    "lastModifiedDateTime",
]


# ============================================================================
# 사용 예시
# ============================================================================


if __name__ == "__main__":
    # 예시 1: 이벤트 필터 파라미터
    filter_params = EventFilterParams(
        start_date_time="2024-12-01T00:00:00Z",
        end_date_time="2024-12-31T23:59:59Z",
        subject="회의",
        importance="high",
        is_online_meeting=True,
    )
    print("=== 이벤트 필터 파라미터 ===")
    print(f"Filter params: {filter_params.model_dump(exclude_none=True)}")
    print(f"Filter query: {build_event_filter_query(filter_params)}")

    # 예시 2: 선택 필드
    select_params = EventSelectParams(
        id=True,
        subject=True,
        start=True,
        end=True,
        location=True,
        attendees=True,
        isOnlineMeeting=True,
    )
    print("\n=== 선택 필드 ===")
    print(f"Selected fields: {select_params.get_selected_fields()}")
    print(f"Select query: {build_event_select_query(select_params)}")

    # 예시 3: 이벤트 생성 파라미터
    create_params = create_event_create_params(
        subject="프로젝트 회의",
        start_datetime="2024-12-15T10:00:00",
        end_datetime="2024-12-15T11:00:00",
        time_zone="Asia/Seoul",
        body="프로젝트 진행 상황 논의",
        isOnlineMeeting=True,
        importance="high",
    )
    print("\n=== 이벤트 생성 파라미터 ===")
    print(f"Create params: {create_params.model_dump(exclude_none=True)}")
    print(f"API body: {create_params.to_graph_api_body()}")

    # 예시 4: 참석자 추가
    attendee1 = create_attendee("user1@example.com", "홍길동", "required")
    attendee2 = create_attendee("user2@example.com", "김철수", "optional")
    print("\n=== 참석자 ===")
    print(f"Attendee 1: {attendee1.model_dump()}")
    print(f"Attendee 2: {attendee2.model_dump()}")

    # 예시 5: Free/Busy 요청
    schedule_req = create_schedule_request(
        schedules=["user1@example.com", "user2@example.com"],
        start_datetime="2024-12-15T08:00:00",
        end_datetime="2024-12-15T18:00:00",
        time_zone="Asia/Seoul",
        interval=30,
    )
    print("\n=== Free/Busy 요청 ===")
    print(f"Schedule request: {schedule_req.model_dump()}")
    print(f"API body: {schedule_req.to_graph_api_body()}")

    # 예시 6: TypedDict 호환성 테스트
    print("\n=== TypedDict 호환성 테스트 ===")
    print(f"filter_params.get('importance'): {filter_params.get('importance')}")
    print(f"filter_params['subject']: {filter_params['subject']}")
    print(f"filter_params.keys(): {list(filter_params.keys())}")

    # 예시 7: 장소 생성
    location = create_location("회의실 A", "conferenceRoom")
    print("\n=== 장소 ===")
    print(f"Location: {location.model_dump(exclude_none=True)}")
