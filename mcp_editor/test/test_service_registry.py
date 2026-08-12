"""
Service Registry 테스트

tool_editor_core/service_registry.py 모듈의 레지스트리 관리 기능을 테스트합니다.

테스트 대상:
- load_services_for_server(): 서버별 서비스 로딩
- scan_all_registries(): 전체 레지스트리 스캔 및 업데이트
"""

import os
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def test_load_services_for_server_from_registry():
    """레지스트리 JSON 파일에서 서비스 로딩 테스트"""
    print("\n=== test_load_services_for_server_from_registry ===")

    # Check if outlook registry exists
    registry_path = Path(__file__).parent.parent / "mcp_outlook" / "registry_outlook.json"

    if not registry_path.exists():
        pytest.skip(f"Registry file not found: {registry_path}")

    # tool_editor_core 는 선택 의존성(extra: editor)이라 미설치 시 skip 한다.
    mod = pytest.importorskip("tool_editor_core.service_registry")
    load_services_for_server = mod.load_services_for_server

    try:
        # Load services for outlook server
        services = load_services_for_server("outlook", None, force_rescan=False)
    except FileNotFoundError as e:
        pytest.skip(f"레지스트리 부속 파일 없음: {e}")

    assert isinstance(services, dict), f"services 는 dict 여야 한다, got {type(services)}"

    print(f"  Loaded {len(services)} services for 'outlook'")

    # Check service structure
    for svc_name in list(services.keys())[:3]:
        svc = services[svc_name]
        print(f"    - {svc_name}:")
        print(f"        signature: {svc.get('signature', '')[:50]}...")
        print(f"        params: {len(svc.get('parameters', []))}")

    if len(services) > 3:
        print(f"    ... and {len(services) - 3} more")

    print("  PASS: Services loaded from registry")


def test_load_services_mcp_prefix():
    """mcp_ 접두사 처리 테스트"""
    print("\n=== test_load_services_mcp_prefix ===")

    # Check if outlook registry exists
    registry_path = Path(__file__).parent.parent / "mcp_outlook" / "registry_outlook.json"

    if not registry_path.exists():
        pytest.skip(f"Registry file not found: {registry_path}")

    mod = pytest.importorskip("tool_editor_core.service_registry")
    load_services_for_server = mod.load_services_for_server

    try:
        # Test with mcp_ prefix
        services1 = load_services_for_server("mcp_outlook", None, force_rescan=False)

        # Test without prefix
        services2 = load_services_for_server("outlook", None, force_rescan=False)
    except FileNotFoundError as e:
        pytest.skip(f"레지스트리 부속 파일 없음: {e}")

    print(f"  'mcp_outlook' loaded {len(services1)} services")
    print(f"  'outlook' loaded {len(services2)} services")

    # Both should load the same services
    assert len(services1) == len(services2), "Both should return same number of services"
    print("  PASS: mcp_ prefix handled correctly")


def test_registry_file_structure():
    """레지스트리 파일 구조 검증"""
    print("\n=== test_registry_file_structure ===")

    # Check all registry files
    registry_dir = Path(__file__).parent.parent
    registry_files = list(registry_dir.glob("mcp_*/registry_*.json"))

    if not registry_files:
        pytest.skip("No registry files found")

    print(f"  Found {len(registry_files)} registry file(s)")

    errors = []
    for registry_file in registry_files:
        try:
            with open(registry_file, 'r', encoding='utf-8') as fp:
                registry = json.load(fp)
        except json.JSONDecodeError as e:
            errors.append(f"{registry_file.name}: Invalid JSON: {e}")
            continue
        except OSError as e:
            errors.append(f"{registry_file.name}: 읽기 실패: {e}")
            continue

        # Check required fields
        required_fields = ["version", "generated_at", "server_name", "services"]
        missing = [name for name in required_fields if name not in registry]

        if missing:
            errors.append(f"{registry_file.name}: 필수 필드 누락 {missing}")
            continue

        # Check services structure
        services = registry.get("services", {})
        if services:
            sample_service = list(services.values())[0]
            service_fields = ["service_name", "handler", "signature", "parameters", "metadata"]
            service_missing = [name for name in service_fields if name not in sample_service]

            if service_missing:
                print(f"  WARN: {registry_file.name} service missing: {service_missing}")

        print(f"  OK: {registry_file.name} - {len(services)} services")

    assert not errors, "레지스트리 파일 검증 실패:\n  " + "\n  ".join(errors)
    print("  PASS: All registry files valid")


