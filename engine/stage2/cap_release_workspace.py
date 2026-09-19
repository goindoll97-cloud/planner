from __future__ import annotations

"""시나리오별 누출공·누출률·누출량 계산에 필요한 입력을 앞 서식에서 모아 cap_release로 계산한다.

연결구·운전압력·운전온도는 별지 제9호, 취급량·성상·비중은 별지 제1호, 분자량은 별지 제6호에서
가져오므로 시나리오마다 다시 묻지 않는다. 추가로 필요한 값은 액위(m)뿐이다.
"""

from dataclasses import dataclass, field
import re
from typing import Any, Mapping

from . import cap_dispersion as disp
from . import cap_endpoints
from . import cap_release as rel
from . import cap_scenario_workspace as sc
from .cap_form9_engine import _pressure_mpa
from .project import Stage2Project

HEAD_COLUMN = "액위(m)"
GAMMA_COLUMN = "비열비"
# 액화가스 2상 유출(P-92 식 6)에 필요한 운전조건 물성. 모두 입력하면 2상 유출식을 쓴다.
LATENT_HEAT_COLUMN = "증발잠열(kcal/kg)"
LIQUID_CP_COLUMN = "액체비열(kcal/kg·℃)"
VAPOR_DENSITY_COLUMN = "증기밀도(kg/m3)"
LEAK_PIPE_COLUMN = "누출지점 배관길이(m)"
FLASH_COLUMNS = (LATENT_HEAT_COLUMN, LIQUID_CP_COLUMN, VAPOR_DENSITY_COLUMN)


def _number(value: object) -> float | None:
    try:
        text = str(value).strip().replace(",", "")
        return float(text) if text else None
    except ValueError:
        return None


def release_for_scenario(project: Stage2Project, scenario: Mapping[str, Any], *,
                         detection: str = "C", isolation: str = "C") -> rel.Release:
    tag = str(scenario.get("대상 설비번호") or "").strip()
    target = next((t for t in sc.evaluate(project) if t.tag == tag), None)
    facility = next((r for r in sc._facility_rows(project) if str(r.get("설비번호") or "").strip() == tag), None)
    problems: list[str] = []
    if target is None or facility is None:
        return rel.Release(0.0, "", None, None, None, "", (f"대상 설비 '{tag}'를 별지 제1호 시설 표에서 찾지 못했습니다.",))
    if target.holding_kg is None:
        problems.append("설비의 최대보유량이 계산되지 않았습니다(별지 제1호).")

    connection = _number(facility.get("최대 연결구 크기(mm)"))
    if connection is None or connection <= 0:
        problems.append("최대 연결구 크기(mm)가 필요합니다(별지 제9호).")
    celsius = _number(facility.get("운전온도"))
    gauge_text = _pressure_mpa(facility.get("운전압력"))
    gauge_mpa = _number(gauge_text)
    if celsius is None:
        problems.append("운전온도가 필요합니다(별지 제9호).")
    if gauge_mpa is None:
        problems.append("운전압력이 필요합니다(별지 제9호).")
    if problems:
        return rel.Release(0.0, "", None, None, None, "", tuple(problems))

    is_lorry = target.kind == sc.LORRY_KIND
    hole = rel.hole_diameter(connection, operating_celsius=celsius, gauge_mpa=gauge_mpa, is_tank_lorry=is_lorry)
    duration = rel.leak_duration_min(detection, isolation)
    state = target.state
    material_row = sc._properties(project).get(target.material, {})

    if state == "고체":
        return rel.Release(hole.diameter_mm, hole.reason, None, None, None, "", ("고체는 누출률 모델이 없습니다.",))
    if state == "기체":
        molar = _number(material_row.get("분자량"))
        if molar is None:
            return rel.Release(hole.diameter_mm, hole.reason, None, None, None, "", ("분자량이 필요합니다(별지 제6호 물성).",))
        gamma = _number(scenario.get(GAMMA_COLUMN)) or rel.DEFAULT_GAMMA
        absolute = rel.ATMOSPHERIC_PA + gauge_mpa * 1.0e6
        rate = rel.gas_release_rate(hole.diameter_mm, absolute, celsius + 273.15, molar, gamma)
        cd = rel.gas_discharge_coefficient(absolute, rel.ATMOSPHERIC_PA, gamma)
        model = f"기체 오리피스 유출(KOSHA GUIDE P-92 식 2·3, Cd {cd:g}, 비열비 {gamma:g}" + (
            "" if _number(scenario.get(GAMMA_COLUMN)) else " 기본값") + ")"
    else:  # 액체, 액화가스의 액상 누출
        gravity = _number(facility.get("비중"))
        head = _number(scenario.get(HEAD_COLUMN))
        if gravity is None:
            return rel.Release(hole.diameter_mm, hole.reason, None, None, None, "", ("비중이 필요합니다(별지 제1호).",))
        if head is None and gauge_mpa <= 0:
            return rel.Release(hole.diameter_mm, hole.reason, None, None, None, "",
                               ("상압 액체는 누출 수두(액위, m)가 필요합니다.",))
        flash = [_number(scenario.get(column)) for column in FLASH_COLUMNS]
        leak_pipe = _number(scenario.get(LEAK_PIPE_COLUMN))
        if state == "기체(액화가스)" and all(value for value in flash) and (leak_pipe is None or leak_pipe >= 0.1):
            latent, cp, rho_g = flash
            rate = rel.equilibrium_flashing_rate(hole.diameter_mm, latent, rho_g, gravity * 1000.0, cp, celsius + 273.15)
            model = "평형 포화액체 2상 유출(KOSHA GUIDE P-92 식 6)"
        else:
            rate = rel.liquid_release_rate(hole.diameter_mm, gravity * 1000.0, gauge_mpa * 1.0e6, head or 0.0)
            model = f"액상 오리피스 유출(P-92 식 4, Cd {rel.CD_LIQUID:g})"
            if state == "기체(액화가스)":
                model += ". 2상 유출로 계산하려면 증발잠열·액체비열·증기밀도를 입력하세요(플래시 증발 미반영)"
    amount = rel.release_amount_kg(rate, duration, target.holding_kg)
    return rel.Release(hole.diameter_mm, hole.reason, rate, float(duration), amount, model)


