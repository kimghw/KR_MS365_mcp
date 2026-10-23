# Session - Azure AD OAuth 2.0 인증 모듈

Azure AD OAuth 2.0 인증 및 토큰 관리를 담당하는 모듈입니다.

- **mode 0 (단일 운영자, 기본)**: 아래 `AuthManager`·`callback_server.py` 흐름. 공용 `database/auth.db`.
- **mode 1 (멀티유저, `MS365_MULTI_USER=1`)**: [멀티유저 모드](#멀티유저-모드-ms365_multi_user1) 절.
  사용자별 암호화 토큰 DB·bearer key·중앙 OAuth 연결 서비스. 이 모드에서는 legacy 클래스
  (`AuthManager`·`AuthDatabase()`·`AuthService`·`AzureConfig`·`CallbackServer`·`session_manager`)
  생성이 `LegacyAuthDisabledError` 로 거부된다. 설계 원본: [spec_멀티유저.md](../spec/spec_멀티유저.md) ②-4·②-6.

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

- 콜백 서버(`callback_server.py`)는 쿼리 문자열(code 포함)·state·토큰·이메일을 로그에 남기지 않는다.
- 인증 대기는 **state 별**이다(`expect(state)` → `wait_for_auth(timeout, state=...)`). 공용 Event 가
  없으므로 알 수 없는 state·다른 인증의 오류 콜백·토큰 교환 실패가 진행 중인 다른 인증을 깨우거나
  중단시키지 못한다. `error` 콜백도 성공 경로와 같은 TTL·1회 소비(`AuthService.consume_state`)를 따른다.
- `_auto_reauth(email)` 는 브라우저에서 **다른 계정으로 로그인하면 그 토큰을 돌려주지 않는다**.
- `complete_auth_flow()` 결과에는 토큰이 없다(토큰은 DB 에만 저장).

## 토큰 자동 갱신

`validate_and_refresh_token(email, auto_reauth=False)` 호출 시:

```
토큰 유효 → access_token 반환
토큰 만료 → refresh_token으로 자동 갱신 → 새 access_token 반환
갱신 실패 → auto_reauth=True  → 브라우저 재인증 자동 시작
           auto_reauth=False → None 반환 (기본값)
```

- access_token: ~1시간 유효, 만료 5분 전 자동 갱신
- refresh_token: 90일 유효. 저장된 `refresh_token_expires_at` 은 **새 refresh_token 이 저장될 때마다
  +90일로 밀린다**(Azure sliding window) — 최초 인증 시각 +90일로 고정되는 것이 아니다.

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

## 멀티유저 모드 (`MS365_MULTI_USER=1`)

### 구성

```
session/
├── identity_registry.py  # 관문: authenticate_bearer / assert_active + 관리 함수 재수출
├── registry_admin.py     # 사용자 등록·키 발급/회전/폐기·상태·연결 해제·삭제 (위성)
├── _registry_db.py       # system/registry.db 커널 (users·kid 인덱스·state/ticket 인덱스·tombstone)
├── user_auth_store.py    # users/<user_key>/auth/auth.db (store_owner·graph_tokens·api_credentials·oauth_attempts)
├── user_crypto.py        # 사용자별 DEK(wrapped_dek.json) + AES-256-GCM 레코드 암호화(AAD 바인딩)
├── key_provider.py       # KEK provider: azure_keyvault | dpapi | env(개발) | memory(테스트)
├── token_store.py        # get_graph_access_token() 단일 refresh 진입점 + BoundGraphTokenProvider
├── file_lock.py          # 프로세스 간 OS 파일 lock (msvcrt / fcntl, 30초)
├── app_settings.py       # Entra 앱 설정 — 환경변수 전용, client secret 비저장
├── entra_client.py       # 토큰 교환·갱신, Graph /me, ID token 검증(JWKS·iss·aud·nonce·tenant)
├── graph_connect.py      # 연결 시도 수명: 시작(ticket) → 브라우저 바인딩(PKCE·nonce·쿠키) → 콜백
├── auth_gateway.py       # Starlette 중앙 연결 서비스 (python -m session.auth_gateway)
├── admin_cli.py          # 관리 CLI (python -m session.admin_cli)
└── mode_guard.py         # legacy 경로 차단 (LegacyAuthDisabledError)
```

### 운영 절차

```bash
# 1) 환경 (예시) — 비밀은 셸 기록이 아닌 서비스 환경/secret 파일로 주입
MS365_MULTI_USER=1
MS365_DATA_ROOT=D:/ms365-data            # 절대경로
MS365_KEK_PROVIDER=dpapi                 # 또는 azure_keyvault(+MS365_KEK_KEY_ID), env(개발 전용)
MS365_ALLOWED_TENANTS=<tenant-uuid>
AZURE_CLIENT_ID=... AZURE_TENANT_ID=<tenant-uuid> AZURE_REDIRECT_URI=https://mcp.example.com/auth/callback
AZURE_CLIENT_SECRET_FILE=/run/secrets/m365   # 또는 AZURE_CLIENT_SECRET

# 2) 초기화·사용자 등록·키 발급 (키 원문은 한 번만 출력된다)
python -m session.admin_cli init
python -m session.admin_cli user add --tenant <tid> --oid <oid>
python -m session.admin_cli key issue <user_key> --domains outlook calendar --days 30

# 3) 중앙 연결 서비스 (AZURE_REDIRECT_URI 포트 또는 MS365_AUTH_GATEWAY_PORT)
python -m session.auth_gateway
```

사용자는 bearer key 로 `POST /auth/graph/start` 를 부르거나, MCP 도구가 돌려준 `connect_url`
(1회용, 300초)을 **같은 브라우저**에서 연다. 등록된 `(tid, oid)` 와 다른 계정으로 로그인하면 저장하지
않고 거부한다.

### 공개 API (다른 WP 가 쓰는 계약)

| 함수 | 용도 |
|------|------|
| `await identity_registry.authenticate_bearer(header, *, domain)` | `Bearer m365v1.<kid>.<secret>` → `Principal` (`unauthenticated`/`forbidden_scope`/`account_inactive`). `domain=None` 은 gateway 전용 |
| `await identity_registry.assert_active(principal)` | 계정 usable(active·pending_link)·auth_epoch·키 미폐기 재확인 |
| `await token_store.get_graph_access_token(principal, minimum_ttl_seconds=120)` | `AccessToken`. 미연결 `graph_not_connected`, 재인증 `graph_reauth_required`, lock 초과 `overloaded` |
| `mcp_common.auth.get_bound_token_provider(principal)` | `BoundTokenProvider` (`close()` no-op, email 은 일치 확인만) |
| `mcp_common.auth.graph_connect_details(principal)` | `{"connect_url", "expires_in": 300}` — 미연결 오류에 붙이는 연결 안내 |
| `app_settings.auth_startup_problems()` | 앱 설정·KEK 기동 점검 (문제 목록) |

### 보안 성질

- 토큰·PKCE verifier 는 SQL 에 들어가기 전에 사용자 DEK 로 AES-256-GCM 암호화된다. AAD 에
  배포 ID·user_key·app_id·종류·버전이 들어가 다른 사용자 DB 로 복사한 ciphertext 는 풀리지 않는다.
- bearer key 는 digest(SHA-256, 배포 ID 로 도메인 분리)만 저장, 사용자당 활성 키 최대 2개.
- refresh 는 `(user_key, app_id)` 단위 프로세스 내 lock + OS 파일 lock 아래에서 재조회·버전 조건부
  저장. 갱신 도중 비활성·연결 해제·삭제되면 결과를 저장하지 않는다.
- 토큰을 돌려주기 직전에 **현재 요청**(`current_identity()`)의 키·만료·계정·epoch 를 재검사한다 —
  풀 슬롯을 기다리는 사이 폐기된 키의 요청은 새 Graph 호출을 하지 못한다. 공급자에 묶인 첫 lease 키는
  보지 않으므로 같은 사용자의 다른 유효 키는 계속 동작한다.
- OAuth 연결 확정은 같은 lock 아래에서 epoch 재검사 → 토큰 저장 → registry `active` 를 한 단위로 한다.
  같은 사용자의 동시 완료는 한 건만 확정되고 다른 건은 토큰을 건드리지 않는다. 되돌림은 버전 조건부
  단일 DELETE 다. 연결 해제도 같은 lock 을 epoch 를 올리기 전에 잡고 그 안에서 epoch 증가 → 버전 조건부
  DELETE 를 하므로, 확정·갱신·해제가 어떤 순서로 겹쳐도 (active+토큰) 또는 (pending_link+토큰 없음) 이다.
  갱신이 lock 을 쥐고 있으면 해제는 그 갱신이 끝날 때까지 기다린다.
- 연결 시도 생성(정리·3개 상한·삽입)은 사용자 lock 아래 한 단위다 — 병렬 start 로 상한을 넘길 수 없다.
- OAuth 시도는 사용자 DB 의 행 하나 — state(256비트)·쿠키·nonce 는 해시, verifier 는 암호화.
  잘못된 state·오류 콜백은 그 시도만 실패시킨다. `pending → redeeming` 전환을 한 요청만 성공한다.
- 로그·응답에 토큰·키·state·ticket·이메일·외부 오류 본문을 남기지 않는다(감사는 `mcp_common.audit`).

### 한계

- **계정 삭제의 drain 은 삭제를 실행하는 프로세스의 서비스 풀에 한정**된다. `delete_user` 는 `deleting` +
  epoch 증가로 새 요청을 막은 뒤 이 프로세스 풀의 `drain()`(없으면 `invalidate()`)을 기다리고 나서
  배타 lock·삭제로 넘어간다. 관리 CLI 는 별도 프로세스이므로 **다른 도메인 프로세스에서 이미 실행 중인
  작업은 끝내지 못한다** — 그 작업은 토큰 획득·외부 호출·저장·응답 전의 epoch·상태 재검사로 막힐 뿐이다.
  프로세스 간 drain(admission 계약)은 사양 ④ 미결이다.

