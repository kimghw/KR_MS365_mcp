"""
Profile Management Module

프로필 재사용 및 삭제 함수들:
- YAML 템플릿 복사
- 에디터 설정 업데이트
- 서버 프로젝트 폴더 생성
- 프로필 삭제
- 파생 프로필 생성 및 관리
"""

import os
import json
import shutil

# Import config module for helper functions
from . import config


def copy_yaml_templates(existing_service: str, new_profile_name: str) -> dict:
    """
    Copy existing service's YAML templates to a new profile directory.

    Args:
        existing_service: Existing service name (e.g., "outlook")
        new_profile_name: New profile name (e.g., "outlook_read")

    Returns:
        {
            "success": bool,
            "yaml_path": str,
            "py_path": str,
            "error": str (on failure)
        }
    """
    try:
        base_dir = os.path.dirname(os.path.dirname(__file__))  # mcp_editor/

        # 1. Source paths
        existing_yaml_path = os.path.join(
            base_dir,
            f"mcp_{existing_service}",
            "tool_definition_templates.yaml"
        )

        existing_py_path = os.path.join(
            base_dir,
            f"mcp_{existing_service}",
            "tool_definition_templates.py"
        )

        if not os.path.exists(existing_yaml_path):
            return {
                "success": False,
                "error": f"Template YAML not found: {existing_yaml_path}"
            }

        # 2. Create new profile directory
        new_profile_dir = os.path.join(base_dir, f"mcp_{new_profile_name}")
        os.makedirs(new_profile_dir, exist_ok=True)
        os.makedirs(os.path.join(new_profile_dir, "backups"), exist_ok=True)

        # 3. Copy YAML file
        new_yaml_path = os.path.join(new_profile_dir, "tool_definition_templates.yaml")
        shutil.copy2(existing_yaml_path, new_yaml_path)

        # 4. Copy or create Python loader file
        new_py_path = os.path.join(new_profile_dir, "tool_definition_templates.py")
        if os.path.exists(existing_py_path):
            shutil.copy2(existing_py_path, new_py_path)
        else:
            # Create Python loader
            py_content = '''"""
MCP Tool Definition Templates - AUTO-GENERATED
Signatures extracted from source code using AST parsing

This file loads tool_definition_templates.yaml and provides MCP_TOOLS list.
"""
from typing import List, Dict, Any
from pathlib import Path
import yaml


def _load_tools_from_yaml() -> List[Dict[str, Any]]:
    """Load tool definitions from YAML file."""
    yaml_path = Path(__file__).parent / "tool_definition_templates.yaml"

    if not yaml_path.exists():
        raise FileNotFoundError(f"YAML file not found: {yaml_path}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data.get("tools", [])


# Provide MCP_TOOLS list for backwards compatibility
MCP_TOOLS: List[Dict[str, Any]] = _load_tools_from_yaml()
'''
            with open(new_py_path, 'w', encoding='utf-8') as f:
                f.write(py_content)

        return {
            "success": True,
            "yaml_path": new_yaml_path,
            "py_path": new_py_path
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def update_editor_config_for_reuse(
    existing_service: str,
    new_profile_name: str,
    port: int
) -> None:
    """
    Add new profile to editor_config.json that reuses existing service.

    Args:
        existing_service: Existing service name (e.g., "outlook")
        new_profile_name: New profile name (e.g., "outlook_read")
        port: New server port number

    Raises:
        KeyError: If existing service not found in config
    """
    base_dir = os.path.dirname(os.path.dirname(__file__))  # mcp_editor/
    config_path = os.path.join(base_dir, "editor_config.json")

    with open(config_path, encoding='utf-8') as f:
        config = json.load(f)

    # Reference existing config
    if existing_service not in config:
        raise KeyError(f"Existing service '{existing_service}' not found in editor_config.json")

    existing_conf = config[existing_service]

    # Add new profile with base_profile reference (source_dir은 컨벤션으로 유추)
    config[new_profile_name] = {
        "base_profile": existing_service,  # 기존 서비스 참조
        "template_definitions_path": f"mcp_{new_profile_name}/tool_definition_templates.py",
        "tool_definitions_path": f"../mcp_{new_profile_name}/mcp_server/tool_definitions.py",
        "backup_dir": f"mcp_{new_profile_name}/backups",
        "types_files": existing_conf.get("types_files", []),  # Same types!
        "host": "0.0.0.0",
        "port": port,
        "is_reused": True  # Mark as reused profile
    }

    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def create_server_project_folder(new_profile_name: str) -> dict:
    """
    Create server project folder for new profile.

    Args:
        new_profile_name: New profile name (e.g., "outlook_read")

    Returns:
        {
            "success": bool,
            "project_dir": str,
            "error": str (on failure)
        }
    """
    try:
        base_dir = os.path.dirname(os.path.dirname(__file__))  # mcp_editor/
        root_dir = os.path.dirname(base_dir)   # /home/kimghw/Connector_auth/

        # 1. Create root project folder
        project_dir = os.path.join(root_dir, f"mcp_{new_profile_name}")

        if os.path.exists(project_dir):
            return {
                "success": False,
                "error": f"Project folder mcp_{new_profile_name} already exists"
            }

        os.makedirs(project_dir, exist_ok=True)

        # 2. Create mcp_server folder
        mcp_server_dir = os.path.join(project_dir, "mcp_server")
        os.makedirs(mcp_server_dir, exist_ok=True)

        return {
            "success": True,
            "project_dir": project_dir
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def create_reused_profile(
    existing_service: str,
    new_profile_name: str,
    port: int
) -> dict:
    """
    Create new MCP profile that reuses existing service.

    Args:
        existing_service: Existing service name (e.g., "outlook")
        new_profile_name: New profile name (e.g., "outlook_read")
        port: New server port number

    Returns:
        {
            "success": bool,
            "profile_name": str,
            "editor_dir": str,
            "error": str (on failure)
        }
    """
    try:
        # 1. Copy YAML templates
        yaml_result = copy_yaml_templates(existing_service, new_profile_name)

        if not yaml_result.get("success"):
            return {
                "success": False,
                "error": yaml_result.get("error", "Failed to copy YAML templates")
            }

        # 2. Update editor_config.json
        update_editor_config_for_reuse(existing_service, new_profile_name, port)

        # 3. Create server project folder (optional)
        project_result = create_server_project_folder(new_profile_name)
        # Continue even if project folder creation fails

        return {
            "success": True,
            "profile_name": new_profile_name,
            "editor_dir": f"mcp_editor/mcp_{new_profile_name}",
            "yaml_path": yaml_result["yaml_path"],
            "py_path": yaml_result["py_path"],
            "project_dir": project_result.get("project_dir", "")
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def delete_mcp_profile(profile_name: str) -> dict:
    """
    Delete an MCP profile completely.

    Deletes:
    - mcp_editor/mcp_{profile}/ folder
    - mcp_{profile}/ folder (if exists)
    - Profile from editor_config.json

    Args:
        profile_name: Profile name (e.g., "outlook_read")

    Returns:
        {
            "success": bool,
            "deleted_paths": list,
            "error": str (on failure)
        }
    """
    try:
        deleted_paths = []
        base_dir = os.path.dirname(os.path.dirname(__file__))  # mcp_editor/
        root_dir = os.path.dirname(base_dir)   # /home/kimghw/Connector_auth/

        # 1. Delete editor profile folder
        editor_dir = os.path.join(base_dir, f"mcp_{profile_name}")
        if os.path.exists(editor_dir):
            shutil.rmtree(editor_dir)
            deleted_paths.append(editor_dir)

        # 2. Delete server project folder (if exists)
        project_dir = os.path.join(root_dir, f"mcp_{profile_name}")
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir)
            deleted_paths.append(project_dir)

        # 3. Delete types_property_{profile}.json file (in mcp_{profile}/ directory)
        profile_dir = os.path.join(base_dir, f"mcp_{profile_name}")
        types_property_file = os.path.join(profile_dir, f"types_property_{profile_name}.json")

        if os.path.exists(types_property_file):
            os.remove(types_property_file)
            deleted_paths.append(f"mcp_{profile_name}/types_property_{profile_name}.json")

        # 4. Remove from editor_config.json
        config_path = os.path.join(base_dir, "editor_config.json")

        if os.path.exists(config_path):
            with open(config_path, encoding='utf-8') as f:
                config = json.load(f)

            if profile_name in config:
                del config[profile_name]

                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)

                deleted_paths.append(f"editor_config.json:{profile_name}")

        return {
            "success": True,
            "deleted_paths": deleted_paths
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def create_derived_profile(
    base_profile: str,
    new_profile_name: str,
    port: int = 8091
) -> dict:
    """
    Create a new derived profile from an existing base profile.

    Extends create_reused_profile() with base-derived relationship management.

    작업 순서:
        1. base_profile 유효성 검증 (존재하는지, source_dir 있는지)
        2. 기존 create_reused_profile() 호출 (내부 함수로 재사용)
        3. base_profile 필드 설정 (editor_config.json)
        4. base 프로필의 derived_profiles에 추가 (config.update_derived_profiles_list 사용)
        5. is_base 플래그 설정

    Args:
        base_profile: Base profile name (e.g., "outlook")
        new_profile_name: New derived profile name (e.g., "outlook_read")
        port: New server port number (default: 8091)

    Returns:
        {
            "success": bool,
            "profile_name": str,
            "base_profile": str,
            "editor_dir": str,
            "project_dir": str,
            "error": str (on failure)
        }

    Terminology:
        - profile_key: `mcp_{server_name}` 형식
        - 모듈 디렉토리: `mcp_{server_name}/`
    """
    try:
        # 1. base_profile 유효성 검증
        base_config = config.get_profile_config(base_profile)

        if not base_config:
            return {
                "success": False,
                "profile_name": new_profile_name,
                "base_profile": base_profile,
                "editor_dir": "",
                "project_dir": "",
                "error": f"Base profile '{base_profile}' not found in editor_config.json"
            }

        # 소스 디렉토리 존재 여부 확인 (컨벤션 기반)
        source_path = config.get_source_path_for_profile(base_profile, base_config)
        if not os.path.exists(source_path):
            return {
                "success": False,
                "profile_name": new_profile_name,
                "base_profile": base_profile,
                "editor_dir": "",
                "project_dir": "",
                "error": f"Source directory not found: {source_path}"
            }

        # 2. 기존 create_reused_profile() 호출
        reuse_result = create_reused_profile(base_profile, new_profile_name, port)

        if not reuse_result.get("success"):
            return {
                "success": False,
                "profile_name": new_profile_name,
                "base_profile": base_profile,
                "editor_dir": "",
                "project_dir": "",
                "error": reuse_result.get("error", "Failed to create reused profile")
            }

        # 3. base_profile 필드 설정 (editor_config.json)
        base_dir = os.path.dirname(os.path.dirname(__file__))  # mcp_editor/
        config_path = os.path.join(base_dir, "editor_config.json")

        with open(config_path, encoding='utf-8') as f:
            editor_config = json.load(f)

        if new_profile_name in editor_config:
            editor_config[new_profile_name]["base_profile"] = base_profile

        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(editor_config, f, indent=2, ensure_ascii=False)

        # 4. base 프로필의 derived_profiles에 추가
        config.update_derived_profiles_list(base_profile, new_profile_name, add=True)

        # 5. is_base 플래그 설정 (이미 update_derived_profiles_list에서 처리됨)
        # config.update_derived_profiles_list는 내부적으로 is_base=True를 설정함

        return {
            "success": True,
            "profile_name": new_profile_name,
            "base_profile": base_profile,
            "editor_dir": reuse_result.get("editor_dir", f"mcp_editor/mcp_{new_profile_name}"),
            "project_dir": reuse_result.get("project_dir", "")
        }

    except Exception as e:
        return {
            "success": False,
            "profile_name": new_profile_name,
            "base_profile": base_profile,
            "editor_dir": "",
            "project_dir": "",
            "error": str(e)
        }


def update_base_derived_relationship(base_profile: str, derived_profile: str) -> bool:
    """
    Update the base-derived relationship between profiles.

    - base 프로필에 derived_profiles 추가
    - base 프로필에 is_base=True 설정

    Args:
        base_profile: Base profile name (e.g., "outlook")
        derived_profile: Derived profile name (e.g., "outlook_read")

    Returns:
        bool: True if successful, False otherwise

    Terminology:
        - profile_key: `mcp_{server_name}` 형식
        - 모듈 디렉토리: `mcp_{server_name}/`
    """
    try:
        base_dir = os.path.dirname(os.path.dirname(__file__))  # mcp_editor/
        config_path = os.path.join(base_dir, "editor_config.json")

        # Load current config
        with open(config_path, encoding='utf-8') as f:
            editor_config = json.load(f)

        # Validate base_profile exists
        if base_profile not in editor_config:
            return False

        # Update base profile with is_base flag
        editor_config[base_profile]["is_base"] = True

        # Add derived_profile to derived_profiles list
        derived_list = editor_config[base_profile].get("derived_profiles", [])
        if derived_profile not in derived_list:
            derived_list.append(derived_profile)
        editor_config[base_profile]["derived_profiles"] = derived_list

        # Save updated config
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(editor_config, f, indent=2, ensure_ascii=False)

        return True

    except Exception as e:
        print(f"Error updating base-derived relationship: {e}")
        return False


def remove_from_derived_list(base_profile: str, derived_profile: str) -> bool:
    """
    Remove a derived profile from the base profile's derived_profiles list.

    Used when deleting a derived profile to maintain consistency.

    Args:
        base_profile: Base profile name (e.g., "outlook")
        derived_profile: Derived profile name to remove (e.g., "outlook_read")

    Returns:
        bool: True if successful, False otherwise

    Terminology:
        - profile_key: `mcp_{server_name}` 형식
        - 모듈 디렉토리: `mcp_{server_name}/`
    """
    try:
        # Use config module's helper function for consistency
        return config.update_derived_profiles_list(base_profile, derived_profile, add=False)

    except Exception as e:
        print(f"Error removing from derived list: {e}")
        return False


def delete_mcp_server_only(profile_name: str) -> dict:
    """
    Delete MCP server-related files only, keeping service code intact.

    This function deletes:
    - mcp_editor/mcp_{profile}/ folder (web editor definitions)
    - mcp_{profile}/mcp_server/ folder (generated server code)
    - mcp_editor/service_registry/registry_{profile}.json
    - Profile entry from editor_config.json

    This function KEEPS:
    - mcp_{profile}/{profile}_service.py (business logic)
    - mcp_{profile}/{profile}_types.py (type definitions)
    - mcp_{profile}/ folder itself (only mcp_server subfolder deleted)

    Args:
        profile_name: Profile name (e.g., "outlook_read")

    Returns:
        {
            "success": bool,
            "deleted_paths": list,
            "kept_paths": list,
            "error": str (on failure)
        }

    Example:
        >>> delete_mcp_server_only("outlook_read")
        {
            "success": True,
            "deleted_paths": [
                "mcp_editor/mcp_outlook_read/",
                "mcp_outlook_read/mcp_server/",
                "registry_outlook_read.json",
                "editor_config.json:outlook_read"
            ],
            "kept_paths": [
                "mcp_outlook_read/outlook_read_service.py"
            ]
        }
    """
    try:
        deleted_paths = []
        kept_paths = []
        base_dir = os.path.dirname(os.path.dirname(__file__))  # mcp_editor/
        root_dir = os.path.dirname(base_dir)   # /home/kimghw/Connector_auth/

        # 1. Delete editor profile folder (mcp_editor/mcp_{profile}/)
        editor_dir = os.path.join(base_dir, f"mcp_{profile_name}")
        if os.path.exists(editor_dir):
            shutil.rmtree(editor_dir)
            deleted_paths.append(f"mcp_editor/mcp_{profile_name}/")

        # 2. Delete only mcp_server folder inside project (NOT the entire project)
        project_dir = os.path.join(root_dir, f"mcp_{profile_name}")
        mcp_server_dir = os.path.join(project_dir, "mcp_server")

        if os.path.exists(mcp_server_dir):
            shutil.rmtree(mcp_server_dir)
            deleted_paths.append(f"mcp_{profile_name}/mcp_server/")

        # Record kept service files
        if os.path.exists(project_dir):
            service_file = os.path.join(project_dir, f"{profile_name}_service.py")
            types_file = os.path.join(project_dir, f"{profile_name}_types.py")

            if os.path.exists(service_file):
                kept_paths.append(f"mcp_{profile_name}/{profile_name}_service.py")
            if os.path.exists(types_file):
                kept_paths.append(f"mcp_{profile_name}/{profile_name}_types.py")

            # List other kept files
            for item in os.listdir(project_dir):
                item_path = os.path.join(project_dir, item)
                if os.path.isfile(item_path) and item not in [f"{profile_name}_service.py", f"{profile_name}_types.py"]:
                    kept_paths.append(f"mcp_{profile_name}/{item}")

        # 3. Delete registry file (mcp_editor/mcp_{profile}/registry_{profile}.json)
        profile_registry_dir = os.path.join(base_dir, f"mcp_{profile_name}")
        registry_file = os.path.join(profile_registry_dir, f"registry_{profile_name}.json")

        if os.path.exists(registry_file):
            os.remove(registry_file)
            deleted_paths.append(f"mcp_{profile_name}/registry_{profile_name}.json")

        # 4. Delete types_property_{profile}.json file
        types_property_file = os.path.join(profile_registry_dir, f"types_property_{profile_name}.json")

        if os.path.exists(types_property_file):
            os.remove(types_property_file)
            deleted_paths.append(f"mcp_{profile_name}/types_property_{profile_name}.json")

        # 5. Remove from editor_config.json
        config_path = os.path.join(base_dir, "editor_config.json")

        if os.path.exists(config_path):
            with open(config_path, encoding='utf-8') as f:
                editor_config = json.load(f)

            if profile_name in editor_config:
                # Check if this profile has a base_profile (is derived)
                base_profile = editor_config[profile_name].get("base_profile")

                # Delete the profile entry
                del editor_config[profile_name]

                # Update base profile's derived_profiles list if applicable
                if base_profile and base_profile in editor_config:
                    derived_list = editor_config[base_profile].get("derived_profiles", [])
                    if profile_name in derived_list:
                        derived_list.remove(profile_name)
                        editor_config[base_profile]["derived_profiles"] = derived_list

                        # If no more derived profiles, remove is_base flag
                        if not derived_list:
                            editor_config[base_profile].pop("is_base", None)
                            editor_config[base_profile].pop("derived_profiles", None)

                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(editor_config, f, indent=2, ensure_ascii=False)

                deleted_paths.append(f"editor_config.json:{profile_name}")

        return {
            "success": True,
            "deleted_paths": deleted_paths,
            "kept_paths": kept_paths
        }

    except Exception as e:
        return {
            "success": False,
            "deleted_paths": [],
            "kept_paths": [],
            "error": str(e)
        }