"""
공통 MCP 런타임.

도메인 서버(outlook/calendar/teams/onedrive/onenote/todo/file_handler)의 transport
계층은 tool dispatch, 기본값 주입, 입력 검증, 오류 변환, 서비스 lifecycle,
health 응답을 각자 복붙해 갖고 있었고 서로 드리프트했다. 그 공통부를 여기로 모은다.

도메인 서버 사용 패턴:

    from mcp_common.runtime import ToolRuntime, ServiceLifecycle

    runtime = ToolRuntime("outlook", MCP_TOOLS, TOOL_HANDLERS)
    lifecycle = ServiceLifecycle("outlook", [mail_service])

    @server.call_tool(validate_input=False)   # 검증은 runtime 이 수행
    async def _call_tool(name, arguments):
        return await runtime.dispatch(name, arguments)

## 멀티유저(mode 1) 호출 순서 (spec/spec_멀티유저.md ②-5.4 — 고정)

    현재 메시지의 검증된 identity 확인 (SDK request scope → 직접 호출이면 bound ContextVar)
    → 계정·키 폐기 상태 재확인 (active_checker)
    → 원본 인자의 user_email 형식·일치 확인 (null·""·불일치는 여기서 끝난다)
    → 스키마에 없는 최상위 인자 거부 (unexpected_argument)
    → schema_normalize boolean 보정 1회 → param_spec 기본값 → 입력 스키마 검증(항상)
    → 사용자별 서비스 lease (풀에 factory 가 있을 때) → 핸들러
    → 응답 전 폐기 상태 재확인 → 안전한 결과/오류

mode 1 에서 `ToolExecutionError` 가 아닌 예외는 원문 없이 `internal_error` + `request_id`
로만 나간다. mode 0 은 기존 동작(예외 타입·메시지 반환)을 그대로 둔다.
"""

import asyncio
import inspect
import logging
import re
import time
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence

from mcp_common.errors import ToolExecutionError, ToolValidationError, normalize_tool_result
from mcp_common.schema_normalize import coerce_boolean_enums_for_schema
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.validation import apply_schema_defaults, validate_arguments

logger = logging.getLogger(__name__)

ToolHandler = Callable[[Dict[str, Any]], Any]
ActiveChecker = Callable[[Any], Awaitable[None]]

#: 감사에서 "denied" 로 분류할 보안 코드 (나머지 실패는 "failure").
_DENIED_CODES = frozenset(
    {
        ErrorCode.MISSING_PRINCIPAL,
        ErrorCode.IDENTITY_MISMATCH,
        ErrorCode.INVALID_USER_EMAIL,
        ErrorCode.ACCOUNT_INACTIVE,
        ErrorCode.FORBIDDEN_SCOPE,
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.UNEXPECTED_ARGUMENT,
        ErrorCode.PATH_NOT_ALLOWED,
        ErrorCode.NOT_FOUND,
    }
)
#: 연결 안내(`connect_url`)를 붙이는 코드 (②-12.4).
_CONNECT_CODES = frozenset({ErrorCode.GRAPH_NOT_CONNECTED, ErrorCode.GRAPH_REAUTH_REQUIRED})
#: 연결 안내 dict 가 덮어쓰면 안 되는 페이로드 키.
_RESERVED_PAYLOAD_KEYS = frozenset({"status", "error", "message"})
#: unexpected_argument 응답에 되돌려 줄 인자 이름 수·길이 상한 (입력 반사 최소화).
_MAX_REPORTED_ARGS = 10
_MAX_REPORTED_ARG_LEN = 64
#: 감사 `error_code` 로 실어도 되는 형식 (고정 코드 모양). 그 밖은 "tool_error".
_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")

#: mode 1 도메인 실패 페이로드에서 버리는 키 — 외부 응답 원문·예외 원문을 싣는 자리 (②-9).
#: 도메인이 `graph_error_summary()` 로 줄여 보내는 것이 1차 방어이고, 이것은 이중 방어다.
_RAW_FAILURE_KEYS = frozenset(
    {
        "details", "detail", "error_detail", "error_details", "error_body", "body",
        "response", "response_body", "raw", "raw_response", "graph_response",
        "traceback", "exception", "stack", "stacktrace",
    }
)
#: 서버 절대경로 (Windows 드라이브·UNC·주요 POSIX 루트)
_ABS_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\)[^\s'\"<>|,;]*"
    r"|(?<![\w.:/])/(?:home|Users|var|tmp|mnt|srv|data|opt|etc|root|private)/[^\s'\"<>|,;]*"
)
_MAX_FAILURE_TEXT = 500
_MAX_FAILURE_DEPTH = 4