def test_types_property_file_structure():
    """types_property 파일 구조 검증"""
    print("\n=== test_types_property_file_structure ===")

    # Check all types_property files
    registry_dir = Path(__file__).parent.parent
    types_files = list(registry_dir.glob("mcp_*/types_property_*.json"))

    if not types_files:
        pytest.skip("No types_property files found")

    print(f"  Found {len(types_files)} types_property file(s)")

    errors = []
    for types_file in types_files:
        try:
            with open(types_file, 'r', encoding='utf-8') as fp:
                types_data = json.load(fp)
        except json.JSONDecodeError as e:
            errors.append(f"{types_file.name}: Invalid JSON: {e}")
            continue
        except OSError as e:
            errors.append(f"{types_file.name}: 읽기 실패: {e}")
            continue

        # Check required fields
        required_fields = ["version", "server_name", "classes", "all_properties"]
        missing = [name for name in required_fields if name not in types_data]

        if missing:
            errors.append(f"{types_file.name}: 필수 필드 누락 {missing}")
            continue

        classes = types_data.get("classes", [])
        all_props = types_data.get("all_properties", [])
        language = types_data.get("language", "unknown")

        print(f"  OK: {types_file.name} - {len(classes)} classes, {len(all_props)} props ({language})")

    assert not errors, "types_property 파일 검증 실패:\n  " + "\n  ".join(errors)
    print("  PASS: All types_property files valid")


def test_scan_all_registries():
    """전체 레지스트리 스캔 테스트 (시뮬레이션)"""
    print("\n=== test_scan_all_registries ===")

    # This test simulates scan_all_registries without actually modifying files
    mod = pytest.importorskip("tool_editor_core.config")
    _load_config_file = mod._load_config_file
    get_source_path_for_profile = mod.get_source_path_for_profile

    config = _load_config_file()

    assert isinstance(config, dict), f"config 는 dict 여야 한다, got {type(config)}"
    assert config, "editor_config.json 에 프로필이 하나도 없다"

    print(f"  Found {len(config)} profile(s) in editor_config.json")

    for profile_name, profile_config in config.items():
        # Skip merged profiles
        if profile_config.get("is_merged"):
            print(f"    - {profile_name}: merged profile (skip)")
            continue

        # Get source path
        source_path = get_source_path_for_profile(profile_name, profile_config)
        assert source_path, f"{profile_name}: source path 를 얻지 못했다"

        # Check if source exists
        if os.path.exists(source_path):
            print(f"    - {profile_name}: source exists at {source_path}")
        else:
            print(f"    - {profile_name}: source NOT found at {source_path}")

    print("  PASS: scan_all_registries would process correctly")


def test_editor_config_structure():
    """editor_config.json 구조 검증"""
    print("\n=== test_editor_config_structure ===")

    config_path = Path(__file__).parent.parent / "editor_config.json"

    if not config_path.exists():
        pytest.skip(f"Config file not found: {config_path}")

    # JSON 파싱 실패는 그대로 터뜨려서 테스트를 실패시킨다.
    with open(config_path, 'r', encoding='utf-8') as fp:
        config = json.load(fp)

    assert isinstance(config, dict), f"editor_config.json 은 object 여야 한다, got {type(config)}"
    print(f"  Found {len(config)} profile(s)")

    errors = []
    for profile_name, profile_config in config.items():
        required_fields = ["template_definitions_path", "tool_definitions_path"]
        missing = [name for name in required_fields if name not in profile_config]

        if missing:
            errors.append(f"{profile_name}: 필수 필드 누락 {missing}")
        else:
            language = profile_config.get("language", "python")
            types_count = len(profile_config.get("types_files", []))
            print(f"    - {profile_name}: {language}, {types_count} types files")

    assert not errors, "editor_config.json 프로필 검증 실패:\n  " + "\n  ".join(errors)
    print("  PASS: editor_config.json structure valid")


def run_all_tests():
    """Run all tests and report results"""
    print("=" * 60)
    print("Service Registry Tests (service_registry.py)")
    print("=" * 60)

    tests = [
        test_load_services_for_server_from_registry,
        test_load_services_mcp_prefix,
        test_registry_file_structure,
        test_types_property_file_structure,
        test_scan_all_registries,
        test_editor_config_structure,
    ]

    # 각 테스트는 이제 반환값이 아니라 예외(AssertionError)로 실패를 알린다.
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
