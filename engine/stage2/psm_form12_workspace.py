from __future__ import annotations

"""PSM 별지 제12호(사업개요) 작성. 이미 입력한 사업장 정보는 다시 묻지 않고 가져온다."""

from typing import Any, Mapping

from .psm_form12_consequence_engine import FORM12_HEADERS, VALID_PROJECT_TYPES
from .project import Stage2Project

KEY = "psm.business.form12_details"
PROJECT_TYPES = ("설치이전", "변경", "기존설비")

# (서식 칸, 이미 있는 사실의 키). 앞쪽이 우선한다.
PREFILL = {
    "사업자등록번호": ("business.registration_no", "cap.business.registration_no"),
    "대표자": ("business.representative", "cap.business.representative"),
    "작성자 성명": ("cap.business.writer_name",),
    "사업장 소재지": ("business.address",),
    "전화번호": ("business.phone", "cap.business.contact"),
    "주요 생산품": ("business.main_products",),
}
# 화면에서 물어야 하는 칸(설명은 화면에 그대로 보인다)
QUESTIONS = (
    ("제출구분", "choice", "이 보고서가 새로 설치·이전하는 설비인지, 변경인지, 이미 운영 중인 설비인지 고릅니다."),
    ("대상 유해·위험설비", "text", "공정안전보고서를 내는 대상 설비 이름입니다. 예: 염소 저장·투입 설비"),
    ("한국표준산업분류", "text", "사업장의 업종 분류(코드와 이름)입니다. 사업자등록증이나 사업개시신고에서 확인합니다."),
    ("근로자수", "text", "예상 근무 근로자 수입니다."),
    ("계약전력(kW)", "text", "전기 계약용량입니다. 전기요금 고지서에서 확인합니다."),
    ("작성자 자격", "text", "보고서 작성자의 자격(예: 화공기사, 공정안전 전문가)입니다."),
    ("주요 원료", "text", "주로 쓰는 원료 이름입니다. 비워 두면 물질 목록에서 가져옵니다."),
    ("사업개요", "text", "사업의 주요 내용 또는 변경 내용을 적습니다."),
    ("전송번호", "text", "팩스 번호입니다. 없으면 '해당 없음'이라고 적습니다."),
    ("부지면적", "text", "사업장 부지 면적입니다."),
    ("주요 건물", "text", "주요 건물 이름입니다."),
    ("총 사업기간", "text", "설치·이전·변경 사업의 전체 기간입니다."),
    ("착공예정일", "text", "착공 예정일입니다."),
    ("시운전기간", "text", "시운전 기간입니다."),
)
# 별지 제12호는 모든 칸이 차 있어야 최종 점검을 통과한다. 해당 없는 칸은 '해당 없음'을 적는다.
NOT_APPLICABLE_HINT = "해당하지 않으면 '해당 없음'이라고 적으세요."


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _fact(project: Stage2Project, keys: tuple[str, ...]) -> str:
    for key in keys:
        record = project.get_field(key)
        if record is not None and _clean(record.value) and not isinstance(record.value, (list, dict)):
            return _clean(record.value)
    return ""


def prefilled(project: Stage2Project) -> dict[str, str]:
    values = {"사업장명": project.company_name}
    for header, keys in PREFILL.items():
        values[header] = _fact(project, keys)
    chemicals = project.get_field("inventory.chemicals")
    if chemicals is not None and isinstance(chemicals.value, list):
        names = [_clean(r.get("물질명") or r.get("제품명")) for r in chemicals.value if isinstance(r, Mapping)]
        values["주요 원료"] = ", ".join(n for n in names if n)[:200]
    return {k: v for k, v in values.items() if v}


def saved(project: Stage2Project) -> dict[str, str]:
    record = project.get_field(KEY)
    if record is None or not isinstance(record.value, list) or not record.value or not isinstance(record.value[0], Mapping):
        return {}
    return {k: _clean(v) for k, v in record.value[0].items() if _clean(v)}


def current(project: Stage2Project) -> dict[str, str]:
    """이미 있는 사실 위에 이 화면에서 적은 값을 덮는다."""
    return {**prefilled(project), **saved(project)}


def save(project: Stage2Project, values: Mapping[str, Any]) -> int:
    """빈 칸은 이미 적은 값을 지우지 않는다."""
    row = {**saved(project)}
    for header in FORM12_HEADERS:
        text = _clean(values.get(header))
        if text:
            row[header] = text
    project.set_field(KEY, "사업개요(별지 제12호 작성대)", [row], "USER_CONFIRMED")
    return len(row)


def needs(project: Stage2Project) -> list[str]:
    have = current(project)
    out = [h for h in FORM12_HEADERS if not have.get(h)]
    if have.get("제출구분") and have["제출구분"] not in VALID_PROJECT_TYPES:
        out.append("제출구분(설치이전·변경·기존설비 중 하나)")
    return out
