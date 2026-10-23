"""
`apply` — manifest 대로 staging 에 사용자별 저장소를 만든다 (②-8.4 4단계).

1. 사전 검사: manifest sidecar hash·충돌 없음·매핑 hash·원본 fingerprint·snapshot hash·registry 상태,
   그리고 **배정을 다시 계산해 plan digest 와 대조**. 하나라도 다르면 아무것도 쓰지 않는다.
2. staging 은 run 하나에 묶인다(`staging/run.json`). 다른 run 의 staging 이 있으면 거부
   (`--reset-staging` 으로 지우고 다시 만든다 — staging 은 파생 데이터다).
3. 사용자마다 도메인 `ensure_storage(principal, staging_paths)` 로 스키마를 만든다. 사용자 DB 에
   owner_key 없는 구형 테이블이 있으면 `LegacySchemaError` — 소유자를 추정하지 않고 멈춘다(M03).
4. 단계마다 한 트랜잭션: 행 삽입(owner_key = user_key) + `_ms365_migration(step_id)` 표식.
   중단 뒤 재실행하면 표식이 있는 단계는 건너뛴다 — 중복도 누락도 없다(M02).
5. 파일은 같은 디렉터리 임시파일에 쓰며 hash 를 확인한 뒤 `os.replace`. 이미 같은 hash 면 건너뛴다.
6. 격리 대상은 `quarantine/<run_id>/` (rows.db · json/ · files/ · files.json) — 어느 사용자에게도 복사하지 않는다.
"""

import hashlib
import os
import shutil
import sqlite3
import stat
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from mcp_common.principal import Principal

from .assignment import Assignment, FileItem, RecordPlan, RowPlan, compute_assignment
from .common import (
    MARKER_TABLE,
    Layout,
    MigrationError,
    audit_event,
    has_files,
    read_json_optional,
    require_no_conflicts,
    sha256_file,
    utcnow_iso,
    write_json,
)
from .content_digest import row_values, rows_by_id, written_columns
from .freeze import check_locks
from .legacy import JSON_SOURCES, SQLITE_SOURCES, check_cross_use, fingerprint, sources_from_manifest
from .mapping import load_mapping
from .planner import (
    UNUSABLE_STATUSES,
    build_inputs,
    require_no_activation_in_progress,
    require_servers_stopped,
    snapshot_paths,
)

#: 테스트가 중단을 흉내 낼 때 쓰는 훅 — 단계가 끝날 때마다 `FAULT_HOOK(label)` 을 부른다.
FAULT_HOOK: Optional[Callable[[str], None]] = None

MARKER_DDL = (
    f"CREATE TABLE IF NOT EXISTS {MARKER_TABLE} ("
    "step_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, rows INTEGER NOT NULL, applied_at TEXT NOT NULL)"
)
_CHUNK_IDS = 500
_COPY_CHUNK = 1024 * 1024


def _hook(label: str) -> None:
    if FAULT_HOOK is not None:
        FAULT_HOOK(label)


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# ----------------------------------------------------------------------
# 사전 검사
# ----------------------------------------------------------------------
def prepare(layout: Layout, manifest: Dict[str, Any]) -> Dict[str, Any]:
    """manifest 와 현재 원본·lock·매핑·registry 가 plan 때와 같은지 확인하고 배정을 다시 계산한다.

    apply 와 activate(처음·재개 모두)가 같은 검사를 거친다 — 쓰기 정지 구간(R10)이 깨졌으면
    (lock 사라짐·원본 fingerprint 변경·매핑 변경·사용자 삭제) 아무것도 쓰거나 옮기지 않는다.
    """
    require_no_conflicts(manifest)
    require_servers_stopped()
    check_locks(manifest)
    mapping = load_mapping(Path(manifest["mapping"]["path"]))
    if mapping.sha256 != manifest["mapping"]["sha256"]:
        raise MigrationError("mapping_changed", "매핑 파일이 plan 이후 바뀌었습니다 — plan 을 다시 실행하세요.")
    sources = sources_from_manifest(manifest["sources"])
    check_cross_use(sources, layout)
    state = manifest["source_state"]
    for name in SQLITE_SOURCES + JSON_SOURCES:
        if fingerprint(sources.path(name)) != state[name]["sha256"]:
            raise MigrationError("source_changed", f"legacy 원본 {name} 이 plan 이후 바뀌었습니다 — plan 을 다시 실행하세요.")
    snapshots = snapshot_paths(layout, state)
    for name, path in snapshots.items():
        if path is not None and (not path.is_file() or sha256_file(path) != state[name]["snapshot_sha256"]):
            raise MigrationError("snapshot_changed", f"snapshot {name} 이 없거나 바뀌었습니다 — plan 을 다시 실행하세요.")
    _check_registry(manifest)
    assignment = compute_assignment(build_inputs(mapping, sources, snapshots))
    if assignment.digest() != manifest["plan_digest"]:
        raise MigrationError("plan_changed", "원본 파일 목록·내용이 plan 과 다릅니다 — plan 을 다시 실행하세요.")
    return {"assignment": assignment, "sources": sources, "snapshots": snapshots}


