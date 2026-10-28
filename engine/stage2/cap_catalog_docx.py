"""사실 카탈로그와 칸 연결(data/stage2/cap_docx_cells.json)로 화학사고예방관리계획서 규정서식 DOCX를 채웁니다.

예전 렌더러(cap_baseline_docx.py)는 별지마다 코드로 칸을 채웠습니다. 여기서는 어느 사실이 어느 표·칸에 들어가는지를
데이터 파일로 두고, 이 모듈이 그 순서대로 채웁니다. 옮겨 오는 중이므로
- delegate가 true인 별지(제2·7·8·12~16호)는 예전 렌더러가 그대로 채우고,
- 옮긴 별지라도 기준 행이 하나도 없으면(fallback_when_empty) 예전 렌더러의 대체 경로를 씁니다.
build_cap_draft는 이 조립기를 먼저 쓰고, 실패하면 예전 렌더러로 만듭니다(대체 수단). 두 결과가 같은지는 시험으로 확인합니다.

값은 작성자료(프로젝트 필드)에서 읽습니다. 회사 파일에서 읽은 사실은 evidence_workspace.publish가 작성자료로 보내 두므로
‘파일 → 사실 → 작성자료 → 칸’이 한 줄로 이어집니다.
"""
from __future__ import annotations

from functools import lru_cache
from io import BytesIO
import json
import logging
from pathlib import Path
from typing import Any, Callable

from docx import Document

from . import cap_baseline_docx as old
from . import cap_fact_catalog as catalog
from . import statutory_report as base
from .cap_final_form_runtime import (render_joint_emergency, render_other_system_review, render_submission_type,
                                     render_writing_level, render_yes_no)
from .ooxml_determinism import canonicalize_docx_zip
from .project import Stage2Project

CELLS_PATH = Path(__file__).resolve().parents[2] / "data" / "stage2" / "cap_docx_cells.json"
SCHEMA_VERSION = "cap-docx-cells-v1"
log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def load_cells() -> dict[str, Any]:
    with CELLS_PATH.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("지원하지 않는 서식 칸 연결 파일 버전입니다.")
    return raw


def referenced_facts() -> dict[int, set[str]]:
    """별지 → 칸 연결 파일이 쓰는 사실 id."""
    out: dict[int, set[str]] = {}
    for form in load_cells()["forms"]:
        ids = out.setdefault(int(form["form"]), set())
        for section in form.get("sections", ()):
            for entry in [section] + list(section.get("columns", ())) + list(section.get("cells", ())):
                if entry.get("fact"):
                    ids.add(entry["fact"])
                ids.update(entry.get("facts", ()))
    return out


def validate() -> list[str]:
    """칸 연결 파일의 실수(없는 사실, 별지에 안 쓰이는 사실, 모르는 원천·그리기 이름)를 알려 줍니다."""
    problems = []
    known = {f.id: f for f in catalog.all_facts()}
    for form, ids in referenced_facts().items():
        for fact_id in ids:
            if fact_id not in known:
                problems.append(f"별지 제{form}호: 카탈로그에 없는 사실 {fact_id}")
            elif form not in known[fact_id].forms:
                problems.append(f"별지 제{form}호: {fact_id}의 used_in에 이 별지가 없습니다")
    forms = {int(f["form"]) for f in load_cells()["forms"]}
    if forms != {int(k) for k in old.FORM_TABLE_INDEX}:
        problems.append("칸 연결 파일의 별지 목록이 규정서식 표 위치와 다릅니다")
    for form in load_cells()["forms"]:
        for section in form.get("sections", ()):
            if section.get("source") and section["source"] not in _SOURCES:
                problems.append(f"별지 제{form['form']}호: 모르는 원천 {section['source']}")
            if section.get("type") == "call" and section.get("name") not in _CALLS:
                problems.append(f"별지 제{form['form']}호: 모르는 그리기 {section.get('name')}")
            for cell in section.get("cells", ()):
                if cell.get("render") and cell["render"] not in _RENDERS:
                    problems.append(f"별지 제{form['form']}호: 모르는 표기 {cell['render']}")
        if form.get("fallback_when_empty") and form["fallback_when_empty"] not in _SOURCES:
            problems.append(f"별지 제{form['form']}호: 모르는 대체 기준 {form['fallback_when_empty']}")
    return problems


# ---------------------------------------------------------------- 값의 원천

def _form1(project):
    from .cap_form1_engine import build_cap_form1_data
    return build_cap_form1_data(project)


