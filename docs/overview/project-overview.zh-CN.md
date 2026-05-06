# TestBot 全局项目上下文

## 这个文档的用途

这份文档是给后续对话或新 agent 快速接手 TestBot 用的全局上下文。它描述“项目现在是什么样、各服务怎么连、配置在哪里、哪些东西已经完成、接下来怎么做”。

配合阅读：

- `docs/overview/ai-memory-plan.zh-CN.md`：AI 与记忆模块的专项设计。
- `docs/deployment/deployment.zh-CN.md`：部署细节。
- `README.md`：主仓库通用说明。

不要把真实 `.env` 内容复制到聊天里；本项目已有多个本地 env 文件包含密钥、token、密码。

## 5 分钟项目速览

如果只想先建立整体心智模型，可以按这一段接手：

- 服务地图：NapCat 通过 WebSocket 连 Go Gateway；Gateway 把消息归一化后交给 Python Brain；Brain 负责路由、记忆、AI runtime、数据库、outbox 和远程模块调用；Bilibili、TSPerson、Weather、Pixiv 是独立 HTTP module service；Renderer 和 Media 是共享基础设施，分别负责卡片图片和视频资产。
- 运行形态：低配服务器推荐 Docker 只跑 `postgres` 和 `napcat`，其余 `testbot-*` 服务用宿主机 systemd 运行；本地服务互相访问 `127.0.0.1`，但发给 NapCat 拉取的图片、视频 URL 通常要写成 `http://host.docker.internal:<port>`。
- 重要文件：Gateway 入口看 `gateway-go/main.go` 和 `gateway-go/handler/router.go`；Brain 主链路看 `brain-python/main.py`、`brain-python/services/chat.py`、`brain-python/modules/registry.py`；数据库迁移在 `database/migrations/`；模块 env 在 `config/modules/*.env`；本地 systemd 汇总 env 在 `/etc/testbot/local.env`。
- 已完成能力：Go Gateway、Brain remote module runtime、tools 聚合、Bilibili/TSPerson/Weather/Pixiv 外部模块、Rust renderer、Media service、Brain outbox、Gateway outbox poller、Postgres message persistence、Memory schema/admin commands、OpenAI-compatible AI runtime、低配 systemd 部署和日志脚本。
- 下一步阅读：排查部署先看 `docs/deployment/local-systemd.zh-CN.md`；理解 AI 与记忆看 `docs/overview/ai-memory-plan.zh-CN.md`；查完整部署细节看 `docs/deployment/deployment.zh-CN.md`；看仓库入口和通用命令看 `README.md`。

## 总体目标

TestBot 是一个面向 QQ/NapCat 的模块化机器人系统。当前架构的核心目标是：

- Go Gateway 只负责接收 NapCat WebSocket 事件和发送 NapCat action。
- Python Brain 负责路由、策略、数据库、outbox、AI runtime 和 tool 聚合。
- 业务插件拆成外部 HTTP module service，避免污染 bot core。
- Renderer、Media 作为共享基础设施服务，供业务模块调用。
- 低配服务器优先使用“Postgres + NapCat in Docker，其余本地 systemd”的运行方式。

## 仓库与本地服务布局

主仓库：

```text
/root/TestBot
```

外部服务仓库：

```text
/root/testbot-module-bilibili
/root/testbot-module-tsperson
/root/testbot-module-weather
/root/testbot-module-pixiv
/root/testbot-render-service
/root/testbot-media-service
```

老插件参考代码曾放在：

```text
/tmp/pig-sender
```

旧 Haruki bot 本地服务：

```text
/root/haruki-bot
```

## 主仓库结构

```text
TestBot/
├── gateway-go/              # Go WebSocket gateway
├── brain-python/            # Python FastAPI Brain
├── database/                # SQL migrations
├── config/modules/          # 外部模块本地 env 文件
├── docs/                    # 文档与路线图
├── json_example/            # NapCat 示例事件
├── scripts/                 # 部署、日志、压测脚本
├── docker-compose.yml
├── docker-compose.modules.yml
├── docker-compose.render.yml
└── docker-compose.media.yml
```

