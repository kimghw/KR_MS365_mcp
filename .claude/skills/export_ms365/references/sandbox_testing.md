# Windows Sandbox 검증

## 왜 샌드박스인가

호스트에는 `.venv`, 이미 깔린 `aiohttp`/`mcp`, 채워진 `.env`, 살아 있는 `auth.db` 가 있다.
번들이 그중 무엇에 몰래 기대고 있어도 호스트에서는 통과한다. 샌드박스는 매번 **백지
Windows** 라 그게 통하지 않는다 — 받은 사람이 겪을 순서를 그대로 겪는다.

## 전제

```powershell
Get-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM   # State: Enabled
Test-Path "$env:WINDIR\System32\WindowsSandbox.exe"                            # True
```

꺼져 있으면:

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -All   # 재부팅 필요
```

Windows 11 Pro/Enterprise/Education 에서만 된다. Home 에는 없다.

## 흐름

| 위치 | 하는 일 |
|---|---|
| 호스트 `sandbox_test.py` | `in/<번들>`(읽기 전용) + `out/`(쓰기) 준비 → `.wsb` 생성 → `WindowsSandbox.exe` 기동 → `out/done.json` 을 기다리며 `out/progress.json` 을 따라 출력 |
| 게스트 `sandbox_runner.ps1` | 번들을 `C:\work` 로 복사 → **uv 설치**(공식 `install.ps1`) → `uv sync --frozen` → `uv run --frozen verify_bundle.py --http` → 결과를 `out/` 에 쓰고 **자동 종료** |

게스트가 `shutdown /s` 를 부르면 샌드박스가 닫힌다. 디버깅하려면 `--no-shutdown` 을 줘서
창을 열어 둔 채 안에서 직접 들여다본다. 샌드박스는 분리해서 띄우므로 호스트 스크립트가
시간 초과로 끝나도 게스트는 계속 돈다 — 상태를 사후에 확인할 수 있다.

## 환경 구성은 `uv sync --frozen` 한 줄

Python 도 의존성도 이 한 줄이 한다. 번들에 들어 있는 `.python-version` 이 정한 Python 을
uv 가 받아오고, `uv.lock` 에 적힌 조합 그대로 깐다. **Python 을 따로 조달하는 단계는 없다** —
예전의 `--python-method embed|installer` 와 러너의 `-PyVersion`/`-PyMethod` 인자는 제거됐다.
Python 버전을 바꾸려면 원본의 `.python-version` 을 고치고 번들을 다시 만든다.

`--frozen` 은 "잠금을 다시 풀지 말라"는 뜻이다. **잠금이 실제로 재현되는지 보는 것이 이
검증의 핵심**이므로 여기서는 반드시 붙인다. 잠금 없이 그날의 최신본을 받으면 어떻게 되는지는
이미 겪었다 — `mcp` 2.x 가 깔려 `Server.list_tools` 가 사라지면서 6개 서버가 전부 기동에
실패했다(2026-09-16). 그래서 `pyproject.toml` 이 `mcp>=1.29,<2` 로 제약돼 있다.

공식 Python 설치본이 `/quiet` 로 15분 멎던 문제는 uv 로 오면서 문제 자체가 사라졌다
(상세: [references/windows_sandbox.md](../../../../references/windows_sandbox.md) 함정 4).

## 단계별 소요 (2026-09-16 실측, 6개 서버 번들)

| 단계 | 대략 |
|---|---|
| 샌드박스 부팅 + 로그온 | ~21초 |
| 번들 복사 | 수 초 |
| uv 설치 | ~6초 |
| `uv sync --frozen` (Python 조달 + 의존성) | ~9초 |
| `verify_bundle.py --http` | 서버당 5~15초 |

전체 **1~2분**이다. pip 경로였을 때의 4~8분에서 줄었다. 기본 `--timeout 900`(15분)은
그대로 넉넉하다 — 회선이 느려도 여유가 있다.

## 검사 항목 (`verify_bundle.py`)

| 검사 | 내용 |
|---|---|
| `structure` | 매니페스트가 말하는 서버 3파일(handlers/stdio/stream)과 공용 구성이 실제로 있는가 |
| `secrets` | `.env` / `*.db` / `*.pem` 이 번들에 섞였는가 |
| `imports:<서버>` | `handlers` 모듈 import 성공 + `MCP_TOOLS` 가 비어 있지 않은가 |
| `schema:<서버>` | 도구마다 `description` 과 dict 형 `inputSchema` 가 있는가 |
| `http:<서버>` | `server_stream.py` 를 실제로 띄워 `/health` 가 응답하는가 (`tool_count` 확인) |

`--http` 는 포트가 이미 쓰이면 임의의 빈 포트로 붙는다(`MCP_SERVER_PORT`). 그래서 호스트에서
서버를 띄워 둔 채 돌려도 충돌하지 않는다.

최신 검증(2026-09-16): 백지 Windows 11, uv 가 받아온 Python **3.12.14**, 6개 서버 번들에서
**14개 검사 전원 통과**, 6개 서버가 기본 포트 5001~5006 에서 `/health: healthy`.

## 진단표

| 증상 | 원인 | 대응 |
|---|---|---|
| `Windows Sandbox 가 이미 실행 중이다` | 샌드박스는 동시에 하나만 뜬다 | 기존 창을 닫고 재시도. 창은 닫혔는데 `vmmemWindowsSandbox` 가 남아 있으면 고아 VM 이다 — 관리자 PowerShell 에서 `Restart-Service CmService -Force` |
| `러너 스크립트에 파싱 오류가 있다` | `.ps1` 이 BOM 없이 저장돼 게스트 PowerShell 5.1 이 cp949 로 읽었다 | `sandbox_test.py` 가 복사할 때 BOM 을 강제하므로 보통 여기까지 오지 않는다. 뜬다면 진짜 문법 오류 — 메시지의 줄 번호를 본다 |
| `out/` 에 아무 파일도 안 생김 (5분 이상) | LogonCommand 가 안 돌았다 | `--no-shutdown` 으로 다시 띄워 게스트에서 러너를 손으로 실행해 본다 |
| `uv-install` 에서 멈춤/실패 | 게스트 네트워크 없음 / TLS | `.wsb` 의 `<Networking>Default</Networking>` 확인. 러너는 TLS 1.2 를 명시한다. `out/uv-install.log` 마지막 줄 |
| `uv sync --frozen 실패` | 잠금과 `pyproject.toml` 이 어긋났다 (또는 Python·휠 내려받기 실패) | `out/uv-sync.log`. 잠금 불일치면 **빌드 쪽 문제**다 — 원본에서 `uv lock` 으로 갱신하고 번들을 다시 만든다. 게스트에서 `--frozen` 을 떼는 식으로 넘기지 않는다 |
| `uv.lock 이 번들에 없다` | 빌드가 `uv.lock` 을 빠뜨렸다 | `build_bundle.py` 의 `COMMON_FILES` 에 `uv.lock`·`.python-version`·`requirements.txt` 가 있는지 확인 |
| `imports:<서버>` 실패 | 잘라낸 범위가 모자라다 | `out/verify.log` 의 `ModuleNotFoundError` 이름 → `build_bundle.py` 의 `COMMON_PACKAGES` 에 추가 |
| `http:<서버>` 만 실패 | 기동 중 예외 | 실패 항목 `detail` 에 서버 로그 꼬리가 붙는다 |
| 시간 초과인데 게스트는 진행 중 | 회선이 느림 | `--timeout` 을 늘린다. `out/progress.json` 이 갱신되고 있으면 살아 있는 것 |

## 산출물

`--keep` 을 주면(또는 실패하면) 작업 폴더가 남는다:

```
<work>/
├── bundle_test.wsb
├── in/                 ← 게스트에 읽기 전용으로 매핑됐던 것
└── out/
    ├── progress.json   ← 단계별 진행
    ├── done.json       ← 최종 판정 (호스트가 이걸 기다린다)
    ├── result.json     ← verify_bundle.py 의 검사 결과
    ├── runner.log      ← 게스트 트랜스크립트 전체
    ├── uv-install.log  ← uv 설치 스크립트 출력
    ├── uv-sync.log     ← `uv sync --frozen` 출력 (Python 조달 + 의존성)
    ├── pip-freeze.txt  ← `uv pip freeze` — 게스트에 실제로 깔린 버전
    └── verify.log
