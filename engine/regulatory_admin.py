from __future__ import annotations

"""Small admin facade for approved regulatory tables.

Dedicated current-law parsers create review candidates. This facade only moves
review-approved candidates into the decision DB. CAP Appendix 1 (hazard-group
rules) is intentionally kept separate from Appendix 2 (CAS/broad-scope rules).
Every successful approval also attempts to archive the exact source PDF in the
human-readable local legal evidence archive.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .legal_archive import archive_approved_evidence
from .regulatory_tables import (
    APPROVED_DIR,
    CANDIDATE_DIR,
    PROJECT_ROOT,
    approve_candidate as _legacy_approve_candidate,
    approved_db_status as _legacy_approved_db_status,
    candidate_preview as _legacy_candidate_preview,
)


LOCAL_TABLES = {
    "CAP_QTY_APP1": {
        "candidate": CANDIDATE_DIR / "cap_qty_app1_candidate.csv",
        "meta": CANDIDATE_DIR / "cap_qty_app1_candidate.meta.json",
        "approved": APPROVED_DIR / "cap_qty_app1.csv",
        "audit": APPROVED_DIR / "cap_qty_app1.approval.json",
        "label": "별표 1",
    },
    "CAP_QTY_APP2": {
        "candidate": CANDIDATE_DIR / "cap_qty_app2_candidate.csv",
        "meta": CANDIDATE_DIR / "cap_qty_app2_candidate.meta.json",
        "approved": APPROVED_DIR / "cap_qty_app2.csv",
        "audit": APPROVED_DIR / "cap_qty_app2.approval.json",
        "label": "별표 2",
    },
}

LEGACY_CANDIDATE_META = {
    "PSM_ANNEX13": CANDIDATE_DIR / "psm_annex13_candidate.meta.json",
    "CAP_QTY_APP3": CANDIDATE_DIR / "cap_qty_app3_candidate.meta.json",
}


def _read_meta(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _candidate_result(meta: dict[str, Any]) -> dict[str, Any]:
    nested = meta.get("result")
    return nested if isinstance(nested, dict) else meta


def _candidate_status(meta_path: Path) -> str:
    return str(_candidate_result(_read_meta(meta_path)).get("status", ""))


def candidate_preview(key: str, max_rows: int = 80) -> pd.DataFrame:
    config = LOCAL_TABLES.get(key)
    if config is None:
        return _legacy_candidate_preview(key, max_rows=max_rows)
    path = config["candidate"]
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False).head(max_rows)
    except Exception:
        return pd.DataFrame()


def _with_archive(result: dict[str, Any], key: str) -> dict[str, Any]:
    if result.get("status") != "APPROVED":
        return result
    archive = archive_approved_evidence(key)
    result = dict(result)
    result["archive"] = archive
    if archive.get("status") == "ARCHIVED":
        result["message"] = (
            str(result.get("message", "승인 DB 저장 완료"))
            + f" 근거 PDF도 로컬 보관소에 저장했습니다: {archive.get('archived_file', '')}"
        )
    else:
        result["archive_warning"] = archive.get("message", "근거 PDF 로컬 보관에 실패했습니다.")
        result["message"] = (
            str(result.get("message", "승인 DB 저장 완료"))
            + " 다만 근거 PDF 로컬 보관은 확인이 필요합니다."
        )
    return result


def approve_candidate(key: str) -> dict[str, Any]:
    config = LOCAL_TABLES.get(key)
    if config is None:
        meta_path = LEGACY_CANDIDATE_META.get(key)
        if meta_path is not None:
            status = _candidate_status(meta_path)
            if status != "REVIEW_REQUIRED":
                return {
                    "status": "VALIDATION_NOT_PASSED",
                    "message": (
                        f"{key} 후보표의 자동검증 상태가 REVIEW_REQUIRED가 아니어서 승인할 수 없습니다. "
                        f"현재 상태: {status or '미확인'}"
                    ),
                }
        return _with_archive(_legacy_approve_candidate(key), key)

    candidate: Path = config["candidate"]
    approved: Path = config["approved"]
    audit: Path = config["audit"]
    meta_path: Path = config["meta"]
    label = str(config["label"])

    if not candidate.exists():
        return {"status": "NO_CANDIDATE", "message": f"먼저 최신 {label} PDF에서 후보표를 추출하세요."}

    meta = _read_meta(meta_path)
    candidate_status = str(_candidate_result(meta).get("status", ""))
    if candidate_status != "REVIEW_REQUIRED":
        return {
            "status": "VALIDATION_NOT_PASSED",
            "message": f"{label} 후보표의 자동검증 상태가 REVIEW_REQUIRED가 아니어서 승인할 수 없습니다. 현재 상태: {candidate_status or '미확인'}",
        }

    try:
        df = pd.read_csv(candidate)
    except Exception as exc:
        return {"status": "READ_ERROR", "message": f"{label} 후보표를 읽지 못했습니다: {type(exc).__name__}: {exc}"}
    if df.empty:
        return {"status": "EMPTY", "message": f"{label} 후보표가 비어 있어 승인할 수 없습니다."}

    result_meta = _candidate_result(meta)
    APPROVED_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate, approved)
    payload = {
        "approved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "key": key,
        "row_count": len(df),
        "candidate_file": str(candidate.relative_to(PROJECT_ROOT)),
        "approved_file": str(approved.relative_to(PROJECT_ROOT)),
        "candidate_status": candidate_status,
        "source_file": result_meta.get("source_file", meta.get("source_file", "")),
        "source_pdf_sha256": result_meta.get("source_pdf_sha256", meta.get("source_pdf_sha256", "")),
    }
    audit.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    result = {
        "status": "APPROVED",
        "message": f"{key} 후보 {len(df):,}행을 판정용 승인 DB로 저장했습니다.",
        "approved_file": str(approved.relative_to(PROJECT_ROOT)),
        "row_count": len(df),
        "approved_at_utc": payload["approved_at_utc"],
    }
    return _with_archive(result, key)


def approved_db_status() -> pd.DataFrame:
    base = _legacy_approved_db_status().copy()
    extras: list[dict[str, Any]] = []
    for key, config in LOCAL_TABLES.items():
        approved: Path = config["approved"]
        count = 0
        if approved.exists():
            try:
                count = len(pd.read_csv(approved))
            except Exception:
                count = -1
        audit = _read_meta(config["audit"])
        extras.append(
            {
                "key": key,
                "approved": approved.exists(),
                "rows": count,
                "file": str(approved.relative_to(PROJECT_ROOT)),
                "approved_at_utc": audit.get("approved_at_utc", ""),
            }
        )

    extra = pd.DataFrame(extras)
    if base.empty:
        return extra
    base = base[~base["key"].astype(str).isin(LOCAL_TABLES.keys())]
    return pd.concat([base, extra], ignore_index=True, sort=False)
