"""제출본 보존부터 제출·변경·이행점검까지 한 사업장 안에서 이어집니다."""
import streamlit as st
from engine.stage2.storage import list_projects, load_project
from ui import version_panel

STEPS = {1: "① 제출본 저장", 2: "② 제출서식", 3: "③ 이전 제출본과 비교", 4: "④ 이행점검"}
st.set_page_config(page_title="제출·이행 관리", page_icon="📮", layout="wide")
st.title("제출·이행 관리")
projects = list_projects()
if not projects:
    st.info("먼저 자료 접수에서 사업장을 만들고 자료를 올려 주세요.")
    st.stop()
options = {p["project_id"]: p["company_name"] for p in projects}
current = st.session_state.get("_stage2_active_project_id")
pid = st.selectbox("사업장", list(options), index=list(options).index(current) if current in options else 0,
                   format_func=options.get)
st.session_state["_stage2_active_project_id"] = pid
project = load_project(pid)
docs = [doc for doc, on in (("CAP", project.cap_in_scope), ("PSM", project.psm_in_scope)) if on]
if not docs:
    docs = ["CAP", "PSM"]
    st.caption("제출 대상 확인 전에도 작성자료를 제출본으로 저장하고 비교할 수 있어요.")
doc_key = "management_doc_" + pid
if st.session_state.get(doc_key) not in docs:
    st.session_state[doc_key] = docs[0]
doc = st.radio("문서", docs, horizontal=True, format_func=version_panel.DOC_NAME.get, key=doc_key) if len(docs) > 1 else docs[0]
goto = st.session_state.pop("cap_goto", None)
if goto and doc == "CAP":
    destination = {2: 3, "submission": 2, "implementation": 4}.get(goto[1])
    if destination:
        st.session_state[f"management_step_{pid}_{doc}"] = destination
steps = list(STEPS) if doc == "CAP" else [1, 2, 3]
step = st.radio("할 일", steps, format_func=STEPS.get, horizontal=True, key=f"management_step_{pid}_{doc}")
if step in (2, 4) and not (project.cap_in_scope if doc == "CAP" else project.psm_in_scope):
    st.info("이 문서의 제출 대상 여부를 먼저 확인해 주세요. 저장한 제출본은 그대로 보존됩니다.")
    st.stop()
base_version = None
if step != 1:
    metas = version_panel.ver.list_versions(pid, doc)
    if metas:
        ids = [m.version_id for m in metas]
        memory = f"management_base_value_{pid}_{doc}"
        selected = st.session_state.get(memory)
        if selected not in ids:
            selected = version_panel._latest(metas).version_id
        base_version = st.selectbox("기준 제출본", ids, index=ids.index(selected), key=f"management_base_{pid}_{doc}")
        st.session_state[memory] = base_version
if step == 1:
    st.caption("제출 시점의 입력값을 저장합니다. 실제 제출·접수 처리는 수행하지 않으며 첨부파일은 저장본에 포함되지 않습니다.")
    version_panel.render(project, doc, inline=True, section="save")
elif step == 2:
    if doc == "CAP":
        from ui import cap_submission_forms_view
        cap_submission_forms_view.render(project, base_version=base_version)
    else:
        from ui import psm_admin_panel
        psm_admin_panel.render(project)
elif step == 3:
    version_panel.render_refresh_banner(project, doc)
    version_panel.render(project, doc, inline=True, section="compare", base_version=base_version)
    if doc == "CAP":
        with st.expander("변경내역 관리대장 · 별지 제2호"):
            from ui import cap_form2_view
            cap_form2_view.render(project, base_version=base_version)
else:
    from ui import cap_implementation_self_check_view
    cap_implementation_self_check_view.render(project, base_version=base_version)
