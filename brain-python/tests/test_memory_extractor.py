from __future__ import annotations

from typing import Any

import httpx
import pytest

from services import memory_extractor


class FakeStore:
    def __init__(self) -> None:
        self.messages = [
            {
                "id": 101,
                "conversation_id": 7,
                "sender_user_id": "100",
                "sender_nickname": "Alice",
                "sender_card": "A",
                "text": "以后别给我发长篇，我懒得看。",
                "created_at": None,
            },
            {
                "id": 102,
                "conversation_id": 7,
                "sender_user_id": "200",
                "sender_nickname": "Bob",
                "sender_card": "",
                "text": "这个群晚上别刷屏。",
                "created_at": None,
            },
        ]
        self.runs: list[dict[str, Any]] = []
        self.finished_runs: list[dict[str, Any]] = []
        self.upserts: list[dict[str, Any]] = []
        self.actions: list[str] = []

    def recent_group_messages_for_extraction(self, group_id: str, *, limit: int) -> list[dict[str, Any]]:
        self.group_id = group_id
        self.limit = limit
        return self.messages[:limit]

    def create_memory_run(
        self,
        *,
        group_id: str,
        conversation_id: int | None,
        input_message_ids: list[int],
        model: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        self.runs.append(
            {
                "group_id": group_id,
                "conversation_id": conversation_id,
                "input_message_ids": input_message_ids,
                "model": model,
                "metadata": metadata,
            }
        )
        return 12

    def finish_memory_run(
        self,
        run_id: int,
        *,
        status: str,
        output_memory_ids: list[int] | None = None,
        error: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.finished_runs.append(
            {
                "run_id": run_id,
                "status": status,
                "output_memory_ids": output_memory_ids,
                "error": error,
                "metadata": metadata,
            }
        )

    def upsert_extracted_memory(self, item: dict[str, Any]) -> tuple[int, str]:
        self.upserts.append(item)
        action = self.actions.pop(0) if self.actions else "inserted"
        return 900 + len(self.upserts), action


@pytest.fixture(autouse=True)
def clear_extractor_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "MEMORY_EXTRACTOR_ENABLED",
        "MEMORY_EXTRACTOR_BASE_URL",
        "MEMORY_EXTRACTOR_API_KEY",
        "MEMORY_EXTRACTOR_MODEL",
        "MEMORY_EXTRACTOR_TIMEOUT",
        "MEMORY_EXTRACTOR_BATCH_SIZE",
        "MEMORY_EXTRACTOR_MAX_CANDIDATES",
        "AI_BASE_URL",
        "AI_API_KEY",
        "AI_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_extractor_requires_enabled_flag() -> None:
    with pytest.raises(memory_extractor.MemoryExtractorConfigurationError) as exc:
        memory_extractor.extract_group_memories(FakeStore(), "200")

    assert "MEMORY_EXTRACTOR_ENABLED" in str(exc.value)


def test_extractor_validates_candidates_and_records_success(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeStore()
    store.actions = ["inserted", "updated"]
    calls: list[dict[str, Any]] = []
    _enable(monkeypatch)

    payload = {
        "memories": [
            {
                "scope": "user",
                "memory_type": "preference",
                "memory_class": "persona",
                "group_id": "200",
                "user_id": "100",
                "content": "Alice 不喜欢长篇回复。",
                "confidence": 0.8,
                "importance": 0.6,
                "evidence_message_ids": [101],
            },
            {
                "scope": "group",
                "memory_type": "style",
                "group_id": "200",
                "content": "这个群晚上不喜欢刷屏。",
                "confidence": 0.7,
                "importance": 0.5,
                "evidence_message_ids": [102],
            },
            {
                "scope": "group",
                "memory_type": "fact",
                "memory_class": "invalid",
                "group_id": "200",
                "content": "非法 class 不应写入。",
                "confidence": 0.7,
                "importance": 0.5,
                "evidence_message_ids": [101],
            },
            {
                "scope": "group",
                "memory_type": "fact",
                "group_id": "200",
                "content": "无证据。",
                "confidence": 0.7,
                "importance": 0.5,
                "evidence_message_ids": [],
            },
            {
                "scope": "global",
                "memory_type": "fact",
                "content": "不允许全局。",
                "confidence": 0.7,
                "importance": 0.5,
                "evidence_message_ids": [101],
            },
            {
                "scope": "user",
                "memory_type": "preference",
                "group_id": "999",
                "user_id": "100",
                "content": "跨群不应接受。",
                "confidence": 0.7,
                "importance": 0.5,
                "evidence_message_ids": [101],
            },
            {
                "scope": "relationship",
                "memory_type": "relationship",
                "group_id": "200",
                "user_id": "100",
                "target_user_id": "100",
                "content": "关系双方不能相同。",
                "confidence": 0.7,
                "importance": 0.5,
                "evidence_message_ids": [101],
            },
        ]
    }

    def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: float) -> FakeResponse:
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse({"choices": [{"message": {"content": memory_extractor.json.dumps(payload)}}]})

    monkeypatch.setattr(memory_extractor.httpx, "post", fake_post)

    result = memory_extractor.extract_group_memories(store, "200", limit=100)

    assert result.run_id == 12
    assert result.input_message_count == 2
    assert result.inserted_count == 1
    assert result.updated_count == 1
    assert result.skipped_count == 5
    assert result.memory_ids == [901, 902]
    assert store.limit == 100
    assert store.runs == [
        {
            "group_id": "200",
            "conversation_id": 7,
            "input_message_ids": [101, 102],
            "model": "memory-model",
            "metadata": {"batch_size": 100, "max_candidates": 12, "version": "memory-extractor-mvp"},
        }
    ]
    assert store.finished_runs[-1]["status"] == "succeeded"
    assert store.finished_runs[-1]["output_memory_ids"] == [901, 902]
    assert store.finished_runs[-1]["metadata"]["skipped"] == 5
    assert len(store.upserts) == 2
    assert store.upserts[0]["scope"] == "user"
    assert store.upserts[0]["group_id"] == "200"
    assert store.upserts[0]["target_user_id"] == ""
    assert store.upserts[0]["memory_class"] == "persona"
    assert store.upserts[0]["metadata"]["raw_candidate"] == payload["memories"][0]
    assert store.upserts[1]["scope"] == "group"
    assert store.upserts[1]["user_id"] == ""
    assert store.upserts[1]["memory_class"] == "procedural"
    assert calls[0]["url"] == "https://llm.example/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer secret"
    assert calls[0]["timeout"] == 30.0
    assert calls[0]["json"]["response_format"] == {"type": "json_object"}
    assert "memory_class" in calls[0]["json"]["messages"][1]["content"]


def test_extractor_falls_back_to_ai_config_and_env_batch_size(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeStore()
    monkeypatch.setenv("MEMORY_EXTRACTOR_ENABLED", "true")
    monkeypatch.setenv("AI_BASE_URL", "https://ai.example")
    monkeypatch.setenv("AI_API_KEY", "ai-secret")
    monkeypatch.setenv("AI_MODEL", "ai-model")
    monkeypatch.setenv("MEMORY_EXTRACTOR_BATCH_SIZE", "30")

    def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: float) -> FakeResponse:
        assert url == "https://ai.example/v1/chat/completions"
        assert headers["Authorization"] == "Bearer ai-secret"
        assert json["model"] == "ai-model"
        return FakeResponse({"choices": [{"message": {"content": "{\"memories\": []}"}}]})

    monkeypatch.setattr(memory_extractor.httpx, "post", fake_post)

    result = memory_extractor.extract_group_memories(store, "200")

    assert result.inserted_count == 0
    assert store.limit == 30


def test_extractor_reports_no_messages_after_config(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeStore()
    store.messages = []
    _enable(monkeypatch)

    with pytest.raises(memory_extractor.MemoryExtractorNoMessagesError):
        memory_extractor.extract_group_memories(store, "200")

    assert store.runs == []


def test_extractor_marks_run_failed_on_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeStore()
    _enable(monkeypatch)
    monkeypatch.setattr(
        memory_extractor.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse({"choices": [{"message": {"content": "not json"}}]}),
    )

    with pytest.raises(memory_extractor.MemoryExtractorUpstreamError):
        memory_extractor.extract_group_memories(store, "200")

    assert store.finished_runs[-1]["status"] == "failed"
    assert store.finished_runs[-1]["run_id"] == 12
    assert store.finished_runs[-1]["error"]
    assert store.finished_runs[-1]["metadata"]["error_type"] == "MemoryExtractorUpstreamError"


def test_extractor_marks_run_failed_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeStore()
    _enable(monkeypatch)
    monkeypatch.setattr(memory_extractor.httpx, "post", lambda *args, **kwargs: FakeResponse({}, status_code=500))

    with pytest.raises(memory_extractor.MemoryExtractorUpstreamError):
        memory_extractor.extract_group_memories(store, "200")

    assert store.finished_runs[-1]["status"] == "failed"


def test_validate_candidates_rejects_missing_and_cross_batch_evidence() -> None:
    messages = [{"id": 1, "sender_user_id": "100"}, {"id": 2, "sender_user_id": "200"}]
    candidates = [
        {
            "scope": "user",
            "memory_type": "preference",
            "group_id": "g",
            "user_id": "999",
            "content": "未知用户。",
            "confidence": 0.5,
            "importance": 0.5,
            "evidence_message_ids": [1],
        },
        {
            "scope": "group",
            "memory_type": "fact",
            "group_id": "g",
            "content": "证据不在本批。",
            "confidence": 0.5,
            "importance": 0.5,
            "evidence_message_ids": [99],
        },
        {
            "scope": "relationship",
            "memory_type": "relationship",
            "group_id": "g",
            "user_id": "100",
            "target_user_id": "200",
            "content": "Alice 和 Bob 经常一起讨论测试。",
            "confidence": 0.5,
            "importance": 0.5,
            "evidence_message_ids": [1, 2],
        },
    ]

    accepted, skipped = memory_extractor._validate_candidates(candidates, "g", messages, 12)

    assert skipped == 2
    assert len(accepted) == 1
    assert accepted[0]["scope"] == "relationship"


def test_validate_candidates_rejects_invalid_memory_class() -> None:
    messages = [{"id": 1, "sender_user_id": "100"}]
    candidates = [
        {
            "scope": "user",
            "memory_type": "preference",
            "memory_class": "unknown",
            "group_id": "g",
            "user_id": "100",
            "content": "Alice 不喜欢长篇回复。",
            "confidence": 0.5,
            "importance": 0.5,
            "evidence_message_ids": [1],
        }
    ]

    accepted, skipped = memory_extractor._validate_candidates(candidates, "g", messages, 12)

    assert accepted == []
    assert skipped == 1


def test_validate_candidates_preserves_conflict_metadata() -> None:
    messages = [{"id": 1, "sender_user_id": "100"}]
    candidate = {
        "scope": "user",
        "memory_type": "preference",
        "memory_class": "affective",
        "group_id": "g",
        "user_id": "100",
        "content": "Alice 现在愿意接收详细解释。",
        "confidence": 0.6,
        "importance": 0.8,
        "evidence_message_ids": [1],
        "conflicts_with_memory_id": "42",
        "conflicts_with": {"content": "Alice 不喜欢长篇回复。"},
    }

    accepted, skipped = memory_extractor._validate_candidates([candidate], "g", messages, 12)

    assert skipped == 0
    assert len(accepted) == 1
    assert accepted[0]["memory_class"] == "affective"
    assert accepted[0]["metadata"] == {
        "raw_candidate": candidate,
        "conflicts_with_memory_id": 42,
        "conflicts_with": {"content": "Alice 不喜欢长篇回复。"},
    }


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_EXTRACTOR_ENABLED", "true")
    monkeypatch.setenv("MEMORY_EXTRACTOR_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("MEMORY_EXTRACTOR_API_KEY", "secret")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MODEL", "memory-model")


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "bad status",
                request=httpx.Request("POST", "https://llm.example"),
                response=httpx.Response(self.status_code),
            )
