ALTER TABLE memory_embeddings
    ADD COLUMN content_hash TEXT NOT NULL DEFAULT '',
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

DELETE FROM memory_embeddings
WHERE id IN (
    SELECT id
    FROM (
        SELECT
            id,
            row_number() OVER (
                PARTITION BY memory_id, embedding_model
                ORDER BY updated_at DESC, created_at DESC, id DESC
            ) AS duplicate_rank
        FROM memory_embeddings
    ) ranked
    WHERE duplicate_rank > 1
);

CREATE UNIQUE INDEX memory_embeddings_memory_model_unique_idx
    ON memory_embeddings (memory_id, embedding_model);

CREATE INDEX memory_embeddings_embedding_ivfflat_idx
    ON memory_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
