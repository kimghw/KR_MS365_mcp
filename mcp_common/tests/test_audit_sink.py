"""WP10 감사 로그 — 허용 필드·값 정화·파일 sink (spec/spec_멀티유저.md ②-9, 테스트 R01)."""

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mcp_common import audit as audit_mod
from mcp_common.audit import EVENTS, FIELDS, OUTCOMES, audit, resource_hmac
from mcp_common.security_policy import ensure_deployment
from mcp_common.testing import bound, make_principal, multi_user_mode, single_user_mode
from mcp_common.user_paths import system_paths

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALLOWED = set(FIELDS) | {"resource"}

CANARY_KEY = "m365v1." + "c" * 32 + ".CANARYSECRETCANARYSECRETCANARYSECRET0000000"
CANARY_JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJjYW5hcnkifQ.CANARYSIG"
CANARY_EMAIL = "canary.user@contoso.com"
CANARY_CODE = "code=CANARYCODE123&state=CANARYSTATE"
CANARIES = (CANARY_KEY, "CANARYSECRET", CANARY_JWT, CANARY_EMAIL, "CANARYCODE", "CANARYSTATE")


def _lines(root: Path):
    out = []
    for f in sorted((root / "system" / "audit").glob("audit-*.jsonl")):
        out.extend(json.loads(line) for line in f.read_text(encoding="utf-8").splitlines())
    return out


# ----------------------------------------------------------------------
# 계약
# ----------------------------------------------------------------------
def test_fields_match_spec_allow_list():
    assert FIELDS == (
        "timestamp", "deployment_id", "request_id", "user_key", "credential_id", "auth_epoch",
        "domain", "tool", "event", "outcome", "error_code", "duration_ms",
    )
    assert "path.denied" in EVENTS and OUTCOMES == {"success", "failure", "denied"}


def test_unknown_event_or_outcome_is_rejected():
    with pytest.raises(ValueError):
        audit("mail.read", outcome="success")
    with pytest.raises(ValueError):
        audit("tool.call", outcome="ok")


def test_no_free_form_arguments():
    with pytest.raises(TypeError):
        audit("tool.call", outcome="success", email="alice@contoso.com")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        audit("tool.call", "success")  # type: ignore[misc]


def test_principal_fields_and_context_autofill():
    alice = make_principal("alice@contoso.com", auth_epoch=3, credential_id="a" * 32)
    with single_user_mode(), bound(alice, request_id="req-ctx-000001"):
        record = audit("tool.call", outcome="success", domain="outlook", tool="mail_send", duration_ms=12.6)
    assert record["user_key"] == alice.user_key
    assert record["credential_id"] == "a" * 32
    assert record["auth_epoch"] == 3
    assert record["request_id"] == "req-ctx-000001"
    assert record["duration_ms"] == 13
    assert set(record) <= ALLOWED
    assert "alice" not in json.dumps(record)


def test_explicit_user_key_is_not_overridden_by_context():
    alice = make_principal("alice@contoso.com")
    bob = make_principal("bob@contoso.com")
    with single_user_mode(), bound(alice):
        record = audit("key.revoke", outcome="success", user_key=bob.user_key)
    assert record["user_key"] == bob.user_key


# ----------------------------------------------------------------------
# 값 정화 (R01)
# ----------------------------------------------------------------------
def test_values_outside_allowed_formats_are_never_recorded():
    with single_user_mode():
        record = audit(
            "auth.bearer",
            outcome="failure",
            request_id=CANARY_EMAIL,
            user_key=CANARY_EMAIL,
            credential_id=CANARY_KEY,
            domain="outlook " + CANARY_EMAIL,
            tool=CANARY_JWT + " " + CANARY_CODE,
            error_code="invalid token " + CANARY_KEY,
            duration_ms="12",  # type: ignore[arg-type]
            resource="https://contoso.sharepoint.com/s/" + CANARY_CODE,
        )
    line = json.dumps(record, ensure_ascii=False)
    for canary in CANARIES:
        assert canary not in line
    assert "user_key" not in record and "credential_id" not in record and "duration_ms" not in record
    assert record["request_id"].startswith("x-")
    assert record["domain"] == record["tool"] == record["error_code"] == "invalid"
    assert len(record["resource"]) == 32 and set(record["resource"]) <= set("0123456789abcdef")
    assert set(record) <= ALLOWED


def test_fake_principal_object_cannot_inject_values():
    class Evil:
        user_key = CANARY_EMAIL
        credential_id = CANARY_KEY
        auth_epoch = "1; DROP"

    with single_user_mode():
        record = audit("tool.call", outcome="denied", principal=Evil())
    assert set(record) == {"timestamp", "event", "outcome"}


