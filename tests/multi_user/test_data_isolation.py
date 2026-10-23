"""시나리오 4 — 같은 Graph 자원을 쓰는 A·B 의 로컬 데이터 분리 (②-7.3, ②-10 D01~D05·F03).

| 도메인 | 공유 식별자 | 검증 |
|--------|-------------|------|
| OneNote | 같은 page_id | items·summaries·changes 가 사용자 DB 에 따로, A 의 요약 조회·삭제(Graph 404)가 B 를 못 건드림 |
| Teams | 같은 chat_id | 한글 이름·활성 상태가 사용자별, 검색이 섞이지 않음 |
| Outlook | 같은 첨부 파일명 | 각자 `files/downloads/outlook/` 에 따로 저장, 응답에 절대경로 없음 |
| FileHandler | 같은 file_url | 메타데이터 검색·조회·삭제가 사용자별 |

전부 실제 HTTP `/mcp` → 실제 서비스 풀 → 사용자별 DB 경로로 돈다.
"""

import base64
import json
import re
import sqlite3
from pathlib import Path

import pytest

from mcp_common.user_paths import paths_for
from tests.multi_user.harness import FakeHttpResponse, contains_bytes, files_under

SHARED_PAGE = "1-shared-page-0001"
SHARED_CHAT = "19:shared-chat@thread.v2"


def _rows(db: Path, sql: str, *params):
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _by_token(mu, mapping):
    """Graph 응답을 호출 토큰의 주인(Account)별로 고른다."""

    def _route(call):
        owner = mu.graph.owner(call)
        if owner is None or owner not in mapping:
            return FakeHttpResponse(401, {"error": {"code": "InvalidAuthenticationToken"}})
        value = mapping[owner]
        return value(call) if callable(value) else value

    return _route


def _no_absolute_paths(text: str, mu) -> None:
    assert str(mu.root) not in text
    assert str(mu.root).replace("\\", "/") not in text
    assert not re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", text), "응답에 드라이브 절대경로가 있다"


# ----------------------------------------------------------------------
# OneNote
# ----------------------------------------------------------------------
def _onenote_page(title: str) -> dict:
    return {
        "id": SHARED_PAGE,
        "title": title,
        "createdDateTime": "2026-10-01T00:00:00Z",
        "lastModifiedDateTime": "2026-10-02T00:00:00Z",
        "links": {"oneNoteWebUrl": {"href": "https://onenote.example/shared"}},
        "parentSection": {"id": "1-sec", "displayName": "Shared Section",
                          "parentNotebook": {"id": "1-nb", "displayName": "Shared NB"}},
    }


def _seed_summary(user, page_id: str, text: str) -> None:
    from mcp_onenote.onenote_db_service import OneNoteDBService

    db = OneNoteDBService(paths_for(user.user_key).onenote_db, owner_key=user.user_key)
    assert db.save_summary(page_id, user.email, f"title-{text}", text, [], [text.lower()], f"hash-{text}")


