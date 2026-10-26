"""주변 지도 조사: 원자료 보존, 부지 관계 분석, 검토 가능한 시설 묶음."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
import re
from typing import Any

from pyproj import Transformer
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform, unary_union

from . import cap_form8_workspace as f8
from .cap_site_lookup import Candidate
from .project import Stage2Project

SURVEY_KEY = "cap.surroundings.survey"
BOUNDARY_KEY = "cap.surroundings.boundary"
GROUPS_KEY = "cap.surroundings.groups"
RELATIONS = {"INSIDE": "부지 내부", "POINT_INSIDE": "대표점이 부지 내부", "OUTSIDE": "부지 외부",
             "CROSSES": "경계 걸침", "TOUCHES": "경계 접촉", "NO_GEOMETRY": "위치 확인 필요",
             "BOUNDARY_REQUIRED": "경계 지정 전"}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _value(project, key, default):
    record = project.get_field(key)
    return deepcopy(record.value) if record is not None else deepcopy(default)


def survey(project: Stage2Project) -> dict:
    return _value(project, SURVEY_KEY, {})


def is_current(project: Stage2Project) -> bool:
    return bool(survey(project)) and survey(project).get("address") == f8.address(project)


@lru_cache(maxsize=1)
def _projector():
    return Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True).transform


def checked_geometry(raw: dict | None, *, polygon_only=False):
    if not isinstance(raw, dict):
        raise ValueError("위치 도형이 없습니다.")
    if raw.get("type") == "Feature":
        raw = raw.get("geometry")
    try:
        geom = shape(raw)
        coords = geom.bounds
        if geom.is_empty or not geom.is_valid or len(coords) != 4 or not all(math.isfinite(v) for v in coords):
            raise ValueError
        if not (-180 <= coords[0] <= coords[2] <= 180 and -90 <= coords[1] <= coords[3] <= 90):
            raise ValueError
        if geom.geom_type not in {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"}:
            raise ValueError
        if polygon_only and (geom.geom_type not in {"Polygon", "MultiPolygon"} or geom.area <= 0):
            raise ValueError
    except Exception as exc:
        raise ValueError("유효한 경도·위도의 도형인지 확인하세요. 경계는 서로 교차하지 않는 면이어야 합니다.") from exc
    return geom


def metric_geometry(raw):
    geom = transform(_projector(), checked_geometry(raw))
    if geom.is_empty or not all(math.isfinite(v) for v in geom.bounds):
        raise ValueError("도형의 좌표를 미터 단위로 변환할 수 없습니다.")
    return geom


def boundary_record(project) -> dict:
    return _value(project, BOUNDARY_KEY, {})


def boundary(project):
    record = project.get_field(BOUNDARY_KEY)
    value = boundary_record(project)
    if record is None or record.status != "USER_CONFIRMED" or value.get("address") != f8.address(project):
        return None
    return checked_geometry(value.get("geometry"), polygon_only=True) if value else None


def _invalidate_imported_review(project):
    rows = f8.saved_rows(project)
    if any("시설묶음ID=" in str(row.get("검색 출처·검색일", "")) for row in rows):
        f8.save(project, rows, no_target=False, scope_reviewed=False, status="HOLD")
        f8.invalidate_review(project)


def save_boundary(project, geometry: dict, source: str, *, confirmed: bool):
    if not confirmed or not source.strip():
        raise ValueError("부지 도면 등 경계의 근거를 적고 경계를 확인했다는 항목을 선택하세요.")
    geom = checked_geometry(geometry, polygon_only=True)
    projected = metric_geometry(mapping(geom))
    current = survey(project)
    if current and is_current(project):
        origin = metric_geometry({"type": "Point", "coordinates": current["center"]})
        if origin.distance(projected) > 10000:
            raise ValueError("경계가 주소 조회점에서 10km 넘게 떨어져 있습니다. 위치와 좌표계를 확인하세요.")
    payload = {"geometry": mapping(geom), "address": f8.address(project), "source": source.strip(), "checked_at": _now()}
    payload["fingerprint"] = _hash({"geometry": payload["geometry"], "address": payload["address"], "source": payload["source"]})
    project.set_field(BOUNDARY_KEY, "주변 조사에 사용하는 사업장 경계", payload, "USER_CONFIRMED",
                      note="담당자가 확인한 도면/지도 경계. 지적 경계나 법적 경계를 자동 확정한 것이 아님.")
    _invalidate_imported_review(project)
    return payload


def clear_boundary(project):
    project.set_field(BOUNDARY_KEY, "주변 조사에 사용하는 사업장 경계", {}, "HOLD")
    _invalidate_imported_review(project)


def boundary_from_drawings(drawings: list[dict]):
    if not drawings:
        raise ValueError("지도에 부지 경계를 그리거나 GeoJSON 경계를 가져오세요.")
    geometries = [checked_geometry(item, polygon_only=True) for item in drawings]
    return mapping(unary_union(geometries))


def save_survey(project, candidates: list[Candidate | dict], *, center: tuple[float, float],
                radius_m: float = 800, notices: list[str] | None = None, source_address: str = "") -> dict:
    lon, lat = map(float, center)
    if not (124 <= lon <= 132 and 33 <= lat <= 39):
        raise ValueError("사업장 좌표의 경도·위도를 확인하세요.")
    if not math.isfinite(radius_m) or not 0 < radius_m <= 10000:
        raise ValueError("조사 반경을 확인하세요.")
    objects = {}
    for candidate in candidates:
        item = asdict(candidate) if isinstance(candidate, Candidate) else deepcopy(candidate)
        if not isinstance(item, dict):
            continue
        item = {key: item.get(key) for key in ("name", "category", "subtype", "address", "distance_m", "source",
                                              "object_id", "geometry", "attributes")}
        item["category"], item["subtype"] = "", ""  # 수집 결과에서 법정 분류를 확정하지 않습니다.
        item["name"] = str(item.get("name") or "명칭 미제공")
        identifier = str(item.get("object_id") or "") or "survey:" + _hash(item)[:24]
        item["object_id"] = identifier
        objects[identifier] = item
    payload = {"address": f8.address(project), "source_address": source_address or f8.address(project),
               "center": [lon, lat], "radius_m": radius_m, "checked_at": _now(),
               "objects": list(objects.values()), "notices": list(notices or [])}
    payload["fingerprint"] = _hash({k: payload[k] for k in ("address", "center", "radius_m", "objects")})
    project.set_field(SURVEY_KEY, "주변 지도 조사 원자료", payload, "HOLD",
                      note="공개 공간자료의 미검토 후보. 원래 도형과 식별번호를 보존함.")
    _invalidate_imported_review(project)
    return payload


def required_radius(project, center, margin=500.0) -> int:
    site = boundary(project)
    if site is None:
        return 800
    origin = metric_geometry({"type": "Point", "coordinates": list(center)})
    bounds = transform(_projector(), site).bounds
    corners = [(bounds[x], bounds[y]) for x in (0, 2) for y in (1, 3)]
    radius = max(origin.distance(Point(point)) for point in corners) + margin + 10
    return max(800, math.ceil(radius))


def collect(project, *, use_kakao=False, ngii_keyword="", expand_to_boundary=False):
    from . import cap_site_lookup as kakao, cap_vworld_lookup as vworld, cap_ngii_lookup as ngii

    address = f8.address(project)
    if not address:
        raise ValueError("별지 제3호에서 사업장 주소를 먼저 저장하세요.")
    center = None
    notices = []
    for title, provider in (("브이월드", vworld), ("카카오", kakao)):
        if provider.api_key():
            try:
                center = provider.geocode(address)
                if center:
                    break
            except Exception as exc:
                notices.append(f"{title} 주소 조회 실패({type(exc).__name__})")
    if center is None:
        raise ValueError("주소 좌표를 찾지 못했습니다. 주소와 API 설정을 확인하세요.")
    center = tuple(map(float, center))
    radius = required_radius(project, center) if expand_to_boundary else 800
    if radius > 10000:
        raise ValueError("이 경계 전체를 포함하려면 조사 반경이 10km를 넘습니다. 경계와 주소 위치를 확인하세요.")
    candidates = []
    if vworld.api_key():
        try:
            rows, notes = vworld.search(center[1], center[0], radius_m=radius)
            candidates.extend(rows)
            notices.extend(notes)
        except Exception as exc:
            notices.append(f"브이월드 공간자료 조회 실패({type(exc).__name__}); 조회 미완료")
    else:
        notices.append("브이월드 키가 없어 건물 윤곽과 환경 레이어를 조회하지 않았습니다.")
    if use_kakao:
        try:
            rows, message = kakao.find_candidates(address)
            candidates.extend(rows)
            notices.append(message)
            if radius > 800:
                notices.append("카카오 장소 검색은 주소점 800m 범위입니다. 브이월드 조사 반경과 다를 수 있습니다.")
        except Exception as exc:
            notices.append(f"카카오 장소 조회 실패({type(exc).__name__}); 조회 미완료")
    if ngii_keyword.strip():
        try:
            rows, notes = ngii.search(address, [ngii_keyword.strip()])
            candidates.extend(rows)
            notices.extend(notes)
        except Exception as exc:
            notices.append(f"국토정보플랫폼 조회 실패({type(exc).__name__}); 조회 미완료")
    notices.append("논·밭·일반 산림의 면적자료는 아직 이 조사에 포함하지 않았습니다. 공간자료와 법정 지정 자료를 추가 확인하세요.")
    return save_survey(project, candidates, center=center, radius_m=radius, notices=notices)


def annotate(project) -> list[dict]:
    data = survey(project)
    site = boundary(project) if is_current(project) else None
    projected_site = metric_geometry(mapping(site)) if site is not None else None
    rows = []
    for raw in data.get("objects", []):
        item = deepcopy(raw)
        item.update(relation="BOUNDARY_REQUIRED", boundary_distance_m=None, geometry_kind="")
        try:
            geom = checked_geometry(item.get("geometry"))
            projected = metric_geometry(mapping(geom))
            item["geometry_kind"] = geom.geom_type
            if projected_site is not None:
                if projected_site.covers(projected):
                    relation = "POINT_INSIDE" if geom.geom_type in {"Point", "MultiPoint"} else "INSIDE"
                elif projected_site.touches(projected):
                    relation = "TOUCHES"
                elif projected_site.intersects(projected):
                    relation = "CROSSES"
                else:
                    relation = "OUTSIDE"
                item.update(relation=relation, boundary_distance_m=round(projected_site.distance(projected), 1))
        except ValueError:
            item["relation"] = "NO_GEOMETRY"
        rows.append(item)
    return rows


def coverage_warning(project) -> str:
    data = survey(project)
    if not is_current(project):
        return "사업장 주소가 조사 당시와 다릅니다. 다시 조사해야 합니다."
    if boundary(project) is None:
        return "사업장 경계를 확인하기 전입니다. 내부·외부 구분과 경계 기준 범위를 아직 판단할 수 없습니다."
    if required_radius(project, data["center"]) > data["radius_m"]:
        return "현재 주소점 조사 원이 사업장 경계 주변 500m 전체를 포함하지 못합니다. ‘경계 기준으로 다시 조사’를 실행하세요."
    return "조사 원이 입력한 경계 주변 500m를 기하학적으로 포함합니다. 자료 누락·레이어 실패·법정 분류 확인은 별도로 필요합니다."


def _normal_name(name):
    if str(name).startswith("명칭 미제공"):
        return ""
    return re.sub(r"[^0-9a-z가-힣]", "", str(name).lower())


def group_suggestions(project, gap_m=60.0) -> list[dict]:
    if not math.isfinite(gap_m) or not 0 <= gap_m <= 500:
        raise ValueError("묶음 간격은 0~500m로 지정하세요.")
    rows = annotate(project)
    parents = list(range(len(rows)))
    projected = []
    for row in rows:
        try:
            projected.append(metric_geometry(row.get("geometry")))
        except ValueError:
            projected.append(None)
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    for i, row in enumerate(rows):
        name = _normal_name(row["name"])
        if not name or projected[i] is None:
            continue
        for j in range(i):
            if (projected[j] is not None and _normal_name(rows[j]["name"]) == name
                    and rows[j]["relation"] == row["relation"]
                    and projected[i].distance(projected[j]) <= gap_m):
                parents[root(i)] = root(j)
    bundles = {}
    for i, row in enumerate(rows):
        bundles.setdefault(root(i), []).append(row["object_id"])
    by_id = {row["object_id"]: row for row in rows}
    result = []
    for ids in bundles.values():
        ids = sorted(ids)
        result.append({"group_id": "suggestion:" + _hash(ids)[:20], "name": by_id[ids[0]]["name"],
                       "members": ids, "confirmed": False, "kind": "자동 묶음 후보"})
    return sorted(result, key=lambda g: (-len(g["members"]), g["name"]))


def saved_groups(project):
    data = survey(project)
    boundary_hash = boundary_record(project).get("fingerprint", "")
    available = {row["object_id"] for row in data.get("objects", [])}
    groups = _value(project, GROUPS_KEY, [])
    for group in groups:
        group["current"] = (is_current(project) and group.get("survey_fingerprint") == data.get("fingerprint")
                            and group.get("boundary_fingerprint") == boundary_hash
                            and set(group.get("members", [])).issubset(available))
    return groups


def save_group(project, name: str, members: list[str], *, confirmed: bool):
    if not is_current(project) or boundary(project) is None:
        raise ValueError("현재 주소의 조사자료와 확인한 사업장 경계가 필요합니다.")
    available = {row["object_id"] for row in survey(project).get("objects", [])}
    if not confirmed or not name.strip() or not members or not set(members).issubset(available):
        raise ValueError("시설명과 구성 객체를 확인하고 묶음 확인 항목을 선택하세요.")
    members = sorted(set(members))
    identifier = "facility:" + _hash(members)[:20]
    payload = {"group_id": identifier, "name": name.strip(), "members": members,
               "confirmed": True, "kind": "담당자 확인 묶음", "checked_at": _now(),
               "survey_fingerprint": survey(project)["fingerprint"],
               "boundary_fingerprint": boundary_record(project)["fingerprint"]}
    groups = [group for group in saved_groups(project) if not set(group["members"]).intersection(members)]
    groups.append(payload)
    project.set_field(GROUPS_KEY, "담당자가 정리한 주변 시설 묶음", groups, "USER_CONFIRMED",
                      note="원자료는 별도 보존. 묶음 확인은 법정 분류 확인이 아님.")
    _invalidate_imported_review(project)
    return payload


def remove_group(project, group_id):
    groups = [g for g in saved_groups(project) if g["group_id"] != group_id]
    project.set_field(GROUPS_KEY, "담당자가 정리한 주변 시설 묶음", groups, "HOLD")
    _invalidate_imported_review(project)


def import_group(project, group_id) -> bool:
    group = next((g for g in saved_groups(project) if g["group_id"] == group_id), None)
    if not group or not group["current"] or boundary(project) is None:
        raise ValueError("조사 또는 경계가 바뀌었습니다. 묶음을 다시 확인하세요.")
    members = [row for row in annotate(project) if row["object_id"] in group["members"]]
    if all(row["relation"] == "INSIDE" for row in members):
        raise ValueError("전체가 부지 내부인 묶음입니다. 주변 목록에 자동 추가하지 않습니다.")
    marker = "시설묶음ID=" + group_id
    rows = f8.saved_rows(project)
    if any(marker in str(row.get("검색 출처·검색일", "")) for row in rows):
        return False
    rows.append({"보호대상 명칭": group["name"], "보호대상 구분": "", "세부유형": "",
                 "주소·위치": f"{members[0].get('address', '')} · 구성 객체 {len(members)}개",
                 "사업장 경계와 거리(m)": "", "검색결과 거리(주소점 기준, 참고)": "",
                 "검색 출처·검색일": f"주변 지도 조사 {survey(project)['checked_at']} · {marker}",
                 "GIS/현장 근거": "", "500m 범위 전체 확인": False})
    f8.save(project, rows, no_target=False, scope_reviewed=False, status="HOLD")
    f8.invalidate_review(project)
    return True


def geojson_export(project):
    features = []
    memberships = {member: group["group_id"] for group in saved_groups(project) for member in group["members"]}
    for row in annotate(project):
        try:
            geom = mapping(checked_geometry(row.get("geometry")))
        except ValueError:
            geom = None
        features.append({"type": "Feature", "id": row["object_id"], "geometry": geom,
                         "properties": {**{key: row.get(key) for key in ("name", "source", "address", "relation", "boundary_distance_m")},
                                        "object_id": row["object_id"], "group_id": memberships.get(row["object_id"], ""),
                                        "legal_classification": "미확정", "attributes": row.get("attributes") or {}}})
    site = boundary(project)
    if site is not None:
        features.append({"type": "Feature", "id": "site-boundary", "geometry": mapping(site),
                         "properties": {"name": "담당자 확인 사업장 경계", "source": boundary_record(project).get("source")}})
    return {"type": "FeatureCollection", "features": features,
            "survey": {k: v for k, v in survey(project).items() if k != "objects"},
            "facility_groups": saved_groups(project), "note": "미검토 지도 조사자료. 최종 보호대상/위험도 판정이 아님."}
