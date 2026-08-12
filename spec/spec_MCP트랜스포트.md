# spec_MCP트랜스포트 — stdio · Streamable HTTP 2종 체계

MCP 서버를 **어떻게 구동하는가**에 대한 사양서다. 어떤 트랜스포트를 지원하고, 두
트랜스포트가 무엇을 공유하며, 무엇만 따로 두는지를 정한다.

> 도구 계약(이름·설명·파라미터·옵션·필수여부·기본값)을 **어떻게 관리하는가**는
> [spec_도구정의.md](spec_도구정의.md) 가 원본이다. 이 문서는 그 계약을 어떻게 실어
> 나르는지만 다룬다.

---

## ① 질의·요청 히스토리

| 날짜 | 요지 | 답/결정 |
|------|------|---------|
| 2026-08-12 | "현재 MCP 서버가 stdio·streamable 로 되어 있나?" | 아니다. 실제로는 **rest / stdio / stream 3종**이었다. 도메인 8개 × 트랜스포트별 파일로 서버 소스 15개가 존재. |
| 2026-08-12 | "streamable 이 최신 표준인가?" | 그렇다. MCP 스펙에서 HTTP+SSE(`/sse` + `/messages` 2엔드포인트)는 2024-11-05 판으로 **폐기(deprecated)** 되었고, 2025-03-26 판부터 단일 엔드포인트 **Streamable HTTP** 가 표준이다. 현행 `server_stream.py` 들은 이미 Streamable HTTP 구현이다. |
| 2026-08-12 | "http_sse 를 삭제하고 싶다" | **`http_sse` 라는 트랜스포트는 이 프로젝트에 실재하지 않았다.** 이름만 SSE 로 잘못 적힌 문서·UI 라벨이 있었을 뿐이고, 진짜 레거시 `/sse` 구현은 참조 0건의 죽은 JS 템플릿 1개뿐이었다. 사용자가 확인 후 **삭제 대상을 REST 계열 전면으로 재확정**했다. |
| 2026-08-12 | "stdio 와 streamable 을 동일하게 관리하고 싶다" | 확정. 도구 계약·핸들러·부트스트랩을 공유하고 트랜스포트 고유 코드만 분리한다(②-2~②-5). |
| 2026-08-12 | stdio 자체 JSON-RPC 루프를 유지할지 질의 | 폐기 확정. 공식 SDK 의 `mcp.server.stdio.stdio_server()` + `mcp.server.lowlevel.Server` 로 전환한다. 자체 루프의 실제 결함 8종은 ③-4 참조. |
| 2026-08-12 | **"진자템플릿은 더이상 사용하지 않을거야. 생성기를 사용하지 않고 spec 으로 api를 관리할거야"** | **방향 전환 확정.** jinja 템플릿·`generate_universal_server.py`·`tool_definition_templates.yaml`·`mcp_editor` 전부 폐지. 서버 파일은 생성물이 아니라 **손으로 쓰는 얇은 배선**이 되고, 도구 계약은 `spec/param_spec/<도메인>.yaml` 이 원본이 된다([spec_도구정의.md](spec_도구정의.md)). 이 문서의 "생성기 계약"·"생성물 마커" 조항은 이 결정으로 무효가 되어 삭제했다. |

---

## ② 확정 사양

### ②-1. 지원 트랜스포트는 2종뿐이다

| 트랜스포트 | 파일 | 용도 |
|---|---|---|
| **stdio** | `mcp_<도메인>/mcp_server/server_stdio.py` | Claude Desktop / Claude Code 로컬 실행 |
| **Streamable HTTP** | `mcp_<도메인>/mcp_server/server_stream.py` | 원격·다중 클라이언트, `/health` 노출 |

- **REST 계열은 전면 폐지한다**(2026-08-12 사용자 확정). `server_rest.py` 계열은 코드에서
  사라졌고 다시 만들지 않는다.
- 새 트랜스포트를 추가하지 않는다. 필요해지면 ①에 질의를 남기고 ②를 고친 뒤 구현한다.
- **모든 도메인은 두 트랜스포트를 모두 갖는다.** 한쪽만 있는 상태는 결함으로 본다.

### ②-2. 도메인 서버는 3파일이다 — 서버 파일은 배선만

