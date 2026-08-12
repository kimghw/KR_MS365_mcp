"""
param_spec 로더 — 도구 계약의 단일 원본을 기동 시 읽어 파생시킨다.

2026-08-12 사용자 확정: **코드 생성(jinja 템플릿 + generate_universal_server.py)을 폐지하고
API 를 spec 으로 관리한다.** 도구 이름·설명·파라미터·옵션·필수여부·기본값은
`spec/param_spec/<도메인>.yaml` 한 곳에만 적고, `inputSchema` 와 서비스 호출 인자는
전부 여기서 파생시킨다. 미리 구워 둔 산출물은 없다.

관련 사양: spec/spec_도구정의.md, spec/spec_MCP트랜스포트.md

## 파일 형태

    server:
      name: calendar
      version: "1.0.0"
      port: 5002

    tools:
      - name: calendar_view
        description: 캘린더 일정을 기간으로 조회합니다.
        service: CalendarService.calendar_view   # 이 도구가 래핑하는 서비스 함수
        params:
          - name: user_email
            type: string          # string|integer|number|boolean|array|object
            required: true
            expose: tool          # tool | internal | hidden
            description: 조회할 사용자의 이메일 주소
          - name: top
            type: integer
            required: false
            expose: tool
            default: 50
            description: 최대 결과 수
          - name: orderby
            type: string
            required: false
            expose: tool
            enum: [start, subject]
            description: 정렬 기준
          - name: select_params
            type: object
            required: false
            expose: internal      # 툴 입력으로 노출하지 않고 서버가 값을 주입
            default: null
            targetParam: select_params
            description: 내부 조회 필드 지정

## expose 의미

- `tool`     — `inputSchema.properties` 에 노출. 에이전트가 채운다.
- `internal` — 노출하지 않고 서버가 `default` 를 주입한다. `default` 또는 `fields` 필수.
- `hidden`   — 호출에 아예 쓰지 않는다. 서비스 함수의 시그니처 기본값에 맡긴다.

## 객체 파라미터 — `fields`

`type: object` 인 파라미터는 `fields:` 로 하위 필드를 적을 수 있다. `expose` 에 따라
역할이 갈리지만 **필드별 설명이 spec 에 남는다**는 점은 같다. 이 설명은 함수 시그니처에서
복원할 수 없으므로 여기서 잃으면 영영 잃는다.

`expose: tool` — 중첩 `inputSchema.properties` 가 된다:

    - name: DatePeriodFilter
      type: object
      required: true
      expose: tool
      description: "검색 범위의 날짜"
      baseModel: FilterParams        # 대응하는 Pydantic 모델 이름 (표식)
      targetParam: filter_params     # 서비스 인자 이름
      fields:
        - name: received_date_from
          type: string
          required: true
          description: "메일 수신 시작 날짜"
          targetParam: received_date_from

`expose: internal` — 서버가 주입할 값의 필드표가 된다. 각 필드의 `default` 를 모아
dict 를 자동으로 만들므로 `default:` 를 따로 적지 않아도 된다. 핸들러는 그 dict 로
Pydantic 모델을 만든다 — `SelectParams(**SPEC.call_args(...)["select_params"])`:

    - name: select
      type: object
      required: false
      expose: internal
      baseModel: SelectParams
      targetParam: select_params
      description: "조회할 메일 필드"
      fields:
        - name: body_preview
          type: boolean
          default: true
          description: "메시지 본문의 처음 255자"

`baseModel` 과 `targetParam` 은 적으면 파생 스키마에 그대로 실린다(기존 동작 보존).

## service — 래핑하는 서비스 함수 (필수)

도구 하나는 서비스 함수 하나를 래핑하며, 그 바인딩은 **spec 의 `service:` 필드가
유일한 선언처**다 (`클래스.메서드` 표기, 예: `MailService.fetch_search`). 같은 함수를
여러 도구가 래핑할 수 있다(outlook 의 `fetch_search` 는 2개 도구가 쓴다).
`handlers.py` 는 이 선언의 배선일 뿐이고, spec 과 다르게 배선하면 위반이다 — 도구가
무슨 함수를 부르는지 알려고 코드를 열게 만들지 않는 것이 이 필드의 목적이다.

## 검증

로드 시점에 계약 위반을 **즉시 오류로 올린다**(CLAUDE.md "필수/선택 일관성"):

- `service` 가 없거나 비어 있으면 오류
- `required: true` 인데 `default` 가 있으면 오류
- `expose: internal` 인데 `default` 가 없으면 오류
- 같은 도구 안에 같은 파라미터 이름이 두 번 나오면 오류
- 알 수 없는 `type` / `expose` 값이면 오류

기동 시 죽는 편이, 잘못된 스키마를 에이전트에게 노출한 채 도는 것보다 안전하다.
"""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from mcp_common.schema_normalize import (
    coerce_boolean_enums_for_schema,
    collect_boolean_params,
    convert_enabled_to_bool,
    normalize_tool_list,
)

