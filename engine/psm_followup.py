from __future__ import annotations

"""Closed-loop follow-up engine for PSM screening.

``psm_engine.assess_psm`` performs the first-pass legal matching.  This module
resolves the facts that cannot be inferred safely from CAS/concentration alone:
property-defined Annex 13 items 1/2, special component conditions for items
23/42, and note 8 quantities that must be excluded from R.

No legal fact is guessed.  Missing answers remain blockers.
"""

from dataclasses import dataclass, field, replace
from typing import Any

from .inventory import IntakeData
from .psm_engine import (
    CAS_RE,
    PSMRatioLine,
    PSMAssessment,
    _aggregate_ratio_lines,
    _clean,
    _kg,
    _load_db,
    _number,
    assess_psm,
    calculate_r_value,
)


SPECIAL_VALUE_RULES: dict[int, tuple[str, str]] = {
    23: ("발연황산의 삼산화황(SO₃) 중량%", "65% 이상 80% 미만"),
    42: ("니트로셀룰로오스의 질소 함유량%", "12.6% 이상"),
}


@dataclass(frozen=True)
class PSMPropertyAnswer:
    applicable: bool | None = None
    manufacture_handling_kg: float | None = None
    storage_kg: float | None = None


@dataclass(frozen=True)
class PSMNote8Adjustment:
    manufacture_handling_kg: float = 0.0
    storage_kg: float = 0.0


@dataclass
class PSMFollowupFacts:
    property_answers: dict[int, PSMPropertyAnswer] = field(default_factory=dict)
    special_values_pct: dict[int, float | None] = field(default_factory=dict)
    note8_answer: str = ""  # "", NO, YES, UNKNOWN
    note8_exclusions: dict[int, PSMNote8Adjustment] = field(default_factory=dict)


@dataclass(frozen=True)
class PSMFollowupRequirements:
    property_items: tuple[int, ...] = ()
    special_items: tuple[int, ...] = ()


@dataclass
class PSMFollowupResult:
    status: str
    label: str
    base: PSMAssessment
    ratio_lines: list[PSMRatioLine] = field(default_factory=list)
    r_before_note8: float = 0.0
    r_value: float = 0.0
    r_complete: bool = False
    industry_trigger: bool = False
    quantity_trigger: bool = False
    trigger_channels: list[str] = field(default_factory=list)
    note8_required: bool = False
    blockers: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


def _item_rows(db, item_no: int):
    if db.empty or "item_no" not in db.columns:
        return db.iloc[0:0]
    values = db["item_no"].apply(_number)
    return db[values.eq(float(item_no))]


def _cas_list_contains(value: Any, cas: str) -> bool:
    return cas in {token.strip() for token in str(value or "").split("|") if token.strip()}


def _special_condition_applies(item_no: int, value_pct: float | None) -> bool | None:
    if value_pct is None:
        return None
    try:
        value = float(value_pct)
    except (TypeError, ValueError):
        return None
    if value < 0 or value > 100:
        return None
    if item_no == 23:
        return 65.0 <= value < 80.0
    if item_no == 42:
        return value >= 12.6
    return None


def detect_followup_requirements(
    intake: IntakeData,
    base: PSMAssessment | None = None,
) -> PSMFollowupRequirements:
    """Return only follow-ups that can change the Stage-1 PSM decision."""
    base = base or assess_psm(intake)
    db = _load_db()
    if db.empty:
        return PSMFollowupRequirements()

    ordinary_industry_trigger = bool(base.industry_match and base.industry_code != "20202")
    property_items: list[int] = []
    if not ordinary_industry_trigger:
        for item_no in (1, 2):
            rows = _item_rows(db, item_no)
            if not rows.empty and "match_type" in rows.columns and rows["match_type"].astype(str).eq("PROPERTY").any():
                property_items.append(item_no)

    special_items: set[int] = set()
    if not ordinary_industry_trigger:
        for _, company_row in intake.chemicals.iterrows():
            cas = _clean(company_row.get("CAS No."))
            if not CAS_RE.fullmatch(cas):
                continue
            for item_no in SPECIAL_VALUE_RULES:
                rows = _item_rows(db, item_no)
                if any(_cas_list_contains(row.get("cas_list"), cas) for _, row in rows.iterrows()):
                    special_items.add(item_no)

    return PSMFollowupRequirements(
        property_items=tuple(sorted(property_items)),
        special_items=tuple(sorted(special_items)),
    )


