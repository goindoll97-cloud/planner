from __future__ import annotations

"""Write confirmed CAP company data into the preserved statutory-form DOCX baseline.

The bundled DOCX is a layout baseline derived from the regulation forms supplied
by the user (별지 제1호~16호서식). It is deliberately not treated as the legal-
currentness authority; that remains the existing law.go.kr monitoring/approval
path. This writer only preserves the supplied form geometry and inserts already-
confirmed project data. Unknown values stay blank rather than guessed, and the
static 별표 1~4 reference tables (regulation thresholds, not company data) and
별지 제2호서식's worked example table are never touched.
"""

import base64
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from docx import Document

from . import statutory_report as base
from .cap_form1_engine import build_cap_form1_data
from .cap_form2_engine import NOT_APPLICABLE as FORM2_NOT_APPLICABLE, build_cap_form2_readiness
from .cap_chemical_legal import build_cap_chemical_legal_data
from .cap_sds_engine import build_cap_form6_sds_data, build_cap_form7_data
from .cap_form8_engine import build_cap_form8_data
from .cap_form9_engine import build_cap_form9_data
from .cap_form10_engine import build_cap_form10_data
from .cap_form11_engine import build_cap_form11_data
from .cap_impact_engine import build_cap_form12_data, build_cap_form13_data
from .cap_risk_engine import build_cap_form14_data, build_cap_form15_data
from .cap_form16_engine import build_cap_form16_data
from .cap_final_form_runtime import (
    render_facility_type_counts,
    render_joint_emergency,
    render_loading_transport,
    render_other_system_review,
    render_submission_type,
    render_writing_level,
    render_yes_no,
)
from .project import CONFIRMED_STATUSES, Stage2Project
from .ooxml_determinism import canonicalize_docx_zip

# Intake workbook templates have used different header wording for the same
# fields over time (e.g. an older "물질명" column vs. a newer
# "물질명(알면 입력)"/"제품명" pair). Company data is confirmed either way, so
# every chemical-identity lookup in this module accepts all known spellings
# rather than silently rendering a blank cell for a template it wasn't
# written against.
_CHEMICAL_NAME_ALIASES = ("물질명", "화학물질명", "유해화학물질명", "물질명(알면 입력)", "제품명", "상품명")
_CAS_ALIASES = ("CAS 번호", "CAS No.", "CAS No", "CAS", "화학물질식별번호(CAS 번호)", "화학물질식별번호")


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = PROJECT_ROOT / "data" / "templates" / "cap"
METADATA_PATH = TEMPLATE_DIR / "cap_statutory_forms_baseline.json"
BASE64_GLOB = "cap_statutory_forms_baseline.docx.b64.*"
MISSING = base.MISSING


# Position of each form's table(s) in doc.tables, after the 6 static 별표 1~4
# reference tables (indexes 0-5). Several forms span more than one table.
FORM_TABLE_INDEX = {
    "1": (6, 7, 8),
    "2": (9, 10),  # table 11 is the worked example; never touched
    "3": (12,),
    "4": (13,),
    "5": (14,),
    "6": (15,),
    "7": (16,),
    "8": (17, 18),
    "9": (19,),
    "10": (20,),
    "11": (21,),
    "12": (22, 23),
    "13": (24, 25, 26, 27, 28),
    "15": (29, 30, 31),
    "16": tuple(range(32, 44)),
}


def _metadata() -> dict[str, Any]:
    with METADATA_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_cap_baseline_bytes() -> bytes:
    meta = _metadata()
    parts = sorted(TEMPLATE_DIR.glob(BASE64_GLOB))
    if not parts:
        raise FileNotFoundError("CAP 규정서식 baseline 파일이 준비되지 않았습니다.")
    decoded_parts: list[bytes] = []
    for part in parts:
        encoded = "".join(part.read_text(encoding="ascii").split())
        try:
            decoded_parts.append(base64.b64decode(encoded, validate=True))
        except Exception as exc:
            raise ValueError("CAP 규정서식 baseline 인코딩을 읽지 못했습니다.") from exc
    data = b"".join(decoded_parts)
    expected = str(meta.get("sha256") or "").lower()
    actual = sha256(data).hexdigest()
    if expected and actual != expected:
        raise ValueError("CAP 규정서식 baseline 해시가 등록값과 일치하지 않습니다.")
    validate_cap_baseline(data)
    return data


def validate_cap_baseline(data: bytes) -> None:
    meta = _metadata()
    try:
        doc = Document(BytesIO(data))
    except Exception as exc:
        raise ValueError("CAP 규정서식 baseline DOCX를 열 수 없습니다.") from exc
    required_count = int(meta.get("required_table_count") or 0)
    if required_count and len(doc.tables) != required_count:
        raise ValueError(
            f"CAP 규정서식 baseline의 표 수가 예상과 다릅니다: {len(doc.tables)}개 / 예상 {required_count}개"
        )
    text = "\n".join(p.text for p in doc.paragraphs)
    missing = [str(marker) for marker in meta.get("required_markers") or [] if str(marker) not in text]
    if missing:
        raise ValueError("CAP 규정서식 baseline에서 필수 별지표시를 찾지 못했습니다: " + ", ".join(missing))


def _unique_cells(row) -> list:
    seen: set[int] = set()
    cells = []
    for cell in row.cells:
        marker = id(cell._tc)
        if marker in seen:
            continue
        seen.add(marker)
        cells.append(cell)
    return cells


def _clean(value: object) -> str:
    if value in (None, "", MISSING):
        return ""
    if isinstance(value, Mapping):
        parts = [f"{key}: {val}" for key, val in value.items() if val not in (None, "", MISSING)]
        return " / ".join(parts)
    if isinstance(value, (list, tuple)):
        return ", ".join(_clean(item) for item in value if _clean(item))
    return str(value).strip()


def _confirmed_text(project: Stage2Project, *keys: str) -> str:
    values: list[str] = []
    for key in keys:
        rec = project.get_field(key)
        if rec is None or rec.status not in CONFIRMED_STATUSES:
            continue
        text = _clean(rec.value)
        if text and text not in values:
            values.append(text)
    return " / ".join(values)