VALID_TYPES = {"string", "integer", "number", "boolean", "array", "object"}
VALID_EXPOSE = {"tool", "internal", "hidden"}

#: `default` 키가 아예 없는 것과 `default: null` 을 구분하기 위한 표식.
_MISSING = object()


class ParamSpecError(ValueError):
    """param_spec 파일의 계약 위반. 기동을 막는다."""


@dataclass(frozen=True)
class Field:
    """`type: object` 파라미터를 이루는 하위 필드.

    두 가지 역할을 겸한다 (파라미터의 `expose` 가 결정한다):

    - `expose: tool`     — 중첩 `inputSchema.properties` 가 된다. 에이전트가 채운다.
    - `expose: internal` — 서버가 주입할 값의 필드표가 된다. 각 `default` 를 모아
      dict 를 만들고, 핸들러가 그것으로 Pydantic 모델을 만든다.

    두 경우 모두 **필드별 설명이 spec 에 남는다** — 이 정보는 함수 시그니처에서
    복원할 수 없으므로 여기서 잃으면 영영 잃는다.
    """

    name: str
    type: str
    description: str = ""
    default: Any = None
    has_default: bool = False
    required: bool = False
    enum: Optional[List[Any]] = None
    target_param: Optional[str] = None
    #: `type: array` 일 때 원소 스키마. JSON Schema 조각을 그대로 싣는다.
    items: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class Param:
    name: str
    type: str
    required: bool
    expose: str
    description: str = ""
    default: Any = None
    has_default: bool = False
    enum: Optional[List[Any]] = None
    #: 서비스 함수의 인자 이름이 도구 파라미터 이름과 다를 때 매핑
    target_param: Optional[str] = None
    order: Optional[int] = None
    #: `type: object` 일 때의 하위 필드 (중첩 스키마 또는 주입 필드표)
    fields: Optional[List[Field]] = None
    #: 이 객체가 대응하는 Pydantic 모델 이름. 문서·핸들러 참조용 표식이다.
    base_model: Optional[str] = None
    #: `type: array` 일 때 원소 스키마. JSON Schema 조각을 그대로 싣는다.
    items: Optional[Dict[str, Any]] = None

    @property
    def service_arg(self) -> str:
        return self.target_param or self.name


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    #: 이 도구가 래핑하는 서비스 함수 (`클래스.메서드`). 바인딩의 유일한 선언처다.
    service: str = ""
    params: List[Param] = field(default_factory=list)

    def param(self, name: str) -> Optional[Param]:
        for p in self.params:
            if p.name == name:
                return p
        return None


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ParamSpecError(message)


def _parse_field(raw: Dict[str, Any], where: str) -> Field:
    _require(isinstance(raw, dict), f"[{where}] fields 항목은 매핑이어야 한다: {raw!r}")
    name = raw.get("name")
    _require(bool(name), f"[{where}] fields 항목에 name 이 없다: {raw!r}")

    ftype = raw.get("type")
    _require(
        ftype in VALID_TYPES,
        f"[{where}.{name}] type 이 {sorted(VALID_TYPES)} 중 하나여야 한다 (받은 값: {ftype!r})",
    )

    default = raw.get("default", _MISSING)
    has_default = default is not _MISSING
    required = bool(raw.get("required", False))
    _require(
        not (required and has_default),
        f"[{where}.{name}] required: true 인데 default 가 있다 — 둘 중 하나만 둬라",
    )

    enum = raw.get("enum")
    if enum is not None:
        _require(
            isinstance(enum, list) and len(enum) > 0,
            f"[{where}.{name}] enum 은 비어 있지 않은 리스트여야 한다",
        )

    return Field(
        name=name,
        type=ftype,
        description=raw.get("description", "") or "",
        default=None if not has_default else default,
        has_default=has_default,
        required=required,
        enum=enum,
        target_param=raw.get("targetParam"),
        items=_parse_items(raw, f"{where}.{name}", ftype),
    )


