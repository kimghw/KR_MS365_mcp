#!/usr/bin/env python3
"""
MCP Meta Register Manager
메타데이터 등록 및 관리를 담당하는 매니저 모듈
템플릿 생성용 독립 실행 스크립트
"""

from typing import Dict, List, Optional, Any
import json
import os
import sys
from datetime import datetime

# 현재 디렉토리를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class MetaRegisterManager:
    """MCP 서비스 메타데이터 등록 관리자"""

    def __init__(self):
        self.registry: Dict[str, Dict[str, Any]] = {}
        self.registration_history: List[Dict[str, Any]] = []

    def register_service(self, service_name: str, metadata: Dict[str, Any]) -> bool:
        """
        서비스 메타데이터를 레지스트리에 등록

        Args:
            service_name: 서비스 이름
            metadata: 서비스 메타데이터

        Returns:
            등록 성공 여부
        """
        try:
            # 등록 타임스탬프 추가
            metadata["registered_at"] = datetime.now().isoformat()

            # 레지스트리에 등록
            self.registry[service_name] = metadata

            # 등록 이력 기록
            self.registration_history.append(
                {"service": service_name, "action": "register", "timestamp": metadata["registered_at"]}
            )

            return True
        except Exception as e:
            print(f"Failed to register service {service_name}: {e}")
            return False

    def unregister_service(self, service_name: str) -> bool:
        """
        서비스를 레지스트리에서 제거

        Args:
            service_name: 제거할 서비스 이름

        Returns:
            제거 성공 여부
        """
        if service_name in self.registry:
            del self.registry[service_name]

            # 제거 이력 기록
            self.registration_history.append(
                {"service": service_name, "action": "unregister", "timestamp": datetime.now().isoformat()}
            )
            return True
        return False

    def get_service_metadata(self, service_name: str) -> Optional[Dict[str, Any]]:
        """
        특정 서비스의 메타데이터 조회

        Args:
            service_name: 조회할 서비스 이름

        Returns:
            서비스 메타데이터 또는 None
        """
        return self.registry.get(service_name)

    def list_registered_services(self) -> List[str]:
        """등록된 모든 서비스 목록 반환"""
        return list(self.registry.keys())

    def get_registry_snapshot(self) -> Dict[str, Any]:
        """현재 레지스트리 상태의 스냅샷 반환"""
        return {
            "services": self.registry.copy(),
            "total_count": len(self.registry),
            "snapshot_time": datetime.now().isoformat(),
        }

    def export_registry(self, file_path: str) -> bool:
        """
        레지스트리를 JSON 파일로 내보내기

        Args:
            file_path: 내보낼 파일 경로

        Returns:
            내보내기 성공 여부
        """
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self.get_registry_snapshot(), f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Failed to export registry: {e}")
            return False

    def import_registry(self, file_path: str) -> bool:
        """
        JSON 파일에서 레지스트리 가져오기

        Args:
            file_path: 가져올 파일 경로

        Returns:
            가져오기 성공 여부
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "services" in data:
                    self.registry = data["services"]
                    return True
            return False
        except Exception as e:
            print(f"Failed to import registry: {e}")
            return False

    def get_registration_history(self) -> List[Dict[str, Any]]:
        """등록/제거 이력 반환"""
        return self.registration_history.copy()

    def collect_from_decorator(self) -> Dict[str, Any]:
        """
        mcp_service_decorator의 런타임 레지스트리에서 데이터 수집

        Returns:
            데코레이터에서 수집된 서비스 메타데이터
        """
        try:
            from mcp_service_decorator import MCP_SERVICE_REGISTRY

            return MCP_SERVICE_REGISTRY.copy()
        except ImportError as e:
            print(f"Failed to import decorator registry: {e}")
            return {}

    def collect_from_scanner(self, base_dir: str, server_name: str = "default") -> Dict[str, Any]:
        """
        mcp_service_scanner를 사용해서 정적 분석으로 데이터 수집

        Args:
            base_dir: 스캔할 디렉토리 경로
            server_name: 서버 이름

        Returns:
            스캐너에서 수집된 서비스 메타데이터
        """
        try:
            from mcp_service_scanner import scan_codebase_for_mcp_services

            # 코드베이스 스캔
            services_by_file = scan_codebase_for_mcp_services(base_dir)

            # 서비스 데이터 처리 - 개선된 구조로 변환
            services = {}
            for func_name, service_data in services_by_file.items():
                # handler 정보 구성
                handler = {
                    "class_name": service_data.get("class"),
                    "instance": service_data.get("instance"),
                    "method": service_data.get("method"),
                    "is_async": service_data.get("is_async", False),
                    "file": service_data.get("file"),
                    "line": service_data.get("line"),
                }

                # 원본 메타데이터 가져오기
                original_metadata = service_data.get("metadata", {})

                # 서비스 구조 구성 - service_name 바로 아래에 주요 필드, metadata는 parameters 다음
                service_entry = {
                    "service_name": func_name,
                    "handler": handler,
                    "signature": service_data.get("signature", ""),
                    "parameters": service_data.get("parameters", []),
                    "metadata": {
                        "description": original_metadata.get("description", ""),
                        "category": original_metadata.get("category", ""),
                        "tags": original_metadata.get("tags", []),
                        "tool_names": original_metadata.get("tool_names", [f"Handle_{func_name}"]),
                    },
                }

                # metadata에 추가 필드가 있으면 포함
                if "priority" in original_metadata:
                    service_entry["metadata"]["priority"] = original_metadata["priority"]

                services[func_name] = service_entry

            return services
        except Exception as e:
            print(f"Failed to scan with mcp_service_scanner: {e}")
            return {}

    def generate_service_manifest(
        self,
        base_dir: Optional[str] = None,
        server_name: str = "default",
        include_runtime: bool = True,
        include_static: bool = True,
    ) -> Dict[str, Any]:
        """
        데코레이터와 스캐너에서 데이터를 수집하여 통합 서비스 매니페스트 생성

        Args:
            base_dir: 스캔할 디렉토리 (static 분석용)
            server_name: 서버 이름
            include_runtime: 런타임 데코레이터 데이터 포함 여부
            include_static: 정적 스캔 데이터 포함 여부

        Returns:
            통합 서비스 매니페스트
        """
        manifest = {
            "version": "1.0",
            "generated_at": datetime.now().isoformat(),
            "server_name": server_name,
            "services": {},
            "sources": [],
        }

        # 런타임 데코레이터 데이터 수집
        if include_runtime:
            runtime_data = self.collect_from_decorator()
            if runtime_data:
                manifest["sources"].append("runtime_decorator")
                for func_name, service_data in runtime_data.items():
                    # 런타임 데이터도 같은 구조로 변환
                    original_metadata = service_data.get("metadata", {})

                    # handler 정보 구성 (런타임은 일부 정보가 없을 수 있음)
                    handler = {"source": "runtime_decorator"}

                    # 런타임 서비스 구조
                    runtime_entry = {
                        "service_name": func_name,
                        "handler": handler,
                        "signature": service_data.get("signature", ""),
                        "parameters": service_data.get("parameters", []),
                        "metadata": {
                            "description": original_metadata.get("description", ""),
                            "category": original_metadata.get("category", ""),
                            "tags": original_metadata.get("tags", []),
                            "tool_names": original_metadata.get("tool_names", [f"Handle_{func_name}"]),
                            "source": "runtime_decorator",
                        },
                    }

                    manifest["services"][f"runtime.{func_name}"] = runtime_entry

        # 정적 스캔 데이터 수집
        if include_static and base_dir:
            static_data = self.collect_from_scanner(base_dir, server_name)
            if static_data:
                manifest["sources"].append("static_scanner")
                for service_key, service_data in static_data.items():
                    # 중복 체크 - static이 runtime보다 우선순위 낮음
                    func_name = service_data.get("service_name", service_key.split(".")[-1])
                    runtime_key = f"runtime.{func_name}"
                    if runtime_key not in manifest["services"]:
                        # metadata에 source 추가
                        service_data["metadata"]["source"] = "static_scanner"
                        manifest["services"][service_key] = service_data

        # 통계 정보 추가
        manifest["statistics"] = {
            "total_services": len(manifest["services"]),
            "runtime_services": sum(
                1 for s in manifest["services"].values() if s.get("metadata", {}).get("source") == "runtime_decorator"
            ),
            "static_services": sum(
                1 for s in manifest["services"].values() if s.get("metadata", {}).get("source") == "static_scanner"
            ),
        }

        return manifest

    def export_service_manifest(
        self, file_path: Optional[str] = None, base_dir: Optional[str] = None, server_name: str = "default"
    ) -> bool:
        """
        서비스 매니페스트를 JSON 파일로 내보내기

        Args:
            file_path: 저장할 파일 경로 (None이면 registry_{server_name}.json 자동 생성)
            base_dir: 스캔할 디렉토리
            server_name: 서버 이름

        Returns:
            내보내기 성공 여부
        """
        try:
            # 파일 경로가 없으면 서버명 기반으로 자동 생성
            if file_path is None:
                file_path = f"registry_{server_name}.json"

            manifest = self.generate_service_manifest(base_dir, server_name)

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)

            print(f"Service manifest exported to: {file_path}")
            print(f"Total services: {manifest['statistics']['total_services']}")
            print(f"- Runtime: {manifest['statistics']['runtime_services']}")
            print(f"- Static: {manifest['statistics']['static_services']}")

            return True
        except Exception as e:
            print(f"Failed to export service manifest: {e}")
            return False


# 전역 매니저 인스턴스
registry_manager = MetaRegisterManager()


def extract_service_metadata():
    """서비스 메타데이터를 추출하고 JSON으로 내보내는 메인 함수"""
    import argparse

    parser = argparse.ArgumentParser(description="MCP Service Registry Manager")
    parser.add_argument("--base-dir", type=str, help="Base directory to scan for services")
    parser.add_argument(
        "--server-name", type=str, default="default", help="Server name for the services (default: 'default')"
    )
    parser.add_argument(
        "--output", type=str, default=None, help="Output file path (default: registry_{server_name}.json)"
    )
    parser.add_argument("--runtime-only", action="store_true", help="Only collect runtime decorator data")
    parser.add_argument("--static-only", action="store_true", help="Only collect static scanner data")

    args = parser.parse_args()

    # 포함 옵션 결정
    if args.static_only and not args.base_dir:
        print("Error: --base-dir is required when using --static-only")
        sys.exit(1)

    # 출력 파일명 결정
    output_file = args.output if args.output else f"registry_{args.server_name}.json"

    # 서비스 매니페스트 생성 및 내보내기
    success = registry_manager.export_service_manifest(
        file_path=output_file, base_dir=args.base_dir, server_name=args.server_name
    )

    if success:
        print(f"\n[OK] Service registry successfully exported to: {output_file}")
    else:
        print("\n[ERROR] Failed to export service registry")
        sys.exit(1)


if __name__ == "__main__":
    extract_service_metadata()
