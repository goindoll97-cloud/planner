from __future__ import annotations

"""공정안전보고서 작성: 화학사고예방관리계획서에서 이미 입력한 사실을 재사용해 별지 제13·15·19호의2를 작성한다."""

import pandas as pd
import streamlit as st

from engine.stage2 import cap_scenario_workspace as sc
from engine.stage2 import psm_attachments as attachments
from engine.stage2 import psm_form12_workspace as f12
from engine.stage2 import psm_form19_2_workspace as f19
from engine.stage2 import psm_table_workspace as tables
from engine.stage2 import statutory_report as report
from engine.stage2.storage import list_projects, load_project, save_project
from ui import cap_frames as frames

ACTIVE_PROJECT_KEY = "_stage2_active_project_id"
EQUIPMENT_KEY = "psm.psi.equipment_specs"
# 별지 제15호에서 CAP 작업에는 없는 PSM 전용 칸(같은 설비번호 행에 덧씌운다)
PSM_ONLY_COLUMNS = ("본체재질", "부속품재질", "개스킷재질", "용접효율", "계산두께", "부식여유", "사용두께",
                    "후열처리 여부", "비파괴검사율")
FORMS = {
    "12": "별지 제12호 · 사업개요",
    "13": "별지 제13호 · 유해·위험물질 목록",
    "14": "별지 제14호 · 동력기계 목록",
    "15": "별지 제15호 · 장치 및 설비 명세",
    "19-2": "별지 제19호의2 · 시나리오 및 피해예측 결과",
    "files": "첨부 자료 · 도면·MSDS 올리기",
}
UNSUPPORTED = ("별지 제16호 배관 및 개스킷 명세",
               "별지 제17호 안전밸브 및 파열판 명세", "별지 제17호의2~5, 제18·19·20·21호")


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _psm_projects() -> list[dict]:
    out = []
    for row in list_projects():
        project_id = _clean(row.get("project_id"))
        if project_id and load_project(project_id).psm_in_scope:
            out.append(row)
    return out


def _project_selector() -> str | None:
    rows = _psm_projects()
    if not rows:
        st.info("공정안전보고서를 작성 범위로 선택한 사업장이 없습니다. '공정안전보고서 (기존 방식)'의 판정진단과 "
                "작성범위 선택에서 먼저 선택하세요.")
        return None
    labels = {row["project_id"]: f"{row['company_name']} · {row['project_id']}" for row in rows}
    ids = list(labels)
    current = st.session_state.get(ACTIVE_PROJECT_KEY)
    selected = st.selectbox("작성 프로젝트", ids, index=ids.index(current) if current in ids else 0,
                            format_func=lambda pid: labels[pid])
    st.session_state[ACTIVE_PROJECT_KEY] = selected
    return selected


def _reuse_note(text: str) -> None:
    st.success(text)


def _table_13(project) -> None:
    st.caption("유해·위험물질의 이름, CAS, 폭발한계, 독성 등을 적는 표입니다. 화학사고예방관리계획서(별지 제6·7호)에서 "
               "입력한 물질 정보를 그대로 가져옵니다. 다시 적을 필요가 없습니다.")
    spec = report.PSM_FORMS["13"]
    rows = report._psm_form13_rows(project)
    if not rows:
        st.warning("가져올 물질 정보가 없습니다. 화학사고예방관리계획서 작성 화면의 별지 제1·6호에서 먼저 입력하세요.")
        return
    _reuse_note(f"물질 {len(rows)}건을 가져왔습니다. 빈 칸은 확인되지 않은 항목입니다.")
    frames.show(pd.DataFrame(rows, columns=list(spec.headers)), width="stretch", hide_index=True)


