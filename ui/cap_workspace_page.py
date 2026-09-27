from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import cap_facility_editor, cap_frames as frames

from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_guideline import form_guidelines
from engine.stage2.cap_calc import SHAPE_DIMENSIONS, SHAPES
from engine.stage2.storage import list_projects, load_project, save_project

ACTIVE_PROJECT_KEY = "_stage2_active_project_id"
DIM_LABELS = {
    "diameter_m": "지름(m)",
    "height_m": "높이(m)",
    "length_m": "길이(m)",
    "width_m": "폭(m)",
}


def _direct_start(expanded: bool) -> None:
    from engine.stage2.direct_template import create_direct_cap_project

    with st.expander("판정 없이 화사계 작성 시작", expanded=expanded):
        st.caption("이미 작성 대상인지 확인한 사업장은 여기서 바로 시작할 수 있습니다. 작성수준은 알 때만 선택하고, 별지 제1호의 최대보유량과 작성수준은 제출 전 확인하세요.")
        with st.form("cap_direct_start"):
            name = st.text_input("사업장명", key="cap_direct_name")
            address = st.text_input("사업장 주소", key="cap_direct_address")
            group = st.selectbox("작성수준 (알면 선택)", ["확인 전", "1군", "2군"], key="cap_direct_group")
            submitted = st.form_submit_button("화사계 작성 시작")
        if submitted:
            try:
                project = create_direct_cap_project(
                    name, address=address, cap_group="" if group == "확인 전" else group,
                )
            except ValueError as exc:
                st.warning(str(exc))
                return
            save_project(project)
            st.session_state[ACTIVE_PROJECT_KEY] = project.project_id
            st.rerun()


def _project_selector() -> str | None:
    projects = list_projects()
    if not projects:
        st.info("작성할 사업장이 아직 없습니다. 사업장 정보를 적고 바로 별지 작성을 시작하세요.")
        _direct_start(expanded=True)
        return None
    labels = {row["project_id"]: f"{row['company_name']} · {row['project_id']}" for row in projects}
    ids = list(labels)
    current = st.session_state.get(ACTIVE_PROJECT_KEY)
    selected = st.selectbox(
        "작성 프로젝트", ids, index=ids.index(current) if current in ids else 0,
        format_func=lambda pid: labels[pid],
    )
    st.session_state[ACTIVE_PROJECT_KEY] = selected
    _direct_start(expanded=False)
    return selected


def _column_config(columns: list[dict]) -> dict:
    config = {}
    for col in columns:
        kind = col.get("kind", "text")
        if kind == "number":
            config[col["id"]] = st.column_config.NumberColumn(col["label"], help=col.get("help"), min_value=0)
        elif kind == "choice":
            config[col["id"]] = st.column_config.SelectboxColumn(
                col["label"], help=col.get("help"), options=col.get("options", [])
            )
        else:
            config[col["id"]] = st.column_config.TextColumn(col["label"], help=col.get("help"))
    return config


def _explain(step: dict) -> None:
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])


st.set_page_config(page_title="화학사고예방관리계획서 작성", page_icon="📝", layout="wide")
st.title("📝 화학사고예방관리계획서 작성")

project_id = _project_selector()
if not project_id:
    st.stop()
project = load_project(project_id)
from engine.stage2 import cap_judgement
from engine.stage2.standalone_entry import is_standalone_stage2_project

