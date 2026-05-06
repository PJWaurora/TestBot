# TestBot 文档目录

这个目录按用途整理 TestBot 的项目文档。文档已按主题拆到不同子目录，
根目录保留这个总入口。

## 快速阅读顺序

| 顺序 | 文档 | 适合场景 |
| --- | --- | --- |
| 1 | [项目总览](overview/project-overview.zh-CN.md) | 先理解 TestBot 的整体目标、服务边界和当前上下文。 |
| 2 | [API 文档总览](api/index.md) | 查服务接口、模块接口、消息链路。 |
| 3 | [部署指南](deployment/deployment.zh-CN.md) | 部署整套服务。 |
| 4 | [低配本地部署](deployment/local-systemd.zh-CN.md) | 在本机或低配机器上用 systemd 跑服务。 |
| 5 | [Roadmap](overview/roadmap.md) | 查看架构迁移方向和后续计划。 |

## 项目概览与规划

| 文档 | 内容 |
| --- | --- |
| [项目总览](overview/project-overview.zh-CN.md) | 全局项目上下文、总体目标、当前架构、服务边界。 |
| [Roadmap](overview/roadmap.md) | 当前架构、已迁移服务、记忆方向、后续演进。 |
| [AI 与记忆整体设计计划](overview/ai-memory-plan.zh-CN.md) | AI 回复、记忆抽取、记忆存储与演进计划。 |

## 开发设计与实施规格

| 文档 | 内容 |
| --- | --- |
| [认知型群聊 Agent 架构愿景](development/TestBot_Cognitive_Agent_Architecture_zh_CN.md) | 长期 Agent 的目标架构；这是 vision，不代表当前全部已实现。 |
| [Cognitive Agent 分阶段设计](development/cognitive-agent-phases.zh-CN.md) | Phase 1-8 的阶段边界、依赖、非目标和验收口径。 |
| [Memory Quality Phase 1 实施规格](development/memory-quality-phase1.zh-CN.md) | 已实现 Phase 1 memory lifecycle/quality 的工程规格、状态机、迁移、命令/API 和测试计划。 |
| [Hybrid Recall Phase 2 实施规格](development/hybrid-recall-phase2.zh-CN.md) | 已实现 Phase 2 hybrid recall 的 embedding 写入、向量召回、候选合并、rerank、debug 和 rollout 计划。 |

## 核心服务 API

| 文档 | 内容 |
| --- | --- |
| [API 文档总览](api/index.md) | API 文档入口，包含主消息流和异步 outbox 流程。 |
| [Gateway API](api/gateway-api.md) | Go Gateway 的 NapCat WebSocket、消息归一化、Brain 响应转换、outbox 轮询。 |
| [Gateway API HTML](api/gateway-api.html) | Gateway API 的 HTML 版本。 |
| [Brain API](api/brain-api.md) | Brain FastAPI 路由、`/chat`、工具聚合、outbox、持久化、记忆、AI runtime。 |
| [AI Runtime API](api/ai-runtime-api.md) | AI 触发、OpenAI-compatible 请求、memory context、环境变量和错误行为。 |
| [Memory Lifecycle API](api/memory-api.md) | Memory 记录结构、生命周期状态、管理/调试命令、extractor JSON 和 scoring。 |
| [Module Service API](api/module-service-api.md) | 外部模块统一实现的 `/manifest`、`/handle`、`/tools`、`/tools/call` 合约。 |
| [Database Schema](api/database-schema.md) | PostgreSQL migrations、消息表、响应审计表、outbox、memory、pgvector。 |

## 功能模块 API

| 文档 | 模块 | 内容 |
| --- | --- | --- |
| [Bilibili Module API](modules/bilibili-module-api.md) | `/root/testbot-module-bilibili` | Bilibili 链接解析、视频卡片、媒体任务、工具调用。 |
| [TSPerson Module API](modules/tsperson-module-api.md) | `/root/testbot-module-tsperson` | TeamSpeak 在线人数查询、通知轮询、工具调用。 |
| [Weather Module API](modules/weather-module-api.md) | `/root/testbot-module-weather` | 高德天气查询、天气卡片渲染、工具调用。 |
| [Pixiv Module API](modules/pixiv-module-api.md) | `/root/testbot-module-pixiv` | Pixiv 排行榜、PID 详情、多个 rank 合并转发、图片缓存、工具调用。 |

## 支撑服务 API

| 文档 | 服务 | 内容 |
| --- | --- | --- |
| [Renderer Service API](services/renderer-service-api.md) | `/root/testbot-render-service` | 卡片渲染、模板列表、PNG asset 缓存与访问。 |
| [Media Service API](services/media-service-api.md) | `/root/testbot-media-service` | Bilibili 视频下载、MP4 缓存、Brain outbox 异步投递。 |

## 部署与运维

| 文档 | 内容 |
| --- | --- |
| [Deployment Guide](deployment/deployment.md) | 英文部署说明、仓库布局、服务运行方式。 |
| [部署指南](deployment/deployment.zh-CN.md) | 中文部署说明、拆分服务部署方式、环境变量。 |
| [低配本地部署](deployment/local-systemd.zh-CN.md) | 本机低配部署、systemd 运行形态、本地 URL 设置。 |

## 按任务查文档

| 想做的事 | 先看 |
| --- | --- |
| 理解消息从 QQ 到回复的完整链路 | [Gateway API](api/gateway-api.md)、[Brain API](api/brain-api.md)、[API 文档总览](api/index.md) |
| 写一个新外部模块 | [Module Service API](api/module-service-api.md)、任意一个功能模块 API |
| 改 Brain 路由或工具调用 | [Brain API](api/brain-api.md) |
| 配置或调试 AI 回复 | [AI Runtime API](api/ai-runtime-api.md)、[AI 与记忆整体设计计划](overview/ai-memory-plan.zh-CN.md) |
| 规划认知型 Agent 阶段 | [Cognitive Agent 分阶段设计](development/cognitive-agent-phases.zh-CN.md)、[认知型群聊 Agent 架构愿景](development/TestBot_Cognitive_Agent_Architecture_zh_CN.md) |
| 调试或扩展 memory lifecycle | [Memory Lifecycle API](api/memory-api.md)、[Memory Quality Phase 1 实施规格](development/memory-quality-phase1.zh-CN.md) |
| 实现 hybrid recall / embedding recall | [Hybrid Recall Phase 2 实施规格](development/hybrid-recall-phase2.zh-CN.md)、[Memory Lifecycle API](api/memory-api.md) |
| 改 merged-forward 或 forward 回复 | [Gateway API](api/gateway-api.md)、[Brain API](api/brain-api.md)、[Pixiv Module API](modules/pixiv-module-api.md) |
| 调试异步视频发送 | [Media Service API](services/media-service-api.md)、[Brain API](api/brain-api.md)、[Gateway API](api/gateway-api.md) |
| 调试卡片图片渲染 | [Renderer Service API](services/renderer-service-api.md)、对应功能模块 API |
| 查数据库字段 | [Database Schema](api/database-schema.md) |
| 部署整套服务 | [部署指南](deployment/deployment.zh-CN.md)、[低配本地部署](deployment/local-systemd.zh-CN.md) |
