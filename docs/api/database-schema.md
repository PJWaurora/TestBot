# Database Schema

Source: `/root/TestBot/database/migrations`

Brain uses PostgreSQL for message persistence, bot response audit rows, async
outbox delivery, and long-term memory. The migrations also enable pgvector for
memory embeddings.

## Migrations

| Migration | Purpose |
| --- | --- |
| `000001_enable_pgvector` | Enables the `vector` extension. |
| `000002_core_chat_tables` | Creates conversations, raw message events, normalized messages, and bot response audit rows. |
| `000003_message_outbox` | Creates async delivery queue table. |
| `000004_memory` | Creates memory items, memory embeddings, extraction runs, and memory settings. |
| `000005_memory_lifecycle` | Adds memory class, lifecycle state, quality scoring fields, and lifecycle recall/debug indexes. |
| `000006_memory_embedding_recall` | Adds embedding freshness metadata, embedding uniqueness, and vector recall index. |

## Extension

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

The current memory embedding table stores `vector(1536)`.

## `conversations`

Conversation identity table.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `BIGSERIAL` | Primary key. |
| `conversation_type` | `TEXT` | Must be `private` or `group`. |
| `external_id` | `TEXT` | QQ user ID or group ID as text. |
| `title` | `TEXT` | Optional display title. |
| `created_at` | `TIMESTAMPTZ` | Default `now()`. |
| `updated_at` | `TIMESTAMPTZ` | Default `now()`. |

Constraints and indexes:

| Name | Definition |
| --- | --- |
| Unique conversation | `(conversation_type, external_id)` |

## `message_events_raw`

Stores the original incoming event JSON before normalization.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `BIGSERIAL` | Primary key. |
| `external_message_id` | `TEXT` | Message ID from QQ/NapCat when available. |
| `post_type` | `TEXT` | Raw post type. |
| `message_type` | `TEXT` | Raw message type. |
| `event` | `JSONB` | Full raw event body. |
| `ingested_at` | `TIMESTAMPTZ` | Default `now()`. |

Indexes:

| Name | Columns |
| --- | --- |
| `message_events_raw_external_message_id_idx` | `external_message_id` |
| `message_events_raw_ingested_at_idx` | `ingested_at` |
| `message_events_raw_event_gin_idx` | `event` using GIN |

## `messages`

Stores normalized incoming messages linked to conversations and optional raw
events.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `BIGSERIAL` | Primary key. |
| `conversation_id` | `BIGINT` | Required, references `conversations(id)` with cascade delete. |
| `raw_event_id` | `BIGINT` | References `message_events_raw(id)`, set null on delete. |
| `external_message_id` | `TEXT` | Gateway/NapCat message ID. |
| `external_message_seq` | `TEXT` | External sequence ID when available. |
| `external_real_id` | `TEXT` | External real ID when available. |
| `external_real_seq` | `TEXT` | External real sequence when available. |
| `post_type` | `TEXT` | Normalized post type. |
| `message_type` | `TEXT` | Usually `group` or `private`. |
| `sub_type` | `TEXT` | Message subtype. |
| `primary_type` | `TEXT` | Gateway-computed primary type. |
| `text` | `TEXT` | Joined text. |
| `raw_message` | `TEXT` | Raw message text/string form when available. |
| `segments` | `JSONB` | Normalized segment array, default `[]`. |
| `sender_user_id` | `TEXT` | Sender QQ ID. |
| `sender_nickname` | `TEXT` | Sender nickname. |
| `sender_card` | `TEXT` | Group card. |
| `sender_role` | `TEXT` | Sender role. |
| `sent_at` | `TIMESTAMPTZ` | Message timestamp from source when available. |
| `created_at` | `TIMESTAMPTZ` | Default `now()`. |
| `updated_at` | `TIMESTAMPTZ` | Default `now()`. |

Indexes:

| Name | Columns |
| --- | --- |
| `messages_conversation_id_created_at_idx` | `conversation_id, created_at` |
| `messages_external_message_id_idx` | `external_message_id` |
| `messages_sender_user_id_idx` | `sender_user_id` |

## `bot_responses`

Stores Brain response audit data for a message.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `BIGSERIAL` | Primary key. |
| `message_id` | `BIGINT` | Required, references `messages(id)` with cascade delete. |
| `should_reply` | `BOOLEAN` | Default `false`. |
| `reply` | `TEXT` | Legacy text reply. |
| `actions` | `JSONB` | Response messages/actions, default `[]`. |
| `model` | `TEXT` | AI/model name when used. |
| `prompt_version` | `TEXT` | Prompt version when used. |
| `created_at` | `TIMESTAMPTZ` | Default `now()`. |

Indexes:

| Name | Columns |
| --- | --- |
| `bot_responses_message_id_idx` | `message_id` |

## `message_outbox`

