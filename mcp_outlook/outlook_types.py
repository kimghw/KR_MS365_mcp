"""
Microsoft Graph API 메일 필터링을 위한 타입 정의
Pydantic 모델을 사용하여 런타임 유효성 검증과 문서화 제공
"""

from typing import Optional, List, Union, Literal, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class FilterParams(BaseModel):
    """메일 필터링 파라미터 (포함 조건)"""

    model_config = ConfigDict(extra="ignore")  # 추가 필드 무시

    # 발신자 관련
    from_address: Optional[Union[str, List[str]]] = Field(
        None,
        description="from/emailAddress/address - 단일 또는 여러 발신자 이메일 주소",
        examples=["user@example.com", ["user1@example.com", "user2@example.com"]],
    )
    sender_address: Optional[Union[str, List[str]]] = Field(
        None, description="sender/emailAddress/address - 실제 발신자 이메일 주소", examples=["sender@example.com"]
    )

    # 날짜/시간 관련
    # 단일 날짜 필터 (ge 연산자만 사용)
    received_date_time: Optional[str] = Field(
        None,
        description="메일 수신 날짜/시간 - 이 시간 이후 메일만 조회 (ISO 8601 형식)",
        examples=["2024-12-01T00:00:00Z"],
    )
    sent_date_time: Optional[str] = Field(
        None,
        description="메일 발신 날짜/시간 - 이 시간 이후 메일만 조회 (ISO 8601 형식)",
        examples=["2024-12-01T00:00:00Z"],
    )
    created_date_time: Optional[str] = Field(
        None, description="메일 생성 날짜/시간 - 이 시간 이후 메일만 조회 (ISO 8601 형식)"
    )
    last_modified_date_time: Optional[str] = Field(
        None, description="메일 최종 수정 날짜/시간 - 이 시간 이후 메일만 조회 (ISO 8601 형식)"
    )

    # 날짜 범위 필터 (received_date_time의 확장 버전)
    received_date_from: Optional[str] = Field(
        None, description="메일 수신 시작 날짜 (포함, receivedDateTime >= 이 값)", examples=["2024-12-01T00:00:00Z"]
    )
    received_date_to: Optional[str] = Field(
        None, description="메일 수신 종료 날짜 (포함, receivedDateTime <= 이 값)", examples=["2024-12-31T23:59:59Z"]
    )
    sent_date_from: Optional[str] = Field(None, description="메일 발신 시작 날짜 (포함, sentDateTime >= 이 값)")
    sent_date_to: Optional[str] = Field(None, description="메일 발신 종료 날짜 (포함, sentDateTime <= 이 값)")

    # 메시지 상태
    is_read: Optional[bool] = Field(None, description="읽음 상태 필터 (true: 읽은 메일, false: 읽지 않은 메일)")
    is_draft: Optional[bool] = Field(None, description="임시 저장 상태 필터")
    has_attachments: Optional[bool] = Field(None, description="첨부파일 포함 여부")
    is_delivery_receipt_requested: Optional[bool] = Field(None, description="배달 확인 요청 여부")
    is_read_receipt_requested: Optional[bool] = Field(None, description="읽음 확인 요청 여부")

    # 메시지 속성
    importance: Optional[Literal["low", "normal", "high"]] = Field(
        None, description="메일 중요도 (low: 낮음, normal: 보통, high: 높음)"
    )
    sensitivity: Optional[Literal["normal", "personal", "private", "confidential"]] = Field(
        None, description="메일 민감도"
    )
    inference_classification: Optional[Literal["focused", "other"]] = Field(
        None, description="받은 편지함 분류 (focused: 중요, other: 기타)"
    )

    # 내용 관련 - 단일 키워드 또는 리스트 (리스트는 OR로 연결)
    subject: Optional[Union[str, List[str]]] = Field(
        None,
        description="제목에 포함될 키워드 (단일 문자열 또는 리스트)",
        examples=["회의", ["프로젝트", "미팅", "회의"]],
    )
    body_content: Optional[Union[str, List[str]]] = Field(
        None, description="본문에 포함될 키워드 (단일 문자열 또는 리스트)"
    )
    body_preview: Optional[Union[str, List[str]]] = Field(
        None, description="미리보기에 포함될 키워드 (단일 문자열 또는 리스트)"
    )

    # 키워드 연결 방식 (리스트일 때만 적용)
    subject_operator: Optional[Literal["or", "and"]] = Field(
        "or", description="제목 키워드 연결 방식 (or: 하나라도 포함, and: 모두 포함)"
    )
    body_operator: Optional[Literal["or", "and"]] = Field(
        "or", description="본문 키워드 연결 방식 (or: 하나라도 포함, and: 모두 포함)"
    )

    # ID 관련
    id: Optional[str] = Field(None, description="메일 고유 ID")
    conversation_id: Optional[str] = Field(None, description="대화 스레드 ID")
    parent_folder_id: Optional[str] = Field(None, description="폴더 ID")

    # 카테고리 및 플래그
    categories: Optional[List[str]] = Field(
        None, description="메일 카테고리 목록", examples=[["중요", "업무", "프로젝트"]]
    )
    flag_status: Optional[Literal["notFlagged", "complete", "flagged"]] = Field(
        None, description="플래그 상태 (notFlagged: 플래그 없음, complete: 완료, flagged: 플래그됨)"
    )

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()


