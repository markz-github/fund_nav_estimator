# 基金估值系统设计文档

## 1. 文档目的

本文档描述基金当日净值估算系统的整体设计、核心数据流、任务队列、AkShare 缓存与并发控制、接口约定、日志规范和后续演进方向。

系统的核心目标是：

- 管理用户关注的基金。
- 同步基金基础资料、官方净值和公开持仓。
- 获取底层资产行情。
- 基于最近一次官方净值、公开持仓和资产涨跌幅估算基金当日净值。
- 将耗时外部请求放入后台队列，避免阻塞 Web 请求和页面访问。

估算结果仅用于辅助观察。基金持仓通常来自季报、半年报或年报，不是基金公司的实时仓位，因此结果不构成投资建议。

## 2. 技术架构

### 2.1 技术栈

| 层级 | 技术 |
|---|---|
| 前端 | Vue 3、TypeScript、Vite |
| Web API | FastAPI |
| ORM | SQLAlchemy |
| 数据库 | MySQL |
| 定时任务 | APScheduler |
| 后台任务 | Web 进程内 `ThreadPoolExecutor(max_workers=2)` |
| 主要数据源 | AkShare、公开网页数据源 |

### 2.2 模块边界

基金模块位于：

```text
backend/app/modules/fund_nav/
```

主要职责如下：

| 模块 | 职责 |
|---|---|
| `api/` | 暴露 HTTP 接口；耗时操作只提交队列任务 |
| `models/` | 基金、净值、持仓、行情、估算和任务队列表模型 |
| `schemas/` | API 入参和出参 |
| `services/` | 业务编排、数据库读写、任务执行 |
| `data_sources/akshare_source.py` | 统一收口 AkShare 调用、缓存和接口级锁 |
| `scheduler/jobs.py` | 定时任务入口；只负责提交队列任务 |

运行状态与错误日志位于独立运维模块：

```text
backend/app/modules/operations/
```

## 3. 核心业务数据

### 3.1 自选基金

`funds` 保存用户关注的基金。新增基金时优先从本地 `fund_profiles` 查找名称和类型，接口不直接执行耗时的全量资料同步。

新增成功后自动提交 `sync_new_fund_data` 队列任务，由后台补齐资料、指数映射、官方净值、持仓、行情和估算结果。

### 3.2 基金资料

`fund_profiles` 保存从 `ak.fund_name_em()` 同步的全量基金名称和类型。

资料读取遵循数据库优先原则：

```text
查询 fund_profiles
  -> 命中：直接返回
  -> 未命中：等待 fund_name_em 专属锁，最多 60 秒
      -> 获得锁后再次查询 fund_profiles
      -> 仍未命中：调用 fund_name_em() 全量同步数据库
      -> 再次查询目标基金
      -> 仍未找到：返回未找到，不无限重试
```

### 3.3 官方净值

`fund_navs` 保存基金官方净值和参考基准。

开放式基金优先读取 `ak.fund_open_fund_daily_em()`。该接口返回宽表，不同基金最新日期列可能为空，因此解析时必须读取目标基金行中最近一个非空净值日期。

历史净值和最新官方净值统一存储在 `fund_navs`。新增基金、刷新官方净值或在详情页手动更新历史净值时，会调用 `ak.fund_open_fund_info_em(symbol, indicator="单位净值走势", period="成立来")` 获取单只基金历史单位净值，并按 `fund_code + nav_date` 写入或更新 `fund_navs`。基金详情页基于 `fund_navs` 展示历史净值走势。

场内 ETF 不一定出现在开放式基金净值表中。对于 ETF：

- 优先读取 `ak.fund_etf_spot_em()`。
- 优先使用 `昨收` 作为估算基准。
- `昨收` 缺失时依次使用 `IOPV实时估值`、`最新价`。
- 使用 `昨收` 时来源标记为 `akshare:etf_spot_prev_close`。
- 使用实时字段时来源标记为 `akshare:etf_spot`。

### 3.4 基金持仓

`fund_holdings` 保存基金最近披露的底层资产及持仓比例。

持仓是估算依据，但存在天然滞后。页面应结合 `report_period` 和估算覆盖率理解结果可信度。

资产是否参与实时估算由 `asset_valuation_configs` 控制。刷新行情和运行估值前会加载该表为内存 Map，并按 `asset_type + market` 匹配，未匹配时视为不可实时估值。债券持仓会进入 `fund_holdings`，但当前默认不可实时估值。

