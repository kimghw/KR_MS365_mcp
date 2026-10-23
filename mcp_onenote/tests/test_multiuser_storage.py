"""
OneNote 저장소 소유자 격리 (spec/spec_멀티유저.md ②-2.5, ②-7.3, ②-10 D01–D03).

- mode 0 IDOR 회귀: 같은 공용 DB 를 두 이메일이 써도 요약 조회·삭제·변경이력이 소유자 범위다.
- 같은 파일에 두 owner_key 를 넣어 SQL 의 owner 조건 자체를 검증한다(파일 분리에 기대지 않음).
- mode 0 구버전 DB 자동 이전: 데이터 손실 없이 owner_key 채움 + 복합 유일성.
- mode 1 DB 에서는 소유자를 추정하지 않는다.

네트워크·실제 사용자 DB 를 쓰지 않는다.
"""

import logging
import sqlite3

import pytest

from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.testing import make_principal, multi_user_mode
from mcp_common.user_paths import paths_for
from mcp_onenote.onenote_db_service import OneNoteDBService
from mcp_onenote.storage_schema import LegacySchemaError, ensure_storage

A = "alice@contoso.com"
B = "bob@contoso.com"
KA = "a" * 64
KB = "b" * 64


def _summary(db, owner_email, page_id, text):
    assert db.save_summary(
        page_id=page_id, user_id=owner_email, page_title=f"title-{text}", summary=text,
        paragraph_summaries=[], keywords=[text], content_hash=f"h-{text}",
    )


# ----------------------------------------------------------------------
# mode 0 — 공용 DB, 소유자 = user_id
# ----------------------------------------------------------------------
class TestMode0OwnerScope:
    @pytest.fixture
    def db(self, tmp_path):
        return OneNoteDBService(str(tmp_path / "onenote.db"))

    def test_summary_read_of_other_users_page_returns_nothing(self, db):
        _summary(db, B, "P-B", "bob-secret")
        assert db.get_summary("P-B", user_id=A) is None
        assert db.get_summary("P-B", user_id=B)["summary"] == "bob-secret"

    def test_summary_delete_of_other_users_page_is_noop(self, db):
        _summary(db, B, "P-B", "bob-secret")
        assert db.delete_summary("P-B", user_id=A) is False
        assert db.get_summary("P-B", user_id=B)["summary"] == "bob-secret"

    def test_page_changes_are_owner_scoped(self, db):
        assert db.save_page_change(page_id="P-B", user_id=B, action="append", content_snippet="x")
        assert db.get_page_changes("P-B", user_id=A) == []
        assert len(db.get_page_changes("P-B", user_id=B)) == 1
        assert db.get_user_changes(A) == []

    def test_same_page_id_keeps_independent_rows(self, db):
        _summary(db, A, "P1", "alice-view")
        _summary(db, B, "P1", "bob-view")
        assert db.save_item(A, "page", "P1", "Alice title")
        assert db.save_item(B, "page", "P1", "Bob title")
        assert db.get_summary("P1", user_id=A)["summary"] == "alice-view"
        assert db.get_summary("P1", user_id=B)["summary"] == "bob-view"
        assert [i["item_name"] for i in db.list_items(A, "page")] == ["Alice title"]
        assert [i["item_name"] for i in db.list_items(B, "page")] == ["Bob title"]
        # 한쪽 삭제가 다른 쪽을 지우지 않는다
        assert db.delete_item(A, "P1") is True
        assert [i["item_id"] for i in db.list_items(B, "page")] == ["P1"]

    def test_empty_item_name_upsert_keeps_existing_name(self, db):
        assert db.save_item(A, "page", "P1", "Original")
        assert db.save_item(A, "page", "P1", "", update_accessed=True)
        assert db.list_items(A, "page")[0]["item_name"] == "Original"

    def test_missing_owner_never_runs_unscoped_sql(self, db):
        for call in (
            lambda: db.get_summary("P1", user_id=None),
            lambda: db.delete_summary("P1", user_id=""),
            lambda: db.get_page_changes("P1", user_id=None),
            lambda: db.list_items(None),
        ):
            with pytest.raises(ValueError):
                call()

    def test_owner_key_is_not_returned(self, db):
        _summary(db, A, "P1", "s")
        db.save_item(A, "page", "P1", "t")
        assert "owner_key" not in db.get_summary("P1", user_id=A)
        assert "owner_key" not in db.list_items(A)[0]