class ExcludeParams(BaseModel):
    """메일 제외 파라미터 (제외 조건)"""

    model_config = ConfigDict(extra="ignore")

    # 발신자 제외 - 단일 문자열 또는 리스트 지원
    exclude_from_address: Optional[Union[str, List[str]]] = Field(
        None, description="제외할 발신자 주소 (from 필드)", examples=[["noreply@github.com", "notification@slack.com"]]
    )
    exclude_sender_address: Optional[Union[str, List[str]]] = Field(
        None, description="제외할 실제 발신자 주소 (sender 필드)"
    )

    # 키워드 제외
    exclude_subject_keywords: Optional[List[str]] = Field(
        None, description="제목에서 제외할 키워드 목록", examples=[["newsletter", "광고", "홍보"]]
    )
    exclude_body_keywords: Optional[List[str]] = Field(None, description="본문에서 제외할 키워드 목록")
    exclude_preview_keywords: Optional[List[str]] = Field(None, description="미리보기에서 제외할 키워드 목록")

    # 속성 제외
    exclude_importance: Optional[Literal["low", "normal", "high"]] = Field(None, description="제외할 중요도")
    exclude_sensitivity: Optional[Literal["normal", "personal", "private", "confidential"]] = Field(
        None, description="제외할 민감도"
    )
    exclude_classification: Optional[Literal["focused", "other"]] = Field(None, description="제외할 받은 편지함 분류")

    # 상태 제외
    exclude_read_status: Optional[bool] = Field(None, description="제외할 읽음 상태")
    exclude_draft_status: Optional[bool] = Field(None, description="제외할 임시 저장 상태")
    exclude_attachment_status: Optional[bool] = Field(None, description="제외할 첨부파일 상태")
    exclude_delivery_receipt: Optional[bool] = Field(None, description="제외할 배달 확인 상태")
    exclude_read_receipt: Optional[bool] = Field(None, description="제외할 읽음 확인 상태")

    # 플래그 및 카테고리 제외
    exclude_flag_status: Optional[Literal["notFlagged", "complete", "flagged"]] = Field(
        None, description="제외할 플래그 상태"
    )
    exclude_categories: Optional[List[str]] = Field(None, description="제외할 카테고리 목록")

    # ID 제외
    exclude_id: Optional[str] = Field(None, description="제외할 메일 ID")
    exclude_conversation_id: Optional[str] = Field(None, description="제외할 대화 스레드 ID")
    exclude_parent_folder_id: Optional[str] = Field(None, description="제외할 폴더 ID")

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def keys(self):
        """dict.keys() 호환성"""
        return self.__class__.model_fields.keys()


