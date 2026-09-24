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
    """환경변수 또는 프로젝트 루트 .env의 KAKAO_REST_API_KEY. 다른 조회(KOSHA)가 먼저 실행되지 않아도 .env를 읽는다."""
    from ..kosha_msds import _load_local_env

    _load_local_env()
    return os.environ.get(ENV_KEY, "").strip()


def _default_get(url: str, params: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    response = requests.get(url, params=params, headers=headers, timeout=15)
    response.raise_for_status()
    return response.json()


def _http_error_hint(exc: requests.HTTPError) -> str:
    """Explain common Kakao Local API HTTP failures without exposing request headers or keys."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    try:
        kakao_code = (response.json() or {}).get("code")
        kakao_code = int(kakao_code) if kakao_code is not None else None
    except (AttributeError, TypeError, ValueError, requests.RequestException):
        kakao_code = None
    code_hints = {
        -3: "앱 설정에서 이 API의 사용 또는 호출 허용이 활성화되어 있는지 확인해 주세요.",
        -5: "이 앱에 해당 API를 호출할 권한이 있는지 카카오 디벨로퍼스에서 확인해 주세요.",
        -12: "카카오 디벨로퍼스 앱 또는 개발자 계정의 이용 제한 여부를 확인해 주세요.",
    }
    if kakao_code in code_hints:
        return f"카카오 오류 코드 {kakao_code}: {code_hints[kakao_code]}"
    hints = {
        400: "요청 형식이나 검색 조건을 확인해 주세요.",
        401: "KAKAO_REST_API_KEY가 유효한 REST API 키인지, 키가 바뀌지 않았는지 확인해 주세요.",
        403: "카카오 디벨로퍼스 앱에서 로컬 API 사용 권한과 앱 설정을 확인해 주세요.",
        429: "카카오 API 호출 한도에 도달했을 수 있습니다. 잠시 뒤 다시 시도해 주세요.",
    }
    if status in hints:
        return f"카카오 API가 HTTP {status}로 요청을 거부했습니다. {hints[status]}"
    if status is not None:
        return f"카카오 API가 HTTP {status} 오류를 반환했습니다. 응답 세부 코드를 확인할 수 없었습니다."
    return "카카오 API가 요청을 거부했습니다."


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
    except requests.HTTPError as exc:
        return [], f"주변 검색에 실패했습니다. {_http_error_hint(exc)} 보호대상을 직접 입력하세요."
    except (requests.RequestException, KeyError, ValueError) as exc:
        return [], f"주변 검색에 실패했습니다({type(exc).__name__}). 보호대상을 직접 입력하세요."
    ordered = sorted(found.values(), key=lambda c: (c.distance_m is None, c.distance_m or 0.0))
    return ordered, f"{len(ordered)}건을 찾았습니다. 규모 조건(별표 4)과 사업장 경계 기준 거리는 확인이 필요합니다."


def env_diagnosis() -> list[str]:
    """키를 못 찾을 때 원인을 사용자가 스스로 확인하도록, 프로그램이 어디를 어떻게 봤는지 알려 준다(키 값은 절대 내보내지 않는다)."""
    from pathlib import Path

    from ..kosha_msds import PROJECT_ROOT

    lines: list[str] = []
    variable = os.environ.get(ENV_KEY)
    lines.append("환경변수 " + (f"{ENV_KEY}: 값이 있음" if variable and variable.strip() else
                              f"{ENV_KEY}: 비어 있음" if variable is not None else f"{ENV_KEY}: 설정되어 있지 않음"))
    seen: set[str] = set()
    for folder in (PROJECT_ROOT, Path.cwd()):
        folder = folder.resolve()
        if str(folder) in seen:
            continue
        seen.add(str(folder))
        path = folder / ".env"
        if not path.exists():
            lines.append(f"{path}: 파일이 없습니다")
            similar = sorted(p.name for p in folder.glob(".env*") if p.name != ".env")
            if similar:
                lines.append(f"  같은 폴더에 비슷한 이름의 파일이 있습니다: {', '.join(similar)} — 파일 이름이 정확히 .env 인지 확인하세요"
                             "(메모장이 .env.txt로 저장하는 경우가 많습니다)")
            continue
        try:
            text = path.read_text(encoding="utf-8-sig", errors="ignore")
        except OSError as exc:
            lines.append(f"{path}: 읽을 수 없습니다({type(exc).__name__})")
            continue
        names = []
        exact_value = False
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if "KAKAO" in key.upper():
                names.append(key)
            if key == ENV_KEY and value:
                exact_value = True
        if exact_value:
            lines.append(f"{path}: 파일을 찾았고 {ENV_KEY} 값도 있습니다(프로그램을 다시 실행했는지 확인하세요)")
        elif names:
            lines.append(f"{path}: 파일은 있지만 정확한 이름 {ENV_KEY}의 값이 없습니다. 파일에 있는 KAKAO 관련 이름: {', '.join(names)}")
        else:
            lines.append(f"{path}: 파일은 있지만 {ENV_KEY} 줄이 없습니다(줄 시작에 #이 붙어 있지 않은지, 이름 철자가 맞는지 확인하세요)")
    return lines
