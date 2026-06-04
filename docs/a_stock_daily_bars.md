# A 股日 K 本地库

本文档描述如何用 AkShare 将全量 A 股最近 10 年日 K 保存到独立 MySQL 数据库。

## 数据库

脚本默认读取 `backend\.env` 中的股票历史数据库配置：

```env
A_STOCK_MYSQL_HOST=127.0.0.1
A_STOCK_MYSQL_PORT=3306
A_STOCK_MYSQL_USER=root
A_STOCK_MYSQL_PASSWORD=change_me
A_STOCK_MYSQL_DATABASE=a_stock_market_data
```

不会使用或修改原有基金业务库 `fund_nav_estimator`。

基金业务库仍使用原来的配置：

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=fund_user
MYSQL_PASSWORD=change_me
MYSQL_DATABASE=fund_nav_estimator
```

如需临时覆盖库名，也可以通过命令参数：

```powershell
.\.venv\Scripts\python.exe scripts\sync_a_stock_daily_bars.py --database a_stock_market_data
```

## 数据表

三种复权口径分别保存到三张表：

| 表名 | 口径 |
|---|---|
| `stock_daily_bars_none` | 不复权 |
| `stock_daily_bars_qfq` | 前复权 |
| `stock_daily_bars_hfq` | 后复权 |

每张表以 `(symbol, trade_date)` 做唯一键。脚本仍兼容 upsert，但正式全量同步建议使用 insert-only 配合进度表。

同步进度额外保存到 `stock_daily_bars_sync_progress`。进度表以 `(symbol, start_date, end_date)` 做唯一键，只有三张 K 线表都写入成功后才标记 `done`。

任务级运行记录保存到 `a_stock_history_sync_tasks`。每次从后端启动同步都会创建一条任务记录，保存日期范围、线程数、运行状态、PID、日志路径、成功数、失败数、运行中数量、耗时和摘要。进度表中的 `task_id` 表示该股票最近一次所属同步任务，用于任务详情页展示明细。

## 字段

每张表包含：

- 股票代码、股票名称、交易日期。
- 开盘、最高、最低、收盘。
- 成交量、成交额。
- 振幅、涨跌幅、涨跌额、换手率。
- 数据来源和同步时间。

## 运行

先确认 `backend\.env` 中 MySQL 连接可用，并且 MySQL 服务已启动。

小批量验证：

```powershell
cd <project-root>\backend
.\.venv\Scripts\python.exe scripts\sync_a_stock_daily_bars.py --limit 1 --sleep-seconds 0
```

指定股票验证：

```powershell
cd <project-root>\backend
.\.venv\Scripts\python.exe scripts\sync_a_stock_daily_bars.py --symbols 000001 600519 --sleep-seconds 0
```

全量同步：

```powershell
cd <project-root>\backend
.\.venv\Scripts\python.exe scripts\sync_a_stock_daily_bars.py --use-progress --insert-only --retry-conflicts --workers 8 --sleep-seconds 0
```

默认日期范围是从当前日期向前 10 年到当前日期。也可以显式指定：

```powershell
cd <project-root>\backend
.\.venv\Scripts\python.exe scripts\sync_a_stock_daily_bars.py --start-date 20160603 --end-date 20260603
```

中断后重跑可以直接执行同一命令，已有日期会被更新。若希望已存在记录的股票直接跳过：
中断后重跑建议继续使用进度表。脚本启动时会跳过 `stock_daily_bars_sync_progress` 中已标记 `done` 的股票；如果 insert-only 遇到唯一键冲突，会删除该股票在三张 K 线表中的旧数据并重试一次：

```powershell
cd <project-root>\backend
.\.venv\Scripts\python.exe scripts\sync_a_stock_daily_bars.py --use-progress --insert-only --retry-conflicts --workers 8 --sleep-seconds 0
```

运行过程中如果遇到进度表中已有 `running` 且开始时间未超过 30 分钟的股票，脚本会先跳过该股票，避免多个同步进程处理同一只股票。主扫描结束后，脚本会重新扫描本次日期范围内超过 30 分钟的 `running` 记录；如果存在，会继续处理这些股票，直到没有超时 `running` 记录。随后脚本会把本次日期范围内仍处于 `failed` 的股票再补跑一次；补跑后仍失败的股票会保留 `failed` 状态，并导致脚本以失败退出。

前端 A 股历史行情页面展示任务列表。点击任务详情可查看该任务的正在处理、最近完成和失败股票。任务存在失败股票时，可通过“重跑失败”创建新的同步任务，只处理该任务下失败的股票。

如果需要从历史 stdout 日志恢复确定完成的股票，可先导入日志中三张表都有明确行数的记录。日志中的 `skip` 不会被当作完成：

```powershell
cd <project-root>\backend
.\.venv\Scripts\python.exe scripts\sync_a_stock_daily_bars.py --symbols 000001 --limit 0 --use-progress --import-completed-from-logs ..\logs\a_stock_daily_sync_20260603_132247.out.log ..\logs\a_stock_daily_sync_workers4_20260603_183132.out.log
```

## 数据量

按当前约 5,500 只 A 股、10 年约 2,400 个交易日估算：

```text
单张表：约 1,300 万 - 1,800 万行
三张表：约 4,000 万 - 5,400 万行
MySQL 磁盘：约 15 GB - 30 GB，取决于索引和字段存储
```
