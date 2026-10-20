# 코드 정리 — 불필요 스크립트·중복 코드 감사

## ① 질의·요청 히스토리

- 2026-10-20 — "현재 프로젝트에서 불필요한 스크립트나 중복되는 게 있는지 검토. Codex(gpt-6-astra, ultra) 호출해서 진행." Codex `exec --sandbox read-only` 로 저장소 전체(257파일, Python 169)를 감사하고, Claude 가 삭제 후보 전건을 grep 으로 재검증했다. 결과는 아래 ④와 부록. 코드 변경은 하지 않았다.

## ② 확정 사양

- 미확정. 아래 ④의 후보 중 무엇을 삭제·통합할지는 사용자 결정 대기.

## ③ 구현 상태

- 미착수(감사만 완료).

## ④ 미결/후속 — 감사 결과 요약

### 삭제 후보 (참조 0건, Claude 재검증 완료)

| 파일 | 근거 | 확신도 |
|------|------|--------|
| `_reauth.py` | "임시 재인증 스크립트". 호출처 없음. `main.py`·`AuthManager.main()` 이 같은 기능 | 높음 |
| `session/session_manager.py` (421줄) | `SessionManager` import·호출 없음. `session/__init__.py` 재수출도 없음 | 높음 |
| `session/time_utils.py` (144줄) | 모든 함수 외부 참조 없음. 만료 판정은 `AuthService.is_token_expired()` 가 담당 | 높음 |
| `mcp_file_handler/attachment_converter.py` | `AttachmentAPI`·`UnifiedAttachmentConverter` 참조 없음. 호환 대상 `mail_to_text_converter.py` 는 존재하지 않음 | 높음 |
| `session/auth_service.py` — `check_and_refresh_if_needed()` (345–441줄) | 호출 없음. `AuthManager.validate_and_refresh_token()` 과 정책 중복(Manager 쪽에만 사용자별 lock). 파일 전체는 사용 중 | 높음 |
| `mcp_common/param_spec.py` — `ParamSpec.coerce_arguments()` (485–496줄) + `_exposed_schemas` | `ToolRuntime.call()` 로 일원화된 뒤 남은 잔존 API. 호출 없음 | 높음 |
| `mcp_outlook/tests/run_tests.py` | pytest 수집 대상 아님. 시나리오가 `test_mail_attachment_*`·`test_integration.py` 와 중복. metadata 테스트는 제품 클래스 대신 자체 dict 검사 | 중간 |
| `cloudflare/reset-tunnel.sh` | Outlook 포트 8001/API 8000 기준으로 작성. 현행 outlook 포트는 5001 — 이미 어긋남. 보관 여부 확인 필요 | 중간 |
| `session/test/` (2파일) | `input()`·브라우저·실 DB 를 쓰는 수동 진단 스크립트. pytest testpaths 는 `session/tests` 만 수집. 두 파일의 `check_db_state()` 가 서로 중복 | 중간 |

### 규칙 위반

| 위치 | 내용 |
|------|------|
| `mcp_common/runtime.py:82–89` `input_schema()` | 빈 스키마 대체·`type: object` 보정을 직접 수행 — `schema_normalize.normalize_input_schema()` 와 책임 중복(단일 진입점 규칙 위반). |
| `mcp_file_handler/mcp_server/tool_definitions.py` | 3파일 구조 밖의 4번째 파일. 내용은 SPEC 재수출이라 SSOT 중복은 아니며 import 부수효과 회피 사유가 기록돼 있음. 다른 7개 도메인처럼 `handlers.py` 로 흡수 가능. |
| 8개 도메인 `handlers.py` `DEFAULT_PORT = SPEC.port or 500x` | 포트 fallback 하드코딩이 spec 과 이중. 도구 인자 기본값 하드코딩·boolean 보정 우회는 **없음**. |

### 중복 코드 (통합 효과 큰 순)

