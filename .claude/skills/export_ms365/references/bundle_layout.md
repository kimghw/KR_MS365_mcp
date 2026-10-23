# 번들 레이아웃 — 무엇이 왜 들어가는가

## 결론부터

번들은 **원본 프로젝트의 부분집합이고, 상대 경로는 원본과 같다.** 새 레이아웃을 발명하지
않는다. 원본 코드가 경로를 루트 기준으로 해석하기 때문이다:

| 코드 | 무엇을 루트 기준으로 찾는가 |
|---|---|
| `mcp_common/bootstrap.py` | `<서버파일>/../../..` 을 프로젝트 루트로 보고 `sys.path` 에 넣는다 |
| `mcp_common/param_spec.py` | `spec/param_spec/<도메인>.yaml` (`MCP_PARAM_SPEC_DIR` 로만 덮어쓸 수 있다) |
| `mcp_common/paths.py` | 허용 루트의 기본값이 프로젝트 루트 |
| `session/auth_manager.py` | `database/auth.db`, 그리고 `callback_server.py` 를 루트 모듈로 import |

경로를 재배치하면 이 넷을 전부 고쳐야 하고, 그러면 원본과 번들이 서로 다른 코드가 된다.
**부분집합 + 동일 경로**가 유일하게 "고칠 것이 없는" 선택이다.

## 의존 그래프 (2026-09-16 기준 실측)

```
mcp_<도메인>/  →  core, mcp_common, (자기 자신)
mcp_common/    →  session
mcp_time/      →  mcp_common
mcp_file_handler/ → mcp_common, session
session/       →  callback_server (루트 단일 모듈)
```

도메인 서버끼리는 서로를 import 하지 않는다. 그래서 **어떤 조합으로 잘라도 성립한다** —
공용 4개(`mcp_common` `core` `session` `mcp_time`) + `callback_server.py` 만 같이 가면 된다.

확인 방법(원본 루트에서):

```bash
for d in mcp_outlook mcp_calendar mcp_teams mcp_onedrive mcp_onenote mcp_todo; do
  echo "=== $d ==="
  grep -rhoE "^\s*(from|import)\s+(mcp_[a-z_]+|session|core|callback_server)[a-zA-Z0-9_.]*" \
    $d --include="*.py" | sed -E 's/^\s*(from|import)\s+//' | cut -d. -f1 | sort -u
done
```

새 도메인이 다른 도메인을 import 하기 시작하면 이 전제가 깨진다. 그때는
`build_bundle.py` 의 `SERVERS` 에 의존 서버를 함께 끌어오는 규칙을 추가해야 한다.

## 항상 들어가는 것과 그 이유

| 구성 | 없으면 생기는 일 |
|---|---|
| `session/`, `callback_server.py` | 첫 도구 호출에서 OAuth 를 못 연다. 토큰 갱신·저장도 없다. |
| `mcp_common/` | 도구 스키마가 파생되지 않아 서버가 기동 자체를 못 한다. |
| `core/` | 서비스 프로토콜 import 실패. |
| `mcp_time/` + `time.yaml` | 에이전트가 "오늘/이번 주" 같은 표현을 날짜로 바꿀 수단을 잃는다. 일정·메일 도구가 상대 날짜를 자주 쓰므로 **공용으로 취급한다**. |
| `spec/param_spec/<도메인>.yaml` | `load_param_spec()` 이 실패해 서버가 뜨지 않는다. 문서가 아니라 **런타임 입력**이다. |
| `.claude/skills/setup_ms365/` | 받은 쪽이 환경(`uv sync --frozen`)·`.env`·MCP 등록을 손으로 해야 한다. |
| `.env.example` | 어떤 환경변수를 채워야 하는지 알 길이 없다. |
| `uv.lock` | 받은 쪽이 **그날의 최신본**을 받는다. 2026-09-16 에 `mcp` 2.x 가 깔려 `Server.list_tools` 가 사라지면서 6개 서버가 전부 기동에 실패했다 — 재현성의 핵심이다. |
| `.python-version` | `uv sync` 가 어떤 Python 을 받아올지 정해지지 않아, 검증된 것과 다른 런타임에서 돌게 된다 (현재 `3.12`). |
| `requirements.txt` | uv 를 쓸 수 없는 환경의 pip 폴백이 사라진다. `uv export` 산출물이므로 손으로 고치지 않는다. |

## 생성되는 것

