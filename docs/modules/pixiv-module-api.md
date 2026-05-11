# Pixiv Module API

Source: `/root/testbot-module-pixiv`

Default port in TestBot deployments: `8014`.

The Pixiv module handles ranking cards, ranking position detail lookups, multi
rank merged-forward replies, PID detail lookups, asset caching, restricted-tag
filtering, and Pixiv tool calls.

## Routes

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness check. |
| `GET` | `/manifest` | Module commands, handles, tools, and config hints. |
| `GET` | `/assets/{asset_name}` | Serves cached ranking cards and artwork images. |
| `POST` | `/handle` | Main module handler. Accepts `ChatRequest`, returns `BrainResponse`. |
| `GET` | `/tools` | Returns Pixiv tool definitions. |
| `POST` | `/tools/call` | Calls Pixiv tools. |

## Manifest

| Field | Value |
| --- | --- |
| `name` | `pixiv` |
| `version` | `0.1.0` |
| `priority` | `90` |
| `required_env` | `PIXIV_REFRESH_TOKEN` |
| `commands` | `pixiv <pid>`, `pixiv 日榜 5`, `pixiv 周榜 5`, `pixiv 月榜 5`, `pixiv 日榜 #3`, `pixiv 日榜 #1 #3 #5`, prefixed examples. |
| `handles` | Ranking text commands, ranking position lookups, PID detail lookups. |

## `POST /handle`

Supported invocations:

```text
pixiv
pixiv 帮助
pixiv <pid>
pixiv 日榜 5
pixiv 周榜 5
pixiv 月榜 5
pixiv 男性日榜 5
pixiv 女性日榜 5
pixiv 日榜 #3
pixiv 日榜 #1 #3 #5
/pixiv 日榜 5
.pixiv 日榜 5
p站 日榜 5
```

Ranking mode aliases:

| Text | Mode |
| --- | --- |
| `日榜`, `每日排行`, `排行榜`, `排行`, `排名`, `榜单` | `day` |
| `周榜` | `week` |
| `月榜` | `month` |
| `男性日榜`, `男榜` | `day_male` |
| `女性日榜`, `女榜` | `day_female` |

### Ranking Card

Request:

```json
{
  "text": "pixiv 日榜 3",
  "message_type": "group",
  "group_id": "123456"
}
```

Response:

```json
{
  "handled": true,
  "should_reply": true,
  "reply": "Pixiv 日榜 Top 3",
  "messages": [
    {
      "type": "image",
      "url": "http://127.0.0.1:8014/assets/<card>.png",
      "metadata": {
        "module": "pixiv",
        "kind": "ranking",
        "mode": "day"
      }
    }
  ],
  "metadata": {
    "module": "pixiv",
    "ok": true,
    "command": "ranking",
    "mode": "day",
    "cached": false,
    "items": []
  }
}
```

The module fetches up to `max(limit, 10) * 3`, capped at `MAX_RANK_DETAIL=100`,
then filters restricted illustrations and returns the requested number.

### Single Rank Detail

Request:

```json
{
  "text": "pixiv 日榜 #3"
}
```

Response is an image if the artwork can be downloaded and cached:

```json
{
  "handled": true,
  "should_reply": true,
  "reply": "title\nPID: 123\n作者: artist\n标签: safe\nhttps://www.pixiv.net/artworks/123",
  "messages": [
    {
      "type": "image",
      "url": "http://127.0.0.1:8014/assets/<image>.jpg",
      "metadata": {
        "module": "pixiv",
        "pid": 123
      }
    }
  ],
  "metadata": {
    "module": "pixiv",
    "ok": true,
    "command": "rank_detail",
    "mode": "day",
    "rank": 3,
    "illust": {}
  }
}
```

If image download fails, the response falls back to a text message containing
title, PID, author, tags, and Pixiv source URL.

### Multi Rank Detail Forward

Request:

```json
{
  "text": "pixiv 日榜 #1 #3 #5"
}
```

Response uses top-level `node` messages. Gateway converts these into
`send_group_forward_msg` or `send_private_forward_msg`:

```json
{
  "handled": true,
  "should_reply": true,
  "reply": "Pixiv 日榜 #1 #3 #5",
  "messages": [
    {
      "type": "node",
      "data": {
        "user_id": 0,
        "nickname": "TestBot Pixiv",
        "content": [
          {
            "type": "text",
            "data": {
              "text": "Pixiv 日榜 #1\ntitle\nPID: 3001\n作者: artist\n浏览: 123,456 / 收藏: 8,765\n标签: safe\nhttps://www.pixiv.net/artworks/3001"
            }
          },
          {
            "type": "image",
            "data": {
              "file": "http://127.0.0.1:8014/assets/<image>.jpg"
            }
          }
        ]
      }
    }
  ],
  "metadata": {
    "module": "pixiv",
    "ok": true,
    "command": "rank_detail_multi",
    "mode": "day",
    "cached": false,
    "requested_ranks": [1, 3, 5],
    "returned_ranks": [1, 3, 5],
    "items": []
  }
}
```

