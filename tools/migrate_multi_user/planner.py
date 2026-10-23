"""
`plan` — snapshot·hash·소유자 배정·충돌 검사 → manifest (②-8.2, ②-8.4 2~3단계).

plan 은 legacy 원본의 **데이터를 읽기만** 한다. legacy 쪽에 쓰는 것은 쓰기 정지 lock
(`freeze.py` — `database/.migration_lock` 등) 하나뿐이고, 데이터 루트에는 `snapshots/<run_id>/` 와
`manifests/<run_id>.json(.sha256)` 만 쓴다. 충돌(blocking)이 있으면 manifest 는 남기되
apply 가 거부한다 — 고칠 내용을 한 번에 보여 주기 위해서다.

서버 포트(도메인·gateway·콜백)가 열려 있으면 plan 을 **거부**한다(②-8.4 1단계 "운영 정지" 를
lock 이 걸리기 전에 확인). 진행 중인 activate(`checkpoints/*.activate.json` = moving)가 있으면
lock 을 이어받지 않고 거부한다.

blocking 충돌:
- 매핑 사용자가 registry 에 없음(`admin_cli user add` 전) 또는 삭제 중/삭제됨
- 같은 legacy 이메일이 다른 사용자에 매핑됨, 같은 경로 규칙에 다른 소유자
- legacy `auth.db` 의 `azure_user_info.object_id` 가 매핑의 object_id 와 다름
"""

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from .assignment import Inputs, compute_assignment, expected_counts, file_listing, step_ids, summarize
from .common import (
    MANIFEST_FORMAT,
    MANIFEST_VERSION,
    Layout,
    MigrationError,
    audit_event,
    new_run_id,
    sha256_bytes,
    sha256_file,
    utcnow_iso,
    write_json,
    write_text,
)
from .content_digest import expected_digests
from .freeze import acquire_locks
from .legacy import (
    JSON_SOURCES,
    SQLITE_SOURCES,
    Sources,
    check_cross_use,
    fingerprint,
    read_json_source,
    read_legacy_users,
    resolve_sources,
    snapshot_auth_db,
    snapshot_sqlite,
    walk_files,
)
from .mapping import AMBIGUOUS, Mapping, load_mapping

UNUSABLE_STATUSES = ("deleting", "deleted")


def require_servers_stopped() -> None:
    """도메인·gateway·콜백 포트 중 하나라도 연결되면 거부 (plan·apply·activate 공통)."""
    from .ports import running_server_ports

    running = running_server_ports()
    if running:
        raise MigrationError(
            "servers_running",
            f"서버 포트 {running} 에 연결됩니다 — MCP 서버·auth gateway·콜백 서버를 모두 멈춘 뒤 다시 실행하세요.",
        )


def require_no_activation_in_progress(layout: Layout) -> None:
    if not layout.checkpoints.is_dir():
        return
    for journal in layout.checkpoints.glob("*.activate.json"):
        from .common import read_json_optional

        if (read_json_optional(journal) or {}).get("status") == "moving":
            raise MigrationError("activation_in_progress", "진행 중인 activate 가 있습니다 — 먼저 같은 manifest 로 activate 를 끝내세요.")

NOT_MIGRATED_REASONS = {
    "azure_token_info": "토큰은 복사하지 않는다 — 사용자는 OIDC 로 새로 연결한다",
    "azure_app_config": "앱 설정·client secret 은 mode 1 에서 환경변수/secret 파일로만 읽는다",
    "azure_user_info": "프로필은 이전하지 않는다 — object_id 대조에만 쓴다",
}


def _sidecar_paths(source: Path) -> List[Path]:
    return [source] + [Path(str(source) + suffix) for suffix in ("-wal", "-shm", "-journal")]


def collect_files(sources: Sources) -> List[Any]:
    exclude: List[Path] = []
    for name in SQLITE_SOURCES + JSON_SOURCES:
        exclude.extend(_sidecar_paths(sources.path(name)))
    return walk_files("downloads", sources.downloads, exclude) + walk_files("output", sources.output, exclude)