# ---------------------------------------------------------------------------
# 독성 누출 피해반경 (끝점농도 도달거리)
# ---------------------------------------------------------------------------

BOUNDARY_COLUMN = "경계까지 거리(m)"
DIKE_KEY = "cap.safety.dike_calculation"
INDUSTRIAL_KEY = "cap.business.industrial_complex"


@dataclass(frozen=True)
class ToxicEffect:
    radius_m: float | None
    off_site_m: float | None
    endpoint_basis: str
    source: str
    source_rate_kg_s: float | None
    weather: str
    problems: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)


def default_terrain(project: Stage2Project) -> str:
    """지침 2-6: 산업단지 안이면 도시지형, 아니면 전원(평탄) 지형으로 본다."""
    record = project.get_field(INDUSTRIAL_KEY)
    value = "" if record is None or record.value is None else str(record.value).strip()
    return disp.URBAN if value and "해당" not in value and value not in ("-", "없음", "아니오") else disp.RURAL


def default_weather(project: Stage2Project, worst_case: bool = False) -> disp.Weather:
    if worst_case:
        return disp.Weather(disp.WORST_WIND_MS, disp.WORST_STABILITY, default_terrain(project), disp.WORST_CASE.label)
    return disp.Weather(disp.DEFAULT_WIND_MS, disp.DEFAULT_STABILITY, default_terrain(project))


def _vapor_pressure_mmhg(text: object) -> float | None:
    raw = str(text or "").strip().lower().replace(",", "")
    found = re.search(r"-?\d+(?:\.\d+)?", raw)
    if not found:
        return None
    value = float(found.group(0))
    if "kpa" in raw:
        return value * 7.50062
    if re.search(r"\bpa\b", raw):
        return value * 0.00750062
    if "bar" in raw:
        return value * 750.062
    return value  # mmHg


def _dike_area_m2(project: Stage2Project, tag: str) -> float | None:
    record = project.get_field(DIKE_KEY)
    if record is None or not isinstance(record.value, list):
        return None
    for row in record.value:
        if isinstance(row, Mapping) and str(row.get("대상 설비번호") or "").strip() == tag and str(row.get("적용여부") or "") == "예":
            length, width = _number(row.get("내부 길이(m)")), _number(row.get("내부 폭(m)"))
            if length and width:
                return length * width
    return None


