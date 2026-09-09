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


def run_preliminary_diagnosis(
    intake: IntakeData,
    law_status_rows: list[dict[str, object]] | None = None,
) -> PreliminaryDiagnosis:
    """Run only the gates that are safe before validated regulatory DBs are connected.

    v0.1 intentionally does NOT infer CAP group or PSM applicability from general
    knowledge. The next implementation stage will plug verified regulatory tables
    and deterministic rules into this function.
    """
    missing = validate_intake(intake)
    sync = overall_sync_gate(law_status_rows)
    messages: list[str] = []

    if missing:
        messages.append("필수 입력값이 부족하여 규제 대상 여부를 확정하지 않습니다.")
    if sync["decision"] == "HOLD":
        messages.append(sync["message"])

    if missing or sync["decision"] == "HOLD":
        cap = "판정보류"
        psm = "판정보류"
    else:
        # This branch will be replaced by verified CAP/PSM rule engines.
        cap = "규제DB 연결 대기"
        psm = "규제DB 연결 대기"
        messages.append("입력자료는 준비되었으나 화사계·PSM 검증 규칙 DB가 아직 연결되지 않았습니다.")

    return PreliminaryDiagnosis(
        law_status=sync["label"],
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
