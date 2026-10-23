"""Automation for the 8-probe Streamable HTTP compliance checklist.

Reference:
    .claude/skills/setup_ms365/references/streamable_http_checklist.md

Usage:
    python streamable_http_probe.py --base http://localhost:5001
    python streamable_http_probe.py --base http://localhost:5001 --json
    python streamable_http_probe.py --base http://localhost:5001 --strict

    # 멀티유저 모드 (MS365_MULTI_USER=1) — bearer key 는 **환경변수로만** 받는다
    MS365_MCP_BEARER_KEY=... python streamable_http_probe.py --base http://localhost:5001 --multi-user
    python streamable_http_probe.py --base ... --multi-user --key-env MY_KEY_VAR

멀티유저 모드는 stateless 다(spec/spec_멀티유저.md ②-4.4): `Mcp-Session-Id` 를 발급하지 않고,
보내면 400, GET/DELETE 는 405, 키 없는 요청은 401 + `WWW-Authenticate: Bearer` 가 **정상**이다.
키 원문은 명령행 인자로 받지 않으며 출력·오류 메시지에도 싣지 않는다.

Pure stdlib only (urllib + json + argparse). Works on Windows native Python.
"""
import argparse
import io
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# Force UTF-8 on Windows consoles that default to cp949/cp1252 — otherwise
# any non-ASCII output (e.g. error messages from the server) would crash.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except (AttributeError, io.UnsupportedOperation):
    pass

PROTO_VER = "2025-03-26"
#: 멀티유저 bearer key 를 담은 환경변수의 기본 이름 (키 자체는 명령행에 넣지 않는다)
DEFAULT_KEY_ENV = "MS365_MCP_BEARER_KEY"
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


class _NoRaiseHTTPProcessor(urllib.request.HTTPErrorProcessor):
    """Don't let urllib raise on 4xx/5xx — we want the status code as data."""

    def http_response(self, request, response):
        return response

    https_response = http_response


_OPENER = urllib.request.build_opener(_NoRaiseHTTPProcessor())


def _http(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    body: Optional[bytes] = None,
    timeout: float = 5.0,
) -> Tuple[int, Dict[str, str], bytes]:
    """One-shot HTTP call. Returns (status, headers-lowercased-dict, body-bytes)."""
    req = urllib.request.Request(url=url, data=body, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            data = resp.read()
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, hdrs, data
    except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
        return 0, {}, str(e).encode("utf-8", "replace")


def _http_open_only(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 2.0,
) -> Tuple[int, Dict[str, str]]:
    """Open a GET connection, read headers, then close (don't drain body).

    Used for SSE probe — we just want to verify the response framing.
    """
    req = urllib.request.Request(url=url, method="GET")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        resp = _OPENER.open(req, timeout=timeout)
        try:
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, hdrs
        finally:
            try:
                resp.close()
            except Exception:
                pass
    except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
        return 0, {"_error": str(e)}


def _init_request_body() -> bytes:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTO_VER,
            "capabilities": {},
            "clientInfo": {"name": "streamable-http-probe", "version": "0"},
        },
    }
    return json.dumps(payload).encode("utf-8")


def _make_probe(
    n: int,
    desc: str,
    expected: str,
    got: str,
    passed: bool,
    reason: str = "",
) -> Dict[str, Any]:
    return {
        "n": n,
        "desc": desc,
        "expected": expected,
        "got": got,
        "result": "PASS" if passed else "FAIL",
        "reason": reason,
    }


