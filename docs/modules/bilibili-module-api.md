# Bilibili Module API

Source: `/root/testbot-module-bilibili`

Default port in TestBot deployments: `8011`.

The Bilibili module parses Bilibili BV IDs, video URLs, `b23.tv` short links,
and QQ JSON cards, then returns TestBot `BrainResponse` messages. It can also
call the renderer for video cards and enqueue media download jobs.

## Routes

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness check. |
| `GET` | `/manifest` | Module metadata, command aliases, handled inputs, and tool definitions. |
| `GET` | `/assets/{asset_name}` | Serves cached remote assets, used for renderer cover/avatar fetches. |
| `POST` | `/handle` | Main module handler. Accepts `ChatRequest`, returns `BrainResponse`. |
| `GET` | `/tools` | Returns `bilibili.parse_video`. |
| `POST` | `/tools/call` | Calls the parser tool. |

## Manifest

Current manifest:

| Field | Value |
| --- | --- |
| `name` | `bilibili` |
| `version` | `0.1.0` |
| `priority` | `100` |
| `commands` | Prefix + aliases from `BILIBILI_COMMAND_PREFIXES` or `BRAIN_COMMAND_PREFIXES`; aliases are `bili`, `bilibili`, `bv`, `b站`. |
| `handles` | BV IDs, Bilibili video URLs, `b23.tv` short links, QQ miniapp `meta.detail_1.qqdocurl`, QQ news `meta.news.jumpUrl`. |

## `POST /handle`

Input is Brain `ChatRequest`. The parser searches:

- `text`
- `content`
- nested `message`
- nested `messages`
- `text_segments`
- string values from `json_messages`

It recognizes:

```text
/bili <BV or URL>
.bili <BV or URL>
/bilibili <BV or URL>
/bv <BV or URL>
/b站 <BV or URL>
BV1xxxxxxxxx
https://www.bilibili.com/video/BV...
https://b23.tv/...
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

Basic video response:

```json
{
  "handled": true,
  "should_reply": true,
  "reply": "https://www.bilibili.com/video/BV1xx411c7mD",
  "messages": [
    {
      "type": "text",
      "text": "https://www.bilibili.com/video/BV1xx411c7mD"
    }
  ],
  "metadata": {
    "module": "bilibili",
    "result": {
      "kind": "video",
      "bvid": "BV1xx411c7mD",
      "canonical_url": "https://www.bilibili.com/video/BV1xx411c7mD"
    }
  }
}
```

When `RENDERER_ENABLED=true` and detail fetch/render succeeds, `messages` starts
with an image card:

```json
{
  "messages": [
    {
      "type": "image",
      "url": "http://renderer-rust:8020/v1/assets/<id>.png",
      "metadata": {
        "template": "bilibili.video",
        "bvid": "BV1xx411c7mD"
      }
    },
    {
      "type": "text",
      "text": "configured text reply"
    }
  ]
}
```

Suppressed responses are handled but silent:

```json
{
  "handled": true,
  "should_reply": false,
  "metadata": {
    "module": "bilibili",
    "reason": "cooldown"
  }
}
```

Current silent reasons include:

| Reason | Meaning |
| --- | --- |
| `cooldown` | Same BVID was seen before `BILIBILI_COOLDOWN_SECONDS` expired. |
| `duration_unknown` | Duration filter is enabled but detail fetch failed. |
| `duration_filter` | Video duration is outside configured min/max. |

## Tool: `bilibili.parse_video`

`GET /tools` returns:

```json
{
  "name": "bilibili.parse_video",
  "description": "Parse a Bilibili BV ID, bilibili.com/video URL, b23.tv short link, or QQ JSON card."
}
```

Call:

```json
{
  "name": "bilibili.parse_video",
  "arguments": {
    "text": "https://www.bilibili.com/video/BV1xx411c7mD"
  },
  "message_type": "group",
  "group_id": "123456"
}
```

Success:

```json
{
  "tool_name": "bilibili.parse_video",
  "ok": true,
  "data": {
    "kind": "video",
    "bvid": "BV1xx411c7mD",
    "canonical_url": "https://www.bilibili.com/video/BV1xx411c7mD"
  }
}
```

Errors include `unknown tool: <name>`, `group_policy_denied`, and `not_found`.

## Renderer Integration

When `RENDERER_ENABLED=true`, the module fetches video detail from:

```text
https://api.bilibili.com/x/web-interface/view?bvid=<bvid>
```

Then it posts to renderer:

```json
{
  "template": "bilibili.video",
  "template_version": "4",
  "idempotency_key": "bilibili:<bvid>:card:v4",
  "data": {
    "bvid": "BV...",
    "detail": {},
    "title": "...",
    "pic": "cached or upstream cover URL",
    "owner": {},
    "duration": 123,
    "stat": {}
  }
}
```

If rendering fails, the module still returns the configured text reply.

## Media Download Integration

The module may enqueue Bilibili MP4 jobs to the media service:

```text
POST {BILIBILI_MEDIA_BASE_URL}/v1/bilibili/jobs
```

Payload:

```json
{
  "bvid": "BV...",
  "canonical_url": "https://www.bilibili.com/video/BV...",
  "quality": "480p",
  "max_duration_seconds": 180,
  "max_bytes": 52428800,
  "target": {
    "message_type": "group",
    "group_id": "123456",
    "user_id": "10001",
    "conversation_id": ""
  },
  "outbox": {
    "message_type": "group",
    "group_id": "123456",
    "user_id": "10001",
    "message_id": "9001"
  }
}
```

Auto download requires:

- `BILIBILI_AUTO_DOWNLOAD_ENABLED=true`
- current group in `BILIBILI_DOWNLOAD_GROUP_ALLOWLIST`
- video detail duration within `BILIBILI_DOWNLOAD_MAX_DURATION_SECONDS`

Manual download requires:

- `BILIBILI_MANUAL_DOWNLOAD_ENABLED=true`
- current group in `BILIBILI_DOWNLOAD_GROUP_ALLOWLIST`
- request text contains `下载` or `download`

Media enqueue failures are ignored so normal parse replies still work.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `BILIBILI_COMMAND_PREFIXES` | `/, .` via code default | Command prefixes; falls back to `BRAIN_COMMAND_PREFIXES`. |
| `BILIBILI_SHORT_LINK_TIMEOUT` | `5` | Timeout for b23.tv resolver. |
| `BILIBILI_TRUST_ENV_PROXY` | `false` | Use process proxy env for short link requests. |
| `BILIBILI_VIDEO_DETAIL_TIMEOUT` | `5` | Video detail HTTP timeout. |
| `BILIBILI_VIDEO_DETAIL_MAX_BYTES` | `4194304` | Max detail response bytes. |
| `BILIBILI_VIDEO_DETAIL_TRUST_ENV_PROXY` | `BILIBILI_TRUST_ENV_PROXY` | Proxy env use for detail API. |
| `BILIBILI_GROUP_ALLOWLIST` | empty | Module group allowlist. |
| `BILIBILI_GROUP_BLOCKLIST` | empty | Module group blocklist. |
| `BRAIN_MODULE_BILIBILI_GROUP_ALLOWLIST` | empty | Brain-scoped module allowlist. |
| `BRAIN_MODULE_BILIBILI_GROUP_BLOCKLIST` | empty | Brain-scoped module blocklist. |
| `BRAIN_GROUP_ALLOWLIST` | empty | Global allowlist. |
| `BRAIN_GROUP_BLOCKLIST` | empty | Global blocklist. |
| `BILIBILI_COOLDOWN_SECONDS` | `0` | In-memory duplicate BVID cooldown. |
| `BILIBILI_SEND_DETAILS` | `true` | Reply with video description/detail text when detail is available. |
| `BILIBILI_SEND_LINK` | `true` | Include canonical URL in text reply. |
| `BILIBILI_PARSE_MIN_DURATION_SECONDS` | empty | Minimum duration filter. |
| `BILIBILI_PARSE_MAX_DURATION_SECONDS` | empty | Maximum duration filter. |
| `RENDERER_ENABLED` | `false` | Enable rendered video card replies. |
| `RENDERER_INTERNAL_BASE_URL` | `http://renderer-rust:8020` | Renderer base URL. |
| `RENDERER_TIMEOUT` | `8` in module README | Renderer timeout. |
| `BILIBILI_AUTO_DOWNLOAD_ENABLED` | `false` | Enable automatic media enqueue. |
| `BILIBILI_MANUAL_DOWNLOAD_ENABLED` | `false` | Enable `下载`/`download` media enqueue. |
| `BILIBILI_DOWNLOAD_GROUP_ALLOWLIST` | empty | Groups allowed to download. |
| `BILIBILI_DOWNLOAD_MAX_DURATION_SECONDS` | `180` | Media duration limit. |
| `BILIBILI_DOWNLOAD_MAX_BYTES` | `52428800` | Media size limit. |
| `BILIBILI_DOWNLOAD_QUALITY` | `480p` | Media quality label. |
| `BILIBILI_MEDIA_BASE_URL` | `http://testbot-media:8030` | Media service URL. |

## Local Test

```bash
cd /root/testbot-module-bilibili
.venv/bin/python -m pytest
```
