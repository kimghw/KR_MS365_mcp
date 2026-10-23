"""이전 도구 테스트 지원 — legacy(mode 0) 저장소 만들기 + 매핑 파일.

실제 사용자 DB·네트워크를 쓰지 않는다. legacy 스키마는 mode 0 코드가 만들던 형태를 그대로 적는다
(owner_key 이전 전). `upgrade_mode0=True` 면 현재 mode 0 서버가 기동하며 하는 owner_key 자동 이전
(`storage_schema.ensure_schema(legacy_backfill=True)`)까지 적용한다.
"""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Optional

from mcp_common.testing import make_principal

ALICE = make_principal("alice@contoso.com")
BOB = make_principal("bob@contoso.com")
ALICE_EMAIL = "alice@contoso.com"
ALICE_OLD_EMAIL = "Alice.Old@Contoso.com"
BOB_EMAIL = "bob@contoso.com"
CAROL_EMAIL = "carol@contoso.com"   # legacy 에는 있지만 매핑하지 않는 사용자
#: 토큰이 어디에도 복사되지 않았는지 찾을 표식
TOKEN_CANARY = "CANARY-LEGACY-TOKEN-0123456789abcdef0123456789abcdef"

LEGACY_AUTH_DDL = """
CREATE TABLE azure_app_config (
    client_id TEXT PRIMARY KEY, client_secret TEXT NOT NULL, tenant_id TEXT NOT NULL DEFAULT 'common',
    redirect_uri TEXT NOT NULL DEFAULT 'http://localhost:5000/callback', app_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE azure_user_info (
    user_email TEXT PRIMARY KEY, object_id TEXT UNIQUE, display_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE azure_token_info (
    user_email TEXT PRIMARY KEY, access_token TEXT NOT NULL, refresh_token TEXT, scope TEXT,
    access_token_expires_at TIMESTAMP NOT NULL, refresh_token_expires_at TIMESTAMP, id_token TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE teams_chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, chat_id TEXT NOT NULL,
    chat_type TEXT DEFAULT 'unknown', topic TEXT, topic_kr TEXT, member_count INTEGER DEFAULT 0,
    members_json TEXT, peer_user_name TEXT, peer_user_email TEXT, last_message_preview TEXT,
    last_message_time TEXT, last_sent_at TEXT, last_received_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_sync_at TEXT, is_active BOOLEAN DEFAULT TRUE, UNIQUE(user_id, chat_id)
);
"""

