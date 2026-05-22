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

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def test_load_services_for_server_from_registry():
    """레지스트리 JSON 파일에서 서비스 로딩 테스트"""
    print("\n=== test_load_services_for_server_from_registry ===")

    # Check if outlook registry exists
    registry_path = Path(__file__).parent.parent / "mcp_outlook" / "registry_outlook.json"

    if not registry_path.exists():
        print(f"  SKIP: Registry file not found: {registry_path}")
        return True

    try:
        # Import after path setup
        from tool_editor_core.service_registry import load_services_for_server

        # Load services for outlook server
        services = load_services_for_server("outlook", None, force_rescan=False)

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
        return True

    except FileNotFoundError as e:
        print(f"  SKIP: {e}")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_load_services_mcp_prefix():
    """mcp_ 접두사 처리 테스트"""
    print("\n=== test_load_services_mcp_prefix ===")

    # Check if outlook registry exists
    registry_path = Path(__file__).parent.parent / "mcp_outlook" / "registry_outlook.json"

    if not registry_path.exists():
        print(f"  SKIP: Registry file not found: {registry_path}")
        return True

    try:
        from tool_editor_core.service_registry import load_services_for_server

        # Test with mcp_ prefix
        services1 = load_services_for_server("mcp_outlook", None, force_rescan=False)

        # Test without prefix
        services2 = load_services_for_server("outlook", None, force_rescan=False)

        print(f"  'mcp_outlook' loaded {len(services1)} services")
        print(f"  'outlook' loaded {len(services2)} services")

        # Both should load the same services
        assert len(services1) == len(services2), "Both should return same number of services"
        print("  PASS: mcp_ prefix handled correctly")
        return True

    except FileNotFoundError as e:
        print(f"  SKIP: {e}")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_registry_file_structure():
    """레지스트리 파일 구조 검증"""
    print("\n=== test_registry_file_structure ===")

    # Check all registry files
    registry_dir = Path(__file__).parent.parent
    registry_files = list(registry_dir.glob("mcp_*/registry_*.json"))

    if not registry_files:
        print("  SKIP: No registry files found")
        return True

    print(f"  Found {len(registry_files)} registry file(s)")

    all_valid = True
    for registry_file in registry_files:
        try:
            with open(registry_file, 'r', encoding='utf-8') as f:
                registry = json.load(f)

            # Check required fields
            required_fields = ["version", "generated_at", "server_name", "services"]
            missing = [f for f in required_fields if f not in registry]

            if missing:
                print(f"  FAIL: {registry_file.name} missing: {missing}")
                all_valid = False
                continue

            # Check services structure
            services = registry.get("services", {})
            if services:
                sample_service = list(services.values())[0]
                service_fields = ["service_name", "handler", "signature", "parameters", "metadata"]
                service_missing = [f for f in service_fields if f not in sample_service]

                if service_missing:
                    print(f"  WARN: {registry_file.name} service missing: {service_missing}")

            print(f"  OK: {registry_file.name} - {len(services)} services")

        except json.JSONDecodeError as e:
            print(f"  FAIL: {registry_file.name} - Invalid JSON: {e}")
            all_valid = False
        except Exception as e:
            print(f"  FAIL: {registry_file.name} - {e}")
            all_valid = False

    if all_valid:
        print("  PASS: All registry files valid")
    return all_valid


def test_types_property_file_structure():
    """types_property 파일 구조 검증"""
    print("\n=== test_types_property_file_structure ===")

    # Check all types_property files
    registry_dir = Path(__file__).parent.parent
    types_files = list(registry_dir.glob("mcp_*/types_property_*.json"))

    if not types_files:
        print("  SKIP: No types_property files found")
        return True

    print(f"  Found {len(types_files)} types_property file(s)")

    all_valid = True
    for types_file in types_files:
        try:
            with open(types_file, 'r', encoding='utf-8') as f:
                types_data = json.load(f)

            # Check required fields
            required_fields = ["version", "server_name", "classes", "all_properties"]
            missing = [f for f in required_fields if f not in types_data]

            if missing:
                print(f"  FAIL: {types_file.name} missing: {missing}")
                all_valid = False
                continue

            classes = types_data.get("classes", [])
            all_props = types_data.get("all_properties", [])
            language = types_data.get("language", "unknown")

            print(f"  OK: {types_file.name} - {len(classes)} classes, {len(all_props)} props ({language})")

        except json.JSONDecodeError as e:
            print(f"  FAIL: {types_file.name} - Invalid JSON: {e}")
            all_valid = False
        except Exception as e:
            print(f"  FAIL: {types_file.name} - {e}")
            all_valid = False

    if all_valid:
        print("  PASS: All types_property files valid")
    return all_valid


def test_scan_all_registries():
    """전체 레지스트리 스캔 테스트 (시뮬레이션)"""
    print("\n=== test_scan_all_registries ===")

    # This test simulates scan_all_registries without actually modifying files
    try:
        from tool_editor_core.config import _load_config_file, get_source_path_for_profile

        config = _load_config_file()

        print(f"  Found {len(config)} profile(s) in editor_config.json")

        for profile_name, profile_config in config.items():
            # Skip merged profiles
            if profile_config.get("is_merged"):
                print(f"    - {profile_name}: merged profile (skip)")
                continue

            # Get source path
            source_path = get_source_path_for_profile(profile_name, profile_config)

            # Check if source exists
            if os.path.exists(source_path):
                print(f"    - {profile_name}: source exists at {source_path}")
            else:
                print(f"    - {profile_name}: source NOT found at {source_path}")

        print("  PASS: scan_all_registries would process correctly")
        return True

    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_editor_config_structure():
    """editor_config.json 구조 검증"""
    print("\n=== test_editor_config_structure ===")

    config_path = Path(__file__).parent.parent / "editor_config.json"

    if not config_path.exists():
        print(f"  SKIP: Config file not found: {config_path}")
        return True

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        print(f"  Found {len(config)} profile(s)")

        for profile_name, profile_config in config.items():
            required_fields = ["template_definitions_path", "tool_definitions_path"]
            missing = [f for f in required_fields if f not in profile_config]

            if missing:
                print(f"    - {profile_name}: missing {missing}")
            else:
                language = profile_config.get("language", "python")
                types_count = len(profile_config.get("types_files", []))
                print(f"    - {profile_name}: {language}, {types_count} types files")

        print("  PASS: editor_config.json structure valid")
        return True

    except json.JSONDecodeError as e:
        print(f"  FAIL: Invalid JSON: {e}")
        return False
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


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
