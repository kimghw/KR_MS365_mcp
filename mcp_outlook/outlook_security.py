"""
Outlook 보안 관문 — Graph URL 정책·토큰 획득·공개 오류 (spec/spec_멀티유저.md ②-7.5, WP4).

토큰을 붙여 보내는 요청과, `mail_query_url` 처럼 호출자가 URL 을 직접 주는 경로의
검사·경로 인코딩·토큰 획득을 이 모듈 한 곳에 둔다. Graph 클라이언트(`graph_mail_*`,
`mail_attachment*`)는 여기의 함수만 쓴다.

| 검사 | mode 0 | mode 1 |
|------|:------:|:------:|
| https + `graph.microsoft.com` 호스트, userinfo·비표준 포트·역슬래시 거부 | ○ | ○ |
| `mail_query_url`·페이지 URL: method=GET, path=`/v1.0/me/<메일 리소스>...` 또는 `/v1.0/users/{본인 oid 또는 본인 연결 이메일}/<메일 리소스>...` | — | ○ |
| Authorization 을 단 요청은 redirect 를 따라가지 않는다 (`BEARER_KW`) | ○ | ○ |
| 사전 서명 URL(OneDrive 업로드 세션 등)은 공용 `check_presigned_url` (공개 호스트·DNS 검사), Graph bearer 미부착, 3xx 는 오류 | ○ | ○ |
| 토큰은 **요청 1건 직전에** 새로 얻는다(`request_headers`) — await·재시도·청크 경계를 넘겨 재사용하지 않는다 (N01) | ○ | ○ |
| message_id·attachment_id·사용자 경로 성분 인코딩 (`seg`, `user_seg`) | ○ | ○ |

메일 리소스 = `messages`, `mailFolders` (OData 키 표기 `messages('id')` 포함, 대소문자 무시).

## 오류 코드 선택

URL 정책 위반은 전부 `SecurityError(PATH_NOT_ALLOWED)` 다. 다른 사용자 식별자
(`/users/other@x/...`)로 바꾼 URL 도 **같은 코드**로 거부한다 — 상대 계정을 조회하지 않고
입력 문자열만으로 판정하므로 `not_found` 로 숨겨야 할 존재 정보가 애초에 생기지 않고,
호출자에게는 "이 URL 형태는 허용되지 않는다"가 정확한 안내다. 판정은 토큰 획득·HTTP
세션 생성보다 먼저 일어난다(토큰이 나가지 않는다).

mode 0 은 기존 계약을 유지한다 — 호스트 검사만 하고, 실패는 `{"status": "error"}` dict 로
돌려준다(호출 측 코드가 처리).
"""

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Sized
from urllib.parse import quote, unquote

from mcp_common.errors import ToolExecutionError
from mcp_common.graph_paths import graph_error_summary
from mcp_common.graph_url_policy import check_presigned_url, is_redirect
from mcp_common.principal import normalize_email_for_compare, require_principal
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.security_policy import multi_user_enabled

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# 입력 한도 (astra 리뷰 R02, 2026-10-23) — param_spec 의 maximum/maxItems 와 같은 값.
# 스키마 검증과 무관하게 도메인 경계(MailService·GraphMailQuery·배치·첨부)에서 다시 거부한다.
# ----------------------------------------------------------------------
MAX_TOP = 1000               # 한 번에 조회할 메일 수 (150개 × 7페이지)
MAX_MESSAGE_IDS = 500        # message_ids / message_attachment_ids 원소 수
MAX_RECIPIENTS = 500         # to/cc/bcc 합계
MAX_SEND_ATTACHMENTS = 20    # 발송·임시저장 첨부 파일 수

# 바이트·시간 예산 (astra 2차 N08). 모듈 속성으로 읽는다 — 테스트가 monkeypatch 할 수 있게.
MAX_SEND_ATTACHMENT_BYTES = 3 * 1024 * 1024          # 발송 첨부 1건 (Graph 직접 첨부 한도)
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024              # 수신 첨부 1건 decode 상한
MAX_REQUEST_ATTACHMENT_BYTES = 200 * 1024 * 1024     # 요청 1건의 decode 누적 상한
CONVERSION_TIMEOUT_SECONDS = 60.0                    # 첨부 → TXT 변환 1건 deadline (worker thread)
MAX_CONVERSION_WORKERS = 4                           # 사용자별 동시 converter 스레드 (P01, 프로세스 전역 슬롯)
CONVERSION_SLOT_TIMEOUT_SECONDS = 5.0                # 슬롯 대기 상한 — 넘기면 overloaded
MAX_USER_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024     # mode 1 사용자 누적 저장 quota (사용자 files/ 전체)

