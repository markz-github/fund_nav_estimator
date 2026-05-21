from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import SessionLocal
from app.modules.information.models.video import InformationVideo
from app.modules.information.services.video_source_adapters import BilibiliVideoSourceAdapter


def duration_from_raw_response(raw_response: str | None) -> int | None:
    if not raw_response:
        return None
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return BilibiliVideoSourceAdapter._duration_seconds(payload.get("length") or payload.get("duration"))


def main() -> None:
    db = SessionLocal()
    try:
        videos = db.scalars(
            select(InformationVideo).where(
                InformationVideo.content_type == "video",
                InformationVideo.duration_seconds.is_(None),
            )
        ).all()
        updated = 0
        for video in videos:
            duration_seconds = duration_from_raw_response(video.raw_response)
            if duration_seconds is None:
                continue
            video.duration_seconds = duration_seconds
            updated += 1
        db.commit()
        print(f"checked={len(videos)} updated={updated}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