if is_standalone_stage2_project(project) and not project.stage1_snapshot.get("legal_applicability_confirmed"):
    st.info("판정 없이 시작한 작성 프로젝트입니다. 법정 제출 대상 여부는 별도 ‘사업장 판정하기’에서 확인할 수 있습니다.")
    with st.expander("작성수준 확인 (별지 제1호)", expanded=not project.cap_group):
        chosen = st.selectbox(
            "회사가 확인한 작성수준", ["확인 전", "1군", "2군"],
            index={"": 0, "1군": 1, "2군": 2}.get(project.cap_group, 0),
            key=f"cap_direct_level_{project.project_id}",
        )
        if st.button("작성수준 저장", key=f"cap_direct_level_save_{project.project_id}"):
            project.cap_group = "" if chosen == "확인 전" else chosen
            if project.cap_group:
                project.set_field("cap.business.writing_level", "작성수준", f"{project.cap_group} 사업장",
                                  "USER_CONFIRMED", note="회사 확인값, 대상 판정 수행하지 않음")
            else:
                project.fields.pop("cap.business.writing_level", None)
            save_project(project)
            st.rerun()
if not project.cap_in_scope and not cap_judgement.undecided(project):
    if project.psm_in_scope:
        st.info("이 사업장은 공정안전보고서 작성 대상입니다. 화학사고예방관리계획서 대상은 아닙니다.")
        st.page_link("ui/psm_workspace_page.py", label="공정안전보고서 작성으로 이동", icon="🏭")
        st.stop()
    st.warning("이 사업장은 화학사고예방관리계획서 작성·제출 대상으로 확인되지 않았습니다. 위에서 다른 사업장을 고르거나 "
               "'사업장 판정하기'에서 확인하세요.")
    st.stop()

from ui import version_panel

version_panel.render(project, "CAP")

from ui import cap_forms_registry as registry

SPECIAL = {
    "submission": "제출·변경 행정서식 · 별지 제31호·제32호",
    "implementation": "이행점검 · 자체점검 별지 제1호~제3호",
    "narrative": "서술형 항목 · 사전관리방침과 비상대응계획",
    "export": "점검·내보내기 · 보고서 내려받기",
}


def _option_label(option) -> str:
    if option in SPECIAL:
        return SPECIAL[option]
    return f"{registry.label(option)} · {form_guidelines()[option].title}"


from ui import unsaved_guard