class SelectParams(BaseModel):
    """메일 조회 시 선택할 필드 ($select 파라미터)"""

    model_config = ConfigDict(extra="ignore")

    # 기본 정보
    id: Optional[bool] = Field(None, description="메시지 고유 식별자 (읽기 전용)")
    created_date_time: Optional[bool] = Field(None, description="메시지 생성 날짜/시간 (ISO 8601 형식, UTC)")
    last_modified_date_time: Optional[bool] = Field(None, description="메시지 최종 수정 날짜/시간 (ISO 8601 형식, UTC)")
    change_key: Optional[bool] = Field(None, description="메시지 버전 키")

    # 카테고리
    categories: Optional[bool] = Field(None, description="메시지에 연결된 카테고리 목록")

    # 날짜/시간
    received_date_time: Optional[bool] = Field(None, description="메시지 수신 날짜/시간 (ISO 8601 형식, UTC)")
    sent_date_time: Optional[bool] = Field(None, description="메시지 발신 날짜/시간 (ISO 8601 형식, UTC)")

    # 메일 속성
    has_attachments: Optional[bool] = Field(None, description="첨부파일 포함 여부")
    internet_message_id: Optional[bool] = Field(None, description="RFC2822 형식의 메시지 ID")
    subject: Optional[bool] = Field(None, description="메시지 제목")
    body_preview: Optional[bool] = Field(None, description="메시지 본문의 처음 255자 (텍스트 형식)")
    importance: Optional[bool] = Field(None, description="메시지 중요도 (low, normal, high)")
    parent_folder_id: Optional[bool] = Field(None, description="부모 메일 폴더의 고유 식별자")
    conversation_id: Optional[bool] = Field(None, description="이메일이 속한 대화의 ID")
    conversation_index: Optional[bool] = Field(None, description="대화 내 메시지 위치를 나타내는 인덱스")

    # 상태
    is_delivery_receipt_requested: Optional[bool] = Field(None, description="배달 확인 요청 여부")
    is_read_receipt_requested: Optional[bool] = Field(None, description="읽음 확인 요청 여부")
    is_read: Optional[bool] = Field(None, description="메시지 읽음 상태")
    is_draft: Optional[bool] = Field(None, description="메시지가 임시 저장 상태인지 여부")

    # 링크 및 분류
    web_link: Optional[bool] = Field(None, description="Outlook Web에서 메시지를 열기 위한 URL")
    inference_classification: Optional[bool] = Field(None, description="메시지 분류 (focused 또는 other)")

    # 복합 객체
    body: Optional[bool] = Field(None, description="메시지 본문 (HTML 또는 텍스트 형식)")
    sender: Optional[bool] = Field(None, description="메시지를 생성하는 데 사용된 계정")
    from_recipient: Optional[bool] = Field(None, description="메시지가 전송된 사서함의 소유자 (from 필드)")
    to_recipients: Optional[bool] = Field(None, description="받는 사람 (To:) 목록")
    cc_recipients: Optional[bool] = Field(None, description="참조 (Cc:) 수신자 목록")
    bcc_recipients: Optional[bool] = Field(None, description="숨은 참조 (Bcc:) 수신자 목록")
    reply_to: Optional[bool] = Field(None, description="회신 시 사용할 이메일 주소 목록")
    flag: Optional[bool] = Field(None, description="메시지의 플래그 상태, 시작 날짜, 기한, 완료 날짜")
    unique_body: Optional[bool] = Field(None, description="현재 메시지에 고유한 본문 부분")
    internet_message_headers: Optional[bool] = Field(
        None, description="RFC5322에 정의된 메시지 헤더 컬렉션 (읽기 전용)"
    )

    # TypedDict 호환성을 위한 메서드
    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 호환성을 위한 메서드"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict['key'] 스타일 접근을 위한 메서드"""
        return getattr(self, key)

    def get_selected_fields(self) -> List[str]:
        """True로 설정된 필드들의 Graph API 필드명 목록 반환"""
        field_mapping = {
            "id": "id",
            "created_date_time": "createdDateTime",
            "last_modified_date_time": "lastModifiedDateTime",
            "change_key": "changeKey",
            "categories": "categories",
            "received_date_time": "receivedDateTime",
            "sent_date_time": "sentDateTime",
            "has_attachments": "hasAttachments",
            "internet_message_id": "internetMessageId",
            "subject": "subject",
            "body_preview": "bodyPreview",
            "importance": "importance",
            "parent_folder_id": "parentFolderId",
            "conversation_id": "conversationId",
            "conversation_index": "conversationIndex",
            "is_delivery_receipt_requested": "isDeliveryReceiptRequested",
            "is_read_receipt_requested": "isReadReceiptRequested",
            "is_read": "isRead",
            "is_draft": "isDraft",
            "web_link": "webLink",
            "inference_classification": "inferenceClassification",
            "body": "body",
            "sender": "sender",
            "from_recipient": "from",
            "to_recipients": "toRecipients",
            "cc_recipients": "ccRecipients",
            "bcc_recipients": "bccRecipients",
            "reply_to": "replyTo",
            "flag": "flag",
            "unique_body": "uniqueBody",
            "internet_message_headers": "internetMessageHeaders",
        }

        selected = []
        for python_field, api_field in field_mapping.items():
            if getattr(self, python_field, None) is True:
                selected.append(api_field)
        return selected


