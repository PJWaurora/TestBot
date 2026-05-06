# TestBot 低配本地部署

适合 2C4G 这类机器：只保留 `postgres` 和 `napcat` 在 Docker，其他服务全部用宿主机 systemd 运行。

## 运行形态

- Docker: `postgres`, `napcat`
- systemd: `testbot-gateway`, `testbot-brain`, `testbot-module-bilibili`, `testbot-module-tsperson`, `testbot-module-weather`, `testbot-module-pixiv`, `testbot-renderer`, `testbot-media`

Pixiv 已接入本地 systemd 启动链路，默认端口是 `8014`。它需要
`/root/TestBot/config/modules/pixiv.env` 里的 `PIXIV_REFRESH_TOKEN`，并且通常需要
按你的网络环境配置 `PIXIV_HTTP_PROXY`。

本地服务之间全部走 `127.0.0.1`。发给 NapCat 拉取的图片和视频 URL 使用：

- `http://host.docker.internal:8020`
- `http://host.docker.internal:8030`
- `http://host.docker.internal:8014`（Pixiv 作品图和排行榜卡片）

因为 NapCat 仍在 Docker 容器里。

## 首次启动前检查

在第一次执行启动脚本前，先确认这些项目：

- `/root/TestBot/.env` 存在，并且包含 Postgres 密码、`OUTBOX_TOKEN` 等基础配置。
- 模块 env 已按需填写：`config/modules/bilibili.env`、`config/modules/tsperson.env`、`config/modules/weather.env`、`config/modules/pixiv.env`、`config/modules/render.env`。
- Pixiv 已设置 `PIXIV_REFRESH_TOKEN`；如果服务器直连 Pixiv 不稳定，已设置 `PIXIV_HTTP_PROXY`。
- Weather 已设置 `WEATHER_AMAP_KEY`。
- TSPerson 已设置 TS3 ServerQuery 地址、账号和密码。
- 需要发图片或视频时，renderer、media、Pixiv 的 public URL 对 NapCat 容器可达，通常是 `http://host.docker.internal:8020`、`http://host.docker.internal:8030`、`http://host.docker.internal:8014`。
- 机器上已经有可用的 Docker Compose、systemd、Python/uv、Go 和 Rust 运行环境；renderer 还需要可显示中文的 CJK 字体。

## 安装和启动

```bash
cd /root/TestBot
chmod +x scripts/install-local-systemd.sh scripts/start-local-systemd.sh
./scripts/install-local-systemd.sh
./scripts/start-local-systemd.sh
```

`scripts/start-all.sh` 现在也是这个低配入口。它不会再启动全 Docker 栈，只会：

- 启动 Docker 里的 `postgres` 和 `napcat`
- 停掉可能残留的 Docker app 容器
- 重启本地 systemd 服务

安装脚本会生成 `/etc/testbot/local.env`，从 `/root/TestBot/.env` 读取数据库密码和 `OUTBOX_TOKEN`，再把模块、renderer、media 的地址改成本地地址。

首次启动后建议立刻做一次健康检查、日志检查和 QQ 实际发消息测试。健康检查都通过只说明 HTTP 服务已经起起来；最终是否能发图、发视频，还要确认 NapCat 容器能拉到 public URL。

## Compose 使用边界

默认 `docker compose up` 只用于基础 Docker 服务，不会启动 Brain、Gateway、模块、renderer 或 media。全 Docker 开发模式需要显式 profile：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.modules.yml \
  -f docker-compose.render.yml \
  -f docker-compose.media.yml \
  --profile docker-app \
  --profile docker-modules \
  --profile docker-render \
  --profile docker-media \
  --profile napcat \
  up
