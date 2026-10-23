"""시나리오 7 — mode 1 기동 거부 (②-4.5, ②-7.4, ②-8.1, ②-10 B02·F07).

- 실제 도메인의 stdio 진입점은 mode 1 에서 lifecycle·stdout 을 건드리기 전에 거부한다.
- 멀티유저와 충돌하는 공용 설정(기본 사용자·공용 경로·입력 검증 끄기·KEK 미설정)이 있으면
  HTTP 앱을 만들지 않는다.
- 실제 진입 스크립트(subprocess)도 같은 이유로 비정상 종료하고 포트를 열지 않는다.
"""

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_common.principal import DOMAINS
from mcp_common.security_contracts import StartupConfigError
from tests.multi_user.harness import BASE_ENV, ENV_TO_CLEAR, HANDLERS, build_domain_app

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _SpyLifecycle:
    def __init__(self, name: str):
        self.server_name = name
        self.errors = []
        self.calls = []

    async def startup(self):
        self.calls.append("startup")

    async def shutdown(self):
        self.calls.append("shutdown")


# ----------------------------------------------------------------------
# stdio
# ----------------------------------------------------------------------
@pytest.mark.parametrize("domain", DOMAINS)
def test_stdio_transport_refuses_mode1_before_lifecycle(mu, domain):
    from mcp_common.stdio_transport import run_stdio

    module = HANDLERS[domain]
    lifecycle = _SpyLifecycle(module.SERVER_NAME)
    with pytest.raises(StartupConfigError) as err:
        run_stdio(module.build_mcp_server(), lifecycle, boot=None)
    assert "stdio" in str(err.value)
    assert lifecycle.calls == []


def _subprocess_env(tmp_path: Path, **extra: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ENV_TO_CLEAR}
    env.update(BASE_ENV)
    env.update({"MS365_MULTI_USER": "1", "MS365_DATA_ROOT": str((tmp_path / "data").resolve()),
                "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    env.update(extra)
    return env


@pytest.mark.parametrize("domain", ["calendar", "file_handler", "time"])
def test_real_stdio_entrypoint_exits_without_speaking_jsonrpc(tmp_path, domain):
    script = PROJECT_ROOT / f"mcp_{domain}" / "mcp_server" / "server_stdio.py"
    init = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                  "clientInfo": {"name": "t", "version": "0"}}})
    proc = subprocess.run(
        [sys.executable, str(script)], input=init + "\n", capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=90, cwd=str(tmp_path), env=_subprocess_env(tmp_path),
    )
    assert proc.returncode != 0
    assert proc.stdout.strip() == "", "mode 1 stdio 가 JSON-RPC 를 응답했다"
    assert "StartupConfigError" in proc.stderr and "MS365_MULTI_USER=1" in proc.stderr


# ----------------------------------------------------------------------
# 충돌 설정
# ----------------------------------------------------------------------
CONFLICTS = {
    "MS365_DEFAULT_USER_EMAIL": "bob@contoso.com",
    "MCP_ALLOWED_PATHS": "C:/",
    "MCP_DATA_DIR": "C:/shared",
    "DB_PATH": "database/auth.db",
    "MCP_ATTACHMENT_OUTPUT_DIR": "./output",
    "MCP_VALIDATE_INPUT": "0",
}


@pytest.mark.parametrize("domain", DOMAINS)
@pytest.mark.parametrize("var", sorted(CONFLICTS))
def test_conflicting_shared_setting_refuses_http_startup(mu, domain, var):
    mu.monkeypatch.setenv(var, CONFLICTS[var])
    with pytest.raises(StartupConfigError) as err:
        build_domain_app(domain, mu.monkeypatch)
    assert var in str(err.value)
    assert CONFLICTS[var] not in str(err.value) or CONFLICTS[var] in ("0",)  # 값은 메시지에 싣지 않는다


@pytest.mark.parametrize("domain", ["outlook", "time"])
def test_missing_kek_provider_refuses_startup(mu, domain):
    mu.monkeypatch.delenv("MS365_KEK_PROVIDER")
    with pytest.raises(StartupConfigError):
        build_domain_app(domain, mu.monkeypatch)


def test_relative_data_root_refuses_startup(tmp_path, monkeypatch):
    from mcp_common.security_policy import reset_policy_cache

    for key in ENV_TO_CLEAR:
        monkeypatch.delenv(key, raising=False)
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("MS365_MULTI_USER", "1")
    monkeypatch.setenv("MS365_DATA_ROOT", "relative/data")
    reset_policy_cache()
    try:
        with pytest.raises(StartupConfigError):
            build_domain_app("calendar", monkeypatch)
    finally:
        monkeypatch.delenv("MS365_MULTI_USER")
        reset_policy_cache()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.parametrize("domain,extra", [
    ("outlook", {"MS365_DEFAULT_USER_EMAIL": "bob@contoso.com"}),
    ("file_handler", {"MCP_ATTACHMENT_TEMP_DIR": "C:/shared-tmp"}),
])
def test_real_http_entrypoint_refuses_conflicting_setting(tmp_path, domain, extra):
    port = _free_port()
    script = PROJECT_ROOT / f"mcp_{domain}" / "mcp_server" / "server_stream.py"
    proc = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=90, cwd=str(tmp_path), env=_subprocess_env(tmp_path, MCP_SERVER_PORT=str(port), **extra),
    )
    assert proc.returncode != 0
    assert "StartupConfigError" in proc.stderr
    assert next(iter(extra)) in proc.stderr
    assert extra[next(iter(extra))] not in proc.stderr


def test_file_handler_home_config_refuses_mode1_import(tmp_path):
    """F07 — 홈 config 가 경로를 바꾸면 mode 1 FileHandler 프로세스는 뜨지 않는다(handlers import 시점)."""
    home = tmp_path / "home"
    (home / ".mcp_file_handler").mkdir(parents=True)
    (home / ".mcp_file_handler" / "config.json").write_text(json.dumps({"output_dir": "C:/shared-out"}),
                                                           encoding="utf-8")
    port = _free_port()
    script = PROJECT_ROOT / "mcp_file_handler" / "mcp_server" / "server_stream.py"
    proc = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=90, cwd=str(tmp_path),
        env=_subprocess_env(tmp_path, MCP_SERVER_PORT=str(port), USERPROFILE=str(home), HOME=str(home)),
    )
    assert proc.returncode != 0
    assert "StartupConfigError" in proc.stderr and "config" in proc.stderr
    assert "C:/shared-out" not in proc.stderr
