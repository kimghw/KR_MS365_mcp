"""
로그 민감정보 마스킹 필터 (spec/spec_멀티유저.md ②-9, WP10).

`install_redaction()` 이 root 로거의 핸들러들과 uvicorn·aiohttp·httpx 로거에
`RedactionFilter` 를 붙인다(여러 번 불러도 한 번만 붙는다). 가리는 것:

| 대상 | 예 | 결과 |
|------|----|------|
| bearer key | `m365v1.<kid>.<secret>` | `m365v1.<kid>.[REDACTED]` (kid 는 감사 credential_id 와 같은 값이라 남긴다) |
| JWT 형태 토큰·그 prefix | `eyJhbGciOi...` | `[REDACTED_JWT]` |
| `Bearer <token>` | `Bearer abc...` | `Bearer [REDACTED]` |
| Authorization·Cookie 헤더 값 | `'Authorization': 'Basic ...'` | 값만 `[REDACTED]` |
| OAuth query/form 값 | `code=`·`state=`·`code_verifier=`·`refresh_token=`·`access_token=` … | `code=[REDACTED]` |
| JSON 의 토큰 키 | `"refresh_token": "..."` | 값만 `[REDACTED]` |
| 200자 이상 연속 토큰 문자열 | 불투명 access/refresh token | `[REDACTED_LONG]` |
| 이메일 (mode 1) | `alice@contoso.com`, `alice%40contoso.com` | `***@contoso.com` |
| access log query string | uvicorn·aiohttp `GET /auth/callback?code=...` | `GET /auth/callback` (mode 1 에서는 httpx 요청 URL 도) |

uvicorn 의 `AccessFormatter` 는 `record.args` 를 5-튜플로 풀어 쓰므로 access 로거는 메시지로
합치지 않고 **인자별로** 정화한다. 그 밖의 레코드는 `getMessage()` 결과를 정화해 바뀐 경우에만
`msg` 를 교체하고 `args` 를 비운다. 예외 traceback(`exc_text`)·`stack_info` 도 정화한다.
정화 중 오류가 나면 원문 대신 고정 문구를 내보낸다(fail closed).

## 한계 (정직하게 — ②-9)

이 필터는 **심층 방어**일 뿐 보장이 아니다. `print()`·`sys.stderr.write()`·하위 프로세스
출력·필터가 붙기 전에 만들어진 핸들러·형식이 다른 비밀(짧은 불투명 토큰, 메일 제목·본문,
파일 경로)은 걸러지지 않는다. 비밀을 로그 호출에 **넣지 않는 것**이 1차 방어이고, 각 WP 는
자기 로그 호출을 직접 고친다. 핸들러를 나중에 더 붙였다면 `install_redaction()` 을 다시 부른다.
"""

import logging
import re
from typing import Any, Iterable, Optional

REDACTED = "[REDACTED]"

#: access log — query string 을 항상 지운다.
ACCESS_LOGGERS = frozenset({"uvicorn.access", "aiohttp.access"})
#: 외부 요청 URL 을 남기는 로거 — mode 1 에서 query string 을 지운다.
URL_LOGGERS = frozenset({"httpx", "httpcore", "aiohttp.client", "urllib3.connectionpool"})
#: `install_redaction()` 이 로거 자체에 필터를 붙이는 대상. 자체 핸들러를 갖고
#: `propagate=False` 인 로거(uvicorn 이 dictConfig 로 만든다)는 root 핸들러 필터를 타지 않는다.
#: 로거 수준 필터는 uvicorn 의 dictConfig 이후에도 남는다(핸들러만 교체된다).
DEFAULT_LOGGERS = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "aiohttp.access",
    "aiohttp.server",
    "aiohttp.web",
    "aiohttp.client",
    "httpx",
    "httpcore",
    "mcp",
)

_SECRET_KEYS = (
    "access_token|refresh_token|id_token|client_secret|client_assertion|code_verifier|"
    "password|passwd|secret|token|ticket|nonce|api_key|apikey|authorization|cookie|bearer"
)

#: Authorization 류 — `scheme token` 까지만 가린다 (줄 나머지는 남긴다).
_AUTH_HEADER_RE = re.compile(
    r"(?i)(\b(?:proxy-)?authorization|\bx-api-key)"
    r"(\s*[\"']?\s*[:=]\s*[\"']?)((?:[A-Za-z][A-Za-z0-9_-]*[ \t]+)?[^\s\"',;]+)"
)
#: Cookie 류 — 값에 `; ` 가 들어가므로 따옴표·줄끝까지 가린다.
_COOKIE_HEADER_RE = re.compile(
    r"(?i)(\bset-cookie|\bcookie)(\s*[\"']?\s*[:=]\s*[\"']?)([^\"'\r\n]+)"
)
_BEARER_KEY_RE = re.compile(r"\bm365v1\.([A-Za-z0-9_-]*)(?:\.[A-Za-z0-9_-]*)?")
_BEARER_RE = re.compile(r"(?i)\b(bearer)(\s+)(?!m365v1\.)(?!\[REDACTED)[A-Za-z0-9._~+/=-]{6,}")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_-]*){0,2}")
_JSON_KEY_RE = re.compile(
    r"(?i)([\"'](?:" + _SECRET_KEYS + r")[\"']\s*:\s*)([\"'])(.*?)(?<!\\)\2"
)
_PARAM_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(code|state|session_state|code_verifier|code_challenge|"
    + _SECRET_KEYS
    + r")=([^&\s\"'#,;<>]+)"
)
_LONG_TOKEN_RE = re.compile(r"[A-Za-z0-9+_\-.!*~$]{200,}={0,2}")
_QUERY_RE = re.compile(r"\?[^\s\"'<>]*")
_EMAIL_RE = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
_EMAIL_ENC_RE = re.compile(r"(?<![A-Za-z0-9._+-])[A-Za-z0-9._+-]+%40([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)", re.I)
_KID_RE = re.compile(r"^[0-9a-f]{32}$")