```
spec/param_spec/<도메인>.yaml        ← 도구 계약의 유일한 원본 (spec_도구정의.md)
        │ 기동 시 파생 (mcp_common/param_spec.py)
        ▼
mcp_<도메인>/mcp_server/handlers.py   ← 배선만. 도구 정의를 여기에 적지 않는다.
        ├── server_stdio.py          # stdio 고유만 (②-5)
        └── server_stream.py         # HTTP 고유만 (②-5)
```

| 파일 | 그 파일에만 있어야 하는 것 |
|---|---|
| `handlers.py` | `SPEC`(param_spec 로드), `SERVER_NAME`/`SERVER_VERSION`/`DEFAULT_PORT`, 도구 이름→서비스 함수 핸들러, `runtime`·`lifecycle`, `build_mcp_server()` |
| `server_stdio.py` | 부트스트랩 호출 + `run_stdio()` 한 줄 |
| `server_stream.py` | 부트스트랩 호출 + ASGI 앱 조립 + 포트 |

- **코드 생성은 없다.** 미리 구워 둔 산출물이 없으므로 spec 과 런타임이 어긋날 수 없다.
  서버 파일은 손으로 쓰지만, **드리프트할 내용 자체를 갖고 있지 않다**(도구 정의도 부트스트랩
  절차도 트랜스포트 배선도 전부 밖에 있다).
- `build_mcp_server()` 가 `mcp.server.lowlevel.Server` 를 만들어 돌려주고, **두 트랜스포트가
  그것을 그대로 받아 구동만 한다.** 도구 등록(`@server.list_tools()` / `@server.call_tool()`)이
  트랜스포트 파일에 나타나면 위반이다. 표준형: `mcp_time/mcp_server/handlers.py:49-66`.
- `handlers.py` 는 트랜스포트를 import 하지 않는다(단방향 의존). 부트스트랩도 하지 않는다 —
  호출자가 `mcp_common.bootstrap` 을 먼저 돌린 뒤 import 해야 한다.
- 서버 파일 목표 크기는 **50줄 안쪽**이다(실측 ③-1).

### ②-3. stdio·stream 은 공식 SDK 위에서 같은 것을 공유한다

- 자체 JSON-RPC 루프는 **폐기**했다. 프로토콜 버전 협상·capabilities·`ping`·오류 코드·취소
  알림은 **SDK 에 맡긴다.** 직접 하드코딩하지 않는다.
- 공유하는 층은 세 개다.

| 층 | 위치 | 공유 대상 |
|---|---|---|
| 도구 계약 | `spec/param_spec/<도메인>.yaml` | 도구 이름·설명·`inputSchema`·기본값 ([spec_도구정의.md](spec_도구정의.md)) |
| 핸들러 + `Server` | `mcp_<도메인>/mcp_server/handlers.py` | 도구 등록 1회, `runtime`, `lifecycle` |
| 트랜스포트 배선·런타임 | `mcp_common/` | 부트스트랩·stdio 구동·HTTP 배선·검증·오류·경로·사용자 해석 |

- **stdio 사본이 stream 보다 열등해지는 일이 구조적으로 불가능해졌다.** 두 파일이 같은
  `Server` 객체를 받으므로 도구 목록·스키마·실행 결과가 갈릴 경로가 없다.
- 설치된 SDK: `mcp` 1.29.0. `LATEST_PROTOCOL_VERSION = "2025-11-25"`,
  `DEFAULT_NEGOTIATED_VERSION = "2025-03-26"` (`venv/Lib/site-packages/mcp/types.py:27,35`).

### ②-4. 부트스트랩은 한 벌이고, 순서가 계약이다

`mcp_common/bootstrap.py` 가 아래 순서를 **고정**한다. 서버 파일은 이 함수를 호출만 한다
(`bootstrap_stdio()` = `:184`, `bootstrap_http()` = `:205`).

1. 원본 stdout 보관 → `sys.stdout = sys.stderr` (**stdio 만**, 가장 먼저)
2. `.env` 로드 (`encoding="utf-8-sig"`)
3. **전체 env 값의 BOM 제거** — 특정 키만 훑는 방식은 금지
4. `sys.path` 삽입 (프로젝트 루트 · 패키지 디렉터리)
5. 로깅 설정 — **stderr 로만**
6. 그 다음에야 서비스 모듈을 import 한다

- `mcp_common` 자체를 import 하려면 프로젝트 루트가 먼저 `sys.path` 에 있어야 하므로, 서버
  파일 선두의 `sys.path.insert` 2줄만은 남는다. `mcp_common` 은 import 시점에 stdout 으로
  아무것도 쓰지 않으므로 이 전문(preamble) 단계에서 읽어도 안전하다.