The module deduplicates rank markers and limits multi-rank forward requests to
`MAX_FORWARD_RANKS=10`. Forward-node artwork downloads run with bounded
parallelism and preserve returned rank order. The same bounded parallelism is
used for ranking-card thumbnail downloads.

### PID Detail

Request:

```json
{
  "text": "pixiv 12345678"
}
```

Response mirrors single rank detail but uses `command=detail`.

## Error Responses

Errors are handled replies unless group policy denies the command.

| Error | Meaning |
| --- | --- |
| `missing_refresh_token` | `PIXIV_REFRESH_TOKEN` is not configured. |
| `ranking_empty` | No non-restricted ranking entries were available. |
| `rank_not_found` | Requested rank does not exist or was filtered. |
| `illust_not_found` | PID does not exist or is inaccessible. |
| `restricted` | Illustration matched `x_restrict` or configured restricted tags. |

Group policy denial:

```json
{
  "handled": true,
  "should_reply": false,
  "metadata": {
    "module": "pixiv",
    "group_policy": "blocked",
    "group_id": "123456"
  }
}
```

## Tools

### `pixiv.get_ranking`

Arguments:

```json
{
  "mode": "day",
  "limit": 5
}
```

Returns:

```json
{
  "tool_name": "pixiv.get_ranking",
  "ok": true,
  "data": {
    "mode": "day",
    "cached": false,
    "items": []
  }
}
```

### `pixiv.get_rank_detail`

Arguments:

```json
{
  "mode": "day",
  "rank": 3
}
```

Returns `data.item`.

### `pixiv.get_illust_detail`

Arguments:

```json
{
  "illust_id": 12345678
}
```

Returns `data.illust`.

Tool errors include `invalid_mode`, `not_found`, `restricted`,
`missing_refresh_token`, and `unknown tool: <name>`.

## Asset Cache

The module caches:

- ranking cards rendered with local PIL;
- downloaded Pixiv artwork for detail and forward replies;
- thumbnail downloads for ranking cards.

Assets are served through:

```text
GET /assets/{name}
```

Asset metadata files sit beside cached files and enforce TTL. If metadata is
missing or expired, the route returns `404`.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `PIXIV_REFRESH_TOKEN` | empty | Required Pixiv OAuth refresh token. |
| `PIXIV_TIMEOUT` | `8` | Pixiv API timeout. |
| `PIXIV_TRUST_ENV_PROXY` | `true` | Use process proxy env for Pixiv HTTP client. |
| `PIXIV_HTTP_PROXY` | empty | Explicit proxy for Pixiv API requests. |
| `PIXIV_AUTH_TTL_SECONDS` | `1800` | Re-auth interval. |
| `PIXIV_DOWNLOAD_CONCURRENCY` | `4` | Bounded parallel download workers for forward artwork and ranking thumbnails. Clamped to `1-8`; set to `1` for serial downloads. |
| `PIXIV_RESTRICTED_TAGS` | built-in list | Comma/semicolon list of blocked tags. |
| `PIXIV_CACHE_TTL_MINUTES` | `60` | In-memory ranking/detail TTL. |
| `PIXIV_IMAGE_CACHE_DIR` | `/tmp/testbot-pixiv-assets` | Asset cache directory. |
| `PIXIV_IMAGE_CACHE_TTL_SECONDS` | `3600` | Asset TTL. |
| `PIXIV_ASSET_BASE_URL` | `http://127.0.0.1:8014` | Public base URL embedded in replies. |
| `PIXIV_COMMAND_PREFIXES` | `/, .` | Command prefixes. |
| `PIXIV_GROUP_ALLOWLIST` | empty | Module group allowlist. |
| `PIXIV_GROUP_BLOCKLIST` | empty | Module group blocklist. |
| `BRAIN_MODULE_PIXIV_GROUP_ALLOWLIST` | empty | Brain-scoped module allowlist. |
| `BRAIN_MODULE_PIXIV_GROUP_BLOCKLIST` | empty | Brain-scoped module blocklist. |
| `BRAIN_GROUP_ALLOWLIST` | empty | Global allowlist. |
| `BRAIN_GROUP_BLOCKLIST` | empty | Global blocklist. |

## Local Test

```bash
cd /root/testbot-module-pixiv
.venv/bin/python -m pytest
```
