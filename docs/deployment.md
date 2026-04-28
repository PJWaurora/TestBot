# TestBot Deployment Guide

This guide covers the current split-service deployment model:

- TestBot core repository: Go Gateway, Python Brain, Postgres, migrations, and compose overlays.
- Bilibili module service: `PJWaurora/testbot-module-bilibili`.
- TSPerson module service: `PJWaurora/testbot-module-tsperson`.
- Rust renderer service: `PJWaurora/testbot-render-service`.

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
└── testbot-render-service/
```

Default compose paths expect exactly this layout:

```env
BILIBILI_MODULE_CONTEXT=../testbot-module-bilibili
TSPERSON_MODULE_CONTEXT=../testbot-module-tsperson
RENDER_SERVICE_CONTEXT=../testbot-render-service
```

## Configuration Files

There are three configuration layers.

Root `.env` in `TestBot/` is used by Docker Compose interpolation. It controls
service ports, build contexts, Docker build proxy variables, module service
registration, and renderer wiring.

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
cp config/modules/render.env.example config/modules/render.env
```

Do not commit real `.env` files or secrets.

## Core Only

Core-only mode runs Postgres, Python Brain, and Go Gateway. It does not start
Bilibili, TSPerson, or the renderer.

```bash
docker compose up -d postgres brain-python gateway-go
```

In this mode Brain loads only the local fake echo module. Normal text, Bilibili
links, and TSPerson commands remain silent unless they match the fake planner or
another configured module.

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

## Module Services

Module mode adds Bilibili and TSPerson as external HTTP services and registers
them with Brain.

Root `.env`:

```env
BRAIN_MODULE_SERVICES=bilibili=http://module-bilibili:8011,tsperson=http://module-tsperson:8012
BRAIN_MODULE_TIMEOUT=5
BILIBILI_MODULE_PORT=8011
TSPERSON_MODULE_PORT=8012
```

Start core plus modules:

```bash
docker compose -f docker-compose.yml -f docker-compose.modules.yml up -d
```

Check module health:

```bash
curl http://127.0.0.1:8011/health
curl http://127.0.0.1:8012/health
curl http://127.0.0.1:8000/tools
```

Brain applies group allow/block policy before calling remote modules. Remote
module timeouts, connection failures, non-2xx responses, and invalid JSON are
treated as no reply. Brain does not retry remote module calls, which avoids
duplicate QQ messages.

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
```

Use group allow/block lists when the module should only run in specific groups.
Blocklists win over allowlists. Empty allowlists mean all groups are allowed.

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
TS3_QUERY_PORT=13986
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

Renderer mode adds `renderer-rust` and lets Bilibili/TSPerson produce image
cards. It is optional and disabled by default.

Root `.env`:

```env
RENDERER_ENABLED=true
RENDERER_INTERNAL_BASE_URL=http://renderer-rust:8020
RENDERER_PUBLIC_BASE_URL=http://renderer-rust:8020
RENDERER_TIMEOUT=3
RENDER_SERVICE_PORT=8020
```

Start core, modules, and renderer:

```bash
docker compose -f docker-compose.yml -f docker-compose.modules.yml -f docker-compose.render.yml up -d
```

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

Run renderer:

```bash
cd ../testbot-render-service
cargo run
```

For local Brain to call local modules, set:

```env
BRAIN_MODULE_SERVICES=bilibili=http://127.0.0.1:8011,tsperson=http://127.0.0.1:8012
```

## Test Commands

Core:

```bash
cd gateway-go && go test ./...
cd brain-python && .venv/bin/python -m pytest
docker compose config
docker compose -f docker-compose.yml -f docker-compose.modules.yml config
docker compose -f docker-compose.yml -f docker-compose.modules.yml -f docker-compose.render.yml config
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

Docker build cannot download dependencies:

- Configure root `.env` Docker build proxy variables.
- If using a host-local proxy, set `DOCKER_BUILD_NETWORK=host`.
- Avoid setting runtime proxy variables for modules unless the module must use
  the proxy at runtime.
