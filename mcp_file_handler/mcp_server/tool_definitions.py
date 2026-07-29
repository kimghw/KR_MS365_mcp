"""
MCP Tool Definitions - YAML 로더 래퍼

SSOT인 mcp_editor/mcp_file_handler/tool_definition_templates.yaml을 로드하여
MCP_TOOLS 리스트를 제공합니다. (mcp_outlook/mcp_server/server_stream.py와 동일 패턴)

경로 우선순위:
    1. MCP_YAML_PATH 환경변수
    2. <project_root>/mcp_editor/mcp_file_handler/tool_definition_templates.yaml
"""
import os
from pathlib import Path
from typing import Any, Dict, List

import yaml


def _load_tools_from_yaml() -> List[Dict[str, Any]]:
    """YAML 파일에서 도구 정의를 로드합니다."""
    yaml_path_str = os.environ.get("MCP_YAML_PATH")
    if yaml_path_str:
        yaml_path = Path(yaml_path_str)
    else:
        project_root = Path(__file__).resolve().parent.parent.parent
        yaml_path = project_root / "mcp_editor" / "mcp_file_handler" / "tool_definition_templates.yaml"

    if not yaml_path.exists():
        raise FileNotFoundError(f"Tool definition YAML not found: {yaml_path}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data.get("tools", [])


MCP_TOOLS: List[Dict[str, Any]] = _load_tools_from_yaml()
