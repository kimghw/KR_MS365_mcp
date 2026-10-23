"""멀티유저 이전 도구 — 정상 경로(A/B 두 사용자) + M01·M02·M03 (spec/spec_멀티유저.md ②-8, ②-10)."""

import json
import socket
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from tools.migrate_multi_user import applier, ports
from tools.migrate_multi_user.activator import run_activate
from tools.migrate_multi_user.applier import run_apply
from tools.migrate_multi_user.cli import build_parser, main
from tools.migrate_multi_user.common import MigrationError, current_layout, load_manifest
from tools.migrate_multi_user.planner import run_plan
from tools.migrate_multi_user.verifier import run_verify
from tools.tests.migration_support import (
    ALICE,
    ALICE_EMAIL,
    BOB,
    BOB_EMAIL,
    CAROL_EMAIL,
    TOKEN_CANARY,
    count,
    make_legacy,
    mapping_doc,
    write_mapping,
)


def _plan(env, doc=None, **legacy_kwargs):
    legacy = make_legacy(env.legacy_root, **legacy_kwargs)
    mapping = write_mapping(env.tmp / "mapping.json", doc or mapping_doc(legacy))
    layout = current_layout()
    result = run_plan(layout, mapping, env.legacy_root)
    return layout, legacy, result


def _all_bytes(directory: Path) -> bytes:
    return b"".join(p.read_bytes() for p in sorted(directory.rglob("*")) if p.is_file())


# ----------------------------------------------------------------------
# 정상 경로 — 두 사용자
# ----------------------------------------------------------------------
@pytest.mark.parametrize("upgrade_mode0", [False, True], ids=["pre_owner_schema", "mode0_owner_key"])
def test_happy_path_two_users(registered, upgrade_mode0):
    layout, legacy, result = _plan(registered, upgrade_mode0=upgrade_mode0)
    assert result["status"] == "ok", result["conflicts"]
    manifest = load_manifest(layout, Path(result["manifest"]))

    run_apply(layout, manifest)
    report = run_verify(layout, manifest)
    assert report["status"] == "ok", report["problems"]
    run_activate(layout, manifest, confirm=True)

    a, b = layout.live_paths(ALICE.user_key), layout.live_paths(BOB.user_key)
    # Teams — alice 는 chat-1(최신 행만) + chat-2, bob 은 같은 chat_id 를 따로 갖는다
    assert count(a.teams_db, "SELECT COUNT(*) FROM teams_chats WHERE owner_key=?", (ALICE.user_key,)) == 2
    assert count(b.teams_db, "SELECT COUNT(*) FROM teams_chats WHERE owner_key=?", (BOB.user_key,)) == 1
    with closing(sqlite3.connect(a.teams_db)) as conn:
        assert conn.execute("SELECT topic FROM teams_chats WHERE chat_id='chat-1'").fetchone()[0] == "Alice 1:1"
    # OneNote — 요약은 이전하지 않는다, 변경 이력은 사용자별
    assert count(a.onenote_db, "SELECT COUNT(*) FROM onenote_items WHERE owner_key=?", (ALICE.user_key,)) == 2
    assert count(b.onenote_db, "SELECT COUNT(*) FROM onenote_items WHERE owner_key=?", (BOB.user_key,)) == 1
    assert count(a.onenote_db, "SELECT COUNT(*) FROM onenote_page_summaries") == 0
    assert count(a.onenote_db, "SELECT COUNT(*) FROM onenote_page_changes") == 2
    assert count(b.onenote_db, "SELECT COUNT(*) FROM onenote_page_changes") == 1
    # 파일 — 자기 것만
    assert (a.files / "downloads" / "outlook" / "alice" / "att1.pdf").read_bytes() == b"%PDF alice attachment"
    assert (a.files / "output" / "alice" / "report.txt").is_file()
    assert (b.files / "downloads" / "outlook" / "bob" / "att2.pdf").is_file()
    assert not (a.files / "downloads" / "outlook" / "bob").exists()
    assert not list(b.files.rglob("report.txt"))

    # 런타임 저장소 클래스로 읽힌다 (mode 1 형식)
    from mcp_file_handler.metadata.storage import OwnedSQLiteStorage
    from mcp_outlook.storage_schema import OutlookMetadataStore

    mail = OutlookMetadataStore.for_paths(a).get_processed_mail("msg-a")
    assert mail["saved_files"] == ["downloads/outlook/alice/att1.pdf", "https://contoso-my.sharepoint.com/a"]
    assert OutlookMetadataStore.for_paths(b).get_processed_mail("msg-a") is None
    assert OwnedSQLiteStorage(a.metadata_db, ALICE.user_key).get("output/alice/report.txt")["keywords"] == ["report", "alice"]
    assert OwnedSQLiteStorage(b.metadata_db, BOB.user_key).get("https://contoso.sharepoint.com/sites/x/doc.docx")

    # 다른 사용자의 이메일이 자기 저장소에 없다, 매핑되지 않은 사용자는 어디에도 없다
    assert BOB_EMAIL.encode() not in _all_bytes(a.root)
    assert b"alice" not in _all_bytes(b.root).lower()
    users_bytes = _all_bytes(layout.live_users)
    assert CAROL_EMAIL.encode() not in users_bytes
    # 토큰·client secret 은 데이터 루트 어디에도 복사되지 않는다 (snapshot 포함)
    assert TOKEN_CANARY.encode() not in _all_bytes(layout.data_root)
    # 인증 저장소(등록 때 만든 것)는 그대로
    assert a.auth_db.is_file() and a.wrapped_dek.is_file()
    # 사용자 manifest 와 staging 정리
    assert json.loads(a.manifest.read_text(encoding="utf-8"))["migrations"][0]["run_id"] == manifest["run_id"]
    assert not layout.staging_paths(ALICE.user_key).root.exists()


