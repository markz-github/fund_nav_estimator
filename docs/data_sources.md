# 数据来源

## 首选数据源：akshare

系统优先通过 `akshare` 获取以下数据：

- 基金基础信息：基金代码、基金名称、基金类型。
- 基金官方净值：单位净值、累计净值、净值日期、日涨跌幅。
- 基金持仓：股票、债券、ETF、指数等底层资产及持仓比例。
- 市场行情：底层资产的最新价、昨收价和当日涨跌幅。

所有 AkShare 调用都应集中在 `backend/app/modules/fund_nav/data_sources/akshare/` 下的数据源 adapter 中，避免业务服务直接依赖具体接口名称。通用基金、持仓、股票和 ETF 行情仍由 `akshare/akshare_source.py` 收口；指数行情按渠道拆分为独立文件，并由 `composites/index_quote_source.py` 统一编排。

高耗时全量行情接口使用进程内 DataFrame 缓存和接口级锁。行情缓存 TTL 为 5 分钟，开放式基金净值表缓存 TTL 为 10 分钟。缓存未命中时只有获得锁的线程请求 AkShare；等待线程获得锁后会再次查询缓存。实时行情刷新失败且存在 15 分钟内旧缓存时允许短暂使用旧缓存并记录 warning，超过 15 分钟的旧缓存会被拒绝，避免旧行情被反复写成新行情。

基金名称和类型优先查询 `fund_profiles`。目标基金不存在时，单个线程调用 `fund_name_em()` 全量同步数据库；同步后仍不存在则停止，不循环重试。

## 数据源目录约定

```text
data_sources/
  akshare/       # 通过 AkShare 调用的渠道 adapter
  web/           # 直接 requests 公开网页或公开接口的 adapter
  composites/    # 组合多个渠道的数据源编排器
  support/       # 测试、空实现或兜底辅助数据源
```

## akshare 接口使用结论

### 基金基础信息

- `ak.fund_name_em()` 可返回全量基金基础信息，当前实测约 2.6 万条。
- 全量结果应定期同步到本地 `fund_profiles` 表。
- 添加自选基金时优先查本地 `fund_profiles`，避免每次添加都访问外部数据源。

### 开放式基金净值

- `ak.fund_open_fund_daily_em()` 用于开放式基金官方净值。
- 该接口返回的是宽表，不同基金在最新日期列可能为空。
- 解析时应按“目标基金这一行中最近一个非空单位净值日期”取值，而不是直接使用全表最大日期。
- 基金历史净值使用 `ak.fund_open_fund_info_em(symbol, indicator="单位净值走势", period="成立来")` 按单只基金获取，写入主业务库 `fund_navs`，用于基金详情页历史净值走势。

### 场内 ETF 净值 / 基准

- 场内 ETF 如 `515450` 不一定出现在 `fund_open_fund_daily_em()` 中。
- 对这类基金可 fallback 到 `ak.fund_etf_spot_em()`。
- `昨收` 优先作为 ETF 参考基准，使估算口径保持为“上一基准价 × 当日持仓涨跌”。
- `昨收` 缺失时再 fallback 到 `IOPV实时估值`，仍缺失时可用 `最新价`。
- 使用 `昨收` 时，基准日期按 `数据日期` 推算到上一工作日，来源标记为 `akshare:etf_spot_prev_close`。
- fallback 到 `IOPV实时估值` / `最新价` 时，`数据日期` 作为基准日期，来源标记为 `akshare:etf_spot`。页面上应理解为 ETF 行情基准，不是传统开放式基金官方净值。

### A 股 / 港股 / ETF 行情

- A 股、港股、ETF 行情优先通过 `AkshareSource.get_market_quotes()` 统一获取。
- ETF 行情可通过 `ak.fund_etf_spot_em()`。
- 部分行情接口可能返回重复 quote_time，写入 `market_quotes` 时需要处理唯一键冲突。
- ETF 作为基金持仓参与联接基金估算时，采用目标 ETF 二级市场行情涨跌幅；估算前需要校验行情交易日期，避免外部数据源返回的旧行情被当成当日行情。

### A 股历史日线

