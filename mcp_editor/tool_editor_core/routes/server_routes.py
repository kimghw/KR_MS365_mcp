"""
Server Control Routes

MCP 서버 제어 API 엔드포인트:
- GET /api/server/status
- POST /api/server/start
- POST /api/server/stop
- POST /api/server/restart
- GET /api/server/logs
- GET /api/server/dashboard - 모든 프로필 상태 조회
- PUT /api/server/port - 서버 포트 변경
"""

import os
import json
from flask import request, jsonify

from . import server_bp
from ..config import ROOT_DIR, BASE_DIR, JINJA_DIR


@server_bp.route("/api/server/status", methods=["GET"])
def get_server_status():
    """Check if MCP server is running"""
    try:
        from mcp_server_controller import MCPServerManager

        profile = request.args.get("profile", "default")
        protocol = request.args.get("protocol", "stream")
        manager = MCPServerManager(profile, protocol)
        result = manager.status()

        return jsonify(result)
    except Exception as e:
        return jsonify({"running": False, "error": str(e)})


@server_bp.route("/api/server/start", methods=["POST"])
def start_server():
    """Start the MCP server"""
    try:
        from mcp_server_controller import MCPServerManager

        profile = request.args.get("profile", "default")
        protocol = request.args.get("protocol", "stream")
        manager = MCPServerManager(profile, protocol)
        result = manager.start()

        if result.get("success"):
            return jsonify(result)
        else:
            return jsonify(result), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@server_bp.route("/api/server/stop", methods=["POST"])
def stop_server():
    """Stop the MCP server"""
    try:
        from mcp_server_controller import MCPServerManager

        profile = request.args.get("profile", "default")
        protocol = request.args.get("protocol", "stream")
        force = request.json.get("force", False) if request.json else False
        manager = MCPServerManager(profile, protocol)
        result = manager.stop(force=force)

        if result.get("success"):
            return jsonify(result)
        else:
            return jsonify(result), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@server_bp.route("/api/server/restart", methods=["POST"])
def restart_server():
    """Restart the MCP server"""
    try:
        from mcp_server_controller import MCPServerManager

        profile = request.args.get("profile", "default")
        protocol = request.args.get("protocol", "stream")
        manager = MCPServerManager(profile, protocol)
        result = manager.restart()

        if result.get("success"):
            return jsonify(result)
        else:
            return jsonify(result), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@server_bp.route("/api/server/logs", methods=["GET"])
def get_server_logs():
    """Get MCP server logs"""
    try:
        from mcp_server_controller import MCPServerManager

        profile = request.args.get("profile", "default")
        protocol = request.args.get("protocol", "stream")
        lines = int(request.args.get("lines", 50))
        manager = MCPServerManager(profile, protocol)
        logs = manager.logs(lines=lines)

        return jsonify({"success": True, "logs": logs, "profile": profile, "protocol": protocol})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@server_bp.route("/api/server/dashboard", methods=["GET"])
def get_server_dashboard():
    """
    Get dashboard data for all server profiles.

    Returns:
    {
        "profiles": [
            {
                "profile": "outlook",
                "server_name": "mcp_outlook",
                "host": "0.0.0.0",
                "port": 8091,
                "protocols": {
                    "rest": {"running": true, "pid": 12345},
                    "stdio": {"running": false, "pid": null},
                    "stream": {"running": false, "pid": null}
                },
                "available_protocols": ["rest", "stdio", "stream"],
                "is_base": true,
                "derived_profiles": ["outlook_test"]
            },
            ...
        ]
    }
    """
    try:
        from mcp_server_controller import MCPServerManager

        config_path = os.path.join(BASE_DIR, "editor_config.json")
        if not os.path.exists(config_path):
            return jsonify({"profiles": [], "error": "editor_config.json not found"})

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        profiles_data = []
        for profile_name, profile_config in config.items():
            # 컨벤션 기반으로 server_name 결정
            server_name = f"mcp_{profile_name}"

            # Get available protocols and their status
            available_protocols = MCPServerManager.get_available_protocols(profile_name)
            protocols_status = {}
            any_running = False
            running_pids = []

            for protocol in ["rest", "stdio", "stream"]:
                if protocol in available_protocols:
                    manager = MCPServerManager(profile_name, protocol)
                    status = manager.status()
                    protocols_status[protocol] = {
                        "available": True,
                        "running": status.get("running", False),
                        "pid": status.get("pid")
                    }
                    if status.get("running"):
                        any_running = True
                        if status.get("pid"):
                            running_pids.append(status.get("pid"))
                else:
                    protocols_status[protocol] = {
                        "available": False,
                        "running": False,
                        "pid": None
                    }

            profile_data = {
                "profile": profile_name,
                "server_name": server_name,
                "host": profile_config.get("host", "0.0.0.0"),
                "port": profile_config.get("port", 8080),
                "running": any_running,  # True if any protocol is running
                "pids": running_pids,
                "protocols": protocols_status,
                "available_protocols": available_protocols,
                "is_base": profile_config.get("is_base", False),
                "is_reused": profile_config.get("is_reused", False),
                "base_profile": profile_config.get("base_profile"),
                "derived_profiles": profile_config.get("derived_profiles", [])
            }
            profiles_data.append(profile_data)

        return jsonify({"profiles": profiles_data})

    except Exception as e:
        return jsonify({"profiles": [], "error": str(e)}), 500