GRAPH_HOST = "graph.microsoft.com"
GRAPH_BASE = f"https://{GRAPH_HOST}/v1.0"

#: Authorization 헤더를 단 aiohttp 요청에 항상 넘기는 키워드 — redirect 로 토큰이 새지 않게.
BEARER_KW: Dict[str, Any] = {"allow_redirects": False}

# beta 는 받지 않는다 (N05) — 내부에서 쓰는 reportMessage $batch 는 호출자 URL 이 아니다.
_VERSIONS = frozenset({"v1.0"})
_MAIL_RESOURCE = re.compile(r"^(messages|mailfolders)(\(.*\))?$", re.IGNORECASE)


# ----------------------------------------------------------------------
# 경로 성분 인코딩
# ----------------------------------------------------------------------
def seg(value: Any) -> str:
    """URL 경로 성분 하나. `/`·`..`·`?`·`#` 를 인코딩해 경로 주입을 막는다."""
    return quote(str(value), safe="")


def user_seg(email: Any) -> str:
    """`/users/{email}` 성분. 일반 이메일은 그대로(`@` 유지), 그 밖의 구분자만 인코딩."""
    return quote(str(email), safe="@")


def bearer_headers(token: str, content_type: Optional[str] = "application/json") -> Dict[str, str]:
    """요청마다 새로 만든다 — 객체에 보관하지 않는다."""
    headers = {"Authorization": f"Bearer {token}"}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


#: 사전 서명 URL(업로드 세션 등)로 보내는 요청의 키워드 — bearer 없음·redirect 미추종.
PRESIGNED_KW: Dict[str, Any] = {"allow_redirects": False}


# ----------------------------------------------------------------------
# URL 검사
# ----------------------------------------------------------------------
def _parse(url: Any):
    import yarl  # aiohttp 가 쓰는 파서와 같은 해석으로 판정한다

    if not isinstance(url, str) or not url or "\\" in url or any(ord(c) < 0x20 for c in url):
        return None
    try:
        parsed = yarl.URL(url)
    except (ValueError, TypeError):
        return None
    if not parsed.is_absolute():
        return None
    return parsed


def is_graph_https(url: Any) -> bool:
    """https + Graph 호스트 + userinfo 없음 + 기본 포트."""
    parsed = _parse(url)
    if parsed is None:
        return False
    return (
        parsed.scheme == "https"
        and (parsed.host or "").lower() == GRAPH_HOST
        and parsed.user is None
        and parsed.password is None
        and parsed.port in (None, 443)
    )


def check_upload_url(url: Any) -> str:
    """Graph 가 준 사전 서명 업로드·다운로드 URL — 공용 정책(`check_presigned_url`) 그대로 (N05).

    https·userinfo 없음·기본 포트·사설/loopback/link-local 호스트 거부·DNS 해석 결과까지 공개
    대역이어야 한다. 위반은 `SecurityError(PATH_NOT_ALLOWED)`. 이 URL 에는 Graph bearer 를 붙이지
    않고(`PRESIGNED_KW`) 3xx 응답은 오류로 본다(`is_redirect`).
    """
    return check_presigned_url(url)


def _deny() -> None:
    raise SecurityError(ErrorCode.PATH_NOT_ALLOWED, "허용되지 않은 Graph URL 입니다. 본인 메일함(/me 또는 본인 /users/{id})의 메일 리소스만 조회할 수 있습니다.")


def _is_own_user_segment(value: str, principal) -> bool:
    if "@" in value:
        return bool(principal.graph_email) and (
            normalize_email_for_compare(value) == normalize_email_for_compare(principal.graph_email)
        )
    try:
        return str(uuid.UUID(value)).lower() == str(uuid.UUID(principal.object_id)).lower()
    except (ValueError, TypeError, AttributeError):
        return False


