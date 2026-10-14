# Mac 局域网部署

- 主机：`192.168.1.23`，用户：`xai`。
- 项目目录：`/Users/xai/Workspace/github-trending`。
- 每日榜：`http://192.168.1.23:8080/trending`。
- Star 总榜：`http://192.168.1.23:8080/stars`。
- Docker Compose 项目名 `github-trending`，独立数据卷 `github-trending_postgres_data`。
- `.env` 保存数据库及 DeepSeek 配置，权限 600；不记录 SSH 密码。

## 启停与日志

在 Mac 终端执行：

```sh
cd /Users/xai/Workspace/github-trending
export PATH=/usr/local/bin:/opt/homebrew/bin:$PATH
docker compose ps
docker compose logs --tail=100 api
docker compose up -d
docker compose stop
```

Mac 是自动采集主机：Trending 每天北京时间 01:00，总榜同为 01:00（前 100 项），两榜依次执行，只有 Trending 使用 DeepSeek 翻译。本机 Windows 的 `.env` 已关闭自动采集，保留项目和数据库副本。迁移是一次性数据同步，之后两台数据库不会双向同步，请在 Mac 服务上操作。

调度依赖 Mac 开机、保持唤醒且 Docker 正常运行；重启后需确保 Docker Desktop 已启动。未修改 macOS 的休眠或登录启动设置。

## 数据备份

迁移备份 `mac-migration.dump` 保存于项目根目录（权限 600）。对应 Windows 备份为 `.local/backups/mac-migration.dump`。不要使用 `docker compose down -v`，该命令会删除数据卷。

后续备份：

```sh
docker compose exec -T db pg_dump -U trending -Fc -f /tmp/trending.dump trending
docker compose cp db:/tmp/trending.dump ./trending.dump
chmod 600 trending.dump
```

应用没有登录认证，仅用于可信局域网；数据库/API 不发布宿主端口。IP 变化时更新 `.env` 的 `APP_ORIGIN`，再执行 `docker compose up -d`。
