# TestBot Deployment Guide

This guide covers the current split-service deployment model:

- TestBot core repository: Go Gateway, Python Brain, Postgres, migrations, and compose overlays.
- Bilibili module service: `PJWaurora/testbot-module-bilibili`.
- TSPerson module service: `PJWaurora/testbot-module-tsperson`.
- Weather module service: `PJWaurora/testbot-module-weather`.
- Pixiv module service: `PJWaurora/testbot-module-pixiv`.
- Rust renderer service: `PJWaurora/testbot-render-service`.
- Media service: `PJWaurora/testbot-media-service`.

The renderer is not a Brain module. Brain talks only to module services. Module
services optionally call the renderer and return image URLs through the normal
Brain response contract.

## Repository Layout

Clone the service repositories side by side unless you override compose context
paths in the root `.env`.

```text
workspace/
├── TestBot/
├── testbot-module-bilibili/
├── testbot-module-tsperson/
├── testbot-module-weather/
├── testbot-module-pixiv/
├── testbot-render-service/
└── testbot-media-service/
```

Default compose paths expect exactly this layout:

```env
BILIBILI_MODULE_CONTEXT=../testbot-module-bilibili
TSPERSON_MODULE_CONTEXT=../testbot-module-tsperson
WEATHER_MODULE_CONTEXT=../testbot-module-weather
PIXIV_MODULE_CONTEXT=../testbot-module-pixiv
RENDER_SERVICE_CONTEXT=../testbot-render-service
MEDIA_SERVICE_CONTEXT=../testbot-media-service
```

## Configuration Files

There are three configuration layers.

Root `.env` in `TestBot/` is used by Docker Compose interpolation. It controls
service ports, build contexts, Docker build proxy variables, module service
registration, the shared outbox token, renderer wiring, and media service
wiring.

`brain-python/.env` is loaded by the Python Brain process for local runtime
configuration. In Docker, the compose overlays pass the most important Brain
settings directly to the `brain-python` container.

`config/modules/*.env` files are local-only env files mounted into module or
renderer services by compose. They are ignored by git and are the correct place
for TSPerson credentials and module-specific group policy.

Start from examples:

```bash
cp .env.example .env
cp brain-python/.env.example brain-python/.env
cp config/modules/bilibili.env.example config/modules/bilibili.env
cp config/modules/tsperson.env.example config/modules/tsperson.env
cp config/modules/weather.env.example config/modules/weather.env
cp config/modules/pixiv.env.example config/modules/pixiv.env
cp config/modules/render.env.example config/modules/render.env
```

Do not commit real `.env` files or secrets.

## Image Naming

Compose uses explicit image names for every service so local builds are easy to
reason about:

```env
POSTGRES_IMAGE=pgvector/pgvector:pg16
BRAIN_IMAGE=testbot-brain-python:latest
GATEWAY_IMAGE=testbot-gateway-go:latest
BILIBILI_MODULE_IMAGE=testbot-module-bilibili:latest
TSPERSON_MODULE_IMAGE=testbot-module-tsperson:latest
WEATHER_MODULE_IMAGE=testbot-module-weather:latest
PIXIV_MODULE_IMAGE=testbot-module-pixiv:latest
RENDER_SERVICE_IMAGE=testbot-renderer-rust:latest
MEDIA_SERVICE_IMAGE=testbot-media-service:latest
NAPCAT_IMAGE=mlikiowa/napcat-docker:latest
```

`postgres` and `migrate` intentionally share `POSTGRES_IMAGE`; `migrate` is a
one-shot SQL runner that uses the same image for `psql`. Bilibili, TSPerson,
Weather, Pixiv, and renderer are separate images because they are separate
service repositories.

## Core Only

Core-only mode runs Postgres, Python Brain, and Go Gateway. It does not start
Bilibili, TSPerson, Weather, or the renderer. On a fresh database, or after
pulling new SQL migrations, run the migration job before starting Brain:

```bash
docker compose up -d postgres
docker compose --profile tools run --rm migrate
docker compose --profile docker-app up -d brain-python gateway-go
```

