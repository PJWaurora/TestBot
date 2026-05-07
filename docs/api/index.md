# API Docs Index

This directory documents TestBot service contracts from the current code. The
docs focus on wire shapes, routes, command behavior, environment switches, and
handoffs between services.

For the full categorized documentation directory, see
[TestBot 文档目录](../README.md).

## Core

| Doc | Covers |
| --- | --- |
| [Gateway API](gateway-api.md) | NapCat WebSocket endpoint, normalized message routing, Brain response conversion, and outbox polling. |
| [Brain API](brain-api.md) | Brain FastAPI routes, `ChatRequest`, `BrainResponse`, tool aggregation, outbox, persistence, memory, and AI runtime. |
| [AI Runtime API](ai-runtime-api.md) | Brain AI trigger contract, OpenAI-compatible upstream request, memory context, env vars, and error behavior. |
| [AI 模块使用指南](ai-module-usage.zh-CN.md) | 面向使用和运维的中文指南：启用 AI、触发方式、memory context、错误行为和未来更新位置。 |
| [Memory Lifecycle API](memory-api.md) | Brain memory records, lifecycle states, admin/debug commands, extractor candidate JSON, and scoring. |
| [Module Service API](module-service-api.md) | Shared HTTP contract implemented by external modules: `/manifest`, `/handle`, `/tools`, and `/tools/call`. |
| [Database Schema](database-schema.md) | SQL migrations for conversations, messages, bot responses, outbox, memory, and pgvector. |

## External Modules And Services

| Doc | Service |
| --- | --- |
| [Bilibili Module API](../modules/bilibili-module-api.md) | `/root/testbot-module-bilibili` |
| [TSPerson Module API](../modules/tsperson-module-api.md) | `/root/testbot-module-tsperson` |
| [Weather Module API](../modules/weather-module-api.md) | `/root/testbot-module-weather` |
| [Pixiv Module API](../modules/pixiv-module-api.md) | `/root/testbot-module-pixiv` |
| [Renderer Service API](../services/renderer-service-api.md) | `/root/testbot-render-service` |
| [Media Service API](../services/media-service-api.md) | `/root/testbot-media-service` |

## Main Message Flow

```text
NapCat
  -> Go Gateway WebSocket /ws
  -> Brain POST /chat
  -> external module POST /handle, when configured
  -> BrainResponse.messages
  -> Gateway NapCat action
  -> QQ
```

Async delivery uses Brain outbox:

```text
producer service
  -> Brain POST /outbox/enqueue
  -> Gateway POST /outbox/pull
  -> NapCat action
  -> Brain POST /outbox/{id}/ack or /fail
```

Rendered and media assets are ordinary HTTP URLs. NapCat must be able to fetch
the returned URLs from its own runtime environment.