class MailQueryParams(BaseModel):
    """전체 메일 쿼리 파라미터"""

    model_config = ConfigDict(extra="ignore")

    filter: Optional[FilterParams] = Field(None, description="포함 조건 필터")
    exclude: Optional[ExcludeParams] = Field(None, description="제외 조건 필터")
    select: Optional[SelectParams] = Field(None, description="반환할 필드 선택")

    # 추가 쿼리 옵션
    top: Optional[int] = Field(10, ge=1, le=1000, description="반환할 최대 메일 수 (1-1000)")
    skip: Optional[int] = Field(None, ge=0, description="건너뛸 메일 수 (페이징용)")
    orderby: Optional[str] = Field(
        "receivedDateTime desc", description="정렬 기준 (예: 'receivedDateTime desc', 'subject asc')"
    )
    search: Optional[str] = Field(None, description="검색어 ($search 파라미터, filter와 동시 사용 불가)")
    count: Optional[bool] = Field(None, description="총 메일 개수 포함 여부")


# 헬퍼 함수들 - 파라미터 생성
def create_filter_params(**kwargs) -> FilterParams:
    """FilterParams 객체를 생성하는 헬퍼 함수"""
    return FilterParams(**kwargs)


def create_exclude_params(**kwargs) -> ExcludeParams:
    """ExcludeParams 객체를 생성하는 헬퍼 함수"""
    return ExcludeParams(**kwargs)


def create_select_params(**kwargs) -> SelectParams:
    """SelectParams 객체를 생성하는 헬퍼 함수

    Examples:
        # 특정 필드만 선택
        select = create_select_params(
            id=True,
            subject=True,
            from_recipient=True,
            received_date_time=True,
            has_attachments=True
        )
    """
    return SelectParams(**kwargs)


