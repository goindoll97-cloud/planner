from __future__ import annotations

"""공정안전보고서 작성: 화학사고예방관리계획서에서 이미 입력한 사실을 재사용해 별지 제13·15·19호의2를 작성한다."""

import pandas as pd
import streamlit as st

from engine import kma_asos
from engine.stage2 import cap_scenario_workspace as sc
from engine.stage2 import psm_attachments as attachments
from engine.stage2 import psm_form12_workspace as f12
from engine.stage2 import psm_form19_2_workspace as f19
from engine.stage2 import psm_export as export
from engine.stage2 import psm_narrative_workspace as narrative
from engine.stage2 import psm_weather
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
    "16": "별지 제16호 · 배관 및 개스킷 명세",
    "17": "별지 제17호 · 안전밸브 및 파열판 명세",
    "17-2": "별지 제17호의2 · 인터록 작동조건 및 가동중지 범위",
    "17-3": "별지 제17호의3 · 소화설비 설치계획",
    "17-4": "별지 제17호의4 · 화재탐지경보설비 설치계획",
    "17-5": "별지 제17호의5 · 가스누출감지경보기 설치계획",
    "18": "별지 제18호 · 내화구조 명세",
    "19": "별지 제19호 · 국소배기장치 개요",
    "19-2": "별지 제19호의2 · 시나리오 및 피해예측 결과",
    "20": "별지 제20호 · 방폭전기/계장 기계·기구 선정기준",
    "21": "별지 제21호 · 위험성평가 참여 전문가 명단",
    "facts": "서술형 항목 · 사실 입력과 AI 초안 확인",
    "export": "점검·내보내기 · 보고서 내려받기",
    "files": "첨부 자료 · 도면·MSDS 올리기",
}
UNSUPPORTED = ()


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


def _use_saved_weather(project) -> None:
    """저장된 산정 값을 입력칸의 초기값으로 쓴다(사용자가 이미 적은 칸은 건드리지 않는다)."""
    basis = psm_weather.saved(project)
    if basis.get("최고기온(℃)") is not None and not st.session_state.get("psm19_temp"):
        st.session_state["psm19_temp"] = f"{basis['최고기온(℃)']:g}"
    if basis.get("평균 상대습도(%)") is not None and not st.session_state.get("psm19_humidity"):
        st.session_state["psm19_humidity"] = f"{basis['평균 상대습도(%)']:g}"


def _fill_weather(project, station: str) -> None:
    """버튼 콜백: 고른 관측소의 지난 3년 관측으로 다시 채운다."""
    result = psm_weather.refresh(project, station)
    if result.status != "FILLED":
        st.session_state["psm19_weather_msg"] = ("warning", result.message)
        return
    basis = psm_weather.saved(project)
    st.session_state["psm19_temp"] = f"{basis['최고기온(℃)']:g}"
    st.session_state["psm19_humidity"] = f"{basis['평균 상대습도(%)']:g}"
    save_project(project)
    st.session_state["psm19_weather_msg"] = (
        "success", f"{basis['관측소']} 관측소 {basis['기간']}({basis['관측일수']}일)의 최고기온 {basis['최고기온(℃)']:g}℃"
        f"({basis['최고기온 일자']}), 평균 상대습도 {basis['평균 상대습도(%)']:g}%를 채웠습니다. "
        f"참고로 평균 풍속은 {basis['평균 풍속(m/s)']:g} m/s입니다.")


def _auto_weather(project) -> None:
    """화면을 처음 열 때 주소로 관측소를 골라 자동으로 채운다(이미 기록되어 있으면 그대로 사용)."""
    if not psm_weather.saved(project) and not st.session_state.get("psm19_auto_tried"):
        st.session_state["psm19_auto_tried"] = True
        with st.spinner("사업장 주소로 가까운 기상 관측소의 지난 3년 자료를 불러오는 중입니다."):
            result = psm_weather.auto_fill(project)
        if result.status == "FILLED":
            save_project(project)
            st.session_state["psm19_weather_msg"] = ("success", result.message + " 아래에서 확인하세요.")
        elif result.status != "SAVED":
            st.session_state["psm19_weather_msg"] = ("info", result.message + " 직접 입력하거나 관측소를 골라 불러오세요.")
    _use_saved_weather(project)


