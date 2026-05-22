"""
FastAPI MCP Server for File Handler MCP Server
Routes MCP protocol requests to service functions
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
# REST API Protocol Handlers for MCP
# ============================================================
# Note: This template is included by universal_server_template.jinja2
# All common imports and utilities are defined in the parent template

app = FastAPI(title="File Handler MCP Server", version="1.0.0")


@app.on_event("startup")
async def startup_event():
    """Initialize services on server startup"""
    if hasattr(file_manager, 'initialize'):
        await file_manager.initialize()
        logger.info("FileManager initialized")
    logger.info("File Handler MCP Server started")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on server shutdown"""
    logger.info("File Handler MCP Server stopped")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "File Handler MCP Server",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "server": "file_handler"}


@app.post("/mcp/v1/initialize")
async def initialize(request: Request):
    """Initialize MCP session"""
    body = await request.json()
    return {
        "protocolVersion": "1.0",
        "serverInfo": {
            "name": "file_handler-mcp-server",
            "version": "1.0.0"
        },
        "capabilities": {
            "tools": {}
        }
    }


@app.post("/mcp/v1/tools/list")
async def list_tools(request: Request):
    """List available MCP tools"""
    try:
        # Get tools metadata
        tools_list = []
        for tool in MCP_TOOLS:
            tools_list.append({
                "name": tool["name"],
                "description": tool.get("description", ""),
                "inputSchema": tool.get("inputSchema", {})
            })

        return JSONResponse(content={
            "result": {
                "tools": tools_list
            }
        })
    except Exception as e:
        logger.error(f"Error listing tools: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(e)}}
        )


@app.post("/mcp/v1/tools/call")
async def call_tool(request: Request):
    """Execute an MCP tool"""
    try:
        data = await request.json()
        tool_name = data.get("name")
        arguments = data.get("arguments", {})

        logger.info(f"Tool call: {tool_name} with args: {arguments}")

        implementation_info = get_tool_implementation(tool_name)
        if not implementation_info:
            return JSONResponse(
                status_code=404,
                content={"error": {"message": f"Unknown tool: {tool_name}"}}
            )

        # Get service instance by class name
        service_class = implementation_info["service_class"]
        service_instance = get_service_instance(service_class)

        if not service_instance:
            return JSONResponse(
                status_code=500,
                content={"error": {"message": f"Service not available: {service_class}"}}
            )

        # Get the handler function (handle_<tool_name>)
        handler_name = f"handle_{tool_name}"
        handler = globals().get(handler_name)
        if not handler:
            return JSONResponse(
                status_code=500,
                content={"error": {"message": f"Handler not found: {handler_name}"}}
            )

        # Call the handler function directly with the arguments
        result = await handler(arguments)

        response_content = format_tool_result(result)
        return JSONResponse(content=build_mcp_content(response_content))

    except aiohttp.ClientResponseError as e:
        # HTTP-level errors from external API calls
        logger.error(f"API error executing tool {tool_name}: {e.status} {e.message}", exc_info=True)
        if e.status == 401:
            return JSONResponse(
                status_code=401,
                content={"error": {"code": "AUTH_EXPIRED", "message": "Access token expired or invalid. Re-authentication required."}}
            )
        elif e.status == 403:
            return JSONResponse(
                status_code=403,
                content={"error": {"code": "PERMISSION_DENIED", "message": "Insufficient permissions for this operation."}}
            )
        elif e.status == 404:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "NOT_FOUND", "message": f"Resource not found: {e.message}"}}
            )
        elif e.status == 429:
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "RATE_LIMITED", "message": "API rate limit exceeded. Please retry later."}}
            )
        else:
            return JSONResponse(
                status_code=e.status,
                content={"error": {"code": "API_ERROR", "message": str(e)}}
            )
    except HTTPException as e:
        # FastAPI HTTP exceptions (pass through)
        logger.error(f"HTTP error executing tool {tool_name}: {e.status_code} {e.detail}", exc_info=True)
        return JSONResponse(
            status_code=e.status_code,
            content={"error": {"code": "HTTP_ERROR", "message": e.detail}}
        )
    except Exception as e:
        # Check for auth-related keywords in generic exceptions
        error_str = str(e).lower()
        if "401" in error_str or "unauthorized" in error_str or "token expired" in error_str:
            logger.error(f"Auth error executing tool {tool_name}: {e}", exc_info=True)
            return JSONResponse(
                status_code=401,
                content={"error": {"code": "AUTH_EXPIRED", "message": "Authentication failed. Re-authentication required."}}
            )
        elif "403" in error_str or "forbidden" in error_str or "permission" in error_str:
            logger.error(f"Permission error executing tool {tool_name}: {e}", exc_info=True)
            return JSONResponse(
                status_code=403,
                content={"error": {"code": "PERMISSION_DENIED", "message": "Permission denied."}}
            )

        # General internal error
        logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": str(e)}}
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)