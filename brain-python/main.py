from fastapi import FastAPI

from schemas import ChatRequest, ChatResponse, HealthResponse
from services.chat import build_chat_response

app = FastAPI(title="TestBot Python Brain")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    return build_chat_response(request)
