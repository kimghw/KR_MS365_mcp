# 번들 내보내기 — MS365 MCP 서버 배포 패키징

선택한 도메인 서버를 **독립 실행 가능한 번들**로 잘라내 zip 또는 새 GitHub 저장소로
내보내는 기능. 구현체는 `/export_ms365` 스킬이다.

---

## ① 질의·요청 히스토리

| 날짜 | 요청 요지 |
|---|---|
| 2026-09-16 | "스킬 하나 만들자. 1개 이상의 캘린더·onedrive·onenote·outlook·teams·todo 를 별도 압축파일이나 GitHub 저장소 생성 후 저장하는 기능. 여기에는 인증, 설치 스킬 관련 내용이나 time 등 공용으로 사용되는 내용도 포함되어야 한다. 그리고 Windows Sandbox 에서 테스트해 달라." |
| 2026-09-16 | (확인 질문 답변) 번들 단위는 **하나의 통합 번들** — 선택한 서버 전부 + 공용 코드를 한 묶음으로. 서버별 개별 번들은 만들지 않는다. |
| 2026-09-16 | (확인 질문 답변) 샌드박스 테스트는 **전체 검증** — 백지 Windows 에 Python 을 설치하고 pip install 까지 한 뒤 서버 기동·도구 목록을 확인한다. 구조 검사만으로 끝내지 않는다. |
| 2026-10-22 | (멀티유저 WP11) 저장소 안의 멀티유저 데이터 루트·키 파일·감사 로그·이전 산출물을 번들에서 빼고, 비밀 스캔이 bearer key(`m365v1.<kid>.<secret>`)와 `MS365_KEK_B64` 값도 잡게 한다. [spec_멀티유저.md](spec_멀티유저.md) ②-7.2·②-11.3 |

---

## ② 확정 사양

### 2-1. 번들의 정의

번들은 **원본 프로젝트의 부분집합이며, 상대 경로 구조가 원본과 동일하다.** 새 레이아웃을
만들지 않는다. 원본 코드가 루트 기준으로 경로를 해석하기 때문이다:

| 코드 | 루트 기준으로 찾는 것 |
|---|---|
| `mcp_common/bootstrap.py` | `<서버파일>/../../..` 을 프로젝트 루트로 보고 `sys.path` 에 삽입 |
| `mcp_common/param_spec.py` | `spec/param_spec/<도메인>.yaml` |
| `mcp_common/paths.py` | 허용 루트 기본값 |
| `session/auth_manager.py` | `database/auth.db`, 루트 모듈 `callback_server` |

경로를 재배치하면 이 넷을 전부 고쳐야 하고 원본과 번들이 다른 코드가 된다. 그래서
**부분집합 + 동일 경로**가 확정 사양이다.

### 2-2. 선택 항목과 자동 포함 항목

사용자는 도메인 서버만 고른다(1개 이상). 나머지는 자동으로 따라간다.

| 구분 | 내용 | 선택 여부 |
|---|---|---|
| 도메인 서버 | `mcp_outlook` `mcp_calendar` `mcp_teams` `mcp_onedrive` `mcp_onenote` `mcp_todo` `mcp_file_handler` | 사용자 선택 |
| 인증 | `session/`, `callback_server.py` | 항상 |
| 공용 런타임 | `mcp_common/`, `core/` | 항상 |
| 공용 time 서버 | `mcp_time/` + `spec/param_spec/time.yaml` | 항상 |
| 설치·운영 스킬 | `.claude/skills/setup_ms365/` | 항상 |
| 도구 계약 | `spec/param_spec/<선택서버>.yaml` | 선택분 |
| 루트 파일 | `requirements.txt` `.env.example` `.gitignore` | 항상 |

`all` 은 도메인 서버 6개를 뜻하며 `file_handler` 는 포함하지 않는다(로컬 파일 접근 도구라
받는 쪽 환경 전제가 다르다 — 필요하면 이름을 명시한다).

**근거**: 도메인 서버끼리는 서로를 import 하지 않는다(2026-09-16 실측). 공용 4개 +
`callback_server.py` 만 따라가면 어떤 조합으로 잘라도 성립한다. 새 도메인이 다른 도메인을
import 하기 시작하면 이 전제가 깨지므로 `build_bundle.py` 에 의존 서버 동반 규칙을 추가해야
한다.

### 2-3. 생성물

