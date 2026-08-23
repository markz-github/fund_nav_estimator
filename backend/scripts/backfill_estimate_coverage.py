"""Correct historical holding-weighted estimate coverage ratios.

Older estimates stored coverage as quoted-weight / disclosed-holdings-weight.
Holding ratios are already percentages of total fund assets, so this script
converts them to quoted-weight / total-fund-assets without recalculating NAVs.
"""

from __future__ import annotations

import argparse
import re
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.modules.fund_nav.models.fund_estimate import FundEstimate
from app.modules.fund_nav.models.fund_holding import FundHolding
from app.modules.fund_nav.models.fund_task_detail_log import FundTaskDetailLog
# Register the referenced table before SQLAlchemy flushes FundTaskDetailLog.
from app.modules.operations.models.task_log import TaskLog  # noqa: F401


HOLDING_PERIOD_PATTERN = re.compile(r"(?:^|;)holdings=([^;]+)")
ONE = Decimal("1")


def holding_period(source_snapshot: str | None) -> str | None:
    match = HOLDING_PERIOD_PATTERN.search(source_snapshot or "")
    return match.group(1) if match else None


def corrected_coverage(
    db: Session,
    *,
    fund_code: str,
    source_snapshot: str | None,
    old_coverage: Decimal | None,
) -> Decimal | None:
    period = holding_period(source_snapshot)
    if old_coverage is None or period is None:
        return None
    disclosed_ratio = db.scalar(
        select(func.coalesce(func.sum(FundHolding.holding_ratio), 0)).where(
            FundHolding.fund_code == fund_code,
            FundHolding.report_period == period,
        )
    )
    return min(Decimal(old_coverage) * min(Decimal(disclosed_ratio), ONE), ONE)


def backfill(db: Session, *, apply: bool) -> tuple[int, int]:
    changed = 0
    inspected = 0
    for model in (FundEstimate, FundTaskDetailLog):
        rows = db.scalars(
            select(model).where(
                model.coverage_ratio.is_not(None),
                model.source_snapshot.like("strategy=holding_weighted;%"),
            )
        ).all()
        for row in rows:
            inspected += 1
            coverage = corrected_coverage(
                db,
                fund_code=row.fund_code,
                source_snapshot=row.source_snapshot,
                old_coverage=row.coverage_ratio,
            )
            if coverage is None or coverage == row.coverage_ratio:
                continue
            changed += 1
            if apply:
                row.coverage_ratio = coverage

    if apply:
        db.commit()
    else:
        db.rollback()
    return inspected, changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill real-time holding coverage ratios.")
    parser.add_argument("--apply", action="store_true", help="Persist changes; default is dry-run.")
    args = parser.parse_args()
    with SessionLocal() as db:
        inspected, changed = backfill(db, apply=args.apply)
    mode = "applied" if args.apply else "dry-run"
    print(f"coverage backfill {mode}: inspected={inspected} changed={changed}")


if __name__ == "__main__":
    main()
