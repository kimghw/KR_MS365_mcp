"""
Streamable HTTP MCP Server for Teams MCP Server

Exposes TeamsService methods as MCP tools over Streamable HTTP transport
(spec: MCP 2025-03-26). Pattern mirrors mcp_outlook/mcp_server/server_stream.py
but uses inline tool definitions instead of a separate YAML file because
mcp_editor/mcp_teams/ does not exist yet.
"""
import json
from typing import Dict, Any, List, Optional
import sys
import os
import logging
import contextlib
from collections.abc import AsyncIterator
from dotenv import load_dotenv

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
grandparent_dir = os.path.dirname(parent_dir)

_env_path = os.path.join(grandparent_dir, ".env")
_env_loaded = load_dotenv(_env_path, encoding="utf-8-sig")

for _key in ("AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_TENANT_ID", "AZURE_REDIRECT_URI", "AZURE_SCOPES"):
    _val = os.environ.get(_key)
    if _val and _val.startswith("﻿"):
        os.environ[_key] = _val.lstrip("﻿")

print(f"[DEBUG] .env path: {_env_path}, exists: {os.path.exists(_env_path)}, loaded: {_env_loaded}", file=sys.stderr)
print(f"[DEBUG] AZURE_CLIENT_ID: {repr(os.getenv('AZURE_CLIENT_ID'))}", file=sys.stderr)

server_module_dir = os.path.join(grandparent_dir, "mcp_teams")
if os.path.isdir(server_module_dir):
    sys.path.insert(0, server_module_dir)
sys.path.insert(0, grandparent_dir)
sys.path.insert(0, parent_dir)

from mcp_teams.teams_service import TeamsService
from session.auth_database import AuthDatabase

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def get_default_user_email() -> Optional[str]:
    try:
        db = AuthDatabase()
        users = db.list_users()
        if users:
            return users[0].get('user_email') or users[0].get('email')
        return None
    except Exception as e:
        logger.warning(f"Failed to get default user email from auth.db: {e}")
        return None


# ============================================================
# Inline tool definitions (no external YAML dependency)
# ============================================================
MCP_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "handler_teams_list_chats",
        "description": "Teams 채팅 목록 조회",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_email": {"type": "string", "description": "사용자 이메일 (선택, 미지정시 기본 사용자)"},
                "limit": {"type": "integer", "description": "조회 개수", "default": 50},
            },
        },
    },
    {
        "name": "handler_teams_get_chat",
        "description": "Teams 특정 채팅 정보 조회",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chat_id": {"type": "string", "description": "채팅 ID"},
                "user_email": {"type": "string"},
            },
            "required": ["chat_id"],
        },
    },
    {
        "name": "handler_teams_get_chat_messages",
        "description": "Teams 채팅 메시지 목록 조회",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chat_id": {"type": "string", "description": "채팅 ID (없으면 Notes)"},
                "limit": {"type": "integer", "default": 50},
                "user_email": {"type": "string"},
            },
        },
    },
    {
        "name": "handler_teams_send_chat_message",
        "description": "Teams 채팅에 메시지 전송",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "메시지 본문"},
                "chat_id": {"type": "string"},
                "prefix": {"type": "string", "default": "[claude]"},
                "content_type": {"type": "string", "default": "text", "enum": ["text", "html"]},
                "user_email": {"type": "string"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "handler_teams_list_teams",
        "description": "사용자가 속한 팀 목록 조회",
        "inputSchema": {
            "type": "object",
            "properties": {"user_email": {"type": "string"}},
        },
    },
    {
        "name": "handler_teams_list_channels",
        "description": "팀의 채널 목록 조회",
        "inputSchema": {
            "type": "object",
            "properties": {
                "team_id": {"type": "string"},
                "user_email": {"type": "string"},
            },
            "required": ["team_id"],
        },
    },
    {
        "name": "handler_teams_get_channel_messages",
        "description": "채널 메시지 목록 조회",
        "inputSchema": {
            "type": "object",
            "properties": {
                "team_id": {"type": "string"},
                "channel_id": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
                "user_email": {"type": "string"},
            },
            "required": ["team_id", "channel_id"],
        },
    },
    {
        "name": "handler_teams_send_channel_message",
        "description": "채널에 메시지 전송",
        "inputSchema": {
            "type": "object",
            "properties": {
                "team_id": {"type": "string"},
                "channel_id": {"type": "string"},
                "content": {"type": "string"},
                "content_type": {"type": "string", "default": "text", "enum": ["text", "html"]},
                "user_email": {"type": "string"},
            },
            "required": ["team_id", "channel_id", "content"],
        },
    },
    {
        "name": "handler_teams_get_message_replies",
        "description": "메시지 답글 목록 조회",
        "inputSchema": {
            "type": "object",
            "properties": {
                "team_id": {"type": "string"},
                "channel_id": {"type": "string"},
                "message_id": {"type": "string"},
                "user_email": {"type": "string"},
            },
            "required": ["team_id", "channel_id", "message_id"],
        },
    },
    {
        "name": "handler_teams_save_korean_name",
        "description": "채팅방의 한글 이름을 DB에 저장 (단일)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic_kr": {"type": "string"},
                "chat_id": {"type": "string"},
                "topic_en": {"type": "string"},
                "user_email": {"type": "string"},
            },
            "required": ["topic_kr"],
        },
    },
    {
        "name": "handler_teams_save_korean_names_batch",
        "description": "여러 채팅방의 한글 이름을 한 번에 DB에 저장",
        "inputSchema": {
            "type": "object",
            "properties": {
                "names": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "topic_en": {"type": "string"},
                            "topic_kr": {"type": "string"},
                        },
                    },
                    "description": "[{\"topic_en\": \"...\", \"topic_kr\": \"...\"}] 배열",
                },
                "user_email": {"type": "string"},
            },
            "required": ["names"],
        },
    },
    {
        "name": "handler_teams_find_chat_by_name",
        "description": "사용자 이름으로 채팅 검색 (한글/영문)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "recipient_name": {"type": "string"},
                "user_email": {"type": "string"},
            },
            "required": ["recipient_name"],
        },
    },
    {
        "name": "handler_teams_sync_chats",
        "description": "채팅 목록을 DB에 동기화",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50},
                "user_email": {"type": "string"},
            },
        },
    },
    {
        "name": "handler_teams_get_chats_without_korean",
        "description": "한글 이름이 없는 채팅 목록 조회",
        "inputSchema": {
            "type": "object",
            "properties": {"user_email": {"type": "string"}},
        },
    },
]


