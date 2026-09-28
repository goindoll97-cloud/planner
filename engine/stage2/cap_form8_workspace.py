from __future__ import annotations

"""별지 제8호(사업장 주변 환경 정보) authoring support.

사람은 보호대상 목록(또는 '없음')만 확인한다. 500m 입지 현황의 갑종·을종·
환경수용체 체크박스는 그 목록에서 파생되고, 주소 기반 주변 검색은 후보만
제안한다(확정은 사용자). 「화학사고예방관리계획서 작성 등에 관한 규정」 별표 4의 규모 조건은 도움말로 함께 보여 준다.
"""

from datetime import date
import math
import re
from typing import Any, Mapping

from . import cap_guideline
from .cap_form8_engine import build_cap_form8_data
from .cap_site_lookup import Candidate
from .project import EvidenceRef, Stage2Project

SITE_KEY = "cap.site.surrounding_environment"
REVIEW_KEY = "cap.workspace.form8_review"
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
REVIEW_ITEMS = (
    ("boundary", "사업장 부지 경계와 검토 범위를 도면·지도에서 확인"),
    ("facilities", "학교·병원·주택 등 주변 건물·시설을 확인"),
    ("environment", "하천·산림·농경지·보호구역 등 자연환경을 확인"),
    ("classification", "각 대상의 위치·거리·법정 분류를 근거자료와 대조"),
)


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


def review(project: Stage2Project) -> dict[str, Any]:
    record = project.get_field(REVIEW_KEY)
    value = record.value if record is not None and isinstance(record.value, Mapping) else {}
    return dict(value)


def invalidate_review(project: Stage2Project) -> None:
    """An edited candidate list must not inherit a previous completed review."""
    project.set_field(REVIEW_KEY, "별지 제8호 지도·목록 확인 기록", {}, "HOLD")


def import_company_rows(raw_rows: list[Mapping[str, Any]], existing: list[Mapping[str, Any]] | None = None
                        ) -> tuple[list[dict[str, Any]], list[str]]:
    """Stage a company's old list for human review; never infer its legal category."""
    aliases = {"명칭": "보호대상 명칭", "이름": "보호대상 명칭", "시설명": "보호대상 명칭",
               "시설 이름": "보호대상 명칭", "구분": "보호대상 구분",
               "종류": "세부유형", "보호대상 종류": "세부유형", "주소": "주소·위치", "위치": "주소·위치",
               "거리(m)": "사업장 경계와 거리(m)", "거리": "사업장 경계와 거리(m)",
               "근거자료": "GIS/현장 근거", "확인근거": "GIS/현장 근거"}

    def clean(value: Any) -> Any:
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            return ""
        return value.strip() if isinstance(value, str) else value

    def identity(row: Mapping[str, Any]) -> tuple[str, str]:
        return _norm(row.get("보호대상 명칭")), _norm(row.get("주소·위치"))

    seen = {identity(row) for row in existing or []}
    imported: list[dict[str, Any]] = []
    notices: list[str] = []
    for line, raw in enumerate(raw_rows, start=2):
        values = {aliases.get(str(k).strip(), str(k).strip()): clean(v) for k, v in raw.items()}
        name = str(values.get("보호대상 명칭") or "").strip()
        if not name:
            notices.append(f"{line}행은 보호대상 명칭이 없어 건너뛰었습니다.")
            continue
        row = {column: values.get(column, "") for column in COLUMNS}
        row["500m 범위 전체 확인"] = False
        # Old search metadata is not evidence that the site was checked today.
        row["검색 출처·검색일"] = ""
        row["검색결과 거리(주소점 기준, 참고)"] = ""
        key = identity(row)
        if key in seen:
            notices.append(f"{line}행 ‘{name}’은 같은 이름·위치가 목록에 있어 건너뛰었습니다.")
            continue
        seen.add(key)
        imported.append(row)
    return imported, notices


