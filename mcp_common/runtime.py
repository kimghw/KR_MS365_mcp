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
"""

import inspect
import logging
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence

from mcp_common.errors import ToolExecutionError, normalize_tool_result
from mcp_common.validation import apply_schema_defaults, validate_arguments

logger = logging.getLogger(__name__)

ToolHandler = Callable[[Dict[str, Any]], Any]


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
    ):
        self.server_name = server_name
        self.tools: List[Dict[str, Any]] = [t for t in (tools or []) if t.get("name")]
        self.handlers = dict(handlers or {})
        self.validate = validate
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
    async def call(self, name: str, arguments: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """도구 실행 → content block dict 목록. 실패는 ToolExecutionError 로 올린다."""
        handler = self.handlers.get(name)
        if handler is None:
            raise ToolExecutionError(
                {
                    "status": "error",
                    "error": "unknown_tool",
                    "tool": name,
                    "available": sorted(self.handlers),
                },
                tool=name,
            )

        schema = self.input_schema(name)
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
