from __future__ import annotations

"""한국산업안전보건공단 기술지원규정(KOSHA GUIDE) 조회서비스 클라이언트.

공공데이터포털 15144147, 서비스 URL https://apis.data.go.kr/B552468/koshaguide/getKoshaGuide
(오픈API 활용가이드 v1.0). 인증키는 KOSHA MSDS 조회와 같은 KOSHA_MSDS_SERVICE_KEY(.env)를 쓴다.
규정명·번호·공표일자·원문 다운로드 링크만 알려 주는 목록 서비스이며, 키가 없거나 호출이
실패해도 계산에는 영향을 주지 않는다(조회 상태만 돌려준다).
"""

from dataclasses import dataclass, field
import re
from typing import Any, Callable

import requests

from .kosha_msds import _REQUEST_HEADERS, _api_error_text, _credential, _safe_error

ENDPOINT = "https://apis.data.go.kr/B552468/koshaguide/getKoshaGuide"
CALL_API_ID = "1050"  # 가이드: 필수 고정값


@dataclass(frozen=True)
class GuideItem:
    name: str
    number: str        # 예: P-92-2023
    announced: str     # 예: 2023-08-24
    download_url: str

    @property
    def year(self) -> int | None:
        found = re.search(r"-(\d{4})$", self.number)
        return int(found.group(1)) if found else None

    @property
    def base_number(self) -> str:
        return re.sub(r"-\d{4}$", "", self.number)


@dataclass(frozen=True)
class GuideSearch:
    status: str        # OK / NO_DATA / NOT_CONFIGURED / ERROR
    message: str
    total: int = 0
    items: tuple[GuideItem, ...] = field(default_factory=tuple)


def _default_get(url: str, params: dict[str, Any]) -> tuple[int, str]:
    response = requests.get(url, params=params, timeout=15, headers=_REQUEST_HEADERS)
    return response.status_code, response.text or ""


def _parse(payload: dict[str, Any]) -> GuideSearch:
    root = payload.get("response", payload)
    header, body = root.get("header") or {}, root.get("body") or {}
    code = str(header.get("resultCode", "00"))
    if code == "03":
        return GuideSearch("NO_DATA", "조건에 맞는 기술지원규정이 없습니다.")
    if code != "00":
        return GuideSearch("ERROR", f"조회 실패({code}): {header.get('resultMsg', '')}".strip())
    raw = (body.get("items") or {})
    items = raw.get("item", []) if isinstance(raw, dict) else []
    if isinstance(items, dict):
        items = [items]
    parsed = tuple(
        GuideItem(str(i.get("techGdlnNm", "")).strip(), str(i.get("techGdlnNo", "")).strip(),
                  str(i.get("techGdlnOfancYmd", "")).strip(), str(i.get("fileDownloadUrl", "")).strip())
        for i in items if isinstance(i, dict)
    )
    total = int(body.get("totalCount") or len(parsed))
    if not parsed:
        return GuideSearch("NO_DATA", "조건에 맞는 기술지원규정이 없습니다.", total)
    return GuideSearch("OK", f"{total}건 중 {len(parsed)}건을 조회했습니다.", total, parsed)


def search_guides(*, name: str = "", number: str = "", announced: str = "", page: int = 1, rows: int = 20,
                  get: Callable[[str, dict[str, Any]], tuple[int, str]] = _default_get) -> GuideSearch:
    """명칭·번호·공표일자(YYYYMMDD)로 검색한다. 키가 없으면 호출하지 않는다."""
    key = _credential()
    if not key:
        return GuideSearch("NOT_CONFIGURED", ".env에 KOSHA_MSDS_SERVICE_KEY가 없어 코샤가이드 조회를 하지 않았습니다.")
    params: dict[str, Any] = {"serviceKey": key, "pageNo": page, "numOfRows": rows, "callApiId": CALL_API_ID}
    if name:
        params["techGdlnNm"] = name
    if number:
        params["techGdlnNo"] = number
    if announced:
        params["ofancYmd"] = announced
    try:
        status_code, text = get(ENDPOINT, params)
        api_error = _api_error_text(text)
        if api_error:
            return GuideSearch("ERROR", api_error)
        if status_code != 200:
            return GuideSearch("ERROR", f"HTTP {status_code}")
        import json

        return _parse(json.loads(text))
    except (requests.RequestException, ValueError) as exc:
        return GuideSearch("ERROR", _safe_error(exc, key))


def latest_version(base_number: str, *, get: Callable[[str, dict[str, Any]], tuple[int, str]] = _default_get) -> tuple[GuideItem | None, GuideSearch]:
    """예: 'P-92' → 공표연도가 가장 큰 P-92-YYYY 항목(없으면 None)과 조회 결과."""
    result = search_guides(number=base_number, rows=50, get=get)
    if result.status != "OK":
        return None, result
    matches = [i for i in result.items if i.base_number.upper() == base_number.upper() and i.year]
    return (max(matches, key=lambda i: i.year) if matches else None), result
