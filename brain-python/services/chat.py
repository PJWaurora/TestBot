from schemas import ChatRequest, ChatResponse


def build_chat_response(request: ChatRequest) -> ChatResponse:
    text = request.text.strip()
    if not text:
        return ChatResponse(reply="", should_reply=False)

    return ChatResponse(reply=f"收到：{text}", should_reply=True)
