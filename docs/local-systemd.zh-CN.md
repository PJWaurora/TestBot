# TestBot 低配本地部署

适合 2C4G 这类机器：只保留 `postgres` 和 `napcat` 在 Docker，其他服务全部用宿主机 systemd 运行。

## 运行形态

- Docker: `postgres`, `napcat`
- systemd: `testbot-gateway`, `testbot-brain`, `testbot-module-bilibili`, `testbot-module-tsperson`, `testbot-module-weather`, `testbot-renderer`, `testbot-media`

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

安装脚本会生成 `/etc/testbot/local.env`，从 `/root/TestBot/.env` 读取数据库密码和 `OUTBOX_TOKEN`，再把模块、renderer、media 的地址改成本地地址。

## 常用命令

查看状态：

```bash
systemctl status testbot-gateway testbot-brain testbot-module-bilibili testbot-module-tsperson testbot-module-weather testbot-renderer testbot-media --no-pager
```

看日志：

```bash
journalctl -u testbot-gateway -f
journalctl -u testbot-brain -f
journalctl -u testbot-module-bilibili -f
journalctl -u testbot-module-tsperson -f
journalctl -u testbot-module-weather -f
journalctl -u testbot-renderer -f
journalctl -u testbot-media -f
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
- `/root/TestBot/config/modules/render.env`

本地部署统一覆盖地址的文件是：

- `/etc/testbot/local.env`

通常只改 `config/modules/*.env` 即可。只有端口、数据库、公共 URL 这类本地运行参数才改 `/etc/testbot/local.env`。