def build_inputs(mapping: Mapping, sources: Sources, snapshots: Dict[str, Optional[Path]]) -> Inputs:
    json_docs = {name: read_json_source(sources.path(name)) for name in JSON_SOURCES}
    return Inputs(mapping=mapping, sources=sources, snapshots=snapshots, json_docs=json_docs,
                  files=collect_files(sources))


def _registry_problems(mapping: Mapping) -> Dict[str, Any]:
    from session.identity_registry import get_user

    statuses: Dict[str, Optional[str]] = {}
    problems: List[str] = []
    for user_key, user in sorted(mapping.users.items()):
        record = get_user(user_key)
        if record is None:
            statuses[user_key] = None
            problems.append(f"user_key {user_key}: registry 에 없습니다 — `python -m session.admin_cli user add` 먼저")
            continue
        statuses[user_key] = record.status
        if record.status in UNUSABLE_STATUSES:
            problems.append(f"user_key {user_key}: registry 상태가 {record.status} 입니다")
        if (record.tenant_id.lower(), record.object_id.lower()) != (user.tenant_id, user.object_id):
            problems.append(f"user_key {user_key}: registry 의 (tenant_id, object_id) 가 매핑과 다릅니다")
    return {"statuses": statuses, "problems": problems}


def _object_id_problems(mapping: Mapping, auth_snapshot: Optional[Path]) -> List[str]:
    problems = set()
    for email, object_id in read_legacy_users(auth_snapshot):
        owner = mapping.owner_of_email(email)
        if owner in (None, AMBIGUOUS) or not object_id:
            continue
        if str(object_id).strip().lower() != mapping.users[owner].object_id:
            problems.add(f"user_key {owner}: legacy auth.db 의 object_id 가 매핑과 다릅니다 — 매핑을 확인하세요")
    return sorted(problems)


def _snapshot(layout: Layout, run_id: str, sources: Sources) -> Dict[str, Any]:
    """SQLite 원본 snapshot + 모든 원본 fingerprint."""
    snap_dir = layout.snapshot_dir(run_id)
    state: Dict[str, Any] = {}
    not_migrated: Dict[str, Any] = {}
    for name in SQLITE_SOURCES:
        src = sources.path(name)
        entry: Dict[str, Any] = {"exists": src.is_file(), "sha256": fingerprint(src), "snapshot": None,
                                 "snapshot_sha256": None}
        if src.is_file():
            target = snap_dir / f"{name}.db"
            try:
                if name == "auth_db":
                    counts = snapshot_auth_db(src, target)
                    for table, reason in NOT_MIGRATED_REASONS.items():
                        if table in counts:
                            not_migrated[table] = {"rows": counts[table], "reason": reason}
                else:
                    snapshot_sqlite(src, target)
            except sqlite3.DatabaseError as exc:
                raise MigrationError(
                    "source_invalid", f"legacy 원본 {name} 을 SQLite 로 읽을 수 없습니다 ({type(exc).__name__})."
                ) from None
            entry["snapshot"] = target.relative_to(layout.migration).as_posix()
            entry["snapshot_sha256"] = sha256_file(target)
        state[name] = entry
    for name in JSON_SOURCES:
        src = sources.path(name)
        state[name] = {"exists": src.is_file(), "sha256": fingerprint(src)}
    for name in ("downloads", "output"):
        state[name] = {"exists": sources.path(name).is_dir()}
    return {"state": state, "not_migrated": not_migrated}


def snapshot_paths(layout: Layout, state: Dict[str, Any]) -> Dict[str, Optional[Path]]:
    return {
        name: (layout.migration / state[name]["snapshot"]) if state.get(name, {}).get("snapshot") else None
        for name in SQLITE_SOURCES
    }