def _fill_text_block(table, value: object, *, header_rows: int = 1) -> None:
    """Place confirmed narrative in an existing official table without parsing it.

    Some company-facing inputs are narrative plans rather than columnar facts.
    We must not invent 기관명/전화번호/일정 by splitting prose heuristically.
    Put the confirmed text in the first available answer cell so the statutory
    section is not falsely blank while preserving fail-closed semantics.
    """
    text = _clean(value)
    if not text:
        return
    start = min(max(header_rows, 0), max(len(table.rows) - 1, 0))
    if not table.rows:
        return
    cells = _unique_cells(table.rows[start])
    if not cells:
        return
    target = cells[-1]
    if not target.text.strip():
        _write_cell(target, text)
    else:
        _append_value(target, text)


def _write_cell(cell, value: object) -> None:
    text = _clean(value)
    runs = [run for paragraph in cell.paragraphs for run in paragraph.runs]
    if runs:
        runs[0].text = text
        for run in runs[1:]:
            run.text = ""
        return
    paragraph = cell.paragraphs[0] if cell.paragraphs else cell.add_paragraph()
    paragraph.add_run(text)


def _append_value(cell, value: object) -> None:
    text = _clean(value)
    if not text:
        return
    label = cell.text.strip()
    _write_cell(cell, (label + " " + text).strip())


def _row_text(row) -> str:
    return " ".join(cell.text.strip() for cell in _unique_cells(row)).strip()


def _first_data_row(table, header_rows: int) -> int:
    """Return the first data row after a 1- or 2-line header banner."""
    for index in range(header_rows, len(table.rows)):
        cells = _unique_cells(table.rows[index])
        if cells and not any(cell.text.strip() for cell in cells):
            return index
    return header_rows


def _note_row(table, start: int) -> int:
    for index in range(start, len(table.rows)):
        if _row_text(table.rows[index]).startswith("주)"):
            return index
    return len(table.rows)


def _ensure_row_capacity(table, start: int, note_index: int, required: int) -> None:
    capacity = note_index - start
    if required <= capacity or capacity <= 0:
        return
    template_tr = table.rows[start]._tr
    extra = required - capacity
    if note_index < len(table.rows):
        note_tr = table.rows[note_index]._tr
        for _ in range(extra):
            note_tr.addprevious(deepcopy(template_tr))
    else:
        # No trailing "주)" note row to anchor before; append at the end.
        for _ in range(extra):
            table._tbl.append(deepcopy(template_tr))


def _fill_table_rows(table, rows: Sequence[Sequence[object]], *, header_rows: int) -> None:
    if not rows:
        return
    start = _first_data_row(table, header_rows)
    note_index = _note_row(table, start)
    _ensure_row_capacity(table, start, note_index, len(rows))
    for offset, values in enumerate(rows):
        cells = _unique_cells(table.rows[start + offset])
        for index, cell in enumerate(cells):
            _write_cell(cell, values[index] if index < len(values) else "")


def _sanitize_rows(rows: Sequence[Sequence[object]]) -> list[list[str]]:
    return [[_clean(value) for value in row] for row in rows]


def _fill_label_rows(table, mapping: Mapping[str, object], *, start: int = 0) -> None:
    """Fill "구분/작성내용" style tables: match each row's first cell against
    the mapping's normalized keys and write the value into the row's last
    (answer) cell. Rows with no matching key are left untouched."""
    normalized = {base._norm(key): value for key, value in mapping.items()}
    for row in table.rows[start:]:
        cells = _unique_cells(row)
        if len(cells) < 2:
            continue
        label = cells[0].text.strip()
        value = normalized.get(base._norm(label))
        if value not in (None, "", MISSING):
            _append_value(cells[-1], value)


def _fill_label_rows_replace(table, mapping: Mapping[str, object], *, start: int = 0) -> None:
    """Replace values in every label/value pair contained in a row.

    Most statutory rows contain one label and one answer. Some official rows,
    including the final row of Annex Form 3, contain two independent pairs in
    the same row. Writing only to the row's last cell shifts the first value
    into the second field and leaves the second value blank.

    Match every label cell and write to its immediate next unique XML cell.
    Replacement is retained so preprinted checkbox text cannot accumulate.
    """
    normalized = {base._norm(key): value for key, value in mapping.items()}
    for row in table.rows[start:]:
        cells = _unique_cells(row)
        if len(cells) < 2:
            continue
        for index, cell in enumerate(cells[:-1]):
            value = normalized.get(base._norm(cell.text.strip()))
            if value not in (None, "", MISSING):
                _write_cell(cells[index + 1], value)


def _fill_single_column_labels(table, mapping: Mapping[str, object]) -> None:
    """별지 제7호서식-style tables: one column, each row starts with a label
    like "가. 물질명" and the answer is appended after it in the same cell."""
    normalized = {base._norm(key): value for key, value in mapping.items()}
    for row in table.rows:
        cells = _unique_cells(row)
        if not cells:
            continue
        label = cells[0].text.strip()
        for alias, value in normalized.items():
            if alias and alias in base._norm(label):
                if value not in (None, "", MISSING):
                    _append_value(cells[0], value)
                break


def _fill_form1(tables, project: Stage2Project) -> None:
    t1, t2, t3 = tables
    prepared = build_cap_form1_data(project)

    t1_rows = [
        [
            row.get("단위공장", ""),
            row.get("유해화학물질", ""),
            row.get("CAS No.", ""),
            row.get("함량(%)", ""),
            row.get("구분기호", ""),
            row.get("취급시설", ""),
            row.get("설계용량(m3)", ""),
            row.get("취급량(ton)", ""),
        ]
        for row in prepared.facility_rows
    ]
    _fill_table_rows(t1, _sanitize_rows(t1_rows), header_rows=1)

    if not t1_rows:
        chemicals = base._chemical_rows(project)
        chem_by_name = {
            base._norm(base._row_value(row, *_CHEMICAL_NAME_ALIASES)): row
            for row in chemicals
        }
        legacy_rows = []
        for facility in base._facility_rows(project):
            material = base._row_value(facility, "취급물질", "물질명")
            chem = chem_by_name.get(base._norm(material), {})
            legacy_rows.append([
                base._row_value(facility, "단위공장·공정", "단위공장", "공정"),
                material,
                base._row_value(chem, *_CAS_ALIASES),
                base._row_value(chem, "함량(%)", "함량"),
                base._row_value(facility, "설비번호", "구분기호"),
                base._row_value(facility, "설비명", "취급시설"),
                base._row_value(facility, "용량", "설계용량"),
                base._row_value(facility, "최대보유량(kg)", "취급량", "최대보유량"),
            ])
        _fill_table_rows(t1, _sanitize_rows(legacy_rows), header_rows=1)

    t2_rows = [
        [
            row.get("물질명", ""),
            row.get("CAS No.", ""),
            row.get("물질구분", ""),
            row.get("사업장 내 최대보유량(ton)", ""),
            row.get("작성수준", "") or project.cap_group,
            row.get("하위규정수량(ton)", ""),
            row.get("상위규정수량(ton)", ""),
        ]
        for row in prepared.chemical_rows
    ]
    _fill_table_rows(t2, _sanitize_rows(t2_rows), header_rows=2)

    _write_cell(_unique_cells(t3.rows[0])[1], project.cap_group or "")


