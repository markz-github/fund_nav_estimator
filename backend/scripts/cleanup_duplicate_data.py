from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sqlalchemy import func, select


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.models  # noqa: F401
from app.database import SessionLocal
from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.fund_estimate import FundEstimate
from app.modules.fund_nav.models.fund_holding import FundHolding
from app.modules.fund_nav.models.fund_index_mapping import FundIndexMapping
from app.modules.fund_nav.models.fund_nav import FundNav
from app.modules.fund_nav.models.fund_profile import FundProfile
from app.modules.fund_nav.models.market_quote import MarketQuote
from app.modules.information.models.information_setting import InformationSetting
from app.modules.information.models.summary_document import InformationSummaryDocumentItem
from app.modules.information.models.summary_document import InformationSummaryDocument
from app.modules.information.models.video import InformationVideo
from app.modules.information.models.video_note import InformationVideoNote
from app.modules.information.models.video_source import InformationVideoSource


def duplicate_groups(db, model, columns):
    statement = (
        select(*columns, func.count(model.id).label("count"))
        .group_by(*columns)
        .having(func.count(model.id) > 1)
    )
    return db.execute(statement).all()


def cleanup_duplicate_notes(db, apply: bool) -> tuple[int, int]:
    rows = db.execute(
        select(
            InformationVideoNote.video_id,
            InformationVideoNote.provider,
            InformationVideoNote.status,
            InformationVideoNote.note_text,
            func.count(InformationVideoNote.id).label("count"),
        )
        .where(InformationVideoNote.note_text.is_not(None))
        .group_by(
            InformationVideoNote.video_id,
            InformationVideoNote.provider,
            InformationVideoNote.status,
            InformationVideoNote.note_text,
        )
        .having(func.count(InformationVideoNote.id) > 1)
    ).all()

    duplicate_groups_count = 0
    deletable_count = 0
    for video_id, provider, status, note_text, _count in rows:
        notes = list(
            db.scalars(
                select(InformationVideoNote)
                .where(
                    InformationVideoNote.video_id == video_id,
                    InformationVideoNote.provider == provider,
                    InformationVideoNote.status == status,
                    InformationVideoNote.note_text == note_text,
                )
                .order_by(InformationVideoNote.id.desc())
            ).all()
        )
        referenced_note_ids = set(
            db.scalars(
                select(InformationSummaryDocumentItem.note_id).where(
                    InformationSummaryDocumentItem.note_id.in_([note.id for note in notes])
                )
            ).all()
        )
        kept = None
        for note in notes:
            if note.id in referenced_note_ids:
                kept = note
                break
        if kept is None:
            kept = notes[0]

        deletable = [note for note in notes if note.id != kept.id and note.id not in referenced_note_ids]
        if not deletable:
            continue
        duplicate_groups_count += 1
        deletable_count += len(deletable)
        if apply:
            for note in deletable:
                db.delete(note)

    if apply:
        db.commit()
    else:
        db.rollback()
    return duplicate_groups_count, deletable_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Find and clean safe duplicate database rows.")
    parser.add_argument("--apply", action="store_true", help="Delete safe duplicate rows. Omit for dry-run.")
    args = parser.parse_args()

    with SessionLocal() as db:
        reported_duplicates = {
            "funds": duplicate_groups(db, Fund, [Fund.fund_code]),
            "fund_navs": duplicate_groups(db, FundNav, [FundNav.fund_code, FundNav.nav_date]),
            "fund_holdings": duplicate_groups(
                db,
                FundHolding,
                [FundHolding.fund_code, FundHolding.report_period, FundHolding.asset_code],
            ),
            "fund_estimates": duplicate_groups(db, FundEstimate, [FundEstimate.fund_code, FundEstimate.estimate_time]),
            "market_quotes": duplicate_groups(db, MarketQuote, [MarketQuote.asset_code, MarketQuote.quote_time]),
            "fund_profiles": duplicate_groups(db, FundProfile, [FundProfile.fund_code]),
            "fund_index_mappings": duplicate_groups(db, FundIndexMapping, [FundIndexMapping.fund_code]),
            "information_settings": duplicate_groups(db, InformationSetting, [InformationSetting.setting_key]),
            "information_video_sources": duplicate_groups(
                db,
                InformationVideoSource,
                [InformationVideoSource.platform, InformationVideoSource.external_source_id],
            ),
            "information_videos": duplicate_groups(
                db,
                InformationVideo,
                [InformationVideo.platform, InformationVideo.external_video_id],
            ),
            "information_summary_documents": duplicate_groups(
                db,
                InformationSummaryDocument,
                [InformationSummaryDocument.platform, InformationSummaryDocument.summary_date],
            ),
            "information_summary_document_items": duplicate_groups(
                db,
                InformationSummaryDocumentItem,
                [InformationSummaryDocumentItem.document_id, InformationSummaryDocumentItem.note_id],
            ),
        }
        note_groups, note_rows = cleanup_duplicate_notes(db, apply=args.apply)

    mode = "apply" if args.apply else "dry-run"
    print(f"mode={mode}")
    for table_name, rows in reported_duplicates.items():
        print(f"duplicate_{table_name}_groups={len(rows)}")
    print(f"safe_duplicate_note_groups={note_groups}")
    print(f"safe_duplicate_note_rows={'deleted' if args.apply else 'deletable'}={note_rows}")
    if any(reported_duplicates.values()):
        print("reported duplicate groups were not auto-merged; only safe duplicate notes are auto-cleaned with --apply.")


if __name__ == "__main__":
    main()
