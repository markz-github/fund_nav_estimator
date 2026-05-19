# 项目开发使用说明

这份文档面向项目开发和维护，包含本地启动、数据库初始化、项目结构和开发文档入口。

## 本地环境

- Python：建议使用 Python 3.11+，当前项目可在 Python 3.14 环境下运行。
- 后端运行环境：使用 `backend\.venv` 虚拟环境。启动服务、初始化数据库、运行测试和执行后端脚本时，优先使用 `backend\.venv\Scripts\python.exe`，避免误用系统 Python。
- Node.js：建议使用当前 LTS 或较新版本。
- 数据库：MySQL。

## 开发约束

- 禁止生成 Python `__pycache__` 目录和 `.pyc` 文件。运行后端脚本、测试或服务时，应设置 `PYTHONDONTWRITEBYTECODE=1`，或使用 `python -B`。
- 每次识别到新的需求、需求变化或新的需求细节时，应同步更新 `docs/requirements/` 下对应的需求文档。
- 系统中的业务数据表应统一使用 `is_deleted` 字段表示软删除状态。`is_deleted` 默认为 `0`，表示未删除；`1` 表示已删除。查询业务数据时应默认过滤 `is_deleted = 0`，避免返回已删除数据。

## 后端启动

项目后端默认使用 `backend\.venv` 虚拟环境运行：

```powershell
cd m:\VscodeProjects\基金当日净值预测\backend
.\.venv\Scripts\Activate.ps1
python scripts\init_db.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

如果还没有虚拟环境：

```powershell
cd backend
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

不激活虚拟环境也可以直接启动：

```powershell
cd m:\VscodeProjects\基金当日净值预测\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

运行后端测试也使用同一个虚拟环境：

```powershell
cd m:\VscodeProjects\基金当日净值预测\backend
.\.venv\Scripts\python.exe -B -m unittest discover tests
```

后台隐藏启动可使用：

```powershell
Start-Process -FilePath "m:\VscodeProjects\基金当日净值预测\backend\.venv\Scripts\python.exe" -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") -WorkingDirectory "m:\VscodeProjects\基金当日净值预测\backend" -WindowStyle Hidden
```

后端默认地址：

```text
http://127.0.0.1:8000
```

健康检查：

```text
http://127.0.0.1:8000/api/health
```

## 前端启动

```powershell
cd m:\VscodeProjects\基金当日净值预测\frontend
g:\nodejs\npm.cmd install
g:\nodejs\npm.cmd run dev -- --host 127.0.0.1
```

前端默认地址：

```text
http://127.0.0.1:5173
```

当前机器上存在多个 npm 入口，建议显式使用 `g:\nodejs\npm.cmd`，避免 Windows 误打开无扩展名的 `npm` 文件。项目内未全局安装 Vite，`npm run dev` 会使用：

```text
frontend\node_modules\.bin\vite.cmd
```

后台隐藏启动可使用：

```powershell
Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "g:\nodejs\npm.cmd run dev -- --host 127.0.0.1 > ..\logs\frontend-dev.log 2> ..\logs\frontend-dev.err.log") -WorkingDirectory "m:\VscodeProjects\基金当日净值预测\frontend" -WindowStyle Hidden
```

如果普通启动遇到 Vite/esbuild 报错：

```text
Error: spawn EPERM
```

通常是 Windows 权限或安全策略拦截 esbuild 子进程。可用管理员终端启动，或在 Windows 安全中心为项目目录增加排除项：

```text
m:\VscodeProjects\基金当日净值预测
```

## 停止和重启服务

查看当前后端和前端进程：

```powershell
Get-Process | Where-Object { $_.ProcessName -match 'python|uvicorn|node|npm' } | Select-Object Id,ProcessName,StartTime,Path
```

停止指定进程：

```powershell
Stop-Process -Id <进程ID> -Force
```

后端重启后可用健康检查确认：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/health
```

前端启动后可访问：

```text
http://127.0.0.1:5173/fund-nav
```

## 数据库初始化

