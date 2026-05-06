import hashlib
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from services.memory import MemoryError


logger = logging.getLogger(__name__)

DEFAULT_DIMENSIONS = 1536
DEFAULT_TIMEOUT = 20.0
DEFAULT_BATCH_SIZE = 32


class MemoryEmbeddingError(MemoryError):
    pass


class MemoryEmbeddingConfigurationError(MemoryEmbeddingError):
    pass


class MemoryEmbeddingUpstreamError(MemoryEmbeddingError):
    pass


@dataclass(frozen=True)
class EmbeddingConfig:
    enabled: bool
    base_url: str
    api_key: str
    model: str
    dimensions: int = DEFAULT_DIMENSIONS
    timeout: float = DEFAULT_TIMEOUT
    batch_size: int = DEFAULT_BATCH_SIZE


def config_from_env() -> EmbeddingConfig:
    enabled = _env_bool("MEMORY_EMBEDDING_ENABLED", False)
    config = EmbeddingConfig(
        enabled=enabled,
        base_url=os.getenv("MEMORY_EMBEDDING_BASE_URL", "").strip().rstrip("/"),
        api_key=os.getenv("MEMORY_EMBEDDING_API_KEY", "").strip(),
        model=os.getenv("MEMORY_EMBEDDING_MODEL", "").strip(),
        dimensions=_env_int("MEMORY_EMBEDDING_DIMENSIONS", DEFAULT_DIMENSIONS),
        timeout=_env_float("MEMORY_EMBEDDING_TIMEOUT", DEFAULT_TIMEOUT),
        batch_size=_env_int("MEMORY_EMBEDDING_BATCH_SIZE", DEFAULT_BATCH_SIZE),
    )
    if not config.enabled:
        return config

    missing = []
    if not config.base_url:
        missing.append("MEMORY_EMBEDDING_BASE_URL")
    if not config.model:
        missing.append("MEMORY_EMBEDDING_MODEL")
    if missing:
        raise MemoryEmbeddingConfigurationError("missing " + ", ".join(missing))

    return config


def embed_texts(texts: list[str], config: EmbeddingConfig) -> list[list[float]]:
    if not config.enabled:
        raise MemoryEmbeddingConfigurationError("MEMORY_EMBEDDING_ENABLED is false")
    if not config.base_url or not config.model:
        raise MemoryEmbeddingConfigurationError("embedding config is incomplete")
    if not texts:
        return []

    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    payload = {
        "model": config.model,
        "input": texts,
    }

    try:
        response = httpx.post(
            embeddings_url(config.base_url),
            json=payload,
            headers=headers,
            timeout=config.timeout,
        )
        response.raise_for_status()
        parsed = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise MemoryEmbeddingUpstreamError(str(exc)) from exc

    return _extract_embeddings(parsed, expected_count=len(texts), dimensions=config.dimensions)


def embeddings_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/v1/embeddings"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/embeddings"
    return f"{normalized}/v1/embeddings"


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _extract_embeddings(payload: Any, *, expected_count: int, dimensions: int) -> list[list[float]]:
    if not isinstance(payload, dict):
        raise MemoryEmbeddingUpstreamError("embedding response must be an object")

    data = payload.get("data")
    if not isinstance(data, list):
        raise MemoryEmbeddingUpstreamError("embedding response must contain a data array")
    if len(data) != expected_count:
        raise MemoryEmbeddingUpstreamError("embedding response count does not match input count")

    embeddings: list[list[float]] = []
    for item in data:
        if not isinstance(item, dict):
            raise MemoryEmbeddingUpstreamError("embedding response items must be objects")
        embedding = item.get("embedding")
        if not isinstance(embedding, list):
            raise MemoryEmbeddingUpstreamError("embedding response items must contain embedding arrays")
        if len(embedding) != dimensions:
            raise MemoryEmbeddingUpstreamError("embedding dimension does not match configuration")

        values: list[float] = []
        for value in embedding:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise MemoryEmbeddingUpstreamError("embedding values must be numbers")
            values.append(float(value))
        embeddings.append(values)

    return embeddings


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("invalid %s=%r; using default %s", key, raw, default)
        return default
    return value if value > 0 else default


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("invalid %s=%r; using default %s", key, raw, default)
        return default
    return value if value > 0 else default
