from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import streamlit as st

from engine.psm_engine import assess_psm
from engine.psm_followup import (
    PSMFollowupFacts,
    PSMNote8Adjustment,
    PSMPropertyAnswer,
    detect_followup_requirements,
    reassess_psm_with_followup,
)


def _optional_float(value: object) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _yn_value(value: str) -> bool | None:
    if value == "예":
        return True
    if value == "아니오":
        return False
    return None


def _property_label(item_no: int) -> str:
    return "인화성 가스" if item_no == 1 else "인화성 액체"


def _build_facts(requirements, *, include_note8: bool = True) -> PSMFollowupFacts:
    property_answers: dict[int, PSMPropertyAnswer] = {}
    for item_no in requirements.property_items:
        answer_text = str(st.session_state.get(f"psm_follow_property_{item_no}", "선택하세요"))
        applicable = _yn_value(answer_text)
        mfg = _optional_float(st.session_state.get(f"psm_follow_property_{item_no}_mfg", ""))
        storage = _optional_float(st.session_state.get(f"psm_follow_property_{item_no}_storage", ""))
        property_answers[item_no] = PSMPropertyAnswer(
            applicable=applicable,
            manufacture_handling_kg=mfg,
            storage_kg=storage,
        )

    special_values = {
        item_no: _optional_float(st.session_state.get(f"psm_follow_special_{item_no}", ""))
        for item_no in requirements.special_items
    }

    note8_answer = ""
    note8_exclusions: dict[int, PSMNote8Adjustment] = {}
    if include_note8:
        raw = str(st.session_state.get("psm_follow_note8", "선택하세요"))
        note8_answer = {
            "아니오": "NO",
            "예": "YES",
            "모름": "UNKNOWN",
        }.get(raw, "")
        for raw_item in st.session_state.get("psm_follow_note8_items", []) or []:
            item_no = int(raw_item)
            note8_exclusions[item_no] = PSMNote8Adjustment(
                manufacture_handling_kg=_optional_float(
                    st.session_state.get(f"psm_follow_note8_{item_no}_mfg", "")
                )
                or 0.0,
                storage_kg=_optional_float(
                    st.session_state.get(f"psm_follow_note8_{item_no}_storage", "")
                )
                or 0.0,
            )

    return PSMFollowupFacts(
        property_answers=property_answers,
        special_values_pct=special_values,
        note8_answer=note8_answer,
        note8_exclusions=note8_exclusions,
    )


