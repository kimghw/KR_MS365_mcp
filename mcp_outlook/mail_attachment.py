"""
Graph Attachment Handler - 메일 첨부파일 Processor
$batch + $expand=attachments로 조회된 메일의 첨부파일을 처리

역할:
    - 첨부파일 다운로드 및 저장
    - 폴더 구조 관리
    - 메타데이터 관리 및 중복 제거

Classes:
    - MailMetadataManager: 메타정보 저장 및 중복 제거 (mode 0 — mail_metadata.json)
    - BatchAttachmentHandler: 배치 첨부파일 처리
    - SingleAttachmentHandler: 개별 첨부파일 처리 (mail_attachment_single.py, 여기서 재수출)

Note:
    MailFolderManager는 mail_attachment_storage.py로 이동됨
    (LocalStorageBackend의 alias로 하위 호환성 유지)

멀티유저 (spec/spec_멀티유저.md ②-2.5·②-7.3, WP4):
    - 토큰 공급자는 **주입받아 빌려 쓴다.** 핸들러는 요청 범위 객체라 `close()` 가 공급자를
      닫지 않는다(공유·사용자 고정 공급자의 수명은 서비스 풀/서비스가 관리).
    - `paths`(UserPaths)가 주어지면 저장 위치는 사용자 `files/downloads/outlook/`(또는
      `resolve_safe_path` 를 통과한 호출자 지정 디렉터리), 메타데이터는 사용자 `db/outlook.db`
      (`storage_schema.OutlookMetadataStore`), 응답 경로는 `files/` 기준 상대경로다.
    - 로그에 이메일·제목·파일 경로·Graph 오류 본문을 싣지 않는다.

한계 (astra 3차 N08 gap 3): `$batch` 응답은 `Content-Length` 가 있을 때만 본문을 읽기 전에
크기를 거부한다(`response_too_large`). Graph 가 chunked 로 보내 헤더가 없으면 `.json()` 이
본문 전체(base64)를 메모리에 올린 뒤에야 첨부 1건·요청 decode 예산이 적용된다 — 상한은
Graph 의 배치당 20건 × 첨부 크기다. 스트리밍 파서 도입은 후속이다.
"""

import os
import json
import base64
import logging
import aiohttp
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path

import sys
from typing import TYPE_CHECKING

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_common.graph_paths import graph_drive_path
from mcp_common.secure_files import safe_filename
from mcp_common.errors import ToolExecutionError
from mcp_common.security_contracts import SecurityError, StartupConfigError
from mcp_common.security_policy import assert_legacy_store_not_frozen, multi_user_enabled

if TYPE_CHECKING:
    from core.protocols import TokenProviderProtocol
    from mcp_common.user_paths import UserPaths
from .graph_mail_url import ExpandBuilder, GraphMailUrlBuilder
from .mail_attachment_storage import StorageBackend, LocalStorageBackend, OneDriveStorageBackend, get_storage_backend, MailFolderManager
from .mail_attachment_converter import ConversionPipeline, get_conversion_pipeline
from .mail_attachment_processor import (
    process_body_content,
    process_attachments,
    process_attachment_with_conversion,
    process_attachment_original,
)
from .mail_attachment_single import SingleAttachmentHandler
from .mail_attachment_user_storage import UserLocalStorageBackend
from .outlook_file_policy import legacy_dir, resolve_save_dir
from . import outlook_security as limits
from .conversion_workers import LEGACY_KEY, WorkerGroup
from .outlook_security import (
    BEARER_KW,
    GRAPH_BASE,
    AttachmentLimitExceeded,
    ByteBudget,
    GraphRequestError,
    acquire_token,
    check_list_size,
    graph_error_entry,
    legacy_token_provider,
    public_error,
    request_headers,
    response_too_large,
    seg,
    user_seg,
)
from .storage_schema import OutlookMetadataStore, ensure_outlook_db

logger = logging.getLogger(__name__)


