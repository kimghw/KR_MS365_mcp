"""
mcp_ms365 — Discover & sanity-check Claude Code HTTP MCP servers.

~/.claude.json을 읽어 type=http로 등록된 모든 MCP 서버를 찾고,
각 서버의 실행 가능성(스크립트/포트 상태)을 점검해 JSON으로 출력합니다.

사용법:
    python discover_servers.py            # 사람 친화 표
    python discover_servers.py --json     # JSON (스킬이 파싱)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(r"c:\Users\USER\KR_MS365_mcp")
VENV_PYTHON = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
CLAUDE_JSON = Path.home() / ".claude.json"


def _display_width(s: str) -> int:
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _display_width(s))


def _port_state(port: int) -> dict:
    """Windows: PowerShell Get-NetTCPConnection으로 점유 상태 + PID."""
    try:
        ps_cmd = (
            f"$c = Get-NetTCPConnection -LocalPort {port} -State Listen "
            f"-ErrorAction SilentlyContinue | Select-Object -First 1; "
            f"if ($c) {{ Write-Host $c.OwningProcess }}"
        )
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        pid_str = out.stdout.strip()
        if pid_str.isdigit():
            return {"in_use": True, "pid": int(pid_str)}
    except Exception:
        pass
    return {"in_use": False, "pid": None}


def _http_health(url: str) -> dict:
    """`/mcp` URL에서 `/health`를 유추해 GET. 200이면 healthy."""
    health_url = re.sub(r"/mcp/?$", "/health", url)
    if health_url == url:
        health_url = url.rstrip("/") + "/health"
    try:
        import urllib.request, urllib.error
        with urllib.request.urlopen(health_url, timeout=3) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(body)
            except Exception:
                payload = {"raw": body[:200]}
            return {"ok": resp.status == 200, "status": resp.status, "url": health_url, "body": payload}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "url": health_url, "body": None}
    except Exception as e:
        return {"ok": False, "status": None, "url": health_url, "body": None, "error": type(e).__name__}


def _walk_claude_json() -> list:
    """top-level + projects.*.mcpServers의 모든 entry 평탄화."""
    if not CLAUDE_JSON.exists():
        return []
    try:
        data = json.loads(CLAUDE_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []

    out = []
    for name, cfg in (data.get("mcpServers") or {}).items():
        out.append({"name": name, "config": cfg, "scope": "user"})
    for proj_path, proj_data in (data.get("projects") or {}).items():
        mcp = proj_data.get("mcpServers") if isinstance(proj_data, dict) else None
        if isinstance(mcp, dict):
            for name, cfg in mcp.items():
                out.append({"name": name, "config": cfg, "scope": f"local:{proj_path}"})
    return out


def _is_http(cfg: dict) -> bool:
    if not isinstance(cfg, dict):
        return False
    if cfg.get("type") == "http":
        return True
    if cfg.get("type") == "sse":
        return True
    url = cfg.get("url")
    return bool(url and isinstance(url, str) and url.startswith("http"))


def _resolve_stream_script(name: str) -> Path:
    """{name}을 mcp_{name}/mcp_server/server_stream.py로 해석."""
    return PROJECT_ROOT / f"mcp_{name}" / "mcp_server" / "server_stream.py"


def discover() -> dict:
    venv_ok = VENV_PYTHON.exists()
    entries = _walk_claude_json()

    servers = []
    for e in entries:
        cfg = e["config"]
        if not _is_http(cfg):
            continue

        url = cfg.get("url", "")
        parsed = urlparse(url)
        port = parsed.port

        stream_script = _resolve_stream_script(e["name"])
        port_info = _port_state(port) if port else {"in_use": False, "pid": None}
        health = _http_health(url) if port_info["in_use"] else {"ok": False, "status": None, "url": None, "body": None}

        issues = []
        if not venv_ok:
            issues.append("venv missing — 먼저 /setup_ms365 실행")
        if not stream_script.exists():
            issues.append(f"stream_script 없음: {stream_script} (등록만 되고 코드가 없는 서버)")
        if not port:
            issues.append(f"URL에서 포트 파싱 실패: {url}")
        if port_info["in_use"] and not health["ok"]:
            issues.append(
                f"포트 {port} LISTEN 중이지만 health 응답 없음 — 다른 프로세스 점유 가능 (pid={port_info['pid']})"
            )

        servers.append({
            "name": e["name"],
            "scope": e["scope"],
            "url": url,
            "host": parsed.hostname,
            "port": port,
            "stream_script": str(stream_script),
            "stream_script_exists": stream_script.exists(),
            "port_in_use": port_info["in_use"],
            "port_pid": port_info["pid"],
            "health": health,
            "startable": (
                venv_ok
                and stream_script.exists()
                and bool(port)
                and not port_info["in_use"]
            ),
            "running": port_info["in_use"] and health["ok"],
            "issues": issues,
        })

    return {
        "project_root": str(PROJECT_ROOT),
        "venv_python": str(VENV_PYTHON),
        "venv_ok": venv_ok,
        "claude_json": str(CLAUDE_JSON),
        "claude_json_exists": CLAUDE_JSON.exists(),
        "http_server_count": len(servers),
        "servers": servers,
    }


def render(data: dict) -> str:
    lines = ["", "mcp_ms365 — HTTP MCP 서버 디스커버리", "-" * 72]
    lines.append(f"  venv: {'OK ' if data['venv_ok'] else 'X  '} {data['venv_python']}")
    lines.append(f"  ~/.claude.json: {'OK ' if data['claude_json_exists'] else 'X  '} {data['claude_json']}")
    lines.append(f"  HTTP MCP 서버 수: {data['http_server_count']}")
    lines.append("")

    if not data["servers"]:
        lines.append("  (등록된 HTTP MCP 서버 없음 — /setup_ms365로 먼저 등록하세요)")
        lines.append("-" * 72)
        return "\n".join(lines)

    for s in data["servers"]:
        if s["running"]:
            state = "RUNNING ✓"
        elif s["port_in_use"]:
            state = f"PORT_BUSY (pid={s['port_pid']}, health X)"
        elif s["startable"]:
            state = "STOPPED — start 가능"
        else:
            state = "UNAVAILABLE — issues 참조"

        lines.append(f"  ── {s['name']} ── {state}")
        lines.append(f"     URL:        {s['url']}")
        lines.append(f"     scope:      {s['scope']}")
        lines.append(f"     script:     {s['stream_script']}  {'(exists)' if s['stream_script_exists'] else '(MISSING)'}")
        if s["issues"]:
            for issue in s["issues"]:
                lines.append(f"     ⚠ {issue}")
        lines.append("")

    lines.append("-" * 72)
    return "\n".join(lines)


def main() -> int:
    data = discover()
    if "--json" in sys.argv[1:]:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
