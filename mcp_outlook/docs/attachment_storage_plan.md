# 첨부파일 저장 시스템

## 1. 개요

### 1.1 목적
메일 첨부파일 저장 시 다양한 저장소(로컬/OneDrive) 및 파일 변환(TXT) 옵션을 지원하는 확장 가능한 구조 구현

### 1.2 현재 상태 (구현 완료)
- `mail_attachment.py`: BatchAttachmentHandler로 배치 첨부파일 처리
- `mail_attachment_storage.py`: Local/OneDrive 저장 Backend 구현
- `mail_attachment_converter.py`: PDF/DOCX/HWP/XLSX/PPTX → TXT 변환 구현
- OneDrive 대용량 파일 업로드 (Upload Session) 지원

---

## 2. 파일 구조

```
mcp_outlook/
├── mail_attachment.py           # 배치 첨부파일 핸들러
│   ├── MailFolderManager        # 로컬 폴더/파일 관리
│   ├── MailMetadataManager      # 메타데이터/중복 관리
│   ├── BatchAttachmentHandler   # 배치 처리 (메인 진입점)
│   └── SingleAttachmentHandler  # 개별 첨부파일 처리
│
├── mail_attachment_storage.py   # 저장소 Backend
│   ├── StorageBackend (ABC)     # 추상 인터페이스
│   ├── LocalStorageBackend      # 로컬 디스크 저장
│   └── OneDriveStorageBackend   # OneDrive 저장 (청크 업로드 지원)
│
├── mail_attachment_converter.py # 파일 변환기
│   ├── FileConverter (ABC)      # 추상 인터페이스
│   ├── PdfConverter             # PDF → TXT
│   ├── WordConverter            # DOCX → TXT
│   ├── HwpConverter             # HWP/HWPX → TXT
│   ├── ExcelConverter           # XLSX → TXT
│   ├── PowerPointConverter      # PPTX → TXT
│   ├── PlainTextConverter       # TXT/CSV/JSON 등
│   └── ConversionPipeline       # 변환기 라우팅
│
└── docs/
    └── attachment_storage_plan.md  # 본 문서
```

---

## 3. 아키텍처

### 3.1 클래스 다이어그램

```
┌─────────────────────────────────────────────────────────────┐
│                    BatchAttachmentHandler                    │
├─────────────────────────────────────────────────────────────┤
│ + fetch_and_save(                                            │
│       user_email, message_ids,                               │
│       storage_type, convert_to_txt, onedrive_folder         │
│   )                                                          │
│ + fetch_metadata_only()                                      │
│ + fetch_specific_attachments()                               │
└──────────────────────────┬──────────────────────────────────┘
                           │ uses
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
┌─────────────────┐ ┌───────────────┐ ┌───────────────────┐
│MailFolderManager│ │Conversion     │ │StorageBackend     │
│                 │ │Pipeline       │ │(ABC)              │
├─────────────────┤ ├───────────────┤ ├───────────────────┤
│+create_folder() │ │+can_convert() │ │+create_folder()   │
│+save_attachment │ │+convert()     │ │+save_file()       │
└─────────────────┘ └───────────────┘ │+save_mail_content()│
                                      └─────────┬─────────┘
                                           ┌────┴────┐
                                           ▼         ▼
                                    ┌──────────┐ ┌──────────┐
                                    │LocalStor │ │OneDrive  │
                                    │ageBackend│ │Storage   │
                                    └──────────┘ └──────────┘
```

### 3.2 처리 흐름

```
┌──────────────────────────────────────────────────────────────┐
│ 입력: user_email, message_ids, storage_type, convert_to_txt  │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  Graph API $batch   │
                    │  (메일 + 첨부파일)   │
                    └──────────┬──────────┘
                               │
              ┌────────────────┴────────────────┐
              ▼                                  ▼
       ┌─────────────┐                   ┌─────────────┐
       │  본문 처리   │                   │ 첨부파일 처리│
       └──────┬──────┘                   └──────┬──────┘
              │                                  │
              └────────────────┬─────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ convert_to_txt?     │
                    └──────────┬──────────┘
                         ┌─────┴─────┐
                         ▼           ▼
                       True        False
                         │           │
                         ▼           │
              ┌───────────────────┐  │
              │ ConversionPipeline│  │
              │ (TXT 변환)        │  │
              └─────────┬─────────┘  │
                        │            │
                        └─────┬──────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │ storage_type?       │
                    └──────────┬──────────┘
                          ┌────┴────┐
                          ▼         ▼
                       local    onedrive
                          │         │
                          ▼         ▼
                   ┌─────────┐ ┌──────────┐
                   │LocalSave│ │OneDrive  │
                   │         │ │Upload    │
                   └─────────┘ └──────────┘
```