1. **Graph HTTP 요청 계층** — `_make_request()`(onedrive 93–156 / onenote 137–201 / teams 89–147), `_get_access_token()`(calendar 237–259 / outlook query 72–94 / id_batch 54–74), calendar `_fetch/_post/_patch/_delete_data()` vs todo `_fetch/_post/_patch/_delete()`. 초기화→토큰→Bearer→요청→상태 처리→오류 dict 포장이 도메인마다 재구현. onenote 는 같은 파일 안에 `_make_request_full_url()` 로 또 한 벌. → `mcp_common` 에 공통 Graph 요청 계층 1개.
2. **파일→텍스트 변환** — `mcp_file_handler/converters/{docx,pdf,excel}` vs `mcp_outlook/mail_attachment_converter.py` 의 `WordConverter/PdfConverter/ExcelConverter`, 그리고 `BaseConverter+FileDetector` vs `FileConverter+ConversionPipeline` 레지스트리 구조. → FileHandler 쪽으로 통합, Outlook 은 bytes 어댑터만.
3. **OneDrive 클라이언트 두 벌** — `mcp_file_handler/onedrive/client.py`(동기 requests, ID/공유 URL) vs `mcp_onedrive/graph_onedrive_client.py`(비동기 aiohttp, 경로). 전자는 file_manager→processor→downloader 체인에서 사용 중이라 기능 보존 후 통합.
4. **메일 본문 저장 3벌** — `mail_attachment_storage.py` 의 `LocalStorageBackend/OneDriveStorageBackend/MailFolderManager.save_mail_content()` + `mail_attachment_processor.process_body_content()` 의 HTML 제거. `save_file()` vs `save_attachment()` 의 파일명 충돌 회피도 중복. → 메일→텍스트 함수 1개.
5. **도메인 서버 배선** — `server_stdio.py` 8개·`server_stream.py` 7개는 도메인명 치환 시 AST 동일. `build_mcp_server()` 도 8개 도메인 동일. 이미 bootstrap 으로 공통화돼 있어 남은 건 진입점 배선만 — 통합 우선순위 낮음.
6. **타입 모델** — `DateTimeTimeZone`·`ItemBody`(calendar vs todo), `UserInfo.from_dict`(onedrive vs teams), `getattr` 기반 dict 호환 메서드(calendar_types vs outlook_types).
7. **스킬 스크립트** — setup_ms365 5개 스크립트에 6도메인 목록·포트 반복, `health_check.probe()` vs export `verify_bundle.check_http()`. 각 스크립트의 존재 근거는 전부 확인됨(삭제 대상 아님).
8. `mcp_file_handler/utils/logger.py` vs `mcp_common/bootstrap._configure_logging()`; `get_default_user_email()` 3벌(auth_service/session_manager/auth_manager → `mcp_common/user_resolver` 로 통일).

### 삭제 제외(사용 확인)

`core/protocols.py`(12개 모듈이 타입 import), `main.py`(README 안내), `callback_server.py`, `conftest.py`, `MANIFEST.in`, `graph_mail_id_batch.py`, `graph_mail_url.py`, `onenote_agent.py`, `mcp_file_handler/{base_converter,config/settings,utils/logger}.py`, Outlook 첨부 3모듈, setup_ms365·export_ms365 스킬 스크립트 전부.

### 기타

- CLAUDE.md 가 참조하는 `spec/spec_아키텍처.md` 가 저장소에 없다(파일 크기 상한 절의 "원본" 링크 깨짐).

---

## 부록 — Codex(gpt-6-astra, reasoning ultra) 원본 보고 (2026-10-20)

검토 범위는 **257개 파일(Python 169개), 비무시 미추적 파일 0개**입니다. `rg`가 설치되어 있지 않아 `git grep -n --untracked -I -E`로 코드·테스트·스킬·spec·README 참조를 검색했습니다. 지정한 제외 디렉터리는 제외했습니다. 파일 수정과 서버·인증·테스트 실행은 하지 않았으며, Python 파일은 AST 구문 분석만 수행했습니다.

아래 경로는 `E:\dev\KR_MS365_mcp` 기준입니다. “외부 참조 없음”은 **해당 파일 밖의 저장소 내 참조 없음**을 뜻합니다.

## 1. 삭제 후보

