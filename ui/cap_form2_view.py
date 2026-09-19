from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import cap_frames as frames

from engine.stage2 import cap_form2_workspace as f2
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft, cap_baseline_filename
from engine.stage2.storage import save_project


def _column_config(columns: list[dict]) -> dict:
    config = {}
    for col in columns:
        if col.get("kind") == "choice":
            config[col["id"]] = st.column_config.SelectboxColumn(col["label"], help=col.get("help"), options=col["options"])
        else:
            config[col["id"]] = st.column_config.TextColumn(col["label"], help=col.get("help"))
    return config


def render(project) -> None:
    schema = ws.load_form_schema(2)
    steps = schema["steps"]
    titles = [step["title"] for step in steps]
    st.header(schema["title"])
    choice = st.radio("단계", titles, horizontal=True, label_visibility="collapsed", key="cap_form02_step")
    step = steps[titles.index(choice)]
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])

    current = f2.submission(project)

    if step["id"] == "submission":
        st.text_input("사업장명", value=current["company"], disabled=True,
                      help="판정진단에서 승계된 값입니다.")
        unit_plant = st.text_input(
            "단위공장명(또는 단위공정명)", value=current["unit_plant"], key=f"cap_form02_unit_{project.project_id}",
            help="별지 제3호의 단위공장명 칸에도 그대로 들어갑니다.",
        )
        types = [""] + list(f2.SUBMISSION_TYPES)
        submission_type = st.selectbox(
            "제출구분", types, index=types.index(current["type"]) if current["type"] in types else 0,
            key=f"cap_form02_type_{project.project_id}", help="별지 제3호의 제출구분 칸에도 그대로 들어갑니다.",
        )
        reasons = [""] + list(f2.SUBMISSION_REASONS)
        reason = st.selectbox(
            "제출 사유", reasons, index=reasons.index(current["reason"]) if current["reason"] in reasons else 0,
            key=f"cap_form02_reason_{project.project_id}",
        )
        if st.button("저장", type="primary", key=f"cap_form02_save_sub_{project.project_id}"):
            f2.save_submission(project, submission_type, reason, unit_plant)
            save_project(project)
            st.success("저장했습니다. 다른 서식의 같은 칸에도 반영됩니다.")
        state = f2.resolve_form2(project)
        (st.info if state.applies is None else st.success if state.applies else st.warning)(state.headline)

    elif step["id"] == "log":
        state = f2.resolve_form2(project)
        if state.applies is False:
            st.warning(state.headline + " 아래 표는 건너뛰어도 됩니다.")
        columns = ws.section(2, "change_log")["columns"]
        ids = [c["id"] for c in columns]
        frame = pd.DataFrame(f2.change_log_rows(project), columns=ids)
        edited = st.data_editor(
            frame, column_config=_column_config(columns), num_rows="dynamic", width="stretch",
            key=f"cap_form02_log_{project.project_id}",
        )
        if st.button("변경내역 저장", type="primary", key=f"cap_form02_save_log_{project.project_id}"):
            rows = [{k: ("" if pd.isna(v) else v) for k, v in r.items()} for r in edited.to_dict("records")]
            saved = f2.save_change_log(project, rows)
            save_project(project)
            st.success(f"변경내역 {saved}건을 저장했습니다.")

    else:
        state = f2.resolve_form2(project)
        st.write(state.headline)
        for blocker in state.readiness.blockers:
            st.error(blocker)
        for message in state.readiness.messages:
            st.caption(message)
        with st.expander("별지 제2호에 채워지는 내용 미리보기", expanded=True):
            st.write(f"**사업장명**: {current['company'] or '-'}    **단위공장명**: {current['unit_plant'] or '-'}")
            if state.applies:
                frames.show(pd.DataFrame(f2.change_log_rows(project)), width="stretch", hide_index=True)
            else:
                st.caption("작성 대상이 아니어서 표는 비워 둡니다.")
        try:
            st.download_button(
                "화학사고예방관리계획서 규정서식 작성본 DOCX 다운로드",
                data=build_cap_baseline_draft(project), file_name=cap_baseline_filename(project),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"cap_form02_download_{project.project_id}",
            )
        except Exception as exc:
            st.error(f"규정서식 작성본을 만들지 못했습니다: {type(exc).__name__}: {exc}")
