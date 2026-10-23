"""
`activate` — 검증된 staging 을 운영 위치 `users/<user_key>/` 로 옮긴다 (②-8.4 8단계).

1. `--yes` 필수. journal(`checkpoints/<run_id>.activate.json`)이 있으면 **먼저 run_id·manifest hash 가
   같은지** 확인한다 — 다른 manifest 의 journal 은 `complete` 여도 믿지 않는다(R11).
2. 처음이든 재개든 `applier.prepare()` 를 다시 거친다: 서버 포트 닫힘, 쓰기 정지 lock 유지, 모든 legacy
   원본 fingerprint·snapshot hash·매핑 hash·registry 사용자(상태·`(tid, oid)`)·배정 digest 가 plan 과
   같아야 한다. 하나라도 다르면 아무것도 옮기지 않고 re-plan 을 요구한다(R10).
3. 처음 시작: `verify`(staging)가 통과해야 하고, 대상 `users/<uk>/db`·`files` 가 비어 있어야 한다.
   사용자가 이미 mode 1 로 데이터를 만들었으면 덮지 않고 멈춘다. `users/<uk>/` 자체는
   `admin_cli user add` 가 만든다 — `auth/`(토큰·DEK)는 건드리지 않는다.
4. 재개: journal 이 `done` 이라고 적은 영역은 **live 위치에서 다시 검증**(hash·행 수·owner_key·표식)하고,
   아직 옮기지 않은 영역은 옮기기 직전에 staging 에서 검증한다. staging 이 없고 대상만 있는 영역
   (rename 뒤 journal 쓰기 전에 멈춘 경우)도 내용 검증을 통과해야 완료로 인정한다.
5. 영역(`db`, `files`)마다 같은 볼륨 안의 디렉터리 `os.replace` — 영역 단위로 원자적이다.
6. 끝나면 `users/<uk>/manifest.json` 에 이전 기록(run_id·행 수·파일 수, 이메일 없음)을 남기고, live 전체를
   `verify --live` 와 같은 검사로 한 번 더 확인한 뒤에야 journal 을 `complete` 로 적는다.
7. 출력의 `completion`/`current_state` 로 "완료 이력"(journal 이 complete — `current_state: unverified`)과
   "지금 검증된 상태"(`completion: now`, `current_state: verified`)를 구분한다.

활성화 뒤 `MS365_MULTI_USER=1` 로 서버를 다시 띄운다. legacy 저장소는 그대로(읽기 전용 보관) 두며
쓰기 정지 lock 도 남긴다 — mode 0 서버가 실수로 기동해 쓰지 않게. 되돌리려면 `unlock --yes`.
"""

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List

from .applier import prepare
from .common import (
    Layout,
    MigrationError,
    audit_event,
    has_files,
    read_json_optional,
    require_no_conflicts,
    utcnow_iso,
    write_json,
)
from .verifier import AREAS, run_verify, verify_area


def _is_link(path: Path) -> bool:
    if os.path.islink(path):
        return True
    is_junction = getattr(os.path, "isjunction", None)
    return bool(is_junction and is_junction(path))


def _journal_path(layout: Layout, manifest: Dict[str, Any]) -> Path:
    return layout.checkpoints / f"{manifest['run_id']}.activate.json"


def _check_journal_identity(journal: Dict[str, Any], manifest: Dict[str, Any]) -> None:
    """journal 을 믿기 전에 — 어떤 상태든 — 이 manifest 의 것인지 확인한다."""
    if journal.get("run_id") != manifest["run_id"] or journal.get("manifest_sha256") != manifest["_sha256"]:
        raise MigrationError(
            "activation_state",
            "activate journal 이 이 manifest 의 것이 아닙니다(run_id 또는 manifest hash 불일치) — 수동 확인이 필요합니다.",
        )
    moves = journal.get("moves")
    if not isinstance(moves, dict) or set(moves) != {u["user_key"] for u in manifest["users"]}:
        raise MigrationError("activation_state", "activate journal 의 사용자 목록이 manifest 와 다릅니다 — 수동 확인이 필요합니다.")


def _live_root_problem(layout: Layout, user_key: str) -> List[str]:
    live = layout.live_paths(user_key)
    if not live.root.is_dir() or _is_link(live.root):
        return [f"user_key {user_key}: users/<user_key>/ 가 없거나 링크입니다 (admin_cli user add 확인)"]
    return []