## 当前主链路

```text
NapCat
  |
  | WebSocket event
  v
Go Gateway
  |
  | normalized ChatRequest
  v
Python Brain
  |
  | deterministic router / memory / AI / remote modules / outbox
  v
External Module Services
  |
  | optional renderer/media calls
  v
Renderer / Media
```

回复路径：

```text
BrainResponse.messages
  -> Go Gateway
  -> NapCat action
  -> QQ group/private message
```

异步消息路径：

```text
Module or Media Service
  -> Brain /outbox/enqueue
  -> Gateway poller /outbox/pull
  -> NapCat action
  -> Brain /outbox/{id}/ack or /fail
```

## 服务与端口

默认端口：

| 服务 | 端口 | 说明 |
| --- | --- | --- |
| Go Gateway | `808` | NapCat WebSocket 连接 `ws://host:808/ws` |
| Python Brain | `8000` | `/chat`、`/tools`、`/outbox/*` |
| Bilibili Module | `8011` | B 站解析、卡片、下载任务触发 |
| TSPerson Module | `8012` | TeamSpeak 查询与通知 |
| Weather Module | `8013` | 高德天气查询 |
| Pixiv Module | `8014` | Pixiv 详情、排行榜、图片资产 |
| Rust Renderer | `8020` | PNG 卡片渲染 |
| Media Service | `8030` | Bilibili 视频下载与 MP4 资产 |
| Postgres | `5432` | pgvector Postgres |
| NapCat WebUI | `6099` | NapCat WebUI |

## Go Gateway

路径：

```text
gateway-go/
```

职责：

- 监听 WebSocket。
- 接收 NapCat 事件。
- 过滤非 message、非 group/private、机器人自己发的消息。
- 归一化 message segments。
- 调用 Brain `/chat`。
- 把 `BrainResponse.messages` 转成 NapCat action。
- 轮询 Brain outbox 并发送异步消息。

关键文件：

```text
gateway-go/main.go
gateway-go/handler/router.go
gateway-go/handler/normalizer/normalizer.go
gateway-go/client/brain/client.go
gateway-go/client/napcat/action.go
```

支持的 Brain message item：

- `text`
- `image`
- `video`
- `reply`
- `at`
- `json`
- `node`
- `forward`

合并转发：

- 如果 Brain 返回单个 `type=forward`，或全是 `type=node`，Gateway 会发 `send_group_forward_msg` / `send_private_forward_msg`。
- 其它情况逐条发普通消息。

Outbox：

- Gateway 每 3 秒拉 Brain `/outbox/pull`。
- 成功发送后 `/outbox/{id}/ack`。
- 失败 `/outbox/{id}/fail`。

常用测试：

```bash
cd gateway-go && go test ./...
```

## Python Brain

路径：

```text
brain-python/
```

核心职责：

- FastAPI HTTP API。
- deterministic module router。
- remote module service 调用。
- tool 列表聚合与 tool call 转发。
- message persistence。
- memory 管理和 recall。
- OpenAI-compatible AI runtime。
- notification outbox。

关键文件：

```text
brain-python/main.py
brain-python/schemas.py
brain-python/services/chat.py
brain-python/services/tools.py
brain-python/services/outbox.py
brain-python/services/persistence.py
brain-python/services/memory.py
brain-python/services/memory_extractor.py
brain-python/services/ai_runtime.py
brain-python/modules/registry.py
brain-python/modules/remote.py
```

API：

```text
GET  /health
POST /chat
GET  /tools
POST /tools/call
POST /outbox/enqueue
POST /outbox/pull
POST /outbox/{id}/ack
POST /outbox/{id}/fail
```

Brain 处理顺序：

