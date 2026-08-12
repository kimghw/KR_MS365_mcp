#!/usr/bin/env python3
"""
MCP Server Manager
Manages MCP server processes with PID file tracking and process control
"""

import os
import sys
import json
import time
import psutil
import subprocess
from typing import Optional, Dict, List

# Get the root directory where all MCP modules are located
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PID_DIR = os.path.join(ROOT_DIR, ".mcp_pids")
LOG_DIR = os.path.join(ROOT_DIR, ".mcp_logs")

# Ensure directories exist
os.makedirs(PID_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)


# Supported protocol types
PROTOCOL_TYPES = ["rest", "stdio", "stream"]
PROTOCOL_SERVER_FILES = {
    "rest": "server_rest.py",
    "stdio": "server_stdio.py",
    "stream": "server_stream.py",
}
# 프로토콜 전용 파일이 없을 때만 시도하는 일반 서버 파일
FALLBACK_SERVER_FILES = ["server.py"]

CONFIG_PATH = os.path.join(ROOT_DIR, "mcp_editor", "editor_config.json")


def _load_editor_config() -> Dict:
    """editor_config.json 로드 (읽기 실패 시 빈 dict)"""
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, IOError, OSError):
        return {}


def _profile_base_path(profile: str) -> Optional[str]:
    """
    editor_config.json 에 등록된 프로필의 mcp_server 디렉터리를 반환.

    미등록 프로필이거나 tool_definitions_path 가 없으면 None.
    """
    profile_conf = _load_editor_config().get(profile)
    if not isinstance(profile_conf, dict):
        return None

    # tool_definitions_path 예: "../mcp_outlook/mcp_server/tool_definitions.py"
    tool_def_path = profile_conf.get("tool_definitions_path", "")
    if not tool_def_path:
        return None

    return os.path.normpath(
        os.path.dirname(os.path.join(ROOT_DIR, "mcp_editor", tool_def_path))
    )


