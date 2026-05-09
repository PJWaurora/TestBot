# AI Runtime API

Source: `/root/TestBot/brain-python/services/ai_runtime.py`

The AI runtime is not a standalone HTTP service. It is a Brain `/chat` routing
stage that can call an OpenAI-compatible chat completions endpoint and return a
normal `BrainResponse` to Gateway.

Default state: disabled.

## Runtime Position

Brain tries AI only after deterministic routing has missed:

```text
Gateway
  -> Brain POST /chat
  -> memory admin commands
  -> in-core deterministic modules
  -> remote module services
  -> fake echo planner
  -> AI runtime
  -> no_route
```

This means normal module commands such as weather, Pixiv, Bilibili, TSPerson,
memory admin, and tool echo take priority over AI.

## Public Entry Point

AI uses Brain's existing chat API:

```text
POST /chat
Content-Type: application/json
```

There is no `/ai` HTTP route. `/ai`, `/chat`, and `/聊天` are message command
aliases inside `ChatRequest.text`.

## Trigger Matrix

| Trigger | Default | Required input | Disabled or denied behavior |
| --- | --- | --- | --- |
| Command alias | enabled | Text command matching `AI_COMMAND_ALIASES`, default `ai,chat,聊天`. Prefixes such as `/`, `.`, or bare aliases are parsed by the shared command parser. | Returns a text error for disabled AI, missing config, group denial, or upstream failure. |
| Bot mention | enabled | `self_id` is present and appears in `at_user_ids`. | Silently falls through to later/no route when disabled, denied, missing config, or upstream failure. |
| Reply trigger | disabled | `reply_to_message_id` is present and `AI_REPLY_TRIGGER_ENABLED=true`. | Silently falls through when disabled, denied, missing config, or upstream failure. |
| Proactive | not implemented | `AI_PROACTIVE_*` envs may exist, but no runtime scheduler currently calls AI proactively. | Does not trigger AI for ordinary unrouted messages. |

## Command Request Example

Gateway sends a normalized `ChatRequest` to Brain:

```json
{
  "self_id": "42",
  "text": "/ai 记得我喜欢什么？",
  "message_type": "group",
  "group_id": "613689332",
  "user_id": "854271190",
  "sender": {
    "nickname": "Aurora",
    "card": "PJW"
  }
}
```

AI strips the command alias before sending the user message upstream:

```text
记得我喜欢什么？
```

If the command has no argument, AI uses:

```text
继续。
```

## Mention Request Example

```json
{
  "self_id": "42",
  "text": "帮我总结一下刚才说了什么",
  "message_type": "group",
  "group_id": "613689332",
  "user_id": "854271190",
  "at_user_ids": ["42"]
}
```

Mention triggers keep the full text as the user message. If policy or config
denies the trigger, Brain returns `None` from the AI stage and the final `/chat`
result may be `handled=false`.

## Successful Brain Response

AI returns a normal text `BrainResponse`:

```json
{
  "handled": true,
  "should_reply": true,
  "reply": "你之前提过喜欢南京天气和 Pixiv。",
  "messages": [
    {
      "type": "text",
      "text": "你之前提过喜欢南京天气和 Pixiv。"
    }
  ],
  "metadata": {
    "module": "ai",
    "model": "test-model",
    "trigger": "command",
    "memory_count": 1,
    "recent_message_count": 1,
    "prompt_version": "ai-memory-v1"
  }
}
```

Gateway sends `messages[0]` as a normal text message.

## Upstream Chat Completions Request

Brain calls an OpenAI-compatible endpoint:

```text
POST <AI_BASE_URL>/v1/chat/completions
Content-Type: application/json
Authorization: Bearer <AI_API_KEY>
```

`AI_BASE_URL` normalization:

| Value | Final URL |
| --- | --- |
| `https://llm.example` | `https://llm.example/v1/chat/completions` |
| `https://llm.example/v1` | `https://llm.example/v1/chat/completions` |
| `https://llm.example/v1/chat/completions` | unchanged |

`Authorization` is omitted when `AI_API_KEY` is empty.

Payload shape:

```json
{
  "model": "test-model",
  "messages": [
    {
      "role": "system",
      "content": "<AI_SYSTEM_PROMPT plus built-in safety prompt>"
    },
    {
      "role": "user",
      "content": "<non-instruction context containing current ids, recent chat, and memories>"
    },
    {
      "role": "user",
      "content": "记得我喜欢什么？"
    }
  ],
  "temperature": 0.7,
  "max_tokens": 800
}
```

## Context And Memory

Before calling the model, Brain calls:

```text
memory_service.recall_context(request, user_text)
```

The returned context can include:

| Field | Shape | Used for |
| --- | --- | --- |
| `recent_messages` | array of `{sender,user_id,text}` | Recent conversation context. Brain includes up to the latest 20 items. |
| `memories` | array of `{id,content,...}` | Long-term memory snippets. |

Memory recall is available only when:

- `MEMORY_ENABLED` is truthy;
- `DATABASE_URL` is configured;
- memory migrations exist;
- the current group has not disabled memory.

Normal AI recall uses only lifecycle-reliable memories:

```text
status = 'active'
lifecycle_status IN ('confirmed', 'reinforced')
```

`weak`, `stale`, `contradicted`, and `archived` memories stay visible to admin
search/debug commands but do not enter the AI prompt by default. For the full
memory lifecycle/admin/debug contract, see [Memory Lifecycle API](memory-api.md).
During rollout, `MEMORY_RECALL_LIFECYCLE_FILTER_ENABLED=false` temporarily
loosens recall to active, non-archived lifecycle rows.

When Phase 2 vector recall is enabled, `recall_context()` can combine keyword,
FTS, and embedding candidates before reranking. AI runtime does not call the
embedding endpoint directly; it only consumes the final memory context returned
by the memory service.

If recall fails, Brain logs the failure and continues with empty memory context.

Context is put in a `user` role message and explicitly labeled as
non-instruction reference data. The system prompt also appends a safety prompt
that tells the model not to obey instructions found in recent chat or memory.

When Phase 3 conversation state is available, Brain also includes a compact
short-term state summary in the same non-instruction context. It can include
current velocity, active topics, recent speaker count, recent bot reply counts,
and `should_avoid_long_reply`. Conversation state is read-only prompt context;
AI runtime does not write state directly.

Text bounds:

| Item | Limit |
| --- | --- |
| Recent message text | `240` characters per item. |
| Memory content | `240` characters per item. |
| Sender display text | `48` characters. |

## Upstream Response Parsing

Brain reads the first choice from the upstream response.

Supported response forms:

```json
{
  "choices": [
    {
      "message": {
        "content": "hello"
      }
    }
  ]
}
```

```json
{
  "choices": [
    {
      "message": {
        "content": [
          {"type": "text", "text": "hello"}
        ]
      }
    }
  ]
}
```

```json
{
  "choices": [
    {
      "text": "hello"
    }
  ]
}
```

If the parsed reply is empty, Brain returns:

```json
{
  "handled": true,
  "should_reply": false,
  "metadata": {
    "module": "ai",
    "reason": "empty_reply"
  }
}
```

## Error Responses

Command triggers return visible text errors because the user explicitly asked
for AI.

| Situation | Reply | Metadata |
| --- | --- | --- |
| Current group denied by AI policy | `AI 未在当前群启用。` | `{"module":"ai","error":"group_policy_denied"}` |
| `AI_ENABLED` is false | `AI 当前未启用。` | `{"module":"ai","error":"disabled"}` |
| `AI_BASE_URL` or `AI_MODEL` missing | `AI 配置不完整：缺少 ...。` | `{"module":"ai","error":"missing_config","missing":[...]}` |
| Upstream timeout, bad status, invalid JSON, or invalid shape | `AI 暂时不可用。` | `{"module":"ai","error":"upstream_unavailable"}` |

Mention and reply triggers are silent on those same failures, so AI does not
spam groups when passive triggers are configured incorrectly.

## Group Policy

AI policy is separate from deterministic module policy.

| Variable | Behavior |
| --- | --- |
| `AI_GROUP_BLOCKLIST` | Blocked groups. Wins over allowlist. |
| `AI_GROUP_ALLOWLIST` | If non-empty, only listed groups are allowed. |

