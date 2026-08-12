"""
도구 정의(ToolSpec) 스키마 정규화 — 단일 기준(SSOT).

배경
----
`inputSchema` 를 다루는 로직이 생성기와 템플릿에 각각 복사돼 있었고 서로
드리프트했다. 특히 boolean -> "enabled"/"disabled" 변환이 두 벌 존재하면서
한쪽만 description 접미사를 붙이는 차이가 생겼다. 그 결과 생성 시점에
`tools_list` 에 구워진 스키마와, 실행 시점에 YAML 에서 다시 로드한 스키마가
달라졌다.

또한 어느 쪽도 `inputSchema` 의 형태를 보장하지 않아서
(`{}` 이거나, `type` 이 없거나, `properties` 가 없는 경우가 섞임)
입력 검증을 켜는 순간 계약 불일치가 런타임 실패로 드러난다.

이 모듈이 그 기준이다. 아래 두 소비자가 같은 규칙을 쓰게 한다:

1. `mcp_editor/jinja/generate_universal_server.py` — 생성 시점.
   이 모듈을 직접 import 한다.
2. `mcp_editor/jinja/python/_schema_helpers.jinja2` — 실행 시점.
   생성된 서버에 코드로 baked-in 되므로 import 가 아니라 "같은 규칙을
   옮겨 적은 것"이다. **이 모듈을 고치면 그 partial 도 함께 고쳐야 한다.**
   (생성된 서버는 mcp_editor 에 의존하면 안 되므로 import 로 합칠 수 없다.)

핵심 불변식
-----------
- `normalize_input_schema()` 결과는 항상
  `{"type": "object", "properties": {...}}` 를 만족한다.
- `required` 는 **절대 유실되지 않는다.** 리스트로 정규화만 하고 내용은 보존한다.
- 변환 함수들은 멱등(idempotent)이다. 이미 변환된 스키마에 다시 적용해도
  enum 이 중복되거나 description 접미사가 두 번 붙지 않는다.
"""

from typing import Any, Dict, List, Optional

# boolean 을 대체하는 문자열 enum. OpenAI function-calling 이 boolean 타입을
# 지원하지 않아서 도입됐다.
ENABLED = "enabled"
DISABLED = "disabled"
ENABLED_DISABLED_ENUM = [ENABLED, DISABLED]

# 변환된 파라미터의 description 에 붙는 설명 접미사.
BOOL_DESCRIPTION_SUFFIX = " (enabled=true, disabled=false)"

__all__ = [
    "ENABLED",
    "DISABLED",
    "ENABLED_DISABLED_ENUM",
    "BOOL_DESCRIPTION_SUFFIX",
    "normalize_input_schema",
    "normalize_required",
    "convert_boolean_schema_to_enabled_disabled",
    "collect_boolean_params",
    "convert_enabled_to_bool",
    "convert_bool_to_enabled",
    "coerce_boolean_enums_for_schema",
    "normalize_tool_list",
]


def normalize_required(required: Any) -> Optional[List[str]]:
    """`required` 를 문자열 리스트로 정규화한다.

    값이 없으면 None 을 돌려준다(호출자가 키 자체를 제거하도록).
    내용은 절대 버리지 않는다.
    """
    if required is None:
        return None
    if isinstance(required, str):
        return [required]
    if isinstance(required, (list, tuple, set)):
        return [str(item) for item in required]
    return None


def normalize_input_schema(schema: Any) -> Dict[str, Any]:
    """inputSchema 를 항상 `{"type": "object", "properties": {...}}` 형태로 만든다.

    입력 검증이 켜진 뒤에는 스키마 형태가 곧 계약이므로, list_tools 로 노출되는
    스키마와 검증 기준이 항상 같은 모양이어야 한다.

    `required` 를 포함한 나머지 키는 모두 보존된다.
    """
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    result = dict(schema)
    # MCP 도구 입력 스키마는 반드시 object 여야 한다. `{"type": "array"}` 처럼
    # truthy 하지만 object 가 아닌 타입은 그대로 두면 properties 를 얻고도 array 로
    # 남아, 런타임 검증기가 배열을 기대하는데 인자는 object 로 들어와 항상 깨진다.
    if result.get("type") != "object":
        result["type"] = "object"

    properties = result.get("properties")
    result["properties"] = properties if isinstance(properties, dict) else {}

    required = normalize_required(result.get("required"))
    if required is None:
        result.pop("required", None)
    else:
        result["required"] = required

    return result