def _table_15(project) -> None:
    st.caption("장치·설비의 번호, 이름, 내용물, 용량, 압력·온도를 적는 표입니다. 이 값들은 화학사고예방관리계획서(별지 제1·9호)에서 "
               "입력한 시설을 그대로 가져옵니다. 아래에서는 공정안전보고서에만 필요한 칸(재질, 용접효율, 두께 등)만 적으세요.")
    spec = report.PSM_FORMS["15"]
    rows = report._psm_facility_rows(project)
    if not rows:
        st.warning("가져올 시설이 없습니다. 화학사고예방관리계획서 작성 화면의 별지 제1호에서 시설을 먼저 입력하세요.")
        return
    _reuse_note(f"설비 {len(rows)}건을 가져왔습니다.")
    frames.show(pd.DataFrame(report._psm_form15_rows(project), columns=list(spec.headers)), width="stretch", hide_index=True)

    st.markdown("**공정안전보고서에서만 적는 칸**")
    st.caption("모르는 칸은 비워 두세요. 비워 둔 칸이 이미 적힌 값을 지우지는 않습니다.")
    frame = pd.DataFrame([{"설비번호": _clean(r.get("설비번호")), "설비명": _clean(r.get("설비명")),
                           **{column: _clean(r.get(column)) for column in PSM_ONLY_COLUMNS}} for r in rows])
    edited = st.data_editor(frames.safe(frame), hide_index=True, width="stretch", key="psm_form15_extra",
                            disabled=["설비번호", "설비명"], column_config={
                                "용접효율": st.column_config.TextColumn("용접효율", help="용접부의 효율입니다. 예: 0.85"),
                                "비파괴검사율": st.column_config.TextColumn("비파괴검사율(%)", help="비파괴검사를 하는 비율입니다.")})
    if st.button("이 표 저장", key="psm_form15_save"):
        stored = {}
        for record in edited.to_dict("records"):
            extra = {k: _clean(record.get(k)) for k in PSM_ONLY_COLUMNS if _clean(record.get(k))}
            if extra and _clean(record.get("설비번호")):
                stored[_clean(record["설비번호"])] = {"설비번호": _clean(record["설비번호"]), **extra}
        previous = {_clean(r.get("설비번호")): dict(r) for r in report._rows(project, EQUIPMENT_KEY)}
        for tag, extra in stored.items():
            previous.setdefault(tag, {}).update(extra)  # 빈 칸은 기존 값을 지우지 않는다
        project.set_field(EQUIPMENT_KEY, "장치 및 설비 명세(공정안전보고서 전용 칸)", list(previous.values()), "USER_CONFIRMED")
        save_project(project)
        st.success("저장했습니다.")
        st.rerun()


def _scenario_designations(project) -> dict[str, str]:
    scenarios = sc.saved_scenarios(project)
    st.caption("최악 시나리오는 사고가 가장 크게 났을 때, 대안 시나리오는 실제로 일어날 법한 사고입니다. "
               "화학사고예방관리계획서에서 확정한 시나리오 중에서 고르세요.")
    options = ["사용 안 함", f19.WORST, f19.ALTERNATIVE]
    labels = {f19.WORST: "최악의 사고 시나리오", f19.ALTERNATIVE: "대안의 사고 시나리오", "사용 안 함": "사용 안 함"}
    chosen: dict[str, str] = {}
    for index, scenario in enumerate(scenarios):
        name = _clean(scenario.get("사고시나리오명"))
        chosen[name] = st.selectbox(name, options, index=0, format_func=lambda o: labels[o],
                                    key=f"psm19_kind_{index}")
    return {k: v for k, v in chosen.items() if v != "사용 안 함"}


def _table_19_2(project) -> None:
    st.caption("사고가 났을 때 화재·폭발·독성이 얼마나 멀리 미치는지 적는 서식입니다. 누출량과 확산 계산은 화학사고예방관리계획서와 "
               "같은 계산을 쓰고, 서식이 정한 기준(복사열 4·12.5·37.5, 독성 ERPG 1·2·3)으로 거리를 구합니다.")
    if not sc.saved_scenarios(project):
        st.warning("사고 시나리오가 없습니다. 화학사고예방관리계획서 작성 화면의 별지 제10·11호에서 시나리오를 먼저 확정하세요.")
        return
    designations = _scenario_designations(project)
    left, right = st.columns(2)
    temperature = left.text_input("대기온도(℃)", key="psm19_temp",
                                  help="지난 3년간 낮 동안의 최대 온도, 또는 통상 온도를 적습니다.")
    humidity = right.text_input("습도(%)", key="psm19_humidity",
                                help="지난 3년간 낮 동안의 평균 습도, 또는 통상 습도를 적습니다.")
    st.caption("풍속과 대기안정도는 최악 시나리오에 1.5 m/s·F, 대안 시나리오에 통상 값(3 m/s·D)을 자동으로 씁니다.")
    if not designations:
        st.info("최악 또는 대안으로 쓸 시나리오를 고르면 계산합니다.")
        return
    results = f19.build(project, designations, {"대기온도(℃)": temperature, "습도(%)": humidity})
    problems = sorted({p for r in results for p in r.problems})
    if problems:
        st.warning("먼저 채워야 할 것")
        for problem in problems:
            st.write(f"• {problem}")
    frame = pd.DataFrame([r.row for r in results]).T
    frame.columns = [f"{i + 1}. {r.row['시나리오 구분']}" for i, r in enumerate(results)]
    frames.show(frame.reset_index().rename(columns={"index": "항목"}), width="stretch", hide_index=True)
    holds = sorted({h for r in results for h in r.holds})
    if holds:
        with st.expander(f"계산하지 않은 칸 {len(holds)}건과 이유"):
            for hold in holds:
                st.write(f"• {hold}")
            st.caption("서식 주석 ⑯: 해당사항이 없는 항목은 생략할 수 있습니다. 근거 없는 값은 채우지 않습니다.")
    if st.button("이 표를 보고서에 반영", type="primary", key="psm19_save", disabled=bool(problems)):
        f19.save(project, results)
        save_project(project)
        st.success("반영했습니다.")


