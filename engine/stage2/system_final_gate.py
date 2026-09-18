from __future__ import annotations

from dataclasses import dataclass

from .cross_validation import CrossValidationReport, filter_validation_report
from .project import Stage2Project
from .report_draft import report_generation_status


PASS = "PASS"
HOLD = "HOLD"
REVIEW_REQUIRED = "REVIEW_REQUIRED"

STATUS_LABELS = {
    PASS: "확인 완료",
    HOLD: "보완 필요",
    REVIEW_REQUIRED: "담당자 확인 필요",
}

SYSTEM_LABELS = {
    "PSM": "공정안전보고서",
    "CAP": "화학사고예방관리계획서",
}


@dataclass(frozen=True)
class SystemFinalCheckpoint:
    key: str
    label: str
    status: str
    message: str

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)


@dataclass(frozen=True)
class SystemFinalGateResult:
    system: str
    system_label: str
    checkpoints: tuple[SystemFinalCheckpoint, ...]

    @property
    def hold_count(self) -> int:
        return sum(item.status == HOLD for item in self.checkpoints)

    @property
    def review_count(self) -> int:
        return sum(item.status == REVIEW_REQUIRED for item in self.checkpoints)

    @property
    def ready(self) -> bool:
        return self.hold_count == 0 and self.review_count == 0


def _normalize_system(system: str) -> str:
    value = str(system or "").strip().upper()
    if value not in SYSTEM_LABELS:
        raise ValueError(f"지원하지 않는 보고서 종류입니다: {system}")
    return value


def _completeness_checkpoint(project: Stage2Project, system: str) -> SystemFinalCheckpoint:
    status = report_generation_status(project, system)
    if status.final_ready:
        return SystemFinalCheckpoint(
            key=f"{system.lower()}.final.completeness",
            label="필수 작성항목 완성도",
            status=PASS,
            message=f"필수 작성항목이 확인 상태입니다. 작성완성도 {status.completion_pct:.1f}%.",
        )

    if status.state == "REVIEW_REQUIRED":
        checkpoint_status = REVIEW_REQUIRED
    else:
        checkpoint_status = HOLD

    labels = ", ".join(status.blocking_labels[:5])
    if len(status.blocking_labels) > 5:
        labels += f" 외 {len(status.blocking_labels) - 5}건"
    detail = f" 미완료 작성항목: {labels}" if labels else ""

    return SystemFinalCheckpoint(
        key=f"{system.lower()}.final.completeness",
        label="필수 작성항목 완성도",
        status=checkpoint_status,
        message=(
            f"필수 작성항목이 아직 최종 확인 상태가 아닙니다. "
            f"작성완성도 {status.completion_pct:.1f}%, 상태 {status.state}.{detail}"
        ),
    )


def _validation_checkpoint(
    report: CrossValidationReport,
    system: str,
) -> SystemFinalCheckpoint:
    scoped = filter_validation_report(report, {"COMMON", system})
    if scoped.final_export_allowed:
        return SystemFinalCheckpoint(
            key=f"{system.lower()}.final.validation",
            label="자동검증·교차검증",
            status=PASS,
            message="해당 문서와 공통자료의 자동검증에서 보완 필요 또는 담당자 확인 필요 항목이 없습니다.",
        )

    status = HOLD if scoped.hold_count else REVIEW_REQUIRED
    return SystemFinalCheckpoint(
        key=f"{system.lower()}.final.validation",
        label="자동검증·교차검증",
        status=status,
        message=(
            f"해당 문서와 공통자료에 보완 필요 {scoped.hold_count}건, "
            f"담당자 확인 필요 {scoped.review_count}건이 남아 있습니다."
        ),
    )


def evaluate_system_final_gate(
    project: Stage2Project,
    system: str,
    report: CrossValidationReport,
) -> SystemFinalGateResult:
    system = _normalize_system(system)
    selected = (
        project.psm_in_scope if system == "PSM" else project.cap_in_scope
    )
    if not selected:
        return SystemFinalGateResult(
            system=system,
            system_label=SYSTEM_LABELS[system],
            checkpoints=(),
        )

    return SystemFinalGateResult(
        system=system,
        system_label=SYSTEM_LABELS[system],
        checkpoints=(
            _completeness_checkpoint(project, system),
            _validation_checkpoint(report, system),
        ),
    )
