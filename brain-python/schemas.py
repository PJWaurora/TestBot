from typing import Any

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
    user_id: str | int | None = None
    group_id: str | int | None = None
    conversation_id: str | None = None
    message_id: str | int | None = None
    message_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    text: str = ""
    content: str = ""
    message: BrainMessage | None = None
    messages: list[BrainMessage] = Field(default_factory=list)
    user_id: str | int | None = None
    group_id: str | int | None = None
    conversation_id: str | None = None
    message_id: str | int | None = None
    message_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BrainResponse):
    pass


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
