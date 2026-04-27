import logging
from typing import cast

from schemas import BrainMessage, BrainResponse, ChatRequest, ToolCall, ToolCallRequest
from modules.registry import default_registry
from services.persistence import ChatPersistenceRepository, get_default_repository
from services.tools import call_tool


logger = logging.getLogger(__name__)
_DEFAULT_REPOSITORY = object()
_repository_override: ChatPersistenceRepository | None | object = _DEFAULT_REPOSITORY


def set_chat_repository(repository: ChatPersistenceRepository | None) -> None:
    global _repository_override
    _repository_override = repository


def reset_chat_repository() -> None:
    global _repository_override
    _repository_override = _DEFAULT_REPOSITORY


def build_chat_response(request: ChatRequest) -> BrainResponse:
    repository = _chat_repository()
    message_id = _save_request(repository, request)
    response = _build_chat_response(request)
    _save_response(repository, message_id, response)
    return response


def _build_chat_response(request: ChatRequest) -> BrainResponse:
    text = _request_text(request)
    if not text:
        return BrainResponse(handled=False, should_reply=False)

    module_response = default_registry.handle(text, context=request)
    if module_response is not None:
        return module_response

    tool_request = _plan_tool_call(text)
    if tool_request is not None:
        result = call_tool(tool_request)
        reply = str(result.data.get("text", "")) if result.ok else ""
        return BrainResponse(
            handled=True,
            reply=reply,
            should_reply=bool(reply),
            messages=[BrainMessage(type="text", text=reply)] if reply else [],
            tool_calls=[ToolCall(name=tool_request.name, arguments=tool_request.arguments)],
            metadata={"planner": "fake"},
        )

    reply = f"收到：{text}"
    return BrainResponse(
        handled=True,
        reply=reply,
        should_reply=True,
        messages=[BrainMessage(type="text", text=reply)],
    )


def _request_text(request: ChatRequest) -> str:
    candidates = [request.text, request.content]
    if request.message is not None:
        candidates.append(_message_text(request.message))
    candidates.extend(_message_text(message) for message in request.messages)

    for candidate in reversed(candidates):
        text = candidate.strip()
        if text:
            return text
    return ""


def _message_text(message: BrainMessage) -> str:
    return message.text or message.content


def _plan_tool_call(text: str) -> ToolCallRequest | None:
    command, _, argument = text.partition(" ")
    if command.lower() != "/echo":
        return None

    return ToolCallRequest(name="echo", arguments={"text": argument.strip()})


def _chat_repository() -> ChatPersistenceRepository | None:
    if _repository_override is _DEFAULT_REPOSITORY:
        return get_default_repository()
    return cast(ChatPersistenceRepository | None, _repository_override)


def _save_request(
    repository: ChatPersistenceRepository | None,
    request: ChatRequest,
) -> int | None:
    if repository is None:
        return None
    try:
        return repository.save_request(request)
    except Exception:
        logger.exception("chat request persistence failed")
        return None


def _save_response(
    repository: ChatPersistenceRepository | None,
    message_id: int | None,
    response: BrainResponse,
) -> None:
    if repository is None or message_id is None:
        return
    try:
        repository.save_response(message_id, response)
    except Exception:
        logger.exception("chat response persistence failed")
