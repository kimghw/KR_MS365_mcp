#!/usr/bin/env python3
"""Register MS365 MCP servers in Claude Code (~/.claude.json) as HTTP transport.

Usage:
    python register_claude_code.py --servers outlook,teams
    python register_claude_code.py --servers all

Reads ~/.claude.json, sets top-level mcpServers[<name>] = {type:"http", url:...}
for each selected server, and removes any duplicate entries lingering in
project-scoped mcpServers. Preserves all other entries. Idempotent.
"""
from __future__ import annotations

import argparse
import json
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
    args = ap.parse_args()

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
        mcp[name] = {"type": "http", "url": f"http://localhost:{port}/mcp"}

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