def _bearer_key_sub(match: "re.Match[str]") -> str:
    kid = match.group(1)
    if _KID_RE.match(kid):
        return f"m365v1.{kid}.{REDACTED}"
    return f"m365v1.{REDACTED}"


def redact_text(text: str, *, mask_emails: bool = False, strip_query: bool = False) -> str:
    """문자열 하나를 정화한다. 로그 외 출력(CLI 등)에도 쓸 수 있다."""
    if not text:
        return text
    out = _AUTH_HEADER_RE.sub(lambda m: m.group(1) + m.group(2) + REDACTED, text)
    out = _COOKIE_HEADER_RE.sub(lambda m: m.group(1) + m.group(2) + REDACTED, out)
    out = _BEARER_KEY_RE.sub(_bearer_key_sub, out)
    out = _BEARER_RE.sub(lambda m: m.group(1) + m.group(2) + REDACTED, out)
    out = _JWT_RE.sub("[REDACTED_JWT]", out)
    out = _JSON_KEY_RE.sub(lambda m: m.group(1) + m.group(2) + REDACTED + m.group(2), out)
    out = _PARAM_RE.sub(lambda m: m.group(1) + "=" + REDACTED, out)
    out = _LONG_TOKEN_RE.sub("[REDACTED_LONG]", out)
    if strip_query:
        out = _QUERY_RE.sub("", out)
    if mask_emails:
        out = _EMAIL_RE.sub(lambda m: "***@" + m.group(1), out)
        out = _EMAIL_ENC_RE.sub(lambda m: "***%40" + m.group(1), out)
    return out


def _multi_user() -> bool:
    try:
        from mcp_common.security_policy import multi_user_enabled

        return multi_user_enabled()
    except Exception:
        return True  # 정책을 읽을 수 없으면 엄격하게


class RedactionFilter(logging.Filter):
    """민감정보를 가리는 필터. 레코드를 버리지 않는다(항상 True).

    Args:
        mask_emails: None 이면 모드를 따른다(mode 1 에서만 이메일 마스킹).
    """

    _MARK = "_ms365_redacted"

    def __init__(self, name: str = "", *, mask_emails: Optional[bool] = None):
        super().__init__(name)
        self._mask_emails = mask_emails

    def _strict(self) -> bool:
        return self._mask_emails if self._mask_emails is not None else _multi_user()

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, self._MARK, False):
            return True
        try:
            self._redact(record)
        except Exception:
            record.msg = "[log record withheld: redaction failed]"
            record.args = None
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        setattr(record, self._MARK, True)
        return True

    def _redact(self, record: logging.LogRecord) -> None:
        strict = self._strict()
        access = record.name in ACCESS_LOGGERS
        strip_query = access or (strict and record.name in URL_LOGGERS)

        def clean(value: str) -> str:
            return redact_text(value, mask_emails=strict, strip_query=strip_query)

        if access and isinstance(record.args, tuple):
            # 구조 보존 — uvicorn AccessFormatter 가 args 를 그대로 풀어 쓴다.
            record.args = tuple(clean(a) if isinstance(a, str) else a for a in record.args)
            if isinstance(record.msg, str):
                record.msg = clean(record.msg)
        else:
            dropped_args = False
            try:
                message = record.getMessage()
            except Exception:
                message, dropped_args = str(record.msg), True
            cleaned = clean(message)
            if dropped_args or cleaned != message:
                record.msg = cleaned
                record.args = None

        # aiohttp access log 의 extra 필드 (사용자 정의 형식이 %(first_request_line)s 등을 쓸 수 있다)
        for attr in ("first_request_line",):
            value = getattr(record, attr, None)
            if isinstance(value, str):
                setattr(record, attr, clean(value))
        for attr in ("request_header", "response_header"):
            value = getattr(record, attr, None)
            if isinstance(value, dict):
                setattr(record, attr, {k: clean(v) if isinstance(v, str) else v for k, v in value.items()})

        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = clean(record.exc_text)
        if record.stack_info:
            record.stack_info = clean(record.stack_info)


_FILTER = RedactionFilter()


def _attach(target: Any) -> bool:
    if any(isinstance(f, RedactionFilter) for f in getattr(target, "filters", ())):
        return False
    target.addFilter(_FILTER)
    return True


def install_redaction(extra_loggers: Iterable[str] = ()) -> RedactionFilter:
    """root 핸들러 전부 + 지정 로거(와 그 핸들러)에 필터를 붙인다. 멱등."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        _attach(handler)
    for name in (*DEFAULT_LOGGERS, *extra_loggers):
        named = logging.getLogger(name)
        _attach(named)
        for handler in list(named.handlers):
            _attach(handler)
    return _FILTER


__all__ = [
    "REDACTED",
    "ACCESS_LOGGERS",
    "URL_LOGGERS",
    "DEFAULT_LOGGERS",
    "RedactionFilter",
    "redact_text",
    "install_redaction",
]
