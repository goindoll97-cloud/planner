from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from engine.regulatory_admin import approve_candidate, approved_db_status, candidate_preview
from engine.regulatory_tables_safe import (
    build_cap_accident_quantity_candidate,
    build_cap_appendix1_candidate,
    build_cap_appendix2_candidate,
    build_psm_annex13_candidate,
)


st.set_page_config(page_title="규정수량 DB 관리", page_icon="🗂️", layout="wide")


def _table(df: pd.DataFrame, max_rows: int = 40) -> None:
    if df is None or df.empty:
        st.caption("표시할 내용이 없습니다.")
        return
    st.dataframe(df.head(max_rows), use_container_width=True, hide_index=True)
    if len(df) > max_rows:
        st.caption(f"전체 {len(df):,}행 중 앞 {max_rows:,}행만 표시합니다.")


def _checks_frame(checks: dict[str, object]) -> pd.DataFrame:
    rows = []
    for key, value in checks.items():
        display = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list, tuple)) else value
        rows.append({"검사항목": key, "값": display})
    return pd.DataFrame(rows)


def _show_persistent_notice() -> None:
    notice = st.session_state.get("regdb_notice")
    if not notice:
        return
    status = str(notice.get("status", ""))
    message = str(notice.get("message", ""))
    if status == "APPROVED":
        st.success(message)
        if notice.get("next"):
            st.info(f"다음 단계: {notice['next']}")
    else:
        st.error(message)


st.title("규정수량 DB 관리")
st.caption("현행 공식 PDF → 자동추출 → 품질검사 → 사람 검토 → 승인 DB 저장 순서로 진행합니다.")
_show_persistent_notice()

status_df = approved_db_status().copy()
if not status_df.empty:
    status_df["상태"] = status_df["approved"].map({True: "승인됨", False: "미승인"})
    cols = [c for c in ["key", "상태", "rows", "file", "approved_at_utc"] if c in status_df.columns]
    _table(status_df[cols].rename(columns={"rows": "행수", "file": "파일", "approved_at_utc": "승인시각(UTC)"}), 20)

st.markdown("### 공식 별표 추출")
c1, c2, c3, c4 = st.columns(4)

if c1.button("PSM 별표 13 추출", use_container_width=True):
    with st.status("PSM 별표 13 추출 중...", expanded=True) as box:
        result = build_psm_annex13_candidate()
        st.session_state["regdb_psm"] = result
        box.update(label="PSM 별표 13 추출 완료", state="complete", expanded=False)
    st.rerun()

if c2.button("화사계 별표 1 추출", type="primary", use_container_width=True):
    with st.status("화사계 별표 1 유해·위험성 그룹표 추출 중...", expanded=True) as box:
        result = build_cap_appendix1_candidate()
        st.session_state["regdb_cap1"] = result
        box.update(label="화사계 별표 1 추출 완료", state="complete", expanded=False)
    st.rerun()

if c3.button("화사계 별표 2 추출", use_container_width=True):
    with st.status("화사계 별표 2 물질별 규정수량 추출 중...", expanded=True) as box:
        result = build_cap_appendix2_candidate()
        st.session_state["regdb_cap2"] = result
        box.update(label="화사계 별표 2 추출 완료", state="complete", expanded=False)
    st.rerun()

if c4.button("화사계 별표 3 추출", use_container_width=True):
    with st.status("화사계 별표 3 사고대비물질 추출 중...", expanded=True) as box:
        result = build_cap_accident_quantity_candidate()
        st.session_state["regdb_cap3"] = result
        box.update(label="화사계 별표 3 추출 완료", state="complete", expanded=False)
    st.rerun()

entries = (
    ("regdb_psm", "PSM_ANNEX13", "PSM 시행령 별표 13", "화사계 별표 1·2·3 및 별표 4 검증"),
    ("regdb_cap1", "CAP_QTY_APP1", "화사계 별표 1 유해·위험성 그룹", "별표 4 최대보유량 산정 규칙 구축"),
    ("regdb_cap2", "CAP_QTY_APP2", "화사계 별표 2 인체·생태유해성", "별표 1 또는 별표 4 구축"),
    ("regdb_cap3", "CAP_QTY_APP3", "화사계 별표 3 사고대비물질", "별표 1 또는 별표 4 구축"),
)

for session_key, db_key, title, next_step in entries:
    result = st.session_state.get(session_key)
    if result is None:
        continue

    st.divider()
    st.markdown(f"### {title} 자동추출 결과")
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
        with st.expander("추출 품질검사 상세", expanded=result.status != "REVIEW_REQUIRED"):
            _table(_checks_frame(result.checks), 80)

    preview = candidate_preview(db_key)
    if not preview.empty:
        with st.expander("후보표 미리보기", expanded=False):
            _table(preview, 30)

    can_approve = result.status == "REVIEW_REQUIRED" and not preview.empty
    if db_key == "CAP_QTY_APP1":
        confirm_text = (
            "공식 별표 1과 22개 유해성 그룹, 구분별 하위·상위 규정수량, "
            "복수 유해성 그룹 시 가장 작은 수량 적용 원칙을 확인했습니다."
        )
    elif db_key == "CAP_QTY_APP2":
        confirm_text = (
            "공식 별표 2와 행수·물질명·CAS·함량기준·규정수량을 확인했고, "
            "CAS 없는 포괄범위·삭제행·용액 특수행이 보존된 것을 확인했습니다."
        )
    else:
        confirm_text = "공식 PDF와 후보표의 행수·물질명·규정수량 및 핵심 행을 확인했습니다."

    confirmed = st.checkbox(confirm_text, key=f"regdb_confirm_{db_key}", disabled=not can_approve)
    if st.button(
        f"{title} 승인 DB로 저장",
        key=f"regdb_approve_{db_key}",
        disabled=not (can_approve and confirmed),
        use_container_width=True,
    ):
        approval = approve_candidate(db_key)
        st.session_state["regdb_notice"] = {
            "status": approval.get("status", ""),
            "message": approval.get("message", "승인 처리 결과를 확인하세요."),
            "next": next_step if approval.get("status") == "APPROVED" else "",
        }
        st.session_state.pop(session_key, None)
        st.rerun()

st.divider()
st.info(
    "화사계 규정수량 우선순위는 사고대비물질 별표 3 → 인체·생태유해성 물질별 별표 2 → "
    "그 밖의 유해화학물질에 대한 유해·위험성 그룹 별표 1 순으로 적용합니다. "
    "별표 1은 CAS 매칭표가 아니라 SDS 유해성·위험성 분류표로 별도 관리합니다."
)
st.caption("최신법령 미반영, 자동검증 실패, 범위 불확실 시 승인 또는 비대상 확정을 하지 않습니다.")
