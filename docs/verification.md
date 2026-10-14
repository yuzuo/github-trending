# 本地验证记录

## 2026-10-14 · 采集项目观察

- 后端 67 项测试通过，包含真实 PostgreSQL 独立测试库及随机 schema；前端 17 项测试通过，生产构建通过。覆盖发现查询接续、跨榜限流、容量、测评保存、公开仓库限制、增长基准、数据过期、重试与前端请求竞态。
- 独立复查发现并修复：持续失败导致健康项目停止更新；发现缓存过期后未再次验证仓库公开性；保存过程中重开详情带入旧笔记；页面长期打开时数据新鲜度不更新。均有回归测试。
- 原数据库已备份至 `.local/backups/before-crawler-watch-20261014.dump`（554,758 字节）；只新增观察模块表，未删除历史榜单数据。API 和 Web 已重建并更新，`/api/health` 与观察接口均返回 200。
- 浏览器验证 `/crawler-watch` 页面、真实添加 `scrapy/scrapy`、原文 README、观测样本、人工测评表单及保存反馈。未给项目编造评分或测评结论。
- 真实 GitHub 首次发现任务进入部分完成，并正确记录匿名 API 限流及冷却时间；不将其记为完整领域采集通过。项目发现恢复会从已保存的查询检查点继续。
- 冷却后第二次真实任务接续成功，新增 28 个项目，连同手动保存的 Scrapy 共 29 个；包括 Firecrawl、Scrapling、Crawl4AI 和 MediaCrawler。随后触发匿名小时额度限制，页面记录下一次可重试时间为北京时间 2026-10-14 13:48。原库 8 条 Trending、1,000 条 Search 快照保持存在。
- 本机 `SCHEDULE_ENABLED=false`，`GITHUB_TOKEN` 未配置。保留原有自动采集关闭状态，等待用户选择自动监测范围；手动更新可用。新模块不调用翻译服务。

以下为历史验证记录，配置与数量均对应记录时点。

验证日期：2026-10-12，Asia/Shanghai。

## 总榜每日 01:00、100 项独立快照

- Mac 已部署 `SEARCH_LIMIT=100`、`COLLECT_HOUR=1`，自动采集开启；与 Trending 依次执行，总榜不创建翻译器。
- Search 新增完整资料 JSONB 快照，按日期展示元数据及 README 原文。每天首次成员列表冻结，失败重试不重新搜索或覆盖完成项目，成功当日不再重复采集。
- 后端 52/52、前端 11/11 测试通过，包含 100 项采集、最后一项失败后跨进程式重试、翻译器零调用、01:00 时间边界、跨日原文保留及详情日期路由。
- Mac 原有 1,000 条总榜保留并标记 `legacy_backfill`；迁移重复运行两次，原字段汇总哈希前后一致。备份位于 Mac 项目 `backups/before-search-archive.dump`。
- Mac API/Web 镜像构建与健康检查通过；Windows 经局域网检查历史总榜数量、带日期详情、Stars 与列表一致及 `/stars` HTTP 200。
- 新日期按 100 项采集，旧日期仍显示原有 1,000 项。未等待实际凌晨触发；GitHub 限流时可能分多次补齐，电脑与 Docker 必须运行。

## Mac 局域网部署与数据迁移

- 部署到 `xai@192.168.1.23:/Users/xai/Workspace/github-trending`，Mac arm64 原生构建 API/Web 镜像，PostgreSQL 16 独立数据卷；已有其他 Docker 项目未修改。
- 迁移前停止 Windows 采集并生成 `.local/backups/mac-migration.dump`（554,758 字节）。备份传输 SHA256 一致：`72332231b6df14e9838b96c8d5cea8466b3dccf1537305f511263300c68140c5`。
- 恢复使用 `pg_restore --exit-on-error --single-transaction`。四张表逐行摘要汇总哈希与源库完全一致：repositories 1,002、search_snapshots 1,000、trending_snapshots 8、collection_runs 7。
- 从 Windows 经局域网实测 `192.168.1.23:8080`：健康接口、两页面、两榜数量、带日期的历史详情以及中英文 README 均通过。
- Mac 开启自动采集（Trending 01:00、Search 09:00），DeepSeek 配置随项目安全迁移；Windows 已关闭自动采集并恢复本地 API，避免两端自动重复采集。迁移后没有双向同步。
- 未修改 Mac 休眠或 Docker 登录启动设置，需主机持续唤醒且 Docker 运行。Mac 迁移前可用空间约 16 GB；旧数据及本机备份保留。嵌入浏览器访问超时，局域网 HTTP/API 验证通过，未声称本次完成 Mac 页面视觉检查。
- 运维步骤见 `docs/deployment-mac.md`。SSH 密码未写入文件，远端 `.env` 与迁移包/备份权限为 600。

## 每日独立快照与 01:00 调度

