from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

import pandas as pd
import streamlit as st

from engine.cap_engine import assess_cap
from engine.cap_final_decision import assess_cap_final, exemption_by_key, exemption_options
from engine.cap_holding import (
    app4_db_ready,
    assess_cap_holding,
    build_cap_facility_workbook,
    read_cap_facility_workbook,
)
from engine.cap_holding_screen import screen_facility_stage
from engine.cap_quick_holding import compare_confirmed_declared_holding
from engine.cap_sds_app1 import app1_sds_options, assess_sds_app1_row
from engine.consulting_guidance import get_guide
from engine.inventory import inventory_preview, read_intake_workbook, validate_intake
from engine.kosha_msds import credential_status as kosha_credential_status, lookup_by_cas
from engine.psm_engine import PSM_EXCLUSION_QUESTIONS, assess_psm


CAP_FULL = "화학사고예방관리계획서"
PSM_FULL = "공정안전보고서(PSM)"

st.set_page_config(page_title=f"{PSM_FULL} · {CAP_FULL} 사전진단", page_icon="✅", layout="wide")
st.markdown(
    """
    <style>
    .block-container { max-width: 1160px; }
    div[data-testid="stSelectbox"] label p,
    div[data-testid="stRadio"] label p,
    div[data-testid="stMultiSelect"] label p,
    div[data-testid="stCheckbox"] label p {
        font-size: 1.02rem !important;
        font-weight: 620 !important;
    }
    .consult-section-banner {
        padding: 0.9rem 1.05rem;
        border-radius: 0.75rem;
        margin: 1.55rem 0 0.85rem 0;
        font-size: 1.42rem;
        font-weight: 760;
        line-height: 1.35;
        border: 1px solid transparent;
    }
    .consult-section-psm {
        background: #fff0df;
        border-color: #efb36f;
        color: #693900;
    }
    .consult-section-cap {
        background: #fff7d6;
        border-color: #efd77a;
        color: #594700;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


_psm_exclusion_guide = get_guide("PSM_EXCLUDED_FACILITY")
EXCLUSION_LABELS = [
    "해당 없음",
    *list(_psm_exclusion_guide.what_to_check if _psm_exclusion_guide else ()),
    "모름",
]


def _table(df: pd.DataFrame, max_rows: int = 50) -> None:
    if df is None or df.empty:
        st.caption("표시할 내용이 없습니다.")
        return
    st.dataframe(df.head(max_rows), width="stretch", hide_index=True)
    if len(df) > max_rows:
        st.caption(f"전체 {len(df):,}행 중 앞 {max_rows:,}행만 표시합니다.")


def _is_psm_exclusion_question(text: str) -> bool:
    return text in PSM_EXCLUSION_QUESTIONS


def _is_psm_note8_question(text: str) -> bool:
    compact = str(text or "").replace(" ", "")
    return "가스를전문으로저장·판매하는시설" in compact or "가스를전문으로저장ㆍ판매하는시설" in compact


def _cap_text(value: object) -> str:
    return str(value or "").replace("화사계", CAP_FULL)


def _num(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _sds_unmatched_explanation(text: str) -> str:
    compact = re.sub(r"[^0-9A-Za-z가-힣]", "", str(text or "")).lower()
    if "눈손상" in compact or "눈자극" in compact:
        return "별표 1의 유해·위험성 그룹에는 눈 손상성/눈 자극성 그룹이 없어 규정수량 선택에 사용하지 않습니다."
    if "생식독성" in compact and "구분2" in compact:
        return "별표 1의 생식독성물질 규정수량은 구분 1에 대해 설정되어 있어 생식독성 구분 2는 별표 1 규정수량 선택에 사용하지 않습니다."
    if "특정표적장기독성1회노출" in compact and "구분3" in compact:
        return "별표 1의 특정표적장기독성(1회 노출)은 구분 1에 대해 규정수량이 설정되어 있어 구분 3은 규정수량 선택에 사용하지 않습니다."
    return "SDS에는 기재되어 있지만 현재 승인된 별표 1의 유해성 그룹·구분과 정확히 연결되지 않아 자동 규정수량 선택에는 사용하지 않았습니다."


def _cap_basis(hit: dict[str, object]) -> str:
    source = str(hit.get("source_key", ""))
    item = str(hit.get("item_no", "-") or "-")
    if source == "CAP_QTY_APP3":
        return f"사고대비물질별 규정수량(별표 3) 제{item}호"
    if source == "CAP_QTY_APP2":
        return f"인체·생태유해성 물질별 규정수량(별표 2) 제{item}호"
    return f"규정수량 기준 제{item}호"


def _cap_direct_preview(intake, legal_hits: list[dict[str, object]]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    seen: set[tuple[int, str, str]] = set()
    for hit in legal_hits:
        row_no = int(hit.get("row_no") or 0)
        source = str(hit.get("source_key", ""))
        item_no = str(hit.get("item_no", ""))
        key = (row_no, source, item_no)
        if row_no <= 0 or row_no > len(intake.chemicals) or key in seen:
            continue
        seen.add(key)
        item = intake.chemicals.iloc[row_no - 1]
        rows.append(
            {
                "제품명": item.get("제품명", ""),
                "CAS No.": item.get("CAS No.", ""),
                "확인된 법적 근거": _cap_basis(hit),
                "회사 입력 최대 동시보유량": item.get("최대 동시보유량(알면 입력)", ""),
                "단위": item.get("수량 단위", ""),
                "하위 규정수량(ton)": hit.get("lower_quantity_ton"),
                "상위 규정수량(ton)": hit.get("upper_quantity_ton"),
            }
        )
    return pd.DataFrame(rows)


def _render_guide(key: str, *, show_title: bool = True, compact: bool = False) -> None:
    guide = get_guide(key)
    if guide is None:
        return
    with st.container(border=True):
        if show_title:
            st.markdown(f"**{guide.title}**")
        if guide.why_needed:
            st.write(f"**왜 확인하나요?** {guide.why_needed}")
        st.write(guide.plain_language)
        if guide.what_to_check and not compact:
            st.markdown("**회사에서 확인할 것**")
            for value in guide.what_to_check:
                st.write(f"• {value}")
        if guide.example:
            st.write(f"**예시** {guide.example}")
        if guide.legal_basis:
            st.info(f"법적 근거: {guide.legal_basis}")
        if getattr(guide, "legal_hierarchy", ()):
            st.markdown("**법령이 다른 규정에 기준을 맡긴 경우**")
            for value in guide.legal_hierarchy:
                st.write(f"• {value}")
        if getattr(guide, "resolved_detail", ""):
            st.success(guide.resolved_detail)
        if getattr(guide, "source_status", ""):
            st.caption(f"근거 확인상태: {guide.source_status}")
        if guide.decision_effect and not compact:
            st.write(f"**이 답변이 판정에 미치는 영향** {guide.decision_effect}")
        if guide.if_unknown:
            st.caption(guide.if_unknown)


def _status_card(title: str, status: str, *, value: str = "", explanation: str = "") -> None:
    with st.container(border=True):
        st.markdown(f"### {title}")
        st.caption("현재 단계")
        st.markdown(f"#### {status}")
        if value:
            st.markdown(f"**{value}**")
        if explanation:
            st.write(explanation)


def _section_header(title: str, theme: str) -> None:
    css_class = "consult-section-psm" if theme == "psm" else "consult-section-cap"
    st.markdown(
        f'<div class="consult-section-banner {css_class}">{title}</div>',
        unsafe_allow_html=True,
    )


def _sds_key(row_no: int, suffix: str) -> str:
    return f"sds_app1_{int(row_no)}_{suffix}"


def _kosha_key(cas: str) -> str:
    return "kosha_msds_" + str(cas or "").replace("-", "_")


def _single_substance_candidate(item: pd.Series | None) -> bool:
    if item is None:
        return False
    pct = _num(item.get("함량(%)"))
    return pct is not None and abs(pct - 100.0) < 1e-9


def _exemption_format(value: str) -> str:
    if value == "UNANSWERED":
        return "선택하세요"
    if value == "NONE":
        return "법 제23조제1항 단서 및 고시 제9조 작성 면제 시설에 해당하지 않습니다"
    if value == "PARTIAL":
        return "법 제23조제1항 단서 또는 고시 제9조 작성 면제 시설이 일부 취급시설에만 해당할 수 있습니다"
    if value == "UNKNOWN":
        return "잘 모르겠습니다"
    option = exemption_by_key(value)
    return option.label if option else value


def _major_format(value: str) -> str:
    return {
        "UNANSWERED": "선택하세요",
        "YES": "예, 상위 규정수량 이상을 취급하는 개별 취급시설이 있습니다",
        "NO": "아니오, 개별 시설은 상위 규정수량 미만입니다",
        "UNKNOWN": "잘 모르겠습니다",
    }.get(value, value)


def _is_upper_row(row: dict[str, Any]) -> bool:
    status = str(row.get("status", ""))
    band = str(row.get("quantity_band", ""))
    return "UPPER" in status or "상위 규정수량 이상" in band


def _is_lower_row(row: dict[str, Any]) -> bool:
    status = str(row.get("status", ""))
    band = str(row.get("quantity_band", ""))
    return "LOWER" in status or "하위 이상" in band


st.title(f"{PSM_FULL} · {CAP_FULL} 사전진단")
st.caption("회사 Excel을 한 번 올리면 두 제도를 각각 자동 선별하고, 정말 필요한 정보만 추가로 확인합니다.")
st.info(
    f"{PSM_FULL}와 {CAP_FULL}는 서로 다른 법적 의무이므로 한 사업장이 둘 다 대상이 될 수 있습니다. "
    "프로그램은 두 제도를 각각 판정합니다."
)

uploaded = st.file_uploader(
    "회사 입력파일 업로드 (.xlsx)",
    type=["xlsx"],
    help="기존 PSM_CAP_테스트용_회사입력파일.xlsx도 그대로 사용할 수 있습니다.",
)
if uploaded is None:
    st.caption("일반 사용자는 이 화면만 사용하면 됩니다. 규정DB 관리와 법령근거 화면은 관리자·검토자용입니다.")
    st.stop()

try:
    intake = read_intake_workbook(uploaded.getvalue())
except Exception as exc:
    st.error(f"입력파일을 읽지 못했습니다: {type(exc).__name__}: {exc}")
    st.stop()

issues = validate_intake(intake)
if issues:
    st.error("입력파일에서 먼저 보완할 항목이 있습니다.")
    for issue in issues:
        st.write(f"• {issue}")
    st.stop()

st.session_state["intake"] = intake
c1, c2 = st.columns(2)
c1.metric("사업장", str(intake.business.get("사업장명") or "미입력"))
c2.metric("입력한 화학물질", f"{len(intake.chemicals):,}개")
with st.expander("업로드한 내용 확인", expanded=False):
    _table(inventory_preview(intake), 40)

psm = assess_psm(intake)
cap = assess_cap(intake)
cap_screen = screen_facility_stage(intake)
app1_options = app1_sds_options()
app1_option_map = {option.key: option for option in app1_options}

psm_exclusion_choice = str(st.session_state.get("simple_psm_exclusion", "선택하세요"))
psm_note8_answer = str(st.session_state.get("simple_psm_note8", "선택하세요"))
cap_holding_choice = str(st.session_state.get("simple_cap_holding_basis", "선택하세요"))

quick_cap = None
if (
    cap_holding_choice == "예, 법정 산정방식으로 계산한 값입니다"
    and app4_db_ready()
    and cap_screen.ready
    and cap_screen.row_numbers
    and not cap_screen.blockers
):
    quick_cap = compare_confirmed_declared_holding(intake, cap_screen.legal_hits)

facility_result = None
facility_frame = None
facility_upload_error = ""
facility_upload_state = st.session_state.get("simple_cap_facility_upload")
if (
    cap_holding_choice in {"아니오, 단순 재고량 또는 임의값입니다", "잘 모르겠습니다"}
    and facility_upload_state is not None
    and app4_db_ready()
    and cap_screen.ready
    and cap_screen.row_numbers
    and not cap_screen.blockers
):
    try:
        facility_bytes = facility_upload_state.getvalue() if hasattr(facility_upload_state, "getvalue") else bytes(facility_upload_state)
        facility_frame = read_cap_facility_workbook(facility_bytes)
        facility_result = assess_cap_holding(
            intake=intake,
            facilities=facility_frame,
            legal_hits=cap_screen.legal_hits,
            required_row_numbers=cap_screen.row_numbers,
        )
    except Exception as exc:
        facility_upload_error = f"시설정보 입력서를 읽거나 계산하지 못했습니다: {type(exc).__name__}: {exc}"

direct_quantity_rows = list(
    (getattr(quick_cap, "comparison_rows", []) if quick_cap is not None else [])
    or (getattr(facility_result, "comparison_rows", []) if facility_result is not None else [])
    or []
)
direct_threshold_upper = any(_is_upper_row(row) for row in direct_quantity_rows)
direct_threshold_lower = any(_is_lower_row(row) for row in direct_quantity_rows)

kosha_state = kosha_credential_status()
app1_runtime: list[dict[str, Any]] = []
app1_results = []
for fallback in cap.app1_required_rows:
    row_no = int(fallback.get("row_no") or 0)
    cas = str(fallback.get("cas") or "")
    item = intake.chemicals.iloc[row_no - 1] if 0 < row_no <= len(intake.chemicals) else None
    auto = None
    if _single_substance_candidate(item) and kosha_state.get("status") == "READY" and cas:
        cache_key = _kosha_key(cas)
        if cache_key not in st.session_state:
            st.session_state[cache_key] = lookup_by_cas(cas)
        auto = st.session_state.get(cache_key)

    manual_mode = bool(st.session_state.get(_sds_key(row_no, "manual_mode"), False))
    auto_confirmed = bool(st.session_state.get(_sds_key(row_no, "auto_confirmed"), False))
    manual_selected = st.session_state.get(_sds_key(row_no, "classes"), []) or []
    verified_none = bool(st.session_state.get(_sds_key(row_no, "none"), False)) if manual_mode else False

    selected = list(manual_selected) if manual_mode else []
    if not manual_mode and auto is not None and getattr(auto, "can_prefill_app1", False) and auto_confirmed:
        selected = list(auto.app1_option_keys)

    row_holding = str(st.session_state.get(_sds_key(row_no, "holding"), "선택하세요"))
    holding_confirmed = (
        cap_holding_choice == "예, 법정 산정방식으로 계산한 값입니다"
        or row_holding == "예, 법정 최대보유량입니다"
    )
    result = assess_sds_app1_row(
        intake,
        row_no,
        selected,
        verified_no_app1_class=verified_none,
        holding_confirmed=holding_confirmed,
    )
    if auto is not None and getattr(auto, "can_prefill_app1", False) and not auto_confirmed and not manual_mode:
        result.status = "HOLD"
        result.label = "회사/제품 SDS와 자동조회 결과의 일치 확인 필요"
        result.blockers = [
            "KOSHA 자료는 참고자료이므로, 자동조회된 제2항 분류가 현재 회사/제품 SDS 제2항과 일치하는지 확인해야 합니다."
        ]
    app1_results.append(result)
    app1_runtime.append({"fallback": fallback, "item": item, "auto": auto, "result": result})

quantity_rows: list[dict[str, Any]] = []
unresolved: list[str] = []
if not cap_screen.ready:
    unresolved.extend(cap_screen.blockers or ["별표 2·3 규정수량 DB 확인 필요"])
elif cap_screen.blockers:
    unresolved.extend(cap_screen.blockers)

if cap_screen.row_numbers:
    if cap_holding_choice == "예, 법정 산정방식으로 계산한 값입니다":
        if quick_cap is not None:
            quantity_rows.extend(quick_cap.comparison_rows)
            if quick_cap.status == "HOLD":
                unresolved.extend(quick_cap.blockers)
    elif facility_result is not None:
        quantity_rows.extend(facility_result.comparison_rows)
        if facility_result.status in {"HOLD", "DB_NOT_READY"}:
            unresolved.extend(facility_result.blockers or [facility_result.label])
    else:
        unresolved.append("별표 2·3 직접대상 물질의 법정 사업장 최대보유량 계산을 위한 시설정보 입력서 작성·재업로드 필요")

if cap.scope_candidates:
    unresolved.append(f"CAS 하나로 확정할 수 없는 포괄 물질범위 검토대상 {len(cap.scope_candidates)}건 확인 필요")

for result in app1_results:
    if result.status in {"HOLD", "DB_NOT_READY"}:
        unresolved.extend(result.blockers or [result.label])
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

unresolved = list(dict.fromkeys(v for v in unresolved if str(v).strip()))
threshold_upper = any(_is_upper_row(row) for row in quantity_rows)
threshold_lower = any(_is_lower_row(row) for row in quantity_rows)

exemption_choice = str(st.session_state.get("cap_final_exemption", "UNANSWERED"))
if exemption_choice in {item.key for item in exemption_options()}:
    exemption_answer = "EXEMPT"
elif exemption_choice in {"NONE", "PARTIAL", "UNKNOWN", "UNANSWERED"}:
    exemption_answer = exemption_choice
else:
    exemption_answer = "UNANSWERED"
exemption_confirmed = bool(st.session_state.get("cap_final_exemption_all", False))
major_answer = str(st.session_state.get("cap_major_facility", "UNANSWERED"))

final_cap = assess_cap_final(
    quantity_rows,
    unresolved_blockers=unresolved,
    exemption_answer=exemption_answer,
    exemption_key=exemption_choice if exemption_answer == "EXEMPT" else "",
    exemption_all_relevant_confirmed=exemption_confirmed,
    major_facility_answer=major_answer,
)

psm_industry_trigger = bool(psm.industry_match and psm.industry_code != "20202")
psm_note8_relevant = bool(psm.r_value is not None and psm.r_value >= 1 and not psm_industry_trigger)

if psm.r_value is None:
    psm_status = _cap_text(psm.label)
    psm_value = ""
    psm_explanation = "「산업안전보건법 시행령」 별표 13 비고 제7호의 합산한 값(R) 산정에 필요한 정보가 더 필요합니다."
elif psm.r_value >= 1:
    psm_value = f"합산한 값(R) = {psm.r_value:.4f}"
    if psm_note8_relevant and psm_note8_answer in {"선택하세요", "잘 모르겠습니다"}:
        psm_status = "별표 13 유해·위험물질 규정량 기준 해당 · 비고 제8호 적용 여부 확인 필요"
        psm_explanation = "별표 13 비고 제8호가 적용되면 해당 가스 수량은 규정량 산정에서 제외되므로, 비고 제7호의 합산한 값(R)을 확정하기 전에 확인합니다."
    elif psm_note8_relevant and psm_note8_answer == "예, 해당하는 가스가 있습니다":
        psm_status = "별표 13 비고 제8호 제외수량 확인 필요"
        psm_explanation = "별표 13 비고 제8호에 따라 전문 저장·판매시설 내 해당 가스는 규정량 산정에서 제외되므로, 해당 수량을 분리한 뒤 비고 제7호의 합산한 값(R)을 다시 산정해야 합니다."
    elif psm_exclusion_choice == "해당 없음":
        psm_status = "공정안전보고서 제출 대상 기준 해당"
        psm_explanation = "별표 13 유해·위험물질 규정량 기준에 해당하고, 「산업안전보건법 시행령」 제43조제2항 제외설비에 해당하지 않는 것으로 사용자가 확인했습니다."
    elif psm_exclusion_choice not in {"선택하세요", "모름"}:
        psm_status = "시행령 제43조제2항 제외설비 적용범위 확인 필요"
        psm_explanation = "별표 13 유해·위험물질 규정량 기준에는 해당하지만 선택한 제43조제2항 제외설비의 실제 적용범위를 확인해야 합니다."
    else:
        psm_status = "별표 13 유해·위험물질 규정량 기준 해당 · 제43조제2항 제외설비 확인 필요"
        psm_explanation = "별표 13 비고 제7호의 합산한 값(R)이 1 이상이어도 시행령 제43조제2항의 제외설비 여부를 함께 확인해야 합니다."
else:
    psm_status = "별표 13 비고 제7호 합산한 값(R) < 1"
    psm_value = f"합산한 값(R) = {psm.r_value:.4f}"
    psm_explanation = "다른 적용조건이나 미확인 정보가 있으면 추가 검토합니다."

cap_status = final_cap.label
if final_cap.status == "REQUIRED_GROUP_1":
    cap_explanation = "법정 작성면제 여부와 주요취급시설 요건까지 확인하여 작성수준을 1군 사업장으로 확인했습니다."
elif final_cap.status == "REQUIRED_GROUP_2":
    cap_explanation = "법정 작성면제 여부까지 확인하여 작성수준을 2군 사업장으로 확인했습니다."
elif final_cap.status == "NOT_REQUIRED":
    cap_explanation = "법령상 작성면제 사유가 확인되었습니다. 구체적인 사유와 법적 근거는 아래 결과에서 확인합니다."
else:
    cap_explanation = final_cap.next_question or "표시된 미확인 항목을 확인하면 최종 작성 여부를 결정합니다."

st.markdown("## 지금까지의 결과를 한눈에 보기")
left, right = st.columns(2, gap="large")
with left:
    _status_card(PSM_FULL, psm_status, value=psm_value, explanation=psm_explanation)
with right:
    _status_card(CAP_FULL, cap_status, explanation=cap_explanation)

_section_header(f"{PSM_FULL} · 「산업안전보건법 시행령」 제43조 제출 대상 요건 확인", "psm")
if psm.r_value is not None:
    st.write(
        f"**별표 13 비고 제7호 합산한 값(R) = {psm.r_value:.4f}** 입니다. "
        "이 값은 「산업안전보건법 시행령」 별표 13 비고 제7호에 따른 합산한 값(R)입니다. 시행령 제43조제1항과 제2항의 요건을 함께 확인해야 공정안전보고서 제출 대상 여부가 확정됩니다."
    )
    with st.expander("별표 13 비고 제7호 합산한 값(R) · 법적 근거 보기", expanded=False):
        _render_guide("PSM_R_RATIO", compact=True)

exclusion_questions = [q for q in psm.questions if _is_psm_exclusion_question(q)]
raw_other_psm_questions = [q for q in psm.questions if not _is_psm_exclusion_question(q)]
note8_questions = [q for q in raw_other_psm_questions if _is_psm_note8_question(q)]
other_psm_questions = [q for q in raw_other_psm_questions if not _is_psm_note8_question(q)]

if psm_industry_trigger:
    note8_questions = []

if exclusion_questions:
    st.markdown("#### 공정안전보고서 확인: 관련 공정·설비가 법정 제외설비에 해당합니까?")
    st.write("법에서 정한 유형과 확인된 하위 고시 내용을 함께 보여드립니다. 모르면 추정하지 말고 '모름'을 선택하세요.")
    _render_guide("PSM_EXCLUDED_FACILITY", show_title=False)
    exclusion = st.selectbox(
        "공정안전보고서 제외설비 선택",
        ["선택하세요", *EXCLUSION_LABELS],
        key="simple_psm_exclusion",
        label_visibility="collapsed",
    )
    if exclusion == "해당 없음" and psm.r_value is not None and psm.r_value >= 1:
        reasons: list[str] = []
        if psm_industry_trigger:
            reasons.append(f"입력된 KSIC {psm.industry_code}는 「산업안전보건법 시행령」 제43조제1항 각 호의 사업 종류({psm.industry_match})에 해당합니다.")
        reasons.append(f"별표 13 비고 제7호의 합산한 값(R)이 {psm.r_value:.4f}로 1 이상입니다.")
        reasons.append("법정 제외설비 확인에서 '해당 없음'을 선택했습니다.")
        with st.container(border=True):
            st.markdown("### 🔴 공정안전보고서 판정 결과")
            st.markdown("#### **현재 입력 기준: 공정안전보고서 제출 대상 기준 해당**")
            st.markdown("**왜 이런 결과가 나왔나요?**")
            for reason in reasons:
                st.write(f"• {reason}")
            st.write(
                "따라서 현재 확인 범위에서는 시행령 제43조제1항의 제출 대상 기준에 해당하며, "
                "다만 실제 보고서 작성에 들어가기 전에는 어느 공정·설비가 대상범위에 포함되는지 확인해야 합니다."
            )
    elif exclusion not in {"선택하세요", "해당 없음", "모름"}:
        st.warning("선택한 제외유형이 이번 물질과 관련된 공정·설비에 실제 적용되는지 증빙 확인이 필요합니다.")
    elif exclusion == "모름":
        st.warning("제외설비 여부가 확인될 때까지 공정안전보고서 판정은 보류됩니다.")

if note8_questions:
    st.markdown("#### 공정안전보고서 추가 확인: 규정량 계산에서 제외되는 전문 가스 저장·판매시설이 있습니까?")
    st.write(
        "산업안전보건법 시행령 별표 13 비고 제8호는 **가스를 전문으로 저장·판매하는 시설 내의 가스**를 규정량 산정에서 제외합니다. "
        "따라서 별표 13 유해·위험물질 규정량 기준으로 제출 대상 여부를 확인하는 경우에만 이 사실을 추가로 확인합니다."
    )
    st.info("법적 근거: 「산업안전보건법 시행령」 별표 13 비고 제8호")
    note8_answer = st.radio(
        "전문 가스 저장·판매시설 여부",
        ["선택하세요", "아니오, 해당하는 가스가 없습니다", "예, 해당하는 가스가 있습니다", "잘 모르겠습니다"],
        key="simple_psm_note8",
        label_visibility="collapsed",
    )
    if note8_answer == "아니오, 해당하는 가스가 없습니다":
        st.success("별표 13 비고 제8호에 따른 제외수량 없이 현재 비고 제7호 합산한 값(R)을 적용합니다.")
    elif note8_answer == "예, 해당하는 가스가 있습니다":
        st.warning(
            "해당 가스는 별표 13 비고 제8호에 따라 규정량 산정에서 제외될 수 있습니다. 현재 회사 입력파일은 물질별 수량을 시설별로 분리하지 않았으므로, "
            "어느 가스가 어느 전문 저장·판매시설에 얼마만큼 있는지 확인한 뒤 비고 제7호의 합산한 값(R)을 다시 산정해야 합니다."
        )
    elif note8_answer == "잘 모르겠습니다":
        st.warning("별표 13 비고 제8호 적용 여부가 확인될 때까지 공정안전보고서 제출 대상 여부 확인을 보류합니다.")

if other_psm_questions:
    st.markdown("#### 공정안전보고서에서 추가로 확인해야 하는 특수조건")
    _render_guide("PSM_SPECIAL_CONDITION", show_title=False, compact=True)
    with st.expander(f"실제 확인 질문 {len(other_psm_questions)}개", expanded=False):
        for question in other_psm_questions:
            st.write(f"• {question}")

with st.expander("공정안전보고서 계산 근거 보기 · 검토자용", expanded=False):
    if psm.ratio_lines:
        ratio_df = pd.DataFrame([asdict(row) for row in psm.ratio_lines])
        st.table(ratio_df.head(30))
        if len(ratio_df) > 30:
            st.caption(f"전체 {len(ratio_df):,}개 계산행 중 앞 30개를 표시합니다.")
    for blocker in psm.blockers:
        st.write(f"• {blocker}")

_section_header(f"{CAP_FULL} · 물질기준과 최대보유량 확인", "cap")
if not cap_screen.ready:
    st.error("시스템 규정수량 DB가 준비되지 않았습니다. 일반 사용자가 해결할 항목이 아니므로 관리자 확인이 필요합니다.")
elif cap_screen.row_numbers:
    st.info(
        f"업로드 물질 중 **{len(cap_screen.row_numbers)}개가 물질별 직접 규정수량 기준에 연결**되었습니다. "
        "이 물질은 법정 사업장 최대보유량을 규정수량과 비교합니다."
    )
    _table(_cap_direct_preview(intake, cap_screen.legal_hits), 30)

    if cap_screen.blockers:
        st.warning("같은 물질이라도 농도·성상 조건에 따라 적용 규정수량이 달라질 수 있어 먼저 확인이 필요합니다.")
        _render_guide("CAP_SPECIAL_CONDITION", show_title=False, compact=True)
        for blocker in cap_screen.blockers:
            st.write(f"• {blocker}")
    elif app4_db_ready():
        st.markdown("#### 화학사고예방관리계획서 확인: Excel의 '최대 동시보유량' 값들이 법에서 말하는 사업장 최대보유량입니까?")
        _render_guide("CAP_MAX_HOLDING", show_title=False)
        holding_choice = st.radio(
            "최대보유량 산정방식 확인",
            ["선택하세요", "예, 법정 산정방식으로 계산한 값입니다", "아니오, 단순 재고량 또는 임의값입니다", "잘 모르겠습니다"],
            key="simple_cap_holding_basis",
            label_visibility="collapsed",
        )
        if holding_choice == "예, 법정 산정방식으로 계산한 값입니다":
            current_quick = compare_confirmed_declared_holding(intake, cap_screen.legal_hits)
            if current_quick.status == "HOLD":
                st.warning(_cap_text(current_quick.label))
                for blocker in current_quick.blockers:
                    st.write(f"• {blocker}")
            elif current_quick.status in {"UPPER_CANDIDATE", "LOWER_CANDIDATE"}:
                with st.container(border=True):
                    st.markdown("### 🔴 화학사고예방관리계획서 최대보유량·규정수량 비교 결과")
                    st.markdown(f"#### **{_cap_text(current_quick.label)}**")
                    st.write("이 결과는 **유해화학물질별 최대보유량과 상위·하위 규정수량을 비교한 결과**입니다. 화학사고예방관리계획서 작성 필요 여부와 작성수준은 법정 작성면제 여부와 주요취급시설 요건까지 확인해 결정합니다.")
                    if current_quick.status == "LOWER_CANDIDATE":
                        st.write("또한 아직 별표 1 검토가 필요한 다른 물질이 있다면, 그 물질이 상위 규정수량에 도달하는지에 따라 1군·2군 구분이 달라질 수 있습니다.")
            else:
                st.info(_cap_text(current_quick.label))
            if current_quick.comparison_rows:
                with st.expander("규정수량 비교 근거 보기", expanded=False):
                    _table(pd.DataFrame(current_quick.comparison_rows), 60)
        elif holding_choice in {"아니오, 단순 재고량 또는 임의값입니다", "잘 모르겠습니다"}:
            st.warning("현재 값으로 법적 최대보유량을 확정하지 않습니다. 아래 시설정보를 받아 「유해화학물질의 규정수량에 관한 규정」 별표 4 방식으로 다시 계산합니다.")
            with st.container(border=True):
                st.markdown("### 시설정보 입력서 사용방법")
                st.write("① 아래 입력서를 다운로드합니다.")
                st.write("② `01_CAP시설정보` 시트의 노란색 칸을 작성합니다. 같은 물질이 여러 시설에 있으면 **시설 하나당 한 줄**로 작성합니다.")
                st.write("③ 파일을 저장합니다.")
                st.write("④ **바로 아래 업로드 칸에 같은 파일을 다시 올립니다.**")
                st.write("⑤ 프로그램이 시설별 최대보유량을 계산·합산하고, 규정수량 비교와 최종판정을 **이 화면에서 그대로 계속**합니다.")
                st.success("별도의 '화학사고예방관리계획서 최대보유량' 화면으로 이동할 필요가 없습니다.")
            template = build_cap_facility_workbook(intake, cap_screen.row_numbers)
            st.download_button(
                "최대보유량 계산용 시설정보 입력서 다운로드",
                data=template,
                file_name="화학사고예방관리계획서_최대보유량_보완입력.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )
            facility_upload = st.file_uploader(
                "작성한 시설정보 입력서를 이곳에 다시 업로드해 주세요.",
                type=["xlsx"],
                key="simple_cap_facility_upload",
            )
            if facility_upload_error:
                st.error(facility_upload_error)
            elif facility_result is not None:
                if facility_frame is not None:
                    with st.expander("업로드한 시설정보 확인", expanded=False):
                        _table(facility_frame, 80)
                if facility_result.status in {"UPPER_CANDIDATE", "LOWER_CANDIDATE"}:
                    with st.container(border=True):
                        st.markdown("### 🔴 사업장 최대보유량 산정 결과")
                        st.markdown(f"#### **{_cap_text(facility_result.label)}**")
                elif facility_result.status == "HOLD":
                    st.warning(_cap_text(facility_result.label))
                else:
                    st.info(_cap_text(facility_result.label))
                if facility_result.facility_rows:
                    with st.expander("시설별 최대보유량 계산 근거", expanded=False):
                        _table(pd.DataFrame([asdict(row) for row in facility_result.facility_rows]), 100)
                if facility_result.comparison_rows:
                    with st.expander("규정수량 비교 결과", expanded=True):
                        _table(pd.DataFrame(facility_result.comparison_rows), 100)
                for blocker in facility_result.blockers:
                    st.write(f"• 확인 필요: {blocker}")
                if not facility_result.blockers and facility_result.comparison_rows:
                    st.success("시설정보 재계산이 완료되었습니다. 이 결과를 사용해 아래 화학사고예방관리계획서 판정을 계속합니다.")
    else:
        st.error("최대보유량 계산기준 DB가 준비되지 않았습니다. 관리자 확인이 필요합니다.")
else:
    st.info("별표 2·3의 직접 물질목록에서는 바로 연결된 물질이 없습니다. 필요한 물질은 아래 SDS 단계에서 계속 확인합니다.")

if cap.app1_required_rows:
    if direct_threshold_upper:
        _section_header(f"{CAP_FULL} · 규제물질 범위 확인을 위한 SDS 제2항 확인", "cap")
        st.info(
            "앞 단계에서 이미 **상위 규정수량 이상이 확인된 물질**이 있습니다. 따라서 이 SDS 확인은 '작성해야 하는지 처음부터 다시 판단'하기 위한 단계가 아니라, "
            "별표 1 대상이 되는 다른 물질과 보고서에 포함할 규제물질 범위를 확인하기 위한 보완 단계입니다."
        )
    elif direct_threshold_lower:
        _section_header(f"{CAP_FULL} · 1군·2군 구분 보완을 위한 SDS 제2항 확인", "cap")
        st.info(
            "앞 단계에서 이미 **하위 규정수량 이상이 확인된 물질**이 있습니다. 따라서 화학사고예방관리계획서 작성 필요 여부와 작성수준을 검토해야 하는 수량범위에 해당합니다. "
            "다만 법정 작성면제 여부 확인 전에는 최종 작성수준을 확정할 수 없고, 다른 미확인 물질이 상위 규정수량에 도달하면 1군·2군 구분이 달라질 수 있으므로 SDS 확인이 필요할 수 있습니다."
        )
    else:
        _section_header(f"{CAP_FULL} · 작성 여부 판정을 위한 SDS 제2항 확인", "cap")
        st.info(
            "앞 단계만으로 하위 규정수량 이상 물질이 아직 확인되지 않았기 때문에, 이 경우 SDS 제2항 확인이 실제 작성 여부 판정에 필요한 단계입니다."
        )

    st.info(
        "이 화면에서 말하는 별표 1~4는 모두 「유해화학물질의 규정수량에 관한 규정」의 별표입니다. "
        "별표 1은 유해·위험성 그룹별 규정수량, 별표 2는 인체·생태유해성 물질별 규정수량, 별표 3은 사고대비물질별 규정수량, 별표 4는 사업장 최대보유량 산정방법입니다."
    )
    st.write(
        "「유해화학물질의 규정수량에 관한 규정」 별표 3과 별표 2에서 직접 결론이 나지 않은 물질은 같은 규정 별표 1의 유해성·위험성 그룹을 확인합니다. "
        "**100% 단일물질이고 CAS가 있으면 한국산업안전보건공단 물질안전보건자료 조회 서비스를 먼저 자동조회**하고, "
        "혼합물·조회실패·불일치일 때만 회사 SDS를 직접 확인합니다."
    )
    st.info(
        "한국산업안전보건공단 화학물질정보는 MSDS 작성·검토를 위한 참고자료입니다. 따라서 자동조회 결과를 그대로 법적 사실로 확정하지 않고 "
        "현재 회사/제품 SDS 제2항과 일치함을 한 번 확인한 뒤 판정에 사용합니다."
    )
    with st.expander("혼합물의 함량(%)은 어떻게 판정하나요?", expanded=False):
        st.write(
            "혼합물이라고 해서 모든 물질에 공통으로 적용되는 '몇 % 이상이면 별표 1 적용' 같은 하나의 기준이 있는 것은 아닙니다. "
            "별표 2·3에 해당 물질의 **명시적인 함량기준**이 있으면 프로그램이 CAS와 함량(%)을 이용해 자동판정합니다. "
            "반면 별표 1은 혼합물 자체의 유해성·위험성 분류를 사용하므로 성분 CAS와 70% 같은 숫자만으로 순물질 분류를 그대로 적용하지 않습니다."
        )
        st.write(
            "별표 1 경로에서는 제품 SDS 제2항의 실제 혼합물 분류를 우선 사용합니다. 혼합물 분류에는 유해성 항목별 한계농도, 가산식, "
            "특정농도한계 또는 물리적 위험성 시험값 등이 관여할 수 있어 단일 성분함량 하나만으로 일괄 판정하면 잘못된 결과가 날 수 있습니다."
        )
        st.info(
            "관련 근거: 「유해화학물질의 규정수량에 관한 규정」 제3조 및 별표 1~3, "
            "「화학물질의 분류 및 표시 등에 관한 규정」 제6조 및 별표 1의 혼합물 분류기준"
        )
    if kosha_state.get("status") != "READY":
        st.warning(
            "한국산업안전보건공단 물질안전보건자료 조회 서비스 API 인증키가 아직 로컬 환경에 설정되지 않았습니다. "
            "`.env`의 `KOSHA_SERVICE_KEY`에 발급받은 키를 넣으면 CAS 자동조회가 활성화됩니다. 키는 GitHub에 올리지 마세요."
        )

    for runtime in app1_runtime:
        fallback = runtime["fallback"]
        item = runtime["item"]
        auto = runtime["auto"]
        row_no = int(fallback.get("row_no") or 0)
        product = str(fallback.get("product_name") or fallback.get("cas") or f"목록 {row_no}행")
        cas = str(fallback.get("cas") or "")
        current_holding = item.get("최대 동시보유량(알면 입력)") if item is not None else ""
        current_unit = item.get("수량 단위") if item is not None else ""
        pure = _single_substance_candidate(item)

        with st.container(border=True):
            st.markdown(f"### {product}")
            st.caption(f"CAS No. {cas or '미확인'} · 함량 {item.get('함량(%)') if item is not None else '-'}% · 최대 동시보유량 {current_holding} {current_unit}")

            if pure and auto is not None and getattr(auto, "status", "") == "MATCHED":
                st.success(f"CAS 자동조회 완료: {auto.chemical_name or product} · 화학물질 ID {auto.chem_id}")
                st.markdown("**자동으로 확인한 SDS 제2항 분류 중 「유해화학물질의 규정수량에 관한 규정」 별표 1에 연결된 항목**")
                for key in auto.app1_option_keys:
                    option = app1_option_map.get(key)
                    if option:
                        st.write(f"• {option.label}")
                if auto.unmatched_classifications:
                    with st.expander("별표 1 규정수량 판정에 사용하지 않은 SDS 분류와 이유", expanded=False):
                        for value in auto.unmatched_classifications:
                            st.write(f"• **{value}**")
                            st.caption(_sds_unmatched_explanation(value))
                st.checkbox(
                    "회사/제품 SDS 제2항과 위 자동조회 분류가 일치함을 확인했습니다.",
                    key=_sds_key(row_no, "auto_confirmed"),
                )
                st.checkbox(
                    "자동조회 결과와 회사 SDS가 다르거나 직접 수정해서 확인하겠습니다.",
                    key=_sds_key(row_no, "manual_mode"),
                )
                st.caption(f"조회 출처: {auto.source} · 확인시각(UTC): {auto.checked_at_utc}")
            elif pure and auto is not None:
                st.warning(auto.message)
                st.checkbox("회사/제품 SDS를 직접 확인하겠습니다.", key=_sds_key(row_no, "manual_mode"))
            elif not pure:
                st.info(
                    "이 행은 **혼합물**로 입력되었습니다. 별표 2·3에 명시적인 함량기준이 있는 물질은 프로그램이 CAS+함량으로 자동 판정하지만, "
                    "별표 1은 혼합물 자체의 유해성·위험성 분류가 필요합니다. 따라서 이 성분이 70%라는 이유만으로 순물질의 SDS 분류를 그대로 적용하지 않고 "
                    "회사/제품 SDS 제2항을 확인합니다."
                )
                st.session_state[_sds_key(row_no, "manual_mode")] = True
            else:
                st.checkbox("회사/제품 SDS를 직접 확인하겠습니다.", key=_sds_key(row_no, "manual_mode"))

            manual_mode_now = bool(st.session_state.get(_sds_key(row_no, "manual_mode"), False))
            selected_now: list[str] = []
            verified_none_now = False
            if manual_mode_now:
                st.markdown("**회사/제품 SDS 제2항의 유해성·위험성 분류를 모두 선택하세요.**")
                selected_now = st.multiselect(
                    "SDS 유해성·위험성 분류",
                    options=[option.key for option in app1_options],
                    format_func=lambda key: app1_option_map[key].label,
                    key=_sds_key(row_no, "classes"),
                    placeholder="SDS 제2항의 분류를 검색해서 선택하세요",
                    label_visibility="collapsed",
                )
                verified_none_now = st.checkbox(
                    "회사/제품 SDS 제2항을 확인했으며, 별표 1 유해성·위험성 분류에 해당하는 항목이 없습니다.",
                    key=_sds_key(row_no, "none"),
                )
            elif auto is not None and getattr(auto, "can_prefill_app1", False) and st.session_state.get(_sds_key(row_no, "auto_confirmed"), False):
                selected_now = list(auto.app1_option_keys)

            row_holding_choice = str(st.session_state.get(_sds_key(row_no, "holding"), "선택하세요"))
            needs_holding_question = bool(selected_now) and cap_holding_choice != "예, 법정 산정방식으로 계산한 값입니다"
            if needs_holding_question:
                st.markdown("**이 물질의 Excel '최대 동시보유량'이 법정 사업장 최대보유량입니까?**")
                row_holding_choice = st.radio(
                    "이 물질 최대보유량 확인",
                    ["선택하세요", "예, 법정 최대보유량입니다", "아니오", "잘 모르겠습니다"],
                    key=_sds_key(row_no, "holding"),
                    label_visibility="collapsed",
                )

            holding_confirmed_now = (
                cap_holding_choice == "예, 법정 산정방식으로 계산한 값입니다"
                or row_holding_choice == "예, 법정 최대보유량입니다"
            )
            current_result = assess_sds_app1_row(
                intake,
                row_no,
                selected_now,
                verified_no_app1_class=verified_none_now,
                holding_confirmed=holding_confirmed_now,
            )
            if auto is not None and getattr(auto, "can_prefill_app1", False) and not manual_mode_now and not st.session_state.get(_sds_key(row_no, "auto_confirmed"), False):
                current_result.status = "HOLD"
                current_result.label = "회사/제품 SDS와 자동조회 결과의 일치 확인 필요"

            if current_result.status == "NOT_APP1":
                st.success("회사 SDS 확인 결과: 이 물질은 현재 별표 1 유해성·위험성 그룹에 해당하지 않습니다.")
            elif current_result.status == "UPPER_CANDIDATE":
                st.success(
                    f"별표 1 적용: 최대보유량 {current_result.max_holding_ton:g} ton은 상위 규정수량 {current_result.upper_quantity_ton:g} ton 이상입니다."
                )
            elif current_result.status == "LOWER_CANDIDATE":
                upper_text = "-" if current_result.upper_quantity_ton is None else f"{current_result.upper_quantity_ton:g} ton"
                st.success(
                    f"별표 1 적용: 최대보유량 {current_result.max_holding_ton:g} ton · 하위 {current_result.lower_quantity_ton:g} ton · 상위 {upper_text}"
                )
            elif current_result.status == "BELOW_LOWER":
                st.info(
                    f"별표 1은 적용되지만 최대보유량 {current_result.max_holding_ton:g} ton은 하위 규정수량 {current_result.lower_quantity_ton:g} ton 미만입니다."
                )
            else:
                st.warning(current_result.label)
                for blocker in current_result.blockers:
                    st.write(f"• {blocker}")

            if selected_now and row_holding_choice in {"아니오", "잘 모르겠습니다"}:
                template = build_cap_facility_workbook(intake, [row_no])
                st.download_button(
                    "이 물질의 최대보유량 계산용 시설정보 입력서 다운로드",
                    data=template,
                    file_name=f"화학사고예방관리계획서_최대보유량_보완_{row_no}행.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"sds_facility_download_{row_no}",
                    width="stretch",
                )

if cap.scope_candidates:
    _section_header(f"{CAP_FULL} · CAS만으로 확정할 수 없는 물질범위", "cap")
    st.warning(
        f"염류·화합물군·반응생성물 등 CAS 하나만으로 확정할 수 없는 규제범위 검토대상이 {len(cap.scope_candidates)}건 있습니다. "
        "확인 전까지 자동으로 화학사고예방관리계획서 작성면제로 판단하지 않습니다."
    )
    _render_guide("CAP_BROAD_SCOPE", show_title=False, compact=True)

_section_header(f"{CAP_FULL} · 최종 적용여부", "cap")
if unresolved:
    st.warning("아직 최종 작성 여부를 확정하기 전에 확인해야 할 정보가 있습니다.")
    for blocker in unresolved:
        st.write(f"• {blocker}")
    st.caption("위 항목이 해결되기 전에는 화학사고예방관리계획서 작성 필요 여부를 추정하지 않고 판정보류합니다.")
else:
    if not threshold_upper and not threshold_lower:
        final_now = assess_cap_final(quantity_rows)
    else:
        st.markdown("### 화학사고예방관리계획서 추가 확인: 법 제23조제1항 단서에 해당합니까?")
        st.write(
            "유해화학물질별 최대보유량이 규정수량 이상이더라도 법령에서 정한 작성면제 시설에 해당하면 화학사고예방관리계획서를 작성하지 않을 수 있습니다. "
            "아래에는 시행규칙뿐 아니라 현재 고시로 구체화된 면제유형까지 표시합니다."
        )
        exemption_values = ["UNANSWERED", "NONE", "PARTIAL", *[item.key for item in exemption_options()], "UNKNOWN"]
        selected_exemption = st.selectbox(
            "법 제23조제1항 단서 해당 여부 확인",
            exemption_values,
            format_func=_exemption_format,
            key="cap_final_exemption",
            label_visibility="collapsed",
        )
        if selected_exemption in {item.key for item in exemption_options()}:
            option = exemption_by_key(selected_exemption)
            if option:
                with st.container(border=True):
                    st.markdown(f"**{option.label}**")
                    st.write(option.plain_language)
                    st.info(f"법적 근거: {option.legal_basis}")
                st.checkbox(
                    "규정수량 판정에 영향을 주는 관련 취급시설 전체가 이 면제유형에 해당함을 확인했습니다.",
                    key="cap_final_exemption_all",
                )
        elif selected_exemption == "PARTIAL":
            st.warning("법 제23조제1항 단서가 일부 취급시설에만 해당한다면, 해당 시설을 제외한 나머지 취급시설을 기준으로 최대보유량을 다시 산정해야 합니다.")
        elif selected_exemption == "UNKNOWN":
            st.info("모르면 추정하지 않습니다. 선택 가능한 면제유형과 법적 근거를 확인한 뒤 판단합니다.")

        with st.expander("법 제23조제1항 단서 및 고시 제9조 작성 면제 시설 전체 보기", expanded=False):
            st.markdown("**법 제23조제1항 단서·시행규칙 제19조제2항·현행 고시 제9조 작성 면제 시설**")
            for option in exemption_options():
                st.markdown(f"**• {option.label}**")
                st.caption(f"{option.plain_language} · {option.legal_basis}")
            st.info(
                "별도로, 사업장의 해당 유해화학물질이 모두 하위 규정수량 미만이면 시행규칙 제19조제2항제2호에 따른 작성면제에 해당하며 프로그램이 자동 확인합니다."
            )

        selected_answer = (
            "EXEMPT" if selected_exemption in {item.key for item in exemption_options()}
            else selected_exemption
        )
        major_now = str(st.session_state.get("cap_major_facility", "UNANSWERED"))
        if threshold_upper and selected_exemption == "NONE":
            st.markdown("### 화학사고예방관리계획서 추가 확인: 상위 규정수량 이상을 취급하는 '개별 취급시설'이 있습니까?")
            st.write(
                "여기서 주요취급시설은 **상위 규정수량 이상의 유해화학물질을 취급하는 사업장 내 개별 취급시설**입니다. "
                "사업장 최대보유량은 여러 시설의 합이므로, 사업장 합계가 상위기준 이상이라는 사실만으로 개별 주요취급시설이 있다고 자동 판단하지 않습니다."
            )
            st.info("법적 근거: 「화학물질관리법 시행규칙」 제19조제8항")
            major_now = st.radio(
                "주요취급시설 확인",
                ["UNANSWERED", "YES", "NO", "UNKNOWN"],
                format_func=_major_format,
                key="cap_major_facility",
                label_visibility="collapsed",
            )

        final_now = assess_cap_final(
            quantity_rows,
            exemption_answer=selected_answer,
            exemption_key=selected_exemption if selected_answer == "EXEMPT" else "",
            exemption_all_relevant_confirmed=bool(st.session_state.get("cap_final_exemption_all", False)),
            major_facility_answer=major_now,
        )

    st.markdown("### 화학사고예방관리계획서 작성 필요 여부 및 작성수준")
    if final_now.status == "REQUIRED_GROUP_1":
        st.success("**화학사고예방관리계획서 작성수준 — 1군 사업장**")
        st.write("1군은 전체 작성항목을 기준으로 작성지원 단계로 진행합니다.")
    elif final_now.status == "REQUIRED_GROUP_2":
        st.success("**화학사고예방관리계획서 작성수준 — 2군 사업장**")
        st.write("2군은 현행 작성규정에 따라 외부 비상대응계획을 제외할 수 있는 작성수준으로 다음 단계에 필요한 자료만 요청합니다.")
    elif final_now.status == "NOT_REQUIRED":
        st.info(f"**{final_now.label}**")
    else:
        st.warning(f"**{final_now.label}**")
        if final_now.next_question:
            st.write(final_now.next_question)
    for reason in final_now.reasons:
        st.write(f"• {reason}")
    if final_now.legal_basis:
        with st.expander("최종 판정 법적 근거 보기", expanded=False):
            for basis in final_now.legal_basis:
                st.write(f"• {basis}")
    for blocker in final_now.blockers:
        st.write(f"• 확인 필요: {blocker}")

st.divider()
st.markdown("### 이 사전진단 단계의 목적")
st.write(
    f"이 화면의 목적은 최소정보로 **{PSM_FULL}을 작성해야 하는지, {CAP_FULL}을 작성해야 하는지, 제외대상인지**를 먼저 결정하는 것입니다. "
    "확정 전에는 보고서 작성용 상세 설비자료를 무조건 요구하지 않고, 판정에 필요한 사실만 순서대로 확인합니다."
)
st.caption("한국산업안전보건공단 API 키·법령 API 키 등 비밀값은 로컬 .env에만 저장하고 GitHub에는 올리지 않습니다.")