def _property_lines(db, facts: PSMFollowupFacts, required_items: tuple[int, ...]) -> tuple[list[PSMRatioLine], list[str]]:
    contributions: list[dict[str, Any]] = []
    blockers: list[str] = []
    for item_no in required_items:
        answer = facts.property_answers.get(item_no, PSMPropertyAnswer())
        label = "인화성 가스" if item_no == 1 else "인화성 액체"
        if answer.applicable is None:
            blockers.append(f"별표 13 제{item_no}호 {label} 해당 여부 미확인")
            continue
        if answer.applicable is False:
            continue

        rows = _item_rows(db, item_no)
        if rows.empty:
            blockers.append(f"별표 13 제{item_no}호 규정량 DB 행을 찾지 못했습니다.")
            continue
        legal = rows.iloc[0]
        mfg_threshold = _number(legal.get("manufacture_handling_threshold_kg"))
        storage_threshold = _number(legal.get("storage_threshold_kg"))
        if not mfg_threshold or not storage_threshold:
            blockers.append(f"별표 13 제{item_no}호 규정량 DB 값 확인 필요")
            continue

        if answer.manufacture_handling_kg is None or answer.storage_kg is None:
            blockers.append(
                f"별표 13 제{item_no}호 {label}: 하루 최대 제조·취급량과 최대 저장량을 모두 kg로 확인해 주세요. 사용하지 않는 구분은 0으로 입력합니다."
            )
            continue
        if answer.manufacture_handling_kg < 0 or answer.storage_kg < 0:
            blockers.append(f"별표 13 제{item_no}호 {label}: 음수 수량은 사용할 수 없습니다.")
            continue

        contributions.append(
            {
                "company_row": 0,
                "cas": "PROPERTY",
                "item_no": item_no,
                "legal_substance": _clean(legal.get("substance_name")) or label,
                "mfg_kg": float(answer.manufacture_handling_kg),
                "storage_kg": float(answer.storage_kg),
                "mfg_threshold": float(mfg_threshold),
                "storage_threshold": float(storage_threshold),
                "quantity_basis": "사용자 확인 물성 + kg 수량",
            }
        )
    return _aggregate_ratio_lines(contributions), blockers


def _special_lines(
    intake: IntakeData,
    db,
    facts: PSMFollowupFacts,
    required_items: tuple[int, ...],
) -> tuple[list[PSMRatioLine], list[str], list[str]]:
    contributions: list[dict[str, Any]] = []
    blockers: list[str] = []
    messages: list[str] = []

    for item_no in required_items:
        value = facts.special_values_pct.get(item_no)
        applies = _special_condition_applies(item_no, value)
        label, rule = SPECIAL_VALUE_RULES[item_no]
        if applies is None:
            blockers.append(f"별표 13 제{item_no}호: {label}를 확인해 주세요({rule}).")
            continue
        if not applies:
            messages.append(f"별표 13 제{item_no}호 특수 성분조건 불충족: 입력 {value:g}% · 기준 {rule}")
            continue

        legal_rows = _item_rows(db, item_no)
        if legal_rows.empty:
            blockers.append(f"별표 13 제{item_no}호 규정량 DB 행을 찾지 못했습니다.")
            continue
        legal = legal_rows.iloc[0]
        mfg_threshold = _number(legal.get("manufacture_handling_threshold_kg"))
        storage_threshold = _number(legal.get("storage_threshold_kg"))
        if not mfg_threshold or not storage_threshold:
            blockers.append(f"별표 13 제{item_no}호 규정량 DB 값 확인 필요")
            continue

        matched = 0
        for idx, company_row in intake.chemicals.iterrows():
            cas = _clean(company_row.get("CAS No."))
            if not CAS_RE.fullmatch(cas) or not _cas_list_contains(legal.get("cas_list"), cas):
                continue
            matched += 1
            unit = company_row.get("수량 단위")
            mfg_kg = _kg(company_row.get("최대 제조·사용량"), unit)
            storage_kg = _kg(company_row.get("최대 저장량"), unit)
            if mfg_kg is None and storage_kg is None:
                blockers.append(f"화학물질 목록 {idx + 1}행: 별표 13 제{item_no}호 수량을 kg/ton으로 확인해 주세요.")
                continue
            contributions.append(
                {
                    "company_row": idx + 1,
                    "cas": cas,
                    "item_no": item_no,
                    "legal_substance": _clean(legal.get("substance_name")),
                    "mfg_kg": mfg_kg,
                    "storage_kg": storage_kg,
                    "mfg_threshold": float(mfg_threshold),
                    "storage_threshold": float(storage_threshold),
                    "quantity_basis": f"특수 성분조건 확인: {label} {value:g}% ({rule}) · 제품질량 기준",
                }
            )
        if matched == 0:
            blockers.append(f"별표 13 제{item_no}호에 해당하는 회사 화학물질 행을 다시 찾지 못했습니다.")

    return _aggregate_ratio_lines(contributions), blockers, messages


