"""SGIS-derived population figures for CAP statutory *drafts*.

Uses the official SGIS Data API: token, userarea.geojson (UTM-K),
2024 population and company statistics. Figures are computed from overlap of
an accident-origin circle with administrative-dong polygons. These are
area-weighted census *estimates*, not surveyed individual building occupants.
The calculated draft facts carry a source/year/method and remain auditable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

import requests
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import unary_union

from . import cap_impact_workspace as impact_workspace
from . import cap_scenario_workspace as scenario_workspace
from .project import Stage2Project

BASE = "https://sgisapi.mods.go.kr/OpenAPI3"
RESULT_KEY = "cap.offsite.sgis_population_assessment"
DEFAULT_YEAR = "2024"
MAX_RADIUS_M = 10000.0
METHOD = (
    "SGIS 행정동별 인구·전국사업체 종사자(제조업 C 별도)를 사고원점 원형 영향범위와 "
    "면적 비율로 배분. 거주민=총인구+비제조업 종사자(중복 가능), "
    "근로자=제조업 종사자(기타 산업시설 근로자 누락 가능). "
    "실제 현장 상주 인원이 아닌 법정서식 초안용 자동 추정치."
)


class SGISPopulationError(ValueError):
    """A failed or incomplete SGIS estimate must never become a verified zero."""


def _setting(key: str) -> str:
    if os.environ.get(key):
        return str(os.environ[key]).strip()
    # Keep the same project-root .env convention as the existing location APIs.
    for path in (Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"):
        try:
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                name, sep, value = line.partition("=")
                if sep and name.strip() == key:
                    return value.strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def configured() -> bool:
    return bool(_setting("SGIS_CONSUMER_KEY") and _setting("SGIS_CONSUMER_SECRET"))


def census_year() -> str:
    value = _setting("SGIS_CENSUS_YEAR") or DEFAULT_YEAR
    if not value.isdigit() or not 2015 <= int(value) <= 2024:
        raise SGISPopulationError("SGIS_CENSUS_YEAR는 공식 제공 연도(2015~2024)로 설정해 주세요.")
    return value


class SGISClient:
    def __init__(self, *, get=None):
        self.get = get or requests.get
        self._token: str | None = None
        self._cached: dict[tuple, Any] = {}

    def _request(self, endpoint: str, **params: Any) -> dict:
        try:
            response = self.get(BASE + endpoint, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError, TypeError) as exc:
            raise SGISPopulationError(f"SGIS 자료를 조회하지 못했습니다({endpoint}, {type(exc).__name__}).") from None
        if not isinstance(data, dict) or str(data.get("errCd", "")) != "0":
            # Never print request parameters, consumer secrets or access tokens.
            raise SGISPopulationError(f"SGIS 응답이 유효하지 않습니다({endpoint}, 오류코드 {data.get('errCd', '형식') if isinstance(data, dict) else '형식'}).")
        return data

    def token(self) -> str:
        if self._token is None:
            if not configured():
                raise SGISPopulationError("SGIS_CONSUMER_KEY와 SGIS_CONSUMER_SECRET을 .env에 설정해 주세요.")
            data = self._request(
                "/auth/authentication.json",
                consumer_key=_setting("SGIS_CONSUMER_KEY"),
                consumer_secret=_setting("SGIS_CONSUMER_SECRET"),
            )
            token = (data.get("result") or {}).get("accessToken")
            if not isinstance(token, str) or not token.strip():
                raise SGISPopulationError("SGIS 인증 응답에 AccessToken이 없습니다.")
            self._token = token
        return self._token

    def records(self, endpoint: str, **params: Any) -> list[dict]:
        cache_key = (endpoint, tuple(sorted(params.items())))
        if cache_key not in self._cached:
            payload = self._request(endpoint, accessToken=self.token(), **params)
            records = payload.get("result")
            if not isinstance(records, list):
                raise SGISPopulationError(f"SGIS 통계 응답의 목록이 없습니다({endpoint}).")
            self._cached[cache_key] = records
        return self._cached[cache_key]

    def administrative_areas(self, extent) -> list[dict]:
        minx, miny, maxx, maxy = extent.bounds
        payload = self._request(
            "/boundary/userarea.geojson",
            accessToken=self.token(), minx=minx, miny=miny, maxx=maxx, maxy=maxy, cd=3,
        )
        records = payload.get("features")
        if not isinstance(records, list) or not records:
            raise SGISPopulationError("사고 영향범위의 행정동 경계를 찾지 못했습니다.")
        return records

    def _stat(self, endpoint: str, adm_cd: str, year: str, field: str, **options: Any) -> int:
        records = self.records(endpoint, year=year, adm_cd=adm_cd, low_search=0, **options)
        match = next((r for r in records if str(r.get("adm_cd", "")) == adm_cd), None)
        if match is None:
            raise SGISPopulationError(f"{adm_cd}의 {year}년 통계가 없어 추정값을 확정할 수 없습니다.")
        value = match.get(field)
        try:
            numeric = float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            raise SGISPopulationError(f"{adm_cd}의 {field} 자료가 누락·비공개되어 있습니다.") from None
        if not math.isfinite(numeric) or numeric < 0 or not numeric.is_integer():
            raise SGISPopulationError(f"{adm_cd}의 {field} 값이 유효하지 않습니다.")
        return int(numeric)

    def counts(self, adm_cd: str, year: str) -> tuple[int, int, int]:
        residents = self._stat("/stats/population.json", adm_cd, year, "tot_ppltn")
        all_workers = self._stat("/stats/company.json", adm_cd, year, "tot_worker")
        manufacture = self._stat("/stats/company.json", adm_cd, year, "tot_worker", class_code="C")
        if manufacture > all_workers:
            raise SGISPopulationError(f"{adm_cd}의 제조업 종사자수가 전체 종사자수보다 큽니다.")
        return residents, all_workers, manufacture


@dataclass(frozen=True)
class Circle:
    name: str
    x: float
    y: float
    radius: float

    @property
    def geometry(self):
        return Point(self.x, self.y).buffer(self.radius, resolution=48)


def _parse_origin(raw: object) -> tuple[float, float]:
    try:
        first, second = (float(x.strip()) for x in str(raw).strip().split(","))
    except (ValueError, AttributeError):
        raise SGISPopulationError("사고원점 WGS84 위도·경도가 없습니다.") from None
    lat, lon = (first, second) if abs(first) <= 90 else (second, first)
    if not (33 <= lat <= 39 and 124 <= lon <= 132):
        raise SGISPopulationError("사고원점이 대한민국 WGS84 좌표가 아닙니다.")
    return lon, lat


def circles_for(project: Stage2Project, impacts) -> list[Circle]:
    scenarios = {
        str(row.get("사고시나리오명") or ""): row
        for row in scenario_workspace.saved_scenarios(project)
    }
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    circles = []
    for item in impacts:
        if not item.is_off_site:
            continue
        if not item.radius_m or not math.isfinite(item.radius_m) or not (0 < item.radius_m <= MAX_RADIUS_M):
            raise SGISPopulationError(f"{item.name}: 유효한 사고 영향반경(0~10,000m)이 없습니다.")
        coords = scenarios.get(item.name, {}).get("사고원점 좌표")
        lon, lat = _parse_origin(coords)
        x, y = transformer.transform(lon, lat)
        circles.append(Circle(item.name, x, y, float(item.radius_m)))
    return circles


def _fingerprint(circles: list[Circle], year: str) -> str:
    compact = sorted((c.name, round(c.x, 3), round(c.y, 3), round(c.radius, 3)) for c in circles)
    return sha256(json.dumps([year, compact], separators=(",", ":")).encode()).hexdigest()


def _estimate_geometry(geom, areas: list[tuple[Any, int, int, int]]) -> tuple[int, int, int, float]:
    all_shapes = unary_union([area for area, *_ in areas])
    coverage = min(1.0, float(geom.intersection(all_shapes).area) / geom.area)
    # When the API omits neighboring dongs, never mistake partial coverage as 0 inhabitants.
    if coverage < 0.995:
        raise SGISPopulationError(f"행정동 경계가 영향범위의 {coverage:.1%}만 덮어 인원 자동 산정을 중단합니다.")
    living, employee, manufacturing = 0.0, 0.0, 0.0
    for area, population, total_workers, factory_workers in areas:
        portion = area.intersection(geom).area / area.area
        living += population * portion
        employee += total_workers * portion
        manufacturing += factory_workers * portion
    # Statistical approximation: non-manufacturing employees are considered
    # resident-class proxies for the current CAP definition, NOT observed people.
    residents = math.floor(living + employee - manufacturing + 0.5)
    workers = math.floor(manufacturing + 0.5)
    return residents, workers, math.floor(living + 0.5), coverage


def estimate(project: Stage2Project, impacts, *, client: SGISClient | None = None) -> dict:
    circles = circles_for(project, impacts)
    if not circles:
        raise SGISPopulationError("장외 영향범위와 실제 사고원점이 확인된 시나리오가 없습니다.")
    year = census_year()
    client = client or SGISClient()
    overall_shape = unary_union([circle.geometry for circle in circles])
    features = client.administrative_areas(overall_shape)
    areas = []
    seen: set[str] = set()
    for feature in features:
        props = feature.get("properties") or {}
        code = str(props.get("adm_cd") or "").strip()
        if len(code) != 8 or not code.isdigit():
            raise SGISPopulationError("SGIS 행정동 경계 코드 형식이 잘못되었습니다.")
        if code in seen:
            continue
        seen.add(code)
        geo = shape(feature.get("geometry"))
        if geo.is_empty or not geo.is_valid or geo.area <= 0 or not geo.intersects(overall_shape):
            continue
        minx, miny, maxx, maxy = geo.bounds
        if not (500000 < minx < 1700000 and 900000 < miny < 2700000):
            raise SGISPopulationError("행정동 경계 좌표가 미터 단위 UTM-K가 아닙니다.")
        population, workers, factory = client.counts(code, year)
        areas.append((geo, population, workers, factory))
    if not areas:
        raise SGISPopulationError("통계를 연결할 수 있는 행정동이 없습니다.")
    estimates = {}
    for circle in circles:
        residents, workers, direct_population, coverage = _estimate_geometry(circle.geometry, areas)
        estimates[circle.name] = {
            "거주민수": residents, "근로자수": workers,
            "SGIS_주거인구": direct_population,
            "공간자료_포괄률": round(coverage, 5),
            "영향반경(m)": round(circle.radius, 1),
        }
    combined = _estimate_geometry(overall_shape, areas)
    return {
        "fingerprint": _fingerprint(circles, year), "source": "SGIS", "year": year,
        "method": METHOD, "source_urls": [
            BASE + "/boundary/userarea.geojson",
            BASE + "/stats/population.json",
            BASE + "/stats/company.json",
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "administrative_dongs": sorted(seen),
        "scenario": estimates,
        "overall": {"거주민수": combined[0], "근로자수": combined[1],
                    "SGIS_주거인구": combined[2], "공간자료_포괄률": round(combined[3], 5)},
        "status": "통계기반 자동 추정·산정(법정서식 초안 기재; 후속 검증 필요)",
    }


def apply_estimate(project: Stage2Project, impacts, result: Mapping[str, Any]) -> bool:
    """Populate draft-capable numerical fields; never assert external legal approval."""
    if result.get("fingerprint") != _fingerprint(circles_for(project, impacts), str(result.get("year") or "")):
        raise SGISPopulationError("사고원점 또는 영향반경이 변경되어 이전 통계를 적용할 수 없습니다.")
    impact_record = project.get_field(impact_workspace.IMPACT_TABLE_KEY)
    summary_record = project.get_field(impact_workspace.SUMMARY_KEY)
    if (impact_record is None or impact_record.status != "CALCULATED" or
            summary_record is None or summary_record.status != "CALCULATED"):
        raise SGISPopulationError("회사 확인값 또는 외부검증값을 자동 통계로 덮어쓸 수 없습니다.")
    rows = [dict(row) for row in impact_record.value]
    for row in rows:
        values = result["scenario"].get(row.get("사고시나리오명"))
        if values:
            for col in ("거주민수", "근로자수"):
                row[col] = values[col]
            row["인원수 산정근거"] = f"SGIS {result['year']} / 면적가중 행정동 통계 / 후속검증"
    summaries = [dict(row) for row in summary_record.value]
    if summaries:
        for col in ("거주민수", "근로자수"):
            summaries[0]["총괄영향범위 내 " + col] = result["overall"][col]
        summaries[0]["인원수 산정근거"] = f"SGIS {result['year']} / 시나리오 원형영향범위 합집합 / 후속검증"
    project.set_field(impact_workspace.IMPACT_TABLE_KEY, "사고시나리오 영향범위 및 SGIS 자동 산정 인원", rows,
                      "CALCULATED", note=METHOD)
    project.set_field(impact_workspace.SUMMARY_KEY, "총괄영향범위 및 SGIS 자동 산정 인원", summaries,
                      "CALCULATED", note=METHOD)
    return True


def refresh_for_draft(project: Stage2Project, impacts=None, *, client: SGISClient | None = None) -> dict:
    impacts = impacts if impacts is not None else impact_workspace.evaluate(project)
    result = estimate(project, impacts, client=client)
    apply_estimate(project, impacts, result)
    project.set_field(RESULT_KEY, "SGIS 공식통계 기반 인원 자동산정 근거", result, "CALCULATED",
                      note="최신 통계가 아닌 기준연도 값이며 면적가중·근로자 분류 추정. 법적 검증 전 초안.")
    return result