def _parse_items(raw: Dict[str, Any], where: str, ptype: str) -> Optional[Dict[str, Any]]:
    """`items` 는 JSON Schema 조각이라 해석하지 않고 그대로 싣는다."""
    items = raw.get("items")
    if items is None:
        return None
    _require(
        ptype == "array",
        f"[{where}] items 는 type: array 인 것에만 쓸 수 있다 (받은 type: {ptype!r})",
    )
    _require(isinstance(items, dict), f"[{where}] items 는 매핑이어야 한다: {items!r}")
    return items


def _parse_param(raw: Dict[str, Any], tool_name: str) -> Param:
    where = f"{tool_name}"
    _require(isinstance(raw, dict), f"[{where}] params 항목은 매핑이어야 한다: {raw!r}")

    name = raw.get("name")
    _require(bool(name), f"[{where}] params 항목에 name 이 없다: {raw!r}")
    where = f"{tool_name}.{name}"

    ptype = raw.get("type")
    _require(
        ptype in VALID_TYPES,
        f"[{where}] type 이 {sorted(VALID_TYPES)} 중 하나여야 한다 (받은 값: {ptype!r})",
    )

    expose = raw.get("expose")
    _require(
        expose in VALID_EXPOSE,
        f"[{where}] expose 가 {sorted(VALID_EXPOSE)} 중 하나여야 한다 (받은 값: {expose!r})",
    )

    _require("required" in raw, f"[{where}] required 를 명시해야 한다")
    required = bool(raw["required"])

    raw_fields = raw.get("fields")
    fields: Optional[List[Field]] = None
    if raw_fields is not None:
        _require(
            ptype == "object",
            f"[{where}] fields 는 type: object 인 파라미터에만 쓸 수 있다 (받은 type: {ptype!r})",
        )
        _require(isinstance(raw_fields, list), f"[{where}] fields 는 리스트여야 한다")
        fields = [_parse_field(f, where) for f in raw_fields]
        seen_fields = set()
        for f in fields:
            _require(f.name not in seen_fields, f"[{where}] 필드 이름이 중복됐다: {f.name}")
            seen_fields.add(f.name)

    default = raw.get("default", _MISSING)
    has_default = default is not _MISSING

    # expose: internal + fields 이면 주입값을 필드표에서 파생시킨다.
    # 기본값이 코드로 새어나가지 않게 하려는 것이 이 형식의 요점이다.
    if expose == "internal" and not has_default and fields is not None:
        default = {f.name: f.default for f in fields if f.has_default}
        has_default = True

    # CLAUDE.md: required 와 default 를 동시에 두면 어느 쪽이 진짜인지 알 수 없다.
    _require(
        not (required and has_default),
        f"[{where}] required: true 인데 default 가 있다 — 둘 중 하나만 둬라",
    )
    _require(
        not (expose == "internal" and not has_default),
        f"[{where}] expose: internal 은 서버가 주입할 default 또는 fields 가 필요하다",
    )

    enum = raw.get("enum")
    if enum is not None:
        _require(
            isinstance(enum, list) and len(enum) > 0,
            f"[{where}] enum 은 비어 있지 않은 리스트여야 한다",
        )

    return Param(
        name=name,
        type=ptype,
        required=required,
        expose=expose,
        description=raw.get("description", "") or "",
        default=None if not has_default else default,
        has_default=has_default,
        enum=enum,
        target_param=raw.get("targetParam"),
        order=raw.get("order"),
        fields=fields,
        base_model=raw.get("baseModel"),
        items=_parse_items(raw, where, ptype),
    )