### 3.5 行情快照

`market_quotes` 保存底层资产行情快照，包括：

- 最新价。
- 昨收价。
- 当日涨跌幅。
- 行情日期与时间。
- 资产类型和市场。

同一个资产在同一个 `quote_time` 只保存一条记录。

### 3.6 估算结果

`fund_estimates` 保存基金估算结果。

估算公式：

```text
加权涨跌幅 = sum(持仓比例 * 资产涨跌幅)
估算净值 = 基准官方净值 * (1 + 加权涨跌幅)
```

当持仓资产本身是场内 ETF 时，资产涨跌幅按目标 ETF 二级市场行情口径估算：

```text
目标 ETF 当日交易价格涨跌幅
  -> 行情交易日期必须等于估算日期
  -> 行情缺失或交易日期陈旧时跳过该资产
```

这样 ETF 联接基金的盘中估算保持与目标 ETF 交易价格同步，同时避免外部数据源返回旧行情时被误写成当日估算。

覆盖率：

```text
coverage_ratio = 有有效行情的持仓比例 / 已披露持仓比例
```

只有可实时估值的持仓资产参与加权涨跌幅计算。不可实时估值资产不参与涨跌计算，但进入覆盖率分母。债券当前按不可实时估值处理。

A 股、港股和场内 ETF 等实时市场行情参与估算前必须校验交易日期。若 `market_quotes.trade_date` 早于估算日期，该行情视为陈旧行情，不参与当天估算。这样即使最新一条 `quote_time` 被写入当前时间，也不会把旧交易日行情误用于当日估算。

当官方净值、持仓或可实时估值资产行情缺失时，基金会被跳过，并在任务摘要中记录原因。

数据库完整建表 SQL 见 [database.md](./database.md)。

## 4. 基金任务队列

### 4.1 设计目标

AkShare 请求主要是网络 I/O，但部分全量接口响应慢，且解析 DataFrame 和写库仍会占用 Web 进程资源。如果 Web 请求直接执行这些任务，会造成页面响应明显变慢。

因此，所有耗时基金任务统一写入数据库队列：

```text
Web 接口 / 定时任务 / 新增基金流程
  -> 写入 fund_task_queue
  -> 立即返回
  -> dispatcher 定期领取任务
  -> ThreadPoolExecutor(max_workers=2) 执行
```

### 4.2 队列表

队列表为：

```text
fund_task_queue
```

关键字段：

| 字段 | 说明 |
|---|---|
| `task_log_id` | 关联 `task_logs.id` |
| `task_type` | 任务类型 |
| `origin` | `manual`、`scheduled`、`new_fund` |
| `payload_json` | 规范化后的任务参数 |
| `dedupe_key` | 任务类型和规范化参数生成的去重键 |
| `status` | `pending`、`running`、`success`、`partial`、`failed` |
| `queued_at` | 入队时间 |
| `started_at` | 开始执行时间 |
| `finished_at` | 结束时间 |
| `duration_ms` | 执行耗时 |

### 4.3 任务类型

| 任务类型 | 说明 | 来源 |
|---|---|---|
| `refresh_profile` | 刷新基金名称和类型 | 定时任务 |
| `refresh_nav` | 刷新官方净值 | 单只、批量、定时任务 |
| `refresh_holding` | 刷新基金持仓 | 单只、定时任务 |
| `refresh_quote` | 刷新持仓资产行情 | 手动、定时任务 |
| `estimate_nav` | 估算基金当日净值 | 手动、定时任务 |
| `refresh_quote_estimate` | 刷新行情并估算 | 手动组合任务 |
| `refresh_index_mapping` | 刷新指数映射 | 单只手动任务 |
| `sync_new_fund_data` | 新增基金后同步数据 | 新增基金流程 |

组合任务作为单个队列任务执行，内部步骤不重新入队。

### 4.4 Dispatcher

Web 进程启动时创建通用线程池：

```python
ThreadPoolExecutor(max_workers=2)
```

执行规则：

- dispatcher 每 `2` 秒检查队列。
- 有空闲槽位时，按 `queued_at ASC, id ASC` 领取最早的 `pending` 任务。
- 使用数据库行锁领取任务，避免同一任务被重复执行。
- 单个进程最多并行执行两个基金任务。
- MySQL 环境使用 advisory lock `fund_task_worker_slot_0` 和 `fund_task_worker_slot_1`，多 Web 实例部署时全局最多同时执行两个基金任务。

