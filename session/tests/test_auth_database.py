"""refresh_token_expires_at 이 새 refresh_token 발급 때마다 +90일로 밀리는지(sliding window)."""

import sqlite3

from session.auth_database import AuthDatabase

OLD = "2020-01-01T00:00:00+00:00"


def _expiry(path):
    return sqlite3.connect(path).execute("SELECT refresh_token_expires_at FROM azure_token_info").fetchone()[0]


def test_refresh_expiry_slides_only_when_new_refresh_token_arrives(tmp_path):
    path = str(tmp_path / "auth.db")
    db = AuthDatabase(path)
    db.save_token("u@x", {"access_token": "a1", "refresh_token": "r1", "expires_at": "2026-01-01T00:00:00+00:00"})

    conn = sqlite3.connect(path)
    conn.execute("UPDATE azure_token_info SET refresh_token_expires_at = ?", (OLD,))
    conn.commit()
    conn.close()

    # access token 만 갱신 (refresh_token 없음) → 만료 시각 유지
    db.save_token("u@x", {"access_token": "a2", "expires_at": "2026-01-01T01:00:00+00:00"})
    assert _expiry(path) == OLD

    # 새 refresh_token 발급 → 만료 시각이 앞으로 밀린다
    db.save_token("u@x", {"access_token": "a3", "refresh_token": "r2", "expires_at": "2026-01-01T02:00:00+00:00"})
    assert _expiry(path) > "2026"
