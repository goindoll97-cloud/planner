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
            requests.append(_request("05_최종판정조건", f"'{applicable_key}'를 Y/N으로 확인하여 작성해 주세요."))
        elif applicable and (mfg is None or storage is None):
            requests.append(_request("05_최종판정조건", f"{label}에 해당하므로 '{mfg_key}'와 '{storage_key}'를 kg로 작성해 주세요. 미사용 구분은 0으로 입력합니다."))

    special_meta = {
        23: "별표 13 제23호 발연황산 삼산화황(SO3) 중량%",
        42: "별표 13 제42호 니트로셀룰로오스 질소 함유량%",
    }
    for item_no in requirements.special_items:
        key = special_meta[item_no]
        value = _num(_condition_value(conditions, key))
        facts.special_values_pct[item_no] = value
        if value is None:
            requests.append(_request("05_최종판정조건", f"'{key}'를 확인하여 숫자(%)로 작성해 주세요."))

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
                    decision.psm_explanation = "「산업안전보건법 시행령」 제43조제1항의 사업 종류 또는 별표 13 유해·위험물질 규정량 기준에 해당하고, 제43조제2항 제외설비에 해당하지 않는 것으로 회사 입력파일에서 확인되었습니다."
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
        decision.psm_legal_basis = ["「산업안전보건법 시행령」 제43조", "같은 영 별표 13"]

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
    if final_cap.status == "REQUIRED_GROUP_1":
        decision.cap_explanation = "회사 입력파일의 최대보유량, 상위 규정수량, 법적 예외 및 주요취급시설 정보를 기준으로 작성수준을 1군 사업장으로 확인했습니다."
    elif final_cap.status == "REQUIRED_GROUP_2":
        decision.cap_explanation = "회사 입력파일의 최대보유량, 하위·상위 규정수량 및 법적 예외 정보를 기준으로 작성수준을 2군 사업장으로 확인했습니다."
    elif final_cap.status == "NOT_REQUIRED":
        decision.cap_explanation = "회사 입력파일과 승인 규정 DB를 기준으로 화학사고예방관리계획서 작성·제출 의무가 없는 사유를 확인했습니다."
    else:
        decision.cap_explanation = "회사 입력파일의 미확인 항목을 보완해야 최종 작성 여부 또는 작성수준을 확정할 수 있습니다."
    decision.cap_legal_basis = list(final_cap.legal_basis)
    decision.cap_quantity_rows = quantity_rows

    unresolved_raw = _condition_value(intake.final_conditions, "미확인 결정조건 존재 여부")
    if _answer_is_yes(unresolved_raw):
        requests.append(_request("05_최종판정조건", "'미확인 결정조건 존재 여부'가 Y로 작성되어 있습니다. 미확인 사항을 확인한 뒤 N으로 갱신해 주세요."))

    decision.company_requests = _unique(requests)
    decision.system_blockers = _unique(system)
    return decision
