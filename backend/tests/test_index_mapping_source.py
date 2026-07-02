from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.modules.fund_nav.data_sources.index_mapping_source import FundIndexMappingSource


class FundIndexMappingSourceTests(unittest.TestCase):
    def test_get_99fund_mapping_extracts_index_code_and_name(self) -> None:
        html = """
        <html><body>
        基准指数代码：930997.CSI
        基准指数简称：中证新能源汽车产业指数
        业绩比较基准：中证新能源汽车产业指数收益率×95%+银行人民币活期存款利率(税后)×5%
        </body></html>
        """

        with patch.object(FundIndexMappingSource, "_fetch_text", return_value=html):
            mapping = FundIndexMappingSource().get_mapping("501057")

        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.fund_code, "501057")
        self.assertEqual(mapping.index_code, "930997.CSI")
        self.assertEqual(mapping.index_name, "中证新能源汽车产业指数")
        self.assertEqual(mapping.source, "99fund")
        self.assertEqual(mapping.confidence, "high")

    def test_get_mapping_does_not_use_code_level_manual_mapping(self) -> None:
        with patch.object(FundIndexMappingSource, "_fetch_text", return_value=""):
            mapping = FundIndexMappingSource().get_mapping("160221")

        self.assertIsNone(mapping)

    def test_get_eastmoney_mapping_extracts_tracking_target_without_colon(self) -> None:
        html = """
        <html><body>
        业绩比较基准 中证港股通大消费主题指数收益率*95%+金融机构人民币活期存款利率(税后)*5%
        跟踪标的 中证港股通大消费主题港元指数 投资目标 本基金采用指数化投资策略
        </body></html>
        """

        def fake_fetch(url: str) -> str:
            return "" if "99fund" in url else html

        with patch.object(FundIndexMappingSource, "_fetch_text", side_effect=fake_fetch):
            mapping = FundIndexMappingSource().get_mapping("006786")

        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.index_code, None)
        self.assertEqual(mapping.index_name, "中证港股通大消费主题港元指数")
        self.assertIn("中证港股通大消费主题指数收益率", mapping.benchmark_text)
        self.assertEqual(mapping.source, "eastmoney")


if __name__ == "__main__":
    unittest.main()