def _check_registry(manifest: Dict[str, Any]) -> None:
    """manifest 의 사용자가 여전히 등록돼 있고 삭제 중이 아니며 같은 (tenant_id, object_id) 인지."""
    for problem in registry_problems(manifest):
        raise MigrationError("registry", problem)


def registry_problems(manifest: Dict[str, Any]) -> List[str]:
    from session.identity_registry import get_user

    problems: List[str] = []
    for user in manifest["users"]:
        user_key = user["user_key"]
        record = get_user(user_key)
        if record is None or record.status in UNUSABLE_STATUSES:
            problems.append(f"user_key {user_key}: registry 에 없거나 삭제 중입니다 — plan 을 다시 실행하세요.")
            continue
        if (record.tenant_id.lower(), record.object_id.lower()) != (user["tenant_id"], user["object_id"]):
            problems.append(f"user_key {user_key}: registry 의 (tenant_id, object_id) 가 manifest 와 다릅니다 — plan 을 다시 실행하세요.")
    return problems


def _staging_guard(layout: Layout, manifest: Dict[str, Any], reset: bool) -> None:
    run_id = manifest["run_id"]
    marker = read_json_optional(layout.staging_marker)
    if marker and marker.get("run_id") == run_id:
        return
    occupied = marker is not None or (layout.staging_users.is_dir() and any(layout.staging_users.iterdir()))
    if occupied:
        if not reset:
            raise MigrationError(
                "staging_foreign",
                "staging 에 다른 run 의 데이터가 있습니다 — `apply --reset-staging` 으로 지우고 다시 만드세요.",
            )
        require_no_activation_in_progress(layout)
        shutil.rmtree(layout.staging)
    write_json(layout.staging_marker, {"run_id": run_id, "manifest_sha256": manifest["_sha256"],
                                       "created_at": utcnow_iso()}, root=layout.migration)