1. 持久化 incoming message。
2. 提取文本、JSON 小程序中的文本候选。
3. `/memory` 或 `/记忆` 管理命令优先。
4. deterministic local module。
5. remote module services。
6. fake echo planner。
7. AI runtime。
8. 持久化 bot response。

默认普通文本静默。

常用测试：

```bash
cd brain-python && .venv/bin/python -m pytest
```

## Brain Remote Module Runtime

外部模块通过 `BRAIN_MODULE_SERVICE_DEFAULTS` 和 `BRAIN_MODULE_SERVICES` 注册。

示例：

```env
BRAIN_MODULE_SERVICE_DEFAULTS=bilibili=http://module-bilibili:8011,tsperson=http://module-tsperson:8012,weather=http://module-weather:8013
BRAIN_MODULE_SERVICES=
BRAIN_MODULE_TIMEOUT=20
```

Brain 会：

- 合并 defaults 和 explicit services。
- 对每个模块应用 group allow/block policy。
- 调用远程模块 `POST /handle`。
- 聚合远程模块 `GET /tools`。
- 根据 tool name 转发 `POST /tools/call`。
- 模块失败时静默 no-reply，不重试。

外部模块统一接口：

```text
GET  /health
GET  /manifest
POST /handle
GET  /tools
POST /tools/call
```

`POST /handle` 输入是 Brain `ChatRequest` wire shape，输出是 `BrainResponse` wire shape。

## Group Policy

Brain core 支持全局和 per-module 群策略：

```env
BRAIN_GROUP_ALLOWLIST=
BRAIN_GROUP_BLOCKLIST=
BRAIN_MODULE_BILIBILI_GROUP_ALLOWLIST=
BRAIN_MODULE_BILIBILI_GROUP_BLOCKLIST=
BRAIN_MODULE_TSPERSON_GROUP_ALLOWLIST=
BRAIN_MODULE_TSPERSON_GROUP_BLOCKLIST=
BRAIN_MODULE_WEATHER_GROUP_ALLOWLIST=
BRAIN_MODULE_WEATHER_GROUP_BLOCKLIST=
BRAIN_MODULE_PIXIV_GROUP_ALLOWLIST=
BRAIN_MODULE_PIXIV_GROUP_BLOCKLIST=
```

模块自身也支持自己的 allow/block：

```env
BILIBILI_GROUP_ALLOWLIST=
BILIBILI_GROUP_BLOCKLIST=
TSPERSON_GROUP_ALLOWLIST=
TSPERSON_GROUP_BLOCKLIST=
WEATHER_GROUP_ALLOWLIST=
WEATHER_GROUP_BLOCKLIST=
PIXIV_GROUP_ALLOWLIST=
PIXIV_GROUP_BLOCKLIST=
```

规则：

- blocklist 优先。
- allowlist 为空表示允许所有群。
- group ID 用逗号、分号或空白分隔。
- Brain policy 在调用模块前生效。
- 模块 policy 在模块内二次生效。

## 数据库

Postgres 使用 pgvector 镜像：

```text
pgvector/pgvector:pg16
```

迁移文件：

```text
database/migrations/000001_enable_pgvector.up.sql
database/migrations/000002_core_chat_tables.up.sql
database/migrations/000003_message_outbox.up.sql
database/migrations/000004_memory.up.sql
```

主要表：

- `conversations`
- `message_events_raw`
- `messages`
- `bot_responses`
- `message_outbox`
- `memory_items`
- `memory_embeddings`
- `memory_runs`
- `memory_settings`

运行迁移：

```bash
docker compose --profile tools run --rm migrate
```

注意：

- 当前迁移不是幂等的，重复跑已创建表会失败。
- `000004_memory` 要求 `memory_items.evidence_message_ids` 非空。
- `memory_embeddings` 当前固定 `vector(1536)`。

## Message Persistence

Brain 在 `DATABASE_URL` 可用时写入消息历史。

写入 incoming：

- `conversations`
- `message_events_raw`
- `messages`

写入 bot response：

- `bot_responses`

