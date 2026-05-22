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

    passed = 0
    failed = 0

    for python_type, expected in test_cases:
        result = map_python_to_json_type(python_type)
        status = "PASS" if result == expected else "FAIL"
        if result == expected:
            passed += 1
        else:
            failed += 1
        print(f"  {status}: map_python_to_json_type('{python_type}') = '{result}' (expected: '{expected}')")

    print(f"  Result: {passed} passed, {failed} failed")
    return failed == 0


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
        return True

    except AssertionError as e:
        print(f"  FAIL: {e}")
        return False
    finally:
        os.unlink(temp_file)


def test_extract_from_real_file():
    """실제 outlook_types.py 파일에서 추출 테스트"""
    print("\n=== test_extract_from_real_file ===")

    # Path to real types file
    types_file = Path(__file__).parent.parent.parent / "mcp_outlook" / "outlook_types.py"

    if not types_file.exists():
        print(f"  SKIP: File not found: {types_file}")
        return True

    try:
        classes = extract_class_properties(str(types_file))
        print(f"  Found {len(classes)} BaseModel class(es) in outlook_types.py")

        # List extracted classes
        for class_name, class_info in list(classes.items())[:5]:
            prop_count = len(class_info.get("properties", []))
            print(f"    - {class_name}: {prop_count} properties")

        if len(classes) > 5:
            print(f"    ... and {len(classes) - 5} more classes")

        # Verify FilterParams exists (known class in outlook_types.py)
        if "FilterParams" in classes:
            filter_params = classes["FilterParams"]
            print(f"  FilterParams has {len(filter_params['properties'])} properties")

            # Check some known properties
            prop_names = [p["name"] for p in filter_params["properties"]]
            if "from_address" in prop_names:
                print("    - from_address: found")
            if "is_read" in prop_names:
                print("    - is_read: found")

        print("  PASS: Successfully extracted from outlook_types.py")
        return True

    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_extract_single_class():
    """특정 클래스만 추출 테스트"""
    print("\n=== test_extract_single_class ===")

    # Path to real types file
    types_file = Path(__file__).parent.parent.parent / "mcp_outlook" / "outlook_types.py"

    if not types_file.exists():
        print(f"  SKIP: File not found: {types_file}")
        return True

    try:
        # Extract only FilterParams
        class_info = extract_single_class(str(types_file), "FilterParams")

        if class_info is None:
            print("  FAIL: FilterParams not found")
            return False

        print(f"  FilterParams found at line {class_info.get('line', '?')}")
        print(f"  Properties: {len(class_info.get('properties', []))}")

        # Try non-existent class
        non_existent = extract_single_class(str(types_file), "NonExistentClass")
        assert non_existent is None, "NonExistentClass should return None"
        print("  NonExistentClass returns None as expected")

        print("  PASS: extract_single_class works correctly")
        return True

    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_scan_py_project_types():
    """전체 프로젝트 타입 스캔 테스트"""
    print("\n=== test_scan_py_project_types ===")

    # Scan mcp_outlook directory
    outlook_dir = Path(__file__).parent.parent.parent / "mcp_outlook"

    if not outlook_dir.exists():
        print(f"  SKIP: Directory not found: {outlook_dir}")
        return True

    try:
        result = scan_py_project_types(str(outlook_dir))

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
            print(f"  Sample property: {sample.get('name')} (source: {sample.get('source')})")

        print("  PASS: scan_py_project_types works correctly")
        return True

    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_export_py_types_property():
    """types_property JSON 생성 테스트"""
    print("\n=== test_export_py_types_property ===")

    # Scan mcp_outlook directory
    outlook_dir = Path(__file__).parent.parent.parent / "mcp_outlook"

    if not outlook_dir.exists():
        print(f"  SKIP: Directory not found: {outlook_dir}")
        return True

    # Create temp output directory
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
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
            return True

        except Exception as e:
            print(f"  FAIL: {e}")
            import traceback
            traceback.print_exc()
            return False


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

    results = []
    for test_func in tests:
        try:
            result = test_func()
            results.append((test_func.__name__, result))
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append((test_func.__name__, False))

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    failed = len(results) - passed

    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  [{status}] {name}")

    print(f"\nTotal: {passed} passed, {failed} failed")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
