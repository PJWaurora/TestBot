CREATE TABLE conversation_states (
    conversation_id BIGINT PRIMARY KEY REFERENCES conversations (id) ON DELETE CASCADE,
    active_topics JSONB NOT NULL DEFAULT '[]'::jsonb,
    mood TEXT NOT NULL DEFAULT 'neutral',
    conversation_velocity TEXT NOT NULL DEFAULT 'quiet',
    current_speaker_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    last_bot_reply_at TIMESTAMPTZ,
    bot_reply_count_1h INTEGER NOT NULL DEFAULT 0,
    bot_reply_count_24h INTEGER NOT NULL DEFAULT 0,
    should_avoid_long_reply BOOLEAN NOT NULL DEFAULT false,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT conversation_states_mood_check
        CHECK (mood IN ('neutral', 'positive', 'tense', 'unclear')),
    CONSTRAINT conversation_states_velocity_check
        CHECK (conversation_velocity IN ('quiet', 'normal', 'active', 'burst')),
    CONSTRAINT conversation_states_bot_reply_count_1h_check
        CHECK (bot_reply_count_1h >= 0),
    CONSTRAINT conversation_states_bot_reply_count_24h_check
        CHECK (bot_reply_count_24h >= 0)
);

CREATE INDEX conversation_states_updated_at_idx
    ON conversation_states (updated_at DESC);