- Windows 인코딩 보정(`reconfigure(encoding="utf-8")`)은 stdout·stdin·stderr 에 적용하며 여기
  포함된다.
- **자격증명 값을 로그로 찍지 않는다.** `.env` 로드 결과는 키의 **존재 여부(bool)** 로만
  남긴다(`bootstrap.py:136-148`).
- `package_name` 인자와 실제 디렉터리가 다르면 기동 시 `ValueError` 로 죽는다 — 파일을 옮기고
  인자를 안 고친 경우를 조용히 넘기지 않는다.

### ②-5. 트랜스포트 고유로 남는 것 (여기까지만 분리한다)

| stdio 고유 | stream 고유 |
|---|---|
| stdout 리다이렉트와 원본 stdout 보관 | `resolve_bind_host()` 바인드 주소 정책 |
| `stdio_server(stdout=...)` 명시 주입 | uvicorn 기동, 포트 |
| stdin EOF = 정상 종료 시맨틱 | `/health` 엔드포인트 |
| | `Mcp-Session-Id` 헤더 세션 관리(SDK) |
| | Accept 헤더에 따른 JSON/SSE 응답 협상 |

- **stdout 명시 주입이 stdio 의 핵심 제약이다.** SDK 는 `sys.stdout.buffer` 를 직접 감싸는데
  부트스트랩이 이미 `sys.stdout` 을 stderr 로 돌려놨으므로, 그대로 두면 JSON-RPC 응답이 통째로
  stderr 로 나가 클라이언트가 아무 응답도 못 받는다. `boot.original_stdout_buffer()` 를
  `stdio_server(stdout=...)` 에 반드시 넘긴다(`mcp_common/stdio_transport.py:46,56`).
- **anyio 백엔드는 asyncio 로 고정한다.** SDK 는 anyio 기반이지만 도메인 서비스가 순수
  asyncio(aiohttp)다 (`stdio_transport.py:76`).
- HTTP 는 `Mount` 가 아니라 `Route("/mcp")` 를 쓴다 — `Mount` 는 `/mcp` 를 `/mcp/` 로
  307 리다이렉트하는데 따라가지 못하는 클라이언트가 있다(`mcp_common/http_transport.py:75-81`).
- 여기서의 "SSE" 는 Streamable HTTP **단일 엔드포인트 안의 응답 형식 협상**(`json_response=False`)을
  뜻하며, 폐기된 HTTP+SSE 트랜스포트와 다르다.

### ②-6. 도메인 고유 확장은 배선 교체로 한다

공통 배선(`build_starlette_app()`)에 도메인 고유 필드가 필요하면, **공통 빌더를 고치지 말고
만들어진 앱의 라우트만 교체한다.** 선례: `mcp_file_handler/mcp_server/server_stream.py:52-75`
가 `/health` 에 보안 고지(허용 루트·바인드 정책)를 덧붙인다. 공통 배선은 그대로 재사용된다.

### ②-6-1. 새 도메인 추가 절차 (2026-08-12 확정 — 본은 `mcp_time`)

스캐폴드 생성기는 없다. 아래 4단계가 표준 절차이며, 전부 합쳐 150줄 안팎이다.

| 순서 | 작업 | 본보기 |
|---|---|---|
| 1 | `spec/param_spec/<도메인>.yaml` 작성 — `server:`(name/version/port) + `tools:`. 형식 정본은 `mcp_common/param_spec.py` docstring | [spec/param_spec/time.yaml](../spec/param_spec/time.yaml) |
| 2 | `mcp_<도메인>/mcp_server/handlers.py` — `SPEC = load_param_spec("<도메인>")`, 서비스 인스턴스, 핸들러(`**SPEC.call_args(...)`), `build_mcp_server()` | [mcp_time/mcp_server/handlers.py](../mcp_time/mcp_server/handlers.py) (79줄) |
| 3 | `server_stdio.py` / `server_stream.py` — `mcp_time` 것을 복사해 도메인명·포트만 교체 | 각 24/45줄 |
| 4 | `.claude/skills/port_manager/port_list.md` 에 포트 행 추가, 필요 시 `~/.claude.json` 에 MCP 등록 | — |

- 도구 정의·기본값·`Server` 등록 코드가 1~3 밖에 나타나면 위반이다(②-2·②-3).
- spec 파일이 없거나 계약 위반이면 **기동 자체가 실패**하므로, 1번을 건너뛴 채 2~3을
  만들 수 없다 — 절차가 코드로 강제된다.

