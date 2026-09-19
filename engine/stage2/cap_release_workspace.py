from __future__ import annotations

"""시나리오별 누출공·누출률·누출량 계산에 필요한 입력을 앞 서식에서 모아 cap_release로 계산한다.

연결구·운전압력·운전온도는 별지 제9호, 취급량·성상·비중은 별지 제1호, 분자량은 별지 제6호에서
가져오므로 시나리오마다 다시 묻지 않는다. 추가로 필요한 값은 액위(m)뿐이다.
"""

from typing import Any, Mapping

from . import cap_release as rel
from . import cap_scenario_workspace as sc
from .cap_form9_engine import _pressure_mpa
from .project import Stage2Project

HEAD_COLUMN = "액위(m)"
GAMMA_COLUMN = "비열비"


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
        rate = rel.gas_release_rate(hole.diameter_mm, rel.ATMOSPHERIC_PA + gauge_mpa * 1.0e6, celsius + 273.15, molar, gamma)
        model = f"기체 오리피스 유출(초크/아임계, Cd {rel.CD_GAS:g}, 비열비 {gamma:g}" + (
            "" if _number(scenario.get(GAMMA_COLUMN)) else " 기본값") + ")"
    else:  # 액체, 액화가스의 액상 누출
        gravity = _number(facility.get("비중"))
        head = _number(scenario.get(HEAD_COLUMN))
        if gravity is None:
            return rel.Release(hole.diameter_mm, hole.reason, None, None, None, "", ("비중이 필요합니다(별지 제1호).",))
        if head is None and gauge_mpa <= 0:
            return rel.Release(hole.diameter_mm, hole.reason, None, None, None, "",
                               ("상압 액체는 누출 수두(액위, m)가 필요합니다.",))
        rate = rel.liquid_release_rate(hole.diameter_mm, gravity * 1000.0, gauge_mpa * 1.0e6, head or 0.0)
        model = f"액상 오리피스 유출(베르누이, Cd {rel.CD_LIQUID:g}, 플래시 증발 미반영)"
    amount = rel.release_amount_kg(rate, duration, target.holding_kg)
    return rel.Release(hole.diameter_mm, hole.reason, rate, float(duration), amount, model)
