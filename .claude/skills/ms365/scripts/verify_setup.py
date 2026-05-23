"""
setup_ms365 통합 검증 스크립트 (Windows)

venv / 의존성 / .env / 토큰 DB / Claude Code 등록 / MCP 서버 포트 상태를
한 번에 확인하고 사람 친화 표 또는 JSON으로 출력합니다.

시스템 Python(venv 부재 시)에서도 동작하도록 표준 라이브러리만 사용합니다.

사용법:
    python verify_setup.py            # 사람 친화 표
    python verify_setup.py --json     # JSON
    python verify_setup.py --exit-code # 0(OK) / 1(어딘가 실패)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(r"c:\Users\USER\KR_MS365_mcp")
VENV_PYTHON = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
ENV_FILE = PROJECT_ROOT / ".env"
DB_FILE = PROJECT_ROOT / "database" / "auth.db"

# 서버별 정의 (이름 → HTTP 포트 + STDIO/Stream 스크립트 경로)
def _srv(name: str, default_port: int) -> dict:
    return {
        "http_port": int(os.environ.get(f"MCP_{name.upper()}_PORT", str(default_port))),
        "stdio_script": PROJECT_ROOT / f"mcp_{name}" / "mcp_server" / "server_stdio.py",
        "stream_script": PROJECT_ROOT / f"mcp_{name}" / "mcp_server" / "server_stream.py",
    }

SERVERS = {
    "outlook":  _srv("outlook",  5001),
    "calendar": _srv("calendar", 5002),
    "teams":    _srv("teams",    5003),
    "onedrive": _srv("onedrive", 5004),
    "onenote":  _srv("onenote",  5005),
    "todo":     _srv("todo",     5006),
}

CORE_DEPS = [
    ("aiohttp", "aiohttp"),
    ("pydantic", "pydantic"),
    ("yaml", "PyYAML"),
    ("dotenv", "python-dotenv"),
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
]


def check_venv() -> dict:
    """venv 존재 + Python 버전 확인."""
    if not VENV_PYTHON.exists():
        return {"exists": False, "python": None, "version": None}
    try:
        out = subprocess.run(
            [str(VENV_PYTHON), "-c", "import sys; print(sys.version.split()[0])"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        version = out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        version = None
    return {"exists": True, "python": str(VENV_PYTHON), "version": version}


def check_deps() -> dict:
    """venv에서 핵심 패키지 import 가능 여부."""
    if not VENV_PYTHON.exists():
        return {"all_ok": False, "missing": [name for _, name in CORE_DEPS], "reason": "no venv"}
    missing = []
    for mod, pkg_name in CORE_DEPS:
        result = subprocess.run(
            [str(VENV_PYTHON), "-c", f"import {mod}"],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            missing.append(pkg_name)
    return {"all_ok": not missing, "missing": missing}


def check_env_file() -> dict:
    """.env 존재 + 필수 Azure 자격증명 키 채워졌는지."""
    if not ENV_FILE.exists():
        return {
            "exists": False,
            "has_client_id": False,
            "has_client_secret": False,
            "has_tenant_id": False,
            "has_redirect_uri": False,
        }
    try:
        text = ENV_FILE.read_text(encoding="utf-8-sig")
    except Exception:
        text = ENV_FILE.read_text(errors="replace")

    def has(key: str) -> bool:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(f"{key}="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                return bool(value)
        return False

    return {
        "exists": True,
        "has_client_id": has("AZURE_CLIENT_ID"),
        "has_client_secret": has("AZURE_CLIENT_SECRET"),
        "has_tenant_id": has("AZURE_TENANT_ID"),
        "has_redirect_uri": has("AZURE_REDIRECT_URI"),
    }


def check_tokens() -> dict:
    """auth.db에 사용자/토큰 레코드 존재 여부."""
    if not DB_FILE.exists():
        return {"db_exists": False, "users": 0, "tokens": 0, "first_user": None}
    try:
        con = sqlite3.connect(str(DB_FILE))
        cur = con.cursor()
        try:
            cur.execute("SELECT COUNT(*) FROM azure_user_info")
            users = cur.fetchone()[0]
        except sqlite3.OperationalError:
            users = 0
        try:
            cur.execute("SELECT COUNT(*) FROM azure_token_info")
            tokens = cur.fetchone()[0]
        except sqlite3.OperationalError:
            tokens = 0
        first_user = None
        if users:
            try:
                cur.execute("SELECT user_email FROM azure_user_info LIMIT 1")
                row = cur.fetchone()
                first_user = row[0] if row else None
            except sqlite3.OperationalError:
                pass
        con.close()
        return {"db_exists": True, "users": users, "tokens": tokens, "first_user": first_user}
    except Exception as e:
        return {"db_exists": True, "users": 0, "tokens": 0, "first_user": None, "error": str(e)}


def _check_claude_json_fallback(server_name: str) -> dict:
    """~/.claude.json에서 server_name 등록 여부 + 스코프 확인 (글로벌/프로젝트)."""
    claude_json = Path.home() / ".claude.json"
    if not claude_json.exists():
        return {"registered": False, "url": None, "scope": None}
    try:
        data = json.loads(claude_json.read_text(encoding="utf-8"))
    except Exception:
        return {"registered": False, "url": None, "scope": None}

    # 1. top-level (글로벌 / -s user)
    entry = (data.get("mcpServers") or {}).get(server_name)
    if entry:
        url = entry.get("url") if isinstance(entry, dict) else None
        return {"registered": True, "url": url, "scope": "user"}

    # 2. project-scoped (-s local) — 어느 프로젝트인지도 알려줌
    for proj_path, proj_data in (data.get("projects") or {}).items():
        proj_mcp = proj_data.get("mcpServers") if isinstance(proj_data, dict) else None
        if isinstance(proj_mcp, dict) and server_name in proj_mcp:
            entry = proj_mcp[server_name]
            url = entry.get("url") if isinstance(entry, dict) else None
            return {"registered": True, "url": url, "scope": f"local:{proj_path}"}

    return {"registered": False, "url": None, "scope": None}


def check_claude_code(server_name: str) -> dict:
    """claude mcp list 또는 ~/.claude.json에서 server_name 등록 여부."""
    claude_exe = shutil.which("claude") or shutil.which("claude.cmd")
    if not claude_exe:
        fb = _check_claude_json_fallback(server_name)
        return {"cli_available": False, "registered": fb["registered"], "url": fb["url"], "scope": fb["scope"], "source": ".claude.json"}
    try:
        result = subprocess.run(
            [claude_exe, "mcp", "list"],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
        output = (result.stdout or "") + (result.stderr or "")
    except Exception as e:
        return {"cli_available": True, "registered": False, "url": None, "error": str(e)}

    registered = False
    url = None
    pattern = rf"^\s*{re.escape(server_name)}\s*[:\-]\s*(\S+)"
    for line in output.splitlines():
        m = re.match(pattern, line, re.IGNORECASE)
        if m:
            url_candidate = m.group(1).rstrip(",;)")
            if url_candidate.startswith("http"):
                url = url_candidate
            registered = True
            break

    # CLI 출력으로 못 잡아도 .claude.json 직접 읽어 스코프 정보 확보
    fb = _check_claude_json_fallback(server_name)
    if fb["registered"]:
        return {"cli_available": True, "registered": True, "url": fb["url"] or url, "scope": fb["scope"], "source": ".claude.json"}

    return {"cli_available": True, "registered": registered, "url": url, "scope": None, "source": "claude mcp list"}


def check_claude_desktop(server_name: str) -> dict:
    """%APPDATA%\\Claude\\claude_desktop_config.json에서 server_name 등록 여부 + 경로 유효성."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return {"config_exists": False, "registered": False, "command": None, "path_valid": None}
    cfg = Path(appdata) / "Claude" / "claude_desktop_config.json"
    if not cfg.exists():
        return {"config_exists": False, "registered": False, "command": None, "path_valid": None}
    try:
        data = json.loads(cfg.read_text(encoding="utf-8-sig"))
    except Exception as e:
        return {"config_exists": True, "registered": False, "command": None, "path_valid": None, "error": f"invalid JSON: {e}"}
    entry = (data.get("mcpServers") or {}).get(server_name)
    if not entry or not isinstance(entry, dict):
        return {"config_exists": True, "registered": False, "command": None, "path_valid": None}

    command = entry.get("command")
    args = entry.get("args") or []
    server_script = args[0] if args else None

    command_ok = bool(command) and Path(command).exists()
    script_ok = bool(server_script) and Path(server_script).exists()
    matches_project = (
        command_ok
        and Path(command).resolve() == VENV_PYTHON.resolve()
    )

    return {
        "config_exists": True,
        "registered": True,
        "command": command,
        "server_script": server_script,
        "path_valid": command_ok and script_ok,
        "matches_project": matches_project,
    }