def _fill_form2(tables, project: Stage2Project) -> None:
    context_table, log_table = tables
    context_cells = _unique_cells(context_table.rows[0])
    _append_value(context_cells[1], project.company_name)
    unit_plant = base._text(project, "cap.business.unit_plant_name", default=project.site_name or "")
    if unit_plant:
        _append_value(context_cells[3], unit_plant)

    prepared = build_cap_form2_readiness(project)
    change_log = [] if prepared.status == FORM2_NOT_APPLICABLE else list(prepared.rows)
    rows = [
        [
            str(idx),
            base._row_value(row, "일자"),
            base._row_value(row, "변경항목"),
            base._row_value(row, "변경의 종류"),
            base._row_value(row, "변경 내용(변경전 → 변경후)", "변경 내용"),
            base._row_value(row, "후속조치"),
            base._row_value(row, "담당자"),
        ]
        for idx, row in enumerate(change_log, 1)
    ]
    _fill_table_rows(log_table, _sanitize_rows(rows), header_rows=1)


def _fill_form3(table, project: Stage2Project) -> None:
    level = project.cap_group or base._text(project, "cap.business.writing_level", default="")
    writer_name = base._text(project, "cap.business.writer_name", default="")
    writer_department = base._text(project, "cap.business.writer_department", default="")
    writer = " ".join(part for part in (writer_department, writer_name) if part)
    if not writer:
        writer = base._text(project, "cap.business.writer_info", default="")

    residents_state = base._text(project, "cap.business.residents_in_overall_range", default="")
    if not residents_state:
        form13 = build_cap_form13_data(project)
        value = form13.summary.get("총괄영향범위 내 거주민수") if form13.summary else ""
        if value not in (None, ""):
            try:
                residents_state = "있음" if float(value) > 0 else "없음"
            except (TypeError, ValueError):
                residents_state = ""

    mapping = {
        "사업장명": project.company_name or "",
        "단위공장명": base._text(project, "cap.business.unit_plant_name", default=project.site_name or ""),
        "사업자 등록번호": base._text(project, "cap.business.registration_no", default=""),
        "대표자": base._text(project, "cap.business.representative", default=""),
        "우편번호/주소": base._text(project, "business.address", default=""),
        "산업단지": base._text(project, "cap.business.industrial_complex", default=""),
        "대표전화": base._text(project, "cap.business.contact", default=""),
        "제출구분": render_submission_type(
            base._text(project, "cap.business.submission_type", default=""),
            base._text(project, "cap.business.submission_reason", default=""),
        ),
        "작성수준": render_writing_level(level),
        "공동비상대응계획 수립 여부": render_joint_emergency(
            base._text(project, "cap.business.joint_emergency_plan", default="")
        ),
        "유사제도 심사결과 활용": render_other_system_review(
            base._text(project, "cap.business.other_system_review", default="")
        ),
        "총괄영향범위내 주민여부": render_yes_no(residents_state),
        "최근 3년간 화학사고 발생 여부": render_yes_no(
            base._text(project, "cap.business.recent_accident", default="")
        ),
        "화학사고예방관리계획서 작성자": writer,
        "담당자 연락처": base._text(project, "cap.business.writer_contact", default=""),
        "담당자 메일주소": base._text(project, "cap.business.writer_email", default=""),
    }
    _fill_label_rows_replace(table, mapping, start=1)


def _rendered_facility_choices(project: Stage2Project, unit_plant: str | None = None) -> dict[str, str]:
    rendered: dict[str, str] = {}
    for line in render_facility_type_counts(project, unit_plant).splitlines():
        match = re.match(r"^[☒☐]\s*(.+)\s+\(([^)]*)\)기$", line.strip())
        if match:
            rendered[base._norm(match.group(1))] = line.strip()
    return rendered


def _rendered_loading_choices(value: object) -> dict[str, str]:
    text = render_loading_transport(value)
    rendered: dict[str, str] = {}
    for label in ("입·출하 시설", "보유 탱크로리"):
        match = re.search(
            rf"([☒☐]\s*{re.escape(label)}\s*\([^)]*\)기)",
            text,
        )
        if match:
            rendered[base._norm(label)] = match.group(1).strip()
    return rendered


def _fill_choice_cells(table, *, row_start: int, row_end: int, rendered: Mapping[str, str]) -> None:
    """Replace each preprinted option cell with the corresponding checked line."""
    for row in table.rows[row_start:row_end]:
        cells = _unique_cells(row)
        for cell in cells[1:]:
            original = base._norm(cell.text)
            if not original:
                continue
            for label_norm, value in rendered.items():
                if label_norm and label_norm in original:
                    _write_cell(cell, value)
                    break


def _facility_chemical_data_rows(table) -> list:
    """Return the official Form 4/5 chemical data rows, excluding the header row."""
    data_rows = []
    for row in table.rows:
        cells = _unique_cells(row)
        if not cells:
            continue
        if base._norm(cells[0].text) != base._norm("유해화학물질 및 취급량"):
            continue
        trailing = " ".join(cell.text for cell in cells[1:])
        if "CAS" in trailing or "최대 보유량" in trailing or "최대보유량" in trailing:
            continue
        if len(cells) >= 4:
            data_rows.append(row)
    return data_rows