# ----------------------------------------------------------------------
# mode 0 — 구버전 DB 자동 이전
# ----------------------------------------------------------------------
_LEGACY_SQL = """
CREATE TABLE onenote_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    item_type TEXT NOT NULL CHECK(item_type IN ('section', 'page')),
    item_id TEXT NOT NULL UNIQUE,
    item_name TEXT NOT NULL,
    notebook_id TEXT, notebook_name TEXT, section_id TEXT, section_name TEXT,
    web_url TEXT, last_accessed TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_onenote_items_user_type ON onenote_items(user_id, item_type);
CREATE TABLE onenote_page_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    page_title TEXT, summary TEXT, paragraph_summaries TEXT, keywords TEXT,
    content_hash TEXT, summarized_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE onenote_page_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id TEXT NOT NULL, user_id TEXT NOT NULL, action TEXT NOT NULL,
    content_snippet TEXT, target TEXT, content_hash TEXT, previous_hash TEXT,
    change_summary TEXT, change_keywords TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO onenote_items (user_id, item_type, item_id, item_name, web_url, last_accessed)
    VALUES ('alice@contoso.com', 'page', 'P1', 'Legacy page', 'https://x', '2026-01-01T00:00:00Z'),
           ('alice@contoso.com', 'section', 'S1', 'Legacy section', NULL, NULL);
INSERT INTO onenote_page_summaries (page_id, user_id, page_title, summary, keywords, content_hash)
    VALUES ('P1', 'alice@contoso.com', 'Legacy page', 'legacy summary', '["k"]', 'h1');
INSERT INTO onenote_page_changes (page_id, user_id, action, change_summary)
    VALUES ('P1', 'alice@contoso.com', 'append', 'legacy change');
"""

# 더 오래된 세대: parent_id/parent_name + 이름 UNIQUE
_OLDEST_SQL = """
CREATE TABLE onenote_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    item_type TEXT NOT NULL,
    item_id TEXT NOT NULL UNIQUE,
    item_name TEXT NOT NULL,
    parent_id TEXT, parent_name TEXT, last_accessed TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, item_type, item_name)
);
INSERT INTO onenote_items (user_id, item_type, item_id, item_name, parent_id, parent_name)
    VALUES ('alice@contoso.com', 'page', 'P1', 'Same name', 'S1', 'Sec 1');
"""


def _make_legacy(path, script):
    conn = sqlite3.connect(path)
    conn.executescript(script)
    conn.commit()
    conn.close()


class TestMode0LegacyMigration:
    def test_legacy_db_is_migrated_without_data_loss(self, tmp_path):
        path = str(tmp_path / "onenote.db")
        _make_legacy(path, _LEGACY_SQL)

        db = OneNoteDBService(path)

        pages = db.list_items(A, "page")
        assert [(p["item_id"], p["item_name"], p["web_url"]) for p in pages] == [("P1", "Legacy page", "https://x")]
        assert db.get_recent_items(A, "page")[0]["item_id"] == "P1"
        assert db.get_summary("P1", user_id=A)["summary"] == "legacy summary"
        assert db.get_page_changes("P1", user_id=A)[0]["change_summary"] == "legacy change"

        conn = sqlite3.connect(path)
        for table in ("onenote_items", "onenote_page_summaries", "onenote_page_changes"):
            rows = conn.execute(f"SELECT owner_key, user_id FROM {table}").fetchall()
            assert rows and all(owner == user for owner, user in rows)
        assert conn.execute("SELECT COUNT(*) FROM onenote_items").fetchone()[0] == 2
        conn.close()

        # 이전 후에는 다른 소유자가 같은 page_id 를 가질 수 있다 (복합 유일성)
        _summary(db, B, "P1", "bob")
        assert db.get_summary("P1", user_id=A)["summary"] == "legacy summary"

        # 다시 열어도(이미 이전됨) 데이터 그대로
        db2 = OneNoteDBService(path)
        assert db2.get_summary("P1", user_id=B)["summary"] == "bob"
        assert len(db2.list_items(A)) == 2

    def test_oldest_generation_schema_is_migrated(self, tmp_path):
        path = str(tmp_path / "onenote.db")
        _make_legacy(path, _OLDEST_SQL)

        db = OneNoteDBService(path)

        page = db.list_items(A, "page")[0]
        assert (page["item_id"], page["section_id"], page["section_name"]) == ("P1", "S1", "Sec 1")
        # 이름 UNIQUE 가 걷혀 다른 섹션의 동명 페이지가 저장된다
        assert db.save_item(A, "page", "P2", "Same name", section_id="S2")
        assert len(db.list_items(A, "page")) == 2


