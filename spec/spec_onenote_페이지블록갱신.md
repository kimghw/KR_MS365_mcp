# spec — OneNote 페이지 블록 갱신 (replace · include_ids · list_pages web_url)

## ① 질의·요청 히스토리

- 2026-09-27 (kr_ext_rerp 확장 Plus): 원노트 페이지 링크 하나로 과제 예상 비용을 여러 사람이 동기화하고 싶다.
  기존 `write_onenote` 는 `append` 만 노출해 페이지가 계속 자라고, `get_content` 는 id·data-id 를 안 주고,
  `list_pages` 는 사용자가 복사한 페이지 링크와 대응할 값이 없었다.

## ② 확정 사양

`spec/param_spec/onenote.yaml` 이 원본. 여기서는 의미만 적는다.

| 도구 | 추가 | 설명 |
|---|---|---|
| `read_onenote` | `include_ids` (boolean, 기본 false) | `get_content` 를 Graph `includeIDs=true` 로 조회해 요소의 생성 id 와 작성 때 붙인 `data-id` 를 HTML 에 포함 |
| `read_onenote` | `list_pages` 응답의 `web_url` | DB 의 `web_url`(`links.oneNoteWebUrl`). 사용자가 복사한 페이지 링크의 페이지 GUID 로 page_id 를 찾는 용도 |
| `write_onenote` | `action: replace` + `target` | `page_id` 의 `target` 요소를 `content` 로 통째로 교체 (Graph PATCH `replace`). `page_id`·`target`·`content` 모두 필수 |

- `target` 은 `include_ids` 로 읽은 **생성 id**(`table:{guid}{n}`)를 준다. `#data-id` 는 Graph 가 table 500 · p/ul 400 을 내고
  div 는 대상이 안 된다 → [references/graph_onenote_patch.md](../references/graph_onenote_patch.md).
- 서비스 계층: `OneNoteWriter.replace()` → `edit_page(action=PageAction.REPLACE, target=…)` (변경 이력·요약 갱신은 append 와 동일).
  `OneNoteReader.get_content(include_ids)` → `GraphOneNoteClient.get_page_content(include_ids=…)` (`?includeIDs=true`).

## ③ 구현 상태

- 2026-09-27 구현·테스트 완료 (`mcp_onenote/tests/test_onenote_service.py`: replace 라우팅·필수값·include_ids 전달·web_url).
  실서버(5005)에서 kr_ext_rerp 의 Node 클라이언트로 append → 읽기(생성 id) → replace → 읽기 왕복 확인.
- 기존 실패 2건(`test_reader_list_pages_empty_triggers_sync`, `test_writer_append_no_recent_page`)은 이 변경 전부터 실패하던 것(이번 범위 밖).

## ④ 미결/후속

- `replace` 가 한 번에 요소 하나만 바꾼다. 여러 요소를 한 PATCH 로 바꾸려면 commands 배열을 받는 도구가 필요.
- `list_pages` 는 로컬 DB 기반이라 새 페이지·공유 노트북은 `sync_onenote_db` 뒤에야 보인다(클라이언트가 못 찾으면 sync 뒤 재시도).
