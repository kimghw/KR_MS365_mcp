"""
Graph URL 경로 성분 인코딩 — 호출자 ID 가 경로 구조를 바꾸지 못하게 (spec/spec_멀티유저.md ②-7.5, G01).

호출자가 준 리소스 ID(event_id, chat_id, page_id, list_id, 드라이브 경로 등)를
`f"/me/events/{event_id}"` 처럼 그대로 끼우면, aiohttp 가 문자열 URL 을 `yarl.URL` 로 바꾸며
dot-segment(`..`)를 **정규화**한다. 그래서 `event_id="../../../users/B/events"` 는 실제로
`/v1.0/users/B/events` 로 나가고, 호출자 A 의 토큰으로 다른 사용자 경로를 친다.

규칙:
- 리소스 ID 하나 → `graph_segment()` — 단일 성분. `/`·`\\`·`?`·`#`·`%` 를 전부 인코딩하고,
  빈 값·`.`·`..`·제어문자는 거부한다(`urllib.parse.quote` 는 `.` 을 인코딩하지 않으므로
  dot-segment 는 따로 막아야 한다).
- OneDrive 처럼 슬래시가 의미 있는 경로 → `graph_drive_path()` — 성분마다 `graph_segment()`.
- 실패는 `SecurityError(NOT_FOUND)` — 경로 주입 시도에 대상 존재 여부를 알려주지 않는다.

Graph 오류 응답 본문은 호출자에게 그대로 돌려주지 않는다 — `graph_error_summary()` 로
상태 코드와 `error.code` 만 남긴다(②-9).
"""

import re
from typing import Any, Dict, Optional
from urllib.parse import quote, unquote

from mcp_common.security_contracts import ErrorCode, SecurityError

_INVALID_ID_MESSAGE = "잘못된 리소스 ID 입니다."
_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{0,63}$")


def _reject() -> SecurityError:
    return SecurityError(ErrorCode.NOT_FOUND, _INVALID_ID_MESSAGE)


def graph_segment(value: Any) -> str:
    """리소스 ID 를 URL 경로 **성분 하나**로 인코딩한다."""
    if value is None:
        raise _reject()
    text = str(value)
    if not text.strip() or any(ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise _reject()
    # 이미 인코딩된 값(`..%2F..`)도 디코딩해 보면 dot-segment 일 수 있다 — 둘 다 검사한다.
    for candidate in (text, unquote(text)):
        if candidate.strip() in (".", ".."):
            raise _reject()
    return quote(text, safe="")


def graph_drive_path(path: Any) -> str:
    """`folder/sub/file.txt` → 성분별 인코딩 후 `/` 로 결합. 빈 성분(앞뒤 `/`)은 버린다.

    `..`·`.` 성분, 백슬래시는 거부한다. 결과가 비면(루트) 빈 문자열.
    """
    if path is None:
        return ""
    text = str(path)
    if "\\" in text:
        raise _reject()
    parts = [p for p in text.split("/") if p != ""]
    return "/".join(graph_segment(p) for p in parts)


def graph_error_summary(status: Optional[int], body: Any = None) -> Dict[str, Any]:
    """Graph 오류를 공개 가능한 최소 정보로 줄인다: HTTP 상태 + `error.code` (형식 검사 통과 시)."""
    summary: Dict[str, Any] = {}
    if isinstance(status, int):
        summary["status_code"] = status
    code = None
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            code = err.get("code")
        elif isinstance(err, str):
            code = err
    if isinstance(code, str) and _CODE_RE.match(code):
        summary["graph_error_code"] = code
    return summary


__all__ = ["graph_segment", "graph_drive_path", "graph_error_summary"]