def _parse_tool(raw: Dict[str, Any]) -> Tool:
    _require(isinstance(raw, dict), f"tools 항목은 매핑이어야 한다: {raw!r}")
    name = raw.get("name")
    _require(bool(name), f"tools 항목에 name 이 없다: {raw!r}")

    description = raw.get("description", "") or ""
    _require(
        bool(description.strip()),
        f"[{name}] description 이 비어 있다 — 에이전트가 읽는 설명이라 필수다",
    )

    service = raw.get("service", "") or ""
    _require(
        bool(service.strip()),
        f"[{name}] service 가 없다 — 이 도구가 래핑하는 서비스 함수(클래스.메서드)를 선언하라",
    )

    raw_params = raw.get("params") or []
    _require(isinstance(raw_params, list), f"[{name}] params 는 리스트여야 한다")

    params = [_parse_param(p, name) for p in raw_params]

    seen = set()
    for p in params:
        _require(p.name not in seen, f"[{name}] 파라미터 이름이 중복됐다: {p.name}")
        seen.add(p.name)

    # order 가 있으면 그 순서로, 없으면 적힌 순서를 유지한다.
    params.sort(key=lambda p: (p.order is None, p.order if p.order is not None else 0))
    return Tool(name=name, description=description, service=service.strip(), params=params)


class ParamSpec:
    """도메인 하나의 도구 계약. `inputSchema` 와 호출 인자를 여기서 파생시킨다."""

    def __init__(self, server: Dict[str, Any], tools: List[Tool], source: str):
        self.server = server
        self.tools = tools
        self.source = source
        self._by_name = {t.name: t for t in tools}
        # boolean -> enabled/disabled 변환 전 스키마에서 boolean 파라미터를 미리 모아 둔다.
        # 변환 후에 모으면 이미 string 이라 탐지할 수 없다.
        self._raw_schemas = {t.name: self._raw_input_schema(t) for t in tools}
        self._boolean_params = {
            name: collect_boolean_params(schema) for name, schema in self._raw_schemas.items()
        }
        # 에이전트에게 실제로 나가는 스키마(boolean 이 enabled/disabled 로 바뀐 것).
        # 한 번만 만들어 두고 `mcp_tools()` 와 `coerce_arguments()` 가 같은 것을 쓴다.
        self._payload = normalize_tool_list(
            [
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": self._raw_schemas[t.name],
                }
                for t in tools
            ],
            convert_booleans=True,
        )
        self._exposed_schemas = {t["name"]: t.get("inputSchema", {}) for t in self._payload}

    # ------------------------------------------------------------------
    @property
    def name(self) -> str:
        return self.server.get("name", "")

    @property
    def version(self) -> str:
        return str(self.server.get("version", "1.0.0"))

    @property
    def port(self) -> Optional[int]:
        port = self.server.get("port")
        return int(port) if port is not None else None

    def tool(self, name: str) -> Optional[Tool]:
        return self._by_name.get(name)

    # ------------------------------------------------------------------
    @staticmethod
    def _field_property(f: Field) -> Dict[str, Any]:
        prop: Dict[str, Any] = {"type": f.type}
        if f.description:
            prop["description"] = f.description
        if f.enum is not None:
            prop["enum"] = list(f.enum)
        if f.items is not None:
            prop["items"] = f.items
        if f.has_default:
            prop["default"] = f.default
        if f.target_param:
            prop["targetParam"] = f.target_param
        return prop

    @classmethod
    def _raw_input_schema(cls, tool: Tool) -> Dict[str, Any]:
        """`expose: tool` 인 파라미터만으로 스키마를 만든다 (boolean 변환 전)."""
        properties: Dict[str, Any] = {}
        required: List[str] = []

        for p in tool.params:
            if p.expose != "tool":
                continue
            prop: Dict[str, Any] = {"type": p.type}
            if p.description:
                prop["description"] = p.description
            if p.enum is not None:
                prop["enum"] = list(p.enum)
            if p.items is not None:
                prop["items"] = p.items

            # type: object + fields → 중첩 스키마
            if p.fields:
                prop["properties"] = {f.name: cls._field_property(f) for f in p.fields}
                nested_required = [f.name for f in p.fields if f.required]
                if nested_required:
                    prop["required"] = nested_required

            if p.has_default:
                prop["default"] = p.default
            if p.base_model:
                prop["baseModel"] = p.base_model
            if p.target_param:
                prop["targetParam"] = p.target_param

            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        schema: Dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema

    def mcp_tools(self) -> List[Dict[str, Any]]:
        """`ToolRuntime` 에 넘길 MCP 도구 목록.

        boolean 은 `schema_normalize` 가 enabled/disabled 문자열 enum 으로 바꾼다
        (OpenAI function-calling 이 boolean 타입을 받지 않는다). 되돌리는 건
        `call_args()` 가 한다.
        """
        return self._payload

    # ------------------------------------------------------------------
    def coerce_arguments(self, tool_name: str, arguments: Any) -> Dict[str, Any]:
        """검증 **전** 보정. 구형 클라이언트가 보낸 진짜 bool 을 흡수한다.

        **반드시 노출 스키마(변환 후)를 넘겨야 한다.** `coerce_boolean_enums_for_schema`
        는 `type: string` + `enum: [enabled, disabled]` 인 속성만 손보므로, 변환 전
        스키마(`type: boolean`)를 넘기면 아무 일도 하지 않는다. 그러면 진짜 `true` 를
        보내는 기존 클라이언트가 `ToolRuntime` 검증에서 거절된다.
        """
        schema = self._exposed_schemas.get(tool_name)
        if schema is None:
            return dict(arguments or {})
        return coerce_boolean_enums_for_schema(schema, arguments)

    def call_args(self, tool_name: str, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """도구 입력을 **서비스 함수 호출 인자**로 바꾼다.

        - `expose: tool`     — 들어온 값, 없으면 default(있을 때만)
        - `expose: internal` — 항상 spec 의 default 를 주입
        - `expose: hidden`   — 넣지 않는다 (시그니처 기본값에 맡김)
        - enabled/disabled 문자열은 원래의 bool 로 되돌린다
        - `targetParam` 이 있으면 그 이름으로 넘긴다
        """
        tool = self._by_name.get(tool_name)
        if tool is None:
            raise ParamSpecError(f"[{self.name}] 알 수 없는 도구: {tool_name}")

        incoming = dict(arguments or {})
        boolean_params = self._boolean_params.get(tool_name, [])
        out: Dict[str, Any] = {}

        for p in tool.params:
            if p.expose == "hidden":
                continue

            if p.expose == "internal":
                out[p.service_arg] = p.default
                continue

            if p.name in incoming:
                value = incoming[p.name]
                if p.name in boolean_params:
                    value = convert_enabled_to_bool(value)
                out[p.service_arg] = value
            elif p.has_default:
                out[p.service_arg] = p.default

        return out


def spec_dir() -> str:
    """`spec/param_spec` 절대 경로. `MCP_PARAM_SPEC_DIR` 로 덮어쓸 수 있다."""
    override = os.environ.get("MCP_PARAM_SPEC_DIR")
    if override:
        return override
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, "spec", "param_spec")


