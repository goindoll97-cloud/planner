from __future__ import annotations

from dataclasses import dataclass

from .inventory import IntakeData, validate_intake
from .law_monitor import overall_sync_gate


@dataclass
class PreliminaryDiagnosis:
    law_status: str
    cap_result: str
    psm_result: str
    missing_items: list[str]
    messages: list[str]


def _rows_for_regime(
    rows: list[dict[str, object]] | None,
    regime: str,
) -> list[dict[str, object]]:
    return [row for row in (rows or []) if str(row.get("regime", "")) == regime]


def run_preliminary_diagnosis(
    intake: IntakeData,
    law_status_rows: list[dict[str, object]] | None = None,
) -> PreliminaryDiagnosis:
    """Run safe input/latest-law gates before the validated rule DBs are connected.

    CAP and PSM law freshness are gated independently. A PSM-only law/PDF update
    therefore does not unnecessarily block the CAP branch, and vice versa.
    """
    missing = validate_intake(intake)
    all_sync = overall_sync_gate(law_status_rows)
    cap_sync = overall_sync_gate(_rows_for_regime(law_status_rows, "화사계"))
    psm_sync = overall_sync_gate(_rows_for_regime(law_status_rows, "PSM"))
    messages: list[str] = []

    if missing:
        messages.append("필수 입력값이 부족하여 규제 대상 여부를 확정하지 않습니다.")

    if cap_sync["decision"] == "HOLD":
        messages.append(f"화사계 법령 게이트: {cap_sync['message']}")
    if psm_sync["decision"] == "HOLD":
        messages.append(f"PSM 법령 게이트: {psm_sync['message']}")

    if missing or cap_sync["decision"] == "HOLD":
        cap = "판정보류"
    else:
        cap = "규제DB 연결 대기"

    if missing or psm_sync["decision"] == "HOLD":
        psm = "판정보류"
    else:
        psm = "규제DB 연결 대기"

    if not missing and cap == "규제DB 연결 대기":
        messages.append("화사계 최신성·입력 게이트는 통과했으며, 다음 단계에서 검증된 화사계 규정수량/면제 규칙 DB를 연결합니다.")
    if not missing and psm == "규제DB 연결 대기":
        messages.append("PSM 최신성·입력 게이트는 통과했으며, 다음 단계에서 검증된 PSM 별표 13/대상업종 규칙 DB를 연결합니다.")

    return PreliminaryDiagnosis(
        law_status=all_sync["label"],
        cap_result=cap,
        psm_result=psm,
        missing_items=missing,
        messages=messages,
    )


def followup_questions(diagnosis: PreliminaryDiagnosis) -> list[str]:
    """Convert data gaps into concise user-facing follow-up questions."""
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
    return questions
