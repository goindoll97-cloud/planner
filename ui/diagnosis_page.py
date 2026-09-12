from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.inventory import inventory_preview, read_intake_workbook, validate_intake
from engine.stage1_workbook import assess_stage1_from_workbook


CAP_FULL = "화학사고예방관리계획서"
PSM_FULL = "공정안전보고서(PSM)"

st.set_page_config(page_title=f"{PSM_FULL} · {CAP_FULL} 사전진단", page_icon="✅", layout="wide")


def _table(df: pd.DataFrame, max_rows: int = 60) -> None:
    if df is None or df.empty:
        st.caption("표시할 내용이 없습니다.")
        return
    st.dataframe(df.head(max_rows), width="stretch", hide_index=True)
    if len(df) > max_rows:
        st.caption(f"전체 {len(df):,}행 중 앞 {max_rows:,}행만 표시합니다.")


def _result_card(title: str, status: str, explanation: str) -> None:
    with st.container(border=True):
        st.markdown(f"### {title}")
        st.markdown(f"#### {status}")
        if explanation:
            st.write(explanation)


st.title(f"{PSM_FULL} · {CAP_FULL} 사전진단")
st.caption(
    "회사가 작성한 Excel을 판정의 유일한 입력원본으로 사용합니다. "
    "업로드 후 화면에서 같은 사실을 다시 선택하거나 수정하지 않습니다."
)

uploaded = st.file_uploader(
    "회사 입력파일 업로드 (.xlsx)",
    type=["xlsx"],
    help="프로그램에서 내려받은 회사 입력 예시파일에 필요한 정보를 작성한 뒤 업로드해 주세요.",
)
if uploaded is None:
    st.info("회사 입력파일을 업로드하면 PSM과 화학사고예방관리계획서를 함께 판정합니다.")
    st.stop()

try:
    intake = read_intake_workbook(uploaded.getvalue())
except Exception as exc:
    st.error(f"입력파일을 읽지 못했습니다: {type(exc).__name__}: {exc}")
    st.stop()

basic_issues = validate_intake(intake)
if basic_issues:
    st.markdown("## 요청사항")
    st.warning("입력파일을 보완한 뒤 같은 파일을 다시 업로드해 주세요.")
    for issue in basic_issues:
        st.write(f"• {issue}")
    st.stop()

with st.spinner("업로드한 회사 입력정보와 승인 규정 DB를 대조하고 있습니다..."):
    decision = assess_stage1_from_workbook(intake)

if decision.system_blockers:
    st.markdown("## 시스템 확인 필요")
    st.error("회사 입력 문제가 아니라 규정 DB 또는 시스템 준비상태를 관리자가 확인해야 합니다.")
    for blocker in decision.system_blockers:
        st.write(f"• {blocker}")
    st.stop()

if decision.company_requests:
    st.markdown("## 요청사항")
    st.warning(
        "판정에 필요한 회사 정보가 아직 충분하지 않습니다. 아래 항목만 Excel에서 확인·수정한 뒤 다시 업로드해 주세요. "
        "화면에서 별도로 선택할 항목은 없습니다."
    )
    for request in decision.company_requests:
        st.write(f"• {request}")
    st.info("입력파일을 수정·저장한 뒤 위 업로드 칸에 다시 올리면 처음부터 자동 판정합니다.")
    st.stop()

st.success("입력파일의 판정 필수정보가 확인되었습니다.")

st.markdown("## 판정 결과")
left, right = st.columns(2, gap="large")
with left:
    _result_card(PSM_FULL, decision.psm_status, decision.psm_explanation)
    if decision.psm_r_value is not None:
        st.caption(f"「산업안전보건법 시행령」 별표 13 비고 제7호 합산한 값(R): {decision.psm_r_value:.4f}")
with right:
    _result_card(CAP_FULL, decision.cap_status, decision.cap_explanation)

with st.expander("법적 근거", expanded=False):
    st.markdown(f"**{PSM_FULL}**")
    for basis in decision.psm_legal_basis:
        st.write(f"• {basis}")
    st.markdown(f"**{CAP_FULL}**")
    if decision.cap_legal_basis:
        for basis in decision.cap_legal_basis:
            st.write(f"• {basis}")
    else:
        st.write("• 적용된 물질별 규정수량 및 작성수준 근거는 승인 규정 DB와 계산근거에 기록됩니다.")

with st.expander("계산 근거 · 검토자용", expanded=False):
    if decision.psm_ratio_rows:
        st.markdown("**공정안전보고서 별표 13 비고 제7호 산정내역**")
        _table(pd.DataFrame(decision.psm_ratio_rows), 80)
    if decision.cap_quantity_rows:
        st.markdown("**화학사고예방관리계획서 최대보유량·규정수량 비교내역**")
        _table(pd.DataFrame(decision.cap_quantity_rows), 100)

with st.expander("업로드한 회사 입력내용 · 검토자용", expanded=False):
    _table(inventory_preview(intake), 80)
