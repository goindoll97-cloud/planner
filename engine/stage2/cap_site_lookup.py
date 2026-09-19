from __future__ import annotations

"""Address-based protected-target *candidates* for 별지 제8호 (Kakao Local API).

This only proposes. A candidate becomes a confirmed row when the user accepts
it; 별표 4 has size/occupancy conditions (예: 300명 이상) that a map search cannot
verify, and distances here are measured from the geocoded address point, not
from the site boundary. Without KAKAO_REST_API_KEY nothing is looked up and the
user enters the receptors manually.
"""

from dataclasses import dataclass
import os
from typing import Any, Callable

import requests

ENV_KEY = "KAKAO_REST_API_KEY"
BASE = "https://dapi.kakao.com/v2/local"
SEARCH_RADIUS_M = 800  # 500 m + margin, because distance is measured from an address point

# (Kakao mode, value, 구분, 별지 제8호 종류)
SEARCHES: tuple[tuple[str, str, str, str], ...] = (
    ("category", "SC4", "갑종", "교육·연구시설"),
    ("category", "PS3", "갑종", "노유자시설"),
    ("category", "HP8", "갑종", "의료시설"),
    ("category", "CT1", "갑종", "문화·집회시설"),
    ("category", "AD5", "갑종", "숙박시설"),
    ("category", "MT1", "갑종", "판매시설"),
    ("category", "SW8", "갑종", "운수시설"),
    ("category", "AT4", "갑종", "관광휴게시설"),
    ("category", "OL7", "을종", "위험물 저장 및 처리시설"),
    ("keyword", "교회", "갑종", "종교시설"),
    ("keyword", "성당", "갑종", "종교시설"),
    ("keyword", "아파트", "갑종", "주택"),
    ("keyword", "하천", "환경수용체", "하천"),
)


@dataclass(frozen=True)
class Candidate:
    name: str
    category: str
    subtype: str
    address: str
    distance_m: float | None
    source: str


def api_key() -> str:
    return os.environ.get(ENV_KEY, "").strip()


def _default_get(url: str, params: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    response = requests.get(url, params=params, headers=headers, timeout=15)
    response.raise_for_status()
    return response.json()


def geocode(address: str, *, get: Callable = _default_get) -> tuple[str, str] | None:
    """(x, y) of the address, or None. Only the address is sent."""
    key = api_key()
    if not key or not address.strip():
        return None
    data = get(f"{BASE}/search/address.json", {"query": address.strip()}, {"Authorization": f"KakaoAK {key}"})
    documents = data.get("documents") or []
    return (documents[0]["x"], documents[0]["y"]) if documents else None


def find_candidates(address: str, *, get: Callable = _default_get) -> tuple[list[Candidate], str]:
    """(candidates, message). Fails closed: no key or no geocode means no candidates."""
    key = api_key()
    if not key:
        return [], f"{ENV_KEY}가 설정되지 않아 주변 검색을 하지 않았습니다. 보호대상을 직접 입력하세요."
    try:
        point = geocode(address, get=get)
        if point is None:
            return [], "주소로 위치를 찾지 못했습니다. 별지 제3호의 주소를 도로명주소로 확인하세요."
        headers = {"Authorization": f"KakaoAK {key}"}
        found: dict[tuple[str, str], Candidate] = {}
        for mode, value, category, subtype in SEARCHES:
            params: dict[str, Any] = {"x": point[0], "y": point[1], "radius": SEARCH_RADIUS_M, "size": 15, "sort": "distance"}
            if mode == "category":
                params["category_group_code"] = value
                url = f"{BASE}/search/category.json"
            else:
                params["query"] = value
                url = f"{BASE}/search/keyword.json"
            for doc in get(url, params, headers).get("documents", []):
                name = str(doc.get("place_name") or "").strip()
                if not name or (name, subtype) in found:
                    continue
                distance = doc.get("distance")
                found[(name, subtype)] = Candidate(
                    name=name, category=category, subtype=subtype,
                    address=str(doc.get("road_address_name") or doc.get("address_name") or ""),
                    distance_m=float(distance) if str(distance or "").strip() else None,
                    source="카카오 로컬 API 검색",
                )
    except (requests.RequestException, KeyError, ValueError) as exc:
        return [], f"주변 검색에 실패했습니다({type(exc).__name__}). 보호대상을 직접 입력하세요."
    ordered = sorted(found.values(), key=lambda c: (c.distance_m is None, c.distance_m or 0.0))
    return ordered, f"{len(ordered)}건을 찾았습니다. 규모 조건(별표 4)과 사업장 경계 기준 거리는 확인이 필요합니다."
