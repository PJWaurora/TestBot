#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ETC_DIR="/etc/testbot"
STATE_DIR="/var/lib/testbot"
ENV_FILE="$ETC_DIR/local.env"

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Run as root so systemd units can be installed." >&2
    exit 1
  fi
}

env_value() {
  local key="$1"
  local fallback="${2:-}"
  local value=""
  if [[ -f "$ROOT_DIR/.env" ]]; then
    value="$(awk -F= -v key="$key" '$1 == key {print substr($0, length(key) + 2)}' "$ROOT_DIR/.env" | tail -n 1)"
  fi
  if [[ -n "$value" ]]; then
    printf '%s\n' "$value"
  else
    printf '%s\n' "$fallback"
  fi
}

install_env() {
  mkdir -p "$ETC_DIR" "$STATE_DIR/render-assets" "$STATE_DIR/media"

  local postgres_db postgres_user postgres_password outbox_token
  postgres_db="$(env_value POSTGRES_DB testbot)"
  postgres_user="$(env_value POSTGRES_USER testbot)"
  postgres_password="$(env_value POSTGRES_PASSWORD change-me-local-only)"
  outbox_token="$(env_value OUTBOX_TOKEN change-me-local-only)"

  umask 077
  cat >"$ENV_FILE" <<EOF
APP_ENV=local

DATABASE_URL=postgres://${postgres_user}:${postgres_password}@127.0.0.1:5432/${postgres_db}?sslmode=disable
OUTBOX_TOKEN=${outbox_token}

BRAIN_BASE_URL=http://127.0.0.1:8000
PYTHON_BRAIN_URL=http://127.0.0.1:8000
BRAIN_MODULE_SERVICE_DEFAULTS=bilibili=http://127.0.0.1:8011,tsperson=http://127.0.0.1:8012,weather=http://127.0.0.1:8013
BRAIN_MODULE_SERVICES=
BRAIN_MODULE_TIMEOUT=20

GATEWAY_LISTEN_ADDR=:808
GATEWAY_WS_PATH=/ws
GATEWAY_BRAIN_TIMEOUT_SECONDS=20

RENDERER_ENABLED=true
RENDERER_INTERNAL_BASE_URL=http://127.0.0.1:8020
RENDERER_PUBLIC_BASE_URL=http://host.docker.internal:8020
RENDERER_TIMEOUT=8
PORT=8020
ASSET_DIR=${STATE_DIR}/render-assets
RENDERER_ASSET_DIR=${STATE_DIR}/render-assets
RUST_LOG=info

BILIBILI_MEDIA_BASE_URL=http://127.0.0.1:8030
MEDIA_CACHE_DIR=${STATE_DIR}/media
MEDIA_PUBLIC_BASE_URL=http://host.docker.internal:8030
MEDIA_CACHE_TTL_SECONDS=3600
MEDIA_MAX_DURATION_SECONDS=180
MEDIA_MAX_BYTES=52428800
OUTBOX_TIMEOUT_SECONDS=5
EOF
  chmod 600 "$ENV_FILE"
}

install_binaries() {
  (cd "$ROOT_DIR/gateway-go" && go build -o /usr/local/bin/testbot-gateway .)

  local renderer_debug="/root/testbot-render-service/target/debug/testbot-render-service"
  if [[ ! -x "$renderer_debug" ]]; then
    echo "Missing renderer binary: $renderer_debug" >&2
    echo "Build it once with the Rust 1.90 toolchain before installing local services." >&2
    exit 1
  fi
  install -m 0755 "$renderer_debug" /usr/local/bin/testbot-render-service
}

write_unit() {
  local name="$1"
  local content="$2"
  printf '%s\n' "$content" >"/etc/systemd/system/${name}.service"
}

