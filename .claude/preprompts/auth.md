# 인증 시스템 개요

**Microsoft Azure AD OAuth 2.0** 기반 다중 사용자 인증 및 토큰 관리 시스템.

---

## 핵심 아키텍처

```
AuthManager (중앙 관리)
    ├── AuthService (OAuth 플로우)
    ├── AuthDatabase (토큰/사용자 저장)
    └── CallbackServer (OAuth 콜백 처리)
```

---

## 주요 컴포넌트

### AuthManager (`session/auth_manager.py`)
```python
class AuthManager:
    async def authenticate_with_browser(timeout=300)  # 브라우저 인증
    async def validate_and_refresh_token(email)       # 토큰 검증/갱신
    async def get_token(email)                        # 토큰 조회
    def list_users()                                  # 사용자 목록
```

### AuthService (`session/auth_service.py`)
```python
class AuthService:
    def start_auth_flow()                     # 인증 URL 생성
    async def complete_auth_flow(code, state) # code → token 교환
    async def refresh_tokens(refresh_token)   # 토큰 갱신
    def is_token_expired(expires_at)          # 만료 확인 (5분 버퍼)
```

### AuthDatabase (`session/auth_database.py`)
```python
class AuthDatabase:
    def save_token(email, token_info)
    def get_token(email)
    def update_token(email, new_tokens)
```

---

## TokenProviderProtocol (의존성 주입)

### Protocol 정의 (`core/protocols.py`)
```python
@runtime_checkable
class TokenProviderProtocol(Protocol):
    """토큰 제공자 추상화 - AuthManager를 교체 가능하게 함"""

    async def validate_and_refresh_token(self, user_email: str) -> Optional[str]:
        """유효한 액세스 토큰 반환 (필요시 자동 갱신)"""
        ...

    async def get_token(self, email: str) -> Optional[Dict[str, Any]]:
        """전체 토큰 정보 조회"""
        ...

    async def close(self) -> None:
        """리소스 정리"""
        ...
```

### Protocol 사용 패턴
```python
class GraphMailQuery:
    def __init__(self, token_provider: Optional["TokenProviderProtocol"] = None):
        if token_provider is None:
            from session.auth_manager import AuthManager
            token_provider = AuthManager()
        self.token_provider = token_provider

    async def _get_access_token(self, user_email: str) -> Optional[str]:
        # Protocol 메서드 호출 - 구현체가 뭔지 신경 쓰지 않음
        return await self.token_provider.validate_and_refresh_token(user_email)
```

**이점**: 테스트 시 Mock 주입, 느슨한 결합, 다른 인증 방식 쉽게 추가

---

## OAuth 2.0 인증 플로우

### 1단계: 인증 URL 생성
```python
params = {
    'client_id': self.config.azure_client_id,
    'response_type': 'code',
    'redirect_uri': 'http://localhost:5000/callback',
    'scope': 'User.Read Mail.Read offline_access',
    'state': state  # CSRF 방지
}
auth_url = f"{authorize_endpoint}?{urlencode(params)}"
```

### 2단계: Code → Token 교환
```python
async def complete_auth_flow(self, code: str, state: str):
    token_result = await self._exchange_code_for_tokens(code)
    user_info = await self._get_user_info(token_result['access_token'])
    self.auth_db.save_token(user_info['mail'], token_result)
    return {'access_token': ..., 'refresh_token': ..., 'user_email': ...}
```

### 3단계: 콜백 처리
```python
# CallbackServer가 /callback 엔드포인트에서 code 수신 후 complete_auth_flow 호출
```

---

## 토큰 관리

### 토큰 구조
```python
token_info = {
    'access_token': str,       # Graph API 호출용 (1시간 유효)
    'refresh_token': str,      # 토큰 갱신용 (90일 유효)
    'expires_at': datetime,    # access_token 만료 시간
    'scope': str,
    'id_token': str
}
```

### 토큰 만료 확인 (5분 버퍼)
```python
def is_token_expired(self, expires_at, buffer_seconds=300):
    buffer = timedelta(seconds=buffer_seconds)
    return datetime.now(timezone.utc) >= (expires_at - buffer)
```

### 자동 토큰 갱신
```python
async def validate_and_refresh_token(self, email: str) -> Optional[str]:
    token_info = self.auth_db.get_token(email)

    if not self.is_token_expired(token_info['expires_at']):
        return token_info['access_token']  # 유효한 토큰

    if not token_info.get('refresh_token'):
        return None  # 재인증 필요

    # Refresh token으로 새 access token 획득
    new_tokens = await self.refresh_tokens(token_info['refresh_token'])
    self.auth_db.update_token(email, new_tokens)
    return new_tokens['access_token']
```

### Refresh Token 갱신
```python
async def refresh_tokens(self, refresh_token: str):
    data = {
        'client_id': self.config.azure_client_id,
        'client_secret': self.config.azure_client_secret,
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token'
    }
    response = await session.post(token_endpoint, data=data)
    return await response.json()
```

---

## Microsoft Graph API 호출

```python
access_token = await self.token_provider.validate_and_refresh_token(email)
headers = {'Authorization': f'Bearer {access_token}'}
response = await session.get("https://graph.microsoft.com/v1.0/me/messages", headers=headers)
```

### 기본 권한 (Scopes)
```python
scopes = ["User.Read", "Mail.Read", "Mail.Send", "Calendars.Read", "offline_access"]
```

---

## 데이터베이스 스키마

```sql
-- 토큰 정보
CREATE TABLE azure_token_info (
    user_email TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    access_token_expires_at TIMESTAMP NOT NULL,
    refresh_token_expires_at TIMESTAMP,
    scope TEXT, id_token TEXT,
    created_at TIMESTAMP, updated_at TIMESTAMP
);

-- 사용자 정보
CREATE TABLE azure_user_info (
    user_email TEXT PRIMARY KEY,
    object_id TEXT UNIQUE,
    display_name TEXT,
    created_at TIMESTAMP, updated_at TIMESTAMP
);
```

---

## 사용 예시

### 브라우저 인증
```python
from session.auth_manager import AuthManager
auth = AuthManager()
result = await auth.authenticate_with_browser(timeout=300)
print(f"인증된 사용자: {result['email']}")
```

### Protocol로 토큰 획득
```python
access_token = await auth.validate_and_refresh_token("user@example.com")
headers = {'Authorization': f'Bearer {access_token}'}
response = await session.get("https://graph.microsoft.com/v1.0/me", headers=headers)
```

### 다중 사용자 관리
```python
for user in auth.list_users():
    print(f"{user['email']}: expired={user['token_expired']}")
```

---

## 보안 요약

| 항목 | 구현 |
|------|------|
| CSRF 방지 | state 파라미터 검증 |
| Access Token | 1시간, 5분 전 자동 갱신 |
| Refresh Token | 90일 |
| offline_access | 필수 (refresh token 획득) |

---

## 파일 위치

```
session/
├── auth_manager.py      # 인증 오케스트레이션
├── auth_service.py      # OAuth 플로우
├── auth_database.py     # 토큰/사용자 DB
├── azure_config.py      # Azure AD 설정
├── callback_server.py   # OAuth 콜백
└── session_manager.py   # 세션 관리

core/
└── protocols.py         # TokenProviderProtocol 정의
```
