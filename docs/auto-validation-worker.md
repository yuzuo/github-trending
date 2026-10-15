# 自动版本验证 worker

后端为已关注项目的发行版入队。worker 在 Docker 主机运行，通过本机 `docker compose exec -T api python -m app.validation_jobs` 领取、完成或报告任务错误。容器内 API 不需要 Docker socket。

## 启动

要求 Python 3.9+、Docker 和 Docker Compose。先启动本项目的 Compose 服务，再在项目根目录运行：

```sh
python3 validation/worker.py --once  # 领取并处理至多一个任务
python3 validation/worker.py         # 串行处理队列；空闲时每 60 秒检查，Ctrl+C 停止
```

Windows 可使用 `.venv\Scripts\python.exe validation/worker.py`。macOS 可以使用系统或自行安装的 Python 3.9+。worker 仅用标准库，不安装被验证项目的依赖。启动后需要保持这个进程运行；本脚本不安装系统后台服务。

主机锁保存在 `.local/auto-validation/worker.lock`，同一个工作目录只允许一个 worker。每次任务记录在 `.local/auto-validation/<任务 ID>/`，包括下载的源码归档、构建/运行日志和 JSON 结果。失败消息向后端仅发送异常类名，不包含凭据或请求正文。GitHub API 无需令牌；公开接口限流、网络失败等交由后端重试。HTTPError 延迟 60 分钟重试，其他执行错误延迟 15 分钟重试，最多 3 次。

## 检查范围

`source-smoke-v1` 面向任意公开 GitHub 仓库：确认 GitHub 数字仓库 ID、名称与公开状态，把发行版 tag 解析为 commit SHA，再从固定的 `codeload.github.com/<owner>/<repo>/tar.gz/<sha>` 下载。任务来源必须是同仓库、同版本的 GitHub release URL。任何 HTTP 重定向都会被拒绝。

源码仅在 Python 3.12 容器中读取，不解压到文件系统，不导入、不执行、不安装。检查 Python 文件的 `ast.parse` 语法和 `package.json` 的 JSON 格式；跳过 tests、fixtures、vendor、node_modules、venv 等目录。没有支持文件时结果为 `unsupported`，不能称为通过。解析错误为 `failed`。不安全、损坏或超限归档无法完成检查，worker 报告 `ArchiveValidationError` 执行错误并重试，不提交为版本回归结果；本地 suite JSON 保留 `archive_error`。这不是项目功能、兼容性、构建、依赖、安全审计或性能验证；新旧 Python 语法可能不兼容 3.12，非 Python 项目目前可能只得到 JSON 格式检查或 unsupported。

限额：压缩包 30 MiB；解压数据合计 100 MiB；最多 5000 个归档条目；单个待解析源码文件 2 MiB。图片等未解析内容仍计入总量限制。拒绝绝对路径、路径穿越、越界链接和特殊设备条目。安全链接不跟随。记录检查文件数、错误文件数与各最多 30 条文件名/错误；证据包含 suite 文件 SHA256、Python 版本、仓库、tag、commit SHA 和下载归档 SHA256。

容器无网络、只读根目录、非 root、去除全部 capabilities、禁止提权，限制 512 MiB 内存、1 CPU 和 64 进程；只读挂载单个输入归档，临时目录为 128 MiB tmpfs。单次源码执行最多 120 秒，并始终尝试删除该任务的 UUID 命名容器。下载、API 请求和镜像构建也各有超时；整个任务在后端 30 分钟租约内完成。

`scrapy-pagination-v1` 仅用于 `scrapy/scrapy` 的 `v?X.Y.Z` 稳定版本，继续调用现有 `validation/run.py --versions X.Y.Z` 的分页、去重、重试与字段检查。其结果是固定 fixture 的行为验证，不能代表所有真实站点，也不等于通用源码检查。

## 本地检查

```sh
python3 -m unittest validation.test_source_suite validation.test_worker
docker build -f validation/Source.Dockerfile -t github-source-smoke:1 validation
```

首次镜像构建需要主机联网拉取基础镜像。后续 suite 容器始终使用 `--network none`。主机日志与归档不会自动清理；需要时可停止 worker 后按任务目录手动清理。不要把 `.env`、Docker socket 或整个工作目录挂载到源码检查容器。