# 헬퍼 함수들 - 쿼리 빌드
def build_filter_query(params: Union[FilterParams, Dict]) -> str:
    """FilterParams를 Graph API $filter 쿼리 문자열로 변환"""
    filters = []

    # Pydantic 모델이면 dict로 변환
    if isinstance(params, FilterParams):
        params_dict = params.model_dump(exclude_none=True)
    else:
        params_dict = params

    # 발신자
    if params_dict.get("from_address"):
        from_addr = params_dict["from_address"]
        if isinstance(from_addr, list):
            # 리스트인 경우 OR 조건으로 연결
            from_filters = [f"from/emailAddress/address eq '{addr}'" for addr in from_addr]
            if from_filters:
                filters.append(f"({' or '.join(from_filters)})")
        else:
            # 단일 문자열
            filters.append(f"from/emailAddress/address eq '{from_addr}'")

    if params_dict.get("sender_address"):
        sender_addr = params_dict["sender_address"]
        if isinstance(sender_addr, list):
            # 리스트인 경우 OR 조건으로 연결
            sender_filters = [f"sender/emailAddress/address eq '{addr}'" for addr in sender_addr]
            if sender_filters:
                filters.append(f"({' or '.join(sender_filters)})")
        else:
            # 단일 문자열
            filters.append(f"sender/emailAddress/address eq '{sender_addr}'")

    # 날짜/시간 - 단일 날짜 필터 (ge 연산자만 사용 - 이후 날짜)
    if params_dict.get("received_date_time"):
        filters.append(f"receivedDateTime ge {params_dict['received_date_time']}")
    if params_dict.get("sent_date_time"):
        filters.append(f"sentDateTime ge {params_dict['sent_date_time']}")
    if params_dict.get("created_date_time"):
        filters.append(f"createdDateTime ge {params_dict['created_date_time']}")
    if params_dict.get("last_modified_date_time"):
        filters.append(f"lastModifiedDateTime ge {params_dict['last_modified_date_time']}")

    # 날짜 범위 필터 (from/to로 정확한 기간 지정)
    if params_dict.get("received_date_from"):
        filters.append(f"receivedDateTime ge {params_dict['received_date_from']}")
    if params_dict.get("received_date_to"):
        filters.append(f"receivedDateTime le {params_dict['received_date_to']}")
    if params_dict.get("sent_date_from"):
        filters.append(f"sentDateTime ge {params_dict['sent_date_from']}")
    if params_dict.get("sent_date_to"):
        filters.append(f"sentDateTime le {params_dict['sent_date_to']}")

    # 상태
    if params_dict.get("is_read") is not None:
        filters.append(f"isRead eq {str(params_dict['is_read']).lower()}")
    if params_dict.get("is_draft") is not None:
        filters.append(f"isDraft eq {str(params_dict['is_draft']).lower()}")
    if params_dict.get("has_attachments") is not None:
        filters.append(f"hasAttachments eq {str(params_dict['has_attachments']).lower()}")

    # 속성
    if params_dict.get("importance"):
        filters.append(f"importance eq '{params_dict['importance']}'")
    if params_dict.get("sensitivity"):
        filters.append(f"sensitivity eq '{params_dict['sensitivity']}'")
    if params_dict.get("inference_classification"):
        filters.append(f"inferenceClassification eq '{params_dict['inference_classification']}'")

    # 키워드 검색
    if params_dict.get("subject"):
        subject = params_dict["subject"]
        if isinstance(subject, list):
            # 리스트인 경우 OR 또는 AND로 연결
            operator = params_dict.get("subject_operator", "or")  # 기본값 'or'
            subject_filters = [f"contains(subject, '{kw}')" for kw in subject]
            if subject_filters:
                if operator == "and":
                    filters.extend(subject_filters)  # AND는 각각 추가
                else:  # or
                    filters.append(f"({' or '.join(subject_filters)})")
        else:
            # 단일 문자열
            filters.append(f"contains(subject, '{subject}')")

    if params_dict.get("body_content"):
        body_content = params_dict["body_content"]
        if isinstance(body_content, list):
            # 리스트인 경우 OR 또는 AND로 연결
            operator = params_dict.get("body_operator", "or")  # 기본값 'or'
            body_filters = [f"contains(body/content, '{kw}')" for kw in body_content]
            if body_filters:
                if operator == "and":
                    filters.extend(body_filters)  # AND는 각각 추가
                else:  # or
                    filters.append(f"({' or '.join(body_filters)})")
        else:
            # 단일 문자열
            filters.append(f"contains(body/content, '{body_content}')")

    if params_dict.get("body_preview"):
        body_preview = params_dict["body_preview"]
        if isinstance(body_preview, list):
            # 리스트인 경우 OR로 연결 (preview는 보통 OR만 사용)
            preview_filters = [f"contains(bodyPreview, '{kw}')" for kw in body_preview]
            if preview_filters:
                filters.append(f"({' or '.join(preview_filters)})")
        else:
            # 단일 문자열
            filters.append(f"contains(bodyPreview, '{body_preview}')")

    # ID
    if params_dict.get("id"):
        filters.append(f"id eq '{params_dict['id']}'")
    if params_dict.get("conversation_id"):
        filters.append(f"conversationId eq '{params_dict['conversation_id']}'")
    if params_dict.get("parent_folder_id"):
        filters.append(f"parentFolderId eq '{params_dict['parent_folder_id']}'")

    # 카테고리
    if params_dict.get("categories"):
        for category in params_dict["categories"]:
            filters.append(f"categories/any(c:c eq '{category}')")

    # 플래그
    if params_dict.get("flag_status"):
        filters.append(f"flag/flagStatus eq '{params_dict['flag_status']}'")

    return " and ".join(filters)


