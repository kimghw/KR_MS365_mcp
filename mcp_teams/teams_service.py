"""
Teams Service - GraphTeamsClient Facade
인자를 그대로 위임하고, 필요시 일부 값만 조정하는 서비스 레이어
(mcp_outlook/outlook_service.py 구조 참조)
"""

import base64
import binascii
import logging
import os
from pathlib import Path
from typing import BinaryIO, Dict, Any, Optional, List, Tuple, Union

from .graph_teams_client import GraphTeamsClient
from .teams_db_manager import TeamsDBManager
from .teams_types import (
    ChatType,
    MessageImportance,
    check_limit,
    check_list_size,
)
from mcp_common.paths import PathNotAllowedError, allowed_roots, resolve_safe_path
from mcp_common.principal import MISSING, Principal, assert_owner, assert_user_email
from mcp_common.secure_files import UnsafePathError, open_for_read
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.security_policy import multi_user_enabled
from mcp_common.user_resolver import resolve_user_email

logger = logging.getLogger(__name__)
# mcp_service 는 메타데이터 표식일 뿐 런타임 동작에는 영향이 없다.
# 도구의 실제 계약은 spec/param_spec/teams.yaml 이며 이 데코레이터의 인자가 아니다.
from mcp_common.service_meta import mcp_service


def _get_default_user_email() -> Optional[str]:
    """
    기본 사용자 이메일 조회 (mcp_common 의 결정적 선택 정책에 위임). **mode 0 전용.**

    Returns:
        기본 사용자의 이메일 또는 None
    """
    return resolve_user_email()


