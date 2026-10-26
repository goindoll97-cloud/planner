"""별지 제8호에서 주소 조사·지도 경계·시설 묶음을 연결합니다."""
from __future__ import annotations

import html
import json

import folium
from folium.plugins import Draw, Fullscreen
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from engine.stage2 import cap_form8_workspace as f8
from engine.stage2 import cap_surroundings as survey
from engine.stage2.storage import save_project

COLORS = {"INSIDE": "#94a3b8", "POINT_INSIDE": "#a855f7", "OUTSIDE": "#2563eb",
          "CROSSES": "#e8790a", "TOUCHES": "#e8790a", "NO_GEOMETRY": "#64748b",
          "BOUNDARY_REQUIRED": "#2563eb"}


def table_rows(rows):
    return [{"객체 ID": row["object_id"], "명칭": row["name"],
             "부지와 관계": survey.RELATIONS[row["relation"]], "도형 종류": row["geometry_kind"],
             "부지까지 최소거리(m, 참고)": row["boundary_distance_m"], "출처": row.get("source", "")}
            for row in rows]


def build_map(data, rows, drawings):
    lon, lat = data["center"]
    result = folium.Map(location=[lat, lon], zoom_start=16, tiles="OpenStreetMap", control_scale=True)
    folium.Marker([lat, lon], tooltip="주소 조회 기준점", icon=folium.Icon(color="blue", icon="info-sign")).add_to(result)
    folium.Circle([lat, lon], radius=data["radius_m"], color="#94a3b8", weight=1, fill=False,
                  tooltip="주소점 기준 조회 범위").add_to(result)
    objects = []
    for row in rows:
        try:
            geometry = survey.checked_geometry(row.get("geometry"))
        except ValueError:
            continue
        objects.append({"type": "Feature", "geometry": geometry.__geo_interface__,
                        "properties": {"id": html.escape(row["object_id"]), "name": html.escape(row["name"]),
                                       "relation": survey.RELATIONS[row["relation"]],
                                       "color": COLORS[row["relation"]],
                                       "distance": str(row["boundary_distance_m"] if row["boundary_distance_m"] is not None else "미산정")}})
    if objects:
        folium.GeoJson({"type": "FeatureCollection", "features": objects}, name="수집한 지도 객체",
                       style_function=lambda feature: {"color": feature["properties"]["color"], "weight": 1.5,
                                                       "fillColor": feature["properties"]["color"], "fillOpacity": .3},
                       marker=folium.CircleMarker(radius=5, fill=True, fill_opacity=.8),
                       highlight_function=lambda feature: {"weight": 4, "fillOpacity": .55},
                       tooltip=folium.GeoJsonTooltip(fields=["name", "relation", "distance", "id"],
                                                     aliases=["명칭", "부지와 관계", "부지까지 거리(m, 참고)", "원본 객체 ID"])).add_to(result)
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
    folium.LayerControl(collapsed=True).add_to(result)
    return result


def _import_diagnostic(project, prefix, persist):
    with st.expander("기존 주소 진단 JSON 가져오기"):
        uploaded = st.file_uploader("주소 조회 결과 JSON", type=["json"], key=prefix + "diagnostic_upload")
        checked = st.checkbox("파일의 주소가 현재 사업장과 같은 위치임을 확인했습니다", key=prefix + "import_checked")
        if st.button("진단 결과를 지도 조사로 가져오기", disabled=uploaded is None or not checked, key=prefix + "import"):
            try:
                if uploaded.size > 20 * 1024 * 1024:
                    raise ValueError("진단 파일은 20MB 이하로 올려 주세요.")
                payload = json.loads(uploaded.getvalue())
                results = payload.get("results", [])
                reference = next((r["coordinate"] for r in results if r.get("coordinate") and r.get("provider") == "vworld"), None)
                reference = reference or next((r["coordinate"] for r in results if r.get("coordinate")), None)
                if reference is None:
                    raise ValueError("파일에 주소 좌표가 없습니다.")
                objects = [row for r in results for row in r.get("candidates", [])]
                if len(objects) > 10000:
                    raise ValueError("한 번에 10,000개 이하 객체를 가져오세요.")
                notes = [note for r in results for note in r.get("notices", [])]
                notes.append("기존 진단 파일에서 가져왔습니다. 파일 생성시각과 누락 여부를 확인하세요.")
                survey.save_survey(project, objects, center=(reference["lon"], reference["lat"]),
                                   notices=notes, source_address=str(payload.get("address", "")))
                persist(project)
                st.rerun()
            except (ValueError, TypeError, KeyError, AttributeError):
                st.error("파일의 주소·좌표·후보 구조를 확인하세요. 오래된 진단 파일에 도형이 없으면 주소로 다시 조사해야 합니다.")


