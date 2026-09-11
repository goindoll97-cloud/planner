from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from engine.diagnosis import followup_questions, run_preliminary_diagnosis
from engine.inventory import inventory_preview, read_intake_workbook
from engine.law_api import credential_status
from engine.law_monitor import (
    approve_latest_observation,
    overall_sync_gate,
    run_law_monitor,
    source_rows,
)
from engine.regulatory_admin import approve_candidate, approved_db_status, candidate_preview
from engine.regulatory_tables_safe import (
    build_cap_accident_quantity_candidate,
    build_cap_appendix2_candidate,
    build_psm_annex13_candidate,
)
from engine.template import build_minimal_input_workbook


st.set_page_config(page_title="화학안전 사전진단", page_icon="🧪", layout="wide")

st.markdown(
    """
    <style>
    html, body, [data-testid="stAppViewContainer"] { scroll-behavior: auto !important; }
    .block-container { max-width: 1080px; padding-top: 1.3rem; }
    .planner-table-wrap {
        width: 100%; overflow-x: auto; overflow-y: visible;
        border: 1px solid rgba(128,128,128,.20); border-radius: 8px;
        margin: .25rem 0 .75rem 0;
    }
    table.planner-table { border-collapse: collapse; width: 100%; font-size: .86rem; }
    table.planner-table th, table.planner-table td {
        border-bottom: 1px solid rgba(128,128,128,.16);
        padding: .4rem .48rem; text-align: left; vertical-align: top;
        white-space: normal;
    }
    table.planner-table th { font-weight: 650; background: rgba(128,128,128,.06); }
    </style>
    """,
    unsafe_allow_html=True,
)


EXCLUSION_OPTIONS = {
    "원자력 설비": "원자력 설비",
    "군사시설": "군사시설",
    "사업장 난방용 연료 저장·사용설비": "난방용 연료",
    "도매·소매시설": "도매·소매시설",
    "차량 등 운송설비": "차량 등의 운송설비",
    "LPG 충전·저장시설": "액화석유가스 충전·저장시설",
    "도시가스 공급시설": "가스공급시설",
    "기타 고용노동부 고시 제외설비": "피해 정도가 크지 않다고 인정",
}


def _static_table(df: pd.DataFrame, max_rows: int = 30) -> None:
    if df is None or df.empty:
        st.caption("표시할 내용이 없습니다.")
        return
    shown = df.head(max_rows).copy()
    html = shown.to_html(index=False, escape=True, border=0, classes="planner-table")
    st.markdown(f'<div class="planner-table-wrap">{html}</div>', unsafe_allow_html=True)
    if len(df) > max_rows:
        st.caption(f"{len(df):,}행 중 앞 {max_rows:,}행만 표시합니다.")


def _candidate_sample(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or len(df) <= 24:
        return df
    return pd.concat([df.head(18).copy(), df.tail(6).copy()], ignore_index=True)


def _checks_frame(checks: dict[str, object]) -> pd.DataFrame:
    rows = []
    for key, value in checks.items():
        display = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list, tuple)) else value
        rows.append({"검사항목": key, "값": display})
    return pd.DataFrame(rows)


def _is_exclusion_question(question: str) -> bool:
    return any(token in question for token in EXCLUSION_OPTIONS.values())


def _is_gas_special_question(question: str) -> bool:
    return "가스를 전문으로 저장·판매" in question


def _short_question(question: str) -> tuple[str, str]:
    if "인화성 가스" in question:
        return "별표 13의 인화성 가스가 있습니까?", "choice"
    if "인화성 액체" in question:
        return "별표 13의 인화성 액체가 있습니까?", "choice"
    value_tokens = ["CAS", "함량", "최대", "질량", "밀도", "중량", "수량 단위", "입력해 주세요"]
    if any(token in question for token in value_tokens):
        return question, "text"
    return question, "choice"


def _split_questions(questions: list[str]) -> tuple[list[str], bool, list[str]]:
    exclusions = [q for q in questions if _is_exclusion_question(q)]
    has_gas_special = any(_is_gas_special_question(q) for q in questions)
    others = [q for q in questions if q not in exclusions and not _is_gas_special_question(q)]
    return exclusions, has_gas_special, others


def _compact_question_count(diagnosis) -> int:
    exclusions, has_gas_special, others = _split_questions(followup_questions(diagnosis))
    return (1 if exclusions else 0) + (1 if has_gas_special else 0) + len(others)