| 파일 | 생성 방식 |
|---|---|
| `pyproject.toml` | **원본을 고쳐 쓴다.** `packages.find` 의 `include` 와 `testpaths` 배열만 번들 범위로 교체하고 의존성·ruff·black 설정은 원본 그대로 둔다. 새로 쓰면 의존성이 두 벌이 되어 드리프트한다. 교체 표식을 못 찾으면 **빌드 실패**. |
| `README.md` | 서버 표(이름·기능·포트·진입점) + 빠른 시작 + 인증 설명. 포트는 `spec/param_spec/<도메인>.yaml` 의 `server.port` 에서 읽는다 — 스크립트에 적지 않는다. |
| `bundle_manifest.json` | 서버 목록·공용 구성·원본 커밋·`tree_sha256`. `verify_bundle.py` 가 이걸 읽어 검사 대상을 정한다. |
| `verify_bundle.py` | 스킬 `assets/` 의 것을 복사. 번들 안에서도 샌드박스에서도 **같은 파일**이 돈다. |
| `MANIFEST.in` | sdist 에 `spec/param_spec/*.yaml` 동봉 |
| `database/.gitkeep` | `auth.db` 가 생길 자리. 원본 `.gitignore` 의 `database/*` 에 막히므로 `!database/.gitkeep` 예외를 덧붙인다 |
| `requirements.txt` | **원본을 그대로 복사하지 않는다.** 버전 제약이 없는 줄을 빌드 환경에 깔린 버전으로 고정한다 — 아래 2-3-1 |

### 2-3-1. 의존성 잠금 (필수)

> **2026-09-16 갱신** — 아래 문제는 `pip freeze` 로 requirements 를 고정해 막고 있었으나,
> 프로젝트가 uv 로 전환되면서 **`uv.lock` 을 동봉하는 방식으로 대체**됐다. 고정 로직은
> 삭제했다. 현행 사양은 [spec_패키지관리.md](spec_패키지관리.md) ②-7 이다.
>
> 지금 번들이 싣는 것: `uv.lock`(전이 의존성까지 잠금), `.python-version`(uv 가 받아올 Python),
> `requirements.txt`(uv export 산출물, pip 사용자용 안전망). 빌드 시 `uv lock --check` 로
> 잠금과 pyproject 가 맞는지 확인하고 어긋나면 빌드를 실패시킨다.

문제의 원본 기록은 남겨 둔다 — 왜 잠금이 필요한지가 여기 있다.

원본 `requirements.txt` 는 `mcp` 처럼 버전을 적지 않았다. 빌드하는 PC 에는 이미 되는 버전이
깔려 있어 아무 문제가 없지만, 번들을 받은 쪽은 **그날의 최신본**을 받는다.

실제로 그렇게 깨졌다(2026-09-16 샌드박스 2차 검증):

| | 호스트(되는 환경) | 샌드박스(새 설치) |
|---|---|---|
| `mcp` | 1.29.0 | **2.2.0** |
| 결과 | 6개 서버 정상 | `AttributeError: 'Server' object has no attribute 'list_tools'` — **6개 전부 기동 실패** |

`import` 와 스키마 검사는 통과했고 **실제 기동(`/health`)에서만** 드러났다. 호스트에서만
돌렸다면 못 잡았을 결함이다.

확정 사양: 번들은 배포물이므로 **검증한 조합을 그대로 싣는다.** `build_bundle.py` 의
`pin_requirements()` 가 빌드 환경의 `pip freeze` 로 버전 없는 줄을 `==` 로 고정하고, 이미
제약이 있는 줄(`pydantic>=2`)은 존중한다. 고정하지 못한 항목은 매니페스트의
`requirements.unpinned` 에 남는다.

**원본 `requirements.txt` 는 이 스킬이 고치지 않는다** — 원본도 같은 문제를 안고 있으나
(새 PC 에서 `pip install -r requirements.txt` 하면 깨진다) 그건 이 사양의 범위 밖이다. ④ 참조.

### 2-4. 비밀 차단 (2겹)

1. **실값 대조** — 로컬 `.env` 의 12자 이상 값들을 번들 텍스트 파일 전체에서 찾는다.
   위반 보고에는 **키 이름과 파일 경로만** 남기고 값은 출력하지 않는다.
