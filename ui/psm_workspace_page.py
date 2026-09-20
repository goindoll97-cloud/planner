from __future__ import annotations

"""공정안전보고서 작성: 화학사고예방관리계획서에서 이미 입력한 사실을 재사용해 별지 제13·15·19호의2를 작성한다."""

import pandas as pd
import streamlit as st

from engine import kma_asos
from engine.stage2 import cap_scenario_workspace as sc
from engine.stage2 import psm_attachments as attachments
from engine.stage2 import psm_admin_forms as admin_forms
from engine.stage2 import psm_form12_workspace as f12
from engine.stage2 import psm_form19_2_workspace as f19
from engine.stage2 import narrative_examples as examples
from engine.stage2 import psm_narrative_workspace as narrative
from engine.stage2 import psm_weather
from engine.stage2 import psm_table_workspace as tables
from engine.stage2 import statutory_report as report
from engine.stage2.storage import list_projects, load_project, save_project
from ui import cap_frames as frames
from ui import table_grid

ACTIVE_PROJECT_KEY = "_stage2_active_project_id"
EQUIPMENT_KEY = "psm.psi.equipment_specs"
# 별지 제15호에서 CAP 작업에는 없는 PSM 전용 칸(같은 설비번호 행에 덧씌운다)
PSM_ONLY_COLUMNS = (
    "용량명세", "직경", "전체길이", "처리단수", "높이", "처리량", "시간당열량", "저장량",
    "본체재질", "부속품재질", "개스킷재질", "용접효율", "계산두께", "부식여유", "사용두께",
    "후열처리 여부", "비파괴검사율", "비고",
)
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
    "admin": "제출·확인 행정서식 · 별지 제1호·제9호",
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
    st.caption("모르는 칸은 비워 두세요. 비워 둔 칸이 이미 적힌 값을 지우지는 않습니다. "
               "탑·반응기·드럼·열교환기·탱크는 직경·높이·처리량 등 해당 설비에 필요한 용량 세부값을 적으면 "
               "규정서식의 용량 칸으로 자동 조합합니다. 비고에는 안전인증·안전검사 등 적용받는 법령명을 적고, "
               "대상이 아니면 '해당 없음'으로 확인합니다.")
    frame = pd.DataFrame([{"설비번호": _clean(r.get("설비번호")), "설비명": _clean(r.get("설비명")),
                           **{column: _clean(r.get(column)) for column in PSM_ONLY_COLUMNS}} for r in rows])
    edited = st.data_editor(frames.safe(frame), hide_index=True, width="stretch", key="psm_form15_extra",
                            disabled=["설비번호", "설비명"], column_config={
                                "용접효율": st.column_config.TextColumn("용접효율", help="용접부의 효율입니다. (예시) 0.85"),
                                "비파괴검사율": st.column_config.TextColumn("비파괴검사율(%)", help="비파괴검사를 하는 비율입니다."),
                                "비고": st.column_config.TextColumn("비고(적용 법령·검사 여부)",
                                    help="안전인증·안전검사 등 적용 법령과 대상 여부를 적습니다. 예: 산업안전보건법 안전검사 대상 / 해당 없음")})
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