原则：

- 写 DB 失败只 warning，不打断聊天。
- Gateway 不写 DB。
- 未来 summary、memory extractor、AI recent context 都依赖这里。

## Memory

当前状态：

- 已有 schema、store、recall、admin commands。
- 已有 keyword recall 和 recent messages。
- 已有手动 `Memory Extractor MVP`，通过 `/memory extract [数量]` 从当前群最近消息抽取长期 memory。

Memory scope：

- `global`
- `group`
- `user`
- `relationship`

Memory type：

- `preference`
- `fact`
- `style`
- `relationship`
- `topic`
- `summary`
- `warning`

管理命令：

```text
/memory status
/memory search <keyword>
/memory user <QQ>
/memory extract [数量]
/memory forget <id>
/memory forget-user <QQ>
/memory forget-group
/memory enable
/memory disable
```

别名：

```text
/记忆
```

权限：

- NapCat sender role 是 `owner/admin` 可以管理本群。
- `MEMORY_ADMIN_USER_IDS` 是全局管理员。
- 群管理员不能跨群删除 memory。
- 全局管理员可以按 memory id 删除。

配置：

```env
MEMORY_ENABLED=true
MEMORY_ADMIN_USER_IDS=
MEMORY_EXTRACTOR_ENABLED=false
MEMORY_EXTRACTOR_BASE_URL=
MEMORY_EXTRACTOR_API_KEY=
MEMORY_EXTRACTOR_MODEL=
MEMORY_EXTRACTOR_TIMEOUT=30
MEMORY_EXTRACTOR_BATCH_SIZE=80
MEMORY_EXTRACTOR_MAX_CANDIDATES=12
```

抽取流程：

1. Brain 已经把 normalized incoming messages 写入 Postgres。
2. 群管理员或 `MEMORY_ADMIN_USER_IDS` 用户在群内执行 `/memory extract`。
3. Brain 立即回复“记忆抽取已开始”，避免 Gateway `/chat` 等到 LLM 超时。
4. 后台 worker 读取当前群最近文本消息，调用 OpenAI-compatible model 生成候选 memory。
5. Brain 校验 scope/type/evidence/group/user/relationship。
6. 合格 memory 写入或更新 `memory_items`，本次运行写入 `memory_runs`。
7. 后台完成或失败后写 Brain outbox，Gateway poller 异步发送群通知。
8. 后续 `/ai`、`/chat`、`/聊天` 或 @bot 时，AI runtime 通过 recall 读取这些长期 memory。

注意：

- `/memory extract` 默认读取 `MEMORY_EXTRACTOR_BATCH_SIZE` 条消息。
- `/memory extract 100` 这类显式数量允许 `10-200`。
- 当前群 `/memory disable` 后不会抽取，也不会 recall。
- extractor 配置为空时会回退 `AI_BASE_URL/API_KEY/MODEL`。
- 第一版是手动触发，不含后台 scheduler、embedding 或 proactive。

更多设计见：

```text
docs/overview/ai-memory-plan.zh-CN.md
```

## AI Runtime

当前状态：

- 已接入 OpenAI-compatible `/v1/chat/completions`。
- 默认关闭。
- 支持显式命令触发。
- 支持 mention trigger。
- reply trigger 默认关闭。
- proactive 不会直接触发普通消息，等待后续 scheduler/cooldown。

触发：

```text
/ai <text>
/chat <text>
/聊天 <text>
@bot <text>
```

配置：

```env
AI_ENABLED=false
AI_BASE_URL=
AI_API_KEY=
AI_MODEL=
AI_TIMEOUT=20
AI_TEMPERATURE=0.7
AI_MAX_TOKENS=800
AI_SYSTEM_PROMPT=
AI_COMMAND_ALIASES=ai,chat,聊天
AI_GROUP_ALLOWLIST=
AI_GROUP_BLOCKLIST=
AI_MENTION_TRIGGER_ENABLED=true
AI_REPLY_TRIGGER_ENABLED=false
AI_PROACTIVE_ENABLED=false
AI_PROACTIVE_GROUP_ALLOWLIST=
```

