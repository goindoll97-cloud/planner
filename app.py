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
from engine.regulatory_tables import approve_candidate, approved_db_status, candidate_preview
from engine.regulatory_tables_safe import (
    build_cap_accident_quantity_candidate,
    build_psm_annex13_candidate,
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
        st.caption("법령·별표 최신성부터 확인한 뒤 입력자료 검증과 승인된 규제DB의 결정규칙을 적용합니다.")
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

    if diagnosis.psm_details:
        with st.expander("PSM 규정량 기준 초과 근거", expanded=True):
            hit_df = pd.DataFrame(diagnosis.psm_details).rename(
                columns={
                    "row_no": "입력행",
                    "product_name": "제품명",
                    "cas": "CAS",
                    "legal_item_no": "별표13 번호",
                    "legal_substance": "법정 물질명",
                    "quantity_kind": "수량구분",
                    "quantity_kg": "입력량(kg)",
                    "threshold_kg": "규정량(kg)",
                    "ratio": "규정량 대비",
                    "basis": "법적근거",
                }
            )
            if "규정량 대비" in hit_df.columns:
                hit_df["규정량 대비"] = pd.to_numeric(hit_df["규정량 대비"], errors="coerce").round(3)
            st.dataframe(hit_df, hide_index=True, use_container_width=True)

    questions = followup_questions(diagnosis)
    if questions:
        st.session_state.step = 4
        st.header("4. 현재 필요한 추가 확인")
        st.write("판정에 필요한 부족한 정보만 표시합니다.")
        for idx, question in enumerate(questions, 1):
            st.write(f"{idx}. {question}")
    else:
        st.info("현재 연결된 검증 규칙 범위에서 추가 질문이 없습니다.")

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

    if migration_keys:
        st.divider()
        st.markdown("**감시 로직 업데이트에 따른 기준선 재등록**")
        st.warning(
            "이 항목들은 법령의 시행일·발령정보가 바뀐 것이 아니라, 프로그램의 PDF 추출·번호 정규화 방식이 개선되어 "
            "기존 해시 목록과 비교 형식이 달라진 자료입니다. 실제 법령 개정으로 표시하지 않습니다. "
            "현재 공식본을 다시 감시 기준선으로 저장하면 됩니다."
        )
        migration_selected = st.multiselect(
            "새 감시 방식으로 기준선을 재등록할 자료",
            options=migration_keys,
            default=migration_keys,
            key="migration_baseline_selection",
        )
        migration_confirmed = st.checkbox(
            "공식 시행일·발령정보가 동일하고, 이번 표시는 감시 로직 변경에 따른 것임을 확인합니다.",
            key="migration_baseline_confirm",
        )
        if st.button(
            "선택 자료의 감시 기준선 재등록",
            disabled=not (migration_selected and migration_confirmed),
            use_container_width=True,
        ):
            result = approve_latest_observation(migration_selected)
            st.success(f"감시 기준선 {result.get('approved', 0)}개를 현재 추출 방식으로 다시 등록했습니다.")
            cached_law_monitor.clear()
            st.session_state.pop("diagnosis", None)
            st.rerun()

    if update_keys:
        st.divider()
        st.markdown("**개정자료 재반영 승인(관리자 전용)**")
        st.error(
            "아래 항목은 공식 시행일·발령정보 또는 동일한 감시 로직에서의 PDF 해시가 기존 기준선과 달라진 자료입니다. "
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
    if migration_keys:
        st.warning(
            "감시 로직 변경으로 기준선 재등록 필요: " + ", ".join(migration_keys)
            + ". 이는 그 자체로 실제 법령 개정을 의미하지 않습니다."
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

with st.expander("관리자용: 규정수량 구조화 DB", expanded=False):
    st.caption(
        "법령 감시로 받은 최신 공식 PDF를 표 형태로 구조화합니다. 자동추출 결과는 즉시 판정에 쓰지 않고, "
        "후보표 → 관리자 검토 → 승인 DB의 3단계를 거칩니다."
    )

    st.markdown("**현재 승인 DB 상태**")
    db_status = approved_db_status().copy()
    if not db_status.empty:
        db_status["상태"] = db_status["approved"].map({True: "승인됨", False: "미승인"})
        st.dataframe(
            db_status[["key", "상태", "rows", "file"]].rename(columns={"rows": "행수", "file": "파일"}),
            hide_index=True,
            use_container_width=True,
        )

    c1, c2 = st.columns(2)
    if c1.button("PSM 별표 13 후보 추출", use_container_width=True):
        with st.spinner("현행 산업안전보건법 시행령 별표 13 전체 페이지를 구조화하고 있습니다..."):
            st.session_state["psm_candidate_result"] = build_psm_annex13_candidate()
        st.rerun()
    if c2.button("화사계 사고대비물질 규정수량 후보 추출", use_container_width=True):
        with st.spinner("현행 유해화학물질 규정수량 고시 별표 3 전체 페이지를 구조화하고 있습니다..."):
            st.session_state["cap3_candidate_result"] = build_cap_accident_quantity_candidate()
        st.rerun()

    for session_key, db_key, title in (
        ("psm_candidate_result", "PSM_ANNEX13", "PSM 시행령 별표 13"),
        ("cap3_candidate_result", "CAP_QTY_APP3", "화사계 규정수량 별표 3(사고대비물질)"),
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
            st.json(result.checks)
        preview = candidate_preview(db_key)
        if not preview.empty:
            st.dataframe(preview, hide_index=True, use_container_width=True, height=420)

        can_approve = result.status == "REVIEW_REQUIRED" and not preview.empty
        confirmed = st.checkbox(
            "공식 PDF와 자동추출 표의 물질명·CAS·규정량 및 첫/마지막 행을 확인했습니다.",
            key=f"approve_confirm_{db_key}",
            disabled=not can_approve,
        )
        if st.button(
            f"{title} 후보를 판정용 승인 DB로 저장",
            key=f"approve_button_{db_key}",
            disabled=not (can_approve and confirmed),
            use_container_width=True,
        ):
            approval = approve_candidate(db_key)
            st.success(approval.get("message", "승인 DB 저장 완료"))
            st.session_state.pop("diagnosis", None)
            st.rerun()

    st.warning(
        "PSM 별표 13 승인 후에는 exact CAS·수량 기준의 PSM 사전판정이 활성화됩니다. "
        "인화성 가스/액체, 대상업종 특수조건, 시행령 제43조제2항 제외설비는 추가 질문으로 남깁니다. "
        "화사계는 별표 1~4와 면제·작성수준 규칙을 모두 검증하기 전까지 최종 1군/2군 판정을 활성화하지 않습니다."
    )

st.divider()
st.caption("원칙: 최신 법령·별표 미반영, 필수자료 누락, 규제물질 식별 불확실 시 비대상으로 추정하지 않고 판정보류합니다.")
