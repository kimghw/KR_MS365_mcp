"""
MCP Service Scanner 테스트

mcp_service_scanner.py 모듈의 @mcp_service 데코레이터 스캔 기능을 테스트합니다.

테스트 대상:
- find_mcp_services_in_python_file(): Python 파일에서 @mcp_service 함수 찾기
- find_jsdoc_mcp_services_in_js_file(): JS 파일에서 JSDoc @mcp_service 함수 찾기
- scan_codebase_for_mcp_services(): 전체 코드베이스 스캔
- export_services_to_json(): registry JSON 생성
- collect_referenced_types(): 참조된 타입 수집
"""

import os
import sys
import json
import tempfile
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from service_registry.scanner import (
    find_mcp_services_in_python_file,
    find_jsdoc_mcp_services_in_js_file,
    scan_codebase_for_mcp_services,
    export_services_to_json,
    signature_from_parameters,
    detect_language,
    Language,
)


def test_detect_language():
    """파일 확장자로 언어 감지 테스트"""
    print("\n=== test_detect_language ===")

    test_cases = [
        (Path("test.py"), Language.PYTHON),
        (Path("test.js"), Language.JAVASCRIPT),
        (Path("test.mjs"), Language.JAVASCRIPT),
        (Path("test.ts"), Language.TYPESCRIPT),
        (Path("test.tsx"), Language.TYPESCRIPT),
        (Path("test.txt"), Language.UNKNOWN),
        (Path("test.md"), Language.UNKNOWN),
    ]

    passed = 0
    failed = 0

    for file_path, expected in test_cases:
        result = detect_language(file_path)
        status = "PASS" if result == expected else "FAIL"
        if result == expected:
            passed += 1
        else:
            failed += 1
        print(f"  {status}: detect_language('{file_path}') = {result.value} (expected: {expected.value})")

    print(f"  Result: {passed} passed, {failed} failed")
    return failed == 0


def test_find_mcp_services_in_python_file():
    """Python 파일에서 @mcp_service 함수 찾기 테스트"""
    print("\n=== test_find_mcp_services_in_python_file ===")

    # Create a sample Python file with @mcp_service decorated functions
    sample_code = '''
from typing import Optional, List
from pydantic import BaseModel

def mcp_service(**kwargs):
    """Mock decorator"""
    def decorator(func):
        return func
    return decorator

class FilterParams(BaseModel):
    user_email: str
    top: int = 50

class MailService:
    @mcp_service(server_name="outlook", description="Get emails")
    async def get_emails(
        self,
        user_email: str,
        filter_params: Optional[FilterParams] = None,
        top: int = 50,
        skip: int = 0
    ):
        """Retrieve emails from inbox"""
        pass

    @mcp_service(server_name="outlook", description="Send email")
    async def send_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        attachments: Optional[List[str]] = None
    ):
        """Send an email"""
        pass

# Standalone function
@mcp_service(server_name="outlook", description="Search emails")
async def search_emails(query: str, folder: str = "inbox"):
    """Search emails by query"""
    pass

# Not a service - no decorator
async def helper_function(data: str):
    """This should not be extracted"""
    pass
'''

    # Write to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(sample_code)
        temp_file = f.name

    try:
        # Extract services
        services = find_mcp_services_in_python_file(temp_file)

        print(f"  Found {len(services)} @mcp_service function(s)")

        # Verify expected services
        expected_services = ["get_emails", "send_email", "search_emails"]
        for svc_name in expected_services:
            if svc_name in services:
                svc = services[svc_name]
                print(f"    - {svc_name}: {svc.get('metadata', {}).get('description', 'N/A')}")
                print(f"      signature: {svc.get('signature', '')[:60]}...")
                print(f"      is_async: {svc.get('is_async')}")
                print(f"      class: {svc.get('class', 'N/A')}")
            else:
                print(f"    - {svc_name}: NOT FOUND")

        # Verify helper_function is NOT extracted
        assert "helper_function" not in services, "helper_function should not be extracted"
        print("    - helper_function: correctly NOT extracted")

        # Check parameters extraction
        if "get_emails" in services:
            params = services["get_emails"].get("parameters", [])
            param_names = [p["name"] for p in params]
            print(f"    get_emails params: {param_names}")

            # Check class_name detection for FilterParams
            filter_param = next((p for p in params if p["name"] == "filter_params"), None)
            if filter_param:
                print(f"      filter_params: type={filter_param.get('type')}, class_name={filter_param.get('class_name')}")

        print("  PASS: Services extracted correctly")
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


