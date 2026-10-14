# GitHub Trending 每日采集与中文展示

## 已确认需求

- FastAPI + SQLAlchemy + PostgreSQL 16 + Vue 3，Docker Compose 本地部署。
- 采集 GitHub Trending 全语言日榜，按页面标注的当日新增 Star 降序展示，仅代表该榜单范围。
- README 使用兼容 OpenAI 的接口翻译，地址、模型、密钥通过本地环境变量配置。
- 保存仓库地址、总 Star、项目创建日期、最近更新日期、采集日期和基本信息，提供中文展示。

## 数据口径与采集

默认北京时间每天 09:00 执行，首次启动当天无成功记录则执行一次；支持手动采集。停机期间无法补回未保存的历史 Trending 榜单，不伪造历史数据。

获取 https://github.com/trending?since=daily 页面实际返回的全部项目，不承诺固定条数。解析仓库名称、榜单顺序和当日新增 Star，再调用 GitHub 仓库和 README API 补全资料。GitHub Token 可选；遇到限流遵循服务端重试时间，不连续重试轰炸接口。

采集日期按 Asia/Shanghai 归档，时间戳存储为带时区的 UTC。页面的 “stars today” 原样作为源站统计值，不解释为北京时间自然日新增数量。字段缺失不得记为零；页面结构异常或空榜视作失败，保留原有数据。

每个项目单独提交，失败不回滚其他成功项目。任务记录成功、部分成功或失败及错误摘要；再次执行更新当天数据，补充失败项目。使用 PostgreSQL advisory lock 防止手动和定时任务重叠。

## 数据表

1. repositories：GitHub 数字 ID（唯一）、owner/name、仓库 URL、描述及中文描述、主要语言、许可证、总 Star、created_at、updated_at、pushed_at、first_fetched_at、last_fetched_at、README 路径和原文、内容哈希、中文译文、译文对应的原文哈希、翻译状态及错误摘要。
2. daily_snapshots：仓库外键、榜单日期、源站榜单顺序、当日新增 Star、采集时总 Star、采集时间；仓库和日期组成唯一约束。
3. collection_runs：开始与结束时间、榜单日期、状态、成功/失败数量、脱敏错误摘要。

历史榜单保留当日 Star 快照；项目详情展示最新资料与 README，明确标注最近采集时间，不承诺 README 历史版本。

## README 汉化

后端通过兼容接口的 /chat/completions 端点调用模型。README 按 Markdown 段落分块，保护代码块及链接；全文处理，不用摘要代替完整翻译，不静默截断。只在原文变化或上次翻译失败时重新翻译。

未配置接口时仍保存和展示原文，状态为未配置；翻译失败保留原文及已有译文，旧译文明确标为过期。只有全部分块成功后才替换完整译文。README 不存在属于可展示状态，不导致项目资料丢失。模型输入中的项目内容视为数据，不授予工具或执行权限。

密钥仅从后端环境读取，不进入数据库、响应、前端构建或日志。异常信息脱敏。配置通过 .env.example 说明，实际 .env 忽略提交。

## 后端与调度

单个 API 进程使用 FastAPI lifespan 启动轻量定时循环，阻塞采集工作在线程中执行；首版固定一个 worker。无需 Redis、Celery 或独立调度平台。SQLAlchemy 使用同步数据库会话，每个工作单元独立创建和关闭。

接口提供日期列表、按日期查询榜单（搜索名称/描述、语言筛选）、项目详情、手动触发采集、最近任务状态和健康检查。触发立即返回任务状态，前端轮询结果；重复触发返回任务正在进行。重启时标记遗留运行记录为中断。

手动写操作仅接受 JSON 并检查同源请求，不开启通配 CORS；Compose 仅将 Web 端口绑定 127.0.0.1，数据库和 API 不向宿主网络发布端口。

## 前端

Vue 3 + Vite 单页界面：榜单页包含日期选择、项目搜索、语言筛选、采集按钮及任务状态。列表显示项目名称、中文简介、语言、总 Star、当日新增 Star、源仓库链接和采集时间。

项目详情展示所有要求的日期字段、许可证及 README 原文/中文切换。Markdown 渲染后做 HTML 清洗，禁止脚本和危险链接，外链安全打开，相对资源链接转换为对应仓库地址。提供加载、空数据、采集失败、翻译失败状态及可键盘操作的控件。

## Docker 与交付文件

Compose 包含 db（postgres:16）、api 和 web（Nginx 托管前端并反向代理 /api）。数据库使用命名卷和健康检查，API 等待数据库就绪；提供 .env.example、部署 README 和一条启动命令 docker compose up -d --build。

交付范围：backend 应用/模型/采集与翻译/测试及解析 fixture；frontend 页面与构建配置；Dockerfile、Nginx 配置、compose.yaml、环境变量示例和操作文档。当前无既有业务代码、调用方或导出接口需要兼容。部署不删除已有数据卷。

## 验证与完成标准

- 用固定 HTML fixture 测试榜单解析、数字分隔符、缺失增长值及异常空页面。
- 用模拟 HTTP 响应验证 GitHub 请求失败、README 缺失、翻译分块和失败后的数据保留。
- 在 PostgreSQL 16 验证重复采集不重复入库、每日快照和任务互斥，测试 API 排序及搜索。
- 前端构建通过，检查 Markdown 危险内容过滤与主要页面状态。
- 验证 Compose 配置；环境允许时启动完整服务并检查健康接口、页面及持久化。
- 实际 GitHub 采集与真实翻译服务联调单独报告，未配置凭证或网络受限时不得宣称通过。

## 已知限制与范围外

Trending HTML 变化可能导致解析需要维护。机器需要运行才能按时采集，数据库从部署后逐步积累历史。翻译可能产生费用和误译，原文始终可查。

首版不包含登录、多用户、通知推送、全站排名、历史数据回填和 README 版本库。不执行仓库代码、不克隆整个项目。远程公开部署前需要增加访问控制。

## 参考

- https://github.com/trending?since=daily
- https://docs.github.com/en/rest/repos/contents#get-a-repository-readme
