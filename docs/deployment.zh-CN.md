# TestBot 部署指南

本文档说明当前的拆分服务部署方式：

- TestBot 主仓库：Go Gateway、Python Brain、Postgres、数据库迁移和 compose overlay。
- Bilibili 模块服务：`PJWaurora/testbot-module-bilibili`。
- TSPerson 模块服务：`PJWaurora/testbot-module-tsperson`。
- Rust 绘图服务：`PJWaurora/testbot-render-service`。
- Media 服务：`PJWaurora/testbot-media-service`。

renderer 不是 Brain 模块。Brain 只调用模块服务；模块服务在需要图片卡片时再调用 renderer，并通过现有 Brain 响应格式返回图片 URL。

## 仓库布局

默认建议把几个仓库放在同一层目录。除非你在 root `.env` 里覆盖 compose context，否则 compose 会按这个布局寻找模块仓库：

```text
workspace/
├── TestBot/
├── testbot-module-bilibili/
├── testbot-module-tsperson/
├── testbot-render-service/
└── testbot-media-service/
```

默认 context：

```env
BILIBILI_MODULE_CONTEXT=../testbot-module-bilibili
TSPERSON_MODULE_CONTEXT=../testbot-module-tsperson
RENDER_SERVICE_CONTEXT=../testbot-render-service
MEDIA_SERVICE_CONTEXT=../testbot-media-service
```

## 配置文件

现在有三层配置。

`TestBot/.env` 给 Docker Compose 做变量插值，用来配置服务端口、build context、Docker build 代理、模块注册、共享 outbox token、renderer 连接和 media 服务连接。

`brain-python/.env` 给本地 Python Brain 运行时读取。Docker 模式下，核心 Brain 配置会由 compose overlay 传给 `brain-python` 容器。

`config/modules/*.env` 是本地私有模块配置，会被 compose 加载到模块或 renderer 容器里。TeamSpeak 账号密码、模块私有配置、模块级群黑白名单都应该放这里。

初始化配置：

```bash
cp .env.example .env
cp brain-python/.env.example brain-python/.env
cp config/modules/bilibili.env.example config/modules/bilibili.env
cp config/modules/tsperson.env.example config/modules/tsperson.env
cp config/modules/render.env.example config/modules/render.env
```

不要提交真实 `.env`、账号、密码或 token。

## 镜像命名

Compose 现在给每个服务都显式写了镜像名，本地 build 和容器来源会更清楚：

```env
POSTGRES_IMAGE=pgvector/pgvector:pg16
BRAIN_IMAGE=testbot-brain-python:latest
GATEWAY_IMAGE=testbot-gateway-go:latest
BILIBILI_MODULE_IMAGE=testbot-module-bilibili:latest
TSPERSON_MODULE_IMAGE=testbot-module-tsperson:latest
RENDER_SERVICE_IMAGE=testbot-renderer-rust:latest
MEDIA_SERVICE_IMAGE=testbot-media-service:latest
NAPCAT_IMAGE=mlikiowa/napcat-docker:latest
```

`postgres` 和 `migrate` 会共用 `POSTGRES_IMAGE`，这是有意的：`migrate`
只是一次性 SQL runner，用同一个镜像里的 `psql` 执行迁移。Bilibili、
TSPerson 和 renderer 是三个独立服务仓库，所以是三个独立镜像。

## 只启动核心服务

核心模式只启动 Postgres、Python Brain 和 Go Gateway，不启动 Bilibili、TSPerson 或 renderer。
如果是全新数据库，或者刚拉取了新的 SQL migration，先跑迁移再启动 Brain：

```bash
docker compose up -d postgres
docker compose --profile tools run --rm migrate
docker compose up -d brain-python gateway-go
```

这个模式下，Brain 默认只加载本地 fake echo 模块。普通文本、Bilibili 链接和 TSPerson 命令会保持静默，除非命中 fake planner 或以后配置的其他模块。

检查服务：

