from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
import json
import re
from zipfile import ZIP_DEFLATED, ZipFile

from docx import Document
from docx.document import Document as DocumentObject
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from .completeness import evaluate_project_completeness
from .intake import field_label, selected_requirement_specs
from .project import CONFIRMED_STATUSES, FieldRecord, Stage2Project
from .requirements import RequirementSpec


PSM = "PSM"
CAP = "CAP"
SYSTEM_LABELS = {
    PSM: "공정안전보고서",
    CAP: "화학사고예방관리계획서",
}
PSM_SECTION_ORDER = (
    "사업개요",
    "공정안전자료",
    "공정위험성평가서",
    "안전운전계획",
    "비상조치계획",
)
CAP_SECTION_ORDER = (
    "기본정보",
    "시설정보",
    "장외평가정보",
    "사전관리방침",
    "내부 비상대응계획",
    "외부 비상대응계획",
)


@dataclass(frozen=True)
class DraftGenerationStatus:
    system: str
    system_label: str
    completion_pct: float
    state: str
    final_ready: bool
    missing_fields: tuple[str, ...]
    draft_fields: tuple[str, ...]
    hold_fields: tuple[str, ...]
    blocking_labels: tuple[str, ...]

    @property
    def unresolved_n(self) -> int:
        return len(set(self.missing_fields + self.draft_fields + self.hold_fields))


def _system_selected(project: Stage2Project, system: str) -> bool:
    return (system == PSM and project.psm_in_scope) or (system == CAP and project.cap_in_scope)


def _normalize_system(system: str) -> str:
    value = str(system or "").strip().upper()
    if value not in SYSTEM_LABELS:
        raise ValueError(f"지원하지 않는 보고서 종류입니다: {system}")
    return value


def _system_specs(project: Stage2Project, system: str) -> list[RequirementSpec]:
    system = _normalize_system(system)
    return [spec for spec in selected_requirement_specs(project) if spec.system == system]


def _canonical_section(system: str, section: str) -> str:
    text = str(section or "").strip()
    if system == CAP:
        text = re.sub(r"^\d+(?:\.\d+)*\s*", "", text).strip()
    return text or "기타 작성사항"


def _section_order(system: str, section: str) -> tuple[int, str]:
    canonical = _canonical_section(system, section)
    order = PSM_SECTION_ORDER if system == PSM else CAP_SECTION_ORDER
    try:
        return order.index(canonical), canonical
    except ValueError:
        return len(order), canonical


def report_generation_status(project: Stage2Project, system: str) -> DraftGenerationStatus:
    system = _normalize_system(system)
    if not _system_selected(project, system):
        raise ValueError(f"현재 작성범위에 {SYSTEM_LABELS[system]}이(가) 포함되어 있지 않습니다.")

    completeness = evaluate_project_completeness(project)
    summary_key = "psm" if system == PSM else "cap"
    summary = completeness[summary_key]

    missing: list[str] = []
    drafts: list[str] = []
    holds: list[str] = []
    blocking_labels: list[str] = []
    for item in completeness["requirements"]:
        if item["system"] not in {"COMMON", system}:
            continue
        if item["state"] in {"READY", "NOT_REQUIRED"}:
            continue
        blocking_labels.append(str(item["label"]))
        missing.extend(str(v) for v in item["missing_fields"])
        drafts.extend(str(v) for v in item["draft_fields"])
        holds.extend(str(v) for v in item["hold_fields"])

    return DraftGenerationStatus(
        system=system,
        system_label=SYSTEM_LABELS[system],
        completion_pct=float(summary.get("completion_pct", 0.0)),
        state=str(summary.get("state") or "HOLD"),
        final_ready=str(summary.get("state") or "") == "READY",
        missing_fields=tuple(dict.fromkeys(missing)),
        draft_fields=tuple(dict.fromkeys(drafts)),
        hold_fields=tuple(dict.fromkeys(holds)),
        blocking_labels=tuple(dict.fromkeys(blocking_labels)),
    )


def _safe_filename(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "_", str(value or "")).strip().strip(".")
    return value or "사업장"


def draft_filename(project: Stage2Project, system: str) -> str:
    system = _normalize_system(system)
    company = project.get_field("business.company_name")
    company_name = str(company.value).strip() if company and company.value not in (None, "") else project.company_name
    return f"{_safe_filename(company_name)}_{SYSTEM_LABELS[system]}_검토용_초안.docx"


def _set_cell_shading(cell, color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), color)


