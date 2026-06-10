from __future__ import annotations

import logging
from time import perf_counter

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

from app.modules.a_stock import api as a_stock_api
from app.modules.fund_nav.api import estimates, funds, history, market
from app.modules.operations.api import errors, tasks
from app.config import get_settings
from app.logging_config import configure_logging
from app.scheduler.scheduler import create_a_stock_scheduler, create_fund_scheduler
from app.modules.fund_nav.services.fund_task_queue_service import dispatcher


settings = get_settings()
configure_logging(settings.log_dir, settings.log_backup_days, settings.log_level)
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
app.include_router(history.router, prefix="/api")
app.include_router(a_stock_api.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(errors.router, prefix="/api")
fund_scheduler = create_fund_scheduler() if settings.scheduler_fund_enabled else None
a_stock_scheduler = create_a_stock_scheduler() if settings.scheduler_a_stock_enabled else None


@app.middleware("http")
async def log_request_duration(request: Request, call_next):
    started_at = perf_counter()
    response = await call_next(request)
    duration_ms = (perf_counter() - started_at) * 1000
    logging.getLogger("app.performance").info(
        "request method=%s path=%s status=%s duration_ms=%.2f",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("startup")
def start_scheduler() -> None:
    dispatcher.start()
    if fund_scheduler and not fund_scheduler.running:
        fund_scheduler.start()
    if a_stock_scheduler and not a_stock_scheduler.running:
        a_stock_scheduler.start()


@app.on_event("shutdown")
def stop_scheduler() -> None:
    dispatcher.shutdown()
    if fund_scheduler and fund_scheduler.running:
        fund_scheduler.shutdown(wait=False)
    if a_stock_scheduler and a_stock_scheduler.running:
        a_stock_scheduler.shutdown(wait=False)
