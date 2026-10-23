"""
서버 기동 여부 추정 — 도메인 MCP 서버·auth gateway·legacy 콜백 포트에 연결이 되는가.

포트 목록은 두 벌로 적지 않는다: 도메인 서버는 `spec/param_spec/*.yaml` 의 `server.port`
(`MCP_PARAM_SPEC_DIR` 로 바뀔 수 있음), gateway 는 `MS365_AUTH_GATEWAY_PORT` 또는
`AZURE_REDIRECT_URI` 의 포트, 그리고 `MCP_SERVER_PORT` 가 설정돼 있으면 그것도 본다.
"""

import os
import socket
from pathlib import Path
from typing import Iterable, List, Optional, Sequence
from urllib.parse import urlsplit

#: legacy 콜백(callback_server.py)·gateway 의 기본 포트 — redirect URI 에서 못 읽을 때
DEFAULT_CALLBACK_PORT = 5000
_WILDCARD_HOSTS = {"", "0.0.0.0", "::", "[::]"}


def _spec_ports(spec_dir: Path) -> List[int]:
    import yaml

    ports: List[int] = []
    for path in sorted(Path(spec_dir).glob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        port = (doc.get("server") or {}).get("port") if isinstance(doc, dict) else None
        if isinstance(port, int) and 0 < port < 65536:
            ports.append(port)
    return ports


def _env_port(name: str) -> Optional[int]:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw.isdigit() and 0 < int(raw) < 65536 else None


def server_ports() -> List[int]:
    from mcp_common.param_spec import spec_dir

    ports = set(_spec_ports(Path(spec_dir())))
    for name in ("MS365_AUTH_GATEWAY_PORT", "MCP_SERVER_PORT"):
        port = _env_port(name)
        if port:
            ports.add(port)
    redirect = os.environ.get("AZURE_REDIRECT_URI", "").strip()
    try:
        redirect_port = urlsplit(redirect).port if redirect else None
    except ValueError:
        redirect_port = None
    ports.add(redirect_port or DEFAULT_CALLBACK_PORT)
    return sorted(ports)


def probe_hosts() -> List[str]:
    hosts = ["127.0.0.1"]
    for name in ("MCP_BIND_HOST", "MS365_AUTH_GATEWAY_HOST"):
        host = os.environ.get(name, "").strip()
        if host not in _WILDCARD_HOSTS and host not in hosts:
            hosts.append(host)
    return hosts


def listening(ports: Iterable[int], hosts: Optional[Sequence[str]] = None, timeout: float = 0.3) -> List[int]:
    """연결이 받아들여지는 포트 목록. 거부·시간 초과는 '안 떠 있음'으로 본다."""
    found: List[int] = []
    for port in ports:
        for host in hosts or probe_hosts():
            try:
                with socket.create_connection((host, int(port)), timeout=timeout):
                    found.append(int(port))
                    break
            except OSError:
                continue
    return found


def running_server_ports() -> List[int]:
    return listening(server_ports())


__all__ = ["server_ports", "probe_hosts", "listening", "running_server_ports"]
