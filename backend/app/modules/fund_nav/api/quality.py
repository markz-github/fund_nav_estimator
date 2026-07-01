from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.schemas.quality import (
    EstimateDriftDetailOut,
    EstimateDriftFundSummaryOut,
    FundNavQualityIssueOut,
    FundNavQualityReportOut,
    FundNavQualityTaskOut,
)
from app.modules.fund_nav.services.estimate_drift_service import EstimateDriftService
from app.modules.operations.models.data_fetch_error import DataFetchError
from app.modules.operations.models.task_log import TaskLog

router = APIRouter(prefix="/fund-nav/quality", tags=["fund-nav-quality"])


@router.get("/nav", response_model=FundNavQualityReportOut)
def get_fund_nav_quality_report(
    limit: int = 200,
    unresolved_only: bool = True,
    db: Session = Depends(get_db),
):
    safe_limit = min(max(limit, 1), 500)
    latest_task = db.scalar(
        select(TaskLog)
        .where(TaskLog.task_type == "check_nav_quality")
        .order_by(TaskLog.started_at.desc())
        .limit(1)
    )
    statement = (
        select(DataFetchError, Fund)
        .outerjoin(Fund, Fund.fund_code == DataFetchError.target_code)
        .where(
            DataFetchError.source == "quality_check",
            DataFetchError.data_type.in_(("fund_nav", "fund_mapping")),
        )
        .order_by(DataFetchError.occurred_at.desc(), DataFetchError.id.desc())
        .limit(safe_limit)
    )
    if unresolved_only:
        statement = statement.where(DataFetchError.resolved == 0)
    rows = db.execute(statement).all()
    issues = [_issue_out(error, fund) for error, fund in rows]
    return {
        "latest_task": _task_out(latest_task),
        "issue_count": len(issues),
        "issues": issues,
    }


@router.get("/estimate-drift/funds", response_model=list[EstimateDriftFundSummaryOut])
def list_estimate_drift_funds(
    start_date: date | None = None,
    end_date: date | None = None,
    threshold: Decimal | None = None,
    db: Session = Depends(get_db),
):
    return EstimateDriftService(db).list_fund_drift_summaries(
        start_date=start_date,
        end_date=end_date,
        threshold=threshold,
    )


@router.get("/estimate-drift/funds/{fund_code}", response_model=EstimateDriftDetailOut)
def get_estimate_drift_detail(
    fund_code: str,
    start_date: date | None = None,
    end_date: date | None = None,
    threshold: Decimal | None = None,
    db: Session = Depends(get_db),
):
    return EstimateDriftService(db).get_fund_drift_points(
        fund_code,
        start_date=start_date,
        end_date=end_date,
        threshold=threshold,
    )


def _task_out(task: TaskLog | None) -> FundNavQualityTaskOut | None:
    if task is None:
        return None
    return FundNavQualityTaskOut(
        id=task.id,
        status=task.status,
        started_at=task.started_at,
        finished_at=task.finished_at,
        message=task.message,
    )


def _issue_out(error: DataFetchError, fund: Fund | None) -> FundNavQualityIssueOut:
    details = _parse_message(error.error_message)
    return FundNavQualityIssueOut(
        id=error.id,
        issue_type=error.data_type,
        fund_code=error.target_code,
        fund_name=fund.fund_name if fund else None,
        latest_nav_date=details.get("latest_nav_date"),
        expected_nav_date=details.get("expected_nav_date"),
        nav_rule=details.get("nav_rule"),
        mapping_type=details.get("mapping_type"),
        action=details.get("action"),
        reason=details.get("reason"),
        occurred_at=error.occurred_at,
        message=error.error_message,
    )


def _parse_message(message: str) -> dict[str, str | None]:
    details: dict[str, str | None] = {}
    for part in message.split(";"):
        key, separator, value = part.partition("=")
        if separator:
            details[key] = value if value != "None" else None
    return details
