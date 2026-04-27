from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.data_sources.akshare_source import AkshareSource
from app.models.fund_holding import FundHolding
from app.models.market_quote import MarketQuote
from app.utils.performance import timed


class MarketService:
    def __init__(self, db: Session, source: AkshareSource | None = None) -> None:
        self.db = db
        self.source = source or AkshareSource()

    @timed()
    def fetch_quotes(self, asset_codes: list[str]):
        return self.source.get_market_quotes(asset_codes)

    @timed()
    def refresh_quotes_for_holdings(self, fund_codes: list[str] | None = None) -> list[MarketQuote]:
        asset_names = self._asset_names_from_latest_holdings(fund_codes)
        asset_codes = list(asset_names.keys())
        snapshots = self.source.get_market_quotes(asset_codes)
        quotes: list[MarketQuote] = []

        for snapshot in snapshots:
            quote = self.db.scalar(
                select(MarketQuote).where(
                    MarketQuote.asset_code == snapshot.asset_code,
                    MarketQuote.quote_time == snapshot.quote_time,
                )
            )
            if quote is None:
                quote = MarketQuote(
                    asset_code=snapshot.asset_code,
                    asset_name=snapshot.asset_name or asset_names.get(snapshot.asset_code),
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
                quote.asset_name = snapshot.asset_name or quote.asset_name or asset_names.get(snapshot.asset_code)
                quote.asset_type = snapshot.asset_type
                quote.market = snapshot.market
                quote.trade_date = snapshot.trade_date
                quote.latest_price = snapshot.latest_price
                quote.prev_close = snapshot.prev_close
                quote.change_rate = snapshot.change_rate
                quote.source = self.source.source_name
            quotes.append(quote)

        self.db.commit()
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

    def _asset_names_from_latest_holdings(self, fund_codes: list[str] | None = None) -> dict[str, str]:
        latest_period_statement = select(
            FundHolding.fund_code,
            func.max(FundHolding.report_period).label("report_period"),
        ).where(FundHolding.holding_ratio > 0)
        if fund_codes:
            latest_period_statement = latest_period_statement.where(FundHolding.fund_code.in_(fund_codes))
        latest_periods = latest_period_statement.group_by(FundHolding.fund_code).subquery()

        statement = (
            select(FundHolding.asset_code, FundHolding.asset_name)
            .join(
                latest_periods,
                (FundHolding.fund_code == latest_periods.c.fund_code)
                & (FundHolding.report_period == latest_periods.c.report_period),
            )
            .distinct()
        )
        rows = self.db.execute(statement).all()
        return {asset_code: asset_name for asset_code, asset_name in rows}