def check_mail_query_url(url: Any, method: str = "GET") -> None:
    """mode 1 `mail_query_url` 정책. 위반이면 `SecurityError(PATH_NOT_ALLOWED)`.

    판정은 aiohttp 와 같은 파서(yarl)가 정규화한 경로로 한다 — `..` 는 이미 접혀 있고,
    인코딩된 `%2F`·`%2E%2E` 는 성분 단위로 풀어서 다시 거부한다.
    """
    if str(method).upper() != "GET" or not is_graph_https(url):
        _deny()
    principal = require_principal()
    parsed = _parse(url)
    segments = [unquote(s) for s in parsed.raw_parts[1:]]  # 첫 원소는 "/"
    for part in segments[:-1]:
        if part == "":
            _deny()
    for part in segments:
        if part in (".", "..") or "/" in part or "\\" in part or any(ord(c) < 0x20 for c in part):
            _deny()
    if len(segments) < 3 or segments[0].lower() not in _VERSIONS:
        _deny()
    owner = segments[1].lower()
    if owner == "me":
        resource_index = 2
    elif owner == "users":
        if len(segments) < 4 or not _is_own_user_segment(segments[2], principal):
            _deny()
        resource_index = 3
    else:
        _deny()
    if not _MAIL_RESOURCE.match(segments[resource_index]):
        _deny()


def enforce_mail_query_url(url: Any) -> None:
    """mode 1 에서만 경로 정책을 적용한다 (mode 0 은 호스트 검사만 — 호출 측)."""
    if multi_user_enabled():
        check_mail_query_url(url)


# ----------------------------------------------------------------------
# 토큰
# ----------------------------------------------------------------------
def legacy_token_provider() -> Any:
    """mode 0 전용 공유 AuthManager. mode 1 에서는 주입이 누락된 배선 오류다."""
    if multi_user_enabled():
        raise RuntimeError("멀티유저 모드에서는 token_provider 를 주입해야 합니다 (공유 AuthManager 금지)")
    from mcp_common.auth import get_shared_auth_manager

    return get_shared_auth_manager()


async def request_headers(
    provider: Any, user_email: Optional[str], content_type: Optional[str] = "application/json"
) -> Dict[str, str]:
    """Graph 요청 1건 직전에 토큰을 **새로** 얻어 헤더를 만든다 (astra 2차 N01).

    공급자(`get_graph_token`)가 매 호출 현재 요청 identity·계정 상태·auth_epoch 를 재검사하므로,
    폐기 뒤의 후속 변경 요청은 여기서 `account_inactive` 등으로 끊긴다. 토큰 문자열을 변수에
    들고 await 를 넘기지 않는다.
    """
    token = await acquire_token(provider, user_email)
    if not token:
        raise SecurityError(ErrorCode.GRAPH_NOT_CONNECTED)
    return bearer_headers(token, content_type)


async def acquire_token(provider: Any, user_email: Optional[str]) -> Optional[str]:
    """요청 1건에 쓸 access token. 보관하지 않는다.

    - `SecurityError`(graph_not_connected·identity_mismatch 등)는 그대로 올린다 —
      런타임이 연결 안내를 붙인다(②-12 4항).
    - mode 1 에서 토큰이 없으면 `graph_not_connected`, 그 밖의 예외는 `internal_error`.
    - mode 0 은 기존대로 None 을 돌려준다(호출 측이 오류 dict·인증 URL 로 처리).
    """
    try:
        token = await provider.validate_and_refresh_token(user_email)
    except SecurityError:
        raise
    except Exception as exc:
        logger.warning("token acquisition failed: %s", type(exc).__name__)
        if multi_user_enabled():
            raise SecurityError(ErrorCode.INTERNAL_ERROR) from None
        return None
    if not token:
        if multi_user_enabled():
            raise SecurityError(ErrorCode.GRAPH_NOT_CONNECTED)
        logger.warning("token acquisition returned no token")
        return None
    return token


# ----------------------------------------------------------------------
# 입력 한도 검사
# ----------------------------------------------------------------------
def _invalid_argument(name: str, message: str, **details: Any) -> ToolExecutionError:
    payload: Dict[str, Any] = {"status": "error", "error": "invalid_argument", "message": message, "argument": name}
    payload.update(details)
    return ToolExecutionError(payload)