def _ratio_line_options(diagnosis) -> tuple[list[str], dict[str, float]]:
    labels: list[str] = []
    ratio_by_label: dict[str, float] = {}
    for row in diagnosis.psm_ratio_details or []:
        item = row.get("legal_item_no", "-")
        name = str(row.get("legal_substance", ""))
        cas = str(row.get("cas_values", ""))
        ratio = float(row.get("controlling_ratio", 0.0) or 0.0)
        label = f"별표13 {item} · {name} · CAS {cas} · 기여 {ratio * 100:.1f}%"
        labels.append(label)
        ratio_by_label[label] = ratio
    return labels, ratio_by_label


def _result_payload(
    *, status: str, message: str, next_step: str, adjusted_r: float,
    exclusion_status: str, tone: str = "info", can_continue: bool = False,
) -> dict[str, object]:
    return {
        "status": status,
        "tone": tone,
        "message": message,
        "next": next_step,
        "adjusted_r": adjusted_r,
        "quantity_status": "충족" if adjusted_r >= 1.0 else "기준 미만",
        "exclusion_status": exclusion_status,
        "can_continue": can_continue,
    }


def _evaluate_followup(
    diagnosis,
    exclusion_choice: str,
    exclusion_scope: str | None,
    gas_choice: str | None,
    gas_selected: list[str],
    ratio_by_label: dict[str, float],
    other_answers: dict[str, str],
) -> dict[str, object]:
    adjusted_r = float(diagnosis.psm_r_value or 0.0)

    unresolved_other = [q for q, answer in other_answers.items() if answer in {"", "모름", "선택하세요"}]
    if unresolved_other:
        return _result_payload(
            status="판정보류",
            message=f"추가정보 {len(unresolved_other)}개가 아직 확정되지 않았습니다.",
            next_step="관련 SDS·설비자료를 확인한 뒤 다시 답변해 주세요.",
            adjusted_r=adjusted_r,
            exclusion_status="추가정보 미확인",
        )

    if exclusion_choice in {"선택하세요", "잘 모르겠음"}:
        return _result_payload(
            status="판정보류",
            message="수량기준은 계산됐지만 PSM 제외설비 해당 여부를 아직 확정하지 못했습니다.",
            next_step="제외설비 해당 여부를 확인하면 판정을 계속할 수 있습니다.",
            adjusted_r=adjusted_r,
            exclusion_status="미확인",
        )

    if exclusion_choice != "해당 없음":
        if exclusion_scope in {None, "선택하세요", "모름"}:
            return _result_payload(
                status="판정보류",
                message=f"'{exclusion_choice}'가 판정대상 설비 전체에 적용되는지 확인이 필요합니다.",
                next_step="선택한 제외유형이 이번 판정대상 설비 전체를 포함하는지 확인해 주세요.",
                adjusted_r=adjusted_r,
                exclusion_status=f"{exclusion_choice} · 범위 미확인",
            )
        if exclusion_scope == "예":
            return _result_payload(
                status="PSM 제외 후보",
                message=f"현재 답변 기준으로 '{exclusion_choice}' 제외조건이 판정대상 설비 전체에 적용됩니다.",
                next_step="해당 제외조항과 실제 설비 범위를 증빙자료로 확인해야 합니다.",
                adjusted_r=adjusted_r,
                exclusion_status=f"{exclusion_choice} 해당 후보",
                tone="success",
            )

    exclusion_status = "해당 없음"

    if gas_choice in {"모름", "선택하세요"}:
        return _result_payload(
            status="판정보류",
            message="일반 제외설비는 정리됐지만 가스 전문 저장·판매시설 예외 적용 여부를 확인하지 못했습니다.",
            next_step="해당 가스가 전문 저장·판매시설 내부의 가스인지 확인해 주세요.",
            adjusted_r=adjusted_r,
            exclusion_status="일반 제외설비 없음 · 가스 예외 미확인",
        )

    if gas_choice == "예":
        if not gas_selected:
            return _result_payload(
                status="판정보류",
                message="가스 전문 저장·판매시설에 해당한다고 답했지만 제외할 가스 물질이 선택되지 않았습니다.",
                next_step="실제로 그 시설에 있는 가스 물질만 선택해 주세요.",
                adjusted_r=adjusted_r,
                exclusion_status="가스 예외 물질 미선택",
            )
        adjusted_r = max(0.0, adjusted_r - sum(ratio_by_label.get(label, 0.0) for label in gas_selected))
        exclusion_status = "가스 전문 저장·판매시설 예외 반영"
        if adjusted_r < 1.0:
            return _result_payload(
                status="PSM 재검토 필요",
                message=f"선택한 가스를 제외하면 합산 규정량 비율이 {adjusted_r * 100:.0f}%로 100% 미만입니다.",
                next_step="대상업종·인화성 가스/액체 등 남은 PSM 적용조건을 다시 확인해야 합니다.",
                adjusted_r=adjusted_r,
                exclusion_status=exclusion_status,
            )

    if adjusted_r >= 1.0:
        return _result_payload(
            status="PSM 대상 후보",
            message=f"수량기준과 현재 확인된 제외조건을 반영해도 합산 규정량 비율이 {adjusted_r * 100:.0f}%입니다.",
            next_step="아래 버튼에서 실제 PSM 대상 공정·설비 범위를 정리하세요.",
            adjusted_r=adjusted_r,
            exclusion_status=exclusion_status,
            tone="success",
            can_continue=True,
        )

    return _result_payload(
        status="PSM 추가검토 필요",
        message=f"현재 합산 규정량 비율은 {adjusted_r * 100:.0f}%로 100% 미만입니다.",
        next_step="다른 PSM 적용조건을 확인한 뒤 판단합니다.",
        adjusted_r=adjusted_r,
        exclusion_status=exclusion_status,
    )