```bash
docker compose ps
curl http://127.0.0.1:8000/health
```

NapCat WebSocket 客户端配置：

```text
ws://<gateway-host>:808/ws
```

如果 NapCat 和 TestBot 在同一个 compose project 里，使用：

```text
ws://gateway-go:808/ws
```

compose 里的 NapCat 三个端口可以分开绑定。如果只想公网访问 WebUI，
只开放 6099，OneBot HTTP/WebSocket 继续留在本机：

```env
NAPCAT_WEBUI_BIND_HOST=0.0.0.0
NAPCAT_HTTP_BIND_HOST=127.0.0.1
NAPCAT_WS_BIND_HOST=127.0.0.1
NAPCAT_WEBUI_PORT=6099
```

## 启动模块服务

模块模式会额外启动 Bilibili 和 TSPerson 两个外部 HTTP 模块服务，并把它们注册到 Brain。

root `.env`：

```env
BRAIN_MODULE_SERVICES=bilibili=http://module-bilibili:8011,tsperson=http://module-tsperson:8012
BRAIN_MODULE_TIMEOUT=5
BILIBILI_MODULE_PORT=8011
TSPERSON_MODULE_PORT=8012
OUTBOX_TOKEN=<random-shared-token>
```

启动核心服务和模块服务：

```bash
docker compose -f docker-compose.yml -f docker-compose.modules.yml up -d
```

检查模块：

```bash
curl http://127.0.0.1:8011/health
curl http://127.0.0.1:8012/health
curl http://127.0.0.1:8000/tools
```

Brain 会先应用群黑白名单策略，再调用远程模块的 `POST /handle`。模块超时、连接失败、非 2xx、非法 JSON 都会被当作 no reply，不会自动重试，避免 QQ 重复发消息。

## Brain Outbox

Brain 提供带鉴权的异步消息 outbox：

```text
POST /outbox/enqueue
POST /outbox/pull
POST /outbox/{id}/ack
POST /outbox/{id}/fail
```

所有 outbox 接口都需要 `Authorization: Bearer <OUTBOX_TOKEN>` 或
`X-Outbox-Token: <OUTBOX_TOKEN>`。`brain-python`、`gateway-go` 和
`testbot-media` 这类 outbox producer 必须使用同一个 `OUTBOX_TOKEN`。

`/outbox/enqueue` 接收 `message_type`（`group` 或 `private`）、目标
`group_id` 或 `user_id`，以及现有 Brain message 格式的 `messages`。
outbox message 支持 `text`、`image`、`video`；图片和视频必须带 `file`、
`url` 或 `path`。

Gateway 在 NapCat WebSocket session 在线时每 3 秒调用 `/outbox/pull`。
拉到 item 后会复用现有 Brain message 到 CQ action 的转换逻辑；action
进入发送队列后 ack，转换失败或入队失败时 fail。Brain 会在 5 次投递失败
后把 item 标记为 `failed`。

## Bilibili 模块

Bilibili 模块支持：

- 普通文本里的 BV ID。
- `bilibili.com/video/...` 链接。
- `b23.tv/...` 短链。
- QQ 小程序 JSON：`meta.detail_1.qqdocurl`。
- QQ 新闻卡片 JSON：`meta.news.jumpUrl`。
- `/bili`、`.bili`、`/bilibili`、`.bv` 等命令。

可选 `config/modules/bilibili.env`：

```env
BILIBILI_GROUP_ALLOWLIST=
BILIBILI_GROUP_BLOCKLIST=
BILIBILI_SHORT_LINK_TIMEOUT=5
BILIBILI_TRUST_ENV_PROXY=false
BILIBILI_VIDEO_DETAIL_TIMEOUT=5
BILIBILI_VIDEO_DETAIL_TRUST_ENV_PROXY=false
BILIBILI_COMMAND_PREFIXES=/,.
BILIBILI_AUTO_DOWNLOAD_ENABLED=false
BILIBILI_DOWNLOAD_GROUP_ALLOWLIST=
BILIBILI_DOWNLOAD_MAX_DURATION_SECONDS=180
BILIBILI_DOWNLOAD_MAX_BYTES=52428800
BILIBILI_DOWNLOAD_QUALITY=480p
BILIBILI_MEDIA_BASE_URL=http://testbot-media:8030
```

