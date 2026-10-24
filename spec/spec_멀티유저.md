# spec_멀티유저

## ① 질의·요청 히스토리

| 날짜 | 질의·요청 원문 요지 |
|---|---|
| 2026-10-22 | 현재 단일 운영자 방식의 MS365 MCP 서버를 멀티유저 방식으로 변경하고, 사용자별 데이터·인증정보를 완전히 분리하며, 여러 코드 에이전트가 병렬 구현할 수 있는 설계와 작업 계약을 작성한다. |
| 2026-10-22 | (사용자) "결과 나오면 astra 한테 재검토 해줘" → 구현·통합 검증 완료 후 astra 재검토 실행(2026-10-23). 판정 "출시 불가(High 2: R01 폐기 키 대기 요청, R02 `top` 무제한)" → R01~R15 전부 반영(③). |
| 2026-10-22 | (구현 후) "approvalinprocedure 웹서버에서 최초 로그인 시 로그인하고, 사용자는 이 정보로 MCP 서버를 사용하고, 그 서버에서도 로그인 정보로 특정 프로젝트에 접근한다. AIP 접수 시 담당자가 되고 중간에 넘길 수도 있다. 그쪽 세션과 대화해서 처리" → AIP 세션(`E:\dev\ApprovalInPrinciple`)에 연동 계약 초안·확인 질문 5개 송부(④ AIP 연동). AIP 는 현재 `currentuser.py` 원천 1 로 이 저장소 `auth.db` 기본 사용자를 읽으므로 mode 1 에서 대체 경로가 필요. |
| 2026-10-23 | (AIP 세션 검토 결과, 사용자 "MS365 mcp 서버 수정이 필요하면 별도 서브세션으로 처리") **책임 분리 합의**: Microsoft 로그인·동의, 토큰 교환·저장·갱신·재인증·연결 해제는 **이 저장소**가, AIP 는 신원과 '어느 계정으로'만 든다(AIP 쪽 요구 원본 `spec_웹로그인.md` ② 'MS365 인증 책임 분리'). 요구 계약 5항 — ⑴ 로그인 위임(인가 코드 제출 → 등록·토큰 보관 → 신원+연결 상태) ⑵ 연결 상태 조회(4상태 + 기능별 권한) ⑶ 재연결/해제 ⑷ 업무 호출은 사용자 신원으로 ⑸ 인증 오류 분류(재인증 vs 일시 장애). 이 PC 의 AIP 는 당분간 mode 0(auth.db, 이메일 키)로 이 라이브러리를 subprocess 로 쓰므로 **1차 = mode 0 라이브러리 계약**(② 13 — `AuthManager.complete_external_login`·`connection_state`·`reason` 코드, 같은 날 구현 ③), mode 1 gateway `POST /auth/token` 은 후속(④). |
| 2026-10-23 | (AIP 세션의 codex 교차 검토 2건, 별도 서브세션 반영) ⑴ AIP [MS365 연결] 재연결에서 다른 계정 B 를 고르면 라이브러리가 B 의 토큰을 **먼저 저장한 뒤** AIP 가 400 mismatch — B 의 등록·갱신이 되돌릴 수 없이 남고 사후 삭제는 B 의 기존 정상 연결까지 지운다 → `complete_external_login(expect_email=)` 선택 인자: 저장 **전** `/me` 메일 대조, 다르면 저장 없이 `ACCOUNT_MISMATCH`. ⑵ AIP 확정 사양 "저장이 안 돼도 로그인은 유지(미연결 표시)"인데 `SAVE_FAILED` 가 예외라 신원까지 잃어 503 → 저장 실패는 정상 반환 + `error="SAVE_FAILED"` 키(신원·`state` 는 DB 기준). 둘 다 추가(additive), ② 13 갱신. |
| 2026-10-24 | (사용자) "mcp365 에서 서버가 브랜치로 들어가 있는데 이걸 싱글모드 서버모드로 병합해서 사용할 수 있을까?" → "지금 승인보류가 된게 뭐지?" → "진행해줘": astra 5차 검토(N03·N04·Q01 한정) + mode 0 병합 전 검증(③) 뒤 `main` fast-forward 병합 — 기본은 mode 0 유지, mode 1 은 비활성(④ 'mode 1 활성화 전 코드' 잔여·운영 입력 확정 전까지 켜지 않음). |

## ② 확정 사양

### 1. 목적과 설계 결정

본 문서는 저장소의 실제 코드를 읽어 작성한 **구현 전 설계**다. 조사 기준은 2026-10-22 작업 트리이며, 기준 HEAD는 `f6c712109df238d9d95c57d0330ba478e8115772`다. 파일을 수정하지 않았고, 실제 `.env`·DB의 인증정보를 열람하거나 서버·테스트를 실행하지 않았다. 따라서 저장된 계정 수, 실제 데이터 소유자, 운영 환경의 프록시·ACL 설정은 확인되지 않았다.

주요 결정을 다음과 같이 고정한다.

| 항목 | 확정 결정 |
|---|---|
| 적용 모드 | `MS365_MULTI_USER=1`인 Streamable HTTP 배포에 적용한다. 미설정 또는 `0`은 기존 단일 운영자 모드다. |
| 호출자 인증 | **② 서버 발급 사용자별 bearer key**를 최초 구현의 인증 방식으로 채택한다. |
| 사용자 식별자 | 검증된 Entra `(tid, oid)`에 대응하는 불변 `user_key`를 사용한다. 이메일은 식별 키로 사용하지 않는다. |
| 사용자 컨텍스트 | 불변 `Principal`을 요청마다 확정하고 `ContextVar`로 전달한다. |
| `user_email` | **호출자와 일치 강제**. `expose: tool`을 유지하지만 계정 선택 기능은 제거한다. |
| 토큰 저장 | **사용자별 별도 SQLite 파일**에 암호화하여 저장한다. |
| 업무 데이터 | 사용자별 DB·파일·임시 디렉터리로 물리 분리한다. |
| 서비스 인스턴스 | 사용자별 서비스·GraphClient를 생성하고, 사용자·도메인·인증 세대에 따라 제한된 캐시를 사용한다. |
| HTTP 세션 | 멀티유저 모드에서는 SDK의 `stateless=True`를 사용한다. 요청 간 MCP 세션에 인증 주체를 보관하지 않는다. |
| OAuth 콜백 | 중앙 연결 서비스 한 곳에서 처리한다. 사용자·브라우저·PKCE·nonce에 바인딩된 인증 시도를 사용한다. |
| stdio | 기존 단일 운영자 모드에서 유지한다. `MS365_MULTI_USER=1`과 stdio 조합은 기동 오류로 처리한다. |
| 기존 데이터 | 명시적 소유자 매핑으로 이전한다. 소유자가 불명확한 데이터는 격리 보관한다. |
| 병렬 구현 | WP0에서 공용 타입·함수 계약을 먼저 고정한 뒤, 파일 소유권이 겹치지 않는 WP를 병렬 진행한다. |

#### 1.1 “완전 분리”의 범위

다음 불변조건을 만족해야 한다.

1. A의 인증정보로 시작한 요청은 B의 토큰 저장소·서비스 인스턴스·DB·파일·임시 디렉터리를 사용할 수 없다.
2. 이메일·리소스 ID·파일 경로·URL·MCP 헤더를 조작해도 위 조건이 바뀌지 않는다.
3. 사용자가 확인되지 않으면 요청을 거부한다. 다른 계정으로 대체하지 않는다.
4. 동일한 Graph 페이지·채팅·파일을 A와 B가 각각 이용하더라도 로컬 캐시·요약·메타데이터는 별개다.
5. 사용자 삭제·키 폐기·서비스 정리는 다른 사용자의 실행과 자원을 변경하지 않는다.
6. 사용자별 저장소가 없거나 손상되었을 때 공용 저장소로 되돌아가지 않는다.

분리의 보안 경계는 **서버 API를 이용하는 서로 다른 사용자**다. 서버 관리자·OS 관리자·서버 프로세스 자체의 완전한 장악까지 사용자별 파일 분리만으로 방어한다고 주장하지 않는다. 그러한 수준의 격리가 필요하면 사용자별 OS 계정·컨테이너·VM을 별도 배포 단위로 적용해야 한다.

Graph에서 A에게 정식으로 공유된 자원을 A의 delegated token으로 읽는 것은 허용한다. 이 경우에도 B의 저장된 토큰이나 B의 로컬 캐시를 사용해서는 안 된다.

---

### 2. 현황 분석과 파일·라인 근거

아래 위치는 조사 당시 작업 트리 기준이다. “확인된 결함”, “공유 상태로 인한 위험”, “현재 실행 경로에서 사용처를 찾지 못한 잔존 코드”를 구분한다.

#### 2.1 공용 런타임과 사용자 선택