def _render_followup_result(result: dict[str, object]) -> None:
    st.subheader("5. PSM 사전판정 결과")
    adjusted_r = float(result.get("adjusted_r") or 0.0)
    c1, c2, c3 = st.columns(3)
    c1.metric("① 수량기준", f"{result.get('quantity_status', '미확인')} · {adjusted_r * 100:.0f}%")
    c2.metric("② 제외조건", str(result.get("exclusion_status", "미확인")))
    c3.metric("③ 현재 결론", str(result.get("status", "판정보류")))
    st.caption("수량기준 → 제외조건 → 현재 결론 순서로 확인합니다.")

    message = str(result.get("message", ""))
    if str(result.get("tone", "info")) == "success":
        st.success(message)
    else:
        st.info(message)
    if result.get("next"):
        st.markdown(f"**다음 단계:** {result['next']}")

    status = str(result.get("status", ""))
    if bool(result.get("can_continue")):
        if st.button("다음 단계 · PSM 대상설비 범위 확인", type="primary", use_container_width=True):
            st.session_state["psm_scope_open"] = True
            st.session_state.step = 6
            st.rerun()
    elif status == "판정보류":
        st.warning("미확인 항목을 먼저 확인한 뒤 다시 판정하세요.")


def _render_psm_scope_stage() -> None:
    if not st.session_state.get("psm_scope_open"):
        return
    st.divider()
    st.subheader("6. PSM 대상설비 범위 확인")
    st.caption("탱크 세부사양이나 P&ID 전체를 한꺼번에 요구하지 않고, 우선 대상 공정·설비 범위만 확인합니다.")

    saved = st.session_state.get("psm_scope", {})
    with st.form("psm_scope_form", clear_on_submit=False):
        process_scope = st.text_area(
            "대상 공정·설비명",
            value=str(saved.get("process_scope", "")),
            placeholder="예: 포스겐 공급설비, 반응공정 R-101",
        )
        options = ["선택하세요", "신규 설치", "이전", "주요 구조변경", "기존설비 적용성 검토"]
        old = str(saved.get("change_type", "선택하세요"))
        change_type = st.selectbox("사업 진행유형", options, index=options.index(old) if old in options else 0)
        planned_date = st.text_input("설치·이전·변경 예정일 (해당 시)", value=str(saved.get("planned_date", "")))
        available_docs = st.multiselect(
            "현재 보유한 자료 (선택)",
            ["공정설명서", "설비목록", "SDS", "PFD", "P&ID", "물질수지", "운전절차", "위험성평가자료", "비상조치자료"],
            default=list(saved.get("available_docs", [])),
        )
        submitted = st.form_submit_button("대상설비 범위 저장", type="primary", use_container_width=True)

    if submitted:
        if not process_scope.strip():
            st.warning("대상 공정·설비명을 최소 1개 입력해 주세요.")
        elif change_type == "선택하세요":
            st.warning("사업 진행유형을 선택해 주세요.")
        else:
            st.session_state["psm_scope"] = {
                "process_scope": process_scope.strip(),
                "change_type": change_type,
                "planned_date": planned_date.strip(),
                "available_docs": available_docs,
            }
            st.success("대상 공정·설비 범위를 저장했습니다.")

    if st.session_state.get("psm_scope"):
        scope = st.session_state["psm_scope"]
        st.markdown("**다음에 준비할 것**")
        st.write(
            "저장한 설비범위를 기준으로 공정안전자료 → 공정위험성평가 → 안전운전계획 → 비상조치계획 순으로 "
            "이미 가진 자료는 재활용하고 부족한 자료만 요청하도록 연결합니다."
        )
        st.caption(f"현재 범위: {scope.get('process_scope', '')} · 진행유형: {scope.get('change_type', '')}")


