"""공용 Graph URL 정책 — nextLink 범위·사전 서명 URL 호스트 검사 (R08, astra 2차 N05)."""

import ipaddress

import pytest

from mcp_common import graph_url_policy as policy
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.testing import bound, make_principal, multi_user_mode

ALICE = make_principal("alice@contoso.com")
RES = frozenset({"events", "calendarview"})


def _denied(fn, *args, **kw):
    with pytest.raises(SecurityError) as e:
        fn(*args, **kw)
    assert e.value.code == ErrorCode.PATH_NOT_ALLOWED


@pytest.mark.parametrize("url", [
    "https://graph.microsoft.com/v1.0/me/events?$skip=50",
    "https://graph.microsoft.com/v1.0/me/calendarView?$skiptoken=x",
    "https://graph.microsoft.com/v1.0/users/alice@contoso.com/events",
])
def test_next_link_own_resources_allowed_mode0(url):
    assert policy.check_next_link(url, "alice@contoso.com", resources=RES) == url


@pytest.mark.parametrize("url", [
    "http://graph.microsoft.com/v1.0/me/events",
    "https://graph.microsoft.com:8443/v1.0/me/events",
    "https://user:pw@graph.microsoft.com/v1.0/me/events",
    "https://graph.microsoft.com.evil.test/v1.0/me/events",
    "https://graph.microsoft.com/beta/me/events",
    "https://graph.microsoft.com/v1.0/users/bob@contoso.com/events",
    "https://graph.microsoft.com/v1.0/me/messages",
    "https://graph.microsoft.com/v1.0/me/events/../../users/bob@contoso.com/events",
    "https://graph.microsoft.com/v1.0/me/events%2F..%2F..%2Fusers%2Fbob",
    "https://graph.microsoft.com/v1.0/me/%2E%2E/users/bob/events",
    "https://graph.microsoft.com/v1.0/$batch",
    "/v1.0/me/events",
])
def test_next_link_rejects_foreign_or_malformed(url):
    _denied(policy.check_next_link, url, "alice@contoso.com", resources=RES)


def test_next_link_mode1_uses_principal_email_and_oid(tmp_path):
    with multi_user_mode(tmp_path), bound(ALICE):
        own_email = f"https://graph.microsoft.com/v1.0/users/{ALICE.graph_email}/events"
        own_oid = f"https://graph.microsoft.com/v1.0/users/{ALICE.object_id.upper()}/events"
        assert policy.check_next_link(own_email, "ignored@x.com", resources=RES) == own_email
        assert policy.check_next_link(own_oid, None, resources=RES) == own_oid
        _denied(policy.check_next_link, "https://graph.microsoft.com/v1.0/users/bob@contoso.com/events", ALICE.graph_email, resources=RES)


@pytest.mark.parametrize("url", [
    "http://cdn.example.com/x",
    "https://cdn.example.com:8443/x",
    "https://u:p@cdn.example.com/x",
    "https://127.0.0.1/x",
    "https://10.0.0.5/x",
    "https://[::1]/x",
    "https://169.254.169.254/latest",
    "https://localhost/x",
    "https://localhost./x",
    "https://intranet/x",
    "https://box.local/x",
    "https://svc.internal/x",
    "https://cdn.example.com\\x",
])
def test_presigned_rejects_private_or_malformed(url):
    _denied(policy.check_presigned_url, url, resolve_dns=False)


def test_presigned_public_literal_ip_allowed():
    assert policy.check_presigned_url("https://8.8.8.8/blob?sig=1") == "https://8.8.8.8/blob?sig=1"


def test_presigned_dns_private_resolution_rejected(monkeypatch):
    monkeypatch.setattr(policy, "_resolved_addresses", lambda host: [ipaddress.ip_address("10.1.2.3")])
    _denied(policy.check_presigned_url, "https://cdn.example.com/x")
    monkeypatch.setattr(policy, "_resolved_addresses", lambda host: [ipaddress.ip_address("93.184.216.34"), ipaddress.ip_address("127.0.0.1")])
    _denied(policy.check_presigned_url, "https://cdn.example.com/x")  # 하나라도 사설이면 거부


def test_presigned_dns_failure_rejected_and_public_allowed(monkeypatch):
    monkeypatch.setattr(policy, "_resolved_addresses", lambda host: [])
    _denied(policy.check_presigned_url, "https://nx.example.com/x")
    monkeypatch.setattr(policy, "_resolved_addresses", lambda host: [ipaddress.ip_address("93.184.216.34")])
    assert policy.check_presigned_url("https://cdn.example.com/x") == "https://cdn.example.com/x"


def test_bearer_kw_blocks_redirects():
    assert policy.BEARER_KW == {"allow_redirects": False}
    assert policy.is_redirect(302) and not policy.is_redirect(200)
