from __future__ import annotations

"""별지 제8호(사업장 주변 환경 정보) authoring support.

사람은 보호대상 목록(또는 '없음')만 확인한다. 500m 입지 현황의 갑종·을종·
환경수용체 체크박스는 그 목록에서 파생되고, 주소 기반 주변 검색은 후보만
제안한다(확정은 사용자). 「화학사고예방관리계획서 작성 등에 관한 규정」 별표 4의 규모 조건은 도움말로 함께 보여 준다.
"""

from datetime import date
import re
from typing import Any, Mapping

from . import cap_guideline
from .cap_form8_engine import build_cap_form8_data
from .cap_site_lookup import Candidate
from .project import Stage2Project

SITE_KEY = "cap.site.surrounding_environment"
ADDRESS_KEY = "business.address"
CATEGORIES = ("갑종", "을종", "환경수용체")
SUBTYPES = {
    "갑종": ("문화·집회시설", "종교시설", "판매시설", "운수시설", "의료시설", "교육·연구시설",
            "노유자시설", "숙박시설", "관광휴게시설", "수련시설", "주택"),
    "을종": ("주택·업무시설", "근린 생활시설", "위험물 저장 및 처리시설", "기타 건축물", "공업시설"),
    "환경수용체": ("생태·경관보호지역", "하천", "자연공원", "산림지 및 유적지", "습지보호지역",
              "상수원 및 취수원", "농경지", "기타 환경수용체"),
}
COLUMNS = ("보호대상 명칭", "보호대상 구분", "세부유형", "주소·위치", "사업장 경계와 거리(m)",
           "검색결과 거리(주소점 기준, 참고)", "검색 출처·검색일", "GIS/현장 근거", "거주민수", "근로자수",
           "500m 범위 전체 확인")
NO_TARGET = "보호대상 없음 여부"


def _norm(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", str(value or "")).lower()


def address(project: Stage2Project) -> str:
    record = project.get_field(ADDRESS_KEY)
    return "" if record is None or record.value is None else str(record.value).strip()


def type_hint(category: str, subtype: str) -> str:
    """화학사고예방관리계획서 작성 등에 관한 규정 별표 4의 세부유형·규모 조건."""
    rules = cap_guideline.protected_target_rules().get(category, {})
    for name, text in rules.items():
        key = _norm(name)
        if key and (key in _norm(subtype) or _norm(subtype) in key):
            return f"{name}: {text}"
    return ""


def saved_rows(project: Stage2Project) -> list[dict[str, Any]]:
    record = project.get_field(SITE_KEY)
    if record is None or not isinstance(record.value, list):
        return []
    return [dict(r) for r in record.value if isinstance(r, Mapping) and _norm(r.get(NO_TARGET)) in ("", "아니오", "no", "n")]


def declared_no_target(project: Stage2Project) -> bool:
    record = project.get_field(SITE_KEY)
    if record is None or not isinstance(record.value, list):
        return False
    return any(isinstance(r, Mapping) and _norm(r.get(NO_TARGET)) in ("예", "yes", "y") for r in record.value)


def scope_reviewed(project: Stage2Project) -> bool:
    """Whether the user explicitly attested that the entire statutory area was reviewed."""
    record = project.get_field(SITE_KEY)
    if record is None or not isinstance(record.value, list) or not record.value:
        return False
    return all(_norm(row.get("500m 범위 전체 확인")) in ("true", "예", "yes", "1")
               for row in record.value if isinstance(row, Mapping))


def save(project: Stage2Project, rows: list[Mapping[str, Any]], no_target: bool, evidence: str = "",
         scope_reviewed: bool = False, status: str = "USER_CONFIRMED") -> int:
    if no_target:
        stored: list[dict[str, Any]] = [{NO_TARGET: "예", "GIS/현장 근거": evidence.strip(),
                                         "500m 범위 전체 확인": bool(scope_reviewed)}]
    else:
        stored = [
            {column: (bool(scope_reviewed) if column == "500m 범위 전체 확인"
                       else ("" if r.get(column) is None else r.get(column))) for column in COLUMNS}
            for r in rows if str(r.get("보호대상 명칭") or "").strip()
        ]
    project.set_field(SITE_KEY, "사업장 주변 환경 정보(별지 제8호 작성대)", stored, status,
                      note="CAP 작성대 별지 제8호에서 보호대상 목록을 확인·입력")
    return 0 if no_target else len(stored)


def candidate_row(candidate: Candidate) -> dict[str, Any]:
    return {
        "보호대상 명칭": candidate.name, "보호대상 구분": candidate.category, "세부유형": candidate.subtype,
        "주소·위치": candidate.address,
        "사업장 경계와 거리(m)": "",
        "검색결과 거리(주소점 기준, 참고)": "" if candidate.distance_m is None else candidate.distance_m,
        "검색 출처·검색일": f"{candidate.source} · {date.today().isoformat()}",
        "GIS/현장 근거": "",
        "500m 범위 전체 확인": False,
    }


def selected_options(project: Stage2Project) -> dict[str, set[str]]:
    """Which printed checkbox options apply, derived from the receptor list."""
    chosen: dict[str, set[str]] = {c: set() for c in CATEGORIES}
    for row in saved_rows(project):
        if _norm(row.get("500m 범위 전체 확인")) not in ("true", "예", "yes", "1"):
            continue
        category = str(row.get("보호대상 구분") or "")
        for option in SUBTYPES.get(category, ()):
            if _norm(option) == _norm(row.get("세부유형")):
                chosen[category].add(option)
    return chosen


def needs(project: Stage2Project) -> list[str]:
    return list(build_cap_form8_data(project).blockers)
