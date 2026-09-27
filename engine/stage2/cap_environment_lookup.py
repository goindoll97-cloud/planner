"""Environmental map candidates near a geocoded address (not a legal inventory).

OpenStreetMap/Overpass is a supplemental, crowd maintained source. These
records must be reviewed against official layers and the actual site boundary.
"""

from __future__ import annotations

import math
from typing import Any, Callable

import requests

from .cap_site_lookup import Candidate, SEARCH_RADIUS_M

ENDPOINT = "https://overpass-api.de/api/interpreter"
HEADERS = {"User-Agent": "FrameworkPlanner/1.0 (https://github.com/goindoll97-cloud/planner)"}


def _distance(lat: float, lon: float, points: list[tuple[float, float]]) -> float:
    """Small-area planar distance to a point or any segment of an OSM way."""
    if not points:
        return math.inf
    scale_x = 111_320 * math.cos(math.radians(lat))
    scale_y = 110_950
    xy = [((p_lon - lon) * scale_x, (p_lat - lat) * scale_y) for p_lat, p_lon in points]
    # An address inside an area intersects it even when its outer ring is >800 m away.
    if len(points) >= 4 and points[0] == points[-1]:
        inside = False
        for (ay, ax), (by, bx) in zip(points, points[1:]):
            if (ay > lat) != (by > lat) and lon < (bx - ax) * (lat - ay) / (by - ay) + ax:
                inside = not inside
        if inside:
            return 0.0
    best = min(math.hypot(x, y) for x, y in xy)
    for (ax, ay), (bx, by) in zip(xy, xy[1:]):
        dx, dy = bx - ax, by - ay
        t = max(0., min(1., -(ax * dx + ay * dy) / (dx * dx + dy * dy))) if dx or dy else 0.
        best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


def search(lat: float, lon: float, *, post: Callable = requests.post) -> list[Candidate]:
    """Fetch mapped POIs, land cover, waterways and natural objects within 800 m.

    Tags indicate map features, not legal protected-area designations. A
    feature may cross the circle even if its label is outside; use geometry.
    """
    if not (33 <= lat <= 39 and 124 <= lon <= 132):
        raise ValueError("사업장 주소 좌표가 대한민국 범위에 있지 않습니다.")
    around = f"(around:{SEARCH_RADIUS_M},{lat},{lon})"
    query = ("[out:json][timeout:30];("
             f'nwr["waterway"]{around};'
             f'nwr["natural"]{around};'
             f'nwr["landuse"]{around};'
             f'nwr["amenity"]{around};'
             f'nwr["tourism"]{around};'
             f'nwr["leisure"]{around};'
             f'nwr["shop"]{around};'
             f'nwr["historic"]{around};'
             f'nwr["building"]{around};'
             f'nwr["office"]{around};'
             f'nwr["healthcare"]{around};'
             f'nwr["craft"]{around};'
             f'nwr["emergency"]{around};'
             f'nwr["public_transport"]{around};'
             f'nwr["man_made"]{around};'
             ");out center geom;")
    response = post(ENDPOINT, data={"data": query}, headers=HEADERS, timeout=40)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise ValueError("환경 지도 응답을 읽을 수 없습니다.")
    if payload.get("remark"):
        raise ValueError("OpenStreetMap 서버가 결과 누락 가능성을 보고했습니다.")
    found: dict[str, Candidate] = {}
    for item in payload["elements"]:
        try:
            tags = item.get("tags") or {}
            typ = str(item["type"])
            identifier = f"{typ}/{item['id']}"
            if typ == "node":
                points = [(float(item["lat"]), float(item["lon"]))]
            else:
                points = [(float(p["lat"]), float(p["lon"])) for p in item.get("geometry") or []]
                if not points and item.get("center"):
                    points = [(float(item["center"]["lat"]), float(item["center"]["lon"]))]
            distance = _distance(lat, lon, points)
            if distance > SEARCH_RADIUS_M:
                continue
            kind = next((f"{key}={tags[key]}" for key in
                         ("waterway", "natural", "landuse", "amenity", "tourism", "leisure", "shop", "historic",
                          "building", "office", "healthcare", "craft", "emergency", "public_transport", "man_made")
                         if key in tags), "지도 객체")
            name = str(tags.get("name:ko") or tags.get("name") or f"이름 없는 {kind}").strip()
            found[identifier] = Candidate(
                name=name, category="", subtype="",
                address=f"지도 분류: {kind} · OSM {identifier}", distance_m=round(distance, 1),
                source="OpenStreetMap/Overpass 지도 객체 (법정 분류 미확인)",
            )
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
    return sorted(found.values(), key=lambda c: c.distance_m if c.distance_m is not None else math.inf)