| 파일 | 근거(호출처 검색 결과) | 확신도 |
|---|---|---|
| [_reauth.py](E:/dev/KR_MS365_mcp/_reauth.py:1) | `_reauth.py`, `\b_reauth\b` 검색에서 외부 참조 없음. 1행에 “임시 재인증 스크립트”로 명시. `main():5–11`은 브라우저 인증·종료만 수행하며 `main.py:24–81`, `session/auth_manager.py:646–715`에 같은 인증 진입점이 있음. | 높음 |
| [session/session_manager.py](E:/dev/KR_MS365_mcp/session/session_manager.py:20) | 모듈명·`SessionManager`·`get_or_create_session`·`invalidate_session` 검색에서 외부 import/호출 없음. `session/__init__.py:6–18`에도 재수출 없음. 다른 `session_manager`는 MCP SDK 객체이며, `auth_manager.py:636`의 `Session`은 설명 문구. 전역 인스턴스만 자체 생성함(`418–421`). | 높음 |
| [session/time_utils.py](E:/dev/KR_MS365_mcp/session/time_utils.py:10) | `time_utils`, `utc_now`, `to_utc`, `to_local`, `format_local_time`, `parse_iso_to_utc`, `time_until_expiry`는 자기 파일 내부에서만 발견. 다른 파일의 `is_expired`는 별도 메서드. 만료 판정은 사용 중인 `AuthService.is_token_expired():302–320`에도 있음. | 높음 |
| [mcp_file_handler/attachment_converter.py](E:/dev/KR_MS365_mcp/mcp_file_handler/attachment_converter.py:14) | `AttachmentAPI`, `UnifiedAttachmentConverter`는 자기 정의만 검색됨. 파일 외부 참조는 `mcp_file_handler/README.md:93`의 디렉터리 목록뿐. 호환 대상이라는 `mail_to_text_converter.py`도 추적·비무시 파일 목록에 없음. 두 클래스는 `FileManager.process()` 래퍼(`21–52`, `62–74`). | 높음 |
| [session/auth_service.py](E:/dev/KR_MS365_mcp/session/auth_service.py:345) **일부만** | `check_and_refresh_if_needed` 검색 결과 정의(`345`)뿐. `345–441`은 Manager의 토큰 갱신 정책과 중복. 이 경로에서만 쓰는 로컬 `get_default_user_email():20–31`도 함께 정리 가능. **AuthService 전체는 사용 중**이므로 파일 삭제 대상은 아님. | 높음 |
| [mcp_common/param_spec.py](E:/dev/KR_MS365_mcp/mcp_common/param_spec.py:485) **일부만** | `coerce_arguments` 검색에서 정의·주석·`spec/spec_도구정의.md:180`의 과거 수정 설명만 발견되고 호출 없음. `ParamSpec.coerce_arguments():485–496` 및 전용 `_exposed_schemas` 저장소(`400`, `493`)는 `ToolRuntime.call():126`으로 일원화된 뒤 남은 코드. | 높음 |
| [mcp_outlook/tests/run_tests.py](E:/dev/KR_MS365_mcp/mcp_outlook/tests/run_tests.py:92) | 외부 참조는 `attachment_storage_plan.md:344,351,367–368`의 독립 실행 설명. `pyproject.toml:137`의 `test_*.py` 수집 대상이 아니며, 변환·저장·통합 시나리오가 아래 pytest 테스트와 겹침. 독립 실행 지원을 정리한다면 삭제 가능. | 중간 |
| [cloudflare/reset-tunnel.sh](E:/dev/KR_MS365_mcp/cloudflare/reset-tunnel.sh:48) | 외부 참조는 setup의 `references/caveats.md:63`. 해당 문서는 Outlook 포트의 `8001→5001` 변경을 설명하지만 스크립트는 여전히 `8001/8000` 설정을 생성(`48–57`)하고 출력(`87–88`). 현행 Outlook 포트는 `spec/param_spec/outlook.yaml:14`의 `5001`. 과거 운영용 보관 여부 확인 필요. | 중간 |

## 2. 중복 코드

스킬 경로 약어: **S** = `.claude/skills/setup_ms365/scripts`, **E** = `.claude/skills/export_ms365`.

