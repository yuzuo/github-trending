# 完整数据库快照：公开脱敏版

文件：[trending-20261023-public.dump](trending-20261023-public.dump)

- 源数据：23 服务器 2026-10-23 16:50（北京时间）的应用数据库一致性备份。
- 格式：PostgreSQL 16 custom archive，可用 `pg_restore` 恢复。
- 包含全部 **17 张业务表、10,488 条记录**，以及表结构、索引、约束和序列等数据库对象。
- 文件大小：31,143,948 字节。
- SHA-256：`8427a6cfa45a53fe611194704099e19afa21be9e4b69334d3ed06f05c606049f`。

## 与原始私有备份的区别

本文件用于公开仓库分发，不是原始备份的逐字节副本：

- 遮盖采集文档、动态和分析中 54 处疑似凭据或含用户名/密码的连接字符串，替换为 `[REDACTED]`。
- 清空 3 条非空项目笔记，不删除对应项目记录。
- 未删除业务表或记录，保留历史快照、关注状态、样本、动态、分析和验证结果。
- 部分原始文档及证据摘录因脱敏已改变，不应用此副本做逐字节证据鉴定。

原始私有备份保存在部署方 `.local/backups/full-20261023T085044Z/`，未提交 GitHub。环境配置、Token、角色密码、Docker 镜像、数据库外测试归档均不包含在本文件中。

已检查 GitHub Token、常见 API Key、AWS Key、私钥标记和含认证信息的 URL 样式；发布版复查无命中。模式扫描不等于能识别所有类型的秘密信息。

## 全新部署恢复

先按主 README 配置 `.env`，将 `SCHEDULE_ENABLED=false`，暂不启动 API、Web 或宿主机 worker。启动空 PostgreSQL 数据卷：

```sh
docker compose up -d db
docker compose ps
```

等待数据库健康，复制并恢复到**尚未初始化应用表的空 `trending` 数据库**：

```sh
docker compose cp data/backups/trending-20261023-public.dump db:/tmp/trending-public.dump
docker compose exec -T db pg_restore -U trending -d trending --no-owner --no-privileges --exit-on-error /tmp/trending-public.dump
docker compose up -d --build
```

此快照已经包含初始化项目，不要再导入 `watch-projects.seed.sql`。先核对页面和各表，再根据需要开启调度、重建 API/Web 并启动 worker。历史运行状态和冷却时间会一并恢复。

**不要恢复到已有业务库，不要为恢复执行 `docker compose down -v`。** 已有数据库请先备份，再创建独立空库验证，最后单独安排切换。`--no-owner --no-privileges` 让现有数据库用户拥有恢复对象，不要求导入原集群的角色密码。

## 独立恢复验证

已对本发布文件执行独立空库全量恢复，`pg_restore --exit-on-error` 成功退出；归档复查为 17 张表、10,488 行。需要自行验证时使用尚不存在的测试库名：

```sh
docker compose cp data/backups/trending-20261023-public.dump db:/tmp/trending-public.dump
docker compose exec -T db createdb -U trending -T template0 trending_public_restore_test
docker compose exec -T db pg_restore -U trending -d trending_public_restore_test --no-owner --no-privileges --exit-on-error /tmp/trending-public.dump
```

| 表 | 记录数 |
| --- | ---: |
| analysis_runs | 192 |
| collection_runs | 158 |
| event_analyses | 465 |
| monitor_events | 675 |
| monitor_runs | 110 |
| monitor_states | 13 |
| project_profiles | 1 |
| repositories | 1020 |
| search_snapshots | 2100 |
| trending_snapshots | 134 |
| validation_jobs | 30 |
| validation_results | 2 |
| validation_tracking | 10 |
| validation_worker_state | 1 |
| watch_projects | 200 |
| watch_runs | 194 |
| watch_samples | 5183 |

这是一份静态快照，不会随线上数据库更新。文件作为明确授权的公开备份单独纳入 Git；其他 `.dump` 文件仍由 `.gitignore` 忽略。