LEGACY_ONENOTE_DDL = """
CREATE TABLE onenote_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
    item_type TEXT NOT NULL CHECK(item_type IN ('section', 'page')), item_id TEXT NOT NULL UNIQUE,
    item_name TEXT NOT NULL, notebook_id TEXT, notebook_name TEXT, section_id TEXT, section_name TEXT,
    web_url TEXT, last_accessed TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE onenote_page_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT, page_id TEXT NOT NULL UNIQUE, user_id TEXT NOT NULL,
    page_title TEXT, summary TEXT, paragraph_summaries TEXT, keywords TEXT, content_hash TEXT,
    summarized_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE onenote_page_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, page_id TEXT NOT NULL, user_id TEXT NOT NULL, action TEXT NOT NULL,
    content_snippet TEXT, target TEXT, content_hash TEXT, previous_hash TEXT, change_summary TEXT,
    change_keywords TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def make_legacy(root: Path, *, upgrade_mode0: bool = False, alice_object_id: Optional[str] = None) -> Dict[str, Path]:
    """legacy 저장소 한 벌. 반환: 주요 경로."""
    root.mkdir(parents=True, exist_ok=True)
    db_dir = root / "database"
    db_dir.mkdir(exist_ok=True)

    auth = db_dir / "auth.db"
    with closing(sqlite3.connect(auth)) as conn:
        conn.executescript(LEGACY_AUTH_DDL)
        conn.execute("INSERT INTO azure_app_config (client_id, client_secret) VALUES ('app', ?)", (TOKEN_CANARY + "-secret",))
        for email, oid in ((ALICE_EMAIL, alice_object_id or ALICE.object_id), (BOB_EMAIL, BOB.object_id),
                           (CAROL_EMAIL, "cccccccc-0000-4000-8000-00000000000c")):
            conn.execute("INSERT INTO azure_user_info (user_email, object_id) VALUES (?, ?)", (email, oid))
            conn.execute(
                "INSERT INTO azure_token_info (user_email, access_token, refresh_token, access_token_expires_at)"
                " VALUES (?, ?, ?, '2026-10-22T00:00:00')",
                (email, TOKEN_CANARY + "-access", TOKEN_CANARY + "-refresh"),
            )
        chats = [
            (ALICE_EMAIL, "chat-1", "Alice 1:1", "2026-10-01"),
            (ALICE_EMAIL, "chat-2", "Alice group", "2026-10-02"),
            (ALICE_OLD_EMAIL, "chat-1", "Alice 1:1 (old address)", "2026-09-01"),  # 병합 시 중복 → 격리
            (BOB_EMAIL, "chat-1", "Bob 1:1", "2026-10-03"),                        # 같은 chat_id, 다른 사용자
            (CAROL_EMAIL, "chat-3", "Carol only", "2026-10-04"),                   # 매핑 없음 → 격리
        ]
        conn.executemany(
            "INSERT INTO teams_chats (user_id, chat_id, topic, updated_at) VALUES (?, ?, ?, ?)", chats
        )
        conn.commit()

    onenote = db_dir / "onenote.db"
    with closing(sqlite3.connect(onenote)) as conn:
        conn.executescript(LEGACY_ONENOTE_DDL)
        conn.executemany(
            "INSERT INTO onenote_items (user_id, item_type, item_id, item_name, section_id) VALUES (?, ?, ?, ?, ?)",
            [
                (ALICE_EMAIL, "section", "sec-a", "Alice section", None),
                (ALICE_OLD_EMAIL, "page", "page-a", "Alice page", "sec-a"),
                (BOB_EMAIL, "page", "page-b", "Bob page", "sec-b"),
                (CAROL_EMAIL, "page", "page-c", "Carol page", "sec-c"),
            ],
        )
        conn.executemany(
            "INSERT INTO onenote_page_summaries (page_id, user_id, summary) VALUES (?, ?, ?)",
            [("page-a", ALICE_EMAIL, "alice summary"), ("page-b", BOB_EMAIL, "bob summary")],
        )
        conn.executemany(
            "INSERT INTO onenote_page_changes (page_id, user_id, action) VALUES (?, ?, ?)",
            [("page-a", ALICE_EMAIL, "append"), ("page-a", ALICE_EMAIL, "replace"),
             ("page-b", BOB_EMAIL, "append"), ("page-c", CAROL_EMAIL, "append")],
        )
        conn.commit()

    if upgrade_mode0:
        from mcp_onenote.storage_schema import ensure_schema as onenote_schema
        from mcp_teams.storage_schema import ensure_schema as teams_schema

        onenote_schema(onenote, legacy_backfill=True)
        teams_schema(auth, legacy_backfill=True)

    downloads = root / "downloads"
    output = root / "output"
    att_a = _write(downloads / "alice" / "att1.pdf", b"%PDF alice attachment")
    _write(downloads / "bob" / "att2.pdf", b"%PDF bob attachment")
    _write(downloads / "shared" / "unknown.txt", b"nobody claimed this")
    report = _write(output / "alice" / "report.txt", b"alice report")
    _write(output / "mcp_outlook.log", b"2026-10-22 log line with alice@contoso.com")
    _write(output / "bundles" / "ms365-mcp-x" / "README.md", b"bundle artifact")

    mail = {
        "processed_messages": {
            "msg-a": {"subject": "A", "from": "x@contoso.com", "received_datetime": "2026-10-01T00:00:00Z",
                      "folder_path": str(downloads / "alice"), "saved_files": [str(att_a), "https://contoso-my.sharepoint.com/a"],
                      "processed_at": "2026-10-01T01:00:00", "attachment_count": 1},
            "msg-b": {"subject": "B", "from": "y@contoso.com", "saved_files": [], "processed_at": "2026-10-02T01:00:00"},
        },
        "last_updated": "2026-10-02T01:00:00",
    }
    _write(downloads / "mail_metadata.json", json.dumps(mail).encode("utf-8"))

    metadata = root / "metadata.db"
    with closing(sqlite3.connect(metadata)) as conn:
        conn.execute("CREATE TABLE metadata (file_url TEXT PRIMARY KEY, keywords TEXT, metadata TEXT,"
                     " created_at TEXT, updated_at TEXT)")
        conn.executemany(
            "INSERT INTO metadata VALUES (?, ?, ?, '2026-10-01', '2026-10-01')",
            [(str(report), "report,alice", '{"pages": 1}'),
             ("https://contoso.sharepoint.com/sites/x/doc.docx", "shared", "{}"),
             (str(root / "elsewhere" / "orphan.pdf"), "orphan", "{}")],
        )
        conn.commit()
    return {"root": root, "auth_db": auth, "onenote_db": onenote, "metadata_db": metadata,
            "downloads": downloads, "output": output, "report": report, "att_a": att_a}


def mapping_doc(legacy: Dict[str, Path], **owners: Any) -> Dict[str, Any]:
    doc_owners: Dict[str, Any] = {
        "metadata_db_rows": {
            str(legacy["report"]): ALICE_EMAIL,
            "https://contoso.sharepoint.com/sites/x/doc.docx": BOB_EMAIL,
            str(legacy["root"] / "elsewhere" / "orphan.pdf"): ALICE_EMAIL,  # 이전되지 않는 로컬 경로 → 격리
        },
        "mail_metadata_rows": {"msg-a": ALICE_EMAIL},
        "paths": [
            {"path": "downloads/alice", "owner": ALICE_EMAIL},
            {"path": "downloads/bob", "owner": BOB_EMAIL},
            {"path": "output/alice", "owner": ALICE_EMAIL},
        ],
    }
    doc_owners.update(owners)
    return {
        "version": 1,
        "users": [
            {"legacy_email": ALICE_EMAIL, "tenant_id": ALICE.tenant_id, "object_id": ALICE.object_id},
            {"legacy_email": ALICE_OLD_EMAIL, "tenant_id": ALICE.tenant_id, "object_id": ALICE.object_id},
            {"legacy_email": BOB_EMAIL, "tenant_id": BOB.tenant_id, "object_id": BOB.object_id},
        ],
        "owners": doc_owners,
    }


def write_mapping(path: Path, doc: Dict[str, Any]) -> Path:
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def count(db: Path, sql: str, params=()) -> int:
    with closing(sqlite3.connect(db)) as conn:
        return int(conn.execute(sql, params).fetchone()[0])
