"""화학사고예방관리계획서 · 작성본 내려받기. 자료 접수에서 만든 규정서식 완성본을 내려받기만 합니다."""
import streamlit as st

from engine.stage2 import report_export as export
from engine.stage2.storage import save_project
from ui import cap_common

st.set_page_config(page_title="작성본 내려받기", page_icon="📥", layout="wide")
st.title("📥 화학사고예방관리계획서 작성본 내려받기")
st.caption("‘자료 접수·확인할 일’에 올린 회사 자료로 작성된 규정서식입니다. 여기서는 입력하지 않고 내려받아 확인만 합니다. "
           "빠진 항목은 자료 접수의 현황표(O/X)에서 확인하고 자료를 보완하세요.")
project = cap_common.open_project()
state = export.evaluate(project, "CAP")
c1, c2, c3 = st.columns(3)
c1.metric("보완 필요", state.hold)
c2.metric("담당자 확인 필요", state.review)
c3.metric("확인 완료", state.passed)
outputs = export.build_outputs(project, final_ready=state.final_ready, system="CAP")
if state.final_ready:
    st.success("최종 준비 기준을 통과해 ‘작성본’으로 표시합니다. 제출 전에는 담당자가 사실·수치·도면을 최종 대조하세요.")
else:
    st.warning("아직 채워지지 않은 항목이 있어 ‘검토용’으로 표시합니다. 제출본이 아닙니다.")
st.download_button("규정서식 DOCX 내려받기", data=outputs.regulation_docx, file_name=outputs.regulation_name,
                   mime=export.DOCX_MIME, key="cap_dl_regulation", width="stretch",
                   type="primary" if state.final_ready else "secondary")
st.download_button("내부 검토용 DOCX(서술형 항목 포함) 내려받기", data=outputs.review_docx, file_name=outputs.review_name,
                   mime=export.DOCX_MIME, key="cap_dl_review", width="stretch")
st.download_button("출력물 검증정보·검증 묶음 ZIP 내려받기", data=outputs.bundle, file_name=outputs.bundle_name,
                   mime="application/zip", key="cap_dl_bundle", width="stretch")
