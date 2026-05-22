"""
Microsoft Graph To Do (Tasks) API 타입 정의
Pydantic 모델로 todoTaskList / todoTask 표현
"""

from typing import Optional, List, Literal, Any
from pydantic import BaseModel, Field, ConfigDict


# Graph API의 task status / importance enum
TaskStatus = Literal[
    "notStarted",
    "inProgress",
    "completed",
    "waitingOnOthers",
    "deferred",
]

TaskImportance = Literal["low", "normal", "high"]
BodyContentType = Literal["text", "html"]


class DateTimeTimeZone(BaseModel):
    """Graph API dateTimeTimeZone 타입."""

    model_config = ConfigDict(extra="ignore")

    dateTime: str = Field(
        ...,
        description="날짜와 시간 (ISO 8601, 예: 2024-12-01T09:00:00)",
    )
    timeZone: str = Field(
        default="Korea Standard Time",
        description="시간대 (IANA 또는 Windows 시간대)",
    )


class ItemBody(BaseModel):
    """Graph API itemBody 타입 (task body)."""

    model_config = ConfigDict(extra="ignore")

    content: str = Field(default="", description="본문 내용")
    contentType: BodyContentType = Field(
        default="text", description="본문 형식 (text|html)"
    )


class TaskListCreateParams(BaseModel):
    """todoTaskList 생성 파라미터."""

    model_config = ConfigDict(extra="ignore")

    displayName: str = Field(..., description="태스크 리스트 표시 이름")


class TaskCreateParams(BaseModel):
    """todoTask 생성 파라미터."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(..., description="태스크 제목")
    body: Optional[ItemBody] = Field(None, description="본문")
    importance: Optional[TaskImportance] = Field(None, description="중요도")
    status: Optional[TaskStatus] = Field(None, description="상태")
    dueDateTime: Optional[DateTimeTimeZone] = Field(None, description="마감일시")
    reminderDateTime: Optional[DateTimeTimeZone] = Field(None, description="알림일시")
    isReminderOn: Optional[bool] = Field(None, description="알림 사용 여부")
    categories: Optional[List[str]] = Field(None, description="카테고리")


class TaskUpdateParams(BaseModel):
    """todoTask 수정 파라미터 (None인 필드는 무시)."""

    model_config = ConfigDict(extra="ignore")

    title: Optional[str] = None
    body: Optional[ItemBody] = None
    importance: Optional[TaskImportance] = None
    status: Optional[TaskStatus] = None
    dueDateTime: Optional[DateTimeTimeZone] = None
    reminderDateTime: Optional[DateTimeTimeZone] = None
    isReminderOn: Optional[bool] = None
    categories: Optional[List[str]] = None
