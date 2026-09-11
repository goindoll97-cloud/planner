from __future__ import annotations

"""Company-facing SDS Section 2 -> CAP Appendix 1 screening.

This stage is used only for inventory rows that were not already claimed by
Appendix 3 or Appendix 2.  It never infers a hazard class from a CAS number or
chemical name.  The user must copy/confirm the classifications from SDS Section
2, or explicitly confirm after review that none of the Appendix-1 classes
applies.
"""

from dataclasses import dataclass, field
from typing import Any, Iterable

import pandas as pd

from .cap_app1_engine import load_approved_app1, select_app1_quantities
from .inventory import IntakeData


@dataclass(frozen=True)
class SDSApp1Option:
    key: str
    classification_system: str
    hazard_group: str
    category_no: int
    lower_quantity_ton: float | None
    upper_quantity_ton: float | None

    @property
    def label(self) -> str:
        lower = "-" if self.lower_quantity_ton is None else f"{self.lower_quantity_ton:g} ton"
        upper = "-" if self.upper_quantity_ton is None else f"{self.upper_quantity_ton:g} ton"
        return (
            f"{self.classification_system} · {self.hazard_group} · 구분 {self.category_no} "
            f"(하위 {lower} / 상위 {upper})"
        )


@dataclass
class SDSApp1Result:
    row_no: int
    product_name: str
    cas: str
    status: str
    label: str
    selected_classifications: list[str] = field(default_factory=list)
    lower_quantity_ton: float | None = None
    upper_quantity_ton: float | None = None
    max_holding_ton: float | None = None
    blockers: list[str] = field(default_factory=list)
    matched_rules: list[dict[str, Any]] = field(default_factory=list)


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


def _option_key(group: str, category_no: int) -> str:
    return f"{group}||{int(category_no)}"


def app1_sds_options() -> list[SDSApp1Option]:
    """Return the approved Appendix-1 rows as human-selectable SDS options."""
    df = load_approved_app1()
    if df.empty:
        return []

    options: list[SDSApp1Option] = []
    seen: set[str] = set()
    for _, row in df.iterrows():
        group = _clean(row.get("hazard_group"))
        system = _clean(row.get("classification_system"))
        category = _num(row.get("category_no"))
        if not group or category is None or int(category) != category:
            continue
        key = _option_key(group, int(category))
        if key in seen:
            continue
        seen.add(key)
        options.append(
            SDSApp1Option(
                key=key,
                classification_system=system,
                hazard_group=group,
                category_no=int(category),
                lower_quantity_ton=_num(row.get("lower_quantity_ton")),
                upper_quantity_ton=_num(row.get("upper_quantity_ton")),
            )
        )
    options.sort(key=lambda x: (x.classification_system, x.hazard_group, x.category_no))
    return options


def _selection_pairs(selected_keys: Iterable[str]) -> tuple[list[tuple[str, int]], list[str]]:
    option_map = {option.key: option for option in app1_sds_options()}
    pairs: list[tuple[str, int]] = []
    invalid: list[str] = []
    for key in selected_keys:
        option = option_map.get(str(key))
        if option is None:
            invalid.append(str(key))
            continue
        pairs.append((option.hazard_group, option.category_no))
    return pairs, invalid


