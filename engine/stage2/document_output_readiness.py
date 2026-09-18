from __future__ import annotations

from dataclasses import dataclass

from .cap_final_gate import CAPFinalGateResult, evaluate_cap_final_gate
from .cross_validation import CrossValidationReport
from .project import Stage2Project
from .system_final_gate import SystemFinalGateResult, evaluate_system_final_gate
from .workflow import validation_confirmed


@dataclass(frozen=True)
class DocumentOutputReadiness:
    system: str
    final_ready: bool
    stage4_confirmed: bool
    system_gate: SystemFinalGateResult
    cap_manual_gate_ready: bool
    cap_gate: CAPFinalGateResult | None
    reasons: tuple[str, ...]


def _normalize_system(system: str) -> str:
    value = str(system or "").strip().upper()
    if value not in {"PSM", "CAP"}:
        raise ValueError(f"지원하지 않는 보고서 종류입니다: {system}")
    return value


def evaluate_document_output_readiness(
    project: Stage2Project,
    system: str,
    report: CrossValidationReport,
) -> DocumentOutputReadiness:
    """Return whether this specific document may be labelled as an authoring-ready output.

    Review drafts remain available elsewhere even when this returns false.
    The decision is intentionally document-scoped: a CAP-only issue must not
    downgrade an otherwise-ready PSM document, and vice versa.
    """

    system = _normalize_system(system)
    selected = project.psm_in_scope if system == "PSM" else project.cap_in_scope
    if not selected:
        raise ValueError(f"현재 작성범위에 {system}이(가) 포함되어 있지 않습니다.")

    stage4_ready = validation_confirmed(project)
    system_gate = evaluate_system_final_gate(project, system, report)

    cap_manual_ready = True
    cap_gate = None
    if system == "CAP":
        cap_gate = evaluate_cap_final_gate(project, report)
        cap_manual_ready = cap_gate.ready

    reasons: list[str] = []
    if not stage4_ready:
        reasons.append("4단계 작성자료 확인이 현재 프로젝트 내용과 일치하는 상태로 완료되지 않았습니다.")
    if not system_gate.ready:
        reasons.append(
            f"{system_gate.system_label} 작성완성도·자동검증에 "
            f"보완 필요 {system_gate.hold_count}건, 담당자 확인 필요 {system_gate.review_count}건이 남아 있습니다."
        )
    if cap_gate is not None and not cap_gate.ready:
        reasons.append(
            "화학사고예방관리계획서 최종 제출 체크포인트에 "
            f"보완 필요 {cap_gate.hold_count}건, 담당자 확인 필요 {cap_gate.review_count}건이 남아 있습니다."
        )

    return DocumentOutputReadiness(
        system=system,
        final_ready=stage4_ready and system_gate.ready and cap_manual_ready,
        stage4_confirmed=stage4_ready,
        system_gate=system_gate,
        cap_manual_gate_ready=cap_manual_ready,
        cap_gate=cap_gate,
        reasons=tuple(reasons),
    )
