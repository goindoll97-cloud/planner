from __future__ import annotations

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
from engine.template import build_minimal_input_workbook


st.set_page_config(page_title="화학안전 계획서 작성 지원", page_icon="🧪", layout="wide")


@st.cache_data(ttl=3600, show_spinner=False)
def cached_law_monitor() -> list[dict[str, object]]:
    return run_law_monitor()


law_rows = cached_law_monitor()
law_gate = overall_sync_gate(law_rows)
api_credential = credential_status()

st.title("화학안전 계획서 작성 지원")
st.write("최소한의 회사 입력으로 화학사고예방관리계획서와 PSM의 사전진단부터 단계적으로 진행합니다.")

with st.sidebar:
    st.subheader("법령 최신성")
    if law_gate["decision"] == "ALLOW":
        st.success(law_gate["label"])
    else:
        st.warning(law_gate["label"])
    if api_credential["status"] == "READY":
        st.caption("법제처 API 연결정보: 설정됨")
    else:
        st.caption("법제처 API 연결정보: LAW_OC 미설정")
    st.caption("최신 공식본과 프로그램 반영본이 일치하지 않으면 확정판정을 하지 않습니다.")

if "step" not in st.session_state:
    st.session_state.step = 1

cols = st.columns(4)
for idx, label in enumerate(["① 입력양식", "② 업로드", "③ 사전진단", "④ 추가확인"], start=1):
    if st.session_state.step >= idx:
        cols[idx - 1].success(label)
    else:
        cols[idx - 1].info(label)

st.header("1. 회사용 최소 입력서")
st.write("사업장 기본정보와 규격화된 화학물질 목록만 우선 입력합니다. 상세 설비정보는 최초 단계에서 요구하지 않습니다.")
st.download_button(
    "회사 입력양식 다운로드 (.xlsx)",
    data=build_minimal_input_workbook(),
    file_name="화사계_PSM_회사용_최소입력서.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)

st.header("2. 작성한 Excel 업로드")
uploaded = st.file_uploader("위 양식에 작성한 파일을 업로드하세요.", type=["xlsx"])

if uploaded is not None:
    st.session_state.step = max(st.session_state.step, 2)
    try:
        intake = read_intake_workbook(uploaded.getvalue())
        st.session_state["intake"] = intake

        c1, c2, c3 = st.columns(3)
        c1.metric("사업장", str(intake.business.get("사업장명") or "미입력"))
        c2.metric("화학물질 행", f"{len(intake.chemicals):,}개")
        c3.metric("업종/생산품", str(intake.business.get("업종 또는 주요 생산품") or "미입력"))

        with st.expander("업로드 내용 미리보기"):
            st.dataframe(inventory_preview(intake), hide_index=True, use_container_width=True)

        st.header("3. 1차 사전진단")
        st.caption("법령·별표 최신성부터 확인한 뒤 입력자료 검증과 규제 판정 게이트를 적용합니다.")
        if st.button("사전진단 실행", type="primary", use_container_width=True):
            st.session_state["diagnosis"] = run_preliminary_diagnosis(
                intake,
                law_status_rows=law_rows,
            )
            st.session_state.step = 3
            st.rerun()
    except Exception as exc:
        st.error(f"입력 파일을 읽지 못했습니다: {type(exc).__name__}: {exc}")


diagnosis = st.session_state.get("diagnosis")
if diagnosis is not None:
    st.header("3. 사전진단 결과")
    c1, c2, c3 = st.columns(3)
    c1.metric("법령 최신성", diagnosis.law_status)
    c2.metric("화사계", diagnosis.cap_result)
    c3.metric("PSM", diagnosis.psm_result)

    for message in diagnosis.messages:
        st.warning(message)

    questions = followup_questions(diagnosis)
    if questions:
        st.session_state.step = 4
        st.header("4. 현재 필요한 추가 확인")
        st.write("판정에 필요한 부족한 정보만 표시합니다.")
        for idx, question in enumerate(questions, 1):
            st.write(f"{idx}. {question}")
    else:
        st.info("회사 입력자료의 기본 형식 검증은 통과했습니다. 다음 단계에서 검증된 화사계·PSM 규칙 DB를 연결합니다.")

with st.expander("관리자용: 법령·별표 PDF 변경 감시", expanded=False):
    st.caption("일반 사용자가 입력하는 영역이 아닙니다. 법제처 API 현행본과 프로그램에 승인된 기준선을 비교합니다.")

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
    st.dataframe(pd.DataFrame(display_rows), hide_index=True, use_container_width=True)

    c1, c2 = st.columns(2)
    if c1.button("최신 법령·PDF 다시 확인", use_container_width=True):
        cached_law_monitor.clear()
        st.session_state.pop("diagnosis", None)
        st.rerun()

    valid_keys = [str(row.get("key")) for row in law_rows if row.get("observation_valid")]
    changed_keys = [
        str(row.get("key"))
        for row in law_rows
        if row.get("observation_valid") and row.get("monitor_status") != "CURRENT"
    ]

    st.divider()
    st.markdown("**기준선 승인(관리자 전용)**")
    st.warning(
        "이 버튼은 단순히 경고를 없애는 버튼이 아닙니다. 해당 최신 법령/PDF를 실제로 프로그램의 규제DB·학습/RAG 자료에 반영하고 검토한 뒤에만 승인해야 합니다."
    )
    selected_keys = st.multiselect(
        "반영·검토를 완료한 자료만 선택",
        options=valid_keys,
        default=[],
        help="변경이 감지된 자료는 새 PDF 재반영이 끝난 뒤 선택하세요.",
    )
    confirmed = st.checkbox("선택한 공식 법령/PDF의 프로그램 반영과 검토를 완료했음을 확인합니다.")
    if c2.button(
        "선택 자료를 최신 기준선으로 승인",
        disabled=not (selected_keys and confirmed),
        use_container_width=True,
    ):
        result = approve_latest_observation(selected_keys)
        st.success(result.get("message", "기준선 저장 완료"))
        cached_law_monitor.clear()
        st.session_state.pop("diagnosis", None)
        st.rerun()

    if changed_keys:
        st.error(
            "변경 또는 최초 기준선 미승인 자료: " + ", ".join(changed_keys)
            + ". 관련 PDF는 data/runtime/law_pending 아래에 해시값을 붙여 저장됩니다."
        )

    with st.expander("감시대상 registry"):
        st.dataframe(pd.DataFrame(source_rows()), hide_index=True, use_container_width=True)

st.divider()
st.caption("원칙: 최신 법령·별표 미반영, 필수자료 누락, 규제물질 식별 불확실 시 비대상으로 추정하지 않고 판정보류합니다.")
