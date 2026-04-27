CREATE TABLE IF NOT EXISTS notification_outbox (
    id BIGSERIAL PRIMARY KEY,
    target_type TEXT NOT NULL CHECK (target_type IN ('private', 'group')),
    target_id TEXT NOT NULL,
    messages JSONB NOT NULL DEFAULT '[]'::jsonb,
    actions JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS notification_outbox_poll_idx
    ON notification_outbox (status, available_at, id)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS notification_outbox_locked_at_idx
    ON notification_outbox (locked_at)
    WHERE locked_at IS NOT NULL;

-- Polling treats stale locks as retryable so a gateway crash after pull but
-- before ack does not leave a notification stuck forever.
