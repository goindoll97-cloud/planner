from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import cap_frames as frames

from engine.stage2 import cap_form9_workspace as f9
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft, cap_baseline_filename
from engine.stage2.cap_form9_engine import build_cap_form9_data
from engine.stage2.storage import save_project

READ_ONLY = ("구분기호", "장치·설비명", "취급물질", "설계용량(m3)", "취급량(ton)")


def render(project) -> None:
    schema = ws.load_form_schema(9)
    steps = schema["steps"]
    titles = [step["title"] for step in steps]
    st.header(schema["title"])
    choice = st.radio("단계", titles, horizontal=True, label_visibility="collapsed", key="cap_form09_step")
    step = steps[titles.index(choice)]
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])

    rows = f9.rows(project)
    if not rows and step["id"] != "result":
        st.warning("별지 제1호에서 시설을 입력하면 이 서식의 목록이 자동으로 채워집니다.")

    if step["id"] == "auto":
        if rows:
            data = build_cap_form9_data(project).rows
            frames.show(pd.DataFrame(data).drop(columns=["연번"], errors="ignore"), width="stretch", hide_index=True)
    elif step["id"] == "specs":
        if rows:
            config = {name: st.column_config.TextColumn(name, disabled=True) for name in READ_ONLY}
            for column, label, help_text in f9.SPEC_COLUMNS:
                config[column] = st.column_config.TextColumn(label, help=help_text)
            edited = st.data_editor(pd.DataFrame(rows), column_config=config, hide_index=True, width="stretch",
                                    key=f"cap_form09_specs_{project.project_id}")
            if st.button("저장", type="primary", key=f"cap_form09_save_{project.project_id}"):
                f9.save_specs(project, edited.to_dict("records"))
                save_project(project)
                st.success("저장했습니다.")
    else:
        needs = f9.needs(project)
        if needs:
            st.warning("아직 필요한 정보")
            for item in needs:
                st.write(f"• {item}")
        else:
            st.success("모든 칸이 채워졌습니다.")
        try:
            st.download_button(
                "화학사고예방관리계획서 규정서식 작성본 DOCX 다운로드",
                data=build_cap_baseline_draft(project), file_name=cap_baseline_filename(project),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"cap_form09_download_{project.project_id}",
            )
        except Exception as exc:
            st.error(f"규정서식 작성본을 만들지 못했습니다: {type(exc).__name__}: {exc}")
