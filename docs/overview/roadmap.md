# TestBot Roadmap

## Done

- Core split is in place: Go Gateway handles NapCat events and CQ actions,
  Python Brain owns routing/policy/outbox APIs, and business features live in
  external HTTP module services.
- Bilibili runs as an external module with renderer card support and optional
  media download/cache delivery.
- TSPerson runs as an external module with renderer support and notification
  delivery through Brain outbox.
- Weather supports Amap live weather queries and renderer card responses.
- Pixiv supports ranking, detail, multi-rank forward messages, image forwarding,
  and image cache support.
- Shared Renderer service exists for card/image generation.
- Shared Media service exists for async download/cache workflows.

## Active

- Memory is implemented enough to persist and recall chat context, but still
  needs continued tuning around recall quality, admin controls, retention, and
  operational safety. The next concrete project is
  [Memory Quality Phase 1](../development/memory-quality-phase1.zh-CN.md).
- AI is available as an opt-in runtime, but still needs continued work around
  policy, trigger safety, reply ownership, cooldowns, and memory integration.
- Existing migrated modules should continue closing legacy parity gaps only when
  the behavior is still useful in the external-module model.

## Development Specs

- [Cognitive Agent Architecture Vision](../development/TestBot_Cognitive_Agent_Architecture_zh_CN.md):
  long-term target architecture. Treat it as a vision document, not current
  implementation state.
- [Cognitive Agent Phases](../development/cognitive-agent-phases.zh-CN.md):
  phase-level design for Phase 1-8, including dependencies, non-goals, and
  acceptance criteria.
- [Memory Quality Phase 1](../development/memory-quality-phase1.zh-CN.md):
  executable implementation spec for memory lifecycle, quality scoring,
  recall filtering, admin/debug surface, rollout, and tests.

## Backlog

- Steam external module: account binding, group status, module-owned storage,
  renderer cards, and outbox notifications.
- HLTV external module: read-only commands first, provider cache/fallback tests,
  then subscriptions and match notifications after scraper stability is proven.
- Summary module: start with non-AI stats from persisted messages; add AI
  summaries only as explicit opt-in group behavior.
- Search Image module: explicit-command image lookup with normalized image
  payloads, no submitted-image retention, and provider keys in module env.
- Continue improving Pixiv safety controls, cache policy, and operational limits.

## Rules

- New business features go into external module repos by default.
- Go Gateway talks only to Brain.
- Python Brain talks to modules and owns policy/outbox.
- Modules may call shared Renderer and Media infrastructure.
- Secrets stay in local `.env` or `config/modules/*.env`, never in git.
