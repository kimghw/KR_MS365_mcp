#!/usr/bin/env python3
"""
동기화 가드: `_schema_helpers.jinja2` <-> `schema_normalize.py`

왜 필요한가
-----------
스키마 정규화 / boolean <-> enabled·disabled 변환 규칙은
`mcp_editor/service_registry/schema_normalize.py` 가 SSOT 다.

그런데 생성된 도메인 서버(mcp_outlook/mcp_server/server_*.py 등)는
mcp_editor(에디터 도구)에 의존하면 안 되므로 이 규칙을 import 할 수 없고,
`mcp_editor/jinja/python/_schema_helpers.jinja2` 가 같은 규칙을 코드로
baked-in 한다. 즉 **두 구현이 물리적으로 분리돼 있다.**

예전에 정확히 이 분리 때문에 사고가 났다: 생성기 쪽만 description 에
" (enabled=true, disabled=false)" 접미사를 붙이고 템플릿 쪽은 안 붙여서,
생성 시점에 구워진 스키마와 실행 시점에 YAML 에서 다시 읽은 스키마가
서로 달랐다.

이 테스트는 두 구현이 다시 갈라지면 즉시 실패한다.

실행 방법
---------
pytest 없이 그냥 실행해도 결과가 나온다:

    python mcp_editor/service_registry/test_schema_helpers_sync.py

pytest 가 있으면 test_* 함수로도 수집된다:

    pytest mcp_editor/service_registry/test_schema_helpers_sync.py

jinja2 가 설치돼 있으면 템플릿을 정식으로 렌더해서 비교하고, 없으면
`_schema_helpers.jinja2` 에 Jinja 변수가 없다는 성질을 이용해 Jinja 주석만
제거하고 그대로 파이썬으로 실행한다(둘 다 같은 코드를 검사한다).
"""

import copy
import re
import sys
from pathlib import Path
from typing import Any, Dict

# 프로젝트 루트를 sys.path 에 올린다.
# mcp_editor/service_registry/test_schema_helpers_sync.py -> parents[2] == 프로젝트 루트
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from mcp_editor.service_registry import schema_normalize as ssot  # noqa: E402

TEMPLATE_PATH = _PROJECT_ROOT / "mcp_editor" / "jinja" / "python" / "_schema_helpers.jinja2"


# ----------------------------------------------------------------------------
# 템플릿이 emit 하는 파이썬 코드를 실행해서 함수들을 얻는다
# ----------------------------------------------------------------------------

def _render_template_source() -> str:
    """`_schema_helpers.jinja2` 가 만들어내는 파이썬 소스를 얻는다."""
    raw = TEMPLATE_PATH.read_text(encoding="utf-8")

    try:
        from jinja2 import Environment, FileSystemLoader
    except ImportError:
        # jinja2 가 없어도 가드는 동작해야 한다.
        # 이 partial 은 Jinja 변수/제어구문 없이 주석 하나만 쓰므로 주석만 제거하면 된다.
        source = re.sub(r"\{#.*?#\}", "", raw, flags=re.DOTALL)
        leftovers = [tag for tag in ("{{", "{%") if tag in source]
        if leftovers:
            raise RuntimeError(
                f"{TEMPLATE_PATH.name} 에 Jinja 구문 {leftovers} 이 생겼다. "
                "이 폴백은 변수 없는 partial 을 전제로 한다 — jinja2 를 설치하고 실행하라."
            )
        return source

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH.parent)))
    return env.get_template(TEMPLATE_PATH.name).render()


def _load_emitted_helpers() -> Dict[str, Any]:
    """렌더된 소스를 실행해 함수 네임스페이스를 돌려준다."""
    source = _render_template_source()
    namespace: Dict[str, Any] = {"Any": Any, "Dict": Dict}
    exec(compile(source, str(TEMPLATE_PATH), "exec"), namespace)
    return namespace


# ----------------------------------------------------------------------------
# 대표 입력 집합
# ----------------------------------------------------------------------------

