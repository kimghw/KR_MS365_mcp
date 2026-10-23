# 패키지·환경 관리 — uv 전환

의존성과 가상환경을 pip/venv 에서 [uv](https://docs.astral.sh/uv/) 로 옮긴 건. 프로젝트 본체,
두 스킬(`setup_ms365`·`export_ms365`), 샌드박스 검증까지 전부 포함한다.

---

## ① 질의·요청 히스토리

| 날짜 | 요청 요지 |
|---|---|
| 2026-09-16 | "uv 로 모두 변경해줘, 이 프로젝트 전부" |
| 2026-09-16 | (확인 질문 답변) 가상환경 디렉터리는 **`.venv`** 로 전환. MCP 등록 6개가 전부 HTTP URL 이라 Python 경로에 묶여 있지 않아 비용이 없음을 확인한 뒤 결정. |
| 2026-09-16 | (확인 질문 답변) `requirements.txt` 는 **`uv export` 산출물로 유지**. uv 없는 사람도 pip 으로 설치할 수 있게. |
| 2026-09-16 | (확인 질문 답변) 번들(`/export_ms365`)과 샌드박스 검증도 **uv 로 바꾸고 재검증**. |
| 2026-10-22 | (멀티유저 WP11) 인증 계층이 직접 쓰는 `cryptography`·`PyJWT[crypto]` 를 명시 의존성으로, Key Vault KEK 용 `keyvault` extra 추가, 관리 도구 `tools/` 패키지·`tools/tests`·`tests/multi_user` testpaths 등록. [spec_멀티유저.md](spec_멀티유저.md) ②-6.2·②-10·②-11.3 |

배경: 직전 작업([spec_번들내보내기.md](spec_번들내보내기.md))의 샌드박스 검증에서 **버전이
고정돼 있지 않아 새 PC 에서 서버가 전부 깨지는 것**이 드러났다. 그때는 `pip freeze` 로
번들만 막았는데, uv 전환으로 프로젝트 본체까지 같은 문제를 닫았다.

---

## ② 확정 사양

### 2-1. 무엇이 정본인가

| 대상 | 정본 | 성격 |
|---|---|---|
| 의존성 선언 | `pyproject.toml` | 손으로 쓴다 |
| 의존성 잠금 | **`uv.lock`** | `uv` 가 쓴다. **커밋한다** |
| Python 버전 | `.python-version` (`3.12`) | 손으로 쓴다. uv 가 이걸 보고 받아온다 |
| 환경 | `.venv/` | uv 가 만든다. 커밋 안 한다 |
| pip 호환 목록 | `requirements.txt` | **`uv export` 산출물.** 손으로 고치지 않는다 |

`requirements.txt` 재생성:

```bash
uv export --no-hashes --no-dev --no-emit-project -o requirements.txt
```

`--no-emit-project` 가 없으면 프로젝트 자신이 `.` 로 들어가 pip 사용자를 혼란스럽게 한다.

### 2-2. `--frozen` 을 기본으로 쓴다

`uv sync --frozen` / `uv run --frozen` — "잠금을 다시 풀지 말라".

셋업·검증·번들 어디서든 `--frozen` 이다. 잠금에 적힌 조합이 **실제로 기동까지 확인된 것**이고,
다시 풀면 그날의 최신본이 들어온다. 의존성을 **의도적으로** 바꿀 때만 `--frozen` 없이 간다:

```bash
uv add <패키지>                      # 추가 (pyproject + uv.lock 동시 갱신)
uv lock --upgrade-package <패키지>   # 특정 패키지만 올리기
uv lock                              # pyproject 를 손으로 고친 뒤 잠금 갱신
```

바꿨으면 `uv.lock` 과 `requirements.txt` 를 **함께 커밋**한다.

### 2-3. `mcp>=1.29,<2` 제약

mcp 2.x 는 `Server.list_tools` 를 없앴다. `handlers.py` 의 `build_mcp_server()` 가 그 데코레이터를
쓰므로 **기동 시점에 `AttributeError` 로 죽는다.** 2026-09-16 샌드박스 검증에서 6개 서버가
전부 깨져 드러났다(호스트에는 1.29.0 이 깔려 있어 보이지 않던 결함).

상한 없이 두면 `uv lock` 이 2.x 를 골라 **깨진 잠금**을 만든다. 그래서 상한은 필수다.
2.x 로 올리려면 SDK 이관이 먼저다 — 상한만 떼면 안 된다.

### 2-4. 개발 도구는 dependency-group 으로

`[project.optional-dependencies] dev` → **`[dependency-groups] dev`** (PEP 735).

`uv sync` 가 dev 그룹을 기본으로 깔아 주므로 따로 지정할 필요가 없고, 배포물(wheel)의 extra
목록이 개발 도구로 오염되지 않는다. `converters`·`agent` 는 런타임 선택 기능이라 extra 로 둔다.

| 무엇 | 어디 | 설치 |
|---|---|---|
| pytest, pytest-asyncio, ruff, black | `[dependency-groups] dev` | `uv sync --frozen` (기본) |
| 첨부파일 변환기 | `[project.optional-dependencies] converters` | `uv sync --frozen --extra converters` |
| OneNote 요약 | `[project.optional-dependencies] agent` | `uv sync --frozen --extra agent` |
| 멀티유저 KEK `azure_keyvault` (azure-identity, azure-keyvault-keys) | `[project.optional-dependencies] keyvault` | `uv sync --frozen --extra keyvault` |

**코드가 직접 import 하는 패키지는 전이 의존에 기대지 않고 명시한다.** `cryptography`(토큰
AES-256-GCM)·`PyJWT[crypto]`(ID token JWKS 검증)는 `mcp` 가 끌고 와서 이미 깔려 있었지만, mcp 가
의존을 바꾸면 조용히 사라진다 — 그래서 기본 의존성에 하한(`cryptography>=42`, `PyJWT[crypto]>=2.8`
— `PyJWKClient(timeout=)` 가 2.6+)과 함께 적었다(2026-10-22). Key Vault SDK 는 provider 를
고른 배포에서만 필요하므로 extra 다(`session/key_provider.py` 가 지연 import).

### 2-5. 환경 디렉터리는 `.venv`

uv 기본값이다. 전환 전 이름이던 `venv/` 는 레거시로, 스크립트가 있으면 인정하되 경고한다
(`verify_setup.py`). 새로 만들 때는 항상 `.venv`.

**바꿔도 안전했던 근거**: MCP 등록 6개가 전부 HTTP URL(`http://localhost:500x/mcp`)이라
Python 경로를 들고 있지 않고, Claude Desktop config 는 아예 없었다. Desktop(STDIO) 을
등록하면 **절대 경로가 config 에 박히므로**, 그 뒤로는 환경을 옮길 때 재등록이 필요하다.

### 2-6. 빌드 백엔드는 setuptools 를 유지한다

flat 레이아웃에 top-level 패키지가 10개, `py-modules = ["callback_server"]`, PEP 420 네임스페이스
패키지, `package-data` 까지 걸려 있다. 지금 설정이 동작하고 `uv sync` 도 이 위에서 잘 돈다.
`uv_build` 는 src 레이아웃·단일 패키지를 전제하므로 맞지 않는다. **백엔드는 건드리지 않는다.**

### 2-7. 번들·샌드박스도 uv 로

- 번들에 `uv.lock`·`.python-version`·`requirements.txt` 를 항상 싣는다.
- 빌드 시 `uv lock --check` 로 잠금과 pyproject 가 맞는지 확인하고, 어긋나면 **빌드를 실패**시킨다.
  어긋난 잠금을 보내면 받는 쪽의 `uv sync --frozen` 이 거부한다.
- 직전에 넣었던 "빌드 환경의 `pip freeze` 로 requirements 를 고정" 로직은 **삭제**했다.
  `uv.lock` 이 그 역할을 제대로 한다(전이 의존성까지).
- 샌드박스 러너: uv 설치 → `uv sync --frozen` → `uv run --frozen verify_bundle.py --http`.
  Python 조달 단계가 통째로 사라졌다 — `.python-version` 을 보고 uv 가 받아온다.

---

## ③ 구현 상태

| 항목 | 상태 | 내용 |
|---|---|---|
| `pyproject.toml` | 완료 | `mcp>=1.29,<2` 제약, `dev` → `[dependency-groups]`. 2026-10-22: `cryptography`·`PyJWT[crypto]` 명시, `keyvault` extra, `tools*` 패키지 포함(`tools.tests` 제외), testpaths 에 `mcp_todo/tests`·`tools/tests`·`tests/multi_user` |
| `.python-version` | 완료 | `3.12` |
| `uv.lock` | 완료 | 77 패키지 → 83 패키지(2026-10-22, `keyvault` extra 의 azure-core·azure-identity·azure-keyvault-keys·isodate·msal·msal-extensions 추가. 기존 잠금 버전은 그대로) |
| `requirements.txt` | 완료 | `uv export` 산출물로 교체 (전이 의존성 포함, `# via` 주석 포함) |
| `.gitignore` | 완료 | `.venv/` 추가, `uv.lock` 은 커밋 대상임을 명시 |
| `setup_ms365` | 완료 | SKILL.md(uv 절 신설·3-A 단계 교체), `verify_setup.py`(uv 검사 추가·`.venv` 경로·레거시 경고), `register_claude_desktop.py`(`.venv` 우선) |
| `export_ms365` | 완료 | `build_bundle.py`(uv.lock 동봉·`uv lock --check`·pip freeze 고정 삭제·README uv 화), `sandbox_runner.ps1`(uv 기반 재작성), `sandbox_test.py`(Python 옵션 제거·BOM 수정), `verify_bundle.py`(환경 디렉터리 제외) |
| `port_list.md` | 완료 | 8개 행의 실행 경로를 `.venv/Scripts/python.exe` 로 |
| 문서 | 완료 | 루트 `README.md` 설치 절 재작성, 스킬 references 5개 |

### 부수적으로 고친 것

| 무엇 | 왜 |
|---|---|
| `verify_setup.py` 의 `CORE_DEPS` 에서 `fastapi` 제거, `mcp`·`starlette` 추가 | fastapi 는 REST 서버 폐지(2026-08-12)로 의존이 사라졌는데 목록에 남아 "missing: fastapi" 를 계속 보고하고 있었다 |
| 샌드박스 `done.json`/`progress.json` 을 BOM 없이 쓰고, 호스트는 `utf-8-sig` 로 읽게 | PS 5.1 의 `Set-Content -Encoding utf8` 이 BOM 을 붙여 호스트의 `json.loads` 가 매번 실패했다. **검사는 14/14 통과했는데 호스트만 시간 초과로 끝나는 유령 실패**였다 |
| `verify_bundle.py` 의 비밀 검사에서 `.venv`·`node_modules`·`__pycache__` 등 제외 | 설치된 certifi 의 `cacert.pem`(공개 CA 번들)을 `*.pem` 규칙이 비밀로 잡았다 |

### 검증 기록

| 날짜 | 범위 | 결과 |
|---|---|---|
| 2026-09-16 | `uv lock` + `uv sync` | 77 패키지 해결, `.venv` 생성 (`mcp 1.30.0`, `starlette 1.6.0`, `uvicorn 0.53.0`) |
| 2026-09-16 | 호스트: 8개 서버 전체 import + `/health` (새 잠금 조합) | **전원 통과** — outlook 12 / calendar 7 / teams 14 / onedrive 9 / onenote 4 / todo 8 / time 1 / file_handler 7 |
| 2026-09-16 | 호스트: `uv run pytest -q` vs 기존 `venv` 비교 | **uv 전환이 새 실패를 만들지 않음.** 양쪽 모두 같은 기존 실패(onenote 2건 + outlook 오류 6건). uv 쪽은 converters 테스트 3건이 실패 대신 정상 skip 으로 바뀌어 오히려 나아짐 |
| 2026-09-16 | 번들 사본에서 `uv lock --check` + `uv sync --frozen` + `uv run verify_bundle.py --http` | 13/14 → 비밀 검사 오탐 수정 후 전원 통과 |
| 2026-09-16 | Windows Sandbox (uv 경로) | **14/14 통과.** 백지 Windows 11, Python **3.12.14**(uv 조달), 6개 서버 기본 포트 5001~5006 `/health: healthy` |
| 2026-09-16 | `uv run ruff check` 로 신규 스크립트 4개 정리 (UP006/UP045 등 100건 자동 수정) | 린트 통과 |
| 2026-09-16 | 린트 후 재검증 — 호스트 `uv sync --frozen` + `verify_bundle.py --http` | 14/14 통과 |
| 2026-09-16 | 린트 후 재검증 — Windows Sandbox 최종 | **14/14 통과, 전체 63초** (복사 24s → uv 설치 27s → `uv sync` 33s → 검증 42~63s). Python 3.12.14 |
| 2026-10-22 | `uv lock` (네트워크 — `--offline` 은 azure 패키지가 캐시에 없어 실패) + `uv lock --check` + `uv export` | 83 패키지. `requirements.txt` 는 `# via` 주석만 바뀜(cryptography·pyjwt 에 `kr-ms365-mcp` 추가) — 기본 설치 조합 불변 |

### 속도

샌드박스 실측(6개 서버 번들, 2회): 부팅·로그온 ~21~24초 → uv 설치 ~6초 → `uv sync --frozen`
**~9초** → 검증(서버 6개 기동·`/health`) ~21초. **전체 63초.** pip 경로는 4~8분이었다.

---

## ④ 미결·후속

- **`.python-version` 은 `3.12`(마이너)로 뒀다.** 패치까지 고정하면(`3.12.10`) 재현성은 더
  높지만 보안 패치를 놓친다. 그래서 호스트는 3.12.10, 샌드박스는 3.12.14 로 서로 다르다 —
  의도된 것이다. 패치 고정이 필요해지면 `.python-version` 만 바꾸면 된다.
- **mcp 2.x 이관**은 별건이다. `Server.list_tools` 를 쓰는 `build_mcp_server()` 를 새 SDK API 로
  옮겨야 한다. 상한(`<2`)만 떼면 기동이 깨진다.
- **기존 `venv/` 디렉터리**는 지우지 않았다. 지금 도는 MCP 서버 6개가 그 안의 Python 으로
  기동돼 있어서다. 서버를 재시작(`/setup_ms365 restart all`)한 뒤 지우면 된다.
- **Claude Desktop(STDIO) 등록**은 현재 없다. 등록하면 `.venv` 절대 경로가 config 에 박히므로,
  그 뒤로 환경을 옮길 때는 재등록이 필요하다.
- ~~**`README.md` 의 모듈 구성 표에 있는 `mcp_editor/` 행**~~ — **해소(2026-10-22).** 멀티유저
  문서 갱신 때 README 의 틀린 내용을 고치면서 지웠다(모듈은 2026-08-12 폐지, 디렉터리 없음).
- **`keyvault` extra 는 잠금에만 있고 기본 `.venv` 에는 깔리지 않는다.** `azure_keyvault` KEK 를
  쓰는 배포만 `uv sync --frozen --extra keyvault` 를 한다. 실제 Key Vault 로 wrap/unwrap 한 검증은
  아직 없다(테스트는 memory/env provider).

---

## 관련 문서

- [spec_번들내보내기.md](spec_번들내보내기.md) — 번들 구성·샌드박스 검증 절차. 버전 미고정 결함이 처음 드러난 곳
- [spec_도구정의.md](spec_도구정의.md) — `spec/param_spec/*.yaml` 이 도구 계약의 유일한 원본
- `references/windows_sandbox.md` — Windows Sandbox 동작·제약(외부 시스템 지식)