def test_onenote_same_page_id_keeps_items_summaries_and_changes_per_user(mu, alice, bob):
    mu.graph.on("GET", r"/me/onenote/pages$", _by_token(mu, {
        alice.account: {"value": [_onenote_page("Alice view")]},
        bob.account: {"value": [_onenote_page("Bob view")]},
    }))
    mu.graph.on("PATCH", rf"/me/onenote/pages/{SHARED_PAGE}/content$", FakeHttpResponse(204, None))

    with mu.client("onenote") as c:
        for user in (alice, bob):
            synced = c.call(user.key, "sync_onenote_db", {})
            assert not synced.is_error and synced.payload["pages_synced"] == 1, synced.text[:300]

        a_db, b_db = paths_for(alice.user_key).onenote_db, paths_for(bob.user_key).onenote_db
        assert a_db != b_db
        assert [r["item_name"] for r in _rows(a_db, "SELECT item_name FROM onenote_items WHERE item_type='page'")] == ["Alice view"]
        assert [r["item_name"] for r in _rows(b_db, "SELECT item_name FROM onenote_items WHERE item_type='page'")] == ["Bob view"]

        # 변경 이력: A 의 append 는 A 의 DB 에만 남는다
        appended = c.call(alice.key, "write_onenote", {"action": "append", "page_id": SHARED_PAGE,
                                                       "content": "<p>alice addition</p>"})
        assert not appended.is_error, appended.text[:300]
        assert len(_rows(a_db, "SELECT * FROM onenote_page_changes")) == 1
        assert _rows(b_db, "SELECT * FROM onenote_page_changes") == []

        # 요약: 같은 page_id 라도 각자의 요약 (D03), B 만 가진 페이지 요약은 A 에게 없다 (D01)
        _seed_summary(alice, SHARED_PAGE, "ALICE-SUMMARY")
        _seed_summary(bob, SHARED_PAGE, "BOB-SUMMARY")
        _seed_summary(bob, "1-bob-only-page", "BOB-PRIVATE")
        a_sum = c.call(alice.key, "read_onenote", {"action": "get_summary", "page_id": SHARED_PAGE})
        b_sum = c.call(bob.key, "read_onenote", {"action": "get_summary", "page_id": SHARED_PAGE})
        assert a_sum.payload["summary"] == "ALICE-SUMMARY" and "BOB" not in a_sum.text
        assert b_sum.payload["summary"] == "BOB-SUMMARY" and "ALICE" not in b_sum.text
        private = c.call(alice.key, "read_onenote", {"action": "get_summary", "page_id": "1-bob-only-page"})
        assert not private.is_error and private.payload.get("has_summary") is False
        assert "BOB-PRIVATE" not in private.text

        # D02: A 의 토큰으로는 이미 없는 페이지(Graph 404) — A 의 행만 정리, B 는 그대로
        mu.graph.on("DELETE", rf"/me/onenote/pages/{SHARED_PAGE}$", FakeHttpResponse(404, {"error": {"code": "20102"}}))
        deleted = c.call(alice.key, "delete_onenote", {"page_id": SHARED_PAGE})
        assert not deleted.is_error and deleted.payload.get("already_deleted") is True, deleted.text[:300]

    assert _rows(a_db, "SELECT * FROM onenote_items WHERE item_id = ?", SHARED_PAGE) == []
    assert _rows(a_db, "SELECT * FROM onenote_page_summaries WHERE page_id = ?", SHARED_PAGE) == []
    assert [r["summary"] for r in _rows(b_db, "SELECT summary FROM onenote_page_summaries ORDER BY page_id")] == [
        "BOB-PRIVATE", "BOB-SUMMARY"]
    assert len(_rows(b_db, "SELECT * FROM onenote_items WHERE item_id = ?", SHARED_PAGE)) == 1
    # 모든 행의 소유자 키가 그 DB 의 주인이다
    for db, user in ((a_db, alice), (b_db, bob)):
        for table in ("onenote_items", "onenote_page_summaries", "onenote_page_changes"):
            owners = {r["owner_key"] for r in _rows(db, f"SELECT owner_key FROM {table}")}
            assert owners <= {user.user_key}, (table, owners)
    assert contains_bytes(paths_for(alice.user_key).root, b"BOB-SUMMARY") == []


# ----------------------------------------------------------------------
# Teams
# ----------------------------------------------------------------------
def _chat(topic: str, chat_id: str = SHARED_CHAT, peer: str = "") -> dict:
    members = []
    chat_type = "group"
    if peer:  # 1:1 — 본인 + 상대방
        chat_type, topic = "oneOnOne", None
        members = [{"user": {"id": "u-peer", "displayName": peer, "email": "peer@fabrikam.com"}},
                   {"user": {"id": "u-bob", "displayName": "Bob", "email": "bob@contoso.com"}}]
    return {"id": chat_id, "topic": topic, "chatType": chat_type, "createdDateTime": "2026-10-01T00:00:00Z",
            "lastUpdatedDateTime": "2026-10-02T00:00:00Z", "members": members}


