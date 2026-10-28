"""예전 다운로드 경로는 자료 접수 ④로 이동합니다."""
import streamlit as st

pid = st.session_state.get("_stage2_active_project_id")
if pid:
    st.session_state["evidence_step_" + pid] = 4
st.switch_page("ui/evidence_workspace_page.py")