def check_server_port(port: int) -> dict:
    """주어진 포트가 listening인지 (Windows: PowerShell Get-NetTCPConnection)."""
    result = {"port": port, "in_use": False, "pid": None}
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
        pid = out.stdout.strip()
        if pid.isdigit():
            result["in_use"] = True
            result["pid"] = int(pid)
    except Exception:
        pass
    return result


def collect() -> dict:
    """공통(venv/deps/.env/tokens) + 서버별(등록/포트) 정보."""
    servers = {}
    for name, meta in SERVERS.items():
        servers[name] = {
            "http_port": meta["http_port"],
            "stdio_script_exists": meta["stdio_script"].exists(),
            "stream_script_exists": meta["stream_script"].exists(),
            "claude_code": check_claude_code(name),
            "claude_desktop": check_claude_desktop(name),
            "server_port": check_server_port(meta["http_port"]),
        }
    return {
        "venv": check_venv(),
        "deps": check_deps(),
        "env_file": check_env_file(),
        "tokens": check_tokens(),
        "servers": servers,
    }


def _display_width(s: str) -> int:
    """East Asian Wide/Full → 2폭, 그 외 → 1폭."""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def _pad(s: str, width: int) -> str:
    pad = width - _display_width(s)
    return s + " " * max(0, pad)


