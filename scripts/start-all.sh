#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $# -gt 0 ]]; then
  echo "scripts/start-all.sh now starts the low-resource local deployment and does not accept docker compose flags." >&2
  echo "Use docker compose directly for full Docker development runs." >&2
  exit 1
fi

echo "Starting TestBot low-resource local deployment..."
echo "Docker: postgres + napcat"
echo "systemd: gateway, brain, modules, renderer, media"
exec "$ROOT_DIR/scripts/start-local-systemd.sh"
