"""
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
