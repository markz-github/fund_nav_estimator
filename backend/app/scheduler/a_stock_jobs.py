from __future__ import annotations

import logging

from app.modules.a_stock.service import AStockHistorySyncService


logger = logging.getLogger(__name__)


def sync_previous_a_stock_trading_day_job() -> None:
    result = AStockHistorySyncService().sync_previous_trading_day_if_missing()
    logger.info("sync_previous_a_stock_trading_day result=%s", result)
