from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings
from app.database import Base, engine
from app.database import SessionLocal
from app.modules.fund_nav.services.asset_valuation_config_service import seed_default_asset_valuation_configs
from app.modules.fund_nav.services.index_quote_source_status_service import seed_default_index_quote_source_statuses
from app.modules.fund_nav.services.index_quote_symbol_service import seed_default_index_quote_symbols
from app import models  # noqa: F401
from scripts.sync_a_stock_daily_bars import (
    create_tables as create_a_stock_tables,
    database_engine as a_stock_database_engine,
    ensure_database_exists as ensure_a_stock_database_exists,
)
from scripts.sync_fund_nav_history import create_tables as create_fund_history_tables


def quote_identifier(identifier: str) -> str:
    return f"`{identifier.replace('`', '``')}`"


def ensure_database_exists() -> None:
    settings = get_settings()
    server_engine = create_engine(settings.mysql_server_url, pool_pre_ping=True)
    database_name = quote_identifier(settings.mysql_database)
    with server_engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS {database_name} "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )


def ensure_column(connection, table_name: str, column_name: str, definition: str) -> None:
    inspector = inspect(connection)
    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in existing_columns:
        return
    connection.execute(text(f"ALTER TABLE {quote_identifier(table_name)} ADD COLUMN {definition}"))


def ensure_index(connection, table_name: str, index_name: str, expression: str) -> None:
    inspector = inspect(connection)
    existing_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name in existing_indexes:
        return
    connection.execute(text(f"CREATE INDEX {quote_identifier(index_name)} ON {quote_identifier(table_name)} ({expression})"))


def ensure_fund_category_columns() -> None:
    with engine.begin() as connection:
        for table_name in ("funds", "fund_profiles"):
            ensure_column(
                connection,
                table_name,
                "fund_category",
                "`fund_category` VARCHAR(30) NULL COMMENT '系统统一基金分类'",
            )
            ensure_column(
                connection,
                table_name,
                "fund_category_source",
                "`fund_category_source` VARCHAR(30) NULL COMMENT '分类来源，如 auto、manual'",
            )
            ensure_column(
                connection,
                table_name,
                "fund_category_updated_at",
                "`fund_category_updated_at` DATETIME NULL COMMENT '分类更新时间'",
            )
        ensure_index(connection, "funds", "idx_funds_category", "`fund_category`")
        ensure_index(connection, "fund_profiles", "idx_fund_profiles_category", "`fund_category`")


def ensure_fund_favorite_column() -> None:
    with engine.begin() as connection:
        ensure_column(
            connection,
            "funds",
            "is_favorite",
            "`is_favorite` INT NOT NULL DEFAULT 0 COMMENT '是否特别关注：0 否，1 是'",
        )


def ensure_index_quote_source_status_columns() -> None:
    with engine.begin() as connection:
        ensure_column(
            connection,
            "index_quote_source_status",
            "source_description",
            "`source_description` VARCHAR(1000) NULL COMMENT '渠道说明和覆盖范围'",
        )
        ensure_column(
            connection,
            "index_quote_source_status",
            "exclude_rule_type",
            "`exclude_rule_type` VARCHAR(20) NOT NULL DEFAULT 'none' COMMENT '排除规则类型：none、regex、enum'",
        )
        ensure_column(
            connection,
            "index_quote_source_status",
            "exclude_rule_value",
            "`exclude_rule_value` VARCHAR(1000) NULL COMMENT '排除规则内容，正则表达式或枚举代码'",
        )
        ensure_column(
            connection,
            "index_quote_source_status",
            "is_deleted",
            "`is_deleted` INT NOT NULL DEFAULT 0 COMMENT '软删除标记'",
        )


def main() -> None:
    ensure_database_exists()
    Base.metadata.create_all(bind=engine)
    ensure_fund_category_columns()
    ensure_fund_favorite_column()
    ensure_index_quote_source_status_columns()
    create_fund_history_tables(engine)
    settings = get_settings()
    ensure_a_stock_database_exists(settings.a_stock_mysql_database)
    create_a_stock_tables(a_stock_database_engine(settings.a_stock_mysql_database))
    with SessionLocal() as db:
        seed_default_asset_valuation_configs(db)
        seed_default_index_quote_source_statuses(db)
        seed_default_index_quote_symbols(db)
        db.commit()
    print("Database initialized.")
    print("Created or verified tables:")
    for table_name in inspect(engine).get_table_names():
        print(f"- {table_name}")


if __name__ == "__main__":
    main()
