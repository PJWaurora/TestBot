# Weather Module API

Source: `/root/testbot-module-weather`

Default port in TestBot deployments: `8013`.

The Weather module parses Chinese weather commands, resolves city names or
Amap adcodes, calls Amap weather APIs, and optionally renders forecast cards.

## Routes

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness check. |
| `GET` | `/manifest` | Module commands, handles, tools, and config hints. |
| `POST` | `/handle` | Main module handler. Accepts `ChatRequest`, returns `BrainResponse`. |
| `GET` | `/tools` | Returns `weather.get_live`. |
| `POST` | `/tools/call` | Calls the live weather tool. |

## Manifest

| Field | Value |
| --- | --- |
| `name` | `weather` |
| `display_name` | `天气查询` |
| `priority` | `60` |
| `required_env` | `WEATHER_AMAP_KEY` |
| `commands` | `天气 <城市>`, `<城市>天气`, `help`, `天气帮助`, `/weather <城市>`, `.weather <城市>` by default. |

## `POST /handle`

Supported commands:

```text
天气 北京
北京天气
/weather 北京
.weather 北京
/weather help
天气帮助
```

Request:

```json
{
  "text": "天气 北京",
  "message_type": "group",
  "group_id": "123456"
}
```

Text response:

```json
{
  "handled": true,
  "should_reply": true,
  "reply": "北京市天气预报\n2026-05-05 周2：晴，12~23°C，风 3级\n更新时间：2026-05-05 10:00:00",
  "messages": [
    {
      "type": "text",
      "text": "北京市天气预报\n..."
    }
  ],
  "metadata": {
    "module": "weather",
    "action": "query",
    "ok": true,
    "city": "北京",
    "adcode": "110000"
  }
}
```

When renderer integration succeeds, the response uses an image message:

```json
{
  "handled": true,
  "should_reply": true,
  "reply": "北京市天气预报\n...",
  "messages": [
    {
      "type": "image",
      "url": "http://renderer-rust:8020/v1/assets/<id>.png",
      "metadata": {
        "template": "weather.forecast"
      }
    }
  ],
  "metadata": {
    "module": "weather",
    "action": "query",
    "ok": true,
    "renderer": {
      "ok": true,
      "asset_url": "http://renderer-rust:8020/v1/assets/<id>.png"
    }
  }
}
```

No route:

```json
{
  "handled": false,
  "should_reply": false,
  "metadata": {
    "reason": "no_route"
  }
}
```

Common handled error metadata:

| Error | Meaning |
| --- | --- |
| `missing_config` | `WEATHER_AMAP_KEY` or base URL missing. |
| `missing_city` | Command was recognized but no city was supplied. |
| `city_not_found` | City lookup found no match. |
| `ambiguous_city` | City lookup found multiple matches. |
| `api_error` | Amap request failed. |
| `empty_weather` | Amap returned no useful weather data. |

## Tool: `weather.get_live`

Tool definition:

```json
{
  "name": "weather.get_live",
  "description": "Query Amap live weather by Chinese city name or Amap adcode.",
  "input_schema": {
    "type": "object",
    "properties": {
      "city": {
        "type": "string",
        "description": "City name, for example 北京 or 北京市朝阳区."
      },
      "adcode": {
        "type": "string",
        "description": "Amap administrative adcode."
      }
    },
    "additionalProperties": false
  }
}
```

Call:

```json
{
  "name": "weather.get_live",
  "arguments": {
    "city": "北京"
  },
  "message_type": "group",
  "group_id": "123456"
}
```

Tool calls use live weather (`prefer_forecast=false`) and return `ToolResult`
with the raw normalized weather result in `data`.

Tool policy errors:

- `group_policy_denied`
- `group_policy_context_required`

## Amap Result Shape

Forecast success includes:

```json
{
  "ok": true,
  "action": "query",
  "city": "北京",
  "adcode": "110000",
  "city_match": {},
  "forecast": {
    "province": "北京",
    "city": "北京市",
    "reporttime": "2026-05-05 10:00:00",
    "casts": [
      {
        "date": "2026-05-05",
        "week": "2",
        "dayweather": "晴",
        "nightweather": "晴",
        "daytemp": "23",
        "nighttemp": "12",
        "daywind": "东",
        "daypower": "3"
      }
    ]
  },
  "weather": {},
  "message": "..."
}
```

Live success includes `weather` with Amap live fields such as `province`,
`city`, `weather`, `temperature`, `humidity`, `winddirection`, `windpower`, and
`reporttime`.

## Renderer Integration

When `RENDERER_ENABLED=true`, successful forecast results are posted to the
renderer template `weather.forecast`. Renderer requires `data.casts` to be a
non-empty list whose entries include:

```text
date
dayweather
nightweather
daytemp
nighttemp
daywind
daypower
```

If renderer setup or rendering fails, the module falls back to text.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `WEATHER_AMAP_KEY` | empty | Required Amap API key. |
| `WEATHER_AMAP_BASE_URL` | `https://restapi.amap.com/v3/weather/weatherInfo` | Amap weather endpoint. |
| `WEATHER_TIMEOUT` | `5` | Amap HTTP timeout. |
| `WEATHER_TRUST_ENV_PROXY` | `false` | Whether HTTP client trusts proxy env. |
| `WEATHER_CITYCODE_PATH` | bundled data | Optional citycode file path. |
| `WEATHER_COMMAND_PREFIXES` | `/, .` | Command prefixes; falls back to `BRAIN_COMMAND_PREFIXES`. |
| `WEATHER_GROUP_ALLOWLIST` | empty | Module group allowlist. |
| `WEATHER_GROUP_BLOCKLIST` | empty | Module group blocklist. |
| `BRAIN_MODULE_WEATHER_GROUP_ALLOWLIST` | empty | Brain-scoped module allowlist. |
| `BRAIN_MODULE_WEATHER_GROUP_BLOCKLIST` | empty | Brain-scoped module blocklist. |
| `BRAIN_GROUP_ALLOWLIST` | empty | Global allowlist. |
| `BRAIN_GROUP_BLOCKLIST` | empty | Global blocklist. |
| `RENDERER_ENABLED` | `false` | Enable forecast card rendering. |
| `RENDERER_INTERNAL_BASE_URL` | `http://renderer-rust:8020` | Renderer base URL. |
| `RENDERER_TIMEOUT` | `3` | Renderer timeout. |

## Local Test

```bash
cd /root/testbot-module-weather
.venv/bin/python -m pytest
```