def render(project, *, persist=save_project, allow_query=True):
    prefix = f"surroundings_{project.project_id}_"
    st.subheader("주소로 주변자료 조사하고 지도에서 정리하기")
    address = f8.address(project)
    st.caption(f"사업장 주소: {address or '별지 제3호에서 주소를 먼저 저장하세요.'}")
    use_kakao = st.checkbox("카카오 장소명도 함께 조회", value=False, key=prefix + "kakao")
    keyword = st.text_input("국토정보플랫폼에서 확인할 인근 시설명 (선택)", key=prefix + "keyword")
    first, second = st.columns(2)
    initial = first.button("주소로 주변자료 조사", disabled=not address or not allow_query, type="primary", key=prefix + "collect")
    expanded = second.button("경계 기준으로 다시 조사", disabled=not address or not allow_query or survey.boundary(project) is None,
                             key=prefix + "recollect")
    if initial or expanded:
        try:
            with st.spinner("주소와 주변 건물·공간자료를 조회합니다. 수 분 걸릴 수 있습니다."):
                survey.collect(project, use_kakao=use_kakao, ngii_keyword=keyword, expand_to_boundary=expanded)
                persist(project)
            st.session_state.pop(prefix + "drawings", None)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    _import_diagnostic(project, prefix, persist)
    data = survey.survey(project)
    if not data:
        st.info("브이월드 건물 윤곽을 가져온 뒤, 지도에서 부지 경계를 그리고 주변 시설을 정리합니다.")
        return
    if not survey.is_current(project):
        st.warning("저장된 조사와 현재 사업장 주소가 다릅니다. 주소로 다시 조사해 주세요.")
        return
    rows = survey.annotate(project)
    counts = {key: sum(row["relation"] == key for row in rows) for key in survey.RELATIONS}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("수집 객체", len(rows))
    c2.metric("부지 내부 도형", counts["INSIDE"])
    c3.metric("경계 걸침·접촉", counts["CROSSES"] + counts["TOUCHES"])
    c4.metric("위치 확인 필요", counts["NO_GEOMETRY"])
    st.info(survey.coverage_warning(project))
    with st.expander(f"조사 출처와 미완료 사항 ({len(data.get('notices', []))}개)"):
        st.write(f"조회 시각(UTC): {data['checked_at']} · 주소점 조사 반경: {data['radius_m']}m")
        for note in data.get("notices", []):
            st.write("• " + str(note))
    show_inside = st.checkbox("부지 내부 도형도 표시 (원자료는 항상 보존)", value=False, key=prefix + "inside")
    visible = [row for row in rows if show_inside or row["relation"] != "INSIDE"]
    st.caption("파랑: 외부/경계 지정 전 · 회색: 내부 · 주황: 경계 걸침·접촉 · 보라: 대표점만 내부. "
               "대표점만으로 시설 전체가 내부라고 판단하지 않습니다.")
    st.write("지도 왼쪽의 다각형·사각형 도구로 부지 경계를 그리세요. 연필로 수정하고 쓰레기통으로 삭제할 수 있습니다.")
    stored_boundary = survey.boundary_record(project).get("geometry")
    initial_drawings = [{"type": "Feature", "geometry": stored_boundary, "properties": {}}] if stored_boundary else []
    draft = st.session_state.get(prefix + "drawings", initial_drawings)
    map_key = prefix + "map_" + data["fingerprint"][:12] + survey.boundary_record(project).get("fingerprint", "")[:8]
    map_result = st_folium(build_map(data, visible, draft), height=550, use_container_width=True,
                           returned_objects=["all_drawings"], key=map_key)
    if map_result.get("all_drawings") is not None:
        drawings = map_result["all_drawings"]
        if drawings != draft:
            st.session_state[prefix + "boundary_confirmed"] = False
        draft = drawings
        st.session_state[prefix + "drawings"] = draft
    with st.expander("부지 도면의 GeoJSON 경계 가져오기"):
        upload = st.file_uploader("경계 GeoJSON (경도·위도, EPSG:4326)", type=["json", "geojson"], key=prefix + "boundary_file")
        if st.button("경계 파일을 지도에 불러오기", disabled=upload is None, key=prefix + "load_boundary"):
            try:
                if upload.size > 1024 * 1024:
                    raise ValueError("경계 파일은 1MB 이하로 올려 주세요.")
                payload = json.loads(upload.getvalue())
                items = payload.get("features", []) if payload.get("type") == "FeatureCollection" else [payload]
                geometry = survey.boundary_from_drawings(items)
                st.session_state[prefix + "drawings"] = [{"type": "Feature", "geometry": geometry, "properties": {}}]
                st.session_state[prefix + "boundary_confirmed"] = False
                st.rerun()
            except (ValueError, TypeError, AttributeError):
                st.error("GeoJSON의 좌표계와 유효한 면 경계를 확인하세요.")
    source = st.text_input("경계를 확인한 도면·지도와 날짜", value=survey.boundary_record(project).get("source", ""),
                           placeholder="예: 부지 배치도 B-01, 2026-10-26 확인", key=prefix + "boundary_source")
    confirmed = st.checkbox("그린 경계가 사업장 부지와 일치하는지 근거자료와 대조했습니다", key=prefix + "boundary_confirmed")
    left, right = st.columns(2)
    if left.button("사업장 경계 저장·내외부 분석", key=prefix + "save_boundary"):
        try:
            survey.save_boundary(project, survey.boundary_from_drawings(draft), source, confirmed=confirmed)
            persist(project)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    if right.button("저장한 경계 지우기", disabled=survey.boundary(project) is None, key=prefix + "clear_boundary"):
        survey.clear_boundary(project)
        persist(project)
        st.session_state[prefix + "drawings"] = []
        st.rerun()
    st.caption("분석한 최소거리는 참고값입니다. 별지의 확정 거리·법정 분류·범위 전체 확인은 자동으로 채우지 않습니다.")
    st.dataframe(pd.DataFrame(table_rows(visible)), hide_index=True, width="stretch")
    if visible:
        originals = {row["object_id"]: row for row in visible}
        with st.expander("원본 속성과 출처 보기"):
            selected = st.selectbox("원본을 확인할 객체", list(originals),
                                    format_func=lambda oid: f"{originals[oid]['name']} · {oid}", key=prefix + "original")
            st.write(originals[selected].get("source", ""))
            st.json(originals[selected].get("attributes") or {})
    _groups(project, rows, visible, prefix, persist)
    exported = json.dumps(survey.geojson_export(project), ensure_ascii=False, indent=2)
    st.download_button("도형·출처·시설 묶음 GeoJSON 내려받기", exported.encode("utf-8"),
                       file_name="surroundings_survey.geojson", mime="application/geo+json", key=prefix + "export")


