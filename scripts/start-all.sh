#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose is not available. Install Docker Compose v2 first." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Missing .env. Create it first:" >&2
  echo "  cp .env.example .env" >&2
  exit 1
fi

compose_files=(
  -f docker-compose.yml
  -f docker-compose.modules.yml
  -f docker-compose.render.yml
)

echo "Starting TestBot core, modules, renderer, and NapCat..."
docker compose "${compose_files[@]}" --profile napcat up -d "$@"

echo
docker compose "${compose_files[@]}" --profile napcat ps
