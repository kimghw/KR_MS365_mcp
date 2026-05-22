"""
STDIO MCP Server for Outlook MCP Server
Handles MCP protocol via standard input/output
Generated from universal template with registry data and protocol selection
"""
import json
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
import sys
import os
import logging
import asyncio
from typing import AsyncIterator
from dotenv import load_dotenv

# Add parent directories to path for module access
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
grandparent_dir = os.path.dirname(parent_dir)

# Load .env from project root before any imports that need env vars
# Use utf-8-sig encoding to handle Windows BOM (Byte Order Mark)
_env_path = os.path.join(grandparent_dir, ".env")
_env_loaded = load_dotenv(_env_path, encoding="utf-8-sig")

# BOM safety: strip \ufeff from env vars that may have been corrupted
for _key in ("AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_TENANT_ID", "AZURE_REDIRECT_URI", "AZURE_SCOPES"):
    _val = os.environ.get(_key)
    if _val and _val.startswith("\ufeff"):
        os.environ[_key] = _val.lstrip("\ufeff")

print(f"[DEBUG] .env path: {_env_path}, exists: {os.path.exists(_env_path)}, loaded: {_env_loaded}", file=sys.stderr)
print(f"[DEBUG] AZURE_CLIENT_ID: {repr(os.getenv('AZURE_CLIENT_ID'))}", file=sys.stderr)
if not os.getenv('AZURE_CLIENT_ID'):
    # Try reading .env file directly to diagnose
    if os.path.exists(_env_path):
        try:
            with open(_env_path, 'rb') as f:
                first_bytes = f.read(100)
            print(f"[ERROR] AZURE_CLIENT_ID is None despite .env existing! First bytes: {first_bytes[:50]}", file=sys.stderr)
        except Exception as e:
            print(f"[ERROR] Cannot read .env: {e}", file=sys.stderr)
    else:
        print(f"[ERROR] .env file does not exist at: {_env_path}", file=sys.stderr)

# CRITICAL: Redirect stdout to stderr BEFORE any module imports.
# STDIO MCP protocol uses stdout exclusively for JSON-RPC messages.
# Any print() from imported modules (graph_mail_query, graph_mail_client, etc.)
# would corrupt the JSON-RPC stream and cause "Unexpected token" errors.
_original_stdout = sys.stdout  # Save for JSON-RPC output
sys.stdout = sys.stderr  # All print() now goes to stderr

# Add paths for imports (generalized for all servers)
server_module_dir = os.path.join(grandparent_dir, "mcp_outlook")
if os.path.isdir(server_module_dir):
    sys.path.insert(0, server_module_dir)  # For server-specific relative imports
sys.path.insert(0, grandparent_dir)  # For session module and package imports
sys.path.insert(0, parent_dir)  # For direct module imports

# Import types dynamically based on type_info
from mcp_outlook.outlook_types import ExcludeParams, FilterParams, SelectParams
from mcp_outlook.graph_mail_client import ProcessingMode, QueryMethod

# Import AuthDatabase for default user_email lookup
from session.auth_database import AuthDatabase


