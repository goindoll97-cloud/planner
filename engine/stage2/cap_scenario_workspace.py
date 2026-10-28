from __future__ import annotations

"""예비시나리오 대상 설비 선정(규정 제23조 ①~③, 별표 2) 및 시나리오 목록.

별지 제1·6·9호에서 이미 입력한 시설·물질 정보로 대상 여부를 판정해 제안하고,
사용자가 확정한 시나리오 목록(cap.workspace.scenarios)을 이후 별지 제12·14·15·16호가
함께 쓴다. 영향거리 계산은 이 모듈에 없다.
"""

from dataclasses import dataclass
import re
from typing import Any, Mapping

from . import cap_chemical_workspace as chem
from . import cap_guideline
from .cap_chemical_legal import build_cap_chemical_legal_data
from .cap_form1_engine import volume_to_m3
from .cap_shared_facts import WORKSPACE_FACILITY_KEY, EXCLUDED_FLAG, equipment_specs, spec_key
from .project import CONFIRMED_STATUSES, Stage2Project

SCENARIO_KEY = "cap.workspace.scenarios"
TOXIC, FIRE = "독성 누출", "화재·폭발"
TARGET, NOT_TARGET, CHECK = "대상", "비대상", "확인 필요"
FIXED_KIND, LORRY_KIND = "고정 설비", "입·출하 설비(탱크로리)"
LORRY_TYPE = "탱크로리·운송차량"
# 예비시나리오 대상 설비에서 제외되는 시설 유형(별표 1 제외 대상 중 설비가 아닌 것)
NON_EQUIPMENT_TYPES = {"사외배관", "취급중단 신고시설"}


@dataclass(frozen=True)
class Target:
    tag: str
    name: str
    material: str
    kind: str
    state: str
    holding_kg: float | None
    threshold_kg: float | None
    verdict: str
    reason: str


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _number(value: object) -> float | None:
    found = re.search(r"-?\d+(?:\.\d+)?", _clean(value).replace(",", ""))
    return float(found.group(0)) if found else None


def _category(value: object) -> int | None:
    found = re.search(r"구분\s*([1-5])", _clean(value))
    return int(found.group(1)) if found else None


def _facility_rows(project: Stage2Project) -> list[dict[str, Any]]:
    record = project.get_field(WORKSPACE_FACILITY_KEY)
    if record is None or record.status not in CONFIRMED_STATUSES or not isinstance(record.value, list):
        return []
    specs = equipment_specs(project)
    rows = []
    for row in record.value:
        if isinstance(row, Mapping) and _clean(row.get("시설유형")) not in NON_EQUIPMENT_TYPES:
            merged = dict(row)
            merged.update({k: v for k, v in specs.get(spec_key(row), {}).items() if _clean(v)})
            rows.append(merged)
    return rows


def _properties(project: Stage2Project) -> dict[str, dict[str, Any]]:
    _, rows = chem._rows(project)
    return {_clean(r.get("물질명") or r.get("유해화학물질명")): r for r in rows}


def _low_diffusion(project: Stage2Project) -> set[str]:
    """Material names the legal DB marks 저확산 (제23조 ①: 예비시나리오 대상 설비에서 제외)."""
    return {
        _clean(row.get("물질명") or row.get("유해화학물질명"))
        for row in build_cap_chemical_legal_data(project).rows
        if "저확산" in _clean(row.get("물질구분"))
    }


def _holding_kg(row: Mapping[str, Any]) -> tuple[float | None, str]:
    if _clean(row.get("시설유형")) == LORRY_TYPE:
        volume = volume_to_m3(row.get("용량"), row.get("용량단위"))
        gravity = _number(row.get("비중"))
        if volume is None or gravity is None:
            return None, "탱크로리 최대 저장량(용량·비중)을 입력해야 합니다."
        return volume * gravity * 1000.0, "탱크로리 최대 저장량(용량 × 비중, 내부 구획 무시)"
    if _clean(row.get(EXCLUDED_FLAG)).upper() == "Y":
        return None, "취급량 계산에서 제외된 시설입니다."
    kg = _number(row.get("최대보유량(kg)"))
    if kg is None:
        return None, "최대보유량이 계산되지 않았습니다(별지 제1호에서 필요한 정보를 입력하세요)."
    return kg, _clean(row.get("산정방법"))