def check_top(value: Any, *, cap: int = MAX_TOP, name: str = "top") -> int:
    """`top` 류 정수 인자: 1 이상 `cap` 이하의 정수만. 위반은 `invalid_argument` 오류.

    스키마 `maximum` 과 별개로 **코루틴·요청을 만들기 전에** 막는다 (R02 defence in depth).
    """
    if isinstance(value, bool):
        raise _invalid_argument(name, f"{name} 은 정수여야 합니다.")
    if not isinstance(value, int):
        try:
            value = int(str(value).strip())
        except (TypeError, ValueError):
            raise _invalid_argument(name, f"{name} 은 정수여야 합니다.") from None
    if value < 1 or value > cap:
        raise _invalid_argument(name, f"{name} 은 1 이상 {cap} 이하여야 합니다.", maximum=cap, minimum=1)
    return value


def check_list_size(items: Any, name: str, cap: int = MAX_MESSAGE_IDS) -> None:
    """리스트 인자의 원소 수 상한. None·빈 값은 통과(호출 측이 처리)."""
    if items is None:
        return
    if not isinstance(items, Sized):
        raise _invalid_argument(name, f"{name} 은 목록이어야 합니다.")
    if len(items) > cap:
        raise _invalid_argument(name, f"{name} 은 최대 {cap}개까지 지정할 수 있습니다.", maximum=cap)


def quota_exceeded(limit: int) -> ToolExecutionError:
    """mode 1 사용자 누적 저장 quota 초과 (N08). 재시도로 풀리지 않으므로 overloaded 가 아니다."""
    return ToolExecutionError(
        {
            "status": "error",
            "error": "quota_exceeded",
            "message": "사용자 다운로드 저장 한도를 초과했습니다. 기존 파일을 정리한 뒤 다시 시도하세요.",
            "limit_bytes": limit,
        }
    )


class AttachmentLimitExceeded(ValueError):
    """첨부 1건·요청 예산·응답 크기 한도 초과 (N08). `code` 가 응답의 오류 코드가 된다."""

    def __init__(self, code: str, limit: int):
        self.code = code
        self.limit = int(limit)
        super().__init__(code)


def response_too_large(response: Any, limit_bytes: int) -> bool:
    """`Content-Length` 가 있으면 본문을 읽기 전에 한도를 판정한다 (N08 gap 3).

    Graph 는 보통 chunked 로 보내 헤더가 없다 — 그때는 판정할 수 없고 `.json()` 이 본문 전체를
    읽은 뒤에야 decode 예산이 적용된다. 그 한계는 호출 모듈 docstring 에 적어 둔다.
    """
    try:
        raw = response.headers.get("Content-Length")
    except AttributeError:
        return False
    if raw is None:
        return False
    try:
        return int(raw) > int(limit_bytes)
    except (TypeError, ValueError):
        return False


class ByteBudget:
    """요청 1건의 decode 바이트 예산 (N08). `take()` 가 False 면 그 항목을 건너뛴다."""

    def __init__(self, limit: int):
        self.limit = int(limit)
        self.used = 0

    def take(self, size: int) -> bool:
        if size < 0 or self.used + size > self.limit:
            return False
        self.used += size
        return True


def base64_decoded_size(encoded: Any) -> int:
    """base64 문자열의 decode 결과 크기 상한 추정 — decode 전에 거부하기 위한 값."""
    return (len(encoded) * 3) // 4 if isinstance(encoded, (str, bytes)) else 0