# ----------------------------------------------------------------------
# mode 1 성격 — 고정 owner_key
# ----------------------------------------------------------------------
class TestFixedOwnerSqlScope:
    """같은 파일에 두 owner 를 넣어도 SQL owner 조건이 막는다 (D01–D03)."""

    @pytest.fixture
    def pair(self, tmp_path):
        path = str(tmp_path / "shared.db")
        return OneNoteDBService(path, owner_key=KA), OneNoteDBService(path, owner_key=KB)

    def test_d01_read_other_owner_summary_returns_nothing(self, pair):
        alice, bob = pair
        _summary(bob, B, "P-B", "bob-secret")
        # 호출자가 B 의 이메일을 user_id 로 넘겨도 소유자는 고정이다
        assert alice.get_summary("P-B", user_id=B) is None
        assert alice.list_summaries(B) == []

    def test_d02_delete_other_owner_rows_is_noop(self, pair):
        alice, bob = pair
        _summary(bob, B, "P1", "bob")
        bob.save_item(B, "page", "P1", "Bob page")
        bob.save_page_change(page_id="P1", user_id=B, action="append")
        assert alice.delete_item(B, "P1") is False
        assert alice.delete_summary("P1", user_id=B) is False
        assert bob.get_summary("P1", user_id=B)["summary"] == "bob"
        assert len(bob.list_items(B)) == 1
        assert len(bob.get_page_changes("P1", user_id=B)) == 1

    def test_d03_same_page_id_independent_summary_and_history(self, pair):
        alice, bob = pair
        _summary(alice, A, "P1", "alice")
        _summary(bob, B, "P1", "bob")
        alice.save_page_change(page_id="P1", user_id=A, action="append", change_summary="a1")
        bob.save_page_change(page_id="P1", user_id=B, action="replace", change_summary="b1")
        bob.save_page_change(page_id="P1", user_id=B, action="append", change_summary="b2")
        assert alice.get_summary("P1", user_id=A)["summary"] == "alice"
        assert bob.get_summary("P1", user_id=B)["summary"] == "bob"
        assert [c["change_summary"] for c in alice.get_page_changes("P1", user_id=A)] == ["a1"]
        assert sorted(c["change_summary"] for c in bob.get_page_changes("P1", user_id=B)) == ["b1", "b2"]

    def test_legacy_table_in_user_db_is_rejected(self, tmp_path):
        path = str(tmp_path / "onenote.db")
        _make_legacy(path, _LEGACY_SQL)
        with pytest.raises(LegacySchemaError):
            OneNoteDBService(path, owner_key=KA)
        # 실패한 초기화는 아무것도 바꾸지 않는다
        conn = sqlite3.connect(path)
        assert "owner_key" not in [r[1] for r in conn.execute("PRAGMA table_info(onenote_items)")]
        conn.close()

    def test_relative_path_with_owner_is_rejected(self):
        with pytest.raises(ValueError):
            OneNoteDBService("database/onenote.db", owner_key=KA)

    def test_logs_do_not_contain_titles_or_ids(self, pair, caplog):
        alice, _ = pair
        caplog.set_level(logging.DEBUG, logger="mcp_onenote")
        alice.save_item(A, "page", "SECRET-PAGE-ID", "SECRET-TITLE")
        _summary(alice, A, "SECRET-PAGE-ID", "SECRET-SUMMARY")
        alice.save_page_change(page_id="SECRET-PAGE-ID", user_id=A, action="append")
        alice.delete_item(A, "SECRET-PAGE-ID")
        text = "\n".join(r.getMessage() for r in caplog.records)
        for secret in ("SECRET-PAGE-ID", "SECRET-TITLE", "SECRET-SUMMARY", A):
            assert secret not in text


