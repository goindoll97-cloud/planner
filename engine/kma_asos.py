from __future__ import annotations

"""기상청 지상(종관, ASOS) 일자료 조회서비스 클라이언트.

공공데이터포털 서비스 AsosDalyInfoService/getWthrDataList(오픈API 활용가이드 v1.0). 인증키는 KOSHA 조회와 같은
KOSHA_MSDS_SERVICE_KEY(.env)를 쓴다. PSM 별지 제19호의2의 '대기온도(지난 3년간 낮 동안 최대 온도)'와 '습도(지난 3년간
평균 습도)' 칸을 관측 자료로 채우는 데 쓴다. 키가 없거나 호출이 실패해도 사용자가 직접 입력하면 되므로 조회 상태만 돌려준다.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
import json
from pathlib import Path
from typing import Any, Callable

import requests

from .kosha_msds import _REQUEST_HEADERS, _api_error_text, _credential, _safe_error

ENDPOINT = "https://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
STATIONS_PATH = Path(__file__).resolve().parents[1] / "data" / "stage2" / "kma" / "asos_stations.json"
PAGE_ROWS = 400
YEARS = 3


@dataclass(frozen=True)
class DailyResult:
    status: str  # OK / NO_DATA / NOT_CONFIGURED / ERROR
    message: str
    rows: tuple[dict[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class WeatherBasis:
    station_id: str
    station_name: str
    period: str
    days: int
    max_temperature_c: float | None
    mean_humidity_pct: float | None
    mean_wind_ms: float | None
    max_temperature_date: str = ""


def stations() -> dict[str, dict[str, str]]:
    return json.loads(STATIONS_PATH.read_text(encoding="utf-8"))["stations"]


def suggest_station(address: str) -> str:
    """주소에 지점 이름(예: 울산, 여수)이 들어 있으면 그 지점을 제안한다. 가장 긴 이름을 우선한다."""
    text = str(address or "")
    matches = [(len(info["name"]), code) for code, info in stations().items()
               if info["name"] and info["name"].rstrip("군시") in text and len(info["name"].rstrip("군시")) >= 2]
    return max(matches)[1] if matches else ""


def _default_get(url: str, params: dict[str, Any]) -> tuple[int, str]:
    response = requests.get(url, params=params, timeout=30, headers=_REQUEST_HEADERS)
    return response.status_code, response.text or ""


def _page(station: str, start: date, end: date, page: int,
          get: Callable[[str, dict[str, Any]], tuple[int, str]], key: str) -> tuple[str, str, list[dict[str, Any]], int]:
    params = {"serviceKey": key, "numOfRows": PAGE_ROWS, "pageNo": page, "dataType": "JSON", "dataCd": "ASOS",
              "dateCd": "DAY", "startDt": start.strftime("%Y%m%d"), "endDt": end.strftime("%Y%m%d"), "stnIds": station}
    status_code, text = get(ENDPOINT, params)
    api_error = _api_error_text(text)
    if api_error:
        return "ERROR", api_error, [], 0
    if status_code != 200:
        return "ERROR", f"HTTP {status_code}", [], 0
    root = json.loads(text).get("response", {})
    header, body = root.get("header") or {}, root.get("body") or {}
    code = str(header.get("resultCode", "00")).zfill(2)
    if code == "03":
        return "NO_DATA", "그 기간의 관측 자료가 없습니다.", [], 0
    if code != "00":
        return "ERROR", f"조회 실패({code}): {header.get('resultMsg', '')}".strip(), [], 0
    items = (body.get("items") or {}).get("item") or []
    if isinstance(items, dict):
        items = [items]
    return "OK", "", [dict(i) for i in items if isinstance(i, dict)], int(body.get("totalCount") or 0)


def fetch_daily(station: str, start: date, end: date,
                get: Callable[[str, dict[str, Any]], tuple[int, str]] = _default_get) -> DailyResult:
    key = _credential()
    if not key:
        return DailyResult("NOT_CONFIGURED", ".env에 KOSHA_MSDS_SERVICE_KEY가 없어 기상청 조회를 하지 않았습니다. 직접 입력하세요.")
    rows: list[dict[str, Any]] = []
    try:
        page = 1
        while True:
            status, message, items, total = _page(station, start, end, page, get, key)
            if status != "OK":
                return DailyResult(status, message) if not rows else DailyResult("ERROR", f"{message} (일부만 받음)")
            rows.extend(items)
            if not items or len(rows) >= total or page >= 10:
                break
            page += 1
    except (requests.RequestException, ValueError) as exc:
        return DailyResult("ERROR", _safe_error(exc, key))
    return DailyResult("OK", "", tuple(rows)) if rows else DailyResult("NO_DATA", "그 기간의 관측 자료가 없습니다.")


def _number(value: object) -> float | None:
    try:
        text = str(value).strip()
        return float(text) if text else None
    except ValueError:
        return None


def summarize(rows: tuple[dict[str, Any], ...] | list[dict[str, Any]], station: str, period: str = "") -> WeatherBasis:
    """일자료를 서식이 요구하는 값으로 요약한다. 결측은 건너뛰고 일수는 실제로 쓴 날만 센다."""
    temps = [(t, str(r.get("tm") or "")) for r in rows if (t := _number(r.get("maxTa"))) is not None]
    humidity = [h for r in rows if (h := _number(r.get("avgRhm"))) is not None]
    wind = [w for r in rows if (w := _number(r.get("avgWs"))) is not None]
    hottest = max(temps) if temps else (None, "")
    return WeatherBasis(
        station_id=station, station_name=stations().get(station, {}).get("name", ""), period=period, days=len(rows),
        max_temperature_c=hottest[0], max_temperature_date=hottest[1],
        mean_humidity_pct=round(sum(humidity) / len(humidity), 1) if humidity else None,
        mean_wind_ms=round(sum(wind) / len(wind), 2) if wind else None,
    )


def three_year_basis(station: str, today: date | None = None,
                     get: Callable[[str, dict[str, Any]], tuple[int, str]] = _default_get) -> tuple[WeatherBasis | None, DailyResult]:
    """어제까지 지난 3년의 관측으로 대기온도·습도 기준값을 만든다."""
    end = (today or date.today()) - timedelta(days=1)
    try:
        start = date(end.year - YEARS, end.month, end.day) + timedelta(days=1)
    except ValueError:  # 2월 29일
        start = date(end.year - YEARS, end.month, 28) + timedelta(days=1)
    result = fetch_daily(station, start, end, get=get)
    if result.status != "OK":
        return None, result
    return summarize(result.rows, station, f"{start.isoformat()} ~ {end.isoformat()}"), result
