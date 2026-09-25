from __future__ import annotations

"""별지 제2호(화학사고예방관리계획서 변경내역 관리대장) authoring support.

Submission type/reason and 단위공장명 are company facts shared with 별지 제3호,
so they are stored under the same keys the 제3호 writer reads and asked once.
Applicability and row validation stay in cap_form2_engine.
"""

from dataclasses import dataclass
from typing import Any, Mapping

from . import cap_guideline
from .cap_form2_engine import NOT_APPLICABLE, CAPForm2Readiness, build_cap_form2_readiness
from .cap_rule29_followup import FollowUpSuggestion, suggest_rule29_followup
from .project import Stage2Project

SUBMISSION_TYPE_KEY = "cap.business.submission_type"
SUBMISSION_REASON_KEY = "cap.business.submission_reason"
UNIT_PLANT_KEY = "cap.business.unit_plant_name"
CHANGE_LOG_KEY = "cap.prevention.change_log"

SUBMISSION_TYPES = (
    "신규제출", "변경제출", "재제출", "5년 재제출",
    "부적합 후 재제출", "이행점검 부적정 재제출",
)
SUBMISSION_REASONS = ("최초", "부적합")

# 현행 별지 제2호(2026. 4. 22. 시행) 주 ③·⑤의 선택지
CHANGE_TYPES = (
    "㈎ 시설규모 변경", "㈏ 시설위치 변경", "㈐ 시설 재질 변경", "㈑ 취급물질 변경",
    "㈒ 고지계획 변경", "㈓ 정보 현행화", "㈔ 기타",
)
FOLLOW_UPS = ("㈎ 변경제출", "㈏ 변경관리", "㈐ 변경신고", "㈑ 변경허가", "㈒ 기재사항 변경", "해당없음")

CHANGE_TYPE_GUIDANCE = {
    "㈎ 시설규모 변경": "시설의 용량·규모가 바뀐 경우입니다. 예: TK-000 저장용량 20톤에서 15톤으로 변경.",
    "㈏ 시설위치 변경": "취급시설의 설치 위치나 배치가 바뀐 경우입니다. 예: R-000 위치 변경 및 설비배치도 개정.",
    "㈐ 시설 재질 변경": "용기·배관 등 취급시설의 재질이 바뀐 경우입니다. 변경 전·후 재질과 대상 설비를 적습니다.",
    "㈑ 취급물질 변경": "취급 물질의 종류·농도 등 계획서상 물질 정보가 바뀐 경우입니다.",
    "㈒ 고지계획 변경": "지역사회 고지 대상·방법·내용 등 고지계획이 바뀐 경우입니다.",
    "㈓ 정보 현행화": "설비 수량·명칭·연락처 등 계획서 정보를 최신 사실에 맞게 고친 경우입니다.",
    "㈔ 기타": "앞의 분류에 맞지 않는 변경입니다. 변경 내용에 무엇이 달라졌는지 구체적으로 적습니다.",
}

FOLLOW_UP_GUIDANCE = {
    "㈎ 변경제출": "현행 작성 규정 제11조의 제출 요건에 해당해 변경된 계획서를 화학물질안전원에 제출하는 조치입니다. 모든 시설 변경이 자동으로 해당하는 것은 아닙니다.",
    "㈏ 변경관리": "변경제출 요건에는 해당하지 않더라도 변경을 사내 절차로 검토·승인하고, 계획서·도면·운영자료를 관리하며 이 대장에 기록하는 조치입니다.",
    "㈐ 변경신고": "유해화학물질 영업자가 화학물질관리법 시행규칙 제29조의 변경신고 요건에 해당할 때 지방환경관서에 신고하는 조치입니다.",
    "㈑ 변경허가": "유해화학물질 영업자가 시행규칙 제29조의 변경허가 요건에 해당할 때 변경 전에 지방환경관서의 허가를 받는 조치입니다.",
    "㈒ 기재사항 변경": "영업허가 관련 서류의 기재사항을 고치는 조치입니다. 해당 여부와 절차는 허가 형태·변경 내용에 따라 관할 지방환경관서에 확인합니다.",
    "해당없음": "계획서 변경제출·변경관리 또는 영업허가 변경조치가 해당하지 않는다고 확인된 경우에 선택합니다.",
}

