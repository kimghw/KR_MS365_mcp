"""A03 다중 프로세스 refresh 테스트용 자식 프로세스 진입점과 가짜 토큰 endpoint(HTTP).

spawn 방식 자식은 이 모듈을 import 해 실행하므로 테스트 파일(test_*) 밖에 둔다.
"""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List
from urllib.parse import parse_qs


class TokenEndpoint:
    """`POST /<tenant>/oauth2/v2.0/token` 만 처리하는 로컬 가짜. 갱신 요청을 세고 느리게 응답한다."""

    def __init__(self, *, valid_refresh: str, delay: float = 1.0):
        self.valid_refresh = {valid_refresh}
        self.delay = delay
        self.calls: List[Dict[str, str]] = []
        self._lock = threading.Lock()
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # 테스트 출력 오염 방지
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode("utf-8")).items()}
                with endpoint._lock:
                    endpoint.calls.append(form)
                    n = len(endpoint.calls)
                    ok = (form.get("grant_type") == "refresh_token"
                          and form.get("refresh_token") in endpoint.valid_refresh)
                    if ok:
                        endpoint.valid_refresh.discard(form["refresh_token"])
                        endpoint.valid_refresh.add(f"rt-new-{n}")
                time.sleep(endpoint.delay)
                if ok:
                    body = {"access_token": f"at-new-{n}", "refresh_token": f"rt-new-{n}", "expires_in": 3600,
                            "token_type": "Bearer", "scope": "x"}
                    status = 200
                else:
                    body, status = {"error": "invalid_grant"}, 400
                raw = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def refresh_worker(env: Dict[str, str], principal_fields: Dict, go_file: str, out_queue) -> None:
    """자식 프로세스: 환경을 맞추고 go 신호를 기다린 뒤 같은 사용자의 토큰을 요청한다."""
    os.environ.update(env)
    try:
        import asyncio

        from mcp_common.principal import Principal
        from mcp_common.security_contracts import SecurityError
        from mcp_common.security_policy import reset_policy_cache

        reset_policy_cache()
        from session.token_store import get_graph_access_token

        fields = dict(principal_fields)
        fields["scopes"] = frozenset(fields["scopes"])
        principal = Principal(**fields)
        out_queue.put(("ready", os.getpid()))
        deadline = time.monotonic() + 30
        while not os.path.exists(go_file):
            if time.monotonic() > deadline:
                out_queue.put(("error", "go timeout"))
                return
            time.sleep(0.01)
        try:
            token = asyncio.run(get_graph_access_token(principal))
            out_queue.put(("token", token.value))
        except SecurityError as exc:
            out_queue.put(("error", exc.code))
    except Exception as exc:  # noqa: BLE001 - 부모에서 원인 확인
        out_queue.put(("error", f"{type(exc).__name__}: {exc}"))
