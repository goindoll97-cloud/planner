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
from engine.regulatory_tables import approve_candidate, approved_db_status, candidate_preview
from engine.regulatory_tables_safe import (
    build_cap_accident_quantity_candidate,
    build_psm_annex13_candidate,
)
from engine.template import build_minimal_input_workbook


st.set_page_config(page_title="화학안전 사전진단", page_icon="🧪", layout="wide")

st.markdown(
    """
    <style>
    html, body, [data-testid="stAppViewContainer"] { scroll-behavior: auto !important; }
    .block-container { max-width: 1180px; padding-top: 2rem; }
    .planner-table-wrap {
        width: 100%; overflow-x: auto; overflow-y: visible;
        border: 1px solid rgba(128,128,128,.22); border-radius: 8px;
        margin: .25rem 0 .75rem 0;
    }
    table.planner-table { border-collapse: collapse; width: 100%; font-size: .88rem; }
    table.planner-table th, table.planner-table td {
        border-bottom: 1px solid rgba(128,128,128,.18);
        padding: .42rem .5rem; text-align: left; vertical-align: top;
        white-space: normal;
    }
    table.planner-table th { font-weight: 650; background: rgba(128,128,128,.07); }
    </style>
    """,
    unsafe_allow_html=True,
)


def _static_table(df: pd.DataFrame, max_rows: int = 30) -> None:
    if df is None or df.empty:
        st.caption("표시할 행이 없습니다.")
        return
    shown = df.head(max_rows).copy()
    html = shown.to_html(index=False, escape=True, border=0, classes="planner-table")
    st.markdown(f'<div class="planner-table-wrap">{html}</div>', unsafe_allow_html=True)
    if len(df) > max_rows:
        st.caption(f"화면 성능을 위해 {len(df):,}행 중 앞 {max_rows:,}행만 표시합니다.")


