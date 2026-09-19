from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.stage2 import cap_form1_engine as form1
from engine.stage2 import cap_form4_workspace as f4
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft, cap_baseline_filename
from engine.stage2.storage import save_project


def render(project) -> None:
    schema = ws.load_form_schema(4)
    steps = schema["steps"]
    titles = [step["title"] for step in steps]
    st.header(schema["title"])
    choice = st.radio("단계", titles, horizontal=True, label_visibility="collapsed", key="cap_form04_step")
    step = steps[titles.index(choice)]
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])

    if step["id"] == "auto":
        counts = f4.equipment_counts(project)
        if counts:
            st.dataframe(pd.DataFrame(counts, columns=["장치·설비 종류", "수량(기)"]), width="stretch", hide_index=True)
        else:
            st.warning("별지 제1호에서 시설을 입력하면 종류와 수량이 자동으로 채워집니다.")
        st.caption(f"보유 탱크로리: {f4.lorry_count(project)}기 (별지 제1호에서 '탱크로리·운송차량'으로 표시한 시설)")
        rows = form1.build_cap_form1_data(project).chemical_rows
        if rows:
            st.dataframe(
                pd.DataFrame([{"화학물질명": r.get("물질명"), "CAS 번호": r.get("CAS No."),
                               "최대 보유량(ton)": r.get("사업장 내 최대보유량(ton)")} for r in rows]),
                width="stretch", hide_index=True,
            )
    elif step["id"] == "describe":
        current = f4.inputs(project)
        draft = f4.draft_overview(project)
        overview_default = current.overview or draft
        if draft and not current.overview:
            st.caption("단위공장 구성은 입력한 시설과 물질로 만든 초안입니다. 맞게 고쳐 저장하세요.")
        overview = st.text_area("단위공장 구성", value=overview_default, key=f"cap_form04_ov_{project.project_id}")
        process = st.text_area("공정개요", value=current.process, key=f"cap_form04_proc_{project.project_id}",
                               help="원료 → 반응 → 정제 → 제품 저장·출하처럼 흐름을 두세 문장으로 적습니다.")
        loading = st.text_input("입·출하 시설 수(기)", value=current.loading_units, key=f"cap_form04_load_{project.project_id}",
                                help="탱크로리에 싣거나 내리는 설비의 수. 없으면 비워 두세요.")
        if st.button("저장", type="primary", key=f"cap_form04_save_{project.project_id}"):
            f4.save_inputs(project, overview, process, loading)
            save_project(project)
            st.success("저장했습니다. 별지 제5호에서도 공정개요를 다시 묻지 않습니다.")
    else:
        missing = f4.missing(project)
        if missing:
            st.warning("아직 필요한 정보: " + ", ".join(missing))
        else:
            st.success("모든 칸이 채워졌습니다.")
        try:
            st.download_button(
                "화학사고예방관리계획서 규정서식 작성본 DOCX 다운로드",
                data=build_cap_baseline_draft(project), file_name=cap_baseline_filename(project),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"cap_form04_download_{project.project_id}",
            )
        except Exception as exc:
            st.error(f"규정서식 작성본을 만들지 못했습니다: {type(exc).__name__}: {exc}")
