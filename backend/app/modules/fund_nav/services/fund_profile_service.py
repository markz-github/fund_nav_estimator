from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.fund_nav.data_sources.akshare_source import AkshareSource
from app.modules.fund_nav.models.fund_profile import FundProfile
from app.utils.performance import timed


class FundProfileService:
    def __init__(self, db: Session, source: AkshareSource | None = None) -> None:
        self.db = db
        self.source = source or AkshareSource()

    @timed()
    def get_profile(self, fund_code: str) -> FundProfile | None:
        normalized_code = self.source._normalize_fund_code(fund_code)
        return self.db.scalar(
            select(FundProfile).where(FundProfile.fund_code == normalized_code)
        )

    @timed()
    def refresh_profiles(self) -> int:
        return self.refresh_profiles_from_source()

    @timed()
    def refresh_profiles_from_source(self) -> int:
        profiles = self.source.get_fund_profiles()
        return self.upsert_profiles(profiles, self.source.source_name)

    @timed()
    def upsert_profiles(self, profiles, source_name: str = "akshare") -> int:
        synced_at = datetime.now()
        refreshed_count = 0

        for profile in profiles:
            existing = self.db.scalar(
                select(FundProfile).where(FundProfile.fund_code == profile.fund_code)
            )
            if existing is None:
                existing = FundProfile(
                    fund_code=profile.fund_code,
                    fund_name=profile.fund_name,
                    fund_type=profile.fund_type,
                    source=source_name,
                    synced_at=synced_at,
                )
                self.db.add(existing)
            else:
                existing.fund_name = profile.fund_name
                existing.fund_type = profile.fund_type
                existing.source = source_name
                existing.synced_at = synced_at
            refreshed_count += 1

        self.db.commit()
        return refreshed_count
