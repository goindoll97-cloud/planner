from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import streamlit as st

from engine.cap_holding import (
    app4_db_ready,
    assess_cap_holding,
    build_cap_facility_workbook,
    read_cap_facility_workbook,
)
from engine.cap_holding_screen import screen_facility_stage
from engine.inventory import read_intake_workbook
from engine.legal_archive import open_archive_folder


st.set_page_config(page_title="화사계 최대보유량", page_icon="📐", layout="wide")


def _table(df: pd.DataFrame, max_rows: int = 60) -> None:
    if df is None or df.empty:
        st.caption("표시할 내용이 없습니다.")
        return
    st.dataframe(df.head(max_rows), width="stretch", hide_index=True)
    if len(df) > max_rows:
        st.caption(f"전체 {len(df):,}행 중 앞 {max_rows:,}행만 표시합니다.")


st.title("화사계 별표 4 · 최대보유량 계산")
st.caption(
    "1차 화학물질 목록에서 별표 3→별표 2 직접 규칙 대상만 추려 시설정보를 추가로 받고, "
    "승인된 별표 4 기준으로 시설별 최대보유량을 산정합니다."
)

intake = st.session_state.get("intake")
if intake is None:
    st.info("메인 사전진단에서 회사 Excel을 먼저 올리거나, 여기에서 같은 회사 입력파일을 올려주세요.")
    uploaded_company = st.file_uploader("회사 입력파일 (.xlsx)", type=["xlsx"], key="cap4_company")
    if uploaded_company is not None:
        try:
            intake = read_intake_workbook(uploaded_company.getvalue())
            st.session_state["intake"] = intake
            st.rerun()
        except Exception as exc:
            st.error(f"회사 입력파일을 읽지 못했습니다: {type(exc).__name__}: {exc}")

if intake is None:
    st.stop()

c1, c2 = st.columns(2)
c1.metric("사업장", str(intake.business.get("사업장명") or "미입력"))
c2.metric("화학물질", f"{len(intake.chemicals):,}개")

st.markdown("### 1. 별표 4 승인 상태")
if not app4_db_ready():
    st.warning("화사계 별표 4 승인 DB가 아직 준비되지 않았습니다. '규정DB 관리'에서 별표 4를 추출·검토·승인한 뒤 돌아오세요.")
    if st.button("별표 4 근거자료 폴더 확인", width="stretch"):
        opened = open_archive_folder("CAP_QTY_APP4")
        if opened.get("status") == "OPENED":
            st.toast("별표 4 근거자료 폴더를 열었습니다.")
        else:
            st.warning(str(opened.get("message", "근거자료 폴더를 열지 못했습니다.")))
    st.stop()
else:
    st.success("승인된 별표 4 규칙 DB를 사용합니다.")

screen = screen_facility_stage(intake)
st.markdown("### 2. 시설정보가 필요한 물질 선별")
for message in screen.messages:
    st.info(message)

if not screen.ready:
    for blocker in screen.blockers:
        st.warning(blocker)
    st.stop()

if screen.row_numbers:
    preview_rows = []
    for row_no in screen.row_numbers:
        item = intake.chemicals.iloc[row_no - 1]
        preview_rows.append(
            {
                "목록행번호": row_no,
                "제품명": item.get("제품명", ""),
                "CAS No.": item.get("CAS No.", ""),
                "함량(%)": item.get("함량(%)", ""),
            }
        )
    _table(pd.DataFrame(preview_rows), 40)
else:
    st.info("별표 2·3 직접 규칙에서 시설정보 단계로 넘길 물질이 없습니다. 별표 1 유해성그룹 또는 포괄 규제범위 검토가 먼저 필요할 수 있습니다.")
    st.stop()

if screen.blockers:
    st.warning("아래 조건은 시설정보만으로 임의 추정하지 않습니다. 해당 조건이 해소되기 전에는 최종 규정수량 비교가 보류됩니다.")
    for blocker in screen.blockers:
        st.write(f"• {blocker}")

st.markdown("### 3. 시설정보 입력")
st.caption(
    "초기 회사 Excel을 다시 복잡하게 만들지 않고, 지금 선별된 물질에 대해서만 2차 시설정보를 받습니다. "
    "같은 물질이 여러 시설에 있으면 입력서에서 행을 복사해 시설별로 작성하세요."
)

facility_template = build_cap_facility_workbook(intake, screen.row_numbers)
st.download_button(
    "화사계 별표4 시설정보 입력서 다운로드 (.xlsx)",
    data=facility_template,
    file_name="화사계_별표4_시설정보_2차입력.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    width="stretch",
)

facility_upload = st.file_uploader(
    "작성한 별표 4 시설정보 입력서를 올려주세요.",
    type=["xlsx"],
    key="cap4_facility_upload",
)

if facility_upload is None:
    st.stop()

try:
    facilities = read_cap_facility_workbook(facility_upload.getvalue())
except Exception as exc:
    st.error(f"시설정보 입력서를 읽지 못했습니다: {type(exc).__name__}: {exc}")
    st.stop()

with st.expander("입력한 시설정보 확인", expanded=False):
    _table(facilities, 80)

result = assess_cap_holding(
    intake=intake,
    facilities=facilities,
    legal_hits=screen.legal_hits,
    required_row_numbers=screen.row_numbers,
)

st.markdown("### 4. 별표 4 최대보유량 계산 결과")
if result.status == "HOLD":
    st.warning(result.label)
elif result.status in {"UPPER_CANDIDATE", "LOWER_CANDIDATE"}:
    st.success(result.label)
else:
    st.info(result.label)

for message in result.messages:
    st.write(f"• {message}")

if result.facility_rows:
    with st.expander("시설별 최대보유량 산정 상세", expanded=True):
        facility_df = pd.DataFrame([asdict(row) for row in result.facility_rows])
        _table(facility_df, 100)

if result.comparison_rows:
    with st.expander("규정수량 비교 상세", expanded=True):
        comparison_df = pd.DataFrame(result.comparison_rows)
        _table(comparison_df, 100)

if result.blockers or screen.blockers:
    st.markdown("**판정보류·추가확인 사항**")
    for blocker in list(dict.fromkeys([*screen.blockers, *result.blockers])):
        st.write(f"• {blocker}")
else:
    st.success("별표 4 시설별 최대보유량 계산과 별표 3→별표 2 규정수량 비교가 완료되었습니다.")
    st.info("다음 단계는 화사계 면제조건 확인과 1군·2군 최종 분류입니다.")

st.divider()
st.caption(
    "혼합물은 규제 함량 이상 여부를 판단할 때 함량을 사용하며, 이 화면의 최대보유량은 해당 혼합물 전체량을 기준으로 계산합니다. "
    "기체·고압가스, 복수성상 또는 근거가 불충분한 시설은 자동 추정하지 않고 판정보류합니다."
)
