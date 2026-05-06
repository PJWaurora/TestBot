DROP INDEX IF EXISTS memory_items_debug_lifecycle_idx;
DROP INDEX IF EXISTS memory_items_recall_lifecycle_idx;

ALTER TABLE memory_items
    DROP CONSTRAINT IF EXISTS memory_items_quality_score_check,
    DROP CONSTRAINT IF EXISTS memory_items_source_count_check,
    DROP CONSTRAINT IF EXISTS memory_items_contradiction_count_check,
    DROP CONSTRAINT IF EXISTS memory_items_decay_score_check,
    DROP CONSTRAINT IF EXISTS memory_items_stability_check,
    DROP CONSTRAINT IF EXISTS memory_items_lifecycle_status_check,
    DROP CONSTRAINT IF EXISTS memory_items_memory_class_check;

ALTER TABLE memory_items
    DROP COLUMN IF EXISTS quality_score,
    DROP COLUMN IF EXISTS archived_at,
    DROP COLUMN IF EXISTS last_confirmed_at,
    DROP COLUMN IF EXISTS source_count,
    DROP COLUMN IF EXISTS contradiction_count,
    DROP COLUMN IF EXISTS decay_score,
    DROP COLUMN IF EXISTS stability,
    DROP COLUMN IF EXISTS lifecycle_status,
    DROP COLUMN IF EXISTS memory_class;