| A 위치 | B 위치 | 중복 내용 | 통합 제안 |
|---|---|---|---|
| `session/auth_manager.py` — `validate_and_refresh_token():230–280`, `refresh_token():151–228` | `session/auth_service.py` — `check_and_refresh_if_needed():345–441` | DB 조회→만료 확인→refresh 확인→갱신→저장 정책이 두 벌. Manager에는 사용자별 lock(`252–253`), Service 경로에는 없음. | Manager에 정책을 유지하고 미사용 Service 메서드 제거. |
| `session/auth_service.py` — `get_default_user_email():20–31` | `session/session_manager.py:20–32`; `session/auth_manager.py:38–63` — 동명 함수 | 앞 두 구현은 DB 첫 사용자, Manager는 공통 resolver로 위임하여 정책도 다름. | `mcp_common/user_resolver.py:62–115,134–136` 경로로 통일. |
| `session/time_utils.py` — `is_expired():110–125` | `session/auth_service.py` — `is_token_expired():302–320`; `session/session_manager.py` — `_is_cached_token_expired():148–160` | UTC 현재시각과 만료시각에서 5분 버퍼를 뺀 값을 비교. 문자열·naive datetime 처리에는 차이 있음. | 사용 중인 AuthService 판정에 유지하고 미사용 계층 제거. |
| `_reauth.py` — `main():5–11`; `main.py` — `main():24–81` | `session/auth_manager.py` — `main():646–715` | 브라우저 인증·결과 표시·`finally: close()` CLI 흐름 반복. Manager CLI에는 갱신 메뉴도 있음. | 인증 CLI 구현을 하나로 모으고 문서화된 `main.py`는 진입점으로 유지. |
| `mcp_calendar/mcp_server/server_stdio.py:8–25` | outlook·onedrive의 동명 파일 `8–25`, onenote·teams·time·todo `8–24`, file_handler `18–34` | 모듈 배선 전체: 경로 추가→bootstrap→handlers import→`run_stdio`. **도메인명 치환 후 8개 파일 AST가 동일**. | 3파일 진입점은 유지하고 추가 축약이 필요하면 공통 launcher만 추출. |
| `mcp_calendar/mcp_server/server_stream.py:8–45` — 모듈 배선·`run()` | outlook·onedrive·onenote·teams·time·todo의 동명 파일 `8–45` | **도메인명 치환 후 7개 AST가 동일**. bootstrap→ASGI 앱 생성→`run_http`. | 공통 HTTP 앱/실행 helper로 축약 가능. file_handler의 보안 health 확장은 별도 유지. |
| `mcp_calendar/mcp_server/handlers.py` — `build_mcp_server():97–114` | onedrive `110–128`, onenote `82–99`, outlook `198–216`, teams `161–178`, time `49–66`, todo `102–119`의 같은 함수 | MCP Server 생성, 도구 목록, `validate_input=False`, runtime dispatch 등록이 동일. file_handler `200–217`도 `arguments or {}`만 다름. | 공통 runtime에 Server 생성 함수를 두고 각 handlers는 호출만 수행. |
| `mcp_onedrive/graph_onedrive_client.py` — `_make_request():93–156` | `mcp_onenote/graph_onenote_client.py:137–201`; `mcp_teams/graph_teams_client.py:89–147` — 같은 함수 | 초기화→토큰→Bearer 헤더→HTTP 요청→200/201/204 처리→오류 dict 포장이 거의 동일. timeout·바이너리·`status_code` 차이 존재. | `mcp_common`에 공통 Graph 요청 계층을 추출하고 옵션·반환 차이는 명시적으로 보존. |
| `mcp_onedrive/graph_onedrive_client.py` — `initialize():59–67`, `close():69–74`, `_get_access_token():76–91` | `mcp_teams/graph_teams_client.py:55–63,65–70,72–87`; OneNote `initialize():69–77`, `close():79–84` | 세션 생성·종료·초기화 플래그와 토큰 provider 호출 반복. | 위 공통 Graph 계층에서 관리. |
| `mcp_calendar/graph_calendar_query.py` — `_get_access_token():237–259` | `mcp_outlook/graph_mail_query.py:72–94`; `graph_mail_id_batch.py:54–74` — 같은 함수 | `validate_and_refresh_token` 호출, 빈 토큰·예외 로그, `None` 반환이 동일. | `mcp_common/auth.py`의 공통 호출 helper 또는 공통 Graph 계층으로 이동. |
| `mcp_calendar/graph_calendar_query.py` — `_fetch_data():279–317`, `_post_data():319–365`, `_patch_data():367–415`, `_delete_data():417–454` | `mcp_todo/graph_todo_query.py` — `_fetch():107–128`, `_post():130–156`, `_patch():158–184`, `_delete():186–207` | 요청별 세션 생성, 헤더, 성공 상태 판정, 오류 상세 제한, 결과 포장 반복. DELETE 성공 상태 등은 다름. | HTTP 요청을 공통화하고 허용 상태·도메인 반환 형식은 인자로 분리. |
| `mcp_onenote/graph_onenote_client.py` — `_make_request():137–201` | 같은 파일 — `_make_request_full_url():307–350` | nextLink 요청용 함수가 인증·세션·헤더·HTTP 오류 처리를 재구현. 후자는 오류 상세와 상태코드도 생략. | 상대 endpoint와 전체 URL을 같은 요청 함수에서 처리. |
| `mcp_file_handler/onedrive/client.py` — `_get_access_token/_get_headers:30–63`, `get_item_by_path:65–77`, `list_children:115–127`, `get_file_content:167–179` | `mcp_onedrive/graph_onedrive_client.py` — `_get_access_token/_make_request:76–156`, `get_item:242–264`, `list_files:202–240`, `read_file:270–342` | `/me/drive` 메타데이터·children·content 요청과 Bearer 처리를 독립 구현. 동기 requests 대 비동기 aiohttp, ID/공유 URL 대 경로 방식 차이. | GraphOneDriveClient에 필요한 ID·공유 URL·bytes 기능을 모으고 FileHandler는 변환·다운로드 조립만 담당. |
| `mcp_file_handler/converters/docx/docx_converter.py` — `DOCXConverter.convert():14–54` | `mcp_outlook/mail_attachment_converter.py` — `WordConverter.convert():128–168` | paragraph 및 table→row→cell 텍스트 추출 루프 중복. 입력 경로/BytesIO, 줄바꿈 정책은 다름. | FileHandler의 추출 구현으로 통합하고 입력 어댑터·출력 정책 유지. |
| `mcp_file_handler/converters/pdf/pdf_converter.py` — `PDFConverter.convert():15–44` | `mcp_outlook/mail_attachment_converter.py` — `PdfConverter.convert():86–111` | `pdfplumber.open`→페이지별 `extract_text()`→빈 결과 제외→join 중복. Outlook은 페이지 제목 추가. | FileHandler 추출기에 페이지 제목 옵션 추가 후 공유. |
| `mcp_file_handler/converters/excel/excel_converter.py` — `_convert_with_openpyxl():65–92` | `mcp_outlook/mail_attachment_converter.py` — `ExcelConverter.convert():308–347` | workbook→sheet→`iter_rows(values_only=True)`→tab join→close 반복. 빈 셀 보존 여부는 다름. | FileHandler의 openpyxl 추출기로 통합하되 빈 셀 정책 보존. |
| `mcp_file_handler/base_converter.py` — `BaseConverter:8–45`; `utils/file_detector.py` — `FileDetector.__init__:23–31`, `get_converter:76–91` | `mcp_outlook/mail_attachment_converter.py` — `FileConverter:28–69`, `ConversionPipeline.__init__:443–452`, `get_converter:479–493` | `supports/convert` 인터페이스와 변환기 순차 선택 구조가 두 벌. 입력·지원 포맷은 서로 다름. | FileHandler에 공통 registry와 path/bytes 어댑터를 두고 양쪽에서 사용. |
| `mcp_outlook/mail_attachment_storage.py` — `LocalStorageBackend.save_mail_content():264–317` | 같은 파일 — `OneDriveStorageBackend.save_mail_content():703–756`, `MailFolderManager.save_mail_content():835–888` | 메일 헤더 작성, 본문 선택, HTML 태그·엔티티 제거가 세 벌. HTML 처리는 `mail_attachment_processor.py`의 `process_body_content():79–129`에도 반복. | 메일→텍스트 함수 하나를 공유하고 backend는 저장만 담당. |
| `mcp_outlook/mail_attachment_storage.py` — `LocalStorageBackend.save_file():217–262` | 같은 파일 — `MailFolderManager.save_attachment():784–833` | 파일명 정리, `_1/_2` 충돌 회피, binary write 반복. 후자는 base64 decode 추가. | LocalStorageBackend 내부 저장 helper를 공유. |
| `mcp_file_handler/utils/logger.py` — `setup_logger():9–54` | `mcp_common/bootstrap.py` — `_configure_logging():127–133` | level·formatter·console handler 설정이 두 경로. FileHandler는 stdout/개별 handler, bootstrap은 stderr/root 설정. | console 설정은 bootstrap으로 통일하고 필요한 파일 handler만 별도 유지. |
| `mcp_calendar/calendar_types.py` — `DateTimeTimeZone.get/__getitem__/keys():37–47`, `EmailAddress:67–77`, `ItemBody:290–300` | `mcp_outlook/outlook_types.py` — `FilterParams:107–117`, `ExcludeParams:166–176`, `SelectParams:232–238` | `getattr` 기반 dict 호환 메서드 반복. | 공통 Pydantic 호환 베이스/믹스인으로 이동. |
| `mcp_calendar/calendar_types.py` — `DateTimeTimeZone:16–47`, `ItemBody:275–300` | `mcp_todo/todo_types.py` — `DateTimeTimeZone:23–35`, `ItemBody:38–46` | 같은 Graph 필드 구조 재정의. 시간대 기본값 UTC/Korea Standard Time, 본문 html/text·필수 여부 차이 있음. | 공통 필드 기반 모델을 추출하고 도메인별 정책은 파생 모델로 유지. |
| `mcp_onedrive/onedrive_types.py` — `UserInfo/from_dict:26–39` | `mcp_teams/teams_types.py` — `UserInfo/from_dict:33–48` | id·display_name·email 및 `data.get("user", data)` 파싱 동일. Teams만 추가 필드 보유. | 공통 UserInfo에 Teams 확장 모델 적용. |
| `session/test/test_login_with_monitoring.py` — `check_db_state():31–137` | `session/test/test_email_fetch_with_monitoring.py` — `check_db_state():31–93` | 실제 auth.db 조회·토큰 상태 출력·ISO/UTC 만료 비교 반복. 로그인 쪽은 추가 통계 포함. | 수동 진단을 유지한다면 DB 상태 조회 함수를 공유. |
| `S/health_check.py` — `DEFAULT_PORTS:27–34`, `main:55–62` | `S/register_claude_code.py:25–32,44–51`; `stop_server.py:23–30,59–68`; `verify_setup.py`의 `_srv/SERVERS:54–69`; `register_claude_desktop.py:29,43–50` | 6개 도메인 목록·포트·대상 선택 반복. 도메인 handlers에도 `SPEC.port or 500x`가 남음: calendar/onenote/teams/todo `28`, onedrive `27`, outlook `41`, time `24`, file_handler `48`. | 서버 목록·포트는 param_spec에서 파생하고 CLI 대상 선택만 공통 helper로 분리. |
| `S/health_check.py` — `probe():37–44` | `E/assets/verify_bundle.py` — `check_http()` 내부 `195–201` | `/health` HTTP 조회·JSON 해석·실패 처리 중복. export에는 시작·재시도·종료가 추가됨. | 단일 health 요청 helper만 공유. |
| `mcp_outlook/tests/run_tests.py` — `test_converter:92–139`, `test_storage:142–211`, `test_integration:214–256`, `test_metadata:259–313` | `test_mail_attachment_converter.py:96–163,289–301`; `test_mail_attachment_storage.py:30–206`; `test_integration.py:182–223,236–284` | 변환·저장·전체 흐름·중복 ID 시나리오 반복. 특히 수동 runner의 metadata 테스트는 제품 클래스 대신 자체 dict를 검사함. | 실제 제품 클래스를 검증하는 pytest 테스트로 통합. |

