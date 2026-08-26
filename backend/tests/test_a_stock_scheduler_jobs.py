from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.modules.a_stock.service import AStockHistorySyncService, previous_weekday
from app.scheduler.a_stock_jobs import sync_previous_a_stock_trading_day_job
from scripts import sync_a_stock_daily_bars


class AStockSchedulerJobTests(unittest.TestCase):
    def test_history_fetch_uses_tencent_before_sina_fallback(self) -> None:
        dataframe = pd.DataFrame(
            [{"date": date(2026, 7, 24), "open": 39, "close": 38.18, "high": 39.15, "low": 38.15, "amount": 1}]
        )
        previous_retry_at = sync_a_stock_daily_bars._hist_source_retry_at
        sync_a_stock_daily_bars._hist_source_retry_at = float("inf")
        try:
            with (
                patch.object(sync_a_stock_daily_bars.ak, "stock_zh_a_hist_tx", return_value=dataframe) as tencent,
                patch.object(sync_a_stock_daily_bars.ak, "stock_zh_a_daily") as sina,
            ):
                result, source = sync_a_stock_daily_bars.fetch_history_dataframe("689009", "20260724", "20260724", "")
        finally:
            sync_a_stock_daily_bars._hist_source_retry_at = previous_retry_at

        self.assertEqual(source, "akshare:stock_zh_a_hist_tx")
        self.assertIs(result, dataframe)
        tencent.assert_called_once_with(symbol="sh689009", start_date="20260724", end_date="20260724", adjust="")
        sina.assert_not_called()

    def test_beijing_exchange_920_code_uses_bj_prefix_for_fallback(self) -> None:
        dataframe = pd.DataFrame(
            [{"date": date(2026, 7, 24), "open": 10, "close": 10, "high": 10, "low": 10, "amount": 1}]
        )
        previous_retry_at = sync_a_stock_daily_bars._hist_source_retry_at
        sync_a_stock_daily_bars._hist_source_retry_at = float("inf")
        try:
            with patch.object(sync_a_stock_daily_bars.ak, "stock_zh_a_hist_tx", return_value=dataframe) as tencent:
                result, source = sync_a_stock_daily_bars.fetch_history_dataframe("920112", "20260724", "20260724", "")
        finally:
            sync_a_stock_daily_bars._hist_source_retry_at = previous_retry_at

        self.assertEqual(source, "akshare:stock_zh_a_hist_tx")
        self.assertIs(result, dataframe)
        tencent.assert_called_once_with(symbol="bj920112", start_date="20260724", end_date="20260724", adjust="")

    def test_primary_history_failure_uses_temporary_cooldown(self) -> None:
        dataframe = pd.DataFrame(
            [{"date": date(2026, 7, 24), "open": 10, "close": 10, "high": 10, "low": 10, "amount": 1}]
        )
        previous_retry_at = sync_a_stock_daily_bars._hist_source_retry_at
        sync_a_stock_daily_bars._hist_source_retry_at = 0.0
        try:
            with (
                patch.object(sync_a_stock_daily_bars.ak, "stock_zh_a_hist", side_effect=RuntimeError("source unavailable")),
                patch.object(sync_a_stock_daily_bars.ak, "stock_zh_a_hist_tx", return_value=dataframe),
            ):
                sync_a_stock_daily_bars.fetch_history_dataframe("600000", "20260724", "20260724", "")
            self.assertGreater(sync_a_stock_daily_bars._hist_source_retry_at, 0.0)
        finally:
            sync_a_stock_daily_bars._hist_source_retry_at = previous_retry_at

    def test_repeated_fetch_issues_are_logged_as_a_summary(self) -> None:
        sync_a_stock_daily_bars.reset_fetch_issue_stats()
        try:
            with patch.object(sync_a_stock_daily_bars.logger, "warning") as warning:
                sync_a_stock_daily_bars.record_fetch_issue("empty_response", "stock_zh_a_daily", "920111", "")
                sync_a_stock_daily_bars.record_fetch_issue("empty_response", "stock_zh_a_daily", "920112", "")
                sync_a_stock_daily_bars.log_fetch_issue_summary()

            self.assertEqual(warning.call_count, 2)
            self.assertIn("repeats_will_be_summarized=true", warning.call_args_list[0].args[0])
            self.assertIn("akshare_fetch_issue_summary", warning.call_args_list[1].args[0])
            self.assertEqual(warning.call_args_list[1].args[4], 2)
        finally:
            sync_a_stock_daily_bars.reset_fetch_issue_stats()

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