def assess_sds_app1_row(
    intake: IntakeData,
    row_no: int,
    selected_keys: Iterable[str],
    *,
    verified_no_app1_class: bool = False,
    holding_confirmed: bool = False,
) -> SDSApp1Result:
    """Assess one Appendix-1 fallback row from verified SDS classifications.

    `verified_no_app1_class=True` means the user actually reviewed SDS Section 2
    and confirmed that none of the approved Appendix-1 hazard/category rows
    applies.  It is not a default negative inference.
    """
    idx = int(row_no) - 1
    if idx < 0 or idx >= len(intake.chemicals):
        return SDSApp1Result(
            row_no=row_no,
            product_name="",
            cas="",
            status="HOLD",
            label="화학물질 행 연결 확인 필요",
            blockers=["SDS 확인 대상 행을 회사 화학물질 목록과 연결하지 못했습니다."],
        )

    item = intake.chemicals.iloc[idx]
    product = _clean(item.get("제품명"))
    cas = _clean(item.get("CAS No."))
    selected = list(dict.fromkeys(str(v) for v in selected_keys if str(v).strip()))

    if not app1_sds_options():
        return SDSApp1Result(
            row_no=row_no,
            product_name=product,
            cas=cas,
            status="DB_NOT_READY",
            label="별표 1 승인 DB 필요",
            blockers=["화학사고예방관리계획서 별표 1 승인 DB가 준비되지 않았습니다."],
        )

    if verified_no_app1_class and selected:
        return SDSApp1Result(
            row_no=row_no,
            product_name=product,
            cas=cas,
            status="HOLD",
            label="SDS 입력이 서로 충돌합니다",
            blockers=["별표 1 해당 분류를 선택하면서 동시에 '해당 없음'을 확인할 수 없습니다."],
        )

    if verified_no_app1_class:
        return SDSApp1Result(
            row_no=row_no,
            product_name=product,
            cas=cas,
            status="NOT_APP1",
            label="SDS 확인 결과 별표 1 해당 분류 없음",
        )

    if not selected:
        return SDSApp1Result(
            row_no=row_no,
            product_name=product,
            cas=cas,
            status="HOLD",
            label="SDS 제2항 확인 필요",
            blockers=["SDS 제2항의 유해성·위험성 분류를 선택하거나, 검토 후 별표 1 해당 분류 없음임을 확인해 주세요."],
        )

    pairs, invalid = _selection_pairs(selected)
    if invalid:
        return SDSApp1Result(
            row_no=row_no,
            product_name=product,
            cas=cas,
            status="HOLD",
            label="SDS 분류 선택값 확인 필요",
            selected_classifications=selected,
            blockers=["현재 승인된 별표 1 DB와 연결되지 않는 선택값이 있습니다."],
        )

    selection = select_app1_quantities(pairs)
    if not selection.ready or not selection.matched:
        return SDSApp1Result(
            row_no=row_no,
            product_name=product,
            cas=cas,
            status="HOLD",
            label="별표 1 규정수량 매칭 확인 필요",
            selected_classifications=selected,
            blockers=list(selection.blockers),
            matched_rules=list(selection.matched_rules),
        )

    base = SDSApp1Result(
        row_no=row_no,
        product_name=product,
        cas=cas,
        status="HOLD",
        label="사업장 최대보유량 확인 필요",
        selected_classifications=selected,
        lower_quantity_ton=selection.lower_quantity_ton,
        upper_quantity_ton=selection.upper_quantity_ton,
        matched_rules=list(selection.matched_rules),
    )

    if not holding_confirmed:
        base.blockers.append(
            "별표 1 규정수량은 확인했지만 회사 Excel의 최대 동시보유량이 법정 사업장 최대보유량인지 확인되지 않았습니다."
        )
        return base

    holding = _mass_ton(item.get("최대 동시보유량(알면 입력)"), item.get("수량 단위"))
    if holding is None:
        base.blockers.append("최대 동시보유량이 없거나 kg/ton 질량단위가 아니어서 규정수량과 비교할 수 없습니다.")
        return base

    base.max_holding_ton = round(holding, 8)
    lower = selection.lower_quantity_ton
    upper = selection.upper_quantity_ton
    if upper is not None and holding >= upper:
        base.status = "UPPER_CANDIDATE"
        base.label = "별표 1 상위 규정수량 이상"
    elif lower is not None and holding >= lower:
        base.status = "LOWER_CANDIDATE"
        base.label = "별표 1 하위 규정수량 이상·상위 미만"
    else:
        base.status = "BELOW_LOWER"
        base.label = "별표 1 하위 규정수량 미만"
    return base
