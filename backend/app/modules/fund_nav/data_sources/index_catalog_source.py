from __future__ import annotations

from dataclasses import dataclass

import akshare as ak


@dataclass(frozen=True)
class MarketIndexSnapshot:
    index_code: str
    index_name: str
    index_short_name: str | None
    provider: str
    currency: str | None
    asset_class: str | None
    source: str
    raw_snapshot: str | None = None


class IndexCatalogSource:
    source_name = "akshare:index_catalog"

    def get_indexes(self) -> list[MarketIndexSnapshot]:
        snapshots: list[MarketIndexSnapshot] = []
        snapshots.extend(self.get_csindex_indexes())
        snapshots.extend(self.get_cni_indexes())
        return snapshots

    def get_csindex_indexes(self) -> list[MarketIndexSnapshot]:
        dataframe = ak.index_csindex_all()
        snapshots: list[MarketIndexSnapshot] = []
        for _, row in dataframe.iterrows():
            index_code = self._clean(row.get("指数代码"))
            index_name = self._clean(row.get("指数全称"))
            if not index_code or not index_name:
                continue
            snapshots.append(
                MarketIndexSnapshot(
                    index_code=index_code,
                    index_name=index_name,
                    index_short_name=self._clean(row.get("指数简称")),
                    provider="csindex",
                    currency=self._clean(row.get("指数币种")),
                    asset_class=self._clean(row.get("资产类别")),
                    source="akshare:index_csindex_all",
                    raw_snapshot=self._row_snapshot(row),
                )
            )
        return snapshots

    def get_cni_indexes(self) -> list[MarketIndexSnapshot]:
        dataframe = ak.index_all_cni()
        snapshots: list[MarketIndexSnapshot] = []
        for _, row in dataframe.iterrows():
            index_code = self._clean(row.get("指数代码"))
            index_short_name = self._clean(row.get("指数简称"))
            if not index_code or not index_short_name:
                continue
            snapshots.append(
                MarketIndexSnapshot(
                    index_code=index_code,
                    index_name=index_short_name,
                    index_short_name=index_short_name,
                    provider="cni",
                    currency=None,
                    asset_class=None,
                    source="akshare:index_all_cni",
                    raw_snapshot=self._row_snapshot(row),
                )
            )
        return snapshots

    @staticmethod
    def _clean(value) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text in {"-", "--"} or text.lower() == "nan":
            return None
        return text

    @classmethod
    def _row_snapshot(cls, row) -> str:
        values = {
            str(key): cls._clean(value)
            for key, value in row.to_dict().items()
            if cls._clean(value) is not None
        }
        return str(values)
