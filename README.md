# 开源观察 · 每日趋势与 Star 总榜

每天分别采集 GitHub Trending 每日趋势榜及官方 Search API 累计 Star 总榜（公开仓库，包含 fork）。两张独立榜单表对应两个页面，分别冻结当日项目资料；仅 Trending 自动翻译简介和 README，总榜只展示原文且不调用翻译服务。

技术栈：FastAPI、SQLAlchemy 2、PostgreSQL 16、Vue 3、Vite、Nginx、Docker Compose。

## 采集项目观察与测评

打开 `/crawler-watch`（本机为 http://localhost:8080/crawler-watch）使用独立的爬虫与数据采集观察模块：

- **自动发现**：每天通过 `web-scraping`、`crawler`、`data-extraction` 主题和网页抓取、爬虫、数据采集相关关键词搜索公开仓库。每条查询取 Stars 前 30 项与最近更新前 20 项，排除 fork 和归档仓库，按仓库 ID 去重。结果属于有限候选集合，不代表全站完整领域排名。
- **手动保存**：输入 `owner/repo` 或 GitHub HTTPS 仓库地址添加并关注；已有项目不重复建立。支持全部项目、我的关注、待测评、已隐藏视图及名称/描述、语言筛选。
- **热度监测**：每 6 小时更新一次，支持立即更新；显示累计 Stars、约 24 小时和约 7 天的净增长。默认按 7 天增长排序，缺少基准时置后并显示“积累中”。首日可以切换累计 Stars 排序。
- **真实数据口径**：增长为最新样本减基准样本；基准选目标时间之前最近且相差不超过 6 小时的观测，详情展示实际区间。允许负增长；不从旧榜单、GitHub Trending 数字或估算数据补造历史。超过 12 小时没有成功样本的项目标记过期，增长排序置于有指标的新鲜项目之后。
- **人工测评**：详情内阅读 README 原文与最近 100 次观测，保存“待测评 / 测评中 / 已测评 / 暂不考虑”、可选 1–5 分评分及最多 20,000 字符的纯文本笔记。评分不代表自动质量评估。
- **容量与隐藏**：最多 200 个活动项目；先更新现有项目，再用自动发现候选按累计 Stars 填补名额。隐藏停止监测但保留记录、笔记和样本，且不会被自动发现重新激活。恢复同样受容量限制。

`SCHEDULE_ENABLED` 同时控制原有两榜和观察模块；开启后启动服务会检查观察任务是否到期。观察频率和容量在本版固定为 6 小时及 200 项。失败/中断任务按小时重试，与两榜共享任务互斥及 GitHub 冷却，优先尝试原有榜单任务。重试保留当天已完成的搜索查询，避免限流后重复从头查询；本轮已成功且不足 6 小时的项目跳过重复请求，长期失败不会永久冻结其他项目。运行时新增项目需等待正在执行的采集结束。

建议配置 `GITHUB_TOKEN`：完整监测最多需要每项目两次 GitHub 请求，发现另有最多 12 次搜索请求及新项目资料/README 请求。匿名限流可能使一轮任务分多次完成；不能承诺每个项目始终按时更新。发现缓存中的项目在保存前重新确认公开状态。新模块不自动翻译，不增加模型调用费用，不执行仓库代码，也不发送外部通知。

数据独立保存在 `watch_projects`、`watch_samples`、`watch_runs`；原有两榜的快照规则不变。应用没有登录，测评笔记为该部署共享数据，可访问应用的人能够查看与编辑。升级前按本文备份数据库，执行 `docker compose up -d --build` 更新服务。

接口：`GET/POST /api/watch/projects`、`GET/PATCH /api/watch/projects/{id}`、`GET /api/watch/run`、`POST /api/watch/refresh`（JSON `{}`）。写入只接受同源 JSON 请求；具体字段见 `/api/docs`。

## 本地启动

需要 Docker Desktop（Linux containers）和 Docker Compose v2。

1. 复制 `.env.example` 为 `.env`，设置 `POSTGRES_PASSWORD`。当前工作目录若已存在 `.env`，请直接编辑，不要覆盖它。
2. 填写翻译服务的三个变量；建议同时设置 GitHub Token。
3. 启动：

```sh
docker compose up -d --build
```

