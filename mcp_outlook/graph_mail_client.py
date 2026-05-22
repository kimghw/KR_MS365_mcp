"""
Graph Mail Client - 통합 메일 처리 클라이언트
쿼리, 메일 처리, 첨부파일 관리를 통합하는 상위 클래스
"""

from typing import Dict, Any, List, Optional, Union, TYPE_CHECKING
from datetime import datetime, timedelta
from enum import Enum

if TYPE_CHECKING:
    from core.protocols import TokenProviderProtocol

from .graph_mail_query import GraphMailQuery
from .graph_mail_id_batch import GraphMailIdBatch
from .outlook_types import FilterParams, ExcludeParams, SelectParams


class QueryMethod(Enum):
    """쿼리 방법 열거형"""

    FILTER = "filter"  # 필터 기반 쿼리
    SEARCH = "search"  # 검색어 기반 쿼리
    URL = "url"  # 직접 URL 제공
    BATCH_ID = "batch_id"  # 메일 ID 배치 조회


class ProcessingMode(Enum):
    """처리 모드 열거형"""

    FETCH_ONLY = "fetch_only"  # 메일만 가져오기
    FETCH_AND_DOWNLOAD = "fetch_download"  # 메일 + 첨부파일 다운로드 (로컬)
    FETCH_AND_CONVERT = "fetch_convert"  # 메일 + 첨부파일 TXT 변환
    FULL_PROCESS = "full_process"  # 전체 처리 (저장, 변환 등)
    FETCH_TO_ONEDRIVE = "fetch_onedrive"  # 메일 + 첨부파일 OneDrive 저장
    FETCH_MEMORY_ONLY = "fetch_memory"  # 메일 + 첨부파일 메모리 반환 (저장 안함)


