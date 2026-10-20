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
