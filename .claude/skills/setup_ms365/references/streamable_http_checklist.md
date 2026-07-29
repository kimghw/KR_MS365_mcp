# MCP Streamable HTTP Transport — Compliance Checklist

**기준 spec**: [MCP "Streamable HTTP" transport, revision 2025-03-26](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http)
(이전 revision `2024-11-05`의 "HTTP+SSE" transport는 **deprecated**. 그 차이는 [차이 섹션](#legacy-http--sse-2024-11-05-과의-차이) 참고)

이 체크리스트는 임의의 MCP HTTP 서버가 표준 Streamable HTTP transport를 구현하는지 **8가지 HTTP-수준 probe**로 확인합니다. application-layer(JSON-RPC method 동작)는 별개로 검증해야 하지만, transport-layer가 표준이 아니면 Claude Code 같은 표준 클라이언트가 아예 붙지 못합니다.

> **언제 이 문서를 봐야 하는가**
> - 새로 만든/받은 MCP HTTP 서버가 표준인지 확인할 때
> - Claude Code에 등록은 됐는데 호출이 이상하게 실패할 때
> - `setup_ms365` 스킬의 셋업 후 `/setup_ms365 check`가 transport 의심을 했을 때
> - "이거 streamable이야?"라는 질문이 나올 때 — 의미적 스트리밍(SSE/chunked)과 **MCP의 표준 transport**는 다른 얘기입니다.

---

## 1. 5초 판별 (이게 표준이냐 아니냐만)

```bash
SERVER_BASE=http://localhost:5001    # 검사할 서버 URL
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST "$SERVER_BASE/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: 2025-03-26" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}'
```

| HTTP 코드 | 판정 |
|---|---|
| **200** | 다음 섹션의 정밀 검증 진행 (표준일 가능성 높음) |
| 404 / 405 | 엔드포인트 경로 또는 메서드 미지원 — 표준 아님 (대표 사례: `/mcp/v1`, `/mcp/v1/initialize` 같은 legacy 분리 경로) |
| 406 | Accept 헤더 협상은 표준 거동 — `-H` 빠뜨렸는지 확인 후 재시도 |
| 500 | 서버 내부 오류 — 서버 로그 확인 |

---

## 2. 정밀 검증 — 8개 probe

각 probe에 **명령**, **기대 동작**, **불합치 시 의심점**을 기재. 통과 = 표준.

### 환경변수

```bash
SERVER_BASE=http://localhost:5001    # 검사 대상
PROTO_VER=2025-03-26                  # MCP-Protocol-Version
```

---

### Probe 1 — initialize 성공 + 세션 발급 + 컨텐츠 협상

```bash
curl -s -i -X POST "$SERVER_BASE/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: $PROTO_VER" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"'$PROTO_VER'","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}' \
  | head -25
```

**기대 응답:**
- HTTP `200 OK`
- 헤더에 **`mcp-session-id: <hex>`** 포함 ← 가장 중요한 표준 시그널
- `content-type: text/event-stream` (또는 `application/json` — Accept 협상 결과)
- SSE 본문: `event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{...}}`
- `result.protocolVersion`은 클라가 보낸 값과 동일 (또는 서버가 지원하는 다른 값)
- `result.serverInfo.name` / `version` 존재

**불합치 시:**
- session-id 헤더 없음 → 자체 구현 가능성 큼 (표준 클라가 후속 요청 못 함)
- 본문이 raw JSON (SSE 프레이밍 없음) + `content-type: application/json` → server가 `json_response=True`로 강제. 허용되긴 하지만 SSE 미지원이라는 뜻
- `result` 없이 `error` 반환 → application-layer 문제. transport는 통과로 간주

---

### Probe 2 — Accept 헤더 누락 시 406

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST "$SERVER_BASE/mcp" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"'$PROTO_VER'","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}'
```

**기대:** `HTTP 406`

**불합치:** 200 반환 → spec의 "client MUST set Accept: application/json AND text/event-stream"을 강제하지 않는 것. 호환성에는 영향 적지만 spec strict 모드 아님.

---

### Probe 3 — notifications/initialized → 202 Accepted

```bash
SID=$(curl -s -D - -o /dev/null -X POST "$SERVER_BASE/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: $PROTO_VER" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"'$PROTO_VER'","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}' \
  | tr -d '\r' | awk -F': ' 'tolower($1)=="mcp-session-id"{print $2}')
echo "session=$SID"

curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST "$SERVER_BASE/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: $PROTO_VER" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'
```

**기대:** `HTTP 202` (notification은 `id`가 없고 응답을 기대하지 않음)

**불합치:** 200 + 본문 응답 → notification과 request를 구분 안 함. 표준 클라가 응답 없는 걸 기대하므로 동작에 영향 적지만 spec strict 아님.

---

### Probe 4 — GET /mcp 으로 서버→클라 SSE 스트림 오픈

```bash
timeout 2 curl -s -i -N -X GET "$SERVER_BASE/mcp" \
  -H "Accept: text/event-stream" \
  -H "MCP-Protocol-Version: $PROTO_VER" \
  -H "Mcp-Session-Id: $SID" | head -10
```

**기대:**
- `HTTP 200 OK`
- `content-type: text/event-stream`
- (선택) 즉시 keep-alive ping 이벤트가 나올 수 있음

**불합치:**
- 405 Method Not Allowed → GET 미구현. 서버 푸시(server-initiated request, progress notification) 못 받음. 일부 시나리오 깨짐
- 404 → session-id 검증 실패 (Probe 3에서 SID 캡처 실패)

---

### Probe 5 — tools/list with 유효 세션

```bash
curl -s -X POST "$SERVER_BASE/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: $PROTO_VER" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' | head -c 300
```

**기대:**
- SSE 또는 JSON 본문에 `"result":{"tools":[...]}`
- 각 tool에 `name`, `description`, `inputSchema` (object) 포함

**불합치:** 빈 배열은 transport 통과로 간주 (application 문제). 에러면 transport+app 모두 의심.

---

### Probe 6 — 위조 session-id로 POST → 404

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST "$SERVER_BASE/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: $PROTO_VER" \
  -H "Mcp-Session-Id: not-a-real-session" \
  -d '{"jsonrpc":"2.0","id":99,"method":"tools/list","params":{}}'
```

**기대:** `HTTP 404`

**불합치:** 200 → session-id 검증 안 함. 멀티 사용자/세션 분리가 안 됨 (단일 사용자 환경에서는 문제 없을 수 있으나 spec 위반).

---

### Probe 7 — DELETE /mcp 으로 세션 종료 → 200

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X DELETE "$SERVER_BASE/mcp" \
  -H "MCP-Protocol-Version: $PROTO_VER" \
  -H "Mcp-Session-Id: $SID"
```

**기대:** `HTTP 200`

**불합치:** 405 → DELETE 미구현. 세션 명시적 종료 불가. spec 위반이지만 단기 사용에는 영향 적음.

---

### Probe 8 — DELETE 이후 같은 session-id로 POST → 404

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST "$SERVER_BASE/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: $PROTO_VER" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/list","params":{}}'
```

**기대:** `HTTP 404` (세션이 진짜 닫힌 것)

**불합치:** 200 → DELETE가 no-op이거나 세션을 안 닫음.

---

## 3. 합격 기준

| 통과 항목 수 | 판정 |
|---|---|
| Probe 1, 4, 5, 6 모두 통과 | **Streamable HTTP 호환** — Claude Code/Desktop의 MCP 클라이언트와 정상 동작 |
| Probe 1, 5 통과 / 6 실패 | **반호환** — 단일 세션에서 동작은 하지만 spec 위반 |
| Probe 1 실패 (404/405/header 없음) | **비호환** — 자체 구현이거나 legacy HTTP+SSE 또는 완전 비표준 |

Probe 2, 3, 7, 8은 엄격성(strict) 검증이라 실패해도 기본 동작은 가능. 하지만 SDK 표준 구현(`StreamableHTTPSessionManager`)을 쓰면 8개 다 자동으로 통과합니다.

---

## 4. 코드-수준 안티패턴 (검토 시 grep 키)

서버 코드를 읽기 전에 다음을 빠르게 점검:

| 안티패턴 | 발견 방법 | 의미 |
|---|---|---|
| `/mcp/v1`, `/mcp/v1/initialize`, `/mcp/v1/tools/list`, `/mcp/v1/tools/call` 같은 분리 경로 | `grep -rn "/mcp/v1" mcp_<server>/` | legacy "HTTP+SSE" 또는 자체 변형. 표준 클라는 `/mcp` 단일 엔드포인트만 호출. |
| `aiohttp.web.Application`을 직접 라우팅 | `grep -rn "from aiohttp import web" mcp_<server>/mcp_server/server_stream.py` | SDK transport를 안 씀. 자체 구현. |
| `self.app.router.add_post('/mcp', ...)` 같이 직접 라우트 등록 | `grep -rn "add_post.*mcp" mcp_<server>/` | SDK transport 미사용 |
| `Transfer-Encoding: chunked`를 NDJSON으로 직접 작성 (`stream_tool_response` 같은 함수) | `grep -rn "x-ndjson\|application/x-ndjson" mcp_<server>/` | 비표준 청크 포맷 — spec의 SSE와 무관 |
| `Mcp-Session-Id` 헤더를 코드 어디에서도 쓰지 않음 | `grep -rni "mcp-session-id\|mcp_session_id" mcp_<server>/` | 표준이면 SDK가 자동 처리하므로 보일 필요는 없지만, 자체 구현이라면 거의 확실히 없음 |

표준 구현의 시그니처:

| 표준 시그니처 | grep 키 |
|---|---|
| `from mcp.server.streamable_http_manager import StreamableHTTPSessionManager` | `grep -rn "streamable_http_manager" mcp_<server>/` |
| `from starlette.applications import Starlette` + `Route("/mcp", endpoint=<ASGI>)` | `grep -rn "Route(.*\"/mcp\"" mcp_<server>/` |
| `uvicorn.run(...)` | `grep -rn "uvicorn.run" mcp_<server>/` |
| `lifespan` 컨텍스트 + `session_manager.run()` | `grep -rn "session_manager.run\|async with session_manager" mcp_<server>/` |

---

## 5. 비표준 → 표준 마이그레이션 시 체크포인트

자체 aiohttp 구현을 SDK 기반으로 갈아끼울 때:

1. **handler 보존** — `async def handle_<tool_name>(args)` 함수들은 거의 그대로 재사용 가능. `args: Dict[str, Any]` 입력, `dict` 출력 패턴 유지.
2. **service 초기화 위치** — 기존 코드에 `await service.initialize()`가 있다면 `lifespan` async context로 옮길 것. SDK 패턴:
   ```python
   @contextlib.asynccontextmanager
   async def lifespan(_app):
       async with session_manager.run():
           if hasattr(service, "initialize"):
               await service.initialize()
           yield
   ```
3. **tool 정의 변환** — YAML로 로드한 dict는 `mcp.types.Tool(name=, description=, inputSchema=)`로 변환해서 `@server.list_tools()` 데코레이터로 노출.
4. **call_tool 시 validate_input** — internal/factor 파라미터가 inputSchema와 정확히 안 맞을 수 있으므로 `@server.call_tool(validate_input=False)` 권장. 기존 stdio 핸들러가 자체 검증.
5. **결과 포장** — handler가 반환한 dict가 이미 `content` 키를 가진 MCP 포맷이면 그대로, 아니면 `mcp_types.TextContent(type="text", text=json.dumps(result))` 한 줄로 감싸기. `auth_required` 같은 특수 상태는 그대로 text로 surface하면 됨.
6. **mount 경로** — `Route("/mcp", endpoint=<ASGI>)` (Mount 아니고 Route). Mount는 trailing slash redirect를 일으켜 클라이언트가 깨질 수 있음. FastMCP가 쓰는 트릭과 동일.
7. **포트 / 환경변수** — `MCP_SERVER_PORT` 환경변수 우선, 없으면 서버별 기본값(outlook 5001, calendar 5002 등).
8. **참조 구현** — [`mcp_outlook/mcp_server/server_stream.py`](../../../../mcp_outlook/mcp_server/server_stream.py) 가 이 프로젝트의 정답 패턴. 새 서버는 이걸 복사 후 service/import만 갈아끼우는 게 가장 안전.

---

## 6. Legacy "HTTP + SSE" (2024-11-05) 과의 차이

이전 transport는 **두 개의 엔드포인트**를 썼습니다:
- `POST /messages` (client → server)
- `GET /sse` (server → client SSE 채널, session-id 쿼리 파라미터)

`Streamable HTTP`(2025-03-26)는 이를 **단일 `/mcp`** 로 통합:
- `POST /mcp` : 요청 송신, 응답은 SSE 또는 JSON (Accept로 협상)
- `GET /mcp` : 서버→클라 푸시용 SSE 채널 (필요 시)
- `DELETE /mcp` : 세션 명시적 종료
- 세션은 `Mcp-Session-Id` **헤더**로 추적 (쿼리 파라미터 아님)

따라서 다음은 모두 **legacy 또는 비표준**으로 봅니다:
- `/sse` + `/messages` 분리 경로 → legacy HTTP+SSE
- `/mcp/v1`, `/mcp/v1/initialize`, `/mcp/v1/tools/list` 분리 경로 → 자체 변형
- 세션 ID를 헤더가 아니라 쿼리/바디로 전달 → 비표준

---

## 7. 알려진 합격 / 불합격 사례 (이 프로젝트)

| 서버 | 합격? | 비고 |
|---|---|---|
| `mcp_outlook` (`server_stream.py`) | ✅ 8/8 통과 | `StreamableHTTPSessionManager` + Starlette `Route("/mcp", ...)` + uvicorn. 표준 구현의 모범. |
| `mcp_calendar` (`server_stream.py`, **legacy**) | ❌ Probe 1 즉시 실패 (POST `/mcp` → 405) | 자체 aiohttp에 `/mcp/v1` 마운트, NDJSON chunked, session-id 미사용. 마이그레이션 필요. |

마이그레이션 완료 시 이 표를 업데이트할 것. 새 서버가 추가되면 같은 형식으로 1줄 추가.

---

## 8. 빠른 자동화 (스크립트 1개로 8개 probe 일괄)

`.claude/skills/setup_ms365/scripts/`에 `streamable_http_probe.sh`(또는 `.py`) 추가를 권장. 인자로 `SERVER_BASE`(예: `http://localhost:5001`)를 받고 8개 probe를 차례로 돌려 표 형태로 합/불 출력. 본 체크리스트의 curl 블록을 그대로 옮기면 됨.

(현재는 수동 — 위 명령들을 복붙해서 사용)
