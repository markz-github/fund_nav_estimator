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
from app.modules.information.models.summary_document import InformationSummaryDocumentItem
from app.modules.information.models.video_note import InformationVideoNote


def cleanup_duplicate_video_notes(apply: bool) -> dict[str, int]:
    stats = {
        "duplicate_groups": 0,
        "active_duplicate_notes": 0,
        "soft_deleted_notes": 0,
        "referenced_notes_skipped": 0,
    }
    with SessionLocal() as db:
        groups = db.execute(
            select(
                InformationVideoNote.video_id,
                InformationVideoNote.provider,
                func.count(InformationVideoNote.id).label("count"),
            )
            .group_by(InformationVideoNote.video_id, InformationVideoNote.provider)
            .having(func.count(InformationVideoNote.id) > 1)
        ).all()
        stats["duplicate_groups"] = len(groups)

        for video_id, provider, count in groups:
            stats["active_duplicate_notes"] += int(count) - 1
            notes = list(
                db.scalars(
                    select(InformationVideoNote)
                    .where(
                        InformationVideoNote.video_id == video_id,
                        InformationVideoNote.provider == provider,
                    )
                    .order_by(
                        InformationVideoNote.updated_at.desc(),
                        InformationVideoNote.created_at.desc(),
                        InformationVideoNote.id.desc(),
                    )
                ).all()
            )
            if not notes:
                continue
            keep = notes[0]
            old_notes = notes[1:]
            old_note_ids = [note.id for note in old_notes]
            referenced_note_ids = set(
                db.scalars(
                    select(InformationSummaryDocumentItem.note_id).where(
                        InformationSummaryDocumentItem.note_id.in_(old_note_ids)
                    )
                ).all()
            )
            for note in old_notes:
                if note.id in referenced_note_ids:
                    stats["referenced_notes_skipped"] += 1
                    continue
                stats["soft_deleted_notes"] += 1
                if apply:
                    db.delete(note)

            # Keep the latest note active even if it had been loaded through an unusual state.
            if apply:
                keep.is_deleted = 0

        if apply:
            db.commit()
        else:
            db.rollback()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean duplicate information_video_notes according to the last-result note policy."
    )
    parser.add_argument("--apply", action="store_true", help="Soft-delete old unreferenced duplicate notes.")
    args = parser.parse_args()

    stats = cleanup_duplicate_video_notes(apply=args.apply)
    print(f"mode={'apply' if args.apply else 'dry-run'}")
    for key, value in stats.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