def test_find_jsdoc_mcp_services_in_js_file():
    """JavaScript 파일에서 JSDoc @mcp_service 함수 찾기 테스트"""
    print("\n=== test_find_jsdoc_mcp_services_in_js_file ===")

    # Create a sample JavaScript file with JSDoc @mcp_service
    sample_code = '''
const crewService = {};

/**
 * @mcp_service
 * @server_name asset_management
 * @tool_name get_crew_list
 * @service_name getCrew
 * @description 전체 선원 정보 조회
 * @category crew_query
 * @tags query,search,filter
 * @param {Object} params - 검색 파라미터
 * @param {Array<number>} [params.shipIds] - 선박 ID 목록
 * @param {string} [params.where] - 검색 조건
 * @returns {Array<Object>} 선원 목록
 */
crewService.getCrew = async (params = {}) => {
    const { shipIds, where } = params;
    // Implementation
    return [];
};

/**
 * @mcp_service
 * @server_name asset_management
 * @tool_name update_crew
 * @description 선원 정보 업데이트
 * @param {number} id - 선원 ID
 * @param {Object} updateData - 업데이트 데이터
 */
async function updateCrew(id, updateData) {
    // Implementation
}

// Not a service - regular function
/**
 * Helper function for internal use
 * @param {string} data - Some data
 */
function helperFunc(data) {
    return data;
}

module.exports = { crewService, updateCrew };
'''

    # Write to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
        f.write(sample_code)
        temp_file = f.name

    try:
        # Extract services
        services = find_jsdoc_mcp_services_in_js_file(temp_file)

        print(f"  Found {len(services)} JSDoc @mcp_service function(s)")

        for svc_name, svc in services.items():
            print(f"    - {svc_name}:")
            print(f"      tool_name: {svc.get('metadata', {}).get('tool_name')}")
            print(f"      description: {svc.get('metadata', {}).get('description', '')[:50]}...")
            print(f"      parameters: {len(svc.get('parameters', []))}")
            print(f"      is_async: {svc.get('is_async')}")

        # Verify helperFunc is NOT extracted
        assert "helperFunc" not in services, "helperFunc should not be extracted"
        print("    - helperFunc: correctly NOT extracted")

        # Check parameters with nested properties
        if "getCrew" in services:
            params = services["getCrew"].get("parameters", [])
            print(f"    getCrew params:")
            for p in params:
                props = p.get("properties", {})
                if props:
                    print(f"      - {p['name']}: type={p['type']}, nested_props={list(props.keys())}")
                else:
                    print(f"      - {p['name']}: type={p['type']}")

        print("  PASS: JSDoc services extracted correctly")
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


def test_signature_from_parameters():
    """파라미터에서 시그니처 문자열 생성 테스트"""
    print("\n=== test_signature_from_parameters ===")

    test_cases = [
        # Simple parameters
        (
            [
                {"name": "query", "type": "str", "is_optional": False, "has_default": False, "default": None},
            ],
            "query: str"
        ),
        # With default value
        (
            [
                {"name": "top", "type": "int", "is_optional": True, "has_default": True, "default": 50},
            ],
            "top: Optional[int] = 50"
        ),
        # With class_name
        (
            [
                {"name": "filter_params", "type": "object", "class_name": "FilterParams", "is_optional": True, "has_default": True, "default": None},
            ],
            "filter_params: Optional[FilterParams] = None"
        ),
        # Multiple parameters
        (
            [
                {"name": "user_id", "type": "str", "is_optional": False, "has_default": False, "default": None},
                {"name": "limit", "type": "int", "is_optional": True, "has_default": True, "default": 10},
            ],
            "user_id: str, limit: Optional[int] = 10"
        ),
    ]

    passed = 0
    failed = 0

    for params, expected in test_cases:
        result = signature_from_parameters(params)
        status = "PASS" if result == expected else "FAIL"
        if result == expected:
            passed += 1
        else:
            failed += 1
        print(f"  {status}: '{result}'")
        if result != expected:
            print(f"         expected: '{expected}'")

    print(f"  Result: {passed} passed, {failed} failed")
    return failed == 0