- 日线同步按“东方财富 `stock_zh_a_hist` → 腾讯 `stock_zh_a_hist_tx` → 新浪 `stock_zh_a_daily`”顺序获取。
- 腾讯日线作为东财失败后的补充，可覆盖科创板存托凭证等新浪历史接口不稳定的证券。
- 腾讯日线没有成交量、换手率等部分字段时，仍写入可用的开高低收和成交额；缺失字段保持为空。

### 指数行情

指数行情通过 `AkshareSource.get_index_quotes()` 对外提供，内部由 `CompositeIndexQuoteSource` 按 `index_quote_source_status` 中 `source_type = index` 的渠道配置和成功率动态排序尝试。净值估算只使用实时指数行情，默认渠道为：

1. 东方财富 HTTP 实时指数：`push2.eastmoney.com/api/qt/ulist.np/get`，中证 `93xxxx` 等指数使用 `secid = 2.<index_code>`，优先覆盖中证主题指数。
2. 东财 AkShare 实时指数：`ak.stock_zh_index_spot_em()`，按“深证系列指数 / 中证系列指数 / 沪深重要指数 / 上证系列指数”分组查询。
3. 新浪 AkShare 实时指数：`ak.stock_zh_index_spot_sina()`，用于前置实时接口失败或未命中时兜底。
4. 新浪 HTTP 实时指数：`hq.sinajs.cn` 简版行情，用于 AkShare 新浪源失败或未命中时兜底。
5. 腾讯 HTTP 实时指数：`qt.gtimg.cn` 简版行情，用于前置实时源失败或未命中时兜底。
6. 雪球 HTTP 实时指数：`stock.xueqiu.com/v5/stock/realtime/quotec.json`，用于前置实时源失败或未命中时兜底。

腾讯 `qt.gtimg.cn` 可返回上证指数、深证成指等常见指数，但当前探测显示不收录大量中证 `93xxxx` 主题指数；`smartbox.gtimg.cn` 搜索这些指数代码也返回未命中。因此腾讯不能作为中证主题指数的主渠道，不能通过简单增加 `sh` / `sz` / `zs` 等前缀解决。新浪 HTTP 和雪球 HTTP 对中证主题指数覆盖也有限，主要作为 `399xxx`、宽基指数等常见指数的补充渠道。对已确认不覆盖中证 `9xxxxx` 的新浪 HTTP、腾讯 HTTP、雪球 HTTP 渠道，调度层会在请求前跳过这些代码，不计入失败次数；渠道管理页面通过“说明”列展示该能力边界。

历史日 K 和历史交易日实时快照都不能作为盘中净值估算兜底。实时渠道都失败、未命中或只留下历史交易日行情时，本轮指数行情缺失，估值阶段记录 `missing_index_quote` 或回退到持仓法，不再尝试日线源。

每个渠道调用后会更新成功/失败统计：本次调用只要为缺失指数返回至少一条可用行情即记为成功，否则记为失败。排序会综合默认优先级、成功率和连续失败次数；连续失败达到冷却阈值后临时跳过，长期连续失败后自动禁用，需人工重新启用。

股票和 ETF 行情也会记录到同一张渠道状态表，分类为 `source_type = stock` 和 `source_type = etf`。其中股票渠道包括 A 股、港股 AkShare 全量实时接口、HTTP 新浪兜底和历史行情兜底；ETF 渠道包括 `fund_etf_spot_em`、东财 HTTP ETF、HTTP 新浪 ETF 和历史行情兜底。当前只有指数渠道会根据成功率动态调整调用顺序；股票/ETF 先记录可观测性，调用顺序仍遵循 `AkshareSource.get_market_quotes()` 中的固定 fallback 流程。

前端“基金 / 渠道管理”页面读取 `/api/market/index-quote-sources`，按指数、股票、ETF 分类展示渠道排序、成功率、失败率、连续失败、冷却状态和最近错误。

指数行情渠道文件：

