from fastapi import FastAPI

from schemas import (
    BrainResponse,
    ChatRequest,
    HealthResponse,
    ToolCallRequest,
    ToolDefinition,
    ToolResult,
)
from services.chat import build_chat_response
from services.tools import call_tool, list_tools

app = FastAPI(title="TestBot Python Brain")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/chat", response_model=BrainResponse, response_model_exclude_none=True, response_model_exclude_defaults=True)
def chat(request: ChatRequest) -> BrainResponse:
    return build_chat_response(request)


@app.get("/tools", response_model=list[ToolDefinition])
def tools() -> list[ToolDefinition]:
    return list_tools()


@app.post("/tools/call", response_model=ToolResult, response_model_exclude_none=True, response_model_exclude_defaults=True)
def tools_call(request: ToolCallRequest) -> ToolResult:
    return call_tool(request)
