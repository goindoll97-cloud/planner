from __future__ import annotations

"""Form-centric authoring workspace for CAP forms (currently 별지 제1호).

The workspace reads/writes the same Stage2Project facts the statutory writers
use, so what the user sees in the on-screen form is exactly what the DOCX
writer produces. It does not duplicate legal logic: the derived tables come
from cap_form1_engine.build_cap_form1_data.
"""

from dataclasses import dataclass, field
from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Mapping

from . import cap_form1_engine as form1
from .cap_calc import internal_volume_m3
from .project import CONFIRMED_STATUSES, Stage2Project

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "data" / "stage2" / "cap_forms"
FACILITY_FIELD_KEY = "cap.workspace.facilities"

# Cell provenance labels shown next to the form.
ORIGIN_DERIVED = "자동(자료·법령DB에서 산출)"
ORIGIN_USER = "직접 입력"
ORIGIN_CALC = "계산값"
ORIGIN_LOOKUP = "자동조회(확인 필요)"


@lru_cache(maxsize=None)
def load_form_schema(form_no: int) -> dict[str, Any]:
    path = SCHEMA_DIR / f"form{form_no:02d}.json"
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if raw.get("schema_version") != "cap-form-workspace-v1":
        raise ValueError("지원하지 않는 CAP 서식 작업대 스키마 버전입니다.")
    return raw


def section(form_no: int, section_id: str) -> dict[str, Any]:
    for item in load_form_schema(form_no)["sections"]:
        if item["id"] == section_id:
            return item
    raise KeyError(section_id)


def column_help(form_no: int, section_id: str) -> dict[str, str]:
    return {col["id"]: col.get("help", "") for col in section(form_no, section_id).get("columns", [])}


def facility_columns() -> list[dict[str, Any]]:
    return list(section(1, "facility_table")["columns"])


def facility_editor_rows(project: Stage2Project) -> list[dict[str, Any]]:
    """Rows for the facility grid, seeded from confirmed facility data."""
    columns = facility_columns()
    aliases = {
        "단위공장·공정": ("단위공장·공정", "단위공장", "공정"),
        "취급물질": ("취급물질", "물질명"),
        "CAS 번호": ("CAS 번호", "CAS No."),
        "설비번호": ("설비번호", "구분기호", "장치번호"),
        "설비명": ("설비명", "취급시설", "장치·설비명"),
        "용량": ("용량", "설계용량"),
        "용량단위": ("용량단위", "설계용량 단위"),
        "최대보유량(kg)": ("최대보유량(kg)",),
    }
    rows: list[dict[str, Any]] = []
    for source in form1._facility_source_rows(project):
        row: dict[str, Any] = {}
        for col in columns:
            value = form1._row_value(source, *aliases.get(col["id"], (col["id"],)))
            row[col["id"]] = value if value not in (None,) else ""
        if not row.get("최대보유량(kg)"):
            ton = form1._facility_holding_ton(source)
            if ton is not None:
                row["최대보유량(kg)"] = form1._fmt_num(ton * 1000.0)
        rows.append(row)
    return rows


def save_facility_rows(project: Stage2Project, rows: list[Mapping[str, Any]]) -> int:
    """Persist edited grid rows as a user-confirmed fact; blank rows are dropped."""
    cleaned = []
    for row in rows:
        item = {key: ("" if value is None else value) for key, value in dict(row).items()}
        if any(str(value).strip() for value in item.values()):
            cleaned.append(item)
    if not cleaned:
        return 0
    project.set_field(
        FACILITY_FIELD_KEY,
        "취급시설 목록(별지 제1호 작성대)",
        cleaned,
        "USER_CONFIRMED",
        note="CAP 서식 작업대의 별지 제1호에서 직접 입력·수정",
    )
    return len(cleaned)


def volume_from_dimensions(shape: str, **dims: float) -> float | None:
    """Geometric 내용적 in m3, rounded for entry into the facility grid."""
    volume = internal_volume_m3(shape, **dims)
    return None if volume is None else round(volume, 4)


@dataclass(frozen=True)
class Form1Workspace:
    facility_rows: tuple[dict[str, Any], ...]
    chemical_rows: tuple[dict[str, Any], ...]
    writing_level: str
    blockers: tuple[str, ...]
    messages: tuple[str, ...]
    needs: tuple[str, ...] = field(default_factory=tuple)
    ready: bool = False


def _needed_facts(project: Stage2Project, editor_rows: list[dict[str, Any]]) -> list[str]:
    """Only the facts still missing for the form, phrased per facility row."""
    needs: list[str] = []
    for index, row in enumerate(editor_rows, start=1):
        label = str(row.get("설비명") or row.get("설비번호") or f"{index}번째 시설").strip()
        if not str(row.get("취급물질") or "").strip():
            needs.append(f"{label}: 취급하는 유해화학물질")
        if not str(row.get("용량") or "").strip():
            needs.append(f"{label}: 설계용량(또는 치수)")
        if not str(row.get("최대보유량(kg)") or "").strip():
            needs.append(f"{label}: 최대보유량(kg)")
    return needs


def resolve_form1(project: Stage2Project) -> Form1Workspace:
    prepared = form1.build_cap_form1_data(project)
    editor_rows = facility_editor_rows(project)
    return Form1Workspace(
        facility_rows=tuple(dict(row) for row in prepared.facility_rows),
        chemical_rows=tuple(dict(row) for row in prepared.chemical_rows),
        writing_level=project.cap_group or "",
        blockers=prepared.blockers,
        messages=prepared.messages,
        needs=tuple(_needed_facts(project, editor_rows)),
        ready=prepared.ready,
    )


def facility_origin(project: Stage2Project) -> str:
    record = project.get_field(FACILITY_FIELD_KEY)
    if record is not None and record.status in CONFIRMED_STATUSES:
        return ORIGIN_USER
    return ORIGIN_DERIVED


def kosha_name_candidate(cas: str) -> dict[str, str]:
    """Look up a single-substance name by CAS; the result is a candidate only."""
    from engine.kosha_msds import lookup_by_cas

    result = lookup_by_cas(cas)
    return {
        "status": result.status,
        "message": result.message,
        "chemical_name": result.chemical_name,
        "origin": ORIGIN_LOOKUP,
    }