def build_exclude_query(params: Union[ExcludeParams, Dict]) -> str:
    """ExcludeParams를 Graph API 제외 쿼리 문자열로 변환"""
    excludes = []

    # Pydantic 모델이면 dict로 변환
    if isinstance(params, ExcludeParams):
        params_dict = params.model_dump(exclude_none=True)
    else:
        params_dict = params

    # 발신자 제외
    if params_dict.get("exclude_from_address"):
        exclude_from = params_dict["exclude_from_address"]
        if isinstance(exclude_from, list):
            # 리스트인 경우 각각 ne 조건으로 추가
            for addr in exclude_from:
                excludes.append(f"from/emailAddress/address ne '{addr}'")
        else:
            # 단일 문자열
            excludes.append(f"from/emailAddress/address ne '{exclude_from}'")

    if params_dict.get("exclude_sender_address"):
        exclude_sender = params_dict["exclude_sender_address"]
        if isinstance(exclude_sender, list):
            # 리스트인 경우 각각 ne 조건으로 추가
            for addr in exclude_sender:
                excludes.append(f"sender/emailAddress/address ne '{addr}'")
        else:
            # 단일 문자열
            excludes.append(f"sender/emailAddress/address ne '{exclude_sender}'")

    # 키워드 제외
    if params_dict.get("exclude_subject_keywords"):
        for keyword in params_dict["exclude_subject_keywords"]:
            excludes.append(f"not contains(subject, '{keyword}')")
    if params_dict.get("exclude_body_keywords"):
        for keyword in params_dict["exclude_body_keywords"]:
            excludes.append(f"not contains(body/content, '{keyword}')")
    if params_dict.get("exclude_preview_keywords"):
        for keyword in params_dict["exclude_preview_keywords"]:
            excludes.append(f"not contains(bodyPreview, '{keyword}')")

    # 속성 제외
    if params_dict.get("exclude_importance"):
        excludes.append(f"importance ne '{params_dict['exclude_importance']}'")
    if params_dict.get("exclude_sensitivity"):
        excludes.append(f"sensitivity ne '{params_dict['exclude_sensitivity']}'")
    if params_dict.get("exclude_classification"):
        excludes.append(f"inferenceClassification ne '{params_dict['exclude_classification']}'")

    # 상태 제외
    if params_dict.get("exclude_read_status") is not None:
        excludes.append(f"isRead ne {str(params_dict['exclude_read_status']).lower()}")
    if params_dict.get("exclude_draft_status") is not None:
        excludes.append(f"isDraft ne {str(params_dict['exclude_draft_status']).lower()}")
    if params_dict.get("exclude_attachment_status") is not None:
        excludes.append(f"hasAttachments ne {str(params_dict['exclude_attachment_status']).lower()}")

    # 플래그 제외
    if params_dict.get("exclude_flag_status"):
        excludes.append(f"flag/flagStatus ne '{params_dict['exclude_flag_status']}'")

    # 카테고리 제외
    if params_dict.get("exclude_categories"):
        for category in params_dict["exclude_categories"]:
            excludes.append(f"not categories/any(c:c eq '{category}')")

    # ID 제외
    if params_dict.get("exclude_id"):
        excludes.append(f"id ne '{params_dict['exclude_id']}'")
    if params_dict.get("exclude_conversation_id"):
        excludes.append(f"conversationId ne '{params_dict['exclude_conversation_id']}'")
    if params_dict.get("exclude_parent_folder_id"):
        excludes.append(f"parentFolderId ne '{params_dict['exclude_parent_folder_id']}'")

    return " and ".join(excludes)