### ②-7. `tools/list` 로 나가는 것

MCP 스펙 필드(`name` / `description` / `inputSchema`)만 나간다. 내부 메타데이터가 섞일 여지
자체가 없다 — `ParamSpec` 이 그 3개 키로만 페이로드를 만들기 때문이다
(`mcp_common/param_spec.py:368-379`). 두 트랜스포트가 같은 객체를 쓴다.

### ②-8. 완료 판정 기준

| # | 기준 | 확인 방법 |
|---|---|---|
| 1 | `server_rest` 문자열이 코드에 0건 | `git grep server_rest` |
| 2 | 도메인 전부가 stdio·stream 2파일을 갖는다 | 파일 목록 |
| 3 | 도구 정의·`Server` 등록이 서버 파일에 0건 | `server_std*.py`/`server_stream.py` 에 `list_tools` 없음 |
| 4 | 같은 도메인의 stdio·stream `tools/list` 가 동일 | 같은 객체를 공유하므로 구조적 보장 |
| 5 | stdio 에 깨진 JSON 한 줄을 보내도 서버가 살아 있다 | ③-4 결함 1의 회귀 검사 |
| 6 | `AZURE_CLIENT_ID` 값이 로그에 나타나지 않는다 | `git grep "AZURE_CLIENT_ID"` 에 `repr` 없음 |
| 7 | 6개 등록 서버의 `/health` 가 200 healthy | `curl /health` |

---

## ③ 구현 상태 (2026-08-12 — ②-1~②-8 이행 완료)

### ③-1. 도메인 8개 전환 완료 (전후 줄 수)

| 도메인 | 도구 | handlers.py | server_stdio.py | server_stream.py |
|---|---:|---:|---:|---:|
| outlook | 10 | 217 | 1306 → **25** | 607 → **45** |
| calendar | 7 | 127 | 1002 → **25** | 481 → **45** |
| teams | 14 | 185 | 487 → **24** | 479 → **45** |
| onedrive | 9 | 141 | 265 → **25** | 351 → **45** |
| onenote | 4 | 112 | 242 → **24** | 266 → **45** |
| todo | 8 | 132 | 285 → **24** | 271 → **45** |
| time | 1 | 79 | 없었음 → **24** | 151 → **45** |
| file_handler | 7 | 245 | 196 → **34** | 154 → **83** |

- `mcp_time` 은 stdio 가 없었다(②-1 위반). 신설해 해소했다.
- `file_handler` 만 조금 크다 — stdio 는 `tool_definitions.py` 관문 경유, stream 은 보안
  고지 `/health` 교체(②-6) 때문이다.
- `mcp_outlook/mcp_server/server_stdio.py` 의 1,200줄 상한 위반(1306줄)은 해소됐다.
- **REST 3파일(2,411줄)은 삭제됐다.**

### ③-2. `mcp_common` — 트랜스포트 공용층 (2,078줄)

| 파일 | 줄 | 성격 | 내용 |
|---|---:|---|---|
| `param_spec.py` | 562 | **신설** | 도구 계약 로더. 형식 정본은 이 모듈 docstring([spec_도구정의.md](spec_도구정의.md)) |
| `runtime.py` | 244 | 기존 | `ToolRuntime`·`ServiceLifecycle`·health 페이로드 |
| `schema_normalize.py` | 233 | **이관** | `mcp_editor` 에서 옮겨 온 정규화 유일 원본 |
| `bootstrap.py` | 221 | **신설** | ②-4 의 기동 순서 |
| `user_resolver.py` | 136 | 기존 | 사용자 이메일 해석 |
| `validation.py` | 132 | 기존 | 인자 검증·기본값 병합 |
| `http_transport.py` | 102 | **신설** | Starlette `/mcp` + `/health` 배선 한 벌 |
| `paths.py` | 94 | 기존 | 허용 루트 경로 해석 |
| `stdio_transport.py` | 81 | **신설** | SDK `stdio_server()` 구동 한 벌 |
| `net.py` | 81 | 기존 | `resolve_bind_host` |
| `errors.py` | 77 | 기존 | 오류 정규화 |
| `service_meta.py` | 60 | **이관** | `@mcp_service` — 메타데이터 표식으로 강등(런타임 무영향) |
| `__init__.py` / `auth.py` | 39 / 16 | 기존 | 재수출 · 인증 헬퍼 |

