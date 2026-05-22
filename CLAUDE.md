# 변경 시 서브 에이전트에서 readme.md 작성

## OneNote DB 관리 (onenote_items 테이블)

### 테이블 위치
- `database/onenote.db` > `onenote_items`, `onenote_page_summaries`, `onenote_page_changes` 테이블

### 컬럼 구조
| 컬럼 | 설명 |
|------|------|
| item_type | `'section'` 또는 `'page'` |
| item_id | 페이지/섹션 고유 ID |
| item_name | 페이지 제목 또는 섹션 이름 |
| notebook_id | 소속 노트북 ID |
| notebook_name | 소속 노트북 이름 |
| section_id | 소속 섹션 ID |
| section_name | 소속 섹션 이름 |
| web_url | OneNote 웹 브라우저 URL |
| last_accessed | 최근 접근 시각 |

### DB 저장 시점
- **페이지 생성 시**: `create_page()` 호출 후 자동으로 DB에 저장
- **sync_db 호출 시**: `/me/onenote/pages`로 전체 페이지를 조회하여 DB 동기화
  - notebook_id, notebook_name, section_id, section_name, web_url 모두 포함
  - 5000개 제한(403) 회피를 위해 섹션별이 아닌 **전체 페이지 기준**으로 조회

### Graph API 호출
- `list_pages`에서 `$expand=parentSection($expand=parentNotebook)` 사용
- 한 번의 API 호출로 페이지 + 섹션 + 노트북 정보를 모두 가져옴

### 주요 파일
- `mcp_onenote/onenote_db_service.py` — DB 저장/조회/동기화
- `mcp_onenote/onenote_service.py` — Facade (create_page, sync_db)
- `mcp_onenote/graph_onenote_client.py` — Graph API 호출
- `mcp_onenote/onenote_types.py` — PageInfo 데이터 모델