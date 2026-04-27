from fastapi import FastAPI, HTTPException

from schemas import (
    BrainResponse,
    ChatRequest,
    HealthResponse,
    OutboxAckRequest,
    OutboxAckResponse,
    OutboxPullItem,
    ToolCallRequest,
    ToolDefinition,
    ToolResult,
)
from services.chat import build_chat_response
from services.outbox import ack as ack_outbox
from services.outbox import pull as pull_outbox
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


@app.get("/outbox/pull", response_model=list[OutboxPullItem])
def outbox_pull(limit: int = 10) -> list[dict[str, object]]:
    return pull_outbox(limit=limit)


@app.post("/outbox/ack", response_model=OutboxAckResponse)
def outbox_ack(request: OutboxAckRequest) -> OutboxAckResponse:
    acked = ack_outbox(ids=request.ids, success=request.success, error=request.error)
    if request.ids and acked != len(request.ids):
        raise HTTPException(
            status_code=503,
            detail={
                "error": "outbox_ack_incomplete",
                "acked": acked,
                "expected": len(request.ids),
            },
        )
    return OutboxAckResponse(acked=acked)
