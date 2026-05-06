from __future__ import annotations

from typing import Any

import httpx
import pytest

from services import memory_embedding


@pytest.fixture(autouse=True)
def clear_embedding_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "MEMORY_EMBEDDING_ENABLED",
        "MEMORY_EMBEDDING_BASE_URL",
        "MEMORY_EMBEDDING_API_KEY",
        "MEMORY_EMBEDDING_MODEL",
        "MEMORY_EMBEDDING_DIMENSIONS",
        "MEMORY_EMBEDDING_TIMEOUT",
        "MEMORY_EMBEDDING_BATCH_SIZE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_config_defaults_to_disabled_without_required_values() -> None:
    config = memory_embedding.config_from_env()

    assert config.enabled is False
    assert config.base_url == ""
    assert config.api_key == ""
    assert config.model == ""
    assert config.dimensions == 1536
    assert config.timeout == 20.0
    assert config.batch_size == 32


def test_enabled_config_requires_base_url_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("MEMORY_EMBEDDING_BASE_URL", "https://embeddings.example")

    with pytest.raises(memory_embedding.MemoryEmbeddingConfigurationError) as exc:
        memory_embedding.config_from_env()

    message = str(exc.value)
    assert "MEMORY_EMBEDDING_MODEL" in message


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://embeddings.example", "https://embeddings.example/v1/embeddings"),
        ("https://embeddings.example/", "https://embeddings.example/v1/embeddings"),
        ("https://embeddings.example/v1", "https://embeddings.example/v1/embeddings"),
        ("https://embeddings.example/v1/", "https://embeddings.example/v1/embeddings"),
        ("https://embeddings.example/v1/embeddings", "https://embeddings.example/v1/embeddings"),
    ],
)
def test_embeddings_url_normalization(base_url: str, expected: str) -> None:
    assert memory_embedding.embeddings_url(base_url) == expected


def test_embed_texts_posts_openai_compatible_request(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    config = memory_embedding.EmbeddingConfig(
        enabled=True,
        base_url="https://embeddings.example/v1",
        api_key="secret",
        model="embedding-model",
        dimensions=3,
        timeout=7.5,
        batch_size=2,
    )

    def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: float) -> FakeResponse:
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse({"data": [{"embedding": [0.1, 2, -0.3]}, {"embedding": [0, 0.4, 0.5]}]})

    monkeypatch.setattr(memory_embedding.httpx, "post", fake_post)

    embeddings = memory_embedding.embed_texts(["first", "second"], config)

    assert embeddings == [[0.1, 2.0, -0.3], [0.0, 0.4, 0.5]]
    assert calls == [
        {
            "url": "https://embeddings.example/v1/embeddings",
            "json": {"model": "embedding-model", "input": ["first", "second"]},
            "headers": {"Authorization": "Bearer secret", "Content-Type": "application/json"},
            "timeout": 7.5,
        }
    ]


def test_embed_texts_omits_authorization_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    config = memory_embedding.EmbeddingConfig(
        enabled=True,
        base_url="https://embeddings.example",
        api_key="",
        model="embedding-model",
        dimensions=2,
    )

    def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: float) -> FakeResponse:
        calls.append({"headers": headers})
        return FakeResponse({"data": [{"embedding": [0.1, 0.2]}]})

    monkeypatch.setattr(memory_embedding.httpx, "post", fake_post)

    assert memory_embedding.embed_texts(["first"], config) == [[0.1, 0.2]]
    assert calls == [{"headers": {"Content-Type": "application/json"}}]


def test_embed_texts_rejects_invalid_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _enabled_config(dimensions=2)
    monkeypatch.setattr(memory_embedding.httpx, "post", lambda *args, **kwargs: FakeResponse({"data": [{}]}))

    with pytest.raises(memory_embedding.MemoryEmbeddingUpstreamError) as exc:
        memory_embedding.embed_texts(["hello"], config)

    assert "embedding arrays" in str(exc.value)


def test_embed_texts_rejects_dimension_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _enabled_config(dimensions=3)
    monkeypatch.setattr(
        memory_embedding.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse({"data": [{"embedding": [0.1, 0.2]}]}),
    )

    with pytest.raises(memory_embedding.MemoryEmbeddingUpstreamError) as exc:
        memory_embedding.embed_texts(["hello"], config)

    assert "dimension" in str(exc.value)


def test_content_hash_is_stable_and_content_sensitive() -> None:
    first = memory_embedding.content_hash("用户不喜欢长篇回复。")
    second = memory_embedding.content_hash("用户不喜欢长篇回复。")
    different = memory_embedding.content_hash("用户喜欢长篇回复。")

    assert first == second
    assert first != different
    assert len(first) == 64


def _enabled_config(*, dimensions: int) -> memory_embedding.EmbeddingConfig:
    return memory_embedding.EmbeddingConfig(
        enabled=True,
        base_url="https://embeddings.example",
        api_key="secret",
        model="embedding-model",
        dimensions=dimensions,
    )


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "bad status",
                request=httpx.Request("POST", "https://embeddings.example/v1/embeddings"),
                response=httpx.Response(self.status_code),
            )
