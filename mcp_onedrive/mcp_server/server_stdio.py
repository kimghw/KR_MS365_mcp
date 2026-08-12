"""STDIO MCP Server for OneDrive."""
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

server_module_dir = os.path.join(grandparent_dir, "mcp_onedrive")
if os.path.isdir(server_module_dir):
    sys.path.insert(0, server_module_dir)
sys.path.insert(0, grandparent_dir)
sys.path.insert(0, parent_dir)

from mcp_onedrive.onedrive_service import OneDriveService
from mcp_common.errors import ToolExecutionError
from mcp_common.runtime import ServiceLifecycle, ToolRuntime
from mcp_common.user_resolver import resolve_user_email

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', stream=sys.stderr)
logger = logging.getLogger(__name__)

SERVER_NAME = "onedrive"


MCP_TOOLS: List[Dict[str, Any]] = [
    {"name": "handler_onedrive_get_drive_info", "description": "OneDrive 드라이브 정보 조회",
     "inputSchema": {"type": "object", "properties": {"user_email": {"type": "string"}}}},
    {"name": "handler_onedrive_list_files", "description": "OneDrive 파일/폴더 목록 조회",
     "inputSchema": {"type": "object", "properties": {
         "user_email": {"type": "string"}, "folder_path": {"type": "string"},
         "search": {"type": "string"}, "limit": {"type": "integer", "default": 50}}}},
    {"name": "handler_onedrive_get_item", "description": "OneDrive 파일/폴더 정보 조회",
     "inputSchema": {"type": "object", "properties": {
         "file_path": {"type": "string"}, "user_email": {"type": "string"}}, "required": ["file_path"]}},
    {"name": "handler_onedrive_read_file", "description": "OneDrive 파일 내용 읽기",
     "inputSchema": {"type": "object", "properties": {
         "file_path": {"type": "string"}, "user_email": {"type": "string"},
         "as_text": {"type": "boolean", "default": True}}, "required": ["file_path"]}},
    {"name": "handler_onedrive_write_file", "description": "OneDrive 파일 쓰기/업로드",
     "inputSchema": {"type": "object", "properties": {
         "file_path": {"type": "string"}, "content": {"type": "string"},
         "user_email": {"type": "string"}, "content_type": {"type": "string", "default": "text/plain"},
         "overwrite": {"type": "boolean", "default": True}}, "required": ["file_path", "content"]}},
    {"name": "handler_onedrive_delete_file", "description": "OneDrive 파일/폴더 삭제",
     "inputSchema": {"type": "object", "properties": {
         "file_path": {"type": "string"}, "user_email": {"type": "string"}}, "required": ["file_path"]}},
    {"name": "handler_onedrive_create_folder", "description": "OneDrive 폴더 생성",
     "inputSchema": {"type": "object", "properties": {
         "folder_name": {"type": "string"}, "user_email": {"type": "string"},
         "parent_path": {"type": "string"}}, "required": ["folder_name"]}},
    {"name": "handler_onedrive_copy_file", "description": "OneDrive 파일 복사",
     "inputSchema": {"type": "object", "properties": {
         "source_path": {"type": "string"}, "dest_path": {"type": "string"},
         "user_email": {"type": "string"}, "new_name": {"type": "string"}},
         "required": ["source_path", "dest_path"]}},
    {"name": "handler_onedrive_move_file", "description": "OneDrive 파일 이동",
     "inputSchema": {"type": "object", "properties": {
         "source_path": {"type": "string"}, "dest_path": {"type": "string"},
         "user_email": {"type": "string"}, "new_name": {"type": "string"}},
         "required": ["source_path", "dest_path"]}},
]


onedrive_service = OneDriveService()


def _resolve_user_email(args):
    """사용자 선택은 mcp_common 정책(SSOT)에 위임. 없으면 ToolExecutionError."""
    return resolve_user_email(args.get("user_email"), required=True)


async def handle_get_drive_info(args):
    return await onedrive_service.get_drive_info(user_email=_resolve_user_email(args))

async def handle_list_files(args):
    return await onedrive_service.list_files(user_email=_resolve_user_email(args),
        folder_path=args.get("folder_path"), search=args.get("search"), limit=args.get("limit", 50))

async def handle_get_item(args):
    return await onedrive_service.get_item(file_path=args["file_path"], user_email=_resolve_user_email(args))

async def handle_read_file(args):
    return await onedrive_service.read_file(file_path=args["file_path"],
        user_email=_resolve_user_email(args), as_text=args.get("as_text", True))

async def handle_write_file(args):
    return await onedrive_service.write_file(file_path=args["file_path"], content=args["content"],
        user_email=_resolve_user_email(args), content_type=args.get("content_type", "text/plain"),
        overwrite=args.get("overwrite", True))

async def handle_delete_file(args):
    return await onedrive_service.delete_file(file_path=args["file_path"], user_email=_resolve_user_email(args))

async def handle_create_folder(args):
    return await onedrive_service.create_folder(folder_name=args["folder_name"],
        user_email=_resolve_user_email(args), parent_path=args.get("parent_path"))

async def handle_copy_file(args):
    return await onedrive_service.copy_file(source_path=args["source_path"], dest_path=args["dest_path"],
        user_email=_resolve_user_email(args), new_name=args.get("new_name"))

async def handle_move_file(args):
    return await onedrive_service.move_file(source_path=args["source_path"], dest_path=args["dest_path"],
        user_email=_resolve_user_email(args), new_name=args.get("new_name"))


TOOL_HANDLERS = {
    "handler_onedrive_get_drive_info": handle_get_drive_info,
    "handler_onedrive_list_files": handle_list_files,
    "handler_onedrive_get_item": handle_get_item,
    "handler_onedrive_read_file": handle_read_file,
    "handler_onedrive_write_file": handle_write_file,
    "handler_onedrive_delete_file": handle_delete_file,
    "handler_onedrive_create_folder": handle_create_folder,
    "handler_onedrive_copy_file": handle_copy_file,
    "handler_onedrive_move_file": handle_move_file,
}


# stream transport 와 동일한 dispatch/검증/오류 계약을 공유한다.
runtime = ToolRuntime(SERVER_NAME, MCP_TOOLS, TOOL_HANDLERS)
lifecycle = ServiceLifecycle(SERVER_NAME, [onedrive_service])


def get_tool_config(tool_name: str) -> Optional[dict]:
    """하위 호환용 조회 헬퍼."""
    return runtime.tool_config(tool_name)


class StdioMCPServer:
    def __init__(self):
        self.running = False
        logger.info("OneDrive MCP STDIO Server initialized")

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
            logger.error(f"Error reading message: {e}")
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
                "serverInfo": {"name": "onedrive", "version": "1.0.0"}}

    async def handle_tools_list(self, params):
        return {"tools": MCP_TOOLS}

    async def handle_tools_call(self, params):
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if not tool_name:
            raise ValueError("Tool name required")
        try:
            # 기본값 주입 + 스키마 검증 + 오류 정규화를 ToolRuntime 이 수행한다.
            blocks = await runtime.call(tool_name, arguments)
            return {"content": blocks}
        except ToolExecutionError as e:
            # 실패는 "성공처럼 보이는 TextContent" 가 아니라 isError=True 로 나간다.
            logger.warning(f"Tool {tool_name} failed: {e}")
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}

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
        await lifecycle.startup()
        logger.info("OneDrive MCP STDIO Server started")
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
            await lifecycle.shutdown()
            logger.info("OneDrive MCP STDIO Server stopped")


async def handle_stdio():
    await StdioMCPServer().run()


if __name__ == "__main__":
    asyncio.run(handle_stdio())