def _ensure_facility_chemical_row_capacity(table, required: int) -> list:
    """Expand the official Form 4/5 chemical block without dropping confirmed chemicals.

    The bundled statutory form contains eight preprinted rows. When the company
    has more confirmed chemicals, clone the final official data-row XML
    immediately after the existing block. This preserves the first-column
    vertical merge, borders, cell widths, fonts and paragraph formatting while
    allowing Word to paginate the enlarged table naturally.
    """
    rows = _facility_chemical_data_rows(table)
    if required <= len(rows):
        return rows
    if not rows:
        raise ValueError(
            "별지 제4·5호 유해화학물질 표의 기준 데이터 행을 찾지 못해 자동 확장할 수 없습니다."
        )

    template_tr = rows[-1]._tr
    anchor_tr = rows[-1]._tr
    for _ in range(required - len(rows)):
        cloned_tr = deepcopy(template_tr)
        anchor_tr.addnext(cloned_tr)
        anchor_tr = cloned_tr

    expanded = _facility_chemical_data_rows(table)
    if len(expanded) < required:
        raise ValueError(
            f"별지 제4·5호 유해화학물질 표를 {required}행까지 자동 확장하지 못했습니다 "
            f"(확인된 작성행 {len(expanded)}행)."
        )
    return expanded


def _fill_facility_chemical_rows(table, project: Stage2Project, chemical_rows=None) -> None:
    unique: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    source_rows = chemical_rows if chemical_rows is not None else build_cap_form1_data(project).chemical_rows
    for row in source_rows:
        name = _clean(row.get("물질명"))
        cas = _clean(row.get("CAS No."))
        holding = _clean(row.get("사업장 내 최대보유량(ton)"))
        key = (name, cas)
        if key in seen:
            continue
        seen.add(key)
        unique.append((name, cas, holding))

    data_rows = _ensure_facility_chemical_row_capacity(table, len(unique))
    if not data_rows:
        return

    for row in data_rows:
        cells = _unique_cells(row)
        for cell in cells[1:4]:
            _write_cell(cell, "")

    for row, (name, cas, holding) in zip(data_rows, unique):
        cells = _unique_cells(row)
        _write_cell(cells[1], name)
        _write_cell(cells[2], cas)
        _write_cell(cells[3], holding)

    # Fail closed only if the post-write document does not contain every
    # confirmed chemical exactly in the intended name/CAS/holding columns.
    rendered: list[tuple[str, str, str]] = []
    for row in data_rows[: len(unique)]:
        cells = _unique_cells(row)
        rendered.append(
            (
                _clean(cells[1].text),
                _clean(cells[2].text),
                _clean(cells[3].text),
            )
        )
    if rendered != unique:
        raise ValueError(
            "별지 제4·5호 유해화학물질 표 자동 확장 후 입력값 검증에 실패하여 "
            "일부 물질이 누락되거나 열이 어긋날 가능성이 있으므로 DOCX 생성을 중단합니다."
        )


def _fill_facility_overview(
    table,
    project: Stage2Project,
    *,
    detailed: bool,
) -> None:
    overview_key = "cap.basic.unit_facility_overview" if detailed else "cap.basic.total_facility_overview"
    unit_plant = None
    unit_chemicals = None
    if detailed:
        from .cap_form5_workspace import unit_chemical_rows

        unit_plant = base._text(project, "cap.business.unit_plant_name", default=project.site_name or "")
        unit_chemicals = unit_chemical_rows(project, unit_plant)
    _fill_label_rows_replace(
        table,
        {
            "단위공장 구성": base._text(project, overview_key, default=""),
            "공정개요": base._text(project, "process.description", default=""),
        },
        start=1,
    )

    _fill_choice_cells(
        table,
        row_start=3,
        row_end=8,
        rendered=_rendered_facility_choices(project, unit_plant),
    )

    loading_value = base._text(project, "cap.basic.loading_transport", default="")
    _fill_choice_cells(
        table,
        row_start=8,
        row_end=9,
        rendered=_rendered_loading_choices(loading_value),
    )

    _fill_facility_chemical_rows(table, project, unit_chemicals)


def _fill_form6(table, project: Stage2Project) -> None:
    prepared = build_cap_form6_sds_data(project)
    rows = []
    for idx, row in enumerate(prepared.rows, 1):
        rows.append([
            str(idx),
            base._row_value(row, *_CHEMICAL_NAME_ALIASES),
            base._row_value(row, "물질구분"),
            base._row_value(row, *_CAS_ALIASES),
            base._row_value(row, "고유번호"),
            base._row_value(row, "물리적 상태", "물질상태"),
            base._row_value(row, "함량(%)", "함량"),
            base._row_value(row, "비중"),
            base._row_value(row, "폭발한계 하한", "폭발하한"),
            base._row_value(row, "폭발한계 상한", "폭발상한"),
            base._row_value(row, "독성구분 항목", "독성구분-항목"),
            base._row_value(row, "독성구분", "독성구분-구분"),
            base._row_value(row, "위험노출수준", "ERPG", "AEGL", "PAC", "IDLH"),
            base._row_value(row, "허용농도값", "TWA", "노출기준"),
            base._row_value(row, "증기압", "증기압(20℃, mmHg)"),
            base._row_value(row, "부식성", "부식성(유, 무)"),
        ])
    _fill_table_rows(table, _sanitize_rows(rows), header_rows=2)


def _fill_form7(table, project: Stage2Project) -> None:
    prepared = build_cap_form7_data(project)
    row = prepared.row
    if not row:
        return

    max_holding = base._row_value(row, "최대보유량(ton)", "최대보유량")
    if max_holding not in (None, "") and "ton" not in str(max_holding).lower():
        max_holding = f"{max_holding} ton"

    source = base._row_value(row, "출처", "SDS 출처")
    sds_file = base._row_value(row, "SDS 파일명", "MSDS 파일명")
    sds_revision = base._row_value(row, "SDS 개정일", "MSDS 개정일", "SDS 작성·개정일")
    source_parts = [
        str(value).strip()
        for value in (source, sds_file, sds_revision)
        if str(value or "").strip()
    ]

    mapping = {
        "물질명": base._row_value(row, *_CHEMICAL_NAME_ALIASES),
        "화학물질식별번호(CAS 번호)": base._row_value(row, *_CAS_ALIASES),
        "유해화학물질 고유번호": base._row_value(row, "고유번호"),
        "농도(또는 함량 %)": base._row_value(row, "함량(%)", "농도", "함량"),
        "최대보유량": max_holding,
        "인체유해성": base._row_value(row, "인체유해성"),
        "물리적 위험성": base._row_value(row, "물리적 위험성"),
        "환경유해성": base._row_value(row, "환경유해성"),
        "출처": " / ".join(source_parts),
        "선정 사유": base._row_value(row, "선정 사유", "선정사유"),
    }
    _fill_single_column_labels(table, mapping)


