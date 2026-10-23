#!/usr/bin/env python3
"""Validate the stored Azure token via AuthManager.validate_and_refresh_token.

Usage:
    python check_token.py

Outputs single-line JSON (단일 운영자 모드, 기본):
    {"status":"valid","email":"..."}
    {"status":"invalid_or_expired","email":"..."}
    {"status":"no_user"}
    {"status":"error","message":"..."}

멀티유저 모드(`MS365_MULTI_USER=1` — 환경변수 또는 `.env`)에서는 공용 auth.db·AuthManager 가
없다(생성하면 `LegacyAuthDisabledError`). 대신 registry 의 연결 상태 **개수만** 출력한다 —
이메일·토큰은 출력하지 않는다. 사용자별 상세는 `python -m session.admin_cli user list`.
    {"status":"multi_user","users":3,"graph_connected":2,"pending_link":1,"inactive":0}
    {"status":"multi_user","error":"registry_missing"}
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Resolve project root from this script's location:
#   <PROJECT>/.claude/skills/setup_ms365/scripts/check_token.py → parents[4]
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

_TRUE = {"1", "true", "yes", "on"}


def _load_env() -> None:
    """서버와 같은 규칙으로 `.env` 를 읽는다 (프로세스 환경변수가 우선)."""
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv(PROJECT_ROOT / ".env", encoding="utf-8-sig", override=False)


def _multi_user_status() -> dict:
    try:
        from session.identity_registry import list_users
    except Exception as e:
        return {"status": "error", "message": f"import failed: {type(e).__name__}"}
    try:
        users = list_users()
    except Exception as e:  # registry 없음·설정 오류 — 메시지 원문 대신 종류만
        return {"status": "multi_user", "error": type(e).__name__}
    if not users:
        from mcp_common.user_paths import system_paths

        if not system_paths().registry_db.is_file():
            return {"status": "multi_user", "error": "registry_missing"}
    return {
        "status": "multi_user",
        "users": len(users),
        "graph_connected": sum(1 for u in users if u.get("graph_connected")),
        "pending_link": sum(1 for u in users if u.get("status") == "pending_link"),
        "inactive": sum(1 for u in users if u.get("status") not in ("active", "pending_link")),
    }


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
    _load_env()
    if os.environ.get("MS365_MULTI_USER", "").strip().lower() in _TRUE:
        result = _multi_user_status()
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("status") == "multi_user" and "error" not in result else 1
    result = asyncio.run(_run())
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