## 3. 규칙 위반

| 파일:줄 | 내용 |
|---|---|
| [mcp_common/runtime.py:82–89](E:/dev/KR_MS365_mcp/mcp_common/runtime.py:82) | `ToolRuntime.input_schema()`가 빈 스키마 대체와 누락된 `type="object"` 보정을 직접 수행함. 같은 책임은 `schema_normalize.normalize_input_schema():72–99`에 있으므로 **스키마 형태 보정의 단일 진입점 규칙 위반**. 두 구현의 보정 범위도 다름. |
| [mcp_file_handler/mcp_server/tool_definitions.py:18–20](E:/dev/KR_MS365_mcp/mcp_file_handler/mcp_server/tool_definitions.py:18) | 사용자 제시 **3파일 구조 규칙과 불일치**하는 네 번째 구현 파일. 다만 내용은 `load_param_spec()`·`SPEC.mcp_tools()` 재수출이므로 **도구 정의 SSOT 중복은 아님**. `handlers.py:42`, `mcp_server/__init__.py:8`에서 사용되며, import 부수효과를 피하려는 이유가 파일 `8–10`행과 `spec/spec_MCP트랜스포트.md:183`에 기록되어 있음. 단독 삭제는 부적절. |

8개 도메인 핸들러에서 **도구 인자 기본값 하드코딩이나 별도 boolean 보정 우회는 발견하지 못했습니다.** `ParamSpec.coerce_arguments()`는 미사용 잔존 API이며, 실제 이중 보정 호출로 판정하지 않았습니다. 위 포트 fallback은 도구 인자 기본값과 구별되는 설정 중복입니다.

