"""
소유자 매핑 파일 — `legacy_email → (tenant_id, object_id)` 와 소유자 없는 데이터의 명시 귀속.

형식은 패키지 docstring(`tools/migrate_multi_user/__init__.py`)이 원본이다. 여기서는
**모르는 키를 거부**한다 — 매핑 파일에 토큰·비밀이 섞여 들어올 자리를 두지 않는다.

- 이메일 비교는 `normalize_email_for_compare`(NFKC → strip → casefold). 이 비교는 legacy 행의
  `user_id` 와 매핑 줄을 맞추는 데만 쓴다 — 새 저장소의 소유권은 user_key 다.
- 같은 이메일이 서로 다른 사용자에 걸리면 **충돌**(apply 가 거부)이고, 그 이메일의 데이터는
  어느 쪽에도 배정하지 않는다.
- 오류·충돌 메시지에는 이메일 대신 `users[3]` 같은 위치만 쓴다.
"""

import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mcp_common.principal import compute_user_key, normalize_email_for_compare

from .common import FILE_SOURCES, MigrationError, sha256_bytes

#: 이메일이 두 사용자에 걸려 어느 쪽에도 배정할 수 없음.
AMBIGUOUS = "<ambiguous>"

_TOP_KEYS = {"version", "users", "owners", "comment"}
_USER_KEYS = {"legacy_email", "tenant_id", "object_id", "comment"}
_OWNER_KEYS = {
    "metadata_db", "metadata_db_rows",
    "metadata_json", "metadata_json_rows",
    "mail_metadata", "mail_metadata_rows",
    "paths",
}
_RULE_KEYS = {"path", "owner", "comment"}
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+$")


def norm_part(part: str) -> str:
    """경로 성분 비교 키 — Windows 는 대소문자를 구분하지 않는다."""
    return part.casefold() if os.name == "nt" else part


@dataclass(frozen=True)
class MappedUser:
    user_key: str
    tenant_id: str
    object_id: str
    legacy_emails: Tuple[str, ...]


@dataclass(frozen=True)
class PathRule:
    index: int
    source: str
    parts: Tuple[str, ...]  # norm_part 적용본
    owner: str              # user_key


@dataclass
class Mapping:
    path: str
    sha256: str
    users: Dict[str, MappedUser]
    email_owner: Dict[str, str]  # 정규화 이메일 → user_key | AMBIGUOUS
    whole_owner: Dict[str, Optional[str]] = field(default_factory=dict)  # metadata_db|metadata_json|mail_metadata
    row_owner: Dict[str, Dict[str, str]] = field(default_factory=dict)   # 같은 키 + 행 키 → user_key
    rules: List[PathRule] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)

    def owner_of_email(self, email: Any) -> Optional[str]:
        """legacy 행의 user_id → user_key. 매핑 없으면 None, 모호하면 AMBIGUOUS."""
        if not isinstance(email, str) or not email.strip():
            return None
        return self.email_owner.get(normalize_email_for_compare(email))

    def owner_of_path(self, source: str, parts: Tuple[str, ...]) -> Tuple[Optional[str], Optional[str]]:
        """파일 → (user_key, 사유). 규칙 0개면 unowned, 소유자 2명 이상이면 ambiguous_owner."""
        key = tuple(norm_part(p) for p in parts)
        owners = {
            rule.owner
            for rule in self.rules
            if rule.source == source and key[: len(rule.parts)] == rule.parts
        }
        if not owners:
            return None, "unowned"
        if len(owners) > 1:
            return None, "ambiguous_owner"
        return owners.pop(), None

    def summary(self) -> List[Dict[str, Any]]:
        """manifest 용 사용자 목록 (legacy 이메일 포함 — manifest 는 관리자 전용)."""
        return [
            {
                "user_key": u.user_key,
                "tenant_id": u.tenant_id,
                "object_id": u.object_id,
                "legacy_emails": list(u.legacy_emails),
            }
            for u in sorted(self.users.values(), key=lambda u: u.user_key)
        ]


# ----------------------------------------------------------------------
# 파싱
# ----------------------------------------------------------------------
def _bad(where: str, why: str) -> MigrationError:
    return MigrationError("mapping_invalid", f"매핑 파일 {where}: {why}")


def _check_keys(obj: Any, allowed: set, where: str) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        raise _bad(where, "객체(JSON object)여야 합니다")
    unknown = sorted(set(obj) - allowed)
    if unknown:
        # 모르는 키 이름만 알린다(값은 싣지 않는다)
        raise _bad(where, f"알 수 없는 키 {unknown}")
    return obj


def _email(value: Any, where: str) -> str:
    if not isinstance(value, str) or len(value) > 320 or not _EMAIL_RE.match(value.strip()):
        raise _bad(where, "이메일 형식이 아닙니다")
    return value.strip()


def parse_rule_path(raw: Any, where: str) -> Tuple[str, Tuple[str, ...]]:
    """`downloads/a/b` → ("downloads", ("a", "b")). 절대경로·드라이브·`..` 거부."""
    if not isinstance(raw, str) or not raw.strip():
        raise _bad(where, "경로 문자열이 필요합니다")
    text = raw.strip().replace("\\", "/")
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise _bad(where, "원본 디렉터리 기준 상대경로여야 합니다")
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if not parts or parts[0] not in FILE_SOURCES:
        raise _bad(where, f"첫 성분은 {list(FILE_SOURCES)} 중 하나여야 합니다")
    if any(p == ".." or ":" in p for p in parts):
        raise _bad(where, "'..'·':' 성분은 쓸 수 없습니다")
    return parts[0], tuple(norm_part(p) for p in parts[1:])


