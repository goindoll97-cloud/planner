from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import cap_frames as frames

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


def _project_selector() -> str | None:
    from ui import cap_start_panel

    projects = list_projects()
    if not projects:
        st.info("작성할 사업장이 아직 없습니다. 아래에서 사업장과 취급 물질을 적고 시작하세요.")
        cap_start_panel.render(expanded=True)
        return None
    labels = {row["project_id"]: f"{row['company_name']} · {row['project_id']}" for row in projects}
    ids = list(labels)
    current = st.session_state.get(ACTIVE_PROJECT_KEY)
    selected = st.selectbox(
        "작성 프로젝트", ids, index=ids.index(current) if current in ids else 0,
        format_func=lambda pid: labels[pid],
    )
    st.session_state[ACTIVE_PROJECT_KEY] = selected
    cap_start_panel.render(expanded=False)
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
if not project.cap_in_scope:
    if project.psm_in_scope:
        st.info("이 사업장은 공정안전보고서 작성 대상입니다. 화학사고예방관리계획서 대상은 아닙니다.")
        st.page_link("ui/psm_workspace_page.py", label="공정안전보고서 작성으로 이동", icon="🏭")
        st.stop()
    st.warning("이 사업장은 화학사고예방관리계획서 작성·제출 대상으로 확인되지 않았습니다. 위에서 다른 사업장을 고르거나 "
               "'새 사업장으로 시작하기'에서 다시 판정하세요.")
    st.stop()

from ui import cap_excel_panel
from ui import cap_forms_registry as registry

cap_excel_panel.render(project)

# 별지 제13호(총괄영향범위)는 별지 제12호 화면에서 함께 만든다.
form_no = st.selectbox(
    "작성할 서식(별지 순서대로)", list(registry.FORM_NUMBERS),
    format_func=lambda n: f"{registry.label(n)} · {form_guidelines()[n].title}", key="cap_form_no",
)
if form_no != 1:
    import importlib

    extra_view = importlib.import_module(f"ui.cap_form{form_no}_view")

    extra_view.render(project)
    st.stop()

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

fac = ws.section(1, "facility_table")
columns = ws.facility_columns()
core_ids = [c["id"] for c in columns]


def _grid_frame() -> pd.DataFrame:
    frame = pd.DataFrame(ws.facility_editor_rows(project), columns=core_ids)
    for col in columns:
        if col.get("kind") == "number":
            frame[col["id"]] = pd.to_numeric(frame[col["id"]], errors="coerce")
    return frame


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
        st.warning("확정된 화학물질 목록이 없습니다. 1. 판정진단에서 물질 목록을 먼저 입력하세요.")
    st.caption("물질 물성(상태·비중·폭발한계 등)은 별지 제6호에서 KOSHA 조회로 채웁니다.")


    st.subheader("시설 표")
    st.info("※ " + fac["form_note"])
    edited = st.data_editor(
        _grid_frame(),
        column_config=_column_config(columns),
        num_rows="dynamic",
        width="stretch",
        key=f"cap_form01_facilities_{project.project_id}",
    )
    rows = [{k: ("" if pd.isna(v) else v) for k, v in row.items()} for row in edited.to_dict("records")]
    saved_rows = {
        (str(r.get("설비번호") or ""), str(r.get("설비명") or "")): r for r in ws.facility_editor_rows(project)
    }
    for index, row in enumerate(rows):
        old = saved_rows.get((str(row.get("설비번호") or ""), str(row.get("설비명") or "")), {})
        row.update({k: old[k] for k in ws.EXTRA_FIELDS if k in old})
        wanted = ws.extra_fields_for(row)
        label = str(row.get("설비명") or row.get("설비번호") or f"{index + 1}번째 시설")
        if wanted:
            with st.expander(f"{label} — 추가로 필요한 정보", expanded=True):
                for field_id in wanted:
                    spec = ws.EXTRA_FIELDS[field_id]
                    key = f"cap_form01_extra_{project.project_id}_{index}_{field_id}"
                    value = row.get(field_id, "")
                    if spec["kind"] == "choice":
                        options = [""] + list(spec["options"])
                        row[field_id] = st.selectbox(
                            spec["label"], options, help=spec["help"], key=key,
                            index=options.index(value) if value in options else 0,
                        )
                    elif spec["kind"] == "number":
                        number = st.number_input(
                            spec["label"], min_value=0.0, help=spec["help"], key=key,
                            value=float(value) if str(value).strip() not in ("", "nan") else 0.0,
                        )
                        row[field_id] = number if number else ""
                    else:
                        row[field_id] = st.text_input(spec["label"], value=str(value), help=spec["help"], key=key)
        for field_id in ws.EXTRA_FIELDS:
            if field_id not in wanted:
                row.pop(field_id, None)

    live = ws.compute_holdings(project, rows) if rows else []
    if live:
        st.subheader("계산 결과 미리보기")
        frames.show(
            pd.DataFrame([
                {
                    "취급시설": r.get("설비명") or r.get("설비번호"),
                    "최대보유량(ton)": None if x.ton is None else round(x.ton, 6),
                    "산정 방법 / 필요한 정보": x.basis or x.problem,
                }
                for r, x in zip(rows, live)
            ]),
            width="stretch", hide_index=True,
        )
    if st.button("시설 자료 저장", type="primary", key=f"cap_form01_save_{project.project_id}"):
        saved = ws.save_facility_rows(project, rows)
        if saved:
            save_project(project)
            st.success(f"시설 {saved}건을 저장했습니다. 4. 결과에서 확인하세요.")
        else:
            st.warning("저장할 시설 자료가 없습니다.")

    with st.expander("설계용량 계산기 (치수만 알 때)"):
        st.caption("치수(m)로 구한 기하학적 내용적입니다. 접시형 경판 등은 반영하지 않으므로 설계도서의 설계용량이 있으면 그 값을 쓰세요.")
        shape = st.selectbox("형태", list(SHAPES), format_func=lambda key: SHAPES[key], key="cap_form01_shape")
        dims = {}
        dim_cols = st.columns(len(SHAPE_DIMENSIONS[shape]))
        for column, name in zip(dim_cols, SHAPE_DIMENSIONS[shape]):
            dims[name] = column.number_input(DIM_LABELS[name], min_value=0.0, value=0.0, key=f"cap_form01_dim_{shape}_{name}")
        volume = ws.volume_from_dimensions(shape, **dims)
        if volume is None:
            st.caption("모든 치수를 0보다 크게 입력하면 계산됩니다.")
        else:
            st.metric("계산된 설계용량", f"{volume:g} m³")
            st.caption("표의 '설계용량'에 이 값을 m3 단위로 넣으세요.")

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
        help="판정진단에서 승계된 값입니다. 바꾸려면 판정진단을 다시 수행합니다.",
    )
    st.info(f"이 서식의 물질별 최대보유량으로 본 결과: **{hint_label}** — {hint_reason}")
    st.caption("1군은 주요취급시설(규칙 제19조제8항)을 운영하는 경우에 해당합니다. 그 여부는 판정진단에서 확인한 값을 따릅니다.")

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
    from ui import attachments_panel, cap_final_evidence_panel, report_export_panel
    from engine.stage2 import psm_attachments

    with st.expander("최종 제출 확인 · 타 제도 심사결과와 공동제출"):
        cap_final_evidence_panel.render(project)
    with st.expander("첨부 자료 · 도면과 분석 자료 올리기"):
        attachments_panel.render(project, psm_attachments.CAP_SLOTS, "cap")
    st.markdown("### 점검하고 내려받기")

    report_export_panel.render(project, "CAP")
