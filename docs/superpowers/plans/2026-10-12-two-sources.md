# 两路采集、两张榜单表与两个页面

> 使用 executing-plans 执行后端与迁移，按 subagent-driven-development 分派独立前端任务。

目标：Trending 每日趋势榜与 Search Star 总榜独立存储、采集、调度和展示。

设计：`trending_snapshots` 与 `search_snapshots` 各自以项目和日期唯一；共用 `repositories` 中的项目资料/README、带 source 的 `collection_runs`。旧 `daily_snapshots` 事务内按来源迁移，逐字段核验后移除，部署前保留 pg_dump 备份。保留既有查询接口 source 参数及默认 Search 行为。

- [x] 后端测试先覆盖两张物理表、重复迁移、两个来源同日隔离、独立调度及采集参数校验。
- [x] 修改 models/database/collector/main；恢复 Trending 页面解析与仓库资料接口。测试 fixtures 使用小型 HTML，验证无效页面不会覆盖已有数据。
- [x] 前端分别提供 `/trending`、`/stars`；导航、文案、排序指标、日期、状态与采集均按来源隔离，详情共用。
- [x] PostgreSQL 独立测试库、前端测试与生产构建通过后，备份业务库并部署。
- [x] 校验迁移前后行数、README 内容、两个 API 与页面可用；更新 README 和验证记录。

范围外：用户管理、分页重设计、翻译供应商配置。外部限流仍如实显示，不把元数据初始化冒充 README/汉化完成。
