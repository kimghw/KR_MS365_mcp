"""
Outlook 멀티유저 — 처리 메일 메타데이터 격리 (spec/spec_멀티유저.md ②-7.3 Outlook metadata 행, F04).

mode 1 은 공용 `mail_metadata.json` 대신 사용자 `db/outlook.db` 를 쓰고, 모든 SQL 에
owner 조건이 있다. 같은 DB 파일을 가리켜도 owner 가 다르면 섞이지 않는다.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.testing import bound

from mcp_outlook.mail_attachment import BatchAttachmentHandler
from mcp_outlook.storage_schema import OutlookMetadataStore, ensure_outlook_db, ensure_storage
from mcp_outlook.tests.multiuser_fakes import *  # noqa: F401,F403 - fixtures

MAIL = {"subject": "s", "from": {"emailAddress": {"address": "x@fabrikam.com"}}, "attachments": [{}]}


def test_each_user_has_own_db(mu, alice, bob, alice_paths, bob_paths):
    ensure_storage(alice, alice_paths)
    ensure_storage(bob, bob_paths)
    store_a = OutlookMetadataStore.for_paths(alice_paths)
    store_b = OutlookMetadataStore.for_paths(bob_paths)

    with bound(alice):
        store_a.add_processed_mail("m1", MAIL, "downloads/outlook/f", ["downloads/outlook/f/a.pdf"])
        assert store_a.is_duplicate("m1")
        assert store_a.get_processed_mail("m1")["saved_files"] == ["downloads/outlook/f/a.pdf"]
    with bound(bob):
        assert not store_b.is_duplicate("m1")
        assert store_b.filter_new_messages(["m1", "m2"]) == ["m1", "m2"]
        assert store_b.get_processed_count() == 0
    assert alice_paths.outlook_db.parent == alice_paths.db_dir
    assert not list(mu.rglob("mail_metadata.json"))


def test_owner_condition_even_in_shared_file(mu, alice, bob, alice_paths, tmp_path):
    db = ensure_outlook_db(alice_paths)
    store_a = OutlookMetadataStore(db, alice.user_key)
    store_b = OutlookMetadataStore(db, bob.user_key)  # 같은 파일, 다른 owner

    store_a.add_processed_mail("same-id", MAIL, "", [])
    store_b.add_processed_mail("other-id", MAIL, "", [])
    assert store_a.get_processed_message_ids() == ["same-id"]
    assert store_b.get_processed_message_ids() == ["other-id"]
    assert not store_b.is_duplicate("same-id")
    assert store_b.get_processed_mail("same-id") is None


def test_store_refuses_other_principal(mu, alice, bob, alice_paths):
    ensure_outlook_db(alice_paths)
    store_a = OutlookMetadataStore.for_paths(alice_paths)
    with bound(bob), pytest.raises(SecurityError) as err:
        store_a.is_duplicate("m1")
    assert err.value.code == ErrorCode.NOT_FOUND
    with pytest.raises(SecurityError):
        ensure_storage(bob, alice_paths)


def test_concurrent_writes_no_lost_update(mu, alice, alice_paths):
    ensure_outlook_db(alice_paths)
    store = OutlookMetadataStore.for_paths(alice_paths)

    def _add(i):
        store.add_processed_mail(f"m{i}", MAIL, "", [f"f{i}"])

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(_add, range(60)))
    assert store.get_processed_count() == 60
    assert sorted(store.get_processed_message_ids()) == sorted(f"m{i}" for i in range(60))


async def test_skip_duplicates_is_per_user(
    mu, alice, bob, alice_paths, bob_paths, alice_tokens, bob_tokens, monkeypatch
):
    mail = mail_with_attachments("m1", [{"name": "a.pdf", "data": b"x"}])
    install_http(monkeypatch, batch_router({alice_tokens.token: mail, bob_tokens.token: mail}))

    with bound(alice):
        first = await BatchAttachmentHandler(token_provider=alice_tokens, paths=alice_paths).fetch_and_save(
            ALICE_EMAIL, ["m1"]
        )
        again = await BatchAttachmentHandler(token_provider=alice_tokens, paths=alice_paths).fetch_and_save(
            ALICE_EMAIL, ["m1"]
        )
    with bound(bob):
        other = await BatchAttachmentHandler(token_provider=bob_tokens, paths=bob_paths).fetch_and_save(
            BOB_EMAIL, ["m1"]
        )

    assert first["processed"] == 1
    assert again["skipped_duplicates"] == 1  # A 의 처리 이력
    assert other["skipped_duplicates"] == 0  # B 는 A 의 이력과 무관
    assert other["processed"] == 1
