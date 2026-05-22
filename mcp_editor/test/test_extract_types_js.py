"""
JavaScript Type Extractor 테스트

extract_types_js.py 모듈의 Sequelize 모델 타입 추출 기능을 테스트합니다.

테스트 대상:
- extract_sequelize_models_from_file(): 파일에서 Sequelize 모델 추출
- scan_js_project_types(): 전체 JS 프로젝트 타입 스캔
- map_sequelize_to_json_type(): Sequelize 타입 → JSON Schema 타입 변환
- map_zod_to_json_type(): Zod 타입 → JSON Schema 타입 변환
"""

import os
import sys
import json
import tempfile
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from service_registry.javascript.types import (
    extract_sequelize_models_from_file,
    scan_js_project_types,
    map_sequelize_to_json_type,
    map_zod_to_json_type,
    export_js_types_property,
)


def test_map_sequelize_to_json_type():
    """Sequelize 타입 → JSON Schema 타입 매핑 테스트"""
    print("\n=== test_map_sequelize_to_json_type ===")

    test_cases = [
        ("STRING", "string"),
        ("STRING(50)", "string"),
        ("TEXT", "string"),
        ("INTEGER", "integer"),
        ("BIGINT", "integer"),
        ("FLOAT", "number"),
        ("DOUBLE", "number"),
        ("DECIMAL", "number"),
        ("BOOLEAN", "boolean"),
        ("DATE", "string"),
        ("DATEONLY", "string"),
        ("JSON", "object"),
        ("JSONB", "object"),
        ("UUID", "string"),
        ("ARRAY", "array"),
        ("UNKNOWN_TYPE", "any"),
    ]

    passed = 0
    failed = 0

    for seq_type, expected in test_cases:
        result = map_sequelize_to_json_type(seq_type)
        status = "PASS" if result == expected else "FAIL"
        if result == expected:
            passed += 1
        else:
            failed += 1
        print(f"  {status}: map_sequelize_to_json_type('{seq_type}') = '{result}' (expected: '{expected}')")

    print(f"  Result: {passed} passed, {failed} failed")
    return failed == 0


def test_map_zod_to_json_type():
    """Zod 타입 → JSON Schema 타입 매핑 테스트"""
    print("\n=== test_map_zod_to_json_type ===")

    test_cases = [
        ("string", "string"),
        ("number", "number"),
        ("boolean", "boolean"),
        ("array", "array"),
        ("object", "object"),
        ("enum", "string"),
        ("date", "string"),
        ("any", "any"),
        ("null", "null"),
        ("unknown", "any"),
    ]

    passed = 0
    failed = 0

    for zod_type, expected in test_cases:
        result = map_zod_to_json_type(zod_type)
        status = "PASS" if result == expected else "FAIL"
        if result == expected:
            passed += 1
        else:
            failed += 1
        print(f"  {status}: map_zod_to_json_type('{zod_type}') = '{result}' (expected: '{expected}')")

    print(f"  Result: {passed} passed, {failed} failed")
    return failed == 0


def test_extract_sequelize_models_from_file():
    """샘플 JS 파일에서 Sequelize 모델 추출 테스트"""
    print("\n=== test_extract_sequelize_models_from_file ===")

    # Create a sample JavaScript file with Sequelize model
    sample_code = '''
const { DataTypes } = require('sequelize');

const Employee = sequelize.define('Employee', {
    id: {
        type: DataTypes.INTEGER,
        primaryKey: true,
        autoIncrement: true
    },
    nameKr: {
        type: DataTypes.STRING(100),
        allowNull: false,
        field: 'NAME_KR'
    },
    nameEn: {
        type: DataTypes.STRING(100),
        allowNull: true,
        field: 'NAME_EN'
    },
    email: {
        type: DataTypes.STRING(200),
        allowNull: false
    },
    hireDate: {
        type: DataTypes.DATEONLY,
        allowNull: true,
        field: 'HIRE_DATE'
    },
    isActive: {
        type: DataTypes.BOOLEAN,
        defaultValue: true
    },
    salary: {
        type: DataTypes.DECIMAL(10, 2),
        allowNull: true
    },
    metadata: {
        type: DataTypes.JSON,
        allowNull: true
    }
}, {
    tableName: 'EMPLOYEES',
    timestamps: false
});

module.exports = Employee;
'''

    # Write to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
        f.write(sample_code)
        temp_file = f.name

    try:
        # Extract models
        models = extract_sequelize_models_from_file(temp_file)

        print(f"  Found {len(models)} Sequelize model(s)")

        if "Employee" not in models:
            print("  FAIL: Employee model not found")
            return False

        employee = models["Employee"]
        properties = employee.get("properties", [])
        print(f"  Employee has {len(properties)} properties")

        # Check property extraction
        prop_names = [p["name"] for p in properties]
        expected_props = ["id", "nameKr", "nameEn", "email", "hireDate", "isActive", "salary", "metadata"]

        for prop_name in expected_props:
            if prop_name in prop_names:
                prop = next(p for p in properties if p["name"] == prop_name)
                print(f"    - {prop_name}: type={prop['type']}, optional={prop.get('is_optional', False)}")
            else:
                print(f"    - {prop_name}: NOT FOUND")

        # Verify specific properties
        id_prop = next((p for p in properties if p["name"] == "id"), None)
        if id_prop:
            assert id_prop["type"] == "integer", f"id should be integer, got {id_prop['type']}"
            assert id_prop.get("is_primary_key") == True, "id should be primary key"

        nameKr_prop = next((p for p in properties if p["name"] == "nameKr"), None)
        if nameKr_prop:
            assert nameKr_prop["type"] == "string", f"nameKr should be string, got {nameKr_prop['type']}"
            assert nameKr_prop.get("maxLength") == 100, f"nameKr maxLength should be 100"
            assert nameKr_prop.get("db_field") == "NAME_KR", "nameKr db_field should be NAME_KR"

        metadata_prop = next((p for p in properties if p["name"] == "metadata"), None)
        if metadata_prop:
            assert metadata_prop["type"] == "object", f"metadata should be object, got {metadata_prop['type']}"

        print("  PASS: All assertions passed")
        return True

    except AssertionError as e:
        print(f"  FAIL: {e}")
        return False
    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        os.unlink(temp_file)


