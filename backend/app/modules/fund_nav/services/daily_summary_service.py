from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.fund_daily_summary import FundDailySummary
from app.modules.fund_nav.models.fund_estimate import FundEstimate
from app.modules.fund_nav.models.fund_latest_snapshot import FundLatestSnapshot
from app.modules.fund_nav.models.fund_nav import FundNav
from app.modules.fund_nav.services.fund_summary_rule_service import FundSummaryRuleService


TREND_HISTORY_LIMIT = 366


class FundDailySummaryService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def generate(self, reference_time: datetime | None = None) -> dict:
        generated_at = reference_time or datetime.now()
        summary_date = generated_at.date()
        fund_rows = self.db.execute(
            select(Fund, FundNav, FundEstimate)
            .outerjoin(FundLatestSnapshot, FundLatestSnapshot.fund_code == Fund.fund_code)
            .outerjoin(FundNav, FundNav.id == FundLatestSnapshot.latest_nav_id)
            .outerjoin(FundEstimate, FundEstimate.id == FundLatestSnapshot.latest_estimate_id)
            .where(Fund.enabled == 1)
        ).all()
        rules = FundSummaryRuleService(self.db).list_rules(enabled_only=True)
        max_window_days = max((rule.window_days for rule in rules), default=0)
        oldest_date = summary_date - timedelta(days=max(max_window_days, 550))
        histories = self._load_histories([row[0].fund_code for row in fund_rows], oldest_date)

        self.db.execute(
            update(FundDailySummary)
            .where(FundDailySummary.summary_date == summary_date)
            .values(is_deleted=1)
        )
        existing_rows = {
            row.fund_code: row
            for row in self.db.scalars(
                select(FundDailySummary)
                .where(FundDailySummary.summary_date == summary_date)
                .execution_options(include_deleted=True)
            ).all()
        }
        for fund, latest_nav, latest_estimate in fund_rows:
            history = list(histories.get(fund.fund_code, []))
            latest_data_date = latest_nav.nav_date if latest_nav else None
            latest_growth_rate = latest_nav.daily_growth_rate if latest_nav else None
            if (
                latest_estimate is not None
                and latest_estimate.estimated_growth_rate is not None
                and (latest_nav is None or latest_estimate.estimate_date > latest_nav.nav_date)
            ):
                latest_data_date = latest_estimate.estimate_date
                latest_growth_rate = latest_estimate.estimated_growth_rate
                history.insert(0, (latest_estimate.estimate_date, latest_estimate.estimated_growth_rate))

            trend = self.calculate_trend(history)
            rule_matches = self.match_rules(history, rules, summary_date)
            row = existing_rows.get(fund.fund_code)
            if row is None:
                row = FundDailySummary(summary_date=summary_date, fund_code=fund.fund_code)
                self.db.add(row)
            row.is_deleted = 0
            row.generated_at = generated_at
            row.latest_data_date = latest_data_date
            row.latest_growth_rate = latest_growth_rate
            row.trend_direction = trend["direction"]
            row.trend_days = trend["days"]
            row.trend_days_capped = int(trend["days_capped"])
            row.trend_start_date = trend["start_date"]
            row.trend_end_date = trend["end_date"]
            row.trend_cumulative_growth_rate = trend["cumulative_growth_rate"]
            row.rule_matches_json = rule_matches

        self.db.commit()
        return self.get_latest()

    def get_latest(self) -> dict:
        summary_date = self.db.scalar(
            select(func.max(FundDailySummary.summary_date)).where(FundDailySummary.is_deleted == 0)
        )
        if summary_date is None:
            return {"summary_date": None, "generated_at": None, "items": []}
        rows = list(
            self.db.scalars(
                select(FundDailySummary)
                .where(FundDailySummary.summary_date == summary_date)
                .order_by(FundDailySummary.fund_code)
            ).all()
        )
        return {
            "summary_date": summary_date,
            "generated_at": max((row.generated_at for row in rows), default=None),
            "items": [
                {
                    "fund_code": row.fund_code,
                    "latest_data_date": row.latest_data_date,
                    "latest_growth_rate": row.latest_growth_rate,
                    "trend_direction": row.trend_direction,
                    "trend_days": row.trend_days,
                    "trend_days_capped": bool(row.trend_days_capped),
                    "trend_start_date": row.trend_start_date,
                    "trend_end_date": row.trend_end_date,
                    "trend_cumulative_growth_rate": row.trend_cumulative_growth_rate,
                    "rule_matches": row.rule_matches_json or [],
                }
                for row in rows
            ],
        }

    def _load_histories(
        self, fund_codes: list[str], oldest_date: date
    ) -> dict[str, list[tuple[date, Decimal | None]]]:
        if not fund_codes:
            return {}
        rows = self.db.execute(
            select(FundNav.fund_code, FundNav.nav_date, FundNav.daily_growth_rate)
            .where(FundNav.fund_code.in_(fund_codes), FundNav.nav_date >= oldest_date)
            .order_by(FundNav.fund_code, FundNav.nav_date.desc())
        ).all()
        histories: dict[str, list[tuple[date, Decimal | None]]] = {code: [] for code in fund_codes}
        for fund_code, nav_date, growth_rate in rows:
            histories[fund_code].append((nav_date, growth_rate))
        return histories

    @staticmethod
    def match_rules(history: list[tuple[date, Decimal | None]], rules: list, summary_date: date) -> list[dict]:
        matches: list[dict] = []
        for rule in rules:
            cutoff = summary_date - timedelta(days=rule.window_days)
            factor = Decimal("1")
            usable_count = 0
            for data_date, growth_rate in history:
                if data_date < cutoff:
                    break
                if growth_rate is None:
                    continue
                factor *= Decimal("1") + growth_rate
                usable_count += 1
            if not usable_count:
                continue
            growth_rate = factor - Decimal("1")
            if growth_rate >= rule.rise_threshold:
                direction, threshold = "up", rule.rise_threshold
            elif growth_rate <= -rule.fall_threshold:
                direction, threshold = "down", rule.fall_threshold
            else:
                continue
            matches.append(
                {
                    "rule_id": rule.id,
                    "rule_name": rule.rule_name,
                    "window_days": rule.window_days,
                    "direction": direction,
                    "growth_rate": str(growth_rate.quantize(Decimal("0.000001"))),
                    "threshold": str(threshold),
                }
            )
        return matches

    @staticmethod
    def calculate_trend(history: list[tuple[date, Decimal | None]]) -> dict:
        if not history or history[0][1] is None or history[0][1] == 0:
            return {
                "direction": None,
                "days": 0,
                "days_capped": False,
                "start_date": None,
                "end_date": history[0][0] if history else None,
                "cumulative_growth_rate": None,
            }
        direction = "up" if history[0][1] > 0 else "down"
        factor = Decimal("1")
        streak: list[tuple[date, Decimal]] = []
        for nav_date, growth_rate in history:
            if growth_rate is None or growth_rate == 0 or ((growth_rate > 0) != (direction == "up")):
                break
            streak.append((nav_date, growth_rate))
            factor *= Decimal("1") + growth_rate
        return {
            "direction": direction,
            "days": len(streak),
            "days_capped": len(streak) >= TREND_HISTORY_LIMIT,
            "start_date": streak[-1][0],
            "end_date": streak[0][0],
            "cumulative_growth_rate": factor - Decimal("1"),
        }