def test_resource_hmac_is_keyed_and_deterministic(monkeypatch):
    with single_user_mode():
        monkeypatch.setenv("MS365_AUDIT_HMAC_KEY", "k1")
        a1, a2 = resource_hmac("page-1"), resource_hmac("page-1")
        monkeypatch.setenv("MS365_AUDIT_HMAC_KEY", "k2")
        b = resource_hmac("page-1")
    assert a1 == a2 != b and len(a1) == 32
    with single_user_mode():
        record = audit("tool.call", outcome="success", resource=a1)
    assert record["resource"] == a1


# ----------------------------------------------------------------------
# sink
# ----------------------------------------------------------------------
def test_mode0_writes_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with single_user_mode():
        audit("tool.call", outcome="success")
    assert not any(tmp_path.rglob("audit-*.jsonl"))


def test_mode1_appends_jsonl_with_deployment_id(tmp_path):
    with multi_user_mode(tmp_path) as root:
        marker = ensure_deployment()
        alice = make_principal("alice@contoso.com")
        audit("auth.bearer", outcome="success", principal=alice, request_id="req-000000001", domain="calendar")
        audit("auth.bearer", outcome="failure", error_code="unauthenticated", domain="calendar")
        records = _lines(root)
    assert [r["outcome"] for r in records] == ["success", "failure"]
    assert all(r["deployment_id"] == marker["deployment_id"] for r in records)
    assert all(set(r) <= ALLOWED for r in records)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    assert (root / "system" / "audit" / f"audit-{day}.jsonl").is_file()


def test_audit_does_not_create_deployment_marker(tmp_path):
    with multi_user_mode(tmp_path) as root:
        record = audit("tool.call", outcome="success")
        assert "deployment_id" not in record
        assert not system_paths().deployment_json.exists()
    assert _lines(root)


def test_sink_rotates_per_utc_day(tmp_path, monkeypatch):
    class FakeDateTime(datetime):
        current = datetime(2026, 1, 2, 23, 59, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(audit_mod, "datetime", FakeDateTime)
    with multi_user_mode(tmp_path) as root:
        audit("tool.call", outcome="success")
        FakeDateTime.current = datetime(2026, 1, 3, 0, 1, tzinfo=timezone.utc)
        audit("tool.call", outcome="success")
    names = sorted(p.name for p in (root / "system" / "audit").iterdir())
    assert names == ["audit-20260102.jsonl", "audit-20260103.jsonl"]


def test_threads_append_whole_lines(tmp_path):
    with multi_user_mode(tmp_path) as root:
        principal = make_principal("alice@contoso.com")

        def worker(n):
            for i in range(50):
                audit("tool.call", outcome="success", principal=principal, request_id=f"req-{n:02d}-{i:04d}")

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        records = _lines(root)
    assert len(records) == 400
    assert len({r["request_id"] for r in records}) == 400


def test_processes_append_without_interleaving(tmp_path):
    """8개 도메인 프로세스가 같은 파일에 쓴다 — OS 수준 append 로 줄이 깨지지 않아야 한다."""
    root = tmp_path / "data"
    code = (
        "import sys\n"
        "from mcp_common.audit import audit\n"
        "n = int(sys.argv[1])\n"
        "for i in range(150):\n"
        "    audit('tool.call', outcome='success', request_id=f'p{n}-{i:05d}', tool='t' * 60)\n"
    )
    env = {**os.environ, "MS365_MULTI_USER": "1", "MS365_DATA_ROOT": str(root), "PYTHONPATH": str(PROJECT_ROOT)}
    env.pop("MCP_ALLOWED_PATHS", None)
    procs = [
        subprocess.Popen([sys.executable, "-c", code, str(n)], env=env, cwd=str(PROJECT_ROOT),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for n in range(4)
    ]
    assert all(p.wait(60) == 0 for p in procs)
    records = _lines(root)  # 깨진 줄이 있으면 json.loads 가 실패한다
    assert len(records) == 600
    assert len({r["request_id"] for r in records}) == 600


def test_sink_failure_never_raises(tmp_path, monkeypatch):
    def boom(path, line):
        raise OSError("disk full")

    with multi_user_mode(tmp_path):
        monkeypatch.setattr(audit_mod, "_append_line", boom)
        record = audit("tool.call", outcome="success")
    assert record["event"] == "tool.call"


def test_sink_unwritable_path_never_raises(tmp_path, monkeypatch):
    directory = tmp_path / "is_a_dir.jsonl"
    directory.mkdir()
    monkeypatch.setattr(audit_mod, "_audit_file", lambda: str(directory))
    with single_user_mode():
        assert audit("tool.call", outcome="failure")["outcome"] == "failure"


def test_audit_logger_line_has_only_allowed_fields(caplog):
    with single_user_mode(), caplog.at_level("INFO", logger="ms365.audit"):
        audit("oauth.fail", outcome="failure", error_code="invalid_grant", user_key=CANARY_EMAIL)
    line = [r.getMessage() for r in caplog.records if r.name == "ms365.audit"][-1]
    parsed = json.loads(line)
    assert set(parsed) <= ALLOWED and CANARY_EMAIL not in line
