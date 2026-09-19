from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import cap_frames as frames

from engine.stage2 import cap_form11_workspace as f11
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft, cap_baseline_filename
from engine.stage2.cap_form11_engine import build_cap_form11_data
from engine.stage2.storage import save_project

ROWS_STATE = "cap_form11_rows_"


def _config(project, only: tuple[str, ...]) -> dict:
    options = {
        "검출대상 물질": f11.chemical_choices(project),
        "설치위치": f11.facility_tags(project),
        "측정방식": list(f11.MEASUREMENT_METHODS),
        "연동여부": list(f11.YES_NO),
    }
    config = {}
    for column, label, kind, help_text in f11.COLUMNS:
        if column not in only:
            continue
        if kind == "choice":
            config[column] = st.column_config.SelectboxColumn(label, help=help_text, options=options[column])
        else:
            config[column] = st.column_config.TextColumn(label, help=help_text)
    return config


def render(project) -> None:
    schema = ws.load_form_schema(11)
    steps = schema["steps"]
    titles = [step["title"] for step in steps]
    st.header(schema["title"])
    choice = st.radio("단계", titles, horizontal=True, label_visibility="collapsed", key="cap_form11_step")
    step = steps[titles.index(choice)]
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])

    saved = f11.saved_rows(project)
    if step["id"] == "rows":
        proposed = f11.skeleton(project)
        if proposed:
            frames.show(pd.DataFrame(proposed)[["감지기 번호", "검출대상 물질", "설치위치"]], width="stretch", hide_index=True)
            if st.button(f"제안한 {len(proposed)}줄 추가", type="primary", key=f"cap_form11_add_{project.project_id}"):
                f11.save(project, saved + proposed)
                save_project(project)
                st.rerun()
        elif not saved:
            st.warning("별지 제1호에서 취급물질이 있는 설비를 입력하면 감지기 줄을 제안합니다.")
        only = ("감지기 번호", "검출대상 물질", "설치위치")
    elif step["id"] == "specs":
        only = f11.COLUMN_IDS[3:]
    else:
        only = ()

    if step["id"] in ("rows", "specs"):
        shown = ["감지기 번호", "검출대상 물질", "설치위치"] if step["id"] == "rows" else ["감지기 번호", *f11.COLUMN_IDS[3:]]
        config = _config(project, only) | {"감지기 번호": st.column_config.TextColumn("구분기호", disabled=step["id"] == "specs")}
        frame = pd.DataFrame(saved, columns=list(dict.fromkeys(["설치형태", *f11.COLUMN_IDS])))
        edited = st.data_editor(frame[shown], column_config=config, num_rows="dynamic", width="stretch", hide_index=True,
                                key=f"cap_form11_{step['id']}_{project.project_id}")
        if st.button("저장", key=f"cap_form11_save_{step['id']}_{project.project_id}"):
            merged = []
            for label, record in zip(edited.index, edited.to_dict("records")):
                # keep columns not shown in this step (matched by original row position)
                base = dict(saved[label]) if isinstance(label, int) and label < len(saved) else {}
                base.update({k: ("" if pd.isna(v) else v) for k, v in record.items()})
                merged.append(base)
            f11.save(project, merged)
            save_project(project)
            st.success("저장했습니다.")
    else:
        data = build_cap_form11_data(project)
        if data.rows:
            frames.show(pd.DataFrame(data.rows), width="stretch", hide_index=True)
        if data.blockers:
            st.warning("아직 필요한 정보")
            for item in data.blockers:
                st.write(f"• {item}")
        else:
            st.success("모든 칸이 채워졌습니다.")
        try:
            st.download_button(
                "화학사고예방관리계획서 규정서식 작성본 DOCX 다운로드",
                data=build_cap_baseline_draft(project), file_name=cap_baseline_filename(project),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"cap_form11_download_{project.project_id}",
            )
        except Exception as exc:
            st.error(f"규정서식 작성본을 만들지 못했습니다: {type(exc).__name__}: {exc}")
