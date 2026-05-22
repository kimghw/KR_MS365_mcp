"""
Tool Saver Module

도구 정의 저장 함수:
- YAML 포맷으로 도구 정의 저장
- mcp_service_factors 포함
"""

import os
import yaml

from .config import (
    BASE_DIR,
    ROOT_DIR,
    ensure_dirs,
)
from .schema_utils import (
    order_schema_fields,
    ensure_target_params,
    convert_params_dict_to_list,
    is_all_none_defaults,
)
from .service_registry import load_services_for_server
from tool_editor_web_server_mappings import get_server_name_from_path


def save_tool_definitions(
    tools_data,
    paths: dict,
    force_rescan: bool = False,
    skip_backup: bool = False,
    internal_args: dict = None,
    signature_defaults: dict = None,
):
    """Save MCP_TOOLS to both tool_definitions.py and tool_definition_templates.py

    Args:
        tools_data: List of tool definitions to save
        paths: Resolved paths dict from resolve_paths()
        force_rescan: Force rescan of service signatures
        skip_backup: Skip internal backup (use when caller already handles backup)
        internal_args: Internal parameters (hidden from LLM, source: 'internal')
        signature_defaults: Signature params with defaults (shown to LLM, source: 'signature_defaults')

    mcp_service_factors에 직접 저장 (중간 JSON 파일 없이 단순화)
    """
    if internal_args is None:
        internal_args = {}
    if signature_defaults is None:
        signature_defaults = {}
    try:
        ensure_dirs(paths)

        # tool_definitions.py is deprecated - YAML is now the Single Source of Truth
        # Server code loads directly from tool_definition_templates.yaml

        # Get server name for service signature extraction
        server_name = get_server_name_from_path(paths.get("tool_path", "")) or get_server_name_from_path(
            paths.get("template_path", "")
        )

        # Save tool_definition_templates.yaml (with AST-extracted metadata)
        # Extract signatures from source code using AST (cached)
        services_by_name = {}
        if server_name:
            module_patterns = [
                os.path.join(ROOT_DIR, f"mcp_{server_name}"),
                os.path.join(ROOT_DIR, f"{server_name}_mcp"),
            ]
            scan_dir = next((p for p in module_patterns if os.path.isdir(p)), None)

            if scan_dir:
                try:
                    services_by_name = load_services_for_server(server_name, scan_dir, force_rescan=force_rescan)
                except FileNotFoundError as e:
                    # Log the error but continue without service signatures
                    print(f"WARNING: {e}")
                    print(f"Continuing without service signatures for {server_name}")
                    services_by_name = {}

        # Build template tools
        template_tools = []
        # internal_args는 파라미터로 전달됨 (중간 파일 없이 직접 사용)

        for tool in tools_data:
            # Create template_tool with ordered keys (name first for readability)
            template_tool = {}
            # 1. name first (most important identifier)
            if "name" in tool:
                template_tool["name"] = tool["name"]
            # 2. description second
            if "description" in tool:
                template_tool["description"] = tool["description"]
            # 3. Copy remaining fields in order
            for k, v in tool.items():
                if k not in template_tool:
                    template_tool[k] = v
            if "inputSchema" in template_tool:
                # Ensure all properties have targetParam and order fields
                cleaned_schema = ensure_target_params(template_tool["inputSchema"])
                template_tool["inputSchema"] = order_schema_fields(cleaned_schema)

            # Convert mcp_service from string to dict if needed (frontend sends string)
            if "mcp_service" in template_tool and isinstance(template_tool["mcp_service"], str):
                service_name = template_tool["mcp_service"]
                if service_name:
                    template_tool["mcp_service"] = {"name": service_name}
                else:
                    del template_tool["mcp_service"]

            # Add signature if available
            if "mcp_service" in template_tool and isinstance(template_tool["mcp_service"], dict):
                service_name = template_tool["mcp_service"].get("name")
                if service_name and service_name in services_by_name:
                    service_info = services_by_name[service_name]
                    template_tool["mcp_service"]["signature"] = service_info.get("signature")
                    if service_info.get("parameters"):
                        template_tool["mcp_service"]["parameters"] = service_info["parameters"]

            # Add mcp_service_factors for internal parameters and signature defaults
            # These are service method parameters that are internally configured or have fallback values
            tool_name = tool.get("name")
            service_factors = {}

            # 1. Add internal args (source: 'internal' - completely hidden from LLM)
            if tool_name and tool_name in internal_args:
                for param_name, param_info in internal_args[tool_name].items():
                    # Each key is the actual service method parameter name
                    # Store essential information for internal parameters
                    # baseModel is the type for this factor (supports class_name from new registry format)
                    base_model = (
                        param_info.get("original_schema", {}).get("baseModel")
                        or param_info.get("class_name")
                        or param_info.get("type")
                    )

                    # targetParam is REQUIRED - specifies which mcp_service parameter this maps to
                    target_param = param_info.get("targetParam", param_name)

                    factor_data = {
                        "source": "internal",
                        "type": base_model,  # Use 'type' instead of 'baseModel' for consistency
                        "targetParam": target_param,  # Required: target mcp_service parameter
                        "description": param_info.get("description", ""),
                    }

                    # Add parameters structure from original_schema if available
                    # Convert from dict format to unified list format
                    original_schema = param_info.get("original_schema", {})
                    props_dict = original_schema.get("properties", {})

                    if props_dict:
                        # Object type with nested properties
                        factor_data["parameters"] = convert_params_dict_to_list(props_dict)
                    else:
                        # Primitive type (integer, string, boolean, etc.)
                        # Store default value directly in factor_data
                        primitive_default = original_schema.get("default")
                        if primitive_default is not None:
                            factor_data["default"] = primitive_default
                        factor_data["parameters"] = []

                    # Skip if all defaults are None (useless factor)
                    if not is_all_none_defaults(factor_data):
                        service_factors[param_name] = factor_data

            # 2. Add signature defaults (source: 'signature_defaults' - visible to LLM but has fallback values)
            if tool_name and tool_name in signature_defaults:
                for param_name, param_info in signature_defaults[tool_name].items():
                    # Each key is the actual service method parameter name
                    # Store essential information for signature defaults (supports class_name from new registry format)
                    base_model = param_info.get("baseModel") or param_info.get("class_name") or param_info.get("type")

                    # targetParam is REQUIRED - specifies which mcp_service parameter this maps to
                    target_param = param_info.get("targetParam", param_name)

                    factor_data = {
                        "source": "signature_defaults",
                        "type": base_model,  # Use 'type' instead of 'baseModel' for consistency
                        "targetParam": target_param,  # Required: target mcp_service parameter
                        "description": param_info.get("description", ""),
                    }

                    # Add parameters structure (properties with default values)
                    # Convert from dict format to unified list format
                    if "properties" in param_info:
                        props_dict = param_info["properties"]
                        factor_data["parameters"] = convert_params_dict_to_list(props_dict)

                    # Skip if all defaults are None (useless factor)
                    if not is_all_none_defaults(factor_data):
                        service_factors[param_name] = factor_data

            if service_factors:
                template_tool["mcp_service_factors"] = service_factors

            template_tools.append(template_tool)

        # Write template file as YAML (use path from config, which includes server folder structure)
        template_path = paths.get("template_path")

        # Convert .py path to .yaml path
        if template_path.endswith('.py'):
            yaml_path = template_path.replace('.py', '.yaml')
        else:
            yaml_path = template_path + '.yaml' if not template_path.endswith('.yaml') else template_path

        # Build YAML structure with metadata header
        yaml_data = {
            "tools": template_tools
        }

        # Custom YAML Dumper to disable anchors/aliases and handle multiline strings
        class NoAliasDumper(yaml.SafeDumper):
            """Custom YAML Dumper that disables anchors/aliases for cleaner output."""
            def ignore_aliases(self, data):
                return True

        # Custom representer for multiline strings
        def str_representer(dumper, data):
            if '\n' in data:
                return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
            return dumper.represent_scalar('tag:yaml.org,2002:str', data)

        NoAliasDumper.add_representer(str, str_representer)

        # Generate YAML content with header comments
        yaml_header = """# =============================================================================
# MCP Tool Definition Templates - AUTO-GENERATED
# =============================================================================
# Signatures extracted from source code using AST parsing
#
# 구조 설명:
#   - name: MCP 도구 이름 (고유 식별자)
#   - description: 도구 설명 (에이전트가 도구 선택 시 참고)
#   - inputSchema: 입력 파라미터 스키마 (JSON Schema 형식)
#   - mcp_service: 백엔드 서비스 연결 정보
#   - mcp_service_factors: 내부 파라미터 기본값 설정
# =============================================================================

"""
        yaml_content = yaml.dump(yaml_data, Dumper=NoAliasDumper, default_flow_style=False, allow_unicode=True, sort_keys=False, indent=2)

        # Ensure template directory exists
        os.makedirs(os.path.dirname(yaml_path), exist_ok=True)

        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write(yaml_header + yaml_content)

        print(f"Saved template to: {os.path.relpath(yaml_path, BASE_DIR)}")

        # Also generate .py wrapper file that loads the YAML
        py_path = yaml_path.replace('.yaml', '.py')
        py_wrapper_content = '''"""
MCP Tool Definition Templates - AUTO-GENERATED
Signatures extracted from source code using AST parsing

이 파일은 tool_definition_templates.yaml을 로드하여 MCP_TOOLS 리스트를 제공합니다.
"""
from typing import List, Dict, Any
from pathlib import Path
import yaml


def _load_tools_from_yaml() -> List[Dict[str, Any]]:
    """YAML 파일에서 도구 정의를 로드합니다."""
    yaml_path = Path(__file__).parent / "tool_definition_templates.yaml"

    if not yaml_path.exists():
        raise FileNotFoundError(f"YAML 파일을 찾을 수 없습니다: {yaml_path}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data.get("tools", [])


# 기존 코드와의 호환성을 위해 MCP_TOOLS 리스트 제공
MCP_TOOLS: List[Dict[str, Any]] = _load_tools_from_yaml()
'''
        with open(py_path, "w", encoding="utf-8") as f:
            f.write(py_wrapper_content)

        print(f"Saved py wrapper to: {os.path.relpath(py_path, BASE_DIR)}")

        return {"success": True, "saved": os.path.relpath(yaml_path, BASE_DIR)}
    except Exception as e:
        return {"error": str(e)}