def _scrub_failure_text(text: str) -> str:
    from mcp_common.log_redaction import redact_text

    out = _ABS_PATH_RE.sub("<path>", redact_text(text, mask_emails=True))
    return out if len(out) <= _MAX_FAILURE_TEXT else out[:_MAX_FAILURE_TEXT] + "…"


def _sanitize_failure_payload(value: Any, depth: int = 0) -> Any:
    """mode 1 도메인 실패 페이로드 정화: 원문 키 제거 + 문자열의 토큰·이메일·절대경로 마스킹."""
    if depth > _MAX_FAILURE_DEPTH:
        return None
    if isinstance(value, dict):
        cleaned = {
            k: _sanitize_failure_payload(v, depth + 1)
            for k, v in value.items()
            if str(k).lower() not in _RAW_FAILURE_KEYS
        }
        # "error" 는 코드 자리다. 도메인이 `str(exc)` 를 넣어 둔 경우가 가장 흔한 원문 유출 경로라
        # 코드 형식이 아니면 고정 코드로 바꾼다(원문은 옮기지 않는다).
        if depth == 0 and isinstance(value.get("error"), str) and not _CODE_RE.match(value["error"]):
            cleaned["error"] = "tool_error"
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_sanitize_failure_payload(v, depth + 1) for v in list(value)[:50]]
    if isinstance(value, str):
        return _scrub_failure_text(value)
    return value


async def maybe_await(value: Any) -> Any:
    """동기/비동기 핸들러를 모두 지원한다 (동기 반환값을 await 하지 않는다)."""
    if inspect.isawaitable(value):
        return await value
    return value


def to_text_contents(blocks: Sequence[Dict[str, Any]]) -> List[Any]:
    """`{"type": "text", ...}` dict 목록을 mcp.types.TextContent 목록으로 변환."""
    import mcp.types as mcp_types

    return [
        mcp_types.TextContent(type="text", text=block.get("text", ""))
        for block in blocks
    ]