def test_cli_output_has_no_emails_and_no_secret_options(registered, capsys):
    legacy = make_legacy(registered.legacy_root)
    mapping = write_mapping(registered.tmp / "mapping.json", mapping_doc(legacy))
    assert main(["plan", "--mapping", str(mapping), "--legacy-root", str(registered.legacy_root)], load_env=False) == 0
    assert main(["apply"], load_env=False) == 0
    assert main(["verify"], load_env=False) == 0
    out = capsys.readouterr().out
    for email in (ALICE_EMAIL, BOB_EMAIL, CAROL_EMAIL, "contoso.com"):
        assert email.lower() not in out.lower()
    assert ALICE.user_key in out
    options = {opt for action in build_parser()._subparsers._group_actions[0].choices.values()
               for a in action._actions for opt in a.option_strings}
    assert not [o for o in options if any(w in o for w in ("token", "secret", "key", "password"))]


def test_activate_requires_yes_and_refuses_when_servers_run(registered, monkeypatch):
    layout, _legacy, result = _plan(registered)
    manifest = load_manifest(layout, Path(result["manifest"]))
    run_apply(layout, manifest)
    with pytest.raises(MigrationError) as exc:
        run_activate(layout, manifest, confirm=False)
    assert exc.value.code == "confirm_required"

    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        monkeypatch.setattr(ports, "server_ports", lambda: [port])
        monkeypatch.setattr(ports, "running_server_ports", lambda: ports.listening(ports.server_ports()))
        with pytest.raises(MigrationError) as exc:
            run_activate(layout, manifest, confirm=True)
    assert exc.value.code == "servers_running"
    assert not ports.listening([port])
    assert layout.staging_paths(ALICE.user_key).db_dir.is_dir()  # 아무것도 옮기지 않았다
    assert not layout.live_paths(ALICE.user_key).onenote_db.exists()


def test_server_ports_come_from_param_spec_and_gateway(monkeypatch):
    monkeypatch.setenv("AZURE_REDIRECT_URI", "https://mcp.example.com:8443/auth/callback")
    monkeypatch.setenv("MS365_AUTH_GATEWAY_PORT", "5099")
    found = ports.server_ports()
    assert {5001, 5002, 5003, 5004, 5005, 5006, 5007, 5008}.issubset(found)
    assert 8443 in found and 5099 in found


def test_activate_refuses_when_target_already_has_data(registered):
    layout, _legacy, result = _plan(registered)
    manifest = load_manifest(layout, Path(result["manifest"]))
    run_apply(layout, manifest)
    live = layout.live_paths(BOB.user_key)
    live.db_dir.mkdir(parents=True, exist_ok=True)
    live.onenote_db.write_bytes(b"mode 1 data written before activation")
    with pytest.raises(MigrationError) as exc:
        run_activate(layout, manifest, confirm=True)
    assert exc.value.code == "target_not_empty"
    assert not layout.live_paths(ALICE.user_key).teams_db.exists()  # 사전 검사에서 멈춤 — 일부만 옮기지 않는다


