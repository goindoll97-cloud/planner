from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.stage2 import cap_form16_workspace as f16
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft, cap_baseline_filename
from engine.stage2.storage import save_project


def _group(project, group: str) -> None:
    saved = False
    edits = {}
    for item in f16.items(group):
        current = f16.current_text(project, item)
        seed = f16.seed(project, item) if not current else ""
        with st.expander(f"{item['label']}  ·  {item['law']}", expanded=not current):
            st.markdown("**포함할 내용**")
            for line in item["checklist"]:
                st.markdown(f"- {line}")
            if seed:
                st.caption("앞 서식 정보로 만든 초안입니다. 실제 계획과 맞게 고쳐 저장하세요.")
            edits[item["id"]] = st.text_area(
                item["label"], value=current or seed, height=150,
                key=f"cap_form16_{project.project_id}_{item['id']}", label_visibility="collapsed",
            )
    if st.button("저장", type="primary", key=f"cap_form16_save_{group}_{project.project_id}"):
        for item in f16.items(group):
            saved = f16.save_text(project, item, edits.get(item["id"], "")) or saved
        save_project(project)
        st.success("저장했습니다." if saved else "저장할 내용이 없습니다.")


def render(project) -> None:
    schema = ws.load_form_schema(16)
    steps = schema["steps"]
    titles = [step["title"] for step in steps]
    st.header(schema["title"])
    choice = st.radio("단계", titles, horizontal=True, label_visibility="collapsed", key="cap_form16_step")
    step = steps[titles.index(choice)]
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])

    if step["id"] == "internal":
        _group(project, "internal")
    elif step["id"] == "external":
        if not f16.external_required(project):
            st.info(f"작성수준이 '{project.cap_group or '미확정'}'입니다. 2군 사업장은 외부 비상대응(제6절)을 생략할 수 있습니다(작성 규정 제35조). "
                    "1군이면 아래를 작성해야 합니다.")
        _group(project, "external")
    else:
        data = f16.status(project)
        st.subheader("자동으로 채워진 부분")
        st.write({k: v for k, v in data.business.items() if k not in ("작성일 기준",)})
        if data.chemical_rows:
            st.dataframe(pd.DataFrame(data.chemical_rows), width="stretch", hide_index=True)
        if data.scenario_rows:
            st.dataframe(pd.DataFrame(data.scenario_rows).drop(columns=["KORA/GIS 근거"], errors="ignore"),
                         width="stretch", hide_index=True)
        blockers = list(data.company_blockers) + list(data.dependency_blockers)
        if blockers:
            st.warning("아직 필요한 정보")
            for item in blockers:
                st.write(f"• {item}")
        else:
            st.success("모든 칸이 채워졌습니다.")
        try:
            st.download_button(
                "화학사고예방관리계획서 규정서식 작성본 DOCX 다운로드",
                data=build_cap_baseline_draft(project), file_name=cap_baseline_filename(project),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"cap_form16_download_{project.project_id}",
            )
        except Exception as exc:
            st.error(f"규정서식 작성본을 만들지 못했습니다: {type(exc).__name__}: {exc}")
