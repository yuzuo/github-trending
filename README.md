# 开源观察

自部署的 GitHub 趋势、采集项目监测与版本验证工具。集中查看每日 Trending、累计 Star 总榜、爬虫项目热度、Release/Issue 动态和有来源引用的 Agent 分析。

技术栈：FastAPI、SQLAlchemy 2、PostgreSQL 16、Vue 3、Vite、Nginx、Docker Compose。

## 功能与边界

| 模块 | 功能 |
| --- | --- |
| 每日 Trending | 保存每日榜单及项目快照，可选翻译简介和 README |
| Star 总榜 | 获取公开仓库累计 Star 前 N 项，包含 fork，不调用翻译 |
| 采集项目观察 | 自动发现、手动添加关注、Star 观测、人工评分与笔记 |
| 项目动态 | 跟踪关注项目的 Release 和 Issue 变化，保留来源与状态历史 |
| 需要关注 | Agent 整理摘要、影响、建议与证据，结合使用版本和场景辅助判断 |
| 自动版本验证 | 正式 Release 入队，独立主机 worker 执行并展示版本对比 |

**源码检查通过不代表项目采集能力可用。** 通用检查只解析 Python 3.12 语法和 `package.json`；Scrapy 另有本地固定的分页、去重、失败重试测试。其他项目的真实网站功能测试需单独配置。当前系统不是开箱即用的多平台视频或社交内容采集服务。

应用没有登录认证，数据和编辑操作由部署的访问者共享。默认面向本机或可信局域网；公网部署需要另行配置 HTTPS 和访问认证。

## 1. 部署前准备

- Git。
- Docker Engine 或已启动的 Docker Desktop，使用 Linux containers。
- Docker Compose v2：`docker compose version`。
- 可访问 GitHub、容器镜像源和构建所需的软件包源。
- 自动版本验证另需宿主机 Python 3.9+；只启动网站无需本机 Python/Node.js。

克隆仓库并进入项目根目录：

```sh
git clone https://github.com/yuzuo/github-trending.git
cd github-trending
```

已有代码目录可直接使用，不要覆盖现有 `.env` 或数据库卷。Compose 项目名固定为 `github-trending`，目录名不会改变数据库卷名称。

首次部署，在项目根目录复制 `.env.example` 为 `.env`。**已有 `.env` 时跳过复制，直接编辑。**

```sh
# macOS / Linux
cp .env.example .env
```

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

## 2. 配置环境变量

编辑 `.env`，至少替换数据库密码；持续监测应配置 GitHub Token。

| 变量 | 默认值或示例 | 用途 |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | 自行设置强密码 | 必填，首次初始化 PostgreSQL 使用 |
| `WEB_PORT` | `8080` | 宿主机 Web 端口 |
| `APP_ORIGIN` | `http://localhost:8080` | 局域网填实际访问地址，如 `http://192.168.1.23:8080` |
| `GITHUB_TOKEN` | 留空 | 建议填写，用于 API 容器读取公开 GitHub 数据 |
| `SEARCH_LIMIT` | `100` | Star 总榜条数，范围 1–1000 |
| `SCHEDULE_ENABLED` | `true` | 控制两榜、观察、动态监测及 Agent 自动调度 |
| `COLLECT_HOUR` | `1` | Star 总榜采集小时，北京时间 0–23 |
| `TRENDING_COLLECT_HOUR` | `1` | Trending 采集小时，北京时间 0–23 |
| `TRANSLATION_BASE_URL` | 留空 | 可选，模型服务基础地址，包含供应商要求的 `/v1` 等前缀 |
| `TRANSLATION_MODEL` | 留空 | 可选，模型名称 |
| `TRANSLATION_API_KEY` | 留空 | 可选，模型 API 密钥 |

### GitHub Token