# ----------------------------------------------------------------------
# M01 — 모호한 소유권은 격리, 전 사용자 복사 없음
# ----------------------------------------------------------------------
def test_m01_ambiguous_ownership_goes_to_quarantine(registered):
    legacy = make_legacy(registered.legacy_root)
    (legacy["downloads"] / "alice" / "x.txt").write_bytes(b"claimed twice")
    doc = mapping_doc(legacy, metadata_db_rows={}, mail_metadata_rows={}, paths=[
        {"path": "downloads/alice", "owner": ALICE_EMAIL},
        {"path": "downloads/alice/x.txt", "owner": BOB_EMAIL},   # 중첩 규칙 → 소유자 2명
        {"path": "downloads/bob", "owner": BOB_EMAIL},
    ])
    mapping = write_mapping(registered.tmp / "mapping.json", doc)
    layout = current_layout()
    result = run_plan(layout, mapping, registered.legacy_root)
    assert result["status"] == "ok"
    manifest = load_manifest(layout, Path(result["manifest"]))
    run_apply(layout, manifest)
    assert run_verify(layout, manifest)["status"] == "ok"

    for principal in (ALICE, BOB):
        paths = layout.staging_paths(principal.user_key)
        names = {p.name for p in paths.files.rglob("*") if p.is_file()}
        assert "x.txt" not in names and "unknown.txt" not in names and "report.txt" not in names
        assert count(paths.metadata_db, "SELECT COUNT(*) FROM file_metadata") == 0
        assert count(paths.outlook_db, "SELECT COUNT(*) FROM processed_messages") == 0
        assert "mcp_outlook.log" not in names

    qdir = layout.quarantine_dir(manifest["run_id"])
    index = {e["rel"]: e["reason"] for e in json.loads((qdir / "files.json").read_text(encoding="utf-8"))}
    assert index["alice/x.txt"] == "ambiguous_owner"
    assert index["shared/unknown.txt"] == "unowned"
    assert index["alice/report.txt"] == "unowned"      # output/alice 규칙을 빼서 소유자 없음
    assert index["mcp_outlook.log"] == "admin_only"
    assert "ms365-mcp-x/README.md" not in json.dumps(index)  # output/bundles 는 이전 대상 아님
    mail_q = json.loads((qdir / "json" / "mail_metadata.json").read_text(encoding="utf-8"))
    assert set(mail_q["reasons"]["unowned"]) == {"msg-a", "msg-b"}
    with closing(sqlite3.connect(qdir / "rows.db")) as conn:
        reasons = dict(conn.execute(
            "SELECT _quarantine_reason, COUNT(*) FROM onenote_db__onenote_page_summaries GROUP BY 1").fetchall())
        assert reasons == {"regenerate": 2}
        carol = conn.execute("SELECT COUNT(*) FROM auth_db__teams_chats WHERE user_id=?", (CAROL_EMAIL,)).fetchone()[0]
        assert carol == 1
        assert conn.execute("SELECT COUNT(*) FROM metadata_db__metadata").fetchone()[0] == 3


def test_m01_same_email_two_users_is_blocking_conflict(registered):
    legacy = make_legacy(registered.legacy_root)
    doc = mapping_doc(legacy, metadata_db_rows={}, mail_metadata_rows={}, paths=[])
    doc["users"].append({"legacy_email": ALICE_EMAIL.upper(), "tenant_id": BOB.tenant_id, "object_id": BOB.object_id})
    mapping = write_mapping(registered.tmp / "mapping.json", doc)
    layout = current_layout()
    result = run_plan(layout, mapping, registered.legacy_root)
    assert result["status"] == "conflicts"
    assert all(ALICE_EMAIL not in c.lower() for c in result["conflicts"])
    manifest = load_manifest(layout, Path(result["manifest"]))
    with pytest.raises(MigrationError) as exc:
        run_apply(layout, manifest)
    assert exc.value.code == "conflicts"
    assert not layout.staging_users.exists()


def test_unregistered_user_and_object_id_mismatch_are_conflicts(mu_env):
    from session.identity_registry import register_user

    register_user(ALICE.tenant_id, ALICE.object_id)  # BOB 은 등록하지 않는다
    layout, _legacy, result = _plan(mu_env, alice_object_id="dddddddd-0000-4000-8000-00000000000d")
    assert result["status"] == "conflicts"
    joined = "\n".join(result["conflicts"])
    assert BOB.user_key in joined and "registry" in joined
    assert "object_id" in joined


