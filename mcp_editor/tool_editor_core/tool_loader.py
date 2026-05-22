"""
Tool Loader Module

도구 정의 로딩 함수들:
- YAML/Python에서 도구 정의 로딩
- mcp_service_factors에서 internal_args 추출
- 파일 수정 시간 추적
"""

import os
import importlib.util
import yaml

from .schema_utils import convert_params_list_to_dict


def load_tool_definitions(paths: dict):
    """
    Load MCP_TOOLS, preferring YAML template file (with mcp_service metadata)
    Templates are auto-generated with AST-extracted signatures

    Load priority:
    1. YAML template (.yaml) - preferred format
    2. Python template (.py) - legacy format, loads via YAML internally
    3. Python definitions (.py) - fallback, cleaned definitions
    """
    try:
        template_path = paths["template_path"]

        # 1. Try YAML template first (preferred format)
        yaml_path = template_path.replace('.py', '.yaml') if template_path.endswith('.py') else template_path
        if os.path.exists(yaml_path):
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data.get("tools", [])

        # 2. Try Python template (legacy - it loads YAML internally now)
        if os.path.exists(template_path):
            spec = importlib.util.spec_from_file_location("tool_definition_templates", template_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.MCP_TOOLS

        # 3. Fallback to cleaned definitions
        spec = importlib.util.spec_from_file_location("tool_definitions", paths["tool_path"])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.MCP_TOOLS
    except Exception as e:
        return {"error": str(e)}


def extract_service_factors(tools: list) -> tuple[dict, dict]:
    """
    Extract internal_args and signature_defaults from mcp_service_factors in tools.

    mcp_service_factors는 tool_definition_templates.py에 직접 저장됩니다.
    source 필드로 구분:
    - 'internal': LLM에게 완전히 숨겨진 파라미터
    - 'signature_defaults': LLM에게 보이지만 기본값이 있는 파라미터

    Returns:
        tuple: (internal_args, signature_defaults)
    """
    internal_args = {}
    signature_defaults = {}

    for tool in tools:
        tool_name = tool.get("name")
        if not tool_name:
            continue

        service_factors = tool.get("mcp_service_factors", {})
        if not service_factors:
            continue

        for param_name, param_info in service_factors.items():
            source = param_info.get("source", "internal")  # 기본값은 internal

            # Support 'class_name' (new), 'type', and 'baseModel' (legacy) field names
            # Prefer class_name for display/model name, fallback to type/baseModel
            factor_type = param_info.get("class_name") or param_info.get("type") or param_info.get("baseModel", "object")

            # Convert parameters from list to dict if needed (for internal structures)
            params = param_info.get("parameters", [])
            if isinstance(params, list):
                params_dict = convert_params_list_to_dict(params)
            else:
                params_dict = params  # Already a dict (legacy format)

            if source == "internal":
                # Internal args 구조로 변환
                if tool_name not in internal_args:
                    internal_args[tool_name] = {}

                # targetParam is REQUIRED - no auto-inference
                target_param = param_info.get("targetParam")
                if not target_param:
                    print(f"  [WARNING] Tool '{tool_name}': mcp_service_factors['{param_name}'] missing 'targetParam'")
                    # Use param_name as fallback for backward compatibility during migration
                    target_param = param_name

                # Extract primitive default for primitive types (integer, string, boolean)
                primitive_default = param_info.get("default")

                # If no explicit default, try to get from mcp_service.parameters using targetParam
                if primitive_default is None and not params_dict:
                    mcp_service = tool.get("mcp_service", {})
                    service_params = mcp_service.get("parameters", [])
                    for sp in service_params:
                        if sp.get("name") == target_param and sp.get("default") is not None:
                            primitive_default = sp["default"]
                            break

                # Determine if this is a primitive type (no nested properties)
                is_primitive = not params_dict
                schema_type = factor_type if is_primitive else "object"

                internal_args[tool_name][param_name] = {
                    "description": param_info.get("description", ""),
                    "type": factor_type,
                    "primitive_default": primitive_default,  # Store primitive default value
                    "original_schema": {
                        "baseModel": factor_type,
                        "description": param_info.get("description", ""),
                        "properties": params_dict,
                        "required": [],
                        "type": schema_type,  # Preserve original type for primitives
                        "default": primitive_default,  # Store default for primitives
                    },
                    "targetParam": target_param,
                    "was_required": False,
                }

            elif source == "signature_defaults":
                # Signature defaults 구조로 변환
                if tool_name not in signature_defaults:
                    signature_defaults[tool_name] = {}

                signature_defaults[tool_name][param_name] = {
                    "baseModel": factor_type,
                    "description": param_info.get("description", ""),
                    "properties": params_dict,
                    "source": "signature_defaults",
                }

    return internal_args, signature_defaults


def get_file_mtimes(paths: dict) -> dict:
    """
    Collect file modification times for conflict detection
    """
    mtimes = {}
    path_keys = [
        ("tool_path", "definitions"),
        ("template_path", "templates"),
    ]
    for path_key, mtime_key in path_keys:
        path = paths.get(path_key)
        if path and os.path.exists(path):
            mtimes[mtime_key] = os.path.getmtime(path)
    return mtimes
