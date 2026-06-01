from __future__ import annotations

from app.database import SessionLocal
from app.modules.fund_nav.schemas.task import FundTaskSubmitOut
from app.modules.fund_nav.services.fund_task_queue_service import FundTaskQueueService


def sync_new_fund_data(fund_code: str) -> FundTaskSubmitOut:
    """Compatibility helper: new-fund synchronization is always queued."""
    with SessionLocal() as db:
        return FundTaskQueueService(db).submit(
            "sync_new_fund_data",
            "新增基金后同步数据",
            origin="new_fund",
            payload={"fund_code": fund_code},
        )
