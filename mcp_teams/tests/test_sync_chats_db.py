"""채팅 동기화: 상대방 선택이 멤버 순서에 안 흔들리는지, 부분 목록이 기존 채팅을 비활성화하지 않는지."""

import sqlite3

from mcp_teams.teams_db_manager import TeamsDBManager

ME = "me@example.com"
PEER = {"display_name": "Peer", "email": "peer@example.com"}
SELF = {"display_name": "Me", "email": "ME@example.com"}  # 대소문자 달라도 본인


def _chat(cid, members):
    return {"id": cid, "chatType": "oneOnOne", "topic": "", "members": members}


async def test_peer_is_the_other_member_regardless_of_order(tmp_path):
    path = str(tmp_path / "t.db")
    await TeamsDBManager(path).sync_chats_to_db(ME, [_chat("c1", [PEER, SELF]), _chat("c2", [SELF, PEER])])
    rows = sqlite3.connect(path).execute(
        "SELECT chat_id, peer_user_email FROM teams_chats ORDER BY chat_id"
    ).fetchall()
    assert rows == [("c1", "peer@example.com"), ("c2", "peer@example.com")]


async def test_partial_list_does_not_deactivate_existing_chats(tmp_path):
    path = str(tmp_path / "t.db")
    db = TeamsDBManager(path)
    await db.sync_chats_to_db(ME, [_chat("c1", [PEER, SELF]), _chat("c2", [PEER, SELF])])

    partial = await db.sync_chats_to_db(ME, [_chat("c1", [PEER, SELF])], deactivate_missing=False)
    assert partial["deactivated"] == 0
    active = sqlite3.connect(path).execute("SELECT COUNT(*) FROM teams_chats WHERE is_active").fetchone()[0]
    assert active == 2

    full = await db.sync_chats_to_db(ME, [_chat("c1", [PEER, SELF])])
    assert full["deactivated"] == 1
