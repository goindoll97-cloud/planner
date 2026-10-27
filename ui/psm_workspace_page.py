"""공정안전보고서: 회사 파일로 채운 내용을 서식별로 보여 주고 초안을 내려받습니다.

사람은 서식을 쓰지 않습니다. 회사 파일(동력기계 목록·배관 명세·안전밸브 명세·사업개요·운영계획 등)은 ‘사업장 업무 > 자료 올리기’에서
올리고, 이 화면은 서식마다 무엇이 채워졌고 무엇이 비었는지(어느 파일에 무엇을 적을지)를 보여 줍니다.
화학사고예방관리계획서에서 이미 올린 사업장·물질·설비·감지기 사실은 다시 묻지 않고 그대로 씁니다.
별지 제19호의2(시나리오 및 피해예측 결과)는 다음 단계에서 ‘사고시나리오 결과’ 화면으로 옮깁니다.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from engine import kma_asos
from engine.stage2 import cap_fact_drafting as fact_drafting
from engine.stage2 import cap_fact_status as fact_status
from engine.stage2 import cap_scenario_workspace as sc
from engine.stage2 import psm_attachments as attachments
from engine.stage2 import psm_admin_forms as admin_forms
from engine.stage2 import psm_form12_workspace as f12
from engine.stage2 import psm_form19_2_workspace as f19
from engine.stage2 import psm_weather
from engine.stage2 import psm_table_workspace as tables
from engine.stage2.psm_form12_consequence_engine import FORM12_HEADERS
from engine.stage2 import statutory_report as report
from engine.stage2.storage import list_projects, load_project, save_project
from ui import cap_frames as frames

ACTIVE_PROJECT_KEY = "_stage2_active_project_id"
FORMS = {
    "status": "한눈에 보기 · 서식별 채워진 정도",
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
    "narrative": "서술형 항목 · 회사 파일 사실로 쓴 초안",
    "admin": "제출·확인 행정서식 · 별지 제1호·제9호",
    "files": "첨부 자료 · 도면·MSDS 올리기",
    "export": "점검·내보내기 · 보고서 내려받기",
}
INTAKE_PAGE = "ui/evidence_workspace_page.py"


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
    from ui import cap_start_panel

    rows = _psm_projects()
    if not rows:
        st.info("공정안전보고서를 작성할 사업장이 아직 없습니다. 아래에서 사업장과 취급 물질을 적고 시작하세요.")
        cap_start_panel.render(expanded=True)
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


def _to_intake() -> None:
    try:
        st.page_link(INTAKE_PAGE, label="파일 올리기·고치기: 사업장 업무 > 자료 올리기 →")
    except Exception:          # 이 화면만 따로 띄웠을 때(시험 등)는 이동 링크를 만들 수 없음
        st.caption("파일 올리기·고치기: 왼쪽 ‘사업장 업무 > 자료 올리기’")


def _fact_lines(project, form: str) -> None:
    """이 서식에 쓰이는 사실 중 비었거나 충돌한 것과, 어느 파일에 무엇을 적을지."""
    rows = [r for r in fact_status.fact_rows(project, docs=("PSM",))
            if r["_company"] and form in _psm_forms(r) and r["_state"] in (fact_status.BLANK, fact_status.CONFLICT,
                                                                             fact_status.CHECK)
            and (r["_required"] or r["_state"] != fact_status.BLANK)]
    if rows:
        st.markdown("**파일에서 채우지 못한 것**")
        st.dataframe([{k: r[k] for k in ("상태", "사실", "올릴 파일", "고칠 점")} for r in rows], hide_index=True, width="stretch")
        _to_intake()


def _psm_forms(row) -> tuple[str, ...]:
    from engine.stage2 import cap_fact_catalog as catalog
    return catalog.get(row["_id"]).psm_forms


def _status(project) -> None:
    st.caption("공정안전보고서 서식마다 회사 파일에서 채운 정도입니다. 빈칸은 ‘사업장 업무 > 자료 올리기’의 사실 표에서 "
               "어느 파일에 무엇을 적을지 알려 줍니다.")
    rows = []
    for form, title in FORMS.items():
        if not form[0].isdigit():
            continue
        if form in tables.SPECS:
            decision = tables.applicability(project, form)[0] if tables.SPECS[form].conditional else ""
            needs = tables.needs(project, form)
            count = len(tables.rows(project, form)) if project.get_field(tables.SPECS[form].key) else 0
            state = "해당 없음" if decision == tables.NOT_APPLICABLE else ("채워짐" if not needs else f"보완 {len(needs)}건")
            rows.append({"서식": title, "상태": state, "줄 수": count or ""})
        elif form == "12":
            needs = f12.needs(project)
            rows.append({"서식": title, "상태": "채워짐" if not needs else f"빈 칸 {len(needs)}개", "줄 수": ""})
        elif form == "13":
            count = len(report._psm_form13_rows(project))
            rows.append({"서식": title, "상태": "채워짐" if count else "물질 자료 없음", "줄 수": count or ""})
        elif form == "15":
            count = len(report._psm_facility_rows(project))
            rows.append({"서식": title, "상태": "채워짐" if count else "설비 자료 없음", "줄 수": count or ""})
        elif form == "19-2":
            saved = project.get_field(f19.TABLE_KEY)
            rows.append({"서식": title, "상태": "반영됨" if saved else "시나리오 결과 전", "줄 수": ""})
    frames.show(pd.DataFrame(rows), width="stretch", hide_index=True)
    _to_intake()


def _table(project, form: str) -> None:
    spec = tables.SPECS[form]
    st.caption(spec.summary + " 회사 파일의 표를 그대로 읽어 채웁니다.")
    if spec.conditional:
        decision, basis = tables.applicability(project, form)
        if decision == tables.NOT_APPLICABLE:
            st.success(f"‘해당 없음’으로 확인된 서식입니다(근거: {basis}). 작성하지 않습니다.")
            return
        if not decision:
            st.info("아직 이 서식의 표도 ‘해당 없음’ 기록도 없습니다. 표를 올리면 ‘적용’, 사업개요 파일에 "
                    f"‘{spec.title} 적용여부: 해당 없음’과 근거를 적으면 ‘해당 없음’이 됩니다.")
    rows = tables.rows(project, form)
    if rows:
        if form == "17-5" and project.get_field(spec.key) is None:
            _reuse_note("화학사고예방관리계획서의 가스감지기 명세에서 가져왔습니다.")
        frames.show(pd.DataFrame(rows, columns=spec.column_ids()), width="stretch", hide_index=True)
    needs = tables.needs(project, form)
    if needs:
        st.warning("보완할 것: " + " / ".join(needs[:10]) + (" 외" if len(needs) > 10 else ""))
    _fact_lines(project, form)


def _table_12(project) -> None:
    st.caption("사업의 개요입니다. 사업장 일반정보(대표자·주소·전화 등)는 화학사고예방관리계획서와 같은 사실을 쓰고, "
               "나머지는 공정안전보고서 사업개요 파일에서 읽습니다. " + f12.NOT_APPLICABLE_HINT)
    have = f12.current(project)
    frames.show(pd.DataFrame([{"칸": h, "값": have.get(h, "")} for h in FORM12_HEADERS]), width="stretch", hide_index=True)
    needs = f12.needs(project)
    if needs:
        st.info("아직 비어 있는 칸: " + ", ".join(needs))
    _fact_lines(project, "12")


def _table_13(project) -> None:
    st.caption("유해·위험물질의 이름, CAS, 폭발한계, 독성 등을 적는 표입니다. 물질 목록·SDS 물성표 파일에서 읽은 물질 사실을 그대로 씁니다.")
    spec = report.PSM_FORMS["13"]
    rows = report._psm_form13_rows(project)
    if not rows:
        st.warning("가져올 물질 정보가 없습니다. 제품·물질 목록과 SDS 물성표 파일을 올려 주세요.")
        _to_intake()
        return
    _reuse_note(f"물질 {len(rows)}건을 가져왔습니다. 빈 칸은 확인되지 않은 항목입니다.")
    frames.show(pd.DataFrame(rows, columns=list(spec.headers)), width="stretch", hide_index=True)
    _fact_lines(project, "13")


def _table_15(project) -> None:
    st.caption("장치·설비 명세입니다. 설비번호·이름·내용물·용량·압력·온도는 설비대장·설비사양 파일에서, 재질·용접효율·두께 등 "
               "공정안전보고서에만 있는 칸은 같은 설비사양 파일의 열(본체재질, 용접효율 등)에서 읽습니다.")
    spec = report.PSM_FORMS["15"]
    rows = report._psm_facility_rows(project)
    if not rows:
        st.warning("가져올 시설이 없습니다. 설비대장 파일을 올려 주세요.")
        _to_intake()
        return
    _reuse_note(f"설비 {len(rows)}건을 가져왔습니다.")
    frames.show(pd.DataFrame(report._psm_form15_rows(project), columns=list(spec.headers)), width="stretch", hide_index=True)
    _fact_lines(project, "15")


def _narrative(project) -> None:
    st.caption("안전운전지침서·교육계획·비상조치계획 같은 글은 회사 파일에서 읽은 사실만으로 초안을 씁니다. 회사 문서에 그 글이 있으면 "
               "그대로 쓰고, 근거가 없는 부분은 ‘[확인 필요]’로 남깁니다. 초안 문서에 ‘AI 초안’으로 표시됩니다.")
    rows = fact_drafting.rows(project, "PSM")
    if rows:
        st.dataframe([{k: v for k, v in r.items() if not k.startswith("_")} for r in rows], hide_index=True, width="stretch")
    with st.expander("초안 보기"):
        for item in fact_drafting.items(project, "PSM"):
            text = item.company_text or item.draft
            if text:
                st.markdown(f"**{item.label}** — {item.state}")
                st.text(text)
    st.caption("로컬 AI로 문장을 다듬거나 초안을 다시 만드는 것은 ‘사업장 업무 > ④ 보내기·진행 현황’에서 합니다.")
    _to_intake()


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
        st.warning("사고 시나리오가 없습니다. 화학사고예방관리계획서 화면의 별지 제10·11호에서 시나리오를 먼저 확정하세요.")
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


def _admin_forms(project) -> None:
    st.caption("본문 별지 제12~21호와 별도로 제출·확인 단계에서 쓰는 행정서식입니다. 별지 제1호는 심사신청 단계, "
               "별지 제9호는 심사 후 확인요청 단계에서 씁니다. 사업장관리번호·신청일·확인요청 담당자 등은 "
               "공정안전보고서 사업개요 파일의 같은 이름 항목에서 읽습니다.")
    for title, values, readiness, build, filename, key in (
            ("별지 제1호 · 공정안전보고서 심사신청서", admin_forms.form1_values(project), admin_forms.form1_readiness(project),
             admin_forms.build_form1_docx, admin_forms.form1_filename, "psm_admin_form1_download"),
            ("별지 제9호 · 공정안전보고서확인요청서", admin_forms.form9_values(project), admin_forms.form9_readiness(project),
             admin_forms.build_form9_docx, admin_forms.form9_filename, "psm_admin_form9_download")):
        st.markdown(f"### {title}")
        frames.show(pd.DataFrame([{"칸": k, "값": v} for k, v in values.items()]), width="stretch", hide_index=True)
        if readiness.ready:
            st.download_button(f"{title.split(' · ')[0]} DOCX 초안 내려받기", data=build(project), file_name=filename(project),
                               mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                               key=key, width="stretch")
        else:
            st.info("파일에서 채우지 못한 것: " + " / ".join(readiness.blockers))
        with st.expander("제출 전 확인할 것"):
            for item in readiness.manual_items:
                st.write(f"• {item}")
    _fact_lines(project, "admin1")


def _files(project) -> None:
    from ui import attachments_panel

    attachments_panel.render(project, attachments.SLOTS, "psm")


def _export(project) -> None:
    from ui import report_export_panel

    report_export_panel.render(project, "PSM")


st.set_page_config(page_title="공정안전보고서", page_icon="🏭", layout="wide")
st.title("🏭 공정안전보고서")
st.caption("회사 파일로 채운 내용을 서식별로 확인하고 초안을 내려받습니다. 화면에서 서식을 쓰지 않고, 고칠 것은 파일을 고쳐 다시 올립니다.")

project_id = _project_selector()
if not project_id:
    st.stop()
project = load_project(project_id)
from ui import version_panel

version_panel.render_refresh_banner(project, "PSM")
version_panel.render_status(project, "PSM")   # 버전 관리는 왼쪽 ‘버전 관리’ 화면으로 옮김

form_key = st.selectbox("볼 서식", list(FORMS), key="psm_form_no", format_func=lambda key: FORMS[key])
VIEWS = {"status": _status, "12": _table_12, "13": _table_13, "15": _table_15, "19-2": _table_19_2,
         "narrative": _narrative, "admin": _admin_forms, "export": _export, "files": _files}
(VIEWS.get(form_key) or (lambda p: _table(p, form_key)))(project)