def _fill_form8(tables, project: Stage2Project) -> None:
    context_table, list_table = tables
    prepared = build_cap_form8_data(project)

    if prepared.no_protected_targets:
        summary = "사업장 경계 500m 내 보호대상 없음 (회사/GIS 확인)"
    elif prepared.rows:
        counts = {"갑종": 0, "을종": 0, "환경수용체": 0}
        evidence: list[str] = []
        for row in prepared.rows:
            category = _clean(row.get("보호대상 구분"))
            if category in counts:
                counts[category] += 1
            basis = _clean(row.get("GIS/현장 근거"))
            if basis and basis not in evidence:
                evidence.append(basis)
        summary = (
            f"사업장 경계 500m 내 보호대상 {len(prepared.rows)}건"
            f" (갑종 {counts['갑종']}건 / 을종 {counts['을종']}건 / "
            f"환경수용체 {counts['환경수용체']}건)"
        )
        if evidence:
            summary += " / 근거: " + ", ".join(evidence)
    else:
        summary = ""

    if summary and len(context_table.rows) > 1:
        cells = _unique_cells(context_table.rows[1])
        if cells:
            _write_cell(cells[-1], summary)

    rows = [
        [
            row.get("일련번호", ""),
            row.get("보호대상 종류", ""),
            row.get("보호대상 명칭", ""),
            row.get("사업장 경계와 거리(m)", ""),
        ]
        for row in prepared.rows
    ]
    if prepared.no_protected_targets and not rows:
        rows = [["-", "-", "해당 없음", "-"]]
    _fill_table_rows(list_table, _sanitize_rows(rows), header_rows=1)


def _fill_form9(table, project: Stage2Project) -> None:
    prepared = build_cap_form9_data(project)
    rows = [
        [
            row.get("연번", ""),
            row.get("구분기호", ""),
            row.get("장치·설비명", ""),
            row.get("취급물질", ""),
            row.get("CAS No.", ""),
            row.get("물질상태", ""),
            row.get("함량(%)", ""),
            row.get("연결구 크기(mm)", ""),
            row.get("압력(MPa)-설계", ""),
            row.get("압력(MPa)-운전", ""),
            row.get("온도(℃)-설계", ""),
            row.get("온도(℃)-운전", ""),
            row.get("설계용량(m3)", ""),
            row.get("취급량(ton)", ""),
            row.get("비고", ""),
        ]
        for row in prepared.rows
    ]
    _fill_table_rows(table, _sanitize_rows(rows), header_rows=2)
    if not rows:
        chemicals = {
            base._norm(base._row_value(item, *_CHEMICAL_NAME_ALIASES)): item
            for item in base._chemical_rows(project)
        }
        fallback = []
        for idx, row in enumerate(base._facility_rows(project), 1):
            material = base._row_value(row, "취급물질", "물질명")
            chem = chemicals.get(base._norm(material), {})
            fallback.append([
                str(idx),
                base._row_value(row, "설비번호", "구분기호", "장치번호"),
                base._row_value(row, "설비명", "장치·설비명", "장치명"),
                material,
                base._row_value(chem, *_CAS_ALIASES),
                base._row_value(chem, "물리적 상태", "물질상태"),
                base._row_value(chem, "함량(%)", "함량"),
                base._row_value(row, "연결구 크기", "호칭경"),
                base._row_value(row, "설계압력"),
                base._row_value(row, "운전압력"),
                base._row_value(row, "설계온도"),
                base._row_value(row, "운전온도"),
                base._row_value(row, "용량", "설계용량"),
                base._row_value(row, "최대보유량(kg)", "취급량", "최대보유량"),
                base._row_value(row, "비고", "P&ID 번호"),
            ])
        _fill_table_rows(table, _sanitize_rows(fallback), header_rows=2)

def _fill_form10(table, project: Stage2Project) -> None:
    prepared = build_cap_form10_data(project)
    rows = [
        [
            row.get("연번", ""),
            row.get("설비형태", ""),
            row.get("구분기호", ""),
            row.get("장치·설비명", ""),
            row.get("설계용량", ""),
            row.get("설비종류", ""),
            row.get("필요용량", ""),
            row.get("유효용량", ""),
            row.get("검토결과", ""),
            row.get("비고", ""),
        ]
        for row in prepared.rows
    ]
    _fill_table_rows(table, _sanitize_rows(rows), header_rows=2)
    if not rows:
        fallback = []
        for idx, row in enumerate(base._rows(project, "cap.safety.dike_layout"), 1):
            fallback.append([
                str(idx), base._row_value(row, "설비형태"),
                base._row_value(row, "구분기호", "설비번호"),
                base._row_value(row, "장치·설비명", "설비명"),
                base._row_value(row, "설계용량"),
                base._row_value(row, "설비종류"),
                base._row_value(row, "필요용량"),
                base._row_value(row, "유효용량"),
                base._row_value(row, "검토결과"),
                base._row_value(row, "비고"),
            ])
        _fill_table_rows(table, _sanitize_rows(fallback), header_rows=2)

def _fill_form11(table, project: Stage2Project) -> None:
    prepared = build_cap_form11_data(project)
    rows = [
        [
            row.get("연번", ""),
            row.get("구분기호", ""),
            row.get("감지대상", ""),
            row.get("설치위치", ""),
            row.get("작동시간", ""),
            row.get("측정방식", ""),
            row.get("경보설정값", ""),
            row.get("경보기 설치장소", ""),
            row.get("연동여부", ""),
            row.get("정밀도", ""),
            row.get("유지관리", ""),
            row.get("비고", ""),
        ]
        for row in prepared.rows
    ]
    _fill_table_rows(table, _sanitize_rows(rows), header_rows=1)
    if not rows:
        fallback = []
        for idx, row in enumerate(base._rows(project, "cap.safety.gas_detection", "psm.psi.gas_detection"), 1):
            fallback.append([
                str(idx),
                base._row_value(row, "감지기 번호", "구분기호", "감지기번호"),
                base._row_value(row, "검출대상 물질", "감지대상"),
                base._row_value(row, "설치위치", "설치장소"),
                base._row_value(row, "작동시간"),
                base._row_value(row, "감지방식", "측정방식"),
                base._row_value(row, "경보 설정값", "경보설정값"),
                base._row_value(row, "경보 위치", "경보기 설치장소"),
                base._row_value(row, "연동여부"),
                base._row_value(row, "정밀도"),
                base._row_value(row, "유지관리", "점검주기"),
                base._row_value(row, "비고", "관련 도면번호"),
            ])
        _fill_table_rows(table, _sanitize_rows(fallback), header_rows=1)

