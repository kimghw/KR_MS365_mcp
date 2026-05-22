> **공통 지침**: 작업 전 [common.md](common.md) 참조

# MCP 서버 테스트 가이드

## 테스트 유형 선택
사용자에게 다음 중 테스트할 항목을 선택하도록 요청하세요. 1개 이상 선택 가능합니다.

---

## 1. MCP Outlook 서버 테스트

### 인증 정보
- 계정: `kimghw@krs.co.kr`
- 세션을 통해 메일 조회 시 자동 인증 진행

### 테스트 순서
```bash
# 1. 서버 시작
cd /home/kimghw/Connector_auth
uvicorn mcp_outlook.mcp_server.server_rest:app --host 0.0.0.0 --port 8001 --reload

# 2. 도구 목록 확인
curl http://localhost:8001/mcp/v1/tools/list

# 3. 개별 도구 테스트
```

### 현재 등록된 도구 목록
| 도구명 | 서비스 매핑 | 설명 |
|--------|------------|------|
| `mail_list_period` | `query_mail_list` | 기간별 메일 목록 조회 |
| `mail_list_keyword` | `fetch_search` | 키워드로 메일 검색 |
| `mail_query_if_emaidID` | `batch_and_fetch` | 메일 ID로 상세 조회 |
| `mail_fetch_filter` | `fetch_filter` | 필터 조건으로 메일 조회 (본문 포함) |
| `mail_fetch_search` | `fetch_search` | 키워드 검색 (본문 포함) |
| `mail_process_with_download` | `process_with_download` | 메일 조회 및 첨부파일 다운로드 |
| `mail_query_url` | `fetch_url` | Graph API URL 직접 호출 |
| `mail_attachment_meta` | `fetch_attachments_metadata` | 첨부파일 메타정보 조회 |
| `mail_attachment_download` | `download_attachments` | 첨부파일 다운로드 |

---

## 2. MCP Calendar 서버 테스트

### 테스트 순서
```bash
# 1. 서버 시작
cd /home/kimghw/Connector_auth
uvicorn mcp_calendar.mcp_server.server_rest:app --host 0.0.0.0 --port 8002 --reload

# 2. 도구 목록 확인
curl http://localhost:8002/mcp/v1/tools/list
```

---

## 3. 병합 서버 테스트 (ms365 등)

### 병합 서버 생성 및 테스트
```bash
# 1. 병합 서버 생성
python jinja/generate_universal_server.py merge \
    --name ms365 \
    --sources outlook,calendar \
    --port 8090 \
    --protocol all

# 2. 서버 시작
uvicorn mcp_ms365.mcp_server.server_rest:app --host 0.0.0.0 --port 8090 --reload

# 3. 도구 목록 확인 (병합된 도구 확인)
curl http://localhost:8090/mcp/v1/tools/list
```

### 테스트 예시
```bash
# mail_list_period 테스트
curl -X POST http://localhost:8001/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "mail_list_period",
    "arguments": {
      "DatePeriodFilter": {
        "received_date_from": "2026-01-01",
        "received_date_to": "2026-01-07"
      }
    }
  }'

# mail_attachment_meta 테스트
curl -X POST http://localhost:8001/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "mail_attachment_meta",
    "arguments": {
      "message_ids": ["MESSAGE_ID_HERE"]
    }
  }'
```

---

## 4. 파라미터 처리 테스트

### 테스트 대상
- **Signature**: LLM이 직접 제공하는 파라미터
- **Signature Defaults**: 기본값이 있는 파라미터
- **Internal**: 시스템 고정값 (select_params 등)

### 테스트 절차
1. 백그라운드 프로세스 종료
```bash
pkill -f "uvicorn.*8001"
```

2. 서버 시작 (각 프로토콜별)
```bash
# REST 서버
python mcp_outlook/mcp_server/server_rest.py

# STDIO 서버 (별도 터미널)
python mcp_outlook/mcp_server/server_stdio.py

# Stream 서버 (별도 터미널)
python mcp_outlook/mcp_server/server_stream.py
```

3. Internal 파라미터 확인 (select_params)
```bash
# mail_list_period 호출 후 응답에서 select_params가 적용되었는지 확인
# 응답 필드: id, subject, sender, bodyPreview, hasAttachments, receivedDateTime, internetMessageId
```

### 확인 사항
- [ ] Signature 파라미터가 정상 전달되는지
- [ ] Signature Defaults가 미입력 시 적용되는지
- [ ] Internal 파라미터(select_params)가 응답에 반영되는지
- [ ] targetParam 매핑이 올바른지

---

## 5. 서버 대시보드 테스트

### 대시보드 API 테스트
```bash
# 대시보드 전체 상태 조회
curl http://localhost:5000/api/server/dashboard

# 프로토콜별 서버 시작
curl -X POST "http://localhost:5000/api/server/start?profile=outlook&protocol=rest"

# 프로토콜별 서버 중지
curl -X POST "http://localhost:5000/api/server/stop?profile=outlook&protocol=rest"

# 로그 조회
curl "http://localhost:5000/api/server/logs?profile=outlook&protocol=rest&lines=50"
```

### 프로토콜별 독립 제어 확인
- [ ] REST만 실행 후 다른 프로토콜 상태 확인 (STDIO, Stream은 Stopped)
- [ ] 여러 프로토콜 동시 실행 확인
- [ ] 개별 프로토콜 재시작 시 다른 프로토콜 영향 없음 확인

---

## 6. 사용자 지정 테스트

사용자가 특정 기능 테스트를 요청한 경우 위 항목을 참조하여 진행합니다.

### 일반 테스트 체크리스트
- [ ] 서버 정상 시작 확인
- [ ] 도구 목록 조회 정상
- [ ] 개별 도구 호출 정상
- [ ] 에러 처리 정상
- [ ] 응답 형식 확인

---

## 프로토콜별 테스트 방법

### REST (port 8001)
```bash
curl http://localhost:8001/mcp/v1/tools/list
curl -X POST http://localhost:8001/mcp/v1/tools/call -d '{"name":"...", "arguments":{...}}'
```

### STDIO
```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python mcp_outlook/mcp_server/server_stdio.py
```

### Stream (SSE)
```bash
curl http://localhost:8002/mcp/v1/tools/list
```

---

## 웹에디터에서 테스트

### 대시보드 활용
1. 웹에디터 좌측 상단 **MCP 로고** 클릭 → 대시보드 모달 열기
2. 테스트할 프로필 선택
3. 원하는 프로토콜 선택 (REST/STDIO/Stream)
4. **Start** 버튼으로 서버 시작
5. 상태 확인 및 로그 모니터링

---

*Last Updated: 2026-01-11*
*Version: 1.1*
*변경사항: 서버 대시보드 테스트, 프로토콜별 독립 제어 테스트 추가*