def _candidate_sample(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or len(df) <= 24:
        return df
    return pd.concat([df.head(18).copy(), df.tail(6).copy()], ignore_index=True)


def _checks_frame(checks: dict[str, object]) -> pd.DataFrame:
    rows = []
    for key, value in checks.items():
        if isinstance(value, (dict, list, tuple)):
            display = json.dumps(value, ensure_ascii=False)
        else:
            display = value
        rows.append({"검사항목": key, "값": display})
    return pd.DataFrame(rows)


def _short_question(question: str) -> tuple[str, str, str]:
    rules = [
        ("원자력 설비", "원자력 설비입니까?"),
        ("군사시설", "군사시설입니까?"),
        ("난방용 연료", "사업장 난방용 연료를 직접 저장·사용하는 설비입니까?"),
        ("도매·소매시설", "도매·소매시설입니까?"),
        ("차량 등의 운송설비", "차량 등 운송설비입니까?"),
        ("액화석유가스 충전·저장시설", "LPG 충전·저장시설입니까?"),
        ("가스공급시설", "도시가스 공급시설입니까?"),
        ("피해 정도가 크지 않다고 인정", "고용노동부가 별도로 정한 저위험 제외설비입니까?"),
        ("가스를 전문으로 저장·판매", "가스를 전문으로 저장·판매하는 시설입니까?"),
        ("인화성 가스", "별표 13의 인화성 가스가 있습니까?"),
        ("인화성 액체", "별표 13의 인화성 액체가 있습니까?"),
    ]
    for token, label in rules:
        if token in question:
            return label, question, "choice"
    value_tokens = ["CAS", "함량", "최대", "질량", "밀도", "중량", "수량 단위", "입력해 주세요"]
    if any(token in question for token in value_tokens):
        return question, question, "text"
    return question, question, "choice"


def _is_exclusion_question(question: str) -> bool:
    tokens = [
        "원자력 설비",
        "군사시설",
        "난방용 연료",
        "도매·소매시설",
        "차량 등의 운송설비",
        "액화석유가스 충전·저장시설",
        "가스공급시설",
        "피해 정도가 크지 않다고 인정",
    ]
    return any(token in question for token in tokens)


def _render_followup_result(diagnosis, questions: list[str], answers: dict[str, str]) -> None:
    if not answers:
        return
    unknown = [q for q in questions if answers.get(q) in {None, "", "모름"}]
    exclusion_yes = [q for q in questions if _is_exclusion_question(q) and answers.get(q) == "예"]
    gas_special_yes = [q for q in questions if "가스를 전문으로 저장·판매" in q and answers.get(q) == "예"]

    if exclusion_yes:
        st.warning(
            "제외설비에 해당할 가능성이 있습니다. 현재 단계에서는 PSM 대상 여부를 확정하지 않고, "
            "해당 제외조항과 실제 설비 범위를 추가 검토해야 합니다."
        )
        return
    if gas_special_yes:
        st.warning(
            "가스 전문 저장·판매시설 조건에 '예'로 답했습니다. 해당 가스는 합산 규정량에서 제외될 수 있으므로 "
            "R 값을 다시 계산해야 합니다."
        )
        return
    if unknown:
        st.info(f"답변이 더 필요합니다. 현재 {len(questions) - len(unknown)}/{len(questions)}개 질문을 확인했습니다.")
        return
    if diagnosis.psm_r_value is not None and diagnosis.psm_r_value >= 1.0:
        st.success(
            "현재 입력자료와 추가답변 범위에서는 PSM 수량기준에 해당하는 후보입니다. "
            "다음 단계에서 대상설비 범위와 제출요건을 확인합니다."
        )
    else:
        st.info("추가답변을 저장했습니다. 현재 확인된 자료를 기준으로 다음 판정단계로 진행할 수 있습니다.")


def _render_followup_form(diagnosis) -> None:
    questions = followup_questions(diagnosis)
    if not questions:
        st.success("현재 단계에서 추가로 확인할 질문이 없습니다.")
        return

    st.session_state.step = 4
    st.subheader("추가 확인")
    st.write("아래 질문에 답하면 다음 판정으로 넘어갑니다. 모르는 항목은 **모름**을 선택해도 됩니다.")

    existing = st.session_state.get("followup_answers", {})
    answered = sum(1 for q in questions if existing.get(q) not in {None, ""})
    st.progress(answered / len(questions), text=f"답변 진행 {answered}/{len(questions)}")

    pending: dict[str, str | None] = {}
    with st.form("followup_form", clear_on_submit=False):
        for idx, question in enumerate(questions, 1):
            label, help_text, kind = _short_question(question)
            st.markdown(f"**{idx}. {label}**")
            if kind == "choice":
                old = existing.get(question)
                options = ["아니오", "예", "모름"]
                old_index = options.index(old) if old in options else None
                pending[question] = st.radio(
                    "답변",
                    options,
                    index=old_index,
                    horizontal=True,
                    key=f"followup_choice_{idx}",
                    help=help_text,
                    label_visibility="collapsed",
                )
            else:
                pending[question] = st.text_input(
                    "답변",
                    value=existing.get(question, ""),
                    key=f"followup_text_{idx}",
                    placeholder="필요한 값을 입력하세요",
                    help=help_text,
                    label_visibility="collapsed",
                )
            if idx < len(questions):
                st.divider()

        submitted = st.form_submit_button("답변 저장하고 다음 판정 확인", type="primary", use_container_width=True)

    if submitted:
        saved = {q: (pending.get(q) or "").strip() for q in questions}
        st.session_state["followup_answers"] = saved
        unanswered = [q for q, value in saved.items() if not value]
        if unanswered:
            st.warning(f"아직 {len(unanswered)}개 질문에 답변이 없습니다. 모르면 '모름'을 선택해 주세요.")
        else:
            st.success("추가답변을 저장했습니다.")
        _render_followup_result(diagnosis, questions, saved)
    elif existing:
        _render_followup_result(diagnosis, questions, existing)


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
    3: "사전진단 결과 확인",
    4: "추가질문 답변",
}
current_step = max(1, min(int(st.session_state.step), 4))

