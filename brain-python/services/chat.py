from schemas import BrainMessage, BrainResponse, ChatRequest, ToolCall, ToolCallRequest
from modules.base import ModuleContext
from modules.registry import default_registry
from services.tools import call_tool


def build_chat_response(request: ChatRequest) -> BrainResponse:
    text, context = _request_text_and_context(request)
    if not text:
        return BrainResponse(handled=False, should_reply=False)

    module_response = default_registry.handle(text, context)
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

    return BrainResponse(handled=False, should_reply=False, metadata={"reason": "no_route"})


def _request_text_and_context(request: ChatRequest) -> tuple[str, ModuleContext]:
    top_level_context = _top_level_context(request)
    candidates: list[tuple[str, ModuleContext]] = [
        (request.text, top_level_context),
        (request.content, top_level_context),
    ]
    if request.message is not None:
        candidates.append((_message_text(request.message), _message_context(request.message, top_level_context)))
    candidates.extend((_message_text(message), _message_context(message, top_level_context)) for message in request.messages)

    for candidate, context in reversed(candidates):
        text = candidate.strip()
        if text:
            return text, context
    return "", top_level_context


def _message_text(message: BrainMessage) -> str:
    return message.text or message.content


def _top_level_context(request: ChatRequest) -> ModuleContext:
    return ModuleContext(
        group_id=_string_id(request.group_id),
        user_id=_string_id(request.user_id),
        message_type=request.message_type or "",
    )


def _message_context(message: BrainMessage, fallback: ModuleContext) -> ModuleContext:
    return ModuleContext(
        group_id=_string_id(message.group_id) or fallback.group_id,
        user_id=_string_id(message.user_id) or fallback.user_id,
        message_type=message.message_type or fallback.message_type,
    )


def _string_id(value: str | int | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _plan_tool_call(text: str) -> ToolCallRequest | None:
    command, _, argument = text.partition(" ")
    if command.lower() != "/echo":
        return None

    return ToolCallRequest(name="echo", arguments={"text": argument.strip()})
