# 보안·정확성 검토 반영 (2026-10 외부 코드 리뷰)

## ① 질의·요청 히스토리

- 2026-10-20 — 사용자가 외부 코드 리뷰 결과(보안 3건 + 기능·운영 10건)를 붙여넣고
  "검토하고 필요한 부분 반영" 요청. 리뷰는 코드를 수정하지 않은 분석이었고, 기본 테스트는
  202 통과 / 2 실패 / 6 준비 오류 / 4 생략 상태였다.
- 같은 날 — 13건을 코드와 대조해 11건 그대로 반영, 1건 부분 반영(Outlook 페이징),
  1건 반려(OneNote 요약 캐시 사용자 구분). 아래 ②.

## ② 확정 사양

| 항목 | 확정 내용 | 적용 위치 |
|------|-----------|-----------|
| Outlook URL 조회 | `_fetch_parallel_with_url` 이 **https + `graph.microsoft.com`** 이 아닌 URL 에는 토큰을 붙이지 않고 `status:error` 를 돌려준다. `query_url` 은 호출자 URL 을 그대로 받으므로 공통 함수에서 막는다. | [graph_mail_query.py](../mcp_outlook/graph_mail_query.py) `ALLOWED_GRAPH_HOSTS` |
| Outlook 페이징 | `$skip` 병렬 조회는 **속도를 위한 설계로 유지**한다. 대신 수집 후 `id` 로 중복 제거한다. `nextLink` 순차 전환은 하지 않는다(④). | 같은 파일, 수집 직후 |
| OneDrive 경로 | `/me/drive/root:/{path}` 의 path 는 전부 `_enc()`(`quote(path, safe="/")`) 로 인코딩한다. `search(q='…')` 는 `'`→`''` 후 인코딩. | [graph_onedrive_client.py](../mcp_onedrive/graph_onedrive_client.py) |
| HTTP Host/Origin | SDK 의 `TransportSecuritySettings` 를 켠다. 기본 허용: `localhost:*`, `127.0.0.1:*`, `[::1]:*` (+ `http://` 오리진). `MCP_BIND_HOST` 가 특정 IP 면 자동 포함, 추가는 `MCP_ALLOWED_HOSTS` / `MCP_ALLOWED_ORIGINS`(쉼표 구분). 실패 시 421/403. 호출자 인증은 범위 밖(④). | [http_transport.py](../mcp_common/http_transport.py) `transport_security()` |
| Teams 동기화 | `list_chats` 가 `has_more`(nextLink 존재)를 돌려주고, `sync_chats_to_db(deactivate_missing=not has_more)` — **전체 목록일 때만** 누락 채팅을 비활성화한다. | [teams_db_manager.py](../mcp_teams/teams_db_manager.py), [teams_service.py](../mcp_teams/teams_service.py) |
| Teams 상대방 | 1:1 채팅의 상대방 = 멤버 중 이메일/UPN 이 본인(user_id, 대소문자 무시)과 다른 첫 멤버. 못 찾으면 종전대로 `members[1]`. | `_member_email()` |
| 첨부파일 완료 표시 | 본문·첨부 저장 실패는 `result["errors"]` 에 남기고, **그 메일에서 오류가 하나도 없을 때만** `add_processed_mail` 로 완료 표시한다(재시도 가능). | [mail_attachment.py](../mcp_outlook/mail_attachment.py) Step 5, [mail_attachment_processor.py](../mcp_outlook/mail_attachment_processor.py) |
| 캘린더 시간대 | calendarView 의 start/end 는 오프셋이 없으면 **`+09:00` 을 붙인다**(생성 기본 "Korea Standard Time" 과 동일 기준). 값은 `quote(..., safe="")` 로 퍼센트 인코딩. param_spec 설명에 명시. | [graph_calendar_query.py](../mcp_calendar/graph_calendar_query.py) `DEFAULT_UTC_OFFSET`, [calendar.yaml](param_spec/calendar.yaml) |
| 현재 시간 도구 | `tzdata; sys_platform == 'win32'` 를 필수 의존성으로 추가. 모르는 시간대 폴백은 `datetime.timezone.utc`. | [pyproject.toml](../pyproject.toml), [time_service.py](../mcp_time/time_service.py) |
| file_handler OneDrive | 공유 URL 토큰에 `u!` 접두사. `download_folder(output_dir=None)` 은 임시 디렉터리를 기준으로 잡아 하위 폴더 구조를 보존한다. | [client.py](../mcp_file_handler/onedrive/client.py), [downloader.py](../mcp_file_handler/onedrive/downloader.py) |
| OneNote 최초 동기화 | `list_pages` 가 비어서 `sync_db` 를 불렀을 때 실패하면 `success:false` + error 로 돌려준다("페이지 0개" 로 포장하지 않음). | [onenote_read.py](../mcp_onenote/onenote_read.py) |
| 인증 콜백 | 쿼리 문자열(code 포함) 로그 제거. HTML 에 들어가는 error/description/user_email 은 `html.escape`. `error` 응답은 **진행 중인 state 와 일치할 때만** 대기자를 깨운다. code/state 가 없는 요청은 400 만 주고 대기 상태를 건드리지 않는다. | [callback_server.py](../callback_server.py) |
| refresh 만료 | `refresh_token_expires_at` 은 **새 refresh_token 이 저장될 때마다 +90일로 민다**(Azure sliding window). `reset_refresh_expiry` 분기 삭제. 만료 전 로컬 판정은 유지. | [auth_database.py](../session/auth_database.py) `save_token` |

