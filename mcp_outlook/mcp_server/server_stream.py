"""
Streamable HTTP MCP Server for Outlook MCP Server

Refactored to use the official MCP Python SDK's Streamable HTTP transport
(spec: MCP 2025-03-26). Mounts `StreamableHTTPSessionManager` on a Starlette
app served by uvicorn. Provides spec-compliant single-endpoint `/mcp` with
POST + GET + DELETE, `Mcp-Session-Id` header session management, and the
`Accept: application/json, text/event-stream` negotiation handled by the SDK.

Tool handlers, env loading, BOM stripping, and YAML tool-definition loading
are preserved from the previous implementation (mirroring `server_stdio.py`).
"""
import json
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
server_module_dir = os.path.join(grandparent_dir, "mcp_outlook")
if os.path.isdir(server_module_dir):
    sys.path.insert(0, server_module_dir)
sys.path.insert(0, grandparent_dir)
sys.path.insert(0, parent_dir)

# Project imports
from mcp_outlook.outlook_types import ExcludeParams, FilterParams, SelectParams
from mcp_outlook.graph_mail_client import ProcessingMode, QueryMethod
from session.auth_database import AuthDatabase

# Configure logging (HTTP transport: stdout is fine for logs)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def get_default_user_email() -> Optional[str]:
    """Get default user email from auth.db when not provided."""
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
        yaml_path = Path(current_dir).parent.parent / "mcp_editor" / "mcp_outlook" / "tool_definition_templates.yaml"
        if not yaml_path.exists():
            yaml_path = Path(current_dir).parent.parent / "mcp_editor" / "mcp_outlook" / "tool_definition_templates.yaml"

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
from mcp_outlook.outlook_service import MailService

mail_service = MailService()


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
# Tool handler functions (copied verbatim from stdio implementation)
# ============================================================

