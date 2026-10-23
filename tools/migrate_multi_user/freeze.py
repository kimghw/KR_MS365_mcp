"""
쓰기 정지(maintenance) lock — 이전 구간 동안 legacy 저장소에 writer 가 붙지 못하게 한다 (R10).

`plan` 이 이전 대상인 **모든 legacy writer 대상 디렉터리**에 `.migration_lock` 을 만든다 —
SQLite 원본(`auth.db`·`onenote.db`·`metadata.db`)과 JSON 메타데이터(`metadata.json`·
`downloads/mail_metadata.json`)의 부모, 그리고 `downloads/`·`output/` 자체(보통 `database/`, legacy
루트, `downloads/`, `output/` 네 곳; 없는 디렉터리는 만든다). 파일 내용은 JSON 한 덩어리 — 비밀·이메일 없음:

    {"format": "ms365-migration-lock", "version": 1, "run_id": ..., "deployment_id": ...,
     "host": ..., "pid": ..., "created_at": ...}

- manifest 에 lock 경로와 sha256 이 기록되고, `apply`·`activate` 는 그 파일이 **같은 내용으로
  남아 있는지** 확인한다(`lock_missing`/`lock_changed` → re-plan). 포트 검사만으로는 stdio·
  백그라운드 writer 정지를 증명할 수 없으므로 lock + 원본 fingerprint 재검사를 함께 쓴다.
- activate 뒤에도 lock 은 **그대로 둔다** — legacy 저장소는 읽기 전용 보관이고 mode 0 서버가
  실수로 다시 쓰면 안 된다. 롤백·중단은 `python -m tools.migrate_multi_user unlock --yes`.
- 같은 배포(deployment_id)의 이전 run 이 남긴 lock 은 새 `plan` 이 이어받는다(run_id 갱신).
  다른 배포의 lock 이나 읽을 수 없는 lock 은 거부한다.

## 런타임(legacy mode 0) 쪽에 필요한 검사 — 이 도구는 런타임 코드를 고치지 않는다

mode 0 저장소를 여는 코드가 **열기 직전**에 같은 디렉터리의 lock 을 보고 거부해야 lock 이
의미를 갖는다. 적용 지점과 규칙(오케스트레이터 적용 대상):

    # mcp_common/security_policy.py (공용 1곳)
    MIGRATION_LOCK_NAME = ".migration_lock"
    ENV_MIGRATION_OVERRIDE = "MS365_MIGRATION_OVERRIDE"

    def assert_legacy_store_not_frozen(db_path) -> None:
        \"\"\"mode 0 전용. db_path 의 디렉터리에 .migration_lock 이 있으면 기동 거부.\"\"\"
        if multi_user_enabled():
            return
        lock = Path(os.path.abspath(db_path)).parent / MIGRATION_LOCK_NAME
        if lock.exists() and os.environ.get(ENV_MIGRATION_OVERRIDE, "").strip() != "1":
            raise StartupConfigError(
                "legacy 저장소가 멀티유저 이전 중(또는 이전 완료)으로 잠겨 있습니다 — "
                "mode 1 로 기동하거나, 되돌리려면 `python -m tools.migrate_multi_user unlock --yes` "
                "또는 MS365_MIGRATION_OVERRIDE=1 (의도적 우회, 감사 기록)."
            )

    호출 지점 (sqlite3.connect / 스키마 생성 **전**):
      1. session/auth_database.py  AuthDatabase.__init__  — self.db_path 확정 직후
      2. mcp_onenote/onenote_db_service.py  OneNoteDBService.__init__  — mode 0 (owner_key is None) 분기, ensure_schema 전
      3. (권고) mcp_file_handler/metadata/storage.py  SQLiteStorage.__init__ / JSONStorage.__init__
      4. (권고) mcp_outlook/mail_attachment.py  MailMetadataManager.__init__ (mail_metadata.json 의 디렉터리)
    1·2 만으로도 Graph 를 쓰는 모든 mode 0 서버(AuthManager → AuthDatabase)와 OneNote DB 가 막힌다.
    `MS365_MIGRATION_OVERRIDE=1` 로 우회할 때는 `audit("admin.config", outcome="success", tool="migration_override")`
    한 줄을 남긴다. lock 파일 이름은 이 모듈의 `LOCK_NAME` 과 같아야 한다.
"""

import json
import os
import socket
from pathlib import Path
from typing import Any, Dict, List, Optional

from .common import FILE_SOURCES, LOCK_NAME, MigrationError, sha256_bytes, utcnow_iso
from .legacy import JSON_SOURCES, SQLITE_SOURCES, Sources

