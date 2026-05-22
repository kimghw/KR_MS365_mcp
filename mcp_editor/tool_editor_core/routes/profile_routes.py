"""
Profile Routes

프로필 관리 API 엔드포인트:
- GET /api/profiles
- POST /api/profiles
- GET /api/available-services
- POST /api/create-mcp-project-reuse
- DELETE /api/delete-mcp-profile
- POST /api/profiles/derive (파생 프로필 생성)
- GET /api/profiles/<profile>/siblings (형제 프로필 목록)
- GET /api/profiles/<profile>/family (가족 관계 조회)
"""

import os
import sys
import json
import subprocess
from flask import request, jsonify

from . import profile_bp
from ..config import (
    BASE_DIR,
    ROOT_DIR,
    get_profile_config,
    resolve_paths,
    list_profile_names,
    _load_config_file,
    _resolve_path,
    get_sibling_profiles,
    get_profile_family,
    is_base_profile,
    get_base_profile,
    get_source_path_for_profile,
)
from ..profile_management import (
    create_reused_profile,
    delete_mcp_profile,
    create_derived_profile,
    delete_mcp_server_only,
)


# Global profiles list (refreshed on changes)
profiles = list_profile_names()


@profile_bp.route("/api/profiles", methods=["GET"])
def get_profiles():
    """List available profiles from editor_config.json with source info"""
    try:
        profiles = list_profile_names()
        active = (
            request.args.get("profile")
            or os.environ.get("MCP_EDITOR_MODULE")
            or (profiles[0] if profiles else "default")
        )

        # Load full config to get profile details
        config = _load_config_file()
        profile_details = {}
        for profile_name in profiles:
            profile_conf = config.get(profile_name, {})
            # 컨벤션 기반으로 base_mcp 결정
            base_mcp = f"mcp_{profile_name}"
            profile_details[profile_name] = {
                "base_mcp": base_mcp,
                "is_reused": profile_conf.get("is_reused", False),
                "base_profile": profile_conf.get("base_profile", ""),
            }

        return jsonify({
            "profiles": profiles,
            "active": active,
            "details": profile_details
        })
    except Exception as e:
        return jsonify({"error": str(e), "profiles": []}), 500


