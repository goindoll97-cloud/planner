from __future__ import annotations

"""PSM 별지 제19호의2(시나리오 및 피해예측 결과)를 CAP에서 입력한 시설·시나리오로 채운다.

새 계산 엔진은 없다. 누출률·증발·확산·화재·폭발은 CAP 작업과 같은 모델을 쓰고, 서식이 요구하는 끝점
(화재 4/12.5/37.5 kW/m2, 폭발 7/21/70 kPa, ERPG 1/2/3)만 psm_endpoints로 바꾼다.
기상 가정은 서식 주석 ①~⑤를 따른다: 최악은 1.5 m/s·F, 대안은 통상 기상(CAP 기본 3 m/s·D), 대기온도·습도는 입력값.
아직 계산하지 않는 항목(인화성 확산 거리, 폭발 21·70 kPa)은 비워 두고 사유를 남긴다(주석 ⑯ 생략 가능).
"""

from dataclasses import dataclass, field
import math
from typing import Any, Mapping

from . import cap_dispersion as disp
from . import cap_fire as fire
from . import cap_release_workspace as crw
from . import cap_scenario_workspace as sc
from . import psm_endpoints as ep
from .project import Stage2Project

TABLE_KEY = "psm.risk.consequence_table"
WORST, ALTERNATIVE = "최악의사고시나리오", "대안의사고시나리오"
WEATHER_INPUTS = ("대기온도(℃)", "습도(%)")
FLAMMABLE_NOTE = "인화성 확산 거리(25% LEL·LEL·UEL)는 아직 계산하지 않습니다."


@dataclass
class Result:
    row: dict[str, str]
    problems: list[str] = field(default_factory=list)
    holds: list[str] = field(default_factory=list)


def _weather(project: Stage2Project, kind: str) -> disp.Weather:
    return crw.default_weather(project, worst_case=(kind == WORST))


def _fmt(value: float | None, digits: int = 0) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def _state_label(state: str) -> str:
    return {"기체": "기체", "액체": "액체", "기체(액화가스)": "2상(액체+기체)"}.get(state, "")


