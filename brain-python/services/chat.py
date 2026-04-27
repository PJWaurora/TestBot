from schemas import BrainMessage, BrainResponse, ChatRequest, ToolCall, ToolCallRequest
from services.tools import call_tool


def build_chat_response(request: ChatRequest) -> BrainResponse:
    text = _request_text(request)
    if not text:
        return BrainResponse(handled=False, should_reply=False)

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
