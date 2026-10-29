"""사고시나리오 결과: 회사 파일로 프로그램이 정하고 계산한 시나리오를 확인하는 화면.

화면에서 사람이 직접 하는 일은 지도에서 사업장 경계를 정하는 것 하나입니다(주소를 찾으면 필지 경계가 표시되고, 필지를 눌러
더하거나 빼거나 직접 고친 뒤 ‘이 경계로 확인’을 누르면 주변 조회·거리 계산·시나리오 계산이 이어서 됩니다).
- 시나리오 선정·피해반경·장외거리·보호대상 집계·시설빈도·위험도·공정안전보고서 별지 제19호의2는 프로그램이 계산합니다.
- 고치고 싶으면 회사 작성용 엑셀의 ‘사고시나리오 검토’ 시트(선정할 사고유형·경계까지 거리·물성·개시사건 개수)나 ‘주변 보호대상’
  시트를 고쳐 자료 접수 ①에 다시 올립니다. 이 화면에서는 지금 반영한 엑셀에 지도 조회 값을 채워 내려받을 수 있습니다.
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
SCENARIO_SHEET = "회사 작성용 엑셀의 ‘사고시나리오 검토’ 시트"
KOREA = (36.4, 127.9)
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _to_intake(label: str = "고친 엑셀 올리기: 사업장 업무 > 자료 접수 ① →") -> None:
    try:
        st.page_link(INTAKE_PAGE, label=label)
    except Exception:          # 이 화면만 따로 띄웠을 때(시험 등)
        st.caption("고친 엑셀 올리기: 왼쪽 ‘사업장 업무 > 자료 접수·확인할 일’의 ①")


def _client(prefix: str):
    """로컬 AI(있으면). 없으면 None — 규칙 문장·이름 규칙 제안만 씁니다."""
    from ui.narrative_panel import _local_config

    config, probe, build = _local_config(prefix)
    if probe is not None and probe.ready:
        return build(config)
    return None


# ---------------------------------------------------------------- ① 지도·경계

PICK, DRAW = "필지 클릭으로 고르기", "직접 그리기·고치기"
RELATION_COLORS = {"OUTSIDE": "#2563eb", "CROSSES": "#e8790a", "TOUCHES": "#e8790a", "POINT_INSIDE": "#a855f7",
                   "BOUNDARY_REQUIRED": "#2563eb"}


def _polygons(geometry):
    geom = survey.checked_geometry(geometry, polygon_only=True)
    for polygon in (list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]):
        yield [[(y, x) for x, y, *_ in ring] for ring in polygon.__geo_interface__["coordinates"]]


def _map(project, *, center, zoom, parcels, drawings, mode):
    """배경(브이월드 항공사진·지적선, 키가 없으면 오픈스트리트맵) + 고른 필지 + 저장한 경계 + 주변 지도 객체."""
    import folium
    from folium.plugins import Draw, Fullscreen
    from engine.stage2 import cap_vworld_lookup as vworld

    tiles = vworld.tile_layers()
    result = folium.Map(location=list(center), zoom_start=zoom, tiles=None, control_scale=True, max_zoom=19)
    if tiles:
        folium.TileLayer(tiles["satellite"], attr="브이월드", name="항공사진", max_zoom=19).add_to(result)
        folium.TileLayer(tiles["base"], attr="브이월드", name="일반지도", max_zoom=19).add_to(result)
        folium.TileLayer(tiles["hybrid"], attr="브이월드", name="지명·도로", overlay=True, max_zoom=19).add_to(result)
        folium.WmsTileLayer(tiles["cadastral_wms"], layers="lp_pa_cbnd_bubun", styles="lp_pa_cbnd_bubun_line",
                            fmt="image/png", transparent=True, overlay=True, name="지적선", version="1.3.0",
                            attr="브이월드 연속지적도", max_zoom=19).add_to(result)
    else:
        folium.TileLayer("OpenStreetMap", name="오픈스트리트맵").add_to(result)
    data = survey.survey(project) if survey.survey(project) and survey.is_current(project) else {}
    if data:
        features = []
        for row in survey.annotate(project):
            if row["relation"] in ("INSIDE", "NO_GEOMETRY"):
                continue
            features.append({"type": "Feature", "geometry": row["geometry"],
                             "properties": {"name": str(row["name"]), "color": RELATION_COLORS.get(row["relation"], "#64748b"),
                                            "distance": "" if row["boundary_distance_m"] is None else f"{row['boundary_distance_m']:.0f} m"}})
        if features:
            folium.GeoJson({"type": "FeatureCollection", "features": features}, name="주변 지도 객체",
                           style_function=lambda f: {"color": f["properties"]["color"], "weight": 1.5,
                                                     "fillColor": f["properties"]["color"], "fillOpacity": .25},
                           marker=folium.CircleMarker(radius=5, fill=True, fill_opacity=.8),
                           tooltip=folium.GeoJsonTooltip(fields=["name", "distance"], aliases=["명칭", "경계에서 거리"])).add_to(result)
    saved = survey.boundary(project)
    if saved is not None and mode == PICK:
        for locations in _polygons(survey.boundary_record(project)["geometry"]):
            folium.Polygon(locations, color="#0f766e", weight=2, dash_array="6", fill=False, tooltip="저장한 사업장 경계").add_to(result)
    if mode == PICK:
        for parcel in parcels:
            for locations in _polygons(parcel["geometry"]):
                folium.Polygon(locations, color="#16a34a", weight=3, fill=True, fill_opacity=.2,
                               tooltip=f"고른 필지 {parcel.get('label', '')} (다시 누르면 빠짐)").add_to(result)
    else:
        editable = folium.FeatureGroup(name="사업장 경계 (편집 가능)").add_to(result)
        for item in drawings:
            try:
                for locations in _polygons(item.get("geometry") if item.get("type") == "Feature" else item):
                    folium.Polygon(locations, color="#16a34a", weight=3, fill=True, fill_opacity=.08).add_to(editable)
            except (ValueError, AttributeError):
                continue
        Draw(feature_group=editable, show_geometry_on_click=False,
             draw_options={"polyline": False, "polygon": {"allowIntersection": False, "showArea": True},
                           "rectangle": True, "circle": False, "marker": False, "circlemarker": False},
             edit_options={"edit": True, "remove": True, "poly": {"allowIntersection": False}}).add_to(result)
    Fullscreen().add_to(result)
    folium.LayerControl(collapsed=True).add_to(result)
    return result


def _search(prefix: str, address: str) -> None:
    """주소로 지도를 옮기고, 그 자리의 필지를 첫 필지로 고릅니다."""
    point, where = ss.locate(address)
    if point is None:
        st.session_state[prefix + "note"] = ("warning", where)
        return
    lon, lat = point
    st.session_state[prefix + "center"], st.session_state[prefix + "zoom"] = (lat, lon), 17
    parcels, note = ss.toggle_parcel([], lat, lon)
    st.session_state[prefix + "parcels"] = parcels
    st.session_state[prefix + "origin"] = "브이월드 연속지적도 필지를 고른 경계"
    st.session_state[prefix + "note"] = (("success", f"{where}에서 주소를 찾았습니다. {note} 공장이 여러 필지면 옆 필지를 눌러 더하세요.")
                                         if parcels else ("info", f"{where}에서 주소를 찾았습니다. {note}"))


def _boundary(project) -> None:
    from streamlit_folium import st_folium

    prefix = f"scn_map_{project.project_id}_"
    record = survey.boundary_record(project)
    saved = survey.boundary(project)
    address = f8.address(project)
    if saved is not None:
        st.success(f"확인한 사업장 경계: {record.get('source', '')}. 바꾸려면 아래에서 다시 고르고 ‘이 경계로 확인’을 누르세요.")
    st.caption("주소를 찾으면 그 자리의 필지 경계가 표시됩니다. 공장이 여러 필지면 옆 필지를 눌러 더하고, 잘못 고른 필지는 다시 눌러 빼세요. "
               "실제 담장과 다르면 ‘직접 그리기·고치기’로 꼭짓점을 고칩니다. ‘이 경계로 확인’을 누르면 주변 조회·거리 계산·시나리오 계산이 이어서 됩니다.")
    left, right = st.columns([4, 1])
    query = left.text_input("주소로 찾기", value=address, key=prefix + "address",
                            help="지도를 옮기는 데만 씁니다. 사업장 주소(서식에 들어가는 값)는 회사 파일의 값입니다.")
    right.write("")
    if right.button("찾기", key=prefix + "search", width="stretch") or (
            address and saved is None and not st.session_state.get(prefix + "searched")):
        st.session_state[prefix + "searched"] = True          # 처음 열 때 회사 파일의 주소로 한 번 찾아 둡니다
        _search(prefix, query)
    note = st.session_state.pop(prefix + "note", None)
    if note:
        getattr(st, note[0])(note[1])

    from engine.stage2 import cap_vworld_lookup as vworld
    has_parcels = bool(vworld.api_key())
    if prefix + "mode_next" in st.session_state:          # 경계 파일을 불러오면 ‘직접 그리기·고치기’로 넘어감
        st.session_state[prefix + "mode"] = st.session_state.pop(prefix + "mode_next")
    mode = st.radio("경계 정하는 방법", [PICK, DRAW], index=0 if has_parcels else 1, horizontal=True, key=prefix + "mode",
                    help="필지 고르기는 브이월드 키가 있어야 합니다.")
    parcels = st.session_state.get(prefix + "parcels", [])
    if prefix + "center" not in st.session_state:
        center, zoom = KOREA, 7
        geometry = record.get("geometry") if saved is not None else None
        if geometry:
            point = survey.checked_geometry(geometry, polygon_only=True).centroid
            center, zoom = (point.y, point.x), 17
        st.session_state[prefix + "center"], st.session_state[prefix + "zoom"] = center, zoom
    if prefix + "drawings" not in st.session_state:
        start = ss.parcels_geometry(parcels) if parcels else (record.get("geometry") if saved is not None else None)
        st.session_state[prefix + "drawings"] = [{"type": "Feature", "geometry": start, "properties": {}}] if start else []
    drawings = st.session_state[prefix + "drawings"]
    if mode == DRAW and parcels and not st.session_state.get(prefix + "drawn_from_parcels"):
        drawings = [{"type": "Feature", "geometry": ss.parcels_geometry(parcels), "properties": {}}]   # 고른 필지에서 고치기 시작
        st.session_state[prefix + "drawings"], st.session_state[prefix + "drawn_from_parcels"] = drawings, True
    if mode == DRAW:
        st.caption("지도 왼쪽 도구: 다각형·사각형으로 그리기, 연필로 꼭짓점 고치기, 쓰레기통으로 지우기.")
    elif not has_parcels:
        st.info("브이월드 키(VWORLD_API_KEY)가 없어 필지를 고를 수 없습니다. ‘직접 그리기·고치기’로 그려 주세요.")

    center, zoom = st.session_state[prefix + "center"], st.session_state[prefix + "zoom"]
    key = prefix + "map_" + mode
    result = st_folium(_map(project, center=center, zoom=zoom, parcels=parcels, drawings=drawings, mode=mode),
                       height=540, use_container_width=True, key=key,
                       returned_objects=["last_clicked", "zoom"] if mode == PICK else ["all_drawings"]) or {}
    if mode == PICK:
        click = result.get("last_clicked")
        if click and (click["lat"], click["lng"]) != st.session_state.get(prefix + "clicked"):
            st.session_state[prefix + "clicked"] = (click["lat"], click["lng"])
            with st.spinner("누른 자리의 필지를 찾습니다."):
                parcels, message = ss.toggle_parcel(parcels, click["lat"], click["lng"])
            st.session_state[prefix + "parcels"] = parcels
            st.session_state[prefix + "center"] = (click["lat"], click["lng"])
            st.session_state[prefix + "zoom"] = result.get("zoom") or zoom
            st.session_state[prefix + "drawn_from_parcels"] = False
            st.session_state[prefix + "origin"] = "브이월드 연속지적도 필지를 고른 경계"
            st.session_state[prefix + "note"] = ("info", message)
            st.rerun()
        if parcels:
            st.write("고른 필지: " + ", ".join(p.get("label", "") for p in parcels))
    elif result.get("all_drawings") is not None and result["all_drawings"] != drawings:
        drawings = result["all_drawings"]
        st.session_state[prefix + "drawings"] = drawings
        if st.session_state.get(prefix + "origin", "").startswith("브이월드"):
            st.session_state[prefix + "origin"] = "브이월드 연속지적도 필지를 고쳐 그린 경계"

    chosen = parcels if mode == PICK else drawings
    if st.button("이 경계로 확인", type="primary", disabled=not chosen, key=prefix + "confirm", width="stretch"):
        try:
            geometry = ss.parcels_geometry(parcels) if mode == PICK else survey.boundary_from_drawings(drawings)
            origin = st.session_state.get(prefix + "origin") or "화면 지도에서 그린 경계"
            if mode == DRAW and not origin.startswith(("브이월드", "경계 파일")):
                origin = "화면 지도에서 그린 경계"
            with st.spinner("경계를 저장하고 주변 지도 조회·거리 계산·사고시나리오 계산을 합니다."):
                summary = ss.confirm(project, geometry, origin)
            save_project(project)
            text = (f"사업장 경계를 확인했습니다. 주변 지도 객체 {summary['objects']}개를 조회했고, 경계 밖 500m 안의 이름 있는 시설 "
                    f"{summary['candidates']}곳을 찾았습니다. ‘② 주변 보호대상’에서 엑셀에 채워 내려받으세요.")
            st.session_state[prefix + "note"] = ("success", text + "".join(" " + n for n in summary["notices"]))
            for name in ("parcels", "drawings", "drawn_from_parcels", "clicked"):
                st.session_state.pop(prefix + name, None)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    with st.expander("도면에서 뽑은 경계 파일 올리기 (GeoJSON 또는 꼭짓점 좌표 CSV)"):
        st.caption("CSV는 ‘경도, 위도’ 머리글 아래에 꼭짓점을 순서대로 적습니다(EPSG:4326). 불러온 경계는 ‘직접 그리기·고치기’에 그려지고, "
                   "‘이 경계로 확인’으로 확정합니다.")
        upload = st.file_uploader("경계 파일", type=["json", "geojson", "csv"], key=prefix + "file")
        if upload is not None and st.button("지도에 불러오기", key=prefix + "load"):
            try:
                if upload.size > 1024 * 1024:
                    raise ValueError("경계 파일은 1MB 이하로 올려 주세요.")
                content = upload.getvalue()
                geometry = (ss.boundary_from_csv(content) if upload.name.lower().endswith(".csv")
                            else ss.boundary_from_geojson(content))
                point = survey.checked_geometry(geometry, polygon_only=True).centroid
                st.session_state[prefix + "drawings"] = [{"type": "Feature", "geometry": geometry, "properties": {}}]
                st.session_state[prefix + "drawn_from_parcels"] = True
                st.session_state[prefix + "center"], st.session_state[prefix + "zoom"] = (point.y, point.x), 17
                st.session_state[prefix + "origin"] = f"경계 파일 {upload.name}"
                st.session_state[prefix + "mode_next"] = DRAW
                st.rerun()
            except (ValueError, TypeError, AttributeError, KeyError) as exc:
                st.error(f"경계를 읽지 못했습니다: {exc}")
    if saved is not None:
        if st.button("확인한 경계 지우기", key=prefix + "clear"):
            survey.clear_boundary(project)
            save_project(project)
            st.rerun()
        if survey.survey(project):
            st.caption(survey.coverage_warning(project))


# ---------------------------------------------------------------- ② 주변 보호대상

def _current_workbook(project) -> tuple[bytes | None, str]:
    """지금 반영한 회사 작성용 엑셀 원본과 그 이름. 없으면 (None, 빈 양식 이름)."""
    from engine.stage2 import cap_upload_template as tpl
    from engine.stage2 import company_workbook_intake as company_intake
    from engine.stage2.storage import load_attachment

    current = company_intake.current(project) or {}
    if current.get("sha256"):
        content = load_attachment(project.project_id, current["sha256"])
        if content:
            return content, current.get("name") or tpl.COMPANY_FILENAME
    return None, tpl.COMPANY_FILENAME


def _targets(project) -> None:
    pid = project.project_id
    st.caption("별지 제8호 보호대상은 회사 작성용 엑셀의 ‘주변 보호대상’ 시트와 ‘사업장 정보’ 시트의 조사 근거 항목에서 읽습니다. "
               "아래 버튼은 지금 반영한 엑셀에 지도 조회로 찾은 경계 밖 500m 안의 시설과 확인한 경계에서 잰 거리를 더해 줍니다. "
               "분류·거리·인원과 확인 항목(예/아니오)을 고쳐 자료 접수 ①에 그대로 다시 올리세요.")
    rows = f8.saved_rows(project)
    if f8.declared_no_target(project):
        st.success("엑셀에 ‘500m 안 보호대상 없음’으로 적혀 있습니다.")
    elif rows:
        frames.show(pd.DataFrame([{c: r.get(c, "") for c in ss.TARGET_COLUMNS} for r in rows]), hide_index=True, width="stretch")
    else:
        st.info("엑셀의 ‘주변 보호대상’ 시트가 아직 비어 있습니다.")
    needs = f8.needs(project)
    if needs:
        st.markdown("**엑셀에서 고칠 것** (‘주변 보호대상’ 시트·‘사업장 정보’의 조사 근거 항목)")
        for need in needs:
            st.write("• " + need)
    candidates = ss.candidate_rows(project)
    st.caption(f"지도 조회 후보 {len(candidates)}곳" if candidates else
               "지도 조회 후보가 없습니다(① 탭에서 경계를 확인하면 주변을 조회합니다). 엑셀의 ‘주변 보호대상’ 시트에 직접 적어도 됩니다.")
    original, name = _current_workbook(project)
    if original is None:
        st.caption("반영한 회사 작성용 엑셀이 없어 빈 양식에 채웁니다.")
    content = ss.company_workbook(project, original)
    if candidates and st.checkbox("로컬 AI로 분류 제안 보태기(이름 규칙으로 못 정한 시설만)", key=f"scn_ai_cls_{pid}"):
        client = _client(f"scn_cls_{pid}")
        if client is None:
            st.warning("로컬 AI를 찾지 못했습니다. 이름 규칙 제안만 넣습니다.")
        elif st.button("AI 분류 제안을 넣어 엑셀 만들기", key=f"scn_ai_make_{pid}"):
            st.session_state[f"scn_ai_book_{pid}"] = ss.company_workbook(project, original, client)
        content = st.session_state.get(f"scn_ai_book_{pid}", content)
    st.download_button("회사 작성용 엑셀에 주변 보호대상 채워 내려받기", content, file_name=name, mime=XLSX,
                       key=f"scn_survey_{pid}", width="stretch")
    _to_intake()


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
               f"{SCENARIO_SHEET}의 ‘선정할 사고유형’ 열을 고쳐(빼려면 ‘선정 안 함’) 다시 올리세요.")
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
    st.caption("장외로 영향이 나가는 시나리오만 시설빈도·위험도를 계산합니다. 개시사건 개수·완화장치는 " + SCENARIO_SHEET + "에서 읽습니다.")
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
                    " 회사 자료에 ‘대기온도(℃)’·‘습도(%)’를 적어 올려도 됩니다.")
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
           "고칠 것은 회사 작성용 엑셀의 ‘사고시나리오 검토’·‘주변 보호대상’ 시트를 고쳐 다시 올립니다.")
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