async def handle_mail_list_period(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle mail_list_period tool call"""
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    DatePeriodFilter_sig = args.get("DatePeriodFilter")
    DatePeriodFilter = DatePeriodFilter_sig if DatePeriodFilter_sig is not None else None

    DatePeriodFilter_sig_defaults = {}
    DatePeriodFilter_data = merge_param_data({}, DatePeriodFilter, DatePeriodFilter_sig_defaults)
    if DatePeriodFilter_data is not None:
        DatePeriodFilter = FilterParams(**DatePeriodFilter_data)
    else:
        DatePeriodFilter = None

    call_args = {
        "user_email": user_email,
        "filter_params": DatePeriodFilter,
        "client_filter": ExcludeParams(**{
            'exclude_from_address': [
                'block@krs.co.kr',
                'no-reply@teams.mail.microsoft',
                'reminders@facebookmail.com',
                'no-reply@sharepointonline.com'
            ]
        }),
        "select_params": SelectParams(**{
            'bcc_recipients': False, 'body': False, 'body_preview': True,
            'categories': False, 'cc_recipients': False, 'change_key': False,
            'conversation_id': False, 'conversation_index': False,
            'created_date_time': False, 'flag': False, 'from_recipient': True,
            'has_attachments': True, 'id': True, 'importance': False,
            'inference_classification': False, 'internet_message_headers': False,
            'internet_message_id': True, 'is_delivery_receipt_requested': False,
            'is_draft': False, 'is_read': False, 'is_read_receipt_requested': False,
            'last_modified_date_time': False, 'parent_folder_id': False,
            'received_date_time': False, 'reply_to': False, 'sender': True,
            'sent_date_time': False, 'subject': True, 'to_recipients': False,
            'unique_body': False, 'web_link': False
        }),
        "top": 500,
    }
    return await mail_service.query_mail_list(**call_args)


async def handle_mail_list_keyword(args: Dict[str, Any]) -> Dict[str, Any]:
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    search_keywords = args["search_keywords"]
    top_sig = args.get("top")
    top = top_sig if top_sig is not None else 50

    call_args = {
        "user_email": user_email,
        "search_term": search_keywords,
        "top": top,
    }
    return await mail_service.fetch_search(**call_args)


async def handle_mail_query_if_emaidID(args: Dict[str, Any]) -> Dict[str, Any]:
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    message_ids = args["message_ids"]
    return await mail_service.batch_and_fetch(user_email=user_email, message_ids=message_ids)


async def handle_mail_attachment_meta(args: Dict[str, Any]) -> Dict[str, Any]:
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    message_ids = args["message_ids"]
    return await mail_service.fetch_attachments_metadata(user_email=user_email, message_ids=message_ids)


async def handle_mail_attachment_download(args: Dict[str, Any]) -> Dict[str, Any]:
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    message_attachment_ids = args["message_attachment_ids"]
    save_directory = args.get("save_directory") or 'downloads'
    flat_folder = args.get("flat_folder") if args.get("flat_folder") is not None else 'disabled'
    skip_duplicates = args.get("skip_duplicates") if args.get("skip_duplicates") is not None else 'enabled'
    save_file = args.get("save_file") if args.get("save_file") is not None else 'enabled'
    storage_type = args.get("storage_type") or 'local'
    convert_to_txt = args.get("convert_to_txt") if args.get("convert_to_txt") is not None else 'disabled'
    include_body = args.get("include_body") if args.get("include_body") is not None else 'enabled'
    onedrive_folder = args.get("onedrive_folder") or '/Attachments'

    skip_duplicates = convert_enabled_to_bool(skip_duplicates)
    save_file = convert_enabled_to_bool(save_file)
    flat_folder = convert_enabled_to_bool(flat_folder)
    convert_to_txt = convert_enabled_to_bool(convert_to_txt)
    include_body = convert_enabled_to_bool(include_body)

    call_args = {
        "user_email": user_email,
        "message_attachment_ids": message_attachment_ids,
        "save_directory": save_directory,
        "flat_folder": flat_folder,
        "skip_duplicates": skip_duplicates,
        "save_file": save_file,
        "storage_type": storage_type,
        "convert_to_txt": convert_to_txt,
        "include_body": include_body,
        "onedrive_folder": onedrive_folder,
    }
    return await mail_service.download_attachments(**call_args)


async def handle_mail_fetch_filter(args: Dict[str, Any]) -> Dict[str, Any]:
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    filter_params = args.get("filter_params")
    exclude_params = args.get("exclude_params")

    filter_params_sig_defaults = {'test_field': 'test_value'}
    filter_params_data = merge_param_data({}, filter_params, filter_params_sig_defaults)
    filter_params = FilterParams(**filter_params_data) if filter_params_data is not None else None

    exclude_params_data = merge_param_data({}, exclude_params, {})
    exclude_params = ExcludeParams(**exclude_params_data) if exclude_params_data is not None else None

    return await mail_service.fetch_filter(
        user_email=user_email,
        filter_params=filter_params,
        exclude_params=exclude_params,
    )


async def handle_mail_fetch_search(args: Dict[str, Any]) -> Dict[str, Any]:
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    search_term = args["search_term"]
    select_params = args.get("select_params")
    top = args.get("top") if args.get("top") is not None else 50

    select_params_data = merge_param_data({}, select_params, {})
    select_params = SelectParams(**select_params_data) if select_params_data is not None else None

    return await mail_service.fetch_search(
        user_email=user_email,
        search_term=search_term,
        select_params=select_params,
        top=top,
    )


async def handle_mail_process_with_download(args: Dict[str, Any]) -> Dict[str, Any]:
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    filter_params = args.get("filter_params")
    search_term = args.get("search_term")
    top = args.get("top") if args.get("top") is not None else 50
    save_directory = args.get("save_directory")

    filter_params_data = merge_param_data({}, filter_params, {})
    filter_params = FilterParams(**filter_params_data) if filter_params_data is not None else None

    return await mail_service.process_with_download(
        user_email=user_email,
        filter_params=filter_params,
        search_term=search_term,
        top=top,
        save_directory=save_directory,
    )


async def handle_mail_query_url(args: Dict[str, Any]) -> Dict[str, Any]:
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    url = args["url"]
    filter_params = args.get("filter_params")
    top = args.get("top") if args.get("top") is not None else 50

    filter_params_data = merge_param_data({}, filter_params, {})
    filter_params = FilterParams(**filter_params_data) if filter_params_data is not None else None

    return await mail_service.fetch_url(
        user_email=user_email,
        url=url,
        filter_params=filter_params,
        top=top,
        select=SelectParams(**{
            'body_preview': True,
            'created_date_time': True,
            'from_recipient': True,
            'id': True,
            'received_date_time': True,
        }),
    )


async def handle_test_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    filter_params = args.get("filter_params")
    exclude_params = args.get("exclude_params")
    select_params = args.get("select_params")
    client_filter = args.get("client_filter")
    top = args.get("top") if args.get("top") is not None else 50

    filter_params_data = merge_param_data({}, filter_params, {})
    filter_params = FilterParams(**filter_params_data) if filter_params_data is not None else None
    exclude_params_data = merge_param_data({}, exclude_params, {})
    exclude_params = ExcludeParams(**exclude_params_data) if exclude_params_data is not None else None
    select_params_data = merge_param_data({}, select_params, {})
    select_params = SelectParams(**select_params_data) if select_params_data is not None else None
    client_filter_data = merge_param_data({}, client_filter, {})
    client_filter = ExcludeParams(**client_filter_data) if client_filter_data is not None else None

    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}

    return await mail_service.fetch_filter(
        filter_params=filter_params,
        exclude_params=exclude_params,
        select_params=select_params,
        client_filter=client_filter,
        top=top,
        user_email=user_email,
    )


# ============================================================
# Tool dispatch
# ============================================================

TOOL_HANDLERS = {
    "mail_list_period": handle_mail_list_period,
    "mail_list_keyword": handle_mail_list_keyword,
    "mail_query_if_emaidID": handle_mail_query_if_emaidID,
    "mail_attachment_meta": handle_mail_attachment_meta,
    "mail_attachment_download": handle_mail_attachment_download,
    "mail_fetch_filter": handle_mail_fetch_filter,
    "mail_fetch_search": handle_mail_fetch_search,
    "mail_process_with_download": handle_mail_process_with_download,
    "mail_query_url": handle_mail_query_url,
    "test_handler": handle_test_handler,
}


def apply_schema_defaults(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Apply default values from inputSchema to arguments if not provided."""
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
from starlette.routing import Mount, Route
from starlette.responses import JSONResponse
from starlette.requests import Request as StarletteRequest


def _build_tool_objects() -> List[mcp_types.Tool]:
    """Convert YAML-loaded tool dicts to mcp.types.Tool objects."""
    tools: List[mcp_types.Tool] = []
    for raw in MCP_TOOLS:
        name = raw.get("name")
        if not name:
            continue
        # jsonschema-style inputSchema must be an object
        input_schema = raw.get("inputSchema") or {"type": "object", "properties": {}}
        if "type" not in input_schema:
            input_schema = {"type": "object", **input_schema}
        description = raw.get("description") or ""
        tools.append(
            mcp_types.Tool(
                name=name,
                description=description,
                inputSchema=input_schema,
            )
        )
    return tools


def build_mcp_server() -> MCPServer:
    """Construct an MCP lowlevel Server with tools registered."""
    server: MCPServer = MCPServer(name="outlook", version="1.0.0")

    tool_objects = _build_tool_objects()

    @server.list_tools()
    async def _list_tools() -> List[mcp_types.Tool]:
        return tool_objects

    # validate_input=False — the existing handlers accept the YAML-converted
    # enabled/disabled string-enum form, and inputSchema may not match exactly
    # for all internal/factored params; behavior matches server_stdio.py.
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
            return [mcp_types.TextContent(type="text", text=json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False))]

        # auth_required: surface as text content; SDK will wrap into CallToolResult
        if isinstance(result, dict) and result.get("status") == "auth_required":
            return [mcp_types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        # Existing handlers may return a dict that already contains MCP-style content.
        if isinstance(result, dict) and "content" in result and isinstance(result["content"], list):
            # Pass through as TextContent items (assume text payloads)
            blocks: List[mcp_types.TextContent] = []
            for item in result["content"]:
                if isinstance(item, dict) and item.get("type") == "text":
                    blocks.append(mcp_types.TextContent(type="text", text=item.get("text", "")))
                else:
                    blocks.append(mcp_types.TextContent(type="text", text=json.dumps(item, ensure_ascii=False)))
            return blocks

        if isinstance(result, str):
            return [mcp_types.TextContent(type="text", text=result)]

        return [mcp_types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

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
        return JSONResponse({
            "status": "healthy",
            "server": "outlook",
            "protocol": "streamable-http",
            "version": "1.0.0",
            "tool_count": len(MCP_TOOLS),
        })

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            # Initialize services once at startup
            if hasattr(mail_service, "initialize"):
                try:
                    await mail_service.initialize()
                    logger.info("MailService initialized")
                except Exception as e:
                    logger.warning(f"MailService initialize() failed: {e}")
            logger.info(f"Outlook MCP Streamable HTTP server ready with {len(MCP_TOOLS)} tools")
            yield

    # NOTE: Use Route(path="/mcp", endpoint=<ASGI app>) — the same trick the
    # MCP SDK's FastMCP uses. A Route with an ASGI-callable endpoint dispatches
    # all HTTP methods (GET/POST/DELETE) to that callable without forcing a
    # trailing-slash redirect (which would otherwise happen with Mount).
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


def run(host: str = "0.0.0.0", port: int = 8091) -> None:
    import uvicorn
    logger.info(f"Starting Outlook MCP Streamable HTTP server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    port = int(os.environ.get("MCP_SERVER_PORT", 8091))
    run(host="0.0.0.0", port=port)
