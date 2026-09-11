from __future__ import annotations

"""Small admin facade for approved regulatory tables.

The active parsers are dedicated modules.  This facade keeps approval/status UI
simple while allowing the new CAP Appendix 2 table to coexist with the already
approved PSM Annex 13 and CAP Appendix 3 tables.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .regulatory_tables import (
    APPROVED_DIR,
    CANDIDATE_DIR,
    PROJECT_ROOT,
    approve_candidate as _legacy_approve_candidate,
    approved_db_status as _legacy_approved_db_status,
    candidate_preview as _legacy_candidate_preview,
)


CAP2_CANDIDATE = CANDIDATE_DIR / "cap_qty_app2_candidate.csv"
CAP2_APPROVED = APPROVED_DIR / "cap_qty_app2.csv"


def candidate_preview(key: str, max_rows: int = 80) -> pd.DataFrame:
    if key != "CAP_QTY_APP2":
        return _legacy_candidate_preview(key, max_rows=max_rows)
    if not CAP2_CANDIDATE.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(CAP2_CANDIDATE, dtype=str, keep_default_na=False).head(max_rows)
    except Exception:
        return pd.DataFrame()


def approve_candidate(key: str) -> dict[str, Any]:
    if key != "CAP_QTY_APP2":
        return _legacy_approve_candidate(key)
    if not CAP2_CANDIDATE.exists():
        return {"status": "NO_CANDIDATE", "message": "먼저 최신 별표 2 PDF에서 후보표를 추출하세요."}
    try:
        df = pd.read_csv(CAP2_CANDIDATE)
    except Exception as exc:
        return {"status": "READ_ERROR", "message": f"별표 2 후보표를 읽지 못했습니다: {type(exc).__name__}: {exc}"}
    if df.empty:
        return {"status": "EMPTY", "message": "별표 2 후보표가 비어 있어 승인할 수 없습니다."}

    APPROVED_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CAP2_CANDIDATE, CAP2_APPROVED)
    audit = APPROVED_DIR / "cap_qty_app2.approval.json"
    audit.write_text(
        json.dumps(
            {
                "approved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "key": key,
                "row_count": len(df),
                "candidate_file": str(CAP2_CANDIDATE.relative_to(PROJECT_ROOT)),
                "approved_file": str(CAP2_APPROVED.relative_to(PROJECT_ROOT)),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "status": "APPROVED",
        "message": f"{key} 후보 {len(df):,}행을 판정용 승인 DB로 저장했습니다.",
        "approved_file": str(CAP2_APPROVED.relative_to(PROJECT_ROOT)),
        "row_count": len(df),
    }


def approved_db_status() -> pd.DataFrame:
    base = _legacy_approved_db_status().copy()
    count = 0
    if CAP2_APPROVED.exists():
        try:
            count = len(pd.read_csv(CAP2_APPROVED))
        except Exception:
            count = -1
    extra = pd.DataFrame([
        {
            "key": "CAP_QTY_APP2",
            "approved": CAP2_APPROVED.exists(),
            "rows": count,
            "file": str(CAP2_APPROVED.relative_to(PROJECT_ROOT)),
        }
    ])
    if base.empty:
        return extra
    base = base[base["key"].astype(str).ne("CAP_QTY_APP2")]
    return pd.concat([base, extra], ignore_index=True)
