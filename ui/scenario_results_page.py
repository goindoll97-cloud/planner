"""사고시나리오 결과: 회사 파일로 프로그램이 정하고 계산한 시나리오를 확인하는 화면.

화면에서 사람이 직접 하는 일은 지도에서 사업장 경계를 그리는 것 하나입니다.
- 시나리오 선정·피해반경·장외거리·보호대상 집계·시설빈도·위험도·공정안전보고서 별지 제19호의2는 프로그램이 계산합니다.
- 고치고 싶으면 ‘사고시나리오 검토자료’(선정할 사고유형·경계까지 거리·물성·개시사건 개수)나 ‘주변 보호대상 조사표’ 파일을 고쳐
  ‘사업장 업무 > 자료 올리기’에 다시 올립니다. 조사표는 이 화면에서 지도 조회 값을 채워 내려받습니다.
- 로컬 AI는 선정 근거 문장과 보호대상 분류 제안에만 씁니다(숫자는 계산 엔진에서만).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.stage2 import cap_form8_workspace as f8
from engine.stage2 import cap_impact_workspace as iw
from engine.stage2 import cap_scenario_workspace as sc
from engine.stage2 import cap_surroundings as survey
from engine.stage2 import psm_form19_2_workspace as f19
from engine.stage2 import scenario_pipeline as sp
from engine.stage2 import scenario_survey as ss
from engine.stage2.cap_risk_engine import build_cap_form14_data, build_cap_form15_data
from engine.stage2.storage import load_project, save_project
from ui import cap_common
from ui import cap_frames as frames

INTAKE_PAGE = "ui/evidence_workspace_page.py"
KOREA = (36.4, 127.9)
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _to_intake(label: str = "파일 올리기·고치기: 사업장 업무 > 자료 올리기 →") -> None:
    try:
        st.page_link(INTAKE_PAGE, label=label)
    except Exception:          # 이 화면만 따로 띄웠을 때(시험 등)
        st.caption("파일 올리기·고치기: 왼쪽 ‘사업장 업무 > 자료 올리기’")


def _client(prefix: str):
    """로컬 AI(있으면). 없으면 None — 규칙 문장·이름 규칙 제안만 씁니다."""
    from ui.narrative_panel import _local_config

    config, probe, build = _local_config(prefix)
    if probe is not None and probe.ready:
        return build(config)
    return None


# ---------------------------------------------------------------- ① 지도·경계

def _map(project, drawings):
    import folium
    from folium.plugins import Draw, Fullscreen

    data = survey.survey(project) if survey.is_current(project) else {}
    if data:
        from ui.surroundings_map_panel import build_map

        rows = [r for r in survey.annotate(project) if r["relation"] != "INSIDE"]
        return build_map(data, rows, drawings)
    center, zoom = KOREA, 7
    for item in drawings or []:
        try:
            point = survey.checked_geometry(item, polygon_only=True).centroid
            center, zoom = (point.y, point.x), 17
            break
        except ValueError:
            continue
    result = folium.Map(location=list(center), zoom_start=zoom, tiles="OpenStreetMap", control_scale=True)
    editable = folium.FeatureGroup(name="사업장 경계 (편집 가능)").add_to(result)
    for item in drawings or []:
        try:
            geom = survey.checked_geometry(item, polygon_only=True)
        except ValueError:
            continue
        for polygon in (list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]):
            locations = [[(y, x) for x, y, *_ in ring] for ring in polygon.__geo_interface__["coordinates"]]
            folium.Polygon(locations, color="#16a34a", weight=3, fill=True, fill_opacity=.08).add_to(editable)
    Draw(feature_group=editable, show_geometry_on_click=False,
         draw_options={"polyline": False, "polygon": {"allowIntersection": False, "showArea": True},
                       "rectangle": True, "circle": False, "marker": False, "circlemarker": False},
         edit_options={"edit": True, "remove": True, "poly": {"allowIntersection": False}}).add_to(result)
    Fullscreen().add_to(result)
    return result


def _boundary(project) -> None:
    from streamlit_folium import st_folium

    prefix = f"scn_map_{project.project_id}_"
    record = survey.boundary_record(project)
    saved = survey.boundary(project)
    address = f8.address(project)
    st.caption(f"사업장 주소: {address or '사업장 일반정보 파일에 주소를 적어 올려 주세요.'}")
    if saved is not None:
        st.success(f"저장한 사업장 경계: {record.get('source', '')}")
    else:
        st.info("지도에 사업장 부지 경계를 그려 저장하세요. 주소의 필지 경계를 초안으로 불러와 고쳐 그려도 됩니다.")
    first, second, third = st.columns(3)
    if first.button("주소 필지 경계를 초안으로 불러오기", disabled=not address, key=prefix + "parcel",
                    help="브이월드 연속지적도에서 주소점이 든 필지를 불러옵니다. 공장 부지가 여러 필지면 지도에서 넓혀 그리세요."):
        geometry, note = ss.parcel_draft(project)
        if geometry:
            st.session_state[prefix + "drawings"] = [{"type": "Feature", "geometry": geometry, "properties": {}}]
            st.session_state[prefix + "origin"] = note + "를 고쳐 그린 경계"
            st.session_state[prefix + "note"] = ("success", note + "를 불러왔습니다. 실제 부지와 맞게 고친 뒤 저장하세요.")
        else:
            st.session_state[prefix + "note"] = ("warning", note)
        st.rerun()
    if second.button("주소로 주변 지도 조회", disabled=not address, key=prefix + "collect",
                     help="브이월드 건물·하천·보호구역 자료를 불러와 지도에 표시합니다. 경계를 저장한 뒤 다시 누르면 경계 기준으로 넓혀 조회합니다."):
        try:
            with st.spinner("주소와 주변 공간자료를 조회합니다."):
                survey.collect(project, expand_to_boundary=saved is not None)
            save_project(project)
        except ValueError as exc:
            st.session_state[prefix + "note"] = ("warning", str(exc))
        st.rerun()
    if third.button("저장한 경계 지우기", disabled=saved is None, key=prefix + "clear"):
        survey.clear_boundary(project)
        save_project(project)
        st.session_state[prefix + "drawings"] = []
        st.rerun()
    note = st.session_state.pop(prefix + "note", None)
    if note:
        getattr(st, note[0])(note[1])
    stored = record.get("geometry") if saved is not None else None
    initial = [{"type": "Feature", "geometry": stored, "properties": {}}] if stored else []
    draft = st.session_state.get(prefix + "drawings", initial)
    st.write("지도 왼쪽의 다각형·사각형 도구로 부지 경계를 그리세요. 연필로 고치고 쓰레기통으로 지웁니다.")
    key = prefix + "map_" + str((survey.survey(project) or {}).get("fingerprint", ""))[:12] + str(record.get("fingerprint", ""))[:8]
    result = st_folium(_map(project, draft), height=520, use_container_width=True, returned_objects=["all_drawings"], key=key)
    if result and result.get("all_drawings") is not None and result["all_drawings"] != draft:
        draft = result["all_drawings"]
        st.session_state[prefix + "drawings"] = draft
    if st.button("그린 경계 저장", type="primary", disabled=not draft, key=prefix + "save"):
        try:
            ss.save_drawn_boundary(project, draft, st.session_state.get(prefix + "origin", "화면 지도에서 그린 경계"))
            save_project(project)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    with st.expander("도면에서 뽑은 경계 파일 올리기 (GeoJSON 또는 꼭짓점 좌표 CSV)"):
        st.caption("CSV는 ‘경도, 위도’ 머리글 아래에 꼭짓점을 순서대로 적습니다(EPSG:4326). 올린 경계는 지도에 그려지고, ‘그린 경계 저장’으로 저장합니다.")
        upload = st.file_uploader("경계 파일", type=["json", "geojson", "csv"], key=prefix + "file")
        if upload is not None and st.button("지도에 불러오기", key=prefix + "load"):
            try:
                if upload.size > 1024 * 1024:
                    raise ValueError("경계 파일은 1MB 이하로 올려 주세요.")
                content = upload.getvalue()
                geometry = (ss.boundary_from_csv(content) if upload.name.lower().endswith(".csv")
                            else ss.boundary_from_geojson(content))
                st.session_state[prefix + "drawings"] = [{"type": "Feature", "geometry": geometry, "properties": {}}]
                st.session_state[prefix + "origin"] = f"경계 파일 {upload.name}"
                st.rerun()
            except (ValueError, TypeError, AttributeError, KeyError) as exc:
                st.error(f"경계를 읽지 못했습니다: {exc}")
    if survey.survey(project):
        st.caption(survey.coverage_warning(project))


# ---------------------------------------------------------------- ② 주변 보호대상

def _targets(project) -> None:
    pid = project.project_id
    st.caption("별지 제8호 보호대상은 ‘주변 보호대상 조사표’ 파일에서 읽습니다. 아래에서 조사표를 내려받으면 지도 조회로 찾은 "
               "경계 밖 500m 안의 시설과 그린 경계에서 잰 거리가 미리 적혀 있습니다. 분류·거리·인원을 고쳐 다시 올리세요.")
    rows = f8.saved_rows(project)
    if f8.declared_no_target(project):
        st.success("조사표에 ‘500m 안 보호대상 없음’으로 적혀 있습니다.")
    elif rows:
        frames.show(pd.DataFrame([{c: r.get(c, "") for c in ss.TARGET_COLUMNS} for r in rows]), hide_index=True, width="stretch")
    else:
        st.info("아직 조사표를 올리지 않았습니다.")
    needs = f8.needs(project)
    if needs:
        st.markdown("**조사표에서 고칠 것**")
        for need in needs:
            st.write("• " + need)
    candidates = ss.candidate_rows(project)
    st.caption(f"지도 조회 후보 {len(candidates)}곳" if candidates else
               "지도 조회 후보가 없습니다(경계를 저장하고 ‘주소로 주변 지도 조회’를 누르면 채워집니다). 빈 조사표에 직접 적어도 됩니다.")
    content = ss.workbook(project)
    if candidates and st.checkbox("로컬 AI로 분류 제안 보태기(이름 규칙으로 못 정한 시설만)", key=f"scn_ai_cls_{pid}"):
        client = _client(f"scn_cls_{pid}")
        if client is None:
            st.warning("로컬 AI를 찾지 못했습니다. 이름 규칙 제안만 넣습니다.")
        elif st.button("AI 분류 제안을 넣어 조사표 만들기", key=f"scn_ai_make_{pid}"):
            st.session_state[f"scn_ai_book_{pid}"] = ss.workbook(project, client)
        content = st.session_state.get(f"scn_ai_book_{pid}", content)
    st.download_button("주변 보호대상 조사표 내려받기 (엑셀)", content, file_name=ss.FILENAME, mime=XLSX,
                       key=f"scn_survey_{pid}", width="stretch")
    _to_intake("채운 조사표 올리기: 사업장 업무 > 자료 올리기 →")


# ---------------------------------------------------------------- ③ 시나리오·영향범위

def _problems(outcome: sp.Outcome) -> None:
    if outcome.problems:
        st.markdown("**파일에서 고칠 것**")
        frames.show(pd.DataFrame([{"어디": p.where, "문제": p.what, "고칠 곳": p.fix} for p in outcome.problems]),
                    hide_index=True, width="stretch")
        _to_intake()


def _scenarios(project, outcome: sp.Outcome) -> None:
    pid = project.project_id
    st.caption("대상 설비는 규정수량 비교(규정 제23조, 별표 2)로, 사고유형은 물질의 독성 구분·폭발한계로 정했습니다. 바꾸려면 "
               "‘사고시나리오 검토자료’ 파일의 ‘선정할 사고유형’ 열을 고쳐(빼려면 ‘선정 안 함’) 다시 올리세요.")
    scenarios = sc.saved_scenarios(project)
    if not scenarios:
        st.info("시나리오 대상 설비가 아직 없습니다. 설비대장·제품목록·SDS 물성표를 올리면 규정수량으로 대상 설비를 정합니다.")
        _problems(outcome)
        return
    frames.show(pd.DataFrame([{"사고시나리오": s.get("사고시나리오명"), "설비": s.get("대상 설비번호"), "물질": s.get("유해화학물질명"),
                               "사고유형": s.get("사고유형"), "취급량(kg)": s.get("취급량(kg)"), "선정 근거": s.get("선정 근거"),
                               "근거 출처": s.get("선정 근거 출처", "")} for s in scenarios]), hide_index=True, width="stretch")
    for line in outcome.plan.skipped:
        st.caption("뺀 시나리오 — " + line)
    st.markdown("#### 피해반경·장외거리와 영향범위 안 보호대상 (별지 제12·13호)")
    frames.show(pd.DataFrame([{
        "사고시나리오": i.name, "유형": i.kind,
        "피해반경(m)": "" if i.radius_m is None else round(i.radius_m), "장외거리(m)": "" if i.off_site_m is None else round(i.off_site_m),
        "갑종/을종/환경": f"{i.count('갑종')}/{i.count('을종')}/{i.count('환경수용체')}",
        "거주민/근로자": f"{i.people('거주민수')}/{i.people('근로자수')}", "근거": i.basis} for i in outcome.impacts]),
        hide_index=True, width="stretch")
    st.write(iw.summary_text(outcome.impacts))
    st.caption("방향(풍향)·지형을 반영하지 않은 사업장 경계 기준 원형 범위입니다(보수적). 결과는 초안이며 KORA 등 동등 프로그램 결과와 대조해 확정합니다.")
    _problems(outcome)
    left, right = st.columns(2)
    left.download_button("영향범위 분석 근거서 내려받기 (DOCX)", sp.report_docx(project), file_name=sp.REPORT_NAME, mime=DOCX,
                         key=f"scn_report_{pid}", width="stretch")
    with right:
        client = None
        if st.checkbox("로컬 AI로 선정 근거 문장 다듬기", key=f"scn_ai_reason_{pid}"):
            client = _client(f"scn_reason_{pid}")
            if client is None:
                st.warning("로컬 AI를 찾지 못했습니다. 규칙 문장을 그대로 씁니다.")
        if client is not None and st.button("선정 근거 다듬기", key=f"scn_polish_{pid}"):
            results = sp.polish_reasons(project, client)
            sp.refresh(project)
            save_project(project)
            st.session_state[f"scn_polish_msg_{pid}"] = f"{sum(r['결과'] == '다듬음' for r in results)}개 문장을 다듬었습니다. 근거에 없는 숫자는 [확인 필요]로 바꿨습니다."
            st.rerun()
    message = st.session_state.pop(f"scn_polish_msg_{pid}", None)
    if message:
        st.success(message)


# ---------------------------------------------------------------- ④ 시설빈도·위험도

def _risk(project) -> None:
    st.caption("장외로 영향이 나가는 시나리오만 시설빈도·위험도를 계산합니다. 개시사건 개수·완화장치는 ‘사고시나리오 검토자료’ 파일에서 읽습니다.")
    form14 = build_cap_form14_data(project)
    if form14.scenario_rows:
        frames.show(pd.DataFrame(list(form14.scenario_rows)), hide_index=True, width="stretch")
    for blocker in form14.blockers:
        st.write("• " + blocker)
    form15 = build_cap_form15_data(project)
    if form15.no_offsite_scenario or form15.scenario_rows:
        st.markdown("#### 위험도 (별지 제15호)")
        frames.show(pd.DataFrame([{"항목": k, "값": v} for k, v in {**form15.totals, **form15.scores}.items()]),
                    hide_index=True, width="stretch")
    for message in form15.messages:
        st.caption(message)
    _to_intake()


# ---------------------------------------------------------------- ⑤ 공정안전보고서 별지 제19호의2

def _psm(project, outcome: sp.Outcome) -> None:
    from engine.stage2 import psm_weather

    pid = project.project_id
    st.caption("화학사고예방관리계획서와 같은 시나리오·계산을 쓰고, 서식 끝점(복사열 4·12.5·37.5 kW/m², 폭발 7·21·70 kPa, ERPG 1·2·3)으로 "
               "거리를 구합니다. 최악·대안은 파일의 ‘공정안전보고서 시나리오 구분’이 먼저이고, 비어 있으면 사고유형마다 피해반경이 가장 큰 "
               "시나리오를 최악으로 씁니다. 최악은 1.5 m/s·F, 대안은 3 m/s·D 기상입니다.")
    weather, _ = sp.weather_inputs(project)
    tried = f"scn_weather_tried_{pid}"
    missing = len(weather) < 2 and not psm_weather.saved(project)
    clicked = missing and st.session_state.get(tried) and st.button("기상청 관측 자료로 다시 채우기", key=f"scn_weather_{pid}")
    if missing and (not st.session_state.get(tried) or clicked):
        st.session_state[tried] = True          # 처음 열 때 한 번 주소로 관측소를 골라 채웁니다
        with st.spinner("사업장 주소로 가까운 기상청 관측소의 지난 3년 자료를 불러옵니다."):
            result = psm_weather.auto_fill(project)
        if result.status == "FILLED":
            outcome = sp.refresh(project)
            save_project(project)
            st.success(result.message)
        else:
            st.info((result.message or "관측 자료를 불러오지 못했습니다.") +
                    " 공정안전보고서 사업개요 파일에 ‘대기온도(℃)’·‘습도(%)’를 적어 올려도 됩니다.")
    weather, source = sp.weather_inputs(project)
    st.write(f"대기온도·습도: {weather.get('대기온도(℃)', '없음')} ℃ · {weather.get('습도(%)', '없음')} % "
             + (f"({source})" if source else ""))
    rows = [r.row for r in outcome.psm]
    if not rows:
        st.info("공정안전보고서에 쓸 시나리오 결과가 아직 없습니다.")
        return
    frame = pd.DataFrame(rows).T
    frame.columns = [f"{i + 1}. {r.get('시나리오 구분', '')}" for i, r in enumerate(rows)]
    frames.show(frame.reset_index().rename(columns={"index": "항목"}), width="stretch", hide_index=True)
    holds = sorted({h for r in outcome.psm for h in r.holds})
    if holds:
        with st.expander(f"계산하지 않은 칸 {len(holds)}건과 이유"):
            for hold in holds:
                st.write("• " + hold)
            st.caption("서식 주석 ⑯: 해당사항이 없는 항목은 생략할 수 있습니다. 근거 없는 값은 채우지 않습니다.")


st.set_page_config(page_title="사고시나리오 결과", page_icon="🧭", layout="wide")
st.title("🧭 사고시나리오 결과")
st.caption("시나리오 선정·피해반경·장외거리·위험도는 회사 파일로 프로그램이 계산한 초안입니다. 화면에서는 지도에 사업장 경계만 그리고, "
           "고칠 것은 ‘사고시나리오 검토자료’·‘주변 보호대상 조사표’ 파일을 고쳐 다시 올립니다.")
project_id = cap_common._project_selector()
if not project_id:
    st.stop()
project = load_project(project_id)
if sp.needs_refresh(project):
    with st.spinner("새로 올린 파일로 시나리오를 다시 계산합니다."):
        sp.refresh(project)
    save_project(project)
outcome = sp.current(project)

labels = ["① 사업장 경계·지도", "② 주변 보호대상(별지 제8호)", "③ 사고시나리오(별지 제12·13호)", "④ 시설빈도·위험도(별지 제14·15호)"]
if project.psm_in_scope:
    labels.append("⑤ 공정안전보고서 별지 제19호의2")
tabs = st.tabs(labels)
with tabs[0]:
    _boundary(project)
with tabs[1]:
    _targets(project)
with tabs[2]:
    _scenarios(project, outcome)
with tabs[3]:
    _risk(project)
if project.psm_in_scope:
    with tabs[4]:
        _psm(project, outcome)
