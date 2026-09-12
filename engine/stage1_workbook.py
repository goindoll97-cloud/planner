from __future__ import annotations

"""Stage-1 screening driven only by the uploaded company workbook.

The workbook is the single source of company facts. This module never asks the
Streamlit UI to overwrite or supplement a company fact. Missing decisive facts
become concise workbook correction requests (fail closed).
"""

from dataclasses import asdict, dataclass, field
import re
from typing import Any

import pandas as pd

from .cap_engine import assess_cap
from .cap_final_decision import assess_cap_final, exemption_options
from .cap_holding import app4_db_ready, assess_cap_holding
from .cap_holding_screen import screen_facility_stage
from .cap_quick_holding import compare_confirmed_declared_holding
from .cap_sds_app1 import assess_sds_app1_row
from .consulting_guidance import get_guide
from .inventory import (
    IntakeData,
    _answer_is_no,
    _answer_is_unknown,
    _answer_is_yes,
    _clean_text,
    _condition_value,
    _map_sds_text_to_app1_keys,
    _norm_answer,
)
from .psm_engine import assess_psm
from .psm_followup import (
    PSMNote8Adjustment,
    PSMFollowupFacts,
    PSMPropertyAnswer,
    detect_followup_requirements,
    reassess_psm_with_followup,
)


@dataclass
class Stage1WorkbookDecision:
    company_requests: list[str] = field(default_factory=list)
    system_blockers: list[str] = field(default_factory=list)
    psm_status: str = ""
    psm_explanation: str = ""
    psm_r_value: float | None = None
    psm_legal_basis: list[str] = field(default_factory=list)
    psm_ratio_rows: list[dict[str, Any]] = field(default_factory=list)
    cap_status: str = ""
    cap_explanation: str = ""
    cap_legal_basis: list[str] = field(default_factory=list)
    cap_quantity_rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.company_requests and not self.system_blockers


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if str(v or "").strip()))


