"""
Graph Calendar Client - 통합 캘린더 처리 클라이언트
GraphCalendarQuery를 통해 캘린더 이벤트 관리를 통합하는 상위 클래스

보안 오류(`SecurityError` — 연결 없음·재인증 필요·계정 불일치)는 오류 dict 로 삼키지 않고
그대로 올린다. 런타임이 고정 코드와 연결 안내로 바꾼다(spec/spec_멀티유저.md ②-12 항목 4).
"""

import logging
from typing import Dict, Any, List, Optional, TYPE_CHECKING

from mcp_common.security_contracts import SecurityError

if TYPE_CHECKING:
    from core.protocols import TokenProviderProtocol

from .graph_calendar_query import GraphCalendarQuery
from .calendar_types import (
    EventFilterParams,
    EventSelectParams,
    EventCreateParams,
    EventUpdateParams,
    ScheduleRequest,
)

logger = logging.getLogger(__name__)

#: 예상하지 못한 처리 오류의 공개 메시지 — 예외 원문은 응답에 싣지 않는다 (②-9)
_CLIENT_ERROR_MESSAGE = "캘린더 요청을 처리하지 못했습니다."


class GraphCalendarClient:
    """
    Graph API 캘린더 통합 클라이언트

    캘린더 이벤트 조회, 생성, 수정, 삭제 및 일정 조회를 통합 관리
    """

    def __init__(self, token_provider: Optional["TokenProviderProtocol"] = None):
        """
        초기화

        Args:
            token_provider: 토큰 제공자 (None이면 mode 0 의 공용 AuthManager 사용 —
                멀티유저에서는 사용자 고정 공급자가 필수). 소유하지 않으므로 닫지 않는다.
        """
        self.token_provider = token_provider
        self.calendar_query: Optional[GraphCalendarQuery] = None
        self._initialized: bool = False

    async def initialize(self) -> bool:
        """
        컴포넌트 초기화

        Returns:
            초기화 성공 여부
        """
        if self._initialized:
            return True

        try:
            # GraphCalendarQuery 초기화 (token_provider 주입)
            self.calendar_query = GraphCalendarQuery(token_provider=self.token_provider)

            if not await self.calendar_query.initialize():
                logger.error("GraphCalendarQuery 초기화 실패")
                return False

            self._initialized = True
            return True

        except Exception as e:
            logger.error("GraphCalendarClient 초기화 오류: %s", type(e).__name__)
            return False

    def _ensure_initialized(self):
        """초기화 확인"""
        if not self._initialized:
            raise Exception("GraphCalendarClient not initialized. Call initialize() first.")

    async def list_events(
        self,
        user_email: str,
        filter_params: Optional[EventFilterParams] = None,
        select_params: Optional[EventSelectParams] = None,
        top: int = 50,
        orderby: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        캘린더 이벤트 목록 조회

        Args:
            user_email: 사용자 이메일
            filter_params: 필터 파라미터
            select_params: 선택 필드 파라미터
            top: 최대 결과 수
            orderby: 정렬 순서

        Returns:
            이벤트 목록 결과
        """
        self._ensure_initialized()

        try:
            result = await self.calendar_query.list_events(
                user_email=user_email,
                filter_params=filter_params,
                select_params=select_params,
                top=top,
                orderby=orderby,
            )
            return result

        except SecurityError:
            raise
        except Exception as e:
            logger.warning("GraphCalendarClient 처리 오류: %s", type(e).__name__)
            return {
                "status": "error",
                "error": _CLIENT_ERROR_MESSAGE,
                "value": [],
            }

    async def list_calendar_view(
        self,
        user_email: str,
        start_datetime: str,
        end_datetime: str,
        select_params: Optional[EventSelectParams] = None,
        top: int = 50,
        orderby: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        캘린더 뷰 조회 (시간 범위 기반)

        Args:
            user_email: 사용자 이메일
            start_datetime: 시작 일시 (ISO 8601 형식)
            end_datetime: 종료 일시 (ISO 8601 형식)
            select_params: 선택 필드 파라미터
            top: 최대 결과 수
            orderby: 정렬 순서

        Returns:
            캘린더 뷰 결과
        """
        self._ensure_initialized()

        try:
            result = await self.calendar_query.list_calendar_view(
                user_email=user_email,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                select_params=select_params,
                top=top,
                orderby=orderby,
            )
            return result

        except SecurityError:
            raise
        except Exception as e:
            logger.warning("GraphCalendarClient 처리 오류: %s", type(e).__name__)
            return {
                "status": "error",
                "error": _CLIENT_ERROR_MESSAGE,
                "value": [],
            }

    async def get_event(
        self,
        user_email: str,
        event_id: str,
        select_params: Optional[EventSelectParams] = None,
    ) -> Dict[str, Any]:
        """
        단일 이벤트 조회

        Args:
            user_email: 사용자 이메일
            event_id: 이벤트 ID
            select_params: 선택 필드 파라미터

        Returns:
            이벤트 정보
        """
        self._ensure_initialized()

        try:
            result = await self.calendar_query.get_event(
                user_email=user_email,
                event_id=event_id,
                select_params=select_params,
            )
            return result

        except SecurityError:
            raise
        except Exception as e:
            logger.warning("GraphCalendarClient 처리 오류: %s", type(e).__name__)
            return {
                "status": "error",
                "error": _CLIENT_ERROR_MESSAGE,
            }

    async def create_event(
        self,
        user_email: str,
        event_data: EventCreateParams,
    ) -> Dict[str, Any]:
        """
        새 이벤트 생성

        Args:
            user_email: 사용자 이메일
            event_data: 이벤트 생성 데이터

        Returns:
            생성된 이벤트 정보
        """
        self._ensure_initialized()

        try:
            result = await self.calendar_query.create_event(
                user_email=user_email,
                event_data=event_data,
            )
            return result

        except SecurityError:
            raise
        except Exception as e:
            logger.warning("GraphCalendarClient 처리 오류: %s", type(e).__name__)
            return {
                "status": "error",
                "error": _CLIENT_ERROR_MESSAGE,
            }

    async def update_event(
        self,
        user_email: str,
        event_id: str,
        event_data: EventUpdateParams,
    ) -> Dict[str, Any]:
        """
        이벤트 수정

        Args:
            user_email: 사용자 이메일
            event_id: 이벤트 ID
            event_data: 이벤트 수정 데이터

        Returns:
            수정된 이벤트 정보
        """
        self._ensure_initialized()

        try:
            result = await self.calendar_query.update_event(
                user_email=user_email,
                event_id=event_id,
                event_data=event_data,
            )
            return result

        except SecurityError:
            raise
        except Exception as e:
            logger.warning("GraphCalendarClient 처리 오류: %s", type(e).__name__)
            return {
                "status": "error",
                "error": _CLIENT_ERROR_MESSAGE,
            }

    async def delete_event(
        self,
        user_email: str,
        event_id: str,
    ) -> Dict[str, Any]:
        """
        이벤트 삭제

        Args:
            user_email: 사용자 이메일
            event_id: 이벤트 ID

        Returns:
            삭제 결과
        """
        self._ensure_initialized()

        try:
            result = await self.calendar_query.delete_event(
                user_email=user_email,
                event_id=event_id,
            )
            return result

        except SecurityError:
            raise
        except Exception as e:
            logger.warning("GraphCalendarClient 처리 오류: %s", type(e).__name__)
            return {
                "status": "error",
                "error": _CLIENT_ERROR_MESSAGE,
            }

    async def get_schedule(
        self,
        user_email: str,
        schedule_request: ScheduleRequest,
    ) -> Dict[str, Any]:
        """
        일정 가용성 조회

        Args:
            user_email: 사용자 이메일
            schedule_request: 일정 조회 요청 데이터

        Returns:
            일정 가용성 정보
        """
        self._ensure_initialized()

        try:
            result = await self.calendar_query.get_schedule(
                user_email=user_email,
                schedule_request=schedule_request,
            )
            return result

        except SecurityError:
            raise
        except Exception as e:
            logger.warning("GraphCalendarClient 처리 오류: %s", type(e).__name__)
            return {
                "status": "error",
                "error": _CLIENT_ERROR_MESSAGE,
            }

    def format_events(self, results: Dict[str, Any], verbose: bool = False) -> str:
        """
        이벤트 결과 포맷팅

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
            output.append(f"Error: {results.get('error', 'Unknown error')}")
            if results.get("errors"):
                output.append(f"   Details: {len(results['errors'])} errors occurred")
            return "\n".join(output)

        # 이벤트 정보
        events = results.get("value", [])
        output.append(f"Events: {len(events)}")

        # 이벤트 목록 (verbose 모드)
        if verbose and events:
            output.append("\n" + "-" * 40)
            for idx, event in enumerate(events[:10], 1):  # 최대 10개만
                subject = event.get("subject", "No Subject")
                start = event.get("start", {}).get("dateTime", "Unknown")
                end = event.get("end", {}).get("dateTime", "Unknown")
                output.append(f"{idx}. {subject[:50]}")
                output.append(f"   Start: {start}")
                output.append(f"   End: {end}")

                # 참석자 정보 (있는 경우)
                attendees = event.get("attendees", [])
                if attendees:
                    attendee_emails = [
                        a.get("emailAddress", {}).get("address", "Unknown")
                        for a in attendees[:3]
                    ]
                    output.append(f"   Attendees: {', '.join(attendee_emails)}")
                    if len(attendees) > 3:
                        output.append(f"              ... and {len(attendees) - 3} more")

        output.append("=" * 80)
        return "\n".join(output)

    async def close(self):
        """리소스 정리 — 쿼리 객체만 닫는다(토큰 공급자는 쿼리도 닫지 않는다)."""
        if self.calendar_query:
            await self.calendar_query.close()
        self._initialized = False
