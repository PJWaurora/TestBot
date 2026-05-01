CREATE TABLE memory_items (
    id BIGSERIAL PRIMARY KEY,
    scope TEXT NOT NULL CHECK (scope IN ('group', 'user', 'relationship', 'global')),
    group_id TEXT,
    user_id TEXT,
    target_user_id TEXT,
    memory_type TEXT NOT NULL CHECK (
        memory_type IN ('preference', 'fact', 'style', 'relationship', 'topic', 'summary', 'warning')
    ),
    content TEXT NOT NULL CHECK (content <> ''),
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
    importance DOUBLE PRECISION NOT NULL DEFAULT 0.5 CHECK (importance >= 0 AND importance <= 1),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived', 'deleted')),
    evidence_message_ids JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT NOT NULL DEFAULT 'extractor',
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(evidence_message_ids) = 'array' AND jsonb_array_length(evidence_message_ids) > 0),
    CHECK (scope <> 'group' OR (group_id IS NOT NULL AND group_id <> '')),
    CHECK (scope <> 'user' OR (group_id IS NOT NULL AND group_id <> '' AND user_id IS NOT NULL AND user_id <> '')),
    CHECK (
        scope <> 'relationship'
        OR (
            group_id IS NOT NULL AND group_id <> ''
            AND user_id IS NOT NULL AND user_id <> ''
            AND target_user_id IS NOT NULL AND target_user_id <> ''
        )
    )
);

CREATE INDEX memory_items_scope_group_user_idx
    ON memory_items (scope, group_id, user_id, target_user_id)
    WHERE status = 'active';

CREATE INDEX memory_items_type_importance_idx
    ON memory_items (memory_type, importance DESC, last_seen_at DESC)
    WHERE status = 'active';

CREATE INDEX memory_items_content_fts_idx
    ON memory_items USING GIN (to_tsvector('simple', content))
    WHERE status = 'active';

CREATE TABLE memory_embeddings (
    id BIGSERIAL PRIMARY KEY,
    memory_id BIGINT NOT NULL REFERENCES memory_items (id) ON DELETE CASCADE,
    embedding vector(1536) NOT NULL,
    embedding_model TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX memory_embeddings_memory_id_idx
    ON memory_embeddings (memory_id);

CREATE TABLE memory_runs (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT REFERENCES conversations (id) ON DELETE SET NULL,
    group_id TEXT,
    user_id TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
    model TEXT,
    input_message_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    output_memory_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    error TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX memory_runs_status_started_at_idx
    ON memory_runs (status, started_at DESC);

CREATE TABLE memory_settings (
    id BIGSERIAL PRIMARY KEY,
    scope TEXT NOT NULL CHECK (scope IN ('group', 'global')),
    group_id TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT true,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scope, group_id),
    CHECK (scope <> 'group' OR group_id <> ''),
    CHECK (scope <> 'global' OR group_id = '')
);
