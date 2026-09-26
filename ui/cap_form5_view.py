from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import cap_frames as frames

from engine.stage2 import cap_form4_workspace as f4
from engine.stage2 import cap_form5_workspace as f5
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_shared_facts import UNIT_COLUMN, unit_plant_names, workspace_facility_rows
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
    names = unit_plant_names(project)
    if others:
        st.info("별지 제1호 시설 표의 다른 단위공장: " + ", ".join(others) + ". 위 작성 대상 단위공장명과 일치하는 시설을 집계합니다.")
    if names and all("".join(name.split()).lower() != "".join(unit.split()).lower() for name in names):
        st.warning("작성 대상 단위공장명과 일치하는 시설이 없습니다. 현재는 사업장 전체 시설이 집계되므로 별지 제1호의 단위공장명과 별지 제2호의 작성 대상 단위공장명을 맞춰 주세요.")
    elif len(names) > 1 and any(not str(row.get(UNIT_COLUMN) or "").strip() for row in workspace_facility_rows(project)):
        st.warning("소속 단위공장명이 빈 시설은 현재 단위공장의 수량에도 포함됩니다. 여러 단위공장을 구분하려면 별지 제1호의 각 시설에 소속 단위공장명을 입력해 주세요.")

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
        text = st.text_area(
            "단위공장 구성",
            value=current or draft,
            key=f"cap_form05_ov_{project.project_id}",
            help=(
                "해당 단위공장에 있는 시설의 종류와 수량을 간단히 적습니다. "
                "예: ‘제조1공정의 취급시설은 저장탱크 2기, 반응기 1기, 여과기 1기로 구성된다.’ "
                "공정의 작업 순서는 별지 제4호의 공정개요에 적습니다."
            ),
        )
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