def _render_followup_form(diagnosis) -> None:
    questions = followup_questions(diagnosis)
    if not questions:
        return
    exclusions, has_gas_special, others = _split_questions(questions)
    st.session_state.step = max(int(st.session_state.get("step", 1)), 4)

    st.subheader("4. PSM에 필요한 정보만 추가 확인")
    st.caption("법 조문을 나열하지 않고 실제 판정에 필요한 항목만 질문합니다. 모르면 '모름'을 선택하세요.")

    total = (1 if exclusions else 0) + (1 if has_gas_special else 0) + len(others)
    answered = 0
    exclusion_choice = "해당 없음"
    exclusion_scope: str | None = None

    if exclusions:
        exclusion_choice = st.selectbox(
            "① 이번 판정대상 설비가 PSM 제외설비에 해당합니까?",
            ["선택하세요", "해당 없음", *EXCLUSION_OPTIONS.keys(), "잘 모르겠음"],
        )
        if exclusion_choice != "선택하세요":
            answered += 1
        if exclusion_choice not in {"선택하세요", "해당 없음", "잘 모르겠음"}:
            exclusion_scope = st.radio(
                "선택한 제외유형이 이번 판정대상 설비 전체에 적용됩니까?",
                ["선택하세요", "예", "아니오", "모름"],
                horizontal=True,
            )

    gas_choice: str | None = None
    gas_selected: list[str] = []
    ratio_labels, ratio_by_label = _ratio_line_options(diagnosis)
    if has_gas_special:
        gas_choice = st.radio(
            "② 계산에 포함된 물질 중 가스를 전문으로 저장·판매하는 시설에만 있는 가스가 있습니까?",
            ["선택하세요", "아니오/해당 없음", "예", "모름"],
            horizontal=True,
        )
        if gas_choice != "선택하세요":
            answered += 1
        if gas_choice == "예":
            gas_selected = st.multiselect("그 시설에 있는 가스 물질만 선택하세요.", ratio_labels)

    other_answers: dict[str, str] = {}
    start_no = 3 if exclusions and has_gas_special else 2
    for offset, question in enumerate(others):
        label, kind = _short_question(question)
        number = start_no + offset
        if kind == "text":
            answer = st.text_input(f"{number}. {label}", placeholder="확인된 값을 입력하세요")
        else:
            answer = st.radio(f"{number}. {label}", ["선택하세요", "아니오", "예", "모름"], horizontal=True)
        other_answers[question] = answer
        if answer not in {"", "선택하세요"}:
            answered += 1

    st.progress((answered / total) if total else 1.0, text=f"PSM 추가확인 {answered}/{total}")
    if st.button("추가 확인 완료 · PSM 결과 보기", type="primary", use_container_width=True):
        st.session_state["followup_result"] = _evaluate_followup(
            diagnosis, exclusion_choice, exclusion_scope, gas_choice, gas_selected,
            ratio_by_label, other_answers,
        )
        st.session_state.step = 5
        st.session_state.pop("psm_scope_open", None)
        st.session_state.pop("psm_scope", None)

    result = st.session_state.get("followup_result")
    if result:
        _render_followup_result(result)
        _render_psm_scope_stage()


