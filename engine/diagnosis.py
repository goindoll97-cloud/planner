from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .inventory import IntakeData, validate_intake
from .law_monitor import overall_sync_gate
from .psm_engine import assess_psm


@dataclass
class PreliminaryDiagnosis:
    law_status: str
    cap_result: str
    psm_result: str
    missing_items: list[str]
    messages: list[str]
    dynamic_questions: list[str] = field(default_factory=list)
    psm_details: list[dict[str, object]] = field(default_factory=list)
    psm_ratio_details: list[dict[str, object]] = field(default_factory=list)
    psm_blockers: list[str] = field(default_factory=list)
    psm_r_value: float | None = None
    psm_r_complete: bool = False


def _rows_for_regime(
    rows: list[dict[str, object]] | None,
    regime: str,
) -> list[dict[str, object]]:
    return [row for row in (rows or []) if str(row.get("regime", "")) == regime]


def run_preliminary_diagnosis(
    intake: IntakeData,
    law_status_rows: list[dict[str, object]] | None = None,
) -> PreliminaryDiagnosis:
    """Run input/latest-law gates and the currently approved deterministic rules.

    Required Excel inputs are a hard first gate. Missing workbook fields are not
    converted into yes/no regulatory questions: the user must correct the source
    workbook first. CAP and PSM law freshness are then gated independently. PSM
    becomes active only after the administrator approves the current 별표 13
    structured table. CAP remains conservative until all quantity tables and
    exemption/group rules are validated.
    """
    missing = validate_intake(intake)
    all_sync = overall_sync_gate(law_status_rows)
    cap_sync = overall_sync_gate(_rows_for_regime(law_status_rows, "화사계"))
    psm_sync = overall_sync_gate(_rows_for_regime(law_status_rows, "PSM"))
    messages: list[str] = []
    dynamic_questions: list[str] = []
    psm_details: list[dict[str, object]] = []
    psm_ratio_details: list[dict[str, object]] = []
    psm_blockers: list[str] = []
    psm_r_value: float | None = None
    psm_r_complete = False

    if missing:
        messages.append(
            "입력파일을 먼저 보완해야 합니다. 아래 항목은 예/아니오 질문이 아니라 Excel 필수입력 항목입니다."
        )
        messages.extend(f"입력 누락: {item}" for item in missing)

    if cap_sync["decision"] == "HOLD":
        messages.append(f"화사계 법령 게이트: {cap_sync['message']}")
    if psm_sync["decision"] == "HOLD":
        messages.append(f"PSM 법령 게이트: {psm_sync['message']}")

    # Input validation is a hard gate before any legal applicability question.
    if missing:
        cap = "입력파일 보완 필요"
    elif cap_sync["decision"] == "HOLD":
        cap = "판정보류"
    else:
        cap = "규정수량 DB 구축 중"
        messages.append(
            "화사계 최신성·입력 게이트는 통과했습니다. 현재는 사고대비물질 규정수량부터 구조화하고 있으며, "
            "별표 1~4 및 면제·작성수준 규칙 검증 전에는 1군/2군/비대상을 확정하지 않습니다."
        )

    if missing:
        psm = "입력파일 보완 필요"
    elif psm_sync["decision"] == "HOLD":
        psm = "판정보류"
    else:
        psm_assessment = assess_psm(intake)
        psm = psm_assessment.label
        messages.extend(psm_assessment.messages)
        dynamic_questions.extend(psm_assessment.questions)
        psm_details = [asdict(hit) for hit in psm_assessment.hits]
        psm_ratio_details = [asdict(line) for line in psm_assessment.ratio_lines]
        psm_blockers = list(psm_assessment.blockers)
        psm_r_value = psm_assessment.r_value
        psm_r_complete = psm_assessment.r_complete

    return PreliminaryDiagnosis(
        law_status=all_sync["label"],
        cap_result=cap,
        psm_result=psm,
        missing_items=missing,
        messages=list(dict.fromkeys(messages)),
        dynamic_questions=list(dict.fromkeys(dynamic_questions)),
        psm_details=psm_details,
        psm_ratio_details=psm_ratio_details,
        psm_blockers=psm_blockers,
        psm_r_value=psm_r_value,
        psm_r_complete=psm_r_complete,
    )


def followup_questions(diagnosis: PreliminaryDiagnosis) -> list[str]:
    """Return only legal/rule follow-up questions after input validation passes.

    Missing required workbook fields must be corrected in the Excel itself. They
    are deliberately not rendered as yes/no survey questions.
    """
    if diagnosis.missing_items:
        return []
    return list(dict.fromkeys(q for q in diagnosis.dynamic_questions if q))
