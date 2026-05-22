# TODO - mcp_outlook 코드 버그 수정

> 검토일: 2026-02-07
> 대상: `mcp_outlook/` 패키지

## 현재 작동하는 기능

- FETCH_ONLY 모드 메일 조회, 검색, 필터 — 정상

---

## Bug Fixes

### 1. `ProcessingOptions` / `MailProcessorHandler` 미정의
- **파일**: `mcp_outlook/graph_mail_client.py` (line 635, 654)
- **증상**: `batch_and_process()`에서 `processing_mode != FETCH_ONLY`일 때 **NameError**
- **원인**: `ProcessingOptions`, `MailProcessorHandler` 클래스가 import도 없고 정의도 없음
- **영향**: 현재는 `FETCH_ONLY` 기본값으로만 호출되어 dead code이나, 다른 모드 사용 시 즉시 실패
- **조치**: 미구현 코드 경로를 `NotImplementedError`로 대체하여 명시적 에러 처리
- [x] 수정 완료

### 2. `mail_storage.value` / `attachment_handling.value` AttributeError
- **파일**: `mcp_outlook/graph_mail_client.py` (line 678-679)
- **증상**: plain string 파라미터에 `.value` 접근 → **AttributeError**
- **원인**: 시그니처가 `mail_storage: str`, `attachment_handling: str`인데 Enum처럼 `.value` 호출
- **영향**: Finding 1과 같은 dead path이므로 현재 실행되지 않으나 수정 필요
- **조치**: Finding 1의 `NotImplementedError` 대체로 해당 코드 경로 자체가 제거되어 자동 해소
- [x] 수정 완료

### 3. `BatchAttachmentHandler`에서 `self.auth_manager` 미정의
- **파일**: `mcp_outlook/mail_attachment.py` (line 452)
- **증상**: `fetch_and_save`에서 `self.auth_manager`를 `get_storage_backend`에 전달 → **AttributeError**
- **원인**: `__init__`에서 `self.token_provider`로 저장하는데 `self.auth_manager`로 참조
- **영향**: `save_file=True`인 모든 첨부파일 다운로드/변환/OneDrive 경로 비작동
- **조치**: `self.auth_manager` → `self.token_provider`로 수정
- [x] 수정 완료

### 4. `close()` 메서드들에서 `self.auth_manager.close()` 호출
- **파일**: `mcp_outlook/mail_attachment.py` (line 721), `mcp_outlook/graph_mail_id_batch.py` (line 318)
- **증상**: 두 클래스 모두 `self.auth_manager.close()` 호출 → **AttributeError**
- **원인**: `self.token_provider`로 저장했는데 `self.auth_manager`로 참조
- **영향**: `GraphMailClient.close()` → `mail_batch.close()` 연쇄 실패로 리소스 정리 불가
- **조치**: `self.auth_manager.close()` → `self.token_provider.close()`로 수정
- [x] 수정 완료

### 5. 첨부파일 처리 플로우 전체 비작동
- **관련**: Finding 3, 4의 결과
- **영향**: `fetch_and_save`, `download_attachments` 등 `save_file=True` 경로 전부 실패
- **조치**: Finding 3, 4 수정으로 자동 해소
- [x] 수정 완료