# 스키마 정규화 + boolean 변환 대상
SCHEMA_CASES = [
    # --- 비정상/결측 입력 ---
    None,
    {},
    [],
    "not-a-schema",
    {"type": "object"},
    {"properties": {}},

    # --- required 보존 ---
    {"properties": {"a": {"type": "string"}}, "required": ["a"]},
    {"properties": {"a": {"type": "string"}}, "required": "a"},          # 문자열 -> 리스트
    {"properties": {"a": {"type": "string"}}, "required": ("a", "b")},   # 튜플 -> 리스트
    {"properties": {"a": {"type": "string"}}, "required": None},         # 키 제거
    {"required": ["only_required"]},                                     # properties 없음
    {"type": "object", "properties": {"a": {"type": "string"}},
     "required": ["a"], "additionalProperties": False},                  # 기타 키 보존

    # --- boolean 변환 ---
    {"properties": {"f": {"type": "boolean"}}},
    {"properties": {"f": {"type": "boolean", "default": True}}},
    {"properties": {"f": {"type": "boolean", "default": False}}},
    {"properties": {"f": {"type": "boolean", "default": True, "description": "flag"}},
     "required": ["f"]},
    {"properties": {"f": {"type": "boolean", "description": "flag"}}},

    # --- boolean 인데 description 에 접미사가 이미 붙어 있는 경우 ---
    # 접미사 중복 방지(멱등) 로직을 실제로 건드리는 유일한 입력이다.
    # 1차 변환에서 type 이 string 으로 바뀌므로, 변환된 결과를 다시 넣는 것만으로는
    # 이 분기를 타지 않는다 -> 반드시 type:boolean 상태로 접미사가 있어야 한다.
    {"properties": {"f": {"type": "boolean",
                          "description": "flag (enabled=true, disabled=false)"}}},
    {"properties": {"f": {"type": "boolean", "default": True,
                          "description": "flag (enabled=true, disabled=false)"}},
     "required": ["f"]},

    # --- 중첩 object ---
    {"properties": {"o": {"type": "object", "properties": {"g": {"type": "boolean"}}}}},
    {"properties": {"o": {"type": "object",
                          "properties": {"g": {"type": "boolean", "default": False},
                                         "h": {"type": "string"}},
                          "required": ["g"]}},
     "required": ["o"]},

    # --- 섞인 타입 / 이상한 값 ---
    {"properties": {"a": {"type": "string"}, "b": {"type": "integer"},
                    "c": {"type": "boolean"}, "d": "not-a-dict"}},
    {"properties": "not-a-dict"},

    # --- 이미 변환된 입력 (멱등성) ---
    {"properties": {"f": {"type": "string", "enum": ["enabled", "disabled"],
                          "default": "enabled",
                          "description": "flag (enabled=true, disabled=false)"}},
     "required": ["f"]},
]

# convert_enabled_to_bool / convert_bool_to_enabled 대상
SCALAR_CASES = [
    "enabled", "disabled", "ENABLED", "Disabled", " enabled ",
    True, False, None, 0, 1, "", "yes",
]

# coerce_boolean_enums_for_schema 대상 (schema, arguments)
COERCE_CASES = [
    (None, None),
    ({}, {}),
    ({"properties": {"f": {"type": "string", "enum": ["enabled", "disabled"]}}}, {"f": True}),
    ({"properties": {"f": {"type": "string", "enum": ["enabled", "disabled"]}}}, {"f": False}),
    ({"properties": {"f": {"type": "string", "enum": ["enabled", "disabled"]}}}, {"f": "enabled"}),
    ({"properties": {"f": {"type": "string", "enum": ["on", "off"]}}}, {"f": True}),
    ({"properties": {"f": {"type": "boolean"}}}, {"f": True}),
    ({"properties": {"f": {"type": "string", "enum": ["enabled", "disabled"]}}},
     {"f": True, "other": 1, "s": "x"}),
    ({"properties": {}}, {"unknown": True}),
]


# ----------------------------------------------------------------------------
# 비교 로직
# ----------------------------------------------------------------------------

def _compare(label: str, expected: Any, actual: Any, failures: list) -> None:
    if expected != actual:
        failures.append(
            f"  [{label}]\n"
            f"      schema_normalize.py (SSOT) -> {expected!r}\n"
            f"      _schema_helpers.jinja2     -> {actual!r}"
        )


