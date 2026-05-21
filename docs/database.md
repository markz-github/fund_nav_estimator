# 数据库设计

数据库使用 MySQL，字符集建议使用 `utf8mb4`。

## 通用字段

系统所有数据表都应包含软删除字段：

```sql
is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '软删除标记：0未删除，1已删除'
```

业务查询默认只返回 `is_deleted = 0` 的数据；删除业务数据时应将 `is_deleted` 更新为 `1`，不做物理删除。现有数据库可执行 `docs/add_is_deleted_columns.sql` 补齐字段。

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
    target_type VARCHAR(50) NULL COMMENT '任务目标类型，如 video、fund、bilinote_task',
    target_id VARCHAR(100) NULL COMMENT '任务目标 ID，如视频 ID、基金代码',
    external_task_id VARCHAR(100) NULL COMMENT '外部任务 ID，如 Bilinote taskid',
    status VARCHAR(20) NOT NULL COMMENT '状态：running、success、failed、partial、skipped',
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

## information_video_sources

信息流视频来源账号表，第一版用于维护 B站 UID 或 space 主页 URL。

```sql
CREATE TABLE information_video_sources (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    platform VARCHAR(30) NOT NULL COMMENT '视频平台，如 bilibili',
    source_name VARCHAR(100) NOT NULL COMMENT '来源账号名称',
    source_url VARCHAR(500) NULL COMMENT '来源主页 URL',
    external_source_id VARCHAR(100) NOT NULL COMMENT '平台账号 ID，如 B站 UID',
    enabled TINYINT NOT NULL DEFAULT 1 COMMENT '是否启用扫描',
    last_scanned_at DATETIME NULL COMMENT '最近扫描时间',
    remark VARCHAR(255) NULL COMMENT '备注',
    raw_response LONGTEXT NULL COMMENT '最近扫描原始响应',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_information_video_source_platform_external (platform, external_source_id),
    INDEX idx_information_video_sources_enabled (enabled)
);
```

## information_videos

信息流视频表，保存扫描到的视频基础信息和处理状态。

```sql
CREATE TABLE information_videos (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    source_id BIGINT NOT NULL COMMENT '来源账号 ID',
    platform VARCHAR(30) NOT NULL COMMENT '视频平台',
    external_video_id VARCHAR(100) NOT NULL COMMENT '平台内容 ID，如 BVID 或 article_xxx',
    title VARCHAR(300) NOT NULL COMMENT '内容标题',
    video_url VARCHAR(500) NOT NULL COMMENT '内容链接',
    content_type VARCHAR(30) NOT NULL DEFAULT 'video' COMMENT '内容类型：video/article',
    content_text LONGTEXT NULL COMMENT '图文正文',
    author_name VARCHAR(100) NULL COMMENT '作者名称',
    published_at DATETIME NULL COMMENT '发布时间',
    status VARCHAR(30) NOT NULL DEFAULT 'discovered' COMMENT '处理状态',
    raw_response LONGTEXT NULL COMMENT '扫描原始响应',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_information_videos_platform_external (platform, external_video_id),
    INDEX idx_information_videos_source (source_id),
    INDEX idx_information_videos_status (status),
    INDEX idx_information_videos_published_at (published_at)
);
```

## information_video_notes

Bilinote 视频文字总结表。

```sql
CREATE TABLE information_video_notes (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    video_id BIGINT NOT NULL COMMENT '视频 ID',
    provider VARCHAR(50) NOT NULL DEFAULT 'bilinote' COMMENT '总结提供方',
    external_task_id VARCHAR(100) NULL COMMENT '外部任务 ID',
    status VARCHAR(30) NOT NULL DEFAULT 'pending' COMMENT '生成状态：pending/running/done/failed',
    note_text LONGTEXT NULL COMMENT '文字版总结',
    error_message TEXT NULL COMMENT '错误信息',
    raw_response LONGTEXT NULL COMMENT '外部接口原始响应',
    generated_at DATETIME NULL COMMENT '生成时间',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_information_video_notes_video_provider (video_id, provider),
    INDEX idx_information_video_notes_status (status)
);
```

## information_summary_documents

Hermes 二次汇总文档表，第一版按每日和平台聚合。

```sql
CREATE TABLE information_summary_documents (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    platform VARCHAR(30) NOT NULL COMMENT '视频平台',
    summary_type VARCHAR(20) NOT NULL DEFAULT 'daily' COMMENT '汇总类型：manual、daily、weekly',
    summary_date DATE NOT NULL COMMENT '汇总日期',
    title VARCHAR(200) NOT NULL COMMENT '文档标题',
    status VARCHAR(30) NOT NULL DEFAULT 'pending' COMMENT '生成状态',
    hermes_run_id VARCHAR(100) NULL COMMENT 'Hermes 异步 run ID',
    document_text LONGTEXT NULL COMMENT '汇总文档正文',
    error_message TEXT NULL COMMENT '错误信息',
    raw_response LONGTEXT NULL COMMENT 'Hermes 原始响应',
    generated_at DATETIME NULL COMMENT '生成时间',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_information_summary_documents_platform_type_date (platform, summary_type, summary_date),
    INDEX idx_information_summary_documents_status (status),
    INDEX idx_information_summary_documents_type_date (summary_type, summary_date)
);
```

## information_summary_document_items

汇总文档与 Bilinote 总结的关联表。

```sql
CREATE TABLE information_summary_document_items (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    document_id BIGINT NOT NULL COMMENT '汇总文档 ID',
    note_id BIGINT NOT NULL COMMENT '视频总结 ID',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_information_summary_document_items_doc_note (document_id, note_id)
);
```

## information_settings

信息流功能设置表，用于保存 Bilinote 和 Hermes 默认参数。

当前使用的设置键包括：

- `bilibili_cookie`：B站扫描请求使用的 Cookie，可为空。
- `article_filter_keywords`：图文投稿过滤关键词，多个关键词可用换行、逗号或分号分隔；扫描时命中标题或正文的图文投稿会标记为 `invalid_content`，不进入 Hermes 图文笔记任务。
- `bilinote_base_url`
- `bilinote_provider_id`
- `bilinote_model_name`
- `bilinote_quality`
- `hermes_base_url`
- `hermes_auth_header_name`：Hermes 鉴权请求头名，默认 `Authorization`，也可配置为 `X-API-Key` 等接口要求的头名。
- `hermes_api_key`：Hermes 接口鉴权令牌。鉴权头名为 `Authorization` 且值未包含认证方案时，后端会以 `Bearer <token>` 形式发送；其他鉴权头名会原样发送该值。
- `hermes_model`：Hermes Runs API 使用的模型名，默认 `hermes-agent`。
- `hermes_run_path`：Hermes Runs API 路径，按 Hermes Agent 当前文档默认使用 `/v1/runs`。
- `hermes_status_path_template`：Hermes Runs 状态轮询路径，按 Hermes Agent 当前文档默认使用 `/v1/runs/{run_id}`。
- `wechat_push_webhook_url`：微信推送接口地址，每天 08:00 推送昨天的已完成每日汇总。
- `wechat_push_token`：微信推送接口可选鉴权令牌。若填写值未包含认证方案，后端会以 `Bearer <token>` 形式发送 `Authorization` 请求头。
- `video_note_recent_days`：Bilinote 总结任务只处理最近 N 天内发布或入库的视频，默认 3 天；设置为 0 表示不限制。
- `hermes_summary_instruction`：手动选择笔记生成自定义汇总时使用的补充说明。
- `hermes_daily_summary_instruction`：每日汇总使用的补充说明。
- `hermes_weekly_summary_instruction`：周汇总使用的补充说明。

```sql
CREATE TABLE information_settings (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    setting_key VARCHAR(100) NOT NULL COMMENT '配置键',
    setting_value TEXT NOT NULL COMMENT '配置值',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_information_settings_key (setting_key)
);
```
