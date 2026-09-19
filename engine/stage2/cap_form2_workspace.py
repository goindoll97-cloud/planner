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
from .project import Stage2Project

SUBMISSION_TYPE_KEY = "cap.business.submission_type"
SUBMISSION_REASON_KEY = "cap.business.submission_reason"
UNIT_PLANT_KEY = "cap.business.unit_plant_name"
CHANGE_LOG_KEY = "cap.prevention.change_log"

SUBMISSION_TYPES = ("신규제출", "변경제출", "재제출", "이행점검 불이행")
SUBMISSION_REASONS = ("최초", "부적합")

# 별지 제2호 주 ③·⑤ 원문의 선택지
CHANGE_TYPES = (
    "㈎ 취급시설 변경", "㈏ 취급물질 변경", "㈐ 안전장치 및 방재장비·물품 변경", "㈑ 공정운전절차 변경",
    "㈒ 운전 책임자 및 작업자 변경", "㈓ 지역사회 고지 계획 변경", "㈔ 정보 현행화", "㈕ 기타",
)
FOLLOW_UPS = ("㈎ 변경제출", "㈏ 변경관리", "㈐ 변경신고", "㈑ 변경허가", "㈒ 기재사항 변경", "해당없음")

LOG_COLUMNS = ("일자", "변경항목", "변경의 종류", "변경 내용(변경전 → 변경후)", "후속조치", "담당자")


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


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


def form_title(form_no: int) -> str:
    return f"별지 제{form_no}호서식 · {cap_guideline.form_guidelines()[form_no].title}"