# ----------------------------------------------------------------------
# M02 — 중단 뒤 재실행: 중복·누락 없음
# ----------------------------------------------------------------------
def test_m02_interrupted_apply_resumes_without_duplicates(registered, monkeypatch):
    layout, _legacy, result = _plan(registered)
    manifest = load_manifest(layout, Path(result["manifest"]))
    first, second = (u["user_key"] for u in manifest["users"])  # apply 순서 (user_key 정렬)
    first_paths, second_paths = layout.staging_paths(first), layout.staging_paths(second)
    changes = {ALICE.user_key: 2, BOB.user_key: 1}
    chats = {ALICE.user_key: 2, BOB.user_key: 1}

    # 1) 단계 사이 중단 — 커밋된 단계는 표식으로 남는다
    def stop_after(label):
        if label == f"{first}:rows:onenote_page_changes":
            raise RuntimeError("power loss")

    monkeypatch.setattr(applier, "FAULT_HOOK", stop_after)
    with pytest.raises(RuntimeError):
        run_apply(layout, manifest)
    assert count(first_paths.onenote_db, "SELECT COUNT(*) FROM onenote_page_changes") == changes[first]
    assert not second_paths.root.exists()

    # 2) 단계 도중 중단 — 행을 넣은 뒤 표식 전에 죽으면 트랜잭션째 사라진다
    original = applier._row_writer

    def crashing_writer(snapshot, plan, user_key):
        write = original(snapshot, plan, user_key)
        if plan.key != "teams_chats" or user_key != second:
            return write

        def wrapped(conn):
            write(conn)
            raise RuntimeError("crash mid-step")

        return wrapped

    monkeypatch.setattr(applier, "FAULT_HOOK", None)
    monkeypatch.setattr(applier, "_row_writer", crashing_writer)
    with pytest.raises(RuntimeError):
        run_apply(layout, manifest)
    assert count(second_paths.teams_db, "SELECT COUNT(*) FROM teams_chats") == 0

    # 3) 정상 재실행 — 이어서 끝나고, 다시 돌려도 그대로
    monkeypatch.setattr(applier, "_row_writer", original)
    resumed = run_apply(layout, manifest)
    again = run_apply(layout, manifest)
    assert resumed["users"][first]["steps"]["rows:onenote_page_changes"] == "skipped"
    assert resumed["users"][second]["steps"]["rows:teams_chats"] == "applied"
    for user_key in (first, second):
        assert set(again["users"][user_key]["steps"].values()) == {"skipped"}
        assert again["users"][user_key]["files"]["copied"] == 0
        paths = layout.staging_paths(user_key)
        assert count(paths.onenote_db, "SELECT COUNT(*) FROM onenote_page_changes") == changes[user_key]
        assert count(paths.teams_db, "SELECT COUNT(*) FROM teams_chats") == chats[user_key]
        assert count(paths.onenote_db,
                     "SELECT COUNT(*) FROM _ms365_migration WHERE step_id='rows:onenote_page_changes'") == 1
    assert run_verify(layout, manifest)["status"] == "ok"


def test_m02_interrupted_activate_resumes(registered, monkeypatch):
    layout, _legacy, result = _plan(registered)
    manifest = load_manifest(layout, Path(result["manifest"]))
    run_apply(layout, manifest)

    from tools.migrate_multi_user import activator

    real_move = activator._move_area
    calls = {"n": 0}

    def flaky_move(layout_, manifest_, user, area):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("interrupted")
        return real_move(layout_, manifest_, user, area)

    monkeypatch.setattr(activator, "_move_area", flaky_move)
    with pytest.raises(OSError):
        run_activate(layout, manifest, confirm=True)
    monkeypatch.setattr(activator, "_move_area", real_move)
    assert run_activate(layout, manifest, confirm=True)["status"] == "ok"
    for principal in (ALICE, BOB):
        live = layout.live_paths(principal.user_key)
        assert live.onenote_db.is_file() and live.files.is_dir()
    assert run_activate(layout, manifest, confirm=True).get("already_active") is True


def test_apply_refuses_when_sources_or_manifest_change(registered):
    layout, legacy, result = _plan(registered)
    manifest_path = Path(result["manifest"])
    manifest = load_manifest(layout, manifest_path)
    with closing(sqlite3.connect(legacy["onenote_db"])) as conn:
        conn.execute("INSERT INTO onenote_page_changes (page_id, user_id, action) VALUES ('page-a', ?, 'late')",
                     (ALICE_EMAIL,))
        conn.commit()
    with pytest.raises(MigrationError) as exc:
        run_apply(layout, manifest)
    assert exc.value.code == "source_changed"

    manifest_path.write_text(manifest_path.read_text(encoding="utf-8").replace('"conflicts": []', '"conflicts": [] '),
                             encoding="utf-8")
    with pytest.raises(MigrationError) as exc:
        load_manifest(layout, manifest_path)
    assert exc.value.code == "manifest_tampered"


def test_apply_refuses_foreign_staging_without_reset(registered):
    layout, legacy, result = _plan(registered)
    run_apply(layout, load_manifest(layout, Path(result["manifest"])))
    mapping = write_mapping(registered.tmp / "mapping2.json", mapping_doc(legacy))
    second = run_plan(layout, mapping, registered.legacy_root)
    manifest2 = load_manifest(layout, Path(second["manifest"]))
    with pytest.raises(MigrationError) as exc:
        run_apply(layout, manifest2)
    assert exc.value.code == "staging_foreign"
    run_apply(layout, manifest2, reset_staging=True)
    assert run_verify(layout, manifest2)["status"] == "ok"


# ----------------------------------------------------------------------
# M03 — mode 0/1 저장소 교차 사용 거부
# ----------------------------------------------------------------------
def test_m03_requires_multi_user_mode_and_initialized_root(tmp_path, monkeypatch, capsys):
    from mcp_common.testing import multi_user_mode, single_user_mode

    with single_user_mode():
        assert main(["verify"], load_env=False) == 1
    assert "mode" in capsys.readouterr().err
    with multi_user_mode(tmp_path / "blank"):
        with pytest.raises(MigrationError) as exc:
            current_layout()
    assert exc.value.code == "not_initialized"


