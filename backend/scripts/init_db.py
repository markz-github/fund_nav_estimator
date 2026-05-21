from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings
from app.database import Base, engine
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


def ensure_schema_columns() -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    with engine.begin() as connection:
        for table_name in Base.metadata.tables:
            if table_name not in table_names:
                continue
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            if "is_deleted" not in columns:
                connection.execute(
                    text(
                        f"ALTER TABLE {quote_identifier(table_name)} "
                        "ADD COLUMN is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '软删除标记：0未删除，1已删除'"
                    )
                )

        if "task_logs" in table_names:
            task_log_columns = {column["name"] for column in inspector.get_columns("task_logs")}
            additions = {
                "target_type": "VARCHAR(50) NULL COMMENT '任务目标类型'",
                "target_id": "VARCHAR(100) NULL COMMENT '任务目标 ID'",
                "external_task_id": "VARCHAR(100) NULL COMMENT '外部任务 ID'",
            }
            for column_name, ddl in additions.items():
                if column_name not in task_log_columns:
                    connection.execute(text(f"ALTER TABLE task_logs ADD COLUMN {column_name} {ddl}"))
        if "information_video_notes" in table_names:
            note_indexes = {index["name"] for index in inspector.get_indexes("information_video_notes")}
            if "uk_information_video_notes_video_provider" in note_indexes:
                connection.execute(text("ALTER TABLE information_video_notes DROP INDEX uk_information_video_notes_video_provider"))
            if "idx_information_video_notes_video_provider" not in note_indexes:
                connection.execute(
                    text("CREATE INDEX idx_information_video_notes_video_provider ON information_video_notes (video_id, provider)")
                )
            connection.execute(text("ALTER TABLE information_video_notes MODIFY COLUMN note_text LONGTEXT NULL COMMENT '文字版总结'"))
            connection.execute(text("ALTER TABLE information_video_notes MODIFY COLUMN raw_response LONGTEXT NULL COMMENT '外部接口原始响应'"))
        if "information_video_sources" in table_names:
            connection.execute(text("ALTER TABLE information_video_sources MODIFY COLUMN raw_response LONGTEXT NULL COMMENT '最近扫描原始响应'"))
        if "information_videos" in table_names:
            video_columns = {column["name"] for column in inspector.get_columns("information_videos")}
            if "duration_seconds" not in video_columns:
                connection.execute(
                    text("ALTER TABLE information_videos ADD COLUMN duration_seconds INT NULL COMMENT '视频时长秒数'")
                )
            connection.execute(text("ALTER TABLE information_videos MODIFY COLUMN raw_response LONGTEXT NULL COMMENT '扫描原始响应'"))
        if "information_summary_documents" in table_names:
            summary_columns = {column["name"] for column in inspector.get_columns("information_summary_documents")}
            if "summary_type" not in summary_columns:
                connection.execute(
                    text(
                        "ALTER TABLE information_summary_documents "
                        "ADD COLUMN summary_type VARCHAR(20) NOT NULL DEFAULT 'daily' COMMENT '汇总类型：daily、weekly、manual'"
                    )
                )
            summary_indexes = {index["name"] for index in inspector.get_indexes("information_summary_documents")}
            if "uk_information_summary_documents_platform_date" in summary_indexes:
                connection.execute(text("ALTER TABLE information_summary_documents DROP INDEX uk_information_summary_documents_platform_date"))
            if "uk_information_summary_documents_platform_type_date" not in summary_indexes:
                connection.execute(
                    text(
                        "CREATE UNIQUE INDEX uk_information_summary_documents_platform_type_date "
                        "ON information_summary_documents (platform, summary_type, summary_date)"
                    )
                )
            if "idx_information_summary_documents_type_date" not in summary_indexes:
                connection.execute(
                    text("CREATE INDEX idx_information_summary_documents_type_date ON information_summary_documents (summary_type, summary_date)")
                )
            connection.execute(text("ALTER TABLE information_summary_documents MODIFY COLUMN document_text LONGTEXT NULL COMMENT '汇总文档正文'"))
            connection.execute(text("ALTER TABLE information_summary_documents MODIFY COLUMN raw_response LONGTEXT NULL COMMENT 'Hermes 原始响应'"))


def main() -> None:
    ensure_database_exists()
    Base.metadata.create_all(bind=engine)
    ensure_schema_columns()

    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    print("Database initialized.")
    print("Created or verified tables:")
    for table_name in table_names:
        print(f"- {table_name}")


if __name__ == "__main__":
    main()