def load_param_spec(domain: str, path: Optional[str] = None) -> ParamSpec:
    """`spec/param_spec/<domain>.yaml` 을 읽어 검증된 `ParamSpec` 을 돌려준다."""
    import yaml

    spec_path = path or os.path.join(spec_dir(), f"{domain}.yaml")
    if not os.path.exists(spec_path):
        raise ParamSpecError(f"param_spec 파일이 없다: {spec_path}")

    with open(spec_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    _require(isinstance(data, dict), f"{spec_path}: 최상위는 매핑이어야 한다")

    server = data.get("server") or {}
    _require(isinstance(server, dict), f"{spec_path}: server 는 매핑이어야 한다")
    _require(bool(server.get("name")), f"{spec_path}: server.name 이 없다")

    raw_tools = data.get("tools") or []
    _require(isinstance(raw_tools, list), f"{spec_path}: tools 는 리스트여야 한다")
    _require(bool(raw_tools), f"{spec_path}: tools 가 비어 있다")

    tools = [_parse_tool(t) for t in raw_tools]

    names = [t.name for t in tools]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    _require(not duplicates, f"{spec_path}: 도구 이름이 중복됐다: {duplicates}")

    return ParamSpec(server=server, tools=tools, source=spec_path)


__all__ = [
    "Param",
    "ParamSpec",
    "ParamSpecError",
    "Tool",
    "load_param_spec",
    "spec_dir",
]
