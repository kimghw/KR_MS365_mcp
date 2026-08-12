# 환경변수 레퍼런스

KR_MS365_mcp 서버들이 읽는 환경변수를 정리한다.
값은 프로젝트 루트의 `.env` 파일 또는 프로세스 환경에서 읽는다
(`.env` 는 저장소에 커밋하지 않는다. 템플릿은 `.env.example` 참조).

---

## 1. 보안 관련 변경 요약 (필독)

**기본 바인드 주소가 `0.0.0.0` 에서 `127.0.0.1`(loopback) 로 바뀌었다.**

이전에는 HTTP/stream 서버들이 기본으로 모든 인터페이스에 열려 있었다.
**MCP 서버에는 호출자 인증(caller authentication) 계층이 전혀 없다.**
포트에 도달할 수 있는 사람은 누구나 인증 없이 도구를 호출해
사용자의 메일·일정·OneDrive 파일·OneNote 노트를 읽고 쓸 수 있다.

따라서 기본값을 loopback 으로 바꿔, 별도 조치가 없으면 **같은 PC 에서만** 접근 가능하다.

기존에 다른 PC 에서 붙여 쓰고 있었다면 업그레이드 후 연결이 끊긴다.
아래 "외부 접속 옵트인" 절차를 따라야 한다.

---

## 2. 네트워크 바인드

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `MCP_BIND_HOST` | `127.0.0.1` | 서버가 바인드할 호스트/IP |
| `MCP_ALLOW_PUBLIC_BIND` | (없음 = 꺼짐) | 외부 노출 주소 바인드를 허용하는 옵트인 스위치 |
| `MCP_SERVER_PORT` | 서버마다 다름 (outlook 5001 등) | 서버가 listen 할 포트 |

구현: `mcp_common/net.py` 의 `resolve_bind_host()`.

### 결정 순서

1. 코드에서 명시적으로 넘긴 인자
2. `MCP_BIND_HOST` 환경변수
3. `127.0.0.1`

### 안전장치

`0.0.0.0`, `::`, `*`, 또는 loopback 이 아닌 IP 를 요청했는데
`MCP_ALLOW_PUBLIC_BIND` 가 켜져 있지 않으면 **경고를 남기고 `127.0.0.1` 로 강등**한다.
즉 `MCP_BIND_HOST` 하나만 바꿔서는 외부에 열리지 않는다. 두 개를 모두 설정해야 한다.

`MCP_ALLOW_PUBLIC_BIND` 가 참으로 인정하는 값: `1`, `true`, `yes`, `on` (대소문자 무관).

### 외부 접속 옵트인 절차

```bash
# .env 또는 프로세스 환경
MCP_BIND_HOST=0.0.0.0
MCP_ALLOW_PUBLIC_BIND=1
```

> **경고 — 반드시 방화벽으로 막을 것**
>
> MCP 서버에는 호출자 인증이 없다. 토큰도, 비밀번호도, 클라이언트 인증서도 없다.
> `MCP_ALLOW_PUBLIC_BIND=1` 로 열면 해당 포트에 TCP 로 도달 가능한 모든 호스트가
> 인증 없이 당신의 MS365 계정 데이터를 읽고 쓸 수 있다.
>
> 외부 노출이 꼭 필요하다면 다음 중 하나를 **반드시** 병행하라.
>
> 1. **Windows 방화벽에서 출발지 IP 를 제한**한다 (가장 기본).
>    ```powershell
>    New-NetFirewallRule -DisplayName "MCP outlook (제한)" `
>      -Direction Inbound -Protocol TCP -LocalPort 5001 `
>      -RemoteAddress 192.168.0.0/24 -Action Allow
>    ```
>    필요한 포트에 대해 각각 등록하고, 그 외 출발지는 차단(Block)한다.
> 2. 특정 인터페이스에만 바인드한다. `MCP_BIND_HOST=0.0.0.0` 대신
>    `MCP_BIND_HOST=192.168.0.10` 처럼 내부망 IP 를 직접 지정한다.
>    (이 경우에도 loopback 이 아니므로 `MCP_ALLOW_PUBLIC_BIND=1` 이 필요하다.)
> 3. 서버를 loopback 에 둔 채 **SSH 터널 / WireGuard 같은 인증된 터널**로만 노출한다.
>    이 방법이 가장 안전하며, `MCP_ALLOW_PUBLIC_BIND` 자체가 필요 없다.
>
> 공인 IP 에 직접 노출하는 것은 어떤 경우에도 권장하지 않는다.

---

## 3. 파일 접근 허용 경로

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `MCP_ALLOWED_PATHS` | (없음) | 파일 읽기/쓰기를 허용할 루트 목록. `os.pathsep` 구분 (Windows `;`, Linux/macOS `:`) |
| `MCP_DATA_DIR` | (없음) | 기본 허용 루트에 추가로 붙일 데이터 디렉터리 |

구현: `mcp_common/paths.py` 의 `resolve_safe_path()`, `allowed_roots()`.

