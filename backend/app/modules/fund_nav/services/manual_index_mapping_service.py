from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.manual_fund_index_mapping import ManualFundIndexMapping
from app.modules.operations.models.data_fetch_error import DataFetchError
from app.modules.fund_nav.schemas.manual_index_mapping import ManualFundIndexMappingIn


class ManualIndexMappingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_mappings(self) -> list[ManualFundIndexMapping]:
        return list(
            self.db.scalars(
                select(ManualFundIndexMapping).order_by(
                    ManualFundIndexMapping.mapping_type.asc(),
                    ManualFundIndexMapping.fund_code.asc(),
                )
            ).all()
        )

    def list_pending_mappings(self) -> list[dict]:
        rows = self.db.execute(
            select(DataFetchError, Fund)
            .outerjoin(Fund, Fund.fund_code == DataFetchError.target_code)
            .where(
                DataFetchError.source == "quality_check",
                DataFetchError.data_type == "fund_mapping",
                DataFetchError.resolved == 0,
            )
            .order_by(DataFetchError.occurred_at.desc(), DataFetchError.id.desc())
        ).all()
        pending: list[dict] = []
        for error, fund in rows:
            details = self._parse_message(error.error_message)
            pending.append(
                {
                    "id": error.id,
                    "fund_code": error.target_code,
                    "fund_name": fund.fund_name if fund else None,
                    "mapping_type": details.get("mapping_type") or "index",
                    "reason": details.get("reason"),
                    "action": details.get("action"),
                    "occurred_at": error.occurred_at,
                    "message": error.error_message,
                }
            )
        return pending

    def get_mapping(self, fund_code: str, mapping_type: str = "index") -> ManualFundIndexMapping | None:
        normalized_code = self._normalize_fund_code(fund_code)
        return self.db.scalar(
            select(ManualFundIndexMapping).where(
                ManualFundIndexMapping.fund_code == normalized_code,
                ManualFundIndexMapping.mapping_type == mapping_type,
            )
        )

    def save_mapping(self, payload: ManualFundIndexMappingIn) -> ManualFundIndexMapping:
        normalized_code = self._normalize_fund_code(payload.fund_code)
        mapping_type = payload.mapping_type
        mapping = self.get_mapping(normalized_code, mapping_type)
        fund = self.db.scalar(select(Fund).where(Fund.fund_code == normalized_code))
        if mapping is None:
            mapping = ManualFundIndexMapping(fund_code=normalized_code, mapping_type=mapping_type)
            self.db.add(mapping)

        mapping.fund_name = self._clean(payload.fund_name) or (fund.fund_name if fund else None)
        mapping.mapping_type = mapping_type
        mapping.target_code = self._clean(payload.target_code) or normalized_code
        mapping.target_name = self._clean(payload.target_name) or mapping.target_code
        mapping.target_market = self._clean(payload.target_market)
        mapping.holding_ratio = payload.holding_ratio
        mapping.holding_value = payload.holding_value
        mapping.report_period = self._clean(payload.report_period)
        mapping.benchmark_text = self._clean(payload.benchmark_text)
        mapping.remark = self._clean(payload.remark)
        self._resolve_pending_mapping_issue(normalized_code, mapping_type)
        self.db.commit()
        self.db.refresh(mapping)
        return mapping

    def delete_mapping(self, fund_code: str, mapping_type: str = "index") -> bool:
        mapping = self.get_mapping(fund_code, mapping_type)
        if mapping is None:
            return False
        self.db.delete(mapping)
        self.db.commit()
        return True

    def resolve_pending_mapping(self, issue_id: int) -> bool:
        error = self.db.get(DataFetchError, issue_id)
        if error is None:
            return False
        if error.source != "quality_check" or error.data_type != "fund_mapping" or error.resolved == 1:
            return False
        error.resolved = 1
        self.db.commit()
        return True

    def get_target_etf_holding(self, fund_code: str) -> dict | None:
        mapping = self.get_mapping(fund_code, "target_etf")
        if mapping is None:
            return None

        return {
            "fund_code": mapping.fund_code,
            "report_period": mapping.report_period or "manual",
            "asset_code": mapping.target_code,
            "asset_name": mapping.target_name,
            "asset_type": "etf",
            "market": mapping.target_market or "CN",
            "holding_ratio": mapping.holding_ratio or Decimal("1"),
            "holding_value": mapping.holding_value,
            "source": "manual:target_etf",
        }

    def _resolve_pending_mapping_issue(self, fund_code: str, mapping_type: str) -> None:
        self.db.execute(
            update(DataFetchError)
            .where(
                DataFetchError.source == "quality_check",
                DataFetchError.data_type == "fund_mapping",
                DataFetchError.target_code == fund_code,
                DataFetchError.resolved == 0,
                DataFetchError.error_message.like(f"mapping_type={mapping_type};%"),
            )
            .values(resolved=1)
        )

    @staticmethod
    def _normalize_fund_code(fund_code: str) -> str:
        value = str(fund_code).strip()
        return value.zfill(6) if value.isdigit() else value

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @staticmethod
    def _parse_message(message: str) -> dict[str, str | None]:
        details: dict[str, str | None] = {}
        for part in message.split(";"):
            key, separator, value = part.partition("=")
            if separator:
                details[key] = value if value != "None" else None
        return details