Prompt 安全：

- fixed system prompt 只放身份、风格、安全规则。
- recent messages 和 memory 作为不可信 user context。
- 上下文会截断。
- 不把 stored memory 当成 system instruction。

## Bilibili Module

仓库：

```text
/root/testbot-module-bilibili
```

端口：

```text
8011
```

能力：

- BV ID 解析。
- `bilibili.com/video/...` 解析。
- `b23.tv/...` 短链解析。
- QQ 小程序 JSON 解析。
- QQ news JSON 解析。
- 获取视频详情。
- 调 renderer 生成 Bilibili 卡片。
- 发送独立简介文本。
- 可选自动/手动下载视频。
- 调 media service 创建下载 job。

命令：

```text
/bili
.bili
/bilibili
.bilibili
/bv
.bv
```

关键配置：

```env
BILIBILI_GROUP_ALLOWLIST=
BILIBILI_GROUP_BLOCKLIST=
BILIBILI_SHORT_LINK_TIMEOUT=5
BILIBILI_TRUST_ENV_PROXY=false
BILIBILI_VIDEO_DETAIL_TIMEOUT=5
BILIBILI_VIDEO_DETAIL_MAX_BYTES=4194304
BILIBILI_VIDEO_DETAIL_TRUST_ENV_PROXY=false
BILIBILI_SEND_DETAILS=true
BILIBILI_SEND_LINK=true
BILIBILI_COOLDOWN_SECONDS=0
RENDERER_ENABLED=false
RENDERER_INTERNAL_BASE_URL=http://renderer-rust:8020
BILIBILI_AUTO_DOWNLOAD_ENABLED=false
BILIBILI_DOWNLOAD_GROUP_ALLOWLIST=
BILIBILI_DOWNLOAD_MAX_DURATION_SECONDS=180
BILIBILI_DOWNLOAD_MAX_BYTES=52428800
BILIBILI_DOWNLOAD_QUALITY=480p
BILIBILI_MEDIA_BASE_URL=http://testbot-media:8030
```

当前期望行为：

1. 触发 B 站链接。
2. 发送渲染卡片。
3. 单独发送简介。
4. 白名单群内可创建视频下载任务。
5. 下载完成后 media service 写 Brain outbox，Gateway 异步发送视频。

## TSPerson Module

仓库：

```text
/root/testbot-module-tsperson
```

端口：

```text
8012
```

能力：

- TeamSpeak ServerQuery 查询。
- TS 在线人数、频道、在线用户。
- 可选 renderer 卡片。
- 可选 join/leave 通知，通过 Brain outbox 发送。

命令：

```text
查询人数
查询人类
ts状态
ts人数
ts在线
teamspeak状态
ts帮助
tsperson帮助
teamspeak帮助
/ts
.ts
/tsperson
.teamspeak
```

关键配置：

```env
TS3_HOST=
TS3_QUERY_PORT=13986
TS3_QUERY_USER=
TS3_QUERY_PASSWORD=
TS3_VIRTUAL_SERVER_ID=1
TS3_TIMEOUT=5
TSPERSON_GROUP_ALLOWLIST=
TSPERSON_GROUP_BLOCKLIST=
TSPERSON_STATUS_CACHE_TTL=0
RENDERER_ENABLED=false
RENDERER_INTERNAL_BASE_URL=http://renderer-rust:8020
TSPERSON_NOTIFY_ENABLED=false
TSPERSON_NOTIFY_GROUPS=
BRAIN_BASE_URL=
OUTBOX_TOKEN=
```

## Weather Module

仓库：

```text
/root/testbot-module-weather
```

端口：

```text
8013
```

能力：

- 高德天气查询。
- city name 到 citycode/adcode 映射。
- 可选 renderer 天气卡片。

命令：

