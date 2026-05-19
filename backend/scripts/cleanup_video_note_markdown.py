from __future__ import annotations

from pathlib import Path
import sys

from sqlalchemy import select


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import SessionLocal
from app.modules.information.models.video import InformationVideo  # noqa: F401
from app.modules.information.models.video_note import InformationVideoNote
from app.modules.information.services.bilinote_client import normalize_markdown_text


def main() -> None:
    updated = 0
    checked = 0
    with SessionLocal() as db:
        notes = db.scalars(
            select(InformationVideoNote).where(InformationVideoNote.note_text.is_not(None))
        ).all()
        for note in notes:
            checked += 1
            normalized = normalize_markdown_text(note.note_text or "")
            if normalized != note.note_text:
                note.note_text = normalized
                updated += 1
        db.commit()
    print(f"checked={checked};updated={updated}")


if __name__ == "__main__":
    main()
