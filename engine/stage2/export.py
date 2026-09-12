from __future__ import annotations

from io import BytesIO
import json

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .completeness import evaluate_project_completeness
from .project import Stage2Project


HEADER_FILL = PatternFill("solid", fgColor="D9EAF7")


def _header(ws, row: int, values: list[str]) -> None:
    for col, value in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col, value=value)
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="top", wrap_text=True)


def build_progress_workbook(project: Stage2Project) -> bytes:
    """Export an audit/progress workbook, not a statutory final submission form."""
    wb = Workbook()
    ws = wb.active
    ws.title = "프로젝트"
    rows = [
        ("프로젝트 ID", project.project_id),
        ("회사명", project.company_name),
        ("사업장명", project.site_name),
        ("공정안전보고서 대상", project.psm_required),
        ("화학사고예방관리계획서 대상", project.cap_required),
        ("화학사고예방관리계획서 작성수준", project.cap_group),
        ("Stage 1 원본 SHA-256", project.stage1_source_fingerprint),
        ("생성일", project.created_at),
        ("최종수정일", project.updated_at),
        ("스키마", project.schema_version),
    ]
    _header(ws, 1, ["항목", "값"])
    for r, (label, value) in enumerate(rows, start=2):
        ws.cell(r, 1, label)
        ws.cell(r, 2, "" if value is None else str(value))
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 70

    completeness = evaluate_project_completeness(project)
    ws2 = wb.create_sheet("작성현황")
    _header(ws2, 1, ["구분", "절", "작성항목", "상태", "완성도(%)", "미확인 필드", "AI 초안 필드", "HOLD 필드", "근거"])
    for r, item in enumerate(completeness["requirements"], start=2):
        values = [
            item["system"], item["section"], item["label"], item["state"],
            item["completion_pct"], ", ".join(item["missing_fields"]),
            ", ".join(item["draft_fields"]), ", ".join(item["hold_fields"]),
            item["legal_basis"],
        ]
        for c, value in enumerate(values, start=1):
            ws2.cell(r, c, value)
    for col, width in {"A": 12, "B": 22, "C": 28, "D": 18, "E": 14, "F": 45, "G": 40, "H": 40, "I": 55}.items():
        ws2.column_dimensions[col].width = width

    ws3 = wb.create_sheet("필드")
    _header(ws3, 1, ["field_key", "표시명", "값", "상태", "비고", "최종수정일", "증빙수"])
    for r, key in enumerate(sorted(project.fields), start=2):
        record = project.fields[key]
        if isinstance(record.value, (list, dict)):
            value = json.dumps(record.value, ensure_ascii=False, default=str)
        else:
            value = "" if record.value is None else str(record.value)
        values = [record.key, record.label, value, record.status, record.note, record.updated_at, len(record.evidence)]
        for c, cell_value in enumerate(values, start=1):
            ws3.cell(r, c, cell_value)
    for col, width in {"A": 34, "B": 28, "C": 80, "D": 18, "E": 50, "F": 28, "G": 10}.items():
        ws3.column_dimensions[col].width = width

    ws4 = wb.create_sheet("증빙목록")
    _header(ws4, 1, ["field_key", "표시명", "source_type", "source_name", "SHA-256", "page", "location", "note"])
    r = 2
    for key in sorted(project.fields):
        record = project.fields[key]
        for evidence in record.evidence:
            values = [key, record.label, evidence.source_type, evidence.source_name, evidence.sha256, evidence.page, evidence.location, evidence.note]
            for c, cell_value in enumerate(values, start=1):
                ws4.cell(r, c, cell_value)
            r += 1
    for col, width in {"A": 34, "B": 28, "C": 22, "D": 42, "E": 68, "F": 12, "G": 70, "H": 50}.items():
        ws4.column_dimensions[col].width = width

    for sheet in wb.worksheets:
        sheet.freeze_panes = "A2"
        for row in sheet.iter_rows():
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)

    out = BytesIO()
    wb.save(out)
    return out.getvalue()
