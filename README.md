# 基金当日净值预测

一个用于估算自选基金当日净值的 Python + Vue 项目。

信息流采集、笔记生成和汇总功能已经拆分到同级目录 `..\信息系统`。本项目只保留基金估值功能。

项目可以维护自选基金池，获取基金官方净值、基金持仓和底层资产行情，并基于最新官方净值和持仓资产涨跌幅计算基金当日估算净值。

## 功能概览

- 自选基金管理：添加、删除、查看基金。
- 官方净值同步：通过公开数据源获取基金最新净值。
- 基金持仓同步：同步基金披露的股票持仓。
- 行情缓存：获取并缓存持仓资产行情。
- 净值估算：根据持仓比例和资产涨跌幅估算当日净值。
- 基金详情：查看基金基础信息、持仓和估算结果。

## 技术栈

- 后端：FastAPI、SQLAlchemy、APScheduler
- 数据库：MySQL
- 前端：Vue 3、Vite、TypeScript
- 数据源：akshare 及公开行情数据源

## 适用场景

- 想跟踪自选基金盘中估算净值。
- 想研究基金持仓与净值变化之间的关系。
- 想基于 Python 和 Vue 搭建一个基金数据分析工具。

## 重要说明

基金持仓通常来自季报、半年报或年报，不是实时披露数据。因此本项目计算出的当日估算净值只能作为参考，不构成投资建议。

## 本地开发快速开始

以下命令以 Windows PowerShell 为例，`<project-root>` 表示本项目根目录。

### 1. 准备环境

- Python 3.11+，当前开发环境可使用 Python 3.14。
- Node.js 18+ 或更新版本。
- MySQL 8.x 或兼容版本。
- 可访问 AkShare 使用的数据源网络。

### 2. 创建后端虚拟环境

```powershell
cd <project-root>
py -3.14 -m venv backend\.venv
backend\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
```

如果本机没有 `py -3.14`，可以换成已安装的 Python：

```powershell
python -m venv backend\.venv
```

需要运行测试时，额外安装 pytest：

```powershell
backend\.venv\Scripts\python.exe -m pip install pytest
```

### 3. 新建后端 `.env`

在 `backend\.env` 新建本地配置文件。该文件包含数据库密码，已经被 `.gitignore` 忽略，不要提交到版本库。

```env
APP_ENV=local

MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=fund_user
MYSQL_PASSWORD=change_me
MYSQL_DATABASE=fund_nav_estimator
```

说明：

- `APP_ENV=local` 会读取 `backend/config/default_config.toml` 和 `backend/config/local.toml`。
- `MYSQL_USER` 需要有创建数据库和建表权限；如果没有创建数据库权限，请先手动创建数据库，再给该用户授予表权限。
- 定时任务默认关闭，配置项在 `backend/config/default_config.toml` 中的 `scheduler_enabled`。

### 4. 初始化数据库

```powershell
cd <project-root>\backend
.\.venv\Scripts\python.exe scripts\init_db.py
```

脚本会根据 `.env` 连接 MySQL，创建数据库，并根据 SQLAlchemy 模型创建或确认数据表。

### 5. 启动后端

```powershell
cd <project-root>\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

健康检查：

```text
http://127.0.0.1:8000/api/health
```

### 6. 新建前端本地配置并启动

建议在 `frontend\.env.local` 中声明本地开发路径和后端 API 地址：

```env
VITE_APP_BASE_PATH=/
VITE_API_BASE_URL=http://127.0.0.1:8000/api
```

然后安装依赖并启动：

```powershell
cd <project-root>\frontend
npm install
npm run dev -- --host 127.0.0.1
```

本地访问：

```text
http://127.0.0.1:5173/fund-nav
```

如果不创建 `frontend\.env.local`，前端会使用默认基础路径 `/fund-nav-estimator/`，访问地址会变成 `http://127.0.0.1:5173/fund-nav-estimator/fund-nav`。

### 7. 常用开发命令

后端测试：

```powershell
cd <project-root>\backend
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests
```

前端构建：

```powershell
cd <project-root>\frontend
npm run build
```

### 8. 常见问题

- `backend\.env` 不能提交，也不要在协作中贴出真实密码。
- 如果 `scripts\init_db.py` 创建数据库失败，通常是 MySQL 用户权限不足。
- 如果前端页面能打开但接口失败，先确认后端 `http://127.0.0.1:8000/api/health` 是否正常。
- 如果 AkShare 请求慢或失败，可能是外部数据源网络波动；可在运行状态页面查看任务日志和数据拉取错误。
- 如果 Vite 构建时出现 `spawn EPERM`，通常是 Windows 权限或安全软件拦截了 `esbuild` 子进程，可尝试管理员终端或将项目目录加入安全软件排除项。

## 设计文档

- [基金估值系统设计](./docs/fund_nav_system_design.md)
- [数据库设计](./docs/database.md)
- [数据来源](./docs/data_sources.md)