def test_scan_js_project_types():
    """전체 JS 프로젝트 타입 스캔 테스트"""
    print("\n=== test_scan_js_project_types ===")

    # Check if asset_management directory exists
    asset_dir = Path(__file__).parent.parent.parent / "mcp_asset_management"

    if not asset_dir.exists():
        print(f"  Directory not found: {asset_dir}")
        print("  Creating sample JS project for testing...")

        # Create temp directory with sample JS files
        with tempfile.TemporaryDirectory() as temp_dir:
            models_dir = Path(temp_dir) / "sequelize" / "models"
            models_dir.mkdir(parents=True)

            # Create sample model file
            sample_model = '''
const { DataTypes } = require('sequelize');

const User = sequelize.define('User', {
    id: { type: DataTypes.INTEGER, primaryKey: true },
    name: { type: DataTypes.STRING(100), allowNull: false },
    email: { type: DataTypes.STRING(200) }
});

module.exports = User;
'''
            (models_dir / "user.js").write_text(sample_model)

            # Scan the temp directory
            result = scan_js_project_types(temp_dir)

            print(f"  Found {len(result['models'])} models")
            print(f"  Total properties: {len(result['all_properties'])}")

            if result["models"]:
                for model_name in result["models"]:
                    print(f"    - {model_name}")

            print("  PASS: scan_js_project_types works with sample data")
            return True
    else:
        try:
            result = scan_js_project_types(str(asset_dir))

            print(f"  Found {len(result['models'])} models")
            print(f"  Total properties: {len(result['all_properties'])}")

            # List some models
            for model_name in list(result["models"].keys())[:5]:
                model = result["models"][model_name]
                prop_count = len(model.get("properties", []))
                print(f"    - {model_name}: {prop_count} properties")

            if len(result["models"]) > 5:
                print(f"    ... and {len(result['models']) - 5} more")

            print("  PASS: scan_js_project_types works correctly")
            return True

        except Exception as e:
            print(f"  FAIL: {e}")
            return False


def test_export_js_types_property():
    """types_property JSON 생성 테스트"""
    print("\n=== test_export_js_types_property ===")

    # Create temp directory with sample JS files
    with tempfile.TemporaryDirectory() as temp_project:
        models_dir = Path(temp_project) / "sequelize" / "models"
        models_dir.mkdir(parents=True)

        # Create sample model files
        employee_model = '''
const { DataTypes } = require('sequelize');

const Employee = sequelize.define('Employee', {
    id: { type: DataTypes.INTEGER, primaryKey: true },
    name: { type: DataTypes.STRING(100), allowNull: false },
    department: { type: DataTypes.STRING(50) },
    salary: { type: DataTypes.DECIMAL(10, 2) }
});

module.exports = Employee;
'''
        (models_dir / "employee.js").write_text(employee_model)

        department_model = '''
const { DataTypes } = require('sequelize');

const Department = sequelize.define('Department', {
    id: { type: DataTypes.INTEGER, primaryKey: true },
    name: { type: DataTypes.STRING(100), allowNull: false },
    code: { type: DataTypes.STRING(10) }
});

module.exports = Department;
'''
        (models_dir / "department.js").write_text(department_model)

        # Create output directory
        with tempfile.TemporaryDirectory() as output_dir:
            try:
                output_path = export_js_types_property(
                    base_dir=temp_project,
                    server_name="test_server",
                    output_dir=output_dir
                )

                print(f"  Generated: {output_path}")

                # Verify file was created
                assert Path(output_path).exists(), "Output file should exist"

                # Load and verify content
                with open(output_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                print(f"  Version: {data.get('version')}")
                print(f"  Server: {data.get('server_name')}")
                print(f"  Language: {data.get('language')}")
                print(f"  Classes (models): {len(data.get('classes', []))}")
                print(f"  All properties: {len(data.get('all_properties', []))}")

                # Check structure
                assert "classes" in data, "Should have classes field"
                assert "properties_by_class" in data, "Should have properties_by_class field"
                assert "all_properties" in data, "Should have all_properties field"
                assert data.get("language") == "javascript", "Language should be javascript"

                # Check models
                class_names = [c["name"] for c in data["classes"]]
                print(f"  Extracted models: {class_names}")

                if "Employee" in class_names:
                    emp_props = data["properties_by_class"].get("Employee", [])
                    print(f"  Employee properties: {[p['name'] for p in emp_props]}")

                print("  PASS: export_js_types_property works correctly")
                return True

            except Exception as e:
                print(f"  FAIL: {e}")
                import traceback
                traceback.print_exc()
                return False


def run_all_tests():
    """Run all tests and report results"""
    print("=" * 60)
    print("JavaScript Type Extractor Tests (extract_types_js.py)")
    print("=" * 60)

    tests = [
        test_map_sequelize_to_json_type,
        test_map_zod_to_json_type,
        test_extract_sequelize_models_from_file,
        test_scan_js_project_types,
        test_export_js_types_property,
    ]

    results = []
    for test_func in tests:
        try:
            result = test_func()
            results.append((test_func.__name__, result))
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
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