def test_m03_legacy_source_inside_data_root_is_refused(registered):
    legacy = make_legacy(registered.legacy_root)
    mapping = write_mapping(registered.tmp / "mapping.json", mapping_doc(legacy))
    layout = current_layout()
    user_db = layout.live_paths(ALICE.user_key).onenote_db
    with pytest.raises(MigrationError) as exc:
        run_plan(layout, mapping, registered.legacy_root, {"onenote_db": str(user_db)})
    assert exc.value.code == "cross_use"
    with pytest.raises(MigrationError) as exc:
        run_plan(layout, mapping, layout.data_root)
    assert exc.value.code == "cross_use"
    with pytest.raises(MigrationError) as exc:  # 데이터 루트를 legacy output/ 안에 둔 구성
        run_plan(layout, mapping, registered.legacy_root, {"output": str(layout.data_root.parent)})
    assert exc.value.code == "cross_use"


def test_m03_legacy_schema_in_user_store_is_not_backfilled(registered):
    layout, _legacy, result = _plan(registered)
    manifest = load_manifest(layout, Path(result["manifest"]))
    from tools.migrate_multi_user.common import write_json

    write_json(layout.staging_marker, {"run_id": manifest["run_id"]}, root=layout.migration)
    planted = layout.staging_paths(ALICE.user_key).onenote_db
    planted.parent.mkdir(parents=True)
    with closing(sqlite3.connect(planted)) as conn:
        conn.execute("CREATE TABLE onenote_items (id INTEGER PRIMARY KEY, user_id TEXT, item_type TEXT,"
                     " item_id TEXT UNIQUE, item_name TEXT)")
        conn.execute("INSERT INTO onenote_items (user_id, item_type, item_id, item_name) VALUES (?, 'page', 'p', 'x')",
                     (CAROL_EMAIL,))
        conn.commit()
    with pytest.raises(MigrationError) as exc:
        run_apply(layout, manifest)
    assert exc.value.code == "legacy_schema"
    with closing(sqlite3.connect(planted)) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(onenote_items)")}
    assert "owner_key" not in cols  # 소유자를 추정해 채우지 않았다


# ----------------------------------------------------------------------
# R10 — 쓰기 정지 구간: lock + activate 직전 원본·매핑·registry 재검사
# ----------------------------------------------------------------------
def _lock_files(legacy):
    """writer 대상 디렉터리 전부: database/(auth.db·onenote.db), legacy 루트(metadata.db·.json), downloads/, output/."""
    from tools.migrate_multi_user.freeze import LOCK_NAME

    return [directory / LOCK_NAME for directory in
            (legacy["auth_db"].parent, legacy["metadata_db"].parent, legacy["downloads"], legacy["output"])]


def test_r10_legacy_write_after_apply_makes_activate_refuse(registered):
    layout, legacy, result = _plan(registered)
    manifest = load_manifest(layout, Path(result["manifest"]))
    run_apply(layout, manifest)
    assert run_verify(layout, manifest)["status"] == "ok"

    # legacy writer 가 apply 뒤에 행을 하나 더 넣었다 (stdio 서버 등 — 포트로는 안 보인다)
    with closing(sqlite3.connect(legacy["onenote_db"])) as conn:
        conn.execute("INSERT INTO onenote_page_changes (page_id, user_id, action) VALUES ('page-a', ?, 'late')",
                     (ALICE_EMAIL,))
        conn.commit()
    with pytest.raises(MigrationError) as exc:
        run_activate(layout, manifest, confirm=True)
    assert exc.value.code == "source_changed"
    assert not (layout.checkpoints / f"{manifest['run_id']}.activate.json").exists()
    assert not layout.live_paths(ALICE.user_key).onenote_db.exists()  # 아무것도 옮기지 않았다

    # 파일 쪽 writer (downloads/ 에 새 첨부) 도 잡는다
    with closing(sqlite3.connect(legacy["onenote_db"])) as conn:
        conn.execute("DELETE FROM onenote_page_changes WHERE action='late'")
        conn.commit()
    (legacy["downloads"] / "alice" / "late.pdf").write_bytes(b"%PDF late")
    with pytest.raises(MigrationError) as exc:
        run_activate(layout, manifest, confirm=True)
    assert exc.value.code in ("source_changed", "plan_changed")


