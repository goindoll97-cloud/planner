from __future__ import annotations

"""Fast-path CAP maximum-holding comparison.

Priority:
1. If the first company workbook already contains ``03_시설별최대보유량``, use
   those facility facts to calculate Appendix-4 maximum holding directly.
2. Otherwise, use the company-declared ``최대 동시보유량`` only when the UI has
   confirmed that it was already calculated on an Appendix-4 basis.

This keeps the one-upload workflow while preserving the detailed facility
calculation as the legally safer path whenever facility data is available.
"""

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .inventory import IntakeData


@dataclass
class QuickHoldingResult:
    status: str
    label: str
    comparison_rows: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _num(value: Any) -> float | None:
    text = _clean(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _mass_ton(value: Any, unit: Any) -> float | None:
    amount = _num(value)
    if amount is None or amount < 0:
        return None
    norm = _clean(unit).lower().replace(" ", "")
    if norm == "kg":
        return amount / 1000.0
    if norm in {"ton", "t", "톤"}:
        return amount
    return None


def _band(amount: float, lowest: float | None, lower: float | None, upper: float | None) -> str:
    if upper is not None and amount >= upper:
        return "상위 규정수량 이상"
    if lower is not None and amount >= lower:
        return "하위 이상·상위 미만"
    if lowest is not None and amount >= lowest:
        return "최하위 이상·하위 미만"
    return "하위 규정수량 미만"


def declared_holding_preview(intake: IntakeData, legal_hits: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for hit in legal_hits:
        row_no = int(hit.get("row_no") or 0)
        if row_no <= 0 or row_no in seen or row_no > len(intake.chemicals):
            continue
        seen.add(row_no)
        item = intake.chemicals.iloc[row_no - 1]
        rows.append(
            {
                "목록행번호": row_no,
                "제품명": _clean(item.get("제품명")),
                "CAS No.": _clean(item.get("CAS No.")),
                "입력 최대동시보유량": item.get("최대 동시보유량(알면 입력)"),
                "단위": _clean(item.get("수량 단위")),
            }
        )
    return pd.DataFrame(rows)


def _from_first_upload_facilities(
    intake: IntakeData,
    legal_hits: list[dict[str, Any]],
) -> QuickHoldingResult | None:
    facilities = getattr(intake, "facilities", None)
    if facilities is None or facilities.empty:
        return None

    # Import lazily to keep the inventory/cap-holding module dependency simple.
    from .cap_holding import assess_cap_holding

    required_rows = sorted(
        {
            int(hit.get("row_no") or 0)
            for hit in legal_hits
            if int(hit.get("row_no") or 0) > 0
        }
    )
    detailed = assess_cap_holding(
        intake=intake,
        facilities=facilities,
        legal_hits=legal_hits,
        required_row_numbers=required_rows,
    )

    comparisons: list[dict[str, Any]] = []
    for row in detailed.comparison_rows:
        copy = dict(row)
        if "confirmed_max_holding_ton" not in copy:
            copy["confirmed_max_holding_ton"] = copy.get("calculated_max_holding_ton")
        copy["basis"] = "최초 회사 입력파일의 03_시설별최대보유량을 별표 4 방식으로 계산"
        comparisons.append(copy)

    return QuickHoldingResult(
        status=detailed.status,
        label=detailed.label,
        comparison_rows=comparisons,
        blockers=list(detailed.blockers),
    )


def compare_confirmed_declared_holding(
    intake: IntakeData,
    legal_hits: list[dict[str, Any]],
) -> QuickHoldingResult:
    facility_result = _from_first_upload_facilities(intake, legal_hits)
    if facility_result is not None:
        return facility_result

    comparisons: list[dict[str, Any]] = []
    blockers: list[str] = []

    for hit in legal_hits:
        row_no = int(hit.get("row_no") or 0)
        if row_no <= 0 or row_no > len(intake.chemicals):
            blockers.append("법적 규칙과 회사 입력행 연결을 확인하지 못했습니다.")
            continue
        item = intake.chemicals.iloc[row_no - 1]
        amount = _mass_ton(item.get("최대 동시보유량(알면 입력)"), item.get("수량 단위"))
        if amount is None:
            blockers.append(
                f"{row_no}행({_clean(item.get('제품명')) or _clean(item.get('CAS No.'))}): "
                "최대 동시보유량이 없거나 kg/ton 질량단위가 아닙니다."
            )
            continue

        lowest = _num(hit.get("lowest_quantity_ton"))
        lower = _num(hit.get("lower_quantity_ton"))
        upper = _num(hit.get("upper_quantity_ton"))
        if lower is None:
            blockers.append(f"{hit.get('source_key', '')} 제{hit.get('item_no', '-')}호 하위 규정수량 확인 필요")
            continue

        comparisons.append(
            {
                "source_key": _clean(hit.get("source_key")),
                "row_no": row_no,
                "product_name": _clean(item.get("제품명")),
                "cas": _clean(item.get("CAS No.")),
                "item_no": _clean(hit.get("item_no")),
                "legal_substance": _clean(hit.get("legal_substance")),
                "hazard_category": _clean(hit.get("hazard_category")),
                "confirmed_max_holding_ton": round(amount, 8),
                "lowest_quantity_ton": lowest,
                "lower_quantity_ton": lower,
                "upper_quantity_ton": upper,
                "quantity_band": _band(amount, lowest, lower, upper),
                "basis": "회사 확인: 1차 입력 최대 동시보유량이 별표 4 기준으로 산정된 값",
            }
        )

    if blockers:
        return QuickHoldingResult(
            status="HOLD",
            label="별표 4 상세 시설정보 확인 필요",
            comparison_rows=comparisons,
            blockers=list(dict.fromkeys(blockers)),
        )

    if any(row["quantity_band"] == "상위 규정수량 이상" for row in comparisons):
        return QuickHoldingResult(
            status="UPPER_CANDIDATE",
            label="화사계 상위기준 후보",
            comparison_rows=comparisons,
        )
    if any(row["quantity_band"] == "하위 이상·상위 미만" for row in comparisons):
        return QuickHoldingResult(
            status="LOWER_CANDIDATE",
            label="화사계 하위기준 후보",
            comparison_rows=comparisons,
        )
    if comparisons:
        return QuickHoldingResult(
            status="BELOW_LOWER",
            label="확인된 별표 2·3 직접대상은 하위 규정수량 미만",
            comparison_rows=comparisons,
        )
    return QuickHoldingResult(status="NO_DIRECT_HIT", label="별표 2·3 직접대상 없음")