install_units() {
  write_unit testbot-compose '[Unit]
Description=TestBot Docker Base Stack (Postgres + NapCat)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/root/TestBot
RemainAfterExit=yes
TimeoutStartSec=0
TimeoutStopSec=120
ExecStart=/usr/bin/docker compose -f /root/TestBot/docker-compose.yml --profile napcat up -d --no-deps postgres napcat
ExecStop=/usr/bin/docker compose -f /root/TestBot/docker-compose.yml --profile napcat stop postgres napcat

[Install]
WantedBy=multi-user.target'

  write_unit testbot-renderer '[Unit]
Description=TestBot local Rust renderer
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/root/testbot-render-service
EnvironmentFile=/etc/testbot/local.env
ExecStart=/usr/local/bin/testbot-render-service
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target'

  write_unit testbot-module-bilibili '[Unit]
Description=TestBot local Bilibili module
After=network-online.target testbot-renderer.service
Wants=network-online.target testbot-renderer.service

[Service]
Type=simple
WorkingDirectory=/root/testbot-module-bilibili
EnvironmentFile=-/root/TestBot/config/modules/bilibili.env
EnvironmentFile=/etc/testbot/local.env
ExecStart=/root/testbot-module-bilibili/.venv/bin/python -m uvicorn bilibili_module.main:app --host 0.0.0.0 --port 8011
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target'

  write_unit testbot-module-tsperson '[Unit]
Description=TestBot local TSPerson module
After=network-online.target testbot-renderer.service
Wants=network-online.target testbot-renderer.service

[Service]
Type=simple
WorkingDirectory=/root/testbot-module-tsperson
Environment=PYTHONPATH=/root/testbot-module-tsperson/src
EnvironmentFile=-/root/TestBot/config/modules/tsperson.env
EnvironmentFile=/etc/testbot/local.env
ExecStart=/root/testbot-module-tsperson/.venv/bin/python -m uvicorn tsperson_service.app:app --host 0.0.0.0 --port 8012
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target'

  write_unit testbot-module-weather '[Unit]
Description=TestBot local Weather module
After=network-online.target testbot-renderer.service
Wants=network-online.target testbot-renderer.service

[Service]
Type=simple
WorkingDirectory=/root/testbot-module-weather
Environment=PYTHONPATH=/root/testbot-module-weather/src
EnvironmentFile=-/root/TestBot/config/modules/weather.env
EnvironmentFile=/etc/testbot/local.env
ExecStart=/root/testbot-module-weather/.venv/bin/python -m uvicorn weather_service.app:app --host 0.0.0.0 --port 8013
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target'

  write_unit testbot-brain '[Unit]
Description=TestBot local Python brain
After=network-online.target testbot-compose.service testbot-module-bilibili.service testbot-module-tsperson.service testbot-module-weather.service
Wants=network-online.target testbot-compose.service testbot-module-bilibili.service testbot-module-tsperson.service testbot-module-weather.service

[Service]
Type=simple
WorkingDirectory=/root/TestBot/brain-python
EnvironmentFile=/etc/testbot/local.env
ExecStart=/root/TestBot/brain-python/.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target'

  write_unit testbot-media '[Unit]
Description=TestBot local media service
After=network-online.target testbot-brain.service
Wants=network-online.target testbot-brain.service

[Service]
Type=simple
WorkingDirectory=/root/testbot-media-service
EnvironmentFile=-/root/TestBot/config/modules/bilibili.env
EnvironmentFile=/etc/testbot/local.env
ExecStart=/root/testbot-media-service/.venv/bin/python -m uvicorn media_service.app:app --host 0.0.0.0 --port 8030
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target'

  write_unit testbot-gateway '[Unit]
Description=TestBot local Go gateway
After=network-online.target testbot-brain.service
Wants=network-online.target testbot-brain.service

[Service]
Type=simple
WorkingDirectory=/root/TestBot/gateway-go
EnvironmentFile=/etc/testbot/local.env
ExecStart=/usr/local/bin/testbot-gateway
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target'

  systemctl daemon-reload
  systemctl enable \
    testbot-compose.service \
    testbot-renderer.service \
    testbot-module-bilibili.service \
    testbot-module-tsperson.service \
    testbot-module-weather.service \
    testbot-brain.service \
    testbot-media.service \
    testbot-gateway.service >/dev/null
}

require_root
install_env
install_binaries
install_units

echo "Installed local systemd services."
echo "Env: $ENV_FILE"
echo "Start with: $ROOT_DIR/scripts/start-local-systemd.sh"
