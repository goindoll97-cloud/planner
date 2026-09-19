from __future__ import annotations

"""Facts entered once in the CAP workspace and reused by every 별지.

The 별지 제1호 facility grid is the single place where 취급시설 are entered.
Forms that list the same facilities (제4·5호 시설 유형별 기수, 제9호 장치·설비
목록, 제10·11호 구분기호 연결) read them through `workspace_facility_rows`
instead of asking again.
"""

from collections.abc import Mapping
from typing import Any

from .project import CONFIRMED_STATUSES, Stage2Project

WORKSPACE_FACILITY_KEY = "cap.workspace.facilities"
EXCLUDED_FLAG = "제외시설여부"
SPEC_KEY = "cap.workspace.equipment_specs"  # 별지 제9호에서 입력한 연결구·압력·온도 등


UNIT_COLUMN = "단위공장·공정"


def _norm(value: object) -> str:
    return "".join(str(value or "").split()).lower()


def unit_plant_names(project: Stage2Project) -> list[str]:
    names: list[str] = []
    for row in workspace_facility_rows(project):
        name = str(row.get(UNIT_COLUMN) or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def workspace_facility_rows(project: Stage2Project, unit_plant: str | None = None) -> list[dict[str, Any]]:
    """Confirmed workspace facilities that count as the site's 취급시설.

    With `unit_plant`, rows of other named 단위공장 are dropped. Rows without a
    단위공장 belong to every unit. If the name matches no row, nothing is filtered.
    """
    rows = _all_workspace_rows(project)
    if unit_plant and any(_norm(r.get(UNIT_COLUMN)) == _norm(unit_plant) for r in rows):
        rows = [r for r in rows if not _norm(r.get(UNIT_COLUMN)) or _norm(r.get(UNIT_COLUMN)) == _norm(unit_plant)]
    return rows


def _all_workspace_rows(project: Stage2Project) -> list[dict[str, Any]]:
    record = project.get_field(WORKSPACE_FACILITY_KEY)
    if record is None or record.status not in CONFIRMED_STATUSES or not isinstance(record.value, list):
        return []
    specs = equipment_specs(project)
    rows = []
    for row in record.value:
        if not isinstance(row, Mapping) or str(row.get(EXCLUDED_FLAG, "")).upper() == "Y":
            continue
        merged = dict(row)
        merged.update({k: v for k, v in specs.get(spec_key(row), {}).items() if str(v or "").strip()})
        rows.append(merged)
    return rows


def spec_key(row: Mapping[str, Any]) -> str:
    return _norm(row.get("설비번호")) or _norm(row.get("설비명"))


def equipment_specs(project: Stage2Project) -> dict[str, dict[str, Any]]:
    """별지 제9호 input keyed by 설비번호 (or 설비명), overlaid on the shared facility rows."""
    record = project.get_field(SPEC_KEY)
    if record is None or record.status not in CONFIRMED_STATUSES or not isinstance(record.value, list):
        return {}
    return {spec_key(r): dict(r) for r in record.value if isinstance(r, Mapping) and spec_key(r)}


def workspace_rows_of_type(project: Stage2Project, facility_type: str) -> list[dict[str, Any]]:
    """All confirmed workspace rows of one 시설유형, including ones excluded from holdings."""
    record = project.get_field(WORKSPACE_FACILITY_KEY)
    if record is None or record.status not in CONFIRMED_STATUSES or not isinstance(record.value, list):
        return []
    return [dict(row) for row in record.value if isinstance(row, Mapping) and row.get("시설유형") == facility_type]


def shared_equipment_rows(project: Stage2Project) -> list[dict[str, Any]]:
    """공용 시설 행을 다른 서식(PSM 장치·설비 명세 등)이 읽는 형태로 돌려준다. 용량은 m3로 환산한다."""
    rows = []
    for row in workspace_facility_rows(project):
        item = dict(row)
        capacity = _number(item.get("용량"))
        if capacity is not None:
            if str(item.get("용량단위") or "").strip().lower() == "l":
                capacity /= 1000
            item["용량"] = f"{capacity:g}"
        rows.append(item)
    return rows


def _number(value: object) -> float | None:
    try:
        return float(str(value).replace(",", "")) if str(value or "").strip() else None
    except ValueError:
        return None
