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
from app import models  # noqa: F401


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


def main() -> None:
    ensure_database_exists()
    Base.metadata.create_all(bind=engine)
    ensure_fund_category_columns()
    with SessionLocal() as db:
        seed_default_asset_valuation_configs(db)
    print("Database initialized.")
    print("Created or verified tables:")
    for table_name in inspect(engine).get_table_names():
        print(f"- {table_name}")


if __name__ == "__main__":
    main()