def _render_form1(project) -> None:
    schema = ws.load_form_schema(1)
    steps = ws.steps(1)
    titles = ["1. 시설 입력", "2. 결과", "3. 서식 내보내기"]
    step_ids = ["inputs", "result", "export"]

    st.header(schema["title"])
    step_title = st.radio("단계", titles, horizontal=True, label_visibility="collapsed", key="cap_form01_step")
    step_id = step_ids[titles.index(step_title)]
    if step_id == "inputs":
        st.caption("아래 표에 시설을 한 줄씩 입력하세요. 물질 목록은 시작하기에서 입력한 값이 자동으로 들어와 있고, 최대보유량은 프로그램이 계산합니다.")
        for part in steps:
            if part["id"] in ("scope", "facilities", "chemicals"):
                for item in part["explain"]:
                    with st.expander(item["term"]):
                        st.write(item["text"])
    else:
        current = next((step for step in steps if step["id"] == step_id), None)
        if current:
            _explain(current)

    if step_id == "inputs":
        st.subheader("취급 물질")
        chemicals = ws.form1._chemical_identity_rows(project)
        if chemicals:
            frames.show(
                pd.DataFrame([
                    {
                        "물질명": ws.form1._row_value(row, "물질명", "유해화학물질명", "제품명"),
                        "CAS No.": ws.form1._row_value(row, "CAS 번호", "CAS No."),
                        "함량(%)": ws.form1._row_value(row, "함량(%)", "함량"),
                    }
                    for row in chemicals
                ]),
                width="stretch", hide_index=True,
            )
        else:
            st.warning("물질 목록이 없습니다. 별지 제6호에서 물질을 직접 추가하거나 엑셀·CSV로 올려 주세요.")
        st.caption("별지 제6호에서도 같은 물질 정보를 사용합니다. 단일물질은 아래에서 KOSHA 후보를 조회할 수 있습니다.")
        from ui import cap_kosha_panel

        with st.expander("KOSHA 물질 정보 조회 (참고 후보)"):
            cap_kosha_panel.render(project, "cap_form01")


        cap_facility_editor.render(project, "cap_form01")

    elif step_id == "result":
        form = ws.resolve_form1(project)
        if form.needs:
            st.warning("아직 필요한 정보가 있습니다")
            for item in form.needs:
                st.write(f"• {item}")
        for blocker in form.blockers:
            st.error(blocker)
        for line in ws.result_sentences(list(form.chemical_rows)):
            st.write("• " + line)
        hint_label, hint_reason = ws.level_hint(list(form.chemical_rows), form.writing_level)
        st.metric(
            "사업장 작성수준", form.writing_level or "미확정",
            help="사업장 판정하기에서 승계했거나 회사가 직접 확인해 입력한 작성수준입니다.",
        )
        st.info(f"이 서식의 물질별 최대보유량으로 본 결과: **{hint_label}** — {hint_reason}")
        st.caption("직접 시작한 프로젝트는 제출 전 작성수준과 최대보유량을 확인하세요. 별도 사업장 판정 결과가 있는 프로젝트는 해당 결과를 따릅니다.")

    else:
        form = ws.resolve_form1(project)
        st.write("입력한 자료로 아래 서식이 채워집니다. 규정서식 표 그대로의 DOCX로 내려받을 수 있습니다.")
        with st.expander("서식에 채워지는 내용 미리보기"):
            st.write("**1. 단위공장별 최대보유량 산출**")
            if form.facility_rows:
                frames.show(pd.DataFrame(form.facility_rows).drop(columns=["산정근거"], errors="ignore"), width="stretch", hide_index=True)
            st.write("**2. 유해화학물질별 사업장 내의 최대보유량 산출**")
            if form.chemical_rows:
                frames.show(pd.DataFrame(form.chemical_rows), width="stretch", hide_index=True)
            st.write(f"**3. 작성수준 도출**: {form.writing_level or '미확정'}")
        st.info("점검하고 보고서를 내려받는 곳은 위 선택 목록의 '점검·내보내기'입니다.")


form_no = unsaved_guard.selector("작성할 서식(별지 순서대로)", [*registry.FORM_NUMBERS, *SPECIAL], key="cap_form_no",
                                 format_func=_option_label)
try:
    if form_no in registry.FORM_NUMBERS:
        st.info("MSDS는 물질 정보를 확인할 때 참고하는 자료입니다. MSDS를 첨부하더라도 각 별지의 작성은 별개이며, 해당 별지에서 요구하는 항목을 서식에 맞게 작성해 주세요.")
    if form_no == "submission":
        from ui import cap_submission_forms_view

        cap_submission_forms_view.render(project)
    elif form_no == "implementation":
        from ui import cap_implementation_self_check_view

        cap_implementation_self_check_view.render(project)
    elif form_no == "narrative":
        from engine.stage2 import cap_narrative_workspace as cap_narrative
        from ui import narrative_panel

        narrative_panel.render(project, cap_narrative.CAP_PROFILE, ("cap-contacts", "cap-resources"), "cap",
                               decision_facts=cap_narrative.visible_facts(project))
    elif form_no == "export":
        from ui import attachments_panel, cap_final_evidence_panel, report_export_panel
        from engine.stage2 import psm_attachments

        with st.expander("최종 제출 확인 · 타 제도 심사결과와 공동제출"):
            cap_final_evidence_panel.render(project)
        with st.expander("첨부 자료 · 도면과 분석 자료 올리기"):
            attachments_panel.render(project, psm_attachments.CAP_SLOTS, "cap")
        st.markdown("### 점검하고 내려받기")
        report_export_panel.render(project, "CAP")
    elif form_no != 1:
        import importlib

        extra_view = importlib.import_module(f"ui.cap_form{form_no}_view")

        extra_view.render(project)
    else:
        _render_form1(project)
finally:
    unsaved_guard.finish()
