"""calendarView 쿼리: 오프셋 기본값(+09:00)과 `+` 퍼센트 인코딩 검증."""

from mcp_calendar.graph_calendar_query import GraphCalendarUrlBuilder, _with_offset


def test_offset_is_added_only_when_missing():
    assert _with_offset("2024-01-01T00:00:00") == "2024-01-01T00:00:00+09:00"
    assert _with_offset("2024-01-01T00:00:00Z") == "2024-01-01T00:00:00Z"
    assert _with_offset("2024-01-01T00:00:00-08:00") == "2024-01-01T00:00:00-08:00"


def test_plus_in_offset_is_percent_encoded():
    url = GraphCalendarUrlBuilder("u@x").build_calendar_view_url("2024-01-01T00:00:00+09:00", "2024-01-02T00:00:00")
    query = url.split("?", 1)[1]
    assert "startDateTime=2024-01-01T00%3A00%3A00%2B09%3A00" in query
    assert "endDateTime=2024-01-02T00%3A00%3A00%2B09%3A00" in query
    assert "+" not in query