---

## 4. API 사용법

### 4.1 기본 사용 (로컬 저장 + 원본)

```python
from mail_attachment import BatchAttachmentHandler

handler = BatchAttachmentHandler(base_directory="downloads")

result = await handler.fetch_and_save(
    user_email="user@example.com",
    message_ids=["msg_id_1", "msg_id_2"],
    # 기본값: storage_type="local", convert_to_txt=False
)
```

### 4.2 TXT 변환 + 로컬 저장

```python
result = await handler.fetch_and_save(
    user_email="user@example.com",
    message_ids=["msg_id_1"],
    convert_to_txt=True,
    storage_type="local",
)
```

### 4.3 OneDrive 저장

```python
result = await handler.fetch_and_save(
    user_email="user@example.com",
    message_ids=["msg_id_1"],
    storage_type="onedrive",
    onedrive_folder="/Mail/Attachments",
)
```

### 4.4 TXT 변환 + OneDrive 저장

```python
result = await handler.fetch_and_save(
    user_email="user@example.com",
    message_ids=["msg_id_1"],
    storage_type="onedrive",
    onedrive_folder="/Mail/Attachments",
    convert_to_txt=True,
)
```

---

## 5. 지원 파일 형식

### 5.1 TXT 변환 지원

| 원본 형식 | 지원 | 사용 라이브러리 | 비고 |
|----------|:----:|----------------|------|
| PDF | ✅ | pdfplumber | 페이지별 텍스트 추출 |
| DOCX | ✅ | python-docx | 문단 + 테이블 추출 |
| DOC | ❌ | - | 구 형식 미지원 |
| HWP/HWPX | ✅ | pyhwpx, olefile | HTML 변환 후 텍스트 추출 |
| XLSX | ✅ | openpyxl | 시트별 탭 구분 텍스트 |
| XLS | ❌ | - | 구 형식 미지원 |
| PPTX | ✅ | python-pptx | 슬라이드별 텍스트 추출 |
| PPT | ❌ | - | 구 형식 미지원 |
| TXT/CSV/JSON/XML/MD | ✅ | 내장 | 인코딩 변환만 |

### 5.2 변환 실패 처리

```
변환 시도 → 실패 시 → 원본 파일로 저장 (fallback)
```

---

## 6. OneDrive 업로드

### 6.1 업로드 방식

| 파일 크기 | 업로드 방식 | 설명 |
|----------|------------|------|
| ≤ 4MB | 단순 PUT | 단일 요청으로 업로드 |
| > 4MB ~ 250GB | Upload Session | 청크 단위 업로드 (10MB/청크) |
| > 250GB | 미지원 | OneDrive 제한 |

### 6.2 Upload Session 흐름

```
1. POST /createUploadSession
   → uploadUrl 획득

2. PUT uploadUrl (청크 반복)
   Content-Range: bytes 0-10485759/52428800
   → 202 Accepted (진행 중)
   → 200/201 OK (완료)

3. 실패 시: DELETE uploadUrl (세션 취소)
```

### 6.3 코드 구현

```python
# mail_attachment_storage.py - OneDriveStorageBackend

SIMPLE_UPLOAD_MAX_SIZE = 4 * 1024 * 1024   # 4MB
CHUNK_SIZE = 10 * 1024 * 1024              # 10MB per chunk
MAX_FILE_SIZE = 250 * 1024 * 1024 * 1024   # 250GB

async def save_file(self, folder_path, filename, content, content_type):
    if len(content) <= SIMPLE_UPLOAD_MAX_SIZE:
        return await self._upload_simple(...)
    else:
        return await self._upload_large(...)  # Upload Session
```

---

## 7. 필요 라이브러리

### 7.1 requirements.txt 추가 필요

```txt
# 파일 변환 라이브러리
pdfplumber>=0.10.0        # PDF 텍스트 추출
python-docx>=0.8.11       # DOCX 텍스트 추출
olefile>=0.47             # HWP 처리 (Linux/Windows)
openpyxl>=3.1.0           # XLSX 텍스트 추출
python-pptx>=0.6.21       # PPTX 텍스트 추출
# pyhwpx>=0.1.0           # HWP 처리 (Windows 전용, 선택사항)
```

