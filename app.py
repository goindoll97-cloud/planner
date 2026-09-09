from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.diagnosis import followup_questions, run_preliminary_diagnosis
from engine.inventory import inventory_preview, read_intake_workbook
from engine.law_monitor import source_rows
from engine.template import build_minimal_input_workbook

st.set_page_config(page_title="화학안전 계획서 작성 지원", page_icon="🧪", layout="wide")

st.title("화학안전 계획서 작성 지원")
st.write("최소한의 회사 입력으로 화학사고예방관리계획서와 PSM의 사전진단부터 단계적으로 진행합니다.")

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
        st.caption("현재 버전은 입력 검증과 판정보류 게이트를 구현한 기반 버전입니다. 검증된 화사계 규정수량 DB와 PSM 별표 13 DB는 다음 단계에서 연결합니다.")
        if st.button("사전진단 실행", type="primary", use_container_width=True):
            st.session_state["diagnosis"] = run_preliminary_diagnosis(intake)
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
        st.info("회사 입력자료의 기본 형식 검증은 통과했습니다. 다음 단계에서 검증된 법령 규칙 DB를 연결합니다.")

with st.expander("관리자용: 법령·별표 감시대상"):
    st.caption("일반 사용자는 이 정보를 입력하지 않습니다. 법제처 API와 PDF 모니터가 자동 관리할 영역입니다.")
    st.dataframe(pd.DataFrame(source_rows()), hide_index=True, use_container_width=True)

st.divider()
st.caption("원칙: 최신 법령·별표 미반영, 필수자료 누락, 규제물질 식별 불확실 시 비대상으로 추정하지 않고 판정보류합니다.")
