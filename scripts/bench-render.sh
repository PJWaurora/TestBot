#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/bench-render.sh [case]

Cases:
  bili-hot       Bilibili card, shared idempotency key, high-concurrency cache-hit benchmark
  bili-cold      Bilibili card, unique idempotency keys, remote image cold-render benchmark
  weather-hot    Weather card, shared idempotency key, high-concurrency cache-hit benchmark
  weather-cold   Weather card, unique idempotency keys, cold-render benchmark
  all            Run all of the above in sequence

Examples:
  scripts/bench-render.sh bili-hot
  scripts/bench-render.sh weather-cold
  scripts/bench-render.sh all
EOF
}

case_name="${1:-all}"
case "$case_name" in
  bili-hot|bili-cold|weather-hot|weather-cold|all)
    ;;
  -h|--help|help)
    usage
    exit 0
    ;;
  *)
    echo "Unknown case: $case_name" >&2
    echo >&2
    usage >&2
    exit 2
    ;;
esac

python3 - "$case_name" <<'PY'
import json
import math
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

URL = "http://127.0.0.1:8020/v1/cards/render"

BILI_BASE = {
    "template": "bilibili.video",
    "template_version": "5",
    "format": "png",
    "width": 900,
    "scale": 2,
    "theme": "light",
    "data": {
        "title": "压力测试标题",
        "desc": "压力测试简介，用于验证 B 站卡片渲染性能。",
        "bvid": "BV1Jo9MBRE3h",
        "pic": "http://i1.hdslb.com/bfs/archive/34f1bdcc6ef1255418446db8257a08fb39f56e55.jpg",
        "avatar_url": "https://i0.hdslb.com/bfs/face/fd690f52048fd9eba8050a28c24c71815c579f98.jpg",
        "owner": {
            "name": "Alpha发条橙",
            "face": "https://i0.hdslb.com/bfs/face/fd690f52048fd9eba8050a28c24c71815c579f98.jpg",
        },
        "duration": 857,
        "pubdate": 1775210779,
        "stat": {"view": 230048, "like": 28929, "danmaku": 2168},
    },
}

WEATHER_BASE = {
    "template": "weather.forecast",
    "template_version": "1",
    "format": "png",
    "width": 1200,
    "scale": 1,
    "theme": "light",
    "data": {
        "province": "浙江",
        "city": "宁波市北仑区",
        "reporttime": "2026-04-29 08:00:00",
        "casts": [
            {
                "date": "2026-04-29",
                "week": "3",
                "dayweather": "中雨",
                "nightweather": "小雨",
                "daytemp": "15",
                "nighttemp": "13",
                "daywind": "西北",
                "daypower": "1-3",
            },
            {
                "date": "2026-04-30",
                "week": "4",
                "dayweather": "晴",
                "nightweather": "晴",
                "daytemp": "25",
                "nighttemp": "12",
                "daywind": "东南",
                "daypower": "2",
            },
            {
                "date": "2026-05-01",
                "week": "5",
                "dayweather": "晴",
                "nightweather": "晴",
                "daytemp": "24",
                "nighttemp": "14",
                "daywind": "东南",
                "daypower": "2",
            },
            {
                "date": "2026-05-02",
                "week": "6",
                "dayweather": "多云",
                "nightweather": "多云",
                "daytemp": "25",
                "nighttemp": "18",
                "daywind": "东",
                "daypower": "2",
            },
        ],
    },
}

CASES = {
    "bili-hot": {"payload": BILI_BASE, "requests": 600, "concurrency": 120, "unique_keys": False},
    "bili-cold": {"payload": BILI_BASE, "requests": 160, "concurrency": 40, "unique_keys": True},
    "weather-hot": {"payload": WEATHER_BASE, "requests": 500, "concurrency": 100, "unique_keys": False},
    "weather-cold": {"payload": WEATHER_BASE, "requests": 500, "concurrency": 100, "unique_keys": True},
}


def percentile(values, p):
    if not values:
        return 0.0
    values = sorted(values)
    k = (len(values) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return values[int(k)]
    return values[f] * (c - k) + values[c] * (k - f)


def post_json(payload):
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        URL,
        data=encoded,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            elapsed = time.perf_counter() - started
            parsed = json.loads(body)
            return {
                "ok": True,
                "status": response.status,
                "elapsed": elapsed,
                "bytes": parsed.get("asset", {}).get("bytes", 0),
            }
    except Exception as exc:  # pragma: no cover
        elapsed = time.perf_counter() - started
        return {"ok": False, "status": None, "elapsed": elapsed, "error": repr(exc)}


def make_payload(base_payload, name, index, unique_keys):
    payload = json.loads(json.dumps(base_payload))
    if unique_keys:
        payload["idempotency_key"] = f"{name}:{index}:{time.time_ns()}"
    else:
        payload["idempotency_key"] = f"{name}:shared:v1"
    return payload


def run_case(name, config):
    payload = config["payload"]
    total = config["requests"]
    concurrency = config["concurrency"]
    unique_keys = config["unique_keys"]

    warmup = post_json(make_payload(payload, name, "warmup", unique_keys))
    started = time.perf_counter()
    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(post_json, make_payload(payload, name, i, unique_keys))
            for i in range(total)
        ]
        for future in as_completed(futures):
            results.append(future.result())
    total_elapsed = time.perf_counter() - started

    ok_results = [result for result in results if result["ok"]]
    err_results = [result for result in results if not result["ok"]]
    latencies = [result["elapsed"] for result in ok_results]
    status_counts = {}
    for result in ok_results:
        status_counts[result["status"]] = status_counts.get(result["status"], 0) + 1

    print(
        json.dumps(
            {
                "name": name,
                "warmup_ok": warmup["ok"],
                "warmup_elapsed_s": round(warmup["elapsed"], 4),
                "requests": total,
                "concurrency": concurrency,
                "success": len(ok_results),
                "errors": len(err_results),
                "status_counts": status_counts,
                "throughput_rps": round(len(results) / total_elapsed, 2),
                "wall_time_s": round(total_elapsed, 3),
                "p50_ms": round(percentile(latencies, 0.50) * 1000, 2) if latencies else None,
                "p95_ms": round(percentile(latencies, 0.95) * 1000, 2) if latencies else None,
                "p99_ms": round(percentile(latencies, 0.99) * 1000, 2) if latencies else None,
                "max_ms": round(max(latencies) * 1000, 2) if latencies else None,
                "sample_errors": [result.get("error") for result in err_results[:3]],
            },
            ensure_ascii=False,
        )
    )


selected = sys.argv[1]
names = list(CASES) if selected == "all" else [selected]
for name in names:
    run_case(name, CASES[name])
PY
