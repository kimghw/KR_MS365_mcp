"""
단일 운영자(mode 0) 저장소 → 멀티유저(mode 1) 사용자별 저장소 이전 (spec/spec_멀티유저.md ②-8.2~8.4).

    python -m tools.migrate_multi_user plan --mapping mapping.json [--legacy-root DIR]
    python -m tools.migrate_multi_user apply    [--manifest FILE] [--reset-staging]
    python -m tools.migrate_multi_user verify   [--manifest FILE]
    python -m tools.migrate_multi_user activate [--manifest FILE] --yes

멀티유저 환경(`MS365_MULTI_USER=1`, `MS365_DATA_ROOT`)에서, `python -m session.admin_cli init`
과 `user add` 를 마친 뒤 실행한다. 명령행으로 토큰·client secret·bearer key 를 받지 않으며,
화면 출력에는 이메일을 싣지 않는다(사용자는 user_key 로만 표시).

## 단계

| 명령 | 하는 일 | 쓰는 곳 (`<MS365_DATA_ROOT>/system/migration/`) |
|------|---------|------|
| `plan` | legacy DB 를 SQLite backup API 로 snapshot, 원본·파일 hash, 소유자 배정 계산, 충돌 검사 | `snapshots/<run_id>/`, `manifests/<run_id>.json(.sha256)` |
| `apply` | manifest 를 다시 계산해 digest 대조 → 사용자별 staging 저장소 생성(`ensure_storage`) → owner_key 로 행 삽입·파일 복사 → 모호한 데이터는 격리 | `staging/users/<user_key>/`, `quarantine/<run_id>/`, `checkpoints/` |
| `verify` | 행 수·owner_key·user_id 귀속·파일 hash·다른 사용자 데이터 부재·격리 보관 확인 | `reports/<run_id>.verify.json` |
| `activate` | 서버 포트·lock·원본 fingerprint·매핑·registry 재검사 → verify → `staging/users/<uk>/{db,files}` 를 `users/<uk>/` 로 원자적 rename. 재개 시 옮긴 영역을 live 에서 재검증 | `users/<user_key>/` |
| `unlock --yes` | legacy 저장소의 쓰기 정지 lock 해제 (롤백·중단) — activate 진행 중이면 거부 | legacy `database/.migration_lock` 등 |

## 쓰기 정지 구간 (R10)

`plan` 은 서버 포트가 열려 있으면 거부하고, legacy SQLite 원본이 있는 디렉터리마다
`.migration_lock`(`freeze.py`)을 만든 뒤 snapshot 을 뜬다. manifest 에 lock 의 hash 가 들어가고
`apply`·`activate` 는 lock 이 그대로인지, 모든 원본 fingerprint·snapshot·매핑·registry 사용자가
plan 때와 같은지 다시 확인한다 — 하나라도 다르면 re-plan. legacy mode 0 저장소를 여는 코드는
그 lock 을 보고 기동을 거부해야 한다(정확한 검사는 `freeze.py` docstring, 런타임 반영은 오케스트레이터).

## 소유자 매핑 파일 (JSON, 필수)

    {
      "version": 1,
      "users": [
        {"legacy_email": "alice@contoso.com", "tenant_id": "<uuid>", "object_id": "<uuid>"},
        {"legacy_email": "alice.old@contoso.com", "tenant_id": "<uuid>", "object_id": "<uuid>"}
      ],
      "owners": {
        "metadata_db": "alice@contoso.com",
        "metadata_db_rows": {"<file_url>": "bob@contoso.com"},
        "metadata_json": null,
        "metadata_json_rows": {},
        "mail_metadata": "alice@contoso.com",
        "mail_metadata_rows": {"<message_id>": "bob@contoso.com"},
        "paths": [
          {"path": "downloads/alice", "owner": "alice@contoso.com"},
          {"path": "output/report.pdf", "owner": "bob@contoso.com"}
        ]
      }
    }

- 한 사람이 여러 legacy 이메일을 썼으면 같은 `(tenant_id, object_id)` 로 여러 줄을 둔다.
- 매핑된 사용자는 registry 에 **이미 등록**돼 있어야 한다(`session.admin_cli user add`).
- legacy `auth.db` 의 `azure_user_info.object_id` 가 매핑과 다르면 충돌로 막는다.
- `owners.paths[].path` 는 `downloads/...` 또는 `output/...` (원본 디렉터리 기준 상대경로).

## 데이터별 처리 (②-8.3)

| 원본 | 처리 |
|------|------|
| `auth.db` 토큰·앱 설정 | **복사하지 않는다**(행 수만 기록). 사용자는 OIDC 로 새로 연결한다. snapshot 에도 넣지 않는다 |
| `auth.db.teams_chats` | user_id 매핑으로 사용자별 `db/teams.db` 분할 |
| `onenote_items`·`onenote_page_changes` | user_id 매핑으로 사용자별 `db/onenote.db` 분할 |
| `onenote_page_summaries` | 전부 격리(전역 upsert 로 소유권이 섞였을 수 있음) — 사용자별로 다시 생성 |
| `metadata.db`·`metadata.json` | 명시 소유자(전체 또는 행별)만 `db/metadata.db`. 로컬 경로 키는 이전된 파일만 `files/` 기준으로 고쳐 쓴다 |
| `downloads/mail_metadata.json` | 명시 소유자만 `db/outlook.db` (processed_messages/files) |
| `downloads/`·`output/` 파일 | 경로 규칙으로 명시된 것만 `files/downloads/outlook/`·`files/output/`. 로그·DB·백업은 관리자 격리 |

매핑되지 않은 행·파일, 둘 이상의 소유자가 걸린 파일, 위험한 이름은 **어느 사용자에게도 복사하지
않고** `quarantine/<run_id>/` 로 보낸다. 재실행은 사용자 DB 안의 `_ms365_migration` 표식(데이터와
같은 트랜잭션)과 파일 hash 로 중복 없이 이어진다.
"""

__all__ = ["main"]


def main(argv=None, *, load_env: bool = True) -> int:
    from .cli import main as _main

    return _main(argv, load_env=load_env)
