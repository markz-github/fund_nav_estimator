# 数据库设计

数据库使用 MySQL，字符集建议使用 `utf8mb4`。

## funds

自选基金表，保存用户关注的基金基础信息。

```sql
CREATE TABLE funds (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    fund_code VARCHAR(20) NOT NULL UNIQUE COMMENT '基金代码',
    fund_name VARCHAR(100) NOT NULL COMMENT '基金名称',
    fund_type VARCHAR(50) NULL COMMENT '基金类型，如股票型、混合型、债券型、指数型',
    enabled TINYINT NOT NULL DEFAULT 1 COMMENT '是否启用估算',
    remark VARCHAR(255) NULL COMMENT '备注',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

## fund_profiles

全量基金基础信息字典表，定期从 `akshare.fund_name_em()` 同步，用于添加基金时快速查询基金名称和类型。

```sql
CREATE TABLE fund_profiles (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    fund_code VARCHAR(20) NOT NULL COMMENT '基金代码',
    fund_name VARCHAR(100) NOT NULL COMMENT '基金名称',
    fund_type VARCHAR(50) NULL COMMENT '基金类型',
    source VARCHAR(50) NOT NULL DEFAULT 'akshare' COMMENT '数据来源',
    synced_at DATETIME NOT NULL COMMENT '最近同步时间',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_fund_profiles_code (fund_code),
    INDEX idx_fund_profiles_name (fund_name),
    INDEX idx_fund_profiles_type (fund_type),
    INDEX idx_fund_profiles_synced_at (synced_at)
);
```

## fund_navs

基金官方净值表。

```sql
CREATE TABLE fund_navs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    fund_code VARCHAR(20) NOT NULL COMMENT '基金代码',
    nav_date DATE NOT NULL COMMENT '净值日期',
    unit_nav DECIMAL(12, 6) NOT NULL COMMENT '单位净值',
    accumulated_nav DECIMAL(12, 6) NULL COMMENT '累计净值',
    daily_growth_rate DECIMAL(10, 6) NULL COMMENT '日涨跌幅，例如 0.0123 表示 1.23%',
    source VARCHAR(50) NOT NULL COMMENT '数据来源',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_fund_nav (fund_code, nav_date),
    INDEX idx_fund_nav_date (nav_date)
);
```

## fund_index_mappings

指数基金与跟踪指数映射表。

```sql
CREATE TABLE fund_index_mappings (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    fund_code VARCHAR(20) NOT NULL COMMENT '基金代码',
    index_code VARCHAR(30) NULL COMMENT '指数代码，如 930997.CSI',
    index_name VARCHAR(100) NULL COMMENT '指数名称',
    benchmark_text TEXT NULL COMMENT '业绩比较基准原文',
    source VARCHAR(50) NOT NULL COMMENT '映射来源，如 99fund、eastmoney',
    confidence VARCHAR(20) NOT NULL DEFAULT 'medium' COMMENT '置信度：high、medium、low',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_fund_index_mapping_code (fund_code),
    INDEX idx_fund_index_mapping_index_code (index_code),
    INDEX idx_fund_index_mapping_updated_at (updated_at)
);
```

## fund_holdings

基金持仓表。

```sql
CREATE TABLE fund_holdings (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    fund_code VARCHAR(20) NOT NULL COMMENT '基金代码',
    report_period VARCHAR(20) NOT NULL COMMENT '报告期，如 2024Q4、2025Q1',
    asset_code VARCHAR(30) NOT NULL COMMENT '资产代码',
    asset_name VARCHAR(100) NOT NULL COMMENT '资产名称',
    asset_type VARCHAR(30) NOT NULL COMMENT '资产类型，如 stock、bond、etf、index、cash',
    market VARCHAR(20) NULL COMMENT '市场，如 SH、SZ、HK、US',
    holding_ratio DECIMAL(10, 6) NOT NULL COMMENT '持仓比例，例如 0.0825 表示 8.25%',
    holding_value DECIMAL(20, 4) NULL COMMENT '持仓市值',
    source VARCHAR(50) NOT NULL COMMENT '数据来源',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_fund_holding (fund_code, report_period, asset_code),
    INDEX idx_fund_holding_fund (fund_code),
    INDEX idx_fund_holding_asset (asset_code)
);
```

## market_quotes

行情快照表。

```sql
CREATE TABLE market_quotes (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    asset_code VARCHAR(30) NOT NULL COMMENT '资产代码',
    asset_name VARCHAR(100) NULL COMMENT '资产名称',
    asset_type VARCHAR(30) NOT NULL COMMENT '资产类型',
    market VARCHAR(20) NULL COMMENT '市场',
    trade_date DATE NOT NULL COMMENT '交易日期',
    quote_time DATETIME NOT NULL COMMENT '行情时间',
    latest_price DECIMAL(20, 6) NULL COMMENT '最新价',
    prev_close DECIMAL(20, 6) NULL COMMENT '昨收价',
    change_rate DECIMAL(10, 6) NULL COMMENT '当日涨跌幅，例如 0.0123 表示 1.23%',
    source VARCHAR(50) NOT NULL COMMENT '数据来源',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_market_quote (asset_code, quote_time),
    INDEX idx_market_quote_asset_date (asset_code, trade_date)
);
```

## fund_estimates

基金估算结果表。

```sql
CREATE TABLE fund_estimates (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    fund_code VARCHAR(20) NOT NULL COMMENT '基金代码',
    estimate_date DATE NOT NULL COMMENT '估算日期',
    estimate_time DATETIME NOT NULL COMMENT '估算时间',
    base_nav_date DATE NOT NULL COMMENT '基准官方净值日期',
    base_unit_nav DECIMAL(12, 6) NOT NULL COMMENT '基准单位净值',
    estimated_growth_rate DECIMAL(10, 6) NULL COMMENT '估算涨跌幅',
    estimated_nav DECIMAL(12, 6) NULL COMMENT '估算单位净值',
    coverage_ratio DECIMAL(10, 6) NULL COMMENT '有效持仓覆盖比例',
    source_snapshot VARCHAR(100) NULL COMMENT '计算使用的数据快照说明',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_fund_estimate (fund_code, estimate_time),
    INDEX idx_fund_estimate_date (estimate_date),
    INDEX idx_fund_estimate_fund_date (fund_code, estimate_date)
);
```

## task_logs

定时任务日志表。

```sql
CREATE TABLE task_logs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    task_name VARCHAR(100) NOT NULL COMMENT '任务名称',
    task_type VARCHAR(50) NOT NULL COMMENT '任务类型，如 refresh_nav、refresh_holding、refresh_quote、estimate_nav',
    status VARCHAR(20) NOT NULL COMMENT '状态：success、failed、partial',
    started_at DATETIME NOT NULL,
    finished_at DATETIME NULL,
    duration_ms BIGINT NULL COMMENT '耗时毫秒',
    message TEXT NULL COMMENT '任务摘要或错误信息',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_task_logs_type_time (task_type, started_at)
);
```

## data_fetch_errors

数据拉取失败记录表。

```sql
CREATE TABLE data_fetch_errors (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    source VARCHAR(50) NOT NULL COMMENT '数据来源',
    data_type VARCHAR(50) NOT NULL COMMENT '数据类型，如 fund_nav、holding、quote',
    target_code VARCHAR(30) NOT NULL COMMENT '目标代码，如基金代码或股票代码',
    error_message TEXT NOT NULL COMMENT '错误信息',
    occurred_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved TINYINT NOT NULL DEFAULT 0 COMMENT '是否已解决',
    INDEX idx_fetch_errors_target (target_code),
    INDEX idx_fetch_errors_time (occurred_at)
);
```
