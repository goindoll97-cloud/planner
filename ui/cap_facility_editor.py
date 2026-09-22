"""별지 제1호 시설 표(시설 입력 → 최대보유량 계산). 별지 작성 화면과 판정 화면이 같은 표를 쓴다."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_calc import SHAPE_DIMENSIONS, SHAPES
from engine.stage2.storage import save_project
from ui import cap_frames as frames

DIM_LABELS = {
    "diameter_m": "지름(m)",
    "height_m": "높이(m)",
    "length_m": "길이(m)",
    "width_m": "폭(m)",
}


def column_config(columns: list[dict]) -> dict:
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


def render(project, prefix: str = "cap_form01", on_saved=None, compact: bool = False) -> None:
    """시설 표를 그리고 저장한다. on_saved(저장한 시설 수)를 주면 저장 뒤 기본 안내문 대신 그것을 부른다."""
    fac = ws.section(1, "facility_table")
    columns = ws.facility_columns()
    core_ids = [c["id"] for c in columns]


    def _grid_frame() -> pd.DataFrame:
        frame = pd.DataFrame(ws.facility_editor_rows(project), columns=core_ids)
        for col in columns:
            if col.get("kind") == "number":
                frame[col["id"]] = pd.to_numeric(frame[col["id"]], errors="coerce")
        return frame


    if not compact:  # 판정 화면 안에서는 제목·안내 상자 없이 표만 보여 준다(안내는 위쪽 제목의 ? 안에 있다)
        st.subheader("시설 표")
        st.info("※ " + fac["form_note"])
    edited = st.data_editor(
        _grid_frame(),
        column_config=column_config(columns),
        num_rows="dynamic",
        width="stretch",
        key=f"{prefix}_facilities_{project.project_id}",
    )
    rows = [{k: ("" if pd.isna(v) else v) for k, v in row.items()} for row in edited.to_dict("records")]
    saved_rows = {
        (str(r.get("설비번호") or ""), str(r.get("설비명") or "")): r for r in ws.facility_editor_rows(project)
    }
    gravity_pool = ws.gravity_candidates(project)
    for index, row in enumerate(rows):
        old = saved_rows.get((str(row.get("설비번호") or ""), str(row.get("설비명") or "")), {})
        row.update({k: old[k] for k in ws.EXTRA_FIELDS if k in old})
        wanted = ws.extra_fields_for(row)
        label = str(row.get("설비명") or row.get("설비번호") or f"{index + 1}번째 시설")
        gravity_matches = ws.gravity_matches_for(row, gravity_pool)
        if wanted or gravity_matches:
            with st.expander(f"{label} — 추가로 필요한 정보", expanded=True):
                if gravity_matches:
                    options = ["직접 입력", *[f"{m['비중']:g} ({m['물질명']})" for m in gravity_matches]]
                    current = str(row.get("비중") or "").strip()
                    default = 0
                    if current.replace(".", "", 1).replace("-", "", 1).isdigit():
                        default = next(
                            (i for i, m in enumerate(gravity_matches, start=1) if abs(m["비중"] - float(current)) < 1e-9),
                            0,
                        )
                    picked = st.selectbox(
                        "비중 참고값(화학물질 목록에서)", options, index=default,
                        key=f"{prefix}_gravity_{project.project_id}_{index}",
                        help="시설 표의 '취급물질'과 이름이 같은 화학물질의 비중입니다(별지 제6호에서 확인한 값). "
                             "물질이 다르거나 값이 안 맞으면 '직접 입력'을 고르고 표의 비중 칸에 직접 적으세요.",
                    )
                    if picked != "직접 입력":
                        row["비중"] = gravity_matches[options.index(picked) - 1]["비중"]
                for field_id in wanted:
                    spec = ws.EXTRA_FIELDS[field_id]
                    key = f"{prefix}_extra_{project.project_id}_{index}_{field_id}"
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
    if st.button("시설 자료 저장", type="primary", key=f"{prefix}_save_{project.project_id}"):
        saved = ws.save_facility_rows(project, rows)
        if saved:
            save_project(project)
            if on_saved is not None:
                on_saved(saved)
            else:
                st.success(f"시설 {saved}건을 저장했습니다. 4. 결과에서 확인하세요.")
        else:
            st.warning("저장할 시설 자료가 없습니다.")

    with st.expander("설계용량 계산기 (치수만 알 때)"):
        st.caption("치수(m)로 구한 기하학적 내용적입니다. 접시형 경판 등은 반영하지 않으므로 설계도서의 설계용량이 있으면 그 값을 쓰세요.")
        shape = st.selectbox("형태", list(SHAPES), format_func=lambda key: SHAPES[key], key=f"{prefix}_shape")
        dims = {}
        dim_cols = st.columns(len(SHAPE_DIMENSIONS[shape]))
        for column, name in zip(dim_cols, SHAPE_DIMENSIONS[shape]):
            dims[name] = column.number_input(DIM_LABELS[name], min_value=0.0, value=0.0, key=f"{prefix}_dim_{shape}_{name}")
        volume = ws.volume_from_dimensions(shape, **dims)
        if volume is None:
            st.caption("모든 치수를 0보다 크게 입력하면 계산됩니다.")
        else:
            st.metric("계산된 설계용량", f"{volume:g} m³")
            st.caption("표의 '설계용량'에 이 값을 m3 단위로 넣으세요.")
