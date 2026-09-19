from __future__ import annotations

"""별지 제5호(세부 취급시설 개요) authoring support.

별지 제4호와 같은 구조이지만 단위공장 하나에 대한 내용이다. 시설 종류·수량과
물질별 최대 보유량은 별지 제1호 시설 표에서 그 단위공장 시설만 골라 계산하고,
공정개요와 입·출하 시설 수는 별지 제4호에서 이미 입력한 값을 그대로 쓴다.
"""

from typing import Any

from . import cap_form2_workspace as f2
from . import cap_form4_workspace as f4
from .cap_final_form_runtime import _FACILITY_CHOICES, facility_type_counts
from .cap_form1_engine import build_cap_form1_data, mass_to_ton
from .cap_shared_facts import unit_plant_names, workspace_facility_rows
from .project import Stage2Project

OVERVIEW_KEY = "cap.basic.unit_facility_overview"


def active_unit(project: Stage2Project) -> str:
    return f2.submission(project)["unit_plant"]


def unit_counts(project: Stage2Project) -> list[tuple[str, int]]:
    counts = facility_type_counts(project, active_unit(project))
    return [(label, counts[label]) for label, _ in _FACILITY_CHOICES if counts.get(label)]


def unit_chemical_rows(project: Stage2Project, unit_plant: str | None = None) -> list[dict[str, Any]] | None:
    """물질명·CAS·최대 보유량 rows for this 단위공장, or None to fall back to the site table."""
    facilities = workspace_facility_rows(project, unit_plant or active_unit(project))
    if not facilities:
        return None
    site_rows = build_cap_form1_data(project).chemical_rows
    cas_by_name = {str(r.get("물질명") or "").strip(): r.get("CAS No.", "") for r in site_rows}
    totals: dict[str, float] = {}
    for row in facilities:
        name = str(row.get("취급물질") or "").strip()
        if not name:
            continue
        kg = str(row.get("최대보유량(kg)") or "").strip()
        ton = mass_to_ton(kg, "kg") if kg else None
        totals[name] = totals.get(name, 0.0) + (ton or 0.0)
    return [
        {"물질명": name, "CAS No.": cas_by_name.get(name, ""), "사업장 내 최대보유량(ton)": f"{total:.6g}"}
        for name, total in totals.items()
    ]


def draft_overview(project: Stage2Project) -> str:
    counts = unit_counts(project)
    if not counts:
        return ""
    unit = active_unit(project) or project.company_name
    parts = ", ".join(f"{label} {n}기" for label, n in counts)
    return f"{unit}의 취급시설은 {parts}로 구성된다."


def overview(project: Stage2Project) -> str:
    record = project.get_field(OVERVIEW_KEY)
    return "" if record is None or record.value is None else str(record.value).strip()


def save_overview(project: Stage2Project, text: str) -> None:
    if text.strip():
        project.set_field(OVERVIEW_KEY, "단위공장 구성(별지 제5호)", text.strip(), "USER_CONFIRMED",
                          note="CAP 작성대 별지 제5호에서 입력")


def missing(project: Stage2Project) -> list[str]:
    out = []
    if not unit_counts(project):
        out.append("시설 목록(별지 제1호 시설 입력)")
    if not overview(project):
        out.append("단위공장 구성")
    if not f4.inputs(project).process:
        out.append("공정개요(별지 제4호에서 입력)")
    return out


def other_units(project: Stage2Project) -> list[str]:
    """Named 단위공장 in the grid other than the one this submission covers."""
    active = "".join(active_unit(project).split()).lower()
    return [n for n in unit_plant_names(project) if "".join(n.split()).lower() != active]