def _rows_of(builder: Callable[[Stage2Project], Any]) -> Callable[[Stage2Project], tuple]:
    return lambda project: tuple(builder(project).rows)


def _form6(project):
    from .cap_sds_engine import build_cap_form6_sds_data
    return build_cap_form6_sds_data(project)


def _form9(project):
    from .cap_form9_engine import build_cap_form9_data
    return build_cap_form9_data(project)


def _form10(project):
    from .cap_form10_engine import build_cap_form10_data
    return build_cap_form10_data(project)


def _form11(project):
    from .cap_form11_engine import build_cap_form11_data
    return build_cap_form11_data(project)


_SOURCES: dict[str, Callable[[Stage2Project], tuple]] = {
    "form1.facility_rows": lambda project: tuple(_form1(project).facility_rows),
    "form1.chemical_rows": lambda project: tuple(_form1(project).chemical_rows),
    "form6.rows": _rows_of(_form6),
    "form9.rows": _rows_of(_form9),
    "form10.rows": _rows_of(_form10),
    "form11.rows": _rows_of(_form11),
}

_VALUES: dict[str, Callable[[Stage2Project], str]] = {
    "company_name": lambda project: project.company_name or "",
    "site_name": lambda project: project.site_name or "",
    "cap_group": lambda project: project.cap_group or "",
}


def _fact_text(project: Stage2Project, fact_id: str, default: str = "") -> str:
    item = catalog.get(fact_id)
    if not item.field_key or item.field_key.startswith("@"):
        return default
    return base._text(project, item.field_key, default=default)


# ---------------------------------------------------------------- 칸 표기(체크박스 등)

def _render_writer(project, facts):
    department, name = (_fact_text(project, f) for f in facts)
    writer = " ".join(part for part in (department, name) if part)
    return writer or base._text(project, "cap.business.writer_info", default="")


def _render_residents(project, facts):
    state = _fact_text(project, facts[0])
    if not state:
        from .cap_impact_engine import build_cap_form13_data
        form13 = build_cap_form13_data(project)
        value = form13.summary.get("총괄영향범위 내 거주민수") if form13.summary else ""
        if value not in (None, ""):
            try:
                state = "있음" if float(value) > 0 else "없음"
            except (TypeError, ValueError):
                state = ""
    return render_yes_no(state)


_RENDERS: dict[str, Callable[[Stage2Project, list[str]], str]] = {
    "submission_type": lambda project, facts: render_submission_type(*(_fact_text(project, f) for f in facts)),
    "writing_level": lambda project, facts: render_writing_level(
        project.cap_group or base._text(project, "cap.business.writing_level", default="")),
    "joint_emergency": lambda project, facts: render_joint_emergency(_fact_text(project, facts[0])),
    "other_system_review": lambda project, facts: render_other_system_review(_fact_text(project, facts[0])),
    "yes_no": lambda project, facts: render_yes_no(_fact_text(project, facts[0])),
    "residents": _render_residents,
    "writer": _render_writer,
}


def _unit_plant(project, form):
    if not form.get("unit_plant"):
        return None
    return base._text(project, "cap.business.unit_plant_name", default=project.site_name or "")


def _call_facility_type_choices(table, project, form):
    old._fill_choice_cells(table, row_start=3, row_end=8, rendered=old._rendered_facility_choices(project, _unit_plant(project, form)))


def _call_loading_choices(table, project, form):
    loading = base._text(project, "cap.basic.loading_transport", default="")
    old._fill_choice_cells(table, row_start=8, row_end=9, rendered=old._rendered_loading_choices(loading))


def _call_facility_chemicals(table, project, form):
    chemicals = None
    if form.get("unit_plant"):
        from .cap_form5_workspace import unit_chemical_rows
        chemicals = unit_chemical_rows(project, _unit_plant(project, form))
    old._fill_facility_chemical_rows(table, project, chemicals)


_CALLS = {"facility_type_choices": _call_facility_type_choices, "loading_choices": _call_loading_choices,
          "facility_chemicals": _call_facility_chemicals}


# ---------------------------------------------------------------- 별지 채우기

def _label_value(project, cell) -> str:
    if cell.get("render"):
        return _RENDERS[cell["render"]](project, list(cell.get("facts", ())))
    if cell.get("value"):
        return _VALUES[cell["value"]](project)
    default = _VALUES[cell["default"]](project) if cell.get("default") else ""
    return _fact_text(project, cell["fact"], default)


def _column_value(project, row, index, column):
    if column.get("index"):
        return str(index)
    if column.get("keys"):
        return base._row_value(row, *column["keys"])
    value = row.get(column["key"], "") if column.get("key") else ""
    if not value and column.get("or"):
        value = _VALUES[column["or"]](project)
    return value


