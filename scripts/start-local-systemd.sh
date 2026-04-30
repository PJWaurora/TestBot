#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root so systemd and Docker services can be managed." >&2
  exit 1
fi

if [[ ! -f /etc/systemd/system/testbot-brain.service ]]; then
  "$ROOT_DIR/scripts/install-local-systemd.sh"
fi

echo "Starting Docker base services: postgres + napcat..."
systemctl start testbot-compose.service

echo "Stopping Docker app containers so local services can bind ports..."
docker compose \
  -f "$ROOT_DIR/docker-compose.yml" \
  -f "$ROOT_DIR/docker-compose.modules.yml" \
  -f "$ROOT_DIR/docker-compose.render.yml" \
  -f "$ROOT_DIR/docker-compose.media.yml" \
  stop gateway-go brain-python module-bilibili module-tsperson module-weather module-pixiv renderer-rust testbot-media >/dev/null 2>&1 || true

echo "Starting local systemd services..."
systemctl restart \
  testbot-renderer.service \
  testbot-module-bilibili.service \
  testbot-module-tsperson.service \
  testbot-module-weather.service \
  testbot-module-pixiv.service \
  testbot-brain.service \
  testbot-media.service \
  testbot-gateway.service

echo
systemctl --no-pager --plain status \
  testbot-renderer.service \
  testbot-module-bilibili.service \
  testbot-module-tsperson.service \
  testbot-module-weather.service \
  testbot-module-pixiv.service \
  testbot-brain.service \
  testbot-media.service \
  testbot-gateway.service \
  | sed -n '1,120p'