2. **모양 대조** — `AZURE_CLIENT_SECRET=<8자+>`, 30자 이상 UUID 형태 CLIENT_ID,
   40자 이상 `refresh_token`/`access_token` 리터럴, 멀티유저 bearer key 실값
   (`m365v1.<32 hex>.<43 base64url>`), `MS365_KEK_B64=<40자+>`. `your_`·`_here`·`example`·`<`·`${`
   같은 자리표시자 힌트가 있거나 hex 자리 3/4 이상이 0 인 테스트용 GUID 면 통과(`.env.example`·
   `mcp_common/testing.py` 가 여기 해당). bearer key 는 형식이 고정이라 자리표시자 예외가 없다.

걸리면 **번들을 지우고 실패**시킨다. 반쯤 만들어진 번들이 남아 실수로 배포되는 것을 막는다.

제외 대상: `.env` `database/*.db` `venv/` `__pycache__/` `*.log` `.git/` `output/`
`downloads/` `*.pem` `*.pfx` `*.p12` `*.key` `*.kek`. 단 `.env` 는 **정확한 이름으로만** 막는다 —
`.env.example` 은 들어가야 하는 파일이다.

멀티유저 산출물(2026-10-22): 이름 규칙 `wrapped_dek.json` `*.jsonl`(감사 로그)
`migration_mapping*.json` `mail_metadata.json` `metadata.json` + 구조 규칙 — `system/deployment.json`
이 있는 디렉터리의 `system/` 과 형제 `users/` 를 통째로 뺀다(데이터 루트를 패키지 안에 둔 경우).
`verify_bundle.py` 의 secrets 검사도 같은 파일 이름과 bearer key 리터럴을 받는 쪽에서 다시 본다.

### 2-5. 배포

| 모드 | 동작 |
|---|---|
| `zip` | `<번들 상위>/<이름>.zip`. 아카이브 루트는 번들 이름 디렉터리. |
| `github` | `gh repo create <이름> --private --source=. --push`. 같은 이름이 이미 있으면 **덮어쓰지 않고 멈춘다.** |
| `both` | 둘 다 |

**public 저장소는 `--confirm-public` 없이 만들지 않는다.** 인증 코드와 사내 도구 계약이
들어 있어 실수로 공개되면 되돌릴 수 없다. 스킬은 사용자에게 먼저 확인받는다.

### 2-6. Windows Sandbox 검증 (기본 동작)

`--no-sandbox` 를 주지 않는 한 배포 전에 항상 돈다. 호스트에는 venv·설치된 패키지·`.env`·
`auth.db` 가 있어 번들이 무엇에 몰래 기대도 통과한다. 샌드박스는 백지라 그게 통하지 않는다.

| 위치 | 하는 일 |
|---|---|
| 호스트 `sandbox_test.py` | `in/<번들>`(읽기전용) + `out/`(쓰기) 준비 → 러너 파싱 검사 → `.wsb` 생성 → **분리 기동** → `out/done.json` 대기 |
| 게스트 `sandbox_runner.ps1` | 번들을 `C:\work` 로 복사 → **uv 설치** → **`uv sync --frozen`** → `uv run --frozen verify_bundle.py --http` → 결과를 `out/` 에 쓰고 자동 종료 |

Python 을 따로 챙기지 않는다 — 번들의 `.python-version` 을 보고 uv 가 받아온다. 전에는
`--python-method embed|installer` 로 골랐고 설치본은 15분 무응답으로 멎은 적이 있는데(②-7),
uv 로 오면서 그 단계 자체가 사라졌다. 규약은 [spec_패키지관리.md](spec_패키지관리.md) ②-7.

샌드박스는 **분리해서 띄운다.** 그러지 않으면 호스트 스크립트가 시간 초과로 끝날 때 게스트가
같이 끌려 내려가 증거가 사라진다(실제로 한 번 날렸다).

검사 항목: `structure` / `secrets` / `imports:<서버>` / `schema:<서버>` / `http:<서버>`
(`server_stream.py` 를 실제로 띄워 `/health` 200 + `tool_count` 확인). 포트가 쓰이고 있으면
임의의 빈 포트로 붙으므로 호스트에서 서버를 띄워 둔 채 돌려도 충돌하지 않는다.

**검증 실패한 번들은 배포하지 않는다.**

### 2-7. 러너 스크립트 인코딩·Python 조달 (실패에서 배운 것)

#### Python 조달 — 폐기됨(2026-09-16, uv 전환)

> 아래는 uv 전환 **전**의 사양이다. 지금 러너는 `uv sync --frozen` 한 줄로 끝내고 Python 을
> 직접 챙기지 않는다([spec_패키지관리.md](spec_패키지관리.md) ②-7). 남겨 두는 이유는
> "왜 이 길로 가지 않는가"의 근거이기 때문이다.

