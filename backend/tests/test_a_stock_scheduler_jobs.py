from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.modules.a_stock.service import AStockHistorySyncService, previous_weekday
from app.scheduler.a_stock_jobs import sync_previous_a_stock_trading_day_job


class AStockSchedulerJobTests(unittest.TestCase):
    def test_scheduler_job_checks_and_starts_missing_previous_trading_day(self) -> None:
        service = Mock()
        service.sync_previous_trading_day_if_missing.return_value = {"started": True, "trade_date": "20260609"}

        with patch("app.scheduler.a_stock_jobs.AStockHistorySyncService", return_value=service):
            sync_previous_a_stock_trading_day_job()

        service.sync_previous_trading_day_if_missing.assert_called_once_with()

    def test_sync_previous_trading_day_skips_when_data_exists(self) -> None:
        service = AStockHistorySyncService()

        with (
            patch.object(service, "previous_trading_day", return_value=date(2026, 6, 9)),
            patch.object(service, "has_daily_bars_for_date", return_value=True),
            patch.object(service, "start") as start,
        ):
            result = service.sync_previous_trading_day_if_missing(today=date(2026, 6, 10))

        self.assertFalse(result["started"])
        self.assertEqual(result["trade_date"], "20260609")
        start.assert_not_called()

    def test_sync_previous_trading_day_starts_when_data_missing(self) -> None:
        service = AStockHistorySyncService()
        service.settings.scheduler_a_stock_history_workers = 3

        with (
            patch.object(service, "previous_trading_day", return_value=date(2026, 6, 9)),
            patch.object(service, "has_daily_bars_for_date", return_value=False),
            patch.object(service, "start", return_value={"started": True, "task_id": 12}) as start,
        ):
            result = service.sync_previous_trading_day_if_missing(today=date(2026, 6, 10))

        self.assertTrue(result["started"])
        self.assertEqual(result["trade_date"], "20260609")
        payload = start.call_args.args[0]
        self.assertEqual(payload.mode, "date_range")
        self.assertEqual(payload.start_date, date(2026, 6, 9))
        self.assertEqual(payload.end_date, date(2026, 6, 9))
        self.assertEqual(payload.workers, 3)

    def test_previous_weekday_skips_weekend(self) -> None:
        self.assertEqual(previous_weekday(date(2026, 6, 8)), date(2026, 6, 5))


if __name__ == "__main__":
    unittest.main()
