"""Time Service — 현재 시간을 다양한 형식으로 반환."""
from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # Python < 3.9


_WEEKDAY_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]


class TimeService:
    """현재 시간/날짜 반환 Facade."""

    DEFAULT_TIMEZONE = "Asia/Seoul"

    async def initialize(self) -> bool:
        return True

    async def close(self):
        pass

    def _resolve_tz(self, tz_name: Optional[str]):
        name = tz_name or self.DEFAULT_TIMEZONE
        if ZoneInfo is None:
            return dt_timezone.utc, "UTC"
        try:
            return ZoneInfo(name), name
        except Exception:
            return ZoneInfo("UTC"), "UTC"

    async def get_current_time(self, timezone: Optional[str] = None) -> Dict[str, Any]:
        """입력은 무시하고 현재 시간을 반환. timezone은 선택 (기본 Asia/Seoul)."""
        tz, tz_name = self._resolve_tz(timezone)
        now = datetime.now(tz)
        return {
            "iso": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "weekday": now.strftime("%A"),
            "weekday_kr": _WEEKDAY_KR[now.weekday()],
            "timezone": tz_name,
            "utc_offset": now.strftime("%z"),
            "unix": int(now.timestamp()),
            "year": now.year,
            "month": now.month,
            "day": now.day,
            "hour": now.hour,
            "minute": now.minute,
            "second": now.second,
        }
