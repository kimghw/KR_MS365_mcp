"""WP12 통합 격리 검증 fixture — 임시 데이터 루트 + memory KEK + 가짜 Entra + 가짜 Graph.

`mu` 하나로 mode 1 환경 전체를 만든다. 실제 registry·토큰 저장소·OAuth gateway·서비스 풀을 쓴다.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pytest

from mcp_common import service_pool
from mcp_common.testing import multi_user_mode
from session.tests.mu_support import ALICE, BOB, FakeEntra
from tests.multi_user.harness import (
    BASE_ENV,
    ENV_TO_CLEAR,
    AccessSpy,
    GraphFake,
    User,
    domain_client,
    onboard,
    register,
)


@dataclass
class MuEnv:
    root: Path
    entra: FakeEntra
    graph: GraphFake
    monkeypatch: Any

    def onboard(self, account, domains=None) -> User:
        return onboard(self.entra, account, domains)

    def register(self, account, domains=None) -> User:
        return register(account, domains)

    def client(self, domain: str):
        return domain_client(domain, self.monkeypatch)

    @property
    def audit_dir(self) -> Path:
        return self.root / "system" / "audit"

    def audit_text(self) -> str:
        if not self.audit_dir.exists():
            return ""
        return "".join(p.read_text(encoding="utf-8") for p in sorted(self.audit_dir.glob("*.jsonl")))


@pytest.fixture
def mu(tmp_path, monkeypatch):
    from session.entra_client import set_entra_http_for_tests, set_jwks_client_for_tests
    from session.key_provider import set_key_provider_for_tests

    for key in ENV_TO_CLEAR:
        monkeypatch.delenv(key, raising=False)
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)

    entra = FakeEntra()
    graph = GraphFake(entra)
    graph.install(monkeypatch)
    set_entra_http_for_tests(entra)
    set_jwks_client_for_tests(entra.jwks)
    # 사전 서명 URL 검사는 호스트를 DNS 로 해석한다(astra 2차 N05). 가짜 호스트
    # (`download.sharepoint.example` 등)가 네트워크 없이 통과하도록 공개 주소로 고정한다 —
    # 사설·loopback·단일 라벨 거부는 이름 규칙이라 그대로 검증된다.
    import ipaddress

    from mcp_common import graph_url_policy

    monkeypatch.setattr(
        graph_url_policy, "_resolved_addresses", lambda host: [ipaddress.ip_address("93.184.216.34")]
    )
    service_pool.reset_service_pool_for_tests()
    with multi_user_mode(tmp_path / "data") as root:
        try:
            yield MuEnv(root, entra, graph, monkeypatch)
        finally:
            service_pool.reset_service_pool_for_tests()
            set_entra_http_for_tests(None)
            set_jwks_client_for_tests(None)
            set_key_provider_for_tests(None)


@pytest.fixture
def spy(mu) -> AccessSpy:
    return AccessSpy().install(mu.monkeypatch)


@pytest.fixture
def alice(mu) -> User:
    return mu.onboard(ALICE)


@pytest.fixture
def bob(mu) -> User:
    return mu.onboard(BOB)
