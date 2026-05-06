# Brain API

Brain is the Python FastAPI core in `brain-python/`. It owns deterministic
routing, remote module dispatch, tool aggregation, persistence, memory, AI
runtime, and authenticated async outbox storage.

Default local port: `8000`.

## Routes

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/health` | none | Liveness check. |
| `POST` | `/chat` | none | Main synchronous gateway entrypoint. Accepts `ChatRequest`, returns `BrainResponse`. |
| `GET` | `/tools` | none | Returns local and remote tool definitions. |
| `POST` | `/tools/call` | none | Calls local fake echo or forwards to the owning remote module tool. |
| `POST` | `/outbox/enqueue` | outbox token | Creates async delivery item. |
| `POST` | `/outbox/pull` | outbox token | Leases pending async delivery items for the gateway. |
| `POST` | `/outbox/{id}/ack` | outbox token | Marks item sent. |
| `POST` | `/outbox/{id}/fail` | outbox token | Records delivery failure and schedules retry or final failure. |

Outbox auth accepts either:

```text
Authorization: Bearer <OUTBOX_TOKEN>
X-Outbox-Token: <OUTBOX_TOKEN>
```

If `OUTBOX_TOKEN` is empty, outbox routes return `503`.

## `GET /health`

Response:

```json
{
  "status": "ok"
}
```

## `POST /chat`

`/chat` is called by Gateway after it normalizes a NapCat message. Brain does
not talk to Gateway directly for normal synchronous replies; it returns
`BrainResponse` and Gateway converts it to NapCat actions.

Request body shape:

| Field | Type | Description |
| --- | --- | --- |
| `self_id` | string/int/null | Bot account ID. |
| `post_type` | string/null | Usually `message`. |
| `sub_type` | string/null | NapCat subtype. |
| `primary_type` | string/null | Gateway computed primary type. |
| `text` | string | Joined text segments. |
| `content` | string | Alternate text. |
| `message` | `BrainMessage`/null | Optional single message item. |
| `messages` | array | Optional list of message items. |
| `text_segments` | array | Text segment values. |
| `json_messages` | array | Parsed QQ JSON card payloads. |
| `images` | array | Normalized image inputs. |
| `videos` | array | Normalized video inputs. |
| `at_user_ids` | array | Mentioned QQ IDs. |
| `at_all` | boolean | Whether message contains `@all`. |
| `reply_to_message_id` | string/int/null | Replied-to message ID. |
| `unknown_types` | array | Unsupported segment types. |
| `segments` | array | Original OneBot segments. |
| `user_id` | string/int/null | Sender QQ ID. |
| `group_id` | string/int/null | Group ID. |
| `group_name` | string | Group name. |
| `target_id` | string/int/null | Private target ID. |
| `sender` | object/null | Sender `{user_id,nickname,card,role}`. |
| `conversation_id` | string/null | Optional conversation ID. |
| `message_id` | string/int/null | Incoming message ID. |
| `message_type` | string/null | `group` or `private`. |
| `metadata` | object | Extra metadata. |

Response body:

| Field | Type | Description |
| --- | --- | --- |
| `handled` | boolean | Whether Brain/module considered the request. |
| `should_reply` | boolean | Whether Gateway should send returned messages. |
| `messages` | array | Preferred reply items. Gateway uses these before `reply`. |
| `reply` | string | Legacy plain text fallback. |
| `tool_calls` | array | Tool call metadata for planning/logging. |
| `job_id` | string/null | Optional job identifier. |
| `metadata` | object/null | Route, module, error, or diagnostic metadata. |

Text reply example:

```json
{
  "handled": true,
  "should_reply": true,
  "messages": [
    {
      "type": "text",
      "text": "hello"
    }
  ],
  "metadata": {
    "module": "example"
  }
}
```

Forward reply example:

```json
{
  "handled": true,
  "should_reply": true,
  "messages": [
    {
      "type": "node",
      "data": {
        "user_id": "0",
        "nickname": "TestBot",
        "content": [
          {"type": "text", "data": {"text": "first node"}},
          {"type": "image", "data": {"file": "https://example.test/a.png"}}
        ]
      }
    }
  ]
}
```

Gateway sends a merged-forward action when every returned message is `node` or
the only returned message is `forward`.

## Routing Order

Brain routes `/chat` in this order:

1. Persist incoming message when `DATABASE_URL` is configured.
2. Extract candidate command text from `text`, `content`, `message`,
   `messages`, `text_segments`, and JSON card string values.
3. For each candidate text, try memory admin commands.
4. For each candidate text, try deterministic in-core modules first.
5. If no in-core module matches that candidate, try configured remote modules
   from `BRAIN_MODULE_SERVICE_DEFAULTS` merged with `BRAIN_MODULE_SERVICES`.
6. Try fake planner echo.
7. Try AI runtime when enabled.
8. Return `handled=false`, `should_reply=false`.

Remote module failures are logged and treated as no route so later modules can
still run.

Routing decision summary:

| Stage | Trigger | Result |
| --- | --- | --- |
| Memory admin | `/memory ...` or `/记忆 ...` from an allowed admin | Handles immediately before modules. |
| Deterministic in-core module | Local module `detect(text)` returns true | Brain applies module group policy, calls the module, and returns its response. |
| Remote module | No local match for that candidate text | Brain POSTs the request to each allowed remote module's `/handle` until one returns `handled` or `should_reply`. |
| Fake planner | `/echo ...` | Brain calls the local `echo` tool and returns a fake planner response. |
| AI runtime | AI command, mention trigger, or reply trigger | Brain calls the configured OpenAI-compatible chat completions endpoint. |
| No route | None of the above | Brain returns `handled=false`, `should_reply=false`. |

The default in-core registry only includes the local echo tool module. Current
feature modules such as Bilibili, TSPerson, Weather, and Pixiv are expected to
run as remote module services.

## Remote Module Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `BRAIN_MODULE_SERVICE_DEFAULTS` | Bilibili, TSPerson, Weather compose URLs | Default `name=url` list. |
| `BRAIN_MODULE_SERVICES` | empty | Extra or overriding `name=url` entries. |
| `BRAIN_MODULE_TIMEOUT` | `5` | HTTP timeout for remote module calls. |
| `BRAIN_COMMAND_PREFIXES` | module-specific default fallback | Shared prefix source for modules that honor it. |

Entry format:

```text
BRAIN_MODULE_SERVICES=pixiv=http://127.0.0.1:8014
```

## `GET /tools`

Returns a list of `ToolDefinition`:

```json
[
  {
    "name": "weather.get_live",
    "description": "Query Amap live weather by Chinese city name or Amap adcode.",
    "input_schema": {
      "type": "object",
      "properties": {
        "city": {"type": "string"}
      }
    }
  }
]
```

Brain includes the local fake `echo` tool and tools fetched from each remote
module's `GET /tools`. Duplicate remote tool names are ignored after the first
owner.

## `POST /tools/call`

Request:

```json
{
  "name": "weather.get_live",
  "arguments": {
    "city": "北京"
  },
  "message_type": "group",
  "group_id": "123456",
  "user_id": "10001"
}
```

Response is `ToolResult`:

```json
{
  "tool_name": "weather.get_live",
  "ok": true,
  "data": {
    "ok": true,
    "city": "北京"
  }
}
```

Remote tool failures return `ok=false` with errors such as
`module_unavailable`, `module_http_<status>`, or `bad_module_response`.

## Outbox

All outbox routes require `OUTBOX_TOKEN`.

### `POST /outbox/enqueue`

Request:

```json
{
  "message_type": "group",
  "group_id": "123456",
  "messages": [
    {
      "type": "text",
      "text": "async notice"
    }
  ],
  "metadata": {
    "source": "media"
  },
  "max_attempts": 5
}
```

Rules:

- `message_type` must be `group` or `private`.
- `group` requires `group_id`.
- `private` requires `user_id`.
- Current Brain validation accepts outbox message types `text`, `image`, and
  `video`.
- Text messages require `text`, `content`, `data.text`, or `data.content`.
- Image/video messages require `file`, `url`, `path`, or matching `data` keys.

Response is `OutboxItem` with status fields and timestamps.

### `POST /outbox/pull`

Request:

```json
{
  "limit": 10,
  "lease_seconds": 30
}
```

Response:

```json
{
  "items": [
    {
      "id": 7,
      "message_type": "group",
      "group_id": "123456",
      "messages": [{"type": "text", "text": "async notice"}],
      "status": "processing",
      "attempts": 0,
      "max_attempts": 5
    }
  ]
}
```

Brain leases pending or expired-processing items using Postgres
`FOR UPDATE SKIP LOCKED`.

### `POST /outbox/{id}/ack`

Request body:

```json
{}
```

Marks the item `sent`, clears `locked_until`, and sets `sent_at`.

### `POST /outbox/{id}/fail`

Request:

```json
{
  "error": "gateway_write_failed"
}
```

Increments attempts. If attempts reaches `max_attempts`, status becomes
`failed`; otherwise it returns to `pending`.

## Persistence

When `DATABASE_URL` is configured, Brain writes:

- normalized incoming messages into `conversations`, `message_events_raw`, and
  `messages`;
- handled bot responses into `bot_responses`;
- async items into `message_outbox`;
- memory data into `memory_*` tables.

Persistence failures are logged and treated as non-fatal for chat routing.

## Memory And AI

Memory admin commands are checked before deterministic and remote modules.
`/memory` and `/记忆` cover status, search, user lookup, lifecycle/debug,
extraction, forget commands, and per-group enable/disable.

For the clean API-style AI runtime contract, see
[AI Runtime API](ai-runtime-api.md).
For memory lifecycle states, extractor JSON, and scoring, see
[Memory Lifecycle API](memory-api.md).

Memory recall is used by AI only when `MEMORY_ENABLED` is truthy, `DATABASE_URL`
is configured, memory tables are available, and the current group has not
disabled memory. Normal AI recall includes only `status='active'` memories whose
`lifecycle_status` is `confirmed` or `reinforced`. Recall failures are logged
and converted to an empty memory context so AI routing can continue.

Memory command examples:

```text
/memory
/memory status
/memory search 高德
/memory search 高德 --status weak
/memory show 42
/memory user 10001
/memory lifecycle status
/memory lifecycle confirm 42
/memory lifecycle archive 42
/memory lifecycle stale 42
/memory lifecycle decay 30
/memory debug recall 高德
/memory extract
/memory extract 50
/memory forget 42
/memory forget-user 10001
/memory forget-group
/memory enable
/memory disable

