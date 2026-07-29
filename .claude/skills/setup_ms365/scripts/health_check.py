#!/usr/bin/env python3
"""Probe /health endpoint of each MS365 MCP HTTP server.

Usage:
    python health_check.py                       # all 6 servers
    python health_check.py --servers outlook,teams
    python health_check.py --json                # JSON output

Prints one line per server:
    outlook   5001  healthy  {"tool_count":N,...}
    teams     5003  unreachable
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
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


def probe(name: str, port: int, timeout: float = 1.0) -> dict:
    url = f"http://localhost:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = json.loads(r.read())
            return {"name": name, "port": port, "status": "healthy", "body": body}
    except Exception as e:
        return {"name": name, "port": port, "status": "unreachable", "error": str(e)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--servers", default="all",
                    help="Comma-separated names or 'all' (default)")
    ap.add_argument("--json", action="store_true", help="Emit JSON array")
    ap.add_argument("--timeout", type=float, default=1.0)
    args = ap.parse_args()

    if args.servers.strip().lower() == "all":
        targets = list(DEFAULT_PORTS.keys())
    else:
        targets = [s.strip() for s in args.servers.split(",") if s.strip()]
        unknown = [s for s in targets if s not in DEFAULT_PORTS]
        if unknown:
            print(f"ERROR: unknown servers: {unknown}", file=sys.stderr)
            return 2

    results = [probe(n, DEFAULT_PORTS[n], args.timeout) for n in targets]

    if args.json:
        print(json.dumps(results, ensure_ascii=False))
    else:
        for r in results:
            if r["status"] == "healthy":
                body = json.dumps(r["body"], ensure_ascii=False)
                print(f"{r['name']:9} {r['port']}  healthy: {body}")
            else:
                print(f"{r['name']:9} {r['port']}  unreachable")

    unhealthy = sum(1 for r in results if r["status"] != "healthy")
    return 0 if unhealthy == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
