# TestBot 低配本地部署

适合 2C4G 这类机器：只保留 `postgres` 和 `napcat` 在 Docker，其他服务全部用宿主机 systemd 运行。

## 运行形态

- Docker: `postgres`, `napcat`
- systemd: `testbot-gateway`, `testbot-brain`, `testbot-module-bilibili`, `testbot-module-tsperson`, `testbot-module-weather`, `testbot-renderer`, `testbot-media`

当前本地 systemd 脚本仍只安装上面这 3 个模块。Pixiv 这次只预留了 compose
和配置文件入口，未在现有脚本里新增 `testbot-module-pixiv` unit，因此不会影响
现有 bilibili/tsperson/weather 运行。

本地服务之间全部走 `127.0.0.1`。发给 NapCat 拉取的图片和视频 URL 使用：

- `http://host.docker.internal:8020`
- `http://host.docker.internal:8030`

因为 NapCat 仍在 Docker 容器里。

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
```

看日志：

```bash
scripts/logs.sh gateway
scripts/logs.sh -f brain
scripts/logs.sh -f bilibili
scripts/logs.sh -f ts
scripts/logs.sh -f weather
scripts/logs.sh -f render
scripts/logs.sh -f media
scripts/logs.sh -f napcat
```

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
curl http://127.0.0.1:8020/health
curl http://127.0.0.1:8030/health
```

## 配置文件

模块原配置仍在：

- `/root/TestBot/config/modules/bilibili.env`
- `/root/TestBot/config/modules/tsperson.env`
- `/root/TestBot/config/modules/weather.env`
- `/root/TestBot/config/modules/pixiv.env`（Pixiv 预留，默认端口 `8014`）
- `/root/TestBot/config/modules/render.env`

本地部署统一覆盖地址的文件是：

- `/etc/testbot/local.env`

通常只改 `config/modules/*.env` 即可。只有端口、数据库、公共 URL 这类本地运行参数才改 `/etc/testbot/local.env`。
