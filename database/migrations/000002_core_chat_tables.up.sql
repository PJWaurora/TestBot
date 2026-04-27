CREATE TABLE conversations (
    id BIGSERIAL PRIMARY KEY,
    conversation_type TEXT NOT NULL CHECK (conversation_type IN ('private', 'group')),
    external_id TEXT NOT NULL,
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (conversation_type, external_id)
);

CREATE TABLE message_events_raw (
    id BIGSERIAL PRIMARY KEY,
    external_message_id TEXT,
    post_type TEXT,
    message_type TEXT,
    event JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX message_events_raw_external_message_id_idx
    ON message_events_raw (external_message_id);

CREATE INDEX message_events_raw_ingested_at_idx
    ON message_events_raw (ingested_at);

CREATE INDEX message_events_raw_event_gin_idx
    ON message_events_raw USING GIN (event);

CREATE TABLE messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    raw_event_id BIGINT REFERENCES message_events_raw (id) ON DELETE SET NULL,
    external_message_id TEXT,
    external_message_seq TEXT,
    external_real_id TEXT,
    external_real_seq TEXT,
    post_type TEXT,
    message_type TEXT,
    sub_type TEXT,
    primary_type TEXT,
    text TEXT,
    raw_message TEXT,
    segments JSONB NOT NULL DEFAULT '[]'::jsonb,
    sender_user_id TEXT,
    sender_nickname TEXT,
    sender_card TEXT,
    sender_role TEXT,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX messages_conversation_id_created_at_idx
    ON messages (conversation_id, created_at);

CREATE INDEX messages_external_message_id_idx
    ON messages (external_message_id);

CREATE INDEX messages_sender_user_id_idx
    ON messages (sender_user_id);

CREATE TABLE bot_responses (
    id BIGSERIAL PRIMARY KEY,
    message_id BIGINT NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    should_reply BOOLEAN NOT NULL DEFAULT false,
    reply TEXT,
    actions JSONB NOT NULL DEFAULT '[]'::jsonb,
    model TEXT,
    prompt_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX bot_responses_message_id_idx
    ON bot_responses (message_id);

-- Embedding storage is intentionally omitted until the embedding model and
-- vector dimensions are finalized.
