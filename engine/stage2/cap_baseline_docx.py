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
    unit_plant = base._text(project, "cap.business.unit_plant_name", default="")
    if unit_plant:
        _append_value(context_cells[3], unit_plant)

    change_log = base._rows(project, "cap.prevention.change_log")
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
    _fill_label_rows(table, mapping, start=1)


def _fill_facility_overview(table, project: Stage2Project) -> None:
    prepared = build_cap_form1_data(project)
    chem_lines = [
        " / ".join(
            part for part in (
                _clean(row.get("물질명")),
                _clean(row.get("CAS No.")),
                (f"{_clean(row.get('사업장 내 최대보유량(ton)'))} ton"
                 if _clean(row.get("사업장 내 최대보유량(ton)")) else ""),
            )
            if part
        )
        for row in prepared.chemical_rows[:12]
    ]
    mapping = {
        "단위공장 구성": base._text(project, "cap.basic.unit_facility_overview", default=""),
        "공정개요": base._text(project, "process.description", default=""),
        "장치 ․ 설비 종류 및 수량": render_facility_type_counts(project),
        "입·출하 및 운반시설": render_loading_transport(
            base._text(project, "cap.basic.loading_transport", default="")
        ),
        "유해화학물질 및 취급량": "\n".join(line for line in chem_lines if line),
    }
    _fill_label_rows(table, mapping, start=1)


def _fill_form6(table, project: Stage2Project) -> None:
    rows = []
    for idx, row in enumerate(base._chemical_rows(project), 1):
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
    source = base._value(project, "cap.chemical.hazard_information", default="")
    items: list[Mapping[str, object]] = []
    if isinstance(source, list):
        items = [dict(v) for v in source if isinstance(v, Mapping)]
    elif isinstance(source, Mapping):
        items = [dict(source)]
    if not items:
        return

    row = items[0]
    mapping = {
        "물질명": base._row_value(row, *_CHEMICAL_NAME_ALIASES),
        "화학물질식별번호(CAS 번호)": base._row_value(row, *_CAS_ALIASES),
        "유해화학물질 고유번호": base._row_value(row, "고유번호"),
        "농도(또는 함량 %)": base._row_value(row, "농도", "함량"),
        "최대보유량": base._row_value(row, "최대보유량"),
        "인체유해성": base._row_value(row, "인체유해성"),
        "물리적 위험성": base._row_value(row, "물리적 위험성"),
        "환경유해성": base._row_value(row, "환경유해성"),
        "출처": base._row_value(row, "출처"),
        "선정 사유": base._row_value(row, "선정 사유", "선정사유"),
    }
    _fill_single_column_labels(table, mapping)


def _fill_form8(tables, project: Stage2Project) -> None:
    context_table, list_table = tables
    _append_value(_unique_cells(context_table.rows[1])[0], base._text(project, "cap.site.surrounding_environment", default=""))
    spec = base.FormSpec("", "", ("일련번호", "보호대상 종류", "보호대상 명칭", "거리(m)"))
    rows = base._generic_form_rows(
        project, "cap.site.surrounding_environment", spec,
        (("일련번호", "연번"), ("보호대상 종류", "종류"), ("보호대상 명칭", "명칭"), ("거리", "거리(m)")),
    )
    _fill_table_rows(list_table, _sanitize_rows(rows), header_rows=1)


