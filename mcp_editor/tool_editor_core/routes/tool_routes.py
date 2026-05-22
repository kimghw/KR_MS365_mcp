"""
Tool Definition Routes

도구 정의 CRUD API 엔드포인트:
- GET /api/tools
- POST /api/tools
- DELETE /api/tools/<int>
- POST /api/tools/validate
- POST /api/tools/save-all

도구 이동/복사 API 엔드포인트:
- POST /api/tools/move
- POST /api/tools/validate-move
- GET /api/tools/movable
"""

from datetime import datetime
from flask import request, jsonify
import shutil

from . import tool_bp
from ..config import (
    get_profile_config,
    resolve_paths,
    ensure_dirs,
    list_profile_names,
)
from ..tool_loader import (
    load_tool_definitions,
    extract_service_factors,
    get_file_mtimes,
)
from ..tool_saver import save_tool_definitions
from ..backup_utils import backup_file, cleanup_old_backups
from ..schema_utils import prune_internal_properties
from ..tool_mover import ToolMover


@tool_bp.route("/api/tools", methods=["GET"])
def get_tools():
    """API endpoint to get current tool definitions + internal args + signature defaults"""
    profile = request.args.get("profile")
    profile_conf = get_profile_config(profile)
    paths = resolve_paths(profile_conf)

    # 1. Load tool definitions (templates)
    tools = load_tool_definitions(paths)
    if isinstance(tools, dict) and "error" in tools:
        return jsonify(tools), 500

    # 2. Extract internal_args and signature_defaults from mcp_service_factors
    # (단순화: 중간 JSON 파일 없이 tool_definition_templates.py에서 직접 추출)
    internal_args, signature_defaults = extract_service_factors(tools)

    # 3. Collect file mtimes for conflict detection
    file_mtimes = get_file_mtimes(paths)

    actual_profile = profile or list_profile_names()[0] if list_profile_names() else "default"
    return jsonify(
        {
            "tools": tools,
            "internal_args": internal_args,
            "signature_defaults": signature_defaults,
            "profile": actual_profile,
            "file_mtimes": file_mtimes,
        }
    )


