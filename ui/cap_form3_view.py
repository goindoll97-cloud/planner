from __future__ import annotations

import streamlit as st

from engine.stage2 import cap_form3_workspace as f3
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft, cap_baseline_filename
from engine.stage2.storage import save_project


def _inputs(project, step_id: str) -> None:
    values = {}
    for item in f3.fields(step_id):
        key = f"cap_form03_{project.project_id}_{item['id']}"
        current = f3.current_value(project, item["key"])
        hint, origin = f3.suggestion(project, item)
        if hint:
            current = hint
            st.caption(f"'{item['label']}': {origin}로 채운 후보입니다. 맞으면 저장을 누르세요.")
        if item["kind"] == "choice":
            options = [""] + item["options"]
            values[item["id"]] = st.selectbox(
                item["label"], options, index=options.index(current) if current in options else 0,
                help=item["help"], key=key,
            )
        else:
            values[item["id"]] = st.text_input(item["label"], value=current, help=item["help"], key=key)
    if st.button("저장", type="primary", key=f"cap_form03_save_{step_id}_{project.project_id}"):
        saved = f3.save_fields(project, values)
        save_project(project)
        st.success(f"{saved}개 칸을 저장했습니다. 이후 서식에도 반영됩니다.")


def render(project) -> None:
    schema = ws.load_form_schema(3)
    steps = schema["steps"]
    titles = [step["title"] for step in steps]
    st.header(schema["title"])
    choice = st.radio("단계", titles, horizontal=True, label_visibility="collapsed", key="cap_form03_step")
    step = steps[titles.index(choice)]
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])

    if step["id"] == "identity":
        st.markdown("**앞에서 이미 채워진 칸**")
        for row in f3.auto_rows(project):
            st.write(f"• {row.label}: **{row.value or '-'}**  _({row.source})_")
        _inputs(project, "identity")
    elif step["id"] in ("submission", "writer"):
        _inputs(project, step["id"])
    else:
        missing = f3.missing_labels(project)
        if missing:
            st.warning("아직 비어 있는 칸: " + ", ".join(missing))
        else:
            st.success("모든 칸이 채워졌습니다.")
        try:
            st.download_button(
                "화학사고예방관리계획서 규정서식 작성본 DOCX 다운로드",
                data=build_cap_baseline_draft(project), file_name=cap_baseline_filename(project),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"cap_form03_download_{project.project_id}",
            )
        except Exception as exc:
            st.error(f"규정서식 작성본을 만들지 못했습니다: {type(exc).__name__}: {exc}")