`mcp_file_handler` 와 에디터는 호출자가 준 임의 경로를 열거나 만든다.
네트워크에 노출된 서버에서 이는 곧바로 로컬 파일 유출/생성 경로가 되므로,
허용 루트 밖의 경로는 `PathNotAllowedError` 로 거부한다.

- `MCP_ALLOWED_PATHS` 가 설정돼 있으면 그 목록만 허용한다.
- 설정돼 있지 않으면 **프로젝트 루트** + (설정된 경우) `MCP_DATA_DIR` 이 허용 루트가 된다.
- 심볼릭 링크와 `..` 는 realpath 로 해소한 뒤 비교하므로
  path traversal 로 우회할 수 없다.

Windows 예시 (경로 구분자는 세미콜론):

```
MCP_ALLOWED_PATHS=E:\dev\KR_MS365_mcp\downloads;E:\dev\KR_MS365_mcp\output
```

허용 범위는 **필요한 만큼만** 좁게 잡아라. `C:\` 나 사용자 홈 전체를 넣으면
경로 허용 목록의 의미가 사라진다.

---

## 4. 입력 검증

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `MCP_VALIDATE_INPUT` | (없음 = 켜짐) | `0`/`false`/`no`/`off` 로 두면 도구 입력 스키마 검증을 끈다 |

구현: `mcp_common/validation.py` 의 `validation_enabled()`, `validate_arguments()`.

stream 서버들이 `@server.call_tool(validate_input=False)` 로 검증을 꺼둔 탓에
"스키마상 optional 인데 핸들러는 필수" 같은 계약 불일치가 런타임 `KeyError` 로만
드러나던 문제를 잡기 위해 공통 런타임에서 검증한다.
`required` / `type` / `enum` / 중첩 object / array items 를 확인한다.

**정상 운영 중에는 끄지 마라.** 긴급 우회용이다.
껐다면 잘못된 인자가 검증 없이 핸들러까지 내려가 원인 파악이 어려운 오류를 낸다.

---

## 5. 기본 사용자

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `MS365_DEFAULT_USER_EMAIL` | (없음) | 도구 호출에 이메일 인자가 없을 때 사용할 기본 사용자 |

구현: `mcp_common/user_resolver.py` 의 `UserResolver.default_email()`.

결정 순서:

1. 요청 인자로 명시된 이메일
2. `MS365_DEFAULT_USER_EMAIL`
3. `auth.db` 에서 결정적(deterministic) 선택
   — 유효 토큰 보유자 우선, 그 다음 이메일 사전순
4. 사용자가 하나도 없으면 `None`

이전에는 일부 서버가 YAML 스키마의 `default` 에 특정 이메일을 박아두어
**공개 도구 스키마에 개인 주소가 노출**됐고, 다른 서버는 `auth.db` 를
`updated_at DESC` 로 정렬해 첫 사용자를 골라서 **토큰이 갱신될 때마다
대상 사용자가 조용히 바뀌는** 문제가 있었다. 위 순서는 그 두 가지를 모두 없앤다.

---

## 6. Azure AD OAuth

| 변수 | 필수 | 설명 |
|------|------|------|
| `AZURE_CLIENT_ID` | O | 앱 등록 클라이언트 ID |
| `AZURE_CLIENT_SECRET` | O | 클라이언트 시크릿 |
| `AZURE_TENANT_ID` | O | 테넌트 ID |
| `AZURE_REDIRECT_URI` | O | OAuth 콜백 URL (기본 `http://localhost:5000/callback`) |
| `AZURE_AUTHORITY` | X | 기본 `https://login.microsoftonline.com` |
| `AZURE_SCOPES` | X | 공백 구분. `offline_access` 가 없으면 refresh_token 이 발급되지 않는다 |

`AZURE_REDIRECT_URI` 의 호스트는 loopback(`localhost`)으로 두는 것이 좋다.
콜백 서버까지 외부에 열 이유는 없다.

---

## 7. 기타

| 변수 | 설명 |
|------|------|
| `MCP_YAML_PATH` | 도구 정의 YAML 경로 직접 지정. 미설정 시 `<project_root>/mcp_editor/mcp_<서버>/tool_definition_templates.yaml` |

---

## 8. 안전한 기본 설정 예시

로컬 개발/단일 PC 사용 (권장):

```bash
# 바인드 관련 변수를 아무것도 설정하지 않으면 127.0.0.1 로 뜬다 — 이게 안전한 기본값이다.
AZURE_CLIENT_ID=...
AZURE_CLIENT_SECRET=...
AZURE_TENANT_ID=...
AZURE_REDIRECT_URI=http://localhost:5000/callback
```

내부망 공유가 꼭 필요한 경우:

```bash
MCP_BIND_HOST=192.168.0.10       # 0.0.0.0 대신 특정 인터페이스
MCP_ALLOW_PUBLIC_BIND=1          # 옵트인 (없으면 loopback 으로 강등됨)
MCP_ALLOWED_PATHS=E:\dev\KR_MS365_mcp\downloads
# + Windows 방화벽에서 출발지 IP 를 반드시 제한할 것
```
