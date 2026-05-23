#!/usr/bin/env python3
"""Register MS365 MCP servers in Claude Desktop (claude_desktop_config.json) as STDIO.

Usage:
    python register_claude_desktop.py --servers outlook,teams
    python register_claude_desktop.py --servers all

Reads %APPDATA%\\Claude\\claude_desktop_config.json (utf-8-sig BOM tolerant),
sets mcpServers[<name>] = {command, args, env} for each selected server,
preserves all other entries. Claude Desktop spawn STDIO automatically once
registered; restart Desktop after running this script.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DEFAULT_PROJECT = Path(r"c:\Users\USER\KR_MS365_mcp")
SERVER_NAMES = ["outlook", "calendar", "teams", "onedrive", "onenote", "todo"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--servers", required=True,
                    help="Comma-separated server names or 'all'")
    ap.add_argument("--project", default=str(DEFAULT_PROJECT),
                    help="Project root (default: %(default)s)")
    ap.add_argument("--config",
                    default=str(Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"),
                    help="Path to claude_desktop_config.json (default: %APPDATA%/Claude/...)")
    args = ap.parse_args()

    if args.servers.strip().lower() == "all":
        targets = SERVER_NAMES[:]
    else:
        targets = [s.strip() for s in args.servers.split(",") if s.strip()]
        unknown = [s for s in targets if s not in SERVER_NAMES]
        if unknown:
            print(f"ERROR: unknown servers: {unknown}", file=sys.stderr)
            return 2

    project = Path(args.project)
    python = project / "venv" / "Scripts" / "python.exe"
    cfg = Path(args.config)
    cfg.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {}
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as e:
            print(f"ERROR: existing config invalid JSON: {e}", file=sys.stderr)
            return 1

    mcp = data.setdefault("mcpServers", {})
    for name in targets:
        mcp[name] = {
            "command": str(python),
            "args": [str(project / f"mcp_{name}" / "mcp_server" / "server_stdio.py")],
            "env": {
                "PYTHONPATH": str(project),
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            },
        }

    cfg.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"updated {cfg}: registered {targets} (Desktop restart required)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