def get_default_user_email() -> Optional[str]:
    """Get default user email from auth.db when not provided.

    Returns the first user's email from azure_user_info table.
    Used for authentication/token-related operations when user_email is not specified.
    """
    try:
        db = AuthDatabase()
        users = db.list_users()
        if users:
            return users[0].get('user_email') or users[0].get('email')
        return None
    except Exception as e:
        logger.warning(f"Failed to get default user email from auth.db: {e}")
        return None

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
       - Uses outlook which is set correctly at generation time for reused profiles
    3. Fallback to mcp_editor/mcp_{server_name}/tool_definition_templates.yaml (original service)
    """
    # Option 1: Environment variable override
    yaml_path_str = os.environ.get("MCP_YAML_PATH")
    if yaml_path_str:
        yaml_path = Path(yaml_path_str)
    else:
        # Option 2: Profile-specific YAML path (supports reused profiles like outlook_read)
        yaml_path = Path(current_dir).parent.parent / "mcp_editor" / "mcp_outlook" / "tool_definition_templates.yaml"
        if not yaml_path.exists():
            # Option 3: Fallback to original server name (for backwards compatibility)
            yaml_path = Path(current_dir).parent.parent / "mcp_editor" / "mcp_outlook" / "tool_definition_templates.yaml"

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
# 기본 서버: outlook
# ============================================================
from mcp_outlook.outlook_service import MailService

# Create service instances
mail_service = MailService()

# ============================================================
# Common MCP protocol utilities (shared across protocols)
# ============================================================

SUPPORTED_PROTOCOLS = {"rest", "stdio", "stream"}

# Pre-computed tool -> implementation mapping
TOOL_IMPLEMENTATIONS = {
    "mail_list_period": {
        "service_class": "MailService",
        "method": "query_mail_list"
    },
    "mail_list_keyword": {
        "service_class": "MailService",
        "method": "fetch_search"
    },
    "mail_query_if_emaidID": {
        "service_class": "MailService",
        "method": "batch_and_fetch"
    },
    "mail_attachment_meta": {
        "service_class": "MailService",
        "method": "fetch_attachments_metadata"
    },
    "mail_attachment_download": {
        "service_class": "MailService",
        "method": "download_attachments"
    },
    "mail_fetch_filter": {
        "service_class": "MailService",
        "method": "fetch_filter"
    },
    "mail_fetch_search": {
        "service_class": "MailService",
        "method": "fetch_search"
    },
    "mail_process_with_download": {
        "service_class": "MailService",
        "method": "process_with_download"
    },
    "mail_query_url": {
        "service_class": "MailService",
        "method": "fetch_url"
    },
    "test_handler": {
        "service_class": "MailService",
        "method": "fetch_filter"
    },
}

# Pre-computed service class -> instance mapping
SERVICE_INSTANCES = {
    "MailService": mail_service,
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
if 'ExcludeParams' in globals():
    INTERNAL_ARG_TYPES['ExcludeParams'] = ExcludeParams
if 'FilterParams' in globals():
    INTERNAL_ARG_TYPES['FilterParams'] = FilterParams
if 'SelectParams' in globals():
    INTERNAL_ARG_TYPES['SelectParams'] = SelectParams


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

async def handle_mail_list_period(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle mail_list_period tool call"""

    # ========================================
    # Step 1: Signature 파라미터 수신
    # - LLM으로부터 전달받은 인자 추출
    # ========================================
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    DatePeriodFilter_sig = args.get("DatePeriodFilter")
    DatePeriodFilter = DatePeriodFilter_sig if DatePeriodFilter_sig is not None else None

    # ========================================
    # Step 2: Signature Defaults 적용
    # - 사용자 입력이 없으면 기본값 병합
    # ========================================
    DatePeriodFilter_sig_defaults = {}
    DatePeriodFilter_data = merge_param_data({}, DatePeriodFilter, DatePeriodFilter_sig_defaults)
    if DatePeriodFilter_data is not None:
        DatePeriodFilter = FilterParams(**DatePeriodFilter_data)
    else:
        DatePeriodFilter = None

    # ========================================
    # Step 3: 서비스 호출 인자 구성
    # - Signature 파라미터 추가
    # ========================================
    call_args = {}
    call_args["user_email"] = user_email
    call_args["filter_params"] = DatePeriodFilter

    # ========================================
    # Step 4: Internal 파라미터 추가
    # - LLM에 노출되지 않는 내부 고정값
    # ========================================
    call_args["client_filter"] = ExcludeParams(**{'exclude_from_address': ['block@krs.co.kr',
                          'no-reply@teams.mail.microsoft',
                          'reminders@facebookmail.com',
                          'no-reply@sharepointonline.com']})
    call_args["select_params"] = SelectParams(**{'bcc_recipients': False,
 'body': False,
 'body_preview': True,
 'categories': False,
 'cc_recipients': False,
 'change_key': False,
 'conversation_id': False,
 'conversation_index': False,
 'created_date_time': False,
 'flag': False,
 'from_recipient': True,
 'has_attachments': True,
 'id': True,
 'importance': False,
 'inference_classification': False,
 'internet_message_headers': False,
 'internet_message_id': True,
 'is_delivery_receipt_requested': False,
 'is_draft': False,
 'is_read': False,
 'is_read_receipt_requested': False,
 'last_modified_date_time': False,
 'parent_folder_id': False,
 'received_date_time': False,
 'reply_to': False,
 'sender': True,
 'sent_date_time': False,
 'subject': True,
 'to_recipients': False,
 'unique_body': False,
 'web_link': False})
    call_args["top"] = 500

    # ========================================
    # Step 5: 서비스 메서드 호출
    # ========================================
    return await mail_service.query_mail_list(**call_args)

