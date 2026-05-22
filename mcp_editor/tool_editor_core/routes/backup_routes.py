"""
Backup Routes

백업 관리 API 엔드포인트:
- GET /api/backups
- GET /api/backups/<filename>
- POST /api/backups/<filename>/restore
"""

import os
import shutil
import importlib.util
from datetime import datetime
from flask import request, jsonify

from . import backup_bp
from ..config import get_profile_config, resolve_paths, ensure_dirs


@backup_bp.route("/api/backups", methods=["GET"])
def list_backups():
    """List available backups"""
    try:
        profile = request.args.get("profile")
        profile_conf = get_profile_config(profile)
        paths = resolve_paths(profile_conf)
        ensure_dirs(paths)
        backups = []
        for filename in os.listdir(paths["backup_dir"]):
            if filename.startswith("tool_definitions_") and filename.endswith(".py"):
                file_path = os.path.join(paths["backup_dir"], filename)
                stat = os.stat(file_path)
                backups.append(
                    {
                        "filename": filename,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    }
                )
        backups.sort(key=lambda x: x["modified"], reverse=True)
        return jsonify(backups)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@backup_bp.route("/api/backups/<filename>", methods=["GET"])
def get_backup(filename):
    """Get a specific backup file"""
    try:
        # Security check - ensure filename is safe
        if ".." in filename or "/" in filename or "\\" in filename:
            return jsonify({"error": "Invalid filename"}), 400

        profile = request.args.get("profile")
        profile_conf = get_profile_config(profile)
        paths = resolve_paths(profile_conf)

        file_path = os.path.join(paths["backup_dir"], filename)
        if not os.path.exists(file_path):
            return jsonify({"error": "Backup not found"}), 404

        spec = importlib.util.spec_from_file_location("backup", file_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return jsonify(module.MCP_TOOLS)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@backup_bp.route("/api/backups/<filename>/restore", methods=["POST"])
def restore_backup(filename):
    """Restore from a backup"""
    try:
        # Security check
        if ".." in filename or "/" in filename or "\\" in filename:
            return jsonify({"error": "Invalid filename"}), 400

        profile = request.args.get("profile")
        profile_conf = get_profile_config(profile)
        paths = resolve_paths(profile_conf)
        ensure_dirs(paths)

        backup_path = os.path.join(paths["backup_dir"], filename)
        if not os.path.exists(backup_path):
            return jsonify({"error": "Backup not found"}), 404

        # Create a backup of current state before restoring
        current_backup = f"tool_definitions_before_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py"
        if os.path.exists(paths["tool_path"]):
            shutil.copy2(paths["tool_path"], os.path.join(paths["backup_dir"], current_backup))

        # Restore the backup
        shutil.copy2(backup_path, paths["tool_path"])

        return jsonify({"success": True, "current_backup": current_backup})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
