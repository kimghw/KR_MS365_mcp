"""
FileHandler 사용자 저장소 초기화 — `ensure_storage(principal, paths)` (spec/spec_멀티유저.md ②-11.1).

멀티유저에서 FileHandler 가 쓰는 DB 는 사용자별 `db/metadata.db` 하나이고, 테이블은
`file_metadata (owner_key, file_url, ...) PRIMARY KEY (owner_key, file_url)` 다.

- 해당 사용자 저장소만 초기화한다. Graph 호출·기본 사용자 탐색을 하지 않는다.
- `db/` 가 링크·junction 이면 거부한다(파일 루트와 업무 DB 를 잇는 우회 금지, ②-7.2).
- 마이그레이션 도구(WP11)와 서비스 `initialize()` 가 같은 함수를 쓴다.
"""

from mcp_common.principal import Principal
from mcp_common.secure_files import UnsafePathError, ensure_within
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.user_paths import UserPaths

from .metadata.storage import OWNED_TABLE, init_owned_schema


def ensure_storage(principal: Principal, paths: UserPaths) -> None:
    if principal.user_key != paths.user_key:
        raise SecurityError(ErrorCode.CONFIG_ERROR, "principal 과 사용자 경로가 다른 사용자입니다.")
    paths.db_dir.mkdir(parents=True, exist_ok=True)
    try:
        ensure_within(paths.db_dir, paths.root)
        ensure_within(paths.metadata_db, paths.db_dir)
    except UnsafePathError:
        raise SecurityError(ErrorCode.CONFIG_ERROR, "사용자 DB 경로가 링크입니다.") from None
    init_owned_schema(paths.metadata_db)


__all__ = ["OWNED_TABLE", "ensure_storage"]
