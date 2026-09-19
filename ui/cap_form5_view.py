from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import cap_frames as frames

from engine.stage2 import cap_form4_workspace as f4
from engine.stage2 import cap_form5_workspace as f5
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft, cap_baseline_filename
from engine.stage2.storage import save_project


def render(project) -> None:
    schema = ws.load_form_schema(5)
    steps = schema["steps"]
    titles = [step["title"] for step in steps]
    st.header(schema["title"])
    choice = st.radio("단계", titles, horizontal=True, label_visibility="collapsed", key="cap_form05_step")
    step = steps[titles.index(choice)]
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])

    unit = f5.active_unit(project)
    st.markdown(f"**작성 대상 단위공장:** {unit or '(별지 제2호에서 단위공장명을 입력하세요)'}")
    others = f5.other_units(project)
    if others:
        st.info("시설 표에 다른 단위공장도 있습니다: " + ", ".join(others) + ". 이 서식에는 위 단위공장 시설만 들어갑니다.")

    if step["id"] == "auto":
        counts = f5.unit_counts(project)
        if counts:
            frames.show(pd.DataFrame(counts, columns=["장치·설비 종류", "수량(기)"]), width="stretch", hide_index=True)
        else:
            st.warning("별지 제1호에서 시설을 입력하면 종류와 수량이 자동으로 채워집니다.")
        rows = f5.unit_chemical_rows(project)
        if rows:
            frames.show(
                pd.DataFrame([{"화학물질명": r["물질명"], "CAS 번호": r["CAS No."],
                               "최대 보유량(ton)": r["사업장 내 최대보유량(ton)"]} for r in rows]),
                width="stretch", hide_index=True,
            )
    elif step["id"] == "describe":
        process = f4.inputs(project).process
        st.write(f"**공정개요(별지 제4호에서 입력):** {process or '아직 없음 — 별지 제4호 2단계에서 입력하세요'}")
        draft = f5.draft_overview(project)
        current = f5.overview(project)
        if draft and not current:
            st.caption("단위공장 구성은 이 단위공장의 시설로 만든 초안입니다. 맞게 고쳐 저장하세요.")
        text = st.text_area("단위공장 구성", value=current or draft, key=f"cap_form05_ov_{project.project_id}")
        if st.button("저장", type="primary", key=f"cap_form05_save_{project.project_id}"):
            f5.save_overview(project, text)
            save_project(project)
            st.success("저장했습니다.")
    else:
        missing = f5.missing(project)
        if missing:
            st.warning("아직 필요한 정보: " + ", ".join(missing))
        else:
            st.success("모든 칸이 채워졌습니다.")
        try:
            st.download_button(
                "화학사고예방관리계획서 규정서식 작성본 DOCX 다운로드",
                data=build_cap_baseline_draft(project), file_name=cap_baseline_filename(project),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"cap_form05_download_{project.project_id}",
            )
        except Exception as exc:
            st.error(f"규정서식 작성본을 만들지 못했습니다: {type(exc).__name__}: {exc}")
