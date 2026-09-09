from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGULATORY_DIR = PROJECT_ROOT / "data" / "regulatory"
CAP_APPROVED = REGULATORY_DIR / "cap_quantity_APPROVED.csv"
PSM_APPROVED = REGULATORY_DIR / "psm_appendix13_APPROVED.csv"

CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")


def normalize_cas(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().replace(" ", "")
    return text if CAS_RE.fullmatch(text) else ""


def _num(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_cap_rules(path: Path = CAP_APPROVED) -> pd.DataFrame:
    """Load human-approved CAP quantity rules only.

    Expected columns:
      cas, substance_name, lower_ton, upper_ton, lowest_ton(optional),
      legal_basis, source_effective_date, source_hash
    """
    cols = [
        "cas", "substance_name", "lower_ton", "upper_ton", "lowest_ton",
        "legal_basis", "source_effective_date", "source_hash",
    ]
    if not path.exists():
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    for col in cols:
        if col not in df.columns:
            df[col] = ""
    df["cas"] = df["cas"].map(normalize_cas)
    for col in ["lower_ton", "upper_ton", "lowest_ton"]:
        df[col] = df[col].map(_num)
    return df[cols].copy()


def load_psm_rules(path: Path = PSM_APPROVED) -> pd.DataFrame:
    """Load human-approved PSM Appendix 13 rules only.

    Exact-CAS rows can be automatically compared. Category rows without CAS
    (e.g. flammable gas/liquid) remain separate and require follow-up logic.

    Expected columns:
      item_no, cas, substance_name, manufacture_use_kg, storage_kg,
      threshold_note, legal_basis, source_effective_date, source_hash
    """
    cols = [
        "item_no", "cas", "substance_name", "manufacture_use_kg", "storage_kg",
        "threshold_note", "legal_basis", "source_effective_date", "source_hash",
    ]
    if not path.exists():
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    for col in cols:
        if col not in df.columns:
            df[col] = ""
    df["cas"] = df["cas"].map(normalize_cas)
    for col in ["manufacture_use_kg", "storage_kg"]:
        df[col] = df[col].map(_num)
    return df[cols].copy()


def regulatory_db_status() -> list[dict[str, object]]:
    cap = load_cap_rules()
    psm = load_psm_rules()
    return [
        {
            "dataset": "화사계 규정수량",
            "path": str(CAP_APPROVED.relative_to(PROJECT_ROOT)),
            "exists": CAP_APPROVED.exists(),
            "rows": len(cap),
            "exact_cas_rows": int(cap["cas"].astype(bool).sum()) if not cap.empty else 0,
            "ready": bool(CAP_APPROVED.exists() and not cap.empty),
        },
        {
            "dataset": "PSM 별표 13",
            "path": str(PSM_APPROVED.relative_to(PROJECT_ROOT)),
            "exists": PSM_APPROVED.exists(),
            "rows": len(psm),
            "exact_cas_rows": int(psm["cas"].astype(bool).sum()) if not psm.empty else 0,
            "ready": bool(PSM_APPROVED.exists() and not psm.empty),
        },
    ]


def approved_rule_hashes() -> dict[str, set[str]]:
    """Hashes recorded in approved rule rows; used to prove DB/PDF alignment."""
    out: dict[str, set[str]] = {"화사계": set(), "PSM": set()}
    for regime, df in (("화사계", load_cap_rules()), ("PSM", load_psm_rules())):
        if "source_hash" in df.columns:
            out[regime] = {str(v).strip() for v in df["source_hash"] if str(v).strip()}
    return out
