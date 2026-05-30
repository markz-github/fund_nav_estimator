from __future__ import annotations

from pathlib import Path
import sys
import unittest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.scheduler.cron_utils import normalize_cron_expression


class CronUtilsTests(unittest.TestCase):
    def test_normalize_cron_expression_uses_standard_weekday_numbers(self) -> None:
        self.assertEqual(normalize_cron_expression("0 7 * * 1"), "0 7 * * mon")
        self.assertEqual(normalize_cron_expression("0 7 * * 0"), "0 7 * * sun")
        self.assertEqual(normalize_cron_expression("0 7 * * 7"), "0 7 * * sun")

    def test_normalize_cron_expression_expands_weekday_ranges(self) -> None:
        self.assertEqual(normalize_cron_expression("0 7 * * 1-5"), "0 7 * * mon,tue,wed,thu,fri")

    def test_normalize_cron_expression_uses_default_for_empty_value(self) -> None:
        self.assertEqual(normalize_cron_expression(None), "0 7 * * *")


if __name__ == "__main__":
    unittest.main()