# ----------------------------------------------------------------------
# DB 단계
# ----------------------------------------------------------------------
def run_step(db_path: Path, step_id: str, run_id: str, writer: Callable[[sqlite3.Connection], int]) -> str:
    """행 쓰기 + 표식을 한 트랜잭션으로. 표식이 이미 있으면 건너뛴다."""
    with closing(sqlite3.connect(os.fspath(db_path), timeout=30, isolation_level=None)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(MARKER_DDL)
        conn.execute("BEGIN IMMEDIATE")
        try:
            done = conn.execute(f"SELECT run_id FROM {MARKER_TABLE} WHERE step_id = ?", (step_id,)).fetchone()
            if done:
                conn.execute("ROLLBACK")
                if done[0] != run_id:
                    raise MigrationError("staging_foreign", "staging DB 에 다른 run 의 표식이 있습니다.")
                return "skipped"
            count = writer(conn)
            conn.execute(f"INSERT INTO {MARKER_TABLE} VALUES (?, ?, ?, ?)", (step_id, run_id, count, utcnow_iso()))
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return "applied"


def _row_writer(snapshot: Optional[Path], plan: RowPlan, user_key: str) -> Callable[[sqlite3.Connection], int]:
    """열 선택·값은 `content_digest` 와 같은 함수를 쓴다 — plan 이 계산한 digest 가 곧 쓰는 값이다."""

    def write(conn: sqlite3.Connection) -> int:
        rowids = plan.by_user.get(user_key, [])
        if not rowids or snapshot is None:
            return 0
        rows = rows_by_id(snapshot, plan.source_table, rowids)
        cols = written_columns(plan.target_table, rows[0].keys() if rows else ())
        sql = f"INSERT INTO {_q(plan.target_table)} ({', '.join(_q(c) for c in cols)}) VALUES ({', '.join('?' for _ in cols)})"
        conn.executemany(sql, [row_values(row, cols, user_key) for row in rows])
        return len(rows)

    return write


def _record_writer(plan: RecordPlan, user_key: str) -> Callable[[sqlite3.Connection], int]:
    records = plan.by_user.get(user_key, [])

    def write_metadata(conn: sqlite3.Connection) -> int:
        conn.executemany(
            "INSERT INTO file_metadata (owner_key, file_url, keywords, metadata, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(user_key, r["file_url"], r["keywords"], r["metadata"], r["created_at"], r["updated_at"]) for r in records],
        )
        return len(records)

    def write_mail(conn: sqlite3.Connection) -> int:
        for r in records:
            conn.execute(
                "INSERT INTO processed_messages (owner_key, message_id, subject, from_address, received_datetime,"
                " folder_path, attachment_count, processed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_key, r["message_id"], r["subject"], r["from_address"], r["received_datetime"],
                 r["folder_path"], r["attachment_count"], r["processed_at"] or utcnow_iso()),
            )
            conn.executemany(
                "INSERT INTO processed_files (owner_key, message_id, seq, file_ref) VALUES (?, ?, ?, ?)",
                [(user_key, r["message_id"], i, ref) for i, ref in enumerate(r["files"])],
            )
        return len(records)

    return write_mail if plan.target_table == "processed_messages" else write_metadata


def _ensure_storage(principal: Principal, paths) -> None:
    from mcp_file_handler.storage_schema import ensure_storage as file_handler_storage
    from mcp_onenote.storage_schema import LegacySchemaError as OneNoteLegacy
    from mcp_onenote.storage_schema import ensure_storage as onenote_storage
    from mcp_outlook.storage_schema import ensure_storage as outlook_storage
    from mcp_teams.storage_schema import LegacySchemaError as TeamsLegacy
    from mcp_teams.storage_schema import ensure_storage as teams_storage

    try:
        for ensure in (onenote_storage, teams_storage, outlook_storage, file_handler_storage):
            ensure(principal, paths)
    except (OneNoteLegacy, TeamsLegacy):
        raise MigrationError(
            "legacy_schema",
            f"user_key {principal.user_key}: staging DB 에 owner_key 없는 구형 테이블이 있습니다 — "
            "소유자를 추정하지 않습니다(`--reset-staging`).",
        ) from None


# ----------------------------------------------------------------------
# 파일
# ----------------------------------------------------------------------
def copy_verified(src: Path, dest: Path, root: Path, expected: str) -> str:
    """원본을 `dest` 로 복사하되 hash 가 `expected` 와 같을 때만 교체한다. root 밖·링크는 거부."""
    from mcp_common.secure_files import create_exclusive, ensure_within

    if dest.is_file() and not os.path.islink(dest) and sha256_file(dest) == expected:
        return "skipped"
    try:
        st = os.lstat(src)
    except FileNotFoundError:
        raise MigrationError("source_changed", "plan 이후 원본 파일이 사라졌습니다 — plan 을 다시 실행하세요.") from None
    if not stat.S_ISREG(st.st_mode):
        raise MigrationError("source_changed", "원본 파일이 일반 파일이 아닙니다 — plan 을 다시 실행하세요.")
    tmp, fh = create_exclusive(dest.parent, f".{dest.name}.{uuid.uuid4().hex[:8]}.tmp", root=root)
    digest = hashlib.sha256()
    try:
        with fh, open(src, "rb") as source:
            for chunk in iter(lambda: source.read(_COPY_CHUNK), b""):
                digest.update(chunk)
                fh.write(chunk)
            fh.flush()
            os.fsync(fh.fileno())
        if digest.hexdigest() != expected:
            raise MigrationError("source_changed", "원본 파일 내용이 plan 과 다릅니다 — plan 을 다시 실행하세요.")
        ensure_within(dest, root)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return "copied"


