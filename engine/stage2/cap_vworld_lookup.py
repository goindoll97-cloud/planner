"""VWorld 2D vector layers: nearby environmental *candidates* only.

The API's point buffer finds intersecting features; distances below use the
returned geometry and are measured from the address point, not the site edge.
"""

from __future__ import annotations

import hashlib
import json
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
    ("LT_C_SPBD", "도로명주소 건물", ("buld_nm", "bd_nm", "bld_nm", "building_name", "name")),
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


def api_domain() -> str:
    from ..kosha_msds import _load_local_env

    _load_local_env()
    return os.environ.get("VWORLD_DOMAIN", "").strip()


def _with_domain(params: dict[str, Any]) -> dict[str, Any]:
    values = dict(params)
    domain = api_domain()
    if domain:
        values.setdefault("domain", domain)
    return values


def _properties(feature: dict) -> dict:
    props = feature.get("properties") or {}
    return {str(k).lower(): v for k, v in props.items()} if isinstance(props, dict) else {}


def _first_text(props: dict, fields) -> str:
    return next((str(props[field]).strip() for field in fields
                 if props.get(field) is not None and str(props[field]).strip()), "")


def _feature_identifier(feature: dict) -> str:
    identifier = str(feature.get("id") or "").strip()
    if identifier:
        return identifier
    identifier = _first_text(_properties(feature), ("gid", "bd_mgt_sn", "bld_mgt_sn", "id"))
    if identifier:
        return identifier
    # 위치나 거리의 반올림값 대신 도형/속성의 안정적인 식별자를 사용합니다.
    data = json.dumps({"geometry": feature.get("geometry"), "properties": feature.get("properties")},
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "geometry-" + hashlib.sha256(data.encode("utf-8")).hexdigest()[:20]


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
            response = requests.get(ADDRESS_ENDPOINT, params=_with_domain(params), timeout=15)
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
    response = requests.get(ENDPOINT, params=_with_domain(params), timeout=10)
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


def search(lat: float, lon: float, *, get: Callable = _default_get,
           radius_m: float = SEARCH_RADIUS_M) -> tuple[list[Candidate], list[str]]:
    """Return (candidates, notices). Individual layer failures stay visible."""
    key = api_key()
    if not key:
        return [], [f"{ENV_KEY}가 없어 브이월드 환경 레이어를 검색하지 않았습니다."]
    if not (33 <= lat <= 39 and 124 <= lon <= 132):
        raise ValueError("주소 좌표가 대한민국 범위에 있지 않습니다.")
    if not math.isfinite(radius_m) or not 0 < radius_m <= 10000:
        raise ValueError("조회 반경은 0m 초과 10,000m 이하로 지정하세요.")
    found: dict[tuple[str, str], Candidate] = {}
    notices: list[str] = []
    for layer, title, name_fields in LAYERS:
        raw_count = 0
        unnamed: set[str] = set()
        malformed = 0
        seen_pages: set[tuple[str, ...]] = set()
        for page in range(1, MAX_PAGES + 1):
            try:
                payload = get({
                    "service": "data", "request": "GetFeature", "version": "2.0",
                    "data": layer, "key": key, "format": "json", "crs": "EPSG:4326",
                    "geomFilter": f"POINT({lon} {lat})", "buffer": radius_m,
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
                    # 실제 응답이 data 코드 자체를 거부할 때에만 지원 미확인으로 표시합니다.
                    # 다른 INVALID_RANGE 오류나 키 오류를 '결과 없음'으로 바꾸지 않습니다.
                    detail_text = str(error.get("text") or "") if isinstance(error, dict) else ""
                    if (code == "INVALID_RANGE" and layer in detail_text
                            and re.search(r"\bdata\b", detail_text, re.IGNORECASE)):
                        notices.append(f"브이월드 {title}: {layer} 코드가 2D 데이터 API에서 거부되었습니다. "
                                       "이 레이어는 조회 미완료입니다. 지원되는 데이터 코드 또는 다른 공식 공간자료를 확인해야 하며 '해당 지역 없음'으로 판단하지 마세요.")
                        break
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
            raw_count += len(features)
            fingerprints = tuple(_feature_identifier(item)
                                 for item in features if isinstance(item, dict))
            if fingerprints and fingerprints in seen_pages:
                notices.append(f"브이월드 {title}에서 같은 결과 페이지가 반복되어 조회를 중단했습니다. 누락 여부를 확인하세요.")
                break
            seen_pages.add(fingerprints)
            for feature in features:
                try:
                    if not isinstance(feature, dict):
                        malformed += 1
                        continue
                    props = _properties(feature)
                    geom = feature.get("geometry") or {}
                    distance = _geometry_distance(lat, lon, geom)
                    if not math.isfinite(distance):
                        malformed += 1
                        continue
                    if distance > radius_m:
                        continue
                    identifier = _feature_identifier(feature)
                    name = _first_text(props, name_fields)
                    if not name:
                        # 이름 없는 객체도 조사 대상으로 보존하되 실제 명칭을 추정하지 않습니다.
                        name = f"명칭 미제공 · {title} · {identifier}"
                        unnamed.add(identifier)
                    found[(layer, identifier)] = Candidate(
                        name=name, category="", subtype="",
                        address=f"브이월드 {title} · {layer} · {identifier}",
                        distance_m=round(distance, 1),
                        source=f"브이월드 2D 데이터 API · {title} (지도 객체 후보, 법정 분류 미확인)",
                        object_id=f"vworld:{layer}:{identifier}",
                        geometry=geom,
                        attributes=dict(feature.get("properties") or {}),
                    )
                except (TypeError, ValueError, KeyError, IndexError, AttributeError, OverflowError):
                    malformed += 1
                    continue
            if len(features) < PAGE_SIZE:
                break
        else:
            notices.append(f"브이월드 {title} 조회가 {MAX_PAGES * PAGE_SIZE}건 제한에 도달했습니다. 누락 여부를 확인하세요.")
        if raw_count:
            kept = sum(1 for key in found if key[0] == layer)
            notices.append(f"브이월드 {title}: API 수신 {raw_count}건, 반경 내 중복제거 후보 {kept}건. "
                           f"이름 없는 {len(unnamed)}건은 식별번호로 보존했습니다. 건물 객체 수는 보호대상 시설 수나 회사 수와 다릅니다.")
        if malformed:
            notices.append(f"브이월드 {title}: 도형/속성을 해석하지 못한 {malformed}건이 있어 검토가 필요합니다.")
    return sorted(found.values(), key=lambda item: item.distance_m or 0), notices


PARCEL_LAYER = "LP_PA_CBND_BUBUN"     # 연속지적도(필지 경계). 사업장 경계의 ‘초안’으로만 씁니다.


def parcel_boundary(lat: float, lon: float, *, get: Callable = _default_get) -> tuple[dict | None, str]:
    """주소점이 들어 있는 필지의 경계(GeoJSON 도형)와 설명. 실패하면 (None, 이유).

    공장 부지는 여러 필지인 경우가 많으므로 사람이 지도에서 고쳐 그리는 출발점일 뿐입니다."""
    key = api_key()
    if not key:
        return None, f"{ENV_KEY}가 없어 필지 경계를 불러오지 않았습니다. 지도에 직접 그리거나 경계 파일을 올려 주세요."
    if not (33 <= lat <= 39 and 124 <= lon <= 132):
        return None, "주소 좌표가 대한민국 범위에 있지 않습니다."
    try:
        payload = get({"service": "data", "request": "GetFeature", "version": "2.0", "data": PARCEL_LAYER, "key": key,
                       "format": "json", "crs": "EPSG:4326", "geomFilter": f"POINT({lon} {lat})", "geometry": "true",
                       "size": 10, "page": 1})
        body = (payload or {}).get("response") or {}
        if body.get("status") == "NOT_FOUND":
            return None, "이 주소점에서 필지 경계를 찾지 못했습니다. 지도에 직접 그려 주세요."
        if body.get("status") != "OK":
            status = body.get("status")
            status = status if isinstance(status, str) and re.fullmatch(r"[A-Z_]{1,32}", status) else "UNKNOWN"
            return None, f"브이월드 필지 경계 조회 실패(응답 상태 {status}). 지도에 직접 그려 주세요."
        features = ((body.get("result") or {}).get("featureCollection") or {}).get("features") or []
    except (requests.RequestException, ValueError, TypeError, AttributeError) as exc:
        return None, f"브이월드 필지 경계 조회 실패({type(exc).__name__}). 지도에 직접 그려 주세요."
    polygons = [f for f in features if isinstance(f, dict) and (f.get("geometry") or {}).get("type") in ("Polygon", "MultiPolygon")]
    if not polygons:
        return None, "이 주소점에서 필지 경계를 찾지 못했습니다. 지도에 직접 그려 주세요."
    chosen = next((f for f in polygons if _geometry_distance(lat, lon, f["geometry"]) == 0.0), polygons[0])
    props = _properties(chosen)
    label = str(props.get("addr") or props.get("jibun") or props.get("pnu") or "").strip()
    return chosen["geometry"], f"브이월드 연속지적도 필지 경계{(' ' + label) if label else ''}"