def _recalculate_line(line: PSMRatioLine, mfg_kg: float, storage_kg: float) -> PSMRatioLine:
    mfg_ratio = mfg_kg / line.manufacture_handling_threshold_kg if line.manufacture_handling_threshold_kg > 0 else 0.0
    storage_ratio = storage_kg / line.storage_threshold_kg if line.storage_threshold_kg > 0 else 0.0
    if mfg_ratio >= storage_ratio:
        controlling_ratio = mfg_ratio
        controlling_basis = "제조·취급"
    else:
        controlling_ratio = storage_ratio
        controlling_basis = "저장"
    return replace(
        line,
        manufacture_handling_kg=round(mfg_kg, 6),
        storage_kg=round(storage_kg, 6),
        manufacture_handling_ratio=round(mfg_ratio, 8),
        storage_ratio=round(storage_ratio, 8),
        controlling_ratio=round(controlling_ratio, 8),
        controlling_basis=controlling_basis,
        quantity_basis=line.quantity_basis + " / 별표 13 비고 제8호 제외수량 반영",
    )


def apply_note8_exclusions(
    lines: list[PSMRatioLine],
    adjustments: dict[int, PSMNote8Adjustment],
) -> tuple[list[PSMRatioLine], list[str]]:
    """Subtract user-confirmed note-8 facility quantities and recalculate R lines."""
    blockers: list[str] = []
    by_item = {line.legal_item_no: line for line in lines}
    updated = dict(by_item)

    for item_no, adjustment in adjustments.items():
        line = by_item.get(int(item_no))
        if line is None:
            blockers.append(f"별표 13 제{item_no}호는 현재 비고 제7호 합산행에 없어 비고 제8호 제외수량을 적용할 수 없습니다.")
            continue
        mfg_ex = float(adjustment.manufacture_handling_kg or 0.0)
        storage_ex = float(adjustment.storage_kg or 0.0)
        if mfg_ex < 0 or storage_ex < 0:
            blockers.append(f"별표 13 제{item_no}호 비고 제8호 제외수량은 음수일 수 없습니다.")
            continue
        if mfg_ex > line.manufacture_handling_kg + 1e-9 or storage_ex > line.storage_kg + 1e-9:
            blockers.append(
                f"별표 13 제{item_no}호 비고 제8호 제외수량이 현재 계산수량보다 큽니다. "
                f"현재 제조·취급 {line.manufacture_handling_kg:g} kg, 저장 {line.storage_kg:g} kg"
            )
            continue
        updated[item_no] = _recalculate_line(
            line,
            line.manufacture_handling_kg - mfg_ex,
            line.storage_kg - storage_ex,
        )

    return [updated[item_no] for item_no in sorted(updated)], blockers


