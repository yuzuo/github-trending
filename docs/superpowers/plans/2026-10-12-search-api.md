# 官方 Search API 切换

用户要求将采集服务切换为 GitHub 官方 Search API，按总 Star 全站搜索排序。沿用既有 README、翻译、日期归档和 Docker 部署。

1. 测试后替换 HTML scraper：GET /search/repositories，q=stars:>0 is:public fork:true，sort=stars，order=desc；每页最多100，最多1000。严格检查 incomplete_results、分页重复、空结果和无效字段，不伪造增长量。复用返回的仓库资料，逐个获取 README。
2. PostgreSQL 启动迁移：快照和任务添加 source，已有行标为 trending，新采集写 search；唯一约束改为仓库+日期+来源。迁移可重复执行且先备份现有业务库。API 默认查询 search，保留 source=trending 的只读历史查询。
3. 采集配置增加 SEARCH_LIMIT；页面改为总 Star 排序，隐藏当天增长，返回 rank 字段并保留旧字段以兼容调用方。定时任务不会被当天 Trending 成功记录阻止。
4. 更新部署说明及环境变量；运行 Search mock 测试、PostgreSQL 迁移/数据隔离/排序测试、前端测试与构建，部署并验证真实搜索采集。

范围：backend/app/sources.py、collector.py、models.py、database.py、main.py、config.py，相关测试与旧 HTML fixture；frontend 页面文案和排名；compose.yaml、.env.example、README、验证记录。原文/译文不删除，旧 Trending 数据不混入总榜。无需新增服务或依赖；移除不再使用的 HTML 解析依赖。
