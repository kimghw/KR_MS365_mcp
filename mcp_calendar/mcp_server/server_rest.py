"""
FastAPI MCP Server for Calendar MCP Server
Routes MCP protocol requests to service functions
Generated from universal template with registry data and protocol selection
"""
import json
import yaml
from pathlib import Path
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

# Add paths for imports (generalized for all servers)
server_module_dir = os.path.join(grandparent_dir, "mcp_calendar")
if os.path.isdir(server_module_dir):
    sys.path.insert(0, server_module_dir)  # For server-specific relative imports
sys.path.insert(0, grandparent_dir)  # For session module and package imports
sys.path.insert(0, parent_dir)  # For direct module imports

# Import types dynamically based on type_info
from mcp_calendar.calendar_types import EventFilterParams, EventSelectParams

# 공통 런타임 (바인드 정책 / 사용자 선택 / 입력 검증 / 오류 계약 / lifecycle)
from mcp_common.net import resolve_bind_host
from mcp_common.errors import ToolExecutionError
from mcp_common.user_resolver import resolve_user_email
from mcp_common.runtime import (
    ToolRuntime,
    ServiceLifecycle,
    build_health_payload,
    health_status_code,
)

SERVER_NAME = "calendar"
SERVER_VERSION = "1.0.0"
DEFAULT_PORT = 5002


def _resolve_user_email(args: Dict[str, Any]) -> str:
    """요청 인자의 user_email 을 공통 정책으로 확정 (미인증이면 예외)."""
    return resolve_user_email(args.get("user_email"), required=True)


