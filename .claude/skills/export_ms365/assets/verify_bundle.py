#!/usr/bin/env python3
"""번들 자체 점검 — "받은 쪽 PC 에서 이게 진짜 도는가"를 인증 없이 확인한다.

번들 루트에 함께 실려 나가고, Windows Sandbox 테스트도 같은 파일을 실행한다
(검증 로직이 두 벌이 되지 않도록).

검사 항목
    structure : bundle_manifest.json 의 서버·공용 구성이 실제로 있는가
    secrets   : .env / *.db 가 섞여 나가지 않았는가
    imports   : 각 서버의 handlers 모듈이 import 되고 도구 목록이 나오는가
    schema    : 도구마다 description·inputSchema 가 있는가 (에이전트가 읽는 계약)
    http      : (--http) server_stream 을 실제로 띄워 /health 가 200 인가

`.env` 없이도 전부 통과해야 한다. Azure 호출은 하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def _fail(check: str, detail: str) -> dict[str, Any]:
    return {"check": check, "ok": False, "detail": detail}


def _ok(check: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"check": check, "ok": True, "detail": detail, **extra}


# ---------------------------------------------------------------------------


def load_manifest() -> dict[str, Any]:
    path = ROOT / "bundle_manifest.json"
    if not path.is_file():
        raise SystemExit("bundle_manifest.json 이 없다 — 번들 루트에서 실행할 것")
    return json.loads(path.read_text(encoding="utf-8"))


def check_structure(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    missing: list[str] = []

    for server in manifest.get("servers", []):
        pkg = server["package"]
        for rel in (f"{pkg}/mcp_server/handlers.py", f"{pkg}/mcp_server/server_stdio.py", f"{pkg}/mcp_server/server_stream.py"):
            if not (ROOT / rel).is_file():
                missing.append(rel)

    common = manifest.get("common", {})
    for pkg in common.get("packages", []):
        if not (ROOT / pkg).is_dir():
            missing.append(f"{pkg}/")
    for fname in common.get("files", []):
        if not (ROOT / fname).is_file():
            missing.append(fname)
    for spec in common.get("specs", []):
        if not (ROOT / "spec" / "param_spec" / spec).is_file():
            missing.append(f"spec/param_spec/{spec}")
    for skill in common.get("skills", []):
        if not (ROOT / ".claude" / "skills" / skill / "SKILL.md").is_file():
            missing.append(f".claude/skills/{skill}/SKILL.md")

    results.append(
        _fail("structure", f"누락 {len(missing)}건: {', '.join(missing[:8])}")
        if missing
        else _ok("structure", f"서버 {len(manifest.get('servers', []))}개 + 공용 구성 모두 존재")
    )
    return results


#: 검사 대상이 아닌 디렉터리. 설치된 의존성은 "번들이 실어 보낸 파일"이 아니다 —
#: 예를 들어 certifi 의 `cacert.pem` 은 공개 CA 번들인데 *.pem 규칙에 걸려 오탐이 난다
#: (2026-09-16 실제로 겪었다: `uv sync` 뒤에 돌리면 secrets 검사만 실패했다).
_SKIP_DIRS = frozenset({".venv", "venv", "env", ".git", "node_modules", "__pycache__", ".uv-cache"})


def _bundle_files() -> list[Path]:
    """번들 자신의 파일만. 가상환경·캐시·VCS 디렉터리는 통째로 건너뛴다."""
    found: list[Path] = []

    def walk(directory: Path) -> None:
        for entry in directory.iterdir():
            if entry.name in _SKIP_DIRS:
                continue
            if entry.is_dir():
                walk(entry)
            elif entry.is_file():
                found.append(entry)

    walk(ROOT)
    return found


def check_secrets() -> list[dict[str, Any]]:
    leaked = [
        p.relative_to(ROOT).as_posix()
        for p in _bundle_files()
        if p.name == ".env" or p.suffix in (".db", ".sqlite", ".sqlite3", ".pem", ".pfx")
    ]
    if leaked:
        return [_fail("secrets", f"번들에 비밀 파일이 있다: {', '.join(leaked[:5])}")]
    return [_ok("secrets", ".env / *.db 없음")]


def check_imports(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """각 서버의 handlers 를 import 해 도구 목록과 스키마를 확인한다."""
    results: list[dict[str, Any]] = []
    sys.path.insert(0, str(ROOT))

    try:
        from mcp_common.bootstrap import bootstrap_http
    except Exception as exc:  # noqa: BLE001 — 의존성 미설치도 여기로 온다
        return [_fail("imports", f"mcp_common.bootstrap import 실패: {exc}")]

    for server in manifest.get("servers", []):
        name, pkg = server["name"], server["package"]
        entry = ROOT / pkg / "mcp_server" / "server_stream.py"
        try:
            bootstrap_http(str(entry), package_name=pkg)
            module = __import__(f"{pkg}.mcp_server.handlers", fromlist=["MCP_TOOLS"])
            tools = list(getattr(module, "MCP_TOOLS", []))
            if not tools:
                results.append(_fail(f"imports:{name}", "도구 목록이 비어 있다"))
                continue

            bad = [
                t.get("name", "?")
                for t in tools
                if not t.get("description") or not isinstance(t.get("inputSchema"), dict)
            ]
            if bad:
                results.append(_fail(f"schema:{name}", f"description/inputSchema 누락: {', '.join(bad[:5])}"))
            else:
                results.append(
                    _ok(
                        f"imports:{name}",
                        f"도구 {len(tools)}개",
                        port=getattr(module, "DEFAULT_PORT", None),
                        version=getattr(module, "SERVER_VERSION", None),
                        tools=[t["name"] for t in tools],
                    )
                )
        except Exception as exc:  # noqa: BLE001
            results.append(_fail(f"imports:{name}", f"{type(exc).__name__}: {exc}"))

    return results


def _free_port(preferred: int | None) -> int:
    if preferred:
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", preferred)) != 0:
                return preferred
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def check_http(manifest: dict[str, Any], python: str, timeout: int = 45) -> list[dict[str, Any]]:
    """server_stream.py 를 실제로 띄우고 /health 를 두드린다."""
    results: list[dict[str, Any]] = []

    for server in manifest.get("servers", []):
        name, pkg = server["name"], server["package"]
        port = _free_port(server.get("port"))
        env = dict(os.environ, MCP_SERVER_PORT=str(port), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        entry = ROOT / pkg / "mcp_server" / "server_stream.py"

        proc = subprocess.Popen(
            [python, str(entry)],
            cwd=str(ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        )
        try:
            deadline = time.time() + timeout
            payload: dict[str, Any] | None = None
            last_error = "시간 초과"
            while time.time() < deadline:
                if proc.poll() is not None:
                    last_error = "프로세스가 조기 종료됐다"
                    break
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as resp:
                        payload = json.loads(resp.read().decode("utf-8"))
                        break
                except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
                    last_error = str(exc)
                    time.sleep(1)

            if payload is not None:
                results.append(
                    _ok(f"http:{name}", f"/health 응답 (port {port})",
                        tool_count=payload.get("tool_count"), status=payload.get("status"))
                )
            else:
                tail = ""
                if proc.stdout is not None:
                    proc.terminate()
                    try:
                        tail = (proc.stdout.read() or "")[-600:]
                    except (OSError, ValueError):
                        tail = ""
                results.append(_fail(f"http:{name}", f"{last_error} | 로그: {tail.strip()[-400:]}"))
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="MS365 MCP 번들 자체 점검")
    parser.add_argument("--json", action="store_true", help="JSON 으로만 출력")
    parser.add_argument("--http", action="store_true", help="server_stream 을 실제로 띄워 /health 확인")
    parser.add_argument("--out", default=None, help="결과 JSON 을 이 경로에도 쓴다")
    args = parser.parse_args()

    manifest = load_manifest()
    results: list[dict[str, Any]] = []
    results += check_structure(manifest)
    results += check_secrets()
    results += check_imports(manifest)
    if args.http:
        results += check_http(manifest, sys.executable)

    failed = [r for r in results if not r["ok"]]
    report = {
        "bundle": manifest.get("bundle_name"),
        "source_commit": manifest.get("source_commit"),
        "servers": [s["name"] for s in manifest.get("servers", [])],
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "ok": not failed,
        "results": results,
    }

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for item in results:
            mark = "PASS" if item["ok"] else "FAIL"
            extra = ""
            if item.get("tools"):
                extra = f" ({len(item['tools'])} tools)"
            elif item.get("tool_count") is not None:
                extra = f" (tool_count={item['tool_count']})"
            print(f"[{mark}] {item['check']}: {item['detail']}{extra}")
        print(f"\n{report['passed']} passed / {report['failed']} failed")

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
