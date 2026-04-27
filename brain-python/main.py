import logging
from pathlib import Path

from fastapi import FastAPI

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - local env loading is optional in tests.
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(Path(__file__).with_name(".env"))

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


class HealthAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 5:
            method = record.args[1]
            path = record.args[2]
            status_code = record.args[4]
            try:
                status = int(status_code)
            except (TypeError, ValueError):
                status = 0
            if method == "GET" and path == "/health" and 200 <= status < 400:
                return False
        return True


logging.getLogger("uvicorn.access").addFilter(HealthAccessLogFilter())

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
