# TestBot Roadmap

## Current Architecture

TestBot core stays small:

- Go Gateway receives NapCat events and sends CQ actions.
- Python Brain owns routing, policy, tools, DB/outbox APIs.
- Business modules run as external HTTP module services.
- Renderer and media downloader are shared infrastructure services, not Brain modules.

## Migrated Services

- Bilibili: external module service, renderer card support, optional media downloads.
- TSPerson: external module service, renderer card support.
- Renderer: Rust card renderer.
- Media: async Bilibili download/cache service with Brain outbox delivery.

## Active Batch

1. Bilibili legacy behavior controls
   - duplicate cooldown
   - richer detail text
   - manual download trigger
   - optional parse duration filters

2. TSPerson legacy parity
   - module-local group allow/block policy
   - status cache
   - join/leave notifications through Brain outbox

3. Weather MVP
   - `天气 <城市>` and `<城市>天气`
   - `/weather` and `.weather`
   - Amap live weather query
   - text response first, renderer card later

## Next Batches

### Steam

- External `testbot-module-steam`.
- Start with 17-digit SteamID binding and group status.
- Move old SQLite state to module-owned storage.
- Use Brain outbox for game-change notifications.
- Move image cards to renderer templates.

### HLTV

- External `testbot-module-hltv`.
- Start with read-only commands: today, live, rankings, results.
- Add provider cache and fallback tests before subscriptions.
- Add subscriptions and match notifications only after scraper stability is clear.

### Summary

- Requires message persistence first.
- MVP should be non-AI stats: message counts, active users, word frequency, hourly activity.
- AI summaries must be opt-in per group with retention and privacy limits.

### Search Image

- Requires normalized image payload support in the Brain `ChatRequest` shape.
- Must be explicit-command only and avoid storing submitted images.
- SauceNao key and API timeouts live in module env.

### Pixiv

- Start with metadata/search/ranking, not original-image caching.
- R-18/R-18G disabled by default.
- Long-lived original image cache from old SQLite should not be migrated as-is.

## Rules

- New business features go into external module repos by default.
- Go Gateway talks only to Brain.
- Python Brain talks to modules and owns policy/outbox.
- Modules may call renderer/media infrastructure.
- Secrets stay in local `.env` or `config/modules/*.env`, never in git.
