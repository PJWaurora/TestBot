# Module Service API

External modules are HTTP services called by Brain. They do not talk to the Go
Gateway directly. Brain sends them the normalized `ChatRequest` shape, and they
return `BrainResponse`; Gateway later converts that response to NapCat actions.

Current module services:

| Module | Default Port | Repository |
| --- | --- | --- |
| Bilibili | `8011` | `/root/testbot-module-bilibili` |
| TSPerson | `8012` | `/root/testbot-module-tsperson` |
| Weather | `8013` | `/root/testbot-module-weather` |
| Pixiv | `8014` | `/root/testbot-module-pixiv` |

## How To Create A New Module

A practical module is a small HTTP service with one deterministic command
surface, optional tools, and no direct Gateway coupling.

Minimal skeleton:

```text
example_module/
  main.py                 # FastAPI app and required routes
  policy.py               # group allow/block helpers
  models.py               # local copies or imports of ChatRequest/BrainResponse shapes
  tests/
    test_handle.py
    test_manifest.py
```

Route shape:

```python
from fastapi import FastAPI

app = FastAPI(title="testbot-module-example")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/manifest")
def manifest():
    return {
        "name": "example",
        "display_name": "Example",
        "version": "0.1.0",
        "priority": 50,
        "commands": ["example <arg>", "/example <arg>"],
        "handles": ["example"],
        "tools": [],
        "config": {
            "required_env": [],
            "optional_env": [
                "EXAMPLE_GROUP_ALLOWLIST",
                "EXAMPLE_GROUP_BLOCKLIST",
            ],
        },
    }


@app.post("/handle")
def handle(request: dict):
    text = (request.get("text") or request.get("content") or "").strip()
    if not text.startswith("/example"):
        return {"handled": False, "should_reply": False, "metadata": {"reason": "no_route"}}
    return {
        "handled": True,
        "should_reply": True,
        "messages": [{"type": "text", "text": "ok"}],
        "metadata": {"module": "example"},
    }


@app.get("/tools")
def tools():
    return []


@app.post("/tools/call")
def call_tool(request: dict):
    return {"tool_name": request.get("name", ""), "ok": False, "error": "unknown_tool"}
```

Environment naming:

- Use an uppercase module prefix based on the manifest `name`; `example`
  becomes `EXAMPLE_*`.
- Put module-private config under that prefix, for example
  `EXAMPLE_API_KEY`, `EXAMPLE_TIMEOUT`, or `EXAMPLE_CACHE_DIR`.
- Use `EXAMPLE_GROUP_ALLOWLIST` and `EXAMPLE_GROUP_BLOCKLIST` for module-local
  group policy.
- Brain also understands `BRAIN_MODULE_EXAMPLE_GROUP_ALLOWLIST` and
  `BRAIN_MODULE_EXAMPLE_GROUP_BLOCKLIST`; use these when policy should live in
  Brain's deployment config instead of the module environment.
- If the module has tools, prefix tool names with the module name, for example
  `example.lookup`, so Brain can aggregate tools without collisions.

Brain registration:

```text
BRAIN_MODULE_SERVICES=example=http://127.0.0.1:8015
```

`BRAIN_MODULE_SERVICES` adds or overrides entries from
`BRAIN_MODULE_SERVICE_DEFAULTS`. Brain sends `/chat` requests to configured
remote modules in map order after in-core deterministic modules and before AI.
The service name in this env entry is also the name used for Brain-side group
policy env normalization.

Group policy checklist:

- Enforce policy in Brain by setting `BRAIN_MODULE_<MODULE>_GROUP_BLOCKLIST`
  or `BRAIN_MODULE_<MODULE>_GROUP_ALLOWLIST`.
- Enforce policy inside the module as well when the module exposes tools,
  async jobs, downloads, expensive upstream calls, or any route that can be
  called outside Brain.
- Treat blocklists as higher priority than allowlists.
- Treat an empty allowlist as allowed everywhere.
- Split group IDs on comma, semicolon, or whitespace, matching Brain's parser.
- Return `handled=true`, `should_reply=false`, and metadata containing
  `module`, `group_policy=blocked`, and `group_id` when denying a matched route.
- Return `handled=false`, `should_reply=false` with `reason=no_route` when the
  text does not belong to the module.

Asset URL rules:

- Return URLs that NapCat can fetch, not URLs reachable only from Brain.
- In Docker, prefer compose service DNS names shared with the NapCat network,
  for example `http://module-example:8015/assets/card.png`.
- In local mixed Docker/systemd runs, use a host address visible to NapCat, such
  as `host.docker.internal` or a LAN/public URL.
- Do not return local filesystem paths unless Gateway/NapCat can read the same
  path.
- Serve stable asset routes such as `GET /assets/{name}` with the correct
  content type and keep cached files long enough for Gateway delivery retries.
- Put the primary media URL in `url` or `file`; `reply` should only be fallback
  text.

Tests to add:

- `GET /health` returns `{"status": "ok"}`.
- `GET /manifest` includes the stable `name`, command examples, tool names, and
  required/optional env hints.
- `/handle` returns the no-route response for unrelated text.
- `/handle` returns a text/media `BrainResponse` for each supported command.
- Group blocklist wins over allowlist and produces a silent handled denial.
- Empty allowlist allows group messages.
- Asset responses use absolute URLs reachable from the intended deployment
  network.
- `/tools` and `/tools/call` cover known tools, unknown tools, bad arguments,
  missing config, and group-policy denial.