teams_service = TeamsService()


def _resolve_user_email(args: Dict[str, Any]) -> Optional[str]:
    user_email = args.get("user_email")
    if user_email:
        return user_email
    return get_default_user_email()


# ============================================================
# Tool handlers — thin wrappers over TeamsService methods
# ============================================================

async def handle_list_chats(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.list_chats(
        user_email=_resolve_user_email(args),
        limit=args.get("limit", 50),
    )


async def handle_get_chat(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.get_chat(
        chat_id=args["chat_id"],
        user_email=_resolve_user_email(args),
    )


async def handle_get_chat_messages(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.get_chat_messages(
        chat_id=args.get("chat_id"),
        limit=args.get("limit", 50),
        user_email=_resolve_user_email(args),
    )


async def handle_send_chat_message(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.send_chat_message(
        content=args["content"],
        chat_id=args.get("chat_id"),
        prefix=args.get("prefix", "[claude]"),
        content_type=args.get("content_type", "text"),
        user_email=_resolve_user_email(args),
    )


async def handle_list_teams(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.list_teams(user_email=_resolve_user_email(args))


async def handle_list_channels(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.list_channels(
        team_id=args["team_id"],
        user_email=_resolve_user_email(args),
    )


async def handle_get_channel_messages(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.get_channel_messages(
        team_id=args["team_id"],
        channel_id=args["channel_id"],
        limit=args.get("limit", 50),
        user_email=_resolve_user_email(args),
    )


async def handle_send_channel_message(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.send_channel_message(
        team_id=args["team_id"],
        channel_id=args["channel_id"],
        content=args["content"],
        content_type=args.get("content_type", "text"),
        user_email=_resolve_user_email(args),
    )


async def handle_get_message_replies(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.get_message_replies(
        team_id=args["team_id"],
        channel_id=args["channel_id"],
        message_id=args["message_id"],
        user_email=_resolve_user_email(args),
    )


async def handle_save_korean_name(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.save_korean_name(
        topic_kr=args["topic_kr"],
        chat_id=args.get("chat_id"),
        topic_en=args.get("topic_en"),
        user_email=_resolve_user_email(args),
    )


async def handle_save_korean_names_batch(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.save_korean_names_batch(
        names=args["names"],
        user_email=_resolve_user_email(args),
    )


async def handle_find_chat_by_name(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.find_chat_by_name(
        recipient_name=args["recipient_name"],
        user_email=_resolve_user_email(args),
    )


async def handle_sync_chats(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.sync_chats(
        limit=args.get("limit", 50),
        user_email=_resolve_user_email(args),
    )


async def handle_get_chats_without_korean(args: Dict[str, Any]) -> Dict[str, Any]:
    return await teams_service.get_chats_without_korean(
        user_email=_resolve_user_email(args),
    )


TOOL_HANDLERS = {
    "handler_teams_list_chats": handle_list_chats,
    "handler_teams_get_chat": handle_get_chat,
    "handler_teams_get_chat_messages": handle_get_chat_messages,
    "handler_teams_send_chat_message": handle_send_chat_message,
    "handler_teams_list_teams": handle_list_teams,
    "handler_teams_list_channels": handle_list_channels,
    "handler_teams_get_channel_messages": handle_get_channel_messages,
    "handler_teams_send_channel_message": handle_send_channel_message,
    "handler_teams_get_message_replies": handle_get_message_replies,
    "handler_teams_save_korean_name": handle_save_korean_name,
    "handler_teams_save_korean_names_batch": handle_save_korean_names_batch,
    "handler_teams_find_chat_by_name": handle_find_chat_by_name,
    "handler_teams_sync_chats": handle_sync_chats,
    "handler_teams_get_chats_without_korean": handle_get_chats_without_korean,
}


def get_tool_config(tool_name: str) -> Optional[dict]:
    for tool in MCP_TOOLS:
        if tool.get("name") == tool_name:
            return tool
    return None


def apply_schema_defaults(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    tool_config = get_tool_config(tool_name)
    if not tool_config:
        return arguments
    input_schema = tool_config.get("inputSchema", {})
    properties = input_schema.get("properties", {})
    merged_args = dict(arguments) if arguments else {}
    for prop_name, prop_def in properties.items():
        if prop_name not in merged_args and "default" in prop_def:
            merged_args[prop_name] = prop_def["default"]
    return merged_args


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


def _build_tool_objects() -> List[mcp_types.Tool]:
    tools: List[mcp_types.Tool] = []
    for raw in MCP_TOOLS:
        name = raw.get("name")
        if not name:
            continue
        input_schema = raw.get("inputSchema") or {"type": "object", "properties": {}}
        if "type" not in input_schema:
            input_schema = {"type": "object", **input_schema}
        tools.append(
            mcp_types.Tool(
                name=name,
                description=raw.get("description") or "",
                inputSchema=input_schema,
            )
        )
    return tools


def build_mcp_server() -> MCPServer:
    server: MCPServer = MCPServer(name="teams", version="1.0.0")
    tool_objects = _build_tool_objects()

    @server.list_tools()
    async def _list_tools() -> List[mcp_types.Tool]:
        return tool_objects

    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: Dict[str, Any]):
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            raise ValueError(f"Unknown tool: {name}")

        merged_args = apply_schema_defaults(name, arguments or {})

        try:
            result = await handler(merged_args)
        except Exception as e:
            logger.exception(f"Error executing tool {name}: {e}")
            return [mcp_types.TextContent(
                type="text",
                text=json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False),
            )]

        if isinstance(result, dict) and result.get("status") == "auth_required":
            return [mcp_types.TextContent(
                type="text",
                text=json.dumps(result, ensure_ascii=False, indent=2),
            )]

        if isinstance(result, str):
            return [mcp_types.TextContent(type="text", text=result)]

        return [mcp_types.TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2, default=str),
        )]

    return server


def build_starlette_app() -> Starlette:
    mcp_server = build_mcp_server()

    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=None,
        json_response=False,
        stateless=False,
    )

    class _StreamableHTTPASGI:
        def __init__(self, sm: StreamableHTTPSessionManager):
            self._sm = sm

        async def __call__(self, scope, receive, send) -> None:
            await self._sm.handle_request(scope, receive, send)

    handle_streamable_http = _StreamableHTTPASGI(session_manager)

    async def health(_request: StarletteRequest) -> JSONResponse:
        return JSONResponse({
            "status": "healthy",
            "server": "teams",
            "protocol": "streamable-http",
            "version": "1.0.0",
            "tool_count": len(MCP_TOOLS),
        })

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            try:
                await teams_service.initialize()
                logger.info("TeamsService initialized")
            except Exception as e:
                logger.warning(f"TeamsService initialize() failed: {e}")
            logger.info(f"Teams MCP Streamable HTTP server ready with {len(MCP_TOOLS)} tools")
            try:
                yield
            finally:
                try:
                    await teams_service.close()
                except Exception:
                    pass

    return Starlette(
        debug=False,
        routes=[
            Route("/mcp", endpoint=handle_streamable_http),
            Route("/health", endpoint=health, methods=["GET"]),
        ],
        lifespan=lifespan,
    )


app = build_starlette_app()


def run(host: str = "0.0.0.0", port: int = 5003) -> None:
    import uvicorn
    logger.info(f"Starting Teams MCP Streamable HTTP server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    port = int(os.environ.get("MCP_SERVER_PORT", 5003))
    run(host="0.0.0.0", port=port)