### 4.5 启动恢复

服务启动时尝试获得全部 worker slot advisory lock：

- 可以获得全部锁：说明没有其他实例正在执行基金任务，将遗留 `running` 任务标记为 `failed`。
- 无法获得全部锁：说明存在活跃 worker，跳过恢复，避免误伤其他实例正在执行的任务。

遗留任务不会自动重试。需要由用户或定时任务重新提交。

### 4.6 去重规则

去重键：

```text
dedupe_key = task_type + SHA256(规范化参数)
```

规范化规则：

- 基金代码列表去重。
- 基金代码排序。
- 数字基金代码补足为 6 位。
- 全量任务使用固定目标 `all`。

行为：

| 已存在任务状态 | 新提交行为 |
|---|---|
| `pending` | 复用已有任务，返回已有任务 ID |
| `running` | 允许新增一条 `pending` |
| `success` | 允许新增一条 `pending` |
| `partial` | 允许新增一条 `pending` |
| `failed` | 允许新增一条 `pending` |

系统不使用固定分钟窗口。相同任务只要仍在等待执行，就不会重复插入。

为避免并发请求同时插入相同任务：

- 单进程使用线程锁保护提交过程。
- MySQL 多实例使用 `fund_task_dedupe_*` advisory lock 保护相同去重键。

## 5. API 行为

所有手动耗时接口只提交任务，返回 HTTP `202`。

新任务示例：

```json
{
  "task_id": 123,
  "task_log_id": 456,
  "status": "pending",
  "reused": false,
  "message": "任务已提交"
}
```

存在相同 `pending` 任务时：

```json
{
  "task_id": 123,
  "task_log_id": 456,
  "status": "pending",
  "reused": true,
  "message": "相同任务已在等待执行"
}
```

前端行为：

- 请求返回后立即解除按钮 loading。
- 新任务提示“任务已提交，可到运行状态查看”。
- 复用任务提示“已有相同任务等待执行”。
- 不等待后台任务完成。
- 不自动轮询。
- 运行状态页展示 `pending`、`running`、`success`、`partial`、`failed` 中文状态。

## 6. AkShare 调用规范

### 6.1 统一收口

基金模块所有直接 AkShare 调用必须放在：

```text
backend/app/modules/fund_nav/data_sources/akshare_source.py
```

业务 Service 不直接依赖 AkShare 函数名，便于统一增加缓存、锁、日志和备用源处理。

### 6.2 全量接口缓存

| 接口 | 缓存来源 | TTL |
|---|---|---:|
| `fund_etf_spot_em()` | 进程内 DataFrame | 5 分钟 |
| `stock_zh_a_spot()` | 进程内 DataFrame | 5 分钟 |
| `stock_zh_a_spot_em()` | 进程内 DataFrame | 5 分钟 |
| `stock_hk_spot()` | 进程内 DataFrame | 5 分钟 |
| `stock_hk_spot_em()` | 进程内 DataFrame | 5 分钟 |
| `fund_open_fund_daily_em()` | 进程内 DataFrame | 10 分钟 |
| `fund_name_em()` | 数据库 `fund_profiles` | 长期保存 |

### 6.3 Singleflight 加载器

高耗时全量接口使用“双重检查 + 接口级锁 + 有界等待”：

```text
查询缓存
  -> 命中：直接返回
  -> 未命中：等待接口级锁，最多 60 秒
      -> 获得锁后再次查询缓存
      -> 命中：返回
      -> 未命中：调用 AkShare
      -> 保存缓存
      -> 返回
      -> finally 释放锁
  -> 等待超时：抛出异常，当前任务失败
```

锁释放后，等待线程会重新查询缓存，通常直接使用前一个线程刚写入的数据，不会重复请求 AkShare。

### 6.4 旧缓存降级

实时行情缓存过期后，如果刷新 AkShare 失败：

```text
存在最近一次成功缓存，且缓存年龄不超过实时旧缓存最大可用时间
  -> 记录 warning 和缓存年龄
  -> 返回旧缓存
旧缓存超过最大可用时间
  -> 拒绝旧缓存，继续走单标的备用源或按行情缺失处理
不存在旧缓存
  -> 抛出异常
```

