#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/logs.sh [options] <service>
  scripts/logs.sh list

Services:
  gateway      systemd: testbot-gateway
  brain        systemd: testbot-brain
  bilibili     systemd: testbot-module-bilibili
  ts           systemd: testbot-module-tsperson
  tsperson     systemd: testbot-module-tsperson
  weather      systemd: testbot-module-weather
  renderer     systemd: testbot-renderer
  render       systemd: testbot-renderer
  media        systemd: testbot-media
  compose      systemd: testbot-compose
  haruki       systemd: haruki-bot
  napcat       docker: testbot-napcat-1
  postgres     docker: testbot-postgres-1
  all          systemd: all local TestBot services

Options:
  -f, --follow          Follow logs
  -n, --lines <count>   Number of lines, default 200
  --since <time>        Show logs since time, e.g. "10 minutes ago"
  -h, --help            Show help

Examples:
  scripts/logs.sh gateway
  scripts/logs.sh -f bilibili
  scripts/logs.sh --since "30 minutes ago" media
  scripts/logs.sh -n 80 napcat
EOF
}

systemd_unit_for() {
  case "$1" in
    gateway) printf '%s\n' testbot-gateway.service ;;
    brain) printf '%s\n' testbot-brain.service ;;
    bilibili) printf '%s\n' testbot-module-bilibili.service ;;
    ts|tsperson) printf '%s\n' testbot-module-tsperson.service ;;
    weather) printf '%s\n' testbot-module-weather.service ;;
    renderer|render) printf '%s\n' testbot-renderer.service ;;
    media) printf '%s\n' testbot-media.service ;;
    compose) printf '%s\n' testbot-compose.service ;;
    haruki) printf '%s\n' haruki-bot.service ;;
    *) return 1 ;;
  esac
}

docker_container_for() {
  case "$1" in
    napcat) printf '%s\n' testbot-napcat-1 ;;
    postgres) printf '%s\n' testbot-postgres-1 ;;
    *) return 1 ;;
  esac
}

list_services() {
  usage | sed -n '/^Services:/,/^Options:/p' | sed '$d'
}

follow=false
lines=200
since=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--follow)
      follow=true
      shift
      ;;
    -n|--lines)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for $1" >&2
        exit 2
      fi
      lines="$2"
      shift 2
      ;;
    --since)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --since" >&2
        exit 2
      fi
      since="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      break
      ;;
  esac
done

service="${1:-}"
if [[ -z "$service" ]]; then
  usage >&2
  exit 2
fi

if [[ "$service" == "list" ]]; then
  list_services
  exit 0
fi

if [[ "$service" == "all" ]]; then
  args=(--no-pager -n "$lines")
  [[ -n "$since" ]] && args+=(--since "$since")
  $follow && args+=(-f)
  exec journalctl "${args[@]}" \
    -u testbot-gateway.service \
    -u testbot-brain.service \
    -u testbot-module-bilibili.service \
    -u testbot-module-tsperson.service \
    -u testbot-module-weather.service \
    -u testbot-renderer.service \
    -u testbot-media.service
fi

if unit="$(systemd_unit_for "$service")"; then
  args=(--no-pager -u "$unit" -n "$lines")
  [[ -n "$since" ]] && args+=(--since "$since")
  $follow && args+=(-f)
  exec journalctl "${args[@]}"
fi

if container="$(docker_container_for "$service")"; then
  args=(logs --tail "$lines")
  [[ -n "$since" ]] && args+=(--since "$since")
  $follow && args+=(-f)
  args+=("$container")
  exec docker "${args[@]}"
fi

echo "Unknown service: $service" >&2
echo >&2
list_services >&2
exit 2
