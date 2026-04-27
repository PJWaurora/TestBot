# TestBot

TestBot is split into a Go WebSocket gateway, a Python Brain service, database assets, JSON event examples, and project documentation.

## Project Structure

```text
.
├── gateway-go/      # Go WebSocket gateway for NapCat events and replies
├── brain-python/    # FastAPI service for chat/brain behavior
├── database/        # Database initialization and schema assets
├── json_example/    # Example NapCat event payloads
├── docs/            # Project notes and roadmap
├── docker-compose.yml
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

Health check:

```bash
curl http://localhost:8000/health
```

### Brain Tool Runtime

The Brain service exposes tools through `GET /tools` and `POST /tools/call`. Chat requests sent to `POST /chat` are resolved by the deterministic command router first; a matching command calls the selected tool, runs the tool result through a presenter, and returns the rendered `reply` and `messages`. When no deterministic command matches, the request falls back to the fake planner path so legacy tool commands and non-command chat still receive the current canned responses.

The local deterministic echo command can be exercised with:

```bash
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"text": "/tool-echo runtime"}'
```

The deterministic Bilibili module detects BV IDs, `bilibili.com/video/...`, and
`b23.tv/...` links. The TeamSpeak module handles `查询人数`, `查询人类`,
`ts状态`, `ts人数`, and `ts帮助`. TeamSpeak querying is optional and uses these
environment variables when enabled:

```text
TS3_HOST
TS3_QUERY_PORT
TS3_QUERY_USER
TS3_QUERY_PASSWORD
TS3_VIRTUAL_SERVER_ID
TS3_TIMEOUT
```

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