打开 http://localhost:8080/stars 查看 Star 总榜，或 http://localhost:8080/trending 查看每日趋势榜。Web 监听所有 IPv4 网卡，数据库和 API 不发布宿主端口。

局域网访问：在 `.env` 设置 `APP_ORIGIN=http://服务器IP:8080`（端口与 `WEB_PORT` 一致），执行 `docker compose up -d --build` 后，通过该地址的 `/stars` 或 `/trending` 访问，localhost 仍可使用。IP 变化后更新 `APP_ORIGIN` 并重建容器；不要填写 `0.0.0.0` 作为访问地址。若其他设备不能连接，检查宿主机防火墙及设备是否在同一网络。应用没有登录认证，可连接该端口的人能查看数据、触发采集；仅用于可信网络。

本机 Docker Desktop 实测 localhost 可用，但当前局域网 IP 8080 连接超时，Windows 未建立该端口监听。可在管理员 PowerShell 中添加定向转发（当前 IP 为 `192.168.1.169`）：

```powershell
netsh interface portproxy add v4tov4 listenaddress=192.168.1.169 listenport=8080 connectaddress=127.0.0.1 connectport=8080
```

需要撤销时使用 `netsh interface portproxy delete v4tov4 listenaddress=192.168.1.169 listenport=8080`。IP 变化时先删除旧规则再使用新 IP 添加。不要关闭系统防火墙来解决连接问题。

```dotenv
POSTGRES_PASSWORD=your-local-database-password
GITHUB_TOKEN=
SEARCH_LIMIT=100
TRANSLATION_BASE_URL=https://your-provider.example/v1
TRANSLATION_MODEL=your-model-name
TRANSLATION_API_KEY=your-provider-key
COLLECT_HOUR=1
TRENDING_COLLECT_HOUR=1
SCHEDULE_ENABLED=true
WEB_PORT=8080
```

`TRANSLATION_BASE_URL` 是 API 基础地址，包含供应商要求的 `/v1` 等前缀；程序追加 `/chat/completions`。模型必须支持文本 Chat Completions，完整响应的 `finish_reason` 应为 `stop`。密钥只从后端环境读取，实际 `.env` 已被 Git 忽略。配置更改后运行 `docker compose up -d` 重新创建受影响的容器。

`SEARCH_LIMIT` 默认 100，可设置为 1–1000；Search API 每页最多 100 条，每次搜索最多可访问前 1,000 条。大量项目需要配置 GitHub Token，否则逐个获取 README 容易触发限流。Search 一次采集使用 1–10 次搜索请求及每项目 1 次 README 请求，无需单独请求项目资料接口。Trending 另需读取榜单页面，以及每项目的资料和 README 接口。两个来源共享 GitHub 限流冷却保护。

Trending 未配置翻译服务时正常采集原文，页面显示“未配置翻译”。配置好后在 Trending 页面点击“立即采集”会补翻本次趋势榜项目。Star 总榜不调用翻译服务，也不显示翻译状态和中文切换。翻译按正文分块调用，可能产生费用；不会自动启用其他供应商或使用聊天账户的凭证。

DeepSeek 已实测兼容：`TRANSLATION_BASE_URL=https://api.deepseek.com`、`TRANSLATION_MODEL=deepseek-flash`，密钥仅写入本地 `TRANSLATION_API_KEY`。`SCHEDULE_ENABLED=true` 开启每日采集，仅 Trending 会产生翻译费用；Search 总榜不产生翻译调用。临时暂停自动任务可设为 `false`，修改后执行 `docker compose up -d`。列表的翻译状态记录上次处理结果，配置服务不会自动改写所有项目的历史“未配置翻译”状态；需实际翻译后才会更新。

## 使用与数据口径