Group IDs are split by comma, semicolon, or whitespace.

Private messages are allowed unless a group context is present.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `AI_ENABLED` | `false` | Enables AI runtime after deterministic routes miss. |
| `AI_BASE_URL` | empty | OpenAI-compatible endpoint root, `/v1`, or full `/chat/completions` URL. Required. |
| `AI_API_KEY` | empty | Optional bearer token sent to upstream. |
| `AI_MODEL` | empty | Chat completion model. Required. |
| `AI_TIMEOUT` | `20` | Upstream request timeout in seconds. Invalid or non-positive values use default. |
| `AI_TEMPERATURE` | `0.7` | Chat completion temperature. Invalid or non-positive values use default. |
| `AI_MAX_TOKENS` | `800` | Chat completion `max_tokens`. Invalid or non-positive values use default. |
| `AI_SYSTEM_PROMPT` | built-in Chinese TestBot prompt | Custom prompt. Brain appends the built-in safety prompt after it. |
| `AI_COMMAND_ALIASES` | `ai,chat,聊天` | Command aliases. Split by comma, semicolon, or whitespace. |
| `AI_GROUP_ALLOWLIST` | empty | Allowed groups. Empty means all groups unless blocklisted. |
| `AI_GROUP_BLOCKLIST` | empty | Blocked groups. Wins over allowlist. |
| `AI_MENTION_TRIGGER_ENABLED` | `true` | Enables mention trigger. |
| `AI_REPLY_TRIGGER_ENABLED` | `false` | Enables reply trigger. |

Memory-related variables that affect AI context:

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | empty | Required for persisted recent chat and long-term memory. |
| `MEMORY_ENABLED` | `true` | Enables recall when database and memory tables are available. |
| `MEMORY_RECALL_LIFECYCLE_FILTER_ENABLED` | `true` | Default-on lifecycle recall filter. Set `false` only as a temporary rollout fallback. |
| `MEMORY_EXTRACTOR_*` | varies | Used by `/memory extract`; extracted memory can later appear in AI context. |

Currently documented but not used by the runtime scheduler:

```text
AI_PROACTIVE_ENABLED
AI_PROACTIVE_GROUP_ALLOWLIST
AI_PROACTIVE_MIN_INTERVAL_SECONDS
AI_PROACTIVE_DAILY_LIMIT
AI_PROACTIVE_SAMPLE_RATE
```

## Minimal Enablement

Example `brain-python/.env`:

```env
AI_ENABLED=true
AI_BASE_URL=https://llm.example/v1
AI_API_KEY=change-me
AI_MODEL=test-model
AI_GROUP_ALLOWLIST=613689332
AI_MENTION_TRIGGER_ENABLED=true
AI_REPLY_TRIGGER_ENABLED=false
```

Then restart Brain.

In local systemd mode:

```bash
systemctl restart testbot-brain
```

## Debugging

Useful checks:

```bash
curl http://127.0.0.1:8000/health
scripts/logs.sh -f brain
```

Direct Brain request:

```bash
curl -sS http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "/ai hello",
    "message_type": "private",
    "user_id": "10001"
  }'
```

Common symptoms:

| Symptom | Check |
| --- | --- |
| `/ai` says disabled | Set `AI_ENABLED=true` and restart Brain. |
| `/ai` says missing config | Set `AI_BASE_URL` and `AI_MODEL`; `AI_API_KEY` is optional only if upstream allows it. |
| `/ai` works in private but not group | Check `AI_GROUP_ALLOWLIST`, `AI_GROUP_BLOCKLIST`, and group ID. |
| Mention does nothing | Check `self_id`, `at_user_ids`, `AI_MENTION_TRIGGER_ENABLED`, and group policy. |
| Reply does nothing | `AI_REPLY_TRIGGER_ENABLED` defaults to false. |
| AI replies without memory | Check `DATABASE_URL`, migrations, `MEMORY_ENABLED`, group memory setting, and whether memories exist. |
| Command returns upstream unavailable | Check Brain logs for timeout/status/JSON errors and verify `AI_BASE_URL` is reachable from Brain. |