# Load tool definitions from YAML (Single Source of Truth)
def _convert_boolean_schema_to_enabled_disabled(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Convert boolean type properties to enabled/disabled enum for OpenAI compatibility.

    OpenAI API does not support boolean type in function parameters.
    This converts at runtime:
        type: boolean, default: true  -> type: string, enum: ["enabled", "disabled"], default: "enabled"
        type: boolean, default: false -> type: string, enum: ["enabled", "disabled"], default: "disabled"
    """
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
    """Load MCP tools from tool_definition_templates.yaml and convert boolean types.

    YAML path resolution order:
    1. Environment variable MCP_YAML_PATH (for explicit override)
    2. mcp_editor/mcp_{profile_name}/tool_definition_templates.yaml (profile-specific)
       - Uses calendar which is set correctly at generation time for reused profiles
    3. Fallback to mcp_editor/mcp_{server_name}/tool_definition_templates.yaml (original service)
    """
    # Option 1: Environment variable override
    yaml_path_str = os.environ.get("MCP_YAML_PATH")
    if yaml_path_str:
        yaml_path = Path(yaml_path_str)
    else:
        # Option 2: Profile-specific YAML path (supports reused profiles like outlook_read)
        yaml_path = Path(current_dir).parent.parent / "mcp_editor" / "mcp_calendar" / "tool_definition_templates.yaml"
        if not yaml_path.exists():
            # Option 3: Fallback to original server name (for backwards compatibility)
            yaml_path = Path(current_dir).parent.parent / "mcp_editor" / "mcp_calendar" / "tool_definition_templates.yaml"

    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            tools = data.get("tools", [])

            # Convert boolean types to enabled/disabled for OpenAI compatibility
            for tool in tools:
                if 'inputSchema' in tool:
                    tool['inputSchema'] = _convert_boolean_schema_to_enabled_disabled(tool['inputSchema'])

            return tools
    raise FileNotFoundError(f"Tool definition YAML not found: {yaml_path}")

MCP_TOOLS = _load_mcp_tools()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================
# Boolean Parameter Conversion (enabled/disabled <-> bool)
# ============================================================
# OpenAI API does not support boolean type in function parameters.
# We use "enabled"/"disabled" strings externally and convert to bool internally.

def convert_enabled_to_bool(value: Any) -> bool:
    """Convert enabled/disabled string to boolean.

    Args:
        value: "enabled", "disabled", True, False, or None

    Returns:
        True if enabled, False otherwise
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() == "enabled"
    return False


def convert_bool_to_enabled(value: bool) -> str:
    """Convert boolean to enabled/disabled string.

    Args:
        value: Boolean value

    Returns:
        "enabled" if True, "disabled" if False
    """
    return "enabled" if value else "disabled"

# Import service classes (unique)
# ============================================================
# 기본 서버: calendar
# ============================================================
from mcp_calendar.calendar_service import CalendarService

# Create service instances
calendar_service = CalendarService()

# ============================================================
# Common MCP protocol utilities (shared across protocols)
# ============================================================

SUPPORTED_PROTOCOLS = {"rest", "stdio", "stream"}

# Pre-computed tool -> implementation mapping
TOOL_IMPLEMENTATIONS = {
    "calendar_view": {
        "service_class": "CalendarService",
        "method": "calendar_view"
    },
    "list_events": {
        "service_class": "CalendarService",
        "method": "list_events"
    },
    "get_event": {
        "service_class": "CalendarService",
        "method": "get_event"
    },
    "create_event": {
        "service_class": "CalendarService",
        "method": "create_event"
    },
    "update_event": {
        "service_class": "CalendarService",
        "method": "update_event"
    },
    "delete_event": {
        "service_class": "CalendarService",
        "method": "delete_event"
    },
    "get_schedule": {
        "service_class": "CalendarService",
        "method": "get_schedule"
    },
}

# Pre-computed service class -> instance mapping
SERVICE_INSTANCES = {
    "CalendarService": calendar_service,
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
# Service Factors Support (Internal + Signature Defaults)
# ============================================================
# Service factors are extracted at runtime from MCP_TOOLS mcp_service_factors
# Structure: { tool_name: { 'internal': {...}, 'signature_defaults': {...} } }


def _extract_service_factors(tools: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Extract service factors from mcp_service_factors in tool definitions at runtime.

    Returns:
        Dict with structure:
        {
            tool_name: {
                'internal': { factor_name: {...}, ... },
                'signature_defaults': { factor_name: {...}, ... }
            }
        }
    """
    service_factors = {}

    for tool in tools:
        tool_name = tool.get('name', '')
        mcp_service_factors = tool.get('mcp_service_factors', {})

        tool_factors = {
            'internal': {},
            'signature_defaults': {}
        }

        for factor_name, factor_data in mcp_service_factors.items():
            source = factor_data.get('source', '')

            # Only process 'internal' and 'signature_defaults' sources
            if source not in ('internal', 'signature_defaults'):
                continue

            # Support both 'type' (new) and 'baseModel' (legacy) field names
            factor_type = factor_data.get('type') or factor_data.get('baseModel', '')

            # targetParam handling
            target_param = factor_data.get('targetParam', factor_name)

            # Get parameters - handle both list format (new) and dict format (legacy)
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
                params_dict = raw_params  # Already a dict

            # Extract default values from parameters
            default_values = {}
            for param_name, param_def in params_dict.items():
                if 'default' in param_def:
                    default_values[param_name] = param_def['default']

            # Build the factor structure
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

        # Only add if there are any factors
        if tool_factors['internal'] or tool_factors['signature_defaults']:
            service_factors[tool_name] = tool_factors

    return service_factors


def _extract_internal_args(tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract internal args from service factors (legacy compatibility)."""
    service_factors = _extract_service_factors(tools)

    # Convert to legacy internal_args format
    internal_args = {}
    for tool_name, factors in service_factors.items():
        tool_internal = {}
        for factor_name, factor_info in factors.get('internal', {}).items():
            tool_internal[factor_name] = {
                'targetParam': factor_info['targetParam'],
                'type': factor_info['type'],
                'value': factor_info['value'],
                'original_schema': factor_info['original_schema']
            }
        if tool_internal:
            internal_args[tool_name] = tool_internal

    return internal_args


# MCP_TOOLS already loaded from YAML above (contains mcp_service_factors)
# Use it directly for service factors extraction

# Extract at module load time from MCP_TOOLS (which have mcp_service_factors)
SERVICE_FACTORS = _extract_service_factors(MCP_TOOLS)
INTERNAL_ARGS = _extract_internal_args(MCP_TOOLS)

# Build INTERNAL_ARG_TYPES dynamically based on imported types
INTERNAL_ARG_TYPES = {}
if 'EventFilterParams' in globals():
    INTERNAL_ARG_TYPES['EventFilterParams'] = EventFilterParams
if 'EventSelectParams' in globals():
    INTERNAL_ARG_TYPES['EventSelectParams'] = EventSelectParams


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


def get_signature_defaults(tool_name: str, factor_name: str) -> dict:
    """Get signature default values for a tool factor.

    Signature defaults are used to provide default values for user input parameters.
    These are applied when the user doesn't provide a value for an optional parameter.
    """
    tool_factors = SERVICE_FACTORS.get(tool_name, {})
    sig_defaults = tool_factors.get('signature_defaults', {})
    factor_info = sig_defaults.get(factor_name, {})
    return factor_info.get('value', {})


def apply_signature_defaults(signature_data: dict, tool_name: str, factor_name: str) -> dict:
    """Apply signature defaults to user-provided data.

    Merge order (priority high to low):
    1. User signature values (non-None)
    2. Signature defaults
    3. Schema defaults
    """
    if signature_data is None:
        signature_data = {}

    # Get signature defaults
    defaults = get_signature_defaults(tool_name, factor_name)
    if not defaults:
        return signature_data

    # Merge: defaults first, then user values override
    merged = {**defaults}
    for key, value in signature_data.items():
        if value is not None:
            merged[key] = value

    return merged


def merge_with_priority(signature_value, signature_defaults_value, internal_value):
    """Merge values with priority: Signature > Signature Defaults > Internal.

    Args:
        signature_value: User-provided value from LLM
        signature_defaults_value: Default value for user input
        internal_value: Hidden system value

    Returns:
        Final merged value with correct priority
    """
    # If all are None, return None
    if signature_value is None and signature_defaults_value is None and internal_value is None:
        return None

    # If signature has value, use it (possibly merged with defaults for objects)
    if signature_value is not None:
        # For dict/object types, merge with signature_defaults
        if isinstance(signature_value, dict):
            base = {}
            if internal_value and isinstance(internal_value, dict):
                base = {**internal_value}
            if signature_defaults_value and isinstance(signature_defaults_value, dict):
                base = {**base, **signature_defaults_value}
            return {**base, **signature_value}
        return signature_value

    # If signature is None but signature_defaults has value
    if signature_defaults_value is not None:
        if isinstance(signature_defaults_value, dict):
            base = {}
            if internal_value and isinstance(internal_value, dict):
                base = {**internal_value}
            return {**base, **signature_defaults_value}
        return signature_defaults_value

    # Fall back to internal value
    return internal_value


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


def merge_param_data(internal_data: dict, runtime_data, signature_defaults: dict = None):
    """Merge parameter data with priority: runtime > signature_defaults > internal.

    Args:
        internal_data: Internal override data (lowest priority, not used for signature params)
        runtime_data: User-provided runtime data (highest priority)
        signature_defaults: Default values for signature params (middle priority)
    """
    # Start with internal data as base (if any)
    result = dict(internal_data) if internal_data else {}

    # Apply signature defaults (overrides internal)
    if signature_defaults:
        result = {**result, **signature_defaults}

    # Apply runtime data (highest priority, overrides all)
    if runtime_data:
        if isinstance(runtime_data, dict):
            result = {**result, **runtime_data}
        else:
            return runtime_data

    return result if result else None

# Tool handler functions

async def handle_calendar_view(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle calendar_view tool call"""

    # ========================================
    # Step 1: Signature 파라미터 수신
    # - LLM으로부터 전달받은 인자 추출
    # ========================================
    user_email = _resolve_user_email(args)
    start_datetime = args["start_datetime"]
    end_datetime = args["end_datetime"]

    # ========================================
    # Step 2: 서비스 호출 인자 구성
    # ========================================
    call_args = {}
    call_args["user_email"] = user_email
    call_args["start_datetime"] = start_datetime
    call_args["end_datetime"] = end_datetime

    # ========================================
    # Step 3: 서비스 메서드 호출
    # ========================================
    return await calendar_service.calendar_view(**call_args)

async def handle_get_event(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle get_event tool call"""

    # ========================================
    # Step 1: Signature 파라미터 수신
    # - LLM으로부터 전달받은 인자 추출
    # ========================================
    user_email = _resolve_user_email(args)
    event_id = args["event_id"]

    # ========================================
    # Step 2: 서비스 호출 인자 구성
    # ========================================
    call_args = {}
    call_args["user_email"] = user_email
    call_args["event_id"] = event_id

    # ========================================
    # Step 3: 서비스 메서드 호출
    # ========================================
    return await calendar_service.get_event(**call_args)

async def handle_create_event(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle create_event tool call"""

    # ========================================
    # Step 1: Signature 파라미터 수신
    # - LLM으로부터 전달받은 인자 추출
    # ========================================
    user_email = _resolve_user_email(args)
    subject = args["subject"]
    start = args["start"]
    end = args["end"]
    body_sig = args.get("body")
    body = body_sig if body_sig is not None else None
    location_sig = args.get("location")
    location = location_sig if location_sig is not None else None

    # ========================================
    # Step 2: 서비스 호출 인자 구성
    # ========================================
    call_args = {}
    call_args["user_email"] = user_email
    call_args["subject"] = subject
    call_args["start"] = start
    call_args["end"] = end
    call_args["body"] = body
    call_args["location"] = location

    # ========================================
    # Step 3: 서비스 메서드 호출
    # ========================================
    return await calendar_service.create_event(**call_args)

async def handle_delete_event(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle delete_event tool call"""

    # ========================================
    # Step 1: Signature 파라미터 수신
    # - LLM으로부터 전달받은 인자 추출
    # ========================================
    user_email = _resolve_user_email(args)
    event_id = args["event_id"]

    # ========================================
    # Step 2: 서비스 호출 인자 구성
    # ========================================
    call_args = {}
    call_args["user_email"] = user_email
    call_args["event_id"] = event_id

    # ========================================
    # Step 3: 서비스 메서드 호출
    # ========================================
    return await calendar_service.delete_event(**call_args)

async def handle_list_events(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle list_events tool call"""

    # ========================================
    # Step 1: Signature 파라미터 수신
    # - LLM으로부터 전달받은 인자 추출
    # ========================================
    user_email = _resolve_user_email(args)
    top_sig = args.get("top")
    top = top_sig if top_sig is not None else 50
    orderby_sig = args.get("orderby")
    orderby = orderby_sig if orderby_sig is not None else None

    # ========================================
    # Step 2: 서비스 호출 인자 구성
    # ========================================
    call_args = {}
    call_args["user_email"] = user_email
    call_args["top"] = top
    call_args["orderby"] = orderby

    # ========================================
    # Step 3: 서비스 메서드 호출
    # ========================================
    return await calendar_service.list_events(**call_args)

async def handle_update_event(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle update_event tool call"""

    # ========================================
    # Step 1: Signature 파라미터 수신
    # - LLM으로부터 전달받은 인자 추출
    # ========================================
    user_email = _resolve_user_email(args)
    event_id = args["event_id"]
    subject = args.get("subject")
    start = args.get("start")
    end = args.get("end")
    body = args.get("body")
    location = args.get("location")

    # ========================================
    # Step 2: 서비스 호출 인자 구성
    # ========================================
    call_args = {}
    call_args["user_email"] = user_email
    call_args["event_id"] = event_id
    call_args["subject"] = subject
    call_args["start"] = start
    call_args["end"] = end
    call_args["body"] = body
    call_args["location"] = location

    # ========================================
    # Step 3: 서비스 메서드 호출
    # ========================================
    return await calendar_service.update_event(**call_args)

async def handle_get_schedule(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle get_schedule tool call"""

    # ========================================
    # Step 1: Signature 파라미터 수신
    # - LLM으로부터 전달받은 인자 추출
    # ========================================
    user_email = _resolve_user_email(args)
    schedules = args["schedules"]
    start_time = args["start_time"]
    end_time = args["end_time"]
    interval_sig = args.get("availability_view_interval")
    availability_view_interval = interval_sig if interval_sig is not None else 30

    # ========================================
    # Step 2: 서비스 호출 인자 구성
    # ========================================
    call_args = {}
    call_args["user_email"] = user_email
    call_args["schedules"] = schedules
    call_args["start_time"] = start_time
    call_args["end_time"] = end_time
    call_args["availability_view_interval"] = availability_view_interval

    # ========================================
    # Step 3: 서비스 메서드 호출
    # ========================================
    return await calendar_service.get_schedule(**call_args)


# ============================================================
# 공통 런타임 (기본값 주입 + 입력 검증 + 오류 정규화 + 서비스 lifecycle)
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

RUNTIME = ToolRuntime(SERVER_NAME, MCP_TOOLS, TOOL_HANDLERS)
LIFECYCLE = ServiceLifecycle(SERVER_NAME, [calendar_service])

# ============================================================
# REST API Protocol Handlers for MCP
# ============================================================
# Note: This template is included by universal_server_template.jinja2
# All common imports and utilities are defined in the parent template

app = FastAPI(title="Calendar MCP Server", version=SERVER_VERSION)


@app.on_event("startup")
async def startup_event():
    """Initialize services on server startup"""
    await LIFECYCLE.startup()
    if LIFECYCLE.errors:
        # 기동은 계속하되 /health 가 degraded/503 을 보고한다
        logger.error(f"Service startup errors: {LIFECYCLE.errors}")
    logger.info("Calendar MCP Server started")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on server shutdown"""
    await LIFECYCLE.shutdown()
    logger.info("Calendar MCP Server stopped")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "Calendar MCP Server",
        "version": "1.0.0"
    }


@app.post("/")
async def mcp_request_root(request: Request):
    """MCP Streamable HTTP - Root endpoint (alias for /mcp/v1)"""
    return await mcp_request(request)


@app.get("/health")
async def health_check():
    """Health check endpoint

    초기화 실패 시 degraded 와 503 을 반환한다 (항상 healthy 로 응답하지 않는다).
    """
    payload = build_health_payload(
        SERVER_NAME, RUNTIME, LIFECYCLE, version=SERVER_VERSION, protocol="rest"
    )
    return JSONResponse(content=payload, status_code=health_status_code(payload))


@app.post("/mcp/v1")
async def mcp_request(request: Request):
    """MCP Streamable HTTP 단일 엔드포인트 - JSON-RPC 2.0"""
    try:
        data = await request.json()
    except Exception as e:
        # 요청 본문 자체가 깨진 경우는 프로토콜 오류 → HTTP 400
        logger.error(f"Invalid JSON-RPC request body: {e}")
        return JSONResponse(
            status_code=400,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
        )

    # 구문상 유효하지만 object 가 아닌 본문([], 배치 배열, 스칼라)은 data.get(...) 에서
    # AttributeError 를 낸다. 아래 except 절이 다시 data.get('id') 를 호출하면 두 번째
    # AttributeError 가 잡히지 않고 원시 500 이 나가므로, 여기서 먼저 걸러 낸다.
    if not isinstance(data, dict):
        return JSONResponse(
            status_code=400,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}},
        )

    try:
        method = data.get('method', '')
        request_id = data.get('id')
        params = data.get('params', {})

        logger.info(f"MCP Request: method={method}, id={request_id}")

        if method == 'initialize':
            return await _handle_initialize(data)
        elif method == 'tools/list':
            return await _handle_tools_list(data)
        elif method == 'tools/call':
            return await _handle_tools_call(data)
        elif method == 'notifications/initialized':
            return JSONResponse(status_code=204, content=None)
        elif method == 'ping':
            return JSONResponse(content={
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {}
            })
        else:
            # 프로토콜 오류(메서드 없음) → HTTP 404 + JSON-RPC error
            return JSONResponse(
                status_code=404,
                content={"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
            )
    except Exception as e:
        logger.error(f"Error in MCP request: {e}", exc_info=True)
        safe_id = data.get('id') if isinstance(data, dict) else None
        return JSONResponse(
            status_code=500,
            content={"jsonrpc": "2.0", "id": safe_id, "error": {"code": -32603, "message": str(e)}}
        )


async def _handle_initialize(data: dict):
    """내부 initialize 처리"""
    request_id = data.get('id')
    params = data.get('params', {})
    client_info = params.get('clientInfo', {})
    logger.info(f"Client connected: {client_info.get('name', 'unknown')}")

    return JSONResponse(content={
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "calendar",
                "version": "1.0.0"
            }
        }
    })


async def _handle_tools_list(data: dict):
    """내부 tools/list 처리"""
    request_id = data.get('id')

    tools_list = []
    for tool in RUNTIME.tools:
        tools_list.append({
            "name": tool["name"],
            "description": tool.get("description", ""),
            "inputSchema": RUNTIME.input_schema(tool["name"])
        })

    return JSONResponse(content={
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "tools": tools_list
        }
    })


async def _handle_tools_call(data: dict):
    """내부 tools/call 처리"""
    request_id = data.get('id')
    params = data.get('params', {})
    tool_name = params.get('name')
    arguments = params.get('arguments', {})

    if not tool_name:
        # 잘못된 요청 파라미터는 프로토콜 오류 → HTTP 400
        return JSONResponse(
            status_code=400,
            content={"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Tool name is required"}}
        )

    # 기본값 주입 / 입력 검증 / 핸들러 호출 / 오류 정규화는 ToolRuntime 이 담당한다.
    try:
        content = await RUNTIME.call(tool_name, arguments)
    except ToolExecutionError as exc:
        logger.error(f"Tool {tool_name} failed: {exc}")
        # 도구 실행 실패는 프로토콜 오류가 아니다 → HTTP 200 + result.isError
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": str(exc)}],
                "isError": True,
            }
        })

    return JSONResponse(content={
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": content
        }
    })


@app.post("/mcp/v1/initialize")
async def initialize(request: Request):
    """Initialize MCP session - JSON-RPC 2.0"""
    data = await request.json()
    return await _handle_initialize(data)


@app.post("/mcp/v1/tools/list")
async def list_tools(request: Request):
    """List available MCP tools - JSON-RPC 2.0"""
    data = await request.json()
    return await _handle_tools_list(data)


@app.post("/mcp/v1/tools/call")
async def call_tool(request: Request):
    """Execute an MCP tool - JSON-RPC 2.0"""
    data = await request.json()
    return await _handle_tools_call(data)

if __name__ == "__main__":
    import uvicorn
    # Port can be set via environment variable or defaults to template value
    port = int(os.environ.get("MCP_SERVER_PORT", DEFAULT_PORT))
    # 기본 바인드는 loopback. 외부 노출은 MCP_BIND_HOST + MCP_ALLOW_PUBLIC_BIND 옵트인 필요.
    uvicorn.run(app, host=resolve_bind_host(server_name=SERVER_NAME), port=port)