该策略用于提高短时间网络波动下行情刷新任务的可用性。实时行情旧缓存最大可用时间为 15 分钟。旧缓存不会伪装成新缓存，日志中会明确标记 `stale_fallback`；超过最大可用时间时记录 `stale_rejected`。

### 6.5 备用源调用

A 股和港股行情遵循按需 fallback：

```text
调用首选全量接口
  -> 已覆盖目标代码：停止
  -> 仍有缺失：调用备用全量接口补齐
```

ETF 官方净值批量刷新只加载一次 ETF 全量表。

### 6.6 暂不全局缓存的接口

以下接口依赖单个基金或资产参数，暂不增加全局 DataFrame 缓存：

- `fund_portfolio_hold_em(symbol, year)`
- `stock_us_daily(symbol)`
- `stock_hk_hist(symbol)`
- `fund_etf_hist_em(symbol)`
- `stock_zh_a_hist(symbol)`

更完整的数据源说明见 [data_sources.md](./data_sources.md)。

## 7. 日志与可观测性

系统使用 `app.performance` logger 记录性能信息，不记录 Cookie、密码或其他敏感配置。

日志覆盖：

| 类别 | 关键字段 |
|---|---|
| 队列提交 | 任务 ID、类型、来源、目标 |
| 队列领取 | 任务 ID、类型、排队耗时 |
| 队列完成 | 任务 ID、状态、执行耗时 |
| 缓存 | 接口名、`hit`、`miss`、`expired`、`stale_fallback`、`stale_rejected`、缓存年龄 |
| 接口锁 | 接口名、等待耗时、`acquired` 或 `timeout` |
| AkShare | 接口名、成功或失败、请求耗时、DataFrame 行数 |
| 解析 | 目标数量、匹配数量、遍历耗时 |
| 备用源 | 市场、接口名、是否 fallback、缺失数量 |
| 数据库 | 写入条数、提交耗时 |
| 估算 | 目标基金数、成功数、跳过数、总耗时 |
| 恢复 | 启动时标记失败的中断任务数 |

当系统出现卡顿时，建议按以下顺序排查：

1. 查看任务是否长时间停留在 `pending`。
2. 查看线程池是否已有两个 `running` 任务。
3. 查看 `akshare_lock` 是否等待或超时。
4. 查看 `akshare_fetch` 是否耗时过高或失败。
5. 查看数据库 commit 耗时。

## 8. 数据库初始化

新增队列表后执行：

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\init_db.py
```

`scripts/init_db.py` 会通过 SQLAlchemy metadata 创建尚不存在的表，不会删除已有数据。

生产环境建表 SQL 可直接参考 [database.md](./database.md) 中的 `fund_task_queue` 章节。

## 9. 测试策略

当前自动测试覆盖：

- 相同 `pending` 任务复用。
- 相同 `running` 任务允许新增等待任务。
- 并发提交相同任务时仅创建一条 `pending`。
- FIFO 领取任务。
- 遗留 `running` 任务恢复为 `failed`。
- ETF 和开放式基金全量表缓存。
- 两个线程同时缓存 miss 时只请求一次 AkShare。
- 过期缓存刷新失败时短时间使用旧缓存，过老实时缓存会被拒绝。
- 首选行情源完整覆盖时不调用备用源。

交付前应执行：

```powershell
cd backend
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests

cd ..\frontend
g:\nodejs\npx.cmd vue-tsc --noEmit
g:\nodejs\npm.cmd run build
```

## 10. 当前限制与演进方向

当前实现有意保持简单：

- worker 暂时运行在 Web 进程内。
- 线程池固定为两个 worker，不区分实时任务和维护任务。
- 缓存是单进程内存缓存，多实例之间不共享。
- 本轮未优化数据库批量写入。
- 本轮未优化估算流程中的 N+1 查询。
- 前端不自动轮询任务状态。

后续数据量、实例数或任务量明显增长时，可评估：

- 使用 Redis 共享行情缓存。
- 将 worker 拆分为独立进程。
- 使用专业任务队列替代进程内 dispatcher。
- 为不同任务类型设置优先级或并发配额。
- 增加任务取消、重试和失败告警。
- 批量写入行情和基金资料。
- 优化估算查询，减少 N+1 数据库访问。

