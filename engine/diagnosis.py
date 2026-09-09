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

    CAP and PSM law freshness are gated independently. PSM becomes active only
    after the administrator approves the current 별표 13 structured table. CAP
    remains conservative until all quantity tables and exemption/group rules are
    validated; the partial CAP quantity parser is managed separately in admin UI.
    """
    missing = validate_intake(intake)
    all_sync = overall_sync_gate(law_status_rows)
    cap_sync = overall_sync_gate(_rows_for_regime(law_status_rows, "화사계"))
    psm_sync = overall_sync_gate(_rows_for_regime(law_status_rows, "PSM"))
    messages: list[str] = []
    dynamic_questions: list[str] = []
    psm_details: list[dict[str, object]] = []

    if missing:
        messages.append("필수 입력값이 부족하여 규제 대상 여부를 확정하지 않습니다.")

    if cap_sync["decision"] == "HOLD":
        messages.append(f"화사계 법령 게이트: {cap_sync['message']}")
    if psm_sync["decision"] == "HOLD":
        messages.append(f"PSM 법령 게이트: {psm_sync['message']}")

    # CAP remains blocked until the complete current quantity/exemption/group
    # rule set is approved. We do not convert the partial accident-material DB
    # into a final group determination.
    if missing or cap_sync["decision"] == "HOLD":
        cap = "판정보류"
    else:
        cap = "규정수량 DB 구축 중"
        messages.append(
            "화사계 최신성·입력 게이트는 통과했습니다. 현재는 사고대비물질 규정수량부터 구조화하고 있으며, "
            "별표 1~4 및 면제·작성수준 규칙 검증 전에는 1군/2군/비대상을 확정하지 않습니다."
        )

    if missing or psm_sync["decision"] == "HOLD":
        psm = "판정보류"
    else:
        psm_assessment = assess_psm(intake)
        psm = psm_assessment.label
        messages.extend(psm_assessment.messages)
        dynamic_questions.extend(psm_assessment.questions)
        psm_details = [asdict(hit) for hit in psm_assessment.hits]

    return PreliminaryDiagnosis(
        law_status=all_sync["label"],
        cap_result=cap,
        psm_result=psm,
        missing_items=missing,
        messages=list(dict.fromkeys(messages)),
        dynamic_questions=list(dict.fromkeys(dynamic_questions)),
        psm_details=psm_details,
    )


def followup_questions(diagnosis: PreliminaryDiagnosis) -> list[str]:
    """Convert data gaps and rule-engine blockers into concise follow-up questions."""
    questions: list[str] = []
    for item in diagnosis.missing_items:
        if "사업장 기본정보" in item:
            questions.append(item.replace("입력 필요", "을 확인해 주세요"))
        elif "수량 단위" in item:
            questions.append(item.replace("수량 단위가 필요합니다.", "수량 단위를 확인해 주세요."))
        elif "최대 제조·사용량" in item:
            questions.append(item.replace("중 하나는 필요합니다.", "중 확인 가능한 최대량을 입력해 주세요."))
        else:
            questions.append(item)
    questions.extend(diagnosis.dynamic_questions)
    return list(dict.fromkeys(q for q in questions if q))
