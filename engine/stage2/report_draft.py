from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import re
from zipfile import ZIP_DEFLATED, ZipFile

from .completeness import evaluate_project_completeness
from .project import Stage2Project
from .statutory_report_v2 import build_statutory_report_draft


PSM = "PSM"
CAP = "CAP"
SYSTEM_LABELS = {
    PSM: "공정안전보고서",
    CAP: "화학사고예방관리계획서",
}


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


def _normalize_system(system: str) -> str:
    value = str(system or "").strip().upper()
    if value not in SYSTEM_LABELS:
        raise ValueError(f"지원하지 않는 보고서 종류입니다: {system}")
    return value


def _system_selected(project: Stage2Project, system: str) -> bool:
    return (system == PSM and project.psm_in_scope) or (system == CAP and project.cap_in_scope)


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
    return f"{_safe_filename(company_name)}_{SYSTEM_LABELS[system]}_법정서식_검토용_초안.docx"


def build_report_draft(project: Stage2Project, system: str) -> bytes:
    """Build a review-only DOCX using the current statutory annex forms.

    The statutory forms and their writing order are the output schema. Company
    facts are placed into fixed legal-form cells/sections. Unknown facts remain
    ``[확인 필요]`` and are never invented merely to make the document look full.
    """
    system = _normalize_system(system)
    status = report_generation_status(project, system)
    return build_statutory_report_draft(project, system, status)


def build_draft_bundle(project: Stage2Project) -> bytes:
    if not project.scope_confirmed or not (project.psm_in_scope or project.cap_in_scope):
        raise ValueError("먼저 작성범위를 선택해야 보고서 초안을 생성할 수 있습니다.")

    out = BytesIO()
    manifest_lines = [
        "Stage 2 법정서식 기반 검토용 작성본 묶음",
        f"프로젝트 ID: {project.project_id}",
        "주의: 현행 고시의 별지서식·작성순서를 기반으로 한 검토용 파일이며, 최종 제출 전 담당자 확인이 필요합니다.",
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