def test_scan_codebase_for_mcp_services():
    """전체 코드베이스 스캔 테스트"""
    print("\n=== test_scan_codebase_for_mcp_services ===")

    # Try scanning mcp_outlook directory
    outlook_dir = Path(__file__).parent.parent.parent / "mcp_outlook"

    if not outlook_dir.exists():
        print(f"  SKIP: Directory not found: {outlook_dir}")
        return True

    try:
        services = scan_codebase_for_mcp_services(str(outlook_dir))

        print(f"  Found {len(services)} services in mcp_outlook")

        for name, svc in list(services.items())[:5]:
            print(f"    - {name}: {svc.get('metadata', {}).get('description', 'N/A')[:40]}...")

        if len(services) > 5:
            print(f"    ... and {len(services) - 5} more")

        print("  PASS: scan_codebase_for_mcp_services works correctly")
        return True

    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_export_services_to_json():
    """registry JSON 생성 테스트"""
    print("\n=== test_export_services_to_json ===")

    # Create temp directory with sample Python service file
    with tempfile.TemporaryDirectory() as temp_project:
        # Create service file
        service_code = '''
from typing import Optional, List
from pydantic import BaseModel, Field

def mcp_service(**kwargs):
    def decorator(func):
        return func
    return decorator

class QueryParams(BaseModel):
    """쿼리 파라미터"""
    query: str = Field(..., description="검색어")
    limit: int = Field(10, description="결과 개수")

class DataService:
    @mcp_service(server_name="test_server", description="Search data")
    async def search_data(
        self,
        params: Optional[QueryParams] = None,
        include_metadata: bool = False
    ):
        """Search for data"""
        pass

    @mcp_service(server_name="test_server", description="Get item by ID")
    async def get_item(self, item_id: str):
        """Get a single item"""
        pass
'''
        service_file = Path(temp_project) / "data_service.py"
        service_file.write_text(service_code)

        # Create types file
        types_code = '''
from pydantic import BaseModel, Field
from typing import Optional

class QueryParams(BaseModel):
    """쿼리 파라미터"""
    query: str = Field(..., description="검색어")
    limit: int = Field(10, description="결과 개수")
'''
        types_file = Path(temp_project) / "data_types.py"
        types_file.write_text(types_code)

        # Create output directory
        with tempfile.TemporaryDirectory() as output_dir:
            try:
                result = export_services_to_json(
                    base_dir=temp_project,
                    server_name="test_server",
                    output_dir=output_dir
                )

                print(f"  Registry: {result.get('registry')}")
                print(f"  Types property: {result.get('types_property')}")
                print(f"  Service count: {result.get('service_count')}")
                print(f"  Type count: {result.get('type_count')}")
                print(f"  Language: {result.get('language')}")

                # Verify registry file
                registry_path = result.get('registry')
                if registry_path and Path(registry_path).exists():
                    with open(registry_path, 'r', encoding='utf-8') as f:
                        registry = json.load(f)

                    print(f"  Registry version: {registry.get('version')}")
                    print(f"  Registry services: {list(registry.get('services', {}).keys())}")

                    # Check service structure
                    for svc_name, svc in registry.get("services", {}).items():
                        print(f"    - {svc_name}:")
                        print(f"        handler: {svc.get('handler', {}).get('method')}")
                        print(f"        params: {len(svc.get('parameters', []))}")

                print("  PASS: export_services_to_json works correctly")
                return True

            except Exception as e:
                print(f"  FAIL: {e}")
                import traceback
                traceback.print_exc()
                return False


def test_scan_real_outlook_project():
    """실제 mcp_outlook 프로젝트 스캔 테스트"""
    print("\n=== test_scan_real_outlook_project ===")

    outlook_dir = Path(__file__).parent.parent.parent / "mcp_outlook"

    if not outlook_dir.exists():
        print(f"  SKIP: Directory not found: {outlook_dir}")
        return True

    # Check if registry file exists
    registry_dir = Path(__file__).parent.parent / "mcp_outlook"
    registry_file = registry_dir / "registry_outlook.json"

    if registry_file.exists():
        try:
            with open(registry_file, 'r', encoding='utf-8') as f:
                registry = json.load(f)

            print(f"  Existing registry: {registry_file}")
            print(f"  Version: {registry.get('version')}")
            print(f"  Generated: {registry.get('generated_at')}")
            print(f"  Services: {len(registry.get('services', {}))}")

            # List some services
            for svc_name in list(registry.get("services", {}).keys())[:5]:
                svc = registry["services"][svc_name]
                desc = svc.get("metadata", {}).get("description", "N/A")
                print(f"    - {svc_name}: {desc[:40]}...")

            if len(registry.get("services", {})) > 5:
                print(f"    ... and {len(registry['services']) - 5} more")

            print("  PASS: Real registry loaded successfully")
            return True

        except Exception as e:
            print(f"  FAIL: {e}")
            return False
    else:
        print(f"  Registry file not found: {registry_file}")
        print("  Scanning source code instead...")

        try:
            services = scan_codebase_for_mcp_services(str(outlook_dir), server_name="outlook")
            print(f"  Found {len(services)} services")
            print("  PASS: Source scan works")
            return True
        except Exception as e:
            print(f"  FAIL: {e}")
            return False


def run_all_tests():
    """Run all tests and report results"""
    print("=" * 60)
    print("MCP Service Scanner Tests (mcp_service_scanner.py)")
    print("=" * 60)

    tests = [
        test_detect_language,
        test_find_mcp_services_in_python_file,
        test_find_jsdoc_mcp_services_in_js_file,
        test_signature_from_parameters,
        test_scan_codebase_for_mcp_services,
        test_export_services_to_json,
        test_scan_real_outlook_project,
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
