"""VWorld 2D vector layers: nearby environmental *candidates* only.

The API's point buffer finds intersecting features; distances below use the
returned geometry and are measured from the address point, not the site edge.
"""

from __future__ import annotations

import math
import os
import re
from typing import Any, Callable

import requests

from .cap_environment_lookup import _distance
from .cap_site_lookup import Candidate, SEARCH_RADIUS_M

ENV_KEY = "VWORLD_API_KEY"
ENDPOINT = "https://api.vworld.kr/req/data"
ADDRESS_ENDPOINT = "https://api.vworld.kr/req/address"
# Published VWorld 2D Data API service IDs. A designation is not proof of
# protection under the CAP annex, and the river network is a mapped line.
LAYERS = (
    ("LT_C_SPBD", "도로명주소 건물", ("bd_nm", "bld_nm", "name")),
    ("LT_C_WKMSTRM", "하천망", ("riv_nm", "riv_name")),
    ("LT_C_UM901", "습지보호지역", ("name", "nm")),
    ("LT_C_WGISARWET", "습지보호구역", ("name", "nm")),
    ("LT_C_WGISNPGUG", "국립자연공원", ("name", "nm")),
    ("LT_C_UF151", "산림보호구역", ("name", "nm")),
    ("LT_C_UM710", "상수원보호구역", ("name", "nm")),
    ("LT_C_WGISARECO", "생태계경관보전지역", ("name", "nm")),
)
PAGE_SIZE = 100
MAX_PAGES = 30  # Surface truncation explicitly if the provider still has more.


class VWorldResponseError(ValueError):
    """Safe diagnostic containing only validated server status and error code."""


def api_key() -> str:
    from ..kosha_msds import _load_local_env

    _load_local_env()
    return next((value.strip() for name in (ENV_KEY, "v_world_key", "VWORLD_KEY")
                 if (value := os.environ.get(name, "").strip())), "")


