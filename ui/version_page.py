"""버전 관리 화면: 사업장 작성자료를 제출 시점마다 저장하고, 바뀐 점을 비교하고, 이전 제출본에서 새 작업을 시작합니다.

버전은 특정 작성 화면이 아니라 사업장 작성자료 전체(자료 정리 결과 포함)의 스냅샷이므로 왼쪽 메뉴의 독립 화면에 둡니다.
작성 화면을 바꾸거나 지워도 저장된 버전과 비교·복원 기능은 그대로 남습니다.
"""
from __future__ import annotations

import streamlit as st

from engine.stage2.storage import list_projects, load_project
from ui import version_panel

ACTIVE_PROJECT_KEY = "_stage2_active_project_id"

st.set_page_config(page_title="버전 관리", page_icon="🕘", layout="wide")
st.title("버전 관리")
st.caption("제출할 때마다 현재 작성자료를 버전으로 저장해 두세요. 이후 값을 고치면 저장한 버전과 무엇이 바뀌었는지 자동으로 비교하고, "
           "변경제출·재제출 때 이전 제출본에서 새 작업을 시작할 수 있어요. 첨부파일은 버전에 들어가지 않고 입력값만 저장돼요.")

projects = list_projects()
if not projects:
    st.info("아직 사업장이 없어요. ‘자료 접수·확인할 일’에서 사업장을 만들고 자료를 올려 주세요.")
    st.stop()
options = {p["project_id"]: p["company_name"] for p in projects}
current = st.session_state.get(ACTIVE_PROJECT_KEY)
project_id = st.selectbox("사업장", list(options), index=list(options).index(current) if current in options else 0,
                          format_func=options.get)
st.session_state[ACTIVE_PROJECT_KEY] = project_id
project = load_project(project_id)

docs = [doc for doc, in_scope in (("CAP", project.cap_in_scope), ("PSM", project.psm_in_scope)) if in_scope] or ["CAP", "PSM"]
doc = st.radio("문서", docs, horizontal=True, format_func=version_panel.DOC_NAME.get, key="version_doc_" + project_id) \
    if len(docs) > 1 else docs[0]

version_panel.render_refresh_banner(project, doc)
version_panel.render(project, doc, inline=True)