def test_teams_same_chat_id_keeps_names_and_active_state_per_user(mu, alice, bob):
    chats = {alice.account: {"value": [_chat("Project Shared")]},
             bob.account: {"value": [_chat("Project Shared"), _chat("", "19:bob-only@thread.v2", peer="Bob Private")]}}
    mu.graph.on("GET", r"/me/chats$", _by_token(mu, {k: (lambda call, k=k: chats[k]) for k in chats}))

    with mu.client("teams") as c:
        for user in (alice, bob):
            synced = c.call(user.key, "handler_teams_sync_chats", {})
            assert not synced.is_error, synced.text[:300]

        assert not c.call(alice.key, "handler_teams_save_korean_name", {"topic_kr": "알파방", "chat_id": SHARED_CHAT}).is_error
        assert not c.call(bob.key, "handler_teams_save_korean_name", {"topic_kr": "베타방", "chat_id": SHARED_CHAT}).is_error

        def find(user, name):
            return c.call(user.key, "handler_teams_find_chat_by_name", {"recipient_name": name}).payload

        assert find(alice, "알파방")["chat_id"] == SHARED_CHAT
        assert find(alice, "베타방")["found"] is False
        assert find(alice, "Bob Private")["found"] is False
        assert find(bob, "베타방")["chat_id"] == SHARED_CHAT
        assert find(bob, "알파방")["found"] is False

        without = c.call(bob.key, "handler_teams_get_chats_without_korean", {}).payload
        assert [ch.get("chat_id") for ch in without["chats"]] == ["19:bob-only@thread.v2"]

        # A 가 채팅을 나가 A 의 목록이 비면 A 의 행만 비활성화된다
        chats[alice.account] = {"value": [_chat("Other", "19:alice-other@thread.v2")]}
        assert not c.call(alice.key, "handler_teams_sync_chats", {}).is_error

    a_db, b_db = paths_for(alice.user_key).teams_db, paths_for(bob.user_key).teams_db
    a_shared = _rows(a_db, "SELECT topic_kr, is_active FROM teams_chats WHERE chat_id = ?", SHARED_CHAT)
    b_shared = _rows(b_db, "SELECT topic_kr, is_active FROM teams_chats WHERE chat_id = ?", SHARED_CHAT)
    assert a_shared == [{"topic_kr": "알파방", "is_active": 0}]
    assert b_shared == [{"topic_kr": "베타방", "is_active": 1}]
    assert contains_bytes(paths_for(alice.user_key).root, "베타방".encode()) == []
    # Teams 상태는 auth.db 가 아니라 teams.db 에 있다
    assert "teams_chats" not in {r["name"] for r in _rows(paths_for(alice.user_key).auth_db,
                                                           "SELECT name FROM sqlite_master WHERE type='table'")}


# ----------------------------------------------------------------------
# Outlook 첨부 다운로드
# ----------------------------------------------------------------------
def _mail(payload: bytes) -> dict:
    return {
        "id": "m1",
        "subject": "Quarterly report",
        "receivedDateTime": "2026-10-01T09:00:00Z",
        "from": {"emailAddress": {"name": "Sender", "address": "sender@fabrikam.com"}},
        "body": {"contentType": "text", "content": "body text"},
        "hasAttachments": True,
        "attachments": [{
            "id": "att0", "name": "report.pdf", "contentType": "application/pdf",
            "@odata.type": "#microsoft.graph.fileAttachment",
            "contentBytes": base64.b64encode(payload).decode("ascii"),
        }],
    }


def test_outlook_same_attachment_name_saved_per_user_without_absolute_paths(mu, alice, bob):
    mails = {alice.account: _mail(b"ALICE-PDF"), bob.account: _mail(b"BOB-PDF")}
    mu.graph.on("POST", r"/\$batch$", _by_token(mu, {
        k: {"responses": [{"id": "1", "status": 200, "body": v}]} for k, v in mails.items()
    }))

    with mu.client("outlook") as c:
        results = {u.user_key: c.call(u.key, "mail_attachment_download",
                                      {"message_attachment_ids": ["m1"], "flat_folder": True})
                   for u in (alice, bob)}

    for user, data in ((alice, b"ALICE-PDF"), (bob, b"BOB-PDF")):
        result = results[user.user_key]
        assert not result.is_error, result.text[:500]
        _no_absolute_paths(result.text, mu)
        refs = result.payload.get("saved_attachments")
        assert refs and all(not Path(r).is_absolute() and r.startswith("downloads/outlook/") for r in refs), refs
        paths = paths_for(user.user_key)
        saved = [p for p in files_under(paths.downloads_for("outlook")) if p.name == "report.pdf"]
        assert len(saved) == 1 and saved[0].read_bytes() == data
    # 데이터 루트 전체에서 첨부 내용은 각 주인의 사용자 영역에만 있다
    assert contains_bytes(mu.root, b"ALICE-PDF") and all(
        str(paths_for(alice.user_key).files) in str(p) for p in contains_bytes(mu.root, b"ALICE-PDF"))
    assert all(str(paths_for(bob.user_key).files) in str(p) for p in contains_bytes(mu.root, b"BOB-PDF"))
    # 각 사용자의 $batch 는 자기 토큰·자기 메일함 경로만
    for call in mu.graph.calls:
        owner = mu.graph.owner(call)
        inner = json.dumps(call.kwargs.get("json") or {})
        assert owner is not None
        other = bob if owner == alice.account else alice
        assert other.email not in inner


