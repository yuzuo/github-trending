# 项目动态监测实施计划

目标：在采集项目观察中，对已关注、未隐藏项目持续检查 Release 与 Issue，展示原文证据及状态变化。

沿用用户已认可的动态监测设计。第一版采用确定性同步和站内未读，不执行第三方代码，不自动声称功能已验证或 Issue 已修复，不发送外部消息。

架构：新增独立 monitor_states、monitor_events、monitor_runs 表，保留现有项目与人工笔记。共用采集线程、PostgreSQL 锁、GitHub 冷却时间及 SCHEDULE_ENABLED。自动调度优先检查关注动态，再执行原有榜单和发现。

- [ ] 先写数据源与 PostgreSQL 集成测试：过滤 PR/草稿、分页恢复、基线、去重、关闭重开、未读竞态、隐藏、冷却与恢复。
- [ ] 实现 monitor.py；models.py 新增表；collector.py 共享冷却；main.py 接入生命周期和调度；watch_api.py 增加动态接口。
- [ ] 新增 Monitor.vue 并接入 Watch.vue：动态筛选、原文、状态历史、已读、立即检查、项目同步状态。
- [ ] 运行后端真实 PostgreSQL 测试、前端测试与构建；检查新旧功能、升级保留数据。
- [ ] 同步到已有 23 服务器：备份数据库与代码，构建切换，验证 API/页面/真实同步。

范围边界：Release 每次读取最新 30 条；Issue 首次读取最近 30 天更新的记录，随后按更新时间增量遍历，每项目每轮最多 3 页，未完成时保留游标。首次数据是历史基线；新事件和标题、正文、标签、状态变化重新标记未读，单纯评论数增长不重复通知。每条事件保留最近 20 次变化摘要。无 LLM 推断、关联 PR 自动归因或真实采集复现。来源资料不等于已验证结论。

验收：重复同步不重复事件；异常/限流不前移未完成分页游标；取消关注及隐藏项目不发请求；Issue 关闭不显示为已修复；旧版本数据、笔记和榜单不被覆盖。API 限定筛选和分页范围，写入保持现有同源检查。

参考：[GitHub Release API](https://docs.github.com/en/rest/releases/releases)、[GitHub Issue API](https://docs.github.com/en/rest/issues/issues)。
