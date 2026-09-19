from __future__ import annotations

"""PSM 새 화면의 점검·내보내기. 기존 4단계(점검)·5단계(보고서 작성)와 같은 엔진·기준을 그대로 쓴다.

- 점검: validate_selected_scope 결과를 '지금 보완할 것'과 '최종 제출 전에 담당자가 따로 준비할 것(첨부)'으로 나눈다.
- 확정: 보완 필요·담당자 확인 필요가 없을 때만 작성자료를 확정한다. 남은 채로 검토용 초안을 만들 수도 있다.
- 내보내기: 규정서식 DOCX(작성본/검토용), 출력물 검증정보와 묶음, 내부 검토용 DOCX. 작성본 표시는 문서별 최종 준비 기준을 통과할 때만 한다.
"""

from dataclasses import dataclass, field
from typing import Any

from .cross_validation import CrossValidationReport
from .document_output_readiness import DocumentOutputReadiness, evaluate_document_output_readiness
from .intake import selected_requirement_specs
from .output_bundle import build_verified_output_bundle, verified_bundle_filename
from .output_provenance import build_output_provenance, output_provenance_filename, output_provenance_json_bytes
from .project import Stage2Project
from .psm_baseline_docx import build_psm_baseline_draft, psm_baseline_filename
from .report_draft import build_report_draft, draft_filename
from .scope_validation import validate_selected_scope
from .workflow import (
    ATTACHMENT_MODE_MANUAL,
    attachment_mode,
    draft_authoring_allowed,
    input_kind_has_attachment,
    mark_draft_with_holds_acknowledged,
    mark_intake_confirmed,
    mark_validation_confirmed,
    validation_confirmed,
)

SYSTEM = "PSM"
STATUS_LABELS = {"HOLD": "보완 필요", "REVIEW_REQUIRED": "담당자 확인 필요", "PASS": "확인 완료"}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass(frozen=True)
class ExportState:
    report: CrossValidationReport
    text_issues: tuple[Any, ...]
    manual_issues: tuple[Any, ...]
    hold: int
    review: int
    passed: int
    readiness: DocumentOutputReadiness | None = None

    @property
    def can_confirm(self) -> bool:
        return self.hold == 0 and self.review == 0

    @property
    def final_ready(self) -> bool:
        return bool(self.readiness and self.readiness.final_ready)


def _attachment_fields(project: Stage2Project) -> set[str]:
    fields = {"documents.pfd", "documents.pid", "documents.site_plan", "psm.psi.msds"}
    for spec in selected_requirement_specs(project):
        if input_kind_has_attachment(spec.input_kind):
            fields.update(spec.field_keys)
    return fields


def evaluate(project: Stage2Project) -> ExportState:
    """기존 4단계 화면과 같은 분류. 첨부가 본체인 항목은 '따로 준비'로 분리한다(첨부를 직접 관리하는 모드가 아닐 때)."""
    if not project.psm_in_scope:
        raise ValueError("현재 작성범위에 공정안전보고서가 포함되어 있지 않습니다.")
    report = validate_selected_scope(project)
    manual_mode = attachment_mode(project) == ATTACHMENT_MODE_MANUAL
    attachments = _attachment_fields(project)

    def deferred(issue) -> bool:
        if not manual_mode:
            return False
        keys = set(issue.field_keys)
        if not keys.intersection(attachments):
            return False
        return issue.code == "CROSSCHECK-SOURCE-MISSING" or any(key in attachments for key in keys)

    manual = tuple(i for i in report.issues if deferred(i))
    text = tuple(i for i in report.issues if not deferred(i))
    return ExportState(
        report=report, text_issues=text, manual_issues=manual,
        hold=sum(1 for i in text if i.status == "HOLD"), review=sum(1 for i in text if i.status == "REVIEW_REQUIRED"),
        passed=sum(1 for i in text if i.status == "PASS"),
        readiness=evaluate_document_output_readiness(project, SYSTEM, report),
    )


def confirm(project: Stage2Project, state: ExportState) -> bool:
    """보완·확인할 것이 없을 때만 작성자료를 확정한다."""
    if not state.can_confirm:
        return False
    mark_intake_confirmed(project, True)
    mark_validation_confirmed(project, True)
    return True


def acknowledge_holds(project: Stage2Project) -> None:
    """확정하지 않고 검토용 초안만 만들겠다는 표시. 최종 제출 준비 판정에는 영향이 없다."""
    mark_intake_confirmed(project, True)
    mark_draft_with_holds_acknowledged(project, True)


def downloads_allowed(project: Stage2Project) -> bool:
    return draft_authoring_allowed(project)


@dataclass(frozen=True)
class Outputs:
    regulation_docx: bytes
    regulation_name: str
    review_docx: bytes
    review_name: str
    provenance_json: bytes
    provenance_name: str
    bundle: bytes
    bundle_name: str
    final_ready: bool
    notes: tuple[str, ...] = field(default_factory=tuple)


def build_outputs(project: Stage2Project, *, final_ready: bool) -> Outputs:
    """작성본 표시는 final_ready일 때만. 아니면 파일명·검증정보 모두 '검토용'."""
    regulation = build_psm_baseline_draft(project)
    name = psm_baseline_filename(project)
    if not final_ready:
        name = name.replace("_규정서식_작성본.docx", "_규정서식_검토용.docx")
    provenance = build_output_provenance(project, SYSTEM, regulation, file_name=name, final_ready=final_ready)
    review = build_report_draft(project, SYSTEM)
    review_name = draft_filename(project, SYSTEM).replace("_법정서식_검토용_초안.docx", "_내부_검토용.docx").replace(
        "_검토용_초안.docx", "_내부_검토용.docx")
    return Outputs(
        regulation_docx=regulation, regulation_name=name, review_docx=review, review_name=review_name,
        provenance_json=output_provenance_json_bytes(provenance), provenance_name=output_provenance_filename(name),
        bundle=build_verified_output_bundle(regulation, provenance), bundle_name=verified_bundle_filename(name),
        final_ready=final_ready,
    )