def render_table(data: dict) -> str:
    venv = data["venv"]
    deps = data["deps"]
    env = data["env_file"]
    tok = data["tokens"]
    servers = data["servers"]

    def mark(ok: bool) -> str:
        return "OK " if ok else "X  "

    common_rows = [
        ("venv", mark(venv["exists"]), f"Python {venv['version']}" if venv["version"] else "missing"),
        ("의존성", mark(deps["all_ok"]),
         "all ok" if deps["all_ok"] else f"missing: {', '.join(deps['missing']) or '(no venv)'}"),
        (".env", mark(env["exists"] and env["has_client_id"] and env["has_client_secret"] and env["has_tenant_id"]),
         "client_id/secret/tenant_id 채워짐" if env["exists"] and env["has_client_id"] and env["has_client_secret"] and env["has_tenant_id"]
         else "missing or incomplete"),
        ("토큰 (공통)", mark(tok["users"] > 0 and tok["tokens"] > 0),
         f"users={tok['users']} tokens={tok['tokens']}" + (f" first={tok['first_user']}" if tok.get("first_user") else "")),
    ]

    lines = ["", "setup_ms365 status", "-" * 72]
    for name, ok, detail in common_rows:
        lines.append(f"  [{ok}] {_pad(name, 22)} {detail}")

    for srv_name, s in servers.items():
        cc = s["claude_code"]
        cd = s["claude_desktop"]
        port = s["server_port"]
        lines.append(f"  ── {srv_name} " + "─" * (66 - len(srv_name)))

        # Claude Code (스코프 표시: user=글로벌, local:<path>=프로젝트)
        scope = cc.get("scope")
        scope_tag = ""
        if scope == "user":
            scope_tag = " [scope=user]"
        elif scope and scope.startswith("local:"):
            scope_tag = f" [scope=local ⚠ project-only]"
        cc_detail = (
            (cc.get("url") or "registered") + scope_tag
            if cc["registered"]
            else ("NOT_REGISTERED" if cc["cli_available"] else "claude CLI not in PATH, .claude.json도 없음")
        )
        # 글로벌이 아니면 OK 마크 안 씀 (사용자 의도는 글로벌)
        cc_ok = cc["registered"] and (scope == "user" if scope else True)
        lines.append(f"  [{mark(cc_ok)}] {_pad('  Claude Code', 22)} {cc_detail}")

        # Claude Desktop
        cd_detail = (
            (
                ("STDIO OK" if cd.get("path_valid") else f"!!! 경로 무효: {cd.get('command')}")
                + (" (PATH MISMATCH)" if cd["registered"] and cd.get("path_valid") and not cd.get("matches_project") else "")
            ) if cd["registered"]
            else (f"config 있음, {srv_name} 없음" if cd["config_exists"] else "claude_desktop_config.json 없음")
        )
        cd_ok = cd["registered"] and cd.get("path_valid", True) and cd.get("matches_project", True)
        lines.append(f"  [{mark(cd_ok)}] {_pad('  Claude Desktop', 22)} {cd_detail}")

        # 포트
        port_label = f"  포트 {port['port']}"
        port_detail = f"in_use (pid={port['pid']})" if port["in_use"] else "free"
        lines.append(f"  [{mark(True)}] {_pad(port_label, 22)} {port_detail}")

    lines.append("-" * 72)
    return "\n".join(lines)


def all_ok(data: dict) -> bool:
    """venv/deps/.env/토큰 OK + 모든 서버가 Code 또는 Desktop 한 곳 이상 등록되면 OK."""
    common = (
        data["venv"]["exists"]
        and data["deps"]["all_ok"]
        and data["env_file"]["exists"]
        and data["env_file"]["has_client_id"]
        and data["env_file"]["has_client_secret"]
        and data["env_file"]["has_tenant_id"]
        and data["tokens"]["users"] > 0
        and data["tokens"]["tokens"] > 0
    )
    if not common:
        return False
    for s in data["servers"].values():
        cc_ok = s["claude_code"]["registered"]
        cd_ok = s["claude_desktop"]["registered"] and s["claude_desktop"].get("path_valid", True) and s["claude_desktop"].get("matches_project", True)
        if not (cc_ok or cd_ok):
            return False
    return True


def main() -> int:
    args = sys.argv[1:]
    json_mode = "--json" in args
    exit_code_mode = "--exit-code" in args

    data = collect()

    if json_mode:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render_table(data))

    if exit_code_mode:
        return 0 if all_ok(data) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
