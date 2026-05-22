"""
Utility Routes

유틸리티 API 엔드포인트:
- GET / (메인 에디터)
- GET /docs (문서 뷰어)
- POST /api/browse-files
- GET /static/<path>
"""

import os
from flask import render_template, request, jsonify, send_from_directory

from . import utility_bp
from ..config import BASE_DIR, ROOT_DIR


@utility_bp.route("/")
def index():
    """Main editor page"""
    return render_template("tool_editor.html")


@utility_bp.route("/docs")
def docs_viewer():
    """Documentation viewer page - MCP 웹에디터 데이터 흐름 및 핸들러 처리 가이드"""
    return render_template("docs_viewer.html")


@utility_bp.route("/api/browse-files", methods=["POST"])
def browse_files():
    """Browse files in a directory for file selection"""
    try:
        data = request.json or {}
        path = data.get("path", ROOT_DIR)
        extension = data.get("extension", "")
        show_files = data.get("show_files", True)  # Default to showing files

        # Security: Ensure we're only browsing within the project root
        abs_path = os.path.abspath(path)
        abs_root = os.path.abspath(ROOT_DIR)

        if not abs_path.startswith(abs_root):
            return jsonify({"error": "Access denied: path outside project"}), 403

        if not os.path.exists(abs_path):
            # If path doesn't exist, use parent directory
            abs_path = os.path.dirname(abs_path)
        elif os.path.isfile(abs_path):
            # If a file path is provided, browse its parent directory
            abs_path = os.path.dirname(abs_path)

        # Build contents list for new format
        contents = []

        # List directory contents
        try:
            for item in sorted(os.listdir(abs_path)):
                item_path = os.path.join(abs_path, item)
                if os.path.isdir(item_path):
                    # Skip hidden directories and __pycache__
                    if not item.startswith(".") and item != "__pycache__":
                        contents.append({"name": item, "path": item_path, "type": "directory"})
                elif os.path.isfile(item_path) and show_files:
                    # Filter by extension if specified
                    if not extension or item.endswith(extension):
                        contents.append({"name": item, "path": item_path, "type": "file"})
        except PermissionError:
            return jsonify({"error": "Permission denied"}), 403

        result = {
            "current_path": abs_path,
            "parent_path": os.path.dirname(abs_path) if abs_path != abs_root else None,
            "contents": contents,
            # Keep old format for compatibility
            "dirs": [c["name"] for c in contents if c["type"] == "directory"],
            "files": [c["name"] for c in contents if c["type"] == "file"],
        }

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@utility_bp.route("/static/<path:path>")
def send_static(path):
    """Serve static files (CSS, JS)"""
    return send_from_directory(os.path.join(BASE_DIR, "static"), path)