def _no_user() -> Dict[str, Any]:
    return {"success": False, "error": "사용자 이메일이 필요합니다. 로그인이 필요합니다."}


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class TeamsService:
    """
    GraphTeamsClient의 Facade

    - 동일 시그니처로 위임
    - 일부 값만 조정/하드코딩
    - DB 연동으로 한글 이름 저장/조회 지원

    모드 (spec/spec_멀티유저.md ②-7.6):
    - mode 0: `TeamsService()` — 공용 AuthManager·`database/auth.db`, 소유자 = user_email.
    - mode 1: `TeamsService(principal=..., token_provider=..., db_path=paths.teams_db,
      files_root=paths.files)` — 한 사용자에 고정. 생성자는 I/O 를 하지 않는다.
      모든 진입점이 호출 principal = 이 서비스 소유자, user_email = 연결 계정을 확인한다.
    """

    def __init__(
        self,
        *,
        principal: Optional[Principal] = None,
        token_provider: Any = None,
        db_path: Optional[Union[str, "os.PathLike[str]"]] = None,
        files_root: Optional[Union[str, "os.PathLike[str]"]] = None,
    ):
        self._principal = principal
        self._token_provider = token_provider
        self._db_path = db_path
        self._files_root = Path(files_root) if files_root is not None else None
        self._client: Optional[GraphTeamsClient] = None
        self._db_manager: Optional[TeamsDBManager] = None
        self._initialized = False

    def _make_db_manager(self) -> TeamsDBManager:
        if self._principal is not None:
            if self._db_path is None:
                raise RuntimeError("사용자 전용 Teams DB 경로가 없습니다")
            return TeamsDBManager(self._db_path, owner_key=self._principal.user_key)
        if multi_user_enabled():
            # 공용 auth.db·공용 인증으로 되돌아가지 않는다
            raise SecurityError(ErrorCode.MISSING_PRINCIPAL)
        return TeamsDBManager(self._db_path) if self._db_path is not None else TeamsDBManager()

    async def initialize(self) -> bool:
        """서비스 초기화"""
        if self._initialized:
            return True

        self._db_manager = self._make_db_manager()
        self._client = GraphTeamsClient(token_provider=self._token_provider)

        if await self._client.initialize():
            self._initialized = True
            return True
        return False

    def _ensure_initialized(self):
        """초기화 확인"""
        if not self._initialized or not self._client:
            raise RuntimeError("TeamsService not initialized. Call initialize() first.")

    def _resolve_user(self, user_email: Optional[str]) -> Optional[str]:
        """진입점의 사용자 확정.

        mode 0: 값이 없으면 기본 사용자(mcp_common 정책).
        mode 1: 요청 principal 이 이 서비스의 소유자여야 하고(아니면 not_found), user_email 은
        연결 계정과 같아야 한다(아니면 identity_mismatch). 기본 사용자 탐색은 하지 않는다.
        """
        if self._principal is None:
            return user_email or _get_default_user_email()
        assert_owner(self._principal.user_key)
        return assert_user_email(MISSING if user_email is None else user_email)

    def _local_file(self, file_path: str) -> str:
        """mode 1 의 file_path → 본인 `files/` 안의 실제 경로.

        검사는 공용 경로 관문 `mcp_common.paths.resolve_safe_path()` 하나로 한다(②-7.4 —
        UNC·장치·ADS·예약명·`..`·링크·auth/db 트리 거부, 절대경로 비노출 오류). 관문은 요청
        principal 의 `files/` 를 보므로 반드시 `_resolve_user()` 로 소유자를 확인한 뒤 부른다.
        결과가 이 서비스의 `files/` 안인지 한 번 더 확인한다.
        """
        resolved = resolve_safe_path(file_path)
        root = self._files_root
        if root is None or not _is_within(Path(resolved), Path(os.path.realpath(root))):
            raise SecurityError(ErrorCode.PATH_NOT_ALLOWED)
        return os.fspath(resolved)

    def _open_local_file(self, file_path: str) -> Tuple[BinaryIO, str]:
        """`file_path` 를 **검증한 handle** 로 연다 (R12 — 검사 후 일반 open 으로 다시 열지 않는다).

        mode 1: 본인 `files/` 루트 기준 → `open_for_read(path, files_root)`.
        mode 0: `mcp_common.paths` 허용 루트(프로젝트 루트·MCP_ALLOWED_PATHS·MCP_DATA_DIR) 중
        그 경로를 담는 루트 기준 → `open_for_read(path, root)`.
        `open_for_read` 는 경계 재확인·일반 파일·하드링크 검사를 연 handle 에서 다시 한다.

        Returns:
            (열린 파일, 실제 경로)
        Raises:
            SecurityError(path_not_allowed): mode 1 루트 밖·링크·하드링크
            PathNotAllowedError: mode 0 허용 루트 밖
            OSError: 없음·디렉터리 등 (메시지에 경로 없음)
        """
        if self._principal is not None:
            resolved = Path(self._local_file(file_path))
            root = Path(self._files_root)  # _local_file 이 None 이면 이미 거부했다
            try:
                return open_for_read(resolved, root), os.fspath(resolved)
            except UnsafePathError as exc:
                raise exc.to_security_error() from None

        resolved = resolve_safe_path(file_path)  # mode 0 허용 루트 밖이면 PathNotAllowedError
        root = next((r for r in allowed_roots() if _is_within(resolved, r)), None)
        if root is None:
            raise PathNotAllowedError("path outside allowed roots")
        return open_for_read(resolved, root), os.fspath(resolved)

    async def close(self):
        """리소스 정리 — 자기 HTTP 세션만 닫는다(토큰 공급자는 서비스 풀이 닫는다)."""
        if self._client:
            await self._client.close()
            self._client = None
        self._initialized = False

    # ========================================================================
    # 채팅 관련 메서드
    # ========================================================================

    @mcp_service(
        tool_name="handler_teams_list_chats",
        server_name="teams",
        service_name="list_chats",
        category="teams_chat",
        tags=["query", "chat"],
        priority=5,
        description="Teams 채팅 목록 조회",
    )
    async def list_chats(
        self,
        user_email: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """채팅 목록 조회"""
        self._ensure_initialized()
        user_email = self._resolve_user(user_email)
        if not user_email:
            return _no_user()
        limit = check_limit(limit)  # 1~1000 (R02)
        return await self._client.list_chats(user_email, limit)

    @mcp_service(
        tool_name="handler_teams_get_chat",
        server_name="teams",
        service_name="get_chat",
        category="teams_chat",
        tags=["query", "chat"],
        priority=5,
        description="Teams 특정 채팅 정보 조회",
    )
    async def get_chat(
        self,
        chat_id: str,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """특정 채팅 정보 조회"""
        self._ensure_initialized()
        user_email = self._resolve_user(user_email)
        if not user_email:
            return _no_user()
        return await self._client.get_chat(user_email, chat_id)

    # ========================================================================
    # 메시지 관련 메서드
    # ========================================================================

    @mcp_service(
        tool_name="handler_teams_get_chat_messages",
        server_name="teams",
        service_name="get_chat_messages",
        category="teams_message",
        tags=["query", "message"],
        priority=5,
        description="Teams 채팅 메시지 목록 조회",
    )
    async def get_chat_messages(
        self,
        chat_id: Optional[str] = None,
        limit: int = 50,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """채팅 메시지 목록 조회"""
        self._ensure_initialized()
        user_email = self._resolve_user(user_email)
        if not user_email:
            return _no_user()
        limit = check_limit(limit)  # 1~1000 (R02)
        return await self._client.get_chat_messages(user_email, chat_id, limit)

    @mcp_service(
        tool_name="handler_teams_send_chat_message",
        server_name="teams",
        service_name="send_chat_message",
        category="teams_message",
        tags=["send", "message"],
        priority=5,
        description="Teams 채팅에 메시지 전송",
    )
    async def send_chat_message(
        self,
        content: str,
        chat_id: Optional[str] = None,
        prefix: str = "[claude]",
        content_type: str = "text",
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """채팅에 메시지 전송"""
        self._ensure_initialized()
        user_email = self._resolve_user(user_email)
        if not user_email:
            return _no_user()
        return await self._client.send_chat_message(
            user_email=user_email,
            content=content,
            chat_id=chat_id,
            prefix=prefix,
            content_type=content_type,
        )

    @mcp_service(
        tool_name="handler_teams_send_chat_file",
        server_name="teams",
        service_name="send_chat_file",
        category="teams_message",
        tags=["send", "message", "file"],
        priority=5,
        description="Teams 채팅에 파일을 붙여 메시지 전송",
    )
    async def send_chat_file(
        self,
        content: str,
        file_name: Optional[str] = None,
        file_base64: Optional[str] = None,
        file_path: Optional[str] = None,
        recipient_email: Optional[str] = None,
        chat_id: Optional[str] = None,
        prefix: str = "",
        content_type: str = "html",
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """채팅에 파일을 붙여 메시지 전송. 파일은 내용(file_base64)이나 이 PC 의 경로(file_path) 가운데 하나로 준다."""
        self._ensure_initialized()
        user_email = self._resolve_user(user_email)
        if not user_email:
            return _no_user()

        if file_base64:
            try:
                file_bytes = base64.b64decode(file_base64, validate=True)
            except (binascii.Error, ValueError):
                return {"success": False, "error": "file_base64 가 올바른 base64 가 아닙니다."}
        elif file_path:
            # mode 1 은 본인 files/ 안만, mode 0 은 허용 루트 안만 — 검증한 handle 에서 읽는다.
            try:
                handle, local_path = self._open_local_file(file_path)
                with handle as f:
                    file_bytes = f.read()
            except SecurityError:
                raise  # mode 1 거부(path_not_allowed)는 고정 오류 코드로 그대로 올린다
            except PathNotAllowedError:
                return {"success": False, "error": "파일을 읽지 못했습니다: 허용 루트 밖 경로"}
            except OSError as e:
                # 응답에는 절대경로·OS 메시지를 싣지 않는다(open_for_read 메시지에도 경로가 없다)
                return {"success": False, "error": f"파일을 읽지 못했습니다: {type(e).__name__}"}
            file_name = file_name or os.path.basename(local_path)
        else:
            return {"success": False, "error": "file_base64 나 file_path 가운데 하나가 필요합니다."}
        if not file_bytes:
            return {"success": False, "error": "빈 파일은 보낼 수 없습니다."}
        # 경로 구분자가 섞인 이름은 OneDrive 의 다른 폴더를 가리키게 된다 — 이름만 남긴다.
        file_name = os.path.basename((file_name or "").replace("\\", "/")).strip()
        if not file_name:
            return {"success": False, "error": "file_name 이 필요합니다(확장자 포함)."}

        return await self._client.send_chat_file(
            user_email=user_email,
            content=content,
            file_name=file_name,
            file_bytes=file_bytes,
            chat_id=chat_id,
            recipient_email=recipient_email,
            prefix=prefix,
            content_type=content_type,
        )

    # ========================================================================
    # 팀 관련 메서드
    # ========================================================================

    @mcp_service(
        tool_name="handler_teams_list_teams",
        server_name="teams",
        service_name="list_teams",
        category="teams_team",
        tags=["query", "team"],
        priority=5,
        description="사용자가 속한 팀 목록 조회",
    )
    async def list_teams(
        self,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """팀 목록 조회"""
        self._ensure_initialized()
        user_email = self._resolve_user(user_email)
        if not user_email:
            return _no_user()
        return await self._client.list_teams(user_email)

    @mcp_service(
        tool_name="handler_teams_list_channels",
        server_name="teams",
        service_name="list_channels",
        category="teams_channel",
        tags=["query", "channel"],
        priority=5,
        description="팀의 채널 목록 조회",
    )
    async def list_channels(
        self,
        team_id: str,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """채널 목록 조회"""
        self._ensure_initialized()
        user_email = self._resolve_user(user_email)
        if not user_email:
            return _no_user()
        return await self._client.list_channels(user_email, team_id)

    @mcp_service(
        tool_name="handler_teams_get_channel_messages",
        server_name="teams",
        service_name="get_channel_messages",
        category="teams_message",
        tags=["query", "channel", "message"],
        priority=5,
        description="채널 메시지 목록 조회",
    )
    async def get_channel_messages(
        self,
        team_id: str,
        channel_id: str,
        limit: int = 50,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """채널 메시지 목록 조회"""
        self._ensure_initialized()
        user_email = self._resolve_user(user_email)
        if not user_email:
            return _no_user()
        limit = check_limit(limit)  # 1~1000 (R02)
        return await self._client.get_channel_messages(user_email, team_id, channel_id, limit)

    @mcp_service(
        tool_name="handler_teams_send_channel_message",
        server_name="teams",
        service_name="send_channel_message",
        category="teams_message",
        tags=["send", "channel", "message"],
        priority=5,
        description="채널에 메시지 전송",
    )
    async def send_channel_message(
        self,
        team_id: str,
        channel_id: str,
        content: str,
        content_type: str = "text",
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """채널에 메시지 전송"""
        self._ensure_initialized()
        user_email = self._resolve_user(user_email)
        if not user_email:
            return _no_user()
        return await self._client.send_channel_message(
            user_email=user_email,
            team_id=team_id,
            channel_id=channel_id,
            content=content,
            content_type=content_type,
        )

    @mcp_service(
        tool_name="handler_teams_get_message_replies",
        server_name="teams",
        service_name="get_message_replies",
        category="teams_message",
        tags=["query", "reply"],
        priority=5,
        description="메시지 답글 목록 조회",
    )
    async def get_message_replies(
        self,
        team_id: str,
        channel_id: str,
        message_id: str,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """메시지 답글 목록 조회"""
        self._ensure_initialized()
        user_email = self._resolve_user(user_email)
        if not user_email:
            return _no_user()
        return await self._client.get_message_replies(user_email, team_id, channel_id, message_id)

    # ========================================================================
    # 한글 이름 관련 메서드 (DB 연동)
    # ========================================================================

    @mcp_service(
        tool_name="handler_teams_save_korean_name",
        server_name="teams",
        service_name="save_korean_name",
        category="teams_chat",
        tags=["update", "korean"],
        priority=5,
        description="채팅방의 한글 이름을 DB에 저장 (단일 저장)",
    )
    async def save_korean_name(
        self,
        topic_kr: str,
        chat_id: Optional[str] = None,
        topic_en: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        채팅의 한글 이름을 저장

        Args:
            topic_kr: 한글 이름
            chat_id: 채팅 ID (선택)
            topic_en: 영문 이름 (선택, chat_id가 없을 때 검색용)
            user_email: 사용자 이메일 (선택, 없으면 기본 사용자)

        Returns:
            저장 결과
        """
        self._ensure_initialized()
        user_email = self._resolve_user(user_email)
        if not user_email:
            return _no_user()
        return await self._db_manager.save_korean_name(
            user_id=user_email,
            topic_kr=topic_kr,
            chat_id=chat_id,
            topic_en=topic_en,
        )

    @mcp_service(
        tool_name="handler_teams_save_korean_names_batch",
        server_name="teams",
        service_name="save_korean_names_batch",
        category="teams_chat",
        tags=["update", "korean", "batch"],
        priority=5,
        description="여러 채팅방의 한글 이름을 한 번에 DB에 저장",
    )
    async def save_korean_names_batch(
        self,
        names: List[Dict[str, str]],
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        여러 채팅의 한글 이름을 한 번에 저장

        Args:
            names: [{"topic_en": "영문", "topic_kr": "한글"}, ...] 형식의 리스트
            user_email: 사용자 이메일 (선택, 없으면 기본 사용자)

        Returns:
            배치 저장 결과
        """
        self._ensure_initialized()
        user_email = self._resolve_user(user_email)
        if not user_email:
            return _no_user()
        check_list_size(names, "names")  # 최대 500개 (R02) — DB 작업 전에 막는다
        return await self._db_manager.save_korean_names_batch(
            user_id=user_email,
            names=names,
        )

    @mcp_service(
        tool_name="handler_teams_find_chat_by_name",
        server_name="teams",
        service_name="find_chat_by_name",
        category="teams_chat",
        tags=["query", "search"],
        priority=5,
        description="사용자 이름으로 채팅 검색 (한글/영문 모두 지원)",
    )
    async def find_chat_by_name(
        self,
        recipient_name: str,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        사용자 이름으로 채팅 검색

        Args:
            recipient_name: 검색할 상대방 이름 (한글 또는 영문)
            user_email: 사용자 이메일 (선택, 없으면 기본 사용자)

        Returns:
            검색된 chat_id
        """
        self._ensure_initialized()
        user_email = self._resolve_user(user_email)
        if not user_email:
            return _no_user()
        chat_id = await self._db_manager.find_chat_by_name(
            user_id=user_email,
            recipient_name=recipient_name,
        )
        if chat_id:
            return {"success": True, "found": True, "chat_id": chat_id}
        # "검색 결과 없음"은 도구 실행 실패가 아니다. success=False 로 돌려주면
        # 공통 오류 계약(mcp_common.errors.is_failure)이 isError=True 로 승격시켜
        # 정상적인 빈 결과가 오류로 보이게 된다.
        return {
            "success": True,
            "found": False,
            "chat_id": None,
            "message": f"'{recipient_name}' 채팅을 찾을 수 없습니다",
        }

    @mcp_service(
        tool_name="handler_teams_sync_chats",
        server_name="teams",
        service_name="sync_chats",
        category="teams_chat",
        tags=["sync", "db"],
        priority=5,
        description="채팅 목록을 DB에 동기화",
    )
    async def sync_chats(
        self,
        limit: int = 50,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        채팅 목록을 조회하고 DB에 동기화

        Args:
            limit: 조회할 채팅 개수
            user_email: 사용자 이메일 (선택, 없으면 기본 사용자)

        Returns:
            동기화 결과
        """
        self._ensure_initialized()

        user_email = self._resolve_user(user_email)
        if not user_email:
            return _no_user()

        # Graph API에서 채팅 목록 조회
        limit = check_limit(limit)  # 1~1000 (R02)
        result = await self._client.list_chats(user_email, limit)
        if not result.get("success"):
            return result

        # DB에 동기화
        chats = result.get("chats", [])
        sync_result = await self._db_manager.sync_chats_to_db(
            user_email, chats, deactivate_missing=not result.get("has_more")
        )
        if not sync_result.get("success"):
            return {
                "success": False,
                "error": sync_result.get("error", "DB 동기화 실패"),
                "chats_count": len(chats),
            }

        return {
            "success": True,
            "chats_count": len(chats),
            "synced": sync_result.get("synced", 0),
            "deactivated": sync_result.get("deactivated", 0),
        }

    @mcp_service(
        tool_name="handler_teams_get_chats_without_korean",
        server_name="teams",
        service_name="get_chats_without_korean",
        category="teams_chat",
        tags=["query", "korean"],
        priority=5,
        description="한글 이름이 없는 채팅 목록 조회",
    )
    async def get_chats_without_korean(
        self,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        한글 이름이 없는 채팅 목록 조회

        Args:
            user_email: 사용자 이메일 (선택, 없으면 기본 사용자)

        Returns:
            한글 이름이 없는 채팅 목록
        """
        self._ensure_initialized()
        user_email = self._resolve_user(user_email)
        if not user_email:
            return _no_user()
        chats = await self._db_manager.get_chats_without_korean_names(user_email)
        return {
            "success": True,
            "chats": chats,
            "count": len(chats),
        }