@tool_bp.route("/api/tools", methods=["POST"])
def save_tools():
    """API endpoint to save tool definitions"""
    try:
        profile = request.args.get("profile")
        profile_conf = get_profile_config(profile)
        paths = resolve_paths(profile_conf)
        tools_data = request.json
        force_rescan = str(request.args.get("force_rescan", "")).lower() in ("1", "true", "yes")
        result = save_tool_definitions(tools_data, paths, force_rescan=force_rescan)
        if "error" in result:
            return jsonify(result), 500
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@tool_bp.route("/api/tools/<int:tool_index>", methods=["DELETE"])
def delete_tool(tool_index):
    """Delete a specific tool by index"""
    try:
        profile = request.args.get("profile")
        profile_conf = get_profile_config(profile)
        paths = resolve_paths(profile_conf)
        # Load current tools
        tools = load_tool_definitions(paths)
        if isinstance(tools, dict) and "error" in tools:
            return jsonify(tools), 500

        if tool_index >= len(tools) or tool_index < 0:
            return jsonify({"error": "Invalid tool index"}), 400

        # Get the tool name for response
        deleted_tool = tools[tool_index]
        tool_name = deleted_tool.get("name", f"Tool {tool_index}")

        # Remove the tool
        tools.pop(tool_index)

        # Save the updated tools
        # mcp_service_factors는 도구 내부에 저장되므로 도구 삭제 시 자동 정리됨
        force_rescan = str(request.args.get("force_rescan", "")).lower() in ("1", "true", "yes")
        result = save_tool_definitions(tools, paths, force_rescan=force_rescan)
        if "error" in result:
            return jsonify(result), 500

        return jsonify(
            {
                "success": True,
                "message": f"Tool '{tool_name}' deleted successfully",
                "backup": result.get("backup"),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@tool_bp.route("/api/tools/validate", methods=["POST"])
def validate_tools():
    """Validate tool definitions"""
    try:
        tools_data = request.json

        # Basic validation
        if not isinstance(tools_data, list):
            return jsonify({"valid": False, "error": "Tools must be a list"}), 400

        for i, tool in enumerate(tools_data):
            if not isinstance(tool, dict):
                return jsonify({"valid": False, "error": f"Tool {i} must be a dictionary"}), 400

            # Check required fields
            if "name" not in tool:
                return jsonify({"valid": False, "error": f"Tool {i} missing 'name' field"}), 400
            if "description" not in tool:
                return jsonify({"valid": False, "error": f"Tool {i} missing 'description' field"}), 400
            if "inputSchema" not in tool:
                return jsonify({"valid": False, "error": f"Tool {i} missing 'inputSchema' field"}), 400

            # Validate inputSchema structure
            schema = tool.get("inputSchema", {})
            if not isinstance(schema, dict):
                return jsonify({"valid": False, "error": f"Tool {i} inputSchema must be a dictionary"}), 400
            if "type" not in schema or schema["type"] != "object":
                return jsonify({"valid": False, "error": f"Tool {i} inputSchema type must be 'object'"}), 400
            if "properties" not in schema:
                return jsonify({"valid": False, "error": f"Tool {i} inputSchema missing 'properties'"}), 400

        return jsonify({"valid": True})
    except Exception as e:
        return jsonify({"valid": False, "error": str(e)}), 500


@tool_bp.route("/api/tools/save-all", methods=["POST"])
def save_all_definitions():
    """
    Atomic save: tool_definitions.py + tool_definition_templates.py (with mcp_service_factors)
    단순화: 중간 JSON 파일 없이 mcp_service_factors에 직접 저장
    """
    try:
        profile = request.args.get("profile")
        profile_conf = get_profile_config(profile)
        paths = resolve_paths(profile_conf)
        ensure_dirs(paths)

        data = request.json
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a JSON object"}), 400

        tools_data = data.get("tools")
        internal_args = data.get("internal_args", {})
        signature_defaults = data.get("signature_defaults", {})
        loaded_mtimes = data.get("file_mtimes")

        # Debug logging
        print(f"\n[DEBUG] /api/tools/save-all called for profile: {profile}")
        print(f"[DEBUG] Received {len(tools_data) if tools_data else 0} tools")
        print(f"[DEBUG] Received internal_args: {len(internal_args)} tools")
        print(f"[DEBUG] Received signature_defaults: {len(signature_defaults)} tools")

        # Debug mail_list_period internal args
        if "mail_list_period" in internal_args:
            import json
            print(f"\n[DEBUG] mail_list_period internal_args:")
            print(json.dumps(internal_args["mail_list_period"], indent=2, ensure_ascii=False))

        if not tools_data or not isinstance(tools_data, list):
            return jsonify({"error": "tools must be a list"}), 400

        # Clean up orphaned internal_args
        tool_names = {tool.get("name") for tool in tools_data if tool.get("name")}
        orphaned_tools = [t for t in internal_args.keys() if t not in tool_names]
        for orphaned in orphaned_tools:
            del internal_args[orphaned]

        # Validate internal_args structure
        validation_errors = []
        for tool_name, tool_args in internal_args.items():
            for arg_name, arg_info in tool_args.items():
                if not isinstance(arg_info, dict):
                    validation_errors.append(f"{tool_name}.{arg_name}: must be an object")
                elif not arg_info.get("type"):
                    validation_errors.append(f"{tool_name}.{arg_name}: missing required 'type' field")

        if validation_errors:
            return (
                jsonify(
                    {
                        "error": "Invalid internal_args",
                        "validation_errors": validation_errors,
                        "action": "fix_required",
                        "message": "Each internal arg must have a 'type' field (e.g., SelectParams, FilterParams)",
                    }
                ),
                400,
            )

        # Strip any properties that are marked as internal before saving
        tools_data = prune_internal_properties(tools_data, internal_args)

        # Check for file conflicts
        if loaded_mtimes:
            current_mtimes = get_file_mtimes(paths)
            conflicts = []
            for key in ["definitions"]:  # Only check definitions (templates are auto-generated)
                if key in loaded_mtimes and key in current_mtimes:
                    if abs(current_mtimes[key] - loaded_mtimes[key]) > 5:
                        conflicts.append(key)
            if conflicts:
                return (
                    jsonify(
                        {
                            "error": "File conflict detected",
                            "conflicts": conflicts,
                            "action": "reload_required",
                            "message": "Files were modified externally. Please reload before saving.",
                        }
                    ),
                    409,
                )

        # Create backups
        backup_dir = paths.get("backup_dir")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backups = {
            "definitions": backup_file(paths.get("tool_path"), backup_dir, timestamp),
            "templates": backup_file(paths.get("template_path"), backup_dir, timestamp),
        }

        saved_files = []
        try:
            # Save tool_definitions.py and templates (with mcp_service_factors)
            # internal_args와 signature_defaults는 mcp_service_factors에 직접 병합됨
            force_rescan = str(request.args.get("force_rescan", "")).lower() in ("1", "true", "yes")
            result = save_tool_definitions(
                tools_data,
                paths,
                force_rescan=force_rescan,
                skip_backup=True,
                internal_args=internal_args,
                signature_defaults=signature_defaults,
            )
            if "error" in result:
                raise Exception(result["error"])
            saved_files.extend(["definitions", "templates"])

            cleanup_old_backups(backup_dir, keep_count=10)

            return jsonify(
                {
                    "success": True,
                    "saved": saved_files,
                    "backups": backups,
                    "timestamp": timestamp,
                    "profile": profile or list_profile_names()[0] if list_profile_names() else "default",
                }
            )

        except Exception as e:
            # Rollback: restore from backups
            for key, backup_path in backups.items():
                if backup_path and os.path.exists(backup_path):
                    target_key = {"definitions": "tool_path", "templates": "template_path"}.get(key)
                    if target_key and paths.get(target_key):
                        try:
                            shutil.copy2(backup_path, paths[target_key])
                        except Exception as restore_error:
                            print(f"Warning: Could not restore {key}: {restore_error}")

            return jsonify({"error": str(e), "rolled_back": saved_files, "action": "all_files_restored"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Deprecated endpoints for backward compatibility
@tool_bp.route("/api/internal-args", methods=["GET"])
def get_internal_args():
    """Get internal args for the current profile (DEPRECATED: use GET /api/tools instead)"""
    try:
        profile = request.args.get("profile")
        profile_conf = get_profile_config(profile)
        paths = resolve_paths(profile_conf)

        # Load tools and extract internal_args from mcp_service_factors
        tools = load_tool_definitions(paths)
        if isinstance(tools, dict) and "error" in tools:
            return jsonify(tools), 500

        internal_args, _ = extract_service_factors(tools)
        return jsonify(
            {
                "internal_args": internal_args,
                "profile": profile or list_profile_names()[0] if list_profile_names() else "default",
                "deprecated": "Use GET /api/tools instead",
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@tool_bp.route("/api/internal-args", methods=["POST"])
def post_internal_args():
    """DEPRECATED: Use POST /api/tools/save-all instead"""
    return jsonify({
        "error": "This endpoint is deprecated",
        "message": "Use POST /api/tools/save-all to save internal_args along with tools"
    }), 410


@tool_bp.route("/api/internal-args/<tool_name>", methods=["PUT"])
def put_internal_args_tool(tool_name: str):
    """DEPRECATED: Use POST /api/tools/save-all instead"""
    return jsonify({
        "error": "This endpoint is deprecated",
        "message": "Use POST /api/tools/save-all to save internal_args along with tools"
    }), 410


# Import os for shutil.copy2 in rollback
import os


# =============================================================================
# Tool Move/Copy API Endpoints
# =============================================================================

@tool_bp.route("/api/tools/move", methods=["POST"])
def move_tools_api():
    """
    도구 이동/복사 API

    Request:
    {
        "source_profile": "outlook",
        "target_profile": "outlook_read",
        "tool_indices": [0, 2, 5],
        "mode": "move"  // 또는 "copy"
    }

    Response:
    {
        "success": true,
        "moved_tools": ["mail_list", "mail_read", "mail_search"],
        "source_count": 7,   // 이동 후 소스 도구 수
        "target_count": 5    // 이동 후 타겟 도구 수
    }
    """
    try:
        data = request.json
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a JSON object"}), 400

        source_profile = data.get("source_profile")
        target_profile = data.get("target_profile")
        tool_indices = data.get("tool_indices", [])
        mode = data.get("mode", "move")

        # 필수 파라미터 검증
        if not source_profile:
            return jsonify({"error": "source_profile is required"}), 400
        if not target_profile:
            return jsonify({"error": "target_profile is required"}), 400
        if not tool_indices or not isinstance(tool_indices, list):
            return jsonify({"error": "tool_indices must be a non-empty list"}), 400
        if mode not in ("move", "copy"):
            return jsonify({"error": "mode must be 'move' or 'copy'"}), 400

        # ToolMover 인스턴스 생성 및 이동 수행
        mover = ToolMover()
        result = mover.move_tools(
            source_profile=source_profile,
            target_profile=target_profile,
            tool_indices=tool_indices,
            mode=mode
        )

        if not result["success"]:
            return jsonify({
                "success": False,
                "error": result.get("error", "Unknown error occurred")
            }), 400

        # 이동 후 도구 수 조회
        try:
            source_data = mover._load_yaml(source_profile)
            source_count = len(source_data.get("tools", []))
        except FileNotFoundError:
            source_count = 0
        except Exception:
            source_count = -1

        try:
            target_data = mover._load_yaml(target_profile)
            target_count = len(target_data.get("tools", []))
        except FileNotFoundError:
            target_count = 0
        except Exception:
            target_count = -1

        return jsonify({
            "success": True,
            "moved_tools": result.get("moved_tools", []),
            "source_count": source_count,
            "target_count": target_count,
            "source_backup": result.get("source_backup"),
            "target_backup": result.get("target_backup")
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@tool_bp.route("/api/tools/validate-move", methods=["POST"])
def validate_move_api():
    """
    이동 가능 여부 사전 검증 API

    Request:
    {
        "source_profile": "outlook",
        "target_profile": "outlook_read",
        "tool_indices": [0, 2, 5]
    }

    Response:
    {
        "valid": true,
        "movable": [0, 2, 5],
        "warnings": ["도구 'mail_list'가 타겟에 이미 존재합니다. 이름이 변경됩니다."]
    }
    """
    try:
        data = request.json
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a JSON object"}), 400

        source_profile = data.get("source_profile")
        target_profile = data.get("target_profile")
        tool_indices = data.get("tool_indices", [])

        # 필수 파라미터 검증
        if not source_profile:
            return jsonify({"error": "source_profile is required"}), 400
        if not target_profile:
            return jsonify({"error": "target_profile is required"}), 400
        if not tool_indices or not isinstance(tool_indices, list):
            return jsonify({"error": "tool_indices must be a non-empty list"}), 400

        # ToolMover 인스턴스 생성 및 검증 수행
        mover = ToolMover()
        validation_result = mover.validate_move(
            source_profile=source_profile,
            target_profile=target_profile,
            tool_indices=tool_indices
        )

        # 이동 가능한 인덱스 필터링 (검증 통과 시 모든 인덱스가 이동 가능)
        movable = tool_indices if validation_result["valid"] else []

        return jsonify({
            "valid": validation_result["valid"],
            "movable": movable,
            "errors": validation_result.get("errors", []),
            "warnings": validation_result.get("warnings", [])
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@tool_bp.route("/api/tools/movable", methods=["GET"])
def get_movable_tools_api():
    """
    이동 가능한 도구 목록 조회 API

    Query params:
    - source: 소스 프로필
    - target: 타겟 프로필

    Response:
    {
        "tools": [
            {"index": 0, "name": "mail_list", "can_move": true},
            {"index": 1, "name": "mail_send", "can_move": true}
        ]
    }
    """
    try:
        source_profile = request.args.get("source")
        target_profile = request.args.get("target")

        # 필수 파라미터 검증
        if not source_profile:
            return jsonify({"error": "source query parameter is required"}), 400
        if not target_profile:
            return jsonify({"error": "target query parameter is required"}), 400

        # ToolMover 인스턴스 생성 및 이동 가능 도구 조회
        mover = ToolMover()
        movable_tools = mover.get_movable_tools(
            source_profile=source_profile,
            target_profile=target_profile
        )

        # 에러 체크
        if movable_tools and isinstance(movable_tools[0], dict) and "error" in movable_tools[0]:
            return jsonify({"error": movable_tools[0]["error"]}), 500

        # 응답 형식으로 변환 (간소화된 버전)
        tools_response = []
        for tool in movable_tools:
            tools_response.append({
                "index": tool.get("index"),
                "name": tool.get("name"),
                "description": tool.get("description", ""),
                "mcp_service": tool.get("mcp_service", ""),
                "can_move": tool.get("can_move", False),
                "reason": tool.get("reason"),
                "duplicate_warning": tool.get("duplicate_warning")
            })

        return jsonify({"tools": tools_response})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