def reassess_psm_with_followup(
    intake: IntakeData,
    facts: PSMFollowupFacts | None = None,
    base: PSMAssessment | None = None,
) -> PSMFollowupResult:
    facts = facts or PSMFollowupFacts()
    base = base or assess_psm(intake)
    if not base.db_ready:
        return PSMFollowupResult(
            status="DB_NOT_READY",
            label=base.label,
            base=base,
            blockers=list(base.blockers or base.messages),
        )

    db = _load_db()
    requirements = detect_followup_requirements(intake, base)
    property_lines, property_blockers = _property_lines(db, facts, requirements.property_items)
    special_lines, special_blockers, special_messages = _special_lines(
        intake, db, facts, requirements.special_items
    )

    # Base lines never contain unresolved property items 1/2 or special items
    # 23/42, so appending these resolved lines cannot double-count them.
    lines = list(base.ratio_lines) + property_lines + special_lines
    lines.sort(key=lambda line: line.legal_item_no)
    r_before_note8 = round(calculate_r_value(lines), 8)

    ordinary_industry_trigger = bool(base.industry_match and base.industry_code != "20202")
    conditional_industry_trigger = bool(
        base.industry_code == "20202"
        and any(
            facts.property_answers.get(item_no, PSMPropertyAnswer()).applicable is True
            for item_no in (1, 2)
        )
    )
    industry_trigger = ordinary_industry_trigger or conditional_industry_trigger

    blockers = [
        blocker
        for blocker in base.blockers
        if not blocker.startswith("법정 농도·성분조건 미확인 항목:")
        and blocker != "별표 13 제1호 인화성 가스 / 제2호 인화성 액체 여부 미확인"
    ]
    blockers.extend(property_blockers)
    blockers.extend(special_blockers)
    messages = list(base.messages) + special_messages

    note8_required = bool(r_before_note8 >= 1.0 and not industry_trigger)
    adjusted_lines = lines
    if note8_required:
        if facts.note8_answer in {"", "UNKNOWN"}:
            blockers.append("별표 13 비고 제8호의 전문 가스 저장·판매시설 해당 여부 미확인")
        elif facts.note8_answer == "YES":
            positive_adjustments = {
                item_no: adjustment
                for item_no, adjustment in facts.note8_exclusions.items()
                if (adjustment.manufacture_handling_kg or 0) > 0 or (adjustment.storage_kg or 0) > 0
            }
            if not positive_adjustments:
                blockers.append("비고 제8호 해당 가스의 제외할 제조·취급량 또는 저장량을 입력해 주세요.")
            else:
                adjusted_lines, note8_blockers = apply_note8_exclusions(lines, positive_adjustments)
                blockers.extend(note8_blockers)
        elif facts.note8_answer != "NO":
            blockers.append("별표 13 비고 제8호 답변값을 확인해 주세요.")

    r_value = round(calculate_r_value(adjusted_lines), 8)
    quantity_trigger = bool(r_value >= 1.0)
    trigger_channels: list[str] = []
    if industry_trigger:
        trigger_channels.append("INDUSTRY_TRIGGER")
    if quantity_trigger:
        trigger_channels.append("QUANTITY_TRIGGER")

    blockers = list(dict.fromkeys(str(v) for v in blockers if str(v).strip()))
    r_complete = not blockers

    if trigger_channels:
        label = "시행령 제43조제1항 기준 해당 · 제2항 제외설비 확인 필요"
        if len(trigger_channels) == 2:
            label = "시행령 제43조제1항의 사업 종류 기준 및 별표 13 유해·위험물질 규정량 기준 해당"
        elif industry_trigger:
            label = "시행령 제43조제1항의 사업 종류 기준 해당"
        else:
            label = "별표 13 유해·위험물질 규정량 기준 해당"
        status = "APPLICABLE_CANDIDATE"
    elif blockers:
        status = "ADDITIONAL_INFO_REQUIRED"
        label = "PSM 추가정보 확인 필요"
    else:
        status = "NO_TRIGGER_IN_CHECKED_SCOPE"
        label = "현재 확인 범위에서 시행령 제43조제1항 제출 대상 기준 미확인"

    return PSMFollowupResult(
        status=status,
        label=label,
        base=base,
        ratio_lines=adjusted_lines,
        r_before_note8=r_before_note8,
        r_value=r_value,
        r_complete=r_complete,
        industry_trigger=industry_trigger,
        quantity_trigger=quantity_trigger,
        trigger_channels=trigger_channels,
        note8_required=note8_required,
        blockers=blockers,
        messages=messages,
    )
