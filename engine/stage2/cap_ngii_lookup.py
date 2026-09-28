"""NGII National Geographic Information Platform keyword POI candidates.

The published search API has keyword pagination but no spatial search parameter.
Geocode the site using the same provider (EPSG:5179) and filter returned POIs
by address-point distance. A limited keyword search is never an area survey.
"""

from __future__ import annotations

import math
import os
from typing import Any, Callable

import requests

from .cap_site_lookup import Candidate, SEARCH_RADIUS_M

ENDPOINT = "https://map.ngii.go.kr/openapi/search.json"
ENV_KEY = "NGII_API_KEY"
REFERRER_KEY = "NGII_REFERRER_URL"
PAGE_SIZE = 20
MAX_PAGES = 3
MAX_KEYWORDS = 5


def config() -> tuple[str, str]:
    from ..kosha_msds import _load_local_env

    _load_local_env()
    return os.environ.get(ENV_KEY, "").strip(), os.environ.get(REFERRER_KEY, "").strip()


def _get(params: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(ENDPOINT, params=params, timeout=12)
    response.raise_for_status()
    return response.json()


def _body(payload: dict[str, Any], target: str) -> tuple[dict[str, Any], dict[str, Any]]:
    body = payload.get("search")
    if not isinstance(body, dict) or not isinstance(body.get("header"), dict):
        raise ValueError("국토정보플랫폼 응답 형식을 확인할 수 없습니다.")
    header = body["header"]
    if str(header.get("responseCode")) not in ("0", "100") or header.get("target") != target:
        # Never print responseMessage: a provider error may contain request credentials.
        raise ValueError("국토정보플랫폼 인증키·등록 주소 또는 검색 응답을 확인하세요.")
    contents = body.get("contents") or {}
    if not isinstance(contents, dict):
        raise ValueError("국토정보플랫폼 검색 결과 형식을 확인할 수 없습니다.")
    return header, contents


def search(address: str, keywords: list[str], *, get: Callable = _get) -> tuple[list[Candidate], list[str]]:
    key, referrer = config()
    if not key or not referrer:
        return [], [f"국토정보플랫폼 검색을 사용하려면 .env에 {ENV_KEY}와 {REFERRER_KEY}(인증키 발급 시 등록한 주소)를 설정하세요."]
    terms = list(dict.fromkeys(term.strip() for term in keywords if term and term.strip()))[:MAX_KEYWORDS]
    if not terms:
        return [], ["국토정보플랫폼은 반경 검색을 제공하지 않습니다. 장소명을 입력하면 해당 검색 결과의 800m 이내 좌표만 확인합니다."]
    try:
        _, contents = _body(get({"target": "geo", "juso": address, "apikey": key,
                                 "refrnUrl": referrer}), "geo")
        geo = contents.get("geo") or {}
        x, y = float(geo["x"]), float(geo["y"])
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError("국토정보플랫폼 주소 좌표가 유효하지 않습니다.")
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        return [], [f"국토정보플랫폼 주소 검색 실패({type(exc).__name__}); 주소·키·등록 주소를 확인하세요."]
    found: dict[tuple[str, str, str], Candidate] = {}
    notices: list[str] = []
    for term in terms:
        for page in range(1, MAX_PAGES + 1):
            try:
                header, contents = _body(get({"target": "poi", "keyword": term,
                                             "onePageRows": PAGE_SIZE, "currentPage": page,
                                             "apikey": key, "refrnUrl": referrer}), "poi")
                records = contents.get("poi") or []
                if isinstance(records, dict):
                    records = [records]
                if not isinstance(records, list):
                    raise ValueError("국토정보플랫폼 관심지점 형식을 확인할 수 없습니다.")
                count = int(header.get("totalCount") or 0)
            except (requests.RequestException, ValueError, TypeError) as exc:
                notices.append(f"국토정보플랫폼 '{term}' 검색 실패({type(exc).__name__}); 이 검색어의 결과는 누락될 수 있습니다.")
                break
            for item in records:
                if not isinstance(item, dict):
                    continue
                try:
                    name = str(item.get("name") or "").strip()
                    px, py = float(item["x"]), float(item["y"])
                    if not name or not (math.isfinite(px) and math.isfinite(py)):
                        continue
                    distance = math.hypot(px - x, py - y)
                    if distance > SEARCH_RADIUS_M:
                        continue
                    address_text = str(item.get("roadAdres") or item.get("jibunAdres") or "").strip()
                    type_name = str(item.get("typeName") or "").strip()
                    found[(name, str(px), str(py))] = Candidate(
                        name=name, category="", subtype="",
                        address=f"{address_text} · 지도 분류: {type_name}" if type_name else address_text,
                        distance_m=round(distance, 1),
                        source="국토정보플랫폼 검색 API · 국가관심지점정보(POI) (법정 분류 미확인)",
                    )
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
            if page * PAGE_SIZE >= count or not records:
                break
        else:
            notices.append(f"국토정보플랫폼 '{term}' 검색은 {MAX_PAGES * PAGE_SIZE}건까지만 확인했습니다. 다른 페이지에 근처 장소가 있을 수 있습니다.")
    notices.insert(0, f"국토정보플랫폼 장소명 검색 {len(terms)}개에서 주소점 800m 이내 POI {len(found)}건을 찾았습니다. 키워드 검색이므로 주변 전체 조사 결과가 아닙니다.")
    return sorted(found.values(), key=lambda c: c.distance_m or 0), notices
