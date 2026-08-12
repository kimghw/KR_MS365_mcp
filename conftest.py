"""pytest 루트 설정.

두 가지 문제를 여기서 한 번에 처리한다.

1) sys.path
   테스트 파일마다 `sys.path.insert(0, ...)` 로 프로젝트 루트를 넣고 있었다.
   루트 conftest.py 는 pytest 가 어떤 디렉터리에서 실행되든 가장 먼저 로드되므로,
   여기서 루트를 한 번만 등록하면 각 테스트의 경로 조작에 의존하지 않아도 된다.

2) Windows 콘솔 인코딩
   테스트들이 한글을 print 하는데 Windows 기본 콘솔은 cp949/cp1252 라
   `UnicodeEncodeError: 'charmap' codec can't encode character ...` 로 수집·실행이 죽는다.
   (그래서 감사 당시 PYTHONUTF8=1 을 줬을 때만 통과했다.)
   pytest ini 로는 콘솔 인코딩을 바꿀 수 없어 여기서 stdout/stderr 를 UTF-8 로 재설정한다.
"""

import sys
from pathlib import Path

# --- 1) 프로젝트 루트를 sys.path 최상단에 등록 ---------------------------------
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --- 2) stdout/stderr 를 UTF-8 로 강제 ----------------------------------------
def _force_utf8_streams() -> None:
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            # errors="replace": 변환 불가 문자가 있어도 테스트를 죽이지 않는다.
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # 이미 detach 된 스트림 등 재설정 불가한 경우는 조용히 넘어간다.
            pass


_force_utf8_streams()