| 파일:라인 | 확인한 현황 | 멀티유저 변경 요구 |
|---|---|---|
| [mcp_common/user_resolver.py:62](../mcp_common/user_resolver.py#L62), `:64–94` | 환경변수를 우선하고, 없으면 DB 사용자 이메일을 사전순으로 정렬하여 하나를 선택한다. | 멀티유저에서는 이 경로를 실행하지 않는다. |
| `mcp_common/user_resolver.py:96–115` | 명시한 이메일을 호출자 확인 없이 반환한다. | principal과 일치 확인을 수행한다. |
| `mcp_common/user_resolver.py:122–136` | 프로세스 전역 resolver가 있다. | 객체 공유 자체는 가능하지만 사용자 선택 상태를 보유해서는 안 된다. |
| `mcp_common/user_resolver.py:69–85` | 현재 구현은 기본 사용자 결과를 캐시하지 않는다. 파일 앞부분의 “유효 토큰 우선” 설명과 달리 실제 정렬 기준은 이메일뿐이다. | 현황을 “최근 갱신 사용자 선택”이나 “유효 토큰 우선”으로 해석하지 않는다. |
| [mcp_common/http_transport.py:61](../mcp_common/http_transport.py#L61), `:61–78` | `stateless=False`인 SDK SessionManager에 요청을 직접 전달한다. 호출자 인증 미들웨어가 없다. | 인증 관문과 요청 컨텍스트 연결을 추가한다. |
| `mcp_common/http_transport.py:25–43` | Host/Origin 허용 목록을 검사한다. | 기존 방어를 유지하되 호출자 인증과 구분한다. |
| `mcp_common/http_transport.py:80–106` | 공용 `/health`에 lifecycle 오류를 포함할 수 있다. | 공개 health에서 내부 오류·사용자 정보를 제거한다. |
| `mcp_common/net.py:21,47–81` | 기본 loopback 바인드, 외부 바인드는 환경변수로 허용한다. | 외부 바인드 허용을 인증 완료의 근거로 사용하지 않는다. |
| `mcp_common/runtime.py:107–147` | 인자 정규화·기본값 적용·검증 후 핸들러를 호출한다. principal 확인은 없다. 예외 문자열을 응답에 포함한다. | 인증 컨텍스트 확인과 안전한 오류 변환을 추가한다. |
| `mcp_common/runtime.py:154–208` | 프로세스 공용 서비스 목록을 startup/shutdown한다. | 사용자별 자원은 별도 서비스 풀에서 관리한다. |
| `mcp_common/validation.py:11,78–93` | 추가 속성을 허용하고 `MCP_VALIDATE_INPUT=0`으로 검증을 끌 수 있다. | 인증·소유권 검증은 이 스위치로 해제할 수 없게 한다. |
| `mcp_common/paths.py:28–48` | 기본 허용 루트가 프로젝트 전체와 `MCP_DATA_DIR`다. | 사용자 파일 영역만 허용한다. |
| `mcp_common/paths.py:59–94` | realpath 기반 경계 검사는 있지만 사용자 개념이 없다. | 사용자 경계·민감 디렉터리 차단·안전한 파일 열기를 추가한다. |
| `mcp_common/bootstrap.py:107–113,151–172` | 공용 `.env`와 프로세스 설정을 로드한다. | 멀티유저 보안 설정을 기동 시 확정하고 요청에서 변경하지 못하게 한다. |
| `mcp_common/stdio_transport.py:48–63` | 동일 공용 lifecycle과 MCP 서버를 실행한다. | 멀티유저 모드의 stdio 기동을 차단한다. |
| `core/protocols.py:28–45` | 토큰 공급 계약부터 `email=None`이면 기본 사용자를 선택하도록 정의한다. | 사용자에 고정된 토큰 공급 계약으로 교체한다. |

#### 2.2 인증 저장소·싱글턴·갱신

| 파일:라인 | 확인한 현황 | 멀티유저 변경 요구 |
|---|---|---|
| [session/auth_database.py:18](../session/auth_database.py#L18), `:25–36` | 기본값은 `database/auth.db`이며 상대 입력은 저장소 루트 기준 절대경로로 변환한다. | 공용 파일 사용을 제거한다. **CWD 상대 DB라고 기술하지 않는다.** |
| `session/auth_database.py:62–101,252–278` | 앱 설정의 client secret과 access/refresh/id token이 같은 DB의 평문 TEXT에 저장된다. | 앱 설정과 사용자 토큰을 분리하고 토큰을 암호화한다. |
| `session/auth_database.py:74–75,90–101,307–315` | 이메일이 사용자·토큰 키다. tenant에 따른 구분과 호출자 확인이 없다. | `(tid, oid)` 기반 소유권을 사용한다. |
| `session/auth_database.py:410–447,455–474` | 전체 사용자 조회와 전체 토큰 정리 기능이 있다. | 관리자 전용으로 제한한다. |
| `session/auth_manager.py:79–108` | 공용 DB·AzureConfig·AuthService와 이메일별 `asyncio.Lock`을 보유한다. | 사용자 저장소와 프로세스 간 refresh lock을 사용한다. |
| `session/auth_manager.py:629–643`; `mcp_common/auth.py:12–16` | 기본 AuthManager는 프로세스 싱글턴이다. | 공유 관문은 유지할 수 있지만 요청 사용자 상태를 보유하지 않게 한다. |
| `session/auth_manager.py:38–63,131–137,161–172,246–255,375–381,411–420` | 조회·갱신·삭제·상태 확인에서 이메일 생략 시 기본 사용자를 선택한다. ImportError용 폴백도 있다. | 멀티유저에서 모든 폴백을 차단한다. |
| `session/auth_service.py:20–30,360–371`; `session/auth_database.py:426` | 별도 폴백은 `list_users()[0]`을 사용하고 DB 목록은 `updated_at DESC`다. | 공용 resolver만 수정해서는 부족하다. 해당 우회 경로도 제거한다. |
| `session/auth_manager.py:252–269` | 정상 검증 경로의 refresh lock은 이메일 키의 프로세스 내부 lock이다. | 도메인 프로세스 사이에서도 같은 사용자의 refresh를 직렬화한다. |
| `session/auth_manager.py:151–200`; `session/auth_service.py:418–423` | 직접 refresh 경로는 위 lock을 우회한다. | 갱신 진입점을 하나로 모은다. |
| `session/auth_manager.py:321–338` | `_auto_reauth(email)`은 브라우저에서 다른 계정으로 인증되면 그 계정의 토큰을 반환할 수 있다. | 예상 `(tid, oid)`와 실제 인증 계정 일치를 강제한다. |
| `session/auth_manager.py:365–388`; `session/auth_database.py:349–380` | `remove_user()`는 실질적으로 토큰 행만 삭제한다. | 계정 삭제 절차를 별도로 구현한다. |
| `session/azure_config.py:38–58,76–89,153–176` | 앱 설정과 secret을 공용 DB·환경변수에서 읽고 DB에 저장한다. | 사용자 토큰 DB에서 앱 설정을 제거한다. |
| `session/azure_config.py:271–302` | `switch_app()`이 객체의 앱을 변경하고 앱 목록에는 secret이 포함될 수 있다. | 요청 중 앱 전환 금지, 목록에서 비밀 제외. |
| `mcp_file_handler/file_manager.py:55`; `mcp_file_handler/onedrive/client.py:27`; `callback_server.py:53–55` | 기본 싱글턴을 통하지 않고 AuthManager를 별도 생성하는 예외가 있다. | 직접 생성 경로를 멀티유저에서 차단한다. |

#### 2.3 OAuth state·콜백·잔존 세션 코드

| 파일:라인 | 확인한 현황 | 판단 |
|---|---|---|
| `session/auth_service.py:63–76,107–114,141–151` | 무작위 state, 10분 TTL, 성공 경로의 일회 소비가 이미 존재한다. | “state 검증 없음”이 아니다. |
| `session/auth_service.py:111–114` | state에 생성 시각과 상태만 저장한다. | 시작 사용자·브라우저·예상 계정과 연결되지 않는다. |
| `session/auth_service.py:183–207` | PKCE challenge/verifier 및 OIDC nonce를 사용하지 않는다. | 코드 가로채기·인증 응답 혼동 방어를 추가한다. |
| `session/auth_service.py:153–176` | Graph `/me`의 이메일로 토큰을 저장하고 반환 객체에 토큰을 포함한다. | 예상 계정 확인 후 저장하고 외부 결과에서 토큰을 제거한다. |
| [callback_server.py:48](../callback_server.py#L48), `:48–50,155–156,319–345` | 완료 Event, 인증 이메일, 오류 필드가 모든 인증에 공유된다. | 인증 시도별 상태로 바꾼다. |
| `callback_server.py:122–128` | 오류 콜백은 pending state 존재만 확인하여 공용 Event를 깨운다. | TTL·소유권·일회 소비를 동일하게 적용한다. |
| `callback_server.py:131–140` | code/state가 없으면 공용 대기를 건드리지 않고 거부한다. | 기존 방어를 유지한다. |
| `callback_server.py:214–218` | 잘못된 state로 발생한 예외도 공용 오류와 Event를 변경한다. | 다른 인증을 중단시키는 경로를 제거한다. |
| `callback_server.py:299–302` | WSL에서는 `0.0.0.0` 바인드를 사용한다. | MCP 서버의 loopback 기본값과 구분한다. |
| `session/auth_manager.py:488–492,533–556,576–595,612–616` | 콜백 포트 소유, 서버 브라우저 실행, 공용 대기 초기화, 신규 DB 이메일로 성공 추정, 콜백 종료 경로가 있다. | 멀티유저에서는 중앙 연결 서비스로 통합한다. |
| `session/session_manager.py:20–31,49–58,80–94,131–145` | 기본 이메일 선택과 토큰 캐시가 있다. | legacy 전용으로 제한한다. |
| `session/session_manager.py:171–183` | 갱신 실패 후 만료 시각을 모르는 주입 토큰을 반환할 수 있다. | 멀티유저에서는 사용 금지. |
| `session/session_manager.py:235–239,277–305,320–356,399–421` | 이메일 키 전역 세션·공용 lock·전체 세션 조회·전역 인스턴스가 있다. | 재사용 시 격리 우회가 되므로 모드 가드를 둔다. |

`session/session_manager.py`는 조사한 운영 Python 코드에서 import 사용처를 찾지 못했다. **현재 HTTP의 세션 구현은 이 모듈이 아니라 MCP SDK의 `StreamableHTTPSessionManager`다.**

#### 2.4 도메인별 전역 서비스·GraphClient

| 도메인 | 전역 서비스 및 클라이언트 근거 | 사용자 선택·공유 상태 근거 |
|---|---|---|
| Outlook | `mcp_outlook/mcp_server/handlers.py:46`; `outlook_service.py:31–44`; `graph_mail_client.py:59–64,77–91` | 핸들러 `:56–57`; `graph_mail_query.py:58–94,110–122`; `graph_mail_id_batch.py:35–73,125–130` |
| Calendar | `mcp_calendar/mcp_server/handlers.py:33`; `calendar_service.py:52–65,633`; `graph_calendar_client.py:28–51` | 핸들러 `:43–44`; 서비스 `:31–40`; `graph_calendar_query.py:219–273` |
| Teams | `mcp_teams/mcp_server/handlers.py:33`; `teams_service.py:46–57` | 핸들러 `:42–43`; 서비스 `:27–34`; `graph_teams_client.py:46–60,83` |
| OneDrive | `mcp_onedrive/mcp_server/handlers.py:32`; `onedrive_service.py:45–55` | 핸들러 `:42–43`; 서비스 `:21–28`; `graph_onedrive_client.py:52–64,87` |
| OneNote | `mcp_onenote/mcp_server/handlers.py:33`; `onenote_service.py:33–48,56–66` | 핸들러 `:43–44`; `graph_onenote_client.py:32–43,62–74,112–131` |
| Todo | `mcp_todo/mcp_server/handlers.py:33`; `todo_service.py:89–99,369`; `graph_todo_client.py:23–32` | 핸들러 `:43–44`; 서비스 `:22–24,106–109`; `graph_todo_query.py:79–101` |
| FileHandler | `mcp_file_handler/mcp_server/handlers.py:65–72,98–102`; `file_manager.py:52–56` | `onedrive/client.py:30–49`에서 이메일 없이 토큰 요청 |
| Time | `mcp_time/mcp_server/handlers.py:29,33,41`; `time_service.py:14–55` | 개인 토큰·DB·사용자 상태는 없다. 멀티유저 HTTP 인증 정책은 동일하게 적용한다. |

Outlook·Calendar·Todo의 단일 `_url_builder`는 이메일에 따라 변경되는 공유 상태다. 현재 코드에서 교차 사용자 누출 race를 재현한 것은 아니므로 **오염 위험**으로 분류한다.

다음 종료 경로는 공유 토큰 공급자의 `close()`까지 호출한다.

- `mcp_outlook/graph_mail_query.py:979–982`
- `mcp_outlook/graph_mail_id_batch.py:627`
- `mcp_outlook/mail_attachment.py:813–815`
- `mcp_calendar/graph_calendar_query.py:873–876`
- `mcp_todo/graph_todo_query.py:505`

사용자별 서비스 퇴거가 다른 사용자의 인증 자원을 닫지 않도록 소유권을 바꿔야 한다.

`core/graph_client.py`는 존재하지 않는다. Graph HTTP 구현은 도메인별로 있으므로 공용 파일 하나만 수정하여 전환을 완료할 수 없다.

#### 2.5 DB·파일 저장과 실제 격리 결함

| 영역 | 파일:라인 | 확인한 현황 |
|---|---|---|
| Teams DB | `mcp_teams/teams_db_manager.py:20,28–33,43–63` | `teams_chats`가 인증정보와 같은 `database/auth.db`에 저장된다. 상대 기본값은 저장소 기준 절대경로로 변환한다. |
| Teams 행 필터 | 같은 파일 `:62,103,167,200,325,334,386,441,473,503` | `UNIQUE(user_id,chat_id)` 및 사용자 조건이 존재한다. 조사 범위에서 user_id 누락 SQL은 발견하지 못했다. 호출자가 user_id를 선택할 수 있는 것이 핵심 문제다. |
| OneNote DB | `mcp_onenote/onenote_db_service.py:20,28–34` | 모든 사용자가 저장소 기준 `database/onenote.db`를 공유한다. |
| OneNote item 충돌 | 같은 파일 `:49,225–235` | `item_id` 전역 UNIQUE와 사용자 조건 없는 conflict 처리다. |
| OneNote summary 충돌 | 같은 파일 `:73–74,530–541` | `page_id` 전역 UNIQUE와 사용자 조건 없는 conflict 처리다. |
| **OneNote 요약 조회 IDOR** | `onenote_service.py:143–146` → `onenote_agent.py:365–373` → `onenote_db_service.py:558–566` | `user_email`을 받지만 사용하지 않고 `page_id`만으로 요약을 반환한다. |
| **OneNote 요약 삭제 IDOR** | `onenote_delete.py:42,53–55`; `onenote_db_service.py:602–609` | A 토큰으로 Graph 404를 받아도 사용자 조건 없는 요약 삭제를 수행할 수 있다. |
| OneNote 변경이력 조회 | `onenote_read.py:236–242`; `onenote_db_service.py:757–772` | 하위 서비스 API가 page_id만으로 변경이력을 조회한다. 현재 MCP 도구로의 직접 도달 여부와는 구분한다. |
| OneNote 정상 필터 | `onenote_db_service.py:274,311,347–348,393,592,799` | 이름·최근 항목·목록·일부 삭제·요약 목록·사용자 변경이력에는 사용자 조건이 있다. |
| FileHandler 설정 | `mcp_file_handler/config/settings.py:13–27,61–77,99–105,117–127` | 공용 output·temp·metadata 경로를 사용하고 환경변수·홈/CWD 설정을 읽는다. |
| metadata SQLite | `mcp_file_handler/metadata/storage.py:72–94,115–119,135–139,167–178,206` | `metadata.db`는 실제 CWD 상대경로다. `file_url`만 PK이며 소유자 열이 없다. |
| metadata JSON | 같은 파일 `:224–249,258–264,278–300` | 공용 JSON 전체를 덮어쓴다. 사용자 분리·동시성 제어가 없다. |
| metadata 도구 | `mcp_file_handler/mcp_server/handlers.py:131–176`; `file_manager.py:106–114,386–397` | 공용 저장소를 검색한다. URL 키는 로컬 경로 검사와 별개다. |
| FileHandler temp | `mcp_file_handler/onedrive/downloader.py:16–23,36–41,78–82,147–157` | 하나의 mutable `temp_dir`를 생성·정리하므로 동시 요청 간 삭제 race가 가능하다. |
| 원격 파일명 결합 | 같은 파일 `:41,91–98`; `onedrive/client.py:154–159` | Graph 파일명을 경로에 결합한 뒤 쓰기 직전 최종 경계 검사가 없다. |
| trusted roots 예외 | `mcp_file_handler/file_manager.py:86–104,257–277` | 공용 임시 루트를 허용 루트 밖에서도 신뢰한다. |
| OCR 임시파일 | `mcp_file_handler/converters/image/ocr_converter.py:99–101` | 사용자별 dir 없이 시스템 임시파일을 만든다. |
| Outlook downloads | `mcp_outlook/mail_attachment_storage.py:167–180` | 프로젝트 공용 `downloads`를 사용한다. |
| Outlook 임의 저장 경로 | 같은 파일 `:197–215`; `mail_attachment.py:701–710,927–949` | 입력 저장 경로를 직접 사용한다. 일부 경로는 원격 첨부파일명도 그대로 결합한다. |
| Outlook 파일명 race | `mail_attachment_storage.py:236–255,799–826` | 파일 존재 검사 후 `wb`로 열어 동시 저장 시 덮어쓰기 가능성이 있다. |
| Outlook metadata | `mail_attachment.py:54–96,117–127,156–183` | 공용 `mail_metadata.json`, message_id 키, 전체 덮어쓰기 방식이다. |
| Outlook provider 누락 | `graph_mail_client.py:316,455,536`; `graph_mail_query.py:959`; `mail_attachment.py:170–174` | 첨부 핸들러 생성 시 기존 provider를 전달하지 않아 공용 AuthManager를 다시 얻는다. |
| 토큰 보유 첨부 객체 | `mail_attachment.py:827–839` | 객체가 access token과 Authorization header를 보관한다. |

기존 `mcp_common.paths`에는 경로 검사가 있다. 다만 허용 범위가 공용이고, **Outlook의 직접 저장 경로는 이 관문을 거치지 않는다.**

#### 2.6 도구 계약의 사용자 인자 전수 목록

다음 54개 `user_email` 선언은 모두 `type: string`, `required: false`, `expose: tool`이며 `default`가 없다.

| 파일 | 선언 수 | 선언 시작 라인 |
|---|---:|---|
| `spec/param_spec/outlook.yaml` | 11 | 40, 223, 240, 257, 362, 408, 447, 495, 538, 641, 706 |
| `spec/param_spec/calendar.yaml` | 7 | 37, 61, 78, 120, 144, 191, 231 |
| `spec/param_spec/teams.yaml` | 15 | 28, 49, 70, 103, 159, 169, 184, 210, 242, 267, 292, 316, 331, 347, 357 |
| `spec/param_spec/onedrive.yaml` | 9 | 25, 34, 62, 75, 99, 122, 135, 157, 178 |
| `spec/param_spec/onenote.yaml` | 4 | 22, 76, 120, 134 |
| `spec/param_spec/todo.yaml` | 8 | 39, 57, 74, 91, 128, 151, 207, 276 |

FileHandler 7개 도구와 Time 1개 도구에는 `user_email`이 없다. Outlook `test_handler`에도 선언은 없지만 핸들러 `:56–57,162–169`에서 이메일을 주입한다. 따라서 `user_email` 인자 검사만 추가해서는 전체 서버를 격리할 수 없다.

각 도메인의 세 진입 파일 구조는 유지한다. 다만 FileHandler에는 실제로 `mcp_server/tool_definitions.py` 관문도 존재하므로 “서버 폴더에 정확히 세 파일만 존재한다”고 가정하지 않는다.

#### 2.7 로그·운영 경로

| 파일:라인 | 확인한 현황 |
|---|---|
| `session/auth_manager.py:676` | CLI가 access token 앞부분을 출력한다. |
| `session/auth_service.py:119`; `auth_manager.py:534`; `callback_server.py:142` | state 앞부분을 로그에 남긴다. |
| `session/auth_database.py:203,282,371`; `auth_service.py:168,383,424`; `auth_manager.py:203,268,384` | 이메일을 로그에 기록한다. |
| `session/auth_service.py:211–213,269–273,298–299`; `callback_server.py:215–218` | OAuth 오류 본문·예외를 로그나 응답으로 전파한다. |
| `callback_server.py:193` | 방어 분기에 token_response 전체 로그가 있다. 현재 정상 경로의 도달 여부와 별개로 제거해야 한다. |
| `mcp_onenote/graph_onenote_client.py:192,346`; `mcp_teams/graph_teams_client.py:139,324`; `mcp_onedrive/graph_onedrive_client.py:148` | Graph 오류 본문을 기록한다. |
| `mcp_onenote/onenote_db_service.py:242,550`; `mcp_teams/teams_db_manager.py:120,125,182,207` | 제목·이름·리소스 ID 등 개인정보를 기록한다. |
| `mcp_file_handler/file_manager.py:146,152,184,216,298,354,357`; `onedrive/processor.py:75,87,91`; `downloader.py:135,139,144`; `client.py:161` | 파일명·경로·공유 URL을 기록한다. |
| `mcp_outlook/mail_attachment_storage.py:257,261,422,523,568`; `mail_attachment.py:905–906` | 파일 경로와 외부 오류 본문이 로그·예외에 포함될 수 있다. |
| `mcp_file_handler/mcp_server/handlers.py:220–226`; `server_stream.py:61–71` | 공개 health에 허용 루트 절대경로를 포함한다. |
| `main.py:28–39,57–68`; `_reauth.py:6–9` | 운영자 전체 사용자 조회·공용 브라우저 인증 경로가 있다. |
| `.claude/skills/setup_ms365/scripts/check_token.py:34–45` | 기본 사용자로 토큰을 확인한다. |
| `.claude/skills/setup_ms365/scripts/verify_setup.py:52,172–198` | 고정 auth.db의 전체 계정·토큰과 첫 이메일을 확인한다. |
| `.claude/skills/setup_ms365/scripts/streamable_http_probe.py:139–154,194–300` | MCP session ID의 존재와 stateful 동작을 정상 조건으로 가정한다. |
| `.claude/skills/export_ms365/scripts/build_bundle.py:85,101,109–110,396–402`; `assets/verify_bundle.py:111–115` | 기존 비밀 제외 정책과 공용 auth.db 안내가 있다. 새 데이터 루트·키·감사·마이그레이션 산출물도 제외해야 한다. |

#### 2.8 기존 사양과의 관계

- `CLAUDE.md:41–140`의 param_spec SSOT·단일 정규화 관문·핸들러 기본값 금지를 유지한다.
- `CLAUDE.md:143–151`의 파일 분할 원칙을 따른다. 이번 변경의 모든 신규·수정 소스 파일에 1,200줄 상한, 900줄 이하 권고를 적용한다.
- `spec/spec_보안정확성검토반영.md:29–31`의 “공유 페이지 요약은 사용자별로 분리하지 않는다”는 결정은 **이번 요구로 대체한다**.
- 같은 문서 `:50–51`의 호출자 인증 미결 항목은 본 사양의 bearer 인증으로 구체화한다.
- 외부 기준은 MCP 2025-11-25 문서와 저장소의 `mcp>=1.29,<2` 제약을 기준으로 삼는다. MCP 2.x API를 전제로 구현하지 않는다.

---

### 3. 위협 모델

공격자는 유효한 A 계정을 가진 MCP 사용자이거나, 인증되지 않은 HTTP 호출자다. 입력 JSON·헤더·URL·파일명·리소스 ID·요청 순서·동시성을 조작할 수 있다고 가정한다.

| 위협 | 공격 경로 | 필수 방어 |
|---|---|---|
| 계정 IDOR | A가 `user_email=B`를 전달하여 B 토큰 선택 | bearer로 principal 확정, 이메일 일치 확인, 사용자 고정 provider |
| 기본 사용자 도용 | 이메일 생략·null·빈 문자열·내부 폴백으로 운영자 계정 선택 | 멀티유저에서 기본 계정 탐색 전면 금지 |
| 로컬 DB IDOR | B의 page_id·file_url을 알고 조회·삭제 | 사용자별 DB와 모든 쿼리의 owner 조건 |
| 캐시 오염 | 이메일·page_id·URL만으로 서비스·결과 캐시 공유 | `(user_key, domain, auth_epoch)` 및 사용자별 결과 키 |
| MCP 세션 혼동 | B의 session ID 재사용, A로 초기화한 세션에서 다른 자격증명 사용 | stateless HTTP, 매 요청 인증, session ID 인증 수단 사용 금지 |
| OAuth 로그인 혼동 | A의 연결 절차에 B 계정 인증 결과 저장 | expected `(tid, oid)`·nonce·브라우저 바인딩 확인 |
| 콜백 가로채기 | 유출 code/state 재사용, 다른 브라우저 콜백 | PKCE S256, 일회 state, TTL, 브라우저 쿠키 바인딩 |
| 콜백 간 간섭 | 잘못된 state로 다른 사용자의 완료 Event 변경 | 시도별 상태, 전역 Event 제거 |
| 경로 traversal | `../`, 절대경로, UNC, junction, symlink, ADS, 원격 파일명 조작 | 사용자 파일 루트, 안전한 파일 열기, 링크·특수 경로 거부 |
| 다운로드 유출 | 공용 다운로드·metadata 검색·정적 파일 URL | 사용자 저장 영역, 인증된 다운로드, 소유권 재검사 |
| Graph confused deputy | 임의 Graph URL·다른 `/users/...` 경로·redirect에 bearer 전송 | 사용자 고정 토큰, endpoint·method 허용 목록, redirect 정책 |
| refresh race | 여러 도메인 프로세스가 같은 refresh token 동시 갱신 | 프로세스 간 lock, 재조회, 버전 조건부 갱신 |
| 파일·metadata race | exists→write, 전체 JSON 덮어쓰기, 공용 temp 정리 | 배타 생성·원자적 교체·SQLite 트랜잭션·요청별 temp |
| 컨텍스트 유실 | executor·백그라운드 작업에서 principal 누락 | 명시적 provider 전달, context 복사, 누락 시 거부 |
| 로그 유출 | 토큰·state·메일 제목·공유 URL·Graph 오류 원문 | 구조화된 허용 필드 감사와 공개 오류 코드 |
| 관리자 기능 노출 | 사용자 목록·계정 삭제·앱 전환을 일반 도구에서 호출 | 별도 관리 CLI, 일반 bearer에 관리 권한 부여 금지 |
| 삭제·폐기 race | 폐기 전 생성된 서비스가 이후에도 토큰 사용 | auth_epoch 확인, 사용자 drain, 응답 전 재검사 |
| 자원 고갈 | 다수 키·연결 시도·서비스·대용량 변환 | 사용자별 동시 실행·연결 시도·파일 크기·캐시 상한 |

---

### 4. 호출자 인증과 identity

#### 4.1 선택지 비교와 권고안

| 선택지 | 장점 | 구현·운영 고려 | 결정 |
|---|---|---|---|
| ① MCP Authorization OAuth resource server + Entra 토큰 검증 | 표준 인증 discovery와 기업 정책에 적합 | MCP용 API audience·scope·클라이언트 등록·metadata·PKCE 지원이 필요하다. Graph용 토큰을 MCP용으로 받아서는 안 된다. | 향후 표준 OAuth 연동 과제로 분리 |
| **② 사용자별 API bearer key** | 기존 HTTP 공용 관문에 적용 가능하고 사용자 매핑·폐기를 명확히 구현할 수 있다. | 클라이언트의 Authorization 헤더 지원과 안전한 키 배포가 필요하다. 자동 OAuth 로그인 기능은 제공하지 않는다. | **최초 멀티유저 버전의 확정안** |
| ③ 리버스 프록시 사용자 헤더 | 조직의 기존 SSO를 활용할 수 있다. | 직접 backend 접근 차단, 헤더 제거·재주입, 프록시 인증, 신뢰 경계 관리가 필수다. | identity 근거로 채택하지 않음 |

MCP의 HTTP authorization 표준은 OAuth 기반이며, stdio는 환경 기반 자격증명을 사용하는 별도 모델이다. 이번 bearer 방식은 **통제된 배포용 인증 방식**이며 MCP OAuth 자동 discovery를 구현한 것으로 표시하지 않는다. [MCP Authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)

Graph access token, ID token, MCP 호출용 bearer key는 서로 다른 자격증명이다. 특히 Microsoft API용 access token을 로컬 디코딩하여 MCP 호출자 신원으로 신뢰하지 않는다. [Microsoft access tokens](https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens)

**가정:** 최초 배포 대상 MCP 클라이언트는 모든 HTTP 요청에 Authorization 헤더를 보낼 수 있다. 이는 출시 전 실제 클라이언트로 검증한다. 지원하지 않는 클라이언트에 대해 인증 없는 예외 경로를 만들지 않는다.

#### 4.2 사용자 등록

1. 관리자가 로컬 관리 CLI로 허용할 `tenant_id`와 `object_id`를 등록한다.
2. 두 값은 UUID 형식이어야 하며, tenant는 배포 허용 목록에 있어야 한다.
3. registry에 `pending_link` 사용자를 생성한다.
4. 관리 CLI가 사용자에게 전달할 bearer key를 한 번만 표시한다.
5. 사용자는 이 키로 Graph 연결 절차를 시작한다.
6. 검증된 OIDC 결과와 Graph `/me.id`가 등록된 `(tid, oid)`와 일치해야 연결을 활성화한다.

이메일만으로 사용자를 생성하거나 기존 데이터 소유자로 확정하지 않는다. 동일 `(tid, oid)`의 중복 사용자 생성은 거부한다.

초기 버전은 조직 계정과 명시적으로 허용한 tenant를 대상으로 한다. 한 principal에 한 Graph 계정만 연결한다. 공유 사서함은 별도 로그인 계정 연결이 아니라 해당 principal의 Graph 위임 권한으로 다룬다.

#### 4.3 bearer key 형식과 저장

```text
m365v1.<kid>.<secret>
```

- `kid`: CSPRNG로 생성한 128비트 값의 소문자 hex.
- `secret`: CSPRNG로 생성한 256비트 값의 padding 없는 base64url.
- 유효기간 기본 30일.
- 사용자별 활성 키 최대 2개.
- 회전 시 기존 키와 신규 키의 중첩 기간 최대 24시간.
- 키의 scope는 `mcp:outlook`, `mcp:calendar` 등 도메인 단위로 발급한다.
- 일반 사용자 키에는 사용자 생성·앱 설정 변경·타 사용자 조회 권한을 부여하지 않는다.

전역 registry에는 `kid → user_key`의 위치 정보만 저장한다. 키 digest·scope·만료·폐기 상태는 해당 사용자의 `auth/auth.db`에 저장한다.

digest는 배포 ID·kid·secret을 길이가 명확한 형식으로 결합한 SHA-256으로 계산하고 상수 시간 비교한다. 고엔트로피 난수 키이므로 비밀번호 해싱을 대신 적용하지 않는다. 원문 키는 저장·로그·URL·오류 응답에 남기지 않는다.

#### 4.4 매 요청 인증 절차

모든 도메인의 `/mcp`에 다음 순서를 적용한다.

1. Host/Origin 및 요청 크기 검사.
2. Authorization 헤더의 개수·형식 검사.
3. kid를 registry에서 조회.
4. 해당 사용자의 키 digest·만료·폐기·계정 상태 검사.
5. 도메인 scope 확인.
6. 현재 registry 상태로 불변 `Principal` 생성.
7. ASGI scope에 서버 내부 값으로 기록.
8. MCP SDK에 요청 전달.

`initialize`, `tools/list`, `tools/call`, notification, GET, DELETE 모두 인증을 거친다. 쿠키·이메일 인자·`Mcp-Session-Id`·`X-User-*` 헤더는 호출자 인증 근거로 사용하지 않는다.

| 상황 | 응답 |
|---|---|
| 키 없음·형식 오류·만료·폐기·알 수 없는 키 | HTTP 401, 일반화된 오류, `WWW-Authenticate: Bearer` |
| 유효한 키지만 도메인 scope 부족 | HTTP 403 |
| 정상 인증 후 `user_email` 불일치 | MCP 도구 오류 `identity_mismatch`, `isError=True` |
| Graph 미연결·재인증 필요 | MCP 도구 오류 `graph_not_connected` 또는 `graph_reauth_required` |
| 다른 사용자의 로컬 리소스 ID | 해당 사용자 관점의 `not_found` |
| 허용 루트 밖 파일 경로 | `path_not_allowed`, 실제 절대경로는 응답하지 않음 |

멀티유저 mode에서는 `stateless=True`, `event_store=None`으로 생성한다. `Mcp-Session-Id`를 전달하면 인증 후 400으로 거부한다. 독립 GET 스트림과 DELETE 세션 종료는 지원하지 않으며 인증 후 405를 반환한다. POST의 요청별 SSE 응답은 사용할 수 있다.

#### 4.5 배포와 stdio

- 외부 구간은 HTTPS만 허용한다.
- TLS 프록시를 쓰는 경우 backend는 loopback 또는 전용 네트워크로 제한한다.
- 프록시는 Authorization을 전달하되 자체 사용자 헤더로 principal을 만들지 않는다.
- trust proxy 설정은 명시한 프록시 주소에만 적용한다.
- `/health`는 인증 없이 최소 `status`, `server`, `version`만 제공한다.
- 멀티유저 모드의 stdio 기동은 즉시 실패한다.
- legacy stdio가 멀티유저 데이터 루트를 열도록 설정하면 기동을 거부한다.

---

### 5. 요청 범위 컨텍스트와 도구 계약

#### 5.1 principal 모델

```python
@dataclass(frozen=True, slots=True)
class Principal:
    user_key: str
    tenant_id: str
    object_id: str
    graph_email: str | None
    credential_id: str
    scopes: frozenset[str]
    auth_epoch: int

@dataclass(frozen=True, slots=True)
class RequestIdentity:
    principal: Principal
    request_id: str
    transport: Literal["http"]
    authenticated_at: datetime
    credential_expires_at: datetime
```

`Principal`에는 토큰·키·client secret을 넣지 않는다. `request_id`는 서버가 생성한 난수 ID다. 외부 correlation ID를 사용할 경우 별도 길이·문자 제한을 적용하며 보안 키로 사용하지 않는다.

#### 5.2 전파 방식

- `mcp_common/principal.py`에 기본값 `None`인 `ContextVar[RequestIdentity | None]`를 둔다.
- 인증 미들웨어는 `scope["state"]["ms365_identity"]`에 검증 결과를 저장한다.
- MCP SDK의 **현재 메시지에 연결된 HTTP request scope**에서 identity를 읽어 각 도구 실행 시 다시 bind한다.
- 단순히 “ASGI에서 ContextVar를 한 번 설정하면 SDK의 모든 작업에 전달된다”고 가정하지 않는다.
- `finally`에서 ContextVar token을 반드시 reset한다.
- 부모 요청이 끝난 뒤 계속 실행되는 사용자 작업은 최초 버전에서 만들지 않는다.
- executor가 필요하면 `copy_context()`를 명시적으로 전달한다. 토큰 공급자와 경로 객체도 생성자에 전달한다.
- 동기 FileHandler의 `executor.submit(asyncio.run, coro)` 인증 브리지는 제거하고 비동기 인증 경로로 통일한다.

현재 설치된 SDK 소스에서는 HTTP request를 메시지 metadata에 연결하고 lowlevel request context로 전달한다. 구현은 이 경로에 대한 통합 테스트를 포함해야 한다.

#### 5.3 `user_email` 정책

기존 54개 선언은 다음 계약으로 유지한다. 설명만 YAML에서 변경한다.

| name | type | required | expose | default | description |
|---|---|---|---|---|---|
| user_email | string | false | tool | 없음 — YAML 키 생략 | 멀티유저 모드에서는 인증된 호출자의 연결 계정과 일치해야 한다. 생략 시 해당 호출자의 연결 계정을 사용한다. 다른 계정을 선택할 수 없다. |

처리 규칙은 다음과 같다.

1. 인자가 **없으면** 현재 principal의 `graph_email`을 사용한다.
2. 인자가 있으면 문자열이어야 하며, 빈 문자열·공백 문자열·null은 거부한다.
3. 정규화한 값이 현재 principal의 연결 계정 이메일과 같아야 한다.
4. 불일치 시 다른 계정의 존재 여부를 조회하지 않고 거부한다.
5. 이메일이 같더라도 저장소·토큰 선택은 `user_key`로 수행한다.
6. 연결된 계정 이메일이 없으면 Graph 작업은 실패한다.
7. FileHandler·Time처럼 이메일 인자가 없는 도구도 principal은 반드시 필요하다.

이메일 비교는 `NFKC → strip → casefold`로 수행한다. 이 정규화는 **호환성 검사**에만 사용하며 계정 병합·소유권 판단에는 사용하지 않는다.

`expose: internal`로 변경하지 않는다. 따라서 `default: null`을 넣고 핸들러에서 실제 사용자로 덮어쓰는 의미 확장이나 새로운 `source` 필드도 도입하지 않는다.

#### 5.4 SSOT와 검증 순서

`ToolRuntime.call()`의 멀티유저 순서는 다음으로 고정한다.

```text
현재 메시지의 검증된 identity 확인
→ 계정·키 폐기 상태 재확인
→ 원본 인자의 user_email 형식·일치 확인
→ 기존 schema_normalize boolean 보정 1회
→ param_spec에서 파생한 기본값 적용
→ 입력 스키마 검증
→ 사용자별 서비스 lease
→ 핸들러 실행
→ 응답 전 폐기 상태 재확인
→ 안전한 결과/오류 반환
```

- identity 검사는 `MCP_VALIDATE_INPUT`과 무관하게 항상 실행한다.
- 멀티유저에서는 `MCP_VALIDATE_INPUT=0` 설정 자체를 기동 오류로 처리한다.
- 최상위 추가 인자는 멀티유저에서 거부한다. 허용 키 목록은 param_spec의 노출 필드에서 파생한다.
- `principal`, `tenant_id`, `user_key`, `token`, `db_path` 같은 보안용 내부 값을 도구 입력으로 주입할 수 없다.
- object 타입 업무 데이터의 허용 필드 의미는 각 param_spec을 따른다.
- schema 보정·boolean 변환은 기존 `schema_normalize.py` 관문을 유지한다.
- 핸들러에는 업무 기본값을 추가하지 않는다.
- 서비스 직접 호출도 bound principal과 전달된 이메일을 검증한다.

#### 5.5 폴백 금지

멀티유저 모드에서 다음은 모두 금지한다.

- `MS365_DEFAULT_USER_EMAIL` 사용
- `AuthDatabase().list_users()[0]`
- 이메일 사전순·갱신순 계정 선택
- GraphClient의 자체 기본 계정 선택
- 인증 실패 후 다른 사용자로 재시도
- `_auto_reauth()`를 통한 서버 브라우저 실행
- DB에서 새로 추가된 이메일을 찾아 인증 성공 계정 추정
- `session/session_manager.py`의 legacy 세션 재사용

`resolve_user_email()`은 멀티유저에서 현재 principal만 참조한다. principal이 없으면 `missing_principal`로 실패하며 legacy resolver를 호출하지 않는다.

---

### 6. 인증정보 완전 분리

#### 6.1 저장 구조

사용자 토큰은 **사용자별 DB 파일**을 사용한다.

```text
data/users/<user_key>/auth/auth.db
```

이 DB에는 다음 데이터만 둔다.

| 테이블 | 주요 필드 |
|---|---|
| `store_owner` | `user_key`, `tenant_id`, `object_id`, `schema_version` |
| `graph_tokens` | `app_id`, `token_version`, `ciphertext`, `nonce`, `dek_version`, `expires_at`, `scope`, `updated_at` |
| `api_credentials` | `kid`, `digest`, `scopes`, `expires_at`, `revoked_at`, `created_at` |
| `oauth_attempts` | `attempt_id`, `state_hash`, 예상 계정, 브라우저 바인딩, 암호화된 verifier, nonce, 만료, 상태 |

DB를 열 때 `store_owner`가 요청 principal과 같은지 확인한다. 파일 경로가 사용자 루트 안에 있다는 사실만으로 소유권을 신뢰하지 않는다.

앱 설정은 `data/system/app_config.db`로 분리한다. 여기에는 client ID·tenant 허용 목록·redirect URI·scope와 **비밀 참조값**만 저장한다. client secret 원문은 저장하지 않는다.

#### 6.2 암호화와 키 관리

- access token·refresh token·저장이 필요한 ID token·PKCE verifier는 AES-256-GCM으로 암호화한다.
- 사용자마다 독립적인 256비트 DEK를 생성한다.
- 암호화할 때마다 새로운 96비트 nonce를 생성한다.
- AAD에는 `deployment_id`, `user_key`, `app_id`, 레코드 종류, 스키마 버전, 레코드 버전을 포함한다.
- B의 ciphertext를 A의 DB로 복사하면 복호화가 실패해야 한다.
- 평문 token은 SQL 파라미터·WAL·임시파일에 들어가기 전에 애플리케이션 계층에서 암호화한다.
- 복호화 실패 시 해당 요청을 실패시키고 다른 키·사용자·평문 저장 방식으로 폴백하지 않는다.

운영 KEK는 **Azure Key Vault의 RSA 키**로 두고 `RSA-OAEP-256`으로 DEK를 wrap한다. 저장소에는 wrapped DEK와 Key Vault key version 참조만 남긴다. Azure 환경에서는 managed identity로 접근한다. 키 원문을 `.env`, 코드, SQLite, 번들에 넣지 않는다. [Azure Key Vault 키와 알고리즘](https://learn.microsoft.com/en-us/azure/key-vault/keys/about-keys-details)

**가정:** 최초 운영 멀티유저 환경은 managed identity와 Key Vault를 사용할 수 있다. 이를 사용할 수 없는 운영 환경에서는 승인된 별도 KEK provider를 먼저 구현해야 하며, 평문 파일 키로 자동 대체하지 않는다. 테스트에는 별도의 메모리 key provider를 사용한다.

키 회전은 다음과 같이 구분한다.

- KEK 회전: 기존 DEK를 새 KEK version으로 다시 wrap한다.
- DEK 회전: 사용자별 lock 아래 토큰을 새 DEK로 재암호화한 뒤 원자적으로 전환한다.
- 구버전 키 제거는 모든 live 데이터와 보존 중인 백업의 참조를 확인한 후 수행한다.

#### 6.3 refresh 동시성

모든 refresh는 `session/token_store.py`의 단일 진입점으로 통합한다.

```python
async def get_graph_access_token(
    principal: Principal,
    *,
    minimum_ttl_seconds: int = 120,
) -> AccessToken:
    ...
```

순서:

1. principal의 계정 상태·auth_epoch 확인.
2. `(user_key, app_id)`의 프로세스 내 lock 획득.
3. 같은 키의 프로세스 간 OS 파일 lock 획득.
4. DB에서 최신 토큰과 `token_version` 재조회.
5. 여전히 갱신이 필요할 때만 token endpoint 호출.
6. 새 refresh token이 있으면 이전 값을 대체.
7. 기존 version을 조건으로 트랜잭션 저장.
8. lock 해제.

초기 버전의 저장소는 **단일 호스트의 로컬 파일시스템**으로 제한한다. 여러 도메인·worker 프로세스는 허용하지만 NFS/SMB 공유 SQLite와 다중 호스트 동시 쓰기는 지원하지 않는다.

OS lock은 프로세스 종료 시 해제되는 방식을 사용한다. 네트워크 호출 동안 SQLite write transaction을 잡고 있지 않는다. lock 대기 시간은 기본 30초이며 시간 초과 시 재시도 가능한 오류를 반환한다.

로컬 “refresh 만료 예상일”만으로 유효한 토큰을 버리지 않는다. 실제 token endpoint의 `invalid_grant` 등을 재연결 신호로 사용한다. 새 refresh token을 받으면 이전 토큰을 교체하며, 이전 토큰이 공급자에서 즉시 폐기된다고 가정하지 않는다. [Microsoft refresh tokens](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens)

#### 6.4 OAuth 연결과 state 바인딩

멀티유저에서는 도메인별 CallbackServer를 띄우지 않는다. 중앙 `session/auth_gateway.py`가 연결 API와 콜백을 담당한다.

| 엔드포인트 | 인증·용도 |
|---|---|
| `POST /auth/graph/start` | bearer 인증 후 본인 연결 시도 생성 |
| `GET /auth/graph/connect` | 짧은 수명의 일회 browser ticket을 소비하고 브라우저 바인딩 생성 |
| `GET /auth/callback` | state·브라우저 바인딩·PKCE·OIDC 결과 검증 |
| `GET /auth/attempts/{attempt_id}` | bearer로 본인 인증 시도의 상태만 조회 |
| `DELETE /auth/graph/connection` | bearer로 본인의 Graph 연결 해제 |

흐름은 다음으로 고정한다.

1. `start`에서 principal과 `auth_epoch`를 인증 시도에 저장한다.
2. 60초 유효한 일회 browser ticket을 반환한다. URL에는 bearer key를 넣지 않는다.
3. 브라우저가 `connect`를 방문하면 시도별 `Secure`, `HttpOnly`, `SameSite=Lax` 쿠키를 발급한다.
4. 256비트 이상 state, PKCE verifier와 S256 challenge, OIDC nonce를 생성한다.
5. state는 해시로 저장하며, 인증 시도는 10분 만료다.
6. 사용자별 pending 시도는 최대 3개다.
7. 콜백에서 state·만료·브라우저 바인딩·예상 계정·현재 auth_epoch를 확인한다.
8. `pending → redeeming` 전환은 원자적으로 수행한다. 하나의 콜백만 code 교환을 수행할 수 있다.
9. ID token의 서명·issuer·audience·시간·nonce·tenant 허용 목록을 검증한다.
10. ID token의 `(tid, oid)` 및 Graph `/me.id`가 등록된 예상 계정과 일치해야 한다.
11. 검증 성공 후에만 해당 사용자의 DB에 암호화한 토큰을 저장한다.
12. 결과는 상태와 연결된 계정 정보만 반환한다. access/refresh token을 반환하지 않는다.

PKCE와 OIDC를 authorization code flow에 적용한다. 이메일·`preferred_username`은 변경 가능하므로 소유권 키로 사용하지 않는다. [Entra authorization code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow), [ID token claims](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference)

state 조회용 전역 인덱스가 필요하면 `state_hash → user_key, attempt_id` 위치 정보만 registry에 둔다. verifier·nonce·브라우저 바인딩 등 실제 인증 상태는 사용자 DB에 둔다.

잘못된 state와 OAuth 오류는 **그 시도 외의 상태를 변경하지 않는다**. 전역 Event·전역 authenticated_email은 사용하지 않는다. code 교환 이후 결과가 불명확해지면 같은 code를 재사용하지 않고 새 연결을 요구한다.

#### 6.5 폐기·연결 해제·계정 삭제

세 동작을 구분한다.

| 동작 | 결과 |
|---|---|
| bearer key 폐기 | 해당 키로 새 요청 불가. 다른 유효 키·Graph 연결은 유지 가능 |
| Graph 연결 해제 | Graph 토큰 삭제, auth_epoch 증가, 서비스 무효화. 사용자 파일은 유지 |
| 계정 삭제 | 모든 키 폐기, Graph 연결 해제, 사용자 데이터·키·캐시 삭제 절차 수행 |

계정 삭제 순서:

1. registry 상태를 `deleting`으로 바꾸고 auth_epoch를 증가시킨다.
2. 새 요청을 차단한다.
3. 진행 중 사용자 작업을 취소·drain한다.
4. 모든 프로세스의 서비스가 다음 외부 호출·저장·응답 전에 상태를 다시 확인하도록 한다.
5. 사용자 전용 배타 lock을 확보한다.
6. 토큰·API 키·OAuth 시도·DB·파일·임시파일·wrapped DEK를 삭제한다.
7. registry에는 재사용 방지용 tombstone과 필요한 감사 기록만 남긴다.

이미 Microsoft에 전달된 요청을 소급 취소할 수 있다고 보장하지 않는다. 로컬 토큰 삭제와 Entra 세션 폐기는 다르다. 조직 전체에 영향을 줄 수 있는 Entra 세션 취소는 별도 관리 작업으로 제공한다.

백업에 남은 데이터는 정해진 보존기간 내 제거한다. “live 파일 삭제”를 “모든 백업의 즉시 암호학적 삭제”로 표현하지 않는다.

---

### 7. 데이터와 파일 완전 분리

#### 7.1 사용자 키

```text
canonical_subject = "entra:v1:" + lower(UUID(tid)) + ":" + lower(UUID(oid))
user_key = SHA256(UTF-8(canonical_subject)).hexdigest()
```

- user_key는 소문자 hex 64자로 고정한다.
- 이메일을 해시한 값을 기본 user_key로 사용하지 않는다.
- 이메일 변경은 user_key와 데이터 경로를 바꾸지 않는다.
- 같은 이메일이라도 `(tid, oid)`가 다르면 별도 사용자다.
- 같은 인물이 여러 tenant에 존재하면 각각 별도 principal이다.
- 경로에 사용할 때 형식 검증과 registry 존재 확인을 모두 수행한다.
- 기존 이메일 기반 데이터는 명시적 이전 매핑을 통해서만 user_key에 귀속한다.

#### 7.2 디렉터리 레이아웃

`MS365_DATA_ROOT`는 운영자가 지정하는 **절대경로**다. 멀티유저에서는 CWD·프로젝트 루트로 자동 결정하지 않는다.

```text
<MS365_DATA_ROOT>/
  system/
    deployment.json
    registry.db
    app_config.db
    locks/
    migration/
      staging/
      quarantine/
      manifests/

  users/
    <user_key>/
      auth/
        auth.db
        wrapped_dek.json
      db/
        onenote.db
        teams.db
        metadata.db
        outlook.db
      files/
        uploads/
        downloads/
          outlook/
          onedrive/
        output/
        tmp/
          <request_id>/
      manifest.json
```

- `auth/`, `db/`, `system/`는 일반 파일 도구로 읽거나 쓸 수 없다.
- 도구의 허용 파일 루트는 해당 사용자의 `files/`다.
- 임시파일은 `files/tmp/<request_id>/`에만 생성한다.
- 토큰 DB·업무 DB·파일 루트 사이의 symlink/junction 연결을 허용하지 않는다.
- 디렉터리와 DB는 서비스 계정·관리자만 OS 수준에서 접근하도록 ACL을 설정한다.
- 백업은 사용자별 단위로 만들고 운영용 암호화 저장소에 보관한다.
- repo·wheel·배포 번들에 `data/`를 포함하지 않는다.

#### 7.3 도메인별 저장 정책

| 영역 | 목표 구조·정책 |
|---|---|
| OneNote | `db/onenote.db`. items·summaries·changes 모두 사용자 전용이다. 모든 테이블에 `owner_key`를 두고 조회·갱신·삭제·upsert에서 확인한다. |
| Teams | `db/teams.db`. auth.db에서 완전히 분리한다. 기존 사용자 조건을 owner_key 조건으로 이전한다. |
| FileHandler | `db/metadata.db`. 멀티유저에서는 SQLite만 허용하고 JSON storage는 기동 오류로 처리한다. |
| Outlook metadata | `db/outlook.db`에 processed mail·첨부파일 메타데이터를 저장한다. 전체 JSON 덮어쓰기를 제거한다. |
| downloads | 사용자별 `files/downloads/<domain>/`. 같은 파일명이어도 사용자 사이에서 공유되지 않는다. |
| output | 사용자별 `files/output/`. 공용 `./output` 사용 금지. |
| 임시파일 | 요청별 `files/tmp/<request_id>/`. downloader의 mutable 공용 temp_dir 제거. |
| OneDrive 서비스 | 원격 접근은 사용자 고정 token provider. 로컬 저장이 발생하면 동일 UserPaths 계약을 사용한다. |
| Calendar·Todo | 개인 DB가 필요하지 않더라도 서비스·GraphClient·URL builder는 사용자별로 고정한다. |
| Time | 사용자 데이터 저장은 추가하지 않는다. 인증·감사 경로는 공유한다. |

OneNote의 유일성은 `(owner_key, item_id)` 또는 `(owner_key, page_id)`로 정의한다. DB 파일이 이미 분리되어 있어도 SQL의 owner 조건을 생략하지 않는다.

Graph 공유 자원이더라도 A의 요약과 B의 요약을 재사용하지 않는다. 사용자별 지시·요약 시점·권한·보존기간이 다를 수 있기 때문이다.

#### 7.4 경로 처리

`mcp_common.paths`는 기존 공개 관문으로 유지한다.

멀티유저에서 `allowed_roots()`는 현재 principal의 `files/`만 반환한다. 다음 설정은 범위를 넓히는 수단으로 사용할 수 없다.

- `MCP_ALLOWED_PATHS`
- `MCP_DATA_DIR`
- FileHandler의 홈/CWD config
- 도구 인자의 output_dir·save_path
- downloader가 생성했다는 이유만으로 추가하는 trusted_roots

멀티유저 설정과 충돌하는 공용 경로 설정이 있으면 조용히 무시하지 않고 기동 오류로 보고한다.

파일 처리 규칙:

1. 상대경로는 현재 사용자의 `files/` 기준으로 해석한다.
2. 절대경로는 같은 파일 루트 내부인 경우에만 허용한다.
3. UNC·장치 경로·Windows ADS·NUL·예약 장치명·드라이브 상대경로를 거부한다.
4. 원격 파일명은 경로가 아니라 단일 이름으로 취급한다.
5. `..`, 경로 구분자, 링크·junction·reparse point를 통한 탈출을 거부한다.
6. 최종 저장 경로를 검사한다. 상위 디렉터리 검사만으로 완료하지 않는다.
7. 새 파일은 배타 생성하거나 같은 디렉터리의 임시파일에 저장 후 원자적으로 교체한다.
8. cleanup은 해당 요청이 발급받은 temp 디렉터리만 대상으로 한다.
9. 압축 해제·변환 라이브러리의 임시파일에도 같은 제한을 적용한다.
10. 공개 응답은 절대경로 대신 사용자 파일 루트 기준 상대경로 또는 opaque file ID를 반환한다.

`resolve_safe_path()`는 검증용이며 최종 보안 경계를 혼자 담당하지 않는다. 실제 파일 열기는 `mcp_common/secure_files.py`로 모은다.

- POSIX에서는 directory handle과 `O_NOFOLLOW` 등을 사용한다.
- Windows에서는 reparse point 검사와 파일 handle의 최종 경로 검사를 수행한다.
- 검사 이후 경로를 바꿔 여는 TOCTOU 우회를 막는다.
- 경로만 받는 변환기는 서버가 소유한 요청 디렉터리에서 실행하며, 사용자가 링크를 만드는 API를 제공하지 않는다.

#### 7.5 파일 다운로드·Graph URL 정책

파일을 HTTP로 제공할 경우 반드시 인증된 다운로드 경로를 사용한다. `file_id → owner_key, relative_path` 조회 후 소유권을 검사한다. 사용자 디렉터리를 정적 웹 루트로 mount하지 않는다.

`mail_query_url`은 Graph 호스트 확인에 더해 해당 도구의 허용 method·path를 검사한다.

- 초기 허용 범위는 현재 사용자 메일 조회에 필요한 `/me/...` 및 현재 연결 계정과 같은 `/users/{id}/...` 경로로 제한한다.
- 타 사용자 식별자로 임의 전환하는 URL은 거부한다.
- 다음 페이지 URL도 같은 정책으로 검사한다.
- Authorization header를 가진 요청은 임의 redirect를 따라가지 않는다.
- Graph가 반환한 사전 서명 다운로드 URL에는 Graph bearer를 붙이지 않는다.
- 임의 URL·redirect로 내부 관리 endpoint나 다른 MCP 도메인을 호출하지 못하게 한다.

#### 7.6 서비스·GraphClient 수명관리

전역으로 유지해도 되는 객체는 immutable spec·도구 정의·서비스 factory·인증 관문·서비스 풀이다. 전역 개인 서비스 인스턴스는 제거한다.

캐시 키:

```text
(user_key, domain, auth_epoch)
```

운영 기본값:

| 항목 | 값 |
|---|---:|
| 프로세스별 사용자 서비스 항목 상한 | 128 |
| 유휴 TTL | 10분 |
| 사용자별·도메인별 동시 작업 상한 | 8 |
| 초기화 중 동일 키의 중복 생성 | 금지 |
| 실행 중 항목 강제 퇴거 | 금지 |

- factory는 principal·UserPaths·사용자 고정 token provider를 받는다.
- GraphClient는 생성 후 사용자를 변경하지 않는다.
- 세션 기본 헤더에 bearer를 저장하지 않고 요청마다 사용자 provider에서 얻는다.
- URL builder는 무상태 또는 사용자 고정 객체다.
- 작업 중 서비스는 lease로 보호한다.
- 전부 사용 중이라 상한을 초과하면 기존 객체를 빼앗지 않고 부하 제한 오류를 반환한다.
- 서비스 close는 자신이 소유한 HTTP 세션·작업 자원만 닫는다.
- token provider의 호환 `close()`는 차용 해제 또는 no-op이며 공용 인증 서비스를 종료하지 않는다.
- 계정 삭제·연결 해제·auth_epoch 변경 시 이전 항목은 신규 lease 대상에서 제외한다.
- auth_epoch와 계정 상태를 토큰 획득·외부 호출·저장·응답 전에 확인한다.

---

### 8. 기존 데이터 마이그레이션과 하위호환

#### 8.1 모드 전환

| 설정 | 동작 |
|---|---|
| `MS365_MULTI_USER` 미설정 또는 `0` | 기존 단일 운영자 구조와 도구 계약 유지 |
| `MS365_MULTI_USER=1`, HTTP | 본 사양 적용. 필수 보안 설정 누락 시 기동 실패 |
| `MS365_MULTI_USER=1`, stdio | 기동 실패 |
| legacy 코드가 멀티유저 저장 루트를 열려고 함 | deployment marker 확인 후 거부 |
| 멀티유저 코드가 legacy DB로 폴백하려 함 | 거부 |

`deployment.json`에 배포 ID·저장 형식·스키마 버전을 기록한다. mode는 프로세스 기동 시 확정하며 요청이나 사용자 입력으로 변경할 수 없다.

기존 배포는 기본 mode가 유지되므로 자동으로 깨지지 않는다. 다만 완전 격리 보장은 mode 1에만 해당한다.

#### 8.2 이전 도구

`python -m tools.migrate_multi_user`에 다음 하위 명령을 제공한다.

```text
plan      소스 구조·소유자 매핑·충돌·격리 대상을 검사
apply     확정 manifest에 따라 staging에 이전
verify    행 수·소유권·파일 hash·격리 불변조건 검증
activate  운영 중지 확인 후 대상 저장소 활성화
```

명령행으로 토큰·client secret·bearer key를 받지 않는다. manifest에는 legacy 이메일과 검증된 `(tid, oid, user_key)` 매핑, 파일 귀속, 원본 hash, 대상 경로를 기록한다.

#### 8.3 데이터별 이전

| 원본 | 이전 방법 |
|---|---|
| `auth.db` 앱 설정 | 비밀 아닌 설정만 `system/app_config.db`로 이전하고 secret은 Key Vault에 등록한다. |
| `auth.db` 사용자·토큰 | 이메일을 새 신원으로 신뢰하지 않는다. 사용자는 새 OIDC 연결을 완료해야 한다. 기존 토큰을 멀티유저 저장소로 단순 복사하지 않는다. |
| `auth.db.teams_chats` | legacy user_id의 명시적 매핑으로 사용자별 teams.db에 분할한다. |
| `onenote_items` | user_id 매핑으로 분할하되 Graph 재동기화로 소유권·현재 상태를 확인한다. |
| `onenote_page_summaries` | 기존 전역 upsert로 소유권이 섞였을 수 있으므로 이전본은 격리 보관하고 사용자별로 다시 생성한다. |
| `onenote_page_changes` | 소유권이 확인되는 행만 분할한다. 불명확한 행은 격리한다. |
| `metadata.db`·`metadata.json` | owner 열이 없으므로 자동 추정하지 않는다. 명시된 단일 소유자 또는 행별 manifest가 필요하다. |
| `mail_metadata.json` | 소유자 확인 후 사용자별 outlook.db로 변환한다. processed 상태도 사용자를 기준으로 분리한다. |
| `downloads/`, `output/` | 파일·디렉터리별 명시 소유자 매핑으로 복사하고 경로 참조를 갱신한다. |
| 시스템 temp | 정상 업무 데이터로 이전하지 않는다. 필요 파일은 운영자가 소유자를 확인한 후 별도 편입한다. |
| 기존 로그·백업 | 서비스 허용 루트 밖의 관리자 전용 격리 영역으로 이동한다. |

불명확한 데이터를 모든 사용자에게 복사하거나 이메일 문자열이 포함된 파일명만으로 소유자를 결정하지 않는다.

기존 전역 UNIQUE 충돌로 덮어쓴 데이터는 DB 분할만으로 복구할 수 없다. 원격 원본 재조회·요약 재생성을 사용한다.

#### 8.4 적용 순서와 롤백

1. 운영 서버·콜백·백그라운드 작업을 정지한다.
2. DB는 SQLite backup 방식으로 일관된 snapshot을 만든다. 실행 중 파일과 WAL을 임의 복사하지 않는다.
3. 원본 파일 hash와 manifest를 확정한다.
4. staging에 사용자별 저장소를 생성한다.
5. 새 Graph 연결을 완료한다.
6. 이전·재동기화·격리 검증을 수행한다.
7. 사용자 A/B 교차 접근 smoke test를 수행한다.
8. 같은 볼륨에서 staging을 원자적으로 활성화한다.
9. mode 1로 재기동한다.
10. legacy 저장소는 서비스 경로 밖에서 읽기 전용으로 보관한다.

이전 도구는 manifest hash와 단계 checkpoint를 사용하여 재실행 가능해야 한다.

새 저장소에 업무 쓰기가 발생하기 전에는 legacy snapshot으로 롤백할 수 있다. 새 쓰기가 발생한 뒤에는 mode만 `0`으로 바꾸지 않는다. 별도의 역이전 또는 데이터 조정이 필요하다.

---

### 9. 로깅과 감사

감사 로그는 일반 사용자 파일 영역 밖의 관리자 전용 sink에 저장한다.

허용 필드:

```text
timestamp, deployment_id, request_id, user_key,
credential_id, auth_epoch, domain, tool,
event, outcome, error_code, duration_ms
```

필요한 경우 리소스 식별자는 별도 감사 키로 HMAC 처리한 값만 기록한다.

기록할 사건:

- bearer 인증 성공·실패·scope 거부
- `user_email` 불일치
- 경로 경계 위반
- OAuth 시작·완료·실패·계정 불일치·replay
- 토큰 refresh 성공·실패
- 키 발급·회전·폐기
- 사용자 비활성화·삭제
- 마이그레이션·관리 설정 변경

기록하지 않을 값:

- bearer key·access/refresh/id token 및 일부 prefix
- Authorization·Cookie 헤더
- OAuth code·state·PKCE verifier·nonce·browser ticket
- 이메일·메일 제목·본문·파일 내용·페이지 요약
- 공유 URL·사전 서명 URL
- 사용자 절대경로
- 외부 오류 response body와 민감한 예외 원문

기존 `print`, logger 호출, CLI token prefix 출력도 수정 대상이다. 공용 logging filter만으로 모든 유출을 막았다고 간주하지 않는다.

프록시·Uvicorn·aiohttp access logger에도 콜백 query string 비기록 정책을 적용한다. 외부 오류는 정해진 코드와 request_id로 변환한다. SDK에 전달하는 예외에도 비밀을 넣지 않는다.

---

### 10. 격리 검증 테스트

테스트는 임시 데이터 루트·가짜 토큰 서버·가짜 Graph 서버를 사용한다. 실제 사용자 DB나 네트워크 계정에 의존하지 않는다.

기존 테스트를 대체하지 않고 아래 격리 회귀를 추가한다.

| ID | 테스트 | 통과 조건 |
|---|---|---|
| I01 | 8개 HTTP 서버의 무인증 initialize/list/call/notification/GET/DELETE | 인증 관문 이전에 개인 서비스·DB가 열리지 않음 |
| I02 | A bearer + B `user_email` | `identity_mismatch`, B token store 호출 0회 |
| I03 | 이메일 생략 | A만 사용, 환경변수·legacy DB 조회 0회 |
| I04 | 이메일 null·빈 문자열·잘못된 타입 | 명시적 입력 오류 |
| I05 | 동일 이메일·서로 다른 tenant/oid | 별도 user_key·DB·서비스 |
| I06 | 위조 principal/user_key/db_path 인자 | 추가 입력 거부 |
| I07 | 만료·폐기·scope 부족 키 | 정해진 401/403, 데이터 접근 0회 |
| I08 | B MCP session ID·위조 사용자 헤더 | 신원 변경 불가 |
| C01 | A/B 요청을 await 경계에서 교차 실행 | 각 호출의 principal·응답이 일치 |
| C02 | 예외·취소 후 다음 요청 실행 | 이전 ContextVar가 남지 않음 |
| C03 | thread 작업·파일 변환 | A 컨텍스트 유지, 누락 시 실패 |
| A01 | B ciphertext를 A DB에 복사 | AAD/owner 검증 실패 |
| A02 | DB·WAL·백업·로그에 토큰 canary 검색 | 평문 토큰 없음 |
| A03 | 두 프로세스가 A token 동시 refresh | token endpoint 갱신 1회, 새 refresh token 보존 |
| A04 | A와 B 동시 refresh | 사용자 사이의 불필요한 전역 직렬화 없음 |
| A05 | refresh 중 폐기·연결 해제 | 폐기 후 결과 저장·신규 Graph 호출 차단 |
| O01 | A/B OAuth를 역순 완료 | 각 시도와 저장소가 정확히 대응 |
| O02 | A 연결 시도에 B 계정 로그인 | 저장 전 거부 |
| O03 | state replay·만료·없는 state·오류 콜백 | 해당 시도만 실패, 다른 시도 불변 |
| O04 | code 가로채기·다른 브라우저·nonce 불일치 | PKCE/브라우저/OIDC 검증 실패 |
| O05 | OAuth 중 프로세스 재시작 | 안전하게 복구하거나 새 연결 요구, 다른 사용자로 매칭하지 않음 |
| D01 | A에서 B page_id 요약 조회 | B 요약 미반환 |
| D02 | A에서 B page_id 삭제, Graph 404 | B summary·changes 불변 |
| D03 | A/B가 같은 Graph page_id 사용 | 각 요약·이력 독립 |
| D04 | A/B가 같은 chat_id 사용 | topic·활성 상태 독립 |
| D05 | A metadata 전체 검색·B URL 조회/삭제 | A 데이터만 반환, B 데이터 불변 |
| F01 | traversal·UNC·ADS·장치경로·symlink·junction | 모든 읽기·쓰기·삭제 경계에서 거부 |
| F02 | 원격 첨부 이름 `../...`·절대경로 | 사용자 파일 루트 탈출 불가 |
| F03 | A와 B 동일 파일명 동시 다운로드 | 저장 경로·내용 독립 |
| F04 | 동일 사용자 동시 파일 생성 | 덮어쓰기·metadata lost update 없음 |
| F05 | A cleanup 중 B 처리 | B temp 유지 |
| F06 | auth.db·업무 DB를 파일 도구로 읽기 | 자기 사용자 DB라도 거부 |
| F07 | 환경변수·홈 config로 공용 경로 지정 | mode 1 기동 실패 |
| G01 | 임의 URL·redirect·다른 사용자 Graph path | 토큰 전달·우회 접근 차단 |
| G02 | Graph 사전 서명 다운로드 URL | Graph Authorization 헤더 미전송 |
| L01 | 서비스 A 퇴거 | B HTTP 세션·provider·콜백에 영향 없음 |
| L02 | 캐시 상한·TTL·동시 초기화 | 상한 준수, 중복 생성 없음, 사용 중 자원 유지 |
| R01 | 로그·오류·health·CLI에 민감 canary 입력 | 민감정보 비노출, principal·request_id 추적 가능 |
| M01 | 모호한 legacy metadata/file 소유권 | quarantine 처리, 전 사용자 복사 없음 |
| M02 | 마이그레이션 중단 후 재실행 | 중복·누락 없이 checkpoint 복구 |
| M03 | mode 0/1 저장소 교차 사용 | 기동 거부 |
| B01 | 기존 mode 0 stdio·HTTP | 기존 도구 계약·기본 동작 회귀 통과 |
| B02 | mode 1 stdio | 명시적 기동 오류 |
| B03 | 실제 지원 클라이언트 | 매 요청 bearer 전달 및 stateless 동작 확인 |

추가 정적 검증:

- 멀티유저 실행 경로에서 인자 없는 `AuthDatabase()`·`AuthManager()` 생성이 없어야 한다.
- 도메인에 무제한 사용자 서비스·토큰 캐시가 없어야 한다.
- 실제 사용자 파일을 여는 경로가 안전한 파일 관문을 통과해야 한다.
- param_spec과 서비스 호출 인자의 불일치가 없어야 한다.
- 신규·수정 파일이 1,200줄을 넘지 않아야 한다.
- Todo 테스트 경로와 새 통합 테스트 경로를 `pyproject.toml` testpaths에 등록한다.

본 문서 작성 과정에서 이 테스트들을 실행한 것은 아니다. 모든 항목은 구현 완료 판정 기준이다.

---

### 11. 병렬 구현을 위한 공용 인터페이스

#### 11.1 WP0에서 먼저 고정할 계약

다음은 **새로 구현할 인터페이스**다. 기존 코드에 존재한다고 가정하지 않는다.

```python
# mcp_common/principal.py
def current_identity() -> RequestIdentity | None: ...
def require_principal() -> Principal: ...

@contextmanager
def bind_identity(identity: RequestIdentity) -> Iterator[None]: ...

def assert_owner(owner_key: str) -> Principal: ...
def assert_user_email(explicit: object = MISSING) -> str: ...


# mcp_common/user_paths.py
@dataclass(frozen=True, slots=True)
class UserPaths:
    root: Path
    auth_db: Path
    wrapped_dek: Path
    onenote_db: Path
    teams_db: Path
    metadata_db: Path
    outlook_db: Path
    files: Path
    uploads: Path
    downloads: Path
    output: Path
    tmp: Path

def paths_for(principal: Principal) -> UserPaths: ...


# mcp_common/security_contracts.py
@dataclass(frozen=True, slots=True)
class AccessToken:
    value: str  # repr=False
    expires_at: datetime
    token_version: int

class BoundTokenProvider(Protocol):
    @property
    def user_key(self) -> str: ...

    async def get_graph_token(
        self, *, minimum_ttl_seconds: int = 120
    ) -> AccessToken: ...

    async def close(self) -> None: ...
    # 차용 해제/no-op. 공용 인증 자원 종료 금지.

class ManagedService(Protocol):
    async def initialize(self) -> None: ...
    async def close(self) -> None: ...


# session/identity_registry.py
async def authenticate_bearer(
    authorization: str, *, domain: str
) -> Principal: ...

async def assert_active(principal: Principal) -> None: ...


# mcp_common/auth.py
def get_bound_token_provider(
    principal: Principal
) -> BoundTokenProvider: ...


# mcp_common/service_pool.py
ServiceFactory = Callable[
    [Principal, UserPaths, BoundTokenProvider],
    Awaitable[ManagedService],
]

class UserServicePool:
    def register(self, domain: str, factory: ServiceFactory) -> None: ...

    @asynccontextmanager
    async def lease(
        self, domain: str, principal: Principal
    ) -> AsyncIterator[ManagedService]: ...

    async def invalidate(self, user_key: str) -> None: ...
    async def close(self) -> None: ...


# 各 mcp_<domain>/mcp_server/handlers.py
async def create_service(
    principal: Principal,
    paths: UserPaths,
    tokens: BoundTokenProvider,
) -> ManagedService: ...


# DB를 사용하는 각 도메인의 storage_schema.py
def ensure_storage(
    principal: Principal,
    paths: UserPaths,
) -> None: ...
```

추가 계약:

- `paths_for()`는 디렉터리를 생성하거나 DB를 열지 않는다. 경로를 계산하고 검증만 한다.
- `ensure_storage()`는 해당 사용자 저장소만 초기화한다. Graph 호출·기본 사용자 탐색을 하지 않는다.
- 모든 factory는 async이며 동기 FileHandler는 해당 WP의 async adapter가 감싼다.
- 서비스 factory 등록은 handler가 담당한다. 공용 WP가 도메인 파일을 수정하지 않는다.
- `get_shared_auth_manager()`는 legacy mode 0 전용으로 남긴다. mode 1 호출은 명시적 오류다.
- 기존 email 기반 provider 메서드가 필요한 과도기 adapter는 내부에서 이메일 일치를 확인하고 bound provider에 위임한다. 계정을 선택하지 않는다.
- security exception은 `mcp_common/security_contracts.py`의 고정 오류 코드로 정의한다.
- 공용 계약 변경은 WP0 담당자만 수행하며 version을 올린다. 각 에이전트가 임의로 함수명을 바꾸지 않는다.

#### 11.2 파일 소유 원칙

- 표의 디렉터리 소유는 해당 하위 코드·테스트와 새 보조 모듈을 포함한다.
- 별도 표기하지 않은 타 WP 파일은 수정하지 않는다.
- 도메인 WP는 자신이 소유한 로그 호출도 수정한다. 감사 WP가 도메인 파일을 동시에 수정하지 않는다.
- 의존 WP가 끝나지 않아도 WP0의 Protocol·fake 구현으로 작업할 수 있다.
- 스키마·동작·테스트를 갖춘 상태를 완료로 판단하며, 단순 stub 작성은 완료가 아니다.

#### 11.3 작업 패키지

| WP | 소유 파일 목록 | 소비·제공 인터페이스 | 완료 기준 | 의존 |
|---|---|---|---|---|
| **WP0 기반** | 신규 `mcp_common/principal.py`, `user_paths.py`, `security_contracts.py`, `security_policy.py`; `core/protocols.py`; 신규 `mcp_common/tests/test_security_contracts.py` | 위 공용 타입·시그니처·오류 코드·mode 정책 | immutable principal, user_key 규칙, mode 검증, 인터페이스 계약 테스트 확정 | 없음 |
| **WP1 HTTP·런타임** | `mcp_common/http_transport.py`, `stdio_transport.py`, `runtime.py`, `user_resolver.py`, `validation.py`, `errors.py`, `net.py`, `param_spec.py`; 신규 `http_identity.py`, `mcp_identity_bridge.py`; 해당 공용 테스트 | `authenticate_bearer`, `bind_identity`, `assert_user_email`, 서비스 pool | 8개 서버 공용 인증, SDK 메시지별 컨텍스트, stateless 정책, legacy 폴백 차단, 안전한 오류 | WP0; 통합 시 WP2·WP3 |
| **WP2 인증·OAuth** | `session/**`, `callback_server.py`, `mcp_common/auth.py`, `main.py`, `_reauth.py` | `authenticate_bearer`, `assert_active`, bound provider, OAuth 연결 API | 사용자별 암호화 DB, KEK 연동, 프로세스 간 refresh lock, 계정 바인딩 OAuth, 폐기·삭제 제어 | WP0 |
| **WP3 경로·서비스 풀** | `mcp_common/paths.py`; 신규 `secure_files.py`, `service_pool.py`, `user_leases.py`; 지정 신규 공용 테스트 | `UserServicePool`, 안전한 파일 열기·저장, 사용자 작업 lease | LRU·TTL·중복 생성 방지, 사용자 경로 경계, TOCTOU 방어, drain 및 정리 | WP0; 인증 상태 통합은 WP2 |
| **WP4 Outlook** | `mcp_outlook/**`; `spec/param_spec/outlook.yaml` | `create_service`, `ensure_storage`, bound provider·UserPaths | 공유 다운로드·JSON metadata 제거, 모든 첨부 provider 전달, Graph URL 정책, 사용자별 close·로그 | WP0; 통합 시 WP1–3 |
| **WP5 OneNote** | `mcp_onenote/**`; `spec/param_spec/onenote.yaml` | 동일 factory·저장소 계약 | 모든 SQL owner 조건, 요약 IDOR·삭제 IDOR 제거, 사용자별 summary·changes·agent | WP0; 통합 시 WP1–3 |
| **WP6 Teams** | `mcp_teams/**`; `spec/param_spec/teams.yaml` | 동일 factory·저장소 계약 | auth.db 의존 제거, 전용 teams.db, 사용자별 채팅 상태·클라이언트 | WP0; 통합 시 WP1–3 |
| **WP7 OneDrive** | `mcp_onedrive/**`; `spec/param_spec/onedrive.yaml` | 동일 factory 계약 | provider 고정, 폴백 제거, 사용자별 클라이언트·로그·경로 정책 | WP0; 통합 시 WP1–3 |
| **WP8 Calendar·Todo·Time** | `mcp_calendar/**`, `mcp_todo/**`, `mcp_time/**`; 해당 3개 YAML | 동일 factory 계약 | Calendar/Todo 개인 상태 분리, URL builder·종료 소유권 수정, Time 인증 연동, Todo 테스트 신설 | WP0; 통합 시 WP1–3 |
| **WP9 FileHandler** | `mcp_file_handler/**`; `spec/param_spec/file_handler.yaml` | async factory, `ensure_storage`, UserPaths·secure_files·bound provider | 별도 AuthManager 제거, SQLite metadata 격리, 요청별 temp/OCR, executor 인증 브리지 제거, health 경로 노출 제거 | WP0; 통합 시 WP1–3 |
| **WP10 감사·부트스트랩** | `mcp_common/bootstrap.py`; 신규 `mcp_common/audit.py`, `log_redaction.py`; 지정 신규 공용 테스트 | `audit(event, *, principal, request_id, outcome, error_code, domain, tool)` | 허용 필드 감사, stderr/stdout 규칙 유지, 기본 logger 안전화, 민감정보 회귀 | WP0 |
| **WP11 이전·배포·문서** | 신규 `tools/migrate_multi_user/**`; `.claude/skills/setup_ms365/**`, `.claude/skills/export_ms365/**`; `pyproject.toml`, `uv.lock`, `requirements.txt`, `MANIFEST.in`, `.gitignore`, `.env.example`, `README.md`, `CLAUDE.md`; 관련 `spec/` 문서와 `references/` 문서 **단, param_spec YAML 제외** | 도메인 `ensure_storage`, WP2 등록·연결·관리 API | plan/apply/verify/activate, 격리 보관, 모드별 설치·probe, 비밀 번들 제외, 의존성·문서 갱신 | plan은 WP0 후 병렬; apply/verify는 WP2·4–9 이후 |
| **WP12 통합 검증** | 신규 `tests/multi_user/**`; 루트 `conftest.py` | 공용 공개 인터페이스와 전체 HTTP 서버 | A/B 교차 접근·다중 프로세스 refresh·OAuth·마이그레이션·실제 클라이언트 검증 | WP0 후 fixture 작업; 최종 판정은 모든 WP 이후 |

WP1·WP3·WP10의 `mcp_common/tests` 파일은 소유 WP별로 구분한다. 예를 들어 `test_multiuser_http_*`, `test_user_paths_*`, `test_audit_*`를 사용하여 파일 충돌을 방지한다. 기존 테스트 파일의 수정자는 해당 기능을 소유한 WP 한 곳으로 지정한다.

WP11이 lockfile·의존성 파일을 단독 소유한다. 다른 WP는 필요한 라이브러리·최소 버전을 전달하고 해당 파일을 직접 수정하지 않는다.

#### 11.4 의존 순서와 병합 관문

```text
WP0 계약 고정
  ├─ WP1 HTTP·런타임
  ├─ WP2 인증·OAuth
  ├─ WP3 경로·서비스 풀
  ├─ WP4~WP9 도메인 전환
  ├─ WP10 감사
  ├─ WP11 이전 plan·배포 준비
  └─ WP12 테스트 fixture
           ↓
공용 계층 통합
           ↓
도메인별 격리 테스트
           ↓
이전 apply/verify + 배포 probe
           ↓
전체 A/B 격리·실제 클라이언트 검증
           ↓
멀티유저 출시
```

최종 출시 관문:

- 모든 도메인의 mode 1 실행 경로에서 legacy 기본 사용자 선택이 차단되어야 한다.
- 전체 격리 테스트가 통과해야 한다.
- 실제 클라이언트의 bearer·stateless 호환성이 확인되어야 한다.
- 운영 KEK·HTTPS·ACL·백업 정책이 구성되어야 한다.
- 마이그레이션 verify에 미해결 소유권 충돌이 없어야 한다.
- 격리 보관 데이터가 일반 사용자에게 노출되지 않아야 한다.

### 12. 구현 착수 시 확정한 조정 (2026-10-22, 오케스트레이터)

설계(1~11)는 astra(Codex gpt-6-astra)가 작성했고, 병렬 구현을 위해 아래를 확정했다.

1. **WP0 범위 확대** — 병렬 WP 가 stub 이 아니라 동작하는 코드에 붙도록 다음까지 WP0 이 구현한다:
   `mcp_common/principal.py`, `user_paths.py`, `security_contracts.py`, `security_policy.py`,
   `service_context.py`, `service_pool.py`, `secure_files.py`(시그니처 고정, WP3 강화),
   `audit.py`(허용 필드 계약, WP10 확장), `testing.py`(테스트 전용 fake). 계약 테스트는
   `mcp_common/tests/test_security_contracts.py`.
2. **도메인 배선 패턴** — `service_context.py` docstring 의 패턴 하나로 통일한다:
   `create_service(principal, paths, tokens)` 는 **생성만** 하고, 풀이 `ensure_user_dirs` →
   factory → `initialize()` 를 부른다. 전역 서비스는 mode 0 에서만 만든다
   (`None if multi_user_enabled() else Service()`), 핸들러는 `service_for(SERVER_NAME, legacy=...)`.
3. **`SecurityError` 는 `ToolExecutionError` 하위 클래스** — 기존 런타임 오류 경로를 그대로 타고
   `isError=True` 로 나간다. 페이로드는 `{"status":"error","error":<code>,"message":...}` 고정.
4. **연결 안내 계약** — `mcp_common.auth.graph_connect_details(principal) -> dict` (WP2 구현).
   런타임(WP1)은 `graph_not_connected`/`graph_reauth_required` 오류에 이 dict(`connect_url`,
   `expires_in`)를 붙인다. 사람이 에이전트 응답을 읽고 클릭하므로 **browser ticket TTL 은 300초**
   (설계 4.4 의 60초에서 조정). 1회용·브라우저 쿠키 바인딩·예상 `(tid, oid)` 검증은 유지.
5. **KEK provider 는 명시 선택, 자동 폴백 없음** — `MS365_KEK_PROVIDER` =
   `azure_keyvault`(운영 권고, optional 의존성) | `dpapi`(Windows 단일 호스트, OS 계정 바인딩) |
   `env`(`MS365_KEK_B64`, 개발용 — 기동 경고) | `memory`(`MS365_TESTING=1` 일 때만).
   미설정이면 mode 1 기동 실패. 어떤 provider 를 운영에 쓸지는 ④ 미결.
6. **bearer 인증 진입점** — `session.identity_registry.authenticate_bearer(header, *, domain)`
   (async, `Principal` 반환, 실패는 `SecurityError`) 와 `assert_active(principal)` (async).
   WP1 은 둘 다 주입 가능하게 받아 테스트한다.
7. **auth gateway 는 별도 프로세스** — `python -m session.auth_gateway` 가 `AZURE_REDIRECT_URI`
   포트에서 `/auth/*` 를 담당한다. 관리 CLI 는 `python -m session.admin_cli`.

### 13. 모드 0 외부 로그인 위임 계약 (AIP, 2026-10-23)

외부 웹 앱(AIP)이 자기 `/auth/callback` 에서 받은 Entra 인가 코드를 넘기면 **이 저장소가** 토큰 교환·Graph `/me`·auth.db 저장·갱신·
재인증 판정을 맡고, 호출자에게는 **신원과 연결 상태만** 돌려준다. 1차 계약은 mode 0 라이브러리 API(AIP 워커가 `from session import
AuthManager` 로 subprocess 안에서 부른다)이고, mode 1 gateway 엔드포인트(`POST /auth/token`·세션 토큰·act-as)는 ④ 후속이다. 전부
**추가(additive)** — 기존 공개 메서드의 시그니처·반환 키·동작은 바꾸지 않았다. 구현 위성 `session/external_login.py`, 관문
`AuthManager`/`AuthService`. 멀티유저 모드에서는 `LegacyAuthDisabledError` 로 거부.

| API | 입력 | 반환 / 오류 |
|---|---|---|
| `await AuthManager.complete_external_login(code, redirect_uri, scopes=None, save=True, expect_email=None)` | `code` 인가 코드 · `redirect_uri` 그 코드를 발급받은 **외부 앱의** redirect_uri · `scopes` 교환 scope(None = `config.default_scopes`, 문자열 또는 목록) · `save` False = 신원만(Graph 동의가 막혔을 때의 `openid profile email User.Read` 폴백, 저장 없음, refresh 없음 허용) · `expect_email`(2026-10-23 codex 교차 검토 ⑴) 호출자가 기대하는 계정(재연결 때의 로그인 사용자) — 값이 있으면 토큰 교환·`/me` 뒤 **저장 전에** `/me` 메일(소문자, `canonical_email` 과 같은 대소문자 무시)과 대조해 다르면 **아무것도 저장하지 않고**(신규 등록·기존 행 갱신 모두 없음) `ACCOUNT_MISMATCH`; None(기본) = 종전(무검증) | `{"email"(소문자), "display_name", "user_info"(id·displayName·mail·userPrincipalName 만), "saved", "has_refresh", "granted_scopes"(권한 이름 목록), "state"(아래 4상태)}`. access/refresh/id token 은 어떤 키·로그에도 없다. **저장 실패(save=True)는 예외가 아니다**(2026-10-23 codex 교차 검토 ⑵ — 저장이 안 돼도 호출자는 신원으로 로그인을 유지하고 미연결로 표시): 같은 꼴로 돌려주되 `"saved": false`, `"has_refresh"` 는 응답 기준, `"state"` 는 DB 기준(`connection_state(email).state` — 보통 `not_connected` 또는 기존 행 상태), **`"error": "SAVE_FAILED"`** 키가 더 있다(저장이 안 된 이유 코드만, 메시지 없음). 정상 저장·`save=False` 에는 `error` 키가 없다. 실패 = `session.ExternalLoginError`(`code` 속성 **EXCHANGE_FAILED**(교환 HTTP 오류·통신 실패·빈 입력·앱 설정 없음, `oauth_error`·`http_status` 동봉) · **USERINFO_FAILED**(`/me` 실패·메일 없음) · **ACCOUNT_MISMATCH**(`expect_email` ≠ `/me` 메일 — 저장 전 판정, `expected_email`·`actual_email` 속성(소문자)에 두 메일, 메시지·로그에는 메일 없음); `str(e)` = `"CODE|메시지"` — 워커 오류 규약과 같은 꼴, 외부 오류 본문·토큰 미포함. `SAVE_FAILED` 코드 상수는 남아 있으나 **예외로는 쓰지 않는다**(반환 `error` 키 전용)) |
| `AuthManager.connection_state(email)` | 계정 메일(대소문자 무시 — `AuthDatabase.canonical_email` 로 저장 표기를 찾는다) | `{"email", "state", "features", "granted_scopes", "access_token_expires_at"(ISO 또는 None), "refresh_token_expired"}` + `unavailable` 일 때만 `"error"`(예외 종류 이름) |

**연결 상태 4가지** — `connected`(refresh token 보유·만료 전·마지막 갱신 거부 없음. access token 만료는 갱신으로 풀리므로 connected) ·
`reauth_required`(refresh token 없음 / `refresh_token_expires_at` 경과 / 마지막 갱신이 `invalid_grant`·`interaction_required` 로 거부됨 —
`azure_token_info.refresh_state = 'reauth_required'`) · `not_connected`(토큰 행 없음) · `unavailable`(auth.db 를 읽지 못함 — 잠김·손상).
AIP 쪽 `consent_required` 는 별도 상태가 아니라 **`features` 의 기능별 False** 로 표현한다(`.default` 로 받아도 그 사용자·테넌트에 동의되지 않은
권한은 토큰 응답 `scope` 에 없다).

**features 대응표** — 저장된 granted scope(토큰 응답의 `scope`, `https://graph.microsoft.com/<권한>` 꼴·`openid` 등 혼재)를 권한 이름으로 정규화해
결정론 판정. 각 기능은 모든 묶음에서 하나 이상 보유해야 True. scope 를 모르는 구형 행은 `features`·`granted_scopes` 둘 다 None. 원본
`session/external_login.py` `FEATURE_REQUIREMENTS`(이 저장소 각 도메인이 실제로 부르는 Graph 경로 기준).

| 기능 | 필요 위임 권한(묶음마다 하나) | 근거 경로 |
|---|---|---|
| mail | {Mail.Read, Mail.ReadWrite} ∧ {Mail.Send} | Outlook `/me/messages`·`$batch` 읽기 + `sendMail`. 임시저장·회신 초안(`POST /me/messages`)은 Mail.ReadWrite 가 더 필요(판정에는 미포함) |
| teams | {Chat.Read, Chat.ReadWrite} ∧ {Chat.ReadWrite, ChatMessage.Send} | `/me/chats` 읽기 + `POST /me/chats/{id}/messages`. 첨부 업로드의 Files.ReadWrite 는 선택 |
| onenote | {Notes.ReadWrite, Notes.ReadWrite.All} | `/me/onenote/*` 조회 + 페이지 생성·PATCH(Notes.Create 만으로는 조회 불가) |
| calendar | {Calendars.ReadWrite} | `/me/events` 조회·생성·PATCH·DELETE |
| todo | {Tasks.ReadWrite} | `/me/todo/lists` 조회·생성·PATCH·DELETE(Tasks.ReadWrite.Shared 는 공유 목록용이라 제외) |

**auth.db(mode 0) 스키마** — `azure_token_info` 의 nullable 컬럼 `scope`(실제 부여 권한)·`refresh_state`('ok'|'reauth_required')를
`AuthDatabase.ensure_tables` 가 열 때마다 `PRAGMA table_info` 로 확인하고 없으면 `ALTER TABLE … ADD COLUMN` 으로 idempotent 보강한다
(mode 0 전용 — mode 1 의 명시 legacy 경로 읽기는 고치지 않아 이전 도구의 fingerprint 가 유지된다. 실패해도 기존 동작 유지, 그 컬럼만 쓰지 않음).
`save_token` 은 `scope` 를 COALESCE 로 저장(빈 문자열은 NULL)하고 새 refresh_token 이 오면 `refresh_state='ok'`(재인증 완료 = 표식 해제).
이 PC 의 실 auth.db 는 이미 `scope` 컬럼이 있었다(2026-10-23 확인) — 추가된 것은 `refresh_state` 하나.

**인증 오류 분류(AUTH_REQUIRED 판정)** — 갱신 실패를 재인증과 일시 장애로 구분한다. `AuthService.refresh_tokens` 는 `TokenRefreshError`
(`Exception` 하위, 메시지 종전 그대로, `code` = OAuth `error`, `reauth_required` = `invalid_grant`|`interaction_required`)를 던지고,
`AuthManager.refresh_token`·`AuthService.check_and_refresh_if_needed` 의 반환 dict 에 **`reason`** 키가 더해진다 — `ok` ·
`not_connected`(토큰 행 없음) · `reauth_required`(refresh 없음·만료·endpoint 거부) · `transient`(네트워크·5xx·DB — 재시도 가능). endpoint 거부일 때만
`refresh_state='reauth_required'` 를 **영구 기록**하므로 반환 형태가 `Optional[str]` 인 `validate_and_refresh_token`(None) 뒤에도
`connection_state(email).state` 로 같은 판정을 읽을 수 있다. `get_token`/`get_token_status` 에는 `refresh_state`·`state` 키만 추가(`needs_reauth` 의
종전 의미는 유지 — 거부 표식은 `state` 에만 반영). **워커가 AUTH_REQUIRED 로 분류해야 하는 조건** = `reason ∈ {not_connected, reauth_required}` 또는
`connection_state().state ∈ {not_connected, reauth_required}`; `transient`·`unavailable` 은 재시도 대상이다.

**하지 않는 것** — 토큰을 반환하는 API, AIP 쪽 범위 정의·계정 선택, 연결 해제의 새 API(기존 `remove_user(email)` = 토큰 행 삭제가 그대로 해제),
mode 1 코드 변경(`token_store`·`auth_gateway`·principal 규칙 불변).

## ③ 구현 상태

| WP | 작업 | 상태 |
|---|---|---|
| WP0 | 공용 principal·경로·보안 계약 | 완료 (2026-10-22, 계약 테스트 48건) |
| WP1 | HTTP 인증·런타임·사용자 해석 | 완료 — `mcp_common/http_identity.py`, `mcp_identity_bridge.py`, runtime·resolver·stdio 가드 |
| WP2 | 사용자별 인증 저장·OAuth·폐기 | 완료 — `session/identity_registry.py`, `token_store.py`, `key_provider.py`, `auth_gateway.py`, `admin_cli.py` 외. `app_config.db` 는 미구현(앱 설정은 env 전용, secret 비저장) |
| WP3 | 경로 보안·서비스 풀·사용자 lease | 완료 — `paths.py` mode 1 사용자 루트 한정, `secure_files.py` 강화(reparse point 전면 거부). 서비스 풀은 WP0 |
| WP4 | Outlook 분리 | 완료 — `outlook_security.py`(URL 정책), `storage_schema.py`(outlook.db), 첨부 저장 배타 생성 |
| WP5 | OneNote 분리 | 완료 — 3개 테이블 `owner_key`, `(owner_key, item_id/page_id)` 유일성, 요약 IDOR 수정(양 모드) |
| WP6 | Teams 분리 | 완료 — mode 1 `db/teams.db`, mode 0 `auth.db` 에 `owner_key` 추가 |
| WP7 | OneDrive 분리 | 완료 — 로컬 저장 없음 확인, provider 고정 |
| WP8 | Calendar·Todo·Time 전환 | 완료 — URL builder 무상태화, `mcp_todo/tests` 신설 |
| WP9 | FileHandler 분리 | 완료 — `service.py`(비동기 래퍼), 요청별 temp, executor 인증 브리지 제거 |
| WP10 | 감사·로그·부트스트랩 | 완료 — `audit.py` 파일 sink, `log_redaction.py` |
| WP11 | 마이그레이션·배포·문서 | 완료 — `tools/migrate_multi_user` (plan/apply/verify/activate, `tools/tests` 16건), pyproject(`cryptography`·`PyJWT[crypto]` 명시, `keyvault` extra)·uv.lock·`.env.example`·README·CLAUDE.md·setup/export 스킬·references 갱신 |
| WP12 | 통합 격리 검증 | 완료 — `tests/multi_user/` 14파일, 실제 8개 서버를 HTTP 로 띄워 A/B 교차 검증(시나리오 1~8). 버그 4건 발견 → 아래 수정 |

**통합 검증(WP12)이 찾은 버그와 수정 (2026-10-23)**

| 버그 | 수정 |
|---|---|
| G01 — 호출자 ID(event_id·chat_id·page_id·list/task_id·드라이브 경로)가 인코딩 없이 Graph 경로에 들어가 `../../../users/B/...` 로 A 토큰이 B 경로를 침 | 신규 `mcp_common/graph_paths.py` (`graph_segment`·`graph_drive_path` — 단일 세그먼트 인코딩, `.`/`..`/인코딩 변형 거부 → `not_found`). Calendar·Todo·OneDrive·OneNote·Teams 전부 적용, 양 모드 |
| 서비스 풀 키가 `credential_id` 를 무시해 첫 키 폐기 시 같은 사용자의 다른 유효 키도 `account_inactive` | `session/token_store.py` 계정 검사는 status·auth_epoch·(tid, oid) 만 확인(요청 키 폐기는 런타임 `assert_active` 가 담당) |
| 삭제 후 reinstate 한 사용자가 auth_epoch 0 부터 재시작 → 이전 생애의 풀 항목 재사용 | tombstone 에 `last_auth_epoch` 저장, reinstate 는 last+1 (registry.db 자동 마이그레이션) |
| ②-9 — Graph 오류 본문·`str(exc)` 가 그대로 응답에 반영 | 도메인: `graph_error_summary(status, body)` 로 status_code + 검증된 `error.code` 만. 런타임: mode 1 에서 `ToolExecutionError` 페이로드를 정화(원문 키 제거·토큰/이메일/절대경로 마스킹, `error` 가 코드 형식이 아니면 `tool_error`) — 이중 방어 |

전체 pytest: **1236 passed, 4 skipped, xfail 0** (2026-10-23 1차).

**astra 재검토(2026-10-23, [reviews/멀티유저_astra_2026-10-23.md](reviews/멀티유저_astra_2026-10-23.md)) 반영**

판정은 "출시 불가(High 2건)"였고, 아래와 같이 전부 반영했다. 편차 판정 중 "거부"였던 삭제·drain 은 프로세스 내 drain 으로 좁혀 수용했다(교차 프로세스는 ④).

| ID | 심각도 | 요지 | 수정 |
|---|---|---|---|
| R01 | High | lease 대기 후 현재 요청 키 재검사 없음 → 폐기된 키가 Graph 변경 전송 | 런타임: lease 획득 직후 `assert_active` 재검사. 토큰 저장소: 토큰 반환 전마다 `current_identity()` 의 키·계정·epoch 재검사(첫 lease 의 키는 검사하지 않음 — 같은 사용자의 다른 키를 살리는 이전 수정 유지) |
| R02 | High | Outlook `top` 무제한 → 페이지 코루틴 선생성으로 프로세스 고갈 | param_spec 에 `minimum/maximum/minItems/maxItems/minLength/maxLength` 필드 신설 + `validation.py` 강제. Outlook: `top` ≤ 1000, ID 목록 ≤ 500, 첨부 ≤ 20 을 YAML·서비스 경계·쿼리 계층 3중 적용, 페이지는 동시 3개 창으로 점진 생성 |
| R03 | Medium | 같은 사용자 동시 OAuth 완료가 성공 토큰을 삭제 | `commit_graph_connection()` — epoch 재검사→버전 조건 저장→registry 확정을 (user, app) lock 안에서 직렬화. 보상 삭제는 버전 조건부 단일 DELETE |
| R04 | Medium | 계정 삭제에 작업 취소·drain 없음 | 서비스 풀 `drain(user_key)` 신설, `delete_user` 가 deleting+epoch 증가 후 drain(실패 시 중단·재실행 가능). 교차 프로세스 drain 은 ④ |
| R05 | Medium | FileHandler 반복 취소 시 worker 보다 temp·lease 가 먼저 정리 | worker 가 temp 디렉터리를 소유하고 종료 시 정리, 취소는 join 루프로 흡수 |
| R06 | Medium | 부분 성공 응답의 Graph 오류 원문이 정화 우회 | Outlook 오류 항목을 생성 지점에서 `graph_error_summary` 로 축약, `batch_and_fetch` 도 `status: partial` |
| R07 | Medium | Outlook OneDrive 저장 폴더에 G01 미적용 | `graph_drive_path`/`graph_segment` 를 폴더 생성·단순 업로드·upload session 전부에 적용 |
| R08 | Medium | 도메인별 redirect·nextLink 정책 불일치 | 모든 bearer 요청 `allow_redirects=False`(3xx 는 정화 오류). nextLink 는 `/v1.0/me/<도메인 리소스>` 또는 본인 `/users/{id}` 만. 사전 서명 URL 은 https·공개 호스트·bearer 없음·후속 redirect 금지. 공용 모듈 `mcp_common/graph_url_policy.py` |
| R09 | Medium | 파일 크기 설정이 실제 제한으로 연결되지 않음 | `mcp_file_handler/limits.py` — 파일 100MB·요청 500MB·파일 200개·깊이 10·출력 2M자·변환 300초·worker 4 (mode 1 은 상한, 낮추기만 가능) |
| R10 | Medium | 마이그레이션 쓰기 정지 구간 미보장 | `plan` 이 legacy DB 디렉터리에 `.migration_lock` 생성(서버 가동 중이면 거부), `apply`/`activate` 공통 사전검사(잠금·fingerprint·매핑·registry 재검증). 런타임: `assert_legacy_store_not_frozen()` 을 auth.db·OneNote DB·Outlook 메타데이터 생성자에서 호출(`MS365_MIGRATION_OVERRIDE=1` 은 감사 기록) |
| R11 | Medium | activate 재개가 journal·경로 존재만 신뢰 | journal 신원(run_id·manifest sha·사용자 집합) 선검사, 이동 완료 영역 재검증(hash·행 수·owner_key), `verify --live` |
| R12 | Low | 검증 후 일반 open 으로 읽기(TOCTOU) | Outlook·Teams 는 `open_for_read` 핸들로, FileHandler 는 검증 핸들에서 요청 디렉터리로 배타 복사 후 변환 |
| R13 | Low | 동시 OAuth 시작 시 pending 3개 초과 | 정리·상한·삽입을 사용자 file lock 안에서 |
| R14 | Low | FileHandler 가 입력 `file_url` 절대경로 반사 | 정규화된 공개 참조만 반환 |
| R15 | Low | mode 0 `calendar_service`·`todo_service` singleton export 제거 | 모듈 `__getattr__` 지연 export 복원(mode 1 은 `LegacyAuthDisabledError`) |

추가 정리: Calendar·Todo·OneDrive 가 각자 갖던 `graph_url_policy.py` 사본 3벌을 `mcp_common/graph_url_policy.py` 로 통합.

전체 pytest(재검토 반영 후): **1368 passed, 4 skipped** (2026-10-23).

**astra 2차 검토([reviews/멀티유저_astra_2차_2026-10-23.md](reviews/멀티유저_astra_2차_2026-10-23.md)) 반영**

판정은 "출시 불가(High 1: N01)". R06·R07·R12·R13·R14 해소 확인, 나머지는 부분 해소 → 아래 전부 반영.

| ID | 심각도 | 요지 | 수정 |
|---|---|---|---|
| N01 | High | 토큰을 한 번 받아 여러 Graph 변경에 재사용 → 폐기 후에도 Outlook OneDrive 폴더 POST 계속 | 전 도메인 원칙: **토큰 문자열을 await 너머로 보관하지 않고 요청 직전마다 provider 에서 재취득**(provider 가 현재 요청 identity 를 재검사). Outlook 전 요청 사이트 적용(`request_headers()`), 사전 서명 요청은 bearer 없이 `_assert_active()`. Calendar·Todo·OneDrive·OneNote·Teams 는 감사 결과 이미 요청별 취득 — 회귀 테스트만 추가 |
| N02 | Medium | disconnect 가 새 epoch 의 OAuth 완료 토큰을 삭제 | disconnect 도 (user, app) lock 을 **먼저** 잡고 epoch 증가 → 버전 조건부 삭제. 불변: (active+토큰) 또는 (pending_link+없음) |
| N03 | Medium | 변환 timeout 후 converter thread 가 살아 있는데 temp·lease 정리 | 실제 thread 를 추적 단위로(`conversion_workers.WorkerGroup`), 응답·lease 는 thread 종료(또는 30초 hard cap 후 지연 정리)까지 대기, worker 슬롯은 프로세스 전역 user_key 별 |
| N04 | Medium | drain 이 admission 차단·close 완료를 보장하지 않음 | 풀: drain 중 새 lease 거부, 무효 항목 재lease 거부, close 진행 수를 `inflight` 에 포함 |
| N05 | Medium | 사전 서명·nextLink 정책 불일치(Outlook 사설 목적지 허용, 공용 DNS 미검사, OneNote 느슨) | 공용 `check_presigned_url` 에 DNS 해석(모든 주소 공개 대역, 실패 거부)·trailing dot 처리 추가. Outlook·FileHandler 가 공용 검사 사용, Outlook 업로드·조회·재시도·취소 redirect 차단·`beta` 제거. OneNote nextLink 는 공용 `check_next_link` 로 교체 |
| N06 | Medium | FileHandler metadata 가 마이그레이션 동결 밖 | `SQLiteStorage`/`JSONStorage` 생성 시 + 쓰기마다 `assert_legacy_store_not_frozen`. 이전 도구는 모든 writer 디렉터리(database·루트·downloads·output)에 잠금 |
| N07 | Medium | DB 내용 손상이 재개 검증 통과 | manifest 에 테이블별 행 digest(정규화 JSON, 휘발 컬럼 제외) 저장, verify/resume/`verify --live` 가 재계산 비교. activate 는 live 검증 후에만 complete |
| N08 | Medium | 자원 상한이 일부 경로만 | Outlook: 첨부 25MiB/요청 200MiB(디코드 전 추정), 변환 60초 스레드, 사용자 누적 2GiB, 발송 첨부 제한 읽기. FileHandler: 로컬 디렉터리도 파일 수·바이트 예산. 타 도메인 14개 인자 전부 YAML+서비스 경계 상한 |
| N09 | Low | `minLength` 미강제 | `validation.py` 강제 |
| N10 | Low | `search_metadata` 가 입력 `file_url` 반사 | 정규화 참조만 응답 |
| R02 잔여 | — | 6개 도메인 수치 9곳·배열 5곳 상한 없음 | 전부 `minimum/maximum/maxItems` + 서비스 경계 검사(`mcp_common/input_bounds.py` 공용; Outlook·OneNote·Teams 는 자체 helper, 같은 페이로드) |
| R15 잔여 | — | wildcard export 미복원 | `__all__` 을 기동 모드에 따라 구성(mode 0 만 singleton 포함) |

추가 정리: `input_bounds.py` 사본 3벌 → `mcp_common/input_bounds.py`.

전체 pytest(2차 반영 후): **1510 passed, 4 skipped** (2026-10-23).

**astra 3차 검토([reviews/멀티유저_astra_3차_2026-10-23.md](reviews/멀티유저_astra_3차_2026-10-23.md)) 반영**

판정 "승인 보류(새 High 없음)". N02·N07·N09·N10·R02·R15 해소 확인, 부분 해소 항목을 아래와 같이 반영.

| ID | 잔여 지적 | 수정 |
|---|---|---|
| N01 | OneDrive·FileHandler 의 302 후속 사전 서명 GET 전 활성 재검사 없음 | 두 클라이언트 모두 사전 서명 GET 직전 `_assert_active()`(provider 재취득 후 폐기). Outlook 의 초기 확인용 토큰 지역변수 12곳은 후속 HTTP 에 재사용되지 않음(잔여 아님) |
| N03 | 30초 hard cap 뒤 converter 생존 상태에서 lease·close 완료, drain 성공 | FileHandler `close()` 가 생존 thread 있으면 `RuntimeError`. 풀 `_close_entry` 가 실패를 기록하고 `drain()` 은 **False** |
| N04 | `_closing` 이 마지막 lease 경로만 집계, 최초 invalidate 에 timeout 미적용 | 모든 제거 경로(LRU·TTL·invalidate·종료)를 `_close_tracked` 로 집계, drain 은 deadline 을 먼저 정하고 `wait_for(shield(invalidate))`, close 실패 시 False |
| N05 | FileHandler 가 자체 URL 검사(DNS 실패·단일 라벨 허용) | 공용 `check_presigned_url` 로 교체 — 다섯 구현 일치 |
| N06 | 검사와 쓰기 사이 상호배제 없음, 이미 열린 OneNote·Outlook writer | OneNote 5개 쓰기 사이트·Outlook `_save_metadata` 가 쓰기 직전 재검사. 상호배제는 ④ 잔여 |
| N08 | 특정 첨부 다운로드 단건 상한, 사용자 지정 폴더 quota 미집계, 응답 본문 예산 | 단건 25MiB 를 디코드 전 적용, quota 는 사용자 `files/` 전체 집계, `Content-Length` 사전 거부(chunked 는 한계로 문서화) |
| P01 | Outlook 변환 timeout 후 thread 미추적 | `mcp_outlook/conversion_workers.py`(FileHandler 와 같은 모양) — 사용자별 전역 슬롯, thread 종료 시 해제, `MailService.close()` join 후 생존 시 실패 |

전체 pytest(3차 반영 후): **1529 passed, 4 skipped** (2026-10-23).

**astra 4차 검토([reviews/멀티유저_astra_4차_2026-10-23.md](reviews/멀티유저_astra_4차_2026-10-23.md)) 반영**

판정 "승인 보류(새 High 없음)". N01·N05 해소, N06·N08 은 지정 보완 확인(잔여는 ④ 설계 한계). N03·N04 의 풀 결함 4건과 Q01 회귀를 반영.

| ID | 잔여 지적 | 수정 |
|---|---|---|
| N03 | drain 이 close 실패 기록을 다음 호출에서 지움 → 즉시 재시도가 True | 실패 항목을 `_failed_entries` 에 **보존**하고 drain 때마다 다시 닫아 본다(`closed` 리셋 후 `_close_tracked`). 여전히 실패하면 False |
| N04-a | 일괄 제거(TTL·종료) 시 항목을 하나씩 집계 → 뒤 항목 미추적 | `_schedule_close_locked` 가 lock 안에서 **전 항목을 먼저 등록**하고 항목별 close task 를 띄운다 |
| N04-b | doomed 수집 뒤 예외(overloaded 등)로 close 누락 | lease 의 lock 블록을 try 로 감싸 예외 시 `_schedule_close_locked(doomed)`. 무효 항목 재lease 거부는 수집 **전**으로 이동 |
| N04-c | close 대기 중 호출 task 취소 → 집계 소실·lease 수 누수 | close 는 독립 task(`_close_and_untrack`)가 집계 해제까지 수행, 호출자는 `shield(gather)` 로 대기. doomed close 를 lease 의 try 안으로 옮겨 취소 시 finally 가 lease 수를 되돌림 |
| Q01 | Outlook 변환 슬롯 획득 대기 중 취소 → 슬롯 누수(사용자 영구 overloaded) | 슬롯 획득을 이벤트 루프의 비차단 `acquire(0)` 폴링으로 바꿈(취소는 sleep 지점에서만), 획득~thread 시작 사이 예외·`start()` 실패 시 반환 보장 |

전체 pytest(4차 반영 후): **1538 passed, 4 skipped** (2026-10-23). 신규·수정 소스 파일 1,200줄 초과 없음. 추가 astra 검토는 사용자 요청 시 — 코드로 해소하지 않은 잔여는 전부 ④ 에 설계 한계로 기록돼 있다.

**모드 0 외부 로그인 위임 계약(② 13) 구현 (2026-10-23, AIP 세션 요청 서브세션)**

| 파일 | 내용 |
|---|---|
| `session/external_login.py` (신규, 303줄) | `complete_external_login`·`connection_state`·`features_from_scopes`·`parse_granted_scopes`·`FEATURE_REQUIREMENTS`·`ExternalLoginError`(`code` + `"CODE|메시지"`) — mode 1 은 `refuse_in_multi_user` |
| `session/auth_service.py` | `_exchange_code_for_tokens(auth_code, *, redirect_uri=None, scope=None)`(기본값 = 종전 동작, HTTP 오류는 `ExternalLoginError(EXCHANGE_FAILED)` — `Exception` 하위) · `TokenRefreshError`(`code`·`reauth_required`)·`REAUTH_OAUTH_ERRORS`·`refresh_failure_reason` · `check_and_refresh_if_needed` 반환에 `reason` + 거부 표식 · 관문 `complete_external_login`/`connection_state` |
| `session/auth_manager.py` | 관문 `complete_external_login`/`connection_state` · `refresh_token` 반환에 `reason` + 거부 표식 · `get_token` 에 `refresh_state` · `get_token_status` 에 `refresh_state`·`state`(기존 키 불변) |
| `session/auth_database.py` | `OPTIONAL_TOKEN_COLUMNS`(`scope`·`refresh_state`) idempotent `ALTER TABLE`(mode 0 전용, 실패 무시) · `save_token` 이 `refresh_state`('ok' on new refresh)·빈 scope→NULL · `get_token(email, strict=False)` · `canonical_email` · `mark_refresh_state` |
| `session/__init__.py` | 지연 export `ExternalLoginError`·`TokenRefreshError` |
| `session/tests/test_external_login.py` (신규, 17건) | 교환 요청(redirect_uri·scope·client secret)·저장 순서·토큰 비노출 / scope 기본·목록 / `save=False` / refresh 없는 저장 / EXCHANGE_FAILED(HTTP·통신·빈 입력, 오류 본문 미노출)·USERINFO_FAILED·SAVE_FAILED / connection_state 4상태(+대소문자 표기·표식 해제·access 만 갱신) / features 대응표·구형 행 None / invalid_grant 표식·transient 구분·`validate_and_refresh_token` None 뒤 상태·재로그인 복구 / `check_and_refresh_if_needed` reason 5경우 / `TokenRefreshError` 분류 / 선택 컬럼 보강(mode 0 idempotent·mode 1 legacy 미수정·컬럼 없을 때 no-op) / mode 1 거부 |

실행: `venv\Scripts\python.exe -m pytest session/tests -q` → **119 passed** / 전체 `venv\Scripts\python.exe -m pytest -q` → **1556 passed, 3 failed, 0 skipped (236.54s)**. 실패 3건은 전부 `mcp_file_handler/tests/test_converters.py`(DOCX·Excel = `PermissionError WinError 32` 임시 파일을 다른 프로세스가 사용 중, OCR = `TesseractNotFoundError` tesseract 미설치) — 종전 "4 skipped" 였던 변환기 테스트가 venv 에 converters 의존이 깔리면서 실행된 환경 문제이며 session/ 변경과 무관(단독 재실행도 같은 결과). 기존 공개 메서드의 시그니처·반환 키·동작 불변(추가만). 실 auth.db 에는 첫 `AuthDatabase` 생성 때 `refresh_state` 컬럼이 추가된다(`scope` 는 이미 있었음). 주의: 구현 중 다른 세션의 커밋 `941b53a`(14:42)가 `auth_database.py`·`external_login.py` 2개를 먼저 담았다 — 나머지 변경(관문·테스트·문서)은 미커밋.

**codex 교차 검토 2건 반영(② 13, 2026-10-23, 별도 서브세션)** — `session/external_login.py`(`expect_email` 저장 전 대조 → `ACCOUNT_MISMATCH`(`expected_email`·`actual_email` 속성) · 저장 실패는 예외 대신 반환 `error="SAVE_FAILED"`, `SAVE_FAILED` 상수는 예외 미사용으로 명시) · 관문 `auth_service.py`·`auth_manager.py` 에 `expect_email=None` 인자(기본 = 종전) · `session/README.md`·`CLAUDE.md` 갱신 · `session/tests/test_external_login.py` 3건(저장 실패 반환 꼴 4경우 — save_token False·save_user 예외·기존 행 있는 계정·정상/save=False 에 error 키 없음 / 불일치 때 save_user·save_token 미호출·코드·속성·대소문자 무시·save=False 도 대조·빈 값 무검증 / 다른 계정 B 의 기존 행 불변). 기존 인자·반환 키·동작·mode 1 코드 불변(추가만). 실행: `venv\Scripts\python.exe -m pytest session/tests -q` → **121 passed in 39.28s**(종전 119 + 신규 2, 저장 실패 테스트 1건은 새 반환 꼴로 교체). AIP 쪽 후속: 워커 `vendor/ms365/auth.py` `LOGIN_CODES` 에 `ACCOUNT_MISMATCH` 등재 + `graph_connect` 가 `expect_email` 을 넘기면 사후 비교가 사전 차단으로 바뀐다(AIP 저장소 — 이 서브세션 범위 밖).

**astra 5차 검토([reviews/멀티유저_astra_5차_2026-10-24.md](reviews/멀티유저_astra_5차_2026-10-24.md)) 반영 (2026-10-24)**

범위는 4차 반영 5건(N03·N04-a·N04-b·N04-c·Q01)과 그 파급, 검토 기준 HEAD `d348c06`. 판정 — **(A) main 병합: 병합 가능**(병합 후 mode 0 유지·mode 1 비활성 전제. mode 0 은 서비스 풀을 쓰지 않고 전역 서비스를 직접 쓴다 — `mcp_common/runtime.py:218`, `mcp_common/service_context.py:65`) · **(B) mode 1 출시: 승인 보류**(신규 High 없음, N03·N04-c 잔여 + 신규 Q02). 이번에는 코드를 고치지 않았다 — 잔여는 ④ 'mode 1 활성화 전 코드' 행.

| ID | 판정 | 요지 |
|---|---|---|
| N03 | 부분 해소 | 순차 drain 재시도·선행 invalidate 실패는 해소. **같은 사용자의 동시 drain** 에서 한쪽이 close 재시도 중인데 다른 쪽이 True — 실패 목록을 꺼낸 뒤 재등록하는 사이 다른 drain 이 빈 목록을 보고, 마지막 판정은 실패 목록만 검사하며, 한 호출의 finally 가 공용 `_draining` 표식을 지운다 |
| N04-a | 해소 | 전 항목 선등록·항목별 독립 close task. TTL 일괄 제거의 뒤 항목도 추적됨 |
| N04-b | 해소(테스트는 가짜 보호) | 무효 항목은 수집 전 거부, 수집 후 예외에도 close 예약. 단 추가된 테스트는 수정을 제거해도 PASS(`doomed=[]` 인 경로만 검사) |
| N04-c | 부분 해소 | 기존 close 추적·lease 수 반환은 해소. **서비스 생성 전에 취소된 entry 의 `ready` 가 미완료로 캐시에 남아** 같은 키 재요청은 무기한 대기·다른 키는 overloaded(미완료 entry 는 TTL·LRU 에서 제외) |
| Q01 | 해소 | mode 0·1 모두 대기 취소 후 슬롯 누수 없음(future 생성·worker 등록·`Thread.start()` 실패 주입 포함). **mode 0 슬롯 키** = 첨부 경로가 명시 전달하는 `LEGACY_KEY`(`None` 도 같은 키) — 같은 보장. 폴링: 여유 슬롯이면 sleep 없음(변환 15회 중앙값 약 0.28ms), 경합 시 10ms sleep + OS 스케줄링(슬롯 해제→결과 약 16ms), busy wait 아님, 4슬롯·64요청 합성 검사에서 교착·처리량 저하 없음 |

신규 **Q02 (Medium) — 동일 키의 TTL 만료 후 닫힌 서비스 재사용(N04-b 수정의 회귀)**: entry 조회가 TTL 수집보다 앞서, 바로 다음 수집에서 제거된 entry 를 지역변수로 그대로 반환한다(기존 객체 반환, 서비스·토큰 closed, factory 1회, 실제 lease 중 inflight 0·drain True). 수집 후 조회 순서로 되돌리면 새 서비스 생성·inflight 1 로 바뀌어 회귀임을 확인. 기존 TTL 테스트(`mcp_common/tests/test_security_contracts.py:381`)는 다른 사용자로 재요청해 놓친다. 권고 = 무효 항목 사전 거부는 유지하고 **수집 후 실제 캐시에서 entry 재조회**.

회귀 테스트 검출력(과거 코드 checkout 이 아니라 현재 테스트 본문에 해당 결함만 재주입·수정 제거해 비교):

| 테스트 | 판정 |
|---|---|
| N03 재시도 (`mcp_common/tests/test_multiuser_runtime_recheck.py:275`) | 유효 — 실패 기록 삭제 재주입 시 FAIL. 동시 drain 은 미검증 |
| N04-a 일괄 TTL (`:299`) | 유효 — 항목별 순차 등록·close 재주입 시 TimeoutError |
| N04-b 예외 (`:343`) | **가짜 보호** — 수정 제거 후에도 PASS(A 를 C 요청에서 이미 닫은 뒤 `doomed=[]` 인 B 의 overloaded 만 검사) |
| N04-c 취소 (`:387`) | 유효하나 B 재lease 를 검사하지 않아 미완료 entry 잔류를 놓침 |
| Q01 취소 (`mcp_outlook/tests/test_multiuser_review4_fixes.py:55`, `:90`) | 유효 — 구 `to_thread(acquire)` 재주입 시 슬롯 누수 FAIL |
| Q01 start 실패 (`:146`) | 현행 보호 제거 시 FAIL 이나 **구 구현에서는 가짜 PASS 가능** — 전역 `Thread.start` 패치가 converter 보다 먼저 executor 생성을 막는다(converter thread 로 한정 필요) |

4차 반영 시점의 `1538 passed, 4 skipped` 는 오케스트레이터 확인값이며 아래 병합 전 검증값과 혼용하지 않는다.

**병합 전 mode 0 검증 (2026-10-24, 읽기 전용 서브세션)**

- 저장소: `multi-user` = `d348c06`(origin 일치), `origin/main` = `f6c7121`(직계 조상 — fast-forward 가능), 작업 트리 clean. `MS365_MULTI_USER` 는 `.env`·프로세스·Windows User/Machine 환경 어디에도 없음(= mode 0).
- 전체 pytest(`venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`, mode 0): **1558 passed, 3 failed, 0 skipped (230.98s)**. 실패 3건은 종전과 같은 환경 문제 — `mcp_file_handler/tests/test_converters.py::TestDOCXConverter::test_convert_simple_docx`·`::TestExcelConverter::test_convert_simple_excel`(PermissionError WinError 32)·`::TestOCRConverter::test_convert_simple_image`(TesseractNotFoundError). 1556 → 1558 은 codex 교차 검토 반영의 session/tests 신규 2건(위 119 → 121).
- Teams chat_id 실 Graph 실측(소유자 계정, GET 만): 실제 코드 경로 `mcp_teams/graph_teams_client.py` `GraphTeamsClient`(mode 0 공유 AuthManager)의 `list_chats`·`get_chat_messages`·`get_chat`·`_chat_member_emails` — chat 단위 호출은 모두 `graph_segment` 경유. `list_chats` 는 200·40건(has_more). 꼴별 1개 채팅의 HTTP 상태(ID·이름·본문은 기록하지 않음):

| chat_id 꼴 | get_chat_messages | get_chat | `/chats/{id}/members` | 문자 그대로 직접 GET | `%3A`·`%40` 강제 직접 GET |
|---|---|---|---|---|---|
| 1:1 `19:…@unq.gbl.spaces` | 200 | 200 | 200 | 200 | 200 |
| 그룹 `19:…@thread.v2` | 200 | 200 | 200 | 200 | 200 |
| 회의 `19:meeting_…@thread.v2` | 200 | 200 | 200 | 200 | 200 |
| Notes `48:notes`(chat_id 생략 기본) | 200 | — | — | — | — |

- 실제 전송 형태: `graph_segment` 가 만든 `19%3A…%40…` 를 aiohttp 3.14.3 / yarl 1.24.5 가 경로 재인용하며 `:`·`@`(경로 허용 문자)로 되돌려 **실제로는 `/v1.0/me/chats/19:****@thread.v2/messages` 꼴로 나간다**. `%2F` 는 유지되므로 G01 의 경로 탈출 방지는 그대로다. yarl `encoded=True` 로 `/v1.0/me/chats/19%3A****%40thread.v2/messages` 를 강제해도 세 꼴 모두 200 — Graph 는 두 표기를 다 받는다 → `graph_segment` safe 집합 조정 불요.
- Outlook `$batch`(`GraphMailIdBatch.batch_fetch_by_ids`, `$select=id`): 안쪽 요청 URL 은 JSON 본문이라 yarl 을 거치지 않아 `seg(mail_id)` 의 `=`→`%3D` 가 그대로 Graph 에 도달한다 — **3/3 성공·오류 0**.
- 부수 효과: 소유자 액세스 토큰이 만료 상태여서 첫 호출이 정상 경로(`validate_and_refresh_token`, auto_reauth 없음)로 갱신해 auth.db 토큰 행이 바뀌었다(정상 갱신, 스키마 변경 없음 — `scope`·`refresh_state` 기존).

**병합 기록 (2026-10-24)**: `main` = 이 커밋(fast-forward, `f6c7121` → 이 문서 커밋). 기본은 mode 0 그대로, mode 1 은 ④ 'mode 1 활성화 전 코드' 잔여 해소·운영 입력 확정 전까지 켜지 않는다. `multi-user` 브랜치는 로컬·원격 모두 보존.

## ④ 미결/후속

아래는 구현 방식을 각 에이전트가 임의로 결정할 항목이 아니라, 운영자가 제공하거나 승인해야 하는 배포 입력이다. 결정 전에는 테스트와 독립 구현을 진행할 수 있지만 운영 활성화는 하지 않는다.

| 항목 | 권고안 | 결정·확인 필요 내용 |
|---|---|---|
| 최초 지원 클라이언트 | Authorization 헤더와 stateless HTTP를 실제 지원하는 클라이언트부터 운영 | 제품·버전·설정 방식과 회귀 대상 |
| 표준 OAuth 필요성 | 최초 버전은 확정된 bearer 방식을 유지 | 자동 로그인·OAuth discovery가 필수라면 별도 후속 사양으로 ① 전환 |
| 허용 tenant·사용자 | 명시적 tenant allowlist와 `(tid, oid)` 등록 | 실제 tenant 및 초기 사용자 목록 |
| 운영 호스트·KEK | 단일 호스트 로컬 저장소 + Azure Key Vault + managed identity | Azure 사용 가능 여부, vault·키·권한·운영 책임자 |
| 외부 URL·콜백 | 고정 HTTPS origin과 중앙 `/auth/callback` | 도메인·인증서·Entra redirect URI |
| 데이터 소유자 매핑 | 확인된 매핑만 이전 | legacy 이메일·metadata·downloads·output의 실제 소유자 |
| 모호한 데이터 | 격리 보관 후 수동 확인 또는 재생성 | 보관기간과 확인 책임자 |
| 백업·삭제 | live 접근 즉시 차단, 백업 기본 보존 30일 후 제거 | 조직의 보존·감사·복구 요구 |
| 감사 보존 | 관리자 전용 sink, 기본 90일 | 실제 보존기간·접근 권한·외부 수집 시스템 |
| 용량·실행 제한 | 사용자별 파일 용량·변환 시간·동시 실행 상한 적용 | 초기 사용자 수·파일 크기·운영 자원에 따른 값 |
| 공유 사서함·공유 자원 | A의 delegated 권한으로 허용된 공유만 사용 | 별도 공유 사서함 기능 확대 여부 |
| 다중 호스트 운영 | 최초 버전 범위에서 제외 | 필요 시 중앙 DB·분산 lock·공유 없는 worker 구조의 별도 설계 |
| 교차 프로세스 drain (R04 잔여) | 삭제·연결 해제 시 다른 도메인 프로세스의 진행 중 작업은 토큰 획득·응답 전 `assert_active` 로 차단되지만 이미 시작된 로컬 저장은 끝까지 간다 | 사용자별 공유/배타 OS lock(Windows `msvcrt` 는 배타만 지원) 또는 admission 서비스 — 필요 시 별도 설계 |
| 변환 worker 종료 (R09·N03·P01 잔여) | Python thread 는 강제 종료 불가. 시간 초과 시 결과 폐기, 실제 thread 를 추적해 **temp 디렉터리와 사용자별 슬롯은 thread 종료까지 유지**(정상 시작된 converter 기준). 요청 lease 는 Outlook 변환 timeout 후·FileHandler 30초 hard cap 후 반환될 수 있다 — 그 보완이 "생존 thread 있으면 서비스 `close()` 실패 → 풀 `drain()` **False**(재시도해도 실패 기록 유지, 삭제 절차 중단)" 이다 — 순차 재시도 기준이며 동시 drain 은 미보장(5차, 아래 'mode 1 활성화 전 코드 — N03 동시 drain') | 프로세스 격리 worker(피클 가능한 변환기 필요) |
| 마이그레이션 동결과 writer 의 상호배제 (N06 잔여) | `.migration_lock` 표식 검사는 생성 시 + 쓰기 직전(FileHandler·OneNote·Outlook)이지만 **검사와 쓰기 사이 상호배제는 없다** — 표식 생성 전에 검사를 통과한 진행 중 쓰기들은 막지 못한다(건수 상한 없음). 운영 절차(모든 legacy writer 정지 확인 후 plan)가 1차 방어 | 완전 해소는 writer 가 쓰기 트랜잭션 동안 잡는 legacy 디렉터리별 OS 배타 lock(`session/file_lock.py` 를 `mcp_common` 으로 올려 공용화)을 이전 도구가 plan~unlock 동안 선점하는 설계 — 필요 시 별도 착수 |
| Outlook 첨부 응답 본문 메모리 상한 (N08 잔여) | `Content-Length` 가 있으면 `.json()` 전에 거부하지만, chunked(헤더 없음) 응답은 전체를 읽은 뒤 디코드 예산을 적용. 사용자 quota 는 동시 요청 간 원자적 총량 제한이 아님(약간의 초과 가능) | 스트리밍 JSON 파서 또는 `$batch` 대신 개별 첨부 스트림 조회로 전환 시 해소 |
| DNS rebinding (R08 잔여) | 사전 서명 URL 호스트 검사는 리터럴 IP·이름·해석 시점 주소 기준 | 해석 IP 고정(pinning) 연결이 필요하면 커스텀 connector |
| `conversion_workers.py` 사본 2벌 | `mcp_outlook/`·`mcp_file_handler/` 가 실행 로직·자료구조가 동일(주석·로그 문구만 다름)한 worker 추적 모듈을 각자 보유 — 도메인 간 import 금지 규칙 때문 | `mcp_common/conversion_workers.py` 로 올리고 도메인은 재수출 shim 으로. 테스트가 도메인 모듈 속성(`HARD_JOIN_CAP_SECONDS`)을 monkeypatch 하므로 상수 읽기 경로를 정리한 뒤 착수 |
| ~~Graph ID 퍼센트 인코딩 실측~~ | **해소(2026-10-24, ③ '병합 전 mode 0 검증')** — Teams 1:1·그룹·회의·Notes chat_id 모두 200(실제 전송은 yarl 재인용으로 `:`·`@` 문자 그대로, `%3A`·`%40` 강제도 200), Outlook `$batch` 의 `%3D` 도 3/3 성공 | 조정 불요 |
| mode 1 활성화 전 코드 — Q02 동일 키 TTL 재생성 (astra 5차) | N04-b 수정으로 entry 조회가 TTL 수집보다 앞서, 수집에서 제거된 같은 키의 닫힌 서비스를 다시 반환한다(실제 lease 중 inflight 0·drain True) | 무효 항목 사전 거부는 유지하고 **수집 후 실제 캐시에서 entry 재조회**. mode 1 활성화 전 필수 |
| mode 1 활성화 전 코드 — N03 동시 drain (astra 5차) | 같은 사용자 drain 이 동시에 돌면 한쪽 close 재시도 중에 다른 쪽이 True — 실패 목록을 꺼낸 뒤 재등록 사이에 빈 목록을 보고, 판정은 실패 목록만 검사하며, 한 호출의 finally 가 공용 `_draining` 표식을 지운다(삭제 경로는 False 일 때만 중단하므로 의미 있는 잔여) | 사용자별 drain 직렬화 또는 진행 중 close 까지 포함하는 동등한 추적 보장(공용 `_draining` 표식 해제 포함). mode 1 활성화 전 필수 |
| mode 1 활성화 전 코드 — N04-c 생성 전 취소 entry (astra 5차) | 서비스 생성 전에 취소된 entry 가 `ready` 미완료로 캐시에 남아 같은 키 재요청은 무기한 대기, 다른 키는 overloaded(미완료 entry 는 TTL·LRU 제외) | 취소 시 미생성 entry 제거 + `ready` 대기자 해소. mode 1 활성화 전 필수 |
| mode 1 활성화 전 코드 — 회귀 테스트 보강 (astra 5차) | N04-b 예외 테스트는 가짜 보호, Q01 start 실패 테스트는 구 구현에서 가짜 PASS 가능, 동일 키 TTL·같은 사용자 동시 drain·취소 후 같은 키 재lease·mode 0 슬롯 취소는 미검증 | N04-b 는 실제 doomed 가 생긴 뒤 예외 발생 · Q01 start 실패 주입을 converter thread 로 한정 · 동일 키 TTL 재요청 · 같은 사용자 동시 drain · 취소 후 같은 키 재lease 성공 · mode 0(`LEGACY_KEY`) 슬롯 취소 테스트 추가 |
| OS 수준 사용자 격리 | API 사용자 간 격리를 최초 보장 범위로 채택 | 관리자·프로세스 침해까지 분리해야 하면 사용자별 실행 환경 추가 |
| AIP 웹 로그인 연동 (2026-10-22 요청) | 공통 신원 = Entra (tid, oid). AIP 웹 최초 로그인(OIDC) 후 AIP 서버가 이 저장소의 **프로비저닝 API**(서버 간·전용 자격증명·loopback)로 사용자 등록·bearer key 발급·MS365 연결 링크를 받는다. 프로젝트 접근(담당자·인계)은 AIP 가 요청마다 판정(이 저장소는 캐시하지 않음 → epoch 불필요) | **AIP 세션 확인(사용자 확정, 2026-10-22)**: 웹 로그인 = MS365 / 접근 = AIP 프로젝트 단위·담당자(대표 `project.manager_member_id` + 공동 `project_participant` role '담당')만, 인계 시 새 담당자 즉시·구 담당자는 '공동으로 남김' 선택 시만 유지 / 접수 전 자료 = 로그인 사용자 전원 공유 / 관리자 = kimghw, 루프백 무로그인 = 관리자 / AIP = 이 PC `127.0.0.1:8035`, 이 저장소를 subprocess 워커로 호출 / **AIP 적응 전까지 이 PC 는 mode 0 유지**. **사용자 답(2026-10-23)**: "AIP 웹서버 로그인 기능을 MCP 로 하고, AIP 웹이 쓰는 MCP 서버를 로그인된 사용자만 접속" / 서버측 자격은 "동작 중인 에이전트와 협의". **AIP 세션에 보낸 설계안 v1 (합의 대기)**: A' AIP 가 자체 Entra 로그인(이미 구현, 같은 Entra 앱)으로 받은 **ID token 을 gateway `POST /auth/token`(grant_type=id_token, loopback, client secret)에 제출 → gateway 가 JWKS 서명·iss·aud·tid 검증 후 사용자 등록(허용 tenant 첫 로그인 = 자동 등록) + `session_token`(m365s1, 8h) + `graph_connected`/`connect_url` 반환** / B 대화형 MCP 호출은 session_token 으로 / C 배경 작업은 **서비스 자격증명 `m365svc.*` + `X-MS365-Act-As: <user_key>`**, 사용자가 로그인 시 'aip' 에 위임 부여한 경우만, 감사 actor=aip / D 과도기: mode 1 은 HTTP 서버·gateway 프로세스 env 로만 켜고 AIP 워커(mode 0, auth.db)와 별도 저장소로 공존. **합의(2026-10-23, AIP 세션 검토)**: 책임 분리(인증은 이 저장소, AIP 는 신원·계정) 확정 → **mode 0 라이브러리 계약 먼저(② 13 — 구현 완료 ③)**: `AuthManager.complete_external_login(code, redirect_uri, scopes, save)`·`connection_state(email)`·`reason` 코드. AIP 쪽 후속 = `webauth._exchange`·`_import_token`·vendor `auth_import` 를 이 API 호출로 교체(그쪽 ④ 12 ⑶). **이 저장소 후속** = mode 1 gateway `POST /auth/token`(grant_type=id_token 또는 인가 코드, loopback·client secret)·`session_token`·서비스 자격 act-as(설계안 A'·B·C) — AIP 의 mode 1 전환(그쪽 순서 ⑸, 토큰 이관 없음·사용자별 재연결 1회) 때 착수 |

이메일 기반 식별, 기본 계정 폴백, 공용 인증 DB, 공용 다운로드, 사용자 구분 없는 캐시를 유지하는 방향은 미결 선택지에 포함하지 않는다.