```

## 常用命令

查看状态：

```bash
systemctl status testbot-gateway testbot-brain testbot-module-bilibili testbot-module-tsperson testbot-module-weather testbot-renderer testbot-media --no-pager
systemctl status testbot-module-pixiv --no-pager
```

看日志：

```bash
scripts/logs.sh gateway
scripts/logs.sh -f brain
scripts/logs.sh -f bilibili
scripts/logs.sh -f ts
scripts/logs.sh -f weather
scripts/logs.sh -f pixiv
scripts/logs.sh -f render
scripts/logs.sh -f media
scripts/logs.sh -f napcat
```

只重启 Brain：

```bash
systemctl restart testbot-brain
```

改了 `brain-python/.env`、Brain Python 代码，或启用 `MEMORY_EXTRACTOR_*`
配置后，只需要重启 `testbot-brain`。Gateway、NapCat、Postgres 和外部模块不需要跟着重启，除非它们自己的配置或代码也改了。

本地 systemd 部署会用 `uvicorn --no-access-log` 启动 Brain、模块和 media，避免 `/health`、`/handle`、`/chat` 这类 HTTP access log 刷屏；应用自身的 warning/error 仍会输出。

Render 压测：

```bash
scripts/bench-render.sh bili-hot
scripts/bench-render.sh bili-cold
scripts/bench-render.sh weather-hot
scripts/bench-render.sh weather-cold
scripts/bench-render.sh all
```

查看可用服务名：

```bash
scripts/logs.sh list
```

重启某个模块：

```bash
systemctl restart testbot-module-bilibili
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8011/health
curl http://127.0.0.1:8012/health
curl http://127.0.0.1:8013/health
curl http://127.0.0.1:8014/health
curl http://127.0.0.1:8020/health
curl http://127.0.0.1:8030/health
```

Docker 基础服务：

```bash
docker compose ps postgres napcat
```

## 期望健康状态

正常启动后，应该看到：

- `systemctl status` 中 `testbot-gateway`、`testbot-brain`、各 `testbot-module-*`、`testbot-renderer`、`testbot-media` 都是 `active (running)`。
- Brain `/health` 返回 2xx，且 Brain 日志没有持续数据库连接失败、模块注册失败或 outbox token 错误。
- 模块 `/health` 返回 2xx；模块日志没有持续缺少 key/token/password 的错误。
- Renderer `/health` 返回 2xx；触发 Bilibili、天气或 TS 卡片时能生成图片 URL。
- Media `/health` 返回 2xx；开启 Bilibili 下载的白名单群里能创建 job，下载完成后通过 outbox 异步发视频。
- Gateway 日志显示已接受 NapCat WebSocket 连接；群聊或私聊命令能进入 Brain `/chat`。
- NapCat WebUI `6099` 可打开，QQ 账号在线，且没有反复掉线。

最小链路验证：

```bash
curl http://127.0.0.1:8000/health
scripts/logs.sh -f gateway
scripts/logs.sh -f brain
```

然后在 QQ 里按已启用模块测试一条确定性命令，例如 `天气 上海`、`ts人数`、`pixiv 日榜` 或一个 B 站 BV 链接。

## 配置变更后的重启

改配置后优先只重启受影响的服务：

- 改 `brain-python/.env`、`/etc/testbot/local.env` 里的 Brain 地址、AI、memory、模块注册、数据库配置：重启 `testbot-brain`。
- 改 `gateway-go` 配置、Brain 地址、NapCat 连接参数：重启 `testbot-gateway`。
- 改 `config/modules/bilibili.env`：重启 `testbot-module-bilibili`。
- 改 `config/modules/tsperson.env`：重启 `testbot-module-tsperson`。
- 改 `config/modules/weather.env`：重启 `testbot-module-weather`。
- 改 `config/modules/pixiv.env`：重启 `testbot-module-pixiv`。
- 改 renderer env、字体、模板或 asset 目录：重启 `testbot-renderer`。
- 改 media env、缓存目录、下载限制、public URL：重启 `testbot-media`。
- 改 Docker 里的 Postgres 或 NapCat 配置：重启对应 Docker 服务，再视情况重启 Gateway 或 Brain。

常用重启命令：

```bash
systemctl restart testbot-brain
systemctl restart testbot-gateway
systemctl restart testbot-module-bilibili
systemctl restart testbot-module-tsperson
systemctl restart testbot-module-weather
systemctl restart testbot-module-pixiv
systemctl restart testbot-renderer
systemctl restart testbot-media
```

如果改了 systemd unit 文件本身，先 reload：

```bash
systemctl daemon-reload
systemctl restart testbot-brain
```

`scripts/start-local-systemd.sh` 适合做一次整体刷新；日常排障时更推荐只重启相关服务，避免把正在下载或正在发送 outbox 的任务一起打断。

## 常见故障症状

### QQ 完全没有响应

优先检查：

- NapCat 是否在线，WebUI `6099` 是否能打开。
- Gateway 是否 `active (running)`，日志是否显示 WebSocket 已连接。
- Brain `/health` 是否正常。
- Gateway 日志里是否有调用 Brain `/chat` 失败、超时或返回非 2xx。
- Brain 的 group allow/block policy 是否把当前群拦掉。

### 文本命令有响应，图片或视频发不出去

优先检查 URL 可达性：

- Renderer、Media、Pixiv 返回的 URL 是否是 `host.docker.internal` 或 NapCat 能访问的真实地址。
- 从 NapCat 容器里能否访问这些 URL。
- 目标服务日志是否出现 asset 不存在、文件权限、下载失败或 404。

### 模块 `/health` 正常，但触发命令没有回复

可能原因：

- Brain 没有注册该模块，检查 `BRAIN_MODULE_SERVICE_DEFAULTS` 和 `BRAIN_MODULE_SERVICES`。
- Brain group policy 或模块自身 group policy 拦截。
- 模块 `/handle` 返回 no-reply，查看对应模块日志。
- 命令格式不匹配，先用该模块文档里的最小命令测试。

### Brain 启动失败或反复重启

优先检查：

- `DATABASE_URL` 是否正确，Postgres 容器是否健康。
- `/etc/testbot/local.env` 是否由安装脚本生成，里面的端口和 token 是否完整。
- `brain-python/.env` 是否有语法错误，比如未闭合引号或多余换行。
- 最近是否改过 Python 依赖或代码，必要时先跑 Brain 测试。

### Pixiv 健康检查失败

常见原因：

- `PIXIV_REFRESH_TOKEN` 缺失或已失效。
- 代理不可用，或 `PIXIV_TRUST_ENV_PROXY`、`PIXIV_HTTP_PROXY` 设置不符合当前网络环境。
- 字体路径不存在，导致排行榜卡片生成失败。

### Bilibili 下载任务失败

常见原因：

- 视频超过 `BILIBILI_DOWNLOAD_MAX_DURATION_SECONDS` 或 `BILIBILI_DOWNLOAD_MAX_BYTES`。
- Bilibili 返回 412 或风控。
- media service 无法写缓存目录，或 ffmpeg/yt-dlp 不可用。
- 下载完成后的 `MEDIA_PUBLIC_BASE_URL` 对 NapCat 不可达。

## URL 可达性排查

本地宿主机检查服务本身：

```bash
curl -i http://127.0.0.1:8020/health
curl -i http://127.0.0.1:8030/health
curl -i http://127.0.0.1:8014/health
```

从 NapCat 容器里检查 public URL：

```bash
docker compose exec napcat sh -lc 'wget -S -O- http://host.docker.internal:8020/health'
docker compose exec napcat sh -lc 'wget -S -O- http://host.docker.internal:8030/health'
docker compose exec napcat sh -lc 'wget -S -O- http://host.docker.internal:8014/health'
```

如果容器里不能解析 `host.docker.internal`，检查 compose 里是否给 NapCat 配置了 host gateway 映射。临时验证时也可以把 public URL 改成宿主机内网 IP，例如 `http://192.168.x.x:8020`，但要保证防火墙允许容器访问。

排查顺序：

1. 先确认宿主机 `127.0.0.1:<port>/health` 正常。
2. 再确认 NapCat 容器能访问 public base URL。
3. 再触发一次实际命令，观察 Gateway、Brain、对应模块、renderer/media/Pixiv 的日志。
4. 如果只有大图或视频失败，小图成功，继续检查资源大小限制、下载 job 状态和 NapCat 日志。

## 配置文件

模块原配置仍在：

- `/root/TestBot/config/modules/bilibili.env`
- `/root/TestBot/config/modules/tsperson.env`
- `/root/TestBot/config/modules/weather.env`
- `/root/TestBot/config/modules/pixiv.env`（Pixiv，默认端口 `8014`）
- `/root/TestBot/config/modules/render.env`

本地部署统一覆盖地址的文件是：

- `/etc/testbot/local.env`

通常只改 `config/modules/*.env` 即可。只有端口、数据库、公共 URL 这类本地运行参数才改 `/etc/testbot/local.env`。