def _weather_panel(project) -> None:
    stations = kma_asos.stations()
    record = project.get_field("business.address")
    suggested = _clean(psm_weather.saved(project).get("관측소코드")) or kma_asos.suggest_station(
        _clean(record.value) if record is not None else "")
    codes = sorted(stations, key=lambda c: stations[c]["name"])
    with st.expander("기상청 관측 자료로 대기온도·습도 채우기(관측소 바꾸기)", expanded=False):
        st.caption("서식은 '지난 3년간 낮 동안 최대 온도'와 '평균 습도'를 적으라고 합니다. 가까운 기상청 관측소의 지난 3년 일자료로 "
                   "채울 수 있습니다. 습도는 낮 동안만이 아니라 하루 평균이라, 서식과 다르게 적으려면 직접 고치세요.")
        station = st.selectbox("가까운 관측소", codes, index=codes.index(suggested) if suggested in codes else 0,
                               format_func=lambda c: f"{stations[c]['name']} ({c})", key="psm19_station",
                               help="사업장 주소에 지점 이름이 있으면 자동으로 골랐습니다. 다르면 가장 가까운 곳을 고르세요.")
        st.button("지난 3년 관측 자료로 채우기", key="psm19_weather_fill", on_click=_fill_weather, args=(project, station))
        message = st.session_state.get("psm19_weather_msg")
        if message:
            getattr(st, message[0])(message[1])


def _table_19_2(project) -> None:
    st.caption("사고가 났을 때 화재·폭발·독성이 얼마나 멀리 미치는지 적는 서식입니다. 누출량과 확산 계산은 화학사고예방관리계획서와 "
               "같은 계산을 쓰고, 서식이 정한 기준(복사열 4·12.5·37.5, 독성 ERPG 1·2·3)으로 거리를 구합니다.")
    if not sc.saved_scenarios(project):
        st.warning("사고 시나리오가 없습니다. 화학사고예방관리계획서 작성 화면의 별지 제10·11호에서 시나리오를 먼저 확정하세요.")
        return
    designations = _scenario_designations(project)
    _auto_weather(project)
    _weather_panel(project)
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
        st.caption(spec.summary)
        if spec.conditional:
            decision, basis = tables.applicability(project, form_no)
            st.markdown("**이 서식을 작성해야 하나요?**")
            options = ["선택하세요", tables.APPLICABLE, tables.NOT_APPLICABLE]
            chosen = st.selectbox("적용 여부", options, index=options.index(decision) if decision in options else 0,
                                  key=f"psm_apply_{form_no}",
                                  help="이 서식은 해당하는 사업장만 작성합니다. 해당하지 않으면 '해당 없음'을 고르고 이유를 적으세요.")
            reason = st.text_input("확인 근거", value=basis, key=f"psm_apply_basis_{form_no}",
                                   help="왜 적용(또는 해당 없음)인지 한 줄로 적습니다. 예: 옥내 소화 설비 없음(옥외 시설만 있음)")
            if st.button("적용 여부 저장", key=f"psm_apply_save_{form_no}"):
                if chosen == "선택하세요" or not reason.strip():
                    st.warning("적용 여부와 확인 근거를 모두 적어야 저장됩니다.")
                else:
                    tables.save_applicability(project, form_no, chosen, reason)
                    save_project(project)
                    st.rerun()
            if decision == tables.NOT_APPLICABLE:
                st.success("이 서식은 '해당 없음'으로 확인되어 작성하지 않습니다.")
                return
            if decision != tables.APPLICABLE:
                st.info("적용 여부를 먼저 저장하면 표를 작성할 수 있습니다.")
                return
        st.caption("모르는 칸은 비워 두어도 저장됩니다. 비워 둔 칸은 아래에 안내됩니다.")
        if spec.seed_key and project.get_field(spec.key) is None and tables.seeded(project, form_no):
            _reuse_note("화학사고예방관리계획서에서 이미 입력한 내용을 미리 채웠습니다. 확인하고 저장하세요.")
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


def _local_config():
    from engine.stage2.local_ai_resilience import build_local_llm_client, local_llm_config_from_sources
    from engine.stage2.local_llm import DEFAULT_MODEL, LocalLLMConfig, probe_local_llm_runtime, validate_local_base_url

    try:
        base = local_llm_config_from_sources({})
    except Exception:
        base = LocalLLMConfig()
    with st.expander("AI 설정 · 필요한 경우만"):
        st.caption("회사 정보는 외부로 보내지 않습니다. 이 PC의 Ollama 같은 로컬 AI만 사용합니다.")
        model = st.text_input("로컬 모델 이름", value=base.model or DEFAULT_MODEL, key="psm_llm_model")
        url = st.text_input("로컬 AI 주소", value=base.base_url, key="psm_llm_url")
    try:
        config = LocalLLMConfig(provider=base.provider, model=model.strip() or DEFAULT_MODEL,
                                base_url=validate_local_base_url(url), timeout_seconds=base.timeout_seconds,
                                max_output_tokens=base.max_output_tokens)
        return config, probe_local_llm_runtime(config), build_local_llm_client
    except Exception as exc:
        st.warning(str(exc))
        return None, None, None


