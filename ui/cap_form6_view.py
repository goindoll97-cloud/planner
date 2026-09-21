from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import cap_frames as frames

from engine.stage2 import cap_form6_workspace as f6
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft, cap_baseline_filename
from engine.stage2.storage import save_project
from ui import cap_kosha_panel, chemical_upload_panel
from engine.stage2 import cap_chemical_upload as chem_upload


def render(project) -> None:
    schema = ws.load_form_schema(6)
    steps = schema["steps"]
    titles = [step["title"] for step in steps]
    st.header(schema["title"])
    choice = st.radio("단계", titles, horizontal=True, label_visibility="collapsed", key="cap_form06_step")
    step = steps[titles.index(choice)]
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])

    if step["id"] == "identity":
        rows, _ = f6.legal_rows(project)
        if rows:
            frames.show(
                pd.DataFrame([{
                    "물질명": r.get("물질명") or r.get("유해화학물질명"),
                    "CAS 번호": r.get("CAS 번호") or r.get("CAS No."),
                    "함량(%)": r.get("함량(%)") or r.get("함량"),
                    "물질구분": r.get("물질구분") or "규정 DB 확인 필요",
                    "고유번호": r.get("고유번호") or "규정 DB 확인 필요",
                } for r in rows]),
                width="stretch", hide_index=True,
            )
        else:
            st.warning("화학물질 목록이 없습니다. 아래 '엑셀·CSV로 물질 목록 올리기'로 넣거나, 새 사업장으로 시작하기에서 물질을 입력하세요.")


        def add_uploaded(good, file_name, sha256):
            added, skipped = chem_upload.add_to_project(project, good, file_name=file_name, sha256=sha256, sds_confirmed=True)
            save_project(project)
            return (f"{file_name}에서 물질 {added}건을 추가했습니다(건너뜀 {skipped}건). 물질을 추가하면 법정 작성 대상 판정이 "
                    "달라질 수 있습니다. 시작하기의 판정은 처음 입력한 물질 기준입니다.")

        chemical_upload_panel.render("cap_form06_upload", existing=chem_upload.existing_keys(project), add_rows=add_uploaded)
    elif step["id"] == "properties":
        cap_kosha_panel.render(project, "cap_form06")
        st.subheader("물성 확인·입력")
        columns = f6.PROPERTY_COLUMNS
        frame = pd.DataFrame(f6.property_rows(project), columns=["물질명", "CAS 번호", *f6.COLUMN_IDS])
        config = {"물질명": st.column_config.TextColumn("물질명", disabled=True),
                  "CAS 번호": st.column_config.TextColumn("CAS 번호", disabled=True)}
        for column, label, help_text in columns:
            config[column] = st.column_config.TextColumn(label, help=help_text)
        edited = st.data_editor(frame, column_config=config, width="stretch", hide_index=True,
                                key=f"cap_form06_props_{project.project_id}")
        if st.button("물성 저장", type="primary", key=f"cap_form06_save_{project.project_id}"):
            changed = f6.save_properties(project, edited.to_dict("records"))
            save_project(project)
            st.success(f"{changed}개 칸을 저장했습니다.")
    else:
        _, blockers = f6.legal_rows(project)
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
                key=f"cap_form06_download_{project.project_id}",
            )
        except Exception as exc:
            st.error(f"규정서식 작성본을 만들지 못했습니다: {type(exc).__name__}: {exc}")
