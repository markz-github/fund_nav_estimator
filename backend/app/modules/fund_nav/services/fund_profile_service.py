from __future__ import annotations

from datetime import datetime
import logging
from threading import Lock
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.fund_nav.data_sources.akshare_source import AkshareSource
from app.modules.fund_nav.models.fund_profile import FundProfile
from app.utils.performance import timed


class FundProfileService:
    _profile_sync_lock = Lock()
    _profile_sync_timeout_seconds = 60
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
        wait_started = perf_counter()
        if not self._profile_sync_lock.acquire(timeout=self._profile_sync_timeout_seconds):
            logging.getLogger("app.performance").error(
                "akshare_lock endpoint=fund_name_em status=timeout wait_ms=%.2f",
                (perf_counter() - wait_started) * 1000,
            )
            raise TimeoutError("Timed out waiting for fund profile synchronization")
        try:
            logging.getLogger("app.performance").info(
                "akshare_lock endpoint=fund_name_em status=acquired wait_ms=%.2f",
                (perf_counter() - wait_started) * 1000,
            )
            return self.refresh_profiles_from_source()
        finally:
            self._profile_sync_lock.release()

    @timed()
    def get_or_sync_profile(self, fund_code: str) -> FundProfile | None:
        profile = self.get_profile(fund_code)
        if profile is not None:
            return profile
        wait_started = perf_counter()
        if not self._profile_sync_lock.acquire(timeout=self._profile_sync_timeout_seconds):
            logging.getLogger("app.performance").error(
                "akshare_lock endpoint=fund_name_em status=timeout wait_ms=%.2f",
                (perf_counter() - wait_started) * 1000,
            )
            raise TimeoutError("Timed out waiting for fund profile synchronization")
        try:
            logging.getLogger("app.performance").info(
                "akshare_lock endpoint=fund_name_em status=acquired wait_ms=%.2f",
                (perf_counter() - wait_started) * 1000,
            )
            profile = self.get_profile(fund_code)
            if profile is not None:
                return profile
            self.refresh_profiles_from_source()
            return self.get_profile(fund_code)
        finally:
            self._profile_sync_lock.release()

    @timed()
    def refresh_profiles_from_source(self) -> int:
        profiles = self.source.get_fund_profiles()
        return self.upsert_profiles(profiles, self.source.source_name)

    @timed()
    def upsert_profiles(self, profiles, source_name: str = "akshare") -> int:
        started = perf_counter()
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
        logging.getLogger("app.performance").info(
            "database operation=upsert_fund_profiles rows=%s total_ms=%.2f",
            refreshed_count,
            (perf_counter() - started) * 1000,
        )
        return refreshed_count
