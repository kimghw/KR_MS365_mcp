#!/usr/bin/env python3
"""Register MS365 MCP servers in Claude Code (~/.claude.json) as HTTP transport.

Usage:
    python register_claude_code.py --servers outlook,teams
    python register_claude_code.py --servers all

Reads ~/.claude.json, sets top-level mcpServers[<name>] = {type:"http", url:...}
for each selected server, and removes any duplicate entries lingering in
project-scoped mcpServers. Preserves all other entries. Idempotent.

멀티유저 모드(MS365_MULTI_USER=1)에서는 서버가 매 요청 `Authorization: Bearer <key>` 를 요구한다.
- 기존 등록의 `headers` 는 **보존**한다(재등록이 bearer 헤더를 지워 401 이 나지 않게).
- `--auth-header-env VAR` 를 주면 `headers.Authorization = "Bearer ${VAR}"` 를 쓴다 — 키 원문이 아니라
  환경변수 참조다. 키 자체는 명령행·설정 파일에 넣지 않는다. 클라이언트가 `${VAR}` 를 확장하지
  않는 버전이면 그 클라이언트의 헤더 설정 방법을 따른다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DEFAULT_PORTS = {
    "outlook":  5001,
    "calendar": 5002,
    "teams":    5003,
    "onedrive": 5004,
    "onenote":  5005,
    "todo":     5006,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--servers", required=True,
                    help="Comma-separated server names or 'all' "
                         f"(known: {','.join(DEFAULT_PORTS)})")
    ap.add_argument("--config", default=str(Path.home() / ".claude.json"),
                    help="Path to ~/.claude.json (default: %(default)s)")
    ap.add_argument("--auth-header-env", default=None, metavar="VAR",
                    help="멀티유저: headers.Authorization 을 'Bearer ${VAR}' 로 쓴다 (환경변수 이름만)")
    args = ap.parse_args()
    if args.auth_header_env and not re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$", args.auth_header_env):
        print("ERROR: --auth-header-env 에는 환경변수 이름만 넣는다 (키를 넣었다면 그 키를 회전할 것)",
              file=sys.stderr)
        return 2

    if args.servers.strip().lower() == "all":
        targets = list(DEFAULT_PORTS.keys())
    else:
        targets = [s.strip() for s in args.servers.split(",") if s.strip()]
        unknown = [s for s in targets if s not in DEFAULT_PORTS]
        if unknown:
            print(f"ERROR: unknown servers: {unknown}", file=sys.stderr)
            return 2

    cfg = Path(args.config)
    data = json.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else {}
    mcp = data.setdefault("mcpServers", {})

    for name in targets:
        port = DEFAULT_PORTS[name]
        entry = {"type": "http", "url": f"http://localhost:{port}/mcp"}
        previous = mcp.get(name)
        if isinstance(previous, dict) and isinstance(previous.get("headers"), dict):
            entry["headers"] = dict(previous["headers"])
        if args.auth_header_env:
            entry.setdefault("headers", {})["Authorization"] = "Bearer ${" + args.auth_header_env + "}"
        mcp[name] = entry

    # Remove duplicate project-scoped entries for the same names
    for proj_path, proj_data in (data.get("projects") or {}).items():
        proj_mcp = proj_data.get("mcpServers") if isinstance(proj_data, dict) else None
        if isinstance(proj_mcp, dict):
            for name in list(proj_mcp.keys()):
                if name in targets:
                    proj_mcp.pop(name)

    cfg.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"updated {cfg}: registered {targets} -> top-level mcpServers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