st.title("화학안전 사전진단")
st.caption("회사 화학물질 목록을 넣으면 화사계와 PSM의 적용 가능성을 단계별로 확인합니다.")
st.progress(current_step / 4, text=f"전체 진행 {current_step}/4 · {step_labels[current_step]}")

with st.sidebar:
    st.subheader("시스템 상태")
    if law_gate["decision"] == "ALLOW":
        st.success("법령 최신본 확인 완료")
    else:
        st.warning("법령 확인 필요")
    if api_credential["status"] == "READY":
        st.caption("법제처 API 연결됨")
    else:
        st.caption("법제처 API 연결정보 확인 필요")
    st.caption("법령이나 규정표가 바뀌면 확정판정은 자동으로 보류됩니다.")

st.subheader("1. 회사 입력파일")
st.write("처음에는 사업장 기본정보와 화학물질 목록만 입력합니다.")
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
    st.session_state.step = max(st.session_state.step, 2)
    try:
        intake = read_intake_workbook(uploaded.getvalue())
        st.session_state["intake"] = intake

        c1, c2 = st.columns(2)
        c1.metric("사업장", str(intake.business.get("사업장명") or "미입력"))
        c2.metric("입력한 화학물질", f"{len(intake.chemicals):,}개")

        with st.expander("입력내용 확인", expanded=False):
            _static_table(inventory_preview(intake), max_rows=30)

        st.subheader("3. 자동 사전진단")
        if st.button("사전진단 시작", type="primary", use_container_width=True):
            st.session_state.pop("followup_answers", None)
            with st.status("사전진단을 진행하고 있습니다...", expanded=True) as status:
                progress = st.progress(10, text="1/4 입력자료 확인 중")
                st.write("✓ 회사 입력자료 형식을 확인합니다.")
                progress.progress(30, text="2/4 최신 법령 상태 확인 중")
                st.write("✓ 최신 법령·별표 감시 상태를 확인합니다.")
                progress.progress(55, text="3/4 PSM·화사계 규정과 대조 중")
                diagnosis_result = run_preliminary_diagnosis(
                    intake,
                    law_status_rows=law_rows,
                )
                progress.progress(90, text="4/4 결과 정리 중")
                st.write("✓ 규정량 계산과 필요한 추가질문을 정리합니다.")
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

    if diagnosis.psm_r_value is not None:
        ratio_percent = diagnosis.psm_r_value * 100.0
        if diagnosis.psm_r_value >= 1.0:
            st.warning(
                f"**PSM 수량기준: 기준 이상** · 합산 규정량 비율 **{ratio_percent:.0f}%**\n\n"
                "입력한 별표 13 물질들의 '규정량 대비 비율'을 합친 값입니다. "
                "**100% 이상이면 PSM 수량기준에 해당하는 후보**가 됩니다."
            )
        else:
            st.info(
                f"**PSM 수량기준: 현재 기준 미만** · 합산 규정량 비율 **{ratio_percent:.0f}%**\n\n"
                "100%가 수량기준입니다. 추가로 확인할 물질·조건이 있으면 최종 결과가 바뀔 수 있습니다."
            )

        question_count = len(followup_questions(diagnosis))
        if question_count:
            st.caption(f"현재 {question_count}개 항목을 추가로 확인하면 다음 판정으로 진행할 수 있습니다.")

        with st.expander("계산 상세 보기 · 전문가용", expanded=False):
            r1, r2, r3 = st.columns(3)
            r1.metric("법령상 계산값 R", f"{diagnosis.psm_r_value:.4f}")
            r2.metric("판정기준", "R ≥ 1")
            r3.metric("계산상태", "완료" if diagnosis.psm_r_complete else "추가확인 필요")
            st.caption(
                "R은 별표 13 물질별로 제조·취급량 또는 저장량을 해당 규정량으로 나눈 비율 중 큰 값을 선택한 뒤 합산한 값입니다. "
                "일반 사용자는 위의 '합산 규정량 비율'만 확인하면 됩니다."
            )
            if diagnosis.psm_ratio_details:
                ratio_df = pd.DataFrame(diagnosis.psm_ratio_details).rename(
                    columns={
                        "legal_item_no": "별표13 번호",
                        "legal_substance": "물질명",
                        "source_rows": "입력행",
                        "cas_values": "CAS",
                        "manufacture_handling_kg": "제조·취급 환산량(kg)",
                        "storage_kg": "저장 환산량(kg)",
                        "manufacture_handling_threshold_kg": "제조·취급 기준량(kg)",
                        "storage_threshold_kg": "저장 기준량(kg)",
                        "manufacture_handling_ratio": "제조·취급 비율",
                        "storage_ratio": "저장 비율",
                        "controlling_ratio": "합산 기여값",
                        "controlling_basis": "적용 기준",
                        "quantity_basis": "함량·환산 근거",
                    }
                )
                for col in ["제조·취급 비율", "저장 비율", "합산 기여값"]:
                    if col in ratio_df.columns:
                        ratio_df[col] = pd.to_numeric(ratio_df[col], errors="coerce").round(4)
                _static_table(ratio_df, max_rows=30)

    with st.expander("판정 근거 및 시스템 알림 · 전문가용", expanded=False):
        for message in diagnosis.messages:
            st.write(f"• {message}")
        if diagnosis.psm_details:
            st.markdown("**개별 규정량 이상 항목**")
            _static_table(pd.DataFrame(diagnosis.psm_details), max_rows=20)
        if diagnosis.psm_blockers:
            st.markdown("**추가 확인 사유**")
            for blocker in diagnosis.psm_blockers:
                st.write(f"• {blocker}")

    _render_followup_form(diagnosis)


