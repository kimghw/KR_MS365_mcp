"""
도구 이동/복사 모듈

동일 base_profile을 공유하는 프로필 간 도구 이동/복사 기능 제공
"""

from typing import Literal
import os
import yaml
from datetime import datetime

from .config import (
    get_sibling_profiles,
    get_profile_config,
    get_base_profile,
    resolve_paths,
    BASE_DIR,
    ROOT_DIR,
)
from .backup_utils import backup_file


class ToolMover:
    """프로필 간 도구 이동/복사를 담당하는 클래스"""

    def __init__(self):
        """초기화 - 설정 로딩"""
        self.base_dir = BASE_DIR
        self.root_dir = ROOT_DIR

    def _get_yaml_path(self, profile_name: str) -> str:
        """
        프로필의 YAML 파일 경로 반환

        Args:
            profile_name: 프로필 이름

        Returns:
            YAML 파일의 절대 경로
        """
        return os.path.join(
            self.base_dir,
            f"mcp_{profile_name}",
            "tool_definition_templates.yaml"
        )

    def _load_yaml(self, profile_name: str) -> dict:
        """
        프로필의 YAML 파일 로드

        Args:
            profile_name: 프로필 이름

        Returns:
            YAML 데이터 딕셔너리

        Raises:
            FileNotFoundError: YAML 파일이 없는 경우
        """
        yaml_path = self._get_yaml_path(profile_name)
        if not os.path.exists(yaml_path):
            raise FileNotFoundError(f"YAML file not found: {yaml_path}")

        with open(yaml_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {"tools": []}

    def _save_yaml(self, profile_name: str, data: dict) -> str:
        """
        YAML 파일 저장

        Args:
            profile_name: 프로필 이름
            data: 저장할 YAML 데이터

        Returns:
            저장된 파일 경로
        """
        yaml_path = self._get_yaml_path(profile_name)

        # 디렉토리가 없으면 생성
        os.makedirs(os.path.dirname(yaml_path), exist_ok=True)

        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(
                data,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False
            )

        return yaml_path

    def _get_backup_dir(self, profile_name: str) -> str:
        """
        프로필의 백업 디렉토리 경로 반환

        Args:
            profile_name: 프로필 이름

        Returns:
            백업 디렉토리 경로
        """
        profile_conf = get_profile_config(profile_name)
        paths = resolve_paths(profile_conf)
        return paths.get("backup_dir", os.path.join(self.base_dir, f"mcp_{profile_name}", "backups"))

    def _get_base_for_profile(self, profile_name: str) -> str:
        """
        프로필의 base 프로필 반환 (자신이 base인 경우 자신 반환)

        Args:
            profile_name: 프로필 이름

        Returns:
            base 프로필 이름
        """
        base = get_base_profile(profile_name)
        return base if base else profile_name

    def validate_move(
        self,
        source_profile: str,
        target_profile: str,
        tool_indices: list[int]
    ) -> dict:
        """
        이동 가능 여부 검증

        검증 항목:
        - source와 target이 동일 base_profile 공유
        - tool_indices가 유효한 범위
        - 도구의 mcp_service가 target에서 사용 가능

        Args:
            source_profile: 소스 프로필 이름
            target_profile: 타겟 프로필 이름
            tool_indices: 이동할 도구 인덱스 목록

        Returns:
            {
                "valid": bool,
                "errors": list[str],
                "warnings": list[str]
            }
        """
        errors = []
        warnings = []

        # 1. 동일 프로필 검사
        if source_profile == target_profile:
            errors.append("Source and target profiles are the same")
            return {"valid": False, "errors": errors, "warnings": warnings}

        # 2. 동일 base_profile 공유 검사
        source_siblings = get_sibling_profiles(source_profile)
        target_siblings = get_sibling_profiles(target_profile)

        source_base = self._get_base_for_profile(source_profile)
        target_base = self._get_base_for_profile(target_profile)

        if source_base != target_base:
            errors.append(
                f"Profiles do not share the same base_profile. "
                f"Source base: '{source_base}', Target base: '{target_base}'"
            )
            return {"valid": False, "errors": errors, "warnings": warnings}

        # 3. 소스 YAML 파일 존재 여부 검사
        source_yaml_path = self._get_yaml_path(source_profile)
        if not os.path.exists(source_yaml_path):
            errors.append(f"Source YAML file not found: {source_yaml_path}")
            return {"valid": False, "errors": errors, "warnings": warnings}

        # 4. 타겟 YAML 파일 존재 여부 검사
        target_yaml_path = self._get_yaml_path(target_profile)
        if not os.path.exists(target_yaml_path):
            warnings.append(
                f"Target YAML file not found. A new file will be created: {target_yaml_path}"
            )

        # 5. 소스 도구 로드 및 인덱스 범위 검사
        try:
            source_data = self._load_yaml(source_profile)
            source_tools = source_data.get("tools", [])
        except Exception as e:
            errors.append(f"Failed to load source YAML: {str(e)}")
            return {"valid": False, "errors": errors, "warnings": warnings}

        if not source_tools:
            errors.append("Source profile has no tools")
            return {"valid": False, "errors": errors, "warnings": warnings}

        # 인덱스 범위 검사
        invalid_indices = []
        for idx in tool_indices:
            if idx < 0 or idx >= len(source_tools):
                invalid_indices.append(idx)

        if invalid_indices:
            errors.append(
                f"Invalid tool indices: {invalid_indices}. "
                f"Valid range: 0-{len(source_tools) - 1}"
            )
            return {"valid": False, "errors": errors, "warnings": warnings}

        # 6. mcp_service 사용 가능 여부 검사
        # 동일 base_profile을 공유하면 동일한 서비스를 사용하므로 일반적으로 가능
        # 단, 경고 메시지 추가
        for idx in tool_indices:
            tool = source_tools[idx]
            tool_name = tool.get("name", f"tool_{idx}")
            mcp_service = tool.get("mcp_service", {})
            service_name = mcp_service.get("name", "")

            if service_name:
                warnings.append(
                    f"Tool '{tool_name}' uses mcp_service '{service_name}'. "
                    f"Ensure this service is available in target profile."
                )

        # 7. 타겟에 중복 이름 검사
        try:
            target_data = self._load_yaml(target_profile)
            target_tools = target_data.get("tools", [])
        except FileNotFoundError:
            target_tools = []
        except Exception as e:
            warnings.append(f"Could not load target YAML for duplicate check: {str(e)}")
            target_tools = []

        existing_names = {t.get("name") for t in target_tools if t.get("name")}
        for idx in tool_indices:
            tool_name = source_tools[idx].get("name", "")
            if tool_name in existing_names:
                warnings.append(
                    f"Tool '{tool_name}' already exists in target. "
                    f"It will be renamed to avoid conflict."
                )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }

    def move_tools(
        self,
        source_profile: str,
        target_profile: str,
        tool_indices: list[int],
        mode: Literal["move", "copy"] = "move"
    ) -> dict:
        """
        도구 이동/복사 수행

        작업 순서:
        1. validate_move() 호출
        2. 소스 YAML 로드
        3. 지정된 도구들 추출
        4. 타겟 YAML 로드
        5. 도구 추가 (중복 이름 처리)
        6. mode가 "move"면 소스에서 삭제
        7. 양쪽 YAML 저장
        8. 백업 생성

        Args:
            source_profile: 소스 프로필 이름
            target_profile: 타겟 프로필 이름
            tool_indices: 이동할 도구 인덱스 목록
            mode: "move" (이동) 또는 "copy" (복사)

        Returns:
            {
                "success": bool,
                "moved_tools": list[str],
                "source_backup": str,
                "target_backup": str,
                "error": str (실패시)
            }
        """
        result = {
            "success": False,
            "moved_tools": [],
            "source_backup": None,
            "target_backup": None,
            "error": None
        }

        # 1. 유효성 검증
        validation = self.validate_move(source_profile, target_profile, tool_indices)
        if not validation["valid"]:
            result["error"] = "; ".join(validation["errors"])
            return result

        try:
            # 2. 소스 YAML 로드
            source_data = self._load_yaml(source_profile)
            source_tools = source_data.get("tools", [])

            # 3. 지정된 도구들 추출 (인덱스 역순으로 정렬하여 삭제 시 인덱스 오류 방지)
            sorted_indices = sorted(tool_indices, reverse=True)
            tools_to_move = []

            # 먼저 도구들을 추출 (정순으로)
            for idx in sorted(tool_indices):
                tools_to_move.append(source_tools[idx].copy())

            # 4. 타겟 YAML 로드
            try:
                target_data = self._load_yaml(target_profile)
            except FileNotFoundError:
                # 타겟 파일이 없으면 새로 생성
                target_data = {"tools": []}

            target_tools = target_data.get("tools", [])

            # 5. 도구 추가 (중복 이름 처리)
            moved_tool_names = []
            for tool in tools_to_move:
                # 중복 이름 처리
                processed_tool = self._handle_duplicate_name(tool, target_tools)
                target_tools.append(processed_tool)
                moved_tool_names.append(processed_tool.get("name", "unnamed"))

            target_data["tools"] = target_tools

            # 6. mode가 "move"면 소스에서 삭제
            if mode == "move":
                for idx in sorted_indices:
                    del source_tools[idx]
                source_data["tools"] = source_tools

            # 7. 타임스탬프 생성 (백업용)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # 8. 백업 생성
            source_yaml_path = self._get_yaml_path(source_profile)
            target_yaml_path = self._get_yaml_path(target_profile)

            source_backup_dir = self._get_backup_dir(source_profile)
            target_backup_dir = self._get_backup_dir(target_profile)

            # 소스 백업 (move 모드인 경우만)
            if mode == "move" and os.path.exists(source_yaml_path):
                source_backup = backup_file(source_yaml_path, source_backup_dir, timestamp)
                result["source_backup"] = source_backup

            # 타겟 백업 (기존 파일이 있는 경우만)
            if os.path.exists(target_yaml_path):
                target_backup = backup_file(target_yaml_path, target_backup_dir, timestamp)
                result["target_backup"] = target_backup

            # 9. YAML 파일 저장
            if mode == "move":
                self._save_yaml(source_profile, source_data)
            self._save_yaml(target_profile, target_data)

            result["success"] = True
            result["moved_tools"] = moved_tool_names

        except Exception as e:
            result["error"] = str(e)

        return result

    def get_movable_tools(
        self,
        source_profile: str,
        target_profile: str
    ) -> list[dict]:
        """
        이동 가능한 도구 목록 조회

        Args:
            source_profile: 소스 프로필 이름
            target_profile: 타겟 프로필 이름

        Returns:
            [
                {
                    "index": 0,
                    "name": "mail_list",
                    "description": "도구 설명",
                    "mcp_service": "서비스명",
                    "can_move": true,
                    "reason": null
                }
            ]
        """
        result = []

        # base_profile 검사
        source_base = self._get_base_for_profile(source_profile)
        target_base = self._get_base_for_profile(target_profile)

        same_base = (source_base == target_base)

        # 소스 도구 로드
        try:
            source_data = self._load_yaml(source_profile)
            source_tools = source_data.get("tools", [])
        except FileNotFoundError:
            return []
        except Exception as e:
            return [{"error": str(e)}]

        # 타겟 도구 로드 (중복 검사용)
        try:
            target_data = self._load_yaml(target_profile)
            target_tools = target_data.get("tools", [])
        except FileNotFoundError:
            target_tools = []
        except Exception:
            target_tools = []

        target_names = {t.get("name") for t in target_tools if t.get("name")}

        for idx, tool in enumerate(source_tools):
            tool_name = tool.get("name", f"tool_{idx}")
            tool_desc = tool.get("description", "")[:100]  # 설명 100자 제한
            mcp_service = tool.get("mcp_service", {})
            service_name = mcp_service.get("name", "")

            can_move = True
            reason = None

            # 이동 불가 사유 검사
            if not same_base:
                can_move = False
                reason = f"Different base profiles: source='{source_base}', target='{target_base}'"
            elif source_profile == target_profile:
                can_move = False
                reason = "Source and target are the same profile"

            # 중복 이름 경고 (이동은 가능하지만 이름이 변경됨)
            duplicate_warning = None
            if tool_name in target_names:
                duplicate_warning = f"Name '{tool_name}' exists in target; will be renamed"

            result.append({
                "index": idx,
                "name": tool_name,
                "description": tool_desc,
                "mcp_service": service_name,
                "can_move": can_move,
                "reason": reason,
                "duplicate_warning": duplicate_warning
            })

        return result

    def _handle_duplicate_name(
        self,
        tool: dict,
        existing_tools: list[dict]
    ) -> dict:
        """
        중복 이름 처리 (예: mail_list -> mail_list_2)

        Args:
            tool: 추가할 도구 딕셔너리
            existing_tools: 기존 도구 목록

        Returns:
            이름이 처리된 도구 딕셔너리 (복사본)
        """
        # 도구 복사본 생성
        processed_tool = tool.copy()
        original_name = processed_tool.get("name", "unnamed")

        # 기존 이름 목록 추출
        existing_names = {t.get("name") for t in existing_tools if t.get("name")}

        # 중복이 없으면 그대로 반환
        if original_name not in existing_names:
            return processed_tool

        # 중복 처리: 숫자 접미사 추가
        counter = 2
        new_name = f"{original_name}_{counter}"

        while new_name in existing_names:
            counter += 1
            new_name = f"{original_name}_{counter}"

        processed_tool["name"] = new_name

        return processed_tool

    def get_sibling_profiles_for_tool_move(self, profile_name: str) -> list[dict]:
        """
        도구 이동 가능한 형제 프로필 목록 조회

        현재 프로필과 동일한 base_profile을 공유하는 프로필 목록 반환

        Args:
            profile_name: 현재 프로필 이름

        Returns:
            [
                {
                    "name": "outlook_read",
                    "is_base": false,
                    "tool_count": 5
                }
            ]
        """
        siblings = get_sibling_profiles(profile_name)
        result = []

        for sibling in siblings:
            if sibling == profile_name:
                continue  # 자신은 제외

            # 도구 수 조회
            try:
                data = self._load_yaml(sibling)
                tool_count = len(data.get("tools", []))
            except FileNotFoundError:
                tool_count = 0
            except Exception:
                tool_count = -1  # 오류 발생

            # base 프로필 여부
            is_base = (get_base_profile(sibling) is None)

            result.append({
                "name": sibling,
                "is_base": is_base,
                "tool_count": tool_count
            })

        return result