- 이전에는 stdio 가 `errors` 만, stream 이 `net` 만 쓰는 식으로 **공통층조차 트랜스포트별로
  다른 부분집합을 소비**했다. 이제 두 트랜스포트가 같은 `runtime`·`errors` 경로를 지나므로
  같은 도구가 실패했을 때 오류 표현이 갈리지 않는다.

### ③-3. 검증 결과 (실측)

| 항목 | 결과 |
|---|---|
| 6개 등록 서버(5001~5006) 재기동 후 `/health` | 전부 **200 healthy** |
| `tools/list` 도구 개수 | 도메인별 기대치와 **전부 일치** |
| 실제 Graph API 호출 | `todo_lists_view top=3` → 요청 URL 에 `$top=3` 반영 **성공** |
| Streamable HTTP 준수 검사 (파일럿 `mcp_time`) | **8/8 PASS** |
| 8개 도메인 import · 6개 서버 기동 (`mcp_editor` 삭제 후) | **정상** |

### ③-4. stdio 자체 구현의 결함 8종 — 전부 해소됨

SDK 전환으로 자동 해소됐다. 회귀 검사 시 확인할 목록으로만 남긴다.

| # | 결함 | 영향 | 확인 |
|---|---|---|---|
| 1 | **깨진 JSON 수신 시 서버 종료** — 파싱 실패를 EOF 로 오인 | 치명 | 깨진 줄에도 **서버 생존 확인** |
| 2 | `protocolVersion` 이 `"2024-11-05"` 하드코딩 | 높음 | **협상 확인(2025-06-18)** |
| 3 | 취소 알림을 `"cancelled"` 로 비교(스펙명 `notifications/cancelled`) — 영영 매칭 안 됨 | 중간 | SDK 처리 |
| 4 | 요청 **순차 처리** — 느린 도구 1건이 이후 전부를 블록 | 높음 | **동시 처리 확인** |
| 5 | `ping` 이 `{"pong": true}` 반환(스펙은 `{}`) | 낮음 | **`{}` 확인** |
| 6 | `-32700` parse error 응답 없음 | 중간 | SDK 처리 |
| 7 | capabilities 고정, `instructions` 없음 | 낮음 | SDK 처리 |
| 8 | 비표준 `shutdown` 메서드 | 낮음 | 제거. Claude Desktop 은 stdin 닫기로 종료하므로 무영향 |

### ③-5. 트랜스포트 통합으로 드러나 해소된 드리프트

| # | 드리프트 | 실태 | 현재 |
|---|---|---|---|
| 1 | **stdio 도구 정의가 stream 보다 열등** | onenote·onedrive·teams 의 stdio 쪽 도구 정의에 **설명이 빠져 있었다** | 한 원본 공유라 갈릴 수 없다 |
| 2 | 부트스트랩 15벌 | env BOM 제거 범위·`reconfigure`·`lifecycle.errors` 검사 유무가 도메인마다 달랐다 | `bootstrap.py` 한 벌 |
| 3 | **자격증명 stderr 노출 8곳** | `repr(os.getenv("AZURE_CLIENT_ID"))` 를 찍었다 | 존재 여부(bool)만 기록 |
| 4 | `file_handler` stdio 의 stdout 미보호 | 서비스 모듈의 `print()` 가 JSON-RPC 를 오염시킬 수 있었다 | `bootstrap_stdio()` 가 항상 보호 |
| 5 | 런타임 객체 이름 2벌(`RUNTIME` vs `runtime`) | calendar 만 대문자 | 소문자로 통일 |
| 6 | `tools/list` 구현 2가지 | 5개 서버가 내부 메타데이터를 그대로 노출 | ②-7 로 구조적 해소 |

### ③-6. 진행 상태 요약

| ②의 항목 | 상태 |
|---|---|
| ②-1 트랜스포트 2종 · REST 폐지 | **완료** (8/8 도메인, REST 3파일 삭제) |
| ②-2 3파일 구조 · 배선만 | **완료** (8/8) |
| ②-3 SDK 공유 | **완료** (stdio 8, stream 8) |
| ②-4 부트스트랩 한 벌 | **완료** |
| ②-5 고유 코드 분리 | **완료** |
| ②-6 도메인 확장 = 배선 교체 | **완료** (file_handler 1건) |
| ②-7 `tools/list` 필드 | **완료** (구조적 보장) |
| ②-8 완료 판정 7항목 | **7/7** |

