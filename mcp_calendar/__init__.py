"""
MCP Calendar Module
Microsoft Graph API Calendar 기능 구현
"""

from .calendar_types import (
    DateTimeTimeZone,
    EmailAddress,
    ResponseStatus,
    Attendee,
    Location,
    ItemBody,
    RecurrencePattern,
    RecurrenceRange,
    PatternedRecurrence,
    EventFilterParams,
    EventSelectParams,
    EventCreateParams,
    EventUpdateParams,
    ScheduleRequest,
    ScheduleItem,
    ScheduleInformation,
    build_event_filter_query,
    build_event_select_query,
    create_date_time_timezone,
    create_attendee,
    create_location,
    create_event_filter_params,
    create_event_select_params,
    create_event_create_params,
    create_schedule_request,
)

from .graph_calendar_query import GraphCalendarQuery
from .graph_calendar_client import GraphCalendarClient
from .calendar_service import CalendarService

# `calendar_service` 는 서브모듈 이름이면서 기존 export(싱글톤 인스턴스) 이름이다. import 가
# 묶어 둔 서브모듈 바인딩을 풀어, 아래 `__getattr__` 가 mode 0 legacy 인스턴스를 지연 제공하게
# 한다(R15). 서브모듈 자체는 `importlib.import_module("mcp_calendar.calendar_service")` 로 얻는다.
# (`del` 대신 pop — `importlib.reload(mcp_calendar)` 때는 바인딩이 다시 생기지 않는다.)
globals().pop("calendar_service", None)

__all__ = [
    # Types
    "DateTimeTimeZone",
    "EmailAddress",
    "ResponseStatus",
    "Attendee",
    "Location",
    "ItemBody",
    "RecurrencePattern",
    "RecurrenceRange",
    "PatternedRecurrence",
    "EventFilterParams",
    "EventSelectParams",
    "EventCreateParams",
    "EventUpdateParams",
    "ScheduleRequest",
    "ScheduleItem",
    "ScheduleInformation",
    # Type helpers
    "build_event_filter_query",
    "build_event_select_query",
    "create_date_time_timezone",
    "create_attendee",
    "create_location",
    "create_event_filter_params",
    "create_event_select_params",
    "create_event_create_params",
    "create_schedule_request",
    # Query
    "GraphCalendarQuery",
    # Client
    "GraphCalendarClient",
    # Service
    "CalendarService",
]

# R15(2차) — 기존 `from mcp_calendar import *` 는 legacy 싱글톤 `calendar_service` 를 내보냈다.
# mode 0 에서만 이름을 `__all__` 에 넣는다(지연 속성이라 `import *` 가 그때 `__getattr__` 로 만든다).
# mode 1 은 넣지 않아 `import *` 가 아무것도 만들지 않는다 — 모드는 기동 시 고정이므로 import
# 시점 판정으로 충분하다.
from mcp_common.security_policy import multi_user_enabled as _multi_user_enabled

if not _multi_user_enabled():
    __all__.append("calendar_service")


def __getattr__(name: str):
    """mode 0 legacy 싱글톤 `calendar_service` 지연 제공 (mode 1 은 StartupConfigError)."""
    if name == "calendar_service":
        import importlib

        return getattr(importlib.import_module(f"{__name__}.calendar_service"), "calendar_service")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | {"calendar_service"})
