"""
Streamable HTTP MCP Server for Calendar MCP Server

Refactored to use the official MCP Python SDK's Streamable HTTP transport
(spec: MCP 2025-03-26). Mounts `StreamableHTTPSessionManager` on a Starlette
app served by uvicorn. Provides spec-compliant single-endpoint `/mcp` with
POST + GET + DELETE, `Mcp-Session-Id` header session management, and the
`Accept: application/json, text/event-stream` negotiation handled by the SDK.

Tool handlers, env loading, BOM stripping, and YAML tool-definition loading
mirror the outlook server_stream.py pattern. See
.claude/skills/setup_ms365/references/streamable_http_checklist.md for the
8-probe compliance test this server must pass.
"""
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional
import sys
import os
import logging
import asyncio
import contextlib
from collections.abc import AsyncIterator
from dotenv import load_dotenv

# Add parent directories to path for module access
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
grandparent_dir = os.path.dirname(parent_dir)

# Load .env from project root before any imports that need env vars
# Use utf-8-sig encoding to handle Windows BOM (Byte Order Mark)
_env_path = os.path.join(grandparent_dir, ".env")
_env_loaded = load_dotenv(_env_path, encoding="utf-8-sig")

# BOM safety: strip ﻿ from env vars that may have been corrupted
for _key in ("AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_TENANT_ID", "AZURE_REDIRECT_URI", "AZURE_SCOPES"):
    _val = os.environ.get(_key)
    if _val and _val.startswith("﻿"):
        os.environ[_key] = _val.lstrip("﻿")

print(f"[DEBUG] .env path: {_env_path}, exists: {os.path.exists(_env_path)}, loaded: {_env_loaded}", file=sys.stderr)
print(f"[DEBUG] AZURE_CLIENT_ID: {repr(os.getenv('AZURE_CLIENT_ID'))}", file=sys.stderr)
if not os.getenv('AZURE_CLIENT_ID'):
    if os.path.exists(_env_path):
        try:
            with open(_env_path, 'rb') as f:
                first_bytes = f.read(100)
            print(f"[ERROR] AZURE_CLIENT_ID is None despite .env existing! First bytes: {first_bytes[:50]}", file=sys.stderr)
        except Exception as e:
            print(f"[ERROR] Cannot read .env: {e}", file=sys.stderr)
    else:
        print(f"[ERROR] .env file does not exist at: {_env_path}", file=sys.stderr)

# Add paths for imports
server_module_dir = os.path.join(grandparent_dir, "mcp_calendar")
if os.path.isdir(server_module_dir):
    sys.path.insert(0, server_module_dir)
sys.path.insert(0, grandparent_dir)
sys.path.insert(0, parent_dir)

# Project imports
from mcp_calendar.calendar_types import EventFilterParams, EventSelectParams
from mcp_common.net import resolve_bind_host
from mcp_common.user_resolver import resolve_user_email
from mcp_common.runtime import (
    ToolRuntime,
    ServiceLifecycle,
    build_health_payload,
    health_status_code,
)

# Configure logging (HTTP transport: stdout is fine for logs)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

SERVER_NAME = "calendar"
SERVER_VERSION = "1.0.0"
DEFAULT_PORT = 5002


def _resolve_user_email(args: Dict[str, Any]) -> str:
    """요청 인자의 user_email 을 공통 정책으로 확정 (미인증이면 예외)."""
    return resolve_user_email(args.get("user_email"), required=True)


# ============================================================
# Tool definitions loading (YAML) - same pattern as server_stdio.py
# ============================================================