def run_probes(base: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Run all 8 probes. Returns (results, captured_session_id)."""
    url = base.rstrip("/") + "/mcp"
    results: List[Dict[str, Any]] = []

    # Probe 1 — initialize with full Accept negotiation
    status, hdrs, body = _http(
        "POST",
        url,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTO_VER,
        },
        body=_init_request_body(),
    )
    session_id = hdrs.get("mcp-session-id")
    ctype = hdrs.get("content-type", "")
    p1_ok = status == 200 and bool(session_id)
    p1_got = f"{status}" + (f"+session" if session_id else "+no-session") + (f"/{ctype.split(';')[0]}" if ctype else "")
    p1_reason = ""
    if status == 0:
        p1_reason = body.decode("utf-8", "replace")[:140]
    elif status != 200:
        p1_reason = "non-200 — endpoint not /mcp or transport not standard"
    elif not session_id:
        p1_reason = "no Mcp-Session-Id header — likely a self-rolled implementation"
    results.append(_make_probe(1, "initialize + Accept(json,sse)", "200+session", p1_got, p1_ok, p1_reason))

    # If probe 1 failed catastrophically (connection error / no session), skip session-dependent probes.
    if not session_id:
        # Probe 2 still runnable (no session needed)
        pass

    # Probe 2 — Accept header missing, expect 406
    status2, _, body2 = _http(
        "POST",
        url,
        headers={
            "Content-Type": "application/json",
            "MCP-Protocol-Version": PROTO_VER,
        },
        body=_init_request_body(),
    )
    p2_ok = status2 == 406
    p2_reason = "" if p2_ok else (
        "connection failed" if status2 == 0
        else "server accepted request without Accept header — spec strict mode not enforced"
    )
    results.append(_make_probe(2, "no Accept header", "406", str(status2), p2_ok, p2_reason))

    # Probe 3 — notifications/initialized (no id) → 202
    if session_id:
        notif_body = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode("utf-8")
        status3, _, _ = _http(
            "POST",
            url,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": PROTO_VER,
                "Mcp-Session-Id": session_id,
            },
            body=notif_body,
        )
        p3_ok = status3 == 202
        p3_reason = "" if p3_ok else "non-202 for notification — server treats notifications as requests"
        results.append(_make_probe(3, "notifications/initialized", "202", str(status3), p3_ok, p3_reason))
    else:
        results.append(_make_probe(3, "notifications/initialized", "202", "skipped", False, "no session from Probe 1"))

    # Probe 4 — GET /mcp with session-id → 200 + text/event-stream
    if session_id:
        status4, hdrs4 = _http_open_only(
            url,
            headers={
                "Accept": "text/event-stream",
                "MCP-Protocol-Version": PROTO_VER,
                "Mcp-Session-Id": session_id,
            },
            timeout=2.0,
        )
        ctype4 = hdrs4.get("content-type", "")
        p4_ok = status4 == 200 and "text/event-stream" in ctype4
        p4_got = f"{status4}/{ctype4.split(';')[0]}" if ctype4 else str(status4)
        p4_reason = ""
        if status4 == 0:
            p4_reason = hdrs4.get("_error", "")[:140]
        elif status4 != 200:
            p4_reason = "GET /mcp not supported — server cannot push messages to client"
        elif "text/event-stream" not in ctype4:
            p4_reason = f"unexpected content-type: {ctype4}"
        results.append(_make_probe(4, "GET /mcp + session-id", "200+sse", p4_got, p4_ok, p4_reason))
    else:
        results.append(_make_probe(4, "GET /mcp + session-id", "200+sse", "skipped", False, "no session from Probe 1"))

    # Probe 5 — tools/list with valid session
    if session_id:
        list_body = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode("utf-8")
        status5, _, body5 = _http(
            "POST",
            url,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": PROTO_VER,
                "Mcp-Session-Id": session_id,
            },
            body=list_body,
        )
        body_text = body5.decode("utf-8", "replace") if body5 else ""
        has_result = '"result"' in body_text and '"tools"' in body_text
        p5_ok = status5 == 200 and has_result
        p5_got = f"{status5}" + ("+result" if has_result else "+no-result")
        p5_reason = ""
        if status5 != 200:
            p5_reason = "non-200 with valid session — application-layer error"
        elif not has_result:
            p5_reason = "200 but no result.tools in body — application returned error"
        results.append(_make_probe(5, "tools/list", "200+result", p5_got, p5_ok, p5_reason))
    else:
        results.append(_make_probe(5, "tools/list", "200+result", "skipped", False, "no session from Probe 1"))

    # Probe 6 — bogus session-id → 404
    bogus_body = json.dumps({"jsonrpc": "2.0", "id": 99, "method": "tools/list", "params": {}}).encode("utf-8")
    status6, _, _ = _http(
        "POST",
        url,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTO_VER,
            "Mcp-Session-Id": "not-a-real-session",
        },
        body=bogus_body,
    )
    p6_ok = status6 == 404
    p6_reason = "" if p6_ok else "non-404 for fake session — server does not enforce session validation"
    results.append(_make_probe(6, "bogus session-id", "404", str(status6), p6_ok, p6_reason))

    # Probe 7 — DELETE /mcp (close session) → 200
    if session_id:
        status7, _, _ = _http(
            "DELETE",
            url,
            headers={
                "MCP-Protocol-Version": PROTO_VER,
                "Mcp-Session-Id": session_id,
            },
        )
        p7_ok = status7 == 200
        p7_reason = "" if p7_ok else (
            "DELETE not supported — cannot explicitly close session" if status7 == 405
            else f"unexpected status {status7}"
        )
        results.append(_make_probe(7, "DELETE /mcp", "200", str(status7), p7_ok, p7_reason))
    else:
        results.append(_make_probe(7, "DELETE /mcp", "200", "skipped", False, "no session from Probe 1"))

    # Probe 8 — POST after DELETE with same session-id → 404
    if session_id:
        post_body = json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}}).encode("utf-8")
        status8, _, _ = _http(
            "POST",
            url,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": PROTO_VER,
                "Mcp-Session-Id": session_id,
            },
            body=post_body,
        )
        p8_ok = status8 == 404
        p8_reason = "" if p8_ok else "DELETE was a no-op — session not actually closed"
        results.append(_make_probe(8, "POST after DELETE", "404", str(status8), p8_ok, p8_reason))
    else:
        results.append(_make_probe(8, "POST after DELETE", "404", "skipped", False, "no session from Probe 1"))

    return results, session_id


def _post(url: str, body: bytes, *, key: Optional[str], extra: Optional[Dict[str, str]] = None,
          accept: bool = True) -> Tuple[int, Dict[str, str], bytes]:
    headers = {"Content-Type": "application/json", "MCP-Protocol-Version": PROTO_VER}
    if accept:
        headers["Accept"] = "application/json, text/event-stream"
    if key is not None:
        headers["Authorization"] = f"Bearer {key}"
    headers.update(extra or {})
    return _http("POST", url, headers=headers, body=body)


def run_probes_multi_user(base: str, key: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """멀티유저(stateless + bearer) 9-probe. 키가 없으면 인증이 필요한 probe 는 건너뛴다."""
    url = base.rstrip("/") + "/mcp"
    results: List[Dict[str, Any]] = []
    no_key = "bearer key 환경변수가 비어 있다 — 키가 필요한 probe 건너뜀"
    list_body = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode("utf-8")

    # 1 — 키 없는 initialize → 401 + WWW-Authenticate: Bearer (이것이 정상)
    s1, h1, b1 = _post(url, _init_request_body(), key=None)
    challenge = h1.get("www-authenticate", "")
    ok1 = s1 == 401 and challenge.lower().startswith("bearer")
    results.append(_make_probe(1, "initialize without key", "401+Bearer", str(s1), ok1,
                               "" if ok1 else ("connection failed: " + b1.decode("utf-8", "replace")[:100] if s1 == 0
                                               else "인증 없이 통과했거나 WWW-Authenticate 가 없다")))

    # 2 — 형식은 맞지만 모르는 키 → 401
    bogus = "m365v1." + "0" * 32 + "." + "A" * 43
    s2, _, _ = _post(url, _init_request_body(), key=bogus)
    results.append(_make_probe(2, "initialize with unknown key", "401", str(s2), s2 == 401,
                               "" if s2 == 401 else "모르는 키를 받아들였다"))

    if not key:
        for n, desc, exp in ((3, "initialize with key", "200+stateless"), (4, "no Accept header", "406"),
                             (5, "notifications/initialized", "202"), (6, "tools/list (no session)", "200+result"),
                             (7, "Mcp-Session-Id sent", "400"), (8, "GET /mcp", "405"), (9, "DELETE /mcp", "405")):
            results.append(_make_probe(n, desc, exp, "skipped", False, no_key))
        return results, None

    # 3 — 키 있는 initialize → 200, Mcp-Session-Id 없음 (stateless)
    s3, h3, _ = _post(url, _init_request_body(), key=key)
    session_id = h3.get("mcp-session-id")
    ok3 = s3 == 200 and not session_id
    results.append(_make_probe(3, "initialize with key", "200+stateless",
                               f"{s3}" + ("+session" if session_id else "+no-session"), ok3,
                               "" if ok3 else ("세션 ID 를 발급했다 — stateless 가 아니다" if session_id
                                               else "키가 거부됐다(401/403: 만료·폐기·scope) 또는 서버 오류")))

    # 4 — Accept 없음 → 406 (인증 뒤 SDK 가 판정)
    s4, _, _ = _post(url, _init_request_body(), key=key, accept=False)
    results.append(_make_probe(4, "no Accept header", "406", str(s4), s4 == 406,
                               "" if s4 == 406 else "Accept 협상을 강제하지 않는다"))

    # 5 — notification → 202
    notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode("utf-8")
    s5, _, _ = _post(url, notif, key=key)
    results.append(_make_probe(5, "notifications/initialized", "202", str(s5), s5 == 202,
                               "" if s5 == 202 else "notification 을 요청처럼 처리한다"))

    # 6 — 세션 없이 tools/list → 200 + result.tools
    s6, _, b6 = _post(url, list_body, key=key)
    text6 = b6.decode("utf-8", "replace") if b6 else ""
    has_result = '"result"' in text6 and '"tools"' in text6
    ok6 = s6 == 200 and has_result
    results.append(_make_probe(6, "tools/list (no session)", "200+result",
                               f"{s6}" + ("+result" if has_result else "+no-result"), ok6,
                               "" if ok6 else "stateless 요청에 도구 목록이 오지 않았다"))

    # 7 — Mcp-Session-Id 를 보내면 400 (세션은 인증 근거도 상태 보관소도 아니다)
    s7, _, _ = _post(url, list_body, key=key, extra={"Mcp-Session-Id": "not-a-real-session"})
    results.append(_make_probe(7, "Mcp-Session-Id sent", "400", str(s7), s7 == 400,
                               "" if s7 == 400 else "세션 헤더를 거부하지 않는다"))

    # 8·9 — GET 스트림·DELETE 세션 종료는 지원하지 않는다 → 405
    auth = {"Authorization": f"Bearer {key}", "MCP-Protocol-Version": PROTO_VER}
    s8, _ = _http_open_only(url, headers={**auth, "Accept": "text/event-stream"})
    results.append(_make_probe(8, "GET /mcp", "405", str(s8), s8 == 405, "" if s8 == 405 else "GET 스트림을 연다"))
    s9, _, _ = _http("DELETE", url, headers=auth)
    results.append(_make_probe(9, "DELETE /mcp", "405", str(s9), s9 == 405, "" if s9 == 405 else "DELETE 를 받아들인다"))
    return results, None


def _print_table(base: str, results: List[Dict[str, Any]]) -> None:
    print(f"=== Streamable HTTP Compliance — {base} ===")
    print(f"{'Probe':<6}{'Description':<38}{'Expected':<14}{'Got':<22}Result")
    for r in results:
        desc = r["desc"][:36]
        exp = r["expected"][:12]
        got = r["got"][:20]
        line = f"{r['n']:<6}{desc:<38}{exp:<14}{got:<22}{r['result']}"
        print(line)
        if r["reason"]:
            print(f"        reason: {r['reason']}")
    passed = sum(1 for r in results if r["result"] == "PASS")
    total = len(results)
    verdict = "compliant" if passed == total else ("partial — see failures" if passed >= 4 else "non-compliant")
    print(f"\nSummary: {passed}/{total} passed   <- {verdict}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the 8-probe MCP Streamable HTTP compliance checklist against a server."
    )
    parser.add_argument(
        "--base",
        required=True,
        help="Server base URL (e.g. http://localhost:5001). /mcp is appended automatically.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of the table.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if any of the probes fail (default exit 0).",
    )
    parser.add_argument(
        "--multi-user",
        action="store_true",
        help="멀티유저 모드(stateless + bearer) 9-probe. 키는 --key-env 가 가리키는 환경변수에서 읽는다.",
    )
    parser.add_argument(
        "--key-env",
        default=DEFAULT_KEY_ENV,
        help="bearer key 를 담은 환경변수 **이름** (기본: %(default)s). 키 자체를 넣지 말 것.",
    )
    args = parser.parse_args(argv)

    if args.multi_user:
        if not _ENV_NAME_RE.match(args.key_env or ""):
            # 키를 명령행에 넣은 실수 — 셸 기록에 남았을 수 있으니 회전을 권한다(값은 출력하지 않는다)
            parser.error("--key-env 에는 환경변수 이름만 넣는다. 키를 명령행에 넣었다면 그 키를 회전(key rotate)할 것.")
        key = os.environ.get(args.key_env, "").strip() or None
        results, _ = run_probes_multi_user(args.base, key)
    else:
        results, _ = run_probes(args.base)

    if args.json:
        passed = sum(1 for r in results if r["result"] == "PASS")
        print(json.dumps({
            "base": args.base,
            "mode": "multi_user" if args.multi_user else "single_operator",
            "passed": passed,
            "total": len(results),
            "compliant": passed == len(results),
            "probes": results,
        }, ensure_ascii=False, indent=2))
    else:
        _print_table(args.base, results)

    if args.strict:
        passed = sum(1 for r in results if r["result"] == "PASS")
        return 0 if passed == len(results) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