def _num(value: object) -> float | None:
    text = _clean_text(value).replace(",", "")
    if not text or _norm_answer(text) in {"해당없음", "모름", "미확인"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if number >= 0 else None


def _answer_bool(value: object) -> bool | None:
    if _answer_is_yes(value):
        return True
    if _answer_is_no(value):
        return False
    return None


def _request(sheet: str, text: str) -> str:
    return f"{sheet}: {text}"



_PSM_INDUSTRY_CLAUSE_BY_CODE = {
    "19210": 1,
    "19229": 2,
    "20111": 3,
    "20202": 3,
    "20311": 4,
    "20312": 5,
    "20321": 6,
    "20494": 7,
}


def _fmt_kg(value: object) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "수량 미확인"
    if amount >= 1000:
        return f"{amount / 1000:,.3f} ton ({amount:,.0f} kg)"
    return f"{amount:,.0f} kg"


def _fmt_ton(value: object) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "수량 미확인"
    return f"{amount:,.4g} ton"


def _build_psm_submission_explanation(psm_result) -> str:
    """Explain why the uploaded company facts satisfy the statutory PSM route."""
    parts = [
        "「산업안전보건법」 제44조제1항은 사업장에 대통령령으로 정하는 유해하거나 위험한 설비가 있는 경우 "
        "공정안전보고서를 작성하여 고용노동부장관에게 제출하도록 규정합니다."
    ]

    if psm_result.industry_trigger:
        code = str(psm_result.base.industry_code or "").strip()
        name = str(psm_result.base.industry_match or "").strip() or "해당 사업 종류"
        clause = _PSM_INDUSTRY_CLAUSE_BY_CODE.get(code)
        if clause:
            sentence = (
                f"귀 사업장이 입력한 한국표준산업분류 코드는 {code}이고, 이는 「산업안전보건법 시행령」 "
                f"제43조제1항제{clause}호의 ‘{name}’에 해당합니다."
            )
        else:
            sentence = (
                f"귀 사업장이 입력한 사업 종류는 「산업안전보건법 시행령」 제43조제1항 각 호의 ‘{name}’에 해당합니다."
            )
        if code == "20202":
            sentence += (
                " 이 사업 종류는 같은 항 제3호 단서에 따라 별표 13 제1호 인화성 가스 또는 제2호 인화성 액체에 "
                "해당하는 경우로 한정되며, 회사 입력정보에서 해당 조건이 확인되었습니다."
            )
        parts.append(sentence)

    if psm_result.quantity_trigger:
        detail_lines = []
        for line in sorted(psm_result.ratio_lines, key=lambda x: float(x.controlling_ratio or 0.0), reverse=True):
            if float(line.controlling_ratio or 0.0) <= 0:
                continue
            if line.controlling_basis == "저장":
                amount = line.storage_kg
                threshold = line.storage_threshold_kg
                ratio = line.storage_ratio
            else:
                amount = line.manufacture_handling_kg
                threshold = line.manufacture_handling_threshold_kg
                ratio = line.manufacture_handling_ratio
            detail_lines.append(
                f"별표 13 제{line.legal_item_no}호 {line.legal_substance}: {line.controlling_basis} "
                f"{_fmt_kg(amount)} / 규정량 {_fmt_kg(threshold)} = {float(ratio):.4f}"
            )
        shown = detail_lines[:5]
        suffix = f" 외 {len(detail_lines) - 5}개 항목" if len(detail_lines) > 5 else ""
        detail_text = "; ".join(shown) + suffix if shown else "별표 13 해당 물질의 규정량 비교 결과"
        parts.append(
            f"또한 「산업안전보건법 시행령」 제43조제1항 및 별표 13 비고 제7호에 따라 산정한 합산한 값(R)이 "
            f"{float(psm_result.r_value):.4f}로 1 이상입니다. 주요 산정근거는 {detail_text}입니다."
        )

    parts.append(
        "회사 입력정보에서 「산업안전보건법 시행령」 제43조제2항 각 호의 제외설비에 해당하지 않는 것으로 확인되어, "
        "귀 사업장은 공정안전보고서 제출 대상에 포함됩니다."
    )
    return " ".join(parts)


def _cap_level(row: dict[str, Any]) -> str:
    raw = str(row.get("quantity_band") or row.get("status") or "")
    upper = raw.upper()
    if "BELOW" in upper or "하위 규정수량 미만" in raw:
        return "BELOW"
    if "UPPER" in upper or "상위 규정수량 이상" in raw:
        return "UPPER"
    if "LOWER" in upper or "하위 이상" in raw or "하위 규정수량 이상" in raw:
        return "LOWER"
    return ""


def _cap_row_summary(row: dict[str, Any], level: str) -> str:
    name = str(row.get("product_name") or row.get("legal_substance") or "해당 유해화학물질").strip()
    cas = str(row.get("cas") or "").strip()
    label = f"{name}" + (f"(CAS {cas})" if cas else "")
    holding = row.get("calculated_max_holding_ton")
    if holding is None:
        holding = row.get("confirmed_max_holding_ton")
    lower = row.get("lower_quantity_ton")
    upper = row.get("upper_quantity_ton")
    if level == "UPPER":
        if holding is not None and upper is not None:
            return f"{label}의 사업장 최대보유량 {_fmt_ton(holding)}이 상위 규정수량 {_fmt_ton(upper)} 이상"
        return f"{label}의 사업장 최대보유량이 상위 규정수량 이상"
    if level == "LOWER":
        if holding is not None and lower is not None and upper is not None:
            return (
                f"{label}의 사업장 최대보유량 {_fmt_ton(holding)}이 하위 규정수량 {_fmt_ton(lower)} 이상이고 "
                f"상위 규정수량 {_fmt_ton(upper)} 미만"
            )
        return f"{label}의 사업장 최대보유량이 하위 규정수량 이상·상위 규정수량 미만"
    return label


def _build_cap_required_explanation(final_cap, quantity_rows: list[dict[str, Any]]) -> str:
    """Explain why the uploaded company facts require a CAP and its writing level."""
    parts = [
        "「화학물질관리법」 제23조제1항은 유해화학물질 취급시설을 설치·운영하려는 자에게 "
        "화학사고예방관리계획서를 작성하여 제출하도록 규정합니다."
    ]
    if final_cap.status == "REQUIRED_GROUP_1":
        matched = [_cap_row_summary(row, "UPPER") for row in quantity_rows if _cap_level(row) == "UPPER"]
        matched = list(dict.fromkeys(matched))
        if matched:
            parts.append("귀 사업장의 규정수량 비교 결과, " + "; ".join(matched[:5]) + "으로 확인되었습니다.")
        parts.append(
            "또한 회사 입력정보에서 「화학물질관리법 시행규칙」 제19조제8항에 따른 주요취급시설을 운영하는 것으로 "
            "확인되었고, 「화학물질관리법」 제23조제1항 단서의 법정 예외에 해당하지 않는 것으로 확인되었습니다."
        )
        parts.append(
            "따라서 「화학사고예방관리계획서 작성 등에 관한 규정」 제2조제1항제12의1, 제4조 및 제6조에 따라 "
            "귀 사업장은 화학사고예방관리계획서 작성수준 1군 사업장으로 작성·제출 대상에 포함됩니다."
        )
    elif final_cap.status == "REQUIRED_GROUP_2":
        matched = [_cap_row_summary(row, "LOWER") for row in quantity_rows if _cap_level(row) == "LOWER"]
        matched = list(dict.fromkeys(matched))
        if matched:
            parts.append("귀 사업장의 규정수량 비교 결과, " + "; ".join(matched[:5]) + "으로 확인되었습니다.")
        parts.append("회사 입력정보에서 「화학물질관리법」 제23조제1항 단서의 법정 예외에 해당하지 않는 것으로 확인되었습니다.")
        parts.append(
            "따라서 「화학사고예방관리계획서 작성 등에 관한 규정」 제2조제1항제12의2, 제4조 및 제6조에 따라 "
            "귀 사업장은 화학사고예방관리계획서 작성수준 2군 사업장으로 작성·제출 대상에 포함됩니다."
        )
    return " ".join(parts)


def _row_label(intake: IntakeData, row_no: int) -> str:
    if row_no <= 0 or row_no > len(intake.chemicals):
        return f"{row_no}행"
    row = intake.chemicals.iloc[row_no - 1]
    product = _clean_text(row.get("제품명"))
    cas = _clean_text(row.get("CAS No."))
    detail = " / ".join(v for v in [product, cas] if v)
    return f"{row_no}행" + (f" ({detail})" if detail else "")


def _all_direct_holding_confirmed(intake: IntakeData, row_numbers: list[int]) -> bool:
    col = "최대보유량 법정 산정 여부"
    value_col = "최대 동시보유량(알면 입력)"
    if col not in intake.chemicals.columns or value_col not in intake.chemicals.columns:
        return False
    for row_no in row_numbers:
        if row_no <= 0 or row_no > len(intake.chemicals):
            return False
        row = intake.chemicals.iloc[row_no - 1]
        if not _answer_is_yes(row.get(col)):
            return False
        if _num(row.get(value_col)) is None:
            return False
    return True


def _match_cap_exemption(value: object) -> str:
    raw = re.sub(r"\s+", "", _clean_text(value))
    if not raw or _norm_answer(raw) in {"해당없음", "모름", "미확인"}:
        return ""
    for option in exemption_options():
        if re.sub(r"\s+", "", option.label) == raw:
            return option.key
    return ""


def _known_psm_exclusion(value: object) -> bool:
    raw = re.sub(r"\s+", "", _clean_text(value))
    if not raw:
        return False
    guide = get_guide("PSM_EXCLUDED_FACILITY")
    if guide is None:
        return False
    return raw in {re.sub(r"\s+", "", str(v)) for v in guide.what_to_check}


def _psm_facts_from_workbook(intake: IntakeData, base, requests: list[str]) -> PSMFollowupFacts:
    conditions = intake.final_conditions
    requirements = detect_followup_requirements(intake, base)
    facts = PSMFollowupFacts()

    property_meta = {
        1: ("인화성 가스", "별표 13 제1호 인화성 가스 해당 여부", "별표 13 제1호 하루 최대 제조·취급량(kg)", "별표 13 제1호 최대 저장량(kg)"),
        2: ("인화성 액체", "별표 13 제2호 인화성 액체 해당 여부", "별표 13 제2호 하루 최대 제조·취급량(kg)", "별표 13 제2호 최대 저장량(kg)"),
    }
    for item_no in requirements.property_items:
        label, applicable_key, mfg_key, storage_key = property_meta[item_no]
        applicable_raw = _condition_value(conditions, applicable_key)
        applicable = _answer_bool(applicable_raw)
        mfg = _num(_condition_value(conditions, mfg_key))
        storage = _num(_condition_value(conditions, storage_key))
        facts.property_answers[item_no] = PSMPropertyAnswer(applicable, mfg, storage)
        if applicable is None:
            requests.append(_request("05_최종판정조건", f"근거: 「산업안전보건법」 제44조제1항 → 「산업안전보건법 시행령」 제43조제1항 및 별표 13 「유해·위험물질 규정량」 제{item_no}호({label}). 귀사의 취급물질·공정이 이 항목에 해당하는지 확인하여 Y/N으로 작성해 주세요."))
        elif applicable and (mfg is None or storage is None):
            requests.append(_request("05_최종판정조건", f"근거: 「산업안전보건법」 제44조제1항 → 「산업안전보건법 시행령」 제43조제1항 및 별표 13 「유해·위험물질 규정량」 제{item_no}호({label}). 해당으로 확인된 경우 하루 최대 제조·취급량과 최대 저장량을 각각 kg로 작성해 주세요. 사용하지 않는 구분은 0으로 입력합니다."))

    special_meta = {
        23: "별표 13 제23호 발연황산 삼산화황(SO3) 중량%",
        42: "별표 13 제42호 니트로셀룰로오스 질소 함유량%",
    }
    for item_no in requirements.special_items:
        key = special_meta[item_no]
        value = _num(_condition_value(conditions, key))
        facts.special_values_pct[item_no] = value
        if value is None:
            legal_name = {
                23: "별표 13 「유해·위험물질 규정량」 제23호 발연황산(삼산화황 중량 65% 이상 80% 미만)",
                42: "별표 13 「유해·위험물질 규정량」 제42호 니트로셀룰로오스(질소 함유량 12.6% 이상)",
            }[item_no]
            requests.append(_request("05_최종판정조건", f"근거: 「산업안전보건법」 제44조제1항 → 「산업안전보건법 시행령」 제43조제1항 및 {legal_name}. 제품 SDS, 시험성적서 또는 제조사 자료에서 해당 성분 함량을 확인하여 숫자(%)로 작성해 주세요."))

    note8_raw = _condition_value(conditions, "가스를 전문으로 저장·판매하는 시설 내 가스 여부")
    if _answer_is_yes(note8_raw):
        facts.note8_answer = "YES"
    elif _answer_is_no(note8_raw):
        facts.note8_answer = "NO"
    elif _answer_is_unknown(note8_raw):
        facts.note8_answer = "UNKNOWN"

    if facts.note8_answer == "YES":
        frame = getattr(intake, "psm_note8_exclusions", pd.DataFrame())
        if frame is None or frame.empty:
            requests.append(_request("06_PSM_비고8제외수량", "전문 가스 저장·판매시설에 해당하는 가스의 별표 13 호수와 제외 제조·취급량/저장량을 작성해 주세요."))
        else:
            grouped: dict[int, list[float]] = {}
            for _, row in frame.iterrows():
                item_no = _num(row.get("별표13 호수"))
                mfg = _num(row.get("제조·취급 제외량(kg)"))
                storage = _num(row.get("저장 제외량(kg)"))
                if item_no is None or int(item_no) != item_no:
                    requests.append(_request("06_PSM_비고8제외수량", "'별표13 호수'를 정수로 작성해 주세요."))
                    continue
                if mfg is None and storage is None:
                    requests.append(_request("06_PSM_비고8제외수량", f"별표 13 제{int(item_no)}호의 제외 제조·취급량 또는 저장량을 kg로 작성해 주세요."))
                    continue
                values = grouped.setdefault(int(item_no), [0.0, 0.0])
                values[0] += float(mfg or 0.0)
                values[1] += float(storage or 0.0)
            for item_no, (mfg, storage) in grouped.items():
                facts.note8_exclusions[item_no] = PSMNote8Adjustment(mfg, storage)

    return facts


def _translate_psm_base_blockers(intake: IntakeData, base, requests: list[str]) -> None:
    for blocker in base.blockers:
        text = str(blocker)
        if text.startswith("CAS 미확인 행:"):
            requests.append(_request("02_화학물질목록", f"{text.split(':', 1)[1].strip()}의 CAS No.를 확인하여 작성해 주세요."))
        elif text.startswith("질량 환산 필요 행:"):
            requests.append(_request("02_화학물질목록", f"{text.split(':', 1)[1].strip()}의 PSM 수량을 kg 또는 ton 질량단위로 작성해 주세요."))
        elif "제조·취급·저장량 미확인 행:" in text:
            requests.append(_request("02_화학물질목록", f"{text.split(':', 1)[1].strip()}의 최대 제조·사용량과 최대 저장량을 확인하여 작성해 주세요."))


def _cap_exemption_inputs(intake: IntakeData) -> tuple[str, str, bool, list[str]]:
    conditions = intake.final_conditions
    requests: list[str] = []
    answer_raw = _condition_value(conditions, "법 제23조제1항 단서 해당 여부") or _condition_value(conditions, "법정 작성 면제시설 해당 여부")
    partial_raw = _condition_value(conditions, "법 제23조제1항 단서가 일부 취급시설에만 해당하는지") or _condition_value(conditions, "일부 시설만 면제조건")
    if _answer_is_yes(partial_raw):
        return "PARTIAL", "", False, requests
    if _answer_is_no(answer_raw):
        return "NONE", "", False, requests
    if _answer_is_unknown(answer_raw) or not _clean_text(answer_raw):
        return "UNANSWERED", "", False, requests
    if not _answer_is_yes(answer_raw):
        return "UNANSWERED", "", False, requests

    type_raw = _condition_value(conditions, "법적 예외 적용 유형")
    key = _match_cap_exemption(type_raw)
    all_raw = _condition_value(conditions, "법적 예외가 관련 취급시설 전체에 적용되는지")
    all_confirmed = _answer_is_yes(all_raw)
    if not key:
        requests.append(_request("05_최종판정조건", "법 제23조제1항 단서에 해당한다고 작성한 경우 '법적 예외 적용 유형'에 법령상 유형을 정확히 작성해 주세요."))
    if _answer_bool(all_raw) is None:
        requests.append(_request("05_최종판정조건", "'법적 예외가 관련 취급시설 전체에 적용되는지'를 Y/N으로 확인해 주세요."))
    if _answer_is_no(all_raw):
        return "PARTIAL", key, False, requests
    return "EXEMPT", key, all_confirmed, requests


def assess_stage1_from_workbook(intake: IntakeData) -> Stage1WorkbookDecision:
    decision = Stage1WorkbookDecision()
    requests: list[str] = []
    system: list[str] = []

    # ---- PSM: workbook facts only ----
    psm_base = assess_psm(intake)
    if not psm_base.db_ready:
        system.append("공정안전보고서 별표 13 승인 DB를 확인해 주세요.")
    else:
        _translate_psm_base_blockers(intake, psm_base, requests)
        psm_facts = _psm_facts_from_workbook(intake, psm_base, requests)
        psm_result = reassess_psm_with_followup(intake, psm_facts, psm_base)
        decision.psm_r_value = psm_result.r_value if psm_result.r_complete else None
        decision.psm_ratio_rows = [asdict(row) for row in psm_result.ratio_lines]
        if psm_result.blockers:
            # Known workbook omissions were already translated above. Any remaining
            # blocker is still fail-closed but is summarized rather than exposed as
            # another on-screen input control.
            known_fragments = (
                "인화성 가스 해당 여부 미확인",
                "인화성 액체 해당 여부 미확인",
                "발연황산의 삼산화황",
                "니트로셀룰로오스의 질소",
                "전문 가스 저장·판매시설 해당 여부 미확인",
                "제외할 제조·취급량 또는 저장량",
            )
            for blocker in psm_result.blockers:
                if any(fragment in blocker for fragment in known_fragments):
                    continue
                if blocker not in psm_base.blockers:
                    requests.append(_request("회사 입력파일", str(blocker)))

        if psm_result.note8_required and not psm_facts.note8_answer:
            requests.append(_request("05_최종판정조건", "'가스를 전문으로 저장·판매하는 시설 내 가스 여부'를 Y/N으로 확인해 주세요."))

        if not psm_result.blockers and not [r for r in requests if r.startswith("05_최종판정조건") or r.startswith("06_PSM") or r.startswith("02_화학물질목록")]:
            if psm_result.industry_trigger or psm_result.quantity_trigger:
                exclusion_raw = _condition_value(intake.final_conditions, "시행령 제43조제2항 제외설비 해당 여부") or _condition_value(intake.final_conditions, "법정 제외설비 해당 여부")
                if _answer_is_no(exclusion_raw):
                    decision.psm_status = "공정안전보고서 제출 대상"
                    decision.psm_explanation = _build_psm_submission_explanation(psm_result)
                elif _answer_is_yes(exclusion_raw):
                    exclusion_type = _condition_value(intake.final_conditions, "시행령 제43조제2항 제외설비 유형")
                    if not _known_psm_exclusion(exclusion_type):
                        requests.append(_request("05_최종판정조건", "제43조제2항 제외설비에 해당한다고 작성한 경우 '시행령 제43조제2항 제외설비 유형'을 법령상 유형으로 정확히 작성해 주세요."))
                    else:
                        decision.psm_status = "시행령 제43조제2항 제외설비 해당"
                        decision.psm_explanation = "회사 입력파일에서 시행령 제43조제2항의 제외설비 유형이 확인되어 공정안전보고서 제출 대상에서 제외되는 것으로 판정했습니다."
                else:
                    requests.append(_request("05_최종판정조건", "'시행령 제43조제2항 제외설비 해당 여부'를 Y/N으로 확인하여 작성해 주세요."))
            else:
                decision.psm_status = "현재 확인 범위에서 공정안전보고서 제출 대상 기준 미해당"
                decision.psm_explanation = "회사 입력파일의 사업 종류, 별표 13 물성·특수조건 및 비고 제7호 합산한 값(R)을 확인한 결과 제출 대상 기준이 확인되지 않았습니다."
        decision.psm_legal_basis = [
            "「산업안전보건법」 제44조제1항",
            "「산업안전보건법 시행령」 제43조제1항",
            "같은 영 제43조제2항",
        ]
        if psm_result.quantity_trigger:
            decision.psm_legal_basis.append("같은 영 별표 13 및 비고 제7호")

    # ---- CAP: workbook facts only ----
    cap = assess_cap(intake)
    cap_screen = screen_facility_stage(intake)
    quantity_rows: list[dict[str, Any]] = []
    cap_unresolved: list[str] = []

    if not cap_screen.ready:
        system.extend(cap_screen.blockers or ["화학사고예방관리계획서 규정수량 승인 DB를 확인해 주세요."])
    elif cap_screen.blockers:
        requests.append(_request("02_화학물질목록", "농도·성상 등 규정수량 결정에 필요한 항목을 확인하여 작성해 주세요."))
        cap_unresolved.extend(cap_screen.blockers)
    elif cap_screen.row_numbers:
        if not app4_db_ready():
            system.append("화학사고예방관리계획서 최대보유량 산정기준 DB를 확인해 주세요.")
        elif intake.facilities is not None and not intake.facilities.empty:
            facility_result = assess_cap_holding(
                intake=intake,
                facilities=intake.facilities,
                legal_hits=cap_screen.legal_hits,
                required_row_numbers=cap_screen.row_numbers,
            )
            quantity_rows.extend(facility_result.comparison_rows)
            if facility_result.blockers:
                cap_unresolved.extend(facility_result.blockers)
                requests.append(_request("04_시설별최대보유량", "시설별 최대보유량 산정에 필요한 용량·밀도·직접확인 최대보유량 등 누락 항목을 확인하여 작성해 주세요."))
        elif _all_direct_holding_confirmed(intake, cap_screen.row_numbers):
            quick = compare_confirmed_declared_holding(intake, cap_screen.legal_hits)
            quantity_rows.extend(quick.comparison_rows)
            if quick.blockers:
                cap_unresolved.extend(quick.blockers)
                requests.append(_request("02_화학물질목록", "'최대 동시보유량'과 '최대보유량 법정 산정 여부'를 다시 확인하여 작성해 주세요."))
        else:
            cap_unresolved.append("법정 사업장 최대보유량 미확인")
            requests.append(_request("04_시설별최대보유량", "사업장 최대보유량을 산정할 수 있도록 시설별 최대보유량 정보를 작성해 주세요. 이미 법정 산정값을 알고 있다면 02 시트의 '최대 동시보유량'과 '최대보유량 법정 산정 여부=Y'를 작성해 주세요."))

    direct_upper = any("UPPER" in str(row.get("status", "")) or "상위 규정수량 이상" in str(row.get("quantity_band", "")) for row in quantity_rows)
    direct_lower = any("LOWER" in str(row.get("status", "")) or "하위 규정수량 이상" in str(row.get("quantity_band", "")) for row in quantity_rows)

    # Appendix 1 SDS facts are needed only while they can still change Stage-1
    # applicability/writing level. A confirmed upper-quantity result already fixes
    # the quantity band, so asking for unrelated SDS again would add noise.
    if cap.app1_required_rows and not direct_upper:
        for fallback in cap.app1_required_rows:
            row_no = int(fallback.get("row_no") or 0)
            if row_no <= 0 or row_no > len(intake.chemicals):
                continue
            row = intake.chemicals.iloc[row_no - 1]
            selected, verified_none = _map_sds_text_to_app1_keys(row.get("SDS 제2항 유해성·위험성 분류(선택 입력)"))
            holding_ok = _answer_is_yes(row.get("최대보유량 법정 산정 여부")) and _num(row.get("최대 동시보유량(알면 입력)")) is not None
            result = assess_sds_app1_row(
                intake,
                row_no,
                selected,
                verified_no_app1_class=verified_none,
                holding_confirmed=holding_ok,
            )
            if result.status in {"HOLD", "DB_NOT_READY"}:
                if not selected and not verified_none:
                    requests.append(_request("02_화학물질목록", f"{_row_label(intake, row_no)}의 'SDS 제2항 유해성·위험성 분류'를 제품 SDS 그대로 작성해 주세요. 해당 분류가 없으면 '별표1 해당없음'으로 작성합니다."))
                if not holding_ok and not verified_none:
                    requests.append(_request("02_화학물질목록", f"{_row_label(intake, row_no)}의 법정 사업장 최대보유량을 확인하여 '최대 동시보유량'과 '최대보유량 법정 산정 여부=Y'를 작성해 주세요."))
                cap_unresolved.extend(result.blockers or [result.label])
            elif result.status in {"UPPER_CANDIDATE", "LOWER_CANDIDATE", "BELOW_LOWER"}:
                quantity_rows.append(
                    {
                        "status": result.status,
                        "row_no": result.row_no,
                        "product_name": result.product_name,
                        "cas": result.cas,
                        "confirmed_max_holding_ton": result.max_holding_ton,
                        "lower_quantity_ton": result.lower_quantity_ton,
                        "upper_quantity_ton": result.upper_quantity_ton,
                        "source_key": "CAP_QTY_APP1",
                    }
                )

    if cap.scope_candidates and not direct_upper:
        requests.append(_request("02_화학물질목록", "CAS 하나로 확정할 수 없는 염·화합물군·반응생성물 등의 규제범위 검토대상이 있습니다. 물질명·CAS·SDS 성분정보를 확인하여 보완해 주세요."))
        cap_unresolved.append("포괄 규제범위 미확인")

    quantity_rows = list(quantity_rows)
    threshold_upper = any("UPPER" in str(row.get("status", "")) or "상위 규정수량 이상" in str(row.get("quantity_band", "")) for row in quantity_rows)

    exemption_answer, exemption_key, exemption_all, exemption_requests = _cap_exemption_inputs(intake)
    requests.extend(exemption_requests)
    major_raw = _condition_value(intake.final_conditions, "개별 주요취급시설 존재 여부")
    major_answer = "YES" if _answer_is_yes(major_raw) else "NO" if _answer_is_no(major_raw) else "UNKNOWN" if _answer_is_unknown(major_raw) else "UNANSWERED"

    final_cap = assess_cap_final(
        quantity_rows,
        unresolved_blockers=cap_unresolved,
        exemption_answer=exemption_answer,
        exemption_key=exemption_key,
        exemption_all_relevant_confirmed=exemption_all,
        major_facility_answer=major_answer,
    )

    if final_cap.status == "HOLD" and not cap_unresolved:
        if threshold_upper and major_answer in {"UNKNOWN", "UNANSWERED"}:
            requests.append(_request("05_최종판정조건", "'상위 규정수량 이상을 취급하는 개별 주요취급시설 존재 여부'를 Y/N으로 확인하여 작성해 주세요."))
        if exemption_answer == "UNANSWERED":
            requests.append(_request("05_최종판정조건", "'법 제23조제1항 단서 해당 여부'를 Y/N으로 확인하여 작성해 주세요."))

    decision.cap_status = final_cap.label
    if final_cap.status in {"REQUIRED_GROUP_1", "REQUIRED_GROUP_2"}:
        decision.cap_explanation = _build_cap_required_explanation(final_cap, quantity_rows)
    elif final_cap.status == "NOT_REQUIRED":
        decision.cap_explanation = "회사 입력정보와 승인 규정 DB를 기준으로 화학사고예방관리계획서 작성·제출 의무가 없는 사유를 확인했습니다."
    else:
        decision.cap_explanation = "회사 입력정보의 미확인 항목을 보완해야 최종 작성 여부 또는 작성수준을 확정할 수 있습니다."
    decision.cap_legal_basis = list(final_cap.legal_basis)
    if final_cap.status in {"REQUIRED_GROUP_1", "REQUIRED_GROUP_2"}:
        decision.cap_legal_basis = _unique([
            "「화학물질관리법」 제23조제1항",
            "「화학물질관리법 시행규칙」 제19조제1항",
            *decision.cap_legal_basis,
        ])
    decision.cap_quantity_rows = quantity_rows

    unresolved_raw = _condition_value(intake.final_conditions, "미확인 결정조건 존재 여부")
    if _answer_is_yes(unresolved_raw):
        requests.append(_request("05_최종판정조건", "'미확인 결정조건 존재 여부'가 Y로 작성되어 있습니다. 미확인 사항을 확인한 뒤 N으로 갱신해 주세요."))

    decision.company_requests = _unique(requests)
    decision.system_blockers = _unique(system)
    return decision
