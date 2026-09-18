from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .cap_form2_engine import (
    HOLD as FORM2_HOLD,
    NOT_APPLICABLE as FORM2_NOT_APPLICABLE,
    PASS as FORM2_PASS,
    REVIEW_REQUIRED as FORM2_REVIEW_REQUIRED,
    build_cap_form2_readiness,
)
from .cross_validation import CrossValidationReport
from .project import CONFIRMED_STATUSES, FieldRecord, Stage2Project
from .requirements import load_cap_manual_registry


PASS = "PASS"
HOLD = "HOLD"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
INFO = "INFO"

STATUS_LABELS = {
    PASS: "확인 완료",
    HOLD: "보완 필요",
    REVIEW_REQUIRED: "담당자 확인 필요",
    INFO: "안내",
}


@dataclass(frozen=True)
class CAPFinalCheckpoint:
    key: str
    label: str
    status: str
    message: str
    manual_pages: tuple[int, ...] = ()

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)


@dataclass(frozen=True)
class CAPFinalGateResult:
    checkpoints: tuple[CAPFinalCheckpoint, ...]

    @property
    def hold_count(self) -> int:
        return sum(item.status == HOLD for item in self.checkpoints)

    @property
    def review_count(self) -> int:
        return sum(item.status == REVIEW_REQUIRED for item in self.checkpoints)

    @property
    def ready(self) -> bool:
        return self.hold_count == 0 and self.review_count == 0


