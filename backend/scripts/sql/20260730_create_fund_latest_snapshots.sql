CREATE TABLE IF NOT EXISTS fund_latest_snapshots (
    fund_code VARCHAR(20) NOT NULL,
    latest_nav_id BIGINT NULL,
    latest_estimate_id BIGINT NULL,
    target_etf_holding_id BIGINT NULL,
    is_deleted INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (fund_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='基金列表最新数据指针';

INSERT INTO fund_latest_snapshots (
    fund_code,
    latest_nav_id,
    latest_estimate_id,
    target_etf_holding_id,
    is_deleted
)
SELECT
    f.fund_code,
    (
        SELECT n.id
        FROM fund_navs n
        WHERE n.fund_code = f.fund_code
          AND n.is_deleted = 0
        ORDER BY n.nav_date DESC, n.id DESC
        LIMIT 1
    ),
    (
        SELECT e.id
        FROM fund_estimates e
        WHERE e.fund_code = f.fund_code
          AND e.is_deleted = 0
        ORDER BY e.estimate_time DESC, e.id DESC
        LIMIT 1
    ),
    (
        SELECT h.id
        FROM fund_holdings h
        WHERE h.fund_code = f.fund_code
          AND h.is_deleted = 0
          AND h.asset_type = 'etf'
          AND h.source IN ('fund_company', 'local:fund_name_match', 'manual:target_etf')
        ORDER BY h.report_period DESC, h.holding_ratio DESC, h.id DESC
        LIMIT 1
    ),
    0
FROM funds f
WHERE f.is_deleted = 0
ON DUPLICATE KEY UPDATE
    latest_nav_id = VALUES(latest_nav_id),
    latest_estimate_id = VALUES(latest_estimate_id),
    target_etf_holding_id = VALUES(target_etf_holding_id),
    is_deleted = 0,
    updated_at = CURRENT_TIMESTAMP;