## 4. 보류/확인 필요

| 항목 | 확인 결과 |
|---|---|
| `core/protocols.py` | 삭제 제외. `TokenProviderProtocol`을 Calendar·OneDrive·OneNote·Outlook·Teams·Todo의 12개 Graph/첨부 모듈에서 타입용으로 import함. 예: `graph_calendar_client.py:9`, `graph_mail_client.py:11`, `mail_attachment_storage.py:28`. `mcp_common/auth.py:12–16`은 공유 인증 객체 접근점이므로 Protocol 대체물이 아님. |
| `main.py`, `callback_server.py`, `conftest.py`, `MANIFEST.in` | 각각 사용 근거 있음. `main.py`는 `README.md:22,121`, `session/README.md:32`에 안내. callback은 `auth_manager.py:479–481`에서 import·생성. conftest는 pytest 자동 로드 설정(`20–41`). MANIFEST `4`행은 sdist에 param_spec YAML을 포함함. |
| `auth_manager.py`와 `auth_service.py` 전체 | 전체 파일끼리 중복으로 삭제할 수 없음. `auth_manager.py:19,91`에서 AuthService 사용, `callback_server.py:61,146`에서도 사용. 정리 대상은 위의 미사용 갱신 정책 메서드. |
| `session/test/`와 `session/tests/` | 전자는 `input()`·브라우저·실제 DB/Graph를 사용하는 수동 진단(`test_login_with_monitoring.py:159,176–181`, `test_email_fetch_with_monitoring.py:230`). 후자는 `tmp_path` 기반 회귀 테스트(`test_auth_database.py:14–30`). 기본 pytest는 후자만 수집(`pyproject.toml:123–133`). 디렉터리 두 벌 자체는 테스트 중복 근거가 아님. 수동 진단 보존 여부는 확인 필요. |
| `session/time_utils.py`와 `mcp_time/time_service.py` | 기능 전체는 다름. TimeService는 `_resolve_tz():25–33`, `get_current_time():35–55`의 현재시간 MCP 서비스. time_utils 삭제 근거는 무참조이며, 모든 함수를 TimeService로 옮길 필요는 없음. |
| FileHandler의 OneDrive 세 파일 | 사용 중: `file_manager.py:25,56`→`processor.py:23–24`→`downloader.py:53,85,131`. `tests/test_onedrive.py:7,17,78,155`도 참조. 재귀 다운로드·임시 파일·공유 URL 기능을 보존한 후 통합해야 함. |
| FileHandler `base_converter.py`, `config/settings.py`, `utils/logger.py` | BaseConverter는 실제 변환기 상속 기반. Settings는 `file_manager.py:26,52`에서 사용하며 공통 모듈에 동등한 설정 클래스가 없음. logger도 `file_manager.py:28,59`에서 호출됨. 즉시 삭제할 파일은 아님. |
| Outlook 첨부 converter·processor·storage | `mail_attachment.py:38–45`에서 import, `175,552,618,625`에서 생성·호출. 부분 중복 정리 대상이지 세 모듈 전체 삭제 대상은 아님. HWP 구현도 라이브러리·stream 처리 차이가 있어 동일 복붙으로 판정하지 않음. |
| `graph_mail_id_batch.py`, `graph_mail_url.py` | 사용 중. batch는 `graph_mail_client.py:14,91` import·생성 후 `397,821,879,936`에서 호출. URL builder는 `graph_mail_query.py:34,121`, `mail_attachment.py:37,184`에서 사용. |
| `onenote_agent.py` | 사용 중. `onenote_service.py:51,56`에서 지연 import·생성, reader/writer에 주입(`59,65`). `onenote_read.py:159,190`에서 검색·요약 호출. |
| `mcp_outlook/tests/test_integration.py` | pytest 수집 대상이며 import 대상도 존재. 정적 검토에서 실행 불가 근거는 찾지 못함. 실제 통과 여부는 실행하지 않아 미확인. |
| Graph 공통화 범위 | `mcp_common/net.py:30–82`는 **서버 bind 정책**, `errors.py:40–79`는 **MCP 결과 변환**이므로 기존 함수로 HTTP 요청을 바로 대체할 수 없음. 페이징도 OneNote `list_pages():352–410`의 nextLink 순회, Outlook `_fetch_parallel_with_url():728–865`의 병렬 skip 방식이 달라 동일 복붙으로 판정하지 않음. |