def _facts(project) -> None:
    st.caption("글로 쓰는 항목은 AI가 초안을 만듭니다. 사람은 프로그램이 알 수 없는 사실만 적고, 완성된 글을 한 번 확인합니다.")
    st.markdown("### 1. 먼저 적을 사실")
    defaults = {"business.employee_count": f12.current(project).get("근로자수", "")}
    values = {}
    for fact in narrative.BASIC_FACTS:
        current = narrative.facts_value(project, fact) or defaults.get(fact.key, "")
        widget = st.text_area if fact.long else st.text_input
        values[fact.key] = widget(fact.label, value=current, help=fact.help, key=f"psm_fact_{fact.key}")
    if st.button("사실 저장", type="primary", key="psm_fact_save"):
        for fact in narrative.BASIC_FACTS:
            narrative.save_fact(project, fact, values[fact.key])
        save_project(project)
        st.rerun()
    missing = narrative.missing_basics(project)
    if missing:
        st.info("아직 적지 않은 사실: " + ", ".join(missing))

    st.markdown("### 2. 회사가 정한 사항")
    for fact in narrative.DECISION_FACTS:
        with st.expander(fact.label):
            st.caption(fact.help)
            current = narrative.facts_value(project, fact)
            entered = {name: st.text_input(label, value=current.get(name, ""), help=help_text,
                                           key=f"psm_fact_{fact.key}_{name}")
                       for name, label, help_text in fact.fields}
            if st.button("저장", key=f"psm_fact_save_{fact.key}"):
                narrative.save_fact(project, fact, entered)
                save_project(project)
                st.rerun()

    st.markdown("### 3. 비상장비·연락체계와 세안·보호구")
    for form_no in ("emergency-resources", "emergency-contacts", "wash-ppe"):
        with st.expander(tables.SPECS[form_no].title):
            _grid(form_no)(project)

    st.markdown("### 4. AI가 만든 글 확인")
    _drafts(project)


def _drafts(project) -> None:
    items = narrative.item_status(project)
    ready = [i for i in items if i["state"] == "초안 만들기 가능"]
    config, probe, build_client = _local_config()
    if ready:
        st.write(f"초안을 만들 수 있는 항목 {len(ready)}개: " + ", ".join(i["label"] for i in ready))
        runtime_ok = probe is not None and probe.ready
        if not runtime_ok and probe is not None:
            from engine.stage2.local_llm import local_runtime_not_ready_message
            st.warning(local_runtime_not_ready_message(config, probe))
        if st.button("초안 만들기", type="primary", key="psm_generate", disabled=not runtime_ok):
            with st.spinner("확정된 사실로 초안을 만드는 중입니다."):
                try:
                    result = narrative.generate(project, build_client(config))
                    save_project(project)
                    if result.rejected:
                        st.warning(f"검증을 통과하지 못한 초안 {len(result.rejected)}개는 저장하지 않았습니다. 사실을 더 적고 다시 시도하세요.")
                except Exception as exc:
                    st.error(f"초안을 만들지 못했습니다: {type(exc).__name__}: {exc}")
            st.rerun()
    for item in items:
        with st.expander(f"{item['label']} — {item['state']}", expanded=item["state"] == "초안 있음"):
            if item["reason"]:
                st.caption(item["reason"])
            if item["text"]:
                text = st.text_area("초안(고쳐 쓸 수 있습니다)", value=item["text"], height=220, key=f"psm_draft_{item['key']}")
                st.caption("AI가 확정된 사실만으로 쓴 초안입니다. 회사 실제와 다르면 고치세요. 확인하면 회사 문서로 채택됩니다.")
                if item["state"] != "확인 완료" and st.button("내용을 확인했습니다", key=f"psm_adopt_{item['key']}"):
                    try:
                        narrative.adopt(project, item["key"], text)
                        save_project(project)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))