def test_r10_lock_created_checked_and_released(registered, capsys):
    layout, legacy, result = _plan(registered)
    manifest = load_manifest(layout, Path(result["manifest"]))
    locks = _lock_files(legacy)
    assert {Path(p) for p in result["locks"]} == set(locks)
    for lock in locks:
        record = json.loads(lock.read_text(encoding="utf-8"))
        assert record["run_id"] == manifest["run_id"] and record["deployment_id"] == layout.deployment_id
        assert "@" not in lock.read_text(encoding="utf-8")  # 이메일 없음

    # lock 이 사라지면(누군가 풀고 mode 0 서버를 돌렸을 수 있음) apply·activate 모두 거부
    saved = locks[0].read_bytes()
    locks[0].unlink()
    with pytest.raises(MigrationError) as exc:
        run_apply(layout, manifest)
    assert exc.value.code == "lock_missing"
    locks[0].write_bytes(saved)
    run_apply(layout, manifest)
    locks[0].write_bytes(saved + b"\n")  # 내용이 바뀌어도 거부
    with pytest.raises(MigrationError) as exc:
        run_activate(layout, manifest, confirm=True)
    assert exc.value.code == "lock_changed"
    locks[0].write_bytes(saved)
    assert run_activate(layout, manifest, confirm=True)["status"] == "ok"
    # activate 뒤에도 lock 은 남는다 — legacy 는 읽기 전용 보관
    assert all(lock.is_file() for lock in locks)

    # unlock 은 --yes 필수, 지우고 나면 두 번째는 no-op
    assert main(["unlock", "--manifest", manifest["_path"]], load_env=False) == 1
    assert all(lock.is_file() for lock in locks)
    assert main(["unlock", "--manifest", manifest["_path"], "--yes"], load_env=False) == 0
    out = capsys.readouterr().out
    assert not any(lock.exists() for lock in locks)
    assert "contoso.com" not in out.lower()


def test_r10_plan_refuses_running_servers_and_foreign_lock(registered, monkeypatch):
    legacy = make_legacy(registered.legacy_root)
    mapping = write_mapping(registered.tmp / "mapping.json", mapping_doc(legacy))
    layout = current_layout()
    monkeypatch.setattr(ports, "running_server_ports", lambda: [5001])
    with pytest.raises(MigrationError) as exc:
        run_plan(layout, mapping, registered.legacy_root)
    assert exc.value.code == "servers_running"
    assert not any(lock.exists() for lock in _lock_files(legacy))
    monkeypatch.setattr(ports, "running_server_ports", lambda: [])

    foreign = _lock_files(legacy)[0]
    foreign.write_text(json.dumps({"format": "ms365-migration-lock", "version": 1, "run_id": "x",
                                   "deployment_id": "0" * 32}), encoding="utf-8")
    with pytest.raises(MigrationError) as exc:
        run_plan(layout, mapping, registered.legacy_root)
    assert exc.value.code == "lock_foreign"
    foreign.write_text("not json", encoding="utf-8")
    with pytest.raises(MigrationError) as exc:
        run_plan(layout, mapping, registered.legacy_root)
    assert exc.value.code == "lock_foreign"
    foreign.unlink()

    # 같은 배포의 이전 run 이 남긴 lock 은 새 plan 이 이어받는다
    first = run_plan(layout, mapping, registered.legacy_root)
    second = run_plan(layout, mapping, registered.legacy_root)
    assert json.loads(foreign.read_text(encoding="utf-8"))["run_id"] == second["run_id"]
    with pytest.raises(MigrationError) as exc:  # 이어받긴 뒤의 옛 manifest 는 진행 불가
        run_apply(layout, load_manifest(layout, Path(first["manifest"])))
    assert exc.value.code == "lock_changed"


def test_r10_registry_change_after_apply_makes_activate_refuse(registered):
    from session.identity_registry import delete_user

    layout, _legacy, result = _plan(registered)
    manifest = load_manifest(layout, Path(result["manifest"]))
    run_apply(layout, manifest)
    delete_user(BOB.user_key)
    with pytest.raises(MigrationError) as exc:
        run_activate(layout, manifest, confirm=True)
    assert exc.value.code == "registry"
    assert not layout.live_paths(ALICE.user_key).onenote_db.exists()


# ----------------------------------------------------------------------
# R11 — activate 재개는 journal·경로 존재가 아니라 내용을 믿는다
# ----------------------------------------------------------------------
def _interrupt_activate(layout, manifest, monkeypatch, *, at_call: int, after_move: bool = False):
    from tools.migrate_multi_user import activator

    real_move = activator._move_area
    calls = {"n": 0}

    def flaky(layout_, manifest_, user, area):
        calls["n"] += 1
        if calls["n"] == at_call:
            if after_move:
                real_move(layout_, manifest_, user, area)  # rename 은 됐고 journal 쓰기 전에 죽음
            raise OSError("interrupted")
        return real_move(layout_, manifest_, user, area)

    monkeypatch.setattr(activator, "_move_area", flaky)
    with pytest.raises(OSError):
        run_activate(layout, manifest, confirm=True)
    monkeypatch.setattr(activator, "_move_area", real_move)