with st.expander("관리자 설정 · 법령/PDF 변경 감시", expanded=False):
    st.caption("일반 사용자는 열지 않아도 됩니다. 법제처 현행본과 프로그램 기준선을 관리하는 영역입니다.")

    if api_credential["status"] != "READY":
        st.warning("LAW_OC가 설정되지 않았습니다. 프로젝트 루트의 .env 또는 운영체제 환경변수에 LAW_OC를 설정하세요.")

    display_rows: list[dict[str, object]] = []
    for row in law_rows:
        reasons = row.get("change_reason", []) or []
        display_rows.append(
            {
                "제도": row.get("regime", ""),
                "문서": row.get("title", ""),
                "시행일": row.get("effective_date", ""),
                "공포/발령번호": row.get("issue_number", ""),
                "PDF 수": row.get("attachment_count", 0),
                "상태": row.get("monitor_status_ko", ""),
                "변경/경고": " / ".join(str(value) for value in reasons),
            }
        )
    _static_table(pd.DataFrame(display_rows), max_rows=30)

    if st.button("최신 법령·PDF 다시 확인", use_container_width=True):
        with st.status("최신 법령을 확인하고 있습니다...", expanded=True) as status:
            progress = st.progress(20, text="1/3 법령 메타정보 조회")
            cached_law_monitor.clear()
            progress.progress(60, text="2/3 별표/PDF 변경 여부 확인")
            refreshed = run_law_monitor()
            st.session_state["law_monitor_refresh_count"] = len(refreshed)
            progress.progress(100, text="3/3 확인 완료")
            status.update(label="법령 확인 완료", state="complete", expanded=False)
        st.session_state.pop("diagnosis", None)
        st.rerun()

    baseline_keys = [
        str(row.get("key"))
        for row in law_rows
        if row.get("observation_valid") and row.get("monitor_status") == "BASELINE_UNAPPROVED"
    ]
    migration_keys = [
        str(row.get("key"))
        for row in law_rows
        if row.get("observation_valid") and row.get("monitor_status") == "BASELINE_MIGRATION_REQUIRED"
    ]
    update_keys = [
        str(row.get("key"))
        for row in law_rows
        if row.get("observation_valid") and row.get("monitor_status") == "UPDATE_PENDING"
    ]
    unverified_keys = [
        str(row.get("key"))
        for row in law_rows
        if row.get("monitor_status") == "UNVERIFIED"
    ]

    if baseline_keys:
        st.divider()
        st.markdown("**최초 감시 기준선 등록**")
        st.info(
            "처음 실행할 때는 비교할 과거 해시가 없어 '최초 기준선 승인 필요'가 표시됩니다. "
            "현재 공식본을 변경감시 기준선으로 저장하는 절차이며 규제DB 승인과는 별개입니다."
        )
        initial_selected = st.multiselect(
            "최초 기준선으로 등록할 공식 자료",
            options=baseline_keys,
            default=baseline_keys,
            key="initial_baseline_selection",
        )
        initial_confirmed = st.checkbox(
            "현재 조회된 법제처 공식본을 최초 변경감시 기준선으로 등록합니다.",
            key="initial_baseline_confirm",
        )
        if st.button(
            "선택 자료를 최초 감시 기준선으로 등록",
            disabled=not (initial_selected and initial_confirmed),
            use_container_width=True,
        ):
            result = approve_latest_observation(initial_selected)
            st.success(f"최초 감시 기준선 {result.get('approved', 0)}개를 등록했습니다.")
            cached_law_monitor.clear()
            st.session_state.pop("diagnosis", None)
            st.rerun()

    if migration_keys:
        st.divider()
        st.markdown("**감시 로직 업데이트에 따른 기준선 재등록**")
        st.warning(
            "법령 자체가 바뀐 것이 아니라 프로그램의 PDF 추출·번호 정규화 방식이 바뀌어 비교형식이 달라진 자료입니다."
        )
        migration_selected = st.multiselect(
            "새 감시 방식으로 기준선을 재등록할 자료",
            options=migration_keys,
            default=migration_keys,
            key="migration_baseline_selection",
        )
        migration_confirmed = st.checkbox(
            "공식 시행일·발령정보가 동일하고, 감시 로직 변경에 따른 것임을 확인합니다.",
            key="migration_baseline_confirm",
        )
        if st.button(
            "선택 자료의 감시 기준선 재등록",
            disabled=not (migration_selected and migration_confirmed),
            use_container_width=True,
        ):
            result = approve_latest_observation(migration_selected)
            st.success(f"감시 기준선 {result.get('approved', 0)}개를 다시 등록했습니다.")
            cached_law_monitor.clear()
            st.session_state.pop("diagnosis", None)
            st.rerun()

    if update_keys:
        st.divider()
        st.markdown("**개정자료 재반영 승인**")
        st.error(
            "공식 시행정보 또는 PDF 해시가 기존 기준선과 다릅니다. 최신 규정의 DB·판정규칙 반영과 검토가 끝나기 전에는 승인하면 안 됩니다."
        )
        changed_selected = st.multiselect(
            "재반영·검토를 완료한 자료만 선택",
            options=update_keys,
            default=[],
            key="changed_baseline_selection",
        )
        changed_confirmed = st.checkbox(
            "선택한 개정 법령/PDF의 프로그램 반영과 검토를 완료했습니다.",
            key="changed_baseline_confirm",
        )
        if st.button(
            "재반영 완료 자료를 최신 기준선으로 승인",
            disabled=not (changed_selected and changed_confirmed),
            use_container_width=True,
        ):
            result = approve_latest_observation(changed_selected)
            st.success(result.get("message", "기준선 저장 완료"))
            cached_law_monitor.clear()
            st.session_state.pop("diagnosis", None)
            st.rerun()

    if baseline_keys:
        st.warning("최초 감시 기준선 미등록: " + ", ".join(baseline_keys))
    if migration_keys:
        st.warning("감시 로직 변경으로 기준선 재등록 필요: " + ", ".join(migration_keys))
    if update_keys:
        st.error("실제 변경 감지 자료: " + ", ".join(update_keys))
    if unverified_keys:
        st.error("공식 최신본 확인 실패/별표 확인 필요: " + ", ".join(unverified_keys))

    with st.expander("감시대상 registry"):
        _static_table(pd.DataFrame(source_rows()), max_rows=30)


