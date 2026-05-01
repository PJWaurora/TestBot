from typing import Any
from datetime import datetime

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str


class BrainMessage(BaseModel):
    role: str = "user"
    type: str = ""
    text: str = ""
    content: str = ""
    file: str = ""
    url: str = ""
    path: str = ""
    name: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    user_id: str | int | None = None
    group_id: str | int | None = None
    conversation_id: str | None = None
    message_id: str | int | None = None
    message_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BrainJSONMessage(BaseModel):
    raw: str = ""
    parsed: dict[str, Any] = Field(default_factory=dict)


class BrainSender(BaseModel):
    user_id: str | int | None = None
    nickname: str = ""
    card: str = ""
    role: str = ""


class BrainImage(BaseModel):
    url: str = ""
    file: str = ""
    summary: str = ""
    sub_type: str = ""
    file_size: str = ""


class BrainVideo(BaseModel):
    url: str = ""
    file: str = ""


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    tool_name: str
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ToolCall(BaseModel):
    id: str | None = None
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class BrainResponse(BaseModel):
    handled: bool
    should_reply: bool
    messages: list[BrainMessage] = Field(default_factory=list)
    reply: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    job_id: str | None = None
    metadata: dict[str, Any] | None = None


class ChatRequest(BaseModel):
    self_id: str | int | None = None
    post_type: str | None = None
    sub_type: str | None = None
    primary_type: str | None = None
    text: str = ""
    content: str = ""
    message: BrainMessage | None = None
    messages: list[BrainMessage] = Field(default_factory=list)
    text_segments: list[str] = Field(default_factory=list)
    json_messages: list[BrainJSONMessage] = Field(default_factory=list)
    images: list[BrainImage] = Field(default_factory=list)
    videos: list[BrainVideo] = Field(default_factory=list)
    at_user_ids: list[str | int] = Field(default_factory=list)
    at_all: bool = False
    reply_to_message_id: str | int | None = None
    unknown_types: list[str] = Field(default_factory=list)
    segments: list[dict[str, Any]] = Field(default_factory=list)
    user_id: str | int | None = None
    group_id: str | int | None = None
    group_name: str = ""
    target_id: str | int | None = None
    sender: BrainSender | None = None
    conversation_id: str | None = None
    message_id: str | int | None = None
    message_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BrainResponse):
    pass


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    message_type: str | None = None
    group_id: str | int | None = None
    user_id: str | int | None = None


class OutboxEnqueueRequest(BaseModel):
    message_type: str
    user_id: str | int | None = None
    group_id: str | int | None = None
    messages: list[BrainMessage] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=5, ge=1, le=100)


class OutboxPullRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=100)
    lease_seconds: int = Field(default=30, ge=1, le=3600)


class OutboxFailRequest(BaseModel):
    error: str = ""


class OutboxItem(BaseModel):
    id: int
    message_type: str
    user_id: str | None = None
    group_id: str | None = None
    messages: list[BrainMessage] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str
    attempts: int
    max_attempts: int
    last_error: str | None = None
    next_attempt_at: datetime | None = None
    locked_until: datetime | None = None
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None = None
    failed_at: datetime | None = None


class OutboxPullResponse(BaseModel):
    items: list[OutboxItem] = Field(default_factory=list)