@server_bp.route("/api/server/port", methods=["PUT"])
def update_server_port():
    """
    Update server port for a profile.

    Request:
    {
        "profile": "outlook",
        "port": 8092
    }

    Response:
    {
        "success": true,
        "profile": "outlook",
        "old_port": 8091,
        "new_port": 8092
    }
    """
    try:
        data = request.json or {}
        profile_name = data.get("profile", "").strip()
        new_port = data.get("port")

        if not profile_name:
            return jsonify({"success": False, "error": "profile is required"}), 400

        if not new_port or not isinstance(new_port, int):
            return jsonify({"success": False, "error": "port must be a valid integer"}), 400

        if new_port < 1024 or new_port > 65535:
            return jsonify({"success": False, "error": "port must be between 1024 and 65535"}), 400

        config_path = os.path.join(BASE_DIR, "editor_config.json")
        if not os.path.exists(config_path):
            return jsonify({"success": False, "error": "editor_config.json not found"}), 404

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        if profile_name not in config:
            return jsonify({"success": False, "error": f"Profile '{profile_name}' not found"}), 404

        old_port = config[profile_name].get("port", 8080)
        config[profile_name]["port"] = new_port

        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        return jsonify({
            "success": True,
            "profile": profile_name,
            "old_port": old_port,
            "new_port": new_port
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@server_bp.route("/api/merge-servers", methods=["POST"])
def merge_servers():
    """
    Merge multiple MCP servers into a single server.

    Request:
    {
        "name": "merged_server",
        "sources": ["outlook", "calendar"],
        "port": 8090,
        "prefix_mode": "auto",  # auto, always, none
        "protocol": "all"       # all, sse, stdio, streamable_http
    }

    Response:
    {
        "success": true,
        "merged_name": "merged_server",
        "tool_count": 15,
        "service_count": 10,
        "types_count": 30
    }
    """
    try:
        import subprocess
        import sys

        data = request.json or {}
        name = data.get("name", "").strip()
        sources = data.get("sources", [])
        port = data.get("port", 8090)
        prefix_mode = data.get("prefix_mode", "auto")
        protocol = data.get("protocol", "all")

        # Validation
        if not name:
            return jsonify({"success": False, "error": "Merged server name is required"}), 400

        if len(sources) < 2:
            return jsonify({"success": False, "error": "At least 2 source profiles are required"}), 400

        # Build command
        sources_str = ",".join(sources)
        cmd = [
            sys.executable,
            os.path.join(JINJA_DIR, "generate_universal_server.py"),
            "merge",
            "--name", name,
            "--sources", sources_str,
            "--port", str(port),
            "--protocol", protocol,
            "--prefix-mode", prefix_mode
        ]

        print(f"Running merge command: {' '.join(cmd)}")

        # Run the merge command
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=ROOT_DIR
        )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown error"
            print(f"Merge failed: {error_msg}")
            return jsonify({"success": False, "error": error_msg}), 500

        # Parse output for counts
        output = result.stdout
        print(f"Merge output: {output}")

        # Try to extract counts from output
        tool_count = None
        service_count = None
        types_count = None

        for line in output.split('\n'):
            if 'tools' in line.lower() and 'merged' in line.lower():
                try:
                    import re
                    match = re.search(r'(\d+)\s*tools', line.lower())
                    if match:
                        tool_count = int(match.group(1))
                except:
                    pass
            if 'services' in line.lower():
                try:
                    import re
                    match = re.search(r'(\d+)\s*services', line.lower())
                    if match:
                        service_count = int(match.group(1))
                except:
                    pass
            if 'types' in line.lower():
                try:
                    import re
                    match = re.search(r'(\d+)\s*types', line.lower())
                    if match:
                        types_count = int(match.group(1))
                except:
                    pass

        return jsonify({
            "success": True,
            "merged_name": name,
            "tool_count": tool_count,
            "service_count": service_count,
            "types_count": types_count,
            "output": output
        })

    except Exception as e:
        print(f"Merge error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500
