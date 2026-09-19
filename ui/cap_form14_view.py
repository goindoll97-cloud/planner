from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import cap_frames as frames

from engine.stage2 import cap_form14_workspace as f14
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_risk_engine import build_cap_form14_data
from engine.stage2.storage import save_project


def render(project) -> None:
    schema = ws.load_form_schema(14)
    steps = schema["steps"]
    titles = [step["title"] for step in steps]
    st.header(schema["title"])
    choice = st.radio("단계", titles, horizontal=True, label_visibility="collapsed", key="cap_form14_step")
    step = steps[titles.index(choice)]
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])

    rows = f14.rows(project)
    if not rows:
        st.warning("별지 제12호에서 사고시나리오를 확정하고 결과를 반영하면 이 서식의 시나리오 목록이 채워집니다.")
        return

    if step["id"] == "counts":
        frame = pd.DataFrame(rows)
        config = {"사고시나리오명": st.column_config.TextColumn("사고시나리오", disabled=True),
                  "제안": st.column_config.TextColumn("프로그램 제안", disabled=True)}
        for event in f14.EVENT_NAMES:
            config[event] = st.column_config.NumberColumn(event, min_value=0, step=1)
        shown = ["사고시나리오명", *f14.EVENT_NAMES, "개수 산정근거", "제안"]
        edited = st.data_editor(frame[shown], column_config=config, hide_index=True, width="stretch",
                                key=f"cap_form14_counts_{project.project_id}")
        cols = st.columns(2)
        merged = []
        for original, new in zip(rows, edited.to_dict("records")):
            item = dict(original)
            item.update({k: ("" if pd.isna(v) else v) for k, v in new.items()})
            merged.append(item)
        if cols[0].button("제안 개수 채우기", key=f"cap_form14_suggest_{project.project_id}",
                          help="비어 있는 칸에만 제안 개수를 넣습니다. 이미 적은 값은 바꾸지 않습니다."):
            f14.save(project, f14.apply_suggestions(project, merged))
            save_project(project)
            st.rerun()
        if cols[1].button("저장", type="primary", key=f"cap_form14_save_{project.project_id}"):
            f14.save(project, merged)
            save_project(project)
            st.success("저장했습니다.")
    elif step["id"] == "mitigation":
        st.info(f14.MITIGATION_NOTE)
        merged = []
        for index, row in enumerate(rows):
            with st.expander(row["사고시나리오명"], expanded=True):
                item = dict(row)
                passive = [x for x in str(row["수동적 완화장치"]).split(", ") if x in f14.PASSIVE_OPTIONS]
                active = [x for x in str(row["능동적 완화장치"]).split(", ") if x in f14.ACTIVE_OPTIONS]
                key = f"cap_form14_{project.project_id}_{index}"
                item["수동적 완화장치"] = ", ".join(st.multiselect("수동적 완화장치", f14.PASSIVE_OPTIONS, default=passive, key=key + "_p"))
                item["능동적 완화장치"] = ", ".join(st.multiselect("능동적 완화장치", f14.ACTIVE_OPTIONS, default=active, key=key + "_a"))
                item["안전성확보설비 증빙"] = st.text_input(
                    "증빙(도면번호·설치 확인 자료)", value=row["안전성확보설비 증빙"], key=key + "_e",
                    help="선택한 설비가 있으면 필요합니다. 예: P&ID 12번 도면, 설치 사진")
                merged.append(item)
        if st.button("저장", type="primary", key=f"cap_form14_save_m_{project.project_id}"):
            f14.save(project, merged)
            save_project(project)
            st.success("저장했습니다.")
    else:
        data = build_cap_form14_data(project)
        if data.scenario_rows:
            frames.show(pd.DataFrame(data.scenario_rows), width="stretch", hide_index=True)
        if data.event_rows:
            with st.expander("개시사건별 계산"):
                frames.show(pd.DataFrame(data.event_rows), width="stretch", hide_index=True)
        if data.blockers:
            st.warning("아직 필요한 정보")
            for item in data.blockers:
                st.write(f"• {item}")
        else:
            st.success("모든 칸이 채워졌습니다.")