def _source_file(sources, item: FileItem) -> Path:
    return sources.path(item.source).joinpath(*item.rel.split("/"))


def _copy_user_files(ctx: Dict[str, Any], paths, user_key: str) -> Dict[str, int]:
    stats = {"copied": 0, "skipped": 0}
    for item in ctx["assignment"].files:
        if item.owner != user_key:
            continue
        dest = paths.files.joinpath(*item.dest.split("/"))
        stats[copy_verified(_source_file(ctx["sources"], item), dest, paths.files, item.sha256)] += 1
    return stats


# ----------------------------------------------------------------------
# 격리
# ----------------------------------------------------------------------
def _quarantine_rows(qdir: Path, run_id: str, snapshot: Optional[Path], source: str, table: str,
                     reasons: Dict[str, List[int]]) -> None:
    if snapshot is None or not reasons:
        return
    qdir.mkdir(parents=True, exist_ok=True)
    qtable = f"{source}__{table}"
    with closing(sqlite3.connect(os.fspath(qdir / "rows.db"), timeout=30, isolation_level=None)) as conn:
        conn.execute("ATTACH DATABASE ? AS src", (os.fspath(snapshot),))
        conn.execute(MARKER_DDL)
        conn.execute("BEGIN IMMEDIATE")
        try:
            step_id = f"q:{qtable}"
            if conn.execute(f"SELECT 1 FROM {MARKER_TABLE} WHERE step_id = ?", (step_id,)).fetchone():
                conn.execute("ROLLBACK")
            else:
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS main.{_q(qtable)} AS SELECT *, CAST(NULL AS TEXT) AS _quarantine_reason,"
                    f" CAST(NULL AS INTEGER) AS _source_rowid FROM src.{_q(table)} WHERE 0"
                )
                total = 0
                for reason, ids in sorted(reasons.items()):
                    for start in range(0, len(ids), _CHUNK_IDS):
                        chunk = ids[start:start + _CHUNK_IDS]
                        marks = ",".join("?" for _ in chunk)
                        conn.execute(
                            f"INSERT INTO main.{_q(qtable)} SELECT *, ?, rowid FROM src.{_q(table)}"
                            f" WHERE rowid IN ({marks})", (reason, *chunk))
                        total += len(chunk)
                conn.execute(f"INSERT INTO {MARKER_TABLE} VALUES (?, ?, ?, ?)", (step_id, run_id, total, utcnow_iso()))
                conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("DETACH DATABASE src")


def _quarantine_json(layout: Layout, qdir: Path, plan: RecordPlan, sources) -> None:
    if not plan.quarantine:
        return
    from .legacy import read_json_source

    doc = read_json_source(sources.path(plan.source)) or {}
    pool = doc.get("processed_messages", {}) if plan.source == "mail_metadata" else doc
    out = {reason: {key: pool.get(key) for key in keys} for reason, keys in sorted(plan.quarantine.items())}
    write_json(qdir / "json" / f"{plan.source}.json", {"source": plan.source, "reasons": out}, root=layout.migration)


def _quarantine_files(layout: Layout, qdir: Path, ctx: Dict[str, Any]) -> int:
    from .legacy import _unsafe_part

    index = []
    copied = 0
    root = qdir / "files"
    for item in ctx["assignment"].files:
        if item.owner or item.reason in ("link", "skipped"):
            continue
        parts = item.rel.split("/")
        if any(_unsafe_part(p) for p in parts):
            dest = root / "_unsafe" / f"{item.sha256}.bin"
        else:
            dest = root.joinpath(item.source, *parts)
        copy_verified(_source_file(ctx["sources"], item), dest, root, item.sha256)
        copied += 1
        index.append({"source": item.source, "rel": item.rel, "reason": item.reason, "sha256": item.sha256,
                      "stored_as": dest.relative_to(qdir).as_posix()})
    if index:
        write_json(qdir / "files.json", index, root=layout.migration)
    return copied


