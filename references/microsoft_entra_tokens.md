# Microsoft Entra ID (Azure AD) 토큰 수명

## refresh token
- v2.0 엔드포인트의 refresh token 은 **비활성 90일** 이 기본 수명이며, 갱신에 성공할 때마다
  **새 refresh token 이 발급되고 90일 창이 다시 시작**된다(sliding window). 즉 꾸준히 쓰면
  최초 인증일과 무관하게 계속 살아 있다.
- 따라서 클라이언트가 "최초 인증일 + 90일" 을 고정 만료로 저장하고 그 뒤 갱신 시도 자체를
  막으면, 실제로는 유효한 토큰을 버리고 불필요한 재인증을 강요하게 된다. 만료 시각을
  저장하려면 **새 refresh token 을 받을 때마다 다시 계산**해야 한다.
- 조직 정책(Conditional Access, 비밀번호 변경, 세션 취소)으로 조기 폐기될 수 있으므로,
  로컬 만료 계산과 별개로 토큰 서버의 `invalid_grant` 응답을 재인증 신호로 다뤄야 한다.
- https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens

## ID token 서명 검증과 JWKS
- OIDC Core 3.1.3.7: authorization code 를 **토큰 엔드포인트와 직접(TLS) 교환해 받은** ID token 은
  TLS 서버 검증으로 발급자 확인을 대신할 수 있어 서명 검증이 선택(MAY)이다. 그래도 JWKS 로 서명을
  검증하는 것은 허용되며(심층 방어), `iss`·`aud`·`exp`·`nonce` 검사는 어느 쪽이든 해야 한다.
- Entra v2.0 서명 키(JWKS): `https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys`
  (`{tenant}` 는 tenant ID 또는 `organizations`/`common`). 메타데이터는
  `https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration` 의 `jwks_uri`.
- 다중 tenant(`organizations`/`common`) 메타데이터의 issuer 는 `{tenantid}` 자리표시자를 담는다 —
  토큰의 `iss` 는 `https://login.microsoftonline.com/<tid>/v2.0` 이므로 `tid` 클레임으로 바꿔 비교한다.
- 키는 주기적으로 교체되므로 헤더의 `kid` 로 고르고, 모르는 `kid` 면 JWKS 를 다시 받는다.
- https://openid.net/specs/openid-connect-core-1_0.html#IDTokenValidation
- https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference
