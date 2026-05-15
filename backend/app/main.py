from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import estimates, funds, market
from app.config import get_settings
from app.logging_config import configure_logging
from app.scheduler.jobs import create_scheduler


settings = get_settings()
configure_logging(settings.log_dir, settings.log_backup_days)
app = FastAPI(title=settings.app_name, debug=settings.debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(funds.router, prefix="/api")
app.include_router(estimates.router, prefix="/api")
app.include_router(market.router, prefix="/api")


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


if settings.scheduler_enabled:
    scheduler = create_scheduler()
    scheduler.start()