def geocode(address: str, *, get: Callable | None = None) -> tuple[str, str] | None:
    """Use VWorld's road address geocoder, then parcel address if needed."""
    key = api_key()
    if not key or not address.strip():
        return None
    if get is None:
        def get(params: dict[str, Any]) -> dict[str, Any]:
            response = requests.get(ADDRESS_ENDPOINT, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
    for kind in ("ROAD", "PARCEL"):
        body = (get({"service": "address", "request": "GetCoord", "version": "2.0",
                     "crs": "EPSG:4326", "address": address.strip(), "refine": "true",
                     "simple": "false", "format": "json", "type": kind, "key": key}) or {}).get("response") or {}
        if body.get("status") == "OK":
            point = ((body.get("result") or {}).get("point") or {})
            return str(point["x"]), str(point["y"])
    return None


def _default_get(params: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(ENDPOINT, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def _paths(geometry: dict) -> list[list[tuple[float, float]]]:
    """Flatten GeoJSON coordinates into latitude/longitude paths."""
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    if kind == "Point":
        return [[(float(coords[1]), float(coords[0]))]]
    if kind in ("LineString", "MultiPoint"):
        return [[(float(p[1]), float(p[0])) for p in coords]]
    if kind in ("Polygon", "MultiLineString"):
        return [[(float(p[1]), float(p[0])) for p in line] for line in coords]
    if kind == "MultiPolygon":
        return [[(float(p[1]), float(p[0])) for p in line] for polygon in coords for line in polygon]
    return []


def _inside(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    for (y1, x1), (y2, x2) in zip(ring, ring[1:]):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _geometry_distance(lat: float, lon: float, geometry: dict) -> float:
    paths = _paths(geometry)
    if geometry.get("type") == "Polygon" and paths and _inside(lat, lon, paths[0]):
        return 0.0
    if geometry.get("type") == "MultiPolygon":
        for polygon in geometry.get("coordinates") or []:
            if polygon and _inside(lat, lon, [(float(p[1]), float(p[0])) for p in polygon[0]]):
                return 0.0
    return min((_distance(lat, lon, path) for path in paths), default=math.inf)


def search(lat: float, lon: float, *, get: Callable = _default_get) -> tuple[list[Candidate], list[str]]:
    """Return (candidates, notices). Individual layer failures stay visible."""
    key = api_key()
    if not key:
        return [], [f"{ENV_KEY}가 없어 브이월드 환경 레이어를 검색하지 않았습니다."]
    if not (33 <= lat <= 39 and 124 <= lon <= 132):
        raise ValueError("주소 좌표가 대한민국 범위에 있지 않습니다.")
    found: dict[tuple[str, str], Candidate] = {}
    notices: list[str] = []
    for layer, title, name_fields in LAYERS:
        seen_pages: set[tuple[str, ...]] = set()
        for page in range(1, MAX_PAGES + 1):
            try:
                payload = get({
                    "service": "data", "request": "GetFeature", "version": "2.0",
                    "data": layer, "key": key, "format": "json", "crs": "EPSG:4326",
                    "geomFilter": f"POINT({lon} {lat})", "buffer": SEARCH_RADIUS_M,
                    "geometry": "true", "size": PAGE_SIZE, "page": page,
                })
                body = payload.get("response") or {}
                if body.get("status") != "OK":
                    # Server text may echo the API key: show only short status/code tokens.
                    error = body.get("error") or {}
                    status = body.get("status")
                    code = error.get("code") if isinstance(error, dict) else None
                    status = status if isinstance(status, str) and re.fullmatch(r"[A-Z_]{1,32}", status) else "UNKNOWN"
                    code = code if isinstance(code, str) and re.fullmatch(r"[A-Z_]{1,40}", code) else ""
                    if status == "NOT_FOUND" and not code:
                        break  # This layer has no features at this address.
                    raise VWorldResponseError(f"응답 상태 {status}" + (f", 코드 {code}" if code else ""))
                collection = (body.get("result") or {}).get("featureCollection") or {}
                features = collection.get("features")
                if not isinstance(features, list):
                    raise ValueError("브이월드 지형정보 응답 형식이 예상과 다릅니다")
            except (requests.RequestException, ValueError, TypeError, AttributeError) as exc:
                detail = str(exc) if isinstance(exc, VWorldResponseError) else type(exc).__name__
                if isinstance(exc, VWorldResponseError) and "코드 INCORRECT_KEY" in detail:
                    notices.append("브이월드 인증키 오류(INCORRECT_KEY): 프로젝트 .env의 VWORLD_API_KEY 또는 v_world_key 값과 브이월드 인증키 발급 시 등록한 도메인을 확인하세요. 브이월드 레이어는 조회되지 않았습니다.")
                    return sorted(found.values(), key=lambda item: item.distance_m or 0), notices
                notices.append(f"브이월드 {title} 조회 실패({detail}); 해당 레이어는 직접 확인하세요.")
                break
            fingerprints = tuple(str(item.get("id") or (item.get("properties") or {}).get("gid") or "")
                                 for item in features if isinstance(item, dict))
            if fingerprints and fingerprints in seen_pages:
                notices.append(f"브이월드 {title}에서 같은 결과 페이지가 반복되어 조회를 중단했습니다. 누락 여부를 확인하세요.")
                break
            seen_pages.add(fingerprints)
            for feature in features:
                try:
                    props = feature.get("properties") or {}
                    geom = feature.get("geometry") or {}
                    distance = _geometry_distance(lat, lon, geom)
                    if distance > SEARCH_RADIUS_M:
                        continue
                    identifier = str(feature.get("id") or props.get("gid") or props.get("bd_mgt_sn") or "").strip()
                    name = next((str(props[field]).strip() for field in name_fields if props.get(field)), "")
                    if not name:
                        continue
                    identifier = identifier or f"{name}/{round(distance, 1)}"
                    found[(layer, identifier)] = Candidate(
                        name=name, category="", subtype="",
                        address=f"브이월드 {title} · {layer} · {identifier}",
                        distance_m=round(distance, 1),
                        source=f"브이월드 2D 데이터 API · {title} (법정 분류 미확인)",
                    )
                except (TypeError, ValueError, KeyError, IndexError, OverflowError):
                    continue
            if len(features) < PAGE_SIZE:
                break
        else:
            notices.append(f"브이월드 {title} 조회가 {MAX_PAGES * PAGE_SIZE}건 제한에 도달했습니다. 누락 여부를 확인하세요.")
    return sorted(found.values(), key=lambda item: item.distance_m or 0), notices
