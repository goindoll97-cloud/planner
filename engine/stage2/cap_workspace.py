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
        "시설유형": ("시설유형",),
        "물질성상": ("물질성상",),
        "비중": ("비중", "비중 또는 밀도(kg/L=ton/m3)"),
    }
    rows: list[dict[str, Any]] = []
    for source in form1._facility_source_rows(project):
        row: dict[str, Any] = {}
        for col in columns:
            value = form1._row_value(source, *aliases.get(col["id"], (col["id"],)))
            row[col["id"]] = value if value not in (None,) else ""
        excluded = form1._clean(form1._row_value(source, "제외시설여부")).upper() == "Y"
        reason = form1._clean(form1._row_value(source, "제외사유"))
        if excluded and reason in EXCLUDED_TYPES:
            row["시설유형"] = reason
        for extra in EXTRA_FIELDS:
            value = form1._row_value(source, extra)
            if value not in (None, ""):
                row[extra] = value
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
    # Store the calculated maximum holding next to the inputs so the form
    # engine and DOCX writer read one consistent value.
    for item, result in zip(cleaned, compute_holdings(project, cleaned)):
        item["제외시설여부"] = "Y" if result.excluded else "N"
        item["최대보유량(kg)"] = "" if result.ton is None or result.excluded else round(result.ton * 1000.0, 6)
        item["산정방법"] = result.basis or result.problem
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
    results = compute_holdings(project, editor_rows)
    for index, (row, result) in enumerate(zip(editor_rows, results), start=1):
        label = str(row.get("설비명") or row.get("설비번호") or f"{index}번째 시설").strip()
        if result.problem:
            needs.append(f"{label}: {result.problem}")
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


# ---------------------------------------------------------------------------
# Facility maximum-holding calculation (reuses the Stage 1 rule engine)
# ---------------------------------------------------------------------------

FACILITY_TYPES = [
    "저장탱크", "제조·사용시설", "보관시설", "기타",
    "탱크로리·운송차량", "사외배관", "취급중단 신고시설",
]
EXCLUDED_TYPES = {"탱크로리·운송차량", "사외배관", "취급중단 신고시설"}
SUBSTANCE_STATES = ["액체", "고체", "기체·고압가스", "복수성상"]
PROCESS_TYPES = ["변화없음", "단순혼합", "반응"]

# Extra facts asked only for the facilities that need them.
EXTRA_FIELDS: dict[str, dict[str, Any]] = {
    "공정유형": {"label": "공정 유형", "kind": "choice", "options": PROCESS_TYPES,
                "help": "제조·사용시설에서 물질이 그대로 저장·사용되면 '변화없음', 섞기만 하면 '단순혼합', 화학반응이 일어나면 '반응'을 고릅니다. 혼합·반응이 있으면 산정 기준 함량이 필요합니다."},
    "별표4 기준함량(%)": {"label": "산정 기준 함량(%)", "kind": "number",
                        "help": "단순혼합은 투입이 끝난 뒤의 최종 함량, 반응은 반응이 일어나기 전의 최종 함량을 씁니다."},
    "함량근거": {"label": "함량 근거", "kind": "text", "help": "함량 수치의 근거 자료(공정배합표, SDS 등)를 적습니다."},
    "직접확인 최대보유량": {"label": "직접 확인한 최대보유량", "kind": "number",
                        "help": "기체·고압가스나 성상이 둘 이상인 물질은 프로그램이 추정하지 않습니다. 운전조건(압력·온도)을 고려해 산정한 최대 체류량을 직접 입력합니다."},
    "질량단위": {"label": "질량 단위", "kind": "choice", "options": ["kg", "ton"], "help": "직접 입력한 양의 단위입니다."},
    "직접확인 근거": {"label": "직접 확인 근거", "kind": "text", "help": "산정 방법과 근거 자료를 적습니다. 비워 두면 계산되지 않습니다."},
    "보관계획도 최대량": {"label": "보관계획도 최대량", "kind": "number", "help": "보관시설의 보관계획도에 표시된 최대 보관량입니다."},
    "일일최대보관량": {"label": "일일 최대 보관량", "kind": "number", "help": "하루 중 보관하는 최대량입니다. 보관계획도 최대량과 비교해 큰 값을 사용합니다."},
}