def _set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def _set_run_font(run, *, size: float | None = None, bold: bool | None = None, color: str | None = None) -> None:
    run.font.name = "Malgun Gothic"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def _configure_document(doc: DocumentObject) -> None:
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(1.8)
    section.bottom_margin = Cm(1.8)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)

    normal = doc.styles["Normal"]
    normal.font.name = "Malgun Gothic"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
    normal.font.size = Pt(10)
    normal.paragraph_format.space_after = Pt(5)
    normal.paragraph_format.line_spacing = 1.15

    for style_name, size in (("Title", 22), ("Heading 1", 16), ("Heading 2", 12)):
        style = doc.styles[style_name]
        style.font.name = "Malgun Gothic"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(31, 78, 121)

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run("검토용 초안 · ")
    _set_run_font(run, size=8, color="808080")
    run = footer.add_run()
    fld_char1 = OxmlElement("w:fldChar")
    fld_char1.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_char2 = OxmlElement("w:fldChar")
    fld_char2.set(qn("w:fldCharType"), "end")
    run._r.extend([fld_char1, instr, fld_char2])


def _add_cover(doc: DocumentObject, project: Stage2Project, status: DraftGenerationStatus) -> None:
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(70)
    title_run = paragraph.add_run(status.system_label)
    _set_run_font(title_run, size=23, bold=True, color="1F4E79")

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run("검토용 자동작성 초안")
    _set_run_font(run, size=15, bold=True, color="C00000")

    company_record = project.get_field("business.company_name")
    company = str(company_record.value).strip() if company_record and company_record.value not in (None, "") else project.company_name
    site_record = project.get_field("business.site_name")
    site = str(site_record.value).strip() if site_record and site_record.value not in (None, "") else project.site_name

    for text in filter(None, (company, site)):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(text)
        _set_run_font(r, size=12, bold=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(24)
    r = p.add_run(f"프로젝트 ID: {project.project_id}")
    _set_run_font(r, size=9, color="666666")

    generated = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(f"자동 생성: {generated}")
    _set_run_font(r, size=9, color="666666")

    doc.add_page_break()


def _add_notice(doc: DocumentObject, status: DraftGenerationStatus) -> None:
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    cell = table.cell(0, 0)
    _set_cell_shading(cell, "FFF2CC")
    p = cell.paragraphs[0]
    r = p.add_run(
        "본 문서는 회사가 확인한 사실·구조화 자료와 등록된 첨부자료 정보를 자동 배치한 검토용 초안입니다. "
        "법정 제출용 최종본이 아니며, 검증 보류(HOLD), AI 초안 또는 미확인 항목이 있으면 반드시 사람이 확인해야 합니다."
    )
    _set_run_font(r, size=9, bold=True)

    p = doc.add_paragraph()
    r = p.add_run(
        f"현재 작성완성도 {status.completion_pct:.1f}% · 상태 {status.state} · "
        f"미해결 필드 {status.unresolved_n}건"
    )
    _set_run_font(r, size=9, bold=True, color="1F4E79")
    if status.final_ready:
        p = doc.add_paragraph()
        r = p.add_run("현재 자료상태는 작성요건 기준 READY입니다. 다만 최종 법정 제출본 확정 기능은 별도 검증 gate를 거쳐야 합니다.")
        _set_run_font(r, size=9, color="008000")
    else:
        p = doc.add_paragraph()
        r = p.add_run("미확인·검증보류 항목이 남아 있으므로 이 파일은 검토용으로만 사용하십시오.")
        _set_run_font(r, size=9, bold=True, color="C00000")


def _value_is_empty(value: object) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _stringify(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _ordered_headers(rows: list[dict]) -> list[str]:
    headers: list[str] = []
    for row in rows:
        for key in row:
            text = str(key)
            if text not in headers:
                headers.append(text)
    return headers


def _add_structured_table(doc: DocumentObject, rows: list[dict]) -> None:
    if not rows:
        return
    headers = _ordered_headers(rows)
    if not headers:
        return
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    header_row = table.rows[0]
    _set_repeat_table_header(header_row)
    for idx, header in enumerate(headers):
        cell = header_row.cells[idx]
        cell.text = header
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        _set_cell_shading(cell, "D9EAF7")
        for run in cell.paragraphs[0].runs:
            _set_run_font(run, size=8, bold=True)
    for row in rows:
        cells = table.add_row().cells
        for idx, header in enumerate(headers):
            value = row.get(header, "")
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, default=str)
            cells[idx].text = _stringify(value)
            cells[idx].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
            for p in cells[idx].paragraphs:
                for run in p.runs:
                    _set_run_font(run, size=8)


def _add_mapping_table(doc: DocumentObject, mapping: dict) -> None:
    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    for key, value in mapping.items():
        row = table.add_row().cells
        row[0].text = str(key)
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, default=str)
        row[1].text = _stringify(value)
        _set_cell_shading(row[0], "F2F2F2")
        for run in row[0].paragraphs[0].runs:
            _set_run_font(run, size=9, bold=True)
        for run in row[1].paragraphs[0].runs:
            _set_run_font(run, size=9)