def classification_suggestion(name: str) -> tuple[str, str, str]:
    """Suggest only recognisable facility types; a name never proves legal eligibility."""
    label = str(name or "").strip().replace(" ", "")
    if label.startswith(("국가하천", "지방하천")):
        return "환경수용체", "하천", "법정 하천 지정 여부를 확인하세요."
    if "생태·경관보호지역" in label:
        return "환경수용체", "생태·경관보호지역", "법정 보호지역 지정 여부를 확인하세요."
    if label.endswith(("국회의원", "시의원", "도의원", "구의원")):
        return "", "", "이름의 '의원'만으로 의료시설인지 알 수 없습니다. 실제 용도를 확인하세요."
    for suffix, category, subtype, reason in (
        ("초등학교", "갑종", "교육·연구시설", "학교의 실제 용도를 확인하세요."),
        ("중학교", "갑종", "교육·연구시설", "학교의 실제 용도를 확인하세요."),
        ("고등학교", "갑종", "교육·연구시설", "학교의 실제 용도를 확인하세요."),
        ("대학교", "갑종", "교육·연구시설", "학교의 실제 용도를 확인하세요."),
        ("도서관", "갑종", "교육·연구시설", "도서관의 실제 용도를 확인하세요."),
        ("연구소", "갑종", "교육·연구시설", "연구소의 실제 용도를 확인하세요."),
        ("병원", "갑종", "의료시설", "병원으로 운영 중인지 확인하세요."),
        ("의원", "갑종", "의료시설", "의원으로 운영 중인지 확인하세요."),
        ("주유소", "을종", "위험물 저장 및 처리시설", "주유소로 운영 중인지 확인하세요."),
        ("LPG충전소", "을종", "위험물 저장 및 처리시설", "충전소의 실제 용도를 확인하세요."),
    ):
        if label.endswith(suffix):
            return category, subtype, reason
    if any(word in label for word in ("아파트", "주택", "교회", "성당", "어린이집", "하천", "강", "공원")):
        return "", "", "시설의 수용 인원·면적 또는 자연환경의 법정 지정 여부를 먼저 확인하세요."
    return "", "", "시설의 실제 용도와 「화학사고예방관리계획서 작성 등에 관한 규정」 별표 4를 확인하세요."


def classification_suggestions(rows: list[Mapping[str, Any]]) -> list[tuple[int, str, str, str, str]]:
    """Propose values only for rows whose category and subtype are both empty."""
    proposals = []
    for index, row in enumerate(rows):
        if str(row.get("보호대상 구분") or "").strip() or str(row.get("세부유형") or "").strip():
            continue
        name = str(row.get("보호대상 명칭") or "").strip()
        if name:
            category, subtype, reason = classification_suggestion(name)
            proposals.append((index, name, category, subtype, reason))
    return proposals


