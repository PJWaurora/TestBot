# TSPerson Module API

Source: `/root/testbot-module-tsperson`

Default port in TestBot deployments: `8012`.

The TSPerson module queries a configured TeamSpeak ServerQuery endpoint, returns
current server/user status, can render a status card, and can optionally send
join/leave notifications through Brain outbox.

## Routes

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness check. |
| `GET` | `/manifest` | Module commands, handles, and tools. |
| `POST` | `/handle` | Main module handler. Accepts `ChatRequest`, returns `BrainResponse`. |
| `GET` | `/tools` | Returns `tsperson.get_status`. |
| `POST` | `/tools/call` | Calls TeamSpeak status tool. |

## Manifest

| Field | Value |
| --- | --- |
| `name` | `tsperson` |
| `priority` | `50` |
| `commands` | Plain Chinese aliases plus prefixed aliases from `TSPERSON_COMMAND_PREFIXES` or `BRAIN_COMMAND_PREFIXES`. |
| `handles` | TeamSpeak status text commands, help commands, prefixed commands. |

Plain command aliases:

```text
查询人数
查询人类
ts状态
ts人数
ts在线
teamspeak状态
ts帮助
tsperson帮助
teamspeak帮助
```

Prefixed aliases include:

```text
/ts
.ts
/tsperson
/teamspeak
/ts 帮助
```

## `POST /handle`

Status request:

```json
{
  "text": "ts在线",
  "message_type": "group",
  "group_id": "123456"
}
```

Text response:

```json
{
  "handled": true,
  "should_reply": true,
  "reply": "TS 服务器：Example\n在线人数：3/32\n频道数：8\n运行时间：2天1小时\n在线用户：Alice、Bob",
  "messages": [
    {
      "type": "text",
      "text": "TS 服务器：Example\n在线人数：3/32\n频道数：8\n运行时间：2天1小时\n在线用户：Alice、Bob"
    }
  ],
  "metadata": {
    "module": "tsperson",
    "action": "status",
    "ok": true
  }
}
```

When renderer integration succeeds, the module returns an image message instead
of text messages:

```json
{
  "messages": [
    {
      "type": "image",
      "url": "http://renderer-rust:8020/v1/assets/<id>.png",
      "metadata": {
        "template": "tsperson.status"
      }
    }
  ],
  "metadata": {
    "module": "tsperson",
    "renderer": {
      "ok": true,
      "asset_url": "http://renderer-rust:8020/v1/assets/<id>.png"
    }
  }
}
```

Missing TS config:

```json
{
  "handled": true,
  "should_reply": true,
  "messages": [
    {
      "type": "text",
      "text": "TS ServerQuery 配置不完整，请设置 TS3_HOST、TS3_QUERY_USER、TS3_QUERY_PASSWORD"
    }
  ],
  "metadata": {
    "module": "tsperson",
    "action": "status",
    "ok": false,
    "error": "missing_config",
    "missing": ["TS3_HOST"]
  }
}
```

No route:

```json
{
  "handled": false,
  "should_reply": false,
  "metadata": {
    "reason": "no_route"
  }
}
```

## Tool: `tsperson.get_status`

Tool definition has no required arguments:

```json
{
  "name": "tsperson.get_status",
  "description": "Query the configured TeamSpeak ServerQuery endpoint for current online status.",
  "input_schema": {
    "type": "object",
    "properties": {},
    "additionalProperties": false
  }
}
```

Call:

```json
{
  "name": "tsperson.get_status",
  "arguments": {},
  "message_type": "group",
  "group_id": "123456"
}
```

Success:

```json
{
  "tool_name": "tsperson.get_status",
  "ok": true,
  "data": {
    "ok": true,
    "action": "status",
    "status": {
      "name": "Example",
      "platform": "Linux",
      "version": "3.x",
      "clients_online": 3,
      "max_clients": 32,
      "channels_online": 8,
      "uptime": 12345,
      "clients": [
        {
          "nickname": "Alice",
          "channel_id": 1,
          "unique_id": "..."
        }
      ],
      "channels": [
        {
          "channel_id": 1,
          "name": "Lobby",
          "total_clients": 1
        }
      ]
    }
  }
}
```

Errors include `unknown tool: <name>`, `group_policy_denied`,
`group_policy_context_required`, `missing_config`, and `provider_error`.

## Notification Poller

When enabled, the module starts a background poller during FastAPI lifespan.
It compares current TeamSpeak clients to the previous snapshot and enqueues text
notifications for configured groups:

```json
{
  "message_type": "group",
  "group_id": "123456",
  "messages": [
    {
      "type": "text",
      "text": "TS 加入：Alice\nTS 离开：Bob"
    }
  ],
  "metadata": {
    "module": "tsperson",
    "action": "notify",
    "joined": [],
    "left": []
  },
  "max_attempts": 5
}
```

The poller only runs when all are present:

```text
TSPERSON_NOTIFY_ENABLED=true
TSPERSON_NOTIFY_GROUPS=<group ids>
BRAIN_BASE_URL=<brain url>
OUTBOX_TOKEN=<shared token>
```

Group policy is applied before sending notifications.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `TS3_HOST` / `TSPERSON_HOST` | empty | TeamSpeak host. |
| `TS3_QUERY_PORT` / `TSPERSON_QUERY_PORT` | `10011` | ServerQuery port. |
| `TS3_QUERY_USER` / `TSPERSON_QUERY_USER` | empty | ServerQuery user. |
| `TS3_QUERY_PASSWORD` / `TSPERSON_QUERY_PASSWORD` | empty | ServerQuery password. |
| `TS3_VIRTUAL_SERVER_ID` / `TSPERSON_VIRTUAL_SERVER_ID` | `1` | Virtual server ID. |
| `TS3_TIMEOUT` / `TSPERSON_TIMEOUT` | `5.0` | ServerQuery timeout. |
| `TSPERSON_COMMAND_PREFIXES` | `/, .` | Command prefixes; falls back to `BRAIN_COMMAND_PREFIXES`. |
| `TSPERSON_GROUP_ALLOWLIST` | empty | Module group allowlist. |
| `TSPERSON_GROUP_BLOCKLIST` | empty | Module group blocklist. |
| `BRAIN_MODULE_TSPERSON_GROUP_ALLOWLIST` | empty | Brain-scoped module allowlist. |
| `BRAIN_MODULE_TSPERSON_GROUP_BLOCKLIST` | empty | Brain-scoped module blocklist. |
| `BRAIN_GROUP_ALLOWLIST` | empty | Global allowlist. |
| `BRAIN_GROUP_BLOCKLIST` | empty | Global blocklist. |
| `RENDERER_ENABLED` | renderer config default | Enable status image rendering. |
| `RENDERER_INTERNAL_BASE_URL` | renderer config default | Renderer base URL. |
| `RENDERER_TIMEOUT` | renderer config default | Renderer timeout. |
| `TSPERSON_NOTIFY_ENABLED` | `false` | Enable join/leave poller. |
| `TSPERSON_NOTIFY_GROUPS` | empty | Notification target groups. |
| `TSPERSON_NOTIFY_INTERVAL` | `30` | Poll interval in seconds. |
| `BRAIN_BASE_URL` | empty | Brain outbox base URL for notifications. |
| `OUTBOX_TOKEN` | empty | Brain outbox bearer token. |

## Local Test

```bash
cd /root/testbot-module-tsperson
.venv/bin/python -m pytest
```
