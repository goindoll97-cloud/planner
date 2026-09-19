from __future__ import annotations

"""별지 제4호(총괄 취급시설 개요) authoring support.

Equipment counts, tank-lorry count, and the 유해화학물질·최대보유량 table come
from the 별지 제1호 inputs; the user only describes the process and how many
loading/unloading facilities there are.
"""

from dataclasses import dataclass
import re

from . import cap_form2_workspace as f2
from .cap_final_form_runtime import _FACILITY_CHOICES, facility_type_counts
from .cap_form1_engine import build_cap_form1_data
from .cap_shared_facts import workspace_rows_of_type
from .project import Stage2Project

OVERVIEW_KEY = "cap.basic.total_facility_overview"
PROCESS_KEY = "process.description"
LOADING_KEY = "cap.basic.loading_transport"
LORRY_TYPE = "탱크로리·운송차량"


@dataclass(frozen=True)
class Form4Inputs:
    overview: str
    process: str
    loading_units: str


def _value(project: Stage2Project, key: str) -> str:
    record = project.get_field(key)
    return "" if record is None or record.value is None else str(record.value).strip()


def equipment_counts(project: Stage2Project) -> list[tuple[str, int]]:
    counts = facility_type_counts(project)
    return [(label, counts[label]) for label, _ in _FACILITY_CHOICES if counts.get(label)]


def lorry_count(project: Stage2Project) -> int:
    return len(workspace_rows_of_type(project, LORRY_TYPE))


def chemical_names(project: Stage2Project) -> list[str]:
    seen: list[str] = []
    for row in build_cap_form1_data(project).chemical_rows:
        name = str(row.get("물질명") or "").strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def draft_overview(project: Stage2Project) -> str:
    """A plain sentence built only from facts already entered; the user edits it."""
    counts = equipment_counts(project)
    if not counts:
        return ""
    unit = f2.submission(project)["unit_plant"] or project.company_name
    parts = ", ".join(f"{label} {n}기" for label, n in counts)
    names = chemical_names(project)
    if names:
        return f"{unit}의 취급시설은 {parts}로 구성되며, {', '.join(names)}을(를) 취급한다."
    return f"{unit}의 취급시설은 {parts}로 구성된다."


def inputs(project: Stage2Project) -> Form4Inputs:
    loading = _value(project, LOADING_KEY)
    found = re.search(r"입[·ㆍ.]?출하[^0-9,]*([0-9]+)", loading)
    return Form4Inputs(_value(project, OVERVIEW_KEY), _value(project, PROCESS_KEY), found.group(1) if found else "")


def save_inputs(project: Stage2Project, overview: str, process: str, loading_units: str) -> None:
    note = "CAP 작성대 별지 제4호에서 입력"
    for key, label, value in ((OVERVIEW_KEY, "총괄 취급시설 단위공장 구성", overview),
                              (PROCESS_KEY, "공정개요", process)):
        if value.strip():
            project.set_field(key, label, value.strip(), "USER_CONFIRMED", note=note)
    loading = []
    if str(loading_units).strip().isdigit():
        loading.append(f"입·출하 시설 {int(str(loading_units).strip())}기")
    lorries = lorry_count(project)
    if lorries:
        loading.append(f"보유 탱크로리 {lorries}기")
    if loading:
        project.set_field(LOADING_KEY, "입·출하 및 운반시설", ", ".join(loading), "USER_CONFIRMED", note=note)


def missing(project: Stage2Project) -> list[str]:
    current = inputs(project)
    out = []
    if not equipment_counts(project):
        out.append("시설 목록(별지 제1호 시설 입력)")
    if not current.overview:
        out.append("단위공장 구성")
    if not current.process:
        out.append("공정개요")
    return out
