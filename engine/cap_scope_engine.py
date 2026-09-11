from __future__ import annotations

"""Minimal CAP identity coverage beyond exact CAS.

This module intentionally reuses only the safe part of the earlier goindoll97
screening design: legal rows without a single direct CAS are preserved and
screened as *review candidates*.  It does not import old legal data, PubChem,
RDKit, LLM classification, or research/validation infrastructure.

Only source-reviewed files in ``data/regulatory/approved`` may be consumed.
Until CAP appendices 1 and 2 are actually extracted, reviewed and approved,
this module reports that coverage as not ready rather than pretending that an
Appendix-3 CAS miss means the material is outside CAP.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .inventory import IntakeData
from .no_cas_scope import build_no_cas_scope_index, screen_no_cas_scopes


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPROVED_DIR = PROJECT_ROOT / "data" / "regulatory" / "approved"

# Reserved output names for the dedicated current-law parsers that are built next.
APPROVED_SCOPE_FILES = {
    "CAP_QTY_APP1": APPROVED_DIR / "cap_qty_app1.csv",
    "CAP_QTY_APP2": APPROVED_DIR / "cap_qty_app2.csv",
}

# A broad-scope table must explicitly distinguish a legal direct-CAS identity
# from CAS values that merely appear inside a group/range description.
IDENTITY_COLUMNS = {
    "scope_type",
    "direct_cas",
}


@dataclass
class CAPScopeScreen:
    ready_keys: list[str] = field(default_factory=list)
    missing_keys: list[str] = field(default_factory=list)
    candidate_rows: list[dict[str, Any]] = field(default_factory=list)
    review_required: bool = False
    messages: list[str] = field(default_factory=list)

    @property
    def fully_ready(self) -> bool:
        return not self.missing_keys and len(self.ready_keys) == len(APPROVED_SCOPE_FILES)


def _load_one(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception:
        return pd.DataFrame()
    if frame.empty or not IDENTITY_COLUMNS.issubset(frame.columns):
        return pd.DataFrame()
    return frame.copy()


def load_approved_scope_tables() -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Load only current-law CAP Appendix 1/2 tables that passed admin approval."""
    loaded: dict[str, pd.DataFrame] = {}
    missing: list[str] = []
    for key, path in APPROVED_SCOPE_FILES.items():
        frame = _load_one(path)
        if frame.empty:
            missing.append(key)
        else:
            loaded[key] = frame
    return loaded, missing


def _tag_table(frame: pd.DataFrame, key: str) -> pd.DataFrame:
    out = frame.copy()
    if "source_key" not in out.columns:
        out["source_key"] = key
    else:
        out["source_key"] = out["source_key"].replace("", key)
    if "regime" not in out.columns:
        out["regime"] = key
    return out


def screen_cap_scope_candidates_from_tables(
    intake: IntakeData,
    tables: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Screen approved broad legal identity rows without auto-confirming them.

    Direct-CAS rows are deliberately excluded by ``build_no_cas_scope_index``.
    The return value therefore contains only legal ranges/groups that need a
    human or later deterministic rule to establish membership.
    """
    if not tables:
        return pd.DataFrame()

    prepared = [_tag_table(frame, key) for key, frame in tables.items() if frame is not None and not frame.empty]
    if not prepared:
        return pd.DataFrame()

    master = pd.concat(prepared, ignore_index=True, sort=False)
    scope_index = build_no_cas_scope_index(master)
    if scope_index.empty:
        return pd.DataFrame()
    return screen_no_cas_scopes(intake.chemicals, scope_index)


def assess_cap_scope(intake: IntakeData) -> CAPScopeScreen:
    tables, missing = load_approved_scope_tables()
    candidates = screen_cap_scope_candidates_from_tables(intake, tables)
    messages: list[str] = []

    if missing:
        messages.append(
            "화사계 별표 1·2의 CAS 미기재 포괄범위 검증이 아직 완성되지 않아, "
            "별표 3 CAS 미매칭만으로 비대상을 확정하지 않습니다."
        )

    if not candidates.empty:
        messages.append(
            f"CAS 하나로 특정되지 않는 화사계 규제범위 후보 {len(candidates)}건을 찾았습니다. "
            "이 후보는 이름 유사성만으로 자동확정하지 않고 범위 포함 여부를 확인합니다."
        )

    return CAPScopeScreen(
        ready_keys=sorted(tables.keys()),
        missing_keys=missing,
        candidate_rows=candidates.to_dict("records") if not candidates.empty else [],
        review_required=not candidates.empty,
        messages=messages,
    )