def _fill_form9(table, project: Stage2Project) -> None:
    chemicals = {base._norm(base._row_value(c, *_CHEMICAL_NAME_ALIASES)): c for c in base._chemical_rows(project)}
    rows = []
    for idx, row in enumerate(base._facility_rows(project), 1):
        material = base._row_value(row, "취급물질", "물질명")
        chem = chemicals.get(base._norm(material), {})
        rows.append([
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
    _fill_table_rows(table, _sanitize_rows(rows), header_rows=2)


def _fill_form10(table, project: Stage2Project) -> None:
    rows = []
    for idx, row in enumerate(base._rows(project, "cap.safety.dike_layout"), 1):
        rows.append([
            str(idx), base._row_value(row, "설비형태"), base._row_value(row, "구분기호", "설비번호"),
            base._row_value(row, "장치·설비명", "설비명"), base._row_value(row, "설계용량"),
            base._row_value(row, "설비종류"), base._row_value(row, "필요용량"), base._row_value(row, "유효용량"),
            base._row_value(row, "검토결과"), base._row_value(row, "비고"),
        ])
    _fill_table_rows(table, _sanitize_rows(rows), header_rows=2)


def _fill_form11(table, project: Stage2Project) -> None:
    rows = []
    for idx, row in enumerate(base._rows(project, "cap.safety.gas_detection", "psm.psi.gas_detection"), 1):
        rows.append([
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
    _fill_table_rows(table, _sanitize_rows(rows), header_rows=1)


def _fill_form12(tables, project: Stage2Project) -> None:
    scenario_table, list_table = tables
    range_result = base._text(project, "cap.offsite.impact_range_result", default="")
    if range_result:
        _append_value(_unique_cells(scenario_table.rows[1])[1], range_result)
    population = base._text(project, "cap.offsite.population_and_protected_targets", default="")
    if population:
        _append_value(_unique_cells(scenario_table.rows[2])[0], population)
    spec = base.FormSpec("", "", ("일련번호", "보호대상 종류", "보호대상 명칭", "장외거리(m)"))
    rows = base._generic_form_rows(
        project, "cap.offsite.population_and_protected_targets", spec,
        (("일련번호", "연번"), ("보호대상 종류", "종류"), ("보호대상 명칭", "명칭"), ("장외거리", "거리(m)")),
    )
    _fill_table_rows(list_table, _sanitize_rows(rows), header_rows=1)


def _fill_form13(tables, project: Stage2Project) -> None:
    _checkbox_table, list_table, freq_table, _blank, summary_table = tables
    spec = base.FormSpec("", "", ("일련번호", "보호대상 명칭", "보호대상 종류"))
    rows = base._generic_form_rows(
        project, "cap.offsite.population_and_protected_targets", spec,
        (("일련번호", "연번"), ("보호대상 명칭", "명칭"), ("보호대상 종류", "종류")),
    )
    _fill_table_rows(list_table, _sanitize_rows(rows), header_rows=1)

    freq_rows = []
    for idx, row in enumerate(base._rows(project, "cap.offsite.scenario_frequency"), 1):
        freq_rows.append([
            str(idx), base._row_value(row, "개시사건"), base._row_value(row, "빈도"),
            base._row_value(row, "개수"), base._row_value(row, "사고빈도"),
        ])
    if freq_rows:
        _fill_table_rows(freq_table, _sanitize_rows(freq_rows), header_rows=1)

    scores = base._value(project, "cap.offsite.risk_analysis", default={})
    if isinstance(scores, Mapping) and scores:
        mapping = {
            "보호대상 종류": base._row_value(scores, "보호대상 종류", "종류"),
            "보호대상 명칭": base._row_value(scores, "보호대상 명칭", "명칭"),
            "장외거리(m)": base._row_value(scores, "장외거리", "거리"),
            "주민수(개수)": base._row_value(scores, "주민수", "개수"),
        }
        _fill_label_rows(summary_table, mapping, start=2)


def _fill_form15(tables, project: Stage2Project) -> None:
    list_table, total_table, score_table = tables
    rows = []
    for idx, row in enumerate(base._rows(project, "cap.offsite.risk_analysis"), 1):
        rows.append([
            str(idx),
            base._row_value(row, "사고시나리오 명", "시나리오"),
            base._row_value(row, "사고시나리오 시설빈도", "시설 빈도"),
            base._row_value(row, "사고시나리오 거리(장외)", "장외거리"),
            base._row_value(row, "주민수"),
        ])
    _fill_table_rows(list_table, _sanitize_rows(rows), header_rows=1)

    scores = base._value(project, "cap.offsite.risk_analysis", default={})
    if isinstance(scores, Mapping) and scores:
        total_cells = _unique_cells(total_table.rows[1])
        _write_cell(total_cells[1], base._row_value(scores, "사고시나리오 총 개수", "A"))
        _write_cell(total_cells[2], base._row_value(scores, "사고시나리오 시설빈도의 합", "B"))
        _write_cell(total_cells[3], base._row_value(scores, "사고시나리오 거리의 합", "C"))
        _write_cell(total_cells[4], base._row_value(scores, "주민수 합", "D"))
        score_cells = _unique_cells(score_table.rows[1])
        _write_cell(score_cells[0], base._row_value(scores, "사고빈도점수", "A+B"))
        _write_cell(score_cells[1], base._row_value(scores, "사고영향점수", "C+D"))


def _fill_form16(tables, project: Stage2Project) -> None:
    (
        info_table, chem_table, protection_types_table, protection_list_table,
        contacts_table, notice_table, coordination_table, evacuation_table,
        local_gov_table, hospital_table, shelter_table, disclosure_table,
    ) = tables

    mapping = {
        "사업장명": project.company_name or "",
        "대표자": base._text(project, "cap.business.representative", default=""),
        "우편번호/주소": base._text(project, "business.address", default=""),
        "사업자 등록번호": base._text(project, "cap.business.registration_no", default=""),
        "담당자 및 연락처": base._text(project, "cap.business.writer_contact", default=""),
    }
    _fill_label_rows(info_table, mapping, start=1)

    chem_rows = []
    for idx, row in enumerate(base._chemical_rows(project), 1):
        chem_rows.append([
            str(idx),
            base._row_value(row, *_CHEMICAL_NAME_ALIASES),
            base._row_value(row, *_CAS_ALIASES),
            base._row_value(row, "함량(%)", "최대함량"),
            base._row_value(row, "최대보유량", "최대보유량(kg)"),
            base._row_value(row, "사고유형"),
        ])
    _fill_table_rows(chem_table, _sanitize_rows(chem_rows), header_rows=1)

    protection_rows = []
    for idx, row in enumerate(base._rows(project, "cap.offsite.population_and_protected_targets"), 1):
        protection_rows.append([str(idx), base._row_value(row, "종류"), base._row_value(row, "명칭")])
    _fill_table_rows(protection_types_table, _sanitize_rows(protection_rows), header_rows=1)

    protection_list_rows = []
    for idx, row in enumerate(base._rows(project, "cap.offsite.population_and_protected_targets"), 1):
        protection_list_rows.append([
            str(idx), base._row_value(row, "보호대상 종류", "종류"), base._row_value(row, "보호대상 명칭", "명칭"),
            base._row_value(row, "실제거리(m)", "거리"), base._row_value(row, "비고"),
        ])
    _fill_table_rows(protection_list_table, _sanitize_rows(protection_list_rows), header_rows=1)

    contact_rows = []
    for row in base._rows(project, "cap.prevention.emergency_system"):
        contact_rows.append([
            base._row_value(row, "관계기관"), base._row_value(row, "전화번호"),
            base._row_value(row, "관계기관2", "관계기관"), base._row_value(row, "전화번호2", "전화번호"),
        ])
    _fill_table_rows(contacts_table, _sanitize_rows(contact_rows), header_rows=1)

    notice_rows = []
    for row in base._rows(project, "cap.external.community_coordination"):
        notice_rows.append([
            base._row_value(row, "대상 기관(협의체)명", "기관명"), base._row_value(row, "제공 정보"),
            base._row_value(row, "제공 방법"), base._row_value(row, "제공 시기"),
        ])
    _fill_table_rows(notice_table, _sanitize_rows(notice_rows), header_rows=1)

    coordination_rows = []
    for row in base._rows(project, "cap.external.community_coordination"):
        coordination_rows.append([
            base._row_value(row, "종류"), base._row_value(row, "참석 대상"), base._row_value(row, "일정"),
            base._row_value(row, "장소"), base._row_value(row, "소통방법"),
        ])
    _fill_table_rows(coordination_table, _sanitize_rows(coordination_rows), header_rows=1)

    evac_rows = []
    for row in base._rows(project, "cap.external.evacuation"):
        evac_rows.append([
            base._row_value(row, "구분"), base._row_value(row, "대상 명칭"), base._row_value(row, "대피경보 방법"),
            base._row_value(row, "연락처"), base._row_value(row, "담당자"),
        ])
    _fill_table_rows(evacuation_table, _sanitize_rows(evac_rows), header_rows=1)

    local_gov_rows = []
    for row in base._rows(project, "cap.external.evacuation"):
        local_gov_rows.append([
            base._row_value(row, "지자체ㆍ협의체명", "지자체명"), base._row_value(row, "담당부서"),
            base._row_value(row, "대상"), base._row_value(row, "대피경보 방법"), base._row_value(row, "연락처"),
        ])
    _fill_table_rows(local_gov_table, _sanitize_rows(local_gov_rows), header_rows=1)

    hospital_rows = []
    for row in base._rows(project, "cap.external.evacuation"):
        if not base._row_value(row, "병원명"):
            continue
        hospital_rows.append([
            base._row_value(row, "구분"), base._row_value(row, "병원명"),
            base._row_value(row, "주소"), base._row_value(row, "전화번호"),
        ])
    _fill_table_rows(hospital_table, _sanitize_rows(hospital_rows), header_rows=1)

    shelter_rows = []
    for row in base._rows(project, "cap.external.evacuation"):
        if not base._row_value(row, "대피장소"):
            continue
        shelter_rows.append([
            base._row_value(row, "대피장소"), base._row_value(row, "수용 인원"),
            base._row_value(row, "사업장으로부터 거리(m)", "거리"), base._row_value(row, "연락처"),
        ])
    _fill_table_rows(shelter_table, _sanitize_rows(shelter_rows), header_rows=1)

    disclosure_rows = []
    for row in base._rows(project, "cap.external.community_notice"):
        disclosure_rows.append([
            base._row_value(row, "고지 방법", "방법"), base._row_value(row, "고지 대상 목록", "대상"),
            base._row_value(row, "고지 예정 시기", "시기"),
        ])
    _fill_table_rows(disclosure_table, _sanitize_rows(disclosure_rows), header_rows=1)


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
    _fill_facility_overview(tables[FORM_TABLE_INDEX["4"][0]], project)
    _fill_facility_overview(tables[FORM_TABLE_INDEX["5"][0]], project)
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
    return out.getvalue()


def cap_baseline_filename(project: Stage2Project) -> str:
    company = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", project.company_name or project.project_id).strip("._")
    company = company or "사업장"
    return f"{company}_화학사고예방관리계획서_규정서식_작성본.docx"
