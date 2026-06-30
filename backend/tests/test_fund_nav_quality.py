from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import sys
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.models  # noqa: F401
from app.database import Base
from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.fund_estimate import FundEstimate
from app.modules.fund_nav.models.fund_nav import FundNav
from app.modules.fund_nav.api.quality import (
    get_estimate_drift_detail,
    get_fund_nav_quality_report,
    list_estimate_drift_funds,
)
from app.modules.fund_nav.services.nav_quality_service import FundNavQualityService
from app.modules.operations.models.data_fetch_error import DataFetchError
from app.modules.operations.models.task_log import TaskLog


class FundNavQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self) -> None:
        self.db.close()

    def test_expected_nav_date_uses_previous_business_day_before_evening(self) -> None:
        self.assertEqual(
            FundNavQualityService.expected_nav_date(datetime(2026, 6, 8, 10, 0)),
            date(2026, 6, 5),
        )
        self.assertEqual(
            FundNavQualityService.expected_nav_date(datetime(2026, 6, 8, 21, 30)),
            date(2026, 6, 8),
        )
        self.assertEqual(
            FundNavQualityService.expected_nav_date(datetime(2026, 6, 14, 21, 30)),
            date(2026, 6, 12),
        )

    def test_check_latest_nav_freshness_records_stale_nav_error_once(self) -> None:
        self.db.add_all(
            [
                Fund(id=1, fund_code="000001", fund_name="滞后基金"),
                Fund(id=2, fund_code="000002", fund_name="正常基金"),
                FundNav(
                    id=1,
                    fund_code="000001",
                    nav_date=date(2026, 6, 5),
                    unit_nav=Decimal("1.0000"),
                    accumulated_nav=None,
                    daily_growth_rate=Decimal("0.0100"),
                    source="test",
                ),
                FundNav(
                    id=2,
                    fund_code="000002",
                    nav_date=date(2026, 6, 8),
                    unit_nav=Decimal("1.0000"),
                    accumulated_nav=None,
                    daily_growth_rate=Decimal("0.0100"),
                    source="test",
                ),
            ]
        )
        self.db.commit()
        service = FundNavQualityService(self.db)

        first = service.check_latest_nav_freshness(datetime(2026, 6, 8, 21, 30))
        second = service.check_latest_nav_freshness(datetime(2026, 6, 8, 21, 30))
        self.db.commit()

        errors = self.db.scalars(select(DataFetchError)).all()
        self.assertEqual(first["checked_count"], 2)
        self.assertEqual(first["stale_count"], 1)
        self.assertEqual(second["stale_count"], 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].source, "quality_check")
        self.assertEqual(errors[0].target_code, "000001")
        self.assertIn("expected_nav_date=2026-06-08", errors[0].error_message)

    def test_qdii_fund_allows_previous_business_day_nav(self) -> None:
        self.db.add_all(
            [
                Fund(
                    id=1,
                    fund_code="017436",
                    fund_name="华宝纳斯达克精选股票发起式(QDII)A",
                    fund_type="QDII",
                ),
                FundNav(
                    id=1,
                    fund_code="017436",
                    nav_date=date(2026, 6, 26),
                    unit_nav=Decimal("2.5000"),
                    accumulated_nav=None,
                    daily_growth_rate=Decimal("0.0100"),
                    source="test",
                ),
            ]
        )
        self.db.commit()

        result = FundNavQualityService(self.db).check_latest_nav_freshness(datetime(2026, 6, 29, 22, 30))
        self.db.commit()

        self.assertEqual(result["stale_count"], 0)
        self.assertEqual(self.db.query(DataFetchError).count(), 0)

    def test_qdii_fund_still_reports_nav_older_than_allowed_window(self) -> None:
        self.db.add_all(
            [
                Fund(
                    id=1,
                    fund_code="017436",
                    fund_name="华宝纳斯达克精选股票发起式(QDII)A",
                    fund_type="QDII",
                ),
                FundNav(
                    id=1,
                    fund_code="017436",
                    nav_date=date(2026, 6, 25),
                    unit_nav=Decimal("2.5000"),
                    accumulated_nav=None,
                    daily_growth_rate=Decimal("0.0100"),
                    source="test",
                ),
            ]
        )
        self.db.commit()

        result = FundNavQualityService(self.db).check_latest_nav_freshness(datetime(2026, 6, 29, 22, 30))
        self.db.commit()

        error = self.db.scalar(select(DataFetchError))
        self.assertEqual(result["stale_count"], 1)
        self.assertIn("expected_nav_date=2026-06-26", error.error_message)
        self.assertIn("nav_rule=qdii_delayed", error.error_message)

    def test_quality_report_returns_latest_task_and_unresolved_issues(self) -> None:
        self.db.add(Fund(id=1, fund_code="000001", fund_name="测试基金"))
        self.db.add(
            TaskLog(
                id=1,
                task_name="检查基金官方净值新鲜度",
                task_type="check_nav_quality",
                status="partial",
                started_at=datetime(2026, 6, 8, 21, 30),
                finished_at=datetime(2026, 6, 8, 21, 31),
                message="checked=1;stale=1",
            )
        )
        self.db.add(
            DataFetchError(
                id=1,
                source="quality_check",
                data_type="fund_nav",
                target_code="000001",
                error_message="latest_nav_date=2026-06-05;expected_nav_date=2026-06-08;reason=stale_nav",
                occurred_at=datetime(2026, 6, 8, 21, 31),
                resolved=0,
            )
        )
        self.db.commit()

        report = get_fund_nav_quality_report(db=self.db)

        self.assertEqual(report["latest_task"].status, "partial")
        self.assertEqual(report["issue_count"], 1)
        self.assertEqual(report["issues"][0].fund_name, "测试基金")
        self.assertEqual(report["issues"][0].expected_nav_date, "2026-06-08")

    def test_estimate_drift_only_compares_dates_with_official_nav_and_uses_latest_estimate(self) -> None:
        self.db.add(Fund(id=1, fund_code="000001", fund_name="测试基金"))
        self.db.add_all(
            [
                FundNav(
                    id=1,
                    fund_code="000001",
                    nav_date=date(2026, 6, 8),
                    unit_nav=Decimal("1.0000"),
                    accumulated_nav=None,
                    daily_growth_rate=Decimal("0.0100"),
                    source="test",
                ),
                FundNav(
                    id=2,
                    fund_code="000001",
                    nav_date=date(2026, 6, 9),
                    unit_nav=Decimal("2.0000"),
                    accumulated_nav=None,
                    daily_growth_rate=Decimal("0.0100"),
                    source="test",
                ),
            ]
        )
        self.db.add_all(
            [
                FundEstimate(
                    id=1,
                    fund_code="000001",
                    estimate_date=date(2026, 6, 8),
                    estimate_time=datetime(2026, 6, 8, 14, 30),
                    base_nav_date=date(2026, 6, 7),
                    base_unit_nav=Decimal("0.9900"),
                    estimated_growth_rate=Decimal("0.0100"),
                    estimated_nav=Decimal("1.2000"),
                    coverage_ratio=Decimal("0.8000"),
                    source_snapshot="test",
                ),
                FundEstimate(
                    id=2,
                    fund_code="000001",
                    estimate_date=date(2026, 6, 8),
                    estimate_time=datetime(2026, 6, 8, 15, 0),
                    base_nav_date=date(2026, 6, 7),
                    base_unit_nav=Decimal("0.9900"),
                    estimated_growth_rate=Decimal("0.0100"),
                    estimated_nav=Decimal("1.0100"),
                    coverage_ratio=Decimal("0.9000"),
                    source_snapshot="test",
                ),
                FundEstimate(
                    id=3,
                    fund_code="000001",
                    estimate_date=date(2026, 6, 9),
                    estimate_time=datetime(2026, 6, 9, 15, 0),
                    base_nav_date=date(2026, 6, 8),
                    base_unit_nav=Decimal("1.0000"),
                    estimated_growth_rate=Decimal("0.0100"),
                    estimated_nav=Decimal("2.0400"),
                    coverage_ratio=Decimal("0.9500"),
                    source_snapshot="test",
                ),
                FundEstimate(
                    id=4,
                    fund_code="000001",
                    estimate_date=date(2026, 6, 10),
                    estimate_time=datetime(2026, 6, 10, 15, 0),
                    base_nav_date=date(2026, 6, 9),
                    base_unit_nav=Decimal("2.0000"),
                    estimated_growth_rate=Decimal("0.0100"),
                    estimated_nav=Decimal("2.0800"),
                    coverage_ratio=Decimal("0.9500"),
                    source_snapshot="test",
                ),
            ]
        )
        self.db.commit()

        summaries = list_estimate_drift_funds(
            start_date=date(2026, 6, 8),
            end_date=date(2026, 6, 10),
            threshold=Decimal("0.015"),
            db=self.db,
        )
        detail = get_estimate_drift_detail(
            "000001",
            start_date=date(2026, 6, 8),
            end_date=date(2026, 6, 10),
            threshold=Decimal("0.015"),
            db=self.db,
        )

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["comparable_count"], 2)
        self.assertEqual(summaries[0]["threshold_exceeded_count"], 1)
        self.assertEqual(detail["comparable_count"], 2)
        self.assertEqual([point["estimate_date"] for point in detail["points"]], [date(2026, 6, 8), date(2026, 6, 9)])
        self.assertEqual(detail["points"][0]["estimated_nav"], Decimal("1.010000"))
        self.assertEqual(detail["points"][0]["difference_rate"], Decimal("0.010000"))
        self.assertFalse(detail["points"][0]["threshold_exceeded"])
        self.assertTrue(detail["points"][1]["threshold_exceeded"])


if __name__ == "__main__":
    unittest.main()