def toxic_effect_for_scenario(project: Stage2Project, scenario: Mapping[str, Any], *, weather: disp.Weather | None = None,
                              detection: str = "C", isolation: str = "C") -> ToxicEffect:
    weather = weather or default_weather(project)
    release = release_for_scenario(project, scenario, detection=detection, isolation=isolation)
    if release.rate_kg_s is None:
        return ToxicEffect(None, None, "", "", None, weather.label, release.problems)
    tag = str(scenario.get("대상 설비번호") or "").strip()
    target = next(t for t in sc.evaluate(project) if t.tag == tag)
    facility = next(r for r in sc._facility_rows(project) if str(r.get("설비번호") or "").strip() == tag)
    material = sc._properties(project).get(target.material, {})
    cas = str(material.get("CAS 번호") or material.get("CAS No.") or "").strip()
    molar = _number(material.get("분자량"))
    problems: list[str] = []
    notes = [f"기상: {weather.label}, {weather.terrain}지형 (Briggs 확산계수)",
             "지표 연속 누출 가우시안 플룸. 중가스 효과·건물 후류·유한 시간 누출은 반영하지 않음"]

    endpoint = cap_endpoints.endpoint_for(cas) if cas else None
    if endpoint is None:
        problems.append("끝점농도 표(기술지침 붙임 1)에 없는 물질입니다. IDLH 대체값(LC50 등)을 확인해야 합니다.")
        return ToxicEffect(None, None, "", "", None, weather.label, tuple(problems), tuple(notes))
    if endpoint.unit == "ppm":
        if molar is None:
            problems.append("ppm 끝점농도를 mg/m3로 바꾸려면 분자량이 필요합니다(별지 제6호).")
            return ToxicEffect(None, None, endpoint.basis, "", None, weather.label, tuple(problems), tuple(notes))
        endpoint_kg_m3 = disp.ppm_to_kg_m3(endpoint.endpoint_value, molar)
    else:
        endpoint_kg_m3 = disp.mg_m3_to_kg_m3(endpoint.endpoint_value)
    if molar is not None and molar > 1.2 * 28.97:
        notes.append("공기보다 무거운 물질입니다. 중가스 확산 효과가 반영되지 않아 실제 거리와 차이가 있을 수 있습니다.")

    if target.state in ("기체", "기체(액화가스)"):
        source_rate = release.rate_kg_s
        source = "기체 상태 누출 전량 확산(지침 3-2 ② 1)"
    else:
        vapor = _vapor_pressure_mmhg(material.get("증기압"))
        gravity = _number(facility.get("비중"))
        if vapor is None or molar is None:
            problems.append("액체 풀 증발 계산에는 증기압(별지 제6호)과 분자량이 필요합니다.")
            return ToxicEffect(None, None, endpoint.basis, "", None, weather.label, tuple(problems), tuple(notes))
        celsius = _number(facility.get("운전온도"))
        area = disp.pool_area_m2(release.amount_kg, gravity, _dike_area_m2(project, tag))
        evaporation = disp.evaporation_rate_kg_min(weather.wind_ms, molar, area, vapor, (celsius if celsius is not None else 25.0) + 273.15) / 60.0
        source_rate = min(evaporation, release.amount_kg / (10 * 60.0))
        source = f"액체 풀 증발(면적 {area:.1f} m2, 지침 붙임 4)"
    radius = disp.distance_to_endpoint(source_rate, endpoint_kg_m3, wind_ms=weather.wind_ms,
                                       stability=weather.stability, terrain=weather.terrain)
    boundary = _number(scenario.get(BOUNDARY_COLUMN))
    off_site = None
    if boundary is None:
        problems.append("설비에서 사업장 경계까지 거리(m)가 있어야 장외거리를 구할 수 있습니다.")
    else:
        off_site = max(0.0, radius - boundary)
    return ToxicEffect(radius, off_site, endpoint.basis, source, source_rate, weather.label, tuple(problems), tuple(notes))
