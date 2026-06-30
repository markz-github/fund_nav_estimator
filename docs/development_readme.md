# 项目开发使用说明

这份文档面向项目开发和维护，包含本地启动、数据库初始化、项目结构和开发文档入口。

本项目只包含基金估值系统。信息系统已经拆分为独立项目。

## 本地环境

- Python：建议使用 Python 3.11+，当前项目可在 Python 3.14 环境下运行。
- 后端运行环境：使用 `backend\.venv` 虚拟环境。启动服务、初始化数据库、运行测试和执行后端脚本时，优先使用 `backend\.venv\Scripts\python.exe`，避免误用系统 Python。
- Node.js：建议使用当前 LTS 或较新版本。
- 数据库：MySQL。

## 开发约束

- 禁止生成 Python `__pycache__` 目录和 `.pyc` 文件。运行后端脚本、测试或服务时，应设置 `PYTHONDONTWRITEBYTECODE=1`，或使用 `python -B`。
- 后端测试应自动清理 pytest cache，避免残留 `.pytest_cache` 或 `pytest-cache-files-*` 临时目录；运行 pytest 时使用 `--cache-clear`，如果本地出现权限残留目录，应在确认没有 Python/pytest 进程占用后删除。
- 每次识别到新的需求、需求变化或新的需求细节时，应同步更新 `docs/requirements/` 下对应的需求文档。
- 开发过程中如果遇到是否需要兼容旧逻辑、旧数据形态或历史临时方案的情况，应先向项目负责人确认是否需要兼容；未经确认不主动增加旧逻辑兼容分支，优先通过明确的数据清洗或迁移处理历史数据。
- 系统中的业务数据表应统一使用 `is_deleted` 字段表示软删除状态。`is_deleted` 默认为 `0`，表示未删除；`1` 表示已删除。查询业务数据时应默认过滤 `is_deleted = 0`，避免返回已删除数据。
- 前端展示日期时间字段时统一使用 `yyyy-MM-dd HH:mm:ss` 格式，例如 `2026-05-21 09:30:05`。仅日期字段继续使用 `yyyy-MM-dd`。前端应通过统一工具函数格式化日期时间，避免在页面中直接展示后端返回的 ISO 字符串或临时截断字符串。
- 前端新增或改造表单、下拉框、弹窗、分页、提示等通用交互时，应优先考虑使用 Element Plus 成熟组件；若继续使用原生元素或自定义实现，应保持现有视觉风格和响应式布局一致。
- 修改前端 bug 后，除了运行构建或类型检查，还必须打开实际浏览器访问对应页面进行验证。涉及布局、交互、样式、路由或数据展示的问题，应使用当前开发地址确认真实渲染结果，并在必要时通过截图或 DOM 坐标核对修复是否生效。

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

开发和运行测试时安装开发依赖：

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

`requirements.txt` 只放后端运行依赖；`requirements-dev.txt` 引用运行依赖，并额外安装 pytest 等开发/测试工具。

不激活虚拟环境也可以直接启动：

```powershell
cd m:\VscodeProjects\基金当日净值预测\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

运行后端测试也使用同一个虚拟环境：

```powershell
cd m:\VscodeProjects\基金当日净值预测\backend
.\.venv\Scripts\python.exe -B -m pytest --cache-clear tests
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

## 后端镜像

后端 Docker 镜像分为两层：

- 项目级基础镜像：`192.168.50.50:16060/markz/fund-nav-estimator-backend-base:py3.14-deps-20260524-193621`，由 `backend/Dockerfile.base` 构建，安装 `backend/requirements.txt` 中的运行依赖。
- 业务镜像：由 `backend/Dockerfile` 构建，基于项目级基础镜像，只复制 `app`、`config` 和 `scripts`。

自动部署中，后端测试使用 runner 上的临时虚拟环境和 `requirements-dev.txt`；生产业务镜像只依赖项目级基础镜像，不安装 pytest。

项目级基础镜像使用固定版本 tag。自动部署不会构建或推送基础镜像；当 `backend/requirements.txt` 或 `backend/Dockerfile.base` 变化时，应先独立构建并推送新的基础镜像 tag，再更新 `backend/Dockerfile`、`docker-compose.yml` 和 `.gitea/workflows/deploy.yml` 中的 `BACKEND_BASE_IMAGE` 默认值。