In this mode Brain loads only the local fake echo module. Normal text, Bilibili
links, TSPerson commands, and Weather commands remain silent unless they match
the fake planner or another configured module.

Check services:

```bash
docker compose ps
curl http://127.0.0.1:8000/health
```

Configure NapCat WebSocket client:

```text
ws://<gateway-host>:808/ws
```

If NapCat runs in the same compose project, use:

```text
ws://gateway-go:808/ws
```

NapCat exposes three ports in compose. For public WebUI access, open only the
WebUI bind host and keep the OneBot HTTP/WebSocket ports local:

```env
NAPCAT_WEBUI_BIND_HOST=0.0.0.0
NAPCAT_HTTP_BIND_HOST=127.0.0.1
NAPCAT_WS_BIND_HOST=127.0.0.1
NAPCAT_WEBUI_PORT=6099
```

## Module Services

Module mode adds Bilibili, TSPerson, and Weather as external HTTP services and
registers them with Brain. Pixiv has a reserved compose entry, but it is kept
behind a separate `docker-pixiv` profile so existing `docker-modules` startup
does not require the new repo.

Root `.env`:

```env
BRAIN_MODULE_SERVICE_DEFAULTS=bilibili=http://module-bilibili:8011,tsperson=http://module-tsperson:8012,weather=http://module-weather:8013
# Optional Pixiv compose default after its repo is ready:
# BRAIN_MODULE_SERVICE_DEFAULTS=bilibili=http://module-bilibili:8011,tsperson=http://module-tsperson:8012,weather=http://module-weather:8013,pixiv=http://module-pixiv:8014
BRAIN_MODULE_SERVICES=
BRAIN_MODULE_TIMEOUT=20
BILIBILI_MODULE_PORT=8011
TSPERSON_MODULE_PORT=8012
WEATHER_MODULE_PORT=8013
PIXIV_MODULE_PORT=8014
OUTBOX_TOKEN=<random-shared-token>
```

Start core plus modules:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.modules.yml \
  --profile docker-app \
  --profile docker-modules \
  up -d
```

Check module health:

```bash
curl http://127.0.0.1:8011/health
curl http://127.0.0.1:8012/health
curl http://127.0.0.1:8013/health
curl http://127.0.0.1:8000/tools
```

Brain applies group allow/block policy before calling remote modules. Remote
module timeouts, connection failures, non-2xx responses, and invalid JSON are
treated as no reply. Brain does not retry remote module calls, which avoids
duplicate QQ messages.

When you want Compose-managed Pixiv later, append
`,pixiv=http://module-pixiv:8014` to `BRAIN_MODULE_SERVICE_DEFAULTS` and start
the extra profile:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.modules.yml \
  --profile docker-app \
  --profile docker-modules \
  --profile docker-pixiv \
  up -d
```

For one-off local testing, you can also leave the compose default unchanged and
set `BRAIN_MODULE_SERVICES=pixiv=http://127.0.0.1:8014`.

## Brain Outbox

Brain exposes an authenticated outbox for async messages:

```text
POST /outbox/enqueue
POST /outbox/pull
POST /outbox/{id}/ack
POST /outbox/{id}/fail
```

All outbox endpoints require `Authorization: Bearer <OUTBOX_TOKEN>` or
`X-Outbox-Token: <OUTBOX_TOKEN>`. Use the same `OUTBOX_TOKEN` for
`brain-python`, `gateway-go`, and producers such as `testbot-media`.

`/outbox/enqueue` accepts `message_type` (`group` or `private`), the target
`group_id` or `user_id`, and `messages` using the existing Brain message shape.
Outbox messages support `text`, `image`, and `video`; image/video messages must
include `file`, `url`, or `path`.

Gateway polls `/outbox/pull` every 3 seconds while a NapCat WebSocket session is
connected. It converts pulled Brain messages to the existing CQ send action,
acks after the action is accepted into the send queue, and calls `fail` when the
item cannot be converted or queued. Brain marks an item as `failed` after 5
failed delivery attempts.

## Bilibili Module

The Bilibili service handles:

- BV IDs in plain text.
- `bilibili.com/video/...` URLs.
- `b23.tv/...` short links.
- QQ miniapp JSON `meta.detail_1.qqdocurl`.
- QQ news JSON `meta.news.jumpUrl`.
- Commands such as `/bili`, `.bili`, `/bilibili`, and `.bv`.

Optional `config/modules/bilibili.env`:

```env
BILIBILI_GROUP_ALLOWLIST=
BILIBILI_GROUP_BLOCKLIST=
BILIBILI_SHORT_LINK_TIMEOUT=5
BILIBILI_TRUST_ENV_PROXY=false
BILIBILI_VIDEO_DETAIL_TIMEOUT=5
BILIBILI_VIDEO_DETAIL_TRUST_ENV_PROXY=false
BILIBILI_COMMAND_PREFIXES=/,.
RENDERER_ENABLED=false
RENDERER_INTERNAL_BASE_URL=http://renderer-rust:8020
RENDERER_TIMEOUT=8
BILIBILI_AUTO_DOWNLOAD_ENABLED=false
BILIBILI_DOWNLOAD_GROUP_ALLOWLIST=
BILIBILI_DOWNLOAD_MAX_DURATION_SECONDS=180
BILIBILI_DOWNLOAD_MAX_BYTES=52428800
BILIBILI_DOWNLOAD_QUALITY=480p
BILIBILI_MEDIA_BASE_URL=http://testbot-media:8030
```

Use group allow/block lists when the module should only run in specific groups.
Blocklists win over allowlists. Empty allowlists mean all groups are allowed.

## Weather Module

The Weather service handles:

- `天气 <城市>`
- `<城市>天气`
- `/weather <城市>`
- `.weather <城市>`
- weather tool calls such as `weather.get_live(city)` or `weather.get_live(adcode)`

Optional `config/modules/weather.env`:

```env
WEATHER_GROUP_ALLOWLIST=
WEATHER_GROUP_BLOCKLIST=
WEATHER_COMMAND_PREFIXES=/,.
WEATHER_AMAP_KEY=
WEATHER_AMAP_BASE_URL=https://restapi.amap.com/v3/weather/weatherInfo
WEATHER_TIMEOUT=5
WEATHER_TRUST_ENV_PROXY=false
# WEATHER_CITYCODE_PATH=/app/citycode.xlsx
RENDERER_ENABLED=false
RENDERER_INTERNAL_BASE_URL=http://renderer-rust:8020
RENDERER_TIMEOUT=3
```

`WEATHER_AMAP_KEY` is required for Amap weather queries. With
`RENDERER_ENABLED=true` and the renderer overlay running, the Weather module can
return rendered weather card images through the normal Brain/Gateway response
contract.

## Pixiv Module

`docker-compose.modules.yml` reserves `module-pixiv` for the separate
`testbot-module-pixiv` repository. It uses:

- compose profile `docker-pixiv`
- container port `8014`
- root `.env` keys `PIXIV_MODULE_CONTEXT`, `PIXIV_MODULE_IMAGE`, and `PIXIV_MODULE_PORT`
- optional local env file `config/modules/pixiv.env`

The tracked template now covers the current runtime knobs:

```env
PIXIV_REFRESH_TOKEN=
PIXIV_TIMEOUT=8
PIXIV_TRUST_ENV_PROXY=true
PIXIV_GROUP_ALLOWLIST=
PIXIV_GROUP_BLOCKLIST=
PIXIV_RESTRICTED_TAGS=R-18,R-18G
PIXIV_CACHE_TTL_MINUTES=60
PIXIV_IMAGE_CACHE_DIR=/tmp/testbot-pixiv-assets
PIXIV_IMAGE_CACHE_TTL_SECONDS=3600
PIXIV_ASSET_BASE_URL=http://127.0.0.1:8014
PIXIV_COMMAND_PREFIXES=/,.
```

## Media Service

Media mode adds `testbot-media` for async media workflows that enqueue
text/image/video messages back to Brain outbox.

Root `.env`:

```env
MEDIA_SERVICE_CONTEXT=../testbot-media-service
MEDIA_SERVICE_IMAGE=testbot-media-service:latest
MEDIA_SERVICE_PORT=8030
MEDIA_PUBLIC_BASE_URL=http://testbot-media:8030
OUTBOX_TOKEN=<random-shared-token>
```

