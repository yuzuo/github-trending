# 23 服务器初始化项目数据

`watch-projects.seed.sql` 是 2026-10-23 从 23 服务器导出的公开项目清单快照，共 **200 个项目、13 个关注项目**，包含 yt-dlp。

## 范围

包含仓库 ID、名称、GitHub URL、观测时的 Star 数、语言、许可证标识、原观测时间，以及手动添加和关注状态。数据由多次只读 API 请求导出，不是数据库事务一致性备份。

不包含 `.env`、Token、密码、私人笔记、评分、README 正文、账号使用档案、两榜历史快照、Star 历史样本、Release/Issue 正文、模型分析或测试结果。完整运行数据仍需按主 README 使用独立数据库备份迁移。

这是导出日的数据，不保证导入时仍为最新。首次刷新会补齐项目简介、README 等资料。导入不伪造历史样本，增长指标需要后续实际采样积累。

## 首次部署时导入

1. 按主 README 配置 `.env`，暂设 `SCHEDULE_ENABLED=false`，防止自动发现提前填满名额。
2. 在项目根目录执行 `docker compose up -d --build`，等待 API 健康、数据库表初始化完成。
3. 执行以下命令（PowerShell、macOS、Linux 均可，不需要管道重定向）：

```sh
docker compose cp data/watch-projects.seed.sql db:/tmp/watch-projects.seed.sql
docker compose exec -T db psql -X -U trending -d trending -v ON_ERROR_STOP=1 -f /tmp/watch-projects.seed.sql
```

4. 核对数量：

```sh
docker compose exec -T db psql -X -U trending -d trending -c "SELECT count(*) AS projects, count(*) FILTER (WHERE followed) AS followed FROM watch_projects;"
```

全新数据库应显示 200 个项目、13 个关注。随后将 `.env` 的 `SCHEDULE_ENABLED` 改回 `true`：

```sh
docker compose up -d --force-recreate api web
```

打开 `/crawler-watch` 查看项目和「我的关注」。需要自动版本验证时另行启动宿主机 worker。

## 重复导入和已有数据库

- 脚本在事务中执行，并使用与应用一致的容量锁。
- 按 GitHub 仓库 ID 去重；已有项目保持原来的关注、笔记、评分与隐藏状态，不覆盖。
- 新项目会导入导出时的关注状态；测评状态从 `pending` 开始。
- 导入后活动项目会超过 200 个时，整次导入失败，不会部分写入。不要通过删除已有业务数据强行导入。
- 23 服务器已拥有这些项目，无需将此文件重新导入生产库。

## 关注清单

导出时关注：D4Vinci/Scrapling、scrapy/scrapy、cv-cat/Spider_XHS、TeamWiseFlow/xiaobei、201206030/novel-plus、dataabc/weibo-crawler、yt-dlp/yt-dlp、NanmiCoder/MediaCrawler、Evil0ctal/Douyin_TikTok_Download_API、Jack-Cherish/python-spider、JoeanAmier/TikTokDownloader、instaloader/instaloader、cv-cat/XHS_ALL_IN_ONE。

## 导入自检

在已初始化应用表结构的数据库中运行以下检查。测试写入会话临时表，不修改真实项目表；最后应输出 `PASS`。其中一次容量错误和随后事务终止是预期测试结果。

```sh
docker compose cp data/watch-projects.seed.sql db:/tmp/watch-projects.seed.sql
docker compose cp data/test-seed.sql db:/tmp/test-seed.sql
docker compose exec -T db psql -X -U trending -d trending -v ON_ERROR_STOP=1 -f /tmp/test-seed.sql
```