class MailMetadataManager:
    """
    메일 메타데이터 관리 (mode 0 — JSON 파일)
    message_id 기반 중복 제거 및 처리 이력 관리

    mode 1 은 사용자 DB 의 `storage_schema.OutlookMetadataStore` 를 쓴다(같은 인터페이스).
    """

    def __init__(self, metadata_file: str = "mail_metadata.json"):
        """
        초기화

        Args:
            metadata_file: 메타데이터 파일 경로
        """
        self.metadata_file = Path(metadata_file)
        self._metadata: Dict[str, Any] = {}
        # 멀티유저 이전 중에는 legacy 공용 메타데이터를 열지 않는다 (astra 재검토 R10)
        assert_legacy_store_not_frozen(self.metadata_file)
        self._load_metadata()

    def _assert_writable(self) -> None:
        """쓰기 **직전** 재검사 (astra 3차 N06) — 열린 뒤 이전이 시작됐으면 더 쓰지 않는다.

        `exists()` 한 번이라 싸다. 잠금은 고정 오류 코드로 올려 요청 전체가 실패한다
        (부분 결과로 감추지 않는다).
        """
        try:
            assert_legacy_store_not_frozen(self.metadata_file)
        except StartupConfigError as exc:
            raise ToolExecutionError(
                {"status": "error", "error": "legacy_store_frozen", "message": str(exc)}
            ) from None

    def _load_metadata(self):
        """메타데이터 파일 로드"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    self._metadata = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("mail metadata load failed: %s", type(e).__name__)
                self._metadata = {}
        else:
            self._metadata = {"processed_messages": {}, "last_updated": None}

    def _save_metadata(self):
        """메타데이터 파일 저장 — 매 쓰기 직전 이전 잠금을 다시 확인한다 (N06)"""
        self._assert_writable()
        try:
            self._metadata["last_updated"] = datetime.now().isoformat()
            with open(self.metadata_file, "w", encoding="utf-8") as f:
                json.dump(self._metadata, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.warning("mail metadata save failed: %s", type(e).__name__)

    def is_duplicate(self, message_id: str) -> bool:
        """
        중복 메일 여부 확인

        Args:
            message_id: 메일 ID

        Returns:
            True if 이미 처리된 메일
        """
        return message_id in self._metadata.get("processed_messages", {})

    def add_processed_mail(
        self,
        message_id: str,
        mail_data: Dict[str, Any],
        folder_path: str,
        saved_files: List[str],
    ):
        """
        처리된 메일 정보 추가

        Args:
            message_id: 메일 ID
            mail_data: 메일 데이터
            folder_path: 저장된 폴더 경로
            saved_files: 저장된 파일 목록
        """
        if "processed_messages" not in self._metadata:
            self._metadata["processed_messages"] = {}

        self._metadata["processed_messages"][message_id] = {
            "subject": mail_data.get("subject", ""),
            "from": mail_data.get("from", {}).get("emailAddress", {}).get("address", ""),
            "received_datetime": mail_data.get("receivedDateTime", ""),
            "folder_path": folder_path,
            "saved_files": saved_files,
            "processed_at": datetime.now().isoformat(),
            "attachment_count": len(mail_data.get("attachments", [])),
        }

        self._save_metadata()

    def get_processed_count(self) -> int:
        """처리된 메일 수 반환"""
        return len(self._metadata.get("processed_messages", {}))

    def get_processed_message_ids(self) -> List[str]:
        """처리된 메일 ID 목록 반환"""
        return list(self._metadata.get("processed_messages", {}).keys())

    def filter_new_messages(self, message_ids: List[str]) -> List[str]:
        """
        새로운 메일 ID만 필터링

        Args:
            message_ids: 전체 메일 ID 목록

        Returns:
            아직 처리되지 않은 메일 ID 목록
        """
        return [mid for mid in message_ids if not self.is_duplicate(mid)]


class BatchAttachmentHandler:
    """
    배치 첨부파일 핸들러
    $batch + $expand=attachments로 메일과 첨부파일을 한번에 조회 및 저장
    """

    def __init__(
        self,
        base_directory: str = "downloads",
        metadata_file: str = "mail_metadata.json",
        token_provider: Optional["TokenProviderProtocol"] = None,
        paths: Optional["UserPaths"] = None,
        workers: Optional[WorkerGroup] = None,
    ):
        """
        초기화

        Args:
            base_directory: 첨부파일 저장 기본 디렉토리
            metadata_file: 메타데이터 파일명 (base_directory 안에 저장됨, mode 0 전용)
            token_provider: 토큰 제공자 (None이면 mode 0 공유 AuthManager — mode 1 은 주입 필수)
            paths: mode 1 사용자 경로. 주면 저장·메타데이터가 그 사용자 영역으로 간다.
            workers: converter 스레드를 등록할 서비스 범위 `WorkerGroup` (P01). None 이면 이 핸들러만의 그룹.
        """
        if token_provider is None:
            token_provider = legacy_token_provider()
        self.token_provider = token_provider
        self.paths = paths
        self.workers = workers if workers is not None else WorkerGroup()
        self.owner_key = paths.user_key if paths is not None else LEGACY_KEY
        if paths is not None:
            # mode 1: 사용자 files/ 안 + 사용자 db/outlook.db
            self.folder_manager = UserLocalStorageBackend(paths, resolve_save_dir(paths, base_directory))
            ensure_outlook_db(paths)
            self.metadata_manager = OutlookMetadataStore.for_paths(paths)
        elif multi_user_enabled():
            raise RuntimeError("멀티유저 모드에서는 paths(UserPaths)를 주입해야 합니다")
        else:
            self.folder_manager = MailFolderManager(base_directory)
            # metadata_file을 base_directory 안에 저장
            # 상대 경로는 프로젝트 루트 기준으로 변환
            metadata_path = str(legacy_dir(base_directory) / metadata_file)
            self.metadata_manager = MailMetadataManager(metadata_path)
        self.expand_builder = ExpandBuilder()

        self.batch_url = f"{GRAPH_BASE}/$batch"
        self.max_batch_size = 20

    async def _get_access_token(self, user_email: str) -> Optional[str]:
        """
        액세스 토큰 획득 (요청 1건용 — 보관하지 않는다)

        Args:
            user_email: 사용자 이메일

        Returns:
            액세스 토큰 또는 None (mode 1 은 실패 시 SecurityError)
        """
        return await acquire_token(self.token_provider, user_email)

    async def _request_headers(self, user_email: str) -> Dict[str, str]:
        """요청 1건 직전에 토큰을 새로 얻는다 (N01)."""
        return await request_headers(self.token_provider, user_email)

    def _build_batch_requests(
        self,
        user_email: str,
        message_ids: List[str],
        select_params: Optional[Any] = None,  # SelectParams 또는 List[str]
    ) -> List[Dict[str, Any]]:
        """
        $batch 요청 본문 생성

        Args:
            user_email: 사용자 이메일
            message_ids: 메일 ID 목록
            select_params: SelectParams 객체 또는 필드 목록

        Returns:
            $batch requests 배열
        """
        from .outlook_types import SelectParams, build_select_query

        # ExpandBuilder 설정
        self.expand_builder.reset()

        # select_params 처리
        select_fields = None
        if select_params:
            if isinstance(select_params, SelectParams):
                # SelectParams 객체인 경우 build_select_query 사용
                select_query = build_select_query(select_params)
                select_fields = select_query.split(",") if select_query else None
            elif isinstance(select_params, list):
                # 리스트인 경우 그대로 사용 (하위 호환성)
                select_fields = select_params

        # 기본 필드 (필수) + 사용자 정의 필드
        # - id: 메일 식별, 중복 체크
        # - subject: 폴더명 생성
        # - from: 폴더명 생성 (보낸사람)
        # - receivedDateTime: 폴더명 생성 (날짜)
        # - body: 메일 본문 저장
        # - hasAttachments: 첨부파일 유무 확인
        default_fields = ["id", "subject", "from", "receivedDateTime", "body", "hasAttachments"]
        if select_fields:
            all_fields = list(set(default_fields + select_fields))
        else:
            all_fields = default_fields

        self.expand_builder.select(all_fields).expand_attachments()

        requests = []
        for i, message_id in enumerate(message_ids):
            url = self.expand_builder.build_url(f"/users/{user_seg(user_email)}/messages/{seg(message_id)}")
            requests.append({"id": str(i + 1), "method": "GET", "url": url})

        return requests

    async def fetch_metadata_only(
        self,
        user_email: str,
        message_ids: List[str],
        select_params: Optional[Any] = None,  # SelectParams 또는 List[str]
    ) -> Dict[str, Any]:
        """
        메일과 첨부파일의 메타데이터만 조회 (다운로드 없음)

        Args:
            user_email: 사용자 이메일
            message_ids: 메일 ID 목록
            select_params: SelectParams 객체 또는 필드 목록

        Returns:
            메타데이터 조회 결과
        """
        result = {
            "success": False,
            "messages": [],
            "total_processed": 0,
            "attachments_count": 0,
            "errors": [],
        }

        if not message_ids:
            result["success"] = True
            result["message"] = "No messages to process"
            return result
        check_list_size(message_ids, "message_ids")

        # 토큰 획득
        access_token = await self._get_access_token(user_email)
        if not access_token:
            result["errors"].append("Failed to acquire access token")
            return result

        # 배치 분할
        batches = [
            message_ids[i : i + self.max_batch_size]
            for i in range(0, len(message_ids), self.max_batch_size)
        ]

        logger.info("[META] fetching metadata for %d emails (%d batches)", len(message_ids), len(batches))

        async with aiohttp.ClientSession() as session:
            for batch_num, batch_ids in enumerate(batches, 1):
                # 배치 요청 생성
                requests = self._build_batch_requests(user_email, batch_ids, select_params)
                batch_body = {"requests": requests}

                try:
                    headers = await self._request_headers(user_email)  # 배치마다 재획득 (N01)
                    async with session.post(
                        self.batch_url, headers=headers, json=batch_body, **BEARER_KW
                    ) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            result["errors"].append(graph_error_entry(response.status, error_text, batch=batch_num))
                            continue

                        if response_too_large(response, limits.MAX_REQUEST_ATTACHMENT_BYTES * 4 // 3 + 1024 * 1024):
                            result["errors"].append({"batch": batch_num, "error": "response_too_large",
                                                     "limit_bytes": limits.MAX_REQUEST_ATTACHMENT_BYTES})
                            continue

                        batch_response = await response.json()

                        # 각 응답 처리 (메타데이터만)
                        for resp in batch_response.get("responses", []):
                            req_id = int(resp.get("id", 0)) - 1
                            if req_id < 0 or req_id >= len(batch_ids):
                                continue

                            message_id = batch_ids[req_id]

                            if resp.get("status") != 200:
                                # R06: 원문 message 대신 상태 코드 + 검증된 error.code 만
                                result["errors"].append(
                                    graph_error_entry(resp.get("status"), resp.get("body"), message_id=message_id)
                                )
                                continue

                            mail_data = resp.get("body", {})

                            # 메타데이터 추출
                            metadata = {
                                "id": mail_data.get("id"),
                                "subject": mail_data.get("subject"),
                                "from": mail_data.get("from", {}).get("emailAddress", {}),
                                "toRecipients": mail_data.get("toRecipients", []),
                                "receivedDateTime": mail_data.get("receivedDateTime"),
                                "hasAttachments": mail_data.get("hasAttachments", False),
                                "importance": mail_data.get("importance"),
                                "isRead": mail_data.get("isRead"),
                                "bodyPreview": mail_data.get("bodyPreview", ""),
                                "body": mail_data.get("body", {}),  # 전체 본문 포함
                                "attachments": []
                            }

                            # 첨부파일 메타데이터 추출
                            attachments = mail_data.get("attachments", [])
                            for att in attachments:
                                att_meta = {
                                    "id": att.get("id"),
                                    "name": att.get("name"),
                                    "contentType": att.get("contentType"),
                                    "size": att.get("size", 0),
                                    "isInline": att.get("isInline", False),
                                    "@odata.type": att.get("@odata.type"),
                                }
                                metadata["attachments"].append(att_meta)
                                result["attachments_count"] += 1

                            result["messages"].append(metadata)
                            result["total_processed"] += 1

                except ToolExecutionError:  # SecurityError·invalid_argument·quota_exceeded 전부 그대로 올린다
                    raise
                except Exception as e:
                    result["errors"].append(f"Batch {batch_num} exception: {public_error(e)}")

        result["success"] = result["total_processed"] > 0
        result["message"] = f"Fetched metadata for {result['total_processed']} emails"

        return result

    async def fetch_and_save(
        self,
        user_email: str,
        message_ids: List[str],
        select_params: Optional[Any] = None,  # SelectParams 또는 List[str]
        skip_duplicates: bool = True,
        flat_folder: bool = False,
        save_file: bool = True,
        storage_type: str = "local",
        convert_to_txt: bool = False,
        include_body: bool = True,
        onedrive_folder: str = "/Attachments",
    ) -> Dict[str, Any]:
        """
        메일과 첨부파일을 조회하여 저장

        Args:
            user_email: 사용자 이메일
            message_ids: 메일 ID 목록
            select_params: SelectParams 객체 또는 필드 목록
            skip_duplicates: 중복 메일 건너뛰기
            save_file: 파일 저장 여부 (False면 메모리 반환만)
            storage_type: 저장 위치 ("local" 또는 "onedrive")
            convert_to_txt: 첨부파일을 TXT로 변환 여부
            include_body: 본문 포함 여부 (False면 첨부파일만)
            onedrive_folder: OneDrive 저장 폴더 경로

        Returns:
            처리 결과
        """
        result = {
            "success": False,
            "total_requested": len(message_ids),
            "processed": 0,
            "skipped_duplicates": 0,
            "saved_mails": [],
            "saved_attachments": [],
            "saved_folders": [],
            "converted_files": [],
            "body_contents": [],          # save_file=False일 때 본문 내용
            "attachment_contents": [],    # save_file=False일 때 첨부파일 내용
            "errors": [],
            "storage_type": storage_type,
            "save_file": save_file,
            "convert_to_txt": convert_to_txt,
            "include_body": include_body,
        }

        if not message_ids:
            result["success"] = True
            result["message"] = "처리할 메일 없음"
            return result
        check_list_size(message_ids, "message_ids")
        if save_file and storage_type == "onedrive":
            graph_drive_path(onedrive_folder)  # R07: 잘못된 OneDrive 경로는 토큰 획득 전에 거부

        # 중복 필터링
        if skip_duplicates:
            new_message_ids = self.metadata_manager.filter_new_messages(message_ids)
            result["skipped_duplicates"] = len(message_ids) - len(new_message_ids)
            message_ids = new_message_ids

            if not message_ids:
                result["success"] = True
                result["message"] = "모든 메일이 이미 처리됨"
                return result

        # 토큰 획득
        access_token = await self._get_access_token(user_email)
        if not access_token:
            result["errors"].append("토큰 획득 실패")
            return result

        # Storage Backend 생성 (저장 모드일 때만)
        storage = None
        if save_file:
            if storage_type != "onedrive" and self.paths is not None:
                # mode 1 로컬: 이미 경계를 확인한 사용자 저장소를 그대로 쓴다
                storage = self.folder_manager
            else:
                storage = get_storage_backend(
                    storage_type=storage_type,
                    auth_manager=self.token_provider,
                    user_email=user_email,
                    base_directory=str(self.folder_manager.base_directory),
                    base_folder=onedrive_folder,
                )

        # Converter 생성 (필요시)
        converter = get_conversion_pipeline() if convert_to_txt else None
        # 요청 1건의 첨부 decode 예산 (N08)
        budget = ByteBudget(limits.MAX_REQUEST_ATTACHMENT_BYTES)

        # 배치 분할
        batches = [
            message_ids[i : i + self.max_batch_size]
            for i in range(0, len(message_ids), self.max_batch_size)
        ]

        storage_label = "memory" if not save_file else ("onedrive" if storage_type == "onedrive" else "local")
        logger.info(
            "[ATTACH] processing %d emails (%d batches) [%s%s%s]",
            len(message_ids), len(batches), storage_label,
            " +txt" if convert_to_txt else "", " +body" if include_body else "",
        )

        async with aiohttp.ClientSession() as session:
            for batch_num, batch_ids in enumerate(batches, 1):
                # 배치 요청 생성
                requests = self._build_batch_requests(user_email, batch_ids, select_params)
                batch_body = {"requests": requests}

                try:
                    headers = await self._request_headers(user_email)  # 배치마다 재획득 (N01)
                    async with session.post(
                        self.batch_url, headers=headers, json=batch_body, **BEARER_KW
                    ) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            result["errors"].append(graph_error_entry(response.status, error_text, batch=batch_num))
                            continue

                        if response_too_large(response, limits.MAX_REQUEST_ATTACHMENT_BYTES * 4 // 3 + 1024 * 1024):
                            result["errors"].append({"batch": batch_num, "error": "response_too_large",
                                                     "limit_bytes": limits.MAX_REQUEST_ATTACHMENT_BYTES})
                            continue

                        batch_response = await response.json()

                        # 각 응답 처리
                        for resp in batch_response.get("responses", []):
                            req_id = int(resp.get("id", 0)) - 1
                            if req_id < 0 or req_id >= len(batch_ids):
                                continue

                            message_id = batch_ids[req_id]

                            if resp.get("status") != 200:
                                # R06: 원문 message 대신 상태 코드 + 검증된 error.code 만
                                result["errors"].append(
                                    graph_error_entry(resp.get("status"), resp.get("body"), message_id=message_id)
                                )
                                continue

                            mail_data = resp.get("body", {})
                            await self._process_mail_with_options(
                                mail_data, result, storage, converter,
                                save_file=save_file, include_body=include_body,
                                flat_folder=flat_folder, budget=budget,
                            )

                except ToolExecutionError:  # SecurityError·invalid_argument·quota_exceeded 전부 그대로 올린다
                    raise
                except Exception as e:
                    result["errors"].append(f"배치 {batch_num} 예외: {public_error(e)}")

        result["success"] = result["processed"] > 0
        result["message"] = f"{result['processed']}개 메일 처리 완료"

        return result

    async def _process_mail(self, mail_data: Dict[str, Any], result: Dict[str, Any]):
        """
        단일 메일 처리 (폴더 생성, 첨부파일/본문 저장) — 구 동기 경로

        Args:
            mail_data: 메일 데이터
            result: 결과 딕셔너리 (업데이트됨)
        """
        if self.paths is not None:
            # mode 1 에는 동기 구 경로가 없다 — 경계·배타 생성을 지키는 비동기 경로로 보낸다
            result.setdefault("body_contents", [])
            result.setdefault("attachment_contents", [])
            await self._process_mail_with_options(mail_data, result, self.folder_manager)
            return

        message_id = mail_data.get("id", "")
        subject = mail_data.get("subject", "제목 없음")

        try:
            # 폴더 생성
            folder_path = self.folder_manager.get_mail_folder_path(mail_data)

            saved_files = []

            # 메일 본문 저장
            mail_file = self.folder_manager.save_mail_content(folder_path, mail_data)
            if mail_file:
                saved_files.append(mail_file)
                result["saved_mails"].append(mail_file)

            # 첨부파일 저장
            attachments = mail_data.get("attachments", [])
            for attachment in attachments:
                att_file = self.folder_manager.save_attachment(folder_path, attachment)
                if att_file:
                    saved_files.append(att_file)
                    result["saved_attachments"].append(att_file)

            # 메타데이터 저장
            self.metadata_manager.add_processed_mail(
                message_id, mail_data, str(folder_path), saved_files
            )

            result["processed"] += 1

        except Exception as e:
            result["errors"].append(f"메일 처리 실패 ({subject[:30]}...): {public_error(e)}")

    async def _process_mail_with_options(
        self,
        mail_data: Dict[str, Any],
        result: Dict[str, Any],
        storage: Optional[StorageBackend],
        converter: Optional[ConversionPipeline] = None,
        save_file: bool = True,
        include_body: bool = True,
        flat_folder: bool = False,
        budget: Optional[ByteBudget] = None,
    ):
        """
        단일 메일 처리 오케스트레이터 (Storage Backend 및 Converter 옵션 적용)

        본문 처리와 첨부파일 처리를 mail_attachment_processor 모듈에 위임

        Args:
            mail_data: 메일 데이터
            result: 결과 딕셔너리 (업데이트됨)
            storage: 저장소 백엔드 (Local 또는 OneDrive), save_file=False면 None
            converter: 텍스트 변환기 (None이면 원본 저장)
            save_file: 파일 저장 여부 (False면 메모리 반환만)
            include_body: 본문 포함 여부
        """
        message_id = mail_data.get("id", "")
        subject = mail_data.get("subject", "제목 없음")

        try:
            folder_path = None
            saved_files = []
            errors_before = len(result["errors"])

            # Step 1: 저장 모드일 때만 폴더 생성
            if save_file and storage:
                if flat_folder:
                    folder_path = await storage.create_folder_flat()
                else:
                    folder_path = await storage.create_folder(mail_data)

            # Step 2: 메일 본문 처리 (processor 모듈 호출)
            if include_body:
                body_saved = await process_body_content(
                    mail_data, result, storage, folder_path, save_file
                )
                if body_saved:
                    saved_files.append(body_saved)

            # Step 3: 첨부파일 처리 (processor 모듈 호출) — 요청 예산·변환 슬롯 적용 (N08/P01)
            attachment_saved = await process_attachments(
                mail_data, result, storage, converter, folder_path, save_file,
                budget=budget, workers=self.workers, owner_key=self.owner_key,
            )
            saved_files.extend(attachment_saved)

            # Step 4: 폴더 경로 기록
            if save_file and folder_path:
                if str(folder_path) not in result.get("saved_folders", []):
                    result.setdefault("saved_folders", []).append(str(folder_path))

            # Step 5: 메타데이터 저장 (저장 모드 + 이 메일의 저장이 전부 성공했을 때만).
            # 실패를 "처리 완료" 로 적으면 중복 제외에 걸려 재시도조차 못 한다.
            if save_file and len(result["errors"]) == errors_before:
                self.metadata_manager.add_processed_mail(
                    message_id, mail_data, str(folder_path) if folder_path else "", saved_files
                )

            result["processed"] += 1

        except ToolExecutionError:  # SecurityError·invalid_argument·quota_exceeded 전부 그대로 올린다
            raise
        except Exception as e:
            logger.warning("[ATTACH] mail processing failed: %s", type(e).__name__)
            result["errors"].append(f"메일 처리 실패 ({subject[:30]}...): {public_error(e)}")

    def _local_target_dir(self, save_directory: Optional[str]) -> Path:
        """fetch_specific_attachments 의 로컬 저장 기준 디렉터리."""
        if self.paths is not None:
            if save_directory:
                return resolve_save_dir(self.paths, save_directory)
            return Path(self.folder_manager.base_directory)
        if save_directory:
            return legacy_dir(save_directory)
        return Path(self.folder_manager.base_directory)

    async def fetch_specific_attachments(
        self,
        user_email: str,
        attachments_info: List[Dict[str, str]],
        save_directory: Optional[str] = None,
        flat_folder: bool = False,
        storage_type: str = "local",
        onedrive_folder: str = "/Attachments",
    ) -> Dict[str, Any]:
        """
        특정 첨부파일들을 선택적으로 다운로드 (메일 ID와 첨부파일 ID 지정)

        Args:
            user_email: 사용자 이메일
            attachments_info: [{"message_id": "...", "attachment_id": "..."}, ...]
            save_directory: 저장 디렉토리
            flat_folder: True면 하위폴더 없이 save_directory에 바로 저장

        Returns:
            처리 결과
        """
        result = {
            "success": False,
            "total_requested": len(attachments_info),
            "downloaded": 0,
            "failed": 0,
            "results": [],
            "errors": [],
        }

        if not attachments_info:
            result["success"] = True
            result["message"] = "No attachments to process"
            return result
        check_list_size(attachments_info, "message_attachment_ids")
        if storage_type == "onedrive":
            graph_drive_path(onedrive_folder)  # R07: 잘못된 OneDrive 경로는 토큰 획득 전에 거부

        # 토큰 확인 (연결 없음은 여기서 바로 실패 — 토큰 자체는 보관하지 않는다)
        if not await self._get_access_token(user_email):
            result["errors"].append("Failed to acquire access token")
            return result

        # 요청마다 공급자에서 토큰을 얻는 핸들러 (토큰 보유 객체 금지 — ②-2.5)
        handler = SingleAttachmentHandler(token_provider=self.token_provider, user_email=user_email)

        # Storage Backend 생성
        use_onedrive = storage_type == "onedrive"
        storage = None
        if use_onedrive:
            storage = get_storage_backend(
                storage_type="onedrive",
                auth_manager=self.token_provider,
                user_email=user_email,
                base_folder=onedrive_folder,
            )

        # 로컬 저장 디렉토리 경로 해석 (mode 1: 사용자 files/ 안만)
        dir_path = None if use_onedrive else self._local_target_dir(save_directory)

        # 메일 정보 캐시 (같은 message_id 첨부파일이 여러 개일 때 중복 API 호출 방지)
        mail_info_cache: Dict[str, Dict[str, Any]] = {}
        budget = ByteBudget(limits.MAX_REQUEST_ATTACHMENT_BYTES)

        for info in attachments_info:
            message_id = info.get("message_id")
            attachment_id = info.get("attachment_id")

            if not message_id or not attachment_id:
                result["errors"].append(f"Invalid attachment info: {info}")
                result["failed"] += 1
                continue

            try:
                # 첨부파일 다운로드
                attachment_data = await handler.get_attachment(message_id, attachment_id, user_email)

                # 파일명 및 경로 설정
                file_name = attachment_data.get("name", f"attachment_{attachment_id}")

                # 메일 정보 조회 (폴더명 생성용) - 캐시 활용
                if not flat_folder and message_id not in mail_info_cache:
                    mail_info_cache[message_id] = await handler.get_message_summary(message_id, user_email)

                # attachment_data는 이미 위에서 조회됨 (contentBytes 포함)
                content_bytes = attachment_data.get("contentBytes")
                if not content_bytes:
                    raise ValueError("No content bytes in attachment")
                estimated = limits.base64_decoded_size(content_bytes)
                if estimated > limits.MAX_ATTACHMENT_BYTES:  # 첨부 1건 상한 (N08 gap 1)
                    raise AttachmentLimitExceeded("attachment_too_large", limits.MAX_ATTACHMENT_BYTES)
                if not budget.take(estimated):               # 요청 예산
                    raise AttachmentLimitExceeded("request_attachment_budget_exceeded", budget.limit)

                if use_onedrive and storage:
                    # OneDrive 저장
                    if flat_folder:
                        folder_path_str = await storage.create_folder_flat()
                    else:
                        mail_data = mail_info_cache.get(message_id, {})
                        if mail_data:
                            folder_path_str = await storage.create_folder(mail_data)
                        else:
                            folder_path_str = await storage.create_folder_flat(
                                storage.child_path(safe_filename(message_id[:8]))
                            )

                    file_content = base64.b64decode(content_bytes)
                    saved_path = await storage.save_file(
                        folder_path_str, file_name, file_content,
                        attachment_data.get("contentType")
                    )
                    result_folder_path = folder_path_str
                else:
                    file_content = base64.b64decode(content_bytes)
                    saved_path, result_folder_path = self._save_specific_local(
                        dir_path, message_id, file_name, file_content,
                        None if flat_folder else mail_info_cache.get(message_id, {}),
                    )

                result["results"].append({
                    "message_id": message_id,
                    "attachment_id": attachment_id,
                    "file_path": saved_path,
                    "folder_path": result_folder_path,
                    "name": file_name,
                    "success": True,
                })
                result["downloaded"] += 1

            except ToolExecutionError:  # SecurityError·invalid_argument·quota_exceeded 전부 그대로 올린다
                raise
            except Exception as e:
                # R06: Graph 오류는 요약(상태 코드·오류 코드)만, 그 밖의 예외는 공개용 문구만
                entry = {"message_id": message_id, "attachment_id": attachment_id, "success": False}
                if isinstance(e, GraphRequestError):
                    entry.update(e.summary)
                elif isinstance(e, AttachmentLimitExceeded):
                    entry.update({"error": e.code, "limit_bytes": e.limit})
                else:
                    entry["error"] = public_error(e)
                result["errors"].append({k: v for k, v in entry.items() if k != "success"})
                result["results"].append(entry)
                result["failed"] += 1

        result["success"] = result["downloaded"] > 0
        result["message"] = f"Downloaded {result['downloaded']}/{result['total_requested']} attachments"

        return result

    def _save_specific_local(
        self,
        dir_path: Path,
        message_id: str,
        file_name: str,
        file_content: bytes,
        mail_data: Optional[Dict[str, Any]],
    ):
        """특정 첨부 1건 로컬 저장 → (파일 참조, 폴더 참조).

        `mail_data` 가 None 이면 flat(하위 폴더 없음). 원격 이름·message_id 는 단일 이름으로
        정화한다. mode 1 은 배타 생성 + `files/` 기준 상대경로, mode 0 은 기존대로 덮어쓰기 +
        절대경로.
        """
        if mail_data is None:
            folder_name = None
        elif mail_data:
            folder_name = self.folder_manager.create_folder_name(mail_data)
        else:
            folder_name = str(message_id)[:8]

        if self.paths is not None:
            storage: UserLocalStorageBackend = self.folder_manager
            folder = Path(dir_path) if folder_name is None else storage.folder_for_name(dir_path, folder_name)
            folder.mkdir(parents=True, exist_ok=True)
            saved = storage.write_bytes(folder, file_name, file_content)
            return storage.public(saved), storage.public(folder)

        folder_path = Path(dir_path) if folder_name is None else Path(dir_path) / safe_filename(folder_name)
        folder_path.mkdir(parents=True, exist_ok=True)
        save_file_path = folder_path / safe_filename(file_name)
        with open(save_file_path, "wb") as f:
            f.write(file_content)
        return str(save_file_path), str(folder_path)

    async def close(self):
        """리소스 정리 — 토큰 공급자는 빌린 것이므로 닫지 않는다 (②-2.4 종료 경로 소유권)."""
        return None

