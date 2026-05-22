"""
Graph Mail URL Builder - URL 빌더 통합 모듈
filter, search, expand URL 생성을 담당

Classes:
    - FilterBuilder: $filter URL 파라미터 빌더
    - SearchBuilder: $search URL 파라미터 빌더
    - ExpandBuilder: $expand URL 파라미터 빌더
    - GraphMailUrlBuilder: 통합 URL 빌더
"""

from typing import Optional, List, Dict, Any, Union
from datetime import datetime, timedelta, timezone


class FilterBuilder:
    """
    Graph API $filter URL 파라미터 빌더

    메일 필터링 조건을 OData $filter 쿼리로 변환
    """

    def __init__(self, user_id: str = "me"):
        """
        Initialize filter builder

        Args:
            user_id: User ID or "me" for current user
        """
        self.user_id = user_id
        self._filters: List[str] = []

    def reset(self) -> "FilterBuilder":
        """필터 초기화"""
        self._filters = []
        return self

    def unread(self, value: bool = True) -> "FilterBuilder":
        """읽지 않은 메일 필터"""
        self._filters.append(f"isRead eq {str(not value).lower()}")
        return self

    def has_attachments(self, value: bool = True) -> "FilterBuilder":
        """첨부파일 있는 메일 필터"""
        self._filters.append(f"hasAttachments eq {str(value).lower()}")
        return self

    def importance(self, value: str) -> "FilterBuilder":
        """중요도 필터 (low, normal, high)"""
        self._filters.append(f"importance eq '{value}'")
        return self

    def from_sender(self, email: str) -> "FilterBuilder":
        """특정 발신자 필터"""
        self._filters.append(f"from/emailAddress/address eq '{email}'")
        return self

    def from_any(self, emails: List[str]) -> "FilterBuilder":
        """여러 발신자 중 하나 필터 (OR)"""
        if emails:
            sender_filters = [f"from/emailAddress/address eq '{email}'" for email in emails]
            self._filters.append(f"({' or '.join(sender_filters)})")
        return self

    def subject_contains(self, text: str) -> "FilterBuilder":
        """제목에 텍스트 포함 필터"""
        self._filters.append(f"contains(subject, '{text}')")
        return self

    def subject_any(self, texts: List[str]) -> "FilterBuilder":
        """제목에 여러 텍스트 중 하나 포함 필터 (OR)"""
        if texts:
            subject_filters = [f"contains(subject, '{text}')" for text in texts]
            self._filters.append(f"({' or '.join(subject_filters)})")
        return self

    def days_back(self, days: int) -> "FilterBuilder":
        """최근 N일 이내 메일 필터"""
        date_from = datetime.now(timezone.utc) - timedelta(days=days)
        self._filters.append(f"receivedDateTime ge {date_from.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        return self

    def received_after(self, date: datetime) -> "FilterBuilder":
        """특정 날짜 이후 메일 필터"""
        self._filters.append(f"receivedDateTime ge {date.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        return self

    def received_before(self, date: datetime) -> "FilterBuilder":
        """특정 날짜 이전 메일 필터"""
        self._filters.append(f"receivedDateTime le {date.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        return self

    def exclude_sender(self, email: str) -> "FilterBuilder":
        """특정 발신자 제외"""
        self._filters.append(f"from/emailAddress/address ne '{email}'")
        return self

    def exclude_senders(self, emails: List[str]) -> "FilterBuilder":
        """여러 발신자 제외"""
        for email in emails:
            self._filters.append(f"from/emailAddress/address ne '{email}'")
        return self

    def exclude_subject(self, text: str) -> "FilterBuilder":
        """제목에 텍스트 포함된 메일 제외"""
        self._filters.append(f"not contains(subject, '{text}')")
        return self

    def exclude_subjects(self, texts: List[str]) -> "FilterBuilder":
        """여러 텍스트 포함된 제목 제외"""
        for text in texts:
            self._filters.append(f"not contains(subject, '{text}')")
        return self

    def add_raw(self, filter_string: str) -> "FilterBuilder":
        """직접 필터 문자열 추가"""
        self._filters.append(filter_string)
        return self

    def build(self) -> str:
        """
        필터 쿼리 문자열 생성

        Returns:
            $filter 쿼리 문자열 (빈 경우 빈 문자열)
        """
        return " and ".join(self._filters) if self._filters else ""

    def build_from_dict(self, params: Dict[str, Any]) -> str:
        """
        딕셔너리에서 필터 쿼리 생성

        Args:
            params: 필터 파라미터 딕셔너리

        Returns:
            $filter 쿼리 문자열
        """
        self.reset()

        if params.get("unread") is not None:
            self.unread(params["unread"])

        if params.get("has_attachments") is not None:
            self.has_attachments(params["has_attachments"])

        if params.get("importance"):
            self.importance(params["importance"])

        if params.get("from_sender"):
            self.from_sender(params["from_sender"])

        if params.get("from_any"):
            self.from_any(params["from_any"])

        if params.get("subject"):
            self.subject_contains(params["subject"])

        if params.get("subject_any"):
            self.subject_any(params["subject_any"])

        if params.get("days_back"):
            self.days_back(params["days_back"])

        if params.get("exclude_senders"):
            self.exclude_senders(params["exclude_senders"])

        if params.get("exclude_subjects"):
            self.exclude_subjects(params["exclude_subjects"])

        return self.build()


class SearchBuilder:
    """
    Graph API $search URL 파라미터 빌더

    KQL (Keyword Query Language) 검색 쿼리 생성
    """

    def __init__(self, user_id: str = "me"):
        """
        Initialize search builder

        Args:
            user_id: User ID or "me" for current user
        """
        self.user_id = user_id
        self._terms: List[str] = []

    def reset(self) -> "SearchBuilder":
        """검색어 초기화"""
        self._terms = []
        return self

    def keyword(self, text: str) -> "SearchBuilder":
        """키워드 검색"""
        self._terms.append(text)
        return self

    def from_sender(self, email: str) -> "SearchBuilder":
        """발신자 검색"""
        self._terms.append(f"from:{email}")
        return self

    def to_recipient(self, email: str) -> "SearchBuilder":
        """수신자 검색"""
        self._terms.append(f"to:{email}")
        return self

    def subject(self, text: str) -> "SearchBuilder":
        """제목 검색"""
        self._terms.append(f"subject:{text}")
        return self

    def body(self, text: str) -> "SearchBuilder":
        """본문 검색"""
        self._terms.append(f"body:{text}")
        return self

    def attachment_name(self, name: str) -> "SearchBuilder":
        """첨부파일명 검색"""
        self._terms.append(f"attachment:{name}")
        return self

    def has_attachment(self) -> "SearchBuilder":
        """첨부파일 있는 메일 검색"""
        self._terms.append("hasattachments:true")
        return self

    def add_raw(self, term: str) -> "SearchBuilder":
        """직접 검색어 추가"""
        self._terms.append(term)
        return self

    def build(self) -> str:
        """
        검색 쿼리 문자열 생성

        Returns:
            $search 쿼리 문자열 (따옴표 포함)
        """
        if not self._terms:
            return ""
        return " ".join(self._terms)


class ExpandBuilder:
    """
    Graph API $expand URL 파라미터 빌더

    관련 리소스 확장 ($expand) 및 필드 선택 ($select) 빌더
    """

    def __init__(self):
        """초기화"""
        self._select_fields: List[str] = []
        self._expand_fields: List[str] = []

    def reset(self) -> "ExpandBuilder":
        """빌더 초기화"""
        self._select_fields = []
        self._expand_fields = []
        return self

    def select(self, fields: Union[List[str], Dict[str, bool]]) -> "ExpandBuilder":
        """
        $select 필드 설정

        Args:
            fields: 선택할 필드 (리스트 또는 dict)

        Returns:
            self (메서드 체이닝용)
        """
        if isinstance(fields, list):
            self._select_fields = fields
        elif isinstance(fields, dict):
            self._select_fields = [field for field, include in fields.items() if include]
        return self

    def expand(self, field: str) -> "ExpandBuilder":
        """
        $expand 필드 추가

        Args:
            field: 확장할 필드 (예: "attachments")

        Returns:
            self (메서드 체이닝용)
        """
        if field not in self._expand_fields:
            self._expand_fields.append(field)
        return self

    def expand_attachments(self) -> "ExpandBuilder":
        """$expand=attachments 추가 (편의 메서드)"""
        return self.expand("attachments")

    def build_select(self) -> str:
        """$select 쿼리 문자열 생성"""
        return ",".join(self._select_fields) if self._select_fields else ""

    def build_expand(self) -> str:
        """$expand 쿼리 문자열 생성"""
        return ",".join(self._expand_fields) if self._expand_fields else ""

    def build_query_string(self) -> str:
        """
        URL 쿼리 문자열 생성

        Returns:
            쿼리 문자열 (예: "$select=id,subject&$expand=attachments")
        """
        parts = []

        if self._select_fields:
            parts.append(f"$select={','.join(self._select_fields)}")

        if self._expand_fields:
            parts.append(f"$expand={','.join(self._expand_fields)}")

        return "&".join(parts)

    def build_url(self, base_url: str) -> str:
        """
        전체 URL 생성

        Args:
            base_url: 기본 URL (예: "/me/messages/{id}")

        Returns:
            쿼리 파라미터가 포함된 URL
        """
        query = self.build_query_string()
        if query:
            return f"{base_url}?{query}"
        return base_url


class GraphMailUrlBuilder:
    """
    Graph API 메일 URL 통합 빌더

    filter, search, expand를 조합하여 완전한 URL 생성
    """

    BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(self, user_email: str = "me"):
        """
        Initialize URL builder

        Args:
            user_email: User email or "me" for current user
        """
        self.user_email = user_email
        self.filter_builder = FilterBuilder(user_email)
        self.search_builder = SearchBuilder(user_email)
        self.expand_builder = ExpandBuilder()

    def reset(self) -> "GraphMailUrlBuilder":
        """모든 빌더 초기화"""
        self.filter_builder.reset()
        self.search_builder.reset()
        self.expand_builder.reset()
        return self

    @property
    def messages_url(self) -> str:
        """메시지 기본 URL"""
        return f"{self.BASE_URL}/users/{self.user_email}/messages"

    def build_filter_url(
        self,
        filter_query: Optional[str] = None,
        select_fields: Optional[List[str]] = None,
        order_by: Optional[str] = None,
        top: Optional[int] = None,
        skip: Optional[int] = None,
    ) -> str:
        """
        $filter 기반 URL 생성

        Args:
            filter_query: $filter 쿼리 문자열
            select_fields: 선택할 필드 목록
            order_by: 정렬 순서
            top: 최대 결과 수
            skip: 건너뛸 결과 수

        Returns:
            완전한 URL
        """
        url = self.messages_url
        params = []

        if filter_query:
            params.append(f"$filter={filter_query}")

        if select_fields:
            params.append(f"$select={','.join(select_fields)}")

        if order_by:
            params.append(f"$orderby={order_by}")

        if top is not None:
            params.append(f"$top={top}")

        if skip is not None:
            params.append(f"$skip={skip}")

        if params:
            url += "?" + "&".join(params)

        return url

    def build_search_url(
        self,
        search_query: str,
        select_fields: Optional[List[str]] = None,
        order_by: Optional[str] = None,
        top: Optional[int] = None,
    ) -> str:
        """
        $search 기반 URL 생성

        Args:
            search_query: 검색 쿼리
            select_fields: 선택할 필드 목록
            order_by: 정렬 순서
            top: 최대 결과 수 (최대 250)

        Returns:
            완전한 URL
        """
        url = self.messages_url
        params = [f'$search="{search_query}"']

        if select_fields:
            params.append(f"$select={','.join(select_fields)}")

        if order_by:
            params.append(f"$orderby={order_by}")

        if top is not None:
            actual_top = min(top, 250)  # Graph API search limit
            params.append(f"$top={actual_top}")

        url += "?" + "&".join(params)
        return url

    def build_message_url(
        self,
        message_id: str,
        select_fields: Optional[List[str]] = None,
        expand: Optional[str] = None,
    ) -> str:
        """
        단일 메시지 URL 생성

        Args:
            message_id: 메시지 ID
            select_fields: 선택할 필드 목록
            expand: 확장할 필드 (예: "attachments")

        Returns:
            완전한 URL
        """
        url = f"{self.messages_url}/{message_id}"
        params = []

        if select_fields:
            params.append(f"$select={','.join(select_fields)}")

        if expand:
            params.append(f"$expand={expand}")

        if params:
            url += "?" + "&".join(params)

        return url

    def build_attachments_url(self, message_id: str) -> str:
        """
        첨부파일 목록 URL 생성

        Args:
            message_id: 메시지 ID

        Returns:
            첨부파일 목록 URL
        """
        return f"{self.messages_url}/{message_id}/attachments"

    def build_attachment_url(self, message_id: str, attachment_id: str) -> str:
        """
        단일 첨부파일 URL 생성

        Args:
            message_id: 메시지 ID
            attachment_id: 첨부파일 ID

        Returns:
            첨부파일 URL
        """
        return f"{self.messages_url}/{message_id}/attachments/{attachment_id}"

    def build_batch_request(
        self,
        message_ids: List[str],
        select_fields: Optional[List[str]] = None,
        expand: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        $batch 요청 본문 생성

        Args:
            message_ids: 메시지 ID 목록
            select_fields: 선택할 필드 목록
            expand: 확장할 필드

        Returns:
            $batch requests 배열
        """
        requests = []

        # 쿼리 파라미터 구성
        params = []
        if select_fields:
            params.append(f"$select={','.join(select_fields)}")
        if expand:
            params.append(f"$expand={expand}")

        query_string = "?" + "&".join(params) if params else ""

        for i, message_id in enumerate(message_ids):
            requests.append({
                "id": str(i + 1),
                "method": "GET",
                "url": f"/users/{self.user_email}/messages/{message_id}{query_string}",
            })

        return requests


# 편의 함수들
def quick_filter(
    unread: Optional[bool] = None,
    has_attachments: Optional[bool] = None,
    importance: Optional[str] = None,
    from_sender: Optional[str] = None,
    from_any: Optional[List[str]] = None,
    subject: Optional[str] = None,
    subject_any: Optional[List[str]] = None,
    days_back: Optional[int] = None,
    exclude_senders: Optional[List[str]] = None,
    exclude_subjects: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    빠른 필터 파라미터 생성

    Returns:
        필터 파라미터 딕셔너리
    """
    params = {}

    if unread is not None:
        params["unread"] = unread
    if has_attachments is not None:
        params["has_attachments"] = has_attachments
    if importance:
        params["importance"] = importance
    if from_sender:
        params["from_sender"] = from_sender
    if from_any:
        params["from_any"] = from_any
    if subject:
        params["subject"] = subject
    if subject_any:
        params["subject_any"] = subject_any
    if days_back:
        params["days_back"] = days_back
    if exclude_senders:
        params["exclude_senders"] = exclude_senders
    if exclude_subjects:
        params["exclude_subjects"] = exclude_subjects

    return params


def build_filter_query(params: Dict[str, Any]) -> str:
    """
    딕셔너리에서 $filter 쿼리 생성 (편의 함수)

    Args:
        params: 필터 파라미터

    Returns:
        $filter 쿼리 문자열
    """
    builder = FilterBuilder()
    return builder.build_from_dict(params)