本地 Docker 仓库地址为 `http://192.168.50.50:16060/repository/docker-group/`。在 Dockerfile、Compose 和部署脚本中引用镜像时使用 Docker registry 前缀 `192.168.50.50:16060`，不要带 `http://` 或 `/repository/docker-group/` 路径。

```powershell
docker build -f backend/Dockerfile.base `
  --build-arg PIP_INDEX_URL=http://192.168.50.50:16666/repository/pypi-group/simple/ `
  --build-arg PIP_TRUSTED_HOST=192.168.50.50 `
  -t 192.168.50.50:16060/markz/fund-nav-estimator-backend-base:py3.14-deps-20260524-193621 `
  backend

docker push 192.168.50.50:16060/markz/fund-nav-estimator-backend-base:py3.14-deps-20260524-193621
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

`log_level` 支持 Python logging 常用级别，例如 `DEBUG`、`INFO`、`WARNING`、`ERROR`。如需查看完整运行过程，可在 `backend/config/local.toml` 中设置：

```toml
log_level = "DEBUG"
```

基金定时任务是否启用通过以下配置控制：

```env
SCHEDULER_FUND_ENABLED=true
```

定时任务执行时间也在 `backend/.env` 中配置，使用标准 5 段 cron 表达式：

```env
SCHEDULER_REFRESH_NAV_CRON=0 20 * * *
SCHEDULER_REFRESH_PROFILES_CRON=10 19 * * *
SCHEDULER_REFRESH_HOLDINGS_CRON=30 20 * * mon-fri
SCHEDULER_REFRESH_QUOTES_CRON=0,30 9-15 * * mon-fri
SCHEDULER_ESTIMATE_NAV_CRON=5,35 9-15 * * mon-fri
```

默认含义：

- `SCHEDULER_REFRESH_NAV_CRON`：每天 20:00 同步官方净值。
- `SCHEDULER_REFRESH_PROFILES_CRON`：每天 19:10 同步全量基金名称和类型到 `fund_profiles`，并回填自选基金基础信息。
- `SCHEDULER_REFRESH_HOLDINGS_CRON`：工作日 20:30 同步基金持仓。
- `SCHEDULER_REFRESH_QUOTES_CRON`：工作日 09:00-15:00 每 30 分钟同步行情。
- `SCHEDULER_ESTIMATE_NAV_CRON`：工作日 09:05-15:35 每 30 分钟估算净值。
## 任务日志状态

`task_logs.status` 使用以下状态：

- `pending`：基金任务已提交到队列，等待 worker 领取。
- `running`：本地后端任务正在执行，尚未写入结束时间。
- `success`：任务已完成，且没有失败或跳过项。
- `failed`：任务已完成，全部处理失败，或任务级异常。
- `partial`：任务已完成，同时存在成功与失败或跳过。
- `skipped`：任务已完成，但没有可处理对象，或业务上跳过执行。

## 项目结构

```text
基金当日净值预测/
├─ backend/
│  ├─ app/
│  │  ├─ models/
│  │  ├─ scheduler/
│  │  │  ├─ fund_jobs.py
│  │  │  ├─ scheduler.py
│  │  │  └─ jobs.py
│  │  ├─ modules/
│  │  │  ├─ fund_nav/
│  │  │  └─ operations/
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
│  │  │  │  ├─ operations/
│  │  │  │  └─ views/
│  │  ├─ router/
│  │  └─ main.ts
│  └─ package.json
├─ docs/
└─ README.md
```

调度任务按业务模块拆分：

- `scheduler/fund_jobs.py`：基金净值、资料、持仓、行情和估算任务。
- `scheduler/scheduler.py`：创建 APScheduler 实例并注册基金任务。
- `scheduler/jobs.py`：兼容旧导入路径，只做 re-export。新增代码不要继续向该文件添加任务实现。

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
- `GET /api/errors?module=fund_nav`

## 开发文档

- [项目计划](project_plan.md)
- [数据库设计](database.md)
- [数据来源](data_sources.md)
- [需求文档](requirements/README.md)

## 敏感配置

后端环境变量文件位于 `backend/.env`。该文件包含数据库连接等本地配置，不应提交到版本管理，也不应在协作过程中展示内容。