def _fill_section(tables, project, form, section, cache):
    table = tables[int(section.get("table", 0))]
    kind = section["type"]
    if kind == "labels":
        mapping = {cell["label"]: _label_value(project, cell) for cell in section["cells"]}
        old._fill_label_rows_replace(table, mapping, start=int(section.get("start", 0)))
    elif kind == "rows":
        rows = cache[section["source"]]
        values = [[_column_value(project, row, index, column) for column in section["columns"]]
                  for index, row in enumerate(rows, 1)]
        old._fill_table_rows(table, old._sanitize_rows(values), header_rows=int(section.get("header_rows", 1)))
    elif kind == "cell":
        value = _VALUES[section["value"]](project)
        old._write_cell(old._unique_cells(table.rows[int(section["row"])])[int(section["cell"])], value)
    elif kind == "call":
        _CALLS[section["name"]](table, project, form)
    else:
        raise ValueError(f"모르는 칸 연결 종류: {kind}")


_OLD_FILLERS: dict[int, Callable[[list, Stage2Project], None]] = {
    1: lambda t, p: old._fill_form1(t, p),
    2: lambda t, p: old._fill_form2(t, p),
    3: lambda t, p: old._fill_form3(t[0], p),
    4: lambda t, p: old._fill_facility_overview(t[0], p, detailed=False),
    5: lambda t, p: old._fill_facility_overview(t[0], p, detailed=True),
    6: lambda t, p: old._fill_form6(t[0], p),
    7: lambda t, p: old._fill_form7(t[0], p),
    8: lambda t, p: old._fill_form8(t, p),
    9: lambda t, p: old._fill_form9(t[0], p),
    10: lambda t, p: old._fill_form10(t[0], p),
    11: lambda t, p: old._fill_form11(t[0], p),
    12: lambda t, p: old._fill_form12(t, p),
    13: lambda t, p: old._fill_form13(t, p),
    15: lambda t, p: old._fill_form15(t, p),
    16: lambda t, p: old._fill_form16(t, p),
}


class _Cache(dict):
    """한 번 만드는 동안 같은 계산 엔진을 여러 번 부르지 않습니다."""

    def __init__(self, project):
        super().__init__()
        self.project = project

    def __missing__(self, key):
        value = _SOURCES[key](self.project)
        self[key] = value
        return value


def fill(doc, project: Stage2Project) -> list[int]:
    """열린 규정서식 문서를 채웁니다. 예전 렌더러가 채운 별지 번호 목록을 돌려줍니다."""
    tables = doc.tables
    total = sum(len(v) for v in old.FORM_TABLE_INDEX.values())
    if len(tables) < 6 + total:
        raise ValueError("CAP 규정서식 baseline 구조가 예상과 달라 자동작성을 중단했습니다.")
    cache = _Cache(project)
    delegated = []
    for form in load_cells()["forms"]:
        number = int(form["form"])
        form_tables = [tables[i] for i in old.FORM_TABLE_INDEX[str(number)]]
        empty = form.get("fallback_when_empty") and not cache[form["fallback_when_empty"]]
        if form.get("delegate") or empty:
            _OLD_FILLERS[number](form_tables, project)
            delegated.append(number)
            continue
        for section in form["sections"]:
            _fill_section(form_tables, project, form, section, cache)
    return delegated


def build_cap_catalog_draft(project: Stage2Project) -> bytes:
    if not project.cap_in_scope:
        raise ValueError("화학사고예방관리계획서는 현재 작성범위에 포함되어 있지 않습니다.")
    doc = Document(BytesIO(old.load_cap_baseline_bytes()))
    fill(doc, project)
    out = BytesIO()
    doc.save(out)
    return canonicalize_docx_zip(out.getvalue())


def build_cap_draft(project: Stage2Project) -> bytes:
    """초안 규정서식 DOCX. 카탈로그 조립기를 쓰고, 실패하면 예전 렌더러로 만듭니다(대체 수단)."""
    if not project.cap_in_scope:
        raise ValueError("화학사고예방관리계획서는 현재 작성범위에 포함되어 있지 않습니다.")
    try:
        return build_cap_catalog_draft(project)
    except Exception:          # 조립기 문제로 초안을 못 받는 일이 없도록
        log.exception("카탈로그 조립기로 서식을 만들지 못해 예전 렌더러를 씁니다.")
        return old.build_cap_baseline_draft(project)