class TestMultiUserMode:
    def test_db_service_without_owner_fails_in_mode1(self, tmp_path):
        with multi_user_mode(tmp_path / "root"):
            with pytest.raises(RuntimeError):
                OneNoteDBService(str(tmp_path / "x.db"))

    def test_ensure_storage_creates_user_db_only(self, tmp_path):
        with multi_user_mode(tmp_path / "root"):
            alice = make_principal(A)
            paths = paths_for(alice)
            ensure_storage(alice, paths)
            assert paths.onenote_db.is_file()
            conn = sqlite3.connect(paths.onenote_db)
            cols = [r[1] for r in conn.execute("PRAGMA table_info(onenote_page_summaries)")]
            conn.close()
            assert "owner_key" in cols

            bob = make_principal(B)
            with pytest.raises(SecurityError) as exc:
                ensure_storage(bob, paths)  # 다른 사용자의 경로
            assert exc.value.code == ErrorCode.NOT_FOUND


# ----------------------------------------------------------------------
# N06 — 이전(migration) 동결은 생성 시점만이 아니라 **쓰기마다** 다시 본다 (astra 3차)
# ----------------------------------------------------------------------
from mcp_common.security_contracts import StartupConfigError  # noqa: E402
from mcp_common.security_policy import ENV_MIGRATION_OVERRIDE, MIGRATION_LOCK_NAME  # noqa: E402


async def test_mode0_writer_stops_when_lock_appears_after_construction(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_MIGRATION_OVERRIDE, raising=False)
    db = OneNoteDBService(str(tmp_path / "onenote.db"))  # lock 이 없을 때 열린 writer
    assert db.save_item(A, "page", "P1", "before", update_accessed=True)
    _summary(db, A, "P1", "s-before")
    assert db.save_page_change(page_id="P1", user_id=A, action="append")

    (tmp_path / MIGRATION_LOCK_NAME).write_text("{}", encoding="utf-8")  # 이전 계획이 잠금을 둔다

    writes = [
        lambda: db.save_item(A, "page", "P2", "after"),
        lambda: db.save_summary("P2", A, "t", "s", [], [], "h"),
        lambda: db.save_page_change(page_id="P1", user_id=A, action="replace"),
        lambda: db.delete_item(A, "P1"),
        lambda: db.delete_summary("P1", user_id=A),
    ]
    for write in writes:
        with pytest.raises(StartupConfigError):
            write()
    with pytest.raises(StartupConfigError):
        await db.sync_pages_to_db(A, [{"id": "P3", "title": "t"}])

    # 아무것도 바뀌지 않았고, 읽기는 계속 된다
    assert [i["item_id"] for i in db.list_items(A, "page")] == ["P1"]
    assert db.get_summary("P1", user_id=A)["summary"] == "s-before"
    assert len(db.get_page_changes("P1", user_id=A)) == 1
    assert db.get_recent_items(A, "page")[0]["item_id"] == "P1"

    # 운영자가 알고 여는 경우(override)만 다시 쓸 수 있다
    monkeypatch.setenv(ENV_MIGRATION_OVERRIDE, "1")
    assert db.save_item(A, "page", "P2", "override")
    assert len(db.list_items(A, "page")) == 2


def test_fixed_owner_db_is_not_subject_to_legacy_freeze(tmp_path, monkeypatch):
    """mode 1 식(소유자 고정) DB 는 사용자 전용이라 동결 대상이 아니다 — lock 이 있어도 쓴다."""
    monkeypatch.delenv(ENV_MIGRATION_OVERRIDE, raising=False)
    (tmp_path / MIGRATION_LOCK_NAME).write_text("{}", encoding="utf-8")
    db = OneNoteDBService(str(tmp_path / "onenote.db"), owner_key=KA)
    assert db.save_item(A, "page", "P1", "t")
    _summary(db, A, "P1", "s")
    assert db.delete_summary("P1", user_id=A) is True
