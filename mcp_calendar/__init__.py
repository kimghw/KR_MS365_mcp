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

from .graph_calendar_url import (
    CalendarFilterBuilder,
    GraphCalendarUrlBuilder,
    quick_event_filter,
    build_filter_query,
)

from .graph_calendar_query import GraphCalendarQuery
from .graph_calendar_client import GraphCalendarClient
from .calendar_service import CalendarService, calendar_service

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
    # URL builders
    "CalendarFilterBuilder",
    "GraphCalendarUrlBuilder",
    "quick_event_filter",
    "build_filter_query",
    # Query
    "GraphCalendarQuery",
    # Client
    "GraphCalendarClient",
    # Service
    "CalendarService",
    "calendar_service",
]
