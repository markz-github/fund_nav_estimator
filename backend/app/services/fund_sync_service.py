from __future__ import annotations

from datetime import datetime

from app.database import SessionLocal
from app.services.estimate_service import EstimateService
from app.services.fund_index_mapping_service import FundIndexMappingService
from app.services.fund_profile_service import FundProfileService
from app.services.fund_service import FundService
from app.services.holding_service import HoldingService
from app.services.market_service import MarketService
from app.services.operation_log_service import log_fetch_error, log_task
from app.utils.performance import timed


@timed()
def sync_new_fund_data(fund_code: str) -> None:
    started_at = datetime.now()
    db = SessionLocal()
    try:
        fund_service = FundService(db)
        if FundProfileService(db).get_profile(fund_code) is None:
            try:
                FundProfileService(db).refresh_profiles()
            except Exception:
                db.rollback()
        profile = fund_service.refresh_profile(fund_code)
        index_mapping = FundIndexMappingService(db).refresh_mapping(fund_code)
        nav = fund_service.refresh_nav(fund_code)
        holdings = HoldingService(db).refresh_holdings(fund_code)
        quotes = MarketService(db).refresh_quotes_for_holdings([fund_code]) if holdings else []
        estimate_result = EstimateService(db).run_estimates([fund_code])
        status = "success"
        if profile is None or nav is None or not holdings or estimate_result["skipped_count"]:
            status = "partial"
        log_task(
            db,
            "新增基金后同步数据",
            "sync_new_fund_data",
            status,
            started_at,
            (
                f"profile={profile is not None};nav={nav is not None};"
                f"index_mapping={index_mapping is not None};"
                f"holdings={len(holdings)};quotes={len(quotes)};"
                f"estimated={estimate_result['estimated_count']};"
                f"skipped={estimate_result['skipped_count']};"
                f"details={estimate_result['skipped']}"
            ),
        )
    except Exception as exc:
        db.rollback()
        log_fetch_error(db, "internal", "sync_new_fund_data", fund_code, repr(exc))
        log_task(db, "新增基金后同步数据", "sync_new_fund_data", "failed", started_at, repr(exc))
    finally:
        db.close()