def render_psm_followup_panel(intake) -> None:
    """Render only facts that can change the PSM Stage-1 decision."""
    base = assess_psm(intake)
    if not base.db_ready:
        return

    requirements = detect_followup_requirements(intake, base)

    st.markdown("---")
    st.markdown("## 🧮 PSM 후속확인 · R 재계산")
    st.caption(
        "위 1차 선별에서 자동으로 확정할 수 없었던 물성·특수 성분조건을 여기서 확인합니다. "
        "입력한 답은 별표 13 계산에 다시 반영되며, 모르는 값은 추정하지 않습니다."
    )

    if requirements.property_items:
        st.markdown("### 1) 별표 13 제1·2호 물성 확인")
        st.info(
            "CAS만으로 인화성 가스·인화성 액체 해당 여부를 자동 확정하지 않습니다. "
            "회사 SDS와 실제 공정조건을 확인해 답해 주세요."
        )
        for item_no in requirements.property_items:
            label = _property_label(item_no)
            with st.container(border=True):
                st.markdown(f"**별표 13 제{item_no}호 · {label}**")
                answer = st.radio(
                    f"사업장에서 {label}에 해당하는 물질을 제조·취급·저장합니까?",
                    ["선택하세요", "아니오", "예", "모름"],
                    horizontal=True,
                    key=f"psm_follow_property_{item_no}",
                )
                if answer == "예":
                    st.write("하루 최대량을 **kg**로 입력하세요. 해당하지 않는 구분은 `0`을 직접 입력합니다.")
                    c1, c2 = st.columns(2)
                    c1.text_input(
                        "최대 제조·취급량 (kg/일)",
                        key=f"psm_follow_property_{item_no}_mfg",
                        placeholder="예: 2500 또는 0",
                    )
                    c2.text_input(
                        "최대 저장량 (kg)",
                        key=f"psm_follow_property_{item_no}_storage",
                        placeholder="예: 150000 또는 0",
                    )
                elif answer == "모름":
                    st.warning("모르는 상태에서는 제1·2호를 자동으로 비해당 처리하지 않습니다.")

    if requirements.special_items:
        st.markdown("### 2) 특수 성분조건 확인")
        for item_no in requirements.special_items:
            if item_no == 23:
                title = "별표 13 제23호 · 발연황산"
                prompt = "삼산화황(SO₃) 중량%"
                help_text = "65% 이상 80% 미만이면 제23호 조건을 충족합니다. 일반 제품 함량(%)과 혼동하지 마세요."
            else:
                title = "별표 13 제42호 · 니트로셀룰로오스"
                prompt = "질소 함유량%"
                help_text = "12.6% 이상이면 제42호 조건을 충족합니다."
            with st.container(border=True):
                st.markdown(f"**{title}**")
                st.text_input(
                    prompt,
                    key=f"psm_follow_special_{item_no}",
                    placeholder="확인한 숫자만 입력",
                    help=help_text,
                )
                st.caption(help_text)

    preliminary_facts = _build_facts(requirements, include_note8=False)
    preliminary = reassess_psm_with_followup(intake, preliminary_facts, base)

    if preliminary.note8_required:
        st.markdown("### 3) 별표 13 비고 제8호 · 전문 가스 저장·판매시설")
        st.write(
            "현재 재계산 R이 1 이상이고 대상업종 트리거가 별도로 확인되지 않아, "
            "규정량에서 제외되는 전문 가스 저장·판매시설 수량이 있는지 확인해야 합니다."
        )
        note8_answer = st.radio(
            "R에 포함된 가스 중 '가스를 전문으로 저장·판매하는 시설 내의 가스'가 있습니까?",
            ["선택하세요", "아니오", "예", "모름"],
            horizontal=True,
            key="psm_follow_note8",
        )
        if note8_answer == "예":
            item_options = [line.legal_item_no for line in preliminary.ratio_lines]
            label_map = {
                line.legal_item_no: f"제{line.legal_item_no}호 {line.legal_substance}"
                for line in preliminary.ratio_lines
            }
            selected = st.multiselect(
                "전문 저장·판매시설 수량이 포함된 별표 13 항목",
                options=item_options,
                format_func=lambda value: label_map.get(value, f"제{value}호"),
                key="psm_follow_note8_items",
            )
            for item_no in selected:
                line = next(line for line in preliminary.ratio_lines if line.legal_item_no == item_no)
                with st.container(border=True):
                    st.markdown(f"**{label_map[item_no]}**")
                    st.caption(
                        f"현재 계산수량: 제조·취급 {line.manufacture_handling_kg:g} kg / 저장 {line.storage_kg:g} kg"
                    )
                    c1, c2 = st.columns(2)
                    c1.text_input(
                        "이 중 제외할 제조·취급량 (kg)",
                        key=f"psm_follow_note8_{item_no}_mfg",
                        placeholder="없으면 0",
                    )
                    c2.text_input(
                        "이 중 제외할 저장량 (kg)",
                        key=f"psm_follow_note8_{item_no}_storage",
                        placeholder="없으면 0",
                    )
            st.warning(
                "비고 제8호 제외수량은 전문 저장·판매시설에 실제 속하는 수량만 입력해야 합니다. "
                "현재 계산수량보다 큰 값은 엔진이 거부합니다."
            )
        elif note8_answer == "모름":
            st.warning("확인될 때까지 수량기준 최종판정은 보류됩니다.")

    final_facts = _build_facts(requirements, include_note8=True)
    result = reassess_psm_with_followup(intake, final_facts, base)

    st.markdown("### PSM 재계산 결과")
    c1, c2 = st.columns(2)
    c1.metric("후속확인 전 R", f"{result.r_before_note8:.4f}")
    c2.metric("현재 최종 R", f"{result.r_value:.4f}")

    if result.status == "APPLICABLE_CANDIDATE":
        st.success(f"**{result.label}**")
        if result.industry_trigger:
            if base.industry_code == "20202":
                st.write("• KSIC 20202 조건과 별표 13 제1·2호 물성 확인을 함께 반영해 대상업종 트리거를 확인했습니다.")
            else:
                st.write(f"• 대상업종 트리거: KSIC {base.industry_code} {base.industry_match}")
        if result.quantity_trigger:
            st.write(f"• 규정량 트리거: 비고 제7호 계산 R = {result.r_value:.4f} ≥ 1.0")
        st.write("• 다음 단계: 실제 관련 설비가 시행령 제43조제2항의 제외설비인지 확인합니다.")
    elif result.status == "NO_TRIGGER_IN_CHECKED_SCOPE":
        st.info("**현재 확인 범위 내 PSM 적용 트리거가 확인되지 않았습니다.**")
        st.write("대상업종 조건과 별표 13 물성·특수조건 및 현재 R 계산까지 확인한 결과입니다.")
    else:
        st.warning(f"**{result.label}**")

    if result.blockers:
        st.markdown("**아직 확인할 항목**")
        for blocker in result.blockers:
            st.write(f"• {blocker}")

    with st.expander("재계산된 별표 13 R 근거", expanded=False):
        if result.ratio_lines:
            frame = pd.DataFrame([asdict(line) for line in result.ratio_lines])
            st.dataframe(frame, width="stretch", hide_index=True)
        else:
            st.caption("현재 R에 포함된 별표 13 계산행이 없습니다.")
        st.info("법적 근거: 「산업안전보건법 시행령」 제43조 및 별표 13 비고 제6호·제7호·제8호")