def _admin_forms(project) -> None:
    st.caption(
        "공정안전보고서 본문 별지 제12~21호와 별도로 제출·확인 단계에서 사용하는 행정서식입니다. "
        "별지 제1호는 심사신청 단계, 별지 제9호는 심사 후 확인요청 단계에서 사용합니다."
    )

    shared_form1 = admin_forms.form1_values(project)
    shared_form9 = admin_forms.form9_values(project)
    st.success("사업자명·사업자등록번호·주소·대표자·전화번호 등 기존 회사 정보를 다시 묻지 않고 가져옵니다.")

    st.markdown("### 별지 제1호 · 공정안전보고서 심사신청서")
    st.caption("신규 심사 제출 단계입니다. 사업장관리번호와 실제 신청일을 확인해 주세요.")
    form1_management = st.text_input(
        "사업장관리번호",
        value=shared_form1.get("사업장관리번호", ""),
        key="psm_admin_workplace_no",
        help="회사에서 확인한 사업장관리번호를 입력합니다. 모르면 임의 생성하지 않습니다.",
    )
    form1_date = st.text_input(
        "심사신청일",
        value=shared_form1.get("신청일", ""),
        key="psm_admin_form1_date",
        help="실제 제출하는 날짜를 YYYY-MM-DD 형식으로 입력합니다. 현재 날짜를 자동 확정하지 않습니다.",
    )
    if st.button("심사신청서 정보 저장", key="psm_admin_form1_save"):
        admin_forms.save_admin_values(project, {
            "psm.admin.workplace_management_no": form1_management,
            "psm.admin.form1.application_date": form1_date,
        })
        save_project(project)
        st.success("심사신청서 정보를 저장했습니다.")
        st.rerun()

    r1 = admin_forms.form1_readiness(project)
    if r1.ready:
        st.success("별지 제1호 작성에 필요한 값이 확인되었습니다.")
        st.download_button(
            "별지 제1호 심사신청서 DOCX 내려받기",
            data=admin_forms.build_form1_docx(project),
            file_name=admin_forms.form1_filename(project),
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key="psm_admin_form1_download",
            width="stretch",
        )
    else:
        st.warning("별지 제1호 보완 필요")
        for blocker in r1.blockers:
            st.write(f"• {blocker}")
    with st.expander("별지 제1호 제출 전 확인"):
        for item in r1.manual_items:
            st.write(f"• {item}")

    st.divider()
    st.markdown("### 별지 제9호 · 공정안전보고서확인요청서")
    st.caption(
        "이 서식은 심사 완료 후 현장 확인을 요청하는 단계에서 사용합니다. "
        "초기 공정안전보고서 제출 준비 여부와는 별도로 관리합니다."
    )

    c1, c2 = st.columns(2)
    contact_name = c1.text_input("담당자 성명", value=shared_form9.get("담당자 성명", ""), key="psm_admin_contact_name")
    contact_mobile = c2.text_input("담당자 휴대전화번호", value=shared_form9.get("담당자 휴대전화번호", ""), key="psm_admin_contact_mobile")
    contact_email = st.text_input("담당자 전자우편 주소", value=shared_form9.get("담당자 전자우편 주소", ""), key="psm_admin_contact_email")
    target = st.text_input("확인대상 사업 또는 설비명", value=shared_form9.get("확인대상 사업 또는 설비명", ""), key="psm_admin_confirm_target")
    review_date = st.text_input("공정안전보고서 심사완료일", value=shared_form9.get("공정안전보고서 심사완료일", ""), key="psm_admin_review_date")
    construction_period = st.text_input("공사기간", value=shared_form9.get("공사기간", ""), key="psm_admin_construction_period")
    request_date = st.text_input("확인요청일", value=shared_form9.get("확인요청일", ""), key="psm_admin_request_date")
    p1, p2 = st.columns(2)
    period_start = p1.text_input("확인요청 기간 시작", value=shared_form9.get("확인요청 기간 시작", ""), key="psm_admin_period_start")
    period_end = p2.text_input("확인요청 기간 종료", value=shared_form9.get("확인요청 기간 종료", ""), key="psm_admin_period_end")
    form9_date = st.text_input("확인요청서 신청일", value=shared_form9.get("신청일", ""), key="psm_admin_form9_date")

    if st.button("확인요청서 정보 저장", key="psm_admin_form9_save"):
        admin_forms.save_admin_values(project, {
            "psm.admin.contact_name": contact_name,
            "psm.admin.contact_mobile": contact_mobile,
            "psm.admin.contact_email": contact_email,
            "psm.admin.confirmation_target": target,
            "psm.admin.review_completion_date": review_date,
            "psm.admin.construction_period": construction_period,
            "psm.admin.confirmation_request_date": request_date,
            "psm.admin.confirmation_period_start": period_start,
            "psm.admin.confirmation_period_end": period_end,
            "psm.admin.form9.application_date": form9_date,
        })
        save_project(project)
        st.success("확인요청서 정보를 저장했습니다.")
        st.rerun()

    r9 = admin_forms.form9_readiness(project)
    if r9.ready:
        st.success("별지 제9호 작성에 필요한 값이 확인되었습니다.")
        st.download_button(
            "별지 제9호 확인요청서 DOCX 내려받기",
            data=admin_forms.build_form9_docx(project),
            file_name=admin_forms.form9_filename(project),
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key="psm_admin_form9_download",
            width="stretch",
        )
    else:
        st.info("별지 제9호는 확인요청 단계에서 아래 값이 모두 확인되면 출력할 수 있습니다.")
        for blocker in r9.blockers:
            st.write(f"• {blocker}")
    with st.expander("별지 제9호 사용 시점"):
        for item in r9.manual_items:
            st.write(f"• {item}")


def _files(project) -> None:
    from ui import attachments_panel

    attachments_panel.render(project, attachments.SLOTS, "psm")


def _facts(project) -> None:
    from ui import narrative_panel

    narrative_panel.render(project, narrative.PSM_PROFILE, ("emergency-resources", "emergency-contacts", "wash-ppe"), "psm",
                           defaults={"business.employee_count": f12.current(project).get("근로자수", "")})


def _export(project) -> None:
    from ui import report_export_panel

    report_export_panel.render(project, "PSM")


st.set_page_config(page_title="공정안전보고서 작성", page_icon="🏭", layout="wide")
st.title("🏭 공정안전보고서 작성")
st.caption("화학사고예방관리계획서에서 이미 입력한 사업장·물질·시설·시나리오는 다시 묻지 않고 그대로 가져옵니다.")

project_id = _project_selector()
if not project_id:
    st.stop()
project = load_project(project_id)
from ui import unsaved_guard

form_key = unsaved_guard.selector("작성할 별지", list(FORMS), key="psm_form_no", format_func=lambda key: FORMS[key])
try:
    {"12": _table_12, "13": _table_13, **{no: table_grid.grid(no) for no in ("14", "16", "17", "17-2", "17-3", "17-4", "17-5", "18", "19", "20", "21")}, "15": _table_15, "19-2": _table_19_2, "admin": _admin_forms, "facts": _facts, "export": _export, "files": _files}[form_key](project)
finally:
    unsaved_guard.finish()