def test_r11_resume_refuses_tampered_live_or_staging(registered, monkeypatch):
    layout, _legacy, result = _plan(registered)
    manifest = load_manifest(layout, Path(result["manifest"]))
    run_apply(layout, manifest)
    first, second = sorted(u["user_key"] for u in manifest["users"])
    _interrupt_activate(layout, manifest, monkeypatch, at_call=3)  # first: db·files 완료, second: 아직

    # 1) 이미 옮긴(live) 영역이 바뀜 — 재개 거부, 남은 영역도 옮기지 않는다
    live_file = next(p for p in layout.live_paths(first).files.rglob("*") if p.is_file())
    original = live_file.read_bytes()
    live_file.write_bytes(b"tampered after move")
    with pytest.raises(MigrationError) as exc:
        run_activate(layout, manifest, confirm=True)
    assert exc.value.code == "activation_state"
    assert not layout.live_paths(second).onenote_db.exists()
    live_file.write_bytes(original)

    # 2) 아직 옮기지 않은 staging 영역에 다른 사용자의 행이 섞임 — 옮기기 직전 검증이 거부
    staging_db = layout.staging_paths(second).teams_db
    with closing(sqlite3.connect(staging_db)) as conn:
        conn.execute("INSERT INTO teams_chats (owner_key, user_id, chat_id) VALUES (?, ?, 'chat-x')",
                     (first, ALICE_EMAIL))
        conn.commit()
    with pytest.raises(MigrationError) as exc:
        run_activate(layout, manifest, confirm=True)
    assert exc.value.code == "verify_failed"
    assert not layout.live_paths(second).teams_db.exists()
    with closing(sqlite3.connect(staging_db)) as conn:
        conn.execute("DELETE FROM teams_chats WHERE chat_id='chat-x'")
        conn.commit()

    # 3) 깨끗해지면 이어서 끝나고, live 검증도 통과한다
    assert run_activate(layout, manifest, confirm=True)["status"] == "ok"
    assert run_verify(layout, manifest, live=True)["status"] == "ok"
    assert main(["verify", "--manifest", manifest["_path"], "--live"], load_env=False) == 0


def test_r11_rename_before_journal_is_verified_not_trusted(registered, monkeypatch):
    layout, _legacy, result = _plan(registered)
    manifest = load_manifest(layout, Path(result["manifest"]))
    run_apply(layout, manifest)
    first = sorted(u["user_key"] for u in manifest["users"])[0]
    # first 사용자의 db 가 rename 된 직후(journal 은 아직 pending) 중단
    _interrupt_activate(layout, manifest, monkeypatch, at_call=1, after_move=True)
    assert layout.live_paths(first).onenote_db.exists()
    assert not layout.staging_paths(first).db_dir.exists()

    with closing(sqlite3.connect(layout.live_paths(first).onenote_db)) as conn:
        conn.execute("INSERT INTO onenote_page_changes (owner_key, page_id, user_id, action) VALUES (?, 'p', ?, 'x')",
                     ("f" * 64, CAROL_EMAIL))
        conn.commit()
    with pytest.raises(MigrationError) as exc:  # "대상이 있으니 완료" 로 보지 않는다
        run_activate(layout, manifest, confirm=True)
    assert exc.value.code == "activation_state"
    with closing(sqlite3.connect(layout.live_paths(first).onenote_db)) as conn:
        conn.execute("DELETE FROM onenote_page_changes WHERE owner_key = ?", ("f" * 64,))
        conn.commit()
    assert run_activate(layout, manifest, confirm=True)["status"] == "ok"
    assert run_verify(layout, manifest, live=True)["status"] == "ok"


def test_r11_complete_journal_with_different_manifest_refuses(registered):
    layout, _legacy, result = _plan(registered)
    manifest = load_manifest(layout, Path(result["manifest"]))
    run_apply(layout, manifest)
    assert run_activate(layout, manifest, confirm=True)["status"] == "ok"
    journal_path = layout.checkpoints / f"{manifest['run_id']}.activate.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal["status"] == "complete"

    tampered = dict(journal, manifest_sha256="0" * 64)
    journal_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(MigrationError) as exc:
        run_activate(layout, manifest, confirm=True)
    assert exc.value.code == "activation_state"
    journal_path.write_text(json.dumps(dict(journal, run_id="other")), encoding="utf-8")
    with pytest.raises(MigrationError) as exc:
        run_activate(layout, manifest, confirm=True)
    assert exc.value.code == "activation_state"

    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    assert run_activate(layout, manifest, confirm=True).get("already_active") is True


