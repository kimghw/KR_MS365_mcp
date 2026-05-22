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


class MCPServerManager:
    """Manages MCP server lifecycle with PID file tracking"""

    def __init__(self, profile: str = "default", protocol: str = "stream"):
        """
        Initialize server manager.

        Args:
            profile: Profile name (e.g., "outlook", "calendar")
            protocol: Server protocol type ("rest", "stdio", "stream")
        """
        self.profile = profile
        self.protocol = protocol if protocol in PROTOCOL_TYPES else "stream"
        # Include protocol in PID/log file names for independent tracking
        self.pid_file = os.path.join(PID_DIR, f"{profile}_{self.protocol}_server.pid")
        self.log_file = os.path.join(LOG_DIR, f"{profile}_{self.protocol}_server.log")
        self.server_path = self._get_server_path()

    def _get_server_path(self) -> Optional[str]:
        """
        Get the server path based on profile and protocol from editor_config.json.

        This method reads the profile configuration from editor_config.json
        to properly support reused profiles (e.g., outlook_read that uses
        mcp_outlook_read/mcp_server/ instead of mcp_outlook/mcp_server/).

        The protocol determines which server file to use:
        - rest: server_rest.py
        - stdio: server_stdio.py
        - stream: server_stream.py
        """
        # Protocol-specific server file takes priority
        protocol_server_file = PROTOCOL_SERVER_FILES.get(self.protocol)
        # Fallback order if protocol-specific file doesn't exist
        fallback_files = ["server.py"]

        # First, try to load from editor_config.json for accurate path resolution
        config_path = os.path.join(ROOT_DIR, "mcp_editor", "editor_config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                if self.profile in config:
                    profile_conf = config[self.profile]
                    # tool_definitions_path gives us the server directory path
                    tool_def_path = profile_conf.get("tool_definitions_path", "")
                    if tool_def_path:
                        # tool_definitions_path is like "../mcp_outlook_read/mcp_server/tool_definitions.py"
                        # Extract the mcp_server directory
                        base_path = os.path.dirname(
                            os.path.join(ROOT_DIR, "mcp_editor", tool_def_path)
                        )
                        base_path = os.path.normpath(base_path)

                        # Try protocol-specific server file first
                        if protocol_server_file:
                            path = os.path.join(base_path, protocol_server_file)
                            if os.path.exists(path):
                                return path

                        # Fallback to generic server files
                        for server_file in fallback_files:
                            path = os.path.join(base_path, server_file)
                            if os.path.exists(path):
                                return path
            except (json.JSONDecodeError, IOError, KeyError):
                pass  # Fall through to legacy behavior

        # Legacy behavior: substring matching (fallback for backwards compatibility)
        if "outlook" in self.profile.lower():
            base_path = os.path.join(ROOT_DIR, "mcp_outlook", "mcp_server")
        elif "file" in self.profile.lower() or "handler" in self.profile.lower():
            base_path = os.path.join(ROOT_DIR, "mcp_file_handler", "mcp_server")
        elif "calendar" in self.profile.lower():
            base_path = os.path.join(ROOT_DIR, "mcp_calendar", "mcp_server")
        else:
            # Default or try to find any server
            for module in ["mcp_outlook", "mcp_file_handler", "mcp_calendar"]:
                base_path = os.path.join(ROOT_DIR, module, "mcp_server")
                # Check if protocol-specific server file exists
                if protocol_server_file:
                    if os.path.exists(os.path.join(base_path, protocol_server_file)):
                        break
                # Check fallback files
                for server_file in fallback_files:
                    if os.path.exists(os.path.join(base_path, server_file)):
                        break
                else:
                    continue
                break
            else:
                return None

        # Try protocol-specific server file first
        if protocol_server_file:
            path = os.path.join(base_path, protocol_server_file)
            if os.path.exists(path):
                return path

        # Fallback to generic server files
        for server_file in fallback_files:
            path = os.path.join(base_path, server_file)
            if os.path.exists(path):
                return path

        return None

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

        return {
            "running": len(processes) > 0,
            "pid": primary_pid,  # Add primary PID for UI display
            "processes": processes,
            "profile": self.profile,
            "protocol": self.protocol,
            "server_path": self.server_path,
        }

    @staticmethod
    def get_available_protocols(profile: str) -> List[str]:
        """
        Get list of available protocols for a profile.
        Checks which server files exist in the profile's server directory.
        """
        available = []
        config_path = os.path.join(ROOT_DIR, "mcp_editor", "editor_config.json")

        base_path = None
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                if profile in config:
                    profile_conf = config[profile]
                    tool_def_path = profile_conf.get("tool_definitions_path", "")
                    if tool_def_path:
                        base_path = os.path.dirname(
                            os.path.join(ROOT_DIR, "mcp_editor", tool_def_path)
                        )
                        base_path = os.path.normpath(base_path)
            except (json.JSONDecodeError, IOError, KeyError):
                pass

        if not base_path:
            # Fallback to legacy path detection
            if "outlook" in profile.lower():
                base_path = os.path.join(ROOT_DIR, "mcp_outlook", "mcp_server")
            elif "file" in profile.lower() or "handler" in profile.lower():
                base_path = os.path.join(ROOT_DIR, "mcp_file_handler", "mcp_server")
            elif "calendar" in profile.lower():
                base_path = os.path.join(ROOT_DIR, "mcp_calendar", "mcp_server")

        if base_path:
            for protocol, server_file in PROTOCOL_SERVER_FILES.items():
                if os.path.exists(os.path.join(base_path, server_file)):
                    available.append(protocol)

        return available

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
            return {"success": False, "error": f"Server path not found for profile: {self.profile}"}

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
                    )

                # Give it a moment to start
                time.sleep(1)

                if process.poll() is None:
                    # Process is running
                    self._write_pid(process.pid)
                    return {
                        "success": True,
                        "pid": process.pid,
                        "message": f"Server started with PID {process.pid}",
                        "log_file": self.log_file,
                    }
                else:
                    # Process failed to start
                    with open(self.log_file, "r") as log:
                        error_output = log.read()
                    return {"success": False, "error": f"Server failed to start: {error_output}"}
            else:
                # Run in foreground (for debugging)
                subprocess.run([sys.executable, self.server_path], cwd=os.path.dirname(self.server_path))
                return {"success": True, "message": "Server ran in foreground mode"}

        except Exception as e:
            return {"success": False, "error": f"Failed to start server: {str(e)}"}

    def stop(self, force: bool = False) -> Dict:
        """Stop the server"""
        processes = self._find_server_processes()
        if not processes:
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
    parser.add_argument("--profile", default="default", help="Profile name (default, outlook, file_handler, etc.)")
    parser.add_argument("--protocol", default="stream", choices=PROTOCOL_TYPES, help="Server protocol (rest, stdio, stream)")
    parser.add_argument("--force", action="store_true", help="Force kill the server (for stop action)")
    parser.add_argument("--foreground", action="store_true", help="Run server in foreground (for start action)")
    parser.add_argument("--lines", type=int, default=50, help="Number of log lines to show (for logs action)")

    args = parser.parse_args()

    if args.action == "protocols":
        # Show available protocols for the profile
        result = MCPServerManager.get_all_protocols_status(args.profile)
        print(json.dumps(result, indent=2))
        sys.exit(0)

    manager = MCPServerManager(args.profile, args.protocol)

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