def _norm(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", str(value or "")).lower()


def _record(project: Stage2Project, key: str) -> FieldRecord | None:
    rec = project.get_field(key)
    if rec is None or rec.status not in CONFIRMED_STATUSES:
        return None
    if rec.value in (None, "", [], {}):
        return None
    return rec


def _has_file_evidence(record: FieldRecord | None) -> bool:
    if record is None:
        return False
    for evidence in record.evidence:
        digest = str(evidence.sha256 or "").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            continue
        source_type = str(evidence.source_type or "").upper()
        if (
            source_type in {"COMPANY_EVIDENCE", "ATTACHMENT", "STAGE2_ATTACHMENT"}
            or "EVIDENCE" in source_type
            or "ATTACH" in source_type
        ):
            return True
    return False


def _checkpoint_meta() -> dict[str, tuple[str, tuple[int, ...]]]:
    registry = load_cap_manual_registry()
    out: dict[str, tuple[str, tuple[int, ...]]] = {}
    for row in registry.get("final_gate_checkpoints") or []:
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        out[key] = (
            str(row.get("label") or key),
            tuple(int(v) for v in row.get("manual_pages") or []),
        )
    return out


def _item(
    meta: dict[str, tuple[str, tuple[int, ...]]],
    key: str,
    status: str,
    message: str,
) -> CAPFinalCheckpoint:
    label, pages = meta.get(key, (key, ()))
    return CAPFinalCheckpoint(
        key=key,
        label=label,
        status=status,
        message=message,
        manual_pages=pages,
    )


def _submission_type_checkpoint(
    project: Stage2Project,
    meta: dict[str, tuple[str, tuple[int, ...]]],
) -> CAPFinalCheckpoint:
    rec = _record(project, "cap.business.submission_type")
    reason = _record(project, "cap.business.submission_reason")
    if rec is None:
        return _item(
            meta,
            "cap.final.form_type",
            HOLD,
            "제출구분이 확인되지 않아 제출유형별 검토신청서 선택을 확정할 수 없습니다.",
        )
    n = _norm(rec.value)
    recognized = any(token in n for token in ("신규", "변경", "재제출", "이행점검"))
    if not recognized:
        return _item(
            meta,
            "cap.final.form_type",
            REVIEW_REQUIRED,
            f"제출구분 '{rec.value}'이 현재 자동분류 범위에 명확히 대응하지 않아 담당자 확인이 필요합니다.",
        )
    if reason is None:
        return _item(
            meta,
            "cap.final.form_type",
            REVIEW_REQUIRED,
            "제출구분은 확인되었지만 제출 사유가 확인되지 않아 최종 신청서 유형을 담당자가 확인해야 합니다.",
        )
    return _item(
        meta,
        "cap.final.form_type",
        PASS,
        f"제출구분 '{rec.value}' / 제출 사유 '{reason.value}'를 확인했습니다.",
    )


def _other_system_checkpoint(
    project: Stage2Project,
    meta: dict[str, tuple[str, tuple[int, ...]]],
) -> CAPFinalCheckpoint:
    rec = _record(project, "cap.business.other_system_review")
    if rec is None:
        return _item(
            meta,
            "cap.final.other_system_review",
            HOLD,
            "공정안전보고서 등 타 제도 심사결과 활용 여부가 확인되지 않았습니다.",
        )

    n = _norm(rec.value)
    if any(token in n for token in ("미해당", "없음", "미사용", "아니오", "no")):
        return _item(
            meta,
            "cap.final.other_system_review",
            PASS,
            "타 제도 심사결과 활용 미해당으로 확인되었습니다.",
        )

    applicable = (
        "공정안전보고서" in n
        or "안전성향상계획" in n
        or n in {"해당", "예", "yes", "사용"}
    )
    if applicable:
        if _has_file_evidence(rec):
            return _item(
                meta,
                "cap.final.other_system_review",
                PASS,
                "타 제도 심사결과 활용 대상이며 연결된 회사 증빙파일을 확인했습니다.",
            )
        return _item(
            meta,
            "cap.final.other_system_review",
            REVIEW_REQUIRED,
            "타 제도 심사결과 활용 대상으로 확인되었지만 관련 심사결과 증빙파일 연결을 확인하지 못했습니다.",
        )

    return _item(
        meta,
        "cap.final.other_system_review",
        REVIEW_REQUIRED,
        f"타 제도 심사결과 활용 값 '{rec.value}'의 의미를 담당자가 확인해야 합니다.",
    )


def _joint_emergency_checkpoint(
    project: Stage2Project,
    meta: dict[str, tuple[str, tuple[int, ...]]],
) -> CAPFinalCheckpoint:
    rec = _record(project, "cap.business.joint_emergency_plan")
    if rec is None:
        return _item(
            meta,
            "cap.final.joint_emergency",
            HOLD,
            "공동비상대응계획 해당 여부가 확인되지 않았습니다.",
        )

    n = _norm(rec.value)
    if "단독" in n:
        return _item(
            meta,
            "cap.final.joint_emergency",
            PASS,
            "단독제출로 확인되어 공동비상대응계획 추가 증빙을 요구하지 않습니다.",
        )
    if "공동" in n:
        if _has_file_evidence(rec):
            return _item(
                meta,
                "cap.final.joint_emergency",
                PASS,
                "공동제출로 확인되었고 관련 회사 증빙파일 연결을 확인했습니다.",
            )
        return _item(
            meta,
            "cap.final.joint_emergency",
            REVIEW_REQUIRED,
            "공동제출로 확인되었지만 공동비상대응계획 관련 증빙파일 연결을 확인하지 못했습니다.",
        )

    return _item(
        meta,
        "cap.final.joint_emergency",
        REVIEW_REQUIRED,
        f"공동비상대응계획 값 '{rec.value}'의 의미를 담당자가 확인해야 합니다.",
    )


def _omission_checkpoint(
    report: CrossValidationReport,
    meta: dict[str, tuple[str, tuple[int, ...]]],
) -> CAPFinalCheckpoint:
    if report.final_export_allowed:
        return _item(
            meta,
            "cap.final.omission_check",
            PASS,
            "선택한 작성범위의 자동검증에서 보완 필요 및 담당자 확인 필요 항목이 없습니다.",
        )
    return _item(
        meta,
        "cap.final.omission_check",
        HOLD,
        f"선택한 작성범위에 보완 필요 {report.hold_count}건, 담당자 확인 필요 {report.review_count}건이 남아 있습니다.",
    )


def _revision_map_checkpoint(
    project: Stage2Project,
    meta: dict[str, tuple[str, tuple[int, ...]]],
) -> CAPFinalCheckpoint:
    form2 = build_cap_form2_readiness(project)
    if form2.status == FORM2_NOT_APPLICABLE:
        return _item(
            meta,
            "cap.final.revision_map",
            PASS,
            "최초 신규제출로 확인되어 신규 제출 기준으로 작성항목을 적용합니다.",
        )
    if form2.status == FORM2_PASS:
        return _item(
            meta,
            "cap.final.revision_map",
            PASS,
            "제출유형과 변경내역 관리대장의 정합성을 확인했습니다.",
        )
    if form2.status == FORM2_HOLD:
        return _item(
            meta,
            "cap.final.revision_map",
            HOLD,
            " / ".join(form2.blockers) or "변경 제출 작성항목 정합성을 확인하지 못했습니다.",
        )
    if form2.status == FORM2_REVIEW_REQUIRED:
        return _item(
            meta,
            "cap.final.revision_map",
            REVIEW_REQUIRED,
            " / ".join(form2.blockers) or "신규·변경 제출 작성항목 적용범위를 담당자가 확인해야 합니다.",
        )
    return _item(
        meta,
        "cap.final.revision_map",
        REVIEW_REQUIRED,
        "신규·변경 제출 작성항목 적용범위를 담당자가 확인해야 합니다.",
    )


def evaluate_cap_final_gate(
    project: Stage2Project,
    report: CrossValidationReport,
) -> CAPFinalGateResult:
    if not project.cap_in_scope:
        return CAPFinalGateResult(checkpoints=())

    meta = _checkpoint_meta()
    checkpoints = (
        _submission_type_checkpoint(project, meta),
        _other_system_checkpoint(project, meta),
        _joint_emergency_checkpoint(project, meta),
        _omission_checkpoint(report, meta),
        _item(
            meta,
            "cap.final.post_submission",
            INFO,
            "제출 후 심사·보완요청이 발생할 수 있으므로 제출기한과 보완 일정은 별도로 관리해야 합니다.",
        ),
        _revision_map_checkpoint(project, meta),
    )
    return CAPFinalGateResult(checkpoints=checkpoints)