```text
天气 <城市>
<城市>天气
/weather <城市>
.weather <城市>
天气帮助
/weather help
```

关键配置：

```env
WEATHER_AMAP_KEY=
WEATHER_AMAP_BASE_URL=https://restapi.amap.com/v3/weather/weatherInfo
WEATHER_TIMEOUT=5
WEATHER_TRUST_ENV_PROXY=false
WEATHER_CITYCODE_PATH=
WEATHER_GROUP_ALLOWLIST=
WEATHER_GROUP_BLOCKLIST=
RENDERER_ENABLED=false
RENDERER_INTERNAL_BASE_URL=http://renderer-rust:8020
```

注意：

- 天气查询依赖 citycode。
- 如果模块 `/handle` 200 但 Brain 没回复，优先检查 `BRAIN_MODULE_SERVICE_DEFAULTS` 是否包含 weather，以及 group policy 是否拦截。

## Pixiv Module

仓库：

```text
/root/testbot-module-pixiv
```

端口：

```text
8014
```

能力：

- Pixiv refresh token OAuth。
- 作品详情。
- 日榜、周榜、月榜。
- 排行榜指定名次。
- restricted tag 过滤。
- 本地 PIL 旧版风格排行榜卡片。
- 本地图片资产缓存和 `/assets/{name}`。

命令示例：

```text
pixiv <pid>
pixiv 日榜
pixiv 周榜
pixiv 月榜
pixiv 日榜 #1
```

关键配置：

```env
PIXIV_REFRESH_TOKEN=
PIXIV_AUTH_TTL_SECONDS=1800
PIXIV_TRUST_ENV_PROXY=true
PIXIV_HTTP_PROXY=
PIXIV_RESTRICTED_TAGS=R-18,R-18G,furry,furry art,kemono,ケモノ,獣人,兽人,manga,漫画,AI生成,AIイラスト,AI-generated,AI generated,NovelAI,Stable Diffusion
PIXIV_CACHE_TTL_MINUTES=60
PIXIV_IMAGE_CACHE_DIR=/tmp/testbot-pixiv-assets
PIXIV_IMAGE_CACHE_TTL_SECONDS=3600
PIXIV_ASSET_BASE_URL=http://host.docker.internal:8014
PIXIV_FONT_PATH=/usr/share/fonts/truetype/pingfang/PingFang.ttc
PIXIV_BOLD_FONT_PATH=/usr/share/fonts/truetype/pingfang/PingFang.ttc
PIXIV_GROUP_ALLOWLIST=
PIXIV_GROUP_BLOCKLIST=
```

注意：

- Pixiv 通常需要代理，和 TS/Bilibili 相反。
- `PIXIV_RESTRICTED_TAGS` 是标签列表循环过滤，不应写成一堆硬编码 if。
- 当前目标是尽量只发图片，不发冗余文本。

## Rust Renderer

仓库：

```text
/root/testbot-render-service
```

端口：

```text
8020
```

技术栈：

- Rust
- axum
- tokio
- tiny-skia
- cosmic-text
- image
- reqwest

API：

```text
GET  /health
GET  /v1/templates
POST /v1/cards/render
GET  /v1/assets/{id}.png
```

模板：

- `bilibili.video`
- `tsperson.status`
- `weather.forecast`
- `generic.summary`

配置：

```env
PORT=8020
ASSET_DIR=/data/assets
RENDERER_ASSET_DIR=/data/assets
RENDERER_PUBLIC_BASE_URL=http://127.0.0.1:8020
RUST_LOG=info
```

注意：

- Docker 镜像会安装 CJK 字体。
- 非 Docker Linux 需要安装 CJK 字体。
- Bilibili/TS/weather 图片风格目标是尽量贴近旧插件卡片，不加水印。
- Render 压测脚本在 `scripts/bench-render.sh`。

## Media Service

仓库：

```text
/root/testbot-media-service
```

端口：

```text
8030
```

能力：