初始化脚本：

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\init_db.py
```

脚本会：

- 创建数据库，如果数据库不存在。
- 根据 SQLAlchemy ORM 模型创建表。
- 输出已创建或已确认存在的表名。

## 定时任务配置

## 日志配置

后端日志目录、保留天数和输出级别在 `backend/config/default_config.toml` 以及当前环境覆盖文件中配置：

```toml
log_dir = "logs"
log_level = "INFO"
log_backup_days = 5
```

`log_level` 支持 Python logging 常用级别，例如 `DEBUG`、`INFO`、`WARNING`、`ERROR`。信息流扫描的成功结果日志使用 `INFO`，失败结果日志使用 `ERROR`，过程日志使用 `DEBUG`；如需查看完整扫描过程，可在 `backend/config/local.toml` 中设置：

```toml
log_level = "DEBUG"
```

定时任务是否启用按业务模块分别配置：

```env
SCHEDULER_FUND_ENABLED=true
SCHEDULER_INFORMATION_ENABLED=true
```

定时任务执行时间也在 `backend/.env` 中配置，使用标准 5 段 cron 表达式：

```env
SCHEDULER_REFRESH_NAV_CRON=0 20 * * *
SCHEDULER_REFRESH_PROFILES_CRON=10 19 * * *
SCHEDULER_REFRESH_HOLDINGS_CRON=30 20 * * mon-fri
SCHEDULER_REFRESH_QUOTES_CRON=0,30 9-15 * * mon-fri
SCHEDULER_ESTIMATE_NAV_CRON=5,35 9-15 * * mon-fri
SCHEDULER_SCAN_VIDEOS_CRON=*/3 * * * *
SCHEDULER_GENERATE_VIDEO_NOTES_INTERVAL_SECONDS=30
SCHEDULER_GENERATE_SUMMARY_DOCUMENTS_CRON=0 7 * * *
SCHEDULER_POLL_SUMMARY_DOCUMENTS_INTERVAL_SECONDS=30
SCHEDULER_PUSH_SUMMARY_DOCUMENTS_CRON=0 8 * * *
```

默认含义：

- `SCHEDULER_REFRESH_NAV_CRON`：每天 20:00 同步官方净值。
- `SCHEDULER_REFRESH_PROFILES_CRON`：每天 19:10 同步全量基金名称和类型到 `fund_profiles`，并回填自选基金基础信息。
- `SCHEDULER_REFRESH_HOLDINGS_CRON`：工作日 20:30 同步基金持仓。
- `SCHEDULER_REFRESH_QUOTES_CRON`：工作日 09:00-15:00 每 30 分钟同步行情。
- `SCHEDULER_ESTIMATE_NAV_CRON`：工作日 09:05-15:35 每 30 分钟估算净值。
- `SCHEDULER_SCAN_VIDEOS_CRON`：每 3 分钟扫描信息流视频来源；定时任务每次只扫描 1 个启用账号，按最近扫描时间轮询，避免集中请求触发风控。
- `SCHEDULER_GENERATE_VIDEO_NOTES_INTERVAL_SECONDS`：每 30 秒检查或提交 Bilinote 视频总结任务。
- `SCHEDULER_GENERATE_SUMMARY_DOCUMENTS_CRON`：每天 07:00 针对昨天发布的视频对应笔记，提交 Hermes `/v1/runs` 汇总任务。
- `SCHEDULER_POLL_SUMMARY_DOCUMENTS_INTERVAL_SECONDS`：每 30 秒检查 Hermes 汇总任务结果。
- `SCHEDULER_PUSH_SUMMARY_DOCUMENTS_CRON`：每天 08:00 将昨天已完成的每日汇总文档推送到微信接口。

Bilinote 总结任务还会读取 `information_settings.video_note_recent_days`，只对最近 N 天内发布或入库的视频提交总结任务。默认值为 `3`，设置为 `0` 表示不限制天数。

## 信息流状态说明

### 视频处理状态

`information_videos.status` 表示视频在信息流处理链路中的状态：

- `note_pending`：视频已扫描入库，等待生成 Bilinote 总结。
- `note_running`：已提交 Bilinote 任务，正在等待生成结果。
- `note_done`：Bilinote 总结已生成。
- `note_failed`：Bilinote 总结生成失败，失败原因见对应 `information_video_notes.error_message`。
- `summarized`：该视频总结已被纳入 Hermes 每日汇总。

### Bilinote 总结状态

`information_video_notes.status` 表示单条 Bilinote 总结任务状态：

- `pending`：总结记录已创建，但尚未提交外部任务。
- `running`：已获得 Bilinote `task_id`，等待 `/api/task_status/{task_id}` 返回最终结果。
- `done`：已获得总结正文，正文保存在 `note_text`。
- `failed`：生成失败或任务过期，失败原因保存在 `error_message`，原始响应保存在 `raw_response`。

Bilinote 状态检查间隔为 30 秒。运行超过 1 天仍未得到结果的任务会标记为 `failed`，错误信息为：

```text
Bilinote task expired after 1 day without result
```

### 任务日志状态

`task_logs.status` 在所有模块中新写入的数据统一使用以下状态：

- `running`：本地后端任务正在执行，尚未写入结束时间。
- `success`：任务已完成，且没有失败或跳过项。
- `failed`：任务已完成，全部处理失败，或任务级异常。
- `partial`：任务已完成，同时存在成功与失败或跳过。
- `skipped`：任务已完成，但没有可处理对象，或业务上跳过执行。

`generate_information_video_notes` 的任务日志只描述本次后端触发是否完成；Bilinote 外部等待状态保存在 `information_videos.status` 和 `information_video_notes.status`，不再把已结束的任务日志保留为 `running`。

Bilinote 总结拆成两类任务日志：

- `submit_information_video_note_task`：提交 `/api/generate_note`，创建笔记记录，并在 `task_logs.external_task_id` 记录 Bilinote 返回的 `task_id`。
- `poll_information_video_notes`：定时扫描 `information_video_notes.status = running` 的记录，调用 `/api/task_status/{task_id}` 获取结果。

Hermes 汇总也拆成两类任务日志：

- `generate_information_summary_documents` / `generate_information_custom_summary` / `retry_information_summary_document`：提交 Hermes run，创建或复用汇总文档，并在文档中保存 `hermes_run_id`。
- `poll_information_summary_documents`：定时扫描 `information_summary_documents.status = running` 的记录，调用 Hermes 状态接口获取最终汇总正文。

信息流定时任务会精简空跑日志：没有启用视频来源、扫描没有新增视频、没有 running Bilinote 任务、没有待提交总结视频、没有可汇总笔记时，不写入 `task_logs`。手动触发的任务仍会写入日志，包括 `skipped` 结果。

## 项目结构

```text
基金当日净值预测/
├─ backend/
│  ├─ app/
│  │  ├─ models/
│  │  ├─ scheduler/
│  │  ├─ modules/
│  │  │  ├─ fund_nav/
│  │  │  └─ information/
│  │  ├─ config.py
│  │  ├─ database.py
│  │  └─ main.py
│  ├─ scripts/
│  └─ requirements.txt
├─ frontend/
│  ├─ src/
│  │  ├─ api/
│  │  │  └─ client.ts
│  │  ├─ modules/
│  │  │  ├─ fund_nav/
│  │  │  │  ├─ api/
│  │  │  │  ├─ components/
│  │  │  │  └─ views/
│  │  │  └─ information/
│  │  │     ├─ api/
│  │  │     └─ views/
│  │  ├─ router/
│  │  └─ main.ts
│  └─ package.json
├─ docs/
└─ README.md
```

## 主要接口

- `GET /api/health`
- `GET /api/funds`
- `POST /api/funds`
- `DELETE /api/funds/{fund_code}`
- `GET /api/funds/{fund_code}`
- `POST /api/funds/{fund_code}/refresh-nav`
- `POST /api/funds/{fund_code}/refresh-holdings`
- `GET /api/funds/{fund_code}/holdings`
- `POST /api/market/refresh`
- `GET /api/market/quotes/latest`
- `POST /api/estimates/actions/run`
- `GET /api/estimates/latest`
- `GET /api/estimates/{fund_code}`
- `GET /api/tasks/logs`
- `GET /api/errors`
- `GET /api/tasks/logs?module=fund_nav`
- `GET /api/tasks/logs?module=information`
- `GET /api/errors?module=fund_nav`
- `GET /api/errors?module=information`
- `GET /api/information/video-sources`
- `POST /api/information/video-sources`
- `PATCH /api/information/video-sources/{source_id}`
- `DELETE /api/information/video-sources/{source_id}`
- `GET /api/information/settings`
- `PUT /api/information/settings`
- `GET /api/information/videos`
- `GET /api/information/video-notes`
- `GET /api/information/summary-documents`
- `GET /api/information/summary-documents/{document_id}`
- `POST /api/information/summary-documents/{document_id}/retry`
- `POST /api/information/actions/scan-videos`
- `POST /api/information/actions/generate-video-notes`
- `POST /api/information/actions/generate-summary`

## 开发文档

- [项目计划](project_plan.md)
- [待处理问题](todo_issues.md)
- [数据库设计](database.md)
- [数据来源](data_sources.md)
- [需求文档](requirements/README.md)

## 敏感配置

后端环境变量文件位于 `backend/.env`。该文件包含数据库连接等本地配置，不应提交到版本管理，也不应在协作过程中展示内容。
