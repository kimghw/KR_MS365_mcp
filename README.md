# KR_MS365_mcp

MS Graph API 기반 MS365 MCP 서버 모음. Outlook / Calendar / OneNote / OneDrive / Teams / Todo / Time 등 각 서비스를 독립 MCP 서버(HTTP Stream)로 제공한다.

## 모듈 구성

| 모듈 | 설명 |
|------|------|
| `mcp_outlook/` | 메일 조회·발송, 첨부파일 처리 (GraphMailClient Facade) |
| `mcp_calendar/` | 일정 조회·생성 (GraphCalendarClient Facade) |
| `mcp_onenote/` | OneNote 페이지 읽기/쓰기/삭제 + 로컬 DB 동기화 (`database/onenote.db`) |
| `mcp_onedrive/` | OneDrive 파일 관리 (GraphOneDriveClient Facade) |
| `mcp_teams/` | Teams 메시지·채널 (GraphTeamsClient Facade + 로컬 DB) |
| `mcp_todo/` | Microsoft To Do 작업 관리 (GraphTodoClient Facade) |
| `mcp_time/` | 현재 시간을 다양한 형식으로 반환 (Graph API 미사용) |
| `mcp_file_handler/` | 파일 변환·관리 (PDF/DOCX/HWP/Excel/이미지, OCR, OneDrive 연동) |
| `mcp_editor/` | MCP 툴 정의 편집용 웹 에디터 (Flask, 선택 설치) |
| `mcp_common/` | 공용 런타임 — param_spec 로딩·스키마 정규화·stdio/HTTP 트랜스포트·부트스트랩 |
| `core/` | 모듈 간 공용 Protocol 정의 (`protocols.py`) |
| `session/` | Azure AD OAuth 인증 (AuthManager, 토큰 SQLite 저장) |
| `cloudflare/` | Cloudflare 터널 리셋 스크립트 |
| `main.py` | 인증 플로우 단독 실행 진입점 |
| `callback_server.py` | OAuth 콜백 처리 웹서버 (aiohttp) |

## 포트 할당

SSOT: `.claude/skills/port_manager/port_list.md`

| 포트 | 서비스 |
|------|--------|
| 5000 | OAuth Callback (`callback_server.py`) |
| 5001 | Outlook MCP |
| 5002 | Calendar MCP |
| 5003 | Teams MCP |
| 5004 | OneDrive MCP |
| 5005 | OneNote MCP |
| 5006 | Todo MCP |
| 5007 | Time MCP |
| 5008 | FileHandler MCP |

각 MCP 서버 실행: `uv run <모듈>/mcp_server/server_stream.py`
(또는 `.venv/Scripts/python.exe <모듈>/mcp_server/server_stream.py`)

## 아키텍처

- **계층 구조**: `*_service.py` (Facade, MCP 툴 진입점) → `graph_*_client.py` (Graph API 호출) → query/하위 모듈
- **토큰 주입 패턴**: `core/protocols.py`의 `TokenProviderProtocol`로 인증을 추상화.
  모든 Graph 클라이언트는 `token_provider` 파라미터로 주입받으며, 미지정 시 기본값으로 `session.AuthManager`를 사용한다. 테스트에서는 Mock 주입 가능.
- **인증(session/)**: Azure AD OAuth 2.0. `AuthManager`(다중 사용자 관리) + `AuthService`(OAuth 플로우) + `AuthDatabase`(SQLite 토큰 저장) + `callback_server.py`(브라우저 인증 콜백).

## 설치