def _groups(project, rows, visible, prefix, persist):
    st.markdown("#### 시설 단위로 묶기")
    st.caption("같은 이름과 가까운 위치로 묶음 후보를 제시합니다. 서로 다른 명칭·이름 없는 객체·내외부가 다른 객체는 자동 병합하지 않습니다.")
    gap = st.slider("같은 이름 객체 사이의 묶음 간격(m)", 0, 300, 60, step=10, key=prefix + "gap")
    visible_ids = {row["object_id"] for row in visible}
    suggestions = [g for g in survey.group_suggestions(project, gap) if set(g["members"]).intersection(visible_ids)]
    by_id = {row["object_id"]: row for row in rows}
    if suggestions:
        options = {g["group_id"]: g for g in suggestions}
        selected = st.selectbox("시설 묶음 후보", list(options),
                                format_func=lambda gid, options=options: f"{options[gid]['name']} · 객체 {len(options[gid]['members'])}개",
                                key=prefix + "suggestion")
        group = options[selected]
        editor_key = prefix + selected + survey.survey(project)["fingerprint"][:8]
        name = st.text_input("확인할 시설명", value=group["name"], key=editor_key + "name")
        members = st.multiselect("이 시설에 속하는 원본 객체", list(by_id), default=group["members"],
                                 format_func=lambda oid: f"{by_id[oid]['name']} · {survey.RELATIONS[by_id[oid]['relation']]} · {oid}",
                                 key=editor_key + "members")
        confirmed = st.checkbox("시설명과 구성 객체가 같은 시설에 속하는지 확인했습니다", key=editor_key + "confirmed")
        if st.button("시설 묶음 확인·저장", key=prefix + "save_group"):
            try:
                survey.save_group(project, name, members, confirmed=confirmed)
                persist(project)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    stored = survey.saved_groups(project)
    if stored:
        st.dataframe(pd.DataFrame([{"시설명": g["name"], "객체 수": len(g["members"]),
                                    "현재 자료와 일치": g["current"]} for g in stored]), hide_index=True, width="stretch")
        options = {g["group_id"]: g for g in stored}
        chosen = st.selectbox("목록에 연결할 확인 묶음", list(options), format_func=lambda gid, options=options: options[gid]["name"],
                              key=prefix + "saved_group")
        if not options[chosen]["current"]:
            st.warning("조사자료나 경계가 바뀌었습니다. 시설 묶음을 다시 확인해야 목록에 연결할 수 있습니다.")
        a, b = st.columns(2)
        if a.button("별지 제8호에 미검토 후보로 추가", disabled=not options[chosen]["current"], key=prefix + "add_group"):
            try:
                added = survey.import_group(project, chosen)
                persist(project)
                st.success("보호대상 목록에 미검토 후보를 추가했습니다. 다음 단계에서 실제 분류와 거리를 확인하세요." if added else "이미 목록에 연결한 묶음입니다.")
            except ValueError as exc:
                st.error(str(exc))
        if b.button("선택 묶음 해제 (원자료 보존)", key=prefix + "remove_group"):
            survey.remove_group(project, chosen)
            persist(project)
            st.rerun()
