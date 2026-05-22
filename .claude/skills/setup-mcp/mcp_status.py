#!/usr/bin/env python3
"""
setup-mcp 스킬용 상태 조회 헬퍼.

발견된 모든 mcp_*/mcp_server/server_stream.py 서버에 대해:
- 기본 포트
- 프로세스 상태 (STOPPED / RUNNING / PORT_BUSY)
- claude 등록 상태 (claude mcp list 결과)
- vscode 등록 상태 (.vscode/mcp.json 존재 여부)

출력 모드:
  --json    machine-readable JSON 목록
  (기본)    사람용 표 (target 컬럼은 --target 인자로 결정)

사용 예:
  .venv/bin/python .claude/skills/setup-mcp/mcp_status.py
  .venv/bin/python .claude/skills/setup-mcp/mcp_status.py --target claude
  .venv/bin/python .claude/skills/setup-mcp/mcp_status.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path("/home/kimghw/KR_MS365_mcp")
VSCODE_MCP = PROJECT_ROOT / ".vscode" / "mcp.json"

PORT_ENV_RE = re.compile(r"MCP_SERVER_PORT[^)]*\)")
PORT_LITERAL_RE = re.compile(r"port\s*=\s*(\d{4,5})")
DIGITS_RE = re.compile(r"\d{4,5}")


def discover_servers() -> list[dict]:
    """프로젝트 안의 mcp_*/mcp_server/server_stream.py 파일을 수집해 (name, port, path) 반환."""
    servers = []
    for path in sorted(PROJECT_ROOT.glob("mcp_*/mcp_server/server_stream.py")):
        name = path.parent.parent.name.removeprefix("mcp_")
        port = _extract_port(path)
        if port is None:
            continue
        servers.append({"name": name, "port": port, "path": str(path)})
    return servers


def _extract_port(path: Path) -> Optional[int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    # 1) os.environ.get("MCP_SERVER_PORT", 8091) 패턴
    for m in PORT_ENV_RE.finditer(text):
        digits = DIGITS_RE.findall(m.group(0))
        if digits:
            return int(digits[-1])
    # 2) port=8001 같은 리터럴
    m = PORT_LITERAL_RE.search(text)
    if m:
        return int(m.group(1))
    return None


def process_state(server: dict) -> dict:
    """포트 LISTEN 여부 + /proc/PID/cmdline로 우리 서버 맞는지 확인."""
    name = server["name"]
    port = server["port"]
    pid = _pid_for_port(port)
    if pid is None:
        return {"state": "STOPPED", "pid": None, "cmdline": None}
    cmdline = _read_cmdline(pid)
    rel_path = f"mcp_{name}/mcp_server/server_stream.py"
    if cmdline and rel_path in cmdline:
        return {"state": "RUNNING", "pid": pid, "cmdline": cmdline}
    return {"state": "PORT_BUSY", "pid": pid, "cmdline": cmdline}


def _pid_for_port(port: int) -> Optional[int]:
    try:
        out = subprocess.check_output(
            ["ss", "-tlnp"], text=True, stderr=subprocess.DEVNULL
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    needle = f":{port}"
    for line in out.splitlines():
        # LISTEN row contains ":<port> " (space) at the local-address column.
        if f"{needle} " not in line:
            continue
        m = re.search(r"pid=(\d+)", line)
        if m:
            return int(m.group(1))
    return None


def _read_cmdline(pid: int) -> Optional[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (FileNotFoundError, PermissionError):
        return None
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()


def claude_registration() -> dict[str, str]:
    """claude mcp list 결과를 파싱해 {server_name: state} 반환.

    state는 'REGISTERED_OK' | 'REGISTERED_FAILED' | 'REGISTERED_UNKNOWN'.
    """
    try:
        out = subprocess.run(
            ["claude", "mcp", "list"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}
    result: dict[str, str] = {}
    for line in out.splitlines():
        # 예: "outlook: http://localhost:8091/mcp - ✓ Connected"
        m = re.match(r"^\s*([\w\-]+)\s*:\s*(.+)$", line)
        if not m:
            continue
        name = m.group(1)
        rest = m.group(2)
        if "Connected" in rest or "✓" in rest:
            result[name] = "REGISTERED_OK"
        elif "Failed" in rest or "✗" in rest:
            result[name] = "REGISTERED_FAILED"
        elif "auth" in rest.lower() or "!" in rest:
            result[name] = "REGISTERED_UNKNOWN"
        else:
            result[name] = "REGISTERED_UNKNOWN"
    return result


def vscode_registration() -> set[str]:
    """.vscode/mcp.json에 등록된 서버 이름 집합."""
    if not VSCODE_MCP.exists():
        return set()
    try:
        data = json.loads(VSCODE_MCP.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    servers = data.get("servers", data.get("mcpServers", {}))
    return set(servers.keys())


def build_status(target: Optional[str] = None) -> list[dict]:
    servers = discover_servers()
    claude_map = claude_registration() if target in (None, "claude") else {}
    vscode_set = vscode_registration() if target in (None, "vscode") else set()
    rows = []
    for srv in servers:
        proc = process_state(srv)
        row = {
            "name": srv["name"],
            "port": srv["port"],
            "path": srv["path"],
            "process": proc,
        }
        if target in (None, "claude"):
            row["claude"] = claude_map.get(srv["name"], "NOT_REGISTERED")
        if target in (None, "vscode"):
            row["vscode"] = "REGISTERED_OK" if srv["name"] in vscode_set else "NOT_REGISTERED"
        rows.append(row)
    return rows


def format_table(rows: list[dict], target: Optional[str]) -> str:
    if not rows:
        return "(no MCP servers discovered)"
    has_claude = target in (None, "claude")
    has_vscode = target in (None, "vscode")
    header = ["Server", "Port", "Process"]
    if has_claude: header.append("claude")
    if has_vscode: header.append("vscode")
    widths = [max(len(h), 12) for h in header]
    # Determine widths from data
    text_rows = []
    for r in rows:
        proc = r["process"]
        if proc["state"] == "RUNNING":
            ptxt = f"RUNNING(pid={proc['pid']})"
        elif proc["state"] == "PORT_BUSY":
            ptxt = f"PORT_BUSY(pid={proc['pid']})"
        else:
            ptxt = "STOPPED"
        cells = [r["name"], str(r["port"]), ptxt]
        if has_claude: cells.append(_pretty(r.get("claude", "")))
        if has_vscode: cells.append(_pretty(r.get("vscode", "")))
        text_rows.append(cells)
        for i, c in enumerate(cells):
            widths[i] = max(widths[i], len(c))

    def fmt(cells):
        return "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(cells)) + " |"

    lines = [fmt(header), fmt(["-" * w for w in widths])]
    for cells in text_rows:
        lines.append(fmt(cells))
    return "\n".join(lines)


def _pretty(state: str) -> str:
    return {
        "REGISTERED_OK": "REGISTERED ✓",
        "REGISTERED_FAILED": "FAILED ✗",
        "REGISTERED_UNKNOWN": "UNKNOWN ?",
        "NOT_REGISTERED": "NOT_REGISTERED",
    }.get(state, state or "-")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MCP server discovery & status")
    parser.add_argument("--target", choices=["claude", "vscode"],
                        help="Show registration state only for the given target")
    parser.add_argument("--json", action="store_true",
                        help="Machine-readable JSON output")
    args = parser.parse_args(argv)

    rows = build_status(target=args.target)

    if args.json:
        json.dump(rows, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    print(f"target: {args.target or 'both'}")
    print(format_table(rows, target=args.target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