def extra_fields_for(row: Mapping[str, Any]) -> list[str]:
    """Field ids that must be asked for this facility, given the core answers."""
    ftype = str(row.get("시설유형") or "").strip()
    state = str(row.get("물질성상") or "").strip()
    if ftype in EXCLUDED_TYPES:
        return []
    if state in {"기체·고압가스", "복수성상"}:
        return ["직접확인 최대보유량", "질량단위", "직접확인 근거"]
    if ftype == "보관시설":
        return ["보관계획도 최대량", "일일최대보관량", "질량단위"]
    if ftype == "기타":
        return ["직접확인 최대보유량", "질량단위", "직접확인 근거"]
    if ftype == "제조·사용시설":
        fields = ["공정유형"]
        if str(row.get("공정유형") or "").strip() in {"단순혼합", "반응"}:
            fields += ["별표4 기준함량(%)", "함량근거"]
        return fields
    return []


@dataclass(frozen=True)
class HoldingResult:
    ton: float | None
    basis: str
    excluded: bool
    problem: str = ""


def _engine_row(row: Mapping[str, Any], list_row_no: int | None) -> dict[str, Any]:
    ftype = str(row.get("시설유형") or "").strip()
    excluded = ftype in EXCLUDED_TYPES
    return {
        "목록행번호": list_row_no,
        "시설명": row.get("설비명"),
        "시설유형": "기타" if excluded else ftype,
        "제외시설여부": "Y" if excluded else "N",
        "제외사유": ftype if excluded else "해당없음",
        "물질성상": row.get("물질성상"),
        "공정유형": row.get("공정유형"),
        "별표4 기준함량(%)": row.get("별표4 기준함량(%)"),
        "함량근거": row.get("함량근거"),
        "설계용량": row.get("용량"),
        "용량단위": row.get("용량단위"),
        "비중 또는 밀도(kg/L=ton/m3)": row.get("비중"),
        "보관계획도 최대량": row.get("보관계획도 최대량"),
        "일일최대보관량": row.get("일일최대보관량"),
        "질량단위": row.get("질량단위"),
        "직접확인 최대보유량": row.get("직접확인 최대보유량"),
        "직접확인 근거": row.get("직접확인 근거"),
    }


def compute_holdings(project: Stage2Project, rows: list[Mapping[str, Any]]) -> list[HoldingResult]:
    """Per-facility maximum holding via the same rules Stage 1 uses."""
    import pandas as pd

    from engine.cap_holding import calculate_facility_rows
    from engine.inventory import IntakeData

    chemicals = form1._chemical_identity_rows(project)
    intake = IntakeData(
        business={}, chemicals=form1._adapt_chemicals_for_stage1(chemicals) if chemicals else pd.DataFrame(),
        documents={}, facilities=pd.DataFrame(),
    )
    by_name, by_cas = form1._chemical_index(chemicals)
    results: list[HoldingResult] = []
    for row in rows:
        name = form1._clean(row.get("취급물질"))
        cas = form1._clean(row.get("CAS 번호"))
        chem_no = by_cas.get(cas) if cas else None
        if chem_no is None and name:
            chem_no = by_name.get(form1._norm(name))
        if chem_no is None:
            results.append(HoldingResult(None, "", False, "취급하는 유해화학물질을 화학물질 목록에서 찾지 못했습니다."))
            continue
        frame = pd.DataFrame([_engine_row(row, chem_no)])
        calcs, blockers = calculate_facility_rows(intake, frame)
        if not calcs:
            results.append(HoldingResult(None, "", False, "; ".join(blockers) or "계산할 수 없습니다."))
            continue
        calc = calcs[0]
        if calc.excluded:
            results.append(HoldingResult(0.0, calc.calculation_basis, True))
        elif calc.max_holding_ton is None:
            results.append(HoldingResult(None, "", False, "; ".join(blockers) or "계산에 필요한 자료가 부족합니다."))
        else:
            results.append(HoldingResult(calc.max_holding_ton, calc.calculation_basis, False))
    return results


def steps(form_no: int = 1) -> list[dict[str, Any]]:
    return list(load_form_schema(form_no).get("steps", []))


def result_sentences(chemical_rows: list[Mapping[str, Any]]) -> list[str]:
    """One plain-language line per substance for the result step."""
    lines: list[str] = []
    for row in chemical_rows:
        name = str(row.get("물질명") or row.get("CAS No.") or "물질").strip()
        holding = str(row.get("사업장 내 최대보유량(ton)") or "").strip()
        lower = str(row.get("하위규정수량(ton)") or "").strip()
        upper = str(row.get("상위규정수량(ton)") or "").strip()
        band = str(row.get("규정수량 비교") or "").strip()
        if not holding:
            lines.append(f"{name}: 최대보유량을 아직 계산하지 못했습니다.")
        elif not (lower and upper):
            lines.append(f"{name}: 최대보유량 {holding}톤. 규정수량을 아직 확인하지 못했습니다.")
        else:
            lines.append(f"{name}: 최대보유량 {holding}톤 (하위 {lower}톤 · 상위 {upper}톤) → {band}")
    return lines
