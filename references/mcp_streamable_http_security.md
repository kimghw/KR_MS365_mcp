# MCP Streamable HTTP — 보안 요구사항

## DNS rebinding 방어 (스펙 MUST)
- 로컬에서 도는 HTTP MCP 서버는 **`Origin` 헤더를 검증해야 한다**. 브라우저에서 열린 악성
  페이지가 `localhost:포트` 로 요청을 보내면 쿠키 없는 로컬 서버라도 그대로 응답하기 때문이다.
  `Host` 헤더도 허용 목록으로 묶어 리바인딩된 호스트명을 막는다.
- 로컬 전용이면 loopback(`127.0.0.1`/`localhost`) 바인드 + 위 헤더 검증, 외부 노출이면
  추가로 호출자 인증이 필요하다.
- https://modelcontextprotocol.io/specification/2025-11-25/basic/transports

## Python SDK 지원 (`mcp>=1.10`)
- `mcp.server.transport_security.TransportSecuritySettings(enable_dns_rebinding_protection,
  allowed_hosts, allowed_origins)` 를 `StreamableHTTPSessionManager(security_settings=...)`
  로 넘기면 SDK 가 `/mcp` 요청마다 검사한다. 값은 정확 일치 또는 `host:*` 포트 와일드카드.
- 실패 응답: Host 불일치 **421**, Origin 불일치 **403**, POST 의 Content-Type 이
  `application/json` 이 아니면 400.
- `settings=None` 이면 하위 호환을 위해 **기본 비활성** 이다 — 명시적으로 켜야 한다.
- 주의: HTTP/1.1 클라이언트는 Host 에 항상 포트를 붙이므로 허용 목록은 `localhost:*` 형식으로
  적는다. 비브라우저 클라이언트(Claude Code 등)는 Origin 을 보내지 않으며, 없는 Origin 은 통과한다.

## stateless 모드와 요청 ContextVar (Python SDK 1.30 확인)
- `StreamableHTTPSessionManager(stateless=True)` 는 요청마다 새 트랜스포트·서버를 만들되, 그 서버를
  **session manager 자신의 task group 안에서** 돌린다. ASGI 미들웨어가 요청 처리 중에 설정한
  `ContextVar` 는 도구 핸들러로 **전파되지 않는다**(태스크가 미들웨어의 컨텍스트에서 파생되지 않음).
- SDK 는 HTTP 요청을 메시지 metadata 로 넘기고 lowlevel `request_ctx` 의 `RequestContext.request` 에
  Starlette `Request` 를 싣는다. 요청별 값(인증 결과 등)은 미들웨어가 ASGI `scope["state"]` 에 넣고,
  핸들러 시점에 `request_ctx.get().request.scope["state"]` 에서 읽어 다시 bind 해야 한다.
  (구현 예: 이 저장소 `mcp_common/mcp_identity_bridge.py`)
- stateless 에서는 `Mcp-Session-Id` 를 발급하지 않는다. 세션 기반 GET 스트림·DELETE 종료는 의미가 없다.