def load_mapping(path: Path) -> Mapping:
    path = Path(path)
    try:
        raw_bytes = path.read_bytes()
    except OSError:
        raise MigrationError("mapping_missing", "매핑 파일을 읽을 수 없습니다.") from None
    import json

    try:
        doc = json.loads(raw_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise _bad("(전체)", "JSON 으로 읽을 수 없습니다") from None
    _check_keys(doc, _TOP_KEYS, "(최상위)")
    if doc.get("version", 1) != 1:
        raise _bad("version", "지원하는 값은 1 입니다")
    users_raw = doc.get("users")
    if not isinstance(users_raw, list) or not users_raw:
        raise _bad("users", "사용자 매핑 목록이 비어 있습니다")

    conflicts: List[str] = []
    users: Dict[str, MappedUser] = {}
    emails_of: Dict[str, List[str]] = {}
    email_owner: Dict[str, str] = {}
    first_seen: Dict[str, int] = {}

    for i, entry in enumerate(users_raw):
        where = f"users[{i}]"
        _check_keys(entry, _USER_KEYS, where)
        email = _email(entry.get("legacy_email"), f"{where}.legacy_email")
        try:
            user_key = compute_user_key(str(entry.get("tenant_id")), str(entry.get("object_id")))
        except ValueError:
            raise _bad(where, "tenant_id·object_id 는 UUID 여야 합니다") from None
        tid = str(uuid.UUID(str(entry["tenant_id"]).strip())).lower()
        oid = str(uuid.UUID(str(entry["object_id"]).strip())).lower()
        known = users.get(user_key)
        if known is None:
            users[user_key] = MappedUser(user_key, tid, oid, ())
        key = normalize_email_for_compare(email)
        previous = email_owner.get(key)
        if previous is None:
            email_owner[key] = user_key
            first_seen[key] = i
            emails_of.setdefault(user_key, []).append(email)
        elif previous not in (user_key, AMBIGUOUS):
            conflicts.append(
                f"{where}.legacy_email 이 users[{first_seen[key]}] 와 같은 이메일인데 다른 사용자입니다 "
                "— 그 이메일의 데이터는 어느 쪽에도 배정하지 않습니다"
            )
            email_owner[key] = AMBIGUOUS

    def _kept(uk: str) -> Tuple[str, ...]:
        # 모호해진 이메일은 어느 사용자의 legacy 이메일로도 남기지 않는다
        return tuple(sorted({e for e in emails_of.get(uk, []) if email_owner.get(normalize_email_for_compare(e)) == uk}))

    users = {uk: MappedUser(u.user_key, u.tenant_id, u.object_id, _kept(uk)) for uk, u in users.items()}
    mapping = Mapping(
        path=str(path.resolve()),
        sha256=sha256_bytes(raw_bytes),
        users=users,
        email_owner=email_owner,
        conflicts=conflicts,
    )
    _parse_owners(mapping, doc.get("owners") or {})
    return mapping


def _owner_ref(mapping: Mapping, value: Any, where: str) -> str:
    email = _email(value, where)
    owner = mapping.email_owner.get(normalize_email_for_compare(email))
    if owner is None:
        raise _bad(where, "users 의 legacy_email 에 없는 소유자입니다")
    if owner == AMBIGUOUS:
        raise _bad(where, "두 사용자에 걸린 이메일이라 소유자로 쓸 수 없습니다")
    return owner


def _parse_owners(mapping: Mapping, owners: Any) -> None:
    _check_keys(owners, _OWNER_KEYS, "owners")
    for name in ("metadata_db", "metadata_json", "mail_metadata"):
        value = owners.get(name)
        mapping.whole_owner[name] = None if value is None else _owner_ref(mapping, value, f"owners.{name}")
        rows = owners.get(f"{name}_rows") or {}
        if not isinstance(rows, dict):
            raise _bad(f"owners.{name}_rows", "객체(행 키 → 소유자 이메일)여야 합니다")
        mapping.row_owner[name] = {
            str(row_key): _owner_ref(mapping, owner, f"owners.{name}_rows[{n}]")
            for n, (row_key, owner) in enumerate(sorted(rows.items()))
        }

    rules_raw = owners.get("paths") or []
    if not isinstance(rules_raw, list):
        raise _bad("owners.paths", "목록이어야 합니다")
    seen: Dict[Tuple[str, Tuple[str, ...]], Tuple[int, str]] = {}
    for i, rule in enumerate(rules_raw):
        where = f"owners.paths[{i}]"
        _check_keys(rule, _RULE_KEYS, where)
        source, parts = parse_rule_path(rule.get("path"), f"{where}.path")
        owner = _owner_ref(mapping, rule.get("owner"), f"{where}.owner")
        prior = seen.get((source, parts))
        if prior is not None:
            if prior[1] == owner:
                continue
            # 규칙도 함께 남겨 그 경로의 파일이 ambiguous_owner 로 격리되게 한다
            mapping.conflicts.append(f"{where} 와 owners.paths[{prior[0]}] 가 같은 경로에 다른 소유자를 지정합니다")
        else:
            seen[(source, parts)] = (i, owner)
        mapping.rules.append(PathRule(i, source, parts, owner))


__all__ = ["AMBIGUOUS", "MappedUser", "PathRule", "Mapping", "load_mapping", "parse_rule_path", "norm_part"]
