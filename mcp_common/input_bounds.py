"""
입력 한도 검사 — 결과 수·목록 길이 상한 (spec/reviews/멀티유저_astra_2차_2026-10-23.md R02).

Calendar·Todo·OneDrive 가 각자 사본으로 갖던 것을 여기로 올렸다(2026-10-23). Outlook
(`outlook_security.check_top/check_list_size`)·OneNote(`onenote_types.check_top`)·Teams
(`teams_types.check_limit/check_list_size`)도 같은 의미·같은 페이로드다 — 새 도메인은 이 모듈을 쓴다.

스키마의 `minimum`/`maximum`/`maxItems` 는 MCP 입력만 막는다. 서비스 함수는 Python 에서 직접
불리기도 하므로 **Graph 요청·코루틴을 만들기 전에** 여기서 한 번 더 막는다(defence in depth).
위반은 `ToolExecutionError({"status": "error", "error": "invalid_argument", ...})` — 런타임이
`isError` 로 내보낸다.
"""

from typing import Any, Dict, Sized

from mcp_common.errors import ToolExecutionError

#: `top`/`limit` 류 결과 수 상한. YAML `maximum` 과 같은 값이어야 한다.
MAX_TOP = 1000


def _invalid_argument(name: str, message: str, **details: Any) -> ToolExecutionError:
    payload: Dict[str, Any] = {
        "status": "error",
        "error": "invalid_argument",
        "message": message,
        "argument": name,
    }
    payload.update(details)
    return ToolExecutionError(payload)


def check_top(value: Any, *, cap: int = MAX_TOP, name: str = "top") -> int:
    """`top`/`limit` 류 정수 인자: 1 이상 `cap` 이하의 정수만. 위반은 `invalid_argument`."""
    if isinstance(value, bool):
        raise _invalid_argument(name, f"{name} 은 정수여야 합니다.")
    if not isinstance(value, int):
        try:
            value = int(str(value).strip())
        except (TypeError, ValueError):
            raise _invalid_argument(name, f"{name} 은 정수여야 합니다.") from None
    if value < 1 or value > cap:
        raise _invalid_argument(
            name, f"{name} 은 1 이상 {cap} 이하여야 합니다.", minimum=1, maximum=cap
        )
    return value


def check_list_size(items: Any, name: str, cap: int) -> None:
    """리스트 인자의 원소 수 상한. None 은 통과(호출 측이 처리)."""
    if items is None:
        return
    if not isinstance(items, Sized) or isinstance(items, (str, bytes)):
        raise _invalid_argument(name, f"{name} 은 목록이어야 합니다.")
    if len(items) > cap:
        raise _invalid_argument(name, f"{name} 은 최대 {cap}개까지 지정할 수 있습니다.", maximum=cap)


__all__ = ["MAX_TOP", "check_top", "check_list_size"]
