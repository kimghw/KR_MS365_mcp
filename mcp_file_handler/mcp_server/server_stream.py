"""
Streaming MCP Server for File Handler MCP Server
Handles MCP protocol via HTTP streaming (SSE)
Generated from universal template with registry data and protocol selection
"""
import json
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import sys
import os
import logging
import aiohttp
import asyncio
from typing import AsyncIterator

# Add parent directories to path for module access
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
grandparent_dir = os.path.dirname(parent_dir)

# Add paths for imports based on server type
file_handler_dir = os.path.join(grandparent_dir, "mcp_file_handler")
sys.path.insert(0, file_handler_dir)  # For file_handler relative imports
sys.path.insert(0, grandparent_dir)  # For session module and package imports
sys.path.insert(0, parent_dir)  # For direct module imports

# Import types dynamically based on type_info

# Import tool definitions
try:
    from .tool_definitions import MCP_TOOLS
except ImportError:
    from tool_definitions import MCP_TOOLS

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import service classes (unique)
from mcp_file_handler.file_manager import FileManager

# Create service instances
file_manager = FileManager()

# ============================================================
# Common MCP protocol utilities (shared across protocols)
# ============================================================

SUPPORTED_PROTOCOLS = {"rest", "stdio", "stream"}

# Pre-computed tool -> implementation mapping
TOOL_IMPLEMENTATIONS = {
    "convert_file_to_text": {
        "service_class": "FileManager",
        "method": "process"
    },
    "process_directory": {
        "service_class": "FileManager",
        "method": "process_directory"
    },
    "save_file_metadata": {
        "service_class": "FileManager",
        "method": "save_metadata"
    },
    "search_metadata": {
        "service_class": "FileManager",
        "method": "search_metadata"
    },
    "convert_onedrive_to_text": {
        "service_class": "FileManager",
        "method": "process_onedrive"
    },
    "get_file_metadata": {
        "service_class": "FileManager",
        "method": "get_metadata"
    },
    "delete_file_metadata": {
        "service_class": "FileManager",
        "method": "delete_metadata"
    },
}

# Pre-computed service class -> instance mapping
SERVICE_INSTANCES = {
    "FileManager": file_manager,
}


def get_tool_config(tool_name: str) -> Optional[dict]:
    """Lookup MCP tool definition by name"""
    for tool in MCP_TOOLS:
        if tool.get("name") == tool_name:
            return tool
    return None


def get_tool_implementation(tool_name: str) -> Optional[dict]:
    """Get implementation mapping for a tool"""
    return TOOL_IMPLEMENTATIONS.get(tool_name)


def get_service_instance(service_class: str):
    """Get instantiated service by class name"""
    return SERVICE_INSTANCES.get(service_class)


def format_tool_result(result: Any) -> Dict[str, Any]:
    """Normalize service results into a consistent MCP payload"""
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        return {"items": result}
    if isinstance(result, str):
        return {"message": result}
    if result is None:
        return {"success": True}
    return {"result": str(result)}


