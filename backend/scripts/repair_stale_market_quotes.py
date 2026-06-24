from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys

from sqlalchemy import create_engine, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings


@dataclass(frozen=True)
class SuspectGroup:
    asset_code: str
    asset_name: str | None
    asset_type: str
    market: str | None
    latest_price: Decimal | None
    prev_close: Decimal | None
    change_rate: Decimal | None
    first_date: date
    last_date: date
    day_count: int
    row_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find or soft-delete stale repeated market quote rows.")
    parser.add_argument("--asset-code", action="append", help="Limit repair to one asset code. Can be repeated.")
    parser.add_argument("--since", default="2026-06-01", help="Start trade_date, YYYY-MM-DD.")
    parser.add_argument("--min-days", type=int, default=3, help="Repeated quote must span at least this many trade days.")
    parser.add_argument("--min-rows", type=int, default=6, help="Repeated quote group must contain at least this many rows.")
    parser.add_argument("--apply", action="store_true", help="Soft-delete suspect rows after the first trade date.")
    return parser.parse_args()


def _asset_filter(asset_codes: list[str] | None) -> tuple[str, dict[str, str]]:
    if not asset_codes:
        return "", {}
    params = {f"asset_code_{index}": asset_code for index, asset_code in enumerate(asset_codes)}
    placeholders = ", ".join(f":{key}" for key in params)
    return f" and asset_code in ({placeholders})", params


def find_suspect_groups(conn, args: argparse.Namespace) -> list[SuspectGroup]:
    asset_filter, asset_params = _asset_filter(args.asset_code)
    rows = conn.execute(
        text(
            f"""
            select asset_code, asset_name, asset_type, market, latest_price, prev_close, change_rate,
                   min(trade_date) first_date,
                   max(trade_date) last_date,
                   count(distinct trade_date) day_count,
                   count(*) row_count
            from market_quotes
            where is_deleted = 0
              and trade_date >= :since
              {asset_filter}
            group by asset_code, asset_name, asset_type, market, latest_price, prev_close, change_rate
            having count(distinct trade_date) >= :min_days
               and count(*) >= :min_rows
            order by day_count desc, row_count desc, asset_code
            """
        ),
        {
            "since": args.since,
            "min_days": args.min_days,
            "min_rows": args.min_rows,
            **asset_params,
        },
    )
    return [SuspectGroup(**dict(row._mapping)) for row in rows]


def soft_delete_group(conn, group: SuspectGroup) -> int:
    result = conn.execute(
        text(
            """
            update market_quotes
            set is_deleted = 1
            where is_deleted = 0
              and asset_code = :asset_code
              and trade_date > :first_date
              and (asset_name = :asset_name or (asset_name is null and :asset_name is null))
              and asset_type = :asset_type
              and (market = :market or (market is null and :market is null))
              and (latest_price = :latest_price or (latest_price is null and :latest_price is null))
              and (prev_close = :prev_close or (prev_close is null and :prev_close is null))
              and (change_rate = :change_rate or (change_rate is null and :change_rate is null))
            """
        ),
        {
            "asset_code": group.asset_code,
            "asset_name": group.asset_name,
            "asset_type": group.asset_type,
            "market": group.market,
            "latest_price": group.latest_price,
            "prev_close": group.prev_close,
            "change_rate": group.change_rate,
            "first_date": group.first_date,
        },
    )
    return result.rowcount or 0


def main() -> None:
    args = parse_args()
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    with engine.begin() as conn:
        groups = find_suspect_groups(conn, args)
        print(f"suspect_groups={len(groups)} apply={args.apply}")
        total_deleted = 0
        for group in groups:
            print(
                "asset={asset} name={name} type={type}/{market} value={price}/{prev}/{change} "
                "days={days} rows={rows} range={first}->{last}".format(
                    asset=group.asset_code,
                    name=group.asset_name,
                    type=group.asset_type,
                    market=group.market,
                    price=group.latest_price,
                    prev=group.prev_close,
                    change=group.change_rate,
                    days=group.day_count,
                    rows=group.row_count,
                    first=group.first_date,
                    last=group.last_date,
                )
            )
            if args.apply:
                total_deleted += soft_delete_group(conn, group)
        if args.apply:
            print(f"soft_deleted_rows={total_deleted}")


if __name__ == "__main__":
    main()
