from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.fund_nav.models.fund_summary_rule import FundSummaryRule
from app.modules.fund_nav.schemas.daily_summary import FundSummaryRuleIn


DEFAULT_FUND_SUMMARY_RULES = (
    ("近30天涨跌预警", 30, "0.10", "0.10"),
    ("近半年涨跌预警", 180, "0.20", "0.20"),
)


class FundSummaryRuleService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_rules(self, *, enabled_only: bool = False) -> list[FundSummaryRule]:
        statement = select(FundSummaryRule).order_by(FundSummaryRule.sort_order, FundSummaryRule.id)
        if enabled_only:
            statement = statement.where(FundSummaryRule.enabled == 1)
        return list(self.db.scalars(statement).all())

    def replace_rules(self, payloads: list[FundSummaryRuleIn]) -> list[FundSummaryRule]:
        self.db.execute(update(FundSummaryRule).values(is_deleted=1))
        existing = {
            row.id: row
            for row in self.db.scalars(
                select(FundSummaryRule).execution_options(include_deleted=True)
            ).all()
        }
        for index, payload in enumerate(payloads):
            row = existing.get(payload.id) if payload.id is not None else None
            if row is None:
                row = FundSummaryRule()
                self.db.add(row)
            row.is_deleted = 0
            row.rule_name = payload.rule_name.strip()
            row.window_days = payload.window_days
            row.rise_threshold = payload.rise_threshold
            row.fall_threshold = payload.fall_threshold
            row.enabled = payload.enabled
            row.sort_order = index
        self.db.commit()
        return self.list_rules()


def seed_default_fund_summary_rules(db: Session) -> None:
    if db.scalar(select(FundSummaryRule.id).limit(1)) is not None:
        return
    for index, (name, days, rise, fall) in enumerate(DEFAULT_FUND_SUMMARY_RULES):
        db.add(
            FundSummaryRule(
                rule_name=name,
                window_days=days,
                rise_threshold=rise,
                fall_threshold=fall,
                enabled=1,
                sort_order=index,
            )
        )
    db.commit()