# ----------------------------------------------------------------------
# FileHandler 메타데이터
# ----------------------------------------------------------------------
def test_file_handler_metadata_is_per_user(mu, alice, bob):
    url = "https://contoso.sharepoint.com/sites/x/Shared%20Documents/plan.docx"
    with mu.client("file_handler") as c:
        assert not c.call(alice.key, "save_file_metadata", {"file_url": url, "keywords": ["alpha"]}).is_error
        assert not c.call(bob.key, "save_file_metadata", {"file_url": url, "keywords": ["beta"],
                                                          "additional_metadata": {"note": "bob-note"}}).is_error

        a_all = c.call(alice.key, "search_metadata", {}).payload
        assert [r["keywords"] for r in a_all["results"]] == [["alpha"]]
        assert c.call(alice.key, "search_metadata", {"keyword": "beta"}).payload["count"] == 0
        assert c.call(bob.key, "get_file_metadata", {"file_url": url}).payload["metadata"]["keywords"] == ["beta"]

        # A 가 같은 URL 을 지워도 B 의 메타데이터는 남는다 (D05)
        assert c.call(alice.key, "delete_file_metadata", {"file_url": url}).payload["deleted"] is True
        assert c.call(alice.key, "get_file_metadata", {"file_url": url}).payload["found"] is False
        b_meta = c.call(bob.key, "get_file_metadata", {"file_url": url})
        assert b_meta.payload["found"] is True and b_meta.payload["metadata"]["metadata"]["note"] == "bob-note"
        _no_absolute_paths(b_meta.text, mu)

    a_db, b_db = paths_for(alice.user_key).metadata_db, paths_for(bob.user_key).metadata_db
    assert a_db.exists() and b_db.exists() and a_db != b_db
    assert contains_bytes(paths_for(alice.user_key).root, b"bob-note") == []


# ----------------------------------------------------------------------
# I05 — 같은 이메일, 다른 (tid, oid)
# ----------------------------------------------------------------------
def test_same_email_different_object_id_is_a_separate_user(mu, alice):
    from session.tests.mu_support import TENANT, Account

    twin_account = Account(TENANT, "cccccccc-0000-4000-8000-00000000000c", alice.email)
    twin = mu.onboard(twin_account)
    assert twin.user_key != alice.user_key
    url = "https://contoso.sharepoint.com/twin.docx"
    with mu.client("file_handler") as fh:
        assert not fh.call(alice.key, "save_file_metadata", {"file_url": url, "keywords": ["original"]}).is_error
        assert not fh.call(twin.key, "save_file_metadata", {"file_url": url, "keywords": ["twin"]}).is_error
        assert fh.call(twin.key, "get_file_metadata", {"file_url": url}).payload["metadata"]["keywords"] == ["twin"]
        assert fh.call(alice.key, "get_file_metadata", {"file_url": url}).payload["metadata"]["keywords"] == ["original"]
    with mu.client("calendar") as c:
        # 이메일이 같으니 user_email 일치 검사는 통과하지만, 토큰·서비스는 user_key 로 고른다
        result = c.call(twin.key, "list_events", {"user_email": alice.email})
        assert not result.is_error, result.text[:300]
    assert mu.graph.calls
    for call in mu.graph.calls:
        assert mu.graph.owner(call) == twin_account
        assert call.principal_key == twin.user_key
    assert paths_for(twin.user_key).root != paths_for(alice.user_key).root
