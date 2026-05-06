ALTER TABLE memory_items
    ADD COLUMN memory_class TEXT NOT NULL DEFAULT 'semantic',
    ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'confirmed',
    ADD COLUMN stability DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    ADD COLUMN decay_score DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    ADD COLUMN contradiction_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN source_count INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN last_confirmed_at TIMESTAMPTZ,
    ADD COLUMN archived_at TIMESTAMPTZ,
    ADD COLUMN quality_score DOUBLE PRECISION NOT NULL DEFAULT 0.5;

UPDATE memory_items
SET
    memory_class = CASE memory_type
        WHEN 'fact' THEN 'semantic'
        WHEN 'topic' THEN 'semantic'
        WHEN 'summary' THEN 'semantic'
        WHEN 'style' THEN 'procedural'
        WHEN 'preference' THEN 'procedural'
        WHEN 'relationship' THEN 'social'
        WHEN 'warning' THEN 'procedural'
        ELSE 'semantic'
    END,
    lifecycle_status = CASE status
        WHEN 'active' THEN 'confirmed'
        WHEN 'archived' THEN 'archived'
        WHEN 'deleted' THEN 'archived'
        ELSE 'confirmed'
    END,
    source_count = jsonb_array_length(evidence_message_ids),
    last_confirmed_at = last_seen_at,
    archived_at = CASE
        WHEN status = 'archived' THEN COALESCE(updated_at, now())
        ELSE archived_at
    END;

UPDATE memory_items
SET quality_score = LEAST(
    1.0,
    GREATEST(
        0.0,
        confidence * 0.35
        + importance * 0.25
        + stability * 0.15
        + (LEAST(source_count, 5)::DOUBLE PRECISION / 5.0) * 0.15
        + decay_score * 0.10
        - LEAST(contradiction_count, 3) * 0.10
    )
);

ALTER TABLE memory_items
    ADD CONSTRAINT memory_items_memory_class_check
        CHECK (memory_class IN ('episodic', 'semantic', 'procedural', 'affective', 'social', 'persona')),
    ADD CONSTRAINT memory_items_lifecycle_status_check
        CHECK (lifecycle_status IN ('weak', 'confirmed', 'reinforced', 'stale', 'contradicted', 'archived')),
    ADD CONSTRAINT memory_items_stability_check CHECK (stability >= 0 AND stability <= 1),
    ADD CONSTRAINT memory_items_decay_score_check CHECK (decay_score >= 0 AND decay_score <= 1),
    ADD CONSTRAINT memory_items_contradiction_count_check CHECK (contradiction_count >= 0),
    ADD CONSTRAINT memory_items_source_count_check CHECK (source_count >= 0),
    ADD CONSTRAINT memory_items_quality_score_check CHECK (quality_score >= 0 AND quality_score <= 1);

CREATE INDEX memory_items_recall_lifecycle_idx
    ON memory_items (
        scope,
        group_id,
        user_id,
        target_user_id,
        lifecycle_status,
        quality_score DESC,
        last_seen_at DESC
    )
    WHERE status = 'active';

CREATE INDEX memory_items_debug_lifecycle_idx
    ON memory_items (lifecycle_status, updated_at DESC)
    WHERE status <> 'deleted';