在 [GitHub Token 设置](https://github.com/settings/personal-access-tokens)创建细粒度 Token，仅访问公开仓库、不授予写权限。填入 `.env` 的 `GITHUB_TOKEN`。参阅 [官方说明](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)。

未配置 Token 时，多项目刷新容易耗尽匿名额度，导致自动任务和手动添加一起进入冷却。Token 到期后需要替换并重新创建 API 容器。

### 可选模型服务

同时填写三个 `TRANSLATION_*` 变量才能启用。程序在基础地址后追加 `/chat/completions`，需要支持文本 Chat Completions 的服务。

- 未配置时仍能采集 GitHub 原文、监测动态和运行独立版本验证。
- 配置后，Trending 翻译和 Agent 动态分析都可能产生模型费用；Star 总榜和项目元数据采集不调用模型。
- 项目档案中的版本、场景和依赖能力用于 Agent 分析；不要在这些字段填写凭据。
- `.env` 已被 Git 忽略，不能提交到仓库，也不要把密钥写进 README 或测试脚本。

## 3. 首次启动网站

在项目根目录执行：

```sh
docker compose up -d --build
docker compose ps
```

三个服务为 `db`、`api`、`web`。API 等待数据库健康，Web 等待 API 健康。首次构建需要下载依赖，耗时取决于网络。

访问以下页面；局域网使用 `.env` 配置的服务器地址替换 `localhost:8080`：

| 地址 | 页面 |
| --- | --- |
| <http://localhost:8080/stars> | Star 总榜 |
| <http://localhost:8080/trending> | 每日 Trending |
| <http://localhost:8080/crawler-watch> | 采集项目观察 |
| <http://localhost:8080/crawler-watch/updates> | 项目动态 |
| <http://localhost:8080/crawler-watch/attention> | 需要关注、使用档案与自动验证 |
| <http://localhost:8080/api/health> | API 健康检查 |
| <http://localhost:8080/api/docs> | 交互接口文档 |

Web 监听所有 IPv4 网卡；数据库和 API 不直接发布宿主机端口。局域网无法访问时检查 `WEB_PORT`、`APP_ORIGIN`、防火墙和网络连通性，不要把 `0.0.0.0` 填作访问地址。

首次没有数据是正常情况。可通过页面手动采集，或等待调度到期；自动调度需要电脑与 Docker 持续运行。仅启动网站不会自动启动宿主机验证 worker。

## 4. 启动自动版本验证

需要自动验证时，在 Docker 所在的宿主机上另开终端，进入同一项目根目录：

```sh
# macOS / Linux：持续处理队列，Ctrl+C 停止
python3 validation/worker.py

# 只处理至多一个任务后退出
python3 validation/worker.py --once
```

Windows 使用 `python validation/worker.py`，或已有虚拟环境的 `.venv\Scripts\python.exe validation/worker.py`。

使用流程：

1. 在「采集项目观察」添加 `owner/repo` 或 GitHub 仓库 URL，并关注。
2. 动态监测发现正式 Release 后入队，首次最多回填最近两个版本。
3. 保持 worker 运行，在「需要关注」查看任务、证据和版本对比。
4. 填写实际使用版本与采集场景；未填写版本时不能判断当前环境是否受影响。

worker 通过本机 `docker compose exec` 访问 API，不向 API 容器挂载 Docker socket。它自动构建测试镜像并运行隔离容器；首次需要联网获取基础镜像或固定版本依赖。日志位于被 Git 忽略的 `.local/auto-validation/`。

**当前 worker 自身的 GitHub 请求不使用 API 容器的 `GITHUB_TOKEN`**，有独立限流等待逻辑；配置 API Token 不代表 worker 的匿名额度也增加。

macOS 常驻模板为 `validation/local.github-trending.validation.plist`，内含特定用户路径。其他机器必须先调整 Python、工作目录和日志路径，再注册 launchd；它不是通用的一键安装文件。详见 [自动验证 worker](docs/auto-validation-worker.md)和 [Scrapy 固定任务](docs/scrapy-validation.md)。

## 5. 日常启动、停止与更新

```sh
# 已构建服务的日常启动
docker compose up -d

# 查看状态和日志
docker compose ps
docker compose logs --tail=100 api
docker compose logs --tail=100 web

# 暂停容器，保留数据
docker compose stop

# 删除容器和项目网络，保留数据库命名卷
docker compose down
```

停止网站前先停止独立 worker（前台 Ctrl+C，常驻服务使用相应进程管理器停止）。`SCHEDULE_ENABLED=false` 只停止应用自动调度，不停止独立 worker。

修改 `.env` 后，单纯 `docker compose restart` 不会加载新环境变量。执行：

```sh
docker compose up -d --force-recreate api web
```

不要在数据库初始化后仅修改 `POSTGRES_PASSWORD`：已有数据卷中的数据库密码不会因此改变，需要单独协调数据库密码变更。

更新代码前先备份数据库、停止 worker，并保存本地改动。在已配置远程和跟踪分支的仓库中执行：

```sh
git pull --ff-only
docker compose up -d --build
docker compose ps
```

核对健康检查与页面后重新启动 worker。不要强制覆盖本地改动，也不要使用 `docker compose down -v`，它会删除业务数据卷。

## 6. 数据备份与迁移

仓库附带 [23 服务器初始化项目数据](data/README.md)：200 个观察项目及 13 个关注状态，可在全新部署中导入。它不是完整数据库备份，不包含历史动态、模型分析、笔记或密钥；导入命令与重复导入规则见该说明。

仓库还提供 [完整数据库公开脱敏快照](data/backups/README.md)，包含 2026-10-23 的全部 17 张业务表与历史数据，附校验值和空库恢复步骤。初始化清单与完整快照按需选择一种；公开快照遮盖疑似凭据并清空项目笔记，原始私有备份不公开。

Git 中的静态快照不替代持续运行数据库的备份。升级或迁移前先生成最新私有备份，以下方法避免 PowerShell 二进制重定向损坏：

```sh
docker compose exec -T db pg_dump -U trending -Fc -f /tmp/trending.dump trending
docker compose cp db:/tmp/trending.dump ./trending.dump
```

将备份保存到安全位置，与代码分开管理。迁移到新机器时复制代码、单独配置 `.env`，并在**全新空数据库**中恢复：

```sh
docker compose up -d db
# 等 docker compose ps 显示 db healthy 后继续
docker compose cp ./trending.dump db:/tmp/trending.dump
docker compose exec -T db pg_restore -U trending -d trending --no-owner --no-privileges --exit-on-error /tmp/trending.dump
docker compose up -d --build
```

已有数据的目标数据库不能直接按此步骤合并，需要先设计去重、冲突与恢复策略。历史快照无法通过重新抓取补回停机期间的真实排名。

## 7. 调度与数据口径

- 两榜按北京时间每天配置的小时采集；失败重试保留已完成部分，同日不覆盖成功快照。
- 项目观察最多 200 个活动项目，常规约每 6 小时刷新、每天发现候选；隐藏保留记录并停止监测。
- 近 24 小时、7 天增长使用实际样本差值，基线允许向前偏差最多 6 小时，应结合实际区间阅读。没有基线显示积累中，不当作零增长。
- 动态监测针对关注项目；Issue 关闭不等于修复已发布，模型分析不等于本地复现。
- Agent 自动分析每小时最多处理 5 个关注项目、每项目一条事件，可能积压；服务故障与证据不足会显示失败或警告。
- API 内采集任务共享互斥和 GitHub 冷却；遇到 409 应检查运行状态和冷却，而不是反复点击。
- 正式 Release 才触发自动版本任务；没有 Release 的项目可能一直等待版本。

详见 [动态监测](docs/project-monitor.md)、[Agent 分析](docs/attention-agent.md)和 [自动验证 worker](docs/auto-validation-worker.md)。

## 8. 常见故障

| 现象 | 检查步骤 |
| --- | --- |
| 页面打不开 | `docker compose ps`，确认 Docker 正常、端口未占用、API/DB 健康 |
| API 已重建但网页请求失败 | 查看 Web 日志；必要时 `docker compose restart web`，让 Nginx 重新解析 API 地址 |
| 添加项目返回 409 | 查看任务和冷却；检查 API 是否加载有效 Token，不要打印 Token |
| 配置 Token 后仍有旧冷却 | 冷却保存在数据库，不因重启自动消失；等待截止后重试，不要删除历史任务 |
| Agent 分析未配置 | 同时填写三个 `TRANSLATION_*` 变量并重新创建 API |
| 模型返回 HTTP 402 | 检查供应商额度或计费状态，具体含义以供应商响应为准 |
| 验证任务一直排队 | 确认宿主机 worker 运行、Docker 可用，并检查 `.local/auto-validation/` 日志 |
| 验证显示 error/unsupported | error 是检查未完成，unsupported 是范围不支持，都不能当作项目功能失败 |

## 9. 开发与检查

生产部署使用 `backend/requirements.lock` 和 `frontend/package-lock.json`。本地前端需 Node.js 22（与镜像一致），后端使用 Python 3.12。后端单元测试：

```sh
cd backend
python -m pip install -r requirements.lock
python -m unittest discover -s tests -v
```

未配置测试数据库时会跳过部分数据库集成测试。完整 PostgreSQL 检查使用独立测试库：

```sh
# 回到项目根目录；createdb 仅首次执行
docker compose exec -T db createdb -U trending trending_test
docker compose run --rm --no-deps api python -m tests.run_postgres
```

前端与 worker 检查：

```sh
cd frontend
npm ci
npm test
npm run build
cd ..
python -m unittest validation.test_source_suite validation.test_worker
```

测试使用模拟响应或固定样本；通过不代表 GitHub、模型供应商或真实目标网站当前可用。

## 目录

```text
backend/app/       配置、数据库模型、采集、分析、验证队列与 API
backend/tests/     单元与 PostgreSQL 集成测试
frontend/src/      Vue 页面与 Markdown 渲染
validation/        独立 worker、隔离检查与固定任务
docs/              设计、运行说明与阶段评测报告
data/              可公开的初始化项目清单与导入说明
compose.yaml       PostgreSQL / API / Web 部署
.env.example       无密钥的配置模板
```

数据来源：[GitHub Trending](https://github.com/trending)、[GitHub REST API](https://docs.github.com/en/rest)。公开可访问不等于具备开源许可证；具体项目使用条件请查看其许可证。