群黑白名单用于控制模块在哪些群生效。blocklist 优先级高于 allowlist。allowlist 为空代表默认允许所有群。

## Media 服务

media 模式会额外启动 `testbot-media`，用于异步媒体流程，并通过 Brain
outbox 把 text/image/video 消息投递回 Gateway。

root `.env`：

```env
MEDIA_SERVICE_CONTEXT=../testbot-media-service
MEDIA_SERVICE_IMAGE=testbot-media-service:latest
MEDIA_SERVICE_PORT=8030
MEDIA_PUBLIC_BASE_URL=http://testbot-media:8030
OUTBOX_TOKEN=<random-shared-token>
```

启动核心服务、模块服务和 media。如果是全新数据库，或者
`database/migrations/` 有更新，先跑迁移：

```bash
docker compose up -d postgres
docker compose --profile tools run --rm migrate
docker compose -f docker-compose.yml -f docker-compose.modules.yml -f docker-compose.media.yml up -d
```

media overlay 会把 `BRAIN_BASE_URL`、`PYTHON_BRAIN_URL` 和 `OUTBOX_TOKEN`
传给 `testbot-media`。它也会加载 `config/modules/bilibili.env`，方便把
Bilibili 相关的 media 配置和 Bilibili 模块配置放在一起。

## TSPerson 模块

TSPerson 模块支持：

- `查询人数`
- `查询人类`
- `ts状态`
- `ts人数`
- `ts帮助`
- `/ts`
- `.ts`
- `/ts 帮助`

TeamSpeak ServerQuery 账号密码放在 `config/modules/tsperson.env`：

```env
TS3_HOST=<teamspeak-host>
TS3_QUERY_PORT=10011
TS3_QUERY_USER=
TS3_QUERY_PASSWORD=
TS3_VIRTUAL_SERVER_ID=1
TS3_TIMEOUT=5
TSPERSON_GROUP_ALLOWLIST=
TSPERSON_GROUP_BLOCKLIST=
TSPERSON_COMMAND_PREFIXES=/,.
```

注意使用 ServerQuery 端口，不是语音端口。如果模块返回 connection refused，优先检查服务器 IP、ServerQuery 端口、防火墙和账号密码。可以从 `module-tsperson` 容器内部测试连通性。

## Rust 绘图服务

renderer 模式会额外启动 `renderer-rust`，让 Bilibili/TSPerson 输出图片卡片。默认不启用。

root `.env`：

```env
RENDERER_PUBLIC_BASE_URL=http://renderer-rust:8020
RENDER_SERVICE_PORT=8020
```

在哪个模块里启用图片卡片，就改对应模块 env：

```env
# config/modules/bilibili.env 或 config/modules/tsperson.env
RENDERER_ENABLED=true
RENDERER_INTERNAL_BASE_URL=http://renderer-rust:8020
RENDERER_TIMEOUT=3
```

启动核心、模块和 renderer：

```bash
docker compose -f docker-compose.yml -f docker-compose.modules.yml -f docker-compose.render.yml up -d
```

检查 renderer：

```bash
curl http://127.0.0.1:8020/health
curl http://127.0.0.1:8020/v1/templates
```

renderer API：

```text
GET  /health
GET  /v1/templates
POST /v1/cards/render
GET  /v1/assets/{id}.png
```

第一批模板：

- `bilibili.video`
- `tsperson.status`
- `generic.summary`

renderer 会把 PNG 存到 `renderer-assets` Docker volume。图片 asset id 基于 SHA-256；带同一个 `idempotency_key` 的重复渲染会返回同一个 URL。

