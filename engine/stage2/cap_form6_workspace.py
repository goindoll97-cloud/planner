from __future__ import annotations

"""별지 제6호(유해화학물질 목록 및 명세) authoring support.

물질명·CAS·함량은 화학물질 목록에서, 물질구분·고유번호는 승인된 규정 DB에서
자동으로 채우고, 물성 칸은 KOSHA 후보(단일물질) 확인 또는 직접 입력으로 채운다.
"""

from typing import Any, Mapping

from .cap_sds_engine import build_cap_form6_sds_data
from . import cap_chemical_workspace as chem
from .project import Stage2Project

# (row column, form label, help). Row columns are the names the 별지 제6호 writer reads.
PROPERTY_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("물질상태", "물질 상태", "기체·액체·고체 중 하나입니다. 제품 MSDS 제9항의 물리적 상태를 옮깁니다."),
    ("비중", "비중", "제품 MSDS 제9항의 비중(상대밀도)입니다."),
    ("폭발한계 하한", "폭발한계 하한(%)", "제품 MSDS 제9항의 폭발(인화) 하한입니다. 해당 없으면 '해당 없음'이라고 적습니다."),
    ("폭발한계 상한", "폭발한계 상한(%)", "제품 MSDS 제9항의 폭발(인화) 상한입니다. 해당 없으면 '해당 없음'이라고 적습니다."),
    ("독성구분 항목", "독성구분 항목", "급성독성의 노출 경로입니다(예시: 급성 독성(흡입))."),
    ("독성구분", "독성구분 구분", "급성독성 구분 번호입니다(예시: 구분 2). MSDS 제2항에서 확인합니다."),
    ("위험노출수준", "위험노출수준", "ERPG → AEGL → PAC → IDLH 순서로 값이 있는 첫 항목을 적습니다(매뉴얼 기준)."),
    ("허용농도값", "허용농도값", "MSDS 제8항의 노출기준(TWA)입니다."),
    ("증기압", "증기압(20℃, mmHg)", "20℃에서의 증기압(mmHg)입니다. 다른 단위면 mmHg로 환산해 적습니다."),
    ("부식성", "부식성(유, 무)", "금속부식성이 있으면 '유', 없으면 '무'입니다."),
    ("SDS 파일명", "근거 MSDS 파일명", "물성값의 출처를 확인할 수 있는 자료명입니다. KOSHA 참고자료를 반영한 값은 실제 제품의 제조·공급자 MSDS와 구분해 확인하세요."),
    ("SDS 개정일", "MSDS 개정일", "그 MSDS의 작성일 또는 개정일입니다."),
)
COLUMN_IDS = tuple(column for column, _, _ in PROPERTY_COLUMNS)


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def property_rows(project: Stage2Project) -> list[dict[str, Any]]:
    """One row per chemical: identity (read-only) plus the editable property columns."""
    _, rows = chem._rows(project)
    out = []
    for row in rows:
        item = {
            "물질명": _clean(row.get("물질명") or row.get("유해화학물질명") or row.get("제품명")),
            "CAS 번호": _clean(row.get("CAS 번호") or row.get("CAS No.") or row.get("CAS")),
        }
        for column in COLUMN_IDS:
            item[column] = _clean(row.get(column))
        out.append(item)
    return out


def save_properties(project: Stage2Project, edited: list[Mapping[str, Any]]) -> int:
    """Merge edited property cells into the company table; blanks never erase values."""
    key, rows = chem._rows(project)
    if not rows:
        return 0
    by_cas = {_clean(item.get("CAS 번호")): item for item in edited}
    changed = 0
    for row in rows:
        source = by_cas.get(_clean(row.get("CAS 번호") or row.get("CAS No.") or row.get("CAS")))
        if not source:
            continue
        for column in COLUMN_IDS:
            value = _clean(source.get(column))
            if value and value != _clean(row.get(column)):
                row[column] = value
                changed += 1
    if changed:
        project.set_field(
            chem.DETAILS_KEY, "화학물질 상세(별지 제6호 작성대)", rows, "USER_CONFIRMED",
            note="CAP 작성대 별지 제6호에서 물성 입력·확인",
        )
    return changed


def legal_rows(project: Stage2Project) -> tuple[list[dict[str, Any]], list[str]]:
    """Rows with 물질구분·고유번호 derived from the legal DB, and what is still missing."""
    data = build_cap_form6_sds_data(project)
    return [dict(row) for row in data.rows], list(data.blockers)
