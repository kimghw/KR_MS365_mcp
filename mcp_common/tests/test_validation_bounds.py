"""입력 스키마의 수치·길이 상한 검증 (astra 재검토 R02 — 무제한 `top` 차단)."""

import pytest

from mcp_common.errors import ToolValidationError
from mcp_common.validation import validate_arguments

SCHEMA = {
    "type": "object",
    "properties": {
        "top": {"type": "integer", "minimum": 1, "maximum": 1000},
        "ratio": {"type": "number", "maximum": 1.0},
        "ids": {"type": "array", "items": {"type": "string", "maxLength": 512}, "maxItems": 20, "minItems": 1},
        "q": {"type": "string", "maxLength": 8},
        "nested": {"type": "object", "properties": {"n": {"type": "integer", "maximum": 3}}},
    },
}


def _violations(args):
    with pytest.raises(ToolValidationError) as e:
        validate_arguments(SCHEMA, args, tool="t")
    return "\n".join(e.value.payload["violations"])


def test_within_bounds_passes():
    validate_arguments(SCHEMA, {"top": 1000, "ratio": 1.0, "ids": ["a"], "q": "12345678", "nested": {"n": 3}})


def test_huge_top_rejected():
    assert "maximum 1000" in _violations({"top": 1000000000000})


def test_below_minimum_rejected():
    assert "minimum 1" in _violations({"top": 0})


def test_number_maximum():
    assert "maximum 1.0" in _violations({"ratio": 1.5})


def test_array_item_count_bounds():
    assert "maxItems 20" in _violations({"ids": ["x"] * 21})
    assert "minItems 1" in _violations({"ids": []})


def test_string_and_item_length():
    assert "maxLength 8" in _violations({"q": "123456789"})
    assert "ids[0]" in _violations({"ids": ["y" * 513]})


def test_nested_object_bounds():
    assert "nested.n" in _violations({"nested": {"n": 4}})


def test_bool_is_not_a_number_for_bounds():
    # True == 1 이지만 수치 상한 검사 대상이 아니다 (타입 검사가 먼저 거른다)
    assert "expected type integer" in _violations({"top": True})


def test_min_length_enforced():
    schema = {"type": "object", "properties": {"q": {"type": "string", "minLength": 1}}}
    with pytest.raises(ToolValidationError) as e:
        validate_arguments(schema, {"q": ""}, tool="t")
    assert "minLength 1" in "\n".join(e.value.payload["violations"])