def convert_boolean_schema_to_enabled_disabled(schema: Any) -> Dict[str, Any]:
    """boolean 타입 속성을 enabled/disabled 문자열 enum 으로 변환한다.

        type: boolean, default: true  -> type: string, enum: [...], default: "enabled"
        type: boolean, default: false -> type: string, enum: [...], default: "disabled"

    중첩된 object 속성도 재귀적으로 처리한다.
    멱등하다: 이미 변환된 스키마를 다시 넣어도 결과가 달라지지 않는다.
    `required` 는 건드리지 않는다(그대로 보존).
    """
    if not isinstance(schema, dict):
        return schema

    result = dict(schema)

    properties = result.get("properties")
    if not isinstance(properties, dict):
        return result

    new_properties: Dict[str, Any] = {}
    for prop_name, prop_def in properties.items():
        if not isinstance(prop_def, dict):
            new_properties[prop_name] = prop_def
            continue

        prop_type = prop_def.get("type")

        if prop_type == "boolean":
            new_prop = dict(prop_def)
            new_prop["type"] = "string"
            new_prop["enum"] = list(ENABLED_DISABLED_ENUM)

            if "default" in new_prop:
                new_prop["default"] = ENABLED if new_prop["default"] else DISABLED

            description = new_prop.get("description")
            # 멱등: 접미사가 이미 있으면 다시 붙이지 않는다.
            if description and not description.endswith(BOOL_DESCRIPTION_SUFFIX):
                new_prop["description"] = f"{description}{BOOL_DESCRIPTION_SUFFIX}"

            new_properties[prop_name] = new_prop

        elif prop_type == "object":
            new_properties[prop_name] = convert_boolean_schema_to_enabled_disabled(prop_def)

        else:
            new_properties[prop_name] = prop_def

    result["properties"] = new_properties
    return result


def collect_boolean_params(schema: Any) -> List[str]:
    """변환 **이전** 스키마에서 boolean 인 최상위 속성 이름을 모은다.

    핸들러가 enabled/disabled 문자열을 다시 bool 로 되돌려야 할 파라미터 목록이다.
    """
    if not isinstance(schema, dict):
        return []
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []
    return [
        name
        for name, prop in properties.items()
        if isinstance(prop, dict) and prop.get("type") == "boolean"
    ]


def convert_enabled_to_bool(value: Any) -> bool:
    """"enabled"/"disabled" 문자열을 bool 로 되돌린다."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == ENABLED
    return False


def convert_bool_to_enabled(value: Any) -> str:
    """bool 을 "enabled"/"disabled" 문자열로 바꾼다."""
    return ENABLED if value else DISABLED


def coerce_boolean_enums_for_schema(schema: Any, arguments: Any) -> Dict[str, Any]:
    """검증 **전에** 구형 클라이언트의 실제 bool 값을 enabled/disabled 로 정규화한다.

    YAML 의 boolean 파라미터는 OpenAI 호환을 위해 enabled/disabled 문자열 enum 으로
    노출된다. 입력 검증이 켜진 뒤로는 클라이언트가 진짜 bool(`true`)을 보내면
    "expected type string" 으로 거절되므로, 하위 호환을 위해 여기서 흡수한다.

    각 프로토콜 템플릿(stdio/rest/stream)은 `coerce_boolean_enums(tool_name, args)`
    라는 얇은 래퍼로 이 함수를 호출한다.
    """
    properties = (schema or {}).get("properties") or {}
    coerced = dict(arguments or {})
    for name, value in list(coerced.items()):
        prop = properties.get(name)
        if not isinstance(prop, dict) or not isinstance(value, bool):
            continue
        if prop.get("type") == "string" and prop.get("enum") == ENABLED_DISABLED_ENUM:
            coerced[name] = convert_bool_to_enabled(value)
    return coerced


def normalize_tool_list(tools: Any, *, convert_booleans: bool = True) -> List[Dict[str, Any]]:
    """도구 목록 전체에 스키마 정규화를 적용한다.

    YAML/JSON 에서 갓 읽어온 도구 목록에 쓰는 진입점이다.
    각 도구의 `inputSchema` 를 제자리에서 갱신하고 같은 리스트를 돌려준다.

    convert_booleans:
        True  — 형태 정규화 + boolean -> enabled/disabled 변환.
                실행 시점 로더(생성된 서버의 `_load_mcp_tools`)용.
        False — 형태 정규화만.
                **생성 시점 로더는 반드시 False 를 써야 한다.** 생성기는 나중에
                원본 `type: boolean` 을 보고 어떤 파라미터에
                `convert_enabled_to_bool()` 호출을 심을지 결정하기 때문에,
                여기서 미리 변환해 버리면 그 탐지가 전부 실패해 생성된 핸들러가
                문자열 "enabled" 를 bool 대신 그대로 서비스에 넘기게 된다.
    """
    if not isinstance(tools, list):
        return []

    for tool in tools:
        if not isinstance(tool, dict):
            continue
        schema = normalize_input_schema(tool.get("inputSchema"))
        if convert_booleans:
            schema = convert_boolean_schema_to_enabled_disabled(schema)
        tool["inputSchema"] = schema

    return tools