with st.expander("관리자 설정 · 규정수량 DB", expanded=False):
    st.caption("일반 사용자는 열지 않아도 됩니다. 공식 별표를 자동추출하고 검토·승인하는 관리자 영역입니다.")

    db_status = approved_db_status().copy()
    if not db_status.empty:
        db_status["상태"] = db_status["approved"].map({True: "승인됨", False: "미승인"})
        _static_table(
            db_status[["key", "상태", "rows", "file"]].rename(columns={"rows": "행수", "file": "파일"}),
            max_rows=20,
        )

    c1, c2 = st.columns(2)
    if c1.button("PSM 별표 13 후보 추출", use_container_width=True):
        with st.status("PSM 별표 13을 구조화하고 있습니다...", expanded=True) as status:
            progress = st.progress(15, text="1/3 공식 PDF 선택")
            progress.progress(35, text="2/3 51개 항목 구조화 및 검증")
            st.session_state["psm_candidate_result"] = build_psm_annex13_candidate()
            progress.progress(100, text="3/3 후보표 생성 완료")
            status.update(label="PSM 별표 13 후보 추출 완료", state="complete", expanded=False)
        st.rerun()

    if c2.button("화사계 사고대비물질 후보 추출", use_container_width=True):
        with st.status("화사계 별표 3을 구조화하고 있습니다...", expanded=True) as status:
            progress = st.progress(15, text="1/3 공식 별표 3 PDF 선택")
            progress.progress(35, text="2/3 100개 기본항목과 특수조건 구조화")
            st.session_state["cap3_candidate_result"] = build_cap_accident_quantity_candidate()
            progress.progress(100, text="3/3 후보표 생성 완료")
            status.update(label="화사계 별표 3 후보 추출 완료", state="complete", expanded=False)
        st.rerun()

    for session_key, db_key, title in (
        ("psm_candidate_result", "PSM_ANNEX13", "PSM 시행령 별표 13"),
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
            if result.status == "REVIEW_REQUIRED":
                st.info(message)
            else:
                st.warning(message)

        if result.checks:
            with st.expander("추출 품질검사 상세", expanded=False):
                _static_table(_checks_frame(result.checks), max_rows=50)

        preview = candidate_preview(db_key)
        if not preview.empty:
            with st.expander("후보표 미리보기", expanded=False):
                sample = _candidate_sample(preview)
                _static_table(sample, max_rows=30)
                if len(preview) > len(sample):
                    st.caption(f"전체 후보는 {len(preview):,}행이며 앞 18행과 마지막 6행만 표시합니다.")

        can_approve = result.status == "REVIEW_REQUIRED" and not preview.empty
        confirmed = st.checkbox(
            "공식 PDF와 자동추출 표의 물질명·CAS·규정량 및 첫/마지막 행을 확인했습니다.",
            key=f"approve_confirm_{db_key}",
            disabled=not can_approve,
        )
        if st.button(
            f"{title} 승인 DB로 저장",
            key=f"approve_button_{db_key}",
            disabled=not (can_approve and confirmed),
            use_container_width=True,
        ):
            approval = approve_candidate(db_key)
            st.success(approval.get("message", "승인 DB 저장 완료"))
            st.session_state.pop("diagnosis", None)
            st.rerun()

    st.caption(
        "PSM은 별표 13 승인 후 사전판정이 활성화됩니다. 화사계는 별표 1~4와 면제·작성수준 규칙 검증이 모두 끝나기 전까지 최종 1군/2군 판정을 하지 않습니다."
    )

st.divider()
st.caption("판정 원칙: 최신 법령 미반영, 필수정보 누락, 물질 식별 불확실 시 임의로 비대상 처리하지 않고 판정을 보류합니다.")