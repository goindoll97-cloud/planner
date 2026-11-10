"""Map-derived accident-origin facts for a facility.

The employee clicks the *actual equipment location* on the map. Coordinates
and shortest distance to the site boundary are derived in EPSG:5179; neither
is ever guessed from the mailing address or site centroid.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

from shapely.geometry import Point, mapping

from . import cap_surroundings as surroundings
from . import scenario_pipeline
from .project import Stage2Project


def location_fact(project: Stage2Project, tag: str, lat: float, lon: float) -> tuple[str, float]:
    if not tag or not tag.strip():
        raise ValueError("설비번호를 먼저 확인해 주세요.")
    if not all(math.isfinite(float(x)) for x in (lat, lon)) or not (33 <= lat <= 39 and 124 <= lon <= 132):
        raise ValueError("실제 설비 위치는 대한민국 내 WGS84 위도·경도로 지정해 주세요.")
    boundary = surroundings.boundary(project)
    if boundary is None:
        raise ValueError("먼저 지도에서 실제 사업장 경계를 선택하거나 그려 주세요.")
    point = Point(lon, lat)
    if not boundary.covers(point):
        raise ValueError("선택한 설비 위치가 저장된 사업장 경계 밖입니다. 필지·설비 위치를 확인해 주세요.")
    projected_boundary = surroundings.metric_geometry(mapping(boundary))
    projected_point = surroundings.metric_geometry(mapping(point))
    metres = projected_boundary.boundary.distance(projected_point)
    # Preserve WGS84 numeric coordinates for statutory form use. Do not round
    # the coordinates before computing the metre distance.
    return f"{lat:.7f},{lon:.7f}", round(float(metres), 2)


def save_location(project: Stage2Project, tag: str, lat: float, lon: float) -> tuple[str, float]:
    known_tags = {
        str(row.get("설비번호") or "").strip()
        for row in scenario_pipeline.sc._facility_rows(project)
    }
    if tag not in known_tags:
        raise ValueError("회사 엑셀의 설비목록에 없는 설비번호입니다.")
    origin, distance = location_fact(project, tag, lat, lon)

    record = project.get_field(scenario_pipeline.INPUT_KEY)
    rows = [dict(row) for row in (record.value if record and isinstance(record.value, list) else [])
            if isinstance(row, Mapping)]
    by_tag = next((row for row in rows if str(row.get("설비번호") or "").strip() == tag), None)
    if by_tag is None:
        by_tag = {"설비번호": tag}
        rows.append(by_tag)
    if (str(by_tag.get("사고원점 좌표") or "").strip() == origin and
            str(by_tag.get("경계까지 거리(m)") or "").strip() == str(distance)):
        return origin, distance

    by_tag["사고원점 좌표"] = origin
    by_tag["경계까지 거리(m)"] = distance
    project.set_field(
        scenario_pipeline.INPUT_KEY,
        "설비별 시나리오 입력(회사 엑셀 및 지도)",
        rows,
        "USER_CONFIRMED",
        evidence=list(record.evidence) if record else None,
        note="설비번호별 실제 지도 클릭 위치와 사업장 경계까지 최단거리(EPSG:5179). "
             "액위 등 기존 엑셀의 회사 사실 입력은 유지.",
    )
    scenario_pipeline.refresh(project)
    return origin, distance