def build_select_query(params: Union[SelectParams, Dict, List[str]]) -> str:
    """SelectParams를 Graph API $select 쿼리 문자열로 변환

    Args:
        params: SelectParams 객체, bool 플래그가 있는 dict, 또는 필드명 리스트

    Returns:
        $select 쿼리 문자열 (예: "id,subject,from,receivedDateTime")

    Examples:
        # SelectParams 객체
        build_select_query(SelectParams(id=True, subject=True))

        # Bool 플래그 dict - snake_case (권장)
        build_select_query({'id': True, 'subject': True, 'received_date_time': True})

        # Bool 플래그 dict - camelCase (Graph API 스타일)
        build_select_query({'id': True, 'subject': True, 'receivedDateTime': True})

        # 필드 리스트 (하위 호환성)
        build_select_query({'fields': ['id', 'subject']})
        build_select_query(['id', 'subject'])
    """
    # Pydantic 모델이면 get_selected_fields 사용
    if isinstance(params, SelectParams):
        selected_fields = params.get_selected_fields()
        return ",".join(selected_fields) if selected_fields else ""

    # 리스트인 경우 직접 반환
    if isinstance(params, list):
        return ",".join(params) if params else ""

    # Dict인 경우 필드 매핑 적용
    # snake_case -> camelCase 매핑
    field_mapping = {
        "id": "id",
        "created_date_time": "createdDateTime",
        "last_modified_date_time": "lastModifiedDateTime",
        "change_key": "changeKey",
        "categories": "categories",
        "received_date_time": "receivedDateTime",
        "sent_date_time": "sentDateTime",
        "has_attachments": "hasAttachments",
        "internet_message_id": "internetMessageId",
        "subject": "subject",
        "body_preview": "bodyPreview",
        "importance": "importance",
        "parent_folder_id": "parentFolderId",
        "conversation_id": "conversationId",
        "conversation_index": "conversationIndex",
        "is_delivery_receipt_requested": "isDeliveryReceiptRequested",
        "is_read_receipt_requested": "isReadReceiptRequested",
        "is_read": "isRead",
        "is_draft": "isDraft",
        "web_link": "webLink",
        "inference_classification": "inferenceClassification",
        "body": "body",
        "sender": "sender",
        "from_recipient": "from",
        "to_recipients": "toRecipients",
        "cc_recipients": "ccRecipients",
        "bcc_recipients": "bccRecipients",
        "reply_to": "replyTo",
        "flag": "flag",
        "unique_body": "uniqueBody",
        "internet_message_headers": "internetMessageHeaders",
    }

    # camelCase -> snake_case 역매핑 (camelCase 입력 지원용)
    camel_to_snake = {v: k for k, v in field_mapping.items()}
    # 'from'은 특수 케이스 (from_recipient과 매핑)
    camel_to_snake["from"] = "from_recipient"

    # 하위 호환성: {'fields': [...]} 형태 지원
    if "fields" in params and isinstance(params.get("fields"), list):
        fields_list = params["fields"]
        # Python 필드명을 API 필드명으로 변환 (필요시)
        converted = []
        for field in fields_list:
            if field in field_mapping:
                converted.append(field_mapping[field])
            else:
                # 이미 API 필드명이거나 알 수 없는 필드는 그대로 사용
                converted.append(field)
        return ",".join(converted) if converted else ""

    selected = []
    # snake_case 키 처리
    for python_field, api_field in field_mapping.items():
        if params.get(python_field) is True:
            selected.append(api_field)

    # camelCase 키 처리 (Graph API 스타일 입력 지원)
    for camel_key, snake_key in camel_to_snake.items():
        # 이미 snake_case로 처리되지 않은 경우만
        if camel_key not in field_mapping and params.get(camel_key) is True:
            # camelCase 키는 그대로 API 필드명
            if camel_key not in selected:
                selected.append(camel_key)

    return ",".join(selected) if selected else ""


