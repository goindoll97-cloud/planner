from __future__ import annotations

from io import BytesIO
from typing import Mapping

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.shared import Pt, RGBColor

from .ai_drafting import ai_draft_field_key
from .intake import selected_requirement_specs
from .project import Stage2Project
from .report_draft import build_report_draft


def _run_font(run, *, size: float = 9, bold: bool = False, color: str = "1F1F1F") -> None:
    run.font.name = "Malgun Gothic"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
    run.font.size = Pt(size)
    run.bold = bold
    run.font.color.rgb = RGBColor.from_string(color)


def _insert_after(paragraph: Paragraph) -> Paragraph:
    new_p = OxmlElement("w:p")
    paragraph._p.addnext(new_p)
    return Paragraph(new_p, paragraph._parent)


def _draft_payload(project: Stage2Project, system: str, requirement_key: str) -> tuple[Mapping[str, object], str] | None:
    record = project.get_field(ai_draft_field_key(system, requirement_key))
    if record is None or not isinstance(record.value, Mapping):
        return None
    text = str(record.value.get("draft_text") or "").strip()
    if not text:
        return None
    return record.value, record.status


def has_ai_report_prose(project: Stage2Project, system: str) -> bool:
    system = str(system or "").strip().upper()
    for spec in selected_requirement_specs(project):
        if spec.system != system:
            continue
        if _draft_payload(project, system, spec.key):
            return True
    return False


def build_ai_enhanced_report_draft(project: Stage2Project, system: str) -> bytes:
    """Inject grounded AI prose immediately after matching requirement headings.

    The deterministic report remains the source-of-truth skeleton. AI prose is
    a separate overlay and never replaces the underlying confirmed field data.
    """
    system = str(system or "").strip().upper()
    base = build_report_draft(project, system)
    doc = Document(BytesIO(base))

    specs = [spec for spec in selected_requirement_specs(project) if spec.system == system]
    by_label = {spec.label: spec for spec in specs}
    inserted = 0

    for paragraph in list(doc.paragraphs):
        spec = by_label.get(paragraph.text.strip())
        if spec is None:
            continue
        payload_status = _draft_payload(project, system, spec.key)
        if payload_status is None:
            continue
        payload, status = payload_status
        draft_text = str(payload.get("draft_text") or "").strip()
        suggestions = payload.get("suggested_additions")

        marker = _insert_after(paragraph)
        marker.alignment = WD_ALIGN_PARAGRAPH.LEFT
        if status == "USER_CONFIRMED":
            run = marker.add_run("AI 보강문장 · 담당자 검토 완료")
            _run_font(run, size=8, bold=True, color="008000")
        else:
            run = marker.add_run("AI 보강 초안 · 사람 검토 필요")
            _run_font(run, size=8, bold=True, color="C00000")

        body = _insert_after(marker)
        for idx, line in enumerate(draft_text.splitlines() or [draft_text]):
            if idx:
                body.add_run("\n")
            run = body.add_run(line)
            _run_font(run, size=9)

        anchor = body
        if isinstance(suggestions, list) and suggestions:
            note = _insert_after(anchor)
            run = note.add_run("추가 확인하면 좋은 내용: " + " / ".join(str(v) for v in suggestions if str(v).strip()))
            _run_font(run, size=8, color="9C6500")
        inserted += 1

    if inserted:
        # Add a front-page notice without altering the deterministic legal scope.
        target = doc.paragraphs[0] if doc.paragraphs else None
        if target is not None:
            note = OxmlElement("w:p")
            target._p.addprevious(note)
            p = Paragraph(note, target._parent)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run("AI 문장 보강 적용 · 회사 확인자료는 원문 표/필드로 함께 보존")
            _run_font(run, size=8, bold=True, color="C00000")

    out = BytesIO()
    doc.save(out)
    return out.getvalue()