공식 설치본(`python-3.12.10-amd64.exe /quiet`)이 게스트에서 **15분 무응답**으로 멎었다
(2026-09-16). 다운로드는 정상이었고 그 다음에서 멈췄다. 그래서 당시엔 이렇게 했다:

- 기본값은 **임베디드 배포판**(`-PyMethod embed`) — 압축 해제뿐이라 멎을 구석이 없다.
  `._pth` 를 `python312.zip / . / Lib\site-packages / import site` 4줄로 다시 쓰고
  `get-pip.py` 로 pip 을 넣는다. 이 4줄을 빼면 pip 은 되는데 import 가 안 된다.
- `installer` 는 선택이며 `WaitForExit(300s)` 상한을 건다. `-Wait` 는 멎으면 영원히 기다린다.

uv 는 이 둘을 모두 없앴다 — 설치 프로그램도, `._pth` 손질도, `get-pip.py` 도 필요 없다.

#### 인코딩

게스트의 Windows PowerShell 5.1 은 **BOM 없는 `.ps1` 을 ANSI 코드페이지(한국어 Windows 는
cp949)로 읽는다.** 한글 주석 한 줄이면 파싱 오류가 나고 `LogonCommand` 는 조용히 죽어
`out/` 에 아무것도 남기지 않는다 — 시간 초과가 날 때까지 원인을 알 수 없다.

확정 사양:

- `assets/sandbox_runner.ps1` 은 **UTF-8 BOM** 으로 저장한다.
- `sandbox_test.py` 가 게스트로 복사할 때 `utf-8-sig` 로 다시 써서 BOM 을 **강제**한다
  (누가 BOM 없이 저장해도 자동 교정).
- 복사 직후 호스트 PowerShell 로 **파싱 검사**를 돌려 1초 만에 잡는다.
- PowerShell 자동 변수(`$args` 등)를 스크립트 변수로 쓰지 않는다.

---

## ③ 구현 상태

| 항목 | 상태 | 위치 |
|---|---|---|
| 스킬 정의 | 완료 | `.claude/skills/export_ms365/SKILL.md` |
| 번들 스테이징 + 생성물 + 비밀 스캔 | 완료 | `.claude/skills/export_ms365/scripts/build_bundle.py` |
| zip / GitHub 배포 | 완료 | `.claude/skills/export_ms365/scripts/publish_bundle.py` |
| 샌드박스 검증 (호스트) | 완료 | `.claude/skills/export_ms365/scripts/sandbox_test.py` |
| 샌드박스 러너 (게스트) | 완료 | `.claude/skills/export_ms365/assets/sandbox_runner.ps1` |
| 번들 자체 점검 | 완료 | `.claude/skills/export_ms365/assets/verify_bundle.py` |
| 참조 문서 | 완료 | `references/bundle_layout.md`, `references/sandbox_testing.md` |
| 외부 시스템 지식 | 완료 | `references/windows_sandbox.md` (프로젝트 지식저장소 — 이번에 신설) |

### 검증 기록

