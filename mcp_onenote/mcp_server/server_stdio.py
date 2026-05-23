"""STDIO MCP Server for OneNote."""
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

_original_stdout = sys.stdout
sys.stdout = sys.stderr

print(f"[DEBUG] .env path: {_env_path}, exists: {os.path.exists(_env_path)}, loaded: {_env_loaded}", file=sys.stderr)
print(f"[DEBUG] AZURE_CLIENT_ID: {repr(os.getenv('AZURE_CLIENT_ID'))}", file=sys.stderr)

server_module_dir = os.path.join(grandparent_dir, "mcp_onenote")
if os.path.isdir(server_module_dir):
    sys.path.insert(0, server_module_dir)
sys.path.insert(0, grandparent_dir)
sys.path.insert(0, parent_dir)

from mcp_onenote.onenote_service import OneNoteService
from session.auth_database import AuthDatabase

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', stream=sys.stderr)
logger = logging.getLogger(__name__)


def get_default_user_email() -> Optional[str]:
    try:
        db = AuthDatabase()
        users = db.list_users()
        if users:
            return users[0].get('user_email') or users[0].get('email')
        return None
    except Exception as e:
        logger.warning(f"Failed to get default user email: {e}")
        return None


MCP_TOOLS: List[Dict[str, Any]] = [
    {"name": "read_onenote", "description": "OneNote 조회 라우터",
     "inputSchema": {"type": "object", "properties": {
         "user_email": {"type": "string"},
         "action": {"type": "string", "enum": ["list_pages", "list_sections", "search", "get_content", "get_summary"]},
         "keyword": {"type": "string"}, "page_id": {"type": "string"},
         "section_id": {"type": "string"}, "notebook_id": {"type": "string"},
         "date_from": {"type": "string"}, "date_to": {"type": "string"},
         "top": {"type": "integer", "default": 50}},
         "required": ["action"]}},
    {"name": "write_onenote", "description": "OneNote 생성/수정 라우터",
     "inputSchema": {"type": "object", "properties": {
         "user_email": {"type": "string"},
         "action": {"type": "string", "enum": ["append", "create_page", "create_section"]},
         "content": {"type": "string"}, "page_id": {"type": "string"},
         "section_id": {"type": "string"}, "notebook_id": {"type": "string"},
         "title": {"type": "string"}},
         "required": ["action"]}},
    {"name": "delete_onenote", "description": "OneNote 페이지 삭제",
     "inputSchema": {"type": "object", "properties": {
         "user_email": {"type": "string"}, "page_id": {"type": "string"}},
         "required": ["page_id"]}},
    {"name": "sync_onenote_db", "description": "OneNote 전체 페이지를 DB에 동기화",
     "inputSchema": {"type": "object", "properties": {"user_email": {"type": "string"}}}},
]


onenote_service = OneNoteService()


def _resolve_user_email(args):
    return args.get("user_email") or get_default_user_email()


def _require_user_email(args):
    user_email = _resolve_user_email(args)
    if not user_email:
        return None, {"success": False, "error": "user_email이 필요합니다."}
    return user_email, None


async def handle_read_onenote(args):
    user_email, err = _require_user_email(args)
    if err:
        return err
    return await onenote_service.read_onenote(
        user_email=user_email, action=args["action"],
        keyword=args.get("keyword"), page_id=args.get("page_id"),
        section_id=args.get("section_id"), notebook_id=args.get("notebook_id"),
        date_from=args.get("date_from"), date_to=args.get("date_to"),
        top=args.get("top", 50),
    )


async def handle_write_onenote(args):
    user_email, err = _require_user_email(args)
    if err:
        return err
    return await onenote_service.write_onenote(
        user_email=user_email, action=args["action"],
        content=args.get("content"), page_id=args.get("page_id"),
        section_id=args.get("section_id"), notebook_id=args.get("notebook_id"),
        title=args.get("title"),
    )


async def handle_delete_onenote(args):
    user_email, err = _require_user_email(args)
    if err:
        return err
    return await onenote_service.delete_onenote(user_email=user_email, page_id=args["page_id"])


async def handle_sync_onenote_db(args):
    user_email, err = _require_user_email(args)
    if err:
        return err
    return await onenote_service.writer.sync_db(user_email=user_email)


TOOL_HANDLERS = {
    "read_onenote": handle_read_onenote,
    "write_onenote": handle_write_onenote,
    "delete_onenote": handle_delete_onenote,
    "sync_onenote_db": handle_sync_onenote_db,
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
    properties = tool_config.get("inputSchema", {}).get("properties", {})
    merged = dict(arguments) if arguments else {}
    for prop_name, prop_def in properties.items():
        if prop_name not in merged and "default" in prop_def:
            merged[prop_name] = prop_def["default"]
    return merged


class StdioMCPServer:
    def __init__(self):
        self.running = False
        logger.info("OneNote MCP STDIO Server initialized")

    async def read_message(self):
        try:
            line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
            if not line:
                return None
            return json.loads(line.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Error reading: {e}")
            return None

    def write_message(self, message):
        try:
            _original_stdout.write(json.dumps(message, ensure_ascii=False, default=str) + '\n')
            _original_stdout.flush()
        except Exception as e:
            logger.error(f"Error writing: {e}")

    def send_error(self, request_id, code, message, data=None):
        err = {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
        if data is not None:
            err["error"]["data"] = data
        self.write_message(err)

    def send_result(self, request_id, result):
        self.write_message({"jsonrpc": "2.0", "id": request_id, "result": result})

    async def handle_initialize(self, params):
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "onenote", "version": "1.0.0"}}

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
                return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}], "isError": True}
            if isinstance(result, str):
                return {"content": [{"type": "text", "text": result}]}
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2, default=str)}]}
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
            logger.error(f"Error: {e}", exc_info=True)
            self.send_error(request_id, -32603, f"Internal error: {e}")

    async def handle_notification(self, notification):
        logger.info(f"Notification: {notification.get('method')}")

    async def run(self):
        self.running = True
        try:
            await onenote_service.initialize()
            logger.info("OneNoteService initialized")
        except Exception as e:
            logger.warning(f"OneNoteService init failed: {e}")
        logger.info("OneNote MCP STDIO Server started")
        try:
            while self.running:
                message = await self.read_message()
                if message is None:
                    break
                if "id" in message:
                    await self.handle_request(message)
                else:
                    await self.handle_notification(message)
        except KeyboardInterrupt:
            pass
        except Exception as e:
            logger.error(f"Server error: {e}", exc_info=True)
        finally:
            try:
                await onenote_service.close()
            except Exception:
                pass
            logger.info("OneNote MCP STDIO Server stopped")


async def handle_stdio():
    await StdioMCPServer().run()


if __name__ == "__main__":
    asyncio.run(handle_stdio())
