from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "基金当日净值预测"
    app_env: str = "local"
    debug: bool = Field(default=True, validation_alias="APP_DEBUG")

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "change_me"
    mysql_database: str = "fund_nav_estimator"

    scheduler_enabled: bool = False
    scheduler_refresh_nav_cron: str = "0 20 * * *"
    scheduler_refresh_holdings_cron: str = "30 20 * * mon-fri"
    scheduler_refresh_quotes_cron: str = "0,30 9-15 * * mon-fri"
    scheduler_estimate_nav_cron: str = "5,35 9-15 * * mon-fri"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )

    @property
    def mysql_server_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