Start core, modules, and media. Run migrations first if this is a fresh
database or if `database/migrations/` changed:

```bash
docker compose up -d postgres
docker compose --profile tools run --rm migrate
docker compose \
  -f docker-compose.yml \
  -f docker-compose.modules.yml \
  -f docker-compose.media.yml \
  --profile docker-app \
  --profile docker-modules \
  --profile docker-media \
  up -d
```

The media overlay passes `BRAIN_BASE_URL`, `PYTHON_BRAIN_URL`, and
`OUTBOX_TOKEN` to `testbot-media`. The service also loads
`config/modules/bilibili.env`, so Bilibili-related media settings can stay with
the Bilibili module configuration.

## TSPerson Module

The TSPerson service handles:

- `查询人数`
- `查询人类`
- `ts状态`
- `ts人数`
- `ts帮助`
- `/ts`
- `.ts`
- `/ts 帮助`

Put TeamSpeak ServerQuery credentials in `config/modules/tsperson.env`:

```env
TS3_HOST=<teamspeak-host>
TS3_QUERY_PORT=10011
TS3_QUERY_USER=
TS3_QUERY_PASSWORD=
TS3_VIRTUAL_SERVER_ID=1
TS3_TIMEOUT=5
TSPERSON_GROUP_ALLOWLIST=
TSPERSON_GROUP_BLOCKLIST=
TSPERSON_COMMAND_PREFIXES=/,.
```

Use the ServerQuery port, not the voice port. If the module returns connection
refused, verify the server IP, ServerQuery port, firewall rules, and credentials
from inside the `module-tsperson` container.

## Rust Renderer

Renderer mode adds `renderer-rust` and lets Bilibili, TSPerson, and Weather
produce image cards. It is optional and disabled by default.

Root `.env`:

```env
RENDERER_PUBLIC_BASE_URL=http://renderer-rust:8020
RENDER_SERVICE_PORT=8020
```

Enable renderer output inside each module env that should generate cards:

```env
# config/modules/bilibili.env, config/modules/tsperson.env, or config/modules/weather.env
RENDERER_ENABLED=true
RENDERER_INTERNAL_BASE_URL=http://renderer-rust:8020
RENDERER_TIMEOUT=3
```

Start core, modules, and renderer:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.modules.yml \
  -f docker-compose.render.yml \
  --profile docker-app \
  --profile docker-modules \
  --profile docker-render \
  up -d
```

Add `-f docker-compose.media.yml` only when you also want the async media
downloader and have the media service repository/config ready.

Check renderer:

```bash
curl http://127.0.0.1:8020/health
curl http://127.0.0.1:8020/v1/templates
```

Renderer API:

```text
GET  /health
GET  /v1/templates
POST /v1/cards/render
GET  /v1/assets/{id}.png
```

First templates:

- `bilibili.video`
- `tsperson.status`
- `weather.forecast`
- `generic.summary`

The renderer stores PNG assets in the `renderer-assets` Docker volume. Rendered
asset IDs are SHA-256 based. Requests with the same `idempotency_key` return the
same asset URL.

## Renderer URL Reachability

`RENDERER_INTERNAL_BASE_URL` is for module containers to call the renderer.
Inside the compose network, `http://renderer-rust:8020` is correct.

`RENDERER_PUBLIC_BASE_URL` is embedded in QQ image messages. NapCat must be able
to fetch this URL.

Use these values by deployment shape:

```text
NapCat in same compose project:
RENDERER_PUBLIC_BASE_URL=http://renderer-rust:8020

NapCat running directly on the same host:
RENDERER_PUBLIC_BASE_URL=http://127.0.0.1:8020

NapCat in a separate Docker container:
RENDERER_PUBLIC_BASE_URL=http://host.docker.internal:8020

NapCat on another machine:
RENDERER_PUBLIC_BASE_URL=http://<server-ip-or-domain>:8020
```

If QQ receives text but not images, first check whether the NapCat environment
can `curl` the public renderer URL.

## Local Development Without Docker

Run Brain:

```bash
cd brain-python
.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Run Gateway:

```bash
cd gateway-go
go run .
```

Run Bilibili module:

```bash
cd ../testbot-module-bilibili
python -m uvicorn bilibili_module.main:app --host 0.0.0.0 --port 8011 --reload
```

Run TSPerson module:

```bash
cd ../testbot-module-tsperson
python -m uvicorn tsperson_service.app:app --host 0.0.0.0 --port 8012 --reload
```

Run Weather module:

```bash
cd ../testbot-module-weather
python -m uvicorn weather_service.app:app --host 0.0.0.0 --port 8013 --reload
```

Run Pixiv module:

```bash
cd ../testbot-module-pixiv
python -m uvicorn pixiv_module.main:app --host 0.0.0.0 --port 8014 --reload
```

Run renderer:

```bash
cd ../testbot-render-service
cargo run
```

For local Brain to call local modules, set:

```env
BRAIN_MODULE_SERVICES=bilibili=http://127.0.0.1:8011,tsperson=http://127.0.0.1:8012,weather=http://127.0.0.1:8013
# Optional Pixiv during local bring-up:
# BRAIN_MODULE_SERVICES=pixiv=http://127.0.0.1:8014
```

## Test Commands

Core:

```bash
cd gateway-go && go test ./...
cd brain-python && .venv/bin/python -m pytest
docker compose config --quiet
docker compose -f docker-compose.yml -f docker-compose.modules.yml --profile docker-app --profile docker-modules config --quiet
docker compose -f docker-compose.yml -f docker-compose.modules.yml -f docker-compose.render.yml --profile docker-app --profile docker-modules --profile docker-render config --quiet
docker compose -f docker-compose.yml -f docker-compose.modules.yml -f docker-compose.media.yml --profile docker-app --profile docker-modules --profile docker-media config --quiet
docker compose -f docker-compose.yml -f docker-compose.modules.yml -f docker-compose.render.yml -f docker-compose.media.yml --profile docker-app --profile docker-modules --profile docker-render --profile docker-media --profile napcat config --quiet
```

Bilibili module:

```bash
cd ../testbot-module-bilibili
python -m pytest
docker build .
```

TSPerson module:

```bash
cd ../testbot-module-tsperson
python -m pytest
docker build .
```

Weather module:

```bash
cd ../testbot-module-weather
python -m pytest
docker build .
```

Pixiv module:

```bash
cd ../testbot-module-pixiv
python -m pytest
docker build .
```

Renderer:

```bash
cd ../testbot-render-service
cargo fmt --check
cargo test
cargo clippy --all-targets --all-features -- -D warnings
docker build .
```

## Troubleshooting

Module commands are silent:

- Check `BRAIN_MODULE_SERVICES` is set in the active environment.
- Check module health endpoints.
- Check group allow/block policy.
- Check Brain logs for remote module timeout or invalid JSON messages.

Bilibili short links do not resolve:

- Check outbound network from `module-bilibili`.
- If a proxy is required, configure it for the module container and enable the
  relevant trust-env proxy setting.

TSPerson cannot connect:

- Verify `TS3_HOST` is the TeamSpeak server host.
- Verify `TS3_QUERY_PORT` is the ServerQuery port.
- Verify credentials and virtual server ID.
- Check firewall rules from the Docker host to the TeamSpeak server.

Renderer image is not sent:

- Verify `RENDERER_ENABLED=true`.
- Verify module logs show a successful render response.
- Verify `RENDERER_PUBLIC_BASE_URL` is reachable from NapCat.
- Verify `GET /v1/assets/{id}.png` returns `image/png`.

Outbox item is not sent:

- Verify `OUTBOX_TOKEN` is set to the same value in Brain, Gateway, and the
  outbox producer.
- Verify NapCat is connected to Gateway; Gateway polls only while a WebSocket
  session is active.
- Check Brain `message_outbox.status`, `attempts`, and `last_error`.

Docker build cannot download dependencies:

- Configure root `.env` Docker build proxy variables.
- If using a host-local proxy, set `DOCKER_BUILD_NETWORK=host`.
- Avoid setting runtime proxy variables for modules unless the module must use
  the proxy at runtime.
