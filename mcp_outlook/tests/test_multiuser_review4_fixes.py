"""
astra 4차 보안 리뷰(spec/reviews/멀티유저_astra_4차_2026-10-23.md) Q01 회귀.

슬롯 획득을 기다리는 task 가 취소돼도 슬롯이 새지 않는다 — 비차단 `acquire(0)` + `asyncio.sleep`
폴링이라 취소는 슬롯을 쥐지 않은 지점에서만 들어온다. 획득 뒤 스레드가 소유권을 받기 전의
실패(start 실패 등)도 슬롯을 되돌린다.
"""

import asyncio
import threading

import pytest

from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.testing import bound

from mcp_outlook import conversion_workers
from mcp_outlook import outlook_security as limits
from mcp_outlook.conversion_workers import WorkerGroup
from mcp_outlook.mail_attachment_converter import ConversionPipeline
from mcp_outlook.mail_attachment_processor import convert_with_deadline
from mcp_outlook.mcp_server import handlers
from mcp_outlook.tests.multiuser_fakes import *  # noqa: F401,F403 - fixtures


class _Counting(ConversionPipeline):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def convert(self, content, filename):
        self.calls += 1
        return "converted", None


def _free_slots(slots: conversion_workers.UserSlots) -> int:
    """비차단 획득으로 남은 슬롯 수를 센다(세어 본 뒤 전부 되돌린다)."""
    taken = 0
    while slots.acquire(0.0):
        taken += 1
    for _ in range(taken):
        slots.release()
    return taken


@pytest.fixture
def one_slot(monkeypatch):
    conversion_workers.reset_registry_for_tests()
    monkeypatch.setattr(limits, "MAX_CONVERSION_WORKERS", 1)
    monkeypatch.setattr(limits, "CONVERSION_SLOT_TIMEOUT_SECONDS", 5.0)
    yield
    conversion_workers.reset_registry_for_tests()


async def test_q01_cancel_while_waiting_does_not_leak_slot(mu, alice, alice_paths, alice_tokens, monkeypatch, one_slot):
    slots = conversion_workers.slots_for(alice.user_key, 1)
    assert slots.acquire(0.0)  # 다른 요청이 유일한 슬롯을 쥐고 있다
    converter = _Counting()

    waiter = asyncio.create_task(
        convert_with_deadline(converter, b"x", "a.txt", owner_key=alice.user_key, workers=WorkerGroup())
    )
    await asyncio.sleep(0.05)  # 대기 루프에 들어간 상태
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    slots.release()  # 점유자가 슬롯을 돌려준다
    await asyncio.sleep(0.05)
    assert converter.calls == 0
    assert conversion_workers.live_workers(alice.user_key) == 0
    assert _free_slots(slots) == 1  # 취소된 대기자가 뒤늦게 슬롯을 가져가지 않았다

    # 같은 사용자의 새 서비스가 정상 변환된다 (registry 는 프로세스 전역이라 누수가 있었다면 여기서 overloaded)
    mail = mail_with_attachments("m1", [{"name": "doc.txt", "data": b"plain text"}])
    install_http(monkeypatch, batch_router({alice_tokens.token: mail}))
    svc = await handlers.create_service(alice, alice_paths, alice_tokens)
    await svc.initialize()
    with bound(alice):
        result = await svc.download_attachments(
            user_email=ALICE_EMAIL, message_attachment_ids=["m1"], convert_to_txt=True, include_body=False
        )
    assert result["status"] == "success", result
    assert len(result["converted_files"]) == 1
    await svc.close()
    assert conversion_workers.live_workers(alice.user_key) == 0
    assert _free_slots(slots) == 1


async def test_q01_repeated_cancellations_leave_zero_slots(mu, alice, one_slot):
    slots = conversion_workers.slots_for(alice.user_key, 1)
    assert slots.acquire(0.0)
    converter = _Counting()

    tasks = [
        asyncio.create_task(
            convert_with_deadline(converter, b"x", f"{i}.txt", owner_key=alice.user_key, workers=WorkerGroup())
        )
        for i in range(6)
    ]
    # 생성 직후(첫 폴링 전)·대기 중·점유 해제와 거의 동시에 — 여러 시점에서 취소한다
    tasks[0].cancel()
    await asyncio.sleep(0.02)
    for task in tasks[1:4]:
        task.cancel()
    await asyncio.sleep(0.03)
    slots.release()
    for task in tasks[4:]:
        task.cancel()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert all(isinstance(r, asyncio.CancelledError) for r in results), results
    await asyncio.sleep(0.05)
    assert converter.calls == 0
    assert conversion_workers.live_workers(alice.user_key) == 0
    assert _free_slots(slots) == 1


async def test_q01_waiter_proceeds_when_slot_is_released(mu, alice, one_slot):
    slots = conversion_workers.slots_for(alice.user_key, 1)
    assert slots.acquire(0.0)
    converter = _Counting()
    waiter = asyncio.create_task(
        convert_with_deadline(converter, b"x", "a.txt", owner_key=alice.user_key, workers=WorkerGroup())
    )
    await asyncio.sleep(0.05)
    assert not waiter.done()
    slots.release()
    assert await waiter == ("converted", None)
    await asyncio.sleep(0.05)
    assert converter.calls == 1
    assert conversion_workers.live_workers(alice.user_key) == 0
    assert _free_slots(slots) == 1


async def test_q01_timeout_while_waiting_is_overloaded_without_leak(mu, alice, monkeypatch, one_slot):
    monkeypatch.setattr(limits, "CONVERSION_SLOT_TIMEOUT_SECONDS", 0.05)
    slots = conversion_workers.slots_for(alice.user_key, 1)
    assert slots.acquire(0.0)
    with pytest.raises(SecurityError) as err:
        await convert_with_deadline(_Counting(), b"x", "a.txt", owner_key=alice.user_key, workers=WorkerGroup())
    assert err.value.code == ErrorCode.OVERLOADED
    slots.release()
    assert _free_slots(slots) == 1


async def test_q01_thread_start_failure_returns_slot(mu, alice, monkeypatch, one_slot):
    def _boom(self):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", _boom)
    workers = WorkerGroup()
    with pytest.raises(RuntimeError):
        await convert_with_deadline(_Counting(), b"x", "a.txt", owner_key=alice.user_key, workers=workers)
    slots = conversion_workers.slots_for(alice.user_key, 1)
    assert conversion_workers.live_workers(alice.user_key) == 0
    assert _free_slots(slots) == 1
    assert workers.live() == []