환경 관리는 [uv](https://docs.astral.sh/uv/)가 한다. Python 을 미리 깔아 둘 필요가 없다 —
`.python-version`(3.12)을 보고 uv 가 받아온다.

```bash
# uv 가 없다면 (Windows, 관리자 권한 불필요)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

uv sync --frozen                       # .venv 생성 + uv.lock 그대로 설치 (dev 그룹 포함)
uv sync --frozen --extra converters    # 선택: 첨부파일 변환기 (PDF/DOCX/HWP/Excel/OCR)
uv sync --frozen --extra agent         # 선택: OneNote 요약 (claude-code-sdk)
```

**`--frozen` 을 기본으로 쓴다.** 잠금을 다시 풀지 말라는 뜻이다 — `uv.lock` 에 적힌 조합이
실제로 기동까지 확인된 것이고, 다시 풀면 그날의 최신본이 들어온다. 실제로 버전이 고정되지
않았던 시절 `mcp` 2.x 가 깔려 `Server.list_tools` 가 사라지는 바람에 6개 서버가 전부 기동에
실패한 적이 있다(2026-09-16, 자세한 경위는 [spec/spec_패키지관리.md](spec/spec_패키지관리.md)).

의존성을 **의도적으로** 바꿀 때만:

```bash
uv add <패키지>                        # 추가 (pyproject + uv.lock 동시 갱신)
uv lock --upgrade-package <패키지>     # 특정 패키지만 올리기
uv export --no-hashes --no-dev --no-emit-project -o requirements.txt   # pip 사용자용 재생성
```

`requirements.txt` 는 **`uv export` 산출물**이라 손으로 고치지 않는다. `uv.lock` 은 커밋한다.

Windows 에서는 `tzdata` 가 **필수 의존성**이다(`mcp_time` 의 `zoneinfo` 가 OS 시간대 DB 를 못
쓴다). `pyproject.toml` 에 `tzdata; sys_platform == 'win32'` 로 잠겨 있어 `uv sync --frozen` 과
`requirements.txt` 모두에 포함된다.

명령 실행은 `uv run <스크립트>` 로 한다 (환경 활성화 불필요):

```bash
uv run pytest -q
uv run ruff check .
```

`.env` 설정 (`.env.example` 참조):

```env
AZURE_CLIENT_ID=...
AZURE_CLIENT_SECRET=...
AZURE_TENANT_ID=...
AZURE_REDIRECT_URI=http://localhost:5000/callback
# 스코프는 공백 구분, offline_access 없으면 refresh_token 미발급
AZURE_SCOPES=https://graph.microsoft.com/.default offline_access openid
```

HTTP 서버(`server_stream.py`) 바인드·요청 검사 (선택, 기본값 있음):

```env
MCP_BIND_HOST=127.0.0.1       # 바인드 호스트 (기본 loopback)
MCP_ALLOW_PUBLIC_BIND=0       # 1 이어야 0.0.0.0 등 public 바인드 허용
MCP_ALLOWED_HOSTS=            # Host 헤더 추가 허용 (쉼표 구분, host:* 와일드카드 가능)
MCP_ALLOWED_ORIGINS=          # Origin 헤더 추가 허용 (쉼표 구분, 같은 규칙)
```

`/mcp` 는 DNS 리바인딩 방어로 `Host`·`Origin` 헤더를 검사한다. 기본 허용은 `localhost:*` ·
`127.0.0.1:*` · `[::1]:*`(오리진은 같은 목록의 `http://`)이고, `MCP_BIND_HOST` 가 특정 IP 면 그
IP 도 자동 포함된다. 허용 밖이면 Host 는 **421**, Origin 은 **403** 으로 거절한다
(`mcp_common/http_transport.py`). 호출자 인증은 없으므로 외부 노출 시 별도 보호가 필요하다.

## 인증 플로우

1. 첫 MCP 툴 호출 시 자동으로 브라우저 인증이 트리거된다 (콜백은 5000 포트).
2. 발급된 토큰은 `database/auth.db`(SQLite)에 저장된다.
3. Refresh token 유효기간은 90일이며, 토큰 갱신·재인증 시 만료 시각이 +90일로 리셋된다.
4. `python main.py`로 인증 플로우만 단독 실행할 수도 있다.

## 스킬 (`.claude/skills/`)

Claude Code에서 슬래시 명령으로 호출하는 프로젝트 전용 스킬.

| 스킬 | 설명 |
|------|------|
| `setup_ms365/` | venv·의존성·`.env`·MCP 등록(셋업)부터 HTTP 서버 실행·중지·상태 점검까지 |
| `port_manager/` | 포트 번호 대장(`port_list.md`) 관리 — 조회·등록·충돌 차단 |
| `export_ms365/` | 선택한 MCP 서버를 독립 실행 가능한 번들로 잘라내 zip 또는 새 GitHub 저장소로 배포 |

### 번들 내보내기 (`/export_ms365`)

도메인 서버(`outlook` `calendar` `teams` `onedrive` `onenote` `todo` `file_handler`) 중
1개 이상을 골라 **그 자체로 기동되는 프로젝트**로 잘라낸다. 인증(`session/`,
`callback_server.py`)·공용 런타임(`mcp_common/`, `core/`)·공용 time 서버(`mcp_time/`)·설치
스킬(`.claude/skills/setup_ms365/`)·선택 서버의 도구 계약(`spec/param_spec/<서버>.yaml`)은
**항상 자동 포함**된다.

- 번들은 원본과 **같은 상대 경로 구조**를 쓴다. 그래야 `mcp_common/bootstrap.py`의 sys.path
  삽입, `param_spec`의 `spec/param_spec` 해석, `session`의 `database/auth.db` 경로가 손대지
  않아도 그대로 성립한다.
- `.env` · `*.db` · `.venv/` · `__pycache__/` · `*.log` · `.git/` 등은 제외된다. 빌드 마지막에
  **비밀 스캔**이 돌아 로컬 `.env`의 실제 값이 번들에 섞이면 번들을 지우고 실패시킨다.
- 의존성 재현을 위해 `uv.lock` · `.python-version` · `requirements.txt`가 함께 실린다.
  빌드 시 `uv lock --check`로 잠금과 `pyproject.toml`이 맞는지 확인하고, 어긋나면 빌드를
  실패시킨다.
- Windows Sandbox 백지 환경에서 uv 설치 → `uv sync --frozen` → 서버 기동(`/health`)까지
  실제로 검증한다 (약 1분, `--no-sandbox`로 생략 가능).
- 결과물은 `output/bundles/` 아래에 만들어진다. public GitHub 저장소는 `--confirm-public`
  없이는 생성하지 않는다.

```bash
/export_ms365                          # 서버·배포 방식을 물어보고 진행
/export_ms365 outlook,calendar zip     # 서버·방식 지정, 질문 없이 끝까지
/export_ms365 all github               # 도메인 서버 6개 (file_handler는 명시해야 포함)
```

## 문서

| 경로 | 내용 |
|------|------|
| `spec/spec_MCP트랜스포트.md` | MCP 트랜스포트(stdio/HTTP Stream) 사양 |
| `spec/spec_도구정의.md` | 도구 정의·param_spec 사양 |
| `spec/spec_번들내보내기.md` | 번들 내보내기 사양 (`/export_ms365`) |
| `spec/spec_패키지관리.md` | uv 전환 — `uv.lock`·`.venv`·`--frozen` 규약, 의존성 바꾸는 법 |
| `spec/param_spec/*.yaml` | 도메인별 도구 계약 SSOT — `inputSchema`·기본값·호출 인자를 여기서 파생 |
| `references/` | 지식저장소 — 외부 시스템의 동작 방식·제약 (예: `windows_sandbox.md`) |
| `docs/` | 설계 메모·환경변수 등 참고 문서 |

## 개발

```bash
# 테스트
pytest mcp_teams/tests mcp_onedrive/tests mcp_file_handler/tests

# 린트/포맷 (설정: pyproject.toml)
ruff check .
black .
```