- `akshare/eastmoney_index_source.py`：通过 AkShare 调用东财实时指数。
- `akshare/sina_index_source.py`：通过 AkShare 调用新浪实时指数。
- `web/eastmoney_index_source.py`：通过东方财富 HTTP 行情接口调用实时指数。
- `web/sina_index_source.py`：通过新浪 HTTP 行情接口调用实时指数。
- `web/tencent_index_source.py`：通过腾讯 HTTP 行情接口调用实时指数。
- `web/xueqiu_index_source.py`：通过雪球 HTTP 行情接口调用实时指数。
- `composites/index_quote_source.py`：按动态优先级组合实时渠道。

### 债券持仓

- 债券持仓通过 `ak.fund_portfolio_bond_hold_em(symbol, date)` 获取。
- 债券入库为 `asset_type = bond`、`market = CN`。
- 当前债券默认不可实时估值，不拉取行情，不参与当日估算涨跌幅；但会进入持仓展示和估算覆盖率分母。
- 是否可实时估值由 `asset_valuation_configs` 控制，刷新行情和运行估值前加载为内存 Map。

### 美股 QDII 行情

- akshare 有美股行情和历史行情接口：
  - `ak.stock_us_spot_em()`：东方财富美股实时行情，通常延迟约 15 分钟。
  - `ak.stock_us_hist()`：东方财富美股日线。
  - `ak.stock_us_daily()`：新浪美股日线。
- 对国内交易时间内的美股 QDII 基金，通常只需要使用美股上一交易日收盘价。
- 当前建议用 `ak.stock_us_daily(symbol="NVDA", adjust="")` 读取日线，并用最近两天 `close` 计算涨跌幅。
- QDII 持仓中可能出现 `00NVDA`、`00AAPL` 这类被补零的代码，入库前应规范化为 `NVDA`、`AAPL`，市场标记为 `US`。

## 基金持仓备用数据源

`HoldingService` 会把普通持仓和 ETF 联接基金的目标 ETF 映射分开处理：

- 普通持仓：`akshare` -> 天天基金 / 东方财富 `FundArchivesDatas.aspx` -> 新浪基金公开接口。
- ETF 联接 / QDII 目标 ETF：易天富 ETF88 移动/PC 持基页 -> 东方财富基金页文本 -> 基金公司官网产品页 -> 新浪基金 -> 基金速查网 / 理杏仁 / Investing 等公开网页文本。

这些来源都不是正式付费 API，页面结构可能变化。各站点解析逻辑应放在 `backend/app/modules/fund_nav/data_sources/web/` 下的独立 adapter 中，业务服务只负责按优先级尝试和入库。

## 已发现的典型问题

### 515450 缺少官方净值

`515450` 是场内 ETF，不在开放式基金净值接口中。应使用 ETF 行情接口作为参考基准：

- `ak.fund_etf_spot_em()`
- 优先使用 `昨收`
- 缺失时 fallback 到 `IOPV实时估值` / `最新价`
- 来源标记为 `akshare:etf_spot_prev_close`，fallback 时为 `akshare:etf_spot`

### 008163 目标 ETF 识别错误

`008163` 是 ETF 联接基金。公开页面文本解析可能误把页面编号或基金自身资产配置代码识别为目标 ETF，例如 `130026`、`187381`。

处理建议：

- 对已确认的联接基金增加保守映射，例如 `008163 -> 515450`。
- 对东方财富文本 hint 解析增加校验，避免把页面编号、基金吧编号、基金自身代码识别为 ETF。
- 目标 ETF 必须能在 ETF 行情源中查到，才应作为估算持仓使用。

### 017436 美股 QDII 无估算

`017436` 的持仓是美股，如 `NFLX`、`NVDA`、`AAPL`、`MSFT`。此前持仓代码被处理成 `00NFLX`、`00NVDA`，并误判为 A 股市场，导致无法获取行情。

处理建议：

- 保留美股 ticker 字母代码，不做数字补零。
- market 标记为 `US`。
- 使用美股日线收盘价估算，而不是 A 股/港股实时行情。

## 数据滞后说明

基金持仓通常来自季报、半年报或年报，不是实时披露数据。因此估算净值本质上是基于最近公开持仓的近似结果。

建议在页面上展示 `coverage_ratio` 和 `report_period`，帮助判断估算结果的可信度。
