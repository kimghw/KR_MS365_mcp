"""
Python Type Extractor 테스트

extract_types.py 모듈의 Pydantic BaseModel 타입 추출 기능을 테스트합니다.

테스트 대상:
- extract_class_properties(): 파일에서 모든 BaseModel 클래스 추출
- extract_single_class(): 특정 클래스만 추출
- scan_py_project_types(): 전체 프로젝트 타입 스캔
- map_python_to_json_type(): Python 타입 → JSON Schema 타입 변환
"""

import os
import sys
import json
import tempfile
from pathlib import Path

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from service_registry.python.types import (
    extract_class_properties,
    extract_single_class,
    scan_py_project_types,
    map_python_to_json_type,
    extract_type_from_annotation,
    export_py_types_property,
)


def test_map_python_to_json_type():
    """Python 타입 → JSON Schema 타입 매핑 테스트"""
    print("\n=== test_map_python_to_json_type ===")

    test_cases = [
        ("str", "string"),
        ("int", "integer"),
        ("float", "number"),
        ("bool", "boolean"),
        ("list", "array"),
        ("dict", "object"),
        ("List", "array"),
        ("Dict", "object"),
        ("Any", "any"),
        ("None", "null"),
        ("Optional", "any"),
        ("CustomClass", "object"),  # Unknown types -> object
    ]

    failures = []

    for python_type, expected in test_cases:
        result = map_python_to_json_type(python_type)
        if result != expected:
            failures.append(f"map_python_to_json_type('{python_type}') = '{result}' (expected: '{expected}')")

    assert not failures, "타입 매핑 불일치:\n  " + "\n  ".join(failures)


def test_extract_class_properties_with_sample():
    """샘플 Python 파일에서 BaseModel 클래스 추출 테스트"""
    print("\n=== test_extract_class_properties_with_sample ===")

    # Create a temporary Python file with Pydantic models
    sample_code = '''
from pydantic import BaseModel, Field
from typing import Optional, List

class UserProfile(BaseModel):
    """사용자 프로필 정보"""
    user_id: str = Field(..., description="사용자 ID")
    email: Optional[str] = Field(None, description="이메일 주소", examples=["user@example.com"])
    age: int = Field(0, description="나이")
    is_active: bool = Field(True, description="활성화 상태")
    tags: List[str] = Field(default=[], description="태그 목록")

class NotABaseModel:
    """일반 클래스 - 추출 대상 아님"""
    name: str = "test"
'''

    # Write to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(sample_code)
        temp_file = f.name

    try:
        # Extract classes
        classes = extract_class_properties(temp_file)

        print(f"  Found {len(classes)} BaseModel class(es)")

        # Verify UserProfile was extracted
        assert "UserProfile" in classes, "UserProfile should be extracted"
        assert "NotABaseModel" not in classes, "NotABaseModel should not be extracted"

        user_profile = classes["UserProfile"]
        print(f"  UserProfile has {len(user_profile['properties'])} properties")

        # Check properties
        prop_names = [p["name"] for p in user_profile["properties"]]
        expected_props = ["user_id", "email", "age", "is_active", "tags"]

        for prop in expected_props:
            assert prop in prop_names, f"Property '{prop}' should be extracted"
            print(f"    - {prop}: found")

        # Check property details
        for prop in user_profile["properties"]:
            if prop["name"] == "email":
                assert prop["type"] == "string", f"email type should be string, got {prop['type']}"
                assert "이메일" in prop["description"], "email should have description"
                print(f"    - email type: {prop['type']}, description: {prop['description'][:30]}...")
            elif prop["name"] == "tags":
                assert "List" in prop["type"], f"tags type should be List, got {prop['type']}"
                print(f"    - tags type: {prop['type']}")

        print("  PASS: All assertions passed")
    finally:
        os.unlink(temp_file)


def test_extract_from_real_file():
    """실제 outlook_types.py 파일에서 추출 테스트"""
    print("\n=== test_extract_from_real_file ===")

    # Path to real types file
    types_file = Path(__file__).parent.parent.parent / "mcp_outlook" / "outlook_types.py"

    if not types_file.exists():
        pytest.skip(f"File not found: {types_file}")

    classes = extract_class_properties(str(types_file))
    print(f"  Found {len(classes)} BaseModel class(es) in outlook_types.py")

    assert isinstance(classes, dict), f"결과는 dict 여야 한다, got {type(classes)}"
    assert classes, "outlook_types.py 에서 BaseModel 클래스를 하나도 추출하지 못했다"

    # List extracted classes
    for class_name, class_info in list(classes.items())[:5]:
        prop_count = len(class_info.get("properties", []))
        print(f"    - {class_name}: {prop_count} properties")

    if len(classes) > 5:
        print(f"    ... and {len(classes) - 5} more classes")

    # Verify FilterParams exists (known class in outlook_types.py)
    if "FilterParams" in classes:
        filter_params = classes["FilterParams"]
        assert filter_params["properties"], "FilterParams 의 properties 가 비어 있다"
        print(f"  FilterParams has {len(filter_params['properties'])} properties")

        # Check some known properties
        prop_names = [p["name"] for p in filter_params["properties"]]
        for known in ("from_address", "is_read"):
            if known in prop_names:
                print(f"    - {known}: found")

    print("  PASS: Successfully extracted from outlook_types.py")


