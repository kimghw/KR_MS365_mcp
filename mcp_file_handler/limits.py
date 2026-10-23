"""
요청별 자원 상한 (astra 리뷰 R09, spec/spec_멀티유저.md ②-7.4 규칙 9).

`max_file_size`·`max_total_size` 는 설정에만 있고 실제 다운로드·변환에 연결돼 있지 않았다.
이 모듈이 설정을 **요청 하나의 상한 객체**로 바꾸고, 다운로드 스트림·입력 복사·변환이
같은 객체를 소비한다.

| 설정 키 | 단위 | 기본값 | 적용 지점 |
|---------|------|-------:|-----------|
| `max_file_size` | MB | 100 | 파일 하나 — 다운로드 스트림 누적·로컬 입력 복사(초과 시 중단) |
| `max_total_size` | MB | 500 | 요청 전체 바이트 예산(다운로드 + 입력 복사 합) |
| `max_download_files` | 개 | 200 | 요청 하나가 처리하는 파일 수 — OneDrive 다운로드와 로컬 디렉터리 순회 모두 (N08) |
| `max_folder_depth` | 단계 | 10 | 폴더 재귀 깊이 |
| `max_output_chars` | 문자 | 2,000,000 | 변환 결과 텍스트(파일별·요청 합계, 초과분 절단) |
| `conversion_timeout` | 초 | 300 | 요청 하나의 변환 시간 (마감 뒤 변환 거부, 진행 중 변환은 결과 폐기) |
| `max_workers` | 개 | 4 | 서비스(사용자)당 동시 변환 스레드 — 시간 초과로 버려진 스레드도 이 수에 포함 |

mode 1 은 기본값이 상한이다 — 환경변수·config 로 낮출 수는 있어도 **넓힐 수 없다**
(`config/settings.py` 가 고정한다).
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from mcp_common.errors import ToolExecutionError

MB = 1024 * 1024

#: `save_file_metadata.keywords` 상한 — 스키마(`maxItems`/`maxLength`)와 서비스 경계 clamp 가 같은 값을 쓴다 (R02).
KEYWORDS_MAX_ITEMS = 100
KEYWORD_MAX_LENGTH = 200

#: (설정 키, 기본값). 설정 모듈과 이 모듈이 같은 표를 쓴다.
LIMIT_DEFAULTS: Dict[str, int] = {
    'max_file_size': 100,
    'max_total_size': 500,
    'max_download_files': 200,
    'max_folder_depth': 10,
    'max_output_chars': 2_000_000,
    'conversion_timeout': 300,
    'max_workers': 4,
}


class LimitExceeded(ToolExecutionError):
    """자원 상한 초과. 페이로드는 고정형(경로·이름·원문 없음)이라 mode 1 런타임도 그대로 내보낸다."""

    def __init__(self, code: str, message: Optional[str] = None):
        self.code = code
        self.message = message or _MESSAGES.get(code, code)
        super().__init__({
            "status": "error",
            "error": "limit_exceeded",
            "limit": code,
            "message": self.message,
        })


_MESSAGES = {
    'file_too_large': "파일 크기가 허용 한도를 넘습니다.",
    'request_too_large': "요청의 총 처리 용량이 허용 한도를 넘습니다.",
    'too_many_files': "요청의 파일 수가 허용 한도를 넘습니다.",
    'folder_too_deep': "폴더 깊이가 허용 한도를 넘습니다.",
    'conversion_timeout': "변환 시간이 허용 한도를 넘었습니다.",
    'output_truncated': "변환 결과가 허용 한도를 넘어 잘렸습니다.",
}


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def pin_limits(config: Dict[str, Any]) -> None:
    """mode 1: 설정값이 기본값보다 크면 기본값으로 내린다(넓히기 금지). 잘못된 값은 기본값."""
    for key, default in LIMIT_DEFAULTS.items():
        config[key] = min(_positive_int(config.get(key), default), default)


class ByteBudget:
    """요청 전체 바이트 예산 (스레드 안전). 초과하는 순간 `LimitExceeded('request_too_large')`."""

    def __init__(self, total: int):
        self.total = total
        self.used = 0
        self._lock = threading.Lock()

    def consume(self, amount: int) -> None:
        with self._lock:
            if self.used + amount > self.total:
                raise LimitExceeded('request_too_large')
            self.used += amount


@dataclass
class RequestLimits:
    """요청 하나의 상한. `FileManager` 가 도구 호출마다 새로 만든다."""

    max_file_bytes: int
    max_files: int
    max_depth: int
    max_output_chars: int
    deadline: float
    budget: ByteBudget
    max_workers: int = 4
    files: int = 0
    output_chars: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def from_settings(cls, settings: Any) -> "RequestLimits":
        get = settings.get if settings is not None else (lambda key, default=None: default)
        value = {key: _positive_int(get(key, default), default) for key, default in LIMIT_DEFAULTS.items()}
        return cls(
            max_file_bytes=value['max_file_size'] * MB,
            max_files=value['max_download_files'],
            max_depth=value['max_folder_depth'],
            max_output_chars=value['max_output_chars'],
            deadline=time.monotonic() + value['conversion_timeout'],
            budget=ByteBudget(value['max_total_size'] * MB),
            max_workers=value['max_workers'],
        )

    # ------------------------------------------------------------------
    def remaining_seconds(self) -> float:
        return self.deadline - time.monotonic()

    def check_deadline(self) -> None:
        if self.remaining_seconds() <= 0:
            raise LimitExceeded('conversion_timeout')

    def count_file(self) -> None:
        with self._lock:
            if self.files + 1 > self.max_files:
                raise LimitExceeded('too_many_files')
            self.files += 1

    def check_depth(self, depth: int) -> None:
        if depth > self.max_depth:
            raise LimitExceeded('folder_too_deep')

    def check_file_size(self, size: int) -> None:
        if size > self.max_file_bytes:
            raise LimitExceeded('file_too_large')

    def cap_output(self, text: str) -> tuple:
        """결과 텍스트를 파일별·요청 합계 상한으로 자른다. (텍스트, 잘렸는지)"""
        with self._lock:
            allowed = max(0, min(self.max_output_chars, self.max_output_chars - self.output_chars))
            truncated = len(text) > allowed
            kept = text[:allowed] if truncated else text
            self.output_chars += len(kept)
        return kept, truncated


class StreamGuard:
    """스트림 쓰기 누적 바이트를 파일 상한·요청 예산에 동시에 적용한다."""

    def __init__(self, limits: Optional[RequestLimits]):
        self.limits = limits
        self.written = 0

    def check_declared(self, content_length: Any) -> None:
        if self.limits is None:
            return
        try:
            declared = int(content_length)
        except (TypeError, ValueError):
            return
        if declared > 0:
            self.limits.check_file_size(declared)

    def add(self, amount: int) -> None:
        self.written += amount
        if self.limits is None:
            return
        self.limits.check_file_size(self.written)
        self.limits.budget.consume(amount)


__all__ = [
    "MB",
    "KEYWORDS_MAX_ITEMS",
    "KEYWORD_MAX_LENGTH",
    "LIMIT_DEFAULTS",
    "LimitExceeded",
    "ByteBudget",
    "RequestLimits",
    "StreamGuard",
    "pin_limits",
]