class MCPServerManager:
    """Manages MCP server lifecycle with PID file tracking"""

    def __init__(self, profile: str = "default", protocol: str = "stream", port: Optional[int] = None):
        """
        Initialize server manager.

        Args:
            profile: Profile name (e.g., "outlook", "calendar")
            protocol: Server protocol type ("rest", "stdio", "stream")
            port: 포트 오버라이드. 없으면 editor_config.json 의 프로필 포트를 사용한다.
        """
        self.profile = profile
        self.protocol = protocol if protocol in PROTOCOL_TYPES else "stream"
        # Include protocol in PID/log file names for independent tracking
        self.pid_file = os.path.join(PID_DIR, f"{profile}_{self.protocol}_server.pid")
        self.log_file = os.path.join(LOG_DIR, f"{profile}_{self.protocol}_server.log")

        profile_conf = _load_editor_config().get(profile)
        self.profile_conf = profile_conf if isinstance(profile_conf, dict) else None
        self.registered = self.profile_conf is not None

        # 설정된 포트를 자식 프로세스에 MCP_SERVER_PORT 로 전달하기 위해 보관
        self.port = port
        if self.port is None and self.profile_conf:
            try:
                configured = self.profile_conf.get("port")
                self.port = int(configured) if configured is not None else None
            except (TypeError, ValueError):
                self.port = None

        self.server_path = self._get_server_path()

    def _get_server_path(self) -> Optional[str]:
        """
        Get the server path based on profile and protocol from editor_config.json.

        editor_config.json 에 등록된 프로필만 해석한다. 미등록 프로필은 None 을 반환한다.

        (구버전은 프로필명 부분 문자열 매칭 후, 그래도 못 찾으면 후보 목록의 첫 항목
         = mcp_outlook 서버로 폴백했다. 그 결과 teams/todo 처럼 editor_config.json 에
         없는 프로필이 조용히 Outlook 서버로 라우팅됐다. 잘못된 서버를 기동/중지하는 것보다
         명시적으로 실패하는 편이 안전하므로 폴백을 제거했다.)

        The protocol determines which server file to use:
        - rest: server_rest.py
        - stdio: server_stdio.py
        - stream: server_stream.py
        """
        base_path = _profile_base_path(self.profile)
        if not base_path:
            return None

        # Protocol-specific server file takes priority
        protocol_server_file = PROTOCOL_SERVER_FILES.get(self.protocol)
        if protocol_server_file:
            path = os.path.join(base_path, protocol_server_file)
            if os.path.exists(path):
                return path

        # Fallback to generic server files (같은 프로필 디렉터리 안에서만)
        for server_file in FALLBACK_SERVER_FILES:
            path = os.path.join(base_path, server_file)
            if os.path.exists(path):
                return path

        return None

    def _unresolved_reason(self) -> str:
        """server_path 를 못 찾은 이유를 사용자에게 설명 가능한 문장으로 만든다"""
        if not self.registered:
            known = ", ".join(sorted(_load_editor_config().keys())) or "(none)"
            return (
                f"Unknown profile '{self.profile}': not registered in mcp_editor/editor_config.json. "
                f"Registered profiles: {known}"
            )

        base_path = _profile_base_path(self.profile)
        if not base_path:
            return (
                f"Profile '{self.profile}' has no usable 'tool_definitions_path' "
                f"in mcp_editor/editor_config.json"
            )

        expected = PROTOCOL_SERVER_FILES.get(self.protocol, FALLBACK_SERVER_FILES[0])
        return (
            f"Server file not found for profile '{self.profile}' (protocol '{self.protocol}'): "
            f"expected {os.path.join(base_path, expected)}"
        )

    def _read_pid(self) -> Optional[int]:
        """Read PID from file"""
        if os.path.exists(self.pid_file):
            try:
                with open(self.pid_file, "r") as f:
                    return int(f.read().strip())
            except (ValueError, FileNotFoundError):
                return None
        return None

    def _write_pid(self, pid: int):
        """Write PID to file"""
        with open(self.pid_file, "w") as f:
            f.write(str(pid))

    def _remove_pid(self):
        """Remove PID file"""
        if os.path.exists(self.pid_file):
            os.remove(self.pid_file)

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process with given PID is running"""
        try:
            process = psutil.Process(pid)
            # Check if it's actually our Python server
            if process.is_running():
                cmdline = " ".join(process.cmdline())
                # Check for any server file (server.py, server_rest.py, server_stdio.py, server_stream.py)
                return "python" in process.name().lower() and ("server.py" in cmdline or "server_" in cmdline)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return False

    def _find_server_processes(self) -> List[Dict]:
        """Find server processes for this specific profile only"""
        processes = []

        # Only check managed process via PID file
        # This ensures each profile only tracks its own server
        pid = self._read_pid()
        if pid and self._is_process_running(pid):
            try:
                proc = psutil.Process(pid)
                cmdline = " ".join(proc.cmdline())

                # Verify this process matches our expected server path
                if self.server_path:
                    # Normalize paths for comparison
                    server_dir = os.path.dirname(self.server_path)
                    # Check if the cmdline contains our specific server directory
                    if server_dir in cmdline or os.path.basename(server_dir) in cmdline:
                        processes.append(
                            {"pid": pid, "cmd": cmdline, "managed": True, "profile": self.profile}
                        )
                    else:
                        # PID file exists but points to wrong process, clean up
                        self._remove_pid()
                else:
                    processes.append(
                        {"pid": pid, "cmd": cmdline, "managed": True, "profile": self.profile}
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                self._remove_pid()

        # If no managed process found, check for unmanaged processes with exact path match
        if not processes and self.server_path:
            server_path_normalized = os.path.normpath(self.server_path)

            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    if proc.info["cmdline"]:
                        cmdline = " ".join(proc.info["cmdline"])

                        # Check for exact server path match in cmdline
                        if "python" in proc.info["name"].lower():
                            # Check if this process is running our specific server file
                            if server_path_normalized in cmdline:
                                processes.append(
                                    {"pid": proc.info["pid"], "cmd": cmdline, "managed": False, "profile": self.profile}
                                )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        return processes

    def status(self) -> Dict:
        """Get server status"""
        processes = self._find_server_processes()
        # Get the primary managed process PID
        managed_processes = [p for p in processes if p.get("managed")]
        primary_pid = managed_processes[0]["pid"] if managed_processes else None

        result = {
            "running": len(processes) > 0,
            "pid": primary_pid,  # Add primary PID for UI display
            "processes": processes,
            "profile": self.profile,
            "protocol": self.protocol,
            "server_path": self.server_path,
            "port": self.port,
            "registered": self.registered,
        }
        # 미등록 프로필/서버 파일 부재는 조용히 넘기지 않고 이유를 함께 돌려준다
        if not self.server_path:
            result["error"] = self._unresolved_reason()
        return result

    @staticmethod
    def get_available_protocols(profile: str) -> List[str]:
        """
        Get list of available protocols for a profile.
        Checks which server files exist in the profile's server directory.

        editor_config.json 미등록 프로필은 빈 목록을 반환한다.
        (구버전의 프로필명 부분 문자열 폴백은 미등록 프로필에 남의 서버 프로토콜을
         노출시켰으므로 제거)
        """
        base_path = _profile_base_path(profile)
        if not base_path:
            return []

        return [
            protocol
            for protocol, server_file in PROTOCOL_SERVER_FILES.items()
            if os.path.exists(os.path.join(base_path, server_file))
        ]

    @staticmethod
    def get_all_protocols_status(profile: str) -> Dict:
        """
        Get status for all available protocols of a profile.
        Returns a dict with protocol as key and status as value.
        """
        available_protocols = MCPServerManager.get_available_protocols(profile)
        result = {
            "profile": profile,
            "protocols": {}
        }

        for protocol in available_protocols:
            manager = MCPServerManager(profile, protocol)
            status = manager.status()
            result["protocols"][protocol] = {
                "running": status["running"],
                "pid": status["pid"],
                "server_path": status["server_path"]
            }

        return result

    def start(self, detached: bool = True) -> Dict:
        """Start the server"""
        # Check if already running
        status = self.status()
        if status["running"]:
            managed = [p for p in status["processes"] if p["managed"]]
            if managed:
                return {
                    "success": False,
                    "error": f"Server already running with PID {managed[0]['pid']}",
                    "pid": managed[0]["pid"],
                }

        if not self.server_path:
            # 미등록 프로필을 다른 서버로 폴백시키지 않고 명확한 오류를 돌려준다
            return {"success": False, "error": self._unresolved_reason(), "profile": self.profile}

        # 프로필에 설정된 포트를 자식 프로세스에 전달한다.
        # 도메인 서버(server_stream.py 등)는 MCP_SERVER_PORT 를 읽고, 없으면 자체 기본 포트를 쓴다.
        env = os.environ.copy()
        if self.port:
            env["MCP_SERVER_PORT"] = str(self.port)

        # Start the server
        try:
            if detached:
                # Start in background with proper detachment
                with open(self.log_file, "w") as log:
                    process = subprocess.Popen(
                        [sys.executable, self.server_path],
                        cwd=os.path.dirname(self.server_path),
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                        close_fds=True,
                        env=env,
                    )

                # Give it a moment to start
                time.sleep(1)

                if process.poll() is None:
                    # Process is running
                    self._write_pid(process.pid)
                    return {
                        "success": True,
                        "pid": process.pid,
                        "port": self.port,
                        "message": f"Server started with PID {process.pid}"
                        + (f" on port {self.port}" if self.port else ""),
                        "log_file": self.log_file,
                    }
                else:
                    # Process failed to start
                    with open(self.log_file, "r") as log:
                        error_output = log.read()
                    return {"success": False, "error": f"Server failed to start: {error_output}"}
            else:
                # Run in foreground (for debugging)
                subprocess.run(
                    [sys.executable, self.server_path],
                    cwd=os.path.dirname(self.server_path),
                    env=env,
                )
                return {"success": True, "message": "Server ran in foreground mode"}

        except Exception as e:
            return {"success": False, "error": f"Failed to start server: {str(e)}"}

    def stop(self, force: bool = False) -> Dict:
        """Stop the server"""
        processes = self._find_server_processes()
        if not processes:
            if not self.server_path:
                # 미등록 프로필이면 "프로세스 없음" 대신 원인을 밝힌다
                return {"success": False, "error": self._unresolved_reason(), "profile": self.profile}
            return {"success": False, "error": "No server process found"}

        killed_count = 0
        errors = []

        for proc_info in processes:
            pid = proc_info["pid"]
            try:
                process = psutil.Process(pid)
                if force:
                    process.kill()  # SIGKILL
                else:
                    process.terminate()  # SIGTERM

                # Wait for process to terminate
                try:
                    process.wait(timeout=5)
                except psutil.TimeoutExpired:
                    if not force:
                        # If gentle termination failed, force kill
                        process.kill()
                        process.wait(timeout=2)

                killed_count += 1

                # Remove PID file if it was managed
                if proc_info["managed"]:
                    self._remove_pid()

            except psutil.NoSuchProcess:
                # Process already gone
                if proc_info["managed"]:
                    self._remove_pid()
                killed_count += 1
            except Exception as e:
                errors.append(f"Failed to stop PID {pid}: {str(e)}")

        if killed_count > 0:
            return {
                "success": True,
                "message": f"Stopped {killed_count} server process(es)",
                "errors": errors if errors else None,
            }
        else:
            return {"success": False, "error": "Failed to stop any processes", "errors": errors}

    def restart(self) -> Dict:
        """Restart the server"""
        # Stop the server
        stop_result = self.stop()

        # Wait a moment
        time.sleep(1)

        # Start the server
        start_result = self.start()

        return {"success": start_result.get("success", False), "stop_result": stop_result, "start_result": start_result}

    def logs(self, lines: int = 50) -> str:
        """Get recent log output"""
        if not os.path.exists(self.log_file):
            return "No log file found"

        try:
            with open(self.log_file, "r") as f:
                all_lines = f.readlines()
                return "".join(all_lines[-lines:])
        except Exception as e:
            return f"Error reading log file: {str(e)}"


def main():
    """CLI interface for server management"""
    import argparse

    parser = argparse.ArgumentParser(description="MCP Server Manager")
    parser.add_argument("action", choices=["start", "stop", "restart", "status", "logs", "protocols"], help="Action to perform")
    parser.add_argument("--profile", default="default", help="Profile name (outlook, calendar, teams, ...)")
    parser.add_argument("--protocol", default="stream", choices=PROTOCOL_TYPES, help="Server protocol (rest, stdio, stream)")
    parser.add_argument("--force", action="store_true", help="Force kill the server (for stop action)")
    parser.add_argument("--foreground", action="store_true", help="Run server in foreground (for start action)")
    parser.add_argument("--lines", type=int, default=50, help="Number of log lines to show (for logs action)")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Override MCP_SERVER_PORT (default: editor_config.json 의 프로필 포트)",
    )

    args = parser.parse_args()

    if args.action == "protocols":
        # Show available protocols for the profile
        result = MCPServerManager.get_all_protocols_status(args.profile)
        print(json.dumps(result, indent=2))
        sys.exit(0)

    manager = MCPServerManager(args.profile, args.protocol, port=args.port)

    if args.action == "status":
        result = manager.status()
        print(json.dumps(result, indent=2))

    elif args.action == "start":
        result = manager.start(detached=not args.foreground)
        print(json.dumps(result, indent=2))

    elif args.action == "stop":
        result = manager.stop(force=args.force)
        print(json.dumps(result, indent=2))

    elif args.action == "restart":
        result = manager.restart()
        print(json.dumps(result, indent=2))

    elif args.action == "logs":
        print(manager.logs(lines=args.lines))
        result = {"success": True}  # Initialize result for logs action

    sys.exit(0 if result.get("success", True) else 1)


if __name__ == "__main__":
    main()
