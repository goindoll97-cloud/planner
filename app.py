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
    st.caption("최신 공식본과 프로그램 감시 기준선이 일치하지 않으면 확정판정을 하지 않습니다.")

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
    st.caption("일반 사용자가 입력하는 영역이 아닙니다. 법제처 API 현행본과 프로그램의 감시 기준선을 비교합니다.")

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

    if st.button("최신 법령·PDF 다시 확인", use_container_width=True):
        cached_law_monitor.clear()
        st.session_state.pop("diagnosis", None)
        st.rerun()

    baseline_keys = [
        str(row.get("key"))
        for row in law_rows
        if row.get("observation_valid") and row.get("monitor_status") == "BASELINE_UNAPPROVED"
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
            "처음 실행할 때는 비교할 과거 해시가 없기 때문에 정상적으로 '최초 기준선 승인 필요'가 표시됩니다. "
            "아래 작업은 현재 법제처 공식본의 시행정보와 PDF 해시를 '변경 감시용 기준선'으로 저장하는 절차입니다. "
            "규제DB/RAG 반영 완료를 의미하지 않습니다."
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
            st.success(
                f"최초 감시 기준선 {result.get('approved', 0)}개를 등록했습니다. "
                "이 작업만으로 화사계·PSM 규칙 DB가 구축되거나 법적 판정이 활성화되는 것은 아닙니다."
            )
            cached_law_monitor.clear()
            st.session_state.pop("diagnosis", None)
            st.rerun()

    if update_keys:
        st.divider()
        st.markdown("**개정자료 재반영 승인(관리자 전용)**")
        st.error(
            "아래 항목은 최초 등록이 아니라 기존 감시 기준선과 실제로 달라진 자료입니다. "
            "관련 최신 법령/PDF를 규제DB·RAG·판정규칙에 반영하고 검토하기 전에는 승인하면 안 됩니다."
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
        st.warning(
            "최초 감시 기준선 미등록 자료: " + ", ".join(baseline_keys)
            + ". 현재 공식 PDF는 data/runtime/law_pending 아래에 해시값을 붙여 보관됩니다."
        )
    if update_keys:
        st.error(
            "실제 변경 감지 자료: " + ", ".join(update_keys)
            + ". 최신 PDF 재반영·검토가 끝날 때까지 관련 판정은 보류됩니다."
        )
    if unverified_keys:
        st.error(
            "공식 최신본 확인 실패/별표 확인 필요: " + ", ".join(unverified_keys)
            + ". 이 자료는 기준선 등록 대상에서도 제외됩니다."
        )

    with st.expander("감시대상 registry"):
        st.dataframe(pd.DataFrame(source_rows()), hide_index=True, use_container_width=True)

st.divider()
st.caption("원칙: 최신 법령·별표 미반영, 필수자료 누락, 규제물질 식별 불확실 시 비대상으로 추정하지 않고 판정보류합니다.")