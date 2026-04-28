CREATE TABLE message_outbox (
    id BIGSERIAL PRIMARY KEY,
    message_type TEXT NOT NULL CHECK (message_type IN ('private', 'group')),
    user_id TEXT,
    group_id TEXT,
    messages JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'sent', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts > 0),
    last_error TEXT,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_until TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (message_type = 'group' AND group_id IS NOT NULL AND group_id <> '')
        OR (message_type = 'private' AND user_id IS NOT NULL AND user_id <> '')
    )
);

CREATE INDEX message_outbox_pending_idx
    ON message_outbox (status, next_attempt_at, created_at, id)
    WHERE status IN ('pending', 'processing');

CREATE INDEX message_outbox_locked_until_idx
    ON message_outbox (locked_until)
    WHERE status = 'processing';

CREATE INDEX message_outbox_created_at_idx
    ON message_outbox (created_at);