def scenario_row(project: Stage2Project, scenario: Mapping[str, Any], kind: str,
                 weather_inputs: Mapping[str, Any] | None = None, endpoints: ep.Endpoints = ep.Endpoints()) -> Result:
    weather_inputs = weather_inputs or {}
    weather = _weather(project, kind)
    release = crw.release_for_scenario(project, scenario)
    result = Result({header: "" for header in _HEADERS})
    row = result.row
    row.update({"시나리오 구분": kind, "풍속(m/s)": f"{weather.wind_ms:g}", "대기안정도(A~F)": weather.stability,
                "대기온도(℃)": str(weather_inputs.get("대기온도(℃)", "") or ""),
                "습도(%)": str(weather_inputs.get("습도(%)", "") or ""),
                "표면거칠기": "도시" if weather.terrain == disp.URBAN else "시골"})
    for missing in WEATHER_INPUTS:
        if not row[missing]:
            result.problems.append(f"{missing}가 필요합니다(서식 주석: 지난 3년 낮 동안 값 또는 통상 값).")
    result.problems.extend(release.problems)
    for problem in ep.Endpoints.problems(endpoints):
        result.problems.append(problem)
    if release.rate_kg_s is None:
        return result

    tag = str(scenario.get("대상 설비번호") or "").strip()
    target = next(t for t in sc.evaluate(project) if t.tag == tag)
    facility = next(r for r in sc._facility_rows(project) if str(r.get("설비번호") or "").strip() == tag)
    material = sc._properties(project).get(target.material, {})
    is_gas = target.state in ("기체", "기체(액화가스)")
    molar = crw._number(material.get("분자량"))
    cas = str(material.get("CAS 번호") or material.get("CAS No.") or "").strip()
    heat = crw._number(material.get(crw.HEAT_COLUMN)) or crw._number(scenario.get(crw.HEAT_COLUMN))
    pressure = crw._pressure_mpa(facility.get("운전압력"))
    row.update({
        "물질명": target.material, "물질의 상태": _state_label(target.state),
        "설비명(또는 배관부위)": str(facility.get("설비명") or facility.get("설비번호") or ""),
        "운전압력(MPa)": str(pressure or ""), "운전온도(℃)": str(facility.get("운전온도") or ""),
        "누출구의 크기(mm2)": _fmt(math.pi / 4 * release.hole_mm ** 2),
        "설비/배관(kg/s)": f"{release.rate_kg_s:.3g}" if is_gas else "",
    })

    pool_area = evaporation_kg_s = None
    if is_gas:
        toxic_source, explosion_mass = release.rate_kg_s, release.amount_kg
    else:
        vapor = crw._vapor_pressure_mmhg(material.get("증기압"))
        gravity = crw._number(facility.get("비중"))
        if vapor is None or molar is None:
            result.problems.append("액체 풀의 증발 계산에는 증기압과 분자량이 필요합니다(별지 제6호).")
            return result
        celsius = crw._number(facility.get("운전온도"))
        pool_area = disp.pool_area_m2(release.amount_kg, gravity, crw._dike_area_m2(project, tag))
        evaporation_kg_min = disp.evaporation_rate_kg_min(weather.wind_ms, molar, pool_area, vapor,
                                                          (celsius if celsius is not None else 25.0) + 273.15)
        evaporation_kg_s = evaporation_kg_min / 60.0
        toxic_source = min(evaporation_kg_s, release.amount_kg / 600.0)
        explosion_mass = min(evaporation_kg_min * 10.0, release.amount_kg)
        row["웅덩이 크기(m2)"] = _fmt(pool_area, 1)
        row["웅덩이(kg/s)"] = f"{evaporation_kg_s:.3g}"

    notes = [f"기상 {weather.label}, {weather.terrain}지형(Briggs). {release.model}"]
    if heat is not None:
        if is_gas:
            fires = ep.fire_distances(kind="jet", endpoints=endpoints, heat_kj_kg=heat, release_rate_kg_s=release.rate_kg_s)
        else:
            boiling, cp, latent = (crw._number(scenario.get(c)) for c in (crw.BOILING_COLUMN, crw.LIQUID_CP_KJ_COLUMN,
                                                                        crw.VAPORIZATION_COLUMN))
            fires = []
            if None in (boiling, cp, latent):
                result.holds.append("풀 화재에는 비점·액체비열·기화열이 필요합니다.")
            else:
                burning = fire.burning_rate_kg_m2_s(heat, cp, boiling, 25.0, latent)
                fires = ep.fire_distances(kind="pool", endpoints=endpoints, heat_kj_kg=heat, pool_area_m2=pool_area,
                                          burning_rate=burning)
        for headers, values in ((("화재-4 kW/m2", "화재-12.5 kW/m2", "화재-37.5 kW/m2"), fires),
                                (("폭발-7 kPa", "폭발-21 kPa", "폭발-70 kPa"),
                                 ep.explosion_distances(explosion_mass, heat, endpoints))):
            for header, distance in zip(headers, values):
                row[header] = _fmt(distance.meters)
                if distance.status == "HOLD":
                    result.holds.append(f"{header}: {distance.note}")
    else:
        result.holds.append("연소열(kJ/kg)이 없어 화재·폭발 거리를 계산하지 않았습니다.")

    if cas:
        for header, distance in zip(("독성-ERPG 1", "독성-ERPG 2", "독성-ERPG 3"),
                                    ep.toxic_distances(cas, toxic_source, wind_ms=weather.wind_ms,
                                                       stability=weather.stability, terrain=weather.terrain,
                                                       molar_mass=molar)):
            row[header] = _fmt(distance.meters)
            if distance.status == "ESTIMATED":
                notes.append(f"{header}: 규정 7(2) 산정 농도 사용")
            if distance.status == "HOLD":
                result.holds.append(f"{header}: {distance.note}")
    result.holds.append(FLAMMABLE_NOTE)
    row["계산모델·결과 근거"] = " / ".join(notes)
    return result


def build(project: Stage2Project, designations: Mapping[str, str], weather_inputs: Mapping[str, Any],
          endpoints: ep.Endpoints = ep.Endpoints()) -> list[Result]:
    """designations: 사고시나리오명 -> 최악/대안. 지정되지 않은 시나리오는 넣지 않는다."""
    out = []
    for scenario in sc.saved_scenarios(project):
        kind = designations.get(str(scenario.get("사고시나리오명") or ""))
        if kind in (WORST, ALTERNATIVE):
            out.append(scenario_row(project, scenario, kind, weather_inputs, endpoints))
    return out


def save(project: Stage2Project, results: list[Result]) -> int:
    rows = [r.row for r in results]
    project.set_field(TABLE_KEY, "시나리오 및 피해예측 결과(별지 제19호의2 작성대)", rows, "CALCULATED",
                      note="CAP 시설·시나리오와 같은 모델로 계산. 기준: 서식 기본 끝점, 독성은 KOSHA C-C-46-2026 표1")
    return len(rows)


_HEADERS = __import__("engine.stage2.psm_form12_consequence_engine", fromlist=["x"]).FORM19_2_HEADERS
