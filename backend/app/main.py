from __future__ import annotations

import logging
from time import perf_counter

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

from app.api import errors, estimates, funds, market, tasks
from app.config import get_settings
from app.scheduler.jobs import create_scheduler


settings = get_settings()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
app = FastAPI(title=settings.app_name, debug=settings.debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(funds.router, prefix="/api")
app.include_router(estimates.router, prefix="/api")
app.include_router(market.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(errors.router, prefix="/api")
scheduler = create_scheduler() if settings.scheduler_enabled else None


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
    if scheduler and not scheduler.running:
        scheduler.start()


@app.on_event("shutdown")
def stop_scheduler() -> None:
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
