DROP INDEX IF EXISTS memory_embeddings_embedding_ivfflat_idx;
DROP INDEX IF EXISTS memory_embeddings_memory_model_unique_idx;

ALTER TABLE memory_embeddings
    DROP COLUMN IF EXISTS updated_at,
    DROP COLUMN IF EXISTS content_hash;
