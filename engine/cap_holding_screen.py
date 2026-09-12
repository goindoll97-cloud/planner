from __future__ import annotations

"""Prepare direct legal rules for the Appendix 4 facility-input stage.

This screen does not use the provisional 'maximum concurrent holding' value from
the first company workbook.  It identifies direct Appendix 3 then Appendix 2
rules from CAS + concentration, preserving the legal priority so the second
stage can request facility facts only for materials that actually need them.

When the company workbook already contains a decisive condition (for example,
whether a material is liquid at ambient temperature/pressure), that information
is consumed here so the Streamlit page does not ask for it again.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import re

import pandas as pd

from .inventory import IntakeData


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPROVED_DIR = PROJECT_ROOT / "data" / "regulatory" / "approved"
APP3 = APPROVED_DIR / "cap_qty_app3.csv"
APP2 = APPROVED_DIR / "cap_qty_app2.csv"
CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")

AMBIENT_LIQUID_FIELDS = (
    "상온·상압 액체 여부(해당 시)",
    "상온·상압 액체 여부",
    "상온상압 액체 여부",
)


@dataclass
class FacilityStageScreen:
    legal_hits: list[dict[str, Any]] = field(default_factory=list)
    row_numbers: list[int] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    ready: bool = False


def _clean(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def _num(value: Any) -> float | None:
    text = _clean(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _split_cas(value: Any) -> set[str]:
    return {
        token.strip()
        for token in re.split(r"[|;,]", _clean(value))
        if CAS_RE.fullmatch(token.strip())
    }


def _truthy(value: Any, default: bool = True) -> bool:
    text = _clean(value).lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "y", "예", "active"}


def _yes_no_unknown(value: Any) -> str:
    text = _clean(value).lower().replace(" ", "")
    if text in {"1", "true", "yes", "y", "예", "해당", "액체"}:
        return "YES"
    if text in {"0", "false", "no", "n", "아니오", "아님", "비해당", "기체"}:
        return "NO"
    return "UNKNOWN"


def _first_field(item: pd.Series, names: tuple[str, ...]) -> Any:
    for name in names:
        if name in item.index and _clean(item.get(name)):
            return item.get(name)
    return None


def _load(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception:
        return pd.DataFrame()


def _app3_hits_for_row(row_no: int, item: pd.Series, app3: pd.DataFrame) -> tuple[list[dict[str, Any]], list[str], bool]:
    cas = _clean(item.get("CAS No."))
    if not CAS_RE.fullmatch(cas) or app3.empty:
        return [], [], False
    matched = app3[app3["cas_list"].map(lambda v: cas in _split_cas(v))].copy()
    if matched.empty:
        return [], [], False

    pct = _num(item.get("함량(%)"))
    product = _clean(item.get("제품명")) or cas
    base = matched[matched.get("variant_type", "BASE").astype(str).eq("BASE")] if "variant_type" in matched.columns else matched
    if base.empty:
        return [], [f"{product}: 별표 3 기본행을 확인하지 못했습니다."], True
    base_row = base.iloc[0]
    threshold = _num(base_row.get("content_threshold_pct"))
    if threshold is not None:
        if pct is None:
            return [], [f"{product}: 별표 3 적용을 위한 함량(%) 확인이 필요합니다."], True
        if pct < threshold:
            return [], [], False

    item_no = int(float(base_row.get("item_no")))
    chosen = base_row
    variants = matched[~matched.index.isin(base.index)]
    if item_no == 46 and pct is not None and pct > 70:
        special = variants[variants["variant_type"].astype(str).eq("CONCENTRATION_GT_70")] if "variant_type" in variants.columns else pd.DataFrame()
        if not special.empty:
            chosen = special.iloc[0]
    elif item_no in {42, 43, 44} and "variant_type" in variants.columns and variants["variant_type"].astype(str).eq("LIQUID_AT_AMBIENT").any():
        ambient_answer = _yes_no_unknown(_first_field(item, AMBIENT_LIQUID_FIELDS))
        if ambient_answer == "YES":
            special = variants[variants["variant_type"].astype(str).eq("LIQUID_AT_AMBIENT")]
            if special.empty:
                return [], [f"{product}: 별표 3 제{item_no}호의 상온·상압 액체 규정행을 확인하지 못했습니다."], True
            chosen = special.iloc[0]
        elif ambient_answer == "NO":
            chosen = base_row
        else:
            return [], [
                f"{product}: 별표 3 제{item_no}호 적용을 위해 '상온·상압 액체 여부'가 필요합니다. "
                "회사 입력파일의 '상온·상압 액체 여부(해당 시)' 열에 예/아니오를 미리 입력할 수 있습니다."
            ], True

    hit = {
        "source_key": "CAP_QTY_APP3",
        "row_no": row_no,
        "product_name": _clean(item.get("제품명")),
        "cas": cas,
        "item_no": str(item_no),
        "legal_substance": _clean(chosen.get("substance_name")),
        "variant_type": _clean(chosen.get("variant_type")) or "BASE",
        "content_threshold_pct": threshold,
        "lowest_quantity_ton": _num(chosen.get("lowest_quantity_ton")),
        "lower_quantity_ton": _num(chosen.get("lower_quantity_ton")),
        "upper_quantity_ton": _num(chosen.get("upper_quantity_ton")),
    }
    return [hit], [], True


def _app2_hits_for_row(row_no: int, item: pd.Series, app2: pd.DataFrame) -> tuple[list[dict[str, Any]], list[str], bool]:
    cas = _clean(item.get("CAS No."))
    if not CAS_RE.fullmatch(cas) or app2.empty or "direct_cas" not in app2.columns:
        return [], [], False
    table = app2.copy()
    if "active" in table.columns:
        table = table[table["active"].map(lambda v: _truthy(v, default=True))]
    matched = table[table["direct_cas"].map(lambda v: cas in _split_cas(v))].copy()
    if matched.empty:
        return [], [], False

    product = _clean(item.get("제품명")) or cas
    if "hazard_category" in matched.columns and matched["hazard_category"].astype(str).str.strip().eq("용액").any():
        return [], [f"{product}: 별표 2 동일 CAS의 '용액' 특수조건 해당 여부를 먼저 확인해야 합니다."], True

    pct = _num(item.get("함량(%)"))
    hits: list[dict[str, Any]] = []
    blockers: list[str] = []
    for _, legal in matched.iterrows():
        threshold = _num(legal.get("content_threshold_pct"))
        if threshold is not None:
            if pct is None:
                blockers.append(f"{product}: 별표 2 적용을 위한 함량(%) 확인이 필요합니다.")
                continue
            if pct < threshold:
                continue
        hits.append(
            {
                "source_key": "CAP_QTY_APP2",
                "row_no": row_no,
                "product_name": _clean(item.get("제품명")),
                "cas": cas,
                "item_no": _clean(legal.get("item_no")),
                "designation_id": _clean(legal.get("designation_id")),
                "legal_substance": _clean(legal.get("substance_name")),
                "hazard_category": _clean(legal.get("hazard_category")),
                "content_threshold_pct": threshold,
                "lowest_quantity_ton": _num(legal.get("lowest_quantity_ton")),
                "lower_quantity_ton": _num(legal.get("lower_quantity_ton")),
                "upper_quantity_ton": _num(legal.get("upper_quantity_ton")),
            }
        )
    return hits, blockers, bool(hits or blockers)


def screen_facility_stage(intake: IntakeData) -> FacilityStageScreen:
    app3 = _load(APP3)
    app2 = _load(APP2)
    missing: list[str] = []
    if app3.empty:
        missing.append("별표 3 승인 DB")
    if app2.empty:
        missing.append("별표 2 승인 DB")
    if missing:
        return FacilityStageScreen(
            ready=False,
            blockers=[" / ".join(missing) + "가 필요합니다."],
            messages=["별표 4 시설정보 단계는 승인된 별표 3→별표 2 직접 규칙을 기준으로 시작합니다."],
        )

    legal_hits: list[dict[str, Any]] = []
    blockers: list[str] = []
    row_numbers: set[int] = set()

    for idx, item in intake.chemicals.iterrows():
        row_no = idx + 1
        app3_hits, app3_blockers, app3_claimed = _app3_hits_for_row(row_no, item, app3)
        if app3_claimed:
            row_numbers.add(row_no)
            legal_hits.extend(app3_hits)
            blockers.extend(app3_blockers)
            continue

        app2_hits, app2_blockers, app2_claimed = _app2_hits_for_row(row_no, item, app2)
        if app2_claimed:
            row_numbers.add(row_no)
            legal_hits.extend(app2_hits)
            blockers.extend(app2_blockers)

    return FacilityStageScreen(
        legal_hits=legal_hits,
        row_numbers=sorted(row_numbers),
        blockers=list(dict.fromkeys(blockers)),
        messages=[
            f"별표 3→별표 2 우선순위로 시설정보가 필요한 직접 규칙 대상 물질 {len(row_numbers)}개를 확인했습니다."
            if row_numbers
            else "현재 별표 2·3 직접 규칙에서 시설정보 단계로 넘길 물질이 없습니다. 별표 1 또는 포괄범위 검토가 먼저일 수 있습니다."
        ],
        ready=True,
    )
