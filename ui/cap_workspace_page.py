from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft, cap_baseline_filename
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
    projects = list_projects()
    if not projects:
        st.info("저장된 작성 프로젝트가 없습니다. 먼저 1. 판정진단부터 진행하세요.")
        return None
    labels = {
        row["project_id"]: f"{row['company_name']} · {row['project_id']}" for row in projects
    }
    ids = list(labels)
    current = st.session_state.get(ACTIVE_PROJECT_KEY)
    selected = st.selectbox(
        "작성 프로젝트", ids, index=ids.index(current) if current in ids else 0,
        format_func=lambda pid: labels[pid],
    )
    st.session_state[ACTIVE_PROJECT_KEY] = selected
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


st.set_page_config(page_title="화학사고예방관리계획서 작성", page_icon="📝", layout="wide")
st.title("📝 화학사고예방관리계획서 작성")

project_id = _project_selector()
if not project_id:
    st.stop()
project = load_project(project_id)
if not project.cap_in_scope:
    st.warning("이 프로젝트는 화학사고예방관리계획서를 작성 대상으로 선택하지 않았습니다. 2. 작성범위 선택에서 확인하세요.")
    st.stop()

schema = ws.load_form_schema(1)
st.header(schema["title"])
st.caption(schema["help_status"])
st.caption(
    "표의 각 칸 머리글에 마우스를 올리면 작성 방법이 나옵니다. 직접 입력한 시설 자료를 저장하면 아래 서식 표가 바로 갱신됩니다."
)

# ---- 1. facility grid (editable) -------------------------------------------
fac = ws.section(1, "facility_table")
st.subheader(fac["title"])
st.info("※ " + fac["form_note"])
rows = ws.facility_editor_rows(project)
columns = ws.facility_columns()
frame = pd.DataFrame(rows, columns=[c["id"] for c in columns])
for col in columns:
    if col.get("kind") == "number":
        frame[col["id"]] = pd.to_numeric(frame[col["id"]], errors="coerce")
edited = st.data_editor(
    frame,
    column_config=_column_config(columns),
    num_rows="dynamic",
    width="stretch",
    key=f"cap_form01_facilities_{project.project_id}",
)
if st.button("시설 자료 저장", type="primary", key=f"cap_form01_save_{project.project_id}"):
    saved = ws.save_facility_rows(
        project, [{k: ("" if pd.isna(v) else v) for k, v in row.items()} for row in edited.to_dict("records")]
    )
    if saved:
        save_project(project)
        st.success(f"시설 {saved}건을 저장했습니다.")
        st.rerun()
    else:
        st.warning("저장할 시설 자료가 없습니다.")

with st.expander("설계용량(내용적) 계산기"):
    st.caption(
        "치수(m)만 알 때의 기하학적 내용적입니다. 접시형 경판 등은 반영하지 않으므로, "
        "매뉴얼이 다른 산식을 정한 설비는 설계도서의 설계용량을 그대로 입력하세요."
    )
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
        st.caption("위 표의 '설계용량' 칸에 이 값을 m3 단위로 입력하세요. (계산값)")

with st.expander("KOSHA 물질 조회 (단일물질만)"):
    st.caption("CAS 번호만 KOSHA로 전송합니다. 혼합물은 조회하지 않습니다. 결과는 후보이며 회사 SDS와 대조해 확인하세요.")
    cas = st.text_input("CAS 번호", key="cap_form01_cas")
    if st.button("조회", key="cap_form01_kosha") and cas.strip():
        found = ws.kosha_name_candidate(cas.strip())
        if found["chemical_name"]:
            st.success(f"KOSHA 물질명 후보: {found['chemical_name']}  ·  {found['origin']}")
        else:
            st.warning(found["message"])

# ---- 2. derived tables ------------------------------------------------------
form = ws.resolve_form1(project)
st.divider()
st.caption(f"표시 중인 서식 값의 출처: {ws.facility_origin(project)}")

if form.needs:
    st.warning("이 서식을 채우려면 아직 필요한 자료")
    for item in form.needs:
        st.write(f"• {item}")
for blocker in form.blockers:
    st.error(blocker)
for message in form.messages:
    st.caption(message)

st.subheader("서식 1페이지 — 취급시설 목록")
if form.facility_rows:
    st.dataframe(pd.DataFrame(form.facility_rows).drop(columns=["산정근거"], errors="ignore"), width="stretch")
else:
    st.caption("취급시설 자료가 입력되면 서식 표가 여기에 나타납니다.")

chem = ws.section(1, "chemical_table")
st.subheader("서식 2페이지 — 유해화학물질별 최대보유량·작성수준")
if form.chemical_rows:
    chem_help = ws.column_help(1, "chemical_table")
    st.dataframe(
        pd.DataFrame(form.chemical_rows),
        column_config={name: st.column_config.Column(name, help=text) for name, text in chem_help.items()},
        width="stretch",
    )
else:
    st.caption("화학물질 목록이 확정되면 표시됩니다.")

st.subheader("서식 3페이지 — 작성수준")
st.metric("작성수준", form.writing_level or "미확정", help=ws.section(1, "writing_level")["help"])

# ---- 3. output --------------------------------------------------------------
st.divider()
try:
    st.download_button(
        "화학사고예방관리계획서 규정서식 작성본 DOCX 다운로드",
        data=build_cap_baseline_draft(project),
        file_name=cap_baseline_filename(project),
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key=f"cap_form01_download_{project.project_id}",
    )
except Exception as exc:
    st.error(f"규정서식 작성본을 만들지 못했습니다: {type(exc).__name__}: {exc}")