# ----------------------------------------------------------------------
# N06 — lock 은 모든 legacy writer 대상 디렉터리에 (JSON 메타데이터·downloads·output 포함)
# ----------------------------------------------------------------------
def test_n06_locks_cover_every_writer_directory(registered):
    import shutil

    legacy = make_legacy(registered.legacy_root)
    shutil.rmtree(legacy["output"])  # 아직 없는 writer 디렉터리도 lock 을 위해 만든다
    mapping = write_mapping(registered.tmp / "mapping.json", mapping_doc(legacy))
    layout = current_layout()
    result = run_plan(layout, mapping, registered.legacy_root)
    assert result["status"] == "ok", result["conflicts"]
    manifest = load_manifest(layout, Path(result["manifest"]))

    locks = _lock_files(legacy)
    assert {Path(p) for p in result["locks"]} == set(locks) == {Path(e["path"]) for e in manifest["locks"]}
    assert {p.parent for p in locks} == {
        legacy["auth_db"].parent,                 # auth.db · onenote.db
        legacy["root"],                           # metadata.db · metadata.json
        legacy["downloads"],                      # mail_metadata.json · 첨부 파일
        legacy["output"],                         # 변환 결과 파일
    }
    assert all(p.is_file() for p in locks)
    # lock 자체는 이전 대상 파일도, 격리 대상도 아니다
    assert not any(f["rel"].endswith(".migration_lock") for f in manifest["files"])
    run_apply(layout, manifest)
    index = json.loads((layout.quarantine_dir(manifest["run_id"]) / "files.json").read_text(encoding="utf-8"))
    assert not any(".migration_lock" in e["rel"] for e in index)
    assert not list(layout.staging_users.rglob(".migration_lock"))

    # JSON 메타데이터·파일 디렉터리의 lock 하나만 사라져도 apply·activate 모두 거부
    for lock in (legacy["downloads"] / ".migration_lock", legacy["output"] / ".migration_lock"):
        saved = lock.read_bytes()
        lock.unlink()
        for step in (run_apply, lambda lay, man: run_activate(lay, man, confirm=True)):
            with pytest.raises(MigrationError) as exc:
                step(layout, manifest)
            assert exc.value.code == "lock_missing"
        lock.write_bytes(saved)
    assert run_activate(layout, manifest, confirm=True)["status"] == "ok"


# ----------------------------------------------------------------------
# N07 — DB 내용(payload) 변경을 staging·재개·live 검증이 잡는다
# ----------------------------------------------------------------------
def _update(db, sql, params=()):
    with closing(sqlite3.connect(db)) as conn:
        conn.execute(sql, params)
        conn.commit()


def test_n07_payload_tamper_detected_in_staging_resume_and_live(registered, monkeypatch, capsys):
    layout, _legacy, result = _plan(registered)
    manifest = load_manifest(layout, Path(result["manifest"]))
    run_apply(layout, manifest)
    for user_key in (ALICE.user_key, BOB.user_key):
        digests = manifest["digests"][user_key]
        assert set(digests) == {"onenote_items", "onenote_page_changes", "onenote_page_summaries", "teams_chats",
                                "file_metadata", "processed_messages", "processed_files"}
        assert all(set(d["columns"]).isdisjoint({"id", "created_at", "updated_at", "processed_at"}) for d in digests.values())
    assert run_verify(layout, manifest)["status"] == "ok"

    # 1) staging: 행 수·owner_key·user_id·표식은 그대로 두고 제목만 바꿈
    staging_db = layout.staging_paths(ALICE.user_key).onenote_db
    _update(staging_db, "UPDATE onenote_items SET item_name='renamed' WHERE item_id='page-a'")
    report = run_verify(layout, manifest)
    assert report["status"] == "failed"
    assert any("onenote_items: 내용 digest" in p for p in report["problems"])
    with pytest.raises(MigrationError) as exc:
        run_activate(layout, manifest, confirm=True)
    assert exc.value.code == "verify_failed"
    _update(staging_db, "UPDATE onenote_items SET item_name='Alice page' WHERE item_id='page-a'")
    assert run_verify(layout, manifest)["status"] == "ok"

    # 2) 재개: 이미 옮긴 live DB 의 ID 가 바뀜 — 행 수·owner 는 그대로
    first, second = sorted(u["user_key"] for u in manifest["users"])
    _interrupt_activate(layout, manifest, monkeypatch, at_call=3)
    live_db = layout.live_paths(first).teams_db
    with closing(sqlite3.connect(live_db)) as conn:
        (chat_id,) = conn.execute("SELECT chat_id FROM teams_chats ORDER BY chat_id LIMIT 1").fetchone()
    _update(live_db, "UPDATE teams_chats SET chat_id='chat-swapped' WHERE chat_id=?", (chat_id,))
    with pytest.raises(MigrationError) as exc:
        run_activate(layout, manifest, confirm=True)
    assert exc.value.code == "activation_state"
    assert not layout.live_paths(second).teams_db.exists()
    _update(live_db, "UPDATE teams_chats SET chat_id=? WHERE chat_id='chat-swapped'", (chat_id,))
    done = run_activate(layout, manifest, confirm=True)
    assert done["status"] == "ok" and done["completion"] == "now" and done["current_state"] == "verified"

    # 3) 완료 이력과 현재 상태는 다른 것: complete journal 은 이력만 답하고, verify --live 가 현재 payload 를 본다
    again = run_activate(layout, manifest, confirm=True)
    assert again["already_active"] is True and again["completion"] == "journal" and again["current_state"] == "unverified"
    assert main(["verify", "--manifest", manifest["_path"], "--live"], load_env=False) == 0
    _update(layout.live_paths(ALICE.user_key).metadata_db, "UPDATE file_metadata SET metadata='{\"pages\": 99}'")
    assert main(["verify", "--manifest", manifest["_path"], "--live"], load_env=False) == 1
    out = capsys.readouterr().out
    assert '"target": "live"' in out and "file_metadata: 내용 digest" in out