@profile_bp.route("/api/profiles", methods=["POST"])
def create_profile():
    """Create a new profile (project) with directory structure"""
    global profiles

    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        profile_name = data.get("name", "").strip().lower().replace(" ", "_")
        if not profile_name:
            return jsonify({"error": "Profile name is required"}), 400

        # Check if profile already exists
        existing = list_profile_names()
        if profile_name in existing:
            return jsonify({"error": f"Profile '{profile_name}' already exists"}), 400

        # Get paths from request or generate defaults
        mcp_server_path = data.get("mcp_server_path", f"../mcp_{profile_name}/mcp_server")
        template_path = data.get("template_path", f"{profile_name}/tool_definition_templates.py")
        backup_dir = data.get("backup_dir", f"{profile_name}/backups")
        port = data.get("port", 8091)

        # Create MCP server directory structure if requested
        if data.get("create_mcp_structure", False):
            # Use create_mcp_project.py to create full scaffolding
            try:
                # Path to create_mcp_project.py
                # jinja is now inside mcp_editor (BASE_DIR/jinja)
                create_script_path = os.path.join(BASE_DIR, "jinja", "create_mcp_project.py")

                if os.path.exists(create_script_path):
                    # Run create_mcp_project.py
                    result = subprocess.run(
                        [
                            sys.executable,
                            create_script_path,
                            profile_name,
                            "--port",
                            str(port),
                            "--description",
                            f"MCP service for {profile_name}",
                            "--author",
                            "MCP Web Editor",
                        ],
                        capture_output=True,
                        text=True,
                        cwd=os.path.dirname(BASE_DIR),
                    )

                    if result.returncode != 0:
                        print(f"Warning: create_mcp_project.py failed: {result.stderr}")
                        # Fall back to simple structure creation
                        _create_minimal_structure(mcp_server_path)
                else:
                    print(f"create_mcp_project.py not found at {create_script_path}, using simple structure")
                    # Fall back to simple structure creation
                    _create_minimal_structure(mcp_server_path)
            except Exception as e:
                print(f"Error running create_mcp_project.py: {str(e)}")
                # Fall back to simple structure creation
                _create_minimal_structure(mcp_server_path)

        # Create profile config
        new_profile = {
            "template_definitions_path": template_path,
            "tool_definitions_path": f"{mcp_server_path}/tool_definitions.py",
            "backup_dir": backup_dir,
            "types_files": [],
            "host": "0.0.0.0",
            "port": port,
        }

        # Create directory structure in mcp_editor (for templates and backups)
        editor_profile_dir = os.path.join(BASE_DIR, profile_name)
        os.makedirs(editor_profile_dir, exist_ok=True)
        os.makedirs(os.path.join(editor_profile_dir, "backups"), exist_ok=True)

        # Create empty tool_definition_templates.py if not exists
        template_file_path = os.path.join(BASE_DIR, template_path)
        if not os.path.exists(template_file_path):
            with open(template_file_path, "w", encoding="utf-8") as f:
                f.write(
                    '''"""
MCP Tool Definition Templates - AUTO-GENERATED
Signatures extracted from source code using AST parsing
"""
from typing import List, Dict, Any

MCP_TOOLS: List[Dict[str, Any]] = []
'''
                )

        # Update editor_config.json
        config_path = os.path.join(BASE_DIR, "editor_config.json")
        config_data = _load_config_file()
        config_data[profile_name] = new_profile

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)

        # Reload profiles
        profiles = list_profile_names()

        return jsonify(
            {"success": True, "profile": profile_name, "config": new_profile, "created_dirs": [editor_profile_dir]}
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@profile_bp.route("/api/available-services", methods=["GET"])
def get_available_services():
    """Get list of available MCP services for reuse"""
    try:
        services = []
        profile_names = list_profile_names()

        for profile in profile_names:
            profile_conf = get_profile_config(profile)
            # 컨벤션 기반으로 소스 경로 확인
            source_path = get_source_path_for_profile(profile, profile_conf)

            # 실제 디렉토리가 존재하는 프로필만 포함
            if os.path.exists(source_path):
                services.append({
                    "name": profile,
                    "display_name": profile.replace("_", " ").title(),
                    "source_path": source_path
                })

        return jsonify({"services": services})
    except Exception as e:
        return jsonify({"error": str(e), "services": []}), 500


@profile_bp.route("/api/delete-mcp-profile", methods=["DELETE"])
def delete_mcp_profile_api():
    """Delete an MCP profile"""
    global profiles

    try:
        data = request.json or {}
        profile_name = data.get("profile_name", "").strip()

        if not profile_name:
            return jsonify({"error": "profile_name is required"}), 400

        # Prevent deletion of protected profiles
        protected_profiles = ["outlook", "calendar", "file_handler"]
        if profile_name in protected_profiles:
            return jsonify({"error": f"Cannot delete protected profile: {profile_name}"}), 403

        # Check if profile exists
        if profile_name not in list_profile_names():
            return jsonify({"error": f"Profile '{profile_name}' not found"}), 404

        result = delete_mcp_profile(profile_name)

        if not result.get("success"):
            return jsonify({"error": result.get("error", "Unknown error")}), 500

        # Reload profiles
        profiles = list_profile_names()

        return jsonify({
            "success": True,
            "message": f"Successfully deleted profile: {profile_name}",
            "deleted_paths": result.get("deleted_paths", [])
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@profile_bp.route("/api/create-mcp-project-reuse", methods=["POST"])
def create_mcp_project_reuse():
    """Create a new MCP profile by reusing existing service"""
    global profiles

    try:
        data = request.json or {}

        existing_service = data.get("existing_service", "").lower().strip()
        new_profile_name = data.get("new_profile_name", "").lower().strip()
        port = data.get("port", 8080)

        if not existing_service or not new_profile_name:
            return jsonify({"error": "existing_service and new_profile_name are required"}), 400

        # Validate profile name
        if not new_profile_name.replace("_", "").isalnum():
            return jsonify({"error": "Profile name should only contain letters, numbers, and underscores"}), 400

        # Check duplicate profile
        if new_profile_name in list_profile_names():
            return jsonify({"error": f"Profile '{new_profile_name}' already exists"}), 400

        # Check existing service
        if existing_service not in list_profile_names():
            return jsonify({"error": f"Existing service '{existing_service}' not found"}), 400

        result = create_reused_profile(existing_service, new_profile_name, port)

        if not result.get("success"):
            return jsonify({"error": result.get("error", "Unknown error")}), 500

        # Reload profiles
        profiles = list_profile_names()

        return jsonify({
            "success": True,
            "profile_name": new_profile_name,
            "editor_dir": result["editor_dir"],
            "message": f"Successfully created reused profile: {new_profile_name}"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _create_minimal_structure(mcp_server_path: str):
    """Create minimal MCP server structure"""
    mcp_dir = _resolve_path(mcp_server_path)
    os.makedirs(mcp_dir, exist_ok=True)

    # Create minimal tool_definitions.py
    tool_def_path = os.path.join(mcp_dir, "tool_definitions.py")
    if not os.path.exists(tool_def_path):
        with open(tool_def_path, "w", encoding="utf-8") as f:
            f.write(
                '''"""
MCP Tool Definitions - AUTO-GENERATED FILE
"""
from typing import List, Dict, Any

MCP_TOOLS: List[Dict[str, Any]] = []


def get_tool_by_name(tool_name: str) -> Dict[str, Any] | None:
    for tool in MCP_TOOLS:
        if tool["name"] == tool_name:
            return tool
    return None


def get_tool_names() -> List[str]:
    return [tool["name"] for tool in MCP_TOOLS]
'''
            )


@profile_bp.route("/api/profiles/derive", methods=["POST"])
def derive_profile():
    """
    파생 프로필 생성 API

    Request:
    {
        "base_profile": "outlook",
        "new_profile_name": "outlook_read",
        "port": 8092,
        "description": "읽기 전용 Outlook 도구"  # 선택
    }

    Response:
    {
        "success": true,
        "profile": {
            "name": "outlook_read",
            "base_profile": "outlook",
            "editor_dir": "mcp_editor/mcp_outlook_read",
            "project_dir": "mcp_outlook_read"
        }
    }
    """
    global profiles

    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        base_profile = data.get("base_profile", "").strip().lower()
        new_profile_name = data.get("new_profile_name", "").strip().lower().replace(" ", "_")
        port = data.get("port", 8091)
        description = data.get("description", "")

        # Validate required fields
        if not base_profile:
            return jsonify({"error": "base_profile is required"}), 400
        if not new_profile_name:
            return jsonify({"error": "new_profile_name is required"}), 400

        # Validate profile name format
        if not new_profile_name.replace("_", "").isalnum():
            return jsonify({"error": "Profile name should only contain letters, numbers, and underscores"}), 400

        # Check if base profile exists
        if base_profile not in list_profile_names():
            return jsonify({"error": f"Base profile '{base_profile}' not found"}), 404

        # Check duplicate profile
        if new_profile_name in list_profile_names():
            return jsonify({"error": f"Profile '{new_profile_name}' already exists"}), 400

        # Create derived profile
        result = create_derived_profile(base_profile, new_profile_name, port)

        if not result.get("success"):
            return jsonify({"error": result.get("error", "Unknown error")}), 500

        # Reload profiles
        profiles = list_profile_names()

        return jsonify({
            "success": True,
            "profile": {
                "name": new_profile_name,
                "base_profile": base_profile,
                "editor_dir": result.get("editor_dir", f"mcp_editor/mcp_{new_profile_name}"),
                "project_dir": result.get("project_dir", f"mcp_{new_profile_name}")
            }
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@profile_bp.route("/api/profiles/<profile>/siblings", methods=["GET"])
def get_sibling_profiles_api(profile: str):
    """
    동일 base를 공유하는 형제 프로필 목록

    Response:
    {
        "profile": "outlook_read",
        "base_profile": "outlook",
        "siblings": ["outlook", "outlook_write"],
        "is_base": false
    }
    """
    try:
        # Check if profile exists
        if profile not in list_profile_names():
            return jsonify({"error": f"Profile '{profile}' not found"}), 404

        # Get sibling profiles
        siblings = get_sibling_profiles(profile)

        # Get base profile
        base = get_base_profile(profile) or profile

        # Check if current profile is base
        is_base = is_base_profile(profile)

        return jsonify({
            "profile": profile,
            "base_profile": base,
            "siblings": siblings,
            "is_base": is_base
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@profile_bp.route("/api/profiles/<profile>/family", methods=["GET"])
def get_profile_family_api(profile: str):
    """
    프로필의 전체 가족 관계 조회

    Response:
    {
        "base": "outlook",
        "derived": ["outlook_read", "outlook_write"],
        "current": "outlook_read",
        "is_base": false
    }
    """
    try:
        # Check if profile exists
        if profile not in list_profile_names():
            return jsonify({"error": f"Profile '{profile}' not found"}), 404

        # Get profile family
        family = get_profile_family(profile)

        return jsonify(family)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@profile_bp.route("/api/delete-mcp-server", methods=["DELETE"])
def delete_mcp_server_api():
    """
    Delete MCP server-related files only (keep service code).

    This is a safer deletion that preserves:
    - {profile}_service.py (business logic)
    - {profile}_types.py (type definitions)

    Request:
    {
        "profile_name": "outlook_read",
        "confirm": "DELETE outlook_read"  # Must match pattern: DELETE {profile_name}
    }

    Response:
    {
        "success": true,
        "message": "Successfully deleted MCP server: outlook_read",
        "deleted_paths": [...],
        "kept_paths": [...]
    }
    """
    global profiles

    try:
        data = request.json or {}
        profile_name = data.get("profile_name", "").strip()
        confirm = data.get("confirm", "").strip()

        if not profile_name:
            return jsonify({"error": "profile_name is required"}), 400

        # Validate confirmation text
        expected_confirm = f"DELETE {profile_name}"
        if confirm != expected_confirm:
            return jsonify({
                "error": f"Confirmation text must be exactly: {expected_confirm}",
                "expected": expected_confirm,
                "received": confirm
            }), 400

        # Prevent deletion of protected profiles
        protected_profiles = ["outlook", "calendar", "file_handler"]
        if profile_name in protected_profiles:
            return jsonify({
                "error": f"Cannot delete protected profile: {profile_name}",
                "hint": "Protected profiles are core system profiles"
            }), 403

        # Check if profile exists
        existing_profiles = list_profile_names()
        if profile_name not in existing_profiles:
            return jsonify({"error": f"Profile '{profile_name}' not found"}), 404

        # Execute deletion
        result = delete_mcp_server_only(profile_name)

        if not result.get("success"):
            return jsonify({"error": result.get("error", "Unknown error")}), 500

        # Reload profiles
        profiles = list_profile_names()

        return jsonify({
            "success": True,
            "message": f"Successfully deleted MCP server: {profile_name}",
            "deleted_paths": result.get("deleted_paths", []),
            "kept_paths": result.get("kept_paths", [])
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@profile_bp.route("/api/profiles/<profile>/info", methods=["GET"])
def get_profile_info_api(profile: str):
    """
    Get detailed profile information for deletion preview.

    Response:
    {
        "profile": "outlook_read",
        "exists": true,
        "is_protected": false,
        "paths": {
            "editor_dir": "mcp_editor/mcp_outlook_read/",
            "mcp_server_dir": "mcp_outlook_read/mcp_server/",
            "registry_file": "registry_outlook_read.json",
            "service_files": ["outlook_read_service.py", "outlook_read_types.py"]
        }
    }
    """
    try:
        # Check if protected
        protected_profiles = ["outlook", "calendar", "file_handler"]
        is_protected = profile in protected_profiles

        # Check if exists
        exists = profile in list_profile_names()

        # Build paths info
        paths = {
            "editor_dir": f"mcp_editor/mcp_{profile}/",
            "mcp_server_dir": f"mcp_{profile}/mcp_server/",
            "registry_file": f"registry_{profile}.json",
            "service_files": []
        }

        # Check for actual service files
        project_dir = os.path.join(ROOT_DIR, f"mcp_{profile}")
        if os.path.exists(project_dir):
            for filename in os.listdir(project_dir):
                if filename.endswith("_service.py") or filename.endswith("_types.py"):
                    paths["service_files"].append(filename)
                elif os.path.isfile(os.path.join(project_dir, filename)):
                    paths["service_files"].append(filename)

        return jsonify({
            "profile": profile,
            "exists": exists,
            "is_protected": is_protected,
            "paths": paths
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