스킬 스크립트는 모두 사용 근거가 확인됐습니다.

| 대상 | 실제 참조·판단 |
|---|---|
| setup `check_token.py` | `setup_ms365/SKILL.md:263`. 본체 `AuthManager.validate_and_refresh_token`을 재사용(`32–48`). 인증 구현의 복제 아님. |
| setup `health_check.py`, `streamable_http_probe.py` | 각각 SKILL `304`, `274`. 후자는 `run_probes():123–302`에서 MCP 세션·Accept·SSE·도구 조회 등을 검사하므로 health 조회와 역할이 다름. |
| setup `register_claude_code.py`, `register_claude_desktop.py` | SKILL `157,222` 및 `158,227`. Code는 HTTP 등록(`53–69`), Desktop은 STDIO 실행정보 등록(`69–81`). 공통 설정 목록 외 전체 중복 아님. |
| setup `stop_server.py`, `verify_setup.py` | SKILL `316–318` 및 `124,332`. 각각 PID 종료와 설치 상태 검사. bootstrap·OAuth callback 서버의 재구현 아님. |
| export `build_bundle.py`, `publish_bundle.py`, `sandbox_test.py` | `export_ms365/SKILL.md:108`, `142–149`, `125`에 실제 호출. 번들 생성·배포·샌드박스 실행으로 역할 분리. |
| export `assets/verify_bundle.py`, `assets/sandbox_runner.ps1` | verifier는 `build_bundle.py:466`에서 복사되고 runner `135`에서 실행. runner는 `sandbox_test.py:102`에서 복사되어 WSB 실행 명령(`56`)에 사용됨. verifier는 본체 `bootstrap_http`를 재사용(`124,132`)하며, runner도 같은 verifier를 호출하므로 검증기 두 벌이 아님. |

공개 API의 저장소 밖 사용 여부와 수동 운영 스크립트의 실제 사용 빈도는 이번 감사만으로 확인할 수 없습니다. Git 명령에는 사용자 전역 ignore 파일 접근 권한 경고가 있었으며, 저장소 기준 비무시 미추적 파일 결과는 0개였습니다.

삭제 우선순위는 `_reauth.py`, 미사용 Session 계층·시간 유틸·첨부 호환 래퍼, 미사용 갱신/보정 메서드입니다.  
중복 정리 효과는 Graph 요청 계층과 파일 변환·메일 본문 저장 코드에서 큽니다.  
도메인 transport는 이미 공통화되어 있으며, 남은 반복은 주로 진입점 배선과 Server 등록 코드입니다.