def _convert_boolean_schema_to_enabled_disabled(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Convert boolean type properties to enabled/disabled enum for OpenAI compatibility."""
    if not isinstance(schema, dict):
        return schema

    result = dict(schema)

    if 'properties' in result:
        new_properties = {}
        for prop_name, prop_def in result['properties'].items():
            if isinstance(prop_def, dict) and prop_def.get('type') == 'boolean':
                new_prop = dict(prop_def)
                new_prop['type'] = 'string'
                new_prop['enum'] = ['enabled', 'disabled']
                if 'default' in new_prop:
                    new_prop['default'] = 'enabled' if new_prop['default'] else 'disabled'
                new_properties[prop_name] = new_prop
            elif isinstance(prop_def, dict) and prop_def.get('type') == 'object':
                new_properties[prop_name] = _convert_boolean_schema_to_enabled_disabled(prop_def)
            else:
                new_properties[prop_name] = prop_def
        result['properties'] = new_properties

    return result


def _load_mcp_tools() -> List[Dict[str, Any]]:
    """Load MCP tools from tool_definition_templates.yaml."""
    yaml_path_str = os.environ.get("MCP_YAML_PATH")
    if yaml_path_str:
        yaml_path = Path(yaml_path_str)
    else:
        yaml_path = Path(current_dir).parent.parent / "mcp_editor" / "mcp_calendar" / "tool_definition_templates.yaml"
        if not yaml_path.exists():
            yaml_path = Path(current_dir).parent.parent / "mcp_editor" / "mcp_calendar" / "tool_definition_templates.yaml"

    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            tools = data.get("tools", [])
            for tool in tools:
                if 'inputSchema' in tool:
                    tool['inputSchema'] = _convert_boolean_schema_to_enabled_disabled(tool['inputSchema'])
            return tools
    raise FileNotFoundError(f"Tool definition YAML not found: {yaml_path}")


MCP_TOOLS = _load_mcp_tools()


# ============================================================
# Boolean conversion helpers
# ============================================================

def convert_enabled_to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() == "enabled"
    return False


def convert_bool_to_enabled(value: bool) -> str:
    return "enabled" if value else "disabled"


# ============================================================
# Service instantiation
# ============================================================
from mcp_calendar.calendar_service import CalendarService

calendar_service = CalendarService()


def get_tool_config(tool_name: str) -> Optional[dict]:
    """Lookup MCP tool definition by name"""
    for tool in MCP_TOOLS:
        if tool.get("name") == tool_name:
            return tool
    return None


# ============================================================
# Service Factors / Internal args extraction (mirrors stdio)
# ============================================================

def _extract_service_factors(tools: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    service_factors = {}
    for tool in tools:
        tool_name = tool.get('name', '')
        mcp_service_factors = tool.get('mcp_service_factors', {})
        tool_factors = {'internal': {}, 'signature_defaults': {}}

        for factor_name, factor_data in mcp_service_factors.items():
            source = factor_data.get('source', '')
            if source not in ('internal', 'signature_defaults'):
                continue
            factor_type = factor_data.get('type') or factor_data.get('baseModel', '')
            target_param = factor_data.get('targetParam', factor_name)

            raw_params = factor_data.get('parameters', [])
            if isinstance(raw_params, list):
                params_dict = {}
                for param in raw_params:
                    name = param.get("name")
                    if not name:
                        continue
                    param_dict = {"type": param.get("type", "string")}
                    if param.get("has_default", False):
                        param_dict["default"] = param.get("default")
                    if param.get("description"):
                        param_dict["description"] = param["description"]
                    params_dict[name] = param_dict
            else:
                params_dict = raw_params

            default_values = {}
            for param_name, param_def in params_dict.items():
                if 'default' in param_def:
                    default_values[param_name] = param_def['default']

            factor_info = {
                'targetParam': target_param,
                'type': factor_type,
                'source': source,
                'value': default_values,
                'original_schema': {
                    'targetParam': target_param,
                    'properties': params_dict,
                    'type': 'object'
                }
            }
            tool_factors[source][factor_name] = factor_info

        if tool_factors['internal'] or tool_factors['signature_defaults']:
            service_factors[tool_name] = tool_factors

    return service_factors


SERVICE_FACTORS = _extract_service_factors(MCP_TOOLS)


def merge_param_data(internal_data: dict, runtime_data, signature_defaults: dict = None):
    """Merge with priority: runtime > signature_defaults > internal."""
    result = dict(internal_data) if internal_data else {}
    if signature_defaults:
        result = {**result, **signature_defaults}
    if runtime_data:
        if isinstance(runtime_data, dict):
            result = {**result, **runtime_data}
        else:
            return runtime_data
    return result if result else None


# ============================================================
# Tool handler functions (preserved verbatim from legacy server_stream)
# ============================================================

async def handle_calendar_view(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle calendar_view tool call"""
    user_email = _resolve_user_email(args)
    start_datetime = args["start_datetime"]
    end_datetime = args["end_datetime"]
    return await calendar_service.calendar_view(
        user_email=user_email,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
    )


async def handle_list_events(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle list_events tool call"""
    user_email = _resolve_user_email(args)
    top_sig = args.get("top")
    top = top_sig if top_sig is not None else 50
    orderby = args.get("orderby")
    return await calendar_service.list_events(
        user_email=user_email,
        top=top,
        orderby=orderby,
    )


async def handle_update_event(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle update_event tool call"""
    user_email = _resolve_user_email(args)
    event_id = args["event_id"]
    subject = args.get("subject")
    start = args.get("start")
    end = args.get("end")
    body = args.get("body")
    location = args.get("location")
    return await calendar_service.update_event(
        user_email=user_email,
        event_id=event_id,
        subject=subject,
        start=start,
        end=end,
        body=body,
        location=location,
    )


async def handle_get_schedule(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle get_schedule tool call"""
    user_email = _resolve_user_email(args)
    schedules = args["schedules"]
    start_time = args["start_time"]
    end_time = args["end_time"]
    interval_sig = args.get("availability_view_interval")
    availability_view_interval = interval_sig if interval_sig is not None else 30
    return await calendar_service.get_schedule(
        user_email=user_email,
        schedules=schedules,
        start_time=start_time,
        end_time=end_time,
        availability_view_interval=availability_view_interval,
    )


async def handle_get_event(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle get_event tool call"""
    user_email = _resolve_user_email(args)
    event_id = args["event_id"]
    return await calendar_service.get_event(
        user_email=user_email,
        event_id=event_id,
    )


async def handle_create_event(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle create_event tool call"""
    user_email = _resolve_user_email(args)
    subject = args["subject"]
    start = args["start"]
    end = args["end"]
    body_sig = args.get("body")
    body = body_sig if body_sig is not None else None
    location_sig = args.get("location")
    location = location_sig if location_sig is not None else None
    return await calendar_service.create_event(
        user_email=user_email,
        subject=subject,
        start=start,
        end=end,
        body=body,
        location=location,
    )


async def handle_delete_event(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle delete_event tool call"""
    user_email = _resolve_user_email(args)
    event_id = args["event_id"]
    return await calendar_service.delete_event(
        user_email=user_email,
        event_id=event_id,
    )


# ============================================================
# Tool dispatch
# ============================================================

TOOL_HANDLERS = {
    "calendar_view": handle_calendar_view,
    "list_events": handle_list_events,
    "get_event": handle_get_event,
    "create_event": handle_create_event,
    "update_event": handle_update_event,
    "delete_event": handle_delete_event,
    "get_schedule": handle_get_schedule,
}


# 기본값 주입 / 입력 검증 / 오류 정규화 / 디스패치를 모두 담당하는 공통 런타임
RUNTIME = ToolRuntime(SERVER_NAME, MCP_TOOLS, TOOL_HANDLERS)
LIFECYCLE = ServiceLifecycle(SERVER_NAME, [calendar_service])


# ============================================================
# MCP SDK: Server + Streamable HTTP transport
# ============================================================
import mcp.types as mcp_types
from mcp.server.lowlevel import Server as MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from starlette.requests import Request as StarletteRequest


def build_mcp_server() -> MCPServer:
    """Construct an MCP lowlevel Server with tools registered."""
    server: MCPServer = MCPServer(name=SERVER_NAME, version=SERVER_VERSION)

    tool_objects = RUNTIME.build_tool_objects()

    @server.list_tools()
    async def _list_tools() -> List[mcp_types.Tool]:
        return tool_objects

    # validate_input=False — SDK 검증 대신 ToolRuntime 이 검증한다.
    # (YAML 이 boolean 을 enabled/disabled 문자열 enum 으로 변환하기 때문에
    #  list_tools 로 노출되는 그 스키마를 기준으로 검증해야 한다.)
    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: Dict[str, Any]):
        # 실패는 ToolExecutionError 로 올라가고 SDK 가 isError=True 로 감싼다.
        return await RUNTIME.dispatch(name, arguments)

    return server


def build_starlette_app() -> Starlette:
    """Build the Starlette ASGI app that hosts the StreamableHTTP MCP endpoint at /mcp."""
    mcp_server = build_mcp_server()

    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=None,
        json_response=False,   # negotiate JSON or SSE based on Accept header
        stateless=False,       # stateful sessions with Mcp-Session-Id
    )

    # Wrap as a class so Starlette's Route treats it as an ASGI app directly
    # (no method filtering, no request_response wrapper). Same trick FastMCP uses.
    class _StreamableHTTPASGI:
        def __init__(self, sm: StreamableHTTPSessionManager):
            self._sm = sm

        async def __call__(self, scope, receive, send) -> None:
            await self._sm.handle_request(scope, receive, send)

    handle_streamable_http = _StreamableHTTPASGI(session_manager)

    async def health(_request: StarletteRequest) -> JSONResponse:
        # 초기화 실패 시 degraded/503 을 반환한다 (항상 healthy 로 응답하지 않는다)
        payload = build_health_payload(
            SERVER_NAME, RUNTIME, LIFECYCLE, version=SERVER_VERSION
        )
        return JSONResponse(payload, status_code=health_status_code(payload))

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            # 서비스 startup/shutdown 을 공통 lifecycle 로 처리 (close() 누락 방지)
            await LIFECYCLE.startup()
            logger.info(
                f"Calendar MCP Streamable HTTP server ready with {len(RUNTIME.tools)} tools"
            )
            try:
                yield
            finally:
                await LIFECYCLE.shutdown()

    # Route(path="/mcp", endpoint=<ASGI app>) — same trick FastMCP uses.
    # A Route with an ASGI-callable endpoint dispatches all HTTP methods
    # (GET/POST/DELETE) to that callable without forcing a trailing-slash
    # redirect (which would otherwise happen with Mount).
    return Starlette(
        debug=False,
        routes=[
            Route("/mcp", endpoint=handle_streamable_http),
            Route("/health", endpoint=health, methods=["GET"]),
        ],
        lifespan=lifespan,
    )


# Module-level ASGI app (so `uvicorn server_stream:app` also works)
app = build_starlette_app()


def run(host: Optional[str] = None, port: int = DEFAULT_PORT) -> None:
    import uvicorn
    # 기본 바인드는 loopback. 외부 노출은 MCP_BIND_HOST + MCP_ALLOW_PUBLIC_BIND 옵트인 필요.
    bind_host = resolve_bind_host(host, server_name=SERVER_NAME)
    logger.info(f"Starting Calendar MCP Streamable HTTP server on {bind_host}:{port}")
    uvicorn.run(app, host=bind_host, port=port, log_level="info")


if __name__ == "__main__":
    port = int(os.environ.get("MCP_SERVER_PORT", DEFAULT_PORT))
    run(port=port)
