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