def classify_rows(rows: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Fill recognisable categories in a draft list, preserving existing choices."""
    updated = [dict(row) for row in rows]
    classified = 0
    unresolved = []
    for index, row in enumerate(updated, start=1):
        name = str(row.get("보호대상 명칭") or "").strip()
        if not name:
            unresolved.append(f"{index}행: 시설명을 먼저 입력하세요.")
            continue
        category = str(row.get("보호대상 구분") or "").strip()
        subtype = str(row.get("세부유형") or "").strip()
        if category and subtype:
            if subtype not in SUBTYPES.get(category, ()):
                unresolved.append(f"{index}행 {name}: 입력된 구분과 세부유형이 맞지 않습니다.")
            continue
        possible = [cat for cat, options in SUBTYPES.items() if subtype in options] if subtype else []
        if subtype and not category:
            if len(possible) == 1 and (possible[0] != "환경수용체" or
                                       (subtype == "하천" and name.startswith(("국가하천", "지방하천"))) or
                                       (subtype == "생태·경관보호지역" and "생태·경관보호지역" in name)):
                row["보호대상 구분"] = possible[0]
                classified += 1
            else:
                unresolved.append(f"{index}행 {name}: 세부유형만으로 법정 분류를 결정할 수 없습니다. 지정 여부·용도를 확인하세요.")
            continue
        suggested_category, suggested_subtype, reason = classification_suggestion(name)
        if suggested_category and (not category or category == suggested_category):
            row["보호대상 구분"] = suggested_category
            row["세부유형"] = suggested_subtype
            classified += 1
        else:
            unresolved.append(f"{index}행 {name}: {reason if not category else '입력된 구분과 이름을 대조해 세부유형을 직접 확인하세요.'}")
    return updated, classified, unresolved


def review_issues(rows: list[Mapping[str, Any]], no_target: bool, checks: Mapping[str, bool],
                  source: str, method: str, map_numbers: str) -> list[str]:
    issues = [f"‘{label}’ 항목을 확인해 주세요." for key, label in REVIEW_ITEMS if not checks.get(key)]
    if not source.strip():
        issues.append("확인한 지도·도면과 확인일을 적어 주세요.")
    if not method.strip():
        issues.append("사업장 경계와 거리의 확인 방법을 적어 주세요.")
    if no_target:
        return issues
    names = [str(row.get("보호대상 명칭") or "").strip() for row in rows]
    if not any(names):
        issues.append("보호대상 목록을 입력하거나, 범위 전체 확인 후 ‘보호대상 없음’을 선택하세요.")
        return issues
    if any(not name for name in names):
        issues.append("목록의 빈 행을 삭제하거나 보호대상 명칭을 입력해 주세요.")
    seen: set[tuple[str, str]] = set()
    for index, row in enumerate(rows, start=1):
        name = names[index - 1] or f"{index}행"
        category = str(row.get("보호대상 구분") or "").strip()
        subtype = str(row.get("세부유형") or "").strip()
        if category not in CATEGORIES or subtype not in SUBTYPES.get(category, ()):
            issues.append(f"{name}: 보호대상 구분과 세부유형을 실제 자료로 확인해 주세요.")
        if not str(row.get("주소·위치") or "").strip():
            issues.append(f"{name}: 위치·주소를 확인해 주세요.")
        try:
            raw_distance = row.get("사업장 경계와 거리(m)")
            distance = float(str("" if raw_distance is None else raw_distance).replace(",", ""))
        except ValueError:
            distance = math.nan
        if not math.isfinite(distance) or distance < 0 or distance > 500:
            issues.append(f"{name}: 사업장 경계에서의 거리를 0~500m로 확인해 주세요.")
        if not str(row.get("GIS/현장 근거") or "").strip():
            issues.append(f"{name}: 지도·현장에서 확인한 자료·날짜·방법을 적어 주세요.")
        identity = (_norm(name), category)
        if identity in seen:
            issues.append(f"{name}: 목록에 같은 이름과 구분이 중복되어 있습니다.")
        seen.add(identity)
    if not map_numbers.strip():
        issues.append("지도에 표시한 보호대상 일련번호를 적어 주세요.")
    else:
        numbers = [part.strip() for part in map_numbers.split(",")]
        expected = set(range(1, len(names) + 1))
        if not all(n.isdigit() for n in numbers) or len(numbers) != len(expected) or {int(n) for n in numbers} != expected:
            issues.append(f"지도 번호와 목록 번호를 대조해 주세요. 목록에는 1~{len(names)}번이 있습니다.")
    return issues


def save_review(project: Stage2Project, checks: Mapping[str, bool], source: str,
                method: str, map_numbers: str, evidence: list[EvidenceRef] | None = None) -> None:
    project.set_field(REVIEW_KEY, "별지 제8호 지도·목록 확인 기록", {
        "확인항목": {key: bool(checks.get(key)) for key, _ in REVIEW_ITEMS},
        "사용자료·확인일": source.strip(), "경계·거리 확인방법": method.strip(),
        "지도 번호": map_numbers.strip(),
    }, "USER_CONFIRMED", evidence=evidence)


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


def candidate_row(candidate: Candidate, *, unclassified: bool = False) -> dict[str, Any]:
    # A provider's search term is not proof of the legal classification.
    # Only suggest readily recognisable types; occupancy and designation cases
    # (housing, worship, waterways, etc.) remain blank for human review.
    source = candidate.source
    kakao_code = source.rsplit("분류 ", 1)[-1] if "카카오 로컬 API · 분류 " in source else ""
    safe_kakao = {"SC4", "HP8", "OL7", "MT1", "SW8"}
    suggested = kakao_code in safe_kakao
    if "카카오 로컬 API · 검색어 " in source:
        suggested = source.rsplit("검색어 ", 1)[-1] in {"공장", "근린생활시설", "국립공원", "도립공원", "군립공원", "생태경관보전지역"}
    if "브이월드 2D 데이터 API" in source:
        suggested = any(label in source for label in ("습지보호지역", "습지보호구역", "국립자연공원", "산림보호구역", "상수원보호구역", "생태계경관보전지역"))
    category = candidate.category if suggested and not unclassified else ""
    subtype = candidate.subtype if suggested and not unclassified else ""
    if suggested and "브이월드 2D 데이터 API" in source:
        mapping = {"습지보호지역": "습지보호지역", "습지보호구역": "습지보호지역",
                   "국립자연공원": "자연공원", "산림보호구역": "산림지 및 유적지",
                   "상수원보호구역": "상수원 및 취수원", "생태계경관보전지역": "생태·경관보호지역"}
        category = "환경수용체"
        subtype = next((value for label, value in mapping.items() if label in source), "")
    if not unclassified and "OpenStreetMap/Overpass 지도 객체" in source:
        osm_types = {"amenity=school": ("갑종", "교육·연구시설"),
                     "amenity=university": ("갑종", "교육·연구시설"),
                     "amenity=hospital": ("갑종", "의료시설"),
                     "amenity=clinic": ("갑종", "의료시설"),
                     "landuse=industrial": ("을종", "공업시설")}
        tag = candidate.address.split("지도 분류: ", 1)[-1].split(" · ", 1)[0]
        category, subtype = osm_types.get(tag, ("", ""))
    if not unclassified and "국토정보플랫폼 검색 API" in source:
        # Use the provider's type, never a substring of the place name (e.g.
        # a bus stop named after a school is not itself a school).
        type_path = candidate.address.split("지도 분류: ", 1)[-1] if "지도 분류: " in candidate.address else ""
        leaves = {part.strip() for part in type_path.split(">")}
        if leaves & {"초등학교", "중학교", "고등학교", "대학교", "대학", "학교"}:
            category, subtype = "갑종", "교육·연구시설"
        elif leaves & {"병원", "의원"}:
            category, subtype = "갑종", "의료시설"
    return {
        "보호대상 명칭": candidate.name,
        "보호대상 구분": category,
        "세부유형": subtype,
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