- 已部署 Trending 每天北京时间 01:00 自动采集，`.env` 的 `TRENDING_COLLECT_HOUR=1`、`SCHEDULE_ENABLED=true` 已生效；Search 保留 09:00 配置且不翻译。
- 每日 Trending 保存独立的完整 JSONB 资料快照；首次成员列表冻结，同日失败重试只补缺失项目或失败译文。跨日、共享缓存更新、历史筛选及历史详情均有回归覆盖。
- 后端 PostgreSQL 测试 49/49、前端 11/11 通过，Docker API/Web 生产镜像构建成功，API/数据库健康。
- 审查复现并修复了“首次页面失败、第二次部分成功、重启后丢失待补成员”的迁移问题；新增重启回归先失败、修复后通过。
- 迁移前备份 `.local/backups/before-daily-archive.dump`，443,949 字节。迁移重复执行两次，1,002 个项目的全字段哈希及 1,000 条 Search、8 条 Trending 原有字段完全一致。
- 8 条旧 Trending 已标记 `legacy_backfill`：其历史 Star/排名保留，其他资料由迁移时最新版本回填。新采集标记 `captured`，README 中提供分析 SQL。
- 浏览器验证每日榜单、所选日期的 Stars/采集时间、旧数据提示及中文 README；线上 API 检查健康、两榜数量与日期详情通过。
- 之前批量补翻结束时 6 项成功、2 项网络失败；新服务启动后已自动重试失败项目，成功项目不重复翻译。未宣称所有译文完成，也未逐句审校。
- 未实际等到凌晨 01:00；通过北京时间 00:59/01:00 边界测试。电脑、Docker 需保持运行，停机期间无法补回错过的真实历史榜单；局域网另一台设备访问仍未验证。

## 仅 Trending 翻译

- 已部署来源限制：只有 Trending 创建 DeepSeek 翻译器；Search 保存函数即便被传入翻译器，也不会调用翻译。共用项目的已有译文保留，原文变化后由 Trending 补翻。
- 后端 40/40、前端 10/10 测试通过，生产构建通过。包含 Search 不产生翻译调用、共用译文保留、后续新增 README 能在 Trending 翻译的回归测试。
- 总榜页面只显示原文，不显示翻译状态/中文切换/翻译警告；浏览器验证通过。Trending 保留中文阅读。
- 当前 Trending 8 项补翻任务已启动，记录时 4 项完成，其余后台执行；未声称全部完成。任务容器 `github-trending-api-run-7d48e8f0b5c9`。
- `.env` 已恢复 `SCHEDULE_ENABLED=true`；已启动等待补翻完成后重建服务的进程，恢复结果记录 `.local/trending-backfill-finish.log`。当前运行中的 API 暂仍关闭自动采集，避免与补翻冲突。新增 README 边界修复镜像已构建，随该重建生效。
- 译文未逐句人工审校，Trending 后续更新会消耗 DeepSeek 额度；Star 总榜不会触发翻译费用。

## DeepSeek 实际翻译

- 已配置官方 `https://api.deepseek.com` 和 `deepseek-flash`，使用本地 `.env` 中的密钥，未输出密钥。重建后端后确认翻译已启用。
- 仅翻译 `boykopovar/AnyPS5`（ID 1322250666）的完整 README 和简介：原文 2,466 字符，中文 README 1,394 字符；调用成功、保护占位符完整、数据库保存成功，原文未改动。
- API 返回 `translation_status=translated`、`translation_stale=false`；浏览器已显示中文简介、“已翻译”及中文 README，链接、代码与原文切换可用。
- `SCHEDULE_ENABLED=false`，自动采集暂时暂停，防止单项目验证期间触发批量付费翻译。未批量翻译其他项目；未逐句人工审校译文。

## IP 访问配置

- Docker Web 监听已改为 `0.0.0.0:8080`，`.env` 配置 `APP_ORIGIN=http://192.168.1.169:8080`，服务已重建，API/数据库健康。
- 后端 38/38 测试通过，覆盖配置 IP、localhost、127.0.0.1 的读取和采集，以及不受信任 Host/Origin 的拒绝；localhost 两页面与健康接口实测返回 200。
- 当前 Windows 上直接访问 `192.168.1.169:8080` 仍超时，未发现本机 TCP 8080 监听。添加定向 portproxy 的命令被 Windows 拒绝：需要管理员权限（不是自动审批拒绝）；转发尚未创建，命令已记录在 README。
- 尚未验证局域网另一台设备访问；没有修改 Windows 防火墙和已有 8081 转发。应用无登录认证，仅用于可信网络。

## 两张榜单表与两个页面