### 7.2 설치 명령

```bash
# Linux/macOS
pip install pdfplumber python-docx olefile openpyxl python-pptx

# Windows (HWP 완전 지원)
pip install pdfplumber python-docx pyhwpx olefile openpyxl python-pptx
```

---

## 8. 필요 권한 (Microsoft Graph)

### 8.1 OneDrive 업로드용 Scope

```
Files.ReadWrite
Files.ReadWrite.All  # 조직 전체 접근 시
```

### 8.2 Azure AD 앱 등록 확인

```
Azure Portal → App registrations → API permissions
→ Microsoft Graph → Files.ReadWrite 추가
```

---

## 9. 에러 처리

### 9.1 변환 실패

```python
try:
    text = converter.convert(content, filename)
except ImportError as e:
    # 라이브러리 미설치 → 원본 저장
except NotImplementedError as e:
    # 구 형식 미지원 → 원본 저장
except Exception as e:
    # 기타 오류 → 원본 저장
```

### 9.2 OneDrive 업로드 실패

```python
# 청크 업로드 실패 시
async with session.put(upload_url, ...) as response:
    if response.status not in [200, 201, 202]:
        await session.delete(upload_url)  # 세션 취소
        return None
```

---

## 10. 테스트 현황

### 10.1 테스트 상태

| 항목 | 상태 | 비고 |
|------|:----:|------|
| 단위 테스트 | ✅ | 19개 테스트 통과 |
| 통합 테스트 | ✅ | 워크플로우 검증 완료 |
| 수동 테스트 | ✅ | 부분 검증 |

### 10.2 테스트 파일 구조

```
mcp_outlook/tests/
├── __init__.py
├── conftest.py                      # 테스트 공통 Fixtures
├── test_mail_attachment.py          # MailFolderManager, MailMetadataManager 테스트
├── test_mail_attachment_converter.py # FileConverter, ConversionPipeline 테스트
├── test_mail_attachment_storage.py  # StorageBackend 테스트
├── test_integration.py              # 통합 테스트
└── run_tests.py                     # 독립 실행 테스트 스크립트
```

### 10.3 테스트 실행 방법

```bash
# 독립 실행 스크립트 (ROS 환경 충돌 방지)
python mcp_outlook/tests/run_tests.py

# pytest 사용 (환경에 따라 플러그인 충돌 가능)
python -m pytest mcp_outlook/tests/ -v
```

### 10.4 테스트 시나리오 검증 현황

| 시나리오 | 상태 | 테스트 파일 |
|---------|:----:|-----------|
| 1. 로컬 저장 + 원본 | ✅ | test_integration.py |
| 2. 로컬 저장 + TXT 변환 | ✅ | test_integration.py |
| 3. OneDrive 저장 + 원본 (4MB 이하) | ⚠️ | 모킹 테스트 |
| 4. OneDrive 저장 + 원본 (청크 업로드) | ⚠️ | 모킹 테스트 |
| 5. OneDrive 저장 + TXT 변환 | ⚠️ | 모킹 테스트 |
| 6. 변환 실패 시 fallback | ✅ | test_integration.py |
| 7. 중복 파일명 처리 | ✅ | test_integration.py, run_tests.py |
| 8. 메타데이터 중복 제거 | ✅ | test_integration.py, run_tests.py |

---

## 11. 구현 상태

| 기능 | 상태 | 파일 |
|------|:----:|------|
| 로컬 저장 | ✅ | mail_attachment_storage.py |
| OneDrive 저장 (4MB 이하) | ✅ | mail_attachment_storage.py |
| OneDrive 저장 (대용량) | ✅ | mail_attachment_storage.py |
| TXT 변환 | ✅ | mail_attachment_converter.py |
| 배치 처리 | ✅ | mail_attachment.py |
| 메타데이터 관리 | ✅ | mail_attachment.py |
| 단위 테스트 | ✅ | tests/test_*.py (19개 테스트) |
| 통합 테스트 | ✅ | tests/test_integration.py |

---

## 12. 변경 이력

| 날짜 | 버전 | 내용 |
|------|------|------|
| 2025-01-08 | 1.0 | 초안 작성 |
| 2025-01-08 | 1.1 | 구현 완료 (Storage/Converter) |
| 2025-01-09 | 1.2 | 문서 현행화, 파일명 수정, 대용량 업로드 추가 |
| 2026-01-09 | 1.3 | 테스트 코드 작성 완료 (19개 테스트), OneDrive 청크 업로드 로직 개선 |
