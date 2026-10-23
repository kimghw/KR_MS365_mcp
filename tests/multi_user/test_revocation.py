"""시나리오 5 — 폐기·비활성화·연결 해제·삭제가 다음 요청부터 반영된다 (②-6.5, ②-7.6, ②-10 A05·L01).

| 동작 | 다음 요청 |
|------|-----------|
| `revoke_key(kid)` | 그 키 401. **같은 사용자의 다른 유효 키**·Graph 연결은 유지 |
| `set_status(disabled)` | 403 `account_inactive`, 다시 enable 하면 정상 |
| Graph 연결 해제(`DELETE /auth/graph/connection`) | bearer 는 유효, 도구 호출은 `graph_not_connected` |
| `bump_auth_epoch` | 풀 항목이 새 epoch 로 다시 만들어지고 이전 서비스는 닫힌다 |
| 실행 중 폐기 | 결과를 돌려주지 않는다 (`account_inactive`) |
| `delete_user` | 401, 사용자 디렉터리 삭제, B 는 영향 없음 |
"""

import pytest
from starlette.testclient import TestClient

from mcp_common import service_pool
from mcp_common.user_paths import paths_for
from session import identity_registry as ir
from session.tests.mu_support import ALICE
from tests.multi_user.harness import GATEWAY_BASE_URL, READ_TOOLS, issue_extra_key, rpc

DOMAIN = "calendar"
TOOL, ARGS = READ_TOOLS[DOMAIN]


def _ok(c, key):
    result = c.call(key, TOOL, ARGS)
    assert not result.is_error, result.text[:300]
    return result


def test_revoked_key_is_401_on_next_request(mu, alice, bob):
    with mu.client(DOMAIN) as c:
        _ok(c, alice.key)
        assert ir.revoke_key(alice.kid) is True
        for body in (rpc("tools/list"), rpc("tools/call", {"name": TOOL, "arguments": ARGS})):
            r = c.post(body, alice.key)
            assert r.status_code == 401
        _ok(c, bob.key)


def test_revoking_one_key_keeps_users_other_key_working_without_waiting_for_cache(mu, alice):
    """②-6.5: 키 하나 폐기는 그 키만 막는다. 다른 유효 키로는 Graph 호출이 계속 돼야 한다."""
    second = issue_extra_key(alice, ["calendar"])
    with mu.client(DOMAIN) as c:
        _ok(c, alice.key)  # 첫 키로 풀에 사용자 서비스가 만들어진다
        ir.revoke_key(alice.kid)
        assert c.post(rpc("tools/list"), alice.key).status_code == 401
        assert c.post(rpc("tools/list"), second).status_code == 200
        result = c.call(second, TOOL, ARGS)
    assert not result.is_error, result.text[:300]


def test_rotated_key_keeps_working_after_old_key_overlap_expires(mu, alice):
    """회전 후 이전 키의 24시간 중첩이 끝나도, 서비스가 계속 쓰이던 사용자는 새 키로 정상 동작해야 한다."""
    from datetime import timedelta

    from session._mu_common import iso, utcnow

    with mu.client(DOMAIN) as c:
        _ok(c, alice.key)
        rotated = ir.rotate_key(alice.kid)
        _ok(c, rotated.key)
        # 24시간이 지난 것처럼 이전 키 만료 (풀 항목은 계속 쓰여 유휴 TTL 에 걸리지 않음)
        ir.get_user(alice.user_key).store().shorten_credential(alice.kid, iso(utcnow() - timedelta(seconds=1)))
        assert c.post(rpc("tools/list"), alice.key).status_code == 401
        result = c.call(rotated.key, TOOL, ARGS)
    assert not result.is_error, result.text[:300]


def test_rotated_key_old_and_new_both_work_during_overlap(mu, alice):
    with mu.client(DOMAIN) as c:
        _ok(c, alice.key)
        rotated = ir.rotate_key(alice.kid)
        _ok(c, rotated.key)
        _ok(c, alice.key)  # 24시간 중첩 기간


def test_disabled_account_is_403_then_enabled_again(mu, alice, bob):
    with mu.client(DOMAIN) as c:
        _ok(c, alice.key)
        ir.set_status(alice.user_key, "disabled")
        r = c.post(rpc("tools/call", {"name": TOOL, "arguments": ARGS}), alice.key)
        assert r.status_code == 403 and r.json()["error"] == "account_inactive"
        _ok(c, bob.key)
        ir.set_status(alice.user_key, "enable")
        _ok(c, alice.key)