```

성공하면 `in/` 만 지우고 `out/` 은 남긴다 — 무엇이 어떤 버전으로 검증됐는지 기록이다.

## 함정

- **매핑 폴더는 게스트에서 UNC 처럼 동작한다.** 읽기 전용 매핑에 `__pycache__` 를 쓰려다
  실패할 수 있어 러너가 번들을 `C:\work` 로 복사한 뒤 돌린다.
- **호스트 경로에 한글이 있으면** 매핑이 실패한 사례가 있다. 작업 폴더는 ASCII 경로로 잡는다
  (기본값인 `%TEMP%` 아래는 안전하다).
- **`shutdown` 은 되돌릴 수 없다.** 게스트 디스크는 닫는 순간 사라진다. 남겨야 할 것은
  전부 `out/` 에 쓴 뒤 종료해야 한다.
- **사용자가 샌드박스 창을 직접 닫으면** `done.json` 없이 호스트가 시간 초과로 끝난다.
  검증 중이라고 미리 알릴 것.
- **러너 `.ps1` 은 UTF-8 BOM 이어야 한다.** 게스트의 Windows PowerShell 5.1 은 BOM 없는
  `.ps1` 을 ANSI(cp949)로 읽어 한글 주석에서 파싱이 깨지고, `LogonCommand` 는 아무 흔적도
  남기지 않고 죽는다. `sandbox_test.py` 가 복사 시 BOM 을 강제하고 호스트에서 파싱 선검사를
  한다 — 이 두 겹을 빼지 말 것.
- **반대로 러너가 `out/` 에 쓰는 JSON 에는 BOM 이 없어야 한다.** `Set-Content -Encoding utf8`
  은 PowerShell 5.1 에서 BOM 을 붙이고, 그러면 호스트의 `json.loads` 가 매번 깨져 "검사는 다
  통과했는데 호스트만 시간 초과"인 유령 실패가 된다. 러너는 `UTF8Encoding($false)` 로 직접
  쓰고 호스트는 `utf-8-sig` 로 읽는다 — 이 두 겹도 유지할 것.

Windows Sandbox 자체의 동작·제약(프로세스 이름, 고아 VM 정리, `.wsb` 스키마, 그리고 uv 이전의
게스트 Python 조달 이력)은
[references/windows_sandbox.md](../../../../references/windows_sandbox.md) 에 정리돼 있다.
