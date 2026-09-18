from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any

from .project import CONFIRMED_STATUSES, Stage2Project


PASS = "PASS"
HOLD = "HOLD"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class CAPForm2Readiness:
    status: str
    submission_type: str
    submission_reason: str
    rows: tuple[dict[str, Any], ...]
    blockers: tuple[str, ...]
    messages: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.status in {PASS, NOT_APPLICABLE}


_REQUIRED_ROW_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("일자", ("일자", "변경일자", "날짜")),
    ("변경항목", ("변경항목", "항목")),
    ("변경의 종류", ("변경의 종류", "변경종류")),
    ("변경 내용", ("변경 내용(변경전 → 변경후)", "변경 내용", "변경내용")),
    ("후속조치", ("후속조치", "조치사항")),
    ("담당자", ("담당자", "작성자", "확인자")),
)


def _norm(value: object) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _confirmed_value(project: Stage2Project, key: str) -> Any:
    rec = project.get_field(key)
    if rec is None or rec.status not in CONFIRMED_STATUSES:
        return None
    if rec.value in (None, "", [], {}):
        return None
    return rec.value


def _row_value(row: Mapping[str, Any], aliases: tuple[str, ...]) -> Any:
    normalized = {_norm(key): value for key, value in row.items()}
    for alias in aliases:
        value = normalized.get(_norm(alias))
        if value not in (None, ""):
            return value
    return ""


def _confirmed_change_rows(project: Stage2Project) -> tuple[dict[str, Any], ...]:
    value = _confirmed_value(project, "cap.prevention.change_log")
    if not isinstance(value, list):
        return ()
    return tuple(dict(row) for row in value if isinstance(row, Mapping))


def _validate_rows(rows: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    blockers: list[str] = []
    if not rows:
        return ("변경내역 관리대장이 확인되지 않았습니다.",)

    for index, row in enumerate(rows, start=1):
        missing = [
            label
            for label, aliases in _REQUIRED_ROW_FIELDS
            if _row_value(row, aliases) in (None, "")
        ]
        if missing:
            blockers.append(
                f"변경내역 관리대장 {index}행의 필수항목이 비어 있습니다: {', '.join(missing)}"
            )
    return tuple(blockers)


def build_cap_form2_readiness(project: Stage2Project) -> CAPForm2Readiness:
    """Evaluate Annex Form 2 without guessing whether a change log applies.

    Explicit initial submission (신규제출 + 최초) is treated as not applicable.
    Explicit change submission requires a confirmed, structurally complete log.
    For re-submission/noncompliance/other ambiguous submission types, a valid
    confirmed log is accepted as company confirmation that Form 2 applies;
    otherwise human review is required instead of inventing applicability.
    """

    submission_type_raw = _confirmed_value(project, "cap.business.submission_type")
    submission_reason_raw = _confirmed_value(project, "cap.business.submission_reason")
    submission_type = str(submission_type_raw or "").strip()
    submission_reason = str(submission_reason_raw or "").strip()
    type_norm = _norm(submission_type)
    reason_norm = _norm(submission_reason)
    rows = _confirmed_change_rows(project)

    if not type_norm:
        return CAPForm2Readiness(
            status=REVIEW_REQUIRED,
            submission_type=submission_type,
            submission_reason=submission_reason,
            rows=rows,
            blockers=("제출구분이 확인되지 않아 별지 제2호 적용 여부를 확정할 수 없습니다.",),
        )

    is_new = "신규" in type_norm
    is_change = "변경" in type_norm and "재제출" not in type_norm
    is_first = "최초" in reason_norm or "최초" in type_norm

    if is_new and is_first:
        return CAPForm2Readiness(
            status=NOT_APPLICABLE,
            submission_type=submission_type,
            submission_reason=submission_reason,
            rows=rows,
            blockers=(),
            messages=("최초 신규제출로 확인되어 변경내역 관리대장을 필수 작성항목으로 적용하지 않습니다.",),
        )

    if is_change:
        blockers = _validate_rows(rows)
        return CAPForm2Readiness(
            status=HOLD if blockers else PASS,
            submission_type=submission_type,
            submission_reason=submission_reason,
            rows=rows,
            blockers=blockers,
            messages=("변경제출에 필요한 변경내역 관리대장을 확인했습니다.",) if not blockers else (),
        )

    # 재제출, 이행점검 불이행 등은 현재 저장된 제출구분만으로 Form 2
    # 적용 여부를 단정하지 않는다. 다만 회사가 확정된 변경대장을
    # 제공했다면 그 사실을 근거로 작성 가능 상태로 본다.
    if rows:
        blockers = _validate_rows(rows)
        return CAPForm2Readiness(
            status=HOLD if blockers else PASS,
            submission_type=submission_type,
            submission_reason=submission_reason,
            rows=rows,
            blockers=blockers,
            messages=("회사에서 확정한 변경내역 관리대장을 확인했습니다.",) if not blockers else (),
        )

    return CAPForm2Readiness(
        status=REVIEW_REQUIRED,
        submission_type=submission_type,
        submission_reason=submission_reason,
        rows=rows,
        blockers=(
            f"제출구분 '{submission_type}'에 대해 별지 제2호 변경내역 관리대장 적용 여부를 담당자가 확인해야 합니다.",
        ),
    )