- 接收 Bilibili 下载 job。
- yt-dlp + ffmpeg 下载公开视频。
- 限制时长、大小。
- MP4 本地缓存。
- 通过 Brain outbox 异步发送视频。

API：

```text
GET  /health
POST /v1/bilibili/jobs
GET  /v1/jobs/{job_id}
GET  /v1/assets/{asset_id}.mp4
```

关键配置：

```env
MEDIA_CACHE_DIR=/data/media
MEDIA_PUBLIC_BASE_URL=http://testbot-media:8030
MEDIA_CACHE_TTL_SECONDS=3600
MEDIA_MAX_BYTES=52428800
MEDIA_MAX_DURATION_SECONDS=180
MEDIA_YTDLP_FORMAT=bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best
BRAIN_BASE_URL=http://brain-python:8000
OUTBOX_TOKEN=
OUTBOX_TIMEOUT_SECONDS=5
```

注意：

- 不使用 Bilibili cookie。
- 可能遇到 Bilibili 412，需要 UA/API fallback 等策略。
- 下载视频只建议对白名单群开启。

## Renderer 与 Media 的 URL 可达性

图片和视频最终由 NapCat 拉取，所以 `asset.url` 必须对 NapCat 可达。

Docker 同网络时：

```env
RENDERER_PUBLIC_BASE_URL=http://renderer-rust:8020
MEDIA_PUBLIC_BASE_URL=http://testbot-media:8030
```

本地 systemd + NapCat Docker 时，通常用：

```env
RENDERER_PUBLIC_BASE_URL=http://host.docker.internal:8020
MEDIA_PUBLIC_BASE_URL=http://host.docker.internal:8030
PIXIV_ASSET_BASE_URL=http://host.docker.internal:8014
```

如果 NapCat 在外部机器，需要改成该机器能访问到的公网或内网地址。

## Docker Compose

基础 compose：

```bash
docker compose up
```

默认只启动基础服务，应用服务用 profiles 控制。

核心 Docker 开发：

```bash
docker compose --profile docker-app up -d postgres brain-python gateway-go
```

模块 Docker 开发：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.modules.yml \
  --profile docker-app \
  --profile docker-modules \
  up
```

全 Docker 开发：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.modules.yml \
  -f docker-compose.render.yml \
  -f docker-compose.media.yml \
  --profile docker-app \
  --profile docker-modules \
  --profile docker-pixiv \
  --profile docker-render \
  --profile docker-media \
  --profile napcat \
  up
```

Compose 检查：

```bash
docker compose config
```

## 低配本地 systemd 部署

推荐给 2C4G 服务器：

- Docker：Postgres + NapCat。
- systemd：gateway、brain、modules、renderer、media。

安装：

```bash
scripts/install-local-systemd.sh
```

启动：

```bash
scripts/start-all.sh
```

或：

```bash
scripts/start-local-systemd.sh
```

systemd units：

```text
testbot-compose
testbot-gateway
testbot-brain
testbot-module-bilibili
testbot-module-tsperson
testbot-module-weather
testbot-module-pixiv
testbot-renderer
testbot-media
haruki-bot
```

日志：

```bash
scripts/logs.sh list
scripts/logs.sh -f gateway
scripts/logs.sh -f brain
scripts/logs.sh -f bilibili
scripts/logs.sh -f media
scripts/logs.sh all
```

## 配置文件位置

主 compose env：

```text
.env
.env.example
```

Brain runtime env：

```text
brain-python/.env
brain-python/.env.example
```

模块 env：

```text
config/modules/bilibili.env
config/modules/tsperson.env
config/modules/weather.env
config/modules/pixiv.env
config/modules/render.env
```

示例：

```text
config/modules/*.env.example
```

systemd 汇总 env：

```text
/etc/testbot/local.env
```

原则：

- 不提交真实 `.env`。
- 不在文档里写真实 token/password。
- TS/Bilibili 通常不走代理。
- Pixiv 通常需要代理。
- renderer/media 的 public URL 要保证 NapCat 可访问。

