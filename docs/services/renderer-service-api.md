# Renderer Service API

Source: `/root/testbot-render-service`

Default port in TestBot deployments: `8020`.

The renderer service is a Rust Axum service that turns structured card data
into PNG assets. Modules use it when they want the bot to reply with a visual
card instead of plain text.

## Routes

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness check. |
| `GET` | `/v1/templates` | Lists supported card templates. |
| `POST` | `/v1/cards/render` | Renders a PNG card and returns an asset URL. |
| `GET` | `/v1/assets/{asset_id}.png` | Serves a previously rendered PNG asset. |

## Runtime Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `PORT` | `8020` | Listen port. Used before `RENDERER_PORT` when both are set. |
| `RENDERER_PORT` | `8020` | Alternate listen port variable. |
| `ASSET_DIR` | `/data/assets` | Directory for rendered PNG files. Used before `RENDERER_ASSET_DIR`. |
| `RENDERER_ASSET_DIR` | `/data/assets` | Alternate asset directory variable. |
| `RENDERER_PUBLIC_BASE_URL` | `http://127.0.0.1:8020` | Public base URL embedded in render responses. |

`RENDERER_PUBLIC_BASE_URL` is trimmed of trailing slashes before asset URLs are
built. The Gateway or NapCat runtime must be able to fetch the returned URL.

## `GET /health`

Response:

```json
{
  "status": "ok"
}
```

## `GET /v1/templates`

Response:

```json
[
  {
    "id": "bilibili.video",
    "name": "Bilibili Video",
    "description": "Cover-first Bilibili video card with title, UP owner, BV, duration, publish time, views, likes, and danmaku."
  }
]
```

Current templates:

| Template | Purpose |
| --- | --- |
| `bilibili.video` | Bilibili video card with cover, title, owner, BV, stats, and publish metadata. |
| `tsperson.status` | TeamSpeak status card with online counts and users. |
| `weather.forecast` | Weather forecast card with current conditions and forecast days. |
| `generic.summary` | Generic title, subtitle, and summary card. |

## `POST /v1/cards/render`

Request body:

| Field | Type | Description |
| --- | --- | --- |
| `template` | string | Required template ID. `template_id` is also accepted as an alias. |
| `template_version` | string/null | Optional caller-controlled template version marker. |
| `format` | string/null | Must be omitted or `png`. |
| `width` | number/null | Optional render width hint. |
| `scale` | number/null | Optional render scale hint. |
| `theme` | string/null | Optional theme hint. |
| `locale` | string/null | Optional locale hint. |
| `idempotency_key` | string/null | Stable key for cache reuse. |
| `title` | string/null | Optional top-level title. |
| `subtitle` | string/null | Optional top-level subtitle. |
| `body` | string/null | Optional top-level body text. |
| `image_url` | string/null | Optional cover image URL. |
| `data` | object/null | Template-specific structured data. |
| `metadata` | object/null | Caller metadata. |

Example:

```json
{
  "template": "weather.forecast",
  "format": "png",
  "idempotency_key": "weather:110000:2026-05-05",
  "data": {
    "city": "北京市",
    "reporttime": "2026-05-05 10:00:00",
    "casts": [
      {
        "date": "2026-05-05",
        "dayweather": "晴",
        "nightweather": "多云",
        "daytemp": "25",
        "nighttemp": "14",
        "daywind": "北",
        "daypower": "3"
      }
    ]
  }
}
```

Response:

```json
{
  "ok": true,
  "asset": {
    "id": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "media_type": "image/png",
    "width": 960,
    "height": 540,
    "bytes": 123456,
    "url": "http://127.0.0.1:8020/v1/assets/0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef.png",
    "expires_at": null
  },
  "warnings": [],
  "asset_id": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "asset_url": "http://127.0.0.1:8020/v1/assets/0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef.png"
}
```

If `idempotency_key` is present, the service hashes that key and returns the
existing PNG when it is already on disk. Without an idempotency key, the asset
ID is a SHA-256 hash of the rendered PNG bytes.

## Field Normalization

The renderer can derive display fields from `data` when top-level fields are
not supplied.

| Output field | Top-level field | Data fallback paths |
| --- | --- | --- |
| Title | `title` | `title`, `detail.title` |
| Subtitle | `subtitle` | `subtitle`, `owner.name`, `detail.owner.name`, `status` |
| Body | `body` | `summary`, `desc`, `detail.desc`, `body` |
| Cover image | `image_url` | `image_url`, `cover_url`, `pic`, `detail.pic`, `detail.cover_url`, `data.image_url`, `data.cover_url`, `data.pic` |
| Avatar image | none | `avatar_url`, `face`, `owner.face`, `detail.owner.face`, `data.avatar_url`, `data.face`, `data.owner.face` |

Remote cover and avatar images are fetched with a 5 second timeout, up to three
redirects, Bilibili-style request headers, and a 5 MiB per-image limit. If an
image cannot be fetched, the card is still rendered without it.

## Template Validation

Unknown templates return `400`.

`format` values other than `png` return `400`.

`weather.forecast` requires `data.casts` to be a non-empty array. Every cast
entry must contain:

```text
date
dayweather
nightweather
daytemp
nighttemp
daywind
daypower
```

## `GET /v1/assets/{asset_id}.png`

`asset_id` must be a 64-character hex string. The response is `image/png` with:

```text
Cache-Control: public, max-age=31536000, immutable
```

Missing assets return `404`. Invalid asset IDs return `400`.

## Module Integration

Modules usually call the renderer this way:

```text
module
  -> POST renderer /v1/cards/render
  -> BrainResponse.messages[0] image url = response.asset_url
  -> Gateway sends image segment to NapCat
```

The modules currently using renderer-compatible templates are Bilibili,
TSPerson, and Weather.

## Common Failure Modes

| Symptom | Likely Cause | Check |
| --- | --- | --- |
| Module replies with text instead of a card | Module-side `RENDERER_ENABLED` is false, renderer request failed, or template payload validation failed. | Check the module log first, then `curl http://127.0.0.1:8020/health`. |
| Render response is `400 unknown template` | Caller sent a template ID not returned by `/v1/templates`. | Compare the module template name with `GET /v1/templates`. |
| Weather card returns `400` | `weather.forecast` requires `data.casts` and required cast fields. | Inspect the module's renderer payload and verify each cast has date/weather/temp/wind fields. |
| Image in QQ is missing even though render succeeded | `RENDERER_PUBLIC_BASE_URL` is reachable from Brain/module but not from NapCat. | From the NapCat runtime, fetch the returned `asset_url`. |
| Card renders without cover/avatar | Remote image fetch timed out, exceeded 5 MiB, redirected too much, or upstream blocked the request. | The card can still be valid; inspect whether the source image URL is externally reachable. |
| Asset URL returns `404` | Asset file is absent from `ASSET_DIR`, wrong asset directory is mounted, or the ID is wrong. | Check `ASSET_DIR`/`RENDERER_ASSET_DIR` and confirm the `{asset_id}.png` file exists. |

Useful checks:

```bash
curl http://127.0.0.1:8020/health
curl http://127.0.0.1:8020/v1/templates
```

In local systemd mode, modules usually call the renderer through
`http://127.0.0.1:8020`, but returned image URLs should use a host address that
NapCat can fetch, commonly `http://host.docker.internal:8020` when NapCat runs
inside Docker.