## Renderer URL 可达性

`RENDERER_INTERNAL_BASE_URL` 是模块容器访问 renderer 的内部地址。在同一个 compose 网络里，`http://renderer-rust:8020` 是正确的。

`RENDERER_PUBLIC_BASE_URL` 会被写进 QQ 图片消息里。NapCat 必须能访问这个 URL，否则 QQ 收不到图片。

按部署方式选择：

```text
NapCat 在同一个 compose project：
RENDERER_PUBLIC_BASE_URL=http://renderer-rust:8020

NapCat 直接跑在同一台宿主机：
RENDERER_PUBLIC_BASE_URL=http://127.0.0.1:8020

NapCat 在另一个 Docker 容器：
RENDERER_PUBLIC_BASE_URL=http://host.docker.internal:8020

NapCat 在另一台机器：
RENDERER_PUBLIC_BASE_URL=http://<server-ip-or-domain>:8020
```

如果 QQ 能收到文字但收不到图片，先在 NapCat 所在环境里 `curl` 这个 public URL。

## 不使用 Docker 的本地开发

运行 Brain：

```bash
cd brain-python
.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

运行 Gateway：

```bash
cd gateway-go
go run .
```

运行 Bilibili 模块：

```bash
cd ../testbot-module-bilibili
python -m uvicorn bilibili_module.main:app --host 0.0.0.0 --port 8011 --reload
```

运行 TSPerson 模块：

```bash
cd ../testbot-module-tsperson
python -m uvicorn tsperson_service.app:app --host 0.0.0.0 --port 8012 --reload
```

运行 renderer：

```bash
cd ../testbot-render-service
cargo run
```

本地 Brain 调本地模块时，设置：

```env
BRAIN_MODULE_SERVICES=bilibili=http://127.0.0.1:8011,tsperson=http://127.0.0.1:8012
```

## 测试命令

主仓库：

```bash
cd gateway-go && go test ./...
cd brain-python && .venv/bin/python -m pytest
docker compose config
docker compose -f docker-compose.yml -f docker-compose.modules.yml config
docker compose -f docker-compose.yml -f docker-compose.modules.yml -f docker-compose.render.yml config
```

Bilibili 模块：

```bash
cd ../testbot-module-bilibili
python -m pytest
docker build .
```

TSPerson 模块：

```bash
cd ../testbot-module-tsperson
python -m pytest
docker build .
```

renderer：

```bash
cd ../testbot-render-service
cargo fmt --check
cargo test
cargo clippy --all-targets --all-features -- -D warnings
docker build .
```

## 排障

命令静默：

- 检查当前运行环境里是否设置了 `BRAIN_MODULE_SERVICES`。
- 检查模块 `/health`。
- 检查群黑白名单。
- 查看 Brain 日志里是否有远程模块 timeout 或 invalid JSON。

Bilibili 短链不解析：

- 检查 `module-bilibili` 的出网。
- 如果必须走代理，给模块容器配置代理，并打开对应 trust-env proxy 配置。

TSPerson 连不上：

- 确认 `TS3_HOST` 是 TeamSpeak 服务器地址。
- 确认 `TS3_QUERY_PORT` 是 ServerQuery 端口。
- 确认账号、密码和 virtual server ID。
- 检查 Docker host 到 TeamSpeak 服务器的防火墙。

renderer 图片没发出来：

- 确认 `RENDERER_ENABLED=true`。
- 查看模块日志里是否 render 成功。
- 确认 NapCat 能访问 `RENDERER_PUBLIC_BASE_URL`。
- 确认 `GET /v1/assets/{id}.png` 返回 `image/png`。

Docker build 下载依赖失败：

- 配置 root `.env` 里的 Docker build proxy。
- 使用宿主机本地代理时，设置 `DOCKER_BUILD_NETWORK=host`。
- 不要随便给运行时模块设置代理，除非模块运行时确实需要出网代理。
