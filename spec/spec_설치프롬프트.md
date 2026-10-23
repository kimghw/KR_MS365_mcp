# 설치 프롬프트 — 새 PC 의 Claude Code 에 붙여 넣는 설치 절차

새 PC 에서 이 저장소를 클론해 6개 MS365 MCP 서버를 쓰게 만드는 **프롬프트 한 장**의 사양.
원본 파일은 저장소가 아니라 OneDrive `shared/KR_M365_MCP/설치_프롬프트.md` 에 있다(`.env` 와 같은
폴더에 두어 함께 내려받게 하기 위해서다). 번들(zip/GitHub 신규 저장소)로 떼어 주는 경로는
[spec_번들내보내기.md](spec_번들내보내기.md), uv·잠금 규약은 [spec_패키지관리.md](spec_패키지관리.md).

## ① 질의·요청 히스토리

| 날짜 | 요청 요지 |
|---|---|
| 2026-10-20 | OneDrive 의 `설치_프롬프트.md` 를 "윈도우 샌드박스에서 설치하고 테스트해 보고, 보완사항 있으면 프롬프트를 개선해 달라". |

## ② 확정 사양

### 2-1. 프롬프트가 보장해야 하는 것

| 항목 | 내용 |
|---|---|
| 전제 | Windows 11 + Claude Code. Git 은 Claude Code(Windows)가 Git for Windows 를 요구하므로 전제에 포함된다. Python 은 불필요(`uv sync --frozen` 이 `.python-version` 의 3.12 를 받아온다). |
| 입력 | 공개 저장소 URL + 별도로 전달되는 `.env`(Azure 자격증명 5키). `.env` 는 프롬프트 파일과 같은 OneDrive 폴더에서 내려받는다. |
| 순서 | 클론 → `.env` 배치 → uv 설치 → `uv sync --frozen` → MCP 등록 → (Code 등록 시) HTTP 서버 기동 → 인증 → `verify_setup.py`. |
| 셸 | Claude Code 의 Bash 도구(Git Bash) 기준으로 쓰되 PowerShell 등가를 괄호로 병기. **경로는 슬래시(/)** — Bash 에서 `E:\dev` 는 역슬래시 이스케이프로 `E:dev` 가 된다. |
| 스킬 가용성 | 프롬프트를 실행하는 세션은 저장소 밖에서 열려 있으므로 프로젝트 스킬 `/setup_ms365` 가 **보이지 않는다**. 등록은 스크립트(또는 `claude mcp add`)로 직접 하고, 끝난 뒤 프로젝트 루트에서 Claude Code 를 다시 열게 안내한다. |
| uv PATH | `irm … \| iex` 직후의 같은 세션에는 PATH 가 반영되지 않는다. 이후 호출은 `~/.local/bin/uv.exe` 전체 경로. `verify_setup.py` 도 같은 위치를 폴백으로 본다(③). |
| 서버 준비 시간 | `server_stream.py` 기동 후 `/health` 200 까지 **약 3초**(실측). 프롬프트는 5초 대기 후 확인, 실패 시 5초 뒤 1회 재확인. |
| 비밀 | `.env` 내용·`auth.db` 를 채팅·메모리에 남기지 않는다. 키 존재 여부만 확인. |
| 운영 주의 | 등록 후 Claude Code 새 세션 필요 / HTTP 서버는 로그아웃·재부팅 시 죽음(`/setup_ms365 start all`) / 포트 5000 의 Hyper-V·WinNAT 예약 범위 충돌(`netsh int ipv4 show excludedportrange protocol=tcp`). |

### 2-2. 검증 방법 (Windows Sandbox 재현)

프롬프트의 1~8단계(7단계 인증 제외)를 백지 Windows 에서 러너 스크립트로 그대로 수행한다. Git 은 포터블
MinGit 을 받아 충족하고, 등록은 `~/.claude.json`·`claude_desktop_config.json` 생성을 확인하며,
서버는 6개를 띄워 `/health` 가 200 이 되는 시각을 서버별로 잰다. 러너·호스트 스크립트는 세션
스크래치에 두며(저장소에 넣지 않음) `.wsb` 생성·BOM·대기 로직은
`.claude/skills/export_ms365/scripts/sandbox_test.py` 를 import 해 재사용한다.

## ③ 구현 상태

### 검증 기록 (2026-10-20, Windows 11 Pro 26200 샌드박스, uv 0.13.3, Python 3.12.15, mcp 1.30.0)

| 단계 | 결과 | 소요 |
|---|---|---|
| `git clone`(public, HEAD f6c7121) | OK | 1.5s |
| `.env` 5키·리다이렉트 URI 확인 | OK | — |
| uv 설치(`irm \| iex`) | OK, 같은 세션 PATH 미반영 확인 | 5.9s |
| `uv sync --frozen`(Python 3.12 내려받기 포함) | OK | 6.1s |
| `register_claude_code.py` / `register_claude_desktop.py --servers all` | 6개 등록, 두 config 생성 | 0.3s |
| 6개 `server_stream.py` 기동 → `/health` | 전부 healthy(툴 12/7/15/9/4/8). Uvicorn ready 는 기동 후 약 3초 | 10.6s(헬스체크 포함) |
| `streamable_http_probe.py`(outlook) | 8-probe 전원 PASS | 16.6s |
| `check_token.py` | `no_user`(인증 전 정상), `database/auth.db` 자동 생성 | 0.4s |
| `verify_setup.py` | 등록·포트·.env·deps 전부 OK. `uv` 만 "미설치" 오탐(PATH) → 폴백 추가로 해소 | 57.8s |
| `uv sync --frozen --extra converters` | 20개 설치(pyhwp 는 소스 빌드, 컴파일러 불필요) | ~5s |
| converters import 확인 | (진단 중 — ④ 참조) | — |

### 반영한 변경

- `.claude/skills/setup_ms365/scripts/verify_setup.py` — `check_uv()` 가 `~/.local/bin/uv.exe` 를 폴백으로 본다.
- `.claude/skills/export_ms365/scripts/sandbox_test.py` — `_preflight()` 가 `WindowsSandboxRemoteSession` 도 실행 중 판정에 포함(이 빌드에서 `vmmemWindowsSandbox` 가 안 보임, [references/windows_sandbox.md](../references/windows_sandbox.md)).
- OneDrive `설치_프롬프트.md` 를 ②에 맞춰 개정.

## ④ 미결·후속

- OneDrive `shared/KR_M365_MCP` 에 **`.env` 가 없다**(2026-10-20 목록 기준 `설치_프롬프트.md` 뿐). 올려야 프롬프트 머리말이 성립한다.
- converters extra 설치 직후 `uv run --frozen python -c "import docx, pptx, …"` 가 1차 샌드박스에서 응답 없이 멈췄다. 실행기(uv run/.venv python)×모듈별로 가른 진단을 진행 중.
- 위 두 스크립트 변경은 커밋·푸시돼야 새 PC 에 반영된다.
- 설치 프롬프트는 **단일 운영자 모드** 기준이다. 2026-10-22 부터 `verify_setup.py`·`check_token.py` 는
  `MS365_MULTI_USER=1` 을 감지하면 공용 `auth.db` 를 읽지 않고 registry·KEK·gateway 를 본다(사용자 수만,
  이메일 미표시). 멀티유저 서버를 새 PC 에 세우는 절차(admin CLI·gateway·bearer 등록)를 프롬프트에 넣을지는
  미정 — 절차 원본은 `.claude/skills/setup_ms365/SKILL.md` "멀티유저 모드 운영", [spec_멀티유저.md](spec_멀티유저.md).
