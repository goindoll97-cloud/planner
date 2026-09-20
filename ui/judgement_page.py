from __future__ import annotations

"""사업장 판정하기: 사업장과 물질 목록(엑셀·CSV 가능)을 넣고, 판정에 필요한 질문에 답하고, 작성할 문서를 정한 뒤 작성으로 넘어간다.

예전의 '판정진단(엑셀 전체 양식) → 작성범위 선택' 두 화면을 한 화면으로 합쳤다. 물질 목록만 파일로 받고 나머지는 질문으로 묻는다.
"""

import streamlit as st

from engine.stage2 import cap_judgement as judgement
from engine.stage2.storage import delete_project, list_projects, load_project
from ui import cap_start_panel, judgement_panel

ACTIVE_PROJECT_KEY = "_stage2_active_project_id"
FLASH_KEY = "_judgement_flash"

st.set_page_config(page_title="사업장 판정하기", page_icon="✅", layout="wide")
st.title("✅ 사업장 판정하기")
st.caption(
    "사업장 정보와 취급 물질 목록을 넣으면 화학사고예방관리계획서·공정안전보고서를 작성해야 하는 사업장인지 판정합니다. "
    "물질 목록은 엑셀·CSV 파일로 올릴 수 있고, 나머지는 질문에 답하면 됩니다. 판정이 끝나면 바로 작성으로 넘어갑니다."
)
flash = st.session_state.pop(FLASH_KEY, "")
if flash:
    st.success(flash)

projects = list_projects()
if not projects:
    st.info("판정한 사업장이 아직 없습니다. 아래에서 사업장과 취급 물질을 넣고 시작하세요.")
    cap_start_panel.render(expanded=True)
    st.stop()

labels = {row["project_id"]: f"{row['company_name']} · {row['project_id']}" for row in projects}
ids = list(labels)
current = st.session_state.get(ACTIVE_PROJECT_KEY)
selected = st.selectbox("사업장", ids, index=ids.index(current) if current in ids else 0, format_func=lambda pid: labels[pid],
                        key="judgement_project")
st.session_state[ACTIVE_PROJECT_KEY] = selected
cap_start_panel.render(expanded=False)

try:
    project = load_project(selected)
except Exception as exc:
    st.error(f"사업장을 읽지 못했습니다: {type(exc).__name__}: {exc}")
    st.stop()

judgement_panel.render(project)

st.markdown("### 다음 단계")
if judgement.undecided(project):
    st.caption("판정을 마치면 작성으로 넘어갈 수 있습니다. 판정 전에도 별지 작성은 미리 시작할 수 있습니다.")
if project.cap_in_scope or judgement.undecided(project):
    st.page_link("ui/cap_workspace_page.py", label="화학사고예방관리계획서 작성으로 이동", icon="📝")
if project.psm_in_scope:
    st.page_link("ui/psm_workspace_page.py", label="공정안전보고서 작성으로 이동", icon="🏭")
if not (project.cap_in_scope or project.psm_in_scope or judgement.undecided(project)):
    st.info("이 사업장은 작성해야 하는 문서가 없습니다. 물질이나 시설이 바뀌면 위에서 다시 판정하세요.")

with st.expander("프로젝트 관리", expanded=False):
    st.warning("프로젝트를 삭제하면 이 사업장에 저장된 작성 자료와 첨부 파일이 함께 삭제됩니다. 법적 판정 결과를 바꾸는 기능은 아닙니다.")
    confirm = st.checkbox(f"{selected} 프로젝트와 저장된 첨부자료를 삭제합니다.", key=f"delete_confirm_{selected}")
    if st.button("선택한 프로젝트 삭제", disabled=not confirm, key=f"delete_project_{selected}"):
        try:
            removed = delete_project(selected)
        except Exception as exc:
            st.error(f"프로젝트를 삭제하지 못했습니다: {type(exc).__name__}: {exc}")
        else:
            if removed:
                st.session_state.pop(ACTIVE_PROJECT_KEY, None)
                st.session_state[FLASH_KEY] = f"프로젝트를 삭제했습니다: {selected}"
                st.rerun()
            else:
                st.warning("이미 삭제되었거나 저장된 프로젝트를 찾을 수 없습니다.")