def test_extract_single_class():
    """특정 클래스만 추출 테스트"""
    print("\n=== test_extract_single_class ===")

    # Path to real types file
    types_file = Path(__file__).parent.parent.parent / "mcp_outlook" / "outlook_types.py"

    if not types_file.exists():
        pytest.skip(f"File not found: {types_file}")

    # Extract only FilterParams
    class_info = extract_single_class(str(types_file), "FilterParams")

    assert class_info is not None, "FilterParams 를 찾지 못했다"

    print(f"  FilterParams found at line {class_info.get('line', '?')}")
    print(f"  Properties: {len(class_info.get('properties', []))}")

    # Try non-existent class
    non_existent = extract_single_class(str(types_file), "NonExistentClass")
    assert non_existent is None, "NonExistentClass should return None"
    print("  NonExistentClass returns None as expected")

    print("  PASS: extract_single_class works correctly")


def test_scan_py_project_types():
    """전체 프로젝트 타입 스캔 테스트"""
    print("\n=== test_scan_py_project_types ===")

    # Scan mcp_outlook directory
    outlook_dir = Path(__file__).parent.parent.parent / "mcp_outlook"

    if not outlook_dir.exists():
        pytest.skip(f"Directory not found: {outlook_dir}")

    result = scan_py_project_types(str(outlook_dir))

    assert "classes" in result, "결과에 classes 키가 있어야 한다"
    assert "all_properties" in result, "결과에 all_properties 키가 있어야 한다"
    assert result["classes"], "mcp_outlook 에서 클래스를 하나도 스캔하지 못했다"

    print(f"  Found {len(result['classes'])} classes")
    print(f"  Total properties: {len(result['all_properties'])}")

    # List some classes
    for class_name in list(result["classes"].keys())[:5]:
        print(f"    - {class_name}")

    if len(result["classes"]) > 5:
        print(f"    ... and {len(result['classes']) - 5} more")

    # Check all_properties format
    if result["all_properties"]:
        sample = result["all_properties"][0]
        assert "name" in sample, "all_properties 항목에 name 이 있어야 한다"
        print(f"  Sample property: {sample.get('name')} (source: {sample.get('source')})")

    print("  PASS: scan_py_project_types works correctly")


def test_export_py_types_property():
    """types_property JSON 생성 테스트"""
    print("\n=== test_export_py_types_property ===")

    # Scan mcp_outlook directory
    outlook_dir = Path(__file__).parent.parent.parent / "mcp_outlook"

    if not outlook_dir.exists():
        pytest.skip(f"Directory not found: {outlook_dir}")

    # Create temp output directory
    with tempfile.TemporaryDirectory() as temp_dir:
        output_path = export_py_types_property(
            base_dir=str(outlook_dir),
            server_name="outlook_test",
            output_dir=temp_dir
        )

        print(f"  Generated: {output_path}")

        # Verify file was created
        assert Path(output_path).exists(), "Output file should exist"

        # Load and verify content
        with open(output_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        print(f"  Version: {data.get('version')}")
        print(f"  Server: {data.get('server_name')}")
        print(f"  Classes: {len(data.get('classes', []))}")
        print(f"  All properties: {len(data.get('all_properties', []))}")

        # Check structure
        assert "classes" in data, "Should have classes field"
        assert "properties_by_class" in data, "Should have properties_by_class field"
        assert "all_properties" in data, "Should have all_properties field"

        print("  PASS: export_py_types_property works correctly")


def run_all_tests():
    """Run all tests and report results"""
    print("=" * 60)
    print("Python Type Extractor Tests (extract_types.py)")
    print("=" * 60)

    tests = [
        test_map_python_to_json_type,
        test_extract_class_properties_with_sample,
        test_extract_from_real_file,
        test_extract_single_class,
        test_scan_py_project_types,
        test_export_py_types_property,
    ]

    # 각 테스트는 이제 반환값이 아니라 예외(AssertionError)로 실패를 알린다.
    # 예외 없이 끝나면 PASS, pytest.skip.Exception 이면 SKIP 으로 집계한다.
    results = []
    for test_func in tests:
        try:
            test_func()
            results.append((test_func.__name__, "PASS"))
        except pytest.skip.Exception as e:
            print(f"  SKIP: {e}")
            results.append((test_func.__name__, "SKIP"))
        except Exception as e:
            print(f"  FAIL: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_func.__name__, "FAIL"))

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    passed = sum(1 for _, r in results if r == "PASS")
    skipped = sum(1 for _, r in results if r == "SKIP")
    failed = sum(1 for _, r in results if r == "FAIL")

    for name, status in results:
        print(f"  [{status}] {name}")

    print(f"\nTotal: {passed} passed, {failed} failed, {skipped} skipped")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
