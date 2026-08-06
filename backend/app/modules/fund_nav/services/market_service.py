from __future__ import annotations

import logging
from datetime import datetime, time
from time import perf_counter
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.fund_nav.data_sources.akshare.akshare_source import AkshareSource, FetchDiagnostic
from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.fund_holding import FundHolding
from app.modules.fund_nav.models.fund_index_mapping import FundIndexMapping
from app.modules.fund_nav.models.market_quote import MarketQuote
from app.modules.fund_nav.services.asset_valuation_config_service import load_asset_valuation_config_map
from app.modules.fund_nav.services.fund_classifier import FundClassifier
from app.utils.performance import timed


class MarketService:
    def __init__(self, db: Session, source: AkshareSource | None = None) -> None:
        self.db = db
        self.source = source or AkshareSource(db)
        self.last_refresh_diagnostics: list[FetchDiagnostic] = []

    @timed()
    def fetch_quotes(self, asset_codes: list[str]):
        return self.source.get_market_quotes(asset_codes)

    @timed()
    def refresh_quotes_for_holdings(
        self,
        fund_codes: list[str] | None = None,
        *,
        reference_time: datetime | None = None,
    ) -> list[MarketQuote]:
        started = perf_counter()
        valuation_configs = load_asset_valuation_config_map(self.db)
        assets = self._assets_from_latest_holdings(fund_codes)
        assets.update(self._etf_fund_assets(fund_codes))
        assets.update(self._index_assets_from_mappings(fund_codes))
        valuable_assets = {
            asset_code: asset
            for asset_code, asset in assets.items()
            if valuation_configs.resolve(asset["asset_type"], asset["market"]).realtime_valuable
        }
        refresh_time = reference_time or datetime.now()
        valuable_assets = {
            asset_code: asset
            for asset_code, asset in valuable_assets.items()
            if self._market_has_opened(asset.get("market"), refresh_time)
        }
        stock_asset_codes = [
            asset_code
            for asset_code, asset in valuable_assets.items()
            if asset["asset_type"] not in {"etf", "index"}
        ]
        etf_codes = [
            asset_code
            for asset_code, asset in valuable_assets.items()
            if asset["asset_type"] == "etf"
        ]
        index_codes = [
            asset_code
            for asset_code, asset in valuable_assets.items()
            if asset["asset_type"] == "index"
        ]
        token = self.source.begin_fetch_diagnostics()
        try:
            snapshots = []
            if stock_asset_codes:
                snapshots.extend(self.source.get_market_quotes(stock_asset_codes))
            if etf_codes:
                snapshots.extend(self.source.get_market_quotes(etf_codes))
            if index_codes:
                snapshots.extend(self.source.get_index_quotes(index_codes))
        finally:
            self.last_refresh_diagnostics = self.source.end_fetch_diagnostics(token)
        quotes: list[MarketQuote] = []

        for snapshot in snapshots:
            asset = valuable_assets.get(snapshot.asset_code, {})
            quote = self.db.scalar(
                select(MarketQuote)
                .where(
                    MarketQuote.asset_code == snapshot.asset_code,
                    MarketQuote.quote_time == snapshot.quote_time,
                )
                .execution_options(include_deleted=True)
            )
            if quote is None:
                quote = MarketQuote(
                    asset_code=snapshot.asset_code,
                    asset_name=snapshot.asset_name or asset.get("asset_name"),
                    asset_type=snapshot.asset_type,
                    market=snapshot.market,
                    trade_date=snapshot.trade_date,
                    quote_time=snapshot.quote_time,
                    latest_price=snapshot.latest_price,
                    prev_close=snapshot.prev_close,
                    change_rate=snapshot.change_rate,
                    source=self.source.source_name,
                )
                self.db.add(quote)
            else:
                quote.is_deleted = 0
                quote.asset_name = snapshot.asset_name or quote.asset_name or asset.get("asset_name")
                quote.asset_type = snapshot.asset_type
                quote.market = snapshot.market
                quote.trade_date = snapshot.trade_date
                quote.latest_price = snapshot.latest_price
                quote.prev_close = snapshot.prev_close
                quote.change_rate = snapshot.change_rate
                quote.source = self.source.source_name
            quotes.append(quote)

        commit_started = perf_counter()
        self.db.commit()
        logging.getLogger("app.performance").info(
            "database operation=upsert_market_quotes rows=%s commit_ms=%.2f total_ms=%.2f",
            len(quotes),
            (perf_counter() - commit_started) * 1000,
            (perf_counter() - started) * 1000,
        )
        for quote in quotes:
            self.db.refresh(quote)
        return quotes

    @timed()
    def latest_quotes(self) -> list[MarketQuote]:
        subquery = (
            select(MarketQuote.asset_code, func.max(MarketQuote.quote_time).label("latest_time"))
            .group_by(MarketQuote.asset_code)
            .subquery()
        )
        return self.db.scalars(
            select(MarketQuote).join(
                subquery,
                (MarketQuote.asset_code == subquery.c.asset_code)
                & (MarketQuote.quote_time == subquery.c.latest_time),
            )
        ).all()

    def _assets_from_latest_holdings(self, fund_codes: list[str] | None = None) -> dict[str, dict[str, str | None]]:
        latest_period_statement = select(
            FundHolding.fund_code,
            func.max(FundHolding.report_period).label("report_period"),
        ).where(FundHolding.holding_ratio > 0)
        if fund_codes:
            latest_period_statement = latest_period_statement.where(FundHolding.fund_code.in_(fund_codes))
        latest_periods = latest_period_statement.group_by(FundHolding.fund_code).subquery()

        statement = (
            select(FundHolding.asset_code, FundHolding.asset_name, FundHolding.asset_type, FundHolding.market)
            .join(
                latest_periods,
                (FundHolding.fund_code == latest_periods.c.fund_code)
                & (FundHolding.report_period == latest_periods.c.report_period),
            )
            .distinct()
        )
        rows = self.db.execute(statement).all()
        return {
            asset_code: {
                "asset_name": asset_name,
                "asset_type": asset_type,
                "market": market,
            }
            for asset_code, asset_name, asset_type, market in rows
        }

    def _etf_fund_assets(self, fund_codes: list[str] | None = None) -> dict[str, dict[str, str | None]]:
        statement = select(Fund).where(Fund.enabled == 1)
        if fund_codes:
            statement = statement.where(Fund.fund_code.in_(fund_codes))
        funds = self.db.scalars(statement).all()
        assets: dict[str, dict[str, str | None]] = {}
        for fund in funds:
            fund_code = str(fund.fund_code or "").strip()
            fund_name = fund.fund_name or ""
            if not FundClassifier.is_exchange_traded_fund(fund):
                continue
            assets[fund_code] = {
                "asset_name": fund_name,
                "asset_type": "etf",
                "market": "CN",
            }
        return assets

    def _index_assets_from_mappings(self, fund_codes: list[str] | None = None) -> dict[str, dict[str, str | None]]:
        fund_statement = select(Fund).where(Fund.enabled == 1)
        if fund_codes:
            fund_statement = fund_statement.where(Fund.fund_code.in_(fund_codes))
        eligible_fund_codes = [
            fund.fund_code
            for fund in self.db.scalars(fund_statement).all()
            if FundClassifier.is_index_tracking_fund(fund)
        ]
        if not eligible_fund_codes:
            return {}

        rows = self.db.execute(
            select(FundIndexMapping.index_code, FundIndexMapping.index_name)
            .where(
                FundIndexMapping.fund_code.in_(eligible_fund_codes),
                FundIndexMapping.index_code.is_not(None),
            )
            .distinct()
        ).all()
        return {
            self._normalize_index_code(index_code): {
                "asset_name": index_name,
                "asset_type": "index",
                "market": "CN",
            }
            for index_code, index_name in rows
            if index_code
        }

    @staticmethod
    def _normalize_index_code(index_code: str) -> str:
        code = str(index_code or "").strip().upper()
        for suffix in (".CSI", ".CSINDEX", ".CNI", ".SH", ".SZ"):
            if code.endswith(suffix):
                return code[: -len(suffix)]
        return code

    @staticmethod
    def _market_has_opened(market: str | None, reference_time: datetime) -> bool:
        """Avoid pre-open realtime requests while retaining post-close close-price refreshes."""
        schedules = {
            "SH": ("Asia/Shanghai", time(9, 30)),
            "SZ": ("Asia/Shanghai", time(9, 30)),
            "BJ": ("Asia/Shanghai", time(9, 30)),
            "CN": ("Asia/Shanghai", time(9, 30)),
            "HK": ("Asia/Hong_Kong", time(9, 30)),
            "US": ("America/New_York", time(9, 30)),
        }
        schedule = schedules.get(market or "")
        if schedule is None:
            return True
        timezone_name, open_time = schedule
        if reference_time.tzinfo:
            local_time = reference_time.astimezone(ZoneInfo(timezone_name))
        else:
            local_time = reference_time.replace(tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(
                ZoneInfo(timezone_name)
            )
        return local_time.weekday() < 5 and local_time.time() >= open_time
