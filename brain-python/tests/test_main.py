from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_replies_to_text() -> None:
    response = client.post("/chat", json={"text": "hello"})

    assert response.status_code == 200
    assert response.json() == {"reply": "收到：hello", "should_reply": True}


def test_chat_does_not_reply_to_empty_text() -> None:
    response = client.post("/chat", json={"text": "   "})

    assert response.status_code == 200
    assert response.json() == {"reply": "", "should_reply": False}