def _fill_form12(tables, project: Stage2Project) -> None:
    scenario_table, list_table = tables
    prepared = build_cap_form12_data(project)

    if prepared.rows:
        first = prepared.rows[0]
        _fill_label_rows(
            scenario_table,
            {
                "사고시나리오명": first.get("사고시나리오명", ""),
                "사고시나리오 명": first.get("사고시나리오명", ""),
                "유해화학물질명": first.get("유해화학물질명", ""),
                "대상 설비번호": first.get("대상 설비번호", ""),
                "사고유형": first.get("사고유형", ""),
                "장외거리": first.get("장외거리(m)", ""),
                "장외거리(m)": first.get("장외거리(m)", ""),
                "거주민수": first.get("거주민수", ""),
                "근로자수": first.get("근로자수", ""),
                "사고원점의 좌표": first.get("사고원점 좌표", ""),
                "사고원점 좌표": first.get("사고원점 좌표", ""),
            },
            start=1,
        )
        summaries = []
        for row in prepared.rows:
            summaries.append(
                " / ".join(
                    part for part in (
                        f"시나리오: {_clean(row.get('사고시나리오명'))}",
                        f"물질: {_clean(row.get('유해화학물질명'))}",
                        f"설비: {_clean(row.get('대상 설비번호'))}",
                        f"사고유형: {_clean(row.get('사고유형'))}",
                        f"장외거리: {_clean(row.get('장외거리(m)'))} m",
                        f"거주민: {_clean(row.get('거주민수'))}명",
                        f"근로자: {_clean(row.get('근로자수'))}명",
                        f"사고원점: {_clean(row.get('사고원점 좌표'))}",
                        f"근거: {_clean(row.get('KORA/GIS 근거'))}",
                    )
                    if part and not part.endswith(": ")
                )
            )
        if len(scenario_table.rows) > 1:
            cells = _unique_cells(scenario_table.rows[1])
            if cells:
                _append_value(cells[-1], "\n".join(summaries))

    # Form 12 protected-target rows are scenario-specific. Do not reuse the
    # overall Form 13 target list unless the company/GIS data explicitly names
    # the scenario to which each target belongs.
    source_targets = base._rows(project, "cap.offsite.population_and_protected_targets")
    scenario_names = {_clean(row.get("사고시나리오명")) for row in prepared.rows}
    rows = []
    for idx, row in enumerate(source_targets, 1):
        scenario = _clean(base._row_value(row, "사고시나리오명", "시나리오명"))
        if not scenario or scenario not in scenario_names:
            continue
        rows.append([
            str(idx),
            base._row_value(row, "보호대상 종류", "세부유형", "종류"),
            base._row_value(row, "보호대상 명칭", "명칭"),
            base._row_value(row, "장외거리(m)", "사업장 경계와 거리(m)", "거리(m)"),
        ])
    _fill_table_rows(list_table, _sanitize_rows(rows), header_rows=1)

def _fill_form13(tables, project: Stage2Project) -> None:
    overall_table, list_table, freq_table, safety_table, protected_summary_table = tables
    form13 = build_cap_form13_data(project)
    form14 = build_cap_form14_data(project)
    form15 = build_cap_form15_data(project)

    if form13.summary:
        summary = form13.summary
        _fill_label_rows(
            overall_table,
            {
                "총괄영향범위 산출방법": summary.get("총괄영향범위 산출방법", ""),
                "총괄영향범위 결과 요약": summary.get("총괄영향범위 결과 요약", ""),
                "거주민수": summary.get("총괄영향범위 내 거주민수", ""),
                "근로자수": summary.get("총괄영향범위 내 근로자수", ""),
                "보호대상 없음 여부": summary.get("보호대상 없음 여부", ""),
                "GIS/KORA 근거": summary.get("GIS/KORA 근거", ""),
            },
            start=1,
        )
        _fill_text_block(
            overall_table,
            " / ".join(
                f"{key}: {value}"
                for key, value in summary.items()
                if _clean(value)
            ),
            header_rows=1,
        )

    target_rows = [
        [
            row.get("일련번호", ""),
            row.get("보호대상 명칭", ""),
            row.get("보호대상 종류", ""),
        ]
        for row in form13.protected_targets
    ]
    if form13.no_protected_targets and not target_rows:
        target_rows = [["-", "해당 없음", "-"]]
    _fill_table_rows(list_table, _sanitize_rows(target_rows), header_rows=1)

    event_rows = [
        [
            str(index),
            (
                f"[{_clean(row.get('사고시나리오명'))}] {_clean(row.get('개시사건'))}"
                if len(form14.scenario_rows) > 1
                else row.get("개시사건", "")
            ),
            row.get("기준빈도(/연)", ""),
            row.get("개수", ""),
            row.get("사고빈도(/연)", ""),
        ]
        for index, row in enumerate(form14.event_rows, 1)
    ]
    _fill_table_rows(freq_table, _sanitize_rows(event_rows), header_rows=1)

    safety_lines = []
    for row in form14.scenario_rows:
        parts = [
            f"시나리오: {_clean(row.get('사고시나리오명'))}",
            f"수동적 완화장치: {_clean(row.get('수동적 완화장치'))}",
            f"능동적 완화장치: {_clean(row.get('능동적 완화장치'))}",
            f"증빙: {_clean(row.get('안전성확보설비 증빙'))}",
        ]
        safety_lines.append(" / ".join(part for part in parts if not part.endswith(": ")))
    _fill_text_block(safety_table, "\n".join(safety_lines), header_rows=1)

    protected_lines = []
    for row in form15.scenario_rows:
        protected_lines.append(
            " / ".join(
                part for part in (
                    f"시나리오: {_clean(row.get('사고시나리오 명'))}",
                    f"갑종: {_clean(row.get('갑종 보호대상 수'))}",
                    f"을종: {_clean(row.get('을종 보호대상 수'))}",
                    f"환경수용체: {_clean(row.get('환경수용체 수'))}",
                    f"장외거리: {_clean(row.get('사고시나리오 거리(장외)'))} m",
                    f"주민수: {_clean(row.get('위험도 주민수'))}",
                )
                if not part.endswith(": ")
            )
        )
    _fill_text_block(protected_summary_table, "\n".join(protected_lines), header_rows=1)