def _precheck(layout: Layout, manifest: Dict[str, Any]) -> List[str]:
    """처음 시작: 대상 영역이 비어 있고 staging 영역이 있어야 한다 (registry 는 prepare 가 봤다)."""
    problems: List[str] = []
    for user in manifest["users"]:
        user_key = user["user_key"]
        root_problem = _live_root_problem(layout, user_key)
        if root_problem:
            problems.extend(root_problem)
            continue
        live = layout.live_paths(user_key)
        staging = layout.staging_paths(user_key)
        for area in AREAS:
            target = live.root / area
            if _is_link(target) or has_files(target):
                problems.append(f"user_key {user_key}: users/<user_key>/{area} 에 이미 데이터가 있습니다 — 덮지 않습니다")
            if not (staging.root / area).is_dir():
                problems.append(f"user_key {user_key}: staging {area} 가 없습니다")
    return problems


def _resume_problems(layout: Layout, manifest: Dict[str, Any], journal: Dict[str, Any]) -> List[str]:
    """재개: 이미 옮긴 영역은 live 에서 재검증, 남은 영역은 staging 또는 대상이 있어야 한다."""
    problems: List[str] = []
    users = {u["user_key"]: u for u in manifest["users"]}
    for user_key, areas in sorted(journal["moves"].items()):
        root_problem = _live_root_problem(layout, user_key)
        if root_problem:
            problems.extend(root_problem)
            continue
        live = layout.live_paths(user_key)
        staging = layout.staging_paths(user_key)
        for area in AREAS:
            if areas.get(area) == "done":
                problems.extend(
                    f"user_key {user_key}: 옮긴 {area} 영역이 manifest 와 다릅니다 — {p}"
                    for p in verify_area(layout, manifest, users[user_key], area, live=True)
                )
            elif not (staging.root / area).exists() and not (live.root / area).exists():
                problems.append(f"user_key {user_key}: {area} 영역이 staging 에도 대상에도 없습니다")
    return problems


def _move_area(layout: Layout, manifest: Dict[str, Any], user: Dict[str, Any], area: str) -> str:
    """영역 하나를 옮긴다. 옮기기 직전 staging 내용을, 이미 옮겨져 있으면 live 내용을 manifest 와 대조한다."""
    user_key = user["user_key"]
    staging_area = layout.staging_paths(user_key).root / area
    target_area = layout.live_paths(user_key).root / area
    if staging_area.exists():
        if _is_link(staging_area):
            raise MigrationError("activation_state", f"user_key {user_key}: staging {area} 가 링크입니다 — 수동 확인이 필요합니다.")
        problems = verify_area(layout, manifest, user, area, live=False)
        if problems:
            raise MigrationError(
                "verify_failed",
                f"user_key {user_key}: staging {area} 가 manifest 와 다릅니다 — 옮기지 않습니다:\n- " + "\n- ".join(problems),
            )
        if target_area.exists():
            if _is_link(target_area) or has_files(target_area):
                raise MigrationError("target_not_empty", f"user_key {user_key}: 대상 {area} 에 데이터가 생겼습니다 — 서버를 멈추고 확인하세요.")
            shutil.rmtree(target_area)  # 빈 디렉터리 트리뿐 (user add 가 만든 자리)
        os.replace(staging_area, target_area)
        return "moved"
    if target_area.exists():
        # rename 뒤 journal 을 쓰기 전에 멈춘 경우 — 경로가 있다는 것만으로 완료로 보지 않는다 (R11)
        problems = verify_area(layout, manifest, user, area, live=True)
        if problems:
            raise MigrationError(
                "activation_state",
                f"user_key {user_key}: 대상 {area} 가 있지만 manifest 와 다릅니다 — 수동 확인이 필요합니다:\n- " + "\n- ".join(problems),
            )
        return "verified"
    raise MigrationError("activation_state", f"user_key {user_key}: {area} 영역이 staging 에도 대상에도 없습니다 — 수동 확인이 필요합니다.")


def _user_manifest(layout: Layout, manifest: Dict[str, Any], user_key: str) -> None:
    live = layout.live_paths(user_key)
    current = read_json_optional(live.manifest) or {"format": "ms365-user-manifest", "user_key": user_key}
    entries = [m for m in current.get("migrations", []) if m.get("run_id") != manifest["run_id"]]
    entries.append({
        "run_id": manifest["run_id"],
        "activated_at": utcnow_iso(),
        "rows": manifest["expected"][user_key],
        "files": manifest["expected_files"][user_key],
    })
    current["migrations"] = entries
    write_json(live.manifest, current, root=live.root)


