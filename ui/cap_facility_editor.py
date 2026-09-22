"""시설 최대보유량 입력 UI.

판정 화면(compact=True)은 판정에 필요한 사실만 조건부로 묻고,
별지 제1호 작성 화면은 정식 시설표를 보여 준다. 두 화면은 같은 저장값을 공유한다.
"""

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



COMPACT_CORE_IDS = ("취급물질", "시설유형", "물질성상")


def _clean(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _norm(value) -> str:
    return "".join(_clean(value).lower().split())


def compact_core_frame(project, focus_names: list[str] | None = None) -> pd.DataFrame:
    """판정 화면의 첫 표: 물질·시설유형·상태만 보인다.

    focus_names가 있으면 판정 규칙이 지금 최대보유량을 요구한 물질만 보여 주되,
    해당 물질의 기존 저장행은 그대로 다시 불러온다.
    """
    saved = [dict(row) for row in ws.facility_editor_rows(project)]
    wanted = [_clean(name) for name in (focus_names or []) if _clean(name)]
    if wanted:
        wanted_norm = {_norm(name) for name in wanted}
        visible = [row for row in saved if _norm(row.get("취급물질")) in wanted_norm]
        existing = {_norm(row.get("취급물질")) for row in visible}
        for name in wanted:
            if _norm(name) not in existing:
                visible.append({"취급물질": name})
                existing.add(_norm(name))
    else:
        visible = saved
    return pd.DataFrame(
        [{key: row.get(key, "") for key in COMPACT_CORE_IDS} for row in visible],
        columns=list(COMPACT_CORE_IDS),
    )


def _compact_source_rows(project, focus_names: list[str] | None) -> tuple[list[dict], list[dict]]:
    """(화면에 보이는 저장행, 이번 판정에서 건드리지 않을 다른 저장행)."""
    saved = [dict(row) for row in ws.facility_editor_rows(project)]
    wanted = [_clean(name) for name in (focus_names or []) if _clean(name)]
    if not wanted:
        return saved, []
    wanted_norm = {_norm(name) for name in wanted}
    visible = [row for row in saved if _norm(row.get("취급물질")) in wanted_norm]
    untouched = [row for row in saved if _norm(row.get("취급물질")) not in wanted_norm]
    existing = {_norm(row.get("취급물질")) for row in visible}
    for name in wanted:
        if _norm(name) not in existing:
            visible.append({"취급물질": name})
            existing.add(_norm(name))
    return visible, untouched


def _compact_choice(label: str, options: list[str], value, key: str, help_text: str = "") -> str:
    choices = [""] + list(options)
    current = _clean(value)
    index = choices.index(current) if current in choices else 0
    return st.selectbox(label, choices, index=index, key=key, help=help_text or None)


def _compact_text_number(label: str, value, key: str, help_text: str = "", placeholder: str = "숫자만") -> str:
    return st.text_input(
        label, value=_clean(value), key=key, help=help_text or None, placeholder=placeholder,
    ).strip()


def _compact_direct_mass(row: dict, prefix: str, pid: str, index: int) -> None:
    row["직접확인 최대보유량"] = _compact_text_number(
        "이미 확인한 최대보유량",
        row.get("직접확인 최대보유량"),
        f"{prefix}_compact_direct_{pid}_{index}",
        "회사 산정표나 설비자료에서 이미 최대보유량을 질량으로 확인한 경우 그 값을 적습니다.",
    )
    row["질량단위"] = _compact_choice(
        "질량 단위", ["kg", "ton"], row.get("질량단위"),
        f"{prefix}_compact_mass_unit_{pid}_{index}",
        "바로 위 최대보유량 값의 단위입니다.",
    )
    row["직접확인 근거"] = st.text_input(
        "확인 근거",
        value=_clean(row.get("직접확인 근거")),
        key=f"{prefix}_compact_direct_basis_{pid}_{index}",
        help="예: 탱크 설계도서, 회사 최대보유량 산정표. 근거가 없으면 직접확인 값으로 확정하지 않습니다.",
        placeholder="예: 설비 최대보유량 산정표",
    ).strip()


def _compact_volume_density(project, row: dict, prefix: str, pid: str, index: int, gravity_pool: list[dict]) -> None:
    left, right = st.columns([2, 1])
    row["용량"] = left.text_input(
        "설계용량",
        value=_clean(row.get("용량")),
        key=f"{prefix}_compact_capacity_{pid}_{index}",
        help="설비 명판이나 설계도서에 적힌 최대 설계용량입니다.",
        placeholder="예: 10",
    ).strip()
    row["용량단위"] = right.selectbox(
        "용량 단위", ["", "m3", "L"],
        index=(["", "m3", "L"].index(_clean(row.get("용량단위"))) if _clean(row.get("용량단위")) in {"m3", "L"} else 0),
        key=f"{prefix}_compact_capacity_unit_{pid}_{index}",
        help="설계도서에 적힌 단위를 그대로 고르세요.",
    )

    matches = ws.gravity_matches_for(row, gravity_pool)
    if matches:
        labels = ["직접 입력"] + [f"{m['비중']:g} ({m['물질명']})" for m in matches]
        current = _clean(row.get("비중"))
        default = 0
        try:
            current_num = float(current)
            default = next((i for i, m in enumerate(matches, start=1) if abs(m["비중"] - current_num) < 1e-9), 0)
        except ValueError:
            pass
        picked = st.selectbox(
            "비중/밀도 참고값",
            labels,
            index=default,
            key=f"{prefix}_compact_gravity_pick_{pid}_{index}",
            help="별지 제6호 등에서 이미 확인한 같은 물질의 비중이 있으면 선택할 수 있습니다. 값이 다르면 직접 입력하세요.",
        )
        if picked != "직접 입력":
            row["비중"] = matches[labels.index(picked) - 1]["비중"]

    row["비중"] = _compact_text_number(
        "비중/밀도 (SDS 제9항)",
        row.get("비중"),
        f"{prefix}_compact_gravity_{pid}_{index}",
        "상온에서의 비중 또는 밀도입니다. 보통 제품 SDS 제9항 '물리화학적 특성'에서 확인합니다. "
        "m3를 쓸 때 kg/L 값은 ton/m3와 같은 숫자로 계산됩니다.",
        placeholder="예: 0.87",
    )


def _compact_process(row: dict, prefix: str, pid: str, index: int) -> None:
    row["공정유형"] = _compact_choice(
        "이 시설에서 물질이 어떻게 처리되나요?",
        list(ws.PROCESS_TYPES),
        row.get("공정유형"),
        f"{prefix}_compact_process_{pid}_{index}",
        "그대로 저장·사용하면 '변화없음', 섞기만 하면 '단순혼합', 화학반응이 일어나면 '반응'을 고릅니다.",
    )
    if row["공정유형"] in {"단순혼합", "반응"}:
        row["별표4 기준함량(%)"] = _compact_text_number(
            "계산에 사용할 함량(%)",
            row.get("별표4 기준함량(%)"),
            f"{prefix}_compact_pct_{pid}_{index}",
            "단순혼합은 투입이 끝난 뒤의 최종 함량, 반응은 반응 직전의 최종 함량을 적습니다.",
        )
        row["함량근거"] = st.text_input(
            "함량 확인 자료",
            value=_clean(row.get("함량근거")),
            key=f"{prefix}_compact_pct_basis_{pid}_{index}",
            help="예: 공정 배합표, 제품 SDS. 계산에 사용한 함량의 출처입니다.",
            placeholder="예: 공정 배합표",
        ).strip()


def _compact_gas(project, row: dict, prefix: str, pid: str, index: int) -> None:
    direct = bool(_clean(row.get("직접확인 최대보유량")))
    method = st.radio(
        "기체의 최대보유량을 어떻게 확인할까요?",
        ["운전조건으로 계산", "이미 계산한 값을 입력"],
        index=1 if direct else 0,
        horizontal=True,
        key=f"{prefix}_compact_gas_method_{pid}_{index}",
        help="설비의 용량·압력·온도를 알면 프로그램이 계산할 수 있습니다. 회사에서 이미 법정 방식으로 산정한 값이 있으면 그 값을 입력해도 됩니다.",
    )
    if method == "이미 계산한 값을 입력":
        _compact_direct_mass(row, prefix, pid, index)
        return

    left, right = st.columns([2, 1])
    row["용량"] = left.text_input(
        "설계용량",
        value=_clean(row.get("용량")),
        key=f"{prefix}_compact_gas_capacity_{pid}_{index}",
        help="기체가 들어 있는 설비의 설계용량입니다. 설비 명판이나 설계도서에서 확인합니다.",
        placeholder="예: 5",
    ).strip()
    row["용량단위"] = right.selectbox(
        "용량 단위", ["", "m3", "L"],
        index=(["", "m3", "L"].index(_clean(row.get("용량단위"))) if _clean(row.get("용량단위")) in {"m3", "L"} else 0),
        key=f"{prefix}_compact_gas_capacity_unit_{pid}_{index}",
    )
    row["운전압력(MPa)"] = _compact_text_number(
        "운전압력(MPa, 게이지)",
        row.get("운전압력(MPa)"),
        f"{prefix}_compact_pressure_{pid}_{index}",
        "정상 운전 중 사용하는 압력입니다. 설비 운전자료나 명세서에서 확인합니다.",
        placeholder="예: 0.5",
    )
    row["운전온도(℃)"] = _compact_text_number(
        "운전온도(℃)",
        row.get("운전온도(℃)"),
        f"{prefix}_compact_temp_{pid}_{index}",
        "정상 운전 중의 온도입니다.",
        placeholder="예: 25",
    )
    row["분자량"] = _compact_text_number(
        "분자량(g/mol, 알면 입력)",
        row.get("분자량"),
        f"{prefix}_compact_mw_{pid}_{index}",
        "화학물질 목록에 분자량이 있으면 프로그램이 그 값을 사용할 수 있습니다. 없으면 SDS 제9항 등에서 확인해 적습니다.",
        placeholder="예: 98.9",
    )
    # 계산 방식을 고른 경우 예전에 저장한 직접확인값이 우선하지 않도록 지운다.
    row.pop("직접확인 최대보유량", None)
    row.pop("질량단위", None)
    row.pop("직접확인 근거", None)


def _render_compact(project, prefix: str, on_saved=None, focus_names: list[str] | None = None) -> None:
    """판정용 최소 시설 입력.

    대상 물질은 판정엔진이 정하고 화면에서 잠근다. 같은 물질의 시설이 여러 개일 때만
    사용자가 '시설 추가' 버튼으로 그 물질의 행을 복제한다.
    """
    pid = project.project_id
    names = []
    for name in (focus_names or []):
        clean = _clean(name)
        if clean and clean not in names:
            names.append(clean)

    if not names:
        st.warning("판정 대상 물질이 정해지지 않아 시설정보를 입력할 수 없습니다. 먼저 물질별 확인값을 저장하고 다시 판정해 주세요.")
        return

    source_rows, untouched = _compact_source_rows(project, names)
    extra_key = f"{prefix}_compact_extra_rows_{pid}"
    extra_counts = dict(st.session_state.get(extra_key, {}) or {})

    # 동일 물질의 추가 시설은 사용자가 물질명을 다시 선택하지 않고 해당 물질 버튼으로 만든다.
    st.caption(
        "물질명은 판정 결과에서 자동으로 정해집니다. 시설이 하나면 그대로 입력하고, "
        "같은 물질을 탱크·반응기 등 여러 시설에서 취급할 때만 해당 물질의 '시설 추가'를 누르세요."
    )
    button_cols = st.columns(min(len(names), 3)) if names else []
    for idx, name in enumerate(names):
        col = button_cols[idx % len(button_cols)] if button_cols else st
        if col.button(f"{name} 시설 추가", key=f"{prefix}_add_{pid}_{idx}"):
            extra_counts[name] = int(extra_counts.get(name, 0)) + 1
            st.session_state[extra_key] = extra_counts
            st.rerun()

    # 아직 저장하지 않은 추가 시설행을 자동으로 동일 물질명으로 만든다.
    working_rows = [dict(row) for row in source_rows]
    for name in names:
        for _ in range(int(extra_counts.get(name, 0))):
            working_rows.append({"취급물질": name})

    frame = pd.DataFrame(
        [{key: row.get(key, "") for key in COMPACT_CORE_IDS} for row in working_rows],
        columns=list(COMPACT_CORE_IDS),
    )

    edited = st.data_editor(
        frame,
        column_config={
            "취급물질": st.column_config.TextColumn(
                "취급 물질",
                disabled=True,
                help="판정엔진이 최대보유량 계산 대상으로 확인한 물질입니다. 사용자가 다른 물질로 바꿀 수 없습니다.",
            ),
            "시설유형": st.column_config.SelectboxColumn(
                "시설 유형",
                options=list(ws.FACILITY_TYPES),
                help="저장탱크, 제조·사용시설, 보관시설 중 실제 형태를 고릅니다. 탱크로리·사외배관·취급중단 신고시설은 법정 최대보유량 산정에서 제외되는 유형입니다.",
            ),
            "물질성상": st.column_config.SelectboxColumn(
                "물질 상태",
                options=list(ws.SUBSTANCE_STATES),
                help="이 시설의 실제 운전조건에서 액체·고체·기체/고압가스 중 무엇인지 고릅니다.",
            ),
        },
        disabled=["취급물질"],
        num_rows="fixed",
        hide_index=True,
        width="stretch",
        key=f"{prefix}_compact_core_{pid}",
    )

    rows: list[dict] = []
    for index, record in enumerate(edited.to_dict("records")):
        old_row = dict(working_rows[index]) if index < len(working_rows) else {}
        row = {**old_row, **{k: ("" if pd.isna(v) else v) for k, v in record.items()}}
        # 방어적으로 취급물질은 source row의 자동값을 강제한다.
        row["취급물질"] = _clean(old_row.get("취급물질"))
        if not row["취급물질"]:
            continue
        rows.append(row)

    gravity_pool = ws.gravity_candidates(project)
    for index, row in enumerate(rows):
        material = _clean(row.get("취급물질"))
        ftype = _clean(row.get("시설유형"))
        state = _clean(row.get("물질성상"))
        if not ftype:
            st.caption(f"• {material}: 시설 유형을 고르면 필요한 입력칸이 나타납니다.")
            continue
        if ftype in ws.EXCLUDED_TYPES:
            st.info(f"{material}: '{ftype}'은 최대보유량 계산에서 제외되는 시설 유형입니다.")
            continue
        if not state:
            st.caption(f"• {material}: 물질 상태를 고르면 필요한 입력칸이 나타납니다.")
            continue

        suffix = f"{material} · 시설 {sum(1 for r in rows[:index+1] if _norm(r.get('취급물질')) == _norm(material))}"
        with st.expander(f"{suffix} — 계산에 필요한 정보", expanded=True):
            if state == "기체·고압가스":
                _compact_gas(project, row, prefix, pid, index)
            elif state == "복수성상":
                st.caption("액체·기체 등 여러 상태가 함께 존재하면 프로그램이 임의 계산하지 않습니다. 회사에서 확인한 최대보유량과 근거를 입력하세요.")
                _compact_direct_mass(row, prefix, pid, index)
            elif ftype == "보관시설":
                row["보관계획도 최대량"] = _compact_text_number(
                    "보관계획도에 적힌 최대량",
                    row.get("보관계획도 최대량"),
                    f"{prefix}_compact_plan_{pid}_{index}",
                    "보관계획도 또는 창고 배치계획에서 허용하는 최대 보관량입니다.",
                )
                row["일일최대보관량"] = _compact_text_number(
                    "하루 중 실제 최대 보관량",
                    row.get("일일최대보관량"),
                    f"{prefix}_compact_daily_{pid}_{index}",
                    "하루 동안 실제로 보관될 수 있는 가장 큰 양입니다. 프로그램은 두 값 중 큰 값을 사용합니다.",
                )
                row["질량단위"] = _compact_choice(
                    "수량 단위", ["kg", "ton"], row.get("질량단위"),
                    f"{prefix}_compact_storage_unit_{pid}_{index}",
                )
            elif ftype == "기타":
                st.caption("자동 계산 규칙을 적용하기 어려운 시설입니다. 회사에서 확인한 최대보유량을 입력하세요.")
                _compact_direct_mass(row, prefix, pid, index)
            else:
                _compact_volume_density(project, row, prefix, pid, index, gravity_pool)
                if ftype == "제조·사용시설":
                    _compact_process(row, prefix, pid, index)

    live = ws.compute_holdings(project, rows) if rows else []
    if live:
        st.markdown("**계산 결과 미리보기**")
        frames.show(
            pd.DataFrame([
                {
                    "취급 물질": row.get("취급물질"),
                    "계산된 최대보유량(ton)": None if result.ton is None else round(result.ton, 6),
                    "확인할 내용": result.basis or result.problem,
                }
                for row, result in zip(rows, live)
            ]),
            width="stretch",
            hide_index=True,
        )

    if st.button("최대보유량 확정하기", type="primary", key=f"{prefix}_save_{pid}"):
        saved = ws.save_facility_rows(project, [*untouched, *rows])
        if saved:
            st.session_state.pop(extra_key, None)
            save_project(project)
            if on_saved is not None:
                on_saved(saved)
            else:
                st.success(f"시설 {saved}건을 저장했습니다.")
        else:
            st.warning("저장할 시설 정보가 없습니다.")

    if any(_clean(row.get("시설유형")) in {"저장탱크", "제조·사용시설"} and
           _clean(row.get("물질성상")) not in {"기체·고압가스", "복수성상"} for row in rows):
        with st.expander("설계용량을 모르면 치수로 계산"):
            st.caption("설비 치수로 대략적인 내부 부피를 계산합니다. 설계도서의 설계용량이 있으면 그 값을 우선 사용하세요.")
            shape = st.selectbox("형태", list(SHAPES), format_func=lambda key: SHAPES[key], key=f"{prefix}_compact_shape")
            dims = {}
            dim_cols = st.columns(len(SHAPE_DIMENSIONS[shape]))
            for column, name in zip(dim_cols, SHAPE_DIMENSIONS[shape]):
                dims[name] = column.number_input(DIM_LABELS[name], min_value=0.0, value=0.0,
                                                 key=f"{prefix}_compact_dim_{shape}_{name}")
            volume = ws.volume_from_dimensions(shape, **dims)
            if volume is not None:
                st.metric("계산된 설계용량", f"{volume:g} m³")


def _render_full(project, prefix: str, on_saved=None) -> None:
    """별지 제1호 작성용 전체 시설표."""
    fac = ws.section(1, "facility_table")
    columns = ws.facility_columns()
    core_ids = [c["id"] for c in columns]

    def _grid_frame() -> pd.DataFrame:
        frame = pd.DataFrame(ws.facility_editor_rows(project), columns=core_ids)
        for col in columns:
            if col.get("kind") == "number":
                frame[col["id"]] = pd.to_numeric(frame[col["id"]], errors="coerce")
        return frame

    current_rows = ws.facility_editor_rows(project)
    st.subheader("시설 표")
    st.info("※ " + fac["form_note"])
    if current_rows and any(
        not _clean(row.get("단위공장·공정")) or not _clean(row.get("설비번호")) or not _clean(row.get("설비명"))
        for row in current_rows
    ):
        st.info(
            "판정 단계에서 입력한 계산값을 불러왔습니다. 보고서 완성을 위해 "
            "'단위공장', '구분기호(설비번호)', '취급시설명'처럼 판정에는 필요하지 않았던 식별정보를 여기서 보완하세요."
        )

    edited = st.data_editor(
        _grid_frame(),
        column_config=column_config(columns),
        num_rows="dynamic",
        width="stretch",
        key=f"{prefix}_facilities_{project.project_id}",
    )
    rows = [{k: ("" if pd.isna(v) else v) for k, v in row.items()} for row in edited.to_dict("records")]
    saved_rows = {
        (str(r.get("설비번호") or ""), str(r.get("설비명") or "")): r for r in current_rows
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


def render(project, prefix: str = "cap_form01", on_saved=None, compact: bool = False,
           focus_names: list[str] | None = None) -> None:
    """시설정보를 표시한다. 판정(compact)과 별지 작성(full)은 화면만 다르고 같은 저장값을 쓴다."""
    if compact:
        _render_compact(project, prefix, on_saved=on_saved, focus_names=focus_names)
        return
    _render_full(project, prefix, on_saved=on_saved)
