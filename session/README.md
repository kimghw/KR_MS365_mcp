# Session - Azure AD OAuth 2.0 인증 모듈

Azure AD OAuth 2.0 인증 및 토큰 관리를 담당하는 모듈입니다.

## 구조

```
session/
├── __init__.py          # 모듈 export (AuthManager, AuthService, AzureConfig, AuthDatabase)
├── auth_manager.py      # 인증 오케스트레이터 (다중 사용자 관리, 토큰 자동 갱신, 직접 실행 가능)
├── auth_service.py      # OAuth 2.0 플로우 (URL 생성, 토큰 교환, 갱신)
├── auth_database.py     # SQLite CRUD (토큰, 사용자, 앱 설정 저장)
└── azure_config.py      # Azure AD 설정 관리 (환경변수/DB 로드)
```

## 실행 방법

```bash
# auth_manager.py 직접 실행
python -m session.auth_manager

# 기존 사용자가 있으면 메뉴 표시:
#   [1] Refresh token   → 토큰 갱신 (실패 시 브라우저 재인증)
#   [2] New auth        → 새 계정 브라우저 인증
#   [3] Exit
# 기존 사용자가 없으면 바로 브라우저 인증 시작
```

## 인증 흐름

```
1. auth_manager.py 실행 (또는 main.py)
2. authenticate_with_browser() → 콜백 서버 시작 (port 5000)
3. 브라우저에서 Azure AD 로그인
4. localhost:5000/callback 으로 authorization code 수신
5. code → access_token + refresh_token 교환
6. database/auth.db 에 토큰 저장
```

## 토큰 자동 갱신

`validate_and_refresh_token(email, auto_reauth=False)` 호출 시:

```
토큰 유효 → access_token 반환
토큰 만료 → refresh_token으로 자동 갱신 → 새 access_token 반환
갱신 실패 → auto_reauth=True  → 브라우저 재인증 자동 시작
           auto_reauth=False → None 반환 (기본값)
```

- access_token: ~1시간 유효, 만료 5분 전 자동 갱신
- refresh_token: 90일 유효

## 주요 메서드 (AuthManager)

| 메서드 | 설명 |
|--------|------|
| `authenticate_with_browser()` | 브라우저 OAuth 인증 시작 |
| `validate_and_refresh_token(email, auto_reauth)` | 토큰 검증 + 자동 갱신 (auto_reauth=True 시 재인증) |
| `refresh_token(email)` | refresh_token으로 갱신 |
| `get_token(email)` | 토큰 정보 조회 |
| `get_token_status(email)` | 토큰 상태 조회 |
| `list_users()` | 인증된 사용자 목록 |
| `remove_user(email)` | 사용자 제거 |
| `cleanup_expired_tokens()` | 만료 토큰 정리 |

## 필수 환경변수 (.env)

> **참고:** `azure_config.py`는 모듈 로드 시 `load_dotenv()`를 호출하여 프로젝트 루트의 `.env` 파일을 자동으로 읽습니다.

```env
# 필수
AZURE_CLIENT_ID=<Azure AD 앱 클라이언트 ID>
AZURE_CLIENT_SECRET=<Azure AD 앱 클라이언트 시크릿>
AZURE_TENANT_ID=<테넌트 ID>
AZURE_REDIRECT_URI=<리다이렉트 URI>

# 선택 (기본값 있음)
AZURE_SCOPES=<스코프>                                 # 기본값: User.Read Mail.Read Mail.Send offline_access
DB_PATH=<DB 파일 경로>                                # 기본값: database/auth.db
```

## 외부 연동

`mcp_outlook` 등 외부 모듈은 `TokenProviderProtocol`을 통해 AuthManager에 토큰을 요청합니다:

```python
from session import AuthManager

auth_manager = AuthManager()
# 기본: refresh 실패 시 None 반환
access_token = await auth_manager.validate_and_refresh_token("user@example.com")
# auto_reauth=True: refresh 실패 시 브라우저 재인증 자동 시작
access_token = await auth_manager.validate_and_refresh_token("user@example.com", auto_reauth=True)
```