def _status_prefix(record: FieldRecord | None) -> str:
    if record is None:
        return "[확인 필요]"
    if record.status in CONFIRMED_STATUSES:
        return ""
    if record.status == "AI_DRAFT":
        return "[AI 초안 · 사람 검토 필요]"
    return "[검증 보류]"


def _add_evidence_note(doc: DocumentObject, record: FieldRecord) -> None:
    if not record.evidence:
        return
    parts: list[str] = []
    for evidence in record.evidence:
        detail = evidence.source_name or evidence.source_type
        if evidence.page:
            detail += f" (p.{evidence.page})"
        if detail and detail not in parts:
            parts.append(detail)
    if not parts:
        return
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.5)
    r = p.add_run("근거자료: " + ", ".join(parts))
    _set_run_font(r, size=8, color="666666")


def _add_field_record(doc: DocumentObject, key: str, record: FieldRecord | None) -> None:
    label = field_label(key)
    prefix = _status_prefix(record)

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(4)
    label_run = p.add_run((prefix + " " if prefix else "") + label)
    _set_run_font(
        label_run,
        size=9,
        bold=True,
        color="C00000" if prefix else "1F1F1F",
    )

    if record is None or _value_is_empty(record.value):
        p = doc.add_paragraph()
        r = p.add_run("자료가 등록되지 않았습니다.")
        _set_run_font(r, size=9, color="C00000")
        return

    value = record.value
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            _add_structured_table(doc, [dict(item) for item in value])
        else:
            for item in value:
                p = doc.add_paragraph(style="List Bullet")
                r = p.add_run(_stringify(item))
                _set_run_font(r, size=9)
    elif isinstance(value, dict):
        _add_mapping_table(doc, value)
    else:
        for idx, line in enumerate(str(value).splitlines() or [str(value)]):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.2)
            r = p.add_run(line)
            _set_run_font(r, size=9)

    if record.note:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.5)
        r = p.add_run("비고: " + record.note)
        _set_run_font(r, size=8, color="666666")
    _add_evidence_note(doc, record)


def _group_specs(project: Stage2Project, system: str) -> list[tuple[str, list[RequirementSpec]]]:
    groups: dict[str, list[RequirementSpec]] = {}
    for spec in _system_specs(project, system):
        section = _canonical_section(system, spec.section)
        groups.setdefault(section, []).append(spec)
    return sorted(groups.items(), key=lambda item: _section_order(system, item[0]))


def _add_project_overview(doc: DocumentObject, project: Stage2Project, system: str) -> None:
    doc.add_heading("문서 기본정보", level=1)
    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    rows = [
        ("프로젝트 ID", project.project_id),
        ("회사명", project.get_field("business.company_name").value if project.get_field("business.company_name") else project.company_name),
        ("사업장명", project.get_field("business.site_name").value if project.get_field("business.site_name") else project.site_name),
        ("사업장 소재지", project.get_field("business.address").value if project.get_field("business.address") else "[확인 필요]"),
    ]
    if system == CAP:
        rows.append(("작성수준", project.cap_group or "[확인 필요]"))
    for label, value in rows:
        cells = table.add_row().cells
        cells[0].text = label
        cells[1].text = _stringify(value)
        _set_cell_shading(cells[0], "D9EAF7")
        for run in cells[0].paragraphs[0].runs:
            _set_run_font(run, size=9, bold=True)
        for run in cells[1].paragraphs[0].runs:
            _set_run_font(run, size=9)


def _add_requirement(doc: DocumentObject, project: Stage2Project, spec: RequirementSpec) -> None:
    doc.add_heading(spec.label, level=2)
    if spec.legal_basis:
        p = doc.add_paragraph()
        r = p.add_run("작성근거: " + spec.legal_basis)
        _set_run_font(r, size=8, color="666666")
    if not spec.field_keys:
        p = doc.add_paragraph()
        r = p.add_run("[확인 필요] 현재 registry에 직접 연결된 회사 입력 필드가 없습니다. 사람이 작성 여부를 확인해야 합니다.")
        _set_run_font(r, size=9, color="C00000")
        return
    for key in spec.field_keys:
        _add_field_record(doc, key, project.get_field(key))