async def handle_mail_list_keyword(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle mail_list_keyword tool call"""

    # ========================================
    # Step 1: Signature 파라미터 수신
    # - LLM으로부터 전달받은 인자 추출
    # ========================================
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    search_keywords = args["search_keywords"]
    top_sig = args.get("top")
    top = top_sig if top_sig is not None else 50

    # ========================================
    # Step 2: 서비스 호출 인자 구성
    # ========================================
    call_args = {}
    call_args["user_email"] = user_email
    call_args["search_term"] = search_keywords
    call_args["top"] = top

    # ========================================
    # Step 3: 서비스 메서드 호출
    # ========================================
    return await mail_service.fetch_search(**call_args)

async def handle_mail_query_if_emaidID(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle mail_query_if_emaidID tool call"""

    # ========================================
    # Step 1: Signature 파라미터 수신
    # - LLM으로부터 전달받은 인자 추출
    # ========================================
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    message_ids = args["message_ids"]

    # ========================================
    # Step 2: 서비스 호출 인자 구성
    # ========================================
    call_args = {}
    call_args["user_email"] = user_email
    call_args["message_ids"] = message_ids

    # ========================================
    # Step 3: 서비스 메서드 호출
    # ========================================
    return await mail_service.batch_and_fetch(**call_args)

async def handle_mail_attachment_meta(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle mail_attachment_meta tool call"""

    # ========================================
    # Step 1: Signature 파라미터 수신
    # - LLM으로부터 전달받은 인자 추출
    # ========================================
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    message_ids = args["message_ids"]

    # ========================================
    # Step 2: 서비스 호출 인자 구성
    # ========================================
    call_args = {}
    call_args["user_email"] = user_email
    call_args["message_ids"] = message_ids

    # ========================================
    # Step 3: 서비스 메서드 호출
    # ========================================
    return await mail_service.fetch_attachments_metadata(**call_args)

async def handle_mail_attachment_download(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle mail_attachment_download tool call"""

    # ========================================
    # Step 1: Signature 파라미터 수신
    # - LLM으로부터 전달받은 인자 추출
    # ========================================
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    message_attachment_ids = args["message_attachment_ids"]
    save_directory_sig = args.get("save_directory")
    save_directory = save_directory_sig if save_directory_sig is not None else 'downloads'
    flat_folder_sig = args.get("flat_folder")
    flat_folder = flat_folder_sig if flat_folder_sig is not None else 'disabled'
    skip_duplicates_sig = args.get("skip_duplicates")
    skip_duplicates = skip_duplicates_sig if skip_duplicates_sig is not None else 'enabled'
    save_file_sig = args.get("save_file")
    save_file = save_file_sig if save_file_sig is not None else 'enabled'
    storage_type_sig = args.get("storage_type")
    storage_type = storage_type_sig if storage_type_sig is not None else 'local'
    convert_to_txt_sig = args.get("convert_to_txt")
    convert_to_txt = convert_to_txt_sig if convert_to_txt_sig is not None else 'disabled'
    include_body_sig = args.get("include_body")
    include_body = include_body_sig if include_body_sig is not None else 'enabled'
    onedrive_folder_sig = args.get("onedrive_folder")
    onedrive_folder = onedrive_folder_sig if onedrive_folder_sig is not None else '/Attachments'

    # ========================================
    # Step 1.5: Boolean 파라미터 변환
    # - enabled/disabled -> True/False
    # ========================================
    skip_duplicates = convert_enabled_to_bool(skip_duplicates)
    save_file = convert_enabled_to_bool(save_file)
    flat_folder = convert_enabled_to_bool(flat_folder)
    convert_to_txt = convert_enabled_to_bool(convert_to_txt)
    include_body = convert_enabled_to_bool(include_body)

    # ========================================
    # Step 2: 서비스 호출 인자 구성
    # ========================================
    call_args = {}
    call_args["user_email"] = user_email
    call_args["message_attachment_ids"] = message_attachment_ids
    call_args["save_directory"] = save_directory
    call_args["flat_folder"] = flat_folder
    call_args["skip_duplicates"] = skip_duplicates
    call_args["save_file"] = save_file
    call_args["storage_type"] = storage_type
    call_args["convert_to_txt"] = convert_to_txt
    call_args["include_body"] = include_body
    call_args["onedrive_folder"] = onedrive_folder

    # ========================================
    # Step 3: 서비스 메서드 호출
    # ========================================
    return await mail_service.download_attachments(**call_args)

async def handle_mail_fetch_filter(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle mail_fetch_filter tool call"""

    # ========================================
    # Step 1: Signature 파라미터 수신
    # - LLM으로부터 전달받은 인자 추출
    # ========================================
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    filter_params_sig = args.get("filter_params")
    filter_params = filter_params_sig if filter_params_sig is not None else None
    exclude_params_sig = args.get("exclude_params")
    exclude_params = exclude_params_sig if exclude_params_sig is not None else None

    # ========================================
    # Step 2: Signature Defaults 적용
    # - 사용자 입력이 없으면 기본값 병합
    # ========================================
    filter_params_sig_defaults = {'test_field': 'test_value'}
    filter_params_data = merge_param_data({}, filter_params, filter_params_sig_defaults)
    if filter_params_data is not None:
        filter_params = FilterParams(**filter_params_data)
    else:
        filter_params = None
    exclude_params_sig_defaults = {}
    exclude_params_data = merge_param_data({}, exclude_params, exclude_params_sig_defaults)
    if exclude_params_data is not None:
        exclude_params = ExcludeParams(**exclude_params_data)
    else:
        exclude_params = None

    # ========================================
    # Step 3: 서비스 호출 인자 구성
    # - Signature 파라미터 추가
    # ========================================
    call_args = {}
    call_args["user_email"] = user_email
    call_args["filter_params"] = filter_params
    call_args["exclude_params"] = exclude_params

    # ========================================
    # Step 5: 서비스 메서드 호출
    # ========================================
    return await mail_service.fetch_filter(**call_args)

async def handle_mail_fetch_search(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle mail_fetch_search tool call"""

    # ========================================
    # Step 1: Signature 파라미터 수신
    # - LLM으로부터 전달받은 인자 추출
    # ========================================
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    search_term = args["search_term"]
    select_params_sig = args.get("select_params")
    select_params = select_params_sig if select_params_sig is not None else None
    top_sig = args.get("top")
    top = top_sig if top_sig is not None else 50

    # ========================================
    # Step 2: Signature Defaults 적용
    # - 사용자 입력이 없으면 기본값 병합
    # ========================================
    select_params_sig_defaults = {}
    select_params_data = merge_param_data({}, select_params, select_params_sig_defaults)
    if select_params_data is not None:
        select_params = SelectParams(**select_params_data)
    else:
        select_params = None

    # ========================================
    # Step 3: 서비스 호출 인자 구성
    # - Signature 파라미터 추가
    # ========================================
    call_args = {}
    call_args["user_email"] = user_email
    call_args["search_term"] = search_term
    call_args["select_params"] = select_params
    call_args["top"] = top

    # ========================================
    # Step 5: 서비스 메서드 호출
    # ========================================
    return await mail_service.fetch_search(**call_args)

async def handle_mail_process_with_download(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle mail_process_with_download tool call"""

    # ========================================
    # Step 1: Signature 파라미터 수신
    # - LLM으로부터 전달받은 인자 추출
    # ========================================
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    filter_params_sig = args.get("filter_params")
    filter_params = filter_params_sig if filter_params_sig is not None else None
    search_term_sig = args.get("search_term")
    search_term = search_term_sig if search_term_sig is not None else None
    top_sig = args.get("top")
    top = top_sig if top_sig is not None else 50
    save_directory_sig = args.get("save_directory")
    save_directory = save_directory_sig if save_directory_sig is not None else None

    # ========================================
    # Step 2: Signature Defaults 적용
    # - 사용자 입력이 없으면 기본값 병합
    # ========================================
    filter_params_sig_defaults = {}
    filter_params_data = merge_param_data({}, filter_params, filter_params_sig_defaults)
    if filter_params_data is not None:
        filter_params = FilterParams(**filter_params_data)
    else:
        filter_params = None

    # ========================================
    # Step 3: 서비스 호출 인자 구성
    # - Signature 파라미터 추가
    # ========================================
    call_args = {}
    call_args["user_email"] = user_email
    call_args["filter_params"] = filter_params
    call_args["search_term"] = search_term
    call_args["top"] = top
    call_args["save_directory"] = save_directory

    # ========================================
    # Step 5: 서비스 메서드 호출
    # ========================================
    return await mail_service.process_with_download(**call_args)

async def handle_mail_query_url(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle mail_query_url tool call"""

    # ========================================
    # Step 1: Signature 파라미터 수신
    # - LLM으로부터 전달받은 인자 추출
    # ========================================
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    url = args["url"]
    filter_params_sig = args.get("filter_params")
    filter_params = filter_params_sig if filter_params_sig is not None else None
    top_sig = args.get("top")
    top = top_sig if top_sig is not None else 50

    # ========================================
    # Step 2: Signature Defaults 적용
    # - 사용자 입력이 없으면 기본값 병합
    # ========================================
    filter_params_sig_defaults = {}
    filter_params_data = merge_param_data({}, filter_params, filter_params_sig_defaults)
    if filter_params_data is not None:
        filter_params = FilterParams(**filter_params_data)
    else:
        filter_params = None

    # ========================================
    # Step 3: 서비스 호출 인자 구성
    # - Signature 파라미터 추가
    # ========================================
    call_args = {}
    call_args["user_email"] = user_email
    call_args["url"] = url
    call_args["filter_params"] = filter_params
    call_args["top"] = top

    # ========================================
    # Step 4: Internal 파라미터 추가
    # - LLM에 노출되지 않는 내부 고정값
    # ========================================
    call_args["select"] = SelectParams(**{'body_preview': True,
 'created_date_time': True,
 'from_recipient': True,
 'id': True,
 'received_date_time': True})

    # ========================================
    # Step 5: 서비스 메서드 호출
    # ========================================
    return await mail_service.fetch_url(**call_args)

async def handle_test_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle test_handler tool call"""

    # ========================================
    # Step 1: Signature 파라미터 수신
    # - LLM으로부터 전달받은 인자 추출
    # ========================================
    filter_params_sig = args.get("filter_params")
    filter_params = filter_params_sig if filter_params_sig is not None else None
    exclude_params_sig = args.get("exclude_params")
    exclude_params = exclude_params_sig if exclude_params_sig is not None else None
    select_params_sig = args.get("select_params")
    select_params = select_params_sig if select_params_sig is not None else None
    client_filter_sig = args.get("client_filter")
    client_filter = client_filter_sig if client_filter_sig is not None else None
    top_sig = args.get("top")
    top = top_sig if top_sig is not None else 50

    # ========================================
    # Step 2: Signature Defaults 적용
    # - 사용자 입력이 없으면 기본값 병합
    # ========================================
    filter_params_sig_defaults = {}
    filter_params_data = merge_param_data({}, filter_params, filter_params_sig_defaults)
    if filter_params_data is not None:
        filter_params = FilterParams(**filter_params_data)
    else:
        filter_params = None
    exclude_params_sig_defaults = {}
    exclude_params_data = merge_param_data({}, exclude_params, exclude_params_sig_defaults)
    if exclude_params_data is not None:
        exclude_params = ExcludeParams(**exclude_params_data)
    else:
        exclude_params = None
    select_params_sig_defaults = {}
    select_params_data = merge_param_data({}, select_params, select_params_sig_defaults)
    if select_params_data is not None:
        select_params = SelectParams(**select_params_data)
    else:
        select_params = None
    client_filter_sig_defaults = {}
    client_filter_data = merge_param_data({}, client_filter, client_filter_sig_defaults)
    if client_filter_data is not None:
        client_filter = ExcludeParams(**client_filter_data)
    else:
        client_filter = None

    # ========================================
    # Step 3: 서비스 호출 인자 구성
    # - Signature 파라미터 추가
    # ========================================
    call_args = {}
    call_args["filter_params"] = filter_params
    call_args["exclude_params"] = exclude_params
    call_args["select_params"] = select_params
    call_args["client_filter"] = client_filter
    call_args["top"] = top

    # ========================================
    # Step 4: Internal 파라미터 추가
    # - LLM에 노출되지 않는 내부 고정값
    # ========================================
    user_email = args.get("user_email")
    if not user_email:
        user_email = get_default_user_email()
        if not user_email:
            return {"status": "error", "error": "user_email not provided and no default user found in auth.db"}
    call_args["user_email"] = user_email

    # ========================================
    # Step 5: 서비스 메서드 호출
    # ========================================
    return await mail_service.fetch_filter(**call_args)

# ============================================================
# STDIO Protocol Implementation for MCP Server
# ============================================================
# Note: This template is included by universal_server_template.jinja2
# All common imports and utilities are defined in the parent template

# Configure logging for STDIO (stderr to avoid interfering with stdout)
# Override the parent's logger to use stderr
import sys
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr  # Important: use stderr for logging
)
logger = logging.getLogger(__name__)

class StdioMCPServer:
    """MCP STDIO Protocol Server

    Handles MCP protocol communication via standard input/output using JSON-RPC format.
    Messages are delimited by newlines for easy parsing.
    """

    def __init__(self):
        self.running = False
        self.request_id_counter = 0
        logger.info(f"Outlook MCP Server STDIO Server initialized")

    async def read_message(self) -> Optional[Dict[str, Any]]:
        """Read a single JSON-RPC message from stdin"""
        try:
            line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
            if not line:
                return None

            message = json.loads(line.strip())
            logger.debug(f"Received message: {message}")
            return message
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON received: {e}")
            return None
        except Exception as e:
            logger.error(f"Error reading message: {e}")
            return None

    def write_message(self, message: Dict[str, Any]):
        """Write a JSON-RPC message to the real stdout (not stderr)"""
        try:
            json_str = json.dumps(message, ensure_ascii=False)
            _original_stdout.write(json_str + '\n')
            _original_stdout.flush()
            logger.debug(f"Sent message: {message}")
        except Exception as e:
            logger.error(f"Error writing message: {e}")

    def send_error(self, request_id: Any, code: int, message: str, data: Any = None):
        """Send JSON-RPC error response"""
        error_response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message
            }
        }
        if data is not None:
            error_response["error"]["data"] = data
        self.write_message(error_response)

    def send_result(self, request_id: Any, result: Any):
        """Send JSON-RPC success response"""
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result
        }
        self.write_message(response)

    async def handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle initialize request"""
        client_info = params.get("clientInfo", {})
        logger.info(f"Client connected: {client_info.get('name', 'unknown')}")

        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "outlook",
                "version": "1.0.0"
            }
        }

    async def handle_tools_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/list request"""
        return {"tools": MCP_TOOLS}

    def apply_schema_defaults(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Apply default values from inputSchema to arguments if not provided."""
        tool_config = get_tool_config(tool_name)
        if not tool_config:
            return arguments

        input_schema = tool_config.get("inputSchema", {})
        properties = input_schema.get("properties", {})

        # Create a copy of arguments to avoid modifying the original
        merged_args = dict(arguments) if arguments else {}

        # Apply defaults for properties that have them and are not in arguments
        for prop_name, prop_def in properties.items():
            if prop_name not in merged_args and "default" in prop_def:
                merged_args[prop_name] = prop_def["default"]
                logger.debug(f"Applied default for {prop_name}: {prop_def['default']}")

        return merged_args

    async def handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call request"""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if not tool_name:
            raise ValueError("Tool name is required")

        # Apply default values from inputSchema
        arguments = self.apply_schema_defaults(tool_name, arguments)

        # Look up the handler function
        handler_name = f"handle_{tool_name.replace('-', '_')}"
        if handler_name not in globals():
            raise ValueError(f"Unknown tool: {tool_name}")

        try:
            # Call the tool handler
            result = await globals()[handler_name](arguments)

            # Check for auth_required response (login URL for LLM)
            if isinstance(result, dict) and result.get("status") == "auth_required":
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, ensure_ascii=False, indent=2)
                        }
                    ],
                    "isError": True
                }

            # Format result for MCP
            if isinstance(result, dict) and "content" in result:
                return result
            elif isinstance(result, str):
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": result
                        }
                    ]
                }
            else:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, ensure_ascii=False, indent=2)
                        }
                    ]
                }
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            raise

    async def handle_request(self, request: Dict[str, Any]):
        """Handle a single JSON-RPC request"""
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if not method:
            self.send_error(request_id, -32600, "Invalid Request: missing method")
            return

        try:
            # Route to appropriate handler based on method
            if method == "initialize":
                result = await self.handle_initialize(params)
            elif method == "tools/list":
                result = await self.handle_tools_list(params)
            elif method == "tools/call":
                result = await self.handle_tools_call(params)
            elif method == "shutdown":
                logger.info("Shutdown requested")
                self.running = False
                result = {}
            elif method == "ping":
                result = {"pong": True}
            else:
                self.send_error(request_id, -32601, f"Method not found: {method}")
                return

            # Send successful response
            self.send_result(request_id, result)

        except ValueError as e:
            self.send_error(request_id, -32602, f"Invalid params: {str(e)}")
        except Exception as e:
            logger.error(f"Error handling request: {e}", exc_info=True)
            self.send_error(request_id, -32603, f"Internal error: {str(e)}")

    async def handle_notification(self, notification: Dict[str, Any]):
        """Handle JSON-RPC notifications (no response expected)"""
        method = notification.get("method")
        params = notification.get("params", {})

        logger.info(f"Received notification: {method}")

        # Notifications don't require responses
        if method == "notifications/initialized":
            logger.info("Client initialization complete")
        elif method == "cancelled":
            logger.info(f"Request cancelled: {params.get('id')}")
        elif method == "progress":
            logger.info(f"Progress update: {params}")
        # Add more notification handlers as needed

    async def run(self):
        """Main server loop"""
        self.running = True

        # Initialize services before starting
        if hasattr(mail_service, 'initialize'):
            await mail_service.initialize()
            logger.info("MailService initialized")

        logger.info(f"Outlook MCP Server STDIO Server started")
        logger.info("Waiting for messages on stdin...")

        try:
            while self.running:
                # Read next message
                message = await self.read_message()

                if message is None:
                    # EOF or error - exit gracefully
                    logger.info("Input stream closed, shutting down")
                    break

                # Check if it's a request or notification
                if "id" in message:
                    # Request - requires response
                    await self.handle_request(message)
                else:
                    # Notification - no response needed
                    await self.handle_notification(message)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception as e:
            logger.error(f"Server error: {e}", exc_info=True)
        finally:
            logger.info("Outlook MCP Server STDIO Server stopped")

# Main entry point for STDIO protocol
async def handle_stdio():
    """Handle MCP protocol via stdin/stdout"""
    server = StdioMCPServer()
    await server.run()

if __name__ == "__main__":
    asyncio.run(handle_stdio())