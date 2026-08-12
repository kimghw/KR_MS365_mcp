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
from ..safe_paths import (
    PathNotAllowedError,
    resolve_request_path,
    path_error_payload,
)


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

        # Security: 허용 루트(기본 프로젝트 루트) 안인지 검사.
        # 기존 startswith 비교는 심볼릭 링크와 형제 디렉터리(예: <root>_backup)를 걸러내지 못했다.
        abs_root = os.path.abspath(ROOT_DIR)
        try:
            abs_path = str(resolve_request_path(path, base=abs_root))
        except PathNotAllowedError as e:
            return jsonify(path_error_payload(e, "path")), 403

        if not os.path.exists(abs_path) or os.path.isfile(abs_path):
            # 존재하지 않거나 파일이면 상위 디렉터리를 탐색 (상위도 허용 루트 안이어야 함)
            try:
                abs_path = str(resolve_request_path(os.path.dirname(abs_path), base=abs_root))
            except PathNotAllowedError as e:
                return jsonify(path_error_payload(e, "path")), 403

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
