from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import SessionLocal
from app.modules.fund_nav.services.fund_profile_service import FundProfileService


def main() -> None:
    with SessionLocal() as db:
        result = FundProfileService(db).initialize_fund_categories()
    print(f"Fund categories initialized: profiles={result['profiles']};funds={result['funds']}")


if __name__ == "__main__":
    main()