def build_complete_query(query_params: Union[MailQueryParams, Dict]) -> str:
    """전체 쿼리 파라미터를 URL 쿼리 문자열로 변환"""
    query_parts = []

    # Pydantic 모델이면 dict로 변환
    if isinstance(query_params, MailQueryParams):
        params_dict = query_params.model_dump(exclude_none=True)
    else:
        params_dict = query_params

    # 필터 조합
    filter_parts = []
    if params_dict.get("filter"):
        filter_query = build_filter_query(params_dict["filter"])
        if filter_query:
            filter_parts.append(filter_query)

    if params_dict.get("exclude"):
        exclude_query = build_exclude_query(params_dict["exclude"])
        if exclude_query:
            filter_parts.append(exclude_query)

    if filter_parts:
        query_parts.append(f"$filter={' and '.join(filter_parts)}")

    # Select
    if params_dict.get("select"):
        select_query = build_select_query(params_dict["select"])
        if select_query:
            query_parts.append(f"$select={select_query}")

    # 기타 옵션
    if params_dict.get("top"):
        query_parts.append(f"$top={params_dict['top']}")
    if params_dict.get("skip"):
        query_parts.append(f"$skip={params_dict['skip']}")
    if params_dict.get("orderby"):
        query_parts.append(f"$orderby={params_dict['orderby']}")
    if params_dict.get("search"):
        query_parts.append(f"$search=\"{params_dict['search']}\"")
    if params_dict.get("count"):
        query_parts.append("$count=true")

    return "&".join(query_parts)


# 사용 예시
if __name__ == "__main__":
    # Pydantic 모델 예시 1: 기본 필터 파라미터
    filter_params = FilterParams(is_read=False, has_attachments=True, importance="high", subject="회의")

    # 모델 검증 확인
    print(f"Filter params: {filter_params.model_dump(exclude_none=True)}")

    # JSON Schema 출력 (API 문서화용)
    print(f"\nJSON Schema:\n{filter_params.model_json_schema()}")

    # 예시 2: 날짜 범위 필터 사용
    date_range_params = FilterParams(
        received_date_from="2024-10-01T00:00:00Z", received_date_to="2024-10-07T23:59:59Z", is_read=False
    )

    # 예시 3: 여러 발신자 조회
    multiple_senders_params = FilterParams(
        from_address=["boss@company.com", "manager@company.com", "ceo@company.com"],
        received_date_from="2024-12-01T00:00:00Z",
        is_read=False,
    )

    # 예시 4: 키워드 검색
    keywords_params = FilterParams(
        subject=["프로젝트", "회의", "미팅"], subject_operator="or", body_content=["승인", "결재"], body_operator="and"
    )

    # 제외 파라미터 설정
    exclude_params = ExcludeParams(
        exclude_from_address=["noreply@github.com", "notification@slack.com"],
        exclude_subject_keywords=["newsletter", "광고", "홍보"],
    )

    # 선택 필드 설정 (각 필드를 True로 지정)
    select_params = SelectParams(
        id=True, subject=True, from_recipient=True, received_date_time=True, has_attachments=True
    )
    print(f"\n선택된 필드: {select_params.get_selected_fields()}")

    # 전체 쿼리 파라미터
    query = MailQueryParams(
        filter=filter_params, exclude=exclude_params, select=select_params, top=50, orderby="receivedDateTime desc"
    )

    # 쿼리 문자열 생성
    query_string = build_complete_query(query)
    print(f"\nGenerated query: {query_string}")

    # 날짜 범위 필터 쿼리 생성
    date_range_query = build_filter_query(date_range_params)
    print(f"\n날짜 범위 필터: {date_range_query}")

    # 여러 발신자 필터 쿼리 생성
    multiple_senders_query = build_filter_query(multiple_senders_params)
    print(f"\n여러 발신자 필터: {multiple_senders_query}")

    # 제외 쿼리 생성
    exclude_query = build_exclude_query(exclude_params)
    print(f"\n제외 필터: {exclude_query}")

    # 키워드 필터
    keywords_query = build_filter_query(keywords_params)
    print(f"\n키워드 필터: {keywords_query}")

    # TypedDict 호환성 테스트
    print("\n=== TypedDict 호환성 테스트 ===")
    print(f"filter_params.get('is_read'): {filter_params.get('is_read')}")
    print(f"filter_params['has_attachments']: {filter_params['has_attachments']}")
    print(f"filter_params.keys(): {list(filter_params.keys())}")

    # 최종 URL 예시
    base_url = "https://graph.microsoft.com/v1.0/me/messages"
    full_url = f"{base_url}?{query_string}"
    print(f"\nFull URL: {full_url}")
    print(f"URL Length: {len(full_url)} characters")
