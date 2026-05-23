#!/usr/bin/env python3
"""Stop processes listening on the given TCP ports (Windows, via PowerShell).

Usage:
    python stop_server.py --ports 5001
    python stop_server.py --ports 5001 5002 5003
    python stop_server.py --servers outlook,teams   # convenience name→port

Uses Get-NetTCPConnection + Stop-Process. Prints one line per port.
"""
from __future__ import annotations

import argparse
import subprocess
import sys

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


def stop(port: int) -> str:
    ps = (
        f"$conn = Get-NetTCPConnection -LocalPort {port} -State Listen "
        f"-ErrorAction SilentlyContinue;"
        f"if ($conn) {{"
        f"  $pids = $conn | Select-Object -ExpandProperty OwningProcess -Unique;"
        f"  foreach ($p in $pids) {{ Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }};"
        f'  Write-Output "stopped PID(s) on port {port}: $pids"'
        f"}} else {{"
        f'  Write-Output "no listener on port {port}"'
        f"}}"
    )
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps],
        capture_output=True, text=True,
    )
    return (r.stdout or "").strip() or (r.stderr or "").strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ports", nargs="+", type=int, help="Port numbers (1..65535)")
    g.add_argument("--servers", help="Comma-separated server names or 'all'")
    args = ap.parse_args()

    if args.servers:
        if args.servers.strip().lower() == "all":
            ports = list(DEFAULT_PORTS.values())
        else:
            names = [s.strip() for s in args.servers.split(",") if s.strip()]
            unknown = [s for s in names if s not in DEFAULT_PORTS]
            if unknown:
                print(f"ERROR: unknown servers: {unknown}", file=sys.stderr)
                return 2
            ports = [DEFAULT_PORTS[n] for n in names]
    else:
        ports = args.ports

    bad = [p for p in ports if not (1 <= p <= 65535)]
    if bad:
        print(f"ERROR: invalid ports {bad} (must be 1..65535)", file=sys.stderr)
        return 2

    for p in ports:
        print(stop(p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