class GraphMailClient:
    """
    Graph API 메일 통합 클라이언트

    메일 쿼리부터 결과 처리, 첨부파일 관리까지 통합 관리
    """

    def __init__(
        self,
        token_provider: Optional["TokenProviderProtocol"] = None,
        mail_query: Optional[GraphMailQuery] = None,
        mail_batch: Optional[GraphMailIdBatch] = None,
    ):
        """
        초기화

        Args:
            token_provider: 토큰 제공자 (None이면 기본 AuthManager 사용)
            mail_query: 메일 조회 구현체 (None이면 기본값 생성)
            mail_batch: 배치 조회 구현체 (None이면 기본값 생성)
        """
        self._token_provider = token_provider
        self._provided_mail_query = mail_query
        self._provided_mail_batch = mail_batch
        self.mail_query: Optional[GraphMailQuery] = None
        self.mail_batch: Optional[GraphMailIdBatch] = None
        self._initialized = False

    async def initialize(self) -> bool:
        """
        컴포넌트 초기화

        Returns:
            초기화 성공 여부
        """
        if self._initialized:
            return True

        try:
            # GraphMailQuery 초기화 (제공된 것 사용 또는 새로 생성)
            if self._provided_mail_query is not None:
                self.mail_query = self._provided_mail_query
            else:
                self.mail_query = GraphMailQuery(token_provider=self._token_provider)

            if not await self.mail_query.initialize():
                print("Failed to initialize GraphMailQuery")
                return False

            # GraphMailIdBatch 초기화 (제공된 것 사용 또는 새로 생성)
            if self._provided_mail_batch is not None:
                self.mail_batch = self._provided_mail_batch
            else:
                self.mail_batch = GraphMailIdBatch(token_provider=self._token_provider)

            if not await self.mail_batch.initialize():
                print("Failed to initialize GraphMailIdBatch")
                return False

            self._initialized = True
            return True

        except Exception as e:
            print(f"Initialization error: {str(e)}")
            return False

    def _ensure_initialized(self):
        """초기화 확인"""
        if not self._initialized:
            raise Exception("GraphMailClient not initialized. Call initialize() first.")

    async def build_and_fetch(
        self,
        user_email: str,
        query_method: QueryMethod = QueryMethod.FILTER,
        # Filter 방식 파라미터
        filter_params: Optional[FilterParams] = None,
        exclude_params: Optional[ExcludeParams] = None,
        select_params: Optional[SelectParams] = None,
        client_filter: Optional[ExcludeParams] = None,
        # Search 방식 파라미터
        search_term: Optional[str] = None,
        # URL 방식 파라미터
        url: Optional[str] = None,
        # 공통 파라미터
        top: int = 50,
        order_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        쿼리를 빌드하고 메일을 가져오기

        Args:
            user_email: User email for authentication
            query_method: 쿼리 방법 (FILTER, SEARCH, URL)
            filter_params: 필터 파라미터 (FILTER 방식)
            exclude_params: 제외 파라미터 (FILTER 방식)
            select_params: 선택 필드 (FILTER, SEARCH 방식)
            client_filter: 클라이언트 필터 (모든 방식)
            search_term: 검색어 (SEARCH 방식)
            url: 직접 URL (URL 방식)
            top: 최대 결과 수
            order_by: 정렬 순서

        Returns:
            쿼리 결과 (에러 정보 포함)
        """
        self._ensure_initialized()

        try:
            # 쿼리 방법에 따라 실행
            if query_method == QueryMethod.FILTER:
                if not filter_params and not exclude_params:
                    return {"error": "No filter or exclude parameters provided", "status": "error", "value": []}

                result = await self.mail_query.query_filter(
                    user_email=user_email,
                    filter=filter_params or {},
                    exclude=exclude_params,
                    select=select_params,
                    client_filter=client_filter,
                    top=top,
                    orderby=order_by,
                )

            elif query_method == QueryMethod.SEARCH:
                if not search_term:
                    return {"error": "No search term provided", "status": "error", "value": []}

                result = await self.mail_query.query_search(
                    user_email=user_email,
                    search=search_term,
                    client_filter=client_filter,
                    select=select_params,
                    top=top,
                    orderby=order_by,
                )

            elif query_method == QueryMethod.URL:
                if not url:
                    return {"error": "No URL provided", "status": "error", "value": []}

                result = await self.mail_query.query_url(
                    user_email=user_email, url=url, top=top, client_filter=client_filter
                )

            else:
                return {"error": f"Unknown query method: {query_method}", "status": "error", "value": []}

            # 결과에 쿼리 방법 추가
            result["query_method"] = query_method.value
            return result

        except Exception as e:
            return {"error": str(e), "status": "error", "value": [], "query_method": query_method.value}

    async def fetch_and_process(
        self,
        user_email: str,
        # 쿼리 파라미터
        query_method: QueryMethod = QueryMethod.FILTER,
        filter_params: Optional[FilterParams] = None,
        exclude_params: Optional[ExcludeParams] = None,
        select_params: Optional[SelectParams] = None,
        client_filter: Optional[ExcludeParams] = None,
        search_term: Optional[str] = None,
        url: Optional[str] = None,
        top: int = 50,
        order_by: Optional[str] = None,
        # 처리 파라미터
        processing_mode: ProcessingMode = ProcessingMode.FETCH_ONLY,
        mail_storage: str = "memory",
        attachment_handling: str = "skip",
        output_format: str = "combined",
        save_directory: Optional[str] = None,
        # 추가 옵션
        return_on_error: bool = True,
    ) -> Dict[str, Any]:
        """
        메일을 가져오고 처리하는 통합 메서드

        Args:
            user_email: User email for authentication
            쿼리 관련 파라미터는 build_and_fetch와 동일
            processing_mode: 처리 모드
            mail_storage: 메일 저장 방식
            attachment_handling: 첨부파일 처리 방식
            output_format: 출력 형식
            save_directory: 저장 디렉토리
            return_on_error: 에러 시 즉시 반환 여부

        Returns:
            처리된 결과
        """
        self._ensure_initialized()

        # 1. 메일 가져오기
        print(f"\n[MAIL] Fetching emails using {query_method.value} method...")
        result = await self.build_and_fetch(
            user_email=user_email,
            query_method=query_method,
            filter_params=filter_params,
            exclude_params=exclude_params,
            select_params=select_params,
            client_filter=client_filter,
            search_term=search_term,
            url=url,
            top=top,
            order_by=order_by,
        )

        # 2. 에러 체크
        if result.get("has_errors"):
            print(f"[WARN] Query completed with errors: {len(result.get('errors', []))} errors")
            if return_on_error:
                return {
                    "status": "error",
                    "error": "Query failed with errors",
                    "errors": result.get("errors", []),
                    "partial_results": result.get("value", []),
                    "query_method": query_method.value,
                }

        if result.get("error"):
            print(f"[ERROR] Query failed: {result['error']}")
            return result

        # 3. 결과 확인
        emails = result.get("value", [])
        if not emails:
            print("[INFO] No emails found")
            return {
                "status": "success",
                "message": "No emails found",
                "value": [],
                "processed_count": 0,
                "query_method": query_method.value,
            }

        print(f"[DONE] Found {len(emails)} email(s)")

        # 4. 처리 모드에 따라 처리
        if processing_mode == ProcessingMode.FETCH_ONLY:
            # 메일만 가져오기
            return {
                "status": "success",
                "value": emails,
                "total": len(emails),
                "processing_mode": processing_mode.value,
                "query_method": query_method.value,
            }

        # 5. 추가 처리가 필요한 경우 - BatchAttachmentHandler 사용
        print(f"\n[PROCESS] Processing emails with mode: {processing_mode.value}")

        # 첨부파일 처리가 필요한 경우 BatchAttachmentHandler 사용
        processing_modes_with_attachments = [
            ProcessingMode.FETCH_AND_DOWNLOAD,
            ProcessingMode.FETCH_AND_CONVERT,
            ProcessingMode.FULL_PROCESS,
            ProcessingMode.FETCH_TO_ONEDRIVE,
            ProcessingMode.FETCH_MEMORY_ONLY,
        ]

        if processing_mode in processing_modes_with_attachments:
            from .mail_attachment import BatchAttachmentHandler

            message_ids = [email.get("id") for email in emails if email.get("id")]
            if message_ids:
                handler = BatchAttachmentHandler(base_directory=save_directory or "downloads")
                try:
                    # 처리 모드에 따른 옵션 설정
                    save_file = processing_mode != ProcessingMode.FETCH_MEMORY_ONLY
                    storage_type = "onedrive" if processing_mode == ProcessingMode.FETCH_TO_ONEDRIVE else "local"
                    convert_to_txt = processing_mode in [ProcessingMode.FETCH_AND_CONVERT, ProcessingMode.FULL_PROCESS]

                    attachment_result = await handler.fetch_and_save(
                        user_email=user_email,
                        message_ids=message_ids,
                        skip_duplicates=True,
                        save_file=save_file,
                        storage_type=storage_type,
                        convert_to_txt=convert_to_txt,
                        include_body=True,
                    )
                    print(f"[ATTACH] Processed {attachment_result.get('processed', 0)} emails with attachments")
                    return {
                        "status": "success",
                        "value": emails,
                        "total": len(emails),
                        "processing_mode": processing_mode.value,
                        "query_method": query_method.value,
                        "attachment_result": attachment_result,
                    }
                except Exception as e:
                    print(f"[WARN] Attachment processing failed: {e}")
                    return {
                        "status": "partial",
                        "value": emails,
                        "total": len(emails),
                        "processing_mode": processing_mode.value,
                        "query_method": query_method.value,
                        "attachment_error": str(e),
                    }

        # 그 외 모드는 쿼리 결과만 반환
        return {
            "status": "success",
            "value": emails,
            "total": len(emails),
            "processing_mode": processing_mode.value,
            "query_method": query_method.value,
        }

    async def batch_and_fetch(
        self, user_email: str, message_ids: List[str], select_params: Optional[SelectParams] = None
    ) -> Dict[str, Any]:
        """
        메일 ID 배치로 조회만 수행

        Args:
            user_email: 사용자 이메일
            message_ids: 메일 ID 리스트
            select_params: 선택할 필드

        Returns:
            조회 결과
        """
        self._ensure_initialized()

        if not message_ids:
            return {
                "status": "success",
                "value": [],
                "total": 0,
                "message": "No message IDs provided",
                "query_method": QueryMethod.BATCH_ID.value,
            }

        try:
            # 배치 조회 실행
            print(f"\n[MAIL] Fetching {len(message_ids)} emails using batch method...")
            result = await self.mail_batch.batch_fetch_by_ids(
                user_email=user_email, message_ids=message_ids, select_params=select_params
            )

            # 결과 변환 (기존 형식과 일관성 유지)
            if result.get("success"):
                return {
                    "status": "success",
                    "value": result.get("value", []),
                    "total": result.get("total", 0),
                    "requested": result.get("requested", 0),
                    "errors": result.get("errors"),
                    "query_method": QueryMethod.BATCH_ID.value,
                    "batches_processed": result.get("batches_processed", 0),
                }
            else:
                return {
                    "status": "error",
                    "error": result.get("error", "Batch fetch failed"),
                    "value": result.get("value", []),
                    "errors": result.get("errors"),
                    "query_method": QueryMethod.BATCH_ID.value,
                }

        except Exception as e:
            return {"status": "error", "error": str(e), "value": [], "query_method": QueryMethod.BATCH_ID.value}

    async def fetch_attachments_metadata(
        self,
        user_email: str,
        message_ids: List[str],
        select_params: Optional[SelectParams] = None,
    ) -> Dict[str, Any]:
        """
        메일과 첨부파일의 메타데이터만 조회 (다운로드 없음)

        Args:
            user_email: 사용자 이메일
            message_ids: 메일 ID 리스트
            select_params: 선택할 필드

        Returns:
            메일 및 첨부파일 메타데이터
        """
        self._ensure_initialized()

        if not message_ids:
            return {
                "status": "success",
                "value": [],
                "total": 0,
                "message": "No message IDs provided",
            }

        try:
            from .mail_attachment import BatchAttachmentHandler

            print(f"\n[META] Fetching metadata for {len(message_ids)} emails...")
            handler = BatchAttachmentHandler()

            result = await handler.fetch_metadata_only(
                user_email=user_email,
                message_ids=message_ids,
                select_params=select_params,
            )

            return {
                "status": "success",
                "value": result.get("messages", []),
                "total": result.get("total_processed", 0),
                "attachments_count": result.get("attachments_count", 0),
                "errors": result.get("errors"),
            }

        except Exception as e:
            return {"status": "error", "error": str(e), "value": []}

    async def download_attachments(
        self,
        user_email: str,
        message_attachment_ids: Union[List[str], List[Dict[str, str]]],
        save_directory: str = "downloads",
        flat_folder: bool = False,
        skip_duplicates: bool = True,
        select_params: Optional[SelectParams] = None,
        # 새 옵션 (mail_attachment.py 반영)
        save_file: bool = True,
        storage_type: str = "local",
        convert_to_txt: bool = False,
        include_body: bool = True,
        onedrive_folder: str = "/Attachments",
    ) -> Dict[str, Any]:
        """
        첨부파일 다운로드 통합 함수

        Args:
            user_email: 사용자 이메일
            message_attachment_ids:
                - 메일 ID 리스트: ["msg_id1", "msg_id2"] -> 해당 메일의 모든 첨부파일 다운로드
                - 첨부파일 ID 쌍 리스트: [{"message_id": "...", "attachment_id": "..."}, ...] -> 특정 첨부파일만 다운로드
            save_directory: 저장 디렉토리
            flat_folder: True면 하위폴더 없이 save_directory에 바로 저장
            skip_duplicates: 중복 건너뛰기 (메일 ID 리스트일 때만 적용)
            select_params: 선택할 필드 (메일 ID 리스트일 때만 적용)
            save_file: 파일 저장 여부 (False면 메모리 반환만)
            storage_type: 저장 위치 ("local" 또는 "onedrive")
            convert_to_txt: TXT 변환 여부
            include_body: 본문 포함 여부
            onedrive_folder: OneDrive 저장 폴더 경로

        Returns:
            다운로드 결과
        """
        self._ensure_initialized()

        if not message_attachment_ids:
            return {
                "status": "success",
                "message": "No message_attachment_ids provided",
                "downloaded": 0,
            }

        try:
            from .mail_attachment import BatchAttachmentHandler

            handler = BatchAttachmentHandler(base_directory=save_directory)

            # 입력 타입 판별
            if all(isinstance(item, str) for item in message_attachment_ids):
                # 메일 ID 리스트 -> 모든 첨부파일 다운로드
                print(f"\n[MAIL] Downloading all attachments from {len(message_attachment_ids)} emails...")

                result = await handler.fetch_and_save(
                    user_email=user_email,
                    message_ids=message_attachment_ids,
                    select_params=select_params,
                    skip_duplicates=skip_duplicates,
                    flat_folder=flat_folder,
                    save_file=save_file,
                    storage_type=storage_type,
                    convert_to_txt=convert_to_txt,
                    include_body=include_body,
                    onedrive_folder=onedrive_folder,
                )

                return {
                    "status": "success",
                    "mode": "all_attachments",
                    "total_mails": result.get("total_requested", 0),
                    "processed": result.get("processed", 0),
                    "saved_attachments": result.get("saved_attachments", []),
                    "saved_folders": result.get("saved_folders", []),
                    "converted_files": result.get("converted_files", []),
                    "body_contents": result.get("body_contents", []),
                    "attachment_contents": result.get("attachment_contents", []),
                    "skipped_duplicates": result.get("skipped_duplicates", 0),
                    "errors": result.get("errors", []),
                    "storage_type": storage_type,
                    "save_file": save_file,
                    "convert_to_txt": convert_to_txt,
                }

            elif all(isinstance(item, dict) and "message_id" in item and "attachment_id" in item for item in message_attachment_ids):
                # 메일/첨부파일 ID 쌍 -> 특정 첨부파일만 다운로드
                print(f"\n[ATTACH] Downloading {len(message_attachment_ids)} specific attachments...")

                result = await handler.fetch_specific_attachments(
                    user_email=user_email,
                    attachments_info=message_attachment_ids,
                    save_directory=save_directory,
                    flat_folder=flat_folder,
                    storage_type=storage_type,
                    onedrive_folder=onedrive_folder,
                )

                return {
                    "status": "success",
                    "mode": "specific_attachments",
                    "total_requested": result.get("total_requested", 0),
                    "downloaded": result.get("downloaded", 0),
                    "failed": result.get("failed", 0),
                    "results": result.get("results", []),
                    "errors": result.get("errors", []),
                }

            else:
                return {
                    "status": "error",
                    "error": "Invalid message_attachment_ids format. Use message IDs list or attachment info list",
                }

        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def batch_and_process(
        self,
        user_email: str,
        message_ids: List[str],
        select_params: Optional[SelectParams] = None,
        # 처리 파라미터
        processing_mode: ProcessingMode = ProcessingMode.FETCH_ONLY,
        mail_storage: str = "memory",
        attachment_handling: str = "skip",
        output_format: str = "combined",
        save_directory: Optional[str] = None,
        return_on_error: bool = True,
    ) -> Dict[str, Any]:
        """
        메일 ID 배치로 조회 + 처리

        Args:
            user_email: 사용자 이메일
            message_ids: 메일 ID 리스트
            select_params: 선택할 필드
            processing_mode: 처리 모드
            mail_storage: 메일 저장 방식
            attachment_handling: 첨부파일 처리 방식
            output_format: 출력 형식
            save_directory: 저장 디렉토리
            return_on_error: 에러 시 즉시 반환 여부

        Returns:
            처리된 결과
        """
        self._ensure_initialized()

        # 1. 배치로 메일 가져오기
        print(f"\n[MAIL] Fetching {len(message_ids)} emails using batch method...")
        result = await self.batch_and_fetch(user_email=user_email, message_ids=message_ids, select_params=select_params)

        # 2. 에러 체크
        if result.get("status") == "error":
            print(f"[ERROR] Batch fetch failed: {result.get('error')}")
            if return_on_error:
                return result

        # 3. 결과 확인
        emails = result.get("value", [])
        if not emails:
            print("[INFO]  No emails found")
            return {
                "status": "success",
                "message": "No emails found",
                "value": [],
                "processed_count": 0,
                "query_method": QueryMethod.BATCH_ID.value,
            }

        print(f"[DONE] Found {len(emails)} email(s)")

        # 4. 처리 모드에 따라 처리
        if processing_mode == ProcessingMode.FETCH_ONLY:
            # 메일만 가져오기
            return {
                "status": "success",
                "value": emails,
                "total": len(emails),
                "processed_count": len(emails),
                "query_method": QueryMethod.BATCH_ID.value,
                "processing_mode": processing_mode.value,
            }

        # 5. 처리 모드별 처리 (미구현)
        # TODO: ProcessingOptions, MailProcessorHandler 구현 후 활성화
        raise NotImplementedError(
            f"Processing mode '{processing_mode.value}' is not yet implemented. "
            f"Only ProcessingMode.FETCH_ONLY is currently supported."
        )

    async def delete_messages(
        self,
        user_email: str,
        message_ids: List[str],
    ) -> Dict[str, Any]:
        """
        메일을 휴지통(Deleted Items)으로 이동

        Args:
            user_email: 사용자 이메일
            message_ids: 삭제할 메일 ID 리스트

        Returns:
            삭제 결과
        """
        self._ensure_initialized()

        if not message_ids:
            return {
                "status": "success",
                "deleted": 0,
                "total": 0,
                "message": "No message IDs provided",
            }

        try:
            print(f"\n[DELETE] Deleting {len(message_ids)} email(s)...")
            result = await self.mail_batch.batch_delete_by_ids(
                user_email=user_email,
                message_ids=message_ids,
            )

            if result.get("success"):
                return {
                    "status": "success",
                    "deleted": result.get("deleted", 0),
                    "failed": result.get("failed", 0),
                    "total": result.get("total", 0),
                    "deleted_ids": result.get("deleted_ids", []),
                    "failed_items": result.get("failed_items"),
                    "batches_processed": result.get("batches_processed", 0),
                }
            else:
                return {
                    "status": "error",
                    "error": result.get("error", "Delete failed"),
                    "deleted": result.get("deleted", 0),
                    "failed": result.get("failed", 0),
                    "total": result.get("total", 0),
                    "failed_items": result.get("failed_items"),
                }

        except Exception as e:
            return {"status": "error", "error": str(e), "deleted": 0}

    async def report_not_junk_messages(
        self,
        user_email: str,
        message_ids: List[str],
    ) -> Dict[str, Any]:
        """
        메일을 '정크 아님'으로 신고 (Safe Senders 등록)

        Beta API: POST /users/{email}/messages/{id}/reportMessage
        body: {"reportAction": "notJunk"}

        Args:
            user_email: 사용자 이메일
            message_ids: 신고할 메일 ID 리스트

        Returns:
            신고 결과
        """
        self._ensure_initialized()

        if not message_ids:
            return {
                "status": "success",
                "reported": 0,
                "total": 0,
                "message": "No message IDs provided",
            }

        try:
            print(f"\n[REPORT] Reporting {len(message_ids)} email(s) as notJunk...")
            result = await self.mail_batch.batch_report_not_junk_by_ids(
                user_email=user_email,
                message_ids=message_ids,
            )

            if result.get("success"):
                return {
                    "status": "success",
                    "reported": result.get("reported", 0),
                    "failed": result.get("failed", 0),
                    "total": result.get("total", 0),
                    "reported_ids": result.get("reported_ids", []),
                    "failed_items": result.get("failed_items"),
                    "batches_processed": result.get("batches_processed", 0),
                }
            else:
                return {
                    "status": "error",
                    "error": result.get("error", "Report notJunk failed"),
                    "reported": result.get("reported", 0),
                    "failed": result.get("failed", 0),
                    "total": result.get("total", 0),
                    "failed_items": result.get("failed_items"),
                }

        except Exception as e:
            return {"status": "error", "error": str(e), "reported": 0}

    async def move_messages(
        self,
        user_email: str,
        message_ids: List[str],
        destination_id: str = "inbox",
    ) -> Dict[str, Any]:
        """
        메일을 지정 폴더로 이동

        Args:
            user_email: 사용자 이메일
            message_ids: 이동할 메일 ID 리스트
            destination_id: 이동할 폴더 (inbox, junkemail, deleteditems, drafts, sentitems 등)

        Returns:
            이동 결과
        """
        self._ensure_initialized()

        if not message_ids:
            return {
                "status": "success",
                "moved": 0,
                "total": 0,
                "message": "No message IDs provided",
            }

        try:
            print(f"\n[MOVE] Moving {len(message_ids)} email(s) to '{destination_id}'...")
            result = await self.mail_batch.batch_move_by_ids(
                user_email=user_email,
                message_ids=message_ids,
                destination_id=destination_id,
            )

            if result.get("success"):
                return {
                    "status": "success",
                    "moved": result.get("moved", 0),
                    "failed": result.get("failed", 0),
                    "total": result.get("total", 0),
                    "moved_ids": result.get("moved_ids", []),
                    "failed_items": result.get("failed_items"),
                    "batches_processed": result.get("batches_processed", 0),
                    "destination": destination_id,
                }
            else:
                return {
                    "status": "error",
                    "error": result.get("error", "Move failed"),
                    "moved": result.get("moved", 0),
                    "failed": result.get("failed", 0),
                    "total": result.get("total", 0),
                    "failed_items": result.get("failed_items"),
                }

        except Exception as e:
            return {"status": "error", "error": str(e), "moved": 0}

    def format_results(self, results: Dict[str, Any], verbose: bool = False) -> str:
        """
        결과 포맷팅

        Args:
            results: 처리 결과
            verbose: 상세 출력 여부

        Returns:
            포맷된 문자열
        """
        output = []
        output.append("\n" + "=" * 80)

        # 상태 확인
        status = results.get("status", "unknown")
        if status == "error":
            output.append(f"[ERROR] Error: {results.get('error', 'Unknown error')}")
            if results.get("errors"):
                output.append(f"   Details: {len(results['errors'])} errors occurred")
            return "\n".join(output)

        # 메일 정보
        emails = results.get("value", [])
        output.append(f"[MAIL] Emails: {len(emails)}")

        # 처리 정보
        if results.get("processing_mode"):
            output.append(f"[PROCESS] Processing Mode: {results['processing_mode']}")

        # 첨부파일 정보
        if results.get("downloaded_count"):
            output.append(f"[ATTACH] Downloaded Attachments: {results['downloaded_count']}")
        if results.get("converted_count"):
            output.append(f"[CONVERT] Converted Files: {results['converted_count']}")

        # 필터링 정보
        if results.get("client_filtered"):
            output.append(f"[FILTER] Client Filtered: {results.get('filtered_count', 0)} items")

        # 메일 목록 (verbose 모드)
        if verbose and emails:
            output.append("\n" + "-" * 40)
            for idx, email in enumerate(emails[:10], 1):  # 최대 10개만
                subject = email.get("subject", "No Subject")
                from_addr = email.get("from", {}).get("emailAddress", {}).get("address", "Unknown")
                output.append(f"{idx}. {subject[:50]}")
                output.append(f"   From: {from_addr}")

        output.append("=" * 80)
        return "\n".join(output)

    async def close(self):
        """리소스 정리"""
        if self.mail_query:
            await self.mail_query.close()
        if self.mail_batch:
            await self.mail_batch.close()