def _fill_form15(tables, project: Stage2Project) -> None:
    list_table, total_table, score_table = tables
    prepared = build_cap_form15_data(project)

    rows = [
        [
            row.get("연번", ""),
            row.get("사고시나리오 명", ""),
            row.get("사고시나리오 시설빈도", ""),
            row.get("사고시나리오 거리(장외)", ""),
            row.get("위험도 주민수", ""),
        ]
        for row in prepared.scenario_rows
    ]
    _fill_table_rows(list_table, _sanitize_rows(rows), header_rows=1)

    totals = prepared.totals or {}
    if len(total_table.rows) > 1:
        total_cells = _unique_cells(total_table.rows[1])
        values = (
            totals.get("사고시나리오 총 개수(A)", ""),
            totals.get("사고시나리오 시설빈도의 합(B)", ""),
            totals.get("사고시나리오 거리의 합(C)", ""),
            totals.get("주민수 합(D)", ""),
        )
        for offset, value in enumerate(values, start=1):
            if offset < len(total_cells):
                _write_cell(total_cells[offset], value)

    scores = prepared.scores or {}
    if len(score_table.rows) > 1:
        score_cells = _unique_cells(score_table.rows[1])
        if score_cells:
            _write_cell(score_cells[0], scores.get("사고빈도점수(A+B)", ""))
        if len(score_cells) > 1:
            _write_cell(score_cells[1], scores.get("사고영향점수(C+D)", ""))
    _fill_label_rows(
        score_table,
        {
            "사고빈도점수(A+B)": scores.get("사고빈도점수(A+B)", ""),
            "사고영향점수(C+D)": scores.get("사고영향점수(C+D)", ""),
            "위험도 판정표 점수(증감 전)": scores.get("위험도 판정표 점수(증감 전)", ""),
            "증감 전 위험도": scores.get("증감 전 위험도", ""),
            "최종 위험도": scores.get("최종 위험도", ""),
        },
        start=0,
    )

