from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPROVED_APP1_DB = PROJECT_ROOT / "data" / "regulatory" / "approved" / "cap_qty_app1.csv"


@dataclass
class App1Selection:
    ready: bool
    matched: bool
    lower_quantity_ton: float | None = None
    upper_quantity_ton: float | None = None
    matched_rules: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return "".join(ch for ch in str(value).strip().lower() if ch.isalnum())


def _num(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "–", "—"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_approved_app1() -> pd.DataFrame:
    if not APPROVED_APP1_DB.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(APPROVED_APP1_DB, dtype=str, keep_default_na=False)
    except Exception:
        return pd.DataFrame()
    required = {
        "classification_system", "hazard_group", "category_no",
        "lower_quantity_ton", "upper_quantity_ton",
    }
    if df.empty or not required.issubset(df.columns):
        return pd.DataFrame()
    return df.copy()


def quantity_source_priority(*, appendix3_applies: bool, appendix2_applies: bool) -> str:
    """Return the legal quantity source without letting Appendix 1 override 2/3.

    Current quantity-regulation structure: accident-preparedness Appendix 3 has
    priority over Appendix 2; Appendix 1 is the fallback only when neither
    substance-specific table applies.
    """
    if appendix3_applies:
        return "CAP_QTY_APP3"
    if appendix2_applies:
        return "CAP_QTY_APP2"
    return "CAP_QTY_APP1"


def select_app1_quantities(classifications: Iterable[tuple[str, int]]) -> App1Selection:
    """Select the smallest applicable Appendix 1 quantities.

    ``classifications`` contains (hazard_group, category_no) pairs taken from
    verified SDS hazard classification. This function performs no AI inference
    from substance names or CAS numbers.
    """
    df = load_approved_app1()
    if df.empty:
        return App1Selection(ready=False, matched=False, blockers=["화사계 별표 1 승인 DB 필요"])

    work = df.copy()
    work["_group"] = work["hazard_group"].map(_norm)
    work["_category"] = pd.to_numeric(work["category_no"], errors="coerce")

    matched_rows: list[dict[str, Any]] = []
    for group, category_no in classifications:
        g = _norm(group)
        rows = work[work["_group"].eq(g) & work["_category"].eq(int(category_no))]
        if rows.empty:
            return App1Selection(
                ready=True,
                matched=False,
                blockers=[f"별표 1 분류 매칭 실패: {group} 구분{category_no}"],
            )
        matched_rows.append(rows.iloc[0].to_dict())

    if not matched_rows:
        return App1Selection(ready=True, matched=False)

    lower_values = [_num(row.get("lower_quantity_ton")) for row in matched_rows]
    upper_values = [_num(row.get("upper_quantity_ton")) for row in matched_rows]
    lower = min(v for v in lower_values if v is not None) if any(v is not None for v in lower_values) else None
    upper = min(v for v in upper_values if v is not None) if any(v is not None for v in upper_values) else None

    if lower is None:
        return App1Selection(
            ready=True,
            matched=False,
            matched_rules=matched_rows,
            blockers=["별표 1 적용 유해성 그룹의 하위 규정수량을 확인하지 못했습니다."],
        )

    return App1Selection(
        ready=True,
        matched=True,
        lower_quantity_ton=lower,
        upper_quantity_ton=upper,
        matched_rules=matched_rows,
    )
