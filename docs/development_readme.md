# 项目开发使用说明

这份文档面向项目开发和维护，包含本地启动、数据库初始化、项目结构和开发文档入口。

## 本地环境

- Python：建议使用 Python 3.11+，当前项目可在 Python 3.14 环境下运行。
- Node.js：建议使用当前 LTS 或较新版本。
- 数据库：MySQL。

## 开发约束

- 禁止生成 Python `__pycache__` 目录和 `.pyc` 文件。运行后端脚本、测试或服务时，应设置 `PYTHONDONTWRITEBYTECODE=1`，或使用 `python -B`。

## 后端启动

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
http://127.0.0.1:5173/
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

定时任务是否启用由 `backend/.env` 控制：

```env
SCHEDULER_ENABLED=true
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
│  │  ├─ components/
│  │  ├─ router/
│  │  └─ views/
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

## 开发文档

- [项目计划](project_plan.md)
- [待处理问题](todo_issues.md)
- [数据库设计](database.md)
- [数据来源](data_sources.md)

## 敏感配置

后端环境变量文件位于 `backend/.env`。该文件包含数据库连接等本地配置，不应提交到版本管理，也不应在协作过程中展示内容。