- Trending 每天北京时间 01:00 采集（`TRENDING_COLLECT_HOUR=1`），当天完成后不重复；01:00 后启动服务会补采当天，之前等待到点。调度每 30 秒检查，需电脑与 Docker 持续运行。失败任务按小时重试，并遵守 GitHub 限流冷却时间和任务互斥。
- Search 总榜每天北京时间 01:00 获取前 100 项，与 Trending 依次执行。01:00 前等待到点，之后启动可补采当天。页面可手动执行；两榜的“补齐今日采集”仅补失败内容，不覆盖当天成功记录。
- 采集正在运行时不会启动第二个采集任务。首版固定一个 API worker。
- 页面支持日期、项目名称/描述搜索、开发语言筛选，以及项目详情和 README 中英文切换。
- 请求 `GET https://api.github.com/search/repositories?q=stars:>0 is:public fork:true&sort=stars&order=desc`。不限制语言、创建日期或组织，不排除归档仓库；结果受 GitHub 搜索索引及官方搜索范围限制，不承诺穷举所有仓库。
- `/stars` 展示累计 Star 总榜，Search 快照的 `daily_stars` 为 NULL。`/trending` 展示每日趋势榜，按 Trending 页面提供的今日新增 Stars 排序，并保留累计 Stars 和源站排名；它不是全站每日增长的完整排名。两个页面的搜索/语言筛选均只过滤已保存快照。
- 若 GitHub 返回 `incomplete_results=true`，仅再尝试一次 `stars:>=1000` 查询；只有该查询结果完整且匹配数至少为 N 时才接受，确保被排除的低星项目不可能进入 Top N。否则任务失败并保留已有榜单。这种回退会增加搜索请求数。
- 仓库总 Star、创建时间、更新及推送时间直接取自 Search API 返回的仓库资料；`updated_at` 与最近代码推送 `pushed_at` 分开显示。
- Trending 每个仓库每天独立保存完整快照：排名、Star、增量、地址、创建/更新/推送时间、简介、README 原文和译文。历史列表、筛选和详情都读取所选日期的快照；Search 也保存独立完整资料与原文快照，不翻译。时间戳存为 UTC，榜单日期按 Asia/Shanghai 归档。
- Trending 当天首次获取的成员列表保存在任务记录；失败重试继续该列表，已成功项目不再请求 GitHub。翻译失败只重试该日冻结的原文，成功内容不会被后续采集覆盖。跨日生成新记录，不删除旧记录。
- 升级前未保存完整快照的榜单仅有当日 Star/排名，其他资料无法还原真实历史，因此按迁移时最新资料回填，并标记 `details_origin=legacy_backfill`，页面明确提示；新记录为 `captured`。
- 停机期间无法恢复未采集的历史排名；只积累实际运行后的快照。
- 两榜重合项目共用原文和已有译文，总榜采集不会调用翻译或删除已有译文；原文或简介变化会标记译文待更新，由下一次 Trending 采集补翻。
- README 不存在不会丢弃项目。原文更新而翻译失败时保留已有译文并标记过期。代码块、行内代码和链接用占位符保护，所有分块成功后才替换译文。
- 每个项目独立提交，单个失败不影响其他项目；任务状态和脱敏错误会显示在页面。搜索响应不完整、重复或格式异常时不会更新榜单。

公开仓库不一定有开源许可证，页面显示源站许可信息，不推断授权。应用不克隆或执行项目代码。

## 数据和运维

两张独立榜单表：`trending_snapshots` 和 `search_snapshots`（各自以仓库 + 日期唯一）；另共用 `repositories`（最新资料缓存）和 `collection_runs`（任务来源、结果、冷却时间及当天首次成员列表）。两张榜单表的 `details` JSONB 保存该日完整资料及 README，`details_origin` 标记来源；同日只补齐失败部分。Search 同样冻结每日首次成员列表，同日只补失败项目，不覆盖成功记录。旧的 1,000 项历史榜单保留，新日期采集 100 项。

升级前先备份数据库。启动时将旧 `daily_snapshots` 按 source 事务内迁移至两张独立表，逐字段核验一致后删除旧表；异常则整体回滚。没有 source 的最早版本按 Trending 迁移。两张榜单表都使用 `/api/dates`、`/api/repositories`、`/api/runs/latest` 的 `source=trending|search` 参数；不传时默认 Search。手动采集使用 `POST /api/collect?source=trending|search`，请求体为 `{}`。历史详情使用 `/api/repositories/{id}?source=trending|search&date=YYYY-MM-DD`，对应日期不存在时返回 404。

分析历史数据直接查询快照表，无需关联可能已变化的最新项目资料：

```sql
SELECT date, repository_id, trending_rank, stars, daily_stars, fetched_at,
       details->>'full_name' AS full_name, details->>'language' AS language,
       details->>'created_at' AS created_at, details->>'updated_at' AS updated_at
FROM trending_snapshots
WHERE details_origin = 'captured'
ORDER BY date, trending_rank;
```

