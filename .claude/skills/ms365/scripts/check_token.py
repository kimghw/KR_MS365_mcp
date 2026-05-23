#!/usr/bin/env python3
"""Validate the stored Azure token via AuthManager.validate_and_refresh_token.

Usage:
    python check_token.py

Outputs single-line JSON:
    {"status":"valid","email":"..."}
    {"status":"invalid_or_expired","email":"..."}
    {"status":"no_user"}
    {"status":"error","message":"..."}
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Resolve project root from this script's location:
#   <PROJECT>/.claude/skills/ms365/scripts/check_token.py → parents[4]
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))


async def _run() -> dict:
    try:
        from session.auth_manager import AuthManager, get_default_user_email
    except Exception as e:
        return {"status": "error", "message": f"import failed: {e}"}

    am = AuthManager()
    try:
        email = get_default_user_email()
        if not email:
            return {"status": "no_user"}
        token = await am.validate_and_refresh_token(email, auto_reauth=False)
        if token:
            return {"status": "valid", "email": email}
        return {"status": "invalid_or_expired", "email": email}
    finally:
        await am.close()


def main() -> int:
    result = asyncio.run(_run())
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
