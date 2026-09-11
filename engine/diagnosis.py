from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .cap_engine import assess_cap
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
    cap_details: list[dict[str, object]] = field(default_factory=list)
    cap_questions: list[str] = field(default_factory=list)
    cap_blockers: list[str] = field(default_factory=list)
    cap_partial_only: bool = True


def _rows_for_regime(
    rows: list[dict[str, object]] | None,
    regime: str,
) -> list[dict[str, object]]:
    return [row for row in (rows or []) if str(row.get("regime", "")) == regime]


def run_preliminary_diagnosis(
    intake: IntakeData,
    law_status_rows: list[dict[str, object]] | None = None,
) -> PreliminaryDiagnosis:
    """Run input/latest-law gates and approved deterministic screening rules.

    Required Excel inputs are a hard first gate. CAP and PSM legal freshness are
    gated independently. PSM uses the approved current Annex 13 DB. CAP now uses
    the approved current quantity Appendix 3 DB for accident-preparedness
    substances, but remains explicitly partial until Appendices 1, 2 and 4 plus
    exemption/group rules are fully validated and approved.
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
    cap_details: list[dict[str, object]] = []
    cap_questions: list[str] = []
    cap_blockers: list[str] = []
    cap_partial_only = True

    if missing:
        messages.append(
            "입력파일을 먼저 보완해야 합니다. 아래 항목은 예/아니오 질문이 아니라 Excel 필수입력 항목입니다."
        )
        messages.extend(f"입력 누락: {item}" for item in missing)

    if cap_sync["decision"] == "HOLD":
        messages.append(f"화사계 법령 게이트: {cap_sync['message']}")
    if psm_sync["decision"] == "HOLD":
        messages.append(f"PSM 법령 게이트: {psm_sync['message']}")

    # CAP: same company Excel is screened automatically. The current production
    # boundary is Appendix 3 only; the UI must never present it as final 1/2군.
    if missing:
        cap = "입력파일 보완 필요"
    elif cap_sync["decision"] == "HOLD":
        cap = "판정보류"
    else:
        cap_assessment = assess_cap(intake)
        cap = cap_assessment.label
        cap_details = [asdict(hit) for hit in cap_assessment.hits]
        cap_questions = list(cap_assessment.questions)
        cap_blockers = list(cap_assessment.blockers)
        cap_partial_only = cap_assessment.partial_only
        messages.extend(cap_assessment.messages)

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
        cap_details=cap_details,
        cap_questions=list(dict.fromkeys(cap_questions)),
        cap_blockers=list(dict.fromkeys(cap_blockers)),
        cap_partial_only=cap_partial_only,
    )


def followup_questions(diagnosis: PreliminaryDiagnosis) -> list[str]:
    """Return PSM legal/rule follow-up questions after input validation passes."""
    if diagnosis.missing_items:
        return []
    return list(dict.fromkeys(q for q in diagnosis.dynamic_questions if q))