## Required Routes

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness check. |
| `GET` | `/manifest` | Module metadata, commands, handles, tools, and config hints. |
| `POST` | `/handle` | Main deterministic handler. Accepts `ChatRequest`, returns `BrainResponse`. |
| `GET` | `/tools` | Tool definitions owned by the module. |
| `POST` | `/tools/call` | Tool call endpoint. Accepts `ToolCallRequest`, returns `ToolResult`. |

Some modules also expose assets, for example `GET /assets/{name}`.

## `GET /health`

Response:

```json
{
  "status": "ok"
}
```

## `GET /manifest`

Common shape:

```json
{
  "name": "weather",
  "display_name": "天气查询",
  "version": "0.1.0",
  "priority": 60,
  "tools": [],
  "commands": ["天气 <城市>", "/weather <城市>"],
  "handles": ["weather help"],
  "config": {
    "required_env": ["WEATHER_AMAP_KEY"],
    "optional_env": ["WEATHER_TIMEOUT"]
  }
}
```

Brain currently does not require every field for routing, but the manifest is
the discovery contract for humans, tools, and future orchestration.

## `POST /handle`

Request is the Brain `ChatRequest` wire shape. Important fields for modules:

| Field | Description |
| --- | --- |
| `text` / `content` | Primary text candidates. |
| `message` / `messages` | Optional nested message items. |
| `text_segments` | Extra text candidates from Gateway. |
| `json_messages` | Parsed QQ JSON cards; Bilibili uses these heavily. |
| `message_type` | `group` or `private`. |
| `group_id` | Used for group policy. |
| `user_id` | Used for private or user-specific context. |
| `images` / `videos` / `segments` | Available when a module needs richer inputs. |

No-route response:

```json
{
  "handled": false,
  "should_reply": false,
  "metadata": {
    "reason": "no_route"
  }
}
```

Group-policy denial response:

```json
{
  "handled": true,
  "should_reply": false,
  "metadata": {
    "module": "weather",
    "group_policy": "blocked",
    "group_id": "123456"
  }
}
```

Text response:

```json
{
  "handled": true,
  "should_reply": true,
  "reply": "plain text",
  "messages": [
    {
      "type": "text",
      "text": "plain text"
    }
  ],
  "metadata": {
    "module": "example",
    "ok": true
  }
}
```

Image response:

```json
{
  "handled": true,
  "should_reply": true,
  "reply": "fallback text",
  "messages": [
    {
      "type": "image",
      "url": "http://module/assets/card.png"
    }
  ]
}
```

Forward response:

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
          {"type": "text", "data": {"text": "node body"}}
        ]
      }
    }
  ]
}
```

Gateway sends a merged forward action when all top-level messages are `node`,
or when the only top-level message is a `forward` wrapper.

## `BrainMessage`

Common module response item:

| Field | Description |
| --- | --- |
| `type` | OneBot/Gateway item type such as `text`, `image`, `video`, `node`, or `forward`. |
| `text` | Text value. |
| `content` | Alternate text/content value. |
| `file` | File or URL value. |
| `url` | Media URL. |
| `path` | Local path fallback. |
| `name` | Optional filename/display name. |
| `data` | Type-specific OneBot data. |
| `metadata` | Module diagnostic metadata, ignored by Gateway conversion. |

Gateway supports more outgoing item types than most modules use: `text`,
`image`, `video`, `record`/`audio`, `file`, `reply`, `at`, `face`, `json`,
`xml`, `markdown`, `dice`, `rps`, `music`, `contact`, `poke`, `mface`,
`node`, and `forward`.

## `GET /tools`

Returns a list of `ToolDefinition`:

```json
[
  {
    "name": "pixiv.get_ranking",
    "description": "Fetch Pixiv ranking items using a refresh-token-backed Pixiv client.",
    "input_schema": {
      "type": "object",
      "properties": {
        "mode": {"type": "string"}
      }
    }
  }
]
```

## `POST /tools/call`

Request:

```json
{
  "name": "pixiv.get_ranking",
  "arguments": {
    "mode": "day",
    "limit": 5
  },
  "message_type": "group",
  "group_id": "123456",
  "user_id": "10001"
}
```

Response:

```json
{
  "tool_name": "pixiv.get_ranking",
  "ok": true,
  "data": {
    "mode": "day",
    "items": []
  }
}
```

Modules should return `ok=false` and an `error` string for unknown tools,
policy denials, missing config, upstream errors, and bad arguments.

## Group Policy Pattern

Modules use the same group list semantics:

- module-specific blocklist wins over allowlist;
- Brain global blocklist also blocks;
- empty allowlist means allowed everywhere;
- values are comma, semicolon, or whitespace separated group IDs.

Common env names:

```text
BRAIN_GROUP_ALLOWLIST
BRAIN_GROUP_BLOCKLIST
BRAIN_MODULE_<MODULE>_GROUP_ALLOWLIST
BRAIN_MODULE_<MODULE>_GROUP_BLOCKLIST
<MODULE>_GROUP_ALLOWLIST
<MODULE>_GROUP_BLOCKLIST
```

## Asset URLs

When modules return `image`, `video`, or `file` URLs, the URL must be reachable
from NapCat, not only from Brain or Gateway. In Docker, this usually means a
service DNS name reachable by the NapCat container. In local systemd mode, it
usually means `host.docker.internal` or a host LAN/public URL.