| 날짜 | 범위 | 결과 |
|---|---|---|
| 2026-09-16 | 호스트: `--servers calendar,todo` 빌드 + `verify_bundle.py --http` | 6 검사 전부 통과 (calendar 7 도구, todo 8 도구) |
| 2026-09-16 | 호스트: `--servers all` 빌드(150파일, 0.36MB zip) + import·스키마 검증 | 8 검사 전부 통과 (도구 합계 54개) |
| 2026-09-16 | 호스트: 엣지 케이스 — 서버 1개(`todo`, 66파일) / 7개 전부(`all,file_handler`, 187파일) | 통과. 도구 합계 61개. 생성 `pyproject.toml` TOML 파싱 검증 |
| 2026-09-16 | 호스트: 비밀 스캐너 음성 테스트 4종 | `.env` 잔존 / 실값 리터럴 / JSON 속 `refresh_token` / 로컬 `.env` 값 유출 모두 검출. `.env.example` 자리표시자 오탐 없음. **JSON 형태 `"refresh_token": "…"` 를 놓치는 버그를 이 테스트로 잡아 수정** |
| 2026-09-16 | 호스트: 배포 가드 | `--repo` 누락 / `public` 인데 `--confirm-public` 없음 / 번들 아닌 경로 — 전부 차단. zip 정상 |
| 2026-09-16 | Windows Sandbox 1차 | **실패** — 러너 `.ps1` 에 BOM 이 없어 게스트 PowerShell 5.1 파싱 오류. `out/` 에 아무 흔적 없음. ②-7 로 확정 |
| 2026-09-16 | Windows Sandbox 2차 (BOM 교정 후, `installer` 모드) | **시간 초과** — 공식 Python 설치본이 15분 무응답. `embed` 를 기본으로 전환 + 대기 상한 도입 |
| 2026-09-16 | Windows Sandbox 3차 (`embed` 모드) | **실패했고, 그게 성과다** — structure/secrets/imports 8개는 통과했으나 `http:*` 6개 전부 `AttributeError: 'Server' object has no attribute 'list_tools'`. 원인은 `mcp` 미고정(호스트 1.29.0 / 샌드박스 2.2.0). ②-3-1 로 확정 |
| 2026-09-16 | Windows Sandbox 4차 (requirements 고정 후) | **14/14 통과** — 백지 Windows 11, Python 3.12.10(embed), `mcp==1.29.0`. 6개 서버 전부 기본 포트(5001~5006)에서 `/health` `healthy`, 도구 합계 54개 |
| 2026-10-22 | 호스트: `--servers all,file_handler` 빌드(275파일) + `verify_bundle.py`(import·스키마) | 9/9 통과. 처음엔 `mcp_common/testing.py` 의 테스트 앱 ID(`00000000-…-c11e`)가 CLIENT_ID 모양 검사에 걸려 번들이 폐기됐다 — 0 GUID 예외로 해소. 비밀 스캐너 음성 테스트(bearer key 실값·`MS365_KEK_B64` 값·데이터 루트 트리) 모두 검출, `m365v1.<kid>.<secret>` 표기·빈 `MS365_KEK_B64=` 은 통과 |

---

## ④ 미결·후속

- ~~**원본 `requirements.txt` / `pyproject.toml` 의 `mcp` 미고정**~~ — **해결됨(2026-09-16).**
  uv 전환으로 `pyproject.toml` 에 `mcp>=1.29,<2` 제약이 들어갔고 `uv.lock` 이 전이 의존성까지
  잠근다. [spec_패키지관리.md](spec_패키지관리.md) ②-3.
- ~~**`requirements.txt` 헤더의 `pip install -e ".[editor]"` 안내**~~ — **해소됨(2026-09-16).**
  `requirements.txt` 가 `uv export` 산출물로 바뀌면서 그 헤더 자체가 사라졌다. 루트
  `README.md` 의 `mcp_editor/` 행도 2026-10-22 에 지웠다.
- **선택 의존성(`converters`) 미검증** — python-docx·pdfplumber·pyhwpx 등은 기본 설치에
  들어가지 않고 함수 안에서 지연 import 된다. 기동·스키마 검증에는 영향이 없지만
  첨부 변환을 실제로 쓰려면 받는 쪽이 `uv sync --frozen --extra converters` 를 해야 한다.
  번들 README 에 적어 두었고, 검증 범위에 넣을지는 미정.
- **Azure 실호출은 검증하지 않는다** — 번들 검증은 인증 없이 도는 범위까지다. 실제 메일
  조회가 되는지는 받는 쪽이 자기 자격증명으로 확인해야 한다.
- **도메인 간 의존이 생기면** `build_bundle.py` 의 `SERVERS` 에 의존 서버 동반 규칙이
  필요하다(현재는 서로 독립이라는 실측 전제 위에 서 있다).
- **`file_handler` 의 위치** — `all` 에서 빼 두었다. 받는 쪽 파일 접근 허용 경로
  (`MCP_ALLOWED_PATHS`) 전제가 달라서인데, 기본 포함으로 바꿀지는 사용 후 판단.

---

## 관련 문서

- [spec_도구정의.md](spec_도구정의.md) — `spec/param_spec/*.yaml` 이 도구 계약의 유일한 원본인 이유
- [spec_MCP트랜스포트.md](spec_MCP트랜스포트.md) — `handlers.py` / `server_stdio.py` / `server_stream.py` 3파일 구조
- `.claude/skills/export_ms365/references/bundle_layout.md` — 의존 그래프 실측·제외 규칙 상세
- `.claude/skills/export_ms365/references/sandbox_testing.md` — 샌드박스 절차·진단표