/记忆 status
/记忆 search 天气
```

Command behavior:

| Command | Scope | Description |
| --- | --- | --- |
| `status` or empty | private/group | Shows whether memory is enabled for the current scope and active memory count. |
| `search <关键词> [--status ...]` | private/group | Searches recallable active memories by default; `--status` can inspect `weak`, `confirmed`, `reinforced`, `stale`, `contradicted`, `archived`, or `all`. |
| `show <id>` | private/group | Shows one memory's class, lifecycle, quality fields, evidence IDs, and content. |
| `user <QQ>` | group only | Lists memories for one user in the current group. |
| `lifecycle status` | private/group | Counts visible memories by lifecycle status. |
| `lifecycle confirm <id>` / `confirm <id>` | private/group | Marks a visible memory `confirmed`. |
| `lifecycle archive <id>` / `archive <id>` | private/group | Archives a visible memory. |
| `lifecycle stale <id>` / `stale <id>` | private/group | Marks a visible memory `stale`. |
| `lifecycle decay [days]` / `decay [days]` | private/group | Applies age-based decay and may mark rows stale or archived. |
| `debug recall <文本>` | private/group | Shows recall score breakdown for eligible and ineligible candidates. |
| `extract [数量]` | group only | Starts background extraction from recent persisted group messages. Limit must be 10 to 200 when provided. |
| `forget <id>` | private/group | Deletes one memory visible in the current group; configured memory admins may also delete global memory. |
| `forget-user <QQ>` | group only | Deletes memories for one user in the current group. |
| `forget-group` | group only | Deletes group-scoped memories for the current group. |
| `enable` / `disable` | group only | Enables or disables recall/extraction for the current group. |

AI runtime is disabled by default. When enabled, configured aliases such as
`/ai`, `/chat`, and `/聊天` call an OpenAI-compatible
`/v1/chat/completions` endpoint with recent persisted messages and recalled
memories. `AI_BASE_URL` may be the service root, a `/v1` URL, or a full
`/chat/completions` URL; Brain normalizes it before posting.

AI trigger matrix:

| Trigger | Default | Env | Behavior when disabled or denied |
| --- | --- | --- | --- |
| Command alias | enabled by aliases `ai`, `chat`, `聊天` | `AI_COMMAND_ALIASES` | Command triggers return a text error for disabled AI, missing config, group denial, or upstream failure. |
| Bot mention | enabled | `AI_MENTION_TRIGGER_ENABLED` | Mention triggers silently fall through when disabled, denied, missing config, or upstream failure. |
| Reply to message | disabled | `AI_REPLY_TRIGGER_ENABLED` | Reply triggers silently fall through when disabled, denied, missing config, or upstream failure. |

AI group policy uses `AI_GROUP_BLOCKLIST` first, then `AI_GROUP_ALLOWLIST`.
Private messages are allowed unless a group context is present.

Environment table:

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | empty | Enables message persistence, outbox storage, and memory tables when configured. |
| `MEMORY_ENABLED` | `true` | Enables memory recall for AI context. `0`, `false`, `no`, and `off` disable it. |
| `MEMORY_RECALL_LIFECYCLE_FILTER_ENABLED` | `true` | Keeps AI recall limited to `confirmed` and `reinforced`; set false only as a temporary rollout fallback. |
| `MEMORY_ADMIN_USER_IDS` | empty | Comma, semicolon, or whitespace separated QQ IDs allowed to run memory admin commands; group sender roles `admin` and `owner` are also accepted. |
| `MEMORY_EXTRACTOR_ENABLED` | `false` | Enables `/memory extract`; otherwise extraction reports configuration unavailable. |
| `MEMORY_EXTRACTOR_BASE_URL` | falls back to `AI_BASE_URL` | OpenAI-compatible base URL for extraction. |
| `MEMORY_EXTRACTOR_API_KEY` | falls back to `AI_API_KEY` | Optional bearer token for extraction. |
| `MEMORY_EXTRACTOR_MODEL` | falls back to `AI_MODEL` | Model used by extraction. |
| `MEMORY_EXTRACTOR_TIMEOUT` | service default | HTTP timeout for extraction model calls. |
| `MEMORY_EXTRACTOR_BATCH_SIZE` | service default | Number of messages sent per extraction batch. |
| `MEMORY_EXTRACTOR_MAX_CANDIDATES` | service default | Maximum candidate memories requested from the extractor, clamped to at least 1. |
| `AI_ENABLED` | `false` | Enables AI runtime after deterministic and remote module routing. |
| `AI_BASE_URL` | empty | OpenAI-compatible endpoint root, `/v1`, or `/chat/completions` URL. Required when AI is enabled. |
| `AI_API_KEY` | empty | Optional bearer token for the AI endpoint. |
| `AI_MODEL` | empty | Chat completion model. Required when AI is enabled. |
| `AI_TIMEOUT` | `20` | HTTP timeout for AI chat completion calls. |
| `AI_TEMPERATURE` | `0.7` | Chat completion temperature. |
| `AI_MAX_TOKENS` | `800` | Maximum generated tokens. |
| `AI_SYSTEM_PROMPT` | built-in Chinese TestBot prompt | Custom system prompt; Brain appends a safety prompt after it. |
| `AI_COMMAND_ALIASES` | `ai,chat,聊天` | Command aliases parsed by the shared command parser. |
| `AI_MENTION_TRIGGER_ENABLED` | `true` | Enables AI when the bot `self_id` appears in `at_user_ids`. |
| `AI_REPLY_TRIGGER_ENABLED` | `false` | Enables AI for messages that reply to another message. |
| `AI_GROUP_BLOCKLIST` | empty | Groups where AI must not answer. |
| `AI_GROUP_ALLOWLIST` | empty | If non-empty, AI answers only in listed groups. |