class ToolRuntime:
    """도구 등록/조회/디스패치의 단일 구현."""

    def __init__(
        self,
        server_name: str,
        tools: Iterable[Dict[str, Any]],
        handlers: Dict[str, ToolHandler],
        *,
        validate: bool = True,
        active_checker: Optional[ActiveChecker] = None,
    ):
        """
        Args:
            validate: mode 0 입력 검증 여부. mode 1 에서는 무시하고 항상 검증한다.
            active_checker: mode 1 계정·키 상태 재확인 `async (principal) -> None`.
                없으면 호출 시점에 `session.identity_registry.assert_active` 를 쓴다.
        """
        self.server_name = server_name
        self.tools: List[Dict[str, Any]] = [t for t in (tools or []) if t.get("name")]
        self.handlers = dict(handlers or {})
        self.validate = validate
        self.active_checker: Optional[ActiveChecker] = active_checker
        self._by_name = {t["name"]: t for t in self.tools}

        missing = sorted(set(self._by_name) - set(self.handlers))
        if missing:
            logger.warning(
                "[%s] tools declared without handlers: %s", server_name, ", ".join(missing)
            )
        orphan = sorted(set(self.handlers) - set(self._by_name))
        if orphan:
            logger.warning(
                "[%s] handlers without tool definitions: %s", server_name, ", ".join(orphan)
            )

    # ------------------------------------------------------------------
    def tool_config(self, name: str) -> Optional[Dict[str, Any]]:
        return self._by_name.get(name)

    def input_schema(self, name: str) -> Optional[Dict[str, Any]]:
        config = self._by_name.get(name)
        if not config:
            return None
        schema = config.get("inputSchema") or {"type": "object", "properties": {}}
        if "type" not in schema:
            schema = {"type": "object", **schema}
        return schema

    def build_tool_objects(self) -> List[Any]:
        """YAML dict 을 mcp.types.Tool 로 변환."""
        import mcp.types as mcp_types

        objects = []
        for raw in self.tools:
            objects.append(
                mcp_types.Tool(
                    name=raw["name"],
                    description=raw.get("description") or "",
                    inputSchema=self.input_schema(raw["name"]),
                )
            )
        return objects

    # ------------------------------------------------------------------
    def _unknown_tool(self, name: str) -> ToolExecutionError:
        return ToolExecutionError(
            {
                "status": "error",
                "error": "unknown_tool",
                "tool": name,
                "available": sorted(self.handlers),
            },
            tool=name,
        )

    async def call(self, name: str, arguments: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """도구 실행 → content block dict 목록. 실패는 ToolExecutionError 로 올린다."""
        from mcp_common.security_policy import multi_user_enabled

        if multi_user_enabled():
            return await self._call_multi_user(name, arguments)

        handler = self.handlers.get(name)
        if handler is None:
            raise self._unknown_tool(name)

        schema = self.input_schema(name)
        # 검증 **전** 보정. boolean 파라미터는 스키마상 enabled/disabled 문자열 enum 으로
        # 노출되는데(OpenAI function-calling 이 boolean 을 안 받는다), 기존 클라이언트는
        # 진짜 true/false 를 보낸다. 여기서 흡수하지 않으면 정상 호출이 검증에서 거절된다.
        # 진입점을 여기 하나로 둬서 도메인마다 우회 코드가 생기지 않게 한다.
        arguments = coerce_boolean_enums_for_schema(schema, arguments)
        merged = apply_schema_defaults(schema, arguments)
        if self.validate:
            validate_arguments(schema, merged, tool=name)

        try:
            result = await maybe_await(handler(merged))
        except ToolExecutionError:
            raise
        except Exception as exc:
            logger.exception("[%s] tool %s failed", self.server_name, name)
            raise ToolExecutionError(
                {
                    "status": "error",
                    "error": type(exc).__name__,
                    "message": str(exc),
                    "tool": name,
                },
                tool=name,
            ) from exc

        return normalize_tool_result(result, tool=name)

    # ------------------------------------------------------------------
    # mode 1 (멀티유저) — 모듈 docstring 의 순서를 그대로 따른다
    # ------------------------------------------------------------------
    async def _call_multi_user(
        self, name: str, arguments: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        from mcp_common.mcp_identity_bridge import resolve_request_identity
        from mcp_common.principal import bind_identity

        started = time.monotonic()
        identity = None
        outcome, error_code = "success", None
        try:
            identity = resolve_request_identity()
            with bind_identity(identity):
                return await self._call_bound(name, arguments, identity)
        except SecurityError as exc:
            outcome = "denied" if exc.code in _DENIED_CODES else "failure"
            error_code = exc.code
            raise
        except ToolExecutionError as exc:
            outcome = "failure"
            payload = exc.payload if isinstance(exc.payload, dict) else {}
            code = payload.get("error")
            # 도메인 페이로드의 "error" 에 예외 원문이 들어 있을 수 있다 — 코드 형식만 감사에 싣는다
            error_code = code if isinstance(code, str) and _CODE_RE.match(code) else "tool_error"
            raise
        except asyncio.CancelledError:
            outcome, error_code = "failure", "cancelled"
            raise
        except BaseException:
            outcome, error_code = "failure", ErrorCode.INTERNAL_ERROR
            raise
        finally:
            self._audit_call(name, identity, outcome, error_code, started)

    async def _call_bound(self, name: str, arguments: Any, identity: Any) -> List[Dict[str, Any]]:
        """identity 가 bind 된 상태에서 실행. 예외 원문은 밖으로 내보내지 않는다."""
        from mcp_common.principal import assert_user_email

        principal = identity.principal
        try:
            await self._ensure_active(principal)

            handler = self.handlers.get(name)
            if handler is None:
                raise self._unknown_tool(name)

            if arguments is None:
                raw: Dict[str, Any] = {}
            elif isinstance(arguments, dict):
                raw = dict(arguments)
            else:
                raise ToolValidationError(
                    {"status": "error", "error": "invalid_arguments", "tool": name,
                     "violations": ["<root>: expected type object"]},
                    tool=name,
                )

            # 원본 인자 기준 — null·""·다른 계정은 기본값·보정 전에 끝낸다 (②-5.3)
            if "user_email" in raw:
                assert_user_email(raw["user_email"])

            schema = self.input_schema(name)
            self._reject_unexpected(name, schema, raw)

            coerced = coerce_boolean_enums_for_schema(schema, raw)
            merged = apply_schema_defaults(schema, coerced)
            # mode 1 에서는 MCP_VALIDATE_INPUT·validate=False 와 무관하게 항상 검증된다
            validate_arguments(schema, merged, tool=name)

            result = await self._run_with_service(handler, merged, principal)

            # 실행 중 폐기·비활성화됐으면 결과를 돌려주지 않는다
            await self._ensure_active(principal)
            return normalize_tool_result(result, tool=name)
        except SecurityError as exc:
            enriched = await self._with_connect_details(exc, principal, name)
            if enriched is exc:
                raise
            raise enriched from exc
        except ToolValidationError:
            # 런타임이 만든 검증 오류 — 인자 이름·규칙만 담는다
            raise
        except ToolExecutionError as exc:
            # 도메인 실패 페이로드는 외부 응답·예외 원문을 품을 수 있다 — 정화해서 다시 올린다
            raise ToolExecutionError(_sanitize_failure_payload(exc.payload), tool=name) from None
        except Exception as exc:
            logger.error(
                "[%s] tool %s failed: %s (request_id=%s)",
                self.server_name, name, type(exc).__name__, identity.request_id,
            )
            logger.debug("[%s] tool %s traceback", self.server_name, name, exc_info=True)
            raise SecurityError(
                ErrorCode.INTERNAL_ERROR,
                details={"request_id": identity.request_id},
                tool=name,
            ) from None

    async def _ensure_active(self, principal: Any) -> None:
        checker = self.active_checker
        if checker is None:
            from mcp_common.mcp_identity_bridge import default_assert_active

            checker = default_assert_active
        await maybe_await(checker(principal))

    def _reject_unexpected(self, name: str, schema: Optional[Dict[str, Any]], raw: Dict[str, Any]) -> None:
        """스키마 `properties` 에 없는 최상위 인자 거부 — `db_path`·`user_key` 주입 차단 (②-5.4)."""
        allowed = set(((schema or {}).get("properties") or {}).keys())
        extra = sorted(str(key) for key in raw if key not in allowed)
        if not extra:
            return
        reported = [key[:_MAX_REPORTED_ARG_LEN] for key in extra[:_MAX_REPORTED_ARGS]]
        raise SecurityError(
            ErrorCode.UNEXPECTED_ARGUMENT, details={"arguments": reported}, tool=name
        )

    async def _run_with_service(self, handler: ToolHandler, merged: Dict[str, Any], principal: Any) -> Any:
        """풀에 이 도메인 factory 가 있으면 사용자 서비스를 lease 해 묶고 핸들러를 부른다."""
        from mcp_common import service_pool
        from mcp_common.service_context import bind_service

        pool = service_pool.get_service_pool()
        if not pool.has_factory(self.server_name):
            return await maybe_await(handler(merged))
        async with pool.lease(self.server_name, principal) as service:
            # lease 대기(슬롯·초기화) 동안 키가 폐기·만료됐을 수 있다 — 외부 호출 전에 현재 요청의
            # 키·계정·epoch 를 다시 확인한다 (astra 재검토 R01). 토큰 공급자도 Graph 호출마다
            # 현재 요청 identity 를 재검사하지만, 이 검사가 첫 관문이다.
            await self._ensure_active(principal)
            with bind_service(self.server_name, service):
                return await maybe_await(handler(merged))

    async def _with_connect_details(self, exc: SecurityError, principal: Any, name: str) -> SecurityError:
        """Graph 미연결·재인증 오류에 연결 안내(`connect_url`, `expires_in`)를 붙인다 (②-12.4).

        `mcp_common.auth.graph_connect_details` 는 WP2 가 구현한다. 없거나 실패하면 원래
        오류를 그대로 올린다 — 연결 안내 실패가 오류 코드를 바꾸지 않는다.
        """
        if exc.code not in _CONNECT_CODES or exc.details.get("connect_url"):
            return exc
        try:
            from mcp_common.auth import graph_connect_details

            details = await maybe_await(graph_connect_details(principal))
        except Exception as inner:
            logger.debug("graph_connect_details unavailable: %s", type(inner).__name__)
            return exc
        if not isinstance(details, dict) or not details.get("connect_url"):
            return exc
        merged = dict(exc.details)
        merged.update({k: v for k, v in details.items() if k not in _RESERVED_PAYLOAD_KEYS})
        return SecurityError(exc.code, exc.public_message, details=merged, tool=exc.tool or name)

    def _audit_call(self, name: str, identity: Any, outcome: str, error_code: Optional[str], started: float) -> None:
        """`tool.call` 감사. 인자 값·결과는 싣지 않는다. 감사 실패는 요청을 바꾸지 않는다."""
        try:
            from mcp_common.audit import audit

            fields: Dict[str, Any] = {
                "principal": identity.principal if identity is not None else None,
                "request_id": identity.request_id if identity is not None else None,
                "domain": self.server_name,
                # 미지 도구 이름은 호출자 입력이므로 기록하지 않는다
                "tool": name if name in self.handlers else None,
                "error_code": error_code,
            }
            audit("tool.call", outcome=outcome,
                  duration_ms=int((time.monotonic() - started) * 1000), **fields)
            if error_code == ErrorCode.IDENTITY_MISMATCH:
                audit("auth.identity_mismatch", outcome="denied", **fields)
        except Exception as exc:  # pragma: no cover - 감사 sink 장애
            logger.warning("[%s] tool audit failed: %s", self.server_name, type(exc).__name__)

    async def dispatch(self, name: str, arguments: Optional[Dict[str, Any]]) -> List[Any]:
        """MCP SDK call_tool 핸들러에서 그대로 반환할 수 있는 TextContent 목록."""
        return to_text_contents(await self.call(name, arguments))


class ServiceLifecycle:
    """서비스 initialize/close 를 일관되게 처리하고 health 에 실패를 반영한다."""

    def __init__(self, server_name: str, services: Optional[Iterable[Any]] = None):
        self.server_name = server_name
        self.services: List[Any] = [s for s in (services or []) if s is not None]
        self.errors: List[str] = []
        self.started = False

    def add(self, service: Any) -> None:
        if service is not None:
            self.services.append(service)

    @property
    def healthy(self) -> bool:
        return self.started and not self.errors

    async def startup(self) -> None:
        self.errors = []
        for service in self.services:
            initialize = getattr(service, "initialize", None)
            if initialize is None:
                continue
            try:
                result = await maybe_await(initialize())
            except Exception as exc:
                message = f"{type(service).__name__}.initialize() failed: {exc}"
                logger.error("[%s] %s", self.server_name, message)
                self.errors.append(message)
                continue
            # 여러 서비스(calendar/outlook/onedrive/onenote/teams/todo)는 클라이언트
            # 초기화 실패 시 예외 대신 False 를 반환한다. 반환값을 버리면 health 가
            # 계속 healthy 로 나와 degraded/503 설계가 무력화된다. None(무반환)은 성공,
            # 명시적 falsy(False/0/"" 등)는 실패로 취급한다.
            if result is None or result:
                logger.info("[%s] %s initialized", self.server_name, type(service).__name__)
            else:
                message = f"{type(service).__name__}.initialize() returned {result!r}"
                logger.error("[%s] %s", self.server_name, message)
                self.errors.append(message)
        self.started = True

    async def shutdown(self) -> None:
        for service in reversed(self.services):
            close = getattr(service, "close", None)
            if close is None:
                continue
            try:
                await maybe_await(close())
                logger.info("[%s] %s closed", self.server_name, type(service).__name__)
            except Exception as exc:
                logger.warning(
                    "[%s] %s.close() failed: %s", self.server_name, type(service).__name__, exc
                )
        self.started = False


def build_health_payload(
    server_name: str,
    runtime: Optional[ToolRuntime] = None,
    lifecycle: Optional[ServiceLifecycle] = None,
    *,
    version: str = "1.0.0",
    protocol: str = "streamable-http",
) -> Dict[str, Any]:
    """초기화 실패를 실제로 반영하는 health 페이로드."""
    healthy = lifecycle.healthy if lifecycle is not None else True
    payload: Dict[str, Any] = {
        "status": "healthy" if healthy else "degraded",
        "server": server_name,
        "protocol": protocol,
        "version": version,
        "tool_count": len(runtime.tools) if runtime else 0,
    }
    if lifecycle is not None and lifecycle.errors:
        payload["errors"] = list(lifecycle.errors)
    return payload


def health_status_code(payload: Dict[str, Any]) -> int:
    return 200 if payload.get("status") == "healthy" else 503


__all__ = [
    "ToolRuntime",
    "ServiceLifecycle",
    "build_health_payload",
    "health_status_code",
    "maybe_await",
    "to_text_contents",
]
