"""
입력 스키마 검증.

Stream 서버들이 `@server.call_tool(validate_input=False)` 로 검증을 꺼둔 탓에
"스키마에는 optional 인데 핸들러는 필수" 같은 계약 불일치가 런타임 KeyError 로만
드러났다. 여기서는 list_tools 로 노출되는 바로 그 스키마(enabled/disabled 변환이
적용된 형태)를 기준으로 검증한다.

의도적으로 최소 구현이다: jsonschema 런타임 의존성을 추가하지 않고
required / type / enum / nested object / array items 만 확인한다.
알 수 없는 추가 속성은 거부하지 않는다(하위 호환).

MCP_VALIDATE_INPUT=0 으로 끌 수 있다(긴급 우회용).
"""

import os
from typing import Any, Dict, List, Optional

from mcp_common.errors import ToolValidationError

_TYPE_MAP = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def _type_ok(value: Any, expected: Any) -> bool:
    if expected is None:
        return True
    if isinstance(expected, list):
        return any(_type_ok(value, item) for item in expected)
    py_type = _TYPE_MAP.get(expected)
    if py_type is None:
        return True
    if expected == "integer" and isinstance(value, bool):
        return False
    if expected == "number" and isinstance(value, bool):
        return False
    return isinstance(value, py_type)


def _validate_node(value: Any, schema: Dict[str, Any], path: str, errors: List[str]) -> None:
    if not isinstance(schema, dict):
        return

    expected_type = schema.get("type")
    if expected_type is not None and not _type_ok(value, expected_type):
        errors.append(
            f"{path or '<root>'}: expected type {expected_type}, got {type(value).__name__}"
        )
        return

    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        errors.append(f"{path or '<root>'}: value {value!r} not in {enum}")

    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        for key in schema.get("required") or []:
            if key not in value or value[key] is None:
                errors.append(f"{path + '.' if path else ''}{key}: required property missing")
        for key, sub_schema in properties.items():
            if key in value and value[key] is not None:
                _validate_node(value[key], sub_schema, f"{path + '.' if path else ''}{key}", errors)

    elif isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                _validate_node(item, items, f"{path}[{index}]", errors)


def validation_enabled() -> bool:
    flag = os.environ.get("MCP_VALIDATE_INPUT")
    if flag is None:
        return True
    return flag.strip().lower() not in ("0", "false", "no", "off")


def validate_arguments(
    schema: Optional[Dict[str, Any]],
    arguments: Optional[Dict[str, Any]],
    *,
    tool: Optional[str] = None,
) -> None:
    """검증 실패 시 ToolValidationError(→ isError=True) 를 던진다."""
    if not schema or not validation_enabled():
        return

    errors: List[str] = []
    _validate_node(arguments or {}, schema, "", errors)
    if errors:
        raise ToolValidationError(
            {
                "status": "error",
                "error": "invalid_arguments",
                "tool": tool,
                "violations": errors,
            },
            tool=tool,
        )


def apply_schema_defaults(
    schema: Optional[Dict[str, Any]], arguments: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """inputSchema 의 default 를 인자에 채워 넣는다(최상위 속성만).

    명시적 None 은 "값 없음"으로 취급한다. 그렇지 않으면 클라이언트가 optional 인자에
    `null` 을 보낼 때 transport 마다 동작이 갈린다(stream 은 default 치환, stdio 는 생략).
    default 가 있으면 default 로 채우고, 없으면 키를 제거해 핸들러의 시그니처 기본값에 맡긴다.
    """
    merged = dict(arguments or {})
    if not schema:
        return merged
    for name, prop in (schema.get("properties") or {}).items():
        if not isinstance(prop, dict):
            continue
        has_default = "default" in prop
        if name not in merged and has_default:
            merged[name] = prop["default"]
        elif merged.get(name) is None and name in merged:
            if has_default:
                merged[name] = prop["default"]
            else:
                del merged[name]
    return merged