- `trending_snapshots` / `search_snapshots` 独立存储；旧 `daily_snapshots` 按来源迁移后移除。迁移前业务库备份 `.local/backups/before-two-sources.dump`，399,892 字节。
- 迁移前后逐字段比较：Search 1,000 条、Trending 8 条全部一致；1,002 个共用项目的全部资料（含 README 和译文）哈希一致；重复执行迁移通过。
- 后端 PostgreSQL 测试 37/37 通过，新增两张物理表、混合/早期数据迁移、冲突回滚、来源校验、Trending 解析/令牌隔离及首次启动任务互斥回归测试。
- 前端测试 10/10 通过，Docker 生产构建通过；浏览器由 `/trending` 导航至 `/stars`，分别显示 8 和 1,000 个项目，导航正确标记当前页面。
- 两个来源 API 分别按今日新增和累计 Stars 排序，日期与任务查询按来源隔离；两个页面及健康接口返回 HTTP 200。PostgreSQL 与 API 容器健康。
- 真实 Trending 页面解析成功 8 项；每日双来源调度与手动来源路由已测试。未等待到次日验证定时触发，未完成 1,000 项 README 补全或真实汉化；已有 Search 失败状态保留，未将其改写为成功。

## Top 1,000 初始化

- 本地 `.env` 的 `SEARCH_LIMIT` 已设为 1,000，API 容器已重新加载配置。
- 官方 Search API 完整获取 10 页、1,000 个唯一公开仓库，项目元数据及今日 Search 快照在同一事务中入库；没有清空已有 README、译文或 Trending 历史。
- 入库断言验证数量 1,000、ID 唯一、排名覆盖 1–1,000，以及项目地址、创建/更新时间和采集时间；API 返回 1,000 项且按总 Star 降序，浏览器显示“Star 总榜 1,000 个项目”及 1,000 张项目卡片。
- 当前榜单 14 项已有 README，其余仅完成元数据初始化，提示“README 待采集”；汉化服务仍未配置。旧 Trending 快照 8 条保留。
- 一次性初始化脚本及原始搜索结果保存在 `.local/initialize_top1000.py` 和 `.local/top1000-search.json`，既有采集任务状态仍表示其 README/翻译执行结果，不代表这次元数据初始化数量。

## GitHub Search API 接入验收

- 已部署官方 Search API 总 Star 降序榜，默认 Top 30；前端同步改为 Star 总榜。
- 真实 Search 请求取得完整 30 项，顺序校验通过；广域查询返回 incomplete_results 时，限定至少 1,000 Stars 的重试取得完整结果，且结果数量足以覆盖 Top 30。
- PostgreSQL 独立测试库上的后端测试 30/30 通过，包含旧数据迁移、来源隔离、同日榜单成员更新和 Search 分页/异常；前端测试 7/7 及生产构建通过。
- 部署前备份位于 `.local/backups/before-search-api.dump`，75,742 字节。迁移后原有 8 条 Trending 快照保留，可通过 `source=trending` 查询。
- 实际采集任务 ID 4：成功 8、失败 22。未认证 GitHub API 在 README 获取阶段触发限流，记录冷却结束时间 2026-10-12 16:51:27（Asia/Shanghai），由既有调度器后续重试；未声称完整 30 项已入库。
- `/api/health` 返回正常；默认榜单返回 8 项且按累计 Stars 降序。浏览器验证新标题、排名、累计 Stars、Top 30 配置说明及“部分完成 / 请求限流”提示。
- 真实翻译服务仍未配置、未验证；请在本地 `.env` 配置 GitHub Token 和兼容 OpenAI 的翻译服务后重建 API 容器。

## 初始 Trending 版本验收（切换前）

- Docker Compose 三个容器已启动，PostgreSQL 16 和 API 健康检查通过，Web 监听 127.0.0.1:8080。
- PostgreSQL 独立测试库上的后端测试 23/23 通过，覆盖真实 SQLAlchemy 查询、唯一约束、事务和 advisory lock。测试未修改业务数据库。
- 前端测试 7/7 通过，生产构建通过。测试覆盖恶意 Markdown、相对链接/图片/章节链接和任务轮询。
- 真实 GitHub Trending 页面解析到 8 个项目；启动采集和手动采集均成功 8、失败 0。第二次采集后仍为 8 条唯一项目快照。
- 浏览器验证榜单、项目详情、创建/更新/推送/采集时间、原文 README、搜索和手动采集状态。
- 重建 API/Web 并重启数据库后，8 条项目记录及任务 ID 2 保留，未重复启动当日成功任务。
- `/api/health` 返回 `{"status":"ok"}`，`/api/docs` 返回 HTTP 200。

当前 `.env` 已生成本地数据库密码，未设置 GitHub Token 或翻译服务凭证。真实翻译供应商调用和翻译质量未验证；翻译协议、失败处理及保护机制通过模拟 HTTP 测试验证。没有伪造中文译文。

本机 Docker 凭据助手路径异常，验证使用项目内 `.local/docker/config.json` 空配置。Nginx 镜像站曾返回 EOF，已从 Docker 官方地址拉取公开镜像并标记供本地构建使用；没有修改全局 Docker 配置。

后端测试依赖 Starlette 对 httpx TestClient 有弃用提示，测试仍通过；尚未切换到新的测试传输依赖。当前目录不是 Git 仓库，未创建提交或远程 PR。