---

## ④ 미결 / 후속

### ④-1. 해소된 것 (더 이상 걸림돌이 아니다)

| 과거 걸림돌 | 결말 |
|---|---|
| SDK `stdio_server()` 와 stdout 리다이렉트 충돌 | `original_stdout_buffer()` 명시 주입으로 해소(②-5) |
| 부트스트랩 순서 제약 | `bootstrap.py` 가 순서를 고정(②-4) |
| `sys.path` 3경로 삽입 관행 | 선두 2줄 preamble + `bootstrap._insert_paths` 로 정리 |
| anyio ↔ asyncio 백엔드 | `backend="asyncio"` 명시 |
| 비표준 `shutdown` 손실 | 사용처 없음 확인, 무영향 |
| `{"pong": true}` 의존 | `verify_setup.py` 에 참조 없음. `/health` 200 으로 재확인 |
| 생성기 어휘 불일치(`sse`/`streamable_http`) | 생성기 자체가 사라져 소멸 |

### ④-2. 이후 해소된 것 (2026-08-12 당일 후속 처리)

| 항목 | 결말 |
|---|---|
| 새 도메인 추가 절차 부재 | **②-6-1 로 확정** — `mcp_time` 을 본으로 4단계 절차를 계약화. spec 없이는 기동이 실패하므로 절차가 코드로 강제된다 |
| `fastapi` 의존성 | `pyproject.toml`·`requirements.txt` 에서 제거 완료. `starlette`·`uvicorn`·`aiohttp` 는 유지 |
| outlook 잔여 모듈 | `server_init.py`·`final_validator.py` 삭제 완료 (참조 0건 확인 후) |
| `mcp_editor` 디렉터리 잔재 | orphan `__pycache__` 67개 포함 디렉터리째 삭제 완료 |
| `port_list.md` 유령 항목(8091) | 행 삭제 완료 |
| **패키징 — spec 이 wheel 밖** | **결정: 현행 유지.** 운영이 소스 트리 기반(port_list·NSSM)이라 wheel 배포가 실사용 경로가 아니다. 설치본 실행 시에는 `MCP_PARAM_SPEC_DIR` 로 지정한다(`mcp_common/param_spec.py` `spec_dir()` 이 최우선으로 읽음). `pyproject.toml` package-data 주석에 명시 |
| `mail_attachment_meta.select_params` 주입 여부 | **결정: `hidden` 확정.** 주입해도 결과가 같다 — None 이면 하류가 기본 6필드를 쓰는데 구 factor 의 4필드는 전부 그 부분집합이라 합집합이 동일하다. 근거를 `spec/param_spec/outlook.yaml` 주석에 기록 |
| pytest 부재 | `pytest`·`pytest-asyncio` 설치 후 전 스위트 실행: **182 통과 / 10 실패**. 실패 10건은 전부 이번 전환과 무관 — 해당 소스가 이 세션에서 미변경(HEAD 동일)이고, 원인은 ①이전 커밋에서 `AuthManager` 심볼 제거 후 테스트 mock 미수정(`test_mail_attachment.py` 6건) ②Windows `NamedTemporaryFile` 잠금(`test_converters.py` 3건) ③DB 상태 의존(`test_onenote_service.py` 1건) |

### ④-3. 남은 것

| # | 항목 | 내용 |
|---|---|---|
| 1 | **merge 기능 소멸** | 여러 도메인을 한 서버로 합치는 기능이 생성기와 함께 사라졌다. 필요해지면 **재설계 대상**(옛 구현은 프로토콜 어휘·옵션명 불일치로 이미 깨져 있었다) |
| 2 | `mcp_outlook/mcp_server/README.md` 낡음 | 172줄 전체가 구식 — 삭제된 `run.py` 실행법(`:37,40`), `http://localhost:3000`(`:43`), 존재하지 않는 도구 나열 |
| 3 | `instructions` 필드에 무엇을 넣을지 | SDK 전환으로 노출 가능해진 필드. 미정 |
| 4 | `docs/mcp_server_merge_design.md` · `docs/work_plan_derived_server.md` 처분 | 둘 다 **폐지된 생성기의 설계·계획서**다. 이 사양서로 대체 후 삭제할지 결정 |
| 5 | 기존 테스트 실패 10건 | ④-2 pytest 항목 참조. 이번 전환과 무관한 기존 결함이므로 별도 수선 대상 |
