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
            st.warning("화학물질 목록이 없습니다. 아래에서 단일물질을 직접 추가하거나 엑셀·CSV로 물질 목록을 올려 주세요.")


        def add_uploaded(good, file_name, sha256):
            added, skipped = chem_upload.add_to_project(project, good, file_name=file_name, sha256=sha256, sds_confirmed=True)
            save_project(project)
            return f"{file_name}에서 물질 {added}건을 추가했습니다(건너뜀 {skipped}건). 별지 제1·6·7호에서 함께 사용합니다."

        st.markdown("**물질 직접 추가 (단일물질)**")
        with st.form(f"cap_form06_add_{project.project_id}"):
            name = st.text_input("물질명 또는 제품명")
            cas = st.text_input("CAS 번호", help="제품 MSDS에 기재된 단일물질의 CAS 번호를 적으세요.")
            content = st.text_input("함량(%, 알면 입력)", help="MSDS에 함량이 없으면 비워 두고 나중에 확인할 수 있습니다.")
            submitted = st.form_submit_button("물질 추가")
        if submitted:
            raw = {"제품명": name, "CAS No.": cas, "혼합물 여부": "N", "함량(%)": content}
            checked = chem_upload.check_rows([raw], *chem_upload.existing_keys(project))
            if not checked.rows or not checked.rows[0]["_ok"]:
                st.warning(checked.rows[0]["확인"] if checked.rows else "물질명과 CAS 번호를 확인해 주세요.")
            else:
                added, _ = chem_upload.add_to_project(
                    project, [raw], file_name="화면 직접 입력", sha256="",
                )
                if added:
                    save_project(project)
                    st.rerun()

        chemical_upload_panel.render("cap_form06_upload", existing=chem_upload.existing_keys(project), add_rows=add_uploaded)
    elif step["id"] == "properties":
        cap_kosha_panel.render(project, "cap_form06")
        st.subheader("물성 확인·입력")
        columns = f6.PROPERTY_COLUMNS
        frame = pd.DataFrame(f6.property_rows(project), columns=["물질명", "CAS 번호", *f6.COLUMN_IDS])
        config = {"물질명": st.column_config.TextColumn("물질명", disabled=True),
                  "CAS 번호": st.column_config.TextColumn("CAS 번호", disabled=True)}
        for column, label, help_text in columns:
            if column in f6.PROPERTY_SELECT_OPTIONS:
                config[column] = st.column_config.SelectboxColumn(
                    label, options=f6.property_choice_options(column, frame[column]),
                    help=help_text, required=False,
                )
            else:
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