def evaluate(project: Stage2Project) -> list[Target]:
    table = cap_guideline.preliminary_scenario_quantities()
    props = _properties(project)
    low_diffusion = _low_diffusion(project)
    targets = []
    for row in _facility_rows(project):
        tag, name = _clean(row.get("설비번호")), _clean(row.get("설비명"))
        material = _clean(row.get("취급물질"))
        kind = LORRY_KIND if _clean(row.get("시설유형")) == LORRY_TYPE else FIXED_KIND
        state = _clean(row.get("물질성상"))
        holding, basis = _holding_kg(row)

        def result(verdict: str, reason: str, threshold: float | None = None, shown_state: str = state) -> Target:
            return Target(tag, name, material, kind, shown_state, holding, threshold, verdict, reason)

        if material in low_diffusion:
            targets.append(result(NOT_TARGET, "규정수량 별표 2의 저확산물질이라 예비시나리오 대상 설비에서 제외됩니다(제23조 ①)."))
            continue
        if not material or state in ("", "복수성상"):
            targets.append(result(CHECK, "운전조건의 물질 성상을 하나로 확인해야 합니다(성상이 둘 이상이면 성상별 구획으로 나누어 산정)."))
            continue
        if holding is None:
            targets.append(result(CHECK, basis))
            continue
        room_state = _clean(props.get(material, {}).get("물질상태"))
        liquefied = state == "액체" and room_state == "기체"  # 액화가스: 별표 2 비고 4
        if state == "기체·고압가스" or liquefied:
            category = _category(props.get(material, {}).get("독성구분"))
            key = ("기체", f"독성구분 {category}" if category in (1, 2, 3) else "독성구분 3")
            note = "액화가스는 기체 규정수량을 적용합니다. " if liquefied else ""
            note += "급성독성 구분이 없거나 1~3 밖이면 독성구분 3 규정수량을 적용합니다." if category not in (1, 2, 3) else ""
            shown = "기체(액화가스)" if liquefied else "기체"
        elif state == "액체":
            key, note, shown = ("액체", "유해성 구분 없음"), "", "액체"
        elif state == "고체":
            key, note, shown = ("고체", "유해성 구분 없음"), "", "고체"
        else:
            targets.append(result(CHECK, f"물질 성상 '{state}'을 판정할 수 없습니다."))
            continue
        threshold = table.get(key)
        if threshold is None:
            targets.append(result(CHECK, f"별표 2에서 {key} 규정수량을 찾지 못했습니다.", shown_state=shown))
        elif holding >= threshold:
            targets.append(result(TARGET, f"취급량 {holding:g}kg ≥ 규정수량 {threshold:g}kg. {note}".strip(), threshold, shown))
        else:
            targets.append(result(NOT_TARGET, f"취급량 {holding:g}kg < 규정수량 {threshold:g}kg. {note}".strip(), threshold, shown))
    return targets


def accident_types(project: Stage2Project, material: str) -> list[str]:
    """Accident kinds a material can have, from 별지 제6호 facts (독성구분 → 독성, 폭발한계 → 화재·폭발)."""
    row = _properties(project).get(material, {})
    kinds = []
    if _category(row.get("독성구분")):
        kinds.append(TOXIC)
    if _number(row.get("폭발한계 하한")) is not None:
        kinds.append(FIRE)
    return kinds


def proposed_scenarios(project: Stage2Project) -> list[dict[str, Any]]:
    """One row per (unit plant, target equipment, accident type)."""
    out = []
    facilities = {_clean(row.get("설비번호")): row for row in _facility_rows(project) if _clean(row.get("설비번호"))}
    for target in evaluate(project):
        if target.verdict != TARGET:
            continue
        source = facilities.get(target.tag, {})
        unit_plant = _clean(source.get("단위공장·공정") or source.get("단위공장") or source.get("공정"))
        if not unit_plant:
            unit_plant = project.company_name
        for kind in accident_types(project, target.material) or [""]:
            label = target.tag or target.name
            out.append({
                "단위공장": unit_plant,
                "사고시나리오명": f"{label} {target.material} {kind}".strip(),
                "대상 설비번호": target.tag, "유해화학물질명": target.material, "사고유형": kind,
                "취급량(kg)": f"{target.holding_kg:g}" if target.holding_kg is not None else "",
                "선정 근거": target.reason,
            })
    return out


def saved_scenarios(project: Stage2Project) -> list[dict[str, Any]]:
    record = project.get_field(SCENARIO_KEY)
    if record is None or not isinstance(record.value, list):
        return []
    return [dict(r) for r in record.value if isinstance(r, Mapping)]


def save_scenarios(project: Stage2Project, rows: list[Mapping[str, Any]]) -> int:
    cleaned = [{k: _clean(v) for k, v in row.items()} for row in rows if _clean(row.get("사고시나리오명"))]
    project.set_field(SCENARIO_KEY, "사고시나리오 목록(작성대)", cleaned, "USER_CONFIRMED",
                      note="예비시나리오 대상(규정 제23조, 별표 2)에서 사용자가 확정. 별지 제12·14·15·16호가 공유")
    return len(cleaned)
