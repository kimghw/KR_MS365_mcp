"""시간대 해석: 기본 Asia/Seoul 이 풀리고, 모르는 이름은 tzdata 없이도 UTC 로 떨어지는지."""

from datetime import timezone

from mcp_time.time_service import TimeService


async def test_default_zone_resolves_on_windows_too():
    assert (await TimeService().get_current_time())["timezone"] == "Asia/Seoul"


def test_unknown_zone_falls_back_to_fixed_utc():
    tz, name = TimeService()._resolve_tz("Not/AZone")
    assert tz is timezone.utc
    assert name == "UTC"
