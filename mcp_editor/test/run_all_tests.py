#!/usr/bin/env python3
"""
Registry 및 Type Extractor 통합 테스트 러너

모든 테스트 모듈을 실행하고 결과를 요약합니다.

사용법:
    python run_all_tests.py           # 전체 테스트 실행
    python run_all_tests.py --verbose # 상세 출력
    python run_all_tests.py --module extract_types  # 특정 모듈만 테스트
"""

import sys
import argparse
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def run_test_module(module_name: str) -> tuple[int, int]:
    """Run a single test module and return (passed, failed) counts."""
    try:
        if module_name == "extract_types":
            from test_extract_types import run_all_tests
        elif module_name == "extract_types_js":
            from test_extract_types_js import run_all_tests
        elif module_name == "mcp_service_scanner":
            from test_mcp_service_scanner import run_all_tests
        elif module_name == "service_registry":
            from test_service_registry import run_all_tests
        else:
            print(f"Unknown module: {module_name}")
            return (0, 1)

        success = run_all_tests()
        return (1, 0) if success else (0, 1)

    except ImportError as e:
        print(f"Failed to import {module_name}: {e}")
        return (0, 1)
    except Exception as e:
        print(f"Error running {module_name}: {e}")
        import traceback
        traceback.print_exc()
        return (0, 1)


def main():
    parser = argparse.ArgumentParser(description="Run registry and type extractor tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--module", "-m", type=str, help="Run specific module only")
    args = parser.parse_args()

    print("=" * 70)
    print("Registry & Type Extractor Integration Tests")
    print("=" * 70)
    print()

    # Available test modules
    all_modules = [
        ("extract_types", "Python Type Extractor (Pydantic BaseModel)"),
        ("extract_types_js", "JavaScript Type Extractor (Sequelize)"),
        ("mcp_service_scanner", "MCP Service Scanner (@mcp_service decorator)"),
        ("service_registry", "Service Registry (JSON loading & validation)"),
    ]

    # Filter modules if specific one requested
    if args.module:
        all_modules = [(m, d) for m, d in all_modules if args.module in m]
        if not all_modules:
            print(f"No matching module for: {args.module}")
            print("Available modules: extract_types, extract_types_js, mcp_service_scanner, service_registry")
            return 1

    total_passed = 0
    total_failed = 0
    module_results = []

    for module_name, description in all_modules:
        print()
        print(f">>> Running: {description}")
        print("-" * 70)

        passed, failed = run_test_module(module_name)
        total_passed += passed
        total_failed += failed
        module_results.append((module_name, passed, failed))

    # Summary
    print()
    print("=" * 70)
    print("OVERALL SUMMARY")
    print("=" * 70)
    print()

    for module_name, passed, failed in module_results:
        if passed > 0:
            status = "PASSED"
        else:
            status = "FAILED"
        print(f"  {module_name:<25} [{status}]")

    print()
    print(f"Modules: {total_passed} passed, {total_failed} failed")
    print()

    if total_failed == 0:
        print("All tests passed!")
        return 0
    else:
        print("Some tests failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