반려 1건 — OneNote 요약 캐시의 사용자 구분: `onenote_page_summaries.page_id` 는 Graph 전역
고유 ID 이고 UNIQUE 다. 다른 사용자가 같은 page_id 에 닿는 경우는 공유 페이지뿐이며 그때의
요약은 같은 내용이므로 분리하지 않는다.

## ③ 구현 상태

- 2026-10-20 — ② 전부 반영. 신규 회귀 테스트 15개 추가(`mcp_common/tests`, `mcp_calendar/tests`,
  `mcp_time/tests`, `session/tests` 신설 — pyproject `testpaths` 등록). 구현 변경을 못 따라온
  기존 테스트 3건 수정(첨부 핸들러 fixture 의 `AuthManager` 패치 → `token_provider` 주입,
  OneNote `list_pages` 재조회 횟수, `append` 의 no_recent_page 는 soft 성공).
- 테스트: **230 통과 / 0 실패 / 4 생략**(생략은 선택 변환 라이브러리 미설치). `uv lock` 으로
  tzdata 잠금, `requirements.txt` 재export.
- 외부 지식은 references 에 분리: [microsoft_graph_api.md](../references/microsoft_graph_api.md),
  [microsoft_entra_tokens.md](../references/microsoft_entra_tokens.md),
  [mcp_streamable_http_security.md](../references/mcp_streamable_http_security.md),
  [python_zoneinfo_windows.md](../references/python_zoneinfo_windows.md).

## ④ 미결/후속

- Outlook 페이징을 `nextLink` 순차 방식으로 바꿀지 — 현재는 병렬 유지 + 중복 제거. 누락(경계
  밀림으로 빠진 한 통)까지 없애려면 순차 전환이 필요하며 속도와 맞바꾼다.
- HTTP 서버 외부 공개 시 호출자 인증(API 키/OAuth) — 바인드 옵트인(`MCP_ALLOW_PUBLIC_BIND`)만
  있고 인증 계층은 없다.
- Graph 요청의 타임아웃·`Retry-After`·안전한 재시도 공통화(리뷰 권고, 미착수).
- Ruff 2,190건(대부분 스타일·구형 타입 표기) 정리 — 별도 작업.