def _table_12(project) -> None:
    st.caption("사업의 개요를 적는 서식입니다. 이미 입력한 사업장 정보는 자동으로 채워져 있으니, 비어 있는 칸만 적으세요. "
               + f12.NOT_APPLICABLE_HINT)
    have = f12.current(project)
    known = {k: v for k, v in f12.prefilled(project).items() if k not in f12.saved(project)}
    if known:
        _reuse_note("이미 입력한 정보 " + ", ".join(known) + "을(를) 가져왔습니다.")
    values: dict[str, str] = {}
    for header, kind, help_text in f12.QUESTIONS:
        if kind == "choice":
            options = ["선택하세요", *f12.PROJECT_TYPES]
            current = have.get(header, "")
            values[header] = st.selectbox(header, options, index=options.index(current) if current in options else 0,
                                          help=help_text, key=f"psm12_{header}")
            if values[header] == "선택하세요":
                values[header] = ""
        else:
            values[header] = st.text_input(header, value=have.get(header, ""), help=help_text, key=f"psm12_{header}")
    for header in f12.PREFILL:
        values[header] = st.text_input(header, value=have.get(header, ""), key=f"psm12_{header}",
                                       help="이미 입력한 사업장 정보에서 가져왔습니다. 다르면 고쳐 쓰세요.")
    needs = f12.needs(project)
    if needs:
        st.info("아직 비어 있는 칸: " + ", ".join(needs))
    if st.button("저장", type="primary", key="psm12_save"):
        f12.save(project, values)
        save_project(project)
        st.success("저장했습니다.")
        st.rerun()


def _grid(form_no: str):
    def render(project) -> None:
        spec = tables.SPECS[form_no]
        st.caption(spec.summary + " 모르는 칸은 비워 두어도 저장됩니다. 비워 둔 칸은 아래에 안내됩니다.")
        frame = pd.DataFrame(tables.rows(project, form_no), columns=spec.column_ids())
        config = {c.id: st.column_config.TextColumn(c.label, help=c.help) for c in spec.columns}
        edited = st.data_editor(frames.safe(frame), num_rows="dynamic", hide_index=True, width="stretch",
                                key=f"psm_grid_{form_no}", column_config=config)
        if st.button("저장", type="primary", key=f"psm_grid_save_{form_no}"):
            count = tables.save(project, form_no, edited.to_dict("records"))
            save_project(project)
            st.success(f"{count}행을 저장했습니다.")
            st.rerun()
        needs = tables.needs(project, form_no)
        if needs:
            st.info("저장된 표에서 더 필요한 것")
            for item in needs:
                st.write(f"• {item}")
        else:
            st.success("이 서식의 필수 칸이 모두 채워졌습니다.")
    return render


def _files(project) -> None:
    st.caption("표로 적을 수 없고 파일 자체가 자료인 것만 올립니다. 올린 파일은 지문(SHA-256)과 함께 기록되고 보고서의 첨부 칸에 연결됩니다. "
               "올렸다고 내용을 확인한 것은 아니므로, 직접 확인한 뒤 '내용을 확인했습니다'를 눌러 주세요.")
    for index, item in enumerate(attachments.status(project)):
        slot = item["slot"]
        with st.expander(f"{slot.label} — {item['state']}", expanded=item["state"] == "올리지 않음" and index < 3):
            st.caption(slot.help)
            if item["file_name"]:
                st.write(f"현재 파일: {item['file_name']} {item['reference_no']} {item['revision']}".strip())
            upload = st.file_uploader("파일 선택", key=f"psm_file_{slot.key}")
            left, right = st.columns(2)
            reference = left.text_input("도면번호(있으면)", key=f"psm_ref_{slot.key}")
            revision = right.text_input("개정번호(있으면)", key=f"psm_rev_{slot.key}")
            if upload is not None and st.button("이 파일 올리기", key=f"psm_up_{slot.key}"):
                attachments.attach(project, slot.key, upload.name, upload.getvalue(), reference_no=reference,
                                   revision=revision)
                save_project(project)
                st.rerun()
            if item["state"] == "내용 확인 필요" and st.button("내용을 확인했습니다", key=f"psm_ok_{slot.key}"):
                attachments.confirm(project, slot.key)
                save_project(project)
                st.rerun()


st.set_page_config(page_title="공정안전보고서 작성", page_icon="🏭", layout="wide")
st.title("🏭 공정안전보고서 작성")
st.caption("화학사고예방관리계획서에서 이미 입력한 사업장·물질·시설·시나리오는 다시 묻지 않고 그대로 가져옵니다.")

project_id = _project_selector()
if not project_id:
    st.stop()
project = load_project(project_id)
form_key = st.selectbox("작성할 별지", list(FORMS), format_func=lambda key: FORMS[key], key="psm_form_no")
{"12": _table_12, "13": _table_13, "14": _grid("14"), "15": _table_15, "19-2": _table_19_2, "files": _files}[form_key](project)
with st.expander("아직 이 화면에서 작성할 수 없는 별지"):
    for item in UNSUPPORTED:
        st.write(f"• {item}")
    st.caption("이 별지들은 '공정안전보고서 (기존 방식)' 화면으로 작성합니다.")