def _add_unresolved_appendix(doc: DocumentObject, project: Stage2Project, status: DraftGenerationStatus) -> None:
    doc.add_page_break()
    doc.add_heading("검토 필요 항목", level=1)
    if status.final_ready:
        p = doc.add_paragraph()
        r = p.add_run("현재 작성요건 기준으로 미확인·검증보류 필드가 없습니다.")
        _set_run_font(r, size=9, color="008000")
        return

    if status.blocking_labels:
        p = doc.add_paragraph()
        r = p.add_run("완료되지 않은 작성항목: " + ", ".join(status.blocking_labels))
        _set_run_font(r, size=9, bold=True, color="C00000")

    rows: list[tuple[str, str, str]] = []
    for key in status.missing_fields:
        rows.append(("미확인", field_label(key), "자료가 등록되지 않음"))
    for key in status.draft_fields:
        record = project.get_field(key)
        rows.append(("AI 초안", field_label(key), record.note if record else "사람 검토 필요"))
    for key in status.hold_fields:
        record = project.get_field(key)
        note = record.note if record else "검증 보류"
        if record and record.evidence:
            note = (note + " / " if note else "") + "근거자료 접수됨"
        rows.append(("검증 보류", field_label(key), note))

    if not rows:
        p = doc.add_paragraph()
        r = p.add_run("요건 단위 HOLD가 있으나 필드 단위 미해결값은 별도 표시되지 않았습니다. 작성근거와 registry를 확인하십시오.")
        _set_run_font(r, size=9, color="C00000")
        return

    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for idx, header in enumerate(("상태", "항목", "확인사항")):
        table.rows[0].cells[idx].text = header
        _set_cell_shading(table.rows[0].cells[idx], "D9EAF7")
        for run in table.rows[0].cells[idx].paragraphs[0].runs:
            _set_run_font(run, size=9, bold=True)
    _set_repeat_table_header(table.rows[0])
    for state, label, note in rows:
        cells = table.add_row().cells
        cells[0].text = state
        cells[1].text = label
        cells[2].text = note
        for cell in cells:
            for run in cell.paragraphs[0].runs:
                _set_run_font(run, size=8)


def build_report_draft(project: Stage2Project, system: str) -> bytes:
    """Build a deterministic review-only DOCX from registered Stage-2 facts.

    The function never invents missing company facts. Missing, AI-draft and HOLD
    fields are explicitly marked for human review. A READY state does not turn
    this into a statutory final submission form; it remains a review draft.
    """
    system = _normalize_system(system)
    status = report_generation_status(project, system)

    doc = Document()
    _configure_document(doc)
    _add_cover(doc, project, status)
    _add_notice(doc, status)
    _add_project_overview(doc, project, system)

    for section, specs in _group_specs(project, system):
        doc.add_page_break()
        doc.add_heading(section, level=1)
        for spec in specs:
            _add_requirement(doc, project, spec)

    _add_unresolved_appendix(doc, project, status)

    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def build_draft_bundle(project: Stage2Project) -> bytes:
    """Return a ZIP containing every report draft in the selected authoring scope."""
    if not project.scope_confirmed or not (project.psm_in_scope or project.cap_in_scope):
        raise ValueError("먼저 작성범위를 선택해야 보고서 초안을 생성할 수 있습니다.")

    out = BytesIO()
    manifest_lines = [
        "Stage 2 보고서 검토용 초안 묶음",
        f"프로젝트 ID: {project.project_id}",
        "주의: 본 파일들은 법정 제출용 최종본이 아닙니다.",
        "",
    ]
    with ZipFile(out, "w", compression=ZIP_DEFLATED) as archive:
        for system in (PSM, CAP):
            if not _system_selected(project, system):
                continue
            status = report_generation_status(project, system)
            filename = draft_filename(project, system)
            archive.writestr(filename, build_report_draft(project, system))
            manifest_lines.append(
                f"- {SYSTEM_LABELS[system]}: 작성완성도 {status.completion_pct:.1f}%, "
                f"상태 {status.state}, 미해결 필드 {status.unresolved_n}건"
            )
        archive.writestr("생성상태.txt", "\n".join(manifest_lines).encode("utf-8"))
    return out.getvalue()