def _render_cap_summary(diagnosis) -> None:
    st.markdown("### 화사계 현재 확인")
    direct_count = len(diagnosis.cap_details or []) + len(diagnosis.cap_scope_direct_hits or [])
    broad_count = len(diagnosis.cap_scope_candidates or [])

    c1, c2, c3 = st.columns(3)
    c1.metric("현재 결과", diagnosis.cap_result)
    c2.metric("직접 규칙 매칭", f"{direct_count}건")
    c3.metric("포괄범위 후보", f"{broad_count}건")

    if broad_count:
        st.warning(
            f"CAS 하나로 특정되지 않는 규제범위 후보가 {broad_count}건 있습니다. "
            "이 항목은 자동으로 비대상 처리하지 않고 범위 확인이 끝날 때까지 판정을 보류합니다."
        )
    elif diagnosis.cap_scope_missing_keys:
        st.info("화사계 별표 1·2 물질범위 DB가 아직 모두 승인되지 않아 현재 결과는 부분검토입니다.")
    elif diagnosis.cap_partial_only:
        st.info("현재는 규정수량 물질대조 단계입니다. 별표 4와 면제·군 분류 규칙 완료 후 최종 1군/2군/비대상으로 확정합니다.")

    if diagnosis.cap_questions:
        st.warning(f"화사계 판정을 계속하려면 추가 확인이 필요한 항목이 {len(diagnosis.cap_questions)}개 있습니다.")
        with st.expander("화사계 추가 확인 항목", expanded=False):
            for question in diagnosis.cap_questions:
                st.write(f"• {question}")

    if diagnosis.cap_scope_candidates:
        with st.expander("포괄 규제범위 후보 · 확인 필요", expanded=False):
            df = pd.DataFrame(diagnosis.cap_scope_candidates)
            columns = [
                c for c in [
                    "row_no", "product_name", "cas", "regulatory_name", "scope_type",
                    "candidate_match_type", "candidate_reason",
                ] if c in df.columns
            ]
            _static_table(df[columns] if columns else df, max_rows=20)

    if diagnosis.cap_scope_direct_hits:
        with st.expander("별표 1·2 직접 CAS 계산 상세 · 전문가용", expanded=False):
            df = pd.DataFrame(diagnosis.cap_scope_direct_hits)
            _static_table(df, max_rows=30)

    if diagnosis.cap_details:
        with st.expander("별표 3 사고대비물질 계산 상세 · 전문가용", expanded=False):
            _static_table(pd.DataFrame(diagnosis.cap_details), max_rows=30)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_law_monitor() -> list[dict[str, object]]:
    return run_law_monitor()


law_rows = cached_law_monitor()
law_gate = overall_sync_gate(law_rows)
api_credential = credential_status()

if "step" not in st.session_state:
    st.session_state.step = 1

step_labels = {
    1: "입력양식 준비",
    2: "회사 Excel 확인",
    3: "PSM·화사계 자동 사전진단",
    4: "필요정보 추가확인",
    5: "사전판정 결과",
    6: "PSM 대상설비 범위 확인",
}
current_step = max(1, min(int(st.session_state.step), 6))

st.title("화학안전 사전진단")
st.caption("회사 Excel 한 번으로 PSM과 화학사고예방관리계획서 적용 가능성을 함께 확인합니다.")
st.progress(current_step / 6, text=f"전체 진행 {current_step}/6 · {step_labels[current_step]}")

with st.sidebar:
    st.subheader("시스템 상태")
    if law_gate["decision"] == "ALLOW":
        st.success("법령 최신본 확인 완료")
    else:
        st.warning("법령 확인 필요")
    st.caption("법령·별표 변경이 감지되면 관련 판정은 자동으로 보류합니다.")
    st.caption("법제처 API 연결됨" if api_credential["status"] == "READY" else "법제처 API 연결정보 확인 필요")