def test_graph_disconnect_then_tool_call_is_graph_not_connected(mu, alice, bob):
    from session.auth_gateway import create_app

    with mu.client(DOMAIN) as c:
        _ok(c, alice.key)
        with TestClient(create_app(entra=mu.entra, jwks_client=mu.entra.jwks), base_url=GATEWAY_BASE_URL) as gw:
            r = gw.delete("/auth/graph/connection", headers={"Authorization": f"Bearer {alice.key}"})
        assert r.status_code == 200, r.text
        assert c.post(rpc("tools/list"), alice.key).status_code == 200  # bearer 는 유효
        mu.graph.reset()
        result = c.call(alice.key, TOOL, ARGS)
        assert result.is_error and result.error_code == "graph_not_connected", result.text[:300]
        assert result.payload.get("connect_url")
        assert mu.graph.calls == []
        _ok(c, bob.key)
    assert ir.get_user(alice.user_key).store().token_app_ids() == []


def test_auth_epoch_change_rebuilds_pool_entry_and_closes_old_service(mu, alice):
    pool = service_pool.get_service_pool()
    created, closed = [], []
    original = pool._factories[DOMAIN]

    async def _factory(principal, paths, tokens):
        service = await original(principal, paths, tokens)
        created.append((principal.auth_epoch, service))
        real_close = service.close

        async def _close():
            closed.append(principal.auth_epoch)
            await real_close()

        service.close = _close
        return service

    mu.monkeypatch.setitem(pool._factories, DOMAIN, _factory)
    with mu.client(DOMAIN) as c:
        _ok(c, alice.key)
        _ok(c, alice.key)
        assert len(created) == 1
        old_epoch = created[0][0]
        ir.bump_auth_epoch(alice.user_key)
        _ok(c, alice.key)
        assert [epoch for epoch, _ in created] == [old_epoch, old_epoch + 1]
        assert closed == [old_epoch]
        keys = {k for k in pool._entries if k[0] == alice.user_key}
        assert keys == {(alice.user_key, DOMAIN, old_epoch + 1)}


@pytest.mark.parametrize("action", ["revoke", "disable", "disconnect"])
def test_revocation_while_call_in_flight_withholds_result(mu, alice, action):
    def _revoke_midway(call):
        if mu.graph.owner(call) == alice.account:
            if action == "revoke":
                ir.revoke_key(alice.kid)
            elif action == "disable":
                ir.set_status(alice.user_key, "disabled")
            else:
                ir.disconnect_graph(alice.user_key)

    mu.graph.on("GET", r"/me/events$", {"value": [{"id": "e1", "subject": "ALICE-PRIVATE-EVENT"}]})
    with mu.client(DOMAIN) as c:
        mu.graph.gate = _revoke_midway
        result = c.call(alice.key, TOOL, ARGS)
        mu.graph.gate = None
    assert result.is_error, result.text[:300]
    assert result.error_code in ("account_inactive", "graph_not_connected"), result.text[:300]
    assert "ALICE-PRIVATE-EVENT" not in result.text


def test_delete_user_after_use_blocks_requests_and_removes_data(mu, alice, bob):
    """여러 도메인 서비스가 풀에 살아 있는 상태에서 삭제해도 파일 삭제가 끝나야 한다(열린 핸들 없음)."""
    uses = {
        "onenote": ("sync_onenote_db", {}),
        "teams": ("handler_teams_sync_chats", {}),
        "file_handler": ("save_file_metadata", {"file_url": "https://x.example/a.docx", "keywords": ["k"]}),
        "outlook": READ_TOOLS["outlook"],
        DOMAIN: (TOOL, ARGS),
    }
    clients = {d: mu.client(d) for d in uses}
    opened = {d: cm.__enter__() for d, cm in clients.items()}
    try:
        for domain, (tool, args) in uses.items():
            result = opened[domain].call(alice.key, tool, args)
            assert not result.is_error, (domain, result.text[:300])
        root = paths_for(alice.user_key).root
        assert root.exists()

        ir.delete_user(alice.user_key)

        assert not root.exists()
        for domain in uses:
            assert opened[domain].post(rpc("tools/list"), alice.key).status_code == 401
        result = opened[DOMAIN].call(bob.key, TOOL, ARGS)
        assert not result.is_error
    finally:
        for cm in clients.values():
            cm.__exit__(None, None, None)


def test_reinstated_user_after_delete_does_not_reuse_stale_service(mu):
    """삭제 후 같은 (tid, oid) 를 reinstate 하면 auth_epoch 가 0 부터 다시 시작한다.

    풀 키 `(user_key, domain, auth_epoch)` 가 삭제 전 항목과 겹치면 이전 계정 수명의 서비스
    (이전 principal·폐기된 키에 묶인 토큰 공급자)가 재사용된다.
    """
    first = mu.onboard(ALICE)
    with mu.client(DOMAIN) as c:
        _ok(c, first.key)
        ir.delete_user(first.user_key)
        ir.register_user(ALICE.tenant_id, ALICE.object_id, reinstate=True)
        from tests.multi_user.harness import User, connect_user

        key = ir.issue_key(first.user_key, None).key
        again = User(ALICE, first.user_key, key)
        assert connect_user(mu.entra, again).status_code == 200
        result = c.call(again.key, TOOL, ARGS)
    assert not result.is_error, result.text[:300]
