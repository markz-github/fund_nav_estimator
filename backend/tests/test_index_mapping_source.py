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


if __name__ == "__main__":
    unittest.main()