st.subheader("1. 회사 입력파일")
st.write("사업장 기본정보와 화학물질 목록을 입력합니다. 파일 안의 '00_작성가이드'에 작성 예시가 있습니다.")
st.download_button(
    "회사 입력양식 다운로드 (.xlsx)",
    data=build_minimal_input_workbook(),
    file_name="화사계_PSM_회사용_최소입력서.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)

st.subheader("2. 작성한 Excel 업로드")
uploaded = st.file_uploader("작성한 회사 입력파일을 올려주세요.", type=["xlsx"])

if uploaded is not None:
    st.session_state.step = max(int(st.session_state.step), 2)
    try:
        intake = read_intake_workbook(uploaded.getvalue())
        st.session_state["intake"] = intake
        c1, c2 = st.columns(2)
        c1.metric("사업장", str(intake.business.get("사업장명") or "미입력"))
        c2.metric("입력한 화학물질", f"{len(intake.chemicals):,}개")
        with st.expander("입력내용 확인", expanded=False):
            _static_table(inventory_preview(intake), max_rows=30)

        st.subheader("3. 자동 사전진단")
        if st.button("PSM·화사계 사전진단 시작", type="primary", use_container_width=True):
            for key in ["followup_result", "psm_scope_open", "psm_scope"]:
                st.session_state.pop(key, None)
            with st.status("사전진단을 진행하고 있습니다...", expanded=True) as status:
                progress = st.progress(10, text="1/4 입력자료 확인")
                progress.progress(30, text="2/4 최신 법령·승인 DB 확인")
                progress.progress(55, text="3/4 PSM·화사계 물질 및 규정량 대조")
                diagnosis_result = run_preliminary_diagnosis(intake, law_status_rows=law_rows)
                progress.progress(90, text="4/4 보류사유와 추가확인 항목 정리")
                progress.progress(100, text="완료")
                status.update(label="사전진단 완료", state="complete", expanded=False)
            st.session_state["diagnosis"] = diagnosis_result
            st.session_state.step = 3
            st.rerun()
    except Exception as exc:
        st.error(f"입력 파일을 읽지 못했습니다: {type(exc).__name__}: {exc}")


diagnosis = st.session_state.get("diagnosis")
if diagnosis is not None:
    st.subheader("사전진단 결과")
    c1, c2 = st.columns(2)
    c1.metric("PSM", diagnosis.psm_result)
    c2.metric("화사계", diagnosis.cap_result)

    if diagnosis.missing_items:
        st.error("Excel 필수입력을 먼저 보완해야 합니다.")
        for item in diagnosis.missing_items:
            st.write(f"• {item}")
    else:
        if diagnosis.psm_r_value is not None:
            ratio_percent = diagnosis.psm_r_value * 100.0
            if diagnosis.psm_r_value >= 1.0:
                st.warning(f"**PSM 수량기준 충족 · {ratio_percent:.0f}%**  (기준 100%)")
            else:
                st.info(f"**PSM 현재 수량기준 미만 · {ratio_percent:.0f}%**  (기준 100%)")
            count = _compact_question_count(diagnosis)
            if count:
                st.caption(f"PSM은 다음 판정을 위해 {count}개 묶음 항목만 추가 확인합니다.")
            with st.expander("PSM 계산 상세 · 전문가용", expanded=False):
                r1, r2 = st.columns(2)
                r1.metric("내부 계산값 R", f"{diagnosis.psm_r_value:.4f}")
                r2.metric("기준", "R ≥ 1")
                if diagnosis.psm_ratio_details:
                    _static_table(pd.DataFrame(diagnosis.psm_ratio_details), max_rows=30)

        _render_cap_summary(diagnosis)

        with st.expander("판정 근거 및 보류사유 · 전문가용", expanded=False):
            for message in diagnosis.messages:
                st.write(f"• {message}")
            if diagnosis.psm_blockers:
                st.markdown("**PSM 보류·추가확인 사유**")
                for blocker in diagnosis.psm_blockers:
                    st.write(f"• {blocker}")
            if diagnosis.cap_blockers:
                st.markdown("**화사계 보류·추가확인 사유**")
                for blocker in diagnosis.cap_blockers:
                    st.write(f"• {blocker}")

        _render_followup_form(diagnosis)


with st.expander("관리자 설정 · 법령/PDF 변경 감시", expanded=False):
    st.caption("일반 사용자는 열지 않아도 됩니다.")
    if api_credential["status"] != "READY":
        st.warning("LAW_OC가 설정되지 않았습니다. .env 또는 운영체제 환경변수에 LAW_OC를 설정하세요.")

    display_rows = []
    for row in law_rows:
        display_rows.append({
            "제도": row.get("regime", ""),
            "문서": row.get("title", ""),
            "시행일": row.get("effective_date", ""),
            "공포/발령번호": row.get("issue_number", ""),
            "PDF 수": row.get("attachment_count", 0),
            "상태": row.get("monitor_status_ko", ""),
            "변경/경고": " / ".join(str(v) for v in (row.get("change_reason", []) or [])),
        })
    _static_table(pd.DataFrame(display_rows), max_rows=30)

    if st.button("최신 법령·PDF 다시 확인", use_container_width=True):
        with st.status("최신 법령을 확인하고 있습니다...", expanded=True) as status:
            progress = st.progress(20, text="1/3 법령 메타정보 조회")
            cached_law_monitor.clear()
            progress.progress(60, text="2/3 별표/PDF 변경 여부 확인")
            run_law_monitor()
            progress.progress(100, text="3/3 확인 완료")
            status.update(label="법령 확인 완료", state="complete", expanded=False)
        st.session_state.pop("diagnosis", None)
        st.session_state.pop("followup_result", None)
        st.rerun()

    baseline_keys = [str(r.get("key")) for r in law_rows if r.get("observation_valid") and r.get("monitor_status") == "BASELINE_UNAPPROVED"]
    migration_keys = [str(r.get("key")) for r in law_rows if r.get("observation_valid") and r.get("monitor_status") == "BASELINE_MIGRATION_REQUIRED"]
    update_keys = [str(r.get("key")) for r in law_rows if r.get("observation_valid") and r.get("monitor_status") == "UPDATE_PENDING"]
    unverified_keys = [str(r.get("key")) for r in law_rows if r.get("monitor_status") == "UNVERIFIED"]

    if baseline_keys:
        selected = st.multiselect("최초 기준선으로 등록할 공식 자료", baseline_keys, default=baseline_keys)
        confirmed = st.checkbox("현재 조회된 공식본을 최초 변경감시 기준선으로 등록합니다.")
        if st.button("선택 자료를 최초 기준선으로 등록", disabled=not (selected and confirmed), use_container_width=True):
            result = approve_latest_observation(selected)
            st.success(f"기준선 {result.get('approved', 0)}개를 등록했습니다.")
            cached_law_monitor.clear(); st.session_state.pop("diagnosis", None); st.rerun()

    if migration_keys:
        selected = st.multiselect("감시 로직 변경으로 재등록할 자료", migration_keys, default=migration_keys)
        confirmed = st.checkbox("공식 시행일·발령정보가 동일함을 확인했습니다.")
        if st.button("선택 자료 기준선 재등록", disabled=not (selected and confirmed), use_container_width=True):
            result = approve_latest_observation(selected)
            st.success(f"기준선 {result.get('approved', 0)}개를 재등록했습니다.")
            cached_law_monitor.clear(); st.session_state.pop("diagnosis", None); st.rerun()

    if update_keys:
        st.error("법령 또는 PDF의 실제 변경이 감지되었습니다. 규칙 반영·검토 전에는 승인하지 마세요.")
        selected = st.multiselect("재반영 검토가 끝난 자료만 선택", update_keys, default=[])
        confirmed = st.checkbox("선택한 개정자료의 프로그램 반영과 검토를 완료했습니다.")
        if st.button("재반영 완료 자료 승인", disabled=not (selected and confirmed), use_container_width=True):
            result = approve_latest_observation(selected)
            st.success(result.get("message", "기준선 저장 완료"))
            cached_law_monitor.clear(); st.session_state.pop("diagnosis", None); st.rerun()

    if unverified_keys:
        st.error("공식 최신본 확인 실패/별표 확인 필요: " + ", ".join(unverified_keys))
    with st.expander("감시대상 registry"):
        _static_table(pd.DataFrame(source_rows()), max_rows=30)


with st.expander("관리자 설정 · 규정수량 DB", expanded=False):
    st.caption("현행 공식 별표를 후보표로 추출한 뒤, 사람이 확인한 자료만 판정 DB로 승인합니다.")
    db_status = approved_db_status().copy()
    if not db_status.empty:
        db_status["상태"] = db_status["approved"].map({True: "승인됨", False: "미승인"})
        _static_table(db_status[["key", "상태", "rows", "file"]].rename(columns={"rows": "행수", "file": "파일"}), max_rows=20)

    c1, c2, c3 = st.columns(3)
    if c1.button("PSM 별표 13 추출", use_container_width=True):
        with st.status("PSM 별표 13을 구조화하고 있습니다...", expanded=True) as status:
            p = st.progress(20, text="1/3 공식 PDF 선택")
            p.progress(55, text="2/3 51개 항목 구조화·검증")
            st.session_state["psm_candidate_result"] = build_psm_annex13_candidate()
            p.progress(100, text="3/3 완료")
            status.update(label="PSM 별표 13 후보 추출 완료", state="complete", expanded=False)
        st.rerun()

    if c2.button("화사계 별표 2 추출", use_container_width=True):
        with st.status("화사계 별표 2를 구조화하고 있습니다...", expanded=True) as status:
            p = st.progress(15, text="1/3 현행 별표 2 PDF 선택")
            p.progress(45, text="2/3 직접 CAS·CAS 없는 포괄범위·다중 유해성 행 구조화")
            st.session_state["cap2_candidate_result"] = build_cap_appendix2_candidate()
            p.progress(100, text="3/3 품질검사 완료")
            status.update(label="화사계 별표 2 후보 추출 완료", state="complete", expanded=False)
        st.rerun()

    if c3.button("화사계 별표 3 추출", use_container_width=True):
        with st.status("화사계 별표 3을 구조화하고 있습니다...", expanded=True) as status:
            p = st.progress(20, text="1/3 공식 별표 3 PDF 선택")
            p.progress(55, text="2/3 기본항목·특수조건 구조화")
            st.session_state["cap3_candidate_result"] = build_cap_accident_quantity_candidate()
            p.progress(100, text="3/3 완료")
            status.update(label="화사계 별표 3 후보 추출 완료", state="complete", expanded=False)
        st.rerun()

    for session_key, db_key, title in (
        ("psm_candidate_result", "PSM_ANNEX13", "PSM 시행령 별표 13"),
        ("cap2_candidate_result", "CAP_QTY_APP2", "화사계 별표 2 인체·생태유해성"),
        ("cap3_candidate_result", "CAP_QTY_APP3", "화사계 별표 3 사고대비물질"),
    ):
        result = st.session_state.get(session_key)
        if result is None:
            continue
        st.divider()
        st.markdown(f"**{title} 자동추출 결과**")
        m1, m2 = st.columns(2)
        m1.metric("상태", result.status)
        m2.metric("추출 행수", f"{result.row_count:,}")
        st.caption(f"원본: {result.source_file or '-'}")
        for message in result.messages:
            (st.info if result.status == "REVIEW_REQUIRED" else st.warning)(message)

        if result.checks:
            with st.expander("추출 품질검사 상세", expanded=False):
                _static_table(_checks_frame(result.checks), max_rows=60)

        preview = candidate_preview(db_key)
        if not preview.empty:
            with st.expander("후보표 미리보기", expanded=False):
                _static_table(_candidate_sample(preview), max_rows=30)

        can_approve = result.status == "REVIEW_REQUIRED" and not preview.empty
        confirm_text = (
            "공식 PDF와 후보표의 행수·물질명·CAS·함량기준·규정수량을 확인했습니다. "
            "CAS가 없는 포괄범위와 삭제/특수행도 누락되지 않았음을 확인했습니다."
            if db_key == "CAP_QTY_APP2"
            else "공식 PDF와 자동추출 표의 물질명·CAS·규정량 및 첫/마지막 행을 확인했습니다."
        )
        confirmed = st.checkbox(confirm_text, key=f"approve_confirm_{db_key}", disabled=not can_approve)
        if st.button(
            f"{title} 승인 DB로 저장",
            key=f"approve_button_{db_key}",
            disabled=not (can_approve and confirmed),
            use_container_width=True,
        ):
            approval = approve_candidate(db_key)
            if approval.get("status") == "APPROVED":
                st.success(approval.get("message", "승인 DB 저장 완료"))
            else:
                st.error(approval.get("message", "승인 실패"))
            st.session_state.pop("diagnosis", None)
            st.rerun()

    st.caption(
        "PSM은 별표 13 승인 후 사전판정이 활성화됩니다. 화사계는 별표 1~4와 면제·군 분류 규칙까지 "
        "검증되어야 최종 1군/2군/비대상을 확정합니다."
    )

st.divider()
st.caption("원칙: 최신법령 미반영·필수정보 누락·물질범위 불확실 시 임의로 비대상 처리하지 않고 판정을 보류합니다.")