def check_sync() -> list:
    """두 구현을 대조하고 불일치 목록을 돌려준다."""
    emitted = _load_emitted_helpers()
    failures: list = []

    # 상수도 함께 검사 (enum 값이나 접미사가 갈라지면 스키마가 통째로 어긋난다)
    for const in ("ENABLED", "DISABLED", "ENABLED_DISABLED_ENUM", "BOOL_DESCRIPTION_SUFFIX"):
        _compare(f"const {const}", getattr(ssot, const), emitted.get(const), failures)

    for case in SCHEMA_CASES:
        label = repr(case)

        # 1) 정규화
        expected_norm = ssot.normalize_input_schema(copy.deepcopy(case))
        actual_norm = emitted["_normalize_input_schema"](copy.deepcopy(case))
        _compare(f"normalize_input_schema({label})", expected_norm, actual_norm, failures)

        # 2) boolean 변환
        expected_conv = ssot.convert_boolean_schema_to_enabled_disabled(copy.deepcopy(expected_norm))
        actual_conv = emitted["_convert_boolean_schema_to_enabled_disabled"](copy.deepcopy(actual_norm))
        _compare(f"convert_boolean(...)({label})", expected_conv, actual_conv, failures)

        # 3) 멱등성 — 다시 적용해도 같아야 한다 (양쪽 각각)
        _compare(
            f"idempotency/ssot({label})",
            expected_conv,
            ssot.convert_boolean_schema_to_enabled_disabled(copy.deepcopy(expected_conv)),
            failures,
        )
        _compare(
            f"idempotency/template({label})",
            actual_conv,
            emitted["_convert_boolean_schema_to_enabled_disabled"](copy.deepcopy(actual_conv)),
            failures,
        )

    for value in SCALAR_CASES:
        _compare(
            f"convert_enabled_to_bool({value!r})",
            ssot.convert_enabled_to_bool(value),
            emitted["convert_enabled_to_bool"](value),
            failures,
        )
        _compare(
            f"convert_bool_to_enabled({value!r})",
            ssot.convert_bool_to_enabled(value),
            emitted["convert_bool_to_enabled"](value),
            failures,
        )

    for schema, arguments in COERCE_CASES:
        _compare(
            f"coerce_boolean_enums_for_schema({schema!r}, {arguments!r})",
            ssot.coerce_boolean_enums_for_schema(copy.deepcopy(schema), copy.deepcopy(arguments)),
            emitted["coerce_boolean_enums_for_schema"](copy.deepcopy(schema), copy.deepcopy(arguments)),
            failures,
        )

    return failures


# ----------------------------------------------------------------------------
# pytest 진입점
# ----------------------------------------------------------------------------

def test_schema_helpers_match_schema_normalize():
    """_schema_helpers.jinja2 가 schema_normalize.py 와 동일하게 동작해야 한다."""
    failures = check_sync()
    assert not failures, (
        "_schema_helpers.jinja2 와 schema_normalize.py 가 갈라졌다:\n"
        + "\n".join(failures)
    )


def test_required_is_never_dropped():
    """required 는 정규화/변환 어느 단계에서도 유실되면 안 된다."""
    emitted = _load_emitted_helpers()
    schema = {"properties": {"a": {"type": "string"}, "f": {"type": "boolean"}},
              "required": ["a", "f"]}
    for name, normalize, convert in (
        ("ssot", ssot.normalize_input_schema, ssot.convert_boolean_schema_to_enabled_disabled),
        ("template", emitted["_normalize_input_schema"],
         emitted["_convert_boolean_schema_to_enabled_disabled"]),
    ):
        result = convert(normalize(copy.deepcopy(schema)))
        assert result.get("required") == ["a", "f"], f"{name}: required 유실 -> {result!r}"


def test_input_schema_shape_is_guaranteed():
    """정규화 결과는 항상 {"type": "object", "properties": {...}} 를 만족해야 한다."""
    emitted = _load_emitted_helpers()
    for name, normalize in (
        ("ssot", ssot.normalize_input_schema),
        ("template", emitted["_normalize_input_schema"]),
    ):
        for case in SCHEMA_CASES:
            result = normalize(copy.deepcopy(case))
            assert result.get("type") == "object", f"{name}: type != object for {case!r}"
            assert isinstance(result.get("properties"), dict), \
                f"{name}: properties is not a dict for {case!r}"


# ----------------------------------------------------------------------------
# 직접 실행 (pytest 없이)
# ----------------------------------------------------------------------------

def main() -> int:
    print("=" * 72)
    print("sync guard: _schema_helpers.jinja2 <-> schema_normalize.py")
    print("=" * 72)
    print(f"template : {TEMPLATE_PATH}")
    print(f"ssot     : {Path(ssot.__file__)}")
    try:
        import jinja2  # noqa: F401
        print("renderer : jinja2")
    except ImportError:
        print("renderer : raw (jinja2 not installed; Jinja comments stripped)")
    print()

    checks = [
        ("implementations match", test_schema_helpers_match_schema_normalize),
        ("required never dropped", test_required_is_never_dropped),
        ("input schema shape guaranteed", test_input_schema_shape_is_guaranteed),
    ]

    failed = 0
    for label, fn in checks:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f"[FAIL] {label}")
            print(str(exc))
            print()
        except Exception as exc:
            failed += 1
            print(f"[ERROR] {label}: {type(exc).__name__}: {exc}")
            print()
        else:
            print(f"[OK]   {label}")

    total_cases = len(SCHEMA_CASES) * 4 + len(SCALAR_CASES) * 2 + len(COERCE_CASES) + 4
    print()
    print("-" * 72)
    if failed:
        print(f"FAILED - {failed} of {len(checks)} checks failed")
        print("두 구현이 갈라졌다. 규칙의 SSOT 는 schema_normalize.py 이므로,")
        print("거기에 맞춰 _schema_helpers.jinja2 를 고쳐라.")
        return 1
    print(f"PASSED - {len(checks)} checks, {total_cases} comparisons")
    return 0


if __name__ == "__main__":
    sys.exit(main())
