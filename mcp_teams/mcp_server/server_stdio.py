"""
STDIO MCP Server for Teams MCP Server

Exposes TeamsService methods as MCP tools over JSON-RPC on stdin/stdout.
Inline tool definitions (no YAML dependency).
"""
import json
from typing import Dict, Any, List, Optional
import sys
import os
import logging
import asyncio
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

# CRITICAL: redirect stdout to stderr BEFORE imports.
# STDIO MCP uses stdout exclusively for JSON-RPC; any stray print would corrupt the stream.
_original_stdout = sys.stdout
sys.stdout = sys.stderr

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


# Inline tool defs (same as server_stream.py)
MCP_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "handler_teams_list_chats",
        "description": "Teams 채팅 목록 조회",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_email": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    {
        "name": "handler_teams_get_chat",
        "description": "Teams 특정 채팅 정보 조회",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chat_id": {"type": "string"},
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
                "chat_id": {"type": "string"},
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
                "content": {"type": "string"},
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
        "description": "채팅방의 한글 이름을 DB에 저장",
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


async def handle_list_chats(args):
    return await teams_service.list_chats(user_email=_resolve_user_email(args), limit=args.get("limit", 50))


async def handle_get_chat(args):
    return await teams_service.get_chat(chat_id=args["chat_id"], user_email=_resolve_user_email(args))


async def handle_get_chat_messages(args):
    return await teams_service.get_chat_messages(
        chat_id=args.get("chat_id"), limit=args.get("limit", 50), user_email=_resolve_user_email(args)
    )


async def handle_send_chat_message(args):
    return await teams_service.send_chat_message(
        content=args["content"],
        chat_id=args.get("chat_id"),
        prefix=args.get("prefix", "[claude]"),
        content_type=args.get("content_type", "text"),
        user_email=_resolve_user_email(args),
    )


async def handle_list_teams(args):
    return await teams_service.list_teams(user_email=_resolve_user_email(args))


async def handle_list_channels(args):
    return await teams_service.list_channels(team_id=args["team_id"], user_email=_resolve_user_email(args))


async def handle_get_channel_messages(args):
    return await teams_service.get_channel_messages(
        team_id=args["team_id"], channel_id=args["channel_id"],
        limit=args.get("limit", 50), user_email=_resolve_user_email(args),
    )


async def handle_send_channel_message(args):
    return await teams_service.send_channel_message(
        team_id=args["team_id"], channel_id=args["channel_id"], content=args["content"],
        content_type=args.get("content_type", "text"), user_email=_resolve_user_email(args),
    )


async def handle_get_message_replies(args):
    return await teams_service.get_message_replies(
        team_id=args["team_id"], channel_id=args["channel_id"],
        message_id=args["message_id"], user_email=_resolve_user_email(args),
    )


async def handle_save_korean_name(args):
    return await teams_service.save_korean_name(
        topic_kr=args["topic_kr"], chat_id=args.get("chat_id"),
        topic_en=args.get("topic_en"), user_email=_resolve_user_email(args),
    )


async def handle_save_korean_names_batch(args):
    return await teams_service.save_korean_names_batch(names=args["names"], user_email=_resolve_user_email(args))


async def handle_find_chat_by_name(args):
    return await teams_service.find_chat_by_name(
        recipient_name=args["recipient_name"], user_email=_resolve_user_email(args)
    )


async def handle_sync_chats(args):
    return await teams_service.sync_chats(limit=args.get("limit", 50), user_email=_resolve_user_email(args))


async def handle_get_chats_without_korean(args):
    return await teams_service.get_chats_without_korean(user_email=_resolve_user_email(args))


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


class StdioMCPServer:
    def __init__(self):
        self.running = False
        logger.info("Teams MCP STDIO Server initialized")

    async def read_message(self) -> Optional[Dict[str, Any]]:
        try:
            line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
            if not line:
                return None
            return json.loads(line.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Error reading message: {e}")
            return None

    def write_message(self, message: Dict[str, Any]):
        try:
            json_str = json.dumps(message, ensure_ascii=False, default=str)
            _original_stdout.write(json_str + '\n')
            _original_stdout.flush()
        except Exception as e:
            logger.error(f"Error writing message: {e}")

    def send_error(self, request_id, code, message, data=None):
        err = {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
        if data is not None:
            err["error"]["data"] = data
        self.write_message(err)

    def send_result(self, request_id, result):
        self.write_message({"jsonrpc": "2.0", "id": request_id, "result": result})

    async def handle_initialize(self, params):
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "teams", "version": "1.0.0"},
        }

    async def handle_tools_list(self, params):
        return {"tools": MCP_TOOLS}

    async def handle_tools_call(self, params):
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if not tool_name:
            raise ValueError("Tool name required")

        arguments = apply_schema_defaults(tool_name, arguments)
        handler = TOOL_HANDLERS.get(tool_name)
        if handler is None:
            raise ValueError(f"Unknown tool: {tool_name}")

        try:
            result = await handler(arguments)
            if isinstance(result, dict) and result.get("status") == "auth_required":
                return {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
                    "isError": True,
                }
            if isinstance(result, str):
                return {"content": [{"type": "text", "text": result}]}
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2, default=str),
                }]
            }
        except Exception as e:
            logger.error(f"Error executing {tool_name}: {e}", exc_info=True)
            raise

    async def handle_request(self, request):
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if not method:
            self.send_error(request_id, -32600, "missing method")
            return

        try:
            if method == "initialize":
                result = await self.handle_initialize(params)
            elif method == "tools/list":
                result = await self.handle_tools_list(params)
            elif method == "tools/call":
                result = await self.handle_tools_call(params)
            elif method == "shutdown":
                self.running = False
                result = {}
            elif method == "ping":
                result = {"pong": True}
            else:
                self.send_error(request_id, -32601, f"Method not found: {method}")
                return
            self.send_result(request_id, result)
        except ValueError as e:
            self.send_error(request_id, -32602, f"Invalid params: {e}")
        except Exception as e:
            logger.error(f"Error handling request: {e}", exc_info=True)
            self.send_error(request_id, -32603, f"Internal error: {e}")

    async def handle_notification(self, notification):
        method = notification.get("method")
        logger.info(f"Notification: {method}")

    async def run(self):
        self.running = True
        try:
            await teams_service.initialize()
            logger.info("TeamsService initialized")
        except Exception as e:
            logger.warning(f"TeamsService initialize() failed: {e}")

        logger.info("Teams MCP STDIO Server started")
        try:
            while self.running:
                message = await self.read_message()
                if message is None:
                    logger.info("Input closed, shutting down")
                    break
                if "id" in message:
                    await self.handle_request(message)
                else:
                    await self.handle_notification(message)
        except KeyboardInterrupt:
            logger.info("Interrupted")
        except Exception as e:
            logger.error(f"Server error: {e}", exc_info=True)
        finally:
            try:
                await teams_service.close()
            except Exception:
                pass
            logger.info("Teams MCP STDIO Server stopped")


async def handle_stdio():
    await StdioMCPServer().run()


if __name__ == "__main__":
    asyncio.run(handle_stdio())
