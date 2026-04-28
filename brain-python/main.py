import logging
import hmac
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, status

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
    OutboxEnqueueRequest,
    OutboxFailRequest,
    OutboxItem,
    OutboxPullRequest,
    OutboxPullResponse,
    ToolCallRequest,
    ToolDefinition,
    ToolResult,
)
from services.chat import build_chat_response
from services.outbox import (
    OutboxConfigurationError,
    OutboxError,
    OutboxNotFoundError,
    OutboxValidationError,
    PostgresOutboxStore,
)
from services.tools import call_tool, list_tools


class QuietAccessLogFilter(logging.Filter):
    _QUIET_SUCCESSFUL_ROUTES = {
        ("GET", "/health"),
        ("POST", "/chat"),
        ("POST", "/outbox/pull"),
    }

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 5:
            method = record.args[1]
            path = record.args[2]
            status_code = record.args[4]
            try:
                status = int(status_code)
            except (TypeError, ValueError):
                status = 0
            if (method, path) in self._QUIET_SUCCESSFUL_ROUTES and 200 <= status < 400:
                return False
        return True


logging.getLogger("uvicorn.access").addFilter(QuietAccessLogFilter())

app = FastAPI(title="TestBot Python Brain")
outbox_store = PostgresOutboxStore.from_env()


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


def require_outbox_token(
    authorization: str | None = Header(default=None),
    x_outbox_token: str | None = Header(default=None),
) -> None:
    expected = os.getenv("OUTBOX_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OUTBOX_TOKEN is not configured")

    provided = _bearer_token(authorization) or (x_outbox_token or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid outbox token")


def _bearer_token(authorization: str | None) -> str:
    if authorization is None:
        return ""
    scheme, separator, token = authorization.strip().partition(" ")
    if not separator or scheme.lower() != "bearer":
        return ""
    return token.strip()


@app.post("/outbox/enqueue", response_model=OutboxItem)
def outbox_enqueue(request: OutboxEnqueueRequest, _: None = Depends(require_outbox_token)) -> OutboxItem:
    try:
        return outbox_store.enqueue(request)
    except OutboxValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except OutboxConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except OutboxError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@app.post("/outbox/pull", response_model=OutboxPullResponse)
def outbox_pull(request: OutboxPullRequest, _: None = Depends(require_outbox_token)) -> OutboxPullResponse:
    try:
        return OutboxPullResponse(items=outbox_store.pull(request.limit, request.lease_seconds))
    except OutboxConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except OutboxError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@app.post("/outbox/{item_id}/ack", response_model=OutboxItem)
def outbox_ack(item_id: int, _: None = Depends(require_outbox_token)) -> OutboxItem:
    try:
        return outbox_store.ack(item_id)
    except OutboxNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except OutboxConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except OutboxError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@app.post("/outbox/{item_id}/fail", response_model=OutboxItem)
def outbox_fail(item_id: int, request: OutboxFailRequest, _: None = Depends(require_outbox_token)) -> OutboxItem:
    try:
        return outbox_store.fail(item_id, request.error)
    except OutboxNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except OutboxConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except OutboxError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