def build_mcp_content(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Wrap normalized payload into MCP content envelope"""
    return {
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, ensure_ascii=False, indent=2)
                }
            ]
        }
    }


# ============================================================
# Internal Args Support
# ============================================================
# Internal args are now embedded in tool definitions via mcp_service_factors
# This data is passed from the generator as part of the context
INTERNAL_ARGS = {}

# Build INTERNAL_ARG_TYPES dynamically based on imported types
INTERNAL_ARG_TYPES = {}


def extract_schema_defaults(arg_info: dict) -> dict:
    """Extract default values from original_schema.properties."""
    original_schema = arg_info.get("original_schema", {})
    properties = original_schema.get("properties", {})
    defaults = {}
    for prop_name, prop_def in properties.items():
        if "default" in prop_def:
            defaults[prop_name] = prop_def["default"]
    return defaults


def build_internal_param(tool_name: str, arg_name: str, runtime_value: dict = None):
    """Instantiate internal parameter object for a tool.

    Value resolution priority:
    1. runtime_value: Dynamic value passed from function arguments at runtime
    2. stored value: Value from INTERNAL_ARGS (generated from mcp_service_factors)
    3. defaults: Static value from original_schema.properties
    """
    arg_info = INTERNAL_ARGS.get(tool_name, {}).get(arg_name)
    if not arg_info:
        return None

    param_cls = INTERNAL_ARG_TYPES.get(arg_info.get("type"))
    if not param_cls:
        logger.warning(f"Unknown internal arg type for {tool_name}.{arg_name}: {arg_info.get('type')}")
        return None

    defaults = extract_schema_defaults(arg_info)
    stored_value = arg_info.get("value")

    if runtime_value is not None and runtime_value != {}:
        final_value = {**defaults, **runtime_value}
    elif stored_value is not None and stored_value != {}:
        final_value = {**defaults, **stored_value}
    else:
        final_value = defaults

    if not final_value:
        return param_cls()

    try:
        return param_cls(**final_value)
    except Exception as exc:
        logger.warning(f"Failed to build internal arg {tool_name}.{arg_name}: {exc}")
        return None


def model_to_dict(model):
    if model is None:
        return {}
    if isinstance(model, dict):
        return model
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=True)
    if hasattr(model, "dict"):
        return model.dict(exclude_none=True)
    return {}


def merge_param_data(internal_data: dict, runtime_data):
    if not runtime_data:
        return internal_data or None
    if internal_data:
        return {**internal_data, **runtime_data}
    return runtime_data

# Tool handler functions

async def handle_convert_file_to_text(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle convert_file_to_text tool call"""

    # Extract parameters from args
    # Extract from input with source param name
    input_path = args["input_path"]

    return await file_manager.process(
        input_path=input_path
    )

async def handle_process_directory(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle process_directory tool call"""

    # Extract parameters from args
    # Extract from input with source param name
    directory_path = args["directory_path"]

    return await file_manager.process_directory(
        directory_path=directory_path
    )

async def handle_save_file_metadata(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle save_file_metadata tool call"""

    # Extract parameters from args
    # Extract from input with source param name
    file_url = args["file_url"]
    # Extract from input with source param name
    keywords = args["keywords"]
    additional_metadata = args.get("additional_metadata")

    # Convert dicts to parameter objects where needed
    additional_metadata_internal_data = {}
    # Use already extracted value if it exists
    # Value was already extracted above, use the existing variable
    additional_metadata_data = merge_param_data(additional_metadata_internal_data, additional_metadata)
    additional_metadata = dict(**additional_metadata_data) if additional_metadata_data is not None else None
    # Prepare call arguments
    call_args = {}

    # Add signature parameters
    call_args["file_url"] = file_url
    call_args["keywords"] = keywords
    call_args["additional_metadata"] = additional_metadata

    return await file_manager.save_metadata(**call_args)

async def handle_search_metadata(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle search_metadata tool call"""

    # Extract parameters from args

    return await file_manager.search_metadata(
    )

async def handle_convert_onedrive_to_text(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle convert_onedrive_to_text tool call"""

    # Extract parameters from args
    # Extract from input with source param name
    url = args["url"]

    return await file_manager.process_onedrive(
        url=url
    )

async def handle_get_file_metadata(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle get_file_metadata tool call"""

    # Extract parameters from args
    # Extract from input with source param name
    file_url = args["file_url"]

    return await file_manager.get_metadata(
        file_url=file_url
    )

async def handle_delete_file_metadata(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle delete_file_metadata tool call"""

    # Extract parameters from args
    # Extract from input with source param name
    file_url = args["file_url"]

    return await file_manager.delete_metadata(
        file_url=file_url
    )

# ============================================================
# StreamableHTTP Protocol Implementation for MCP Server
# ============================================================
# Note: This template is included by universal_server_template.jinja2
# All common imports and utilities are defined in the parent template

from aiohttp import web

# Use the logger from parent template
logger = logging.getLogger(__name__)

class StreamableHTTPMCPServer:
    """MCP StreamableHTTP Protocol Server

    HTTP 기반 스트리밍 프로토콜로 청크 단위의 응답을 지원합니다.
    Transfer-Encoding: chunked를 사용하여 점진적 응답 전송이 가능합니다.
    """

    def __init__(self):
        self.app = web.Application()
        self.setup_routes()
        logger.info(f"File Handler MCP Server StreamableHTTP Server initialized")

    def setup_routes(self):
        """HTTP 라우트 설정"""
        # MCP 표준 엔드포인트
        self.app.router.add_post('/mcp/v1/initialize', self.handle_initialize)
        self.app.router.add_post('/mcp/v1/tools/list', self.handle_tools_list)
        self.app.router.add_post('/mcp/v1/tools/call', self.handle_tools_call)
        # Health check
        self.app.router.add_get('/health', self.handle_health)
        # CORS 처리
        self.app.router.add_route('OPTIONS', '/{path:.*}', self.handle_options)

    async def handle_options(self, request: web.Request) -> web.Response:
        """CORS preflight 요청 처리"""
        return web.Response(
            headers={
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Max-Age': '3600'
            }
        )

    def add_cors_headers(self, response: web.Response) -> web.Response:
        """CORS 헤더 추가"""
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response

    async def handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint"""
        response = web.json_response({
            "status": "healthy",
            "server": "file_handler",
            "protocol": "streamableHTTP",
            "version": "1.0.0"
        })
        return self.add_cors_headers(response)

    async def handle_initialize(self, request: web.Request) -> web.Response:
        """Initialize endpoint"""
        try:
            data = await request.json()
            client_info = data.get('clientInfo', {})
            logger.info(f"Client connected: {client_info.get('name', 'unknown')}")

            response_data = {
                "protocolVersion": "0.1.0",
                "capabilities": {
                    "tools": {},
                    "prompts": {},
                    "resources": {},
                    "streaming": True  # 스트리밍 지원 표시
                },
                "serverInfo": {
                    "name": "file_handler",
                    "version": "1.0.0",
                    "protocol": "streamableHTTP"
                }
            }

            response = web.json_response(response_data)
            return self.add_cors_headers(response)

        except Exception as e:
            logger.error(f"Error in initialize: {e}")
            return web.json_response(
                {"error": {"code": -32603, "message": str(e)}},
                status=500
            )

    async def handle_tools_list(self, request: web.Request) -> web.Response:
        """List available tools"""
        try:
            # MCP_TOOLS에 스트리밍 지원 정보 추가
            tools_with_streaming = []
            for tool in MCP_TOOLS:
                tool_copy = tool.copy()
                # 특정 도구에 대해 스트리밍 지원 표시 가능
                tool_copy['supportsStreaming'] = True
                tools_with_streaming.append(tool_copy)

            response = web.json_response({"tools": tools_with_streaming})
            return self.add_cors_headers(response)

        except Exception as e:
            logger.error(f"Error listing tools: {e}")
            return web.json_response(
                {"error": {"code": -32603, "message": str(e)}},
                status=500
            )

    async def handle_tools_call(self, request: web.Request) -> web.Response:
        """도구 실행 - 스트리밍 응답 지원"""
        try:
            data = await request.json()
            tool_name = data.get('name')
            arguments = data.get('arguments', {})
            stream = data.get('stream', False)  # 스트리밍 옵션

            if not tool_name:
                return web.json_response(
                    {"error": {"code": -32602, "message": "Tool name is required"}},
                    status=400
                )

            # 도구 핸들러 검색
            handler_name = f"handle_{tool_name.replace('-', '_')}"
            if handler_name not in globals():
                return web.json_response(
                    {"error": {"code": -32602, "message": f"Unknown tool: {tool_name}"}},
                    status=400
                )

            if stream:
                # 스트리밍 응답
                return await self.stream_tool_response(tool_name, arguments, request)
            else:
                # 일반 응답
                result = await globals()[handler_name](arguments)

                # 결과 포맷팅
                if isinstance(result, dict) and "content" in result:
                    response_data = result
                elif isinstance(result, str):
                    response_data = {
                        "content": [
                            {"type": "text", "text": result}
                        ]
                    }
                else:
                    response_data = {
                        "content": [
                            {"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}
                        ]
                    }

                response = web.json_response(response_data)
                return self.add_cors_headers(response)

        except ValueError as e:
            return web.json_response(
                {"error": {"code": -32602, "message": str(e)}},
                status=400
            )
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
            return web.json_response(
                {"error": {"code": -32603, "message": str(e)}},
                status=500
            )

    async def stream_tool_response(self, tool_name: str, arguments: dict, request: web.Request) -> web.StreamResponse:
        """도구 응답을 스트리밍으로 전송"""
        response = web.StreamResponse()
        response.headers['Content-Type'] = 'application/x-ndjson'  # Newline Delimited JSON
        response.headers['Transfer-Encoding'] = 'chunked'
        response.headers['Cache-Control'] = 'no-cache'

        # CORS 헤더 추가
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'

        await response.prepare(request)

        try:
            # 도구 핸들러 실행
            handler_name = f"handle_{tool_name.replace('-', '_')}"
            handler = globals()[handler_name]

            # 스트리밍 가능한 도구인지 확인
            if asyncio.iscoroutinefunction(handler):
                result = await handler(arguments)

                # 결과를 청크로 분할하여 전송 (시뮬레이션)
                if isinstance(result, str):
                    # 텍스트를 청크로 분할
                    chunks = [result[i:i+100] for i in range(0, len(result), 100)]
                    for i, chunk in enumerate(chunks):
                        chunk_data = {
                            "type": "chunk",
                            "content": chunk,
                            "index": i,
                            "done": False
                        }
                        await response.write((json.dumps(chunk_data) + '\n').encode('utf-8'))
                        await asyncio.sleep(0.1)  # 스트리밍 효과

                elif isinstance(result, dict):
                    # 딕셔너리를 부분적으로 전송
                    chunk_data = {
                        "type": "chunk",
                        "content": result,
                        "index": 0,
                        "done": False
                    }
                    await response.write((json.dumps(chunk_data) + '\n').encode('utf-8'))

                elif isinstance(result, list):
                    # 리스트 항목을 하나씩 전송
                    for i, item in enumerate(result):
                        chunk_data = {
                            "type": "chunk",
                            "content": item,
                            "index": i,
                            "done": False
                        }
                        await response.write((json.dumps(chunk_data) + '\n').encode('utf-8'))
                        await asyncio.sleep(0.05)  # 스트리밍 효과

            # 완료 신호
            end_chunk = {
                "type": "end",
                "done": True,
                "summary": f"Completed {tool_name} execution"
            }
            await response.write((json.dumps(end_chunk) + '\n').encode('utf-8'))

        except Exception as e:
            # 에러 청크 전송
            error_chunk = {
                "type": "error",
                "error": {"code": -32603, "message": str(e)},
                "done": True
            }
            await response.write((json.dumps(error_chunk) + '\n').encode('utf-8'))
            logger.error(f"Streaming error for {tool_name}: {e}", exc_info=True)

        finally:
            await response.write_eof()

        return response

    async def on_startup(self, app):
        """서버 시작 시 실행"""
        logger.info(f"File Handler MCP Server StreamableHTTP Server starting on port {app['port']}")

        # Initialize services
        if hasattr(file_manager, 'initialize'):
            await file_manager.initialize()
            logger.info("FileManager initialized")

    async def on_cleanup(self, app):
        """서버 종료 시 정리"""
        logger.info(f"File Handler MCP Server StreamableHTTP Server shutting down")

    def run(self, host: str = '0.0.0.0', port: int = 8001):
        """서버 실행"""
        self.app['port'] = port
        self.app.on_startup.append(self.on_startup)
        self.app.on_cleanup.append(self.on_cleanup)

        logger.info(f"Starting File Handler MCP Server StreamableHTTP Server on {host}:{port}")
        web.run_app(self.app, host=host, port=port, print=lambda _: None)

# 메인 엔트리 포인트
def handle_streamablehttp(host: str = '0.0.0.0', port: int = 8001):
    """Handle MCP protocol via StreamableHTTP"""
    server = StreamableHTTPMCPServer()
    server.run(host, port)

if __name__ == "__main__":
    handle_streamablehttp(host="0.0.0.0", port=8001)  # StreamableHTTP server