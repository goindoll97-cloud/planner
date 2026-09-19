from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.stage2 import cap_form10_workspace as f10
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft, cap_baseline_filename
from engine.stage2.cap_form10_engine import build_cap_form10_data
from engine.stage2.storage import save_project

READ_ONLY = ("구분기호", "장치·설비명", "설계용량(m3)")


def render(project) -> None:
    schema = ws.load_form_schema(10)
    steps = schema["steps"]
    titles = [step["title"] for step in steps]
    st.header(schema["title"])
    choice = st.radio("단계", titles, horizontal=True, label_visibility="collapsed", key="cap_form10_step")
    step = steps[titles.index(choice)]
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])

    rows = f10.edit_rows(project)
    current_rule = f10.rule(project)
    if not rows and step["id"] != "result":
        st.warning("별지 제1호에서 시설을 입력하면 이 서식의 설비 목록이 자동으로 채워집니다.")
        return

    if step["id"] in ("targets", "capacity"):
        ratio = current_rule["비율(%)"]
        basis = current_rule["근거"]
        if step["id"] == "capacity":
            ratio = st.text_input("필요용량 기준: 설계용량 대비 비율(%)", value=ratio,
                                  key=f"cap_form10_ratio_{project.project_id}",
                                  help="법 제24조 기준에서 확인한 값을 적습니다. 예: 기준이 설계용량의 110%면 110")
            basis = st.text_input("기준 근거", value=basis, key=f"cap_form10_basis_{project.project_id}",
                                  help="예: 화학물질관리법 시행규칙 별표 5 제○호(해당 조문을 확인해 적으세요)")
        columns = ("적용여부", "설비형태", "확산방지설비 종류") if step["id"] == "targets" else \
            ("확산방지설비 종류", *f10.COLUMN_IDS[3:])
        config = {name: st.column_config.TextColumn(name, disabled=True) for name in READ_ONLY}
        for column, label, help_text in f10.EDIT_COLUMNS:
            if column not in columns:
                continue
            if column == "적용여부":
                config[column] = st.column_config.SelectboxColumn(label, help=help_text, options=[f10.APPLICABLE, f10.NOT_APPLICABLE])
            elif column == "설비형태":
                config[column] = st.column_config.SelectboxColumn(label, help=help_text, options=list(f10.FACILITY_FORMS))
            elif column == "확산방지설비 종류":
                config[column] = st.column_config.SelectboxColumn(label, help=help_text, options=list(f10.CONTAINMENT_TYPES))
            else:
                config[column] = st.column_config.TextColumn(label, help=help_text)
        shown = [*READ_ONLY, *columns]
        frame = pd.DataFrame(rows)
        edited = st.data_editor(frame[shown], column_config=config, hide_index=True, width="stretch",
                                key=f"cap_form10_{step['id']}_{project.project_id}")
        if st.button("저장", type="primary", key=f"cap_form10_save_{step['id']}_{project.project_id}"):
            merged = []
            for original, new in zip(rows, edited.to_dict("records")):
                item = dict(original)
                item.update({k: ("" if pd.isna(v) else v) for k, v in new.items()})
                merged.append(item)
            f10.save(project, merged, ratio, basis)
            save_project(project)
            st.success("저장했습니다.")
    else:
        data = build_cap_form10_data(project)
        if data.rows:
            st.dataframe(pd.DataFrame(data.rows).drop(columns=["필요용량 근거", "유효용량 산정근거"], errors="ignore"),
                         width="stretch", hide_index=True)
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
                key=f"cap_form10_download_{project.project_id}",
            )
        except Exception as exc:
            st.error(f"규정서식 작성본을 만들지 못했습니다: {type(exc).__name__}: {exc}")