Async delivery queue consumed by Gateway. Producer services enqueue here
through Brain `/outbox/enqueue`.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `BIGSERIAL` | Primary key. |
| `message_type` | `TEXT` | Must be `group` or `private`. |
| `user_id` | `TEXT` | Required for private outbox items. |
| `group_id` | `TEXT` | Required for group outbox items. |
| `messages` | `JSONB` | Array of outbound message items, default `[]`. Brain validates it as non-empty before insert. |
| `metadata` | `JSONB` | Producer metadata, default `{}`. |
| `status` | `TEXT` | `pending`, `processing`, `sent`, or `failed`. Default `pending`. |
| `attempts` | `INTEGER` | Delivery attempts, default `0`. |
| `max_attempts` | `INTEGER` | Default `5`, must be positive. |
| `last_error` | `TEXT` | Most recent gateway/NapCat delivery error. |
| `next_attempt_at` | `TIMESTAMPTZ` | Retry eligibility time, default `now()`. |
| `locked_until` | `TIMESTAMPTZ` | Lease expiry for in-flight delivery. |
| `sent_at` | `TIMESTAMPTZ` | Send completion time. |
| `failed_at` | `TIMESTAMPTZ` | Final failure time. |
| `created_at` | `TIMESTAMPTZ` | Default `now()`. |
| `updated_at` | `TIMESTAMPTZ` | Default `now()`. |

Indexes:

| Name | Columns / Predicate |
| --- | --- |
| `message_outbox_pending_idx` | `status, next_attempt_at, created_at, id` where `status IN ('pending', 'processing')` |
| `message_outbox_locked_until_idx` | `locked_until` where `status='processing'` |
| `message_outbox_created_at_idx` | `created_at` |

Lifecycle:

```text
pending -> processing -> sent
pending -> processing -> pending
pending -> processing -> failed
```

When Gateway fails an item and attempts remain, Brain puts it back to
`pending` with a future `next_attempt_at`. When attempts are exhausted, Brain
marks it `failed`.

## `memory_items`

Long-term memory records extracted from messages.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `BIGSERIAL` | Primary key. |
| `scope` | `TEXT` | `group`, `user`, `relationship`, or `global`. |
| `group_id` | `TEXT` | Required for group, user, and relationship memories. |
| `user_id` | `TEXT` | Required for user and relationship memories. |
| `target_user_id` | `TEXT` | Required for relationship memories. |
| `memory_type` | `TEXT` | `preference`, `fact`, `style`, `relationship`, `topic`, `summary`, or `warning`. |
| `memory_class` | `TEXT` | `episodic`, `semantic`, `procedural`, `affective`, `social`, or `persona`. Backfilled from `memory_type`; default `semantic`. |
| `content` | `TEXT` | Required non-empty memory content. |
| `confidence` | `DOUBLE PRECISION` | Default `0.5`, range `0..1`. |
| `importance` | `DOUBLE PRECISION` | Default `0.5`, range `0..1`. |
| `status` | `TEXT` | `active`, `archived`, or `deleted`. Default `active`. |
| `lifecycle_status` | `TEXT` | Quality lifecycle: `weak`, `confirmed`, `reinforced`, `stale`, `contradicted`, or `archived`. Default `confirmed`. |
| `stability` | `DOUBLE PRECISION` | Default `0.5`, range `0..1`; increases as evidence reinforces the memory. |
| `decay_score` | `DOUBLE PRECISION` | Default `1.0`, range `0..1`; lower values indicate stale or decayed memories. |
| `contradiction_count` | `INTEGER` | Default `0`; number of recorded contradiction events. |
| `source_count` | `INTEGER` | Default `1`; backfilled from `jsonb_array_length(evidence_message_ids)`. |
| `last_confirmed_at` | `TIMESTAMPTZ` | Last time the memory was confirmed; backfilled from `last_seen_at`. |
| `archived_at` | `TIMESTAMPTZ` | Set when an existing archived memory is migrated or when lifecycle logic archives it. |
| `quality_score` | `DOUBLE PRECISION` | Default `0.5`, range `0..1`; persisted quality score for admin sorting and recall ranking. |
| `evidence_message_ids` | `JSONB` | Required non-empty array. |
| `metadata` | `JSONB` | Default `{}`. |
| `created_by` | `TEXT` | Default `extractor`. |
| `first_seen_at` | `TIMESTAMPTZ` | Default `now()`. |
| `last_seen_at` | `TIMESTAMPTZ` | Default `now()`. |
| `expires_at` | `TIMESTAMPTZ` | Optional expiry. |
| `created_at` | `TIMESTAMPTZ` | Default `now()`. |
| `updated_at` | `TIMESTAMPTZ` | Default `now()`. |

Indexes:

| Name | Columns / Predicate |
| --- | --- |
| `memory_items_scope_group_user_idx` | `scope, group_id, user_id, target_user_id` where `status='active'` |
| `memory_items_type_importance_idx` | `memory_type, importance DESC, last_seen_at DESC` where `status='active'` |
| `memory_items_content_fts_idx` | `to_tsvector('simple', content)` using GIN where `status='active'` |
| `memory_items_recall_lifecycle_idx` | `scope, group_id, user_id, target_user_id, lifecycle_status, quality_score DESC, last_seen_at DESC` where `status='active'` |
| `memory_items_debug_lifecycle_idx` | `lifecycle_status, updated_at DESC` where `status <> 'deleted'` |

Scope constraints:

| Scope | Required IDs |
| --- | --- |
| `global` | none |
| `group` | `group_id` |
| `user` | `group_id`, `user_id` |
| `relationship` | `group_id`, `user_id`, `target_user_id` |

Quality and lifecycle constraints:

| Field | Constraint |
| --- | --- |
| `memory_class` | Must be one of `episodic`, `semantic`, `procedural`, `affective`, `social`, or `persona`. |
| `lifecycle_status` | Must be one of `weak`, `confirmed`, `reinforced`, `stale`, `contradicted`, or `archived`. |
| `stability` | `0..1` |
| `decay_score` | `0..1` |
| `contradiction_count` | `>= 0` |
| `source_count` | `>= 0` |
| `quality_score` | `0..1` |

Lifecycle semantics:

| Field | Purpose | Recall behavior |
| --- | --- | --- |
| `status` | Visibility and deletion state. `deleted` is never recalled. | AI recall requires `status='active'`. |
| `lifecycle_status` | Quality and lifecycle state. | AI recall defaults to `confirmed` and `reinforced` only. |

Migration `000005_memory_lifecycle` keeps old `status` values intact. Existing
`active` rows become lifecycle `confirmed`; existing `archived` and `deleted`
rows become lifecycle `archived`. `memory_class` is backfilled from
`memory_type`: `fact`, `topic`, and `summary` become `semantic`; `style`,
`preference`, and `warning` become `procedural`; `relationship` becomes
`social`.

## `memory_embeddings`

Vector embeddings for memory similarity search.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `BIGSERIAL` | Primary key. |
| `memory_id` | `BIGINT` | Required, references `memory_items(id)` with cascade delete. |
| `embedding` | `vector(1536)` | Embedding vector. |
| `embedding_model` | `TEXT` | Model name used to create the embedding. |
| `content_hash` | `TEXT` | Hash of the memory content used to detect stale embeddings. Added by `000006_memory_embedding_recall`. |
| `created_at` | `TIMESTAMPTZ` | Default `now()`. |
| `updated_at` | `TIMESTAMPTZ` | Last embedding refresh time. Added by `000006_memory_embedding_recall`. |

Indexes:

| Name | Columns |
| --- | --- |
| `memory_embeddings_memory_id_idx` | `memory_id` |
| `memory_embeddings_memory_model_unique_idx` | Unique `(memory_id, embedding_model)` |
| `memory_embeddings_embedding_ivfflat_idx` | `embedding vector_cosine_ops` using ivfflat |

## `memory_runs`

Tracks memory extraction/indexing runs.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `BIGSERIAL` | Primary key. |
| `conversation_id` | `BIGINT` | References `conversations(id)`, set null on delete. |
| `group_id` | `TEXT` | Group context. |
| `user_id` | `TEXT` | User context. |
| `started_at` | `TIMESTAMPTZ` | Default `now()`. |
| `finished_at` | `TIMESTAMPTZ` | Optional completion time. |
| `status` | `TEXT` | `running`, `succeeded`, or `failed`. Default `running`. |
| `model` | `TEXT` | Extraction model. |
| `input_message_ids` | `JSONB` | Default `[]`. |
| `output_memory_ids` | `JSONB` | Default `[]`. |
| `error` | `TEXT` | Failure detail. |
| `metadata` | `JSONB` | Default `{}`. |

Indexes:

| Name | Columns |
| --- | --- |
| `memory_runs_status_started_at_idx` | `status, started_at DESC` |

## `memory_settings`

Controls whether memory is enabled globally or per group.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `BIGSERIAL` | Primary key. |
| `scope` | `TEXT` | `group` or `global`. |
| `group_id` | `TEXT` | Required for group settings, empty for global. |
| `enabled` | `BOOLEAN` | Default `true`. |
| `metadata` | `JSONB` | Default `{}`. |
| `created_at` | `TIMESTAMPTZ` | Default `now()`. |
| `updated_at` | `TIMESTAMPTZ` | Default `now()`. |

Constraints:

| Name | Definition |
| --- | --- |
| Unique setting | `(scope, group_id)` |
| Group scope | `group_id <> ''` |
| Global scope | `group_id = ''` |