def run_plan(
    layout: Layout,
    mapping_path: Path,
    legacy_root: Path,
    overrides: Optional[Dict[str, Optional[str]]] = None,
) -> Dict[str, Any]:
    sources = resolve_sources(legacy_root, overrides)
    check_cross_use(sources, layout)
    mapping = load_mapping(mapping_path)
    require_servers_stopped()
    require_no_activation_in_progress(layout)

    run_id = new_run_id()
    # 쓰기 정지 lock 을 먼저 건 뒤 snapshot 을 뜬다 — lock 이후에 legacy 를 여는 mode 0 코드는 거부된다
    locks = acquire_locks(sources, run_id=run_id, deployment_id=layout.deployment_id)
    registry = _registry_problems(mapping)
    snap = _snapshot(layout, run_id, sources)
    snapshots = snapshot_paths(layout, snap["state"])
    inputs = build_inputs(mapping, sources, snapshots)
    assignment = compute_assignment(inputs)
    summary = summarize(assignment)

    conflicts = list(mapping.conflicts) + registry["problems"] + _object_id_problems(mapping, snapshots["auth_db"])
    warnings: List[str] = []
    if not any(v.get("exists") for v in snap["state"].values()):
        warnings.append("legacy 원본을 하나도 찾지 못했습니다 — --legacy-root 를 확인하세요")
    unassigned_files = [f for f in assignment.files if f.reason in ("unowned", "ambiguous_owner")]
    if unassigned_files:
        warnings.append(f"소유자가 정해지지 않은 파일 {len(unassigned_files)}개는 격리됩니다 (owners.paths 로 지정 가능)")

    users = []
    for entry in mapping.summary():
        entry["registry_status"] = registry["statuses"].get(entry["user_key"])
        users.append(entry)
    manifest = {
        "format": MANIFEST_FORMAT,
        "version": MANIFEST_VERSION,
        "run_id": run_id,
        "created_at": utcnow_iso(),
        "deployment_id": layout.deployment_id,
        "data_root": str(layout.data_root),
        "mapping": {"path": mapping.path, "sha256": mapping.sha256},
        "sources": sources.as_dict(),
        "source_state": snap["state"],
        "locks": locks,
        "users": users,
        "plan_digest": assignment.digest(),
        "expected": {uk: expected_counts(assignment, uk) for uk in sorted(mapping.users)},
        # apply 가 쓸 행의 내용 digest — verify·재개·verify --live 가 같은 열로 다시 계산해 비교한다 (N07)
        "digests": {uk: expected_digests(assignment, snapshots, uk) for uk in sorted(mapping.users)},
        "expected_files": {uk: summary["users"].get(uk, {}).get("files", 0) for uk in sorted(mapping.users)},
        "refs_dropped": {uk: summary["users"].get(uk, {}).get("refs_dropped", 0) for uk in sorted(mapping.users)},
        "steps": {uk: step_ids(assignment, uk) for uk in sorted(mapping.users)},
        "quarantine": summary["quarantine"],
        "files": file_listing(assignment),
        "not_migrated": snap["not_migrated"],
        "conflicts": conflicts,
        "warnings": warnings,
    }
    path = layout.manifest_path(run_id)
    data = write_json(path, manifest, root=layout.migration)
    write_text(Path(str(path) + ".sha256"), sha256_bytes(data) + "\n", root=layout.migration)
    audit_event("plan", "failure" if conflicts else "success", error_code="conflicts" if conflicts else None)

    return {
        "status": "conflicts" if conflicts else "ok",
        "run_id": run_id,
        "manifest": str(path),
        "users": [
            {"user_key": u["user_key"], "registry_status": u["registry_status"],
             "rows": manifest["expected"][u["user_key"]], "files": manifest["expected_files"][u["user_key"]]}
            for u in users
        ],
        "quarantine": manifest["quarantine"],
        "not_migrated": {k: v["rows"] for k, v in manifest["not_migrated"].items()},
        "conflicts": conflicts,
        "warnings": warnings,
        "locks": [entry["path"] for entry in locks],
        "next": None if conflicts else f"python -m tools.migrate_multi_user apply --manifest {path}",
    }


__all__ = [
    "run_plan",
    "build_inputs",
    "collect_files",
    "snapshot_paths",
    "require_servers_stopped",
    "require_no_activation_in_progress",
    "UNUSABLE_STATUSES",
]