def _quarantine(layout: Layout, manifest: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, int]:
    run_id = manifest["run_id"]
    qdir = layout.quarantine_dir(run_id)
    assignment: Assignment = ctx["assignment"]
    for plan in assignment.rows:
        _quarantine_rows(qdir, run_id, ctx["snapshots"].get(plan.source), plan.source, plan.source_table, plan.quarantine)
        _hook(f"quarantine:rows:{plan.key}")
    for plan in assignment.records:
        if plan.source == "metadata_db":
            ids = {r: [int(i) for i in keys] for r, keys in plan.quarantine.items()}
            _quarantine_rows(qdir, run_id, ctx["snapshots"].get("metadata_db"), "metadata_db", "metadata", ids)
        else:
            _quarantine_json(layout, qdir, plan, ctx["sources"])
        _hook(f"quarantine:records:{plan.key}")
    files = _quarantine_files(layout, qdir, ctx)
    _hook("quarantine:files")
    return {"files": files}


# ----------------------------------------------------------------------
# 공개
# ----------------------------------------------------------------------
def _checkpoint(layout: Layout, run_id: str, status: str, done: List[str]) -> None:
    write_json(layout.checkpoints / f"{run_id}.apply.json",
               {"run_id": run_id, "status": status, "done": sorted(set(done)), "updated_at": utcnow_iso()},
               root=layout.migration)


def run_apply(layout: Layout, manifest: Dict[str, Any], *, reset_staging: bool = False) -> Dict[str, Any]:
    ctx = prepare(layout, manifest)
    _staging_guard(layout, manifest, reset_staging)
    run_id = manifest["run_id"]
    previous = read_json_optional(layout.checkpoints / f"{run_id}.apply.json") or {}
    done: List[str] = list(previous.get("done", []))
    _checkpoint(layout, run_id, "in_progress", done)
    assignment: Assignment = ctx["assignment"]
    report: Dict[str, Any] = {"status": "ok", "run_id": run_id, "users": {}}

    for user in manifest["users"]:
        user_key = user["user_key"]
        principal = Principal(user_key=user_key, tenant_id=user["tenant_id"], object_id=user["object_id"])
        paths = layout.staging_paths(user_key)
        _ensure_storage(principal, paths)
        steps: Dict[str, str] = {}
        for plan in assignment.rows:
            if plan.key == "onenote_page_summaries":
                continue  # 요약은 이전하지 않는다 — 사용자별로 다시 생성
            step_id = f"rows:{plan.key}"
            writer = _row_writer(ctx["snapshots"].get(plan.source), plan, user_key)
            steps[step_id] = run_step(getattr(paths, plan.target_db), step_id, run_id, writer)
            done.append(f"{user_key}:{step_id}")
            _hook(f"{user_key}:{step_id}")
        for plan in assignment.records:
            step_id = f"records:{plan.key}"
            steps[step_id] = run_step(getattr(paths, plan.target_db), step_id, run_id, _record_writer(plan, user_key))
            done.append(f"{user_key}:{step_id}")
            _hook(f"{user_key}:{step_id}")
        files = _copy_user_files(ctx, paths, user_key)
        done.append(f"{user_key}:files")
        _checkpoint(layout, run_id, "in_progress", done)
        _hook(f"{user_key}:files")
        if has_files(paths.auth_dir):
            raise MigrationError("auth_written", "staging auth/ 에 파일이 있습니다 — 이전 도구는 인증 저장소를 쓰지 않습니다.")
        report["users"][user_key] = {"steps": steps, "files": files}
        audit_event("apply", "success", user_key=user_key)

    report["quarantine"] = _quarantine(layout, manifest, ctx)
    done.append("quarantine")
    _checkpoint(layout, run_id, "complete", done)
    audit_event("apply", "success")
    report["next"] = f"python -m tools.migrate_multi_user verify --manifest {manifest['_path']}"
    return report


__all__ = ["FAULT_HOOK", "MARKER_DDL", "prepare", "registry_problems", "run_step", "copy_verified", "run_apply"]
