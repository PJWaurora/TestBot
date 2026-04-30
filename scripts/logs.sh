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
  weather      systemd: testbot-module-weather
  pixiv        systemd: testbot-module-pixiv
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
  scripts/logs.sh all
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
    pixiv) printf '%s\n' testbot-module-pixiv.service ;;
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

label_color() {
  local label="$1"
  if [[ ! -t 1 || -n "${NO_COLOR:-}" ]]; then
    printf ''
    return
  fi

  case "$label" in
    gateway) printf '\033[36m' ;;
    brain) printf '\033[35m' ;;
    bilibili) printf '\033[34m' ;;
    ts|tsperson) printf '\033[33m' ;;
    weather) printf '\033[32m' ;;
    pixiv) printf '\033[95m' ;;
    render|renderer) printf '\033[96m' ;;
    media) printf '\033[31m' ;;
    napcat) printf '\033[92m' ;;
    postgres) printf '\033[95m' ;;
    haruki) printf '\033[93m' ;;
    *) printf '\033[37m' ;;
  esac
}

prefix_stream() {
  local label="$1"
  local color reset
  color="$(label_color "$label")"
  if [[ -n "$color" ]]; then
    reset=$'\033[0m'
  else
    reset=''
  fi

  awk -v label="$label" -v color="$color" -v reset="$reset" '
    {
      printf "%s%-10s%s | %s\n", color, label, reset, $0
      fflush()
    }
  '
}

docker_since_value() {
  local value="$1"
  if [[ -z "$value" ]]; then
    return 0
  fi
  date -d "$value" --iso-8601=seconds 2>/dev/null || printf '%s\n' "$value"
}

journalctl_args() {
  local unit="$1"
  local args=(--no-pager -o cat -u "$unit" -n "$lines")
  [[ -n "$since" ]] && args+=(--since "$since")
  $follow && args+=(-f)
  printf '%s\0' "${args[@]}"
}

run_systemd_logs() {
  local label="$1"
  local unit="$2"
  local args=()
  while IFS= read -r -d '' arg; do
    args+=("$arg")
  done < <(journalctl_args "$unit")
  journalctl "${args[@]}" | prefix_stream "$label"
}

run_docker_logs() {
  local label="$1"
  local container="$2"
  local args=(logs --tail "$lines")
  [[ -n "$since" ]] && args+=(--since "$(docker_since_value "$since")")
  $follow && args+=(-f)
  args+=("$container")
  docker "${args[@]}" 2>&1 | prefix_stream "$label"
}

run_all_logs() {
  local labels=(gateway brain bilibili ts weather pixiv render media napcat)
  local pids=()

  for label in "${labels[@]}"; do
    if unit="$(systemd_unit_for "$label")"; then
      run_systemd_logs "$label" "$unit" &
      pids+=("$!")
    elif container="$(docker_container_for "$label")"; then
      run_docker_logs "$label" "$container" &
      pids+=("$!")
    fi
  done

  trap 'kill "${pids[@]}" >/dev/null 2>&1 || true' INT TERM EXIT
  wait
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
  run_all_logs
  exit 0
fi

if unit="$(systemd_unit_for "$service")"; then
  run_systemd_logs "$service" "$unit"
  exit 0
fi

if container="$(docker_container_for "$service")"; then
  run_docker_logs "$service" "$container"
  exit 0
fi

echo "Unknown service: $service" >&2
echo >&2
list_services >&2
exit 2
