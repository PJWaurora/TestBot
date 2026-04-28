# TestBot

TestBot is split into a Go WebSocket gateway, a Python Brain service, database assets, JSON event examples, and project documentation.

## Project Structure

```text
.
├── gateway-go/      # Go WebSocket gateway for NapCat events and replies
├── brain-python/    # FastAPI service for chat/brain behavior
├── database/        # Database initialization and schema assets
├── config/modules/  # Optional local module service env files
├── json_example/    # Example NapCat event payloads
├── docs/            # Project notes and roadmap
├── docker-compose.yml
├── docker-compose.modules.yml
├── docker-compose.render.yml
└── README.md
```

## Local Development

### Go Gateway

The gateway listens for NapCat WebSocket connections on port `808`.

```bash
cd gateway-go
go mod download
go run .
```

Optional environment overrides:

```bash
GATEWAY_LISTEN_ADDR=:808 GATEWAY_WS_PATH=/ws go run .
```

Configure the NapCat WebSocket client to connect to:

```text
ws://<host>:808/ws
```

NapCat currently runs outside this repository and is not part of the default compose setup.

### Python Brain

Create local configuration from the example file, then run the FastAPI app.

```bash
cd brain-python
cp .env.example .env
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

`brain-python/.env` is loaded by the FastAPI app for local runs. In Docker,
the root `.env` is used for Compose interpolation; Brain runtime settings such
as remote module services and module group policies live in `brain-python/.env`.

Health check:

```bash
curl http://localhost:8000/health
```

### Brain Module And Tool Runtime

The Brain service exposes tools through `GET /tools` and `POST /tools/call`. Chat requests sent to `POST /chat` are resolved by the deterministic command router first. By default, Brain core loads only the local fake echo module; `GET /tools` returns only `echo` unless remote module services are configured.

Bilibili and TSPerson are external HTTP module services, not default in-core Brain modules. Enable them through `docker-compose.modules.yml` and `BRAIN_MODULE_SERVICES`.

`BRAIN_MODULE_SERVICES` is a comma-separated list of `name=url` entries:

```text
BRAIN_MODULE_SERVICES=bilibili=http://module-bilibili:8011,tsperson=http://module-tsperson:8012
BRAIN_MODULE_TIMEOUT=5
```

For each configured module, Brain applies the core group allow/block policy before calling `POST /handle` on the remote service with the existing `ChatRequest` JSON shape. Remote service failures, timeouts, non-2xx responses, and invalid JSON are logged and treated as no reply with no retries.

`GET /tools` returns the local fake echo tool plus tools discovered from each remote module service's `GET /tools`. `POST /tools/call` forwards remote tool calls to the owning service by discovered tool name; remote call failures return `ToolResult(ok=false)`.

Command signatures use `BRAIN_COMMAND_PREFIXES`, defaulting to `/` and `.`. When no deterministic module matches, the request falls back to the fake planner path.

The local deterministic echo command can be exercised with:

```bash
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"text": "/tool-echo runtime"}'
```

Plain text that does not match a deterministic module or fake planner command
is intentionally silent. Brain runtime settings live in `brain-python/.env`.
Per-module group policies and command prefixes can be configured with environment variables:

```text
BRAIN_COMMAND_PREFIXES
BRAIN_MODULE_SERVICES
BRAIN_MODULE_TIMEOUT
BRAIN_GROUP_ALLOWLIST
BRAIN_GROUP_BLOCKLIST
BRAIN_MODULE_BILIBILI_GROUP_ALLOWLIST
BRAIN_MODULE_BILIBILI_GROUP_BLOCKLIST
BRAIN_MODULE_TSPERSON_GROUP_ALLOWLIST
BRAIN_MODULE_TSPERSON_GROUP_BLOCKLIST
BILIBILI_GROUP_ALLOWLIST
BILIBILI_GROUP_BLOCKLIST
TSPERSON_GROUP_ALLOWLIST
TSPERSON_GROUP_BLOCKLIST
```

Use comma, semicolon, or whitespace separated group IDs. Blocklists win over
allowlists. Empty allowlists mean the module is allowed in all groups.

## Docker Compose

Copy the root example env file before running Docker:

```bash
cp .env.example .env
```

The compose setup is local-development friendly:

- `brain-python` bind-mounts `./brain-python` into `/app` and runs uvicorn with reload.
- root `.env` configures Compose interpolation; `brain-python/.env` configures Brain runtime env.
- `gateway-go` bind-mounts `./gateway-go` into `/src` and runs `go run .` with named Go cache volumes.
- database migrations are mounted into a one-shot `migrate` service.
- NapCat stores QQ data, config, and plugins under `${NAPCAT_DATA_DIR:-./napcat}`.

Docker build proxy variables in the root `.env` are optional. Leave them blank
unless the build needs to reach a local proxy; set `DOCKER_BUILD_NETWORK=host`
only for that local-proxy case.

Start Postgres, Brain, and Gateway:

```bash
docker compose up -d postgres brain-python gateway-go
```

Start the core services with the optional Bilibili and TSPerson module services:

```bash
docker compose -f docker-compose.yml -f docker-compose.modules.yml up
```

The modules compose overlay expects the module repositories to be cloned next to
this repository by default:

```text
../testbot-module-bilibili
../testbot-module-tsperson
```

Use `BILIBILI_MODULE_CONTEXT` and `TSPERSON_MODULE_CONTEXT` in the root `.env`
when the module repositories live elsewhere. The overlay publishes module ports
with `BILIBILI_MODULE_PORT` and `TSPERSON_MODULE_PORT`, defaulting to `8011` and
`8012`.

Start the core services, module services, and optional Rust renderer service:

```bash
docker compose -f docker-compose.yml -f docker-compose.modules.yml -f docker-compose.render.yml up
```

The render compose overlay expects the renderer repository to be cloned next to
this repository by default:

```text
../testbot-render-service
```

Use `RENDER_SERVICE_CONTEXT` in the root `.env` when the renderer repository
lives elsewhere. The overlay publishes the renderer port with
`RENDER_SERVICE_PORT`, defaulting to `8020`, and stores generated assets in the
`renderer-assets` volume. The renderer is configured separately from
`BRAIN_MODULE_SERVICES`; enable module-side rendering with `RENDERER_ENABLED`
and point modules at `RENDERER_INTERNAL_BASE_URL`. Set
`RENDERER_PUBLIC_BASE_URL` in the root `.env`; this is the URL embedded in image
messages and must be reachable by NapCat. The render overlay passes renderer
settings into `module-bilibili` and `module-tsperson`, but does not make Brain
depend on the renderer service.

Optional per-module env files live under `config/modules/`. Copy the examples
when you need local module-specific settings:

```bash
cp config/modules/bilibili.env.example config/modules/bilibili.env
cp config/modules/tsperson.env.example config/modules/tsperson.env
cp config/modules/render.env.example config/modules/render.env
```

Files matching `config/modules/*.env` are local-only and must not contain
committed secrets. The `.env.example` files are tracked as safe templates.

Run SQL migrations on a fresh database:

```bash
docker compose --profile tools run --rm migrate
```

Start NapCat only when you want Docker-managed NapCat:

```bash
docker compose --profile napcat up -d napcat
```

When NapCat runs in the same compose project, configure its WebSocket client to:

```text
ws://gateway-go:808/ws
```

When NapCat runs outside compose on the host, use:

```text
ws://127.0.0.1:808/ws
```

For rendered images, NapCat must be able to reach the URL returned by the
renderer. When NapCat runs in the same compose project,
`RENDERER_PUBLIC_BASE_URL=http://renderer-rust:8020` is reachable from NapCat.
When NapCat runs outside compose, set `RENDERER_PUBLIC_BASE_URL` in the root
`.env` to a host URL that NapCat can fetch, such as `http://127.0.0.1:8020`.

## Tests

Run Go tests:

```bash
cd gateway-go
go test ./...
```

Run Python tests with the local virtual environment when available:

```bash
cd brain-python
.venv/bin/python -m pytest
```

If `.venv/` does not exist, use:

```bash
cd brain-python
python3 -m pytest
```

## Documentation

See [docs/roadmap.md](docs/roadmap.md) for the current roadmap.
