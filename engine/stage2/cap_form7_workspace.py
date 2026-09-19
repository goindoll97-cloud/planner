from __future__ import annotations

"""별지 제7호(유해화학물질의 유해성 정보) authoring support.

법령 기준: 화학물질관리법 시행규칙 별표 4 제1호 나목 2)는 유해성이 가장 큰 대표물질 2종을,
작성 규정 제19조 ③은 독성 누출·화재·폭발 사고유형별로 유해성이 큰 대표물질을 선정 사유와 함께
별지 제7호에 적도록 한다. 두 규정이 함께 충족되도록 대표물질은 2종(가능하면 독성 1종 +
화재·폭발 1종)으로 제안한다. 매뉴얼의 "사고유형별 2종(최대 4종)"보다 법령이 우선한다.
대표물질은 별지 제6호 물성(폭발한계 하한, 급성독성 구분)으로 제안하고, 서술 초안은 KOSHA
참고자료(단일물질)에서 가져오며, 사람은 확인·수정만 한다.
"""

from dataclasses import dataclass
import re
from typing import Any, Mapping

from . import cap_form6_workspace as f6
from .cap_authoritative import cap_form7_reference_candidates
from .cap_sds_engine import build_cap_form7_data
from .msds_reference import stored_msds_reference
from .project import Stage2Project

HAZARD_KEY = "cap.chemical.hazard_information"
KOSHA_SOURCE = "KOSHA 물질안전보건자료(참고, CAS 조회)"
FIRE, TOXIC = "화재·폭발", "독성"
MAX_REPRESENTATIVES = 2  # 시행규칙 별표 4: 대표물질 2종 (매뉴얼의 4종보다 법령 우선)


@dataclass(frozen=True)
class Suggestion:
    name: str
    cas: str
    kinds: tuple[str, ...]
    reason: str


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _number(text: object) -> float | None:
    found = re.search(r"-?\d+(?:\.\d+)?", _clean(text).replace(",", ""))
    return float(found.group(0)) if found else None


def _category(text: object) -> int | None:
    found = re.search(r"구분\s*([1-5])", _clean(text))
    return int(found.group(1)) if found else None


def suggest_representatives(project: Stage2Project) -> list[Suggestion]:
    """Rank by 별지 제6호 facts: lowest 폭발하한 → 화재·폭발, lowest 급성독성 구분 → 독성."""
    rows = f6.property_rows(project)
    fire = sorted(
        ((_number(r.get("폭발한계 하한")), r) for r in rows if _number(r.get("폭발한계 하한")) is not None),
        key=lambda pair: pair[0],
    )
    toxic = sorted(
        ((_category(r.get("독성구분")), r) for r in rows if _category(r.get("독성구분")) is not None),
        key=lambda pair: pair[0],
    )
    picked: dict[str, dict[str, Any]] = {}

    def add(kind: str, value: float, row: dict[str, Any]) -> None:
        entry = picked.setdefault(row["CAS 번호"], {"row": row, "kinds": [], "reasons": []})
        if kind in entry["kinds"]:
            return
        entry["kinds"].append(kind)
        if kind == FIRE:
            entry["reasons"].append(f"폭발한계 하한이 {value:g}%로 낮아 화재·폭발 위험이 큰 물질")
        else:
            entry["reasons"].append(f"{_clean(row.get('독성구분 항목')) or '급성독성'} 구분 {value:g}로 독성이 큰 물질")

    # 사고유형별로 가장 유해성이 큰 물질 1종씩, 겹치면 다음 순위로 채워 모두 2종 이내
    for kind, ranked in ((FIRE, fire), (TOXIC, toxic)):
        if ranked:
            add(kind, ranked[0][0], ranked[0][1])
    for kind, ranked in ((FIRE, fire), (TOXIC, toxic)):
        for value, row in ranked:
            if len(picked) >= MAX_REPRESENTATIVES:
                break
            if row["CAS 번호"] not in picked:
                add(kind, value, row)
    return [
        Suggestion(item["row"]["물질명"], cas, tuple(item["kinds"]), "이고, ".join(item["reasons"]) + "이므로 대표물질로 선정함")
        for cas, item in picked.items()
    ]


def _candidate_for(project: Stage2Project, cas: str) -> Mapping[str, str]:
    for row in cap_form7_reference_candidates(project):
        if row.get("CAS 번호") == cas:
            return row
    return {}


def draft_row(project: Stage2Project, cas: str, name: str, reason: str = "") -> dict[str, str]:
    """Editable draft: KOSHA explicit text where available, blank otherwise."""
    candidate = _candidate_for(project, cas)
    props = next((r for r in f6.property_rows(project) if r["CAS 번호"] == cas), {})
    reference = stored_msds_reference(project, cas) or {}
    return {
        "물질명": name,
        "CAS 번호": cas,
        "인체유해성": _clean(candidate.get("인체유해성 후보")),
        "물리적 위험성": _clean(candidate.get("물리적 위험성 후보")),
        "환경유해성": _clean(candidate.get("환경유해성 후보")),
        "출처": KOSHA_SOURCE if candidate else "",
        "선정 사유": reason,
        "SDS 파일명": _clean(props.get("SDS 파일명")) or (KOSHA_SOURCE if candidate else ""),
        "SDS 개정일": _clean(props.get("SDS 개정일")) or _clean(reference.get("checked_at_utc"))[:10],
    }


def saved_rows(project: Stage2Project) -> list[dict[str, Any]]:
    record = project.get_field(HAZARD_KEY)
    if record is None or not isinstance(record.value, list):
        return []
    return [dict(row) for row in record.value if isinstance(row, Mapping)]


def save_rows(project: Stage2Project, rows: list[Mapping[str, Any]]) -> int:
    cleaned = [{k: _clean(v) for k, v in row.items()} for row in rows if _clean(row.get("물질명")) or _clean(row.get("CAS 번호"))]
    project.set_field(HAZARD_KEY, "유해화학물질 유해성 정보(별지 제7호 작성대)", cleaned, "USER_CONFIRMED",
                      note="CAP 작성대 별지 제7호에서 대표물질과 서술을 확인·입력")
    return len(cleaned)


def needs(project: Stage2Project) -> list[str]:
    return list(build_cap_form7_data(project).blockers)