def _export(project) -> None:
    from engine.stage2.workflow import validation_confirmed

    st.caption("입력한 내용을 점검하고 보고서(DOCX)를 내려받습니다. 부족한 내용은 위의 각 별지 화면에서 채우면 여기 점검 결과에 바로 반영됩니다.")
    try:
        state = export.evaluate(project)
    except Exception as exc:
        st.error(f"점검하지 못했습니다: {type(exc).__name__}: {exc}")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("보완 필요", state.hold)
    c2.metric("담당자 확인 필요", state.review)
    c3.metric("확인 완료", state.passed)
    c4.metric("최종 제출 전 별도 준비", len(state.manual_issues))
    if state.can_confirm:
        st.success("보고서 작성에 필요한 기본 자료 점검이 끝났습니다.")
    else:
        st.warning("보완하거나 담당자가 확인할 항목이 남아 있습니다. 채우고 오거나, 현재 자료만으로 검토용 초안을 만들 수 있습니다.")
    rows = [{"상태": export.STATUS_LABELS.get(i.status, i.status_label), "작성항목": i.legal_item, "확인할 내용": i.message,
             "근거": i.legal_basis} for i in state.text_issues if i.status != "PASS"]
    if rows:
        frames.show(pd.DataFrame(rows), width="stretch", hide_index=True)
    if state.manual_issues:
        with st.expander(f"최종 제출 전에 따로 준비할 자료 {len(state.manual_issues)}건"):
            st.caption("도면·MSDS 같은 첨부 자료입니다. 첨부 자료 화면에서 올릴 수 있고, 최종 제출 전에 실제 파일을 대조해야 합니다.")
            frames.show(pd.DataFrame([{"작성항목": i.legal_item, "준비할 내용": i.message} for i in state.manual_issues]),
                        width="stretch", hide_index=True)

    if state.can_confirm and not validation_confirmed(project):
        if st.button("작성자료 확인 완료", type="primary", key="psm_export_confirm"):
            export.confirm(project, state)
            save_project(project)
            st.rerun()
    elif not state.can_confirm and not export.downloads_allowed(project):
        if st.button("현재 자료로 검토용 초안 만들기", type="primary", key="psm_export_ack"):
            export.acknowledge_holds(project)
            save_project(project)
            st.rerun()
    if not export.downloads_allowed(project):
        st.info("작성자료를 확인 완료하거나 검토용 초안 만들기를 선택하면 내려받을 수 있습니다.")
        return
    try:
        outputs = export.build_outputs(project, final_ready=state.final_ready)
    except Exception as exc:
        st.error(f"보고서를 만들지 못했습니다: {type(exc).__name__}: {exc}")
        return
    if state.final_ready:
        st.success("문서별 최종 준비 기준을 통과해 '작성본'으로 표시합니다. 그래도 제출 전에는 담당자가 사실·수치·도면을 최종 대조해야 합니다.")
    else:
        st.warning("최종 준비 기준을 아직 통과하지 못해 '검토용'으로 표시합니다. 제출본이 아닙니다.")
        for reason in (state.readiness.reasons if state.readiness else ()):
            st.write(f"• {reason}")
    st.download_button("규정서식 DOCX 내려받기", data=outputs.regulation_docx, file_name=outputs.regulation_name,
                       mime=export.DOCX_MIME, key="psm_dl_regulation", width="stretch",
                       type="primary" if state.final_ready else "secondary")
    st.download_button("내부 검토용 DOCX(서술형 항목 포함) 내려받기", data=outputs.review_docx, file_name=outputs.review_name,
                       mime=export.DOCX_MIME, key="psm_dl_review", width="stretch")
    with st.expander("출력물 검증정보"):
        st.caption("파일이 나중에 바뀌지 않았는지 확인하는 지문(SHA-256)과 생성 기록입니다.")
        st.download_button("검증정보 JSON", data=outputs.provenance_json, file_name=outputs.provenance_name,
                           mime="application/json", key="psm_dl_prov", width="stretch")
        st.download_button("검증 묶음 ZIP(DOCX + 검증정보)", data=outputs.bundle, file_name=outputs.bundle_name,
                           mime="application/zip", key="psm_dl_bundle", width="stretch")


st.set_page_config(page_title="공정안전보고서 작성", page_icon="🏭", layout="wide")
st.title("🏭 공정안전보고서 작성")
st.caption("화학사고예방관리계획서에서 이미 입력한 사업장·물질·시설·시나리오는 다시 묻지 않고 그대로 가져옵니다.")

project_id = _project_selector()
if not project_id:
    st.stop()
project = load_project(project_id)
form_key = st.selectbox("작성할 별지", list(FORMS), format_func=lambda key: FORMS[key], key="psm_form_no")
{"12": _table_12, "13": _table_13, **{no: _grid(no) for no in ("14", "16", "17", "17-2", "17-3", "17-4", "17-5", "18", "19", "20", "21")}, "15": _table_15, "19-2": _table_19_2, "facts": _facts, "export": _export, "files": _files}[form_key](project)