LOCK_FORMAT = "ms365-migration-lock"
LOCK_VERSION = 1


def lock_directories(sources: Sources) -> List[Path]:
    """legacy writer 대상 디렉터리 전부 — SQLite·JSON 메타데이터의 부모 + downloads/·output/ (중복 제거, 정렬)."""
    seen: Dict[str, Path] = {}
    for name in SQLITE_SOURCES + JSON_SOURCES:
        directory = Path(sources.path(name)).parent
        seen.setdefault(os.path.normcase(os.path.abspath(directory)), directory)
    for name in FILE_SOURCES:
        directory = Path(sources.path(name))
        seen.setdefault(os.path.normcase(os.path.abspath(directory)), directory)
    return [seen[k] for k in sorted(seen)]


def lock_paths(sources: Sources) -> List[Path]:
    return [directory / LOCK_NAME for directory in lock_directories(sources)]


def read_lock(path: Path) -> Optional[Dict[str, Any]]:
    """lock 내용. 없으면 None, 있는데 형식이 아니면 `lock_foreign`."""
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        raise MigrationError("lock_foreign", "maintenance lock 을 읽을 수 없습니다 — 수동 확인이 필요합니다.") from None
    try:
        record = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise MigrationError("lock_foreign", "maintenance lock 이 이 도구의 형식이 아닙니다 — 수동 확인이 필요합니다.") from None
    if not isinstance(record, dict) or record.get("format") != LOCK_FORMAT:
        raise MigrationError("lock_foreign", "maintenance lock 이 이 도구의 형식이 아닙니다 — 수동 확인이 필요합니다.")
    record["_sha256"] = sha256_bytes(data)
    return record


def _write_lock(path: Path, record: Dict[str, Any]) -> str:
    from mcp_common.secure_files import atomic_write_bytes

    data = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(Path(path), data)
    return sha256_bytes(data)


def acquire_locks(sources: Sources, *, run_id: str, deployment_id: str) -> List[Dict[str, str]]:
    """lock 을 만들거나(없으면) 같은 배포의 이전 run 것을 이어받는다. manifest 에 실을 목록을 돌려준다."""
    record = {
        "format": LOCK_FORMAT,
        "version": LOCK_VERSION,
        "run_id": run_id,
        "deployment_id": deployment_id,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "created_at": utcnow_iso(),
    }
    out: List[Dict[str, str]] = []
    for path in lock_paths(sources):
        existing = read_lock(path)
        if existing is not None and existing.get("deployment_id") != deployment_id:
            raise MigrationError(
                "lock_foreign",
                "다른 배포의 maintenance lock 이 legacy 저장소에 있습니다 — 그 배포에서 unlock 하거나 수동 확인이 필요합니다.",
            )
        out.append({"path": str(path), "sha256": _write_lock(path, record)})
    return out


def check_locks(manifest: Dict[str, Any]) -> None:
    """manifest 가 기록한 lock 이 같은 내용으로 남아 있어야 한다 — 아니면 쓰기 정지 구간이 깨진 것."""
    for entry in manifest.get("locks", []):
        path = Path(entry["path"])
        existing = read_lock(path)
        if existing is None:
            raise MigrationError(
                "lock_missing",
                "legacy 저장소의 maintenance lock 이 사라졌습니다 — 쓰기 정지가 깨졌을 수 있으니 plan 을 다시 실행하세요.",
            )
        if existing["_sha256"] != entry["sha256"]:
            raise MigrationError(
                "lock_changed",
                "legacy 저장소의 maintenance lock 이 plan 이후 바뀌었습니다(다른 run 이 이어받음) — 최신 manifest 로 진행하세요.",
            )


def release_locks(manifest: Dict[str, Any]) -> List[str]:
    """manifest 의 lock 을 지운다. 다른 run 이 이어받은 lock 은 지우지 않는다."""
    removed: List[str] = []
    for entry in manifest.get("locks", []):
        path = Path(entry["path"])
        existing = read_lock(path)
        if existing is None:
            continue
        if existing.get("run_id") != manifest["run_id"]:
            raise MigrationError("lock_changed", "lock 을 다른 run 이 이어받았습니다 — 그 run 의 manifest 로 unlock 하세요.")
        path.unlink()
        removed.append(str(path))
    return removed


__all__ = [
    "LOCK_NAME",
    "LOCK_FORMAT",
    "lock_directories",
    "lock_paths",
    "read_lock",
    "acquire_locks",
    "check_locks",
    "release_locks",
]
