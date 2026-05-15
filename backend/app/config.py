from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import tomllib

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseModel):
    app_name: str = "基金当日净值预测"
    debug: bool = True
    log_dir: str = "logs"
    log_backup_days: int = 30
    scheduler_enabled: bool = False
    cors_allow_origins: list[str] = Field(default_factory=list)
    scheduler_refresh_nav_cron: str = "0 20 * * *"
    scheduler_refresh_profiles_cron: str = "10 19 * * *"
    scheduler_refresh_holdings_cron: str = "30 20 * * mon-fri"
    scheduler_refresh_quotes_cron: str = "0,30 9-15 * * mon-fri"
    scheduler_estimate_nav_cron: str = "5,35 9-15 * * mon-fri"


class DatabaseConfig(BaseSettings):
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "change_me"
    mysql_database: str = "fund_nav_estimator"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


class Settings(AppConfig):
    app_env: str = "local"

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "change_me"
    mysql_database: str = "fund_nav_estimator"

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


def _config_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "config"


def _read_config_file(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}

    with path.open("rb") as config_file:
        return tomllib.load(config_file)


def _load_app_config(app_env: str) -> AppConfig:
    config_dir = _config_dir()
    merged_config = _read_config_file(config_dir / "default_config.toml")
    merged_config.update(_read_config_file(config_dir / f"{app_env}.toml"))
    return AppConfig(**merged_config)


@lru_cache
def get_settings() -> Settings:
    database_config = DatabaseConfig()
    app_env = os.getenv("APP_ENV", "local")
    app_config = _load_app_config(app_env)
    return Settings(
        **app_config.model_dump(),
        app_env=app_env,
        mysql_host=database_config.mysql_host,
        mysql_port=database_config.mysql_port,
        mysql_user=database_config.mysql_user,
        mysql_password=database_config.mysql_password,
        mysql_database=database_config.mysql_database,
    )