分析旧 Star/排名可以包含 `legacy_backfill`；分析真实历史项目资料时应排除它。

```sh
docker compose ps
docker compose logs --tail=100 api
docker compose down
```

`down` 保留数据库命名卷；**不要使用 `down -v`，它会删除已保存的数据。** 初次创建数据库后不要只修改 `.env` 密码；已有 PostgreSQL 数据卷不会自动同步修改密码。

数据库备份（先在容器内生成，再复制到当前目录，避免 Windows PowerShell 二进制重定向损坏）：

```sh
docker compose exec -T db pg_dump -U trending -Fc -f /tmp/trending.dump trending
docker compose cp db:/tmp/trending.dump ./trending.dump
```

数据库结构在首次启动创建。本次升级包含可重复执行的来源字段和唯一约束迁移，保留历史记录；升级前请备份。后续其他表结构变化仍需单独编写迁移。

本机若出现 `docker-credential-desktop` 路径错误，可在项目内创建 `.local/docker/config.json`，内容为 `{}`，并改用 `docker --config .local/docker compose ...`。这是只拉取公开镜像的独立配置，不修改系统 Docker 设置。若本机配置的镜像站下载失败，可先从官方地址拉取再标记，例如：

```sh
docker --config .local/docker pull registry-1.docker.io/library/nginx:alpine
docker --config .local/docker tag registry-1.docker.io/library/nginx:alpine nginx:alpine
```

## 开发与验证

后端锁文件为 `backend/requirements.lock`，前端使用 `frontend/package-lock.json`。生产镜像按锁文件安装。

```sh
cd backend
python -m pip install -r requirements.lock
python -m unittest discover -s tests -v
```

未配置 `TEST_DATABASE_URL` 时明确跳过数据库测试。完整测试使用独立的 `trending_test` 数据库，每项测试创建随机 schema，只删除该 schema，不删除业务表：

```sh
docker compose exec -T db createdb -U trending trending_test
docker compose run --rm --no-deps api python -m tests.run_postgres
```

`createdb` 仅首次运行；数据库已存在时直接执行测试。测试连接必须指向名称以 `_test` 结尾的 PostgreSQL 数据库。

```sh
cd frontend
npm ci
npm test
npm run build
```

后端覆盖官方搜索参数/分页、搜索不完整保护和安全回退、限流、README 缺失、代码块/链接保护、翻译截断、重复入库、来源隔离/迁移、榜单成员更新、历史保留、失败后保留旧译文、任务锁、调度和 API。前端覆盖 Markdown 清洗与相对链接以及采集轮询状态转换。

接口：`GET /api/dates`、`GET /api/repositories?date=&q=&language=`、`GET /api/repositories/{id}`、`GET /api/runs/latest`、`POST /api/collect`（JSON `{}`）、`GET /api/health`。交互接口文档位于 `/api/docs`。

真实翻译联调需要配置自己的服务；模拟翻译测试不代表特定供应商兼容性或译文质量已验证。

## 项目布局

### 本地 Git 管理

项目使用本地 Git 仓库保存代码版本。日常修改后执行：

```sh
git status --short
git diff
git add <本次修改的文件>
git commit -m "说明本次改动"
git log --oneline -10
```

`.env`、`.local/`、数据库备份、依赖目录、IDE 缓存及根目录的本地供应商实验脚本已忽略；`.env.example` 保留作为配置模板。Git 只管理代码，不备份运行中的数据库。仓库未配置远程地址，不会自动上传代码。

```text
backend/app/       配置、SQLAlchemy 模型、采集/翻译、HTTP API
backend/tests/     API 响应模拟、单元测试与 PostgreSQL 集成测试
frontend/src/      Vue 页面、样式、Markdown 渲染及轮询状态
compose.yaml      PostgreSQL / API / Web 三容器部署
docs/superpowers/ 已确认设计及实施计划
```

数据来源：[GitHub Trending](https://github.com/trending?since=daily)、[GitHub Search API](https://docs.github.com/en/rest/search/search#search-repositories)、[GitHub README API](https://docs.github.com/en/rest/repos/contents#get-a-repository-readme)。兼容接口参考：[Chat Completions](https://developers.openai.com/api/reference/resources/chat)。