| 파일 | 어떻게 만들어지나 |
|---|---|
| `pyproject.toml` | **원본을 고쳐 쓴다.** `packages.find` 의 `include` 와 `testpaths` 배열만 번들 범위로 교체하고 의존성·ruff·black·pytest 설정은 원본 그대로. 새로 쓰면 의존성이 두 벌이 되어 드리프트한다. 표식을 못 찾으면 조용히 넘어가지 않고 실패한다. |
| `README.md` | 서버 표(이름·기능·포트·진입점) + 빠른 시작(`uv sync --frozen` → `uv run verify_bundle.py` → `uv run <pkg>/mcp_server/server_stream.py`, uv 를 못 쓸 때의 `requirements.txt` + pip 폴백 포함) + 인증 설명. 잠긴 핵심 버전(`mcp` 등)도 여기 적힌다. 포트는 `spec/param_spec/<도메인>.yaml` 의 `server.port` 에서 읽는다 — 스크립트에 적지 않는다. |
| `bundle_manifest.json` | 서버 목록, 공용 구성, 원본 커밋, `tree_sha256`. `verify_bundle.py` 가 이 파일을 읽어 무엇을 검사할지 정한다. |
| `verify_bundle.py` | 스킬의 `assets/verify_bundle.py` 를 복사. 번들 안에서도, 샌드박스에서도 **같은 파일**이 돈다. |
| `MANIFEST.in` | sdist 에 `spec/param_spec/*.yaml` 을 동봉 (wheel 에는 패키지 밖이라 안 들어간다). |
| `database/.gitkeep` | `auth.db` 가 생길 자리. 디렉터리가 없으면 첫 인증에서 실패한다. |

`requirements.txt` 는 **생성하지 않는다** — 원본의 `uv export --no-hashes --no-dev
--no-emit-project` 산출물을 그대로 복사한다. 예전의 "빌드 환경의 `pip freeze` 로 requirements 를
고정한다"는 로직은 삭제됐다 — `uv.lock` 이 그 역할을 제대로 한다.

대신 빌드는 복사 직후 `uv lock --check` 로 **잠금과 `pyproject.toml` 이 맞는지 확인**하고,
어긋나면 빌드를 실패시킨다(`check_lock()`). 어긋난 잠금을 실어 보내면 받는 쪽의
`uv sync --frozen` 이 거부한다 — 그건 여기서 막아야 할 일이다.

## 제외 규칙

`build_bundle.py` 의 `EXCLUDE_PATTERNS` / `EXCLUDE_EXACT`. 패턴은 디렉터리 이름과 파일
이름 양쪽에 적용된다(`shutil.copytree(ignore=...)`).

주의: `.env` 는 정확한 이름으로만 막는다 — `.env.example` 은 **들어가야 하는** 파일이다.
`*.env` 같은 와일드카드로 막으면 예시 파일까지 사라진다.

멀티유저 모드(`MS365_MULTI_USER=1`) 산출물은 이름 규칙 + 구조 규칙 두 겹으로 막는다.

- 이름: `wrapped_dek.json`, `*.jsonl`(감사 로그), `*.key`/`*.kek`, `migration_mapping*.json`,
  `mail_metadata.json`, `metadata.json`
- 구조(`DATA_ROOT_MARKER`): `system/deployment.json` 이 있는 디렉터리의 `system/` 과 형제 `users/`
  를 통째로 뺀다. 데이터 루트를 실수로 패키지 안에 둔 경우까지 잡기 위해서다 — 사용자별 토큰 DB·
  registry·이전 산출물(snapshot·staging·quarantine)이 전부 그 아래에 있다.

## 비밀 스캔

두 겹이다.

1. **실값 대조** — 로컬 `.env` 를 파싱해 12자 이상인 값들을 뽑고, 번들의 모든 텍스트
   파일에 그 문자열이 있는지 본다. 가장 확실한 신호다. 위반 보고에는 **키 이름과 파일
   경로만** 남기고 값은 절대 찍지 않는다.
2. **모양 대조** — `AZURE_CLIENT_SECRET=<8자 이상>`, 30자 이상 UUID 형태의 CLIENT_ID,
   40자 이상 `refresh_token`/`access_token` 리터럴, 멀티유저 bearer key 실값
   (`m365v1.<32 hex>.<43 base64url>`), `MS365_KEK_B64=<40자 이상>`. `your_`, `_here`, `example`, `<`,
   `${` 같은 자리표시자 힌트가 값에 있거나, hex 자리 3/4 이상이 0 인 테스트용 GUID 면 통과시킨다
   (`.env.example`·`mcp_common/testing.py` 가 여기 해당한다). bearer key 는 형식이 고정이라 예외가 없다.

`verify_bundle.py` 의 secrets 검사도 같은 대상(파일 이름 + bearer key 리터럴)을 받는 쪽에서 다시 본다.

걸리면 **번들을 지우고** 예외를 던진다. 반쯤 만들어진 번들이 남아 실수로 배포되는 것을
막기 위해서다.

## 검증되지 않는 것

- **Azure 실호출**: 번들 검증은 인증 없이 도는 범위(import·스키마·`/health`)까지다.
  실제 메일 조회가 되는지는 받은 쪽이 자기 자격증명으로 확인해야 한다.
- **선택 의존성**: `converters` extra(python-docx, pdfplumber, pyhwpx 등)는
  `requirements.txt` 에 없다. 첨부파일 변환 경로는 함수 안에서 지연 import 되므로
  기동·스키마 검증에는 영향이 없지만, 실제 변환을 쓰려면 받은 쪽이
  `uv sync --frozen --extra converters` 를 해야 한다.
