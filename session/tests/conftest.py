"""session 테스트 공용 fixture — 멀티유저 임시 데이터 루트 + memory KEK + 가짜 Entra."""

import pytest

from mcp_common.testing import multi_user_mode
from session.tests.mu_support import BASE_ENV, CLEARED_ENV, FakeEntra


@pytest.fixture
def mu_root(tmp_path, monkeypatch):
    """MS365_MULTI_USER=1 + 임시 데이터 루트 + 테스트 앱 설정. 끝나면 주입한 가짜를 해제한다."""
    from session.entra_client import set_entra_http_for_tests, set_jwks_client_for_tests
    from session.key_provider import set_key_provider_for_tests

    for key in CLEARED_ENV:
        monkeypatch.delenv(key, raising=False)
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    with multi_user_mode(tmp_path / "data") as root:
        try:
            yield root
        finally:
            set_entra_http_for_tests(None)
            set_jwks_client_for_tests(None)
            set_key_provider_for_tests(None)


@pytest.fixture
def fake_entra(mu_root):
    from session.entra_client import set_entra_http_for_tests, set_jwks_client_for_tests

    fake = FakeEntra()
    set_entra_http_for_tests(fake)
    set_jwks_client_for_tests(fake.jwks)
    return fake