def _fill_form16(tables, project: Stage2Project) -> None:
    (
        info_table, chem_table, protection_types_table, protection_list_table,
        contacts_table, notice_table, coordination_table, evacuation_table,
        local_gov_table, hospital_table, shelter_table, disclosure_table,
    ) = tables

    prepared = build_cap_form16_data(project)
    form13 = build_cap_form13_data(project)
    business = prepared.business
    contact_display = " / ".join(
        part for part in (
            _clean(business.get("담당자")),
            _clean(business.get("담당자 연락처")),
            _clean(business.get("담당자 메일주소")),
        )
        if part
    )
    mapping = {
        "사업장명": business.get("사업장명", ""),
        "대표자": business.get("대표자", ""),
        "우편번호/주소": business.get("우편번호/주소", ""),
        "사업자 등록번호": business.get("사업자 등록번호", ""),
        "담당자 및 연락처": contact_display,
        "담당자": business.get("담당자", ""),
        "담당자 연락처": business.get("담당자 연락처", ""),
        "담당자 메일주소": business.get("담당자 메일주소", ""),
        "작성일": business.get("작성일", ""),
    }
    _fill_label_rows(info_table, mapping, start=1)

    chem_rows = [
        [
            row.get("연번", ""),
            row.get("유해화학물질명", ""),
            row.get("화학물질식별번호(CAS 번호)", ""),
            row.get("최대함량(%)", ""),
            row.get("최대보유량(ton)", ""),
            row.get("사고유형", ""),
        ]
        for row in prepared.chemical_rows
    ]
    _fill_table_rows(chem_table, _sanitize_rows(chem_rows), header_rows=1)

    protection_rows = [
        [
            row.get("일련번호", ""),
            row.get("보호대상 구분", ""),
            row.get("보호대상 종류", ""),
        ]
        for row in form13.protected_targets
    ]
    if form13.no_protected_targets and not protection_rows:
        protection_rows = [["-", "해당 없음", "-"]]
    _fill_table_rows(protection_types_table, _sanitize_rows(protection_rows), header_rows=1)

    protection_list_rows = [
        [
            row.get("일련번호", ""),
            row.get("보호대상 종류", ""),
            row.get("보호대상 명칭", ""),
            row.get("사업장 경계와 거리(m)", ""),
            row.get("GIS 근거", ""),
        ]
        for row in form13.protected_targets
    ]
    if form13.no_protected_targets and not protection_list_rows:
        protection_list_rows = [["-", "-", "해당 없음", "-", form13.summary.get("GIS/KORA 근거", "")]]
    _fill_table_rows(protection_list_table, _sanitize_rows(protection_list_rows), header_rows=1)

    # Legacy structured tables remain supported. If the company supplied only
    # narrative confirmed facts, keep the original table structure and place
    # that narrative in its first answer row instead of inventing columns.
    contact_rows = []
    for row in base._rows(project, "cap.prevention.emergency_system"):
        contact_rows.append([
            base._row_value(row, "관계기관"), base._row_value(row, "전화번호"),
            base._row_value(row, "관계기관2", "관계기관"), base._row_value(row, "전화번호2", "전화번호"),
        ])
    _fill_table_rows(contacts_table, _sanitize_rows(contact_rows), header_rows=1)
    if not contact_rows:
        _fill_text_block(
            contacts_table,
            _confirmed_text(
                project,
                "cap.prevention.emergency_contact_system",
                "cap.external.mutual_aid_contacts",
            ),
            header_rows=1,
        )

    notice_rows = []
    for row in base._rows(project, "cap.external.community_coordination"):
        notice_rows.append([
            base._row_value(row, "대상 기관(협의체)명", "기관명"),
            base._row_value(row, "제공 정보"),
            base._row_value(row, "제공 방법"),
            base._row_value(row, "제공 시기"),
        ])
    _fill_table_rows(notice_table, _sanitize_rows(notice_rows), header_rows=1)
    if not notice_rows:
        _fill_text_block(
            notice_table,
            _confirmed_text(
                project,
                "cap.external.stakeholders",
                "cap.external.communication_plan",
                "cap.external.communication_schedule",
            ),
            header_rows=1,
        )

    coordination_rows = []
    for row in base._rows(project, "cap.external.community_coordination"):
        coordination_rows.append([
            base._row_value(row, "종류"), base._row_value(row, "참석 대상"),
            base._row_value(row, "일정"), base._row_value(row, "장소"),
            base._row_value(row, "소통방법"),
        ])
    _fill_table_rows(coordination_table, _sanitize_rows(coordination_rows), header_rows=1)
    if not coordination_rows:
        _fill_text_block(
            coordination_table,
            _confirmed_text(
                project,
                "cap.external.communication_plan",
                "cap.external.mutual_aid_contacts",
                "cap.external.resource_support",
                "cap.external.joint_drill_plan",
            ),
            header_rows=1,
        )

    evac_rows = []
    for row in base._rows(project, "cap.external.evacuation"):
        evac_rows.append([
            base._row_value(row, "구분"), base._row_value(row, "대상 명칭"),
            base._row_value(row, "대피경보 방법"), base._row_value(row, "연락처"),
            base._row_value(row, "담당자"),
        ])
    _fill_table_rows(evacuation_table, _sanitize_rows(evac_rows), header_rows=1)
    if not evac_rows:
        _fill_text_block(
            evacuation_table,
            _confirmed_text(project, "cap.external.warning_system", "cap.external.evacuation_routes"),
            header_rows=1,
        )

    local_gov_rows = []
    for row in base._rows(project, "cap.external.evacuation"):
        local_gov_rows.append([
            base._row_value(row, "지자체ㆍ협의체명", "지자체명"),
            base._row_value(row, "담당부서"), base._row_value(row, "대상"),
            base._row_value(row, "대피경보 방법"), base._row_value(row, "연락처"),
        ])
    _fill_table_rows(local_gov_table, _sanitize_rows(local_gov_rows), header_rows=1)
    if not local_gov_rows:
        _fill_text_block(
            local_gov_table,
            _confirmed_text(project, "cap.external.mutual_aid_contacts", "cap.external.warning_system"),
            header_rows=1,
        )

    hospital_rows = []
    for row in base._rows(project, "cap.external.evacuation"):
        if not base._row_value(row, "병원명"):
            continue
        hospital_rows.append([
            base._row_value(row, "구분"), base._row_value(row, "병원명"),
            base._row_value(row, "주소"), base._row_value(row, "전화번호"),
        ])
    _fill_table_rows(hospital_table, _sanitize_rows(hospital_rows), header_rows=1)
    if not hospital_rows:
        _fill_text_block(
            hospital_table,
            _confirmed_text(project, "cap.external.medical_contacts"),
            header_rows=1,
        )

    shelter_rows = []
    for row in base._rows(project, "cap.external.evacuation"):
        if not base._row_value(row, "대피장소"):
            continue
        shelter_rows.append([
            base._row_value(row, "대피장소"), base._row_value(row, "수용 인원"),
            base._row_value(row, "사업장으로부터 거리(m)", "거리"),
            base._row_value(row, "연락처"),
        ])
    _fill_table_rows(shelter_table, _sanitize_rows(shelter_rows), header_rows=1)
    if not shelter_rows:
        _fill_text_block(
            shelter_table,
            _confirmed_text(project, "cap.external.shelters", "cap.external.evacuation_routes"),
            header_rows=1,
        )

    disclosure_rows = []
    for row in base._rows(project, "cap.external.community_notice"):
        disclosure_rows.append([
            base._row_value(row, "고지 방법", "방법"),
            base._row_value(row, "고지 대상 목록", "대상"),
            base._row_value(row, "고지 예정 시기", "시기"),
        ])
    _fill_table_rows(disclosure_table, _sanitize_rows(disclosure_rows), header_rows=1)
    if not disclosure_rows:
        _fill_text_block(
            disclosure_table,
            _confirmed_text(
                project,
                "cap.external.notice_method",
                "cap.external.notice_targets",
                "cap.external.notice_content",
            ),
            header_rows=1,
        )

def build_cap_baseline_draft(project: Stage2Project) -> bytes:
    if not project.cap_in_scope:
        raise ValueError("화학사고예방관리계획서는 현재 작성범위에 포함되어 있지 않습니다.")
    doc = Document(BytesIO(load_cap_baseline_bytes()))
    tables = doc.tables
    total_forms = sum(len(v) for v in FORM_TABLE_INDEX.values())
    if len(tables) < 6 + total_forms:
        raise ValueError("CAP 규정서식 baseline 구조가 예상과 달라 자동작성을 중단했습니다.")

    _fill_form1([tables[i] for i in FORM_TABLE_INDEX["1"]], project)
    _fill_form2([tables[i] for i in FORM_TABLE_INDEX["2"]], project)
    _fill_form3(tables[FORM_TABLE_INDEX["3"][0]], project)
    _fill_facility_overview(tables[FORM_TABLE_INDEX["4"][0]], project, detailed=False)
    _fill_facility_overview(tables[FORM_TABLE_INDEX["5"][0]], project, detailed=True)
    _fill_form6(tables[FORM_TABLE_INDEX["6"][0]], project)
    _fill_form7(tables[FORM_TABLE_INDEX["7"][0]], project)
    _fill_form8([tables[i] for i in FORM_TABLE_INDEX["8"]], project)
    _fill_form9(tables[FORM_TABLE_INDEX["9"][0]], project)
    _fill_form10(tables[FORM_TABLE_INDEX["10"][0]], project)
    _fill_form11(tables[FORM_TABLE_INDEX["11"][0]], project)
    _fill_form12([tables[i] for i in FORM_TABLE_INDEX["12"]], project)
    _fill_form13([tables[i] for i in FORM_TABLE_INDEX["13"]], project)
    _fill_form15([tables[i] for i in FORM_TABLE_INDEX["15"]], project)
    _fill_form16([tables[i] for i in FORM_TABLE_INDEX["16"]], project)

    out = BytesIO()
    doc.save(out)
    return canonicalize_docx_zip(out.getvalue())


def cap_baseline_filename(project: Stage2Project) -> str:
    company = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", project.company_name or project.project_id).strip("._")
    company = company or "사업장"
    return f"{company}_화학사고예방관리계획서_규정서식_작성본.docx"
