# Memory Lifecycle API

Sources:

- `/root/TestBot/brain-python/services/memory.py`
- `/root/TestBot/brain-python/services/memory_extractor.py`
- `/root/TestBot/database/migrations/000004_memory.up.sql`
- `/root/TestBot/database/migrations/000005_memory_lifecycle.up.sql`

Memory is not a standalone HTTP service. It is a Brain runtime subsystem used by
`POST /chat`, AI context assembly, admin commands, and the background extractor.

## Runtime Position

```text
Gateway
  -> Brain POST /chat
  -> memory admin command, when text starts with /memory or /记忆
  -> normal routing
  -> AI runtime
       -> recall_context()
       -> confirmed/reinforced memory snippets
```

Admin memory commands run before deterministic modules and AI. AI recall is
read-only and silently falls back to empty context when memory is disabled or
unavailable.

## Lifecycle States

| State | Meaning | Default AI recall |
| --- | --- | --- |
| `weak` | Candidate with valid evidence but not enough quality or repeated support. | No |
| `confirmed` | Stable enough for normal AI context. | Yes |
| `reinforced` | Confirmed memory with repeated evidence or high stability. | Yes |
| `stale` | Possibly outdated; visible in admin/debug tools. | No |
| `contradicted` | Conflicting evidence was observed. | No |
| `archived` | Retired memory. | No |

Brain also keeps the older `status` field:

| `status` | Meaning |
| --- | --- |
| `active` | Row can be considered by admin search and lifecycle logic. |
| `archived` | Retired but not hard-deleted. |
| `deleted` | Never recalled and excluded from most debug surfaces. |

AI recall requires:

```text
status = 'active'
lifecycle_status IN ('confirmed', 'reinforced')
```

For rollout recovery, `MEMORY_RECALL_LIFECYCLE_FILTER_ENABLED=false` loosens
recall to active, non-archived lifecycle rows. The default is `true`.

## Memory Record Shape

Service-level `MemoryRecord` fields:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | int | Database ID. |
| `scope` | string | `global`, `group`, `user`, or `relationship`. Extractor accepts only group/user/relationship. |
| `group_id` | string | Required for group/user/relationship scope. |
| `user_id` | string | Required for user/relationship scope. |
| `target_user_id` | string | Required for relationship scope. |
| `memory_type` | string | `preference`, `fact`, `style`, `relationship`, `topic`, `summary`, or `warning`. |
| `memory_class` | string | `episodic`, `semantic`, `procedural`, `affective`, `social`, or `persona`. |
| `content` | string | Long-term memory text. |
| `confidence` | float | Clamped to `0..1`. |
| `importance` | float | Clamped to `0..1`. |
| `lifecycle_status` | string | Quality lifecycle state. |
| `stability` | float | Reinforcement score, `0..1`. |
| `decay_score` | float | Aging score, `0..1`. |
| `contradiction_count` | int | Number of conflict updates. |
| `source_count` | int | Evidence count after de-duplication. |
| `quality_score` | float | Persisted ranking score, `0..1`. |
| `evidence_message_ids` | int[] | Message IDs supporting the memory. |
| `metadata` | object | Extractor/admin/debug metadata. |

## Admin Command API

Commands are sent as normal chat text through `POST /chat`.

```json
{
  "text": "/memory lifecycle status",
  "message_type": "group",
  "group_id": "613689332",
  "user_id": "854271190",
  "sender": {
    "role": "admin"
  }
}
```

Admin authorization accepts group sender roles `admin` and `owner`, plus IDs in
`MEMORY_ADMIN_USER_IDS`.

| Command | Scope | Response metadata |
| --- | --- | --- |
| `/memory status` | private/group | `{"module":"memory","command":"status","count":3,"enabled":true}` |
| `/memory search <text>` | private/group | Searches recallable active memories. |
| `/memory search <text> --status <state>` | private/group | Searches a lifecycle state or `all`. |
| `/memory show <id>` | private/group | Shows class, lifecycle, quality, evidence, and content. |
| `/memory user <QQ>` | group only | Lists memories for one user in the current group. |
| `/memory lifecycle status` | private/group | Counts rows by lifecycle state. |
| `/memory lifecycle confirm <id>` | private/group | Moves a visible row to `confirmed`. |
| `/memory lifecycle archive <id>` | private/group | Moves a visible row to `archived`. |
| `/memory lifecycle stale <id>` | private/group | Marks a visible row `stale`. |
| `/memory lifecycle decay [days]` | private/group | Applies age-based decay to visible rows. |
| `/memory debug recall <text>` | private/group | Shows recall score breakdown, including ineligible rows. |
| `/memory extract [10..200]` | group only | Starts background extraction from recent persisted group messages. |
| `/memory forget <id>` | private/group | Marks one row deleted. |
| `/memory forget-user <QQ>` | group only | Marks one user's rows deleted in the current group. |
| `/memory forget-group` | group only | Marks current group rows deleted. |
| `/memory enable` / `/memory disable` | group only | Updates group memory setting. |

Short aliases are supported for lifecycle actions:

```text
/memory confirm 42
/memory archive 42
/memory stale 42
/memory decay 30
```

## Admin Response Examples

Lifecycle status:

```json
{
  "handled": true,
  "should_reply": true,
  "reply": "记忆生命周期：\nweak: 1\nconfirmed: 2\nreinforced: 0\nstale: 0\ncontradicted: 0\narchived: 0",
  "metadata": {
    "module": "memory",
    "command": "lifecycle",
    "action": "status",
    "counts": {
      "weak": 1,
      "confirmed": 2,
      "reinforced": 0,
      "stale": 0,
      "contradicted": 0,
      "archived": 0
    }
  }
}
```

Debug recall:

```text
召回调试：
#9 score=0.81 eligible=yes lifecycle=confirmed keyword=1.00 entity=0.90 scope=0.75 quality=0.50 recency=0.50 用户喜欢南京天气。
```

## Extractor Candidate API

`/memory extract` calls an OpenAI-compatible chat completions endpoint. The
model must return a JSON object:

```json
{
  "memories": [
    {
      "scope": "user",
      "memory_type": "preference",
      "memory_class": "procedural",
      "group_id": "613689332",
      "user_id": "854271190",
      "target_user_id": "",
      "content": "Aurora 不喜欢长篇回复。",
      "confidence": 0.82,
      "importance": 0.64,
      "evidence_message_ids": [101, 104]
    }
  ]
}
```

Validation rules:

| Field | Rule |
| --- | --- |
| `scope` | Must be `group`, `user`, or `relationship`. Extractor cannot create `global`. |
| `memory_type` | Must be a valid memory type. |
| `memory_class` | Optional; missing values are inferred from `memory_type`. Invalid values reject the candidate. |
| `group_id` | Must match the current extraction group. |
| `content` | Required, normalized whitespace, max 300 characters. |
| `confidence` / `importance` | Required floats in `0..1`. |
| `evidence_message_ids` | Must point to messages in the extraction batch. |
| `user_id` | Required for user and relationship scope, and must be a sender in the batch. |
| `target_user_id` | Required for relationship scope, must be a sender in the batch, and cannot equal `user_id`. |

Optional conflict metadata:

```json
{
  "conflicts_with_memory_id": 42,
  "conflicts_with": {
    "content": "Aurora 喜欢长篇回复。"
  }
}
```

When `conflicts_with_memory_id` is valid, Brain marks that existing memory
`contradicted`, increments `contradiction_count`, lowers `quality_score`, and
stores `metadata.last_contradiction`.

## Upsert Rules

New memory:

| Condition | Initial lifecycle |
| --- | --- |
| `memory_type = warning` and `confidence >= 0.7` | `confirmed` |
| `confidence >= 0.78`, `importance >= 0.55`, and at least 2 evidence IDs | `confirmed` |
| Otherwise | `weak` |

Matching existing memory:

- matches by scope, group/user/target IDs, `memory_class`, `memory_type`, and
  normalized content;
- merges de-duplicated evidence IDs;
- increases confidence by at most `0.03` when new evidence appears;
- increases stability by `0.05` when new evidence appears;
- resets `decay_score` to `1.0`;
- keeps `contradicted` and `archived` rows from being silently restored.

Reinforcement:

| Existing state | Result |
| --- | --- |
| `weak` + enough evidence | `confirmed` |
| `confirmed` + `source_count >= 3` or `stability >= 0.75` | `reinforced` |
| `stale` + enough evidence | `confirmed` |
| `contradicted` | stays `contradicted` until admin/manual handling |
| `archived` | stays archived |

## Scoring

Persisted `quality_score`:

```text
confidence * 0.35
+ importance * 0.25
+ stability * 0.15
+ min(source_count, 5) / 5 * 0.15
+ decay_score * 0.10
- min(contradiction_count, 3) * 0.10
```

Recall debug score:

```text
keyword_match * 0.30
+ entity_relevance * 0.20
+ scope_relevance * 0.15
+ quality_score * 0.25
+ recency_weight * 0.10
```

Both scores are clamped to `0..1`.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | empty | Required for memory tables and extraction runs. |
| `MEMORY_ENABLED` | `true` | Enables AI recall context. |
| `MEMORY_RECALL_LIFECYCLE_FILTER_ENABLED` | `true` | Keeps AI recall limited to `confirmed` and `reinforced`; set `false` only as a temporary rollout fallback. |
| `MEMORY_ADMIN_USER_IDS` | empty | Extra admin QQ IDs for `/memory` commands. |
| `MEMORY_EXTRACTOR_ENABLED` | `false` | Enables `/memory extract`. |
| `MEMORY_EXTRACTOR_BASE_URL` | falls back to `AI_BASE_URL` | Extractor chat completions endpoint root. |
| `MEMORY_EXTRACTOR_API_KEY` | falls back to `AI_API_KEY` | Optional bearer token. |
| `MEMORY_EXTRACTOR_MODEL` | falls back to `AI_MODEL` | Extractor model. |
| `MEMORY_EXTRACTOR_TIMEOUT` | `30` | Upstream timeout seconds. |
| `MEMORY_EXTRACTOR_BATCH_SIZE` | `80` | Default extraction message count, clamped to `10..200`. |
| `MEMORY_EXTRACTOR_MAX_CANDIDATES` | `12` | Maximum candidates accepted per run. |

## Related Docs

- [AI Runtime API](ai-runtime-api.md)
- [Brain API](brain-api.md)
- [Database Schema](database-schema.md)
- [Memory Quality Phase 1](../development/memory-quality-phase1.zh-CN.md)