def run_activate(layout: Layout, manifest: Dict[str, Any], *, confirm: bool) -> Dict[str, Any]:
    if not confirm:
        raise MigrationError("confirm_required", "activate 는 운영 저장소를 바꿉니다 — 확인하려면 --yes 를 붙이세요.")
    require_no_conflicts(manifest)
    run_id = manifest["run_id"]
    journal_path = _journal_path(layout, manifest)
    journal = read_json_optional(journal_path)
    if journal is not None:
        _check_journal_identity(journal, manifest)
        if journal.get("status") == "complete":
            # 완료 **이력**일 뿐이다 — 현재 live 상태(사용자가 그 뒤 쓴 데이터 포함)는 검증하지 않는다
            return {"status": "ok", "run_id": run_id, "already_active": True,
                    "completion": "journal", "completed_at": journal.get("completed_at"),
                    "current_state": "unverified",
                    "next": "현재 live 상태를 검증하려면 `verify --live` (이전 뒤 사용자가 쓴 데이터가 있으면 달라진다)."}

    # 처음이든 재개든: 서버 정지·lock·원본 fingerprint·매핑·registry·배정 digest 재검사 (R10)
    prepare(layout, manifest)
    users = {u["user_key"]: u for u in manifest["users"]}

    if journal is None:
        report = run_verify(layout, manifest)
        if report["status"] != "ok":
            raise MigrationError("verify_failed", f"verify 실패 {len(report['problems'])}건 — activate 하지 않습니다.")
        problems = _precheck(layout, manifest)
        if problems:
            raise MigrationError("target_not_empty", "activate 사전 검사 실패:\n- " + "\n- ".join(problems))
        journal = {
            "run_id": run_id,
            "manifest_sha256": manifest["_sha256"],
            "status": "moving",
            "started_at": utcnow_iso(),
            "moves": {uk: {area: "pending" for area in AREAS} for uk in sorted(users)},
        }
        write_json(journal_path, journal, root=layout.migration)
    else:
        problems = _resume_problems(layout, manifest, journal)
        if problems:
            raise MigrationError("activation_state", "activate 재개 검사 실패:\n- " + "\n- ".join(problems))

    result: Dict[str, Any] = {}
    for user_key in sorted(journal["moves"]):
        user = users[user_key]
        staging = layout.staging_paths(user_key)
        for area in AREAS:
            if journal["moves"][user_key][area] == "done":
                continue
            _move_area(layout, manifest, user, area)
            journal["moves"][user_key][area] = "done"
            write_json(journal_path, journal, root=layout.migration)
        _user_manifest(layout, manifest, user_key)
        if staging.root.exists() and not has_files(staging.root):
            shutil.rmtree(staging.root)  # 남은 것은 빈 auth/ 뿐
        result[user_key] = "active"
        audit_event("activate", "success", user_key=user_key)

    # 옮긴 결과 전체를 live 위치에서 한 번 더 검증한 뒤에야 완료로 적는다 — 실패하면 journal 은 moving 으로 남고
    # 다음 재개가 같은 검사를 다시 한다 (사용자 검사·수동 복구 뒤).
    live_report = run_verify(layout, manifest, live=True)
    if live_report["status"] != "ok":
        raise MigrationError(
            "activation_state",
            f"옮긴 뒤 live 검증 실패 {len(live_report['problems'])}건 — 완료로 기록하지 않습니다. reports/ 를 확인하세요.",
        )
    if layout.staging_users.is_dir() and not any(layout.staging_users.iterdir()):
        layout.staging_marker.unlink(missing_ok=True)
    journal["status"] = "complete"
    journal["completed_at"] = utcnow_iso()
    write_json(journal_path, journal, root=layout.migration)
    audit_event("activate", "success")
    return {
        "status": "ok",
        "run_id": run_id,
        "users": result,
        "completion": "now",
        "current_state": "verified",
        "next": "MS365_MULTI_USER=1 로 auth gateway 와 도메인 HTTP 서버를 다시 기동하세요. legacy 저장소는 "
                "읽기 전용으로 보관하고 maintenance lock 은 그대로 둡니다(되돌리려면 `unlock --yes`).",
    }


__all__ = ["AREAS", "run_activate"]