CHANGE_ITEM_SUGGESTIONS = (
    "사업장 일반정보", "취급시설 개요", "유해화학물질 목록 및 명세", "유해화학물질 유해성 정보",
    "설비배치도", "사업장 주변 환경정보", "공정개요", "공정흐름도(PFD)", "공정배관계장도(P&ID)",
    "장치·설비 목록 및 명세", "공정위험성 분석 자료", "운전책임자 및 작업자 현황",
    "고정식 유해감지시설 명세 및 배치도", "지역사회 고지계획",
)

LOG_COLUMNS = ("일자", "변경항목", "변경의 종류", "변경 내용(변경전 → 변경후)", "후속조치", "담당자")


def _clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " / ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def format_follow_up_actions(actions: list[str], dates: Mapping[str, str] | None = None) -> str:
    """Format selected follow-up actions as the statutory form's cell text."""
    dates = dates or {}
    parts = []
    for action in actions:
        label = _clean(action)
        if not label:
            continue
        if label == "해당없음":
            parts.append(label)
            continue
        name = label.split(" ", 1)[1] if label.startswith(("㈎ ", "㈏ ", "㈐ ", "㈑ ", "㈒ ")) else label
        action_date = _clean(dates.get(label))
        parts.append(f"{name}({action_date})" if action_date else name)
    return " / ".join(parts)


def submission(project: Stage2Project) -> dict[str, str]:
    def value(key: str) -> str:
        record = project.get_field(key)
        return _clean(record.value) if record else ""

    return {
        "type": value(SUBMISSION_TYPE_KEY),
        "reason": value(SUBMISSION_REASON_KEY),
        "company": project.company_name or "",
        "unit_plant": value(UNIT_PLANT_KEY) or project.site_name or "",
    }


def save_submission(project: Stage2Project, submission_type: str, reason: str, unit_plant: str) -> None:
    for key, label, value in (
        (SUBMISSION_TYPE_KEY, "제출구분", submission_type),
        (SUBMISSION_REASON_KEY, "제출 사유", reason),
        (UNIT_PLANT_KEY, "단위공장명", unit_plant),
    ):
        if _clean(value):
            project.set_field(key, label, _clean(value), "USER_CONFIRMED",
                              note="CAP 작성대 별지 제2호에서 입력(별지 제3호와 공유)")


def change_log_rows(project: Stage2Project) -> list[dict[str, Any]]:
    record = project.get_field(CHANGE_LOG_KEY)
    if record is None or not isinstance(record.value, list):
        return []
    return [dict(row) for row in record.value if isinstance(row, Mapping)]


def save_change_log(project: Stage2Project, rows: list[Mapping[str, Any]]) -> int:
    cleaned = [
        {column: _clean(row.get(column)) for column in LOG_COLUMNS}
        for row in rows
        if any(_clean(row.get(column)) for column in LOG_COLUMNS)
    ]
    project.set_field(CHANGE_LOG_KEY, "변경내역 관리대장(별지 제2호 작성대)", cleaned, "USER_CONFIRMED",
                      note="CAP 작성대의 별지 제2호에서 직접 입력")
    return len(cleaned)


@dataclass(frozen=True)
class Form2State:
    applies: bool | None  # None: 아직 판단할 수 없음
    readiness: CAPForm2Readiness
    headline: str


def resolve_form2(project: Stage2Project) -> Form2State:
    readiness = build_cap_form2_readiness(project)
    if readiness.status == NOT_APPLICABLE:
        return Form2State(False, readiness, "이번 제출에는 별지 제2호를 작성하지 않아도 됩니다(신규 최초 제출).")
    if readiness.status == "REVIEW_REQUIRED":
        return Form2State(None, readiness, "제출구분을 입력하면 이 서식이 필요한지 알려 드립니다.")
    return Form2State(True, readiness, "변경·재제출 자료이므로 변경내역 관리대장을 작성합니다.")


def rule29_followup_suggestion(facts: Mapping[str, Any]) -> FollowUpSuggestion:
    """시행규칙 제29조에 따라 변경신고·변경허가 후보를 fail-closed로 제안합니다."""
    return suggest_rule29_followup(facts)


def form_title(form_no: int) -> str:
    return f"별지 제{form_no}호서식 · {cap_guideline.form_guidelines()[form_no].title}"