def read_limited(fh: Any, limit: int, *, what: str = "파일") -> bytes:
    """handle 에서 최대 `limit`+1 바이트만 읽어, 한도를 넘으면 전체를 읽지 않고 거부한다 (N08)."""
    data = fh.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{what}이 {limit // (1024 * 1024)}MB 초과 (직접 첨부 한도)")
    return data


# ----------------------------------------------------------------------
# 공개 오류
# ----------------------------------------------------------------------
class GraphRequestError(Exception):
    """Graph 요청 실패. 공개 가능한 요약(상태 코드·오류 코드)만 담고 본문은 버린다."""

    def __init__(self, status: Optional[int], body: Any = None, *, what: str = "request"):
        self.summary = graph_error_entry(status, body)
        self.what = what
        super().__init__(f"{what} failed: {errors_text([self.summary])}")


def _parse_body(body: Any) -> Any:
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", errors="replace")
    if isinstance(body, str):
        try:
            return json.loads(body)
        except ValueError:
            return None
    return body


def graph_error_entry(status: Any, body: Any = None, **extra: Any) -> Dict[str, Any]:
    """부분 성공 응답의 오류 항목 (R06). HTTP 상태 + 검증된 `error.code` 만 — 원문 메시지 없음."""
    status_code = status if isinstance(status, int) and not isinstance(status, bool) else None
    entry = dict(extra)
    entry.update(graph_error_summary(status_code, _parse_body(body)))
    entry.setdefault("status_code", status_code)
    return entry


def errors_text(errors: List[Any]) -> str:
    """오류 항목 목록을 응답용 한 줄 요약으로 (dict 항목은 요약 필드만)."""
    parts = []
    for item in errors or []:
        if isinstance(item, dict):
            bits = []
            for key in ("message_id", "mail_id", "attachment_id", "batch", "page"):
                if item.get(key) is not None:
                    bits.append(f"{key}={str(item[key])[:24]}")
            if item.get("status_code") is not None:
                bits.append(f"HTTP {item['status_code']}")
            if item.get("graph_error_code"):
                bits.append(str(item["graph_error_code"]))
            if item.get("error"):
                bits.append(str(item["error"]))
            parts.append(" ".join(bits) or "error")
        else:
            parts.append(str(item))
    return "; ".join(parts)


def graph_error_code(body: Any) -> str:
    """Graph 오류 본문에서 `error.code` 만. 없으면 빈 문자열."""
    try:
        data = json.loads(body) if isinstance(body, (str, bytes)) else body
        code = (data or {}).get("error", {}).get("code")
        return str(code) if code else ""
    except (ValueError, AttributeError, TypeError):
        return ""


def graph_error_detail(body: Any, limit: int = 200) -> str:
    """응답에 싣는 Graph 오류 상세. mode 0 은 본문 앞부분(기존), mode 1 은 오류 코드만."""
    if multi_user_enabled():
        return graph_error_code(body) or "graph_error"
    text = body if isinstance(body, str) else str(body)
    return text[:limit]


def public_error(exc: BaseException) -> str:
    """응답에 싣는 예외 문자열. mode 1 은 경로·외부 원문이 섞일 수 있는 예외를 이름만."""
    if isinstance(exc, GraphRequestError):
        return str(exc)
    if isinstance(exc, SecurityError):
        return exc.public_message
    if isinstance(exc, ToolExecutionError):
        payload = exc.payload
        return str(payload.get("message", payload) if isinstance(payload, dict) else payload)[:300]
    if not multi_user_enabled():
        return str(exc)
    if isinstance(exc, ValueError):  # 이 패키지가 공개용 문구로 올리는 검증 오류
        return str(exc)[:300]
    return type(exc).__name__


__all__ = [
    "GRAPH_HOST",
    "GRAPH_BASE",
    "BEARER_KW",
    "PRESIGNED_KW",
    "seg",
    "user_seg",
    "bearer_headers",
    "request_headers",
    "is_graph_https",
    "check_upload_url",
    "is_redirect",
    "check_mail_query_url",
    "enforce_mail_query_url",
    "legacy_token_provider",
    "acquire_token",
    "MAX_SEND_ATTACHMENT_BYTES",
    "MAX_ATTACHMENT_BYTES",
    "MAX_REQUEST_ATTACHMENT_BYTES",
    "CONVERSION_TIMEOUT_SECONDS",
    "MAX_USER_DOWNLOAD_BYTES",
    "MAX_CONVERSION_WORKERS",
    "CONVERSION_SLOT_TIMEOUT_SECONDS",
    "quota_exceeded",
    "AttachmentLimitExceeded",
    "response_too_large",
    "ByteBudget",
    "base64_decoded_size",
    "read_limited",
    "MAX_TOP",
    "MAX_MESSAGE_IDS",
    "MAX_RECIPIENTS",
    "MAX_SEND_ATTACHMENTS",
    "check_top",
    "check_list_size",
    "GraphRequestError",
    "graph_error_entry",
    "errors_text",
    "graph_error_code",
    "graph_error_detail",
    "public_error",
]
