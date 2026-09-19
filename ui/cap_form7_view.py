from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.stage2 import cap_form6_workspace as f6
from engine.stage2 import cap_form7_workspace as f7
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft, cap_baseline_filename
from engine.stage2.storage import save_project

NARRATIVE = ("인체유해성", "물리적 위험성", "환경유해성")


def _selected_key(project) -> str:
    return f"cap_form07_selected_{project.project_id}"


def render(project) -> None:
    schema = ws.load_form_schema(7)
    steps = schema["steps"]
    titles = [step["title"] for step in steps]
    st.header(schema["title"])
    choice = st.radio("단계", titles, horizontal=True, label_visibility="collapsed", key="cap_form07_step")
    step = steps[titles.index(choice)]
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])

    rows = f6.property_rows(project)
    names = {r["CAS 번호"]: r["물질명"] for r in rows}
    suggestions = {s.cas: s for s in f7.suggest_representatives(project)}
    saved = {r.get("CAS 번호"): r for r in f7.saved_rows(project)}

    if step["id"] == "select":
        if suggestions:
            st.dataframe(
                pd.DataFrame([{"물질": s.name, "CAS": s.cas, "구분": " · ".join(s.kinds), "제안 사유": s.reason}
                              for s in suggestions.values()]),
                width="stretch", hide_index=True,
            )
        else:
            st.warning("별지 제6호의 폭발한계 하한·독성구분이 비어 있어 제안할 수 없습니다. 별지 제6호 물성을 먼저 채우세요.")
        default = [cas for cas in (saved or suggestions) if cas in names]
        chosen = st.multiselect(
            "대표물질(화재·폭발 2종 + 독성 2종, 중복 합산)", list(names), default=default,
            format_func=lambda cas: f"{names[cas]} ({cas})", key=_selected_key(project),
        )
        if st.button("대표물질 저장", type="primary", key=f"cap_form07_save_sel_{project.project_id}"):
            keep = [dict(saved[cas]) if cas in saved else f7.draft_row(
                project, cas, names[cas], suggestions[cas].reason if cas in suggestions else "") for cas in chosen]
            f7.save_rows(project, keep)
            save_project(project)
            st.success(f"{len(keep)}종을 저장했습니다. 다음 단계에서 서술을 확인하세요.")
    elif step["id"] == "narrative":
        current = f7.saved_rows(project)
        if not current:
            st.info("먼저 1단계에서 대표물질을 저장하세요.")
        edited = []
        for index, row in enumerate(current):
            with st.expander(f"{row.get('물질명')} ({row.get('CAS 번호')})", expanded=True):
                updated = dict(row)
                for field in (*NARRATIVE, "선정 사유"):
                    updated[field] = st.text_area(
                        field, value=row.get(field, ""), key=f"cap_form07_{project.project_id}_{index}_{field}",
                    )
                edited.append(updated)
        if current and st.button("서술 저장", type="primary", key=f"cap_form07_save_text_{project.project_id}"):
            f7.save_rows(project, edited)
            save_project(project)
            st.success("저장했습니다.")
    else:
        needs = f7.needs(project)
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
                key=f"cap_form07_download_{project.project_id}",
            )
        except Exception as exc:
            st.error(f"규정서식 작성본을 만들지 못했습니다: {type(exc).__name__}: {exc}")