## CI 与测试

GitHub Actions：

```text
.github/workflows/ci.yml
```

CI 包含：

- Go tests
- Python tests
- Compose config

本地完整验证：

```bash
cd brain-python && .venv/bin/python -m pytest
cd gateway-go && go test ./...
docker compose config
```

Renderer 验证：

```bash
cd /root/testbot-render-service
cargo fmt --check
cargo test
cargo clippy --all-targets --all-features -- -D warnings
```

模块验证：

```bash
cd /root/testbot-module-bilibili && python -m pytest
cd /root/testbot-module-tsperson && python -m pytest
cd /root/testbot-module-weather && python -m pytest
cd /root/testbot-module-pixiv && python -m pytest
cd /root/testbot-media-service && python -m pytest
```

Render 压测：

```bash
scripts/bench-render.sh all
scripts/bench-render.sh bili-hot
scripts/bench-render.sh weather-cold
```

## 当前已完成的重要能力

- Go Gateway normalized envelope。
- Brain remote module runtime。
- Brain tools 聚合和远程 tool call。
- Bilibili 外部模块。
- TSPerson 外部模块。
- Weather 外部模块。
- Pixiv 外部模块。
- Rust renderer。
- Media service。
- Brain outbox。
- Gateway outbox poller。
- Postgres message persistence。
- Memory schema + admin commands。
- OpenAI-compatible AI runtime。
- 低配 systemd 部署脚本。
- 日志聚合脚本。

## 当前限制与坑

### Memory

- Memory Extractor 目前是手动触发 MVP，还没有后台 scheduler。
- `memory_embeddings` 固定 `vector(1536)`。
- 长期 memory 必须有 evidence，手工插入时要注意。

### AI

- 默认关闭。
- tool calling loop 还没做。
- proactive 还没做 scheduler/cooldown。
- reply trigger 默认关闭，因为当前还不能证明 reply 的对象是 bot。

### Bilibili

- 短链/详情/下载可能遇到 B 站 412。
- 下载不使用 cookie，只支持公开视频。
- 视频下载建议只开白名单群。

### Pixiv

- refresh token 必填。
- 通常需要代理。
- 字体要保证中文可显示。
- restricted tags 要持续维护。

### Renderer

- NapCat 必须能访问 renderer 返回的 URL。
- 冷渲染可能受远程图片下载影响，不只是 Rust 绘制速度。

### Weather

- 依赖 citycode/adcode 数据。
- 高德 key 必填。

## 推荐后续路线

优先级从高到低：

1. AI Tool Calling
   - AI 使用 `/tools` 聚合能力。
   - 自然语言调用 weather/bilibili/ts/pixiv。
   - deterministic 命令仍然优先。

2. Embedding Recall
   - 写 memory embedding。
   - keyword + vector hybrid recall。
   - rerank。

3. Background Memory Extractor
   - scheduler。
   - per-group cooldown。
   - batch watermark。

4. Proactive AI
   - group allowlist。
   - cooldown。
   - daily quota。
   - random sampling。
   - quiet hours。

5. Summary Module
   - 基于 Postgres message history。
   - 先非 AI stats，再 AI summary。

6. Steam / HLTV / Search Image
   - 继续外部 module service 化。
   - 状态变化通知走 Brain outbox。

## 给后续 agent 的注意事项

- 不要把业务插件重新塞回 `brain-python/modules`。
- 不要让 Go Gateway 直接调用模块或写数据库。
- 不要提交真实 `.env`。
- 改动前先跑 `git status --short`。
- 这个项目经常有 live service，避免随便删除文件或重启服务。
- 对模块改动优先在对应 `/root/testbot-module-*` 仓库做。
- 对 renderer 改动在 `/root/testbot-render-service` 做。
- 对 media 改动在 `/root/testbot-media-service` 做。
- 主仓库只负责 core、compose、docs、gateway、brain。
