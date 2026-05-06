# Media Service API

Source: `/root/testbot-media-service`

Default port in TestBot deployments: `8030`.

The media service downloads supported remote media, converts it to MP4,
caches the asset, and optionally enqueues an async video message through Brain
outbox. The current implemented source type is Bilibili video.

## Routes

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness check. |
| `POST` | `/v1/bilibili/jobs` | Creates a Bilibili download job. Returns `202`. |
| `GET` | `/v1/jobs/{job_id}` | Reads job status and result metadata. |
| `GET` | `/v1/assets/{asset_id}.mp4` | Serves a cached MP4 asset. |

## Runtime Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `MEDIA_CACHE_DIR` | `/data/media` | Directory for MP4 files, temp files, and the default manifest. |
| `MEDIA_PUBLIC_BASE_URL` | `http://testbot-media:8030` | Public base URL embedded in asset URLs. |
| `MEDIA_CACHE_TTL_SECONDS` | `3600` | How long completed jobs/assets remain usable. |
| `MEDIA_MAX_BYTES` | `52428800` | Default maximum MP4 size. |
| `MEDIA_MAX_DURATION_SECONDS` | `180` | Default maximum video duration. |
| `MEDIA_YTDLP_FORMAT` | `bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best` | Default yt-dlp format expression. |
| `MEDIA_MANIFEST_PATH` | `<MEDIA_CACHE_DIR>/manifest.json` | Optional custom manifest path. |
| `BRAIN_BASE_URL` | `http://brain-python:8000` | Brain base URL for outbox enqueue. |
| `OUTBOX_TOKEN` | empty | Required to send completed videos to Brain outbox. |
| `OUTBOX_TIMEOUT_SECONDS` | `5.0` | Timeout for Brain outbox enqueue. |

## `GET /health`

Response:

```json
{
  "status": "ok"
}
```

## `POST /v1/bilibili/jobs`

Creates a background job. The response status is `202` whether the job is newly
queued or served from cache.

Request body:

| Field | Type | Description |
| --- | --- | --- |
| `bvid` | string/null | Optional Bilibili BV ID. Used in the cache key when present. |
| `canonical_url` | string/null | Preferred source URL. |
| `url` | string/null | Fallback source URL. |
| `quality` | string | Quality selector. Default `480p`. `best` uses `MEDIA_YTDLP_FORMAT`. |
| `max_duration_seconds` | number/null | Per-job duration limit. Must be positive when set. |
| `max_bytes` | number/null | Per-job byte limit. Must be positive when set. |
| `target` | object | Delivery target fallback. |
| `outbox` | object | Preferred delivery target for Brain outbox. |
| `metadata` | object | Caller metadata, preserved into the job manifest. |
| `correlation_id` | string/null | Caller correlation ID. |

Either `canonical_url` or `url` must resolve to an `http` or `https` URL on
`bilibili.com`, a Bilibili subdomain, `b23.tv`, or a b23 subdomain.

Target shape:

```json
{
  "message_type": "group",
  "group_id": "123456",
  "user_id": null,
  "conversation_id": "",
  "message_id": "90001",
  "self_id": "42"
}
```

Example request:

```json
{
  "bvid": "BV1xx411c7mD",
  "canonical_url": "https://www.bilibili.com/video/BV1xx411c7mD",
  "quality": "480p",
  "max_duration_seconds": 180,
  "max_bytes": 52428800,
  "outbox": {
    "message_type": "group",
    "group_id": "123456"
  },
  "metadata": {
    "source": "bilibili-module"
  },
  "correlation_id": "message-90001"
}
```

Response body:

```json
{
  "id": "7c1ba6f5-3b1b-4f8d-a6d5-17614f5df75f",
  "status": "queued",
  "source_type": "bilibili",
  "source_url": "https://www.bilibili.com/video/BV1xx411c7mD",
  "created_at": "2026-05-05T10:00:00Z",
  "updated_at": "2026-05-05T10:00:00Z",
  "expires_at": null,
  "asset_id": null,
  "asset_url": null,
  "title": null,
  "duration_seconds": null,
  "size_bytes": null,
  "error": null,
  "metadata": {
    "bvid": "BV1xx411c7mD",
    "canonical_url": "https://www.bilibili.com/video/BV1xx411c7mD",
    "quality": "480p",
    "max_duration_seconds": 180,
    "max_bytes": 52428800,
    "target": {},
    "outbox": {
      "message_type": "group",
      "group_id": "123456",
      "user_id": null,
      "conversation_id": "",
      "message_id": null,
      "self_id": null
    },
    "cache_key": "bilibili-video:BV1xx411c7mD:480p"
  },
  "correlation_id": "message-90001",
  "outbox_status": null,
  "outbox_error": null,
  "cached": false
}
```

## Cache Behavior

The cache key is:

```text
bilibili-video:<bvid-or-source-url>:<quality>
```

When a completed non-expired job exists for the same cache key, the service
checks the requested duration and byte limits. If the cached asset is still
within limits, the service reuses it, attempts a fresh outbox delivery for the
current target, and returns the cached job with `cached=true`.

Completed jobs and assets expire after `MEDIA_CACHE_TTL_SECONDS`. Expired MP4
files are deleted during request-time cleanup.

## Job Processing

New jobs move through these statuses:

```text
queued -> processing -> completed
queued -> processing -> failed
```

Processing uses yt-dlp first. If yt-dlp fails and a BV ID can be extracted, the
service falls back to Bilibili web APIs, downloads the play URL, and converts
the result with ffmpeg.

Quality handling:

| `quality` | Behavior |
| --- | --- |
| empty or `best` | Uses `MEDIA_YTDLP_FORMAT`. |
| `<height>p` such as `480p` | Builds a yt-dlp format constrained to that height or lower. |
| any other value | Uses `MEDIA_YTDLP_FORMAT`. |

The service enforces duration and size limits before and after download where
possible. Limit failures mark the job `failed`.

## `GET /v1/jobs/{job_id}`

Returns the same `JobResponse` shape as job creation. Missing jobs return
`404` with `detail="job not found"`.

Completed job example:

```json
{
  "id": "7c1ba6f5-3b1b-4f8d-a6d5-17614f5df75f",
  "status": "completed",
  "source_type": "bilibili",
  "source_url": "https://www.bilibili.com/video/BV1xx411c7mD",
  "created_at": "2026-05-05T10:00:00Z",
  "updated_at": "2026-05-05T10:00:12Z",
  "expires_at": "2026-05-05T11:00:12Z",
  "asset_id": "30f2648d-b015-4646-b93b-5fc24698b627",
  "asset_url": "http://testbot-media:8030/v1/assets/30f2648d-b015-4646-b93b-5fc24698b627.mp4",
  "title": "Video title",
  "duration_seconds": 32.5,
  "size_bytes": 4312345,
  "error": null,
  "metadata": {},
  "correlation_id": "message-90001",
  "outbox_status": "sent",
  "outbox_error": null,
  "cached": false
}
```

## `GET /v1/assets/{asset_id}.mp4`

Serves a completed cached MP4 as:

```text
Content-Type: video/mp4
```

Missing assets, expired assets, or missing files return `404`.

## Brain Outbox Delivery

After a job completes, the media service calls:

```text
POST <BRAIN_BASE_URL>/outbox/enqueue
Authorization: Bearer <OUTBOX_TOKEN>
```

Outbox payload:

```json
{
  "message_type": "group",
  "group_id": "123456",
  "messages": [
    {
      "type": "video",
      "url": "http://testbot-media:8030/v1/assets/<asset_id>.mp4",
      "metadata": {
        "source": "testbot-media-service",
        "job_id": "<job_id>",
        "asset_id": "<asset_id>",
        "source_type": "bilibili",
        "source_url": "https://www.bilibili.com/video/BV1xx411c7mD",
        "title": "Video title",
        "duration_seconds": 32.5,
        "size_bytes": 4312345
      }
    }
  ],
  "metadata": {
    "source": "testbot-media-service",
    "job_id": "<job_id>",
    "asset_id": "<asset_id>",
    "asset_url": "http://testbot-media:8030/v1/assets/<asset_id>.mp4",
    "source_type": "bilibili",
    "source_url": "https://www.bilibili.com/video/BV1xx411c7mD",
    "bvid": "BV1xx411c7mD",
    "quality": "480p",
    "correlation_id": "message-90001"
  },
  "max_attempts": 5
}
```

`outbox_status` values recorded on the job:

| Status | Meaning |
| --- | --- |
| `sent` | Brain accepted the outbox item. |
| `failed` | Brain request failed. The error string is stored in `outbox_error`. |
| `skipped` | `OUTBOX_TOKEN` is not configured. |

## Bilibili Module Handoff

The Bilibili module creates media jobs for video forwarding:

```text
bilibili-module
  -> POST media /v1/bilibili/jobs
  -> media downloads/transcodes MP4
  -> media POSTs Brain /outbox/enqueue
  -> Gateway polls Brain /outbox/pull
  -> Gateway sends video segment to NapCat
```

## Common Failure Modes

| Symptom | Likely Cause | Check |
| --- | --- | --- |
| Job stays `queued` | Background task did not run or service process is unhealthy. | Check media service logs and `GET /v1/jobs/{job_id}`. |
| Job becomes `failed` with yt-dlp or API error | Bilibili blocked the request, source URL is unsupported, network/proxy failed, or fallback API failed. | Try the canonical URL manually from the media host and inspect the job `error`. |
| Job fails with duration or size limit | Requested media exceeds `max_duration_seconds`, `max_bytes`, or service defaults. | Compare job `duration_seconds`/`size_bytes` with request and env limits. |
| Job completes but QQ does not receive video | Brain outbox enqueue failed, Gateway did not poll outbox, or NapCat cannot fetch `asset_url`. | Check `outbox_status`, Brain `/outbox/*` logs, Gateway logs, and URL reachability from NapCat. |
| `outbox_status=skipped` | `OUTBOX_TOKEN` is not configured in media service. | Set the same `OUTBOX_TOKEN` used by Brain/Gateway and restart media. |
| `GET /v1/assets/{asset_id}.mp4` returns `404` | Asset expired, file was deleted, manifest points to a missing path, or the wrong cache dir is mounted. | Check `MEDIA_CACHE_DIR`, `MEDIA_MANIFEST_PATH`, and `MEDIA_CACHE_TTL_SECONDS`. |
| Cached job returned but target did not receive video | Cache reuse still requires a fresh outbox enqueue for the current target, which may have failed. | Check `cached=true`, `outbox_status`, and `outbox_error` in the response. |

Useful checks:

```bash
curl http://127.0.0.1:8030/health
curl http://127.0.0.1:8030/v1/jobs/<job_id>
```

In local systemd mode, the Bilibili module can call media through
`http://127.0.0.1:8030`, but `MEDIA_PUBLIC_BASE_URL` should be reachable by
NapCat, commonly `http://host.docker.internal:8030` when NapCat runs in Docker.
