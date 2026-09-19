from __future__ import annotations

"""KOSHA-assisted chemical information for single substances.

Only the CAS number is sent to KOSHA. The result is stored as a reference
(never as a company fact). Values KOSHA states explicitly become *candidates*;
they are written into the company chemical table only when the user accepts
them, never over a value the company already entered.
"""

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from . import cap_endpoints
from .cap_authoritative import cap_form6_msds_candidates
from .msds_reference import (
    MSDSRefreshItem,
    extract_cas_numbers,
    inventory_chemicals,
    refresh_msds_references,
    stored_msds_reference,
)
from .project import CONFIRMED_STATUSES, Stage2Project

DETAILS_KEY = "cap.chemical.details"
INVENTORY_KEY = "inventory.chemicals"

# candidate field (cap_authoritative) -> column name the 별지 제6호 writer reads
ROW_COLUMN = {
    "물질상태": "물질상태",
    "비중": "비중",
    "폭발한계 하한(%)": "폭발한계 하한",
    "폭발한계 상한(%)": "폭발한계 상한",
    "독성구분-항목": "독성구분 항목",
    "독성구분-구분": "독성구분",
    "위험노출수준": "위험노출수준",
    "허용농도값": "허용농도값",
    "증기압(20℃, mmHg)": "증기압",
    "부식성(유, 무)": "부식성",
    "분자량": "분자량",
}
KOSHA_SDS_FILE = "KOSHA MSDS 참고자료(CAS 조회)"


@dataclass(frozen=True)
class Candidate:
    cas: str
    name: str
    field: str
    value: str
    source: str


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _rows(project: Stage2Project) -> tuple[str, list[dict[str, Any]]]:
    for key in (DETAILS_KEY, INVENTORY_KEY):
        record = project.get_field(key)
        if record is not None and record.status in CONFIRMED_STATUSES and isinstance(record.value, list):
            rows = [dict(row) for row in record.value if isinstance(row, Mapping)]
            if rows:
                return key, rows
    return "", []


def _row_cas(row: Mapping[str, Any]) -> tuple[str, ...]:
    text = " ".join(_clean(row.get(k)) for k in ("CAS 번호", "CAS No.", "CAS", "화학물질식별번호"))
    return extract_cas_numbers(text)


def _is_mixture(row: Mapping[str, Any]) -> bool:
    if len(_row_cas(row)) != 1:
        return True
    return any("혼합" in _clean(value) for key, value in row.items() if "구분" in key or "유형" in key or "형태" in key)


def single_substance_cas(project: Stage2Project) -> list[str]:
    """CAS numbers of single-substance rows; mixtures are never looked up."""
    _, rows = _rows(project)
    return list(dict.fromkeys(_row_cas(row)[0] for row in rows if not _is_mixture(row)))


def fetch_references(project: Stage2Project, lookup: Callable | None = None) -> tuple[MSDSRefreshItem, ...]:
    cas = single_substance_cas(project)
    if not cas:
        return ()
    kwargs = {"lookup": lookup} if lookup else {}
    return refresh_msds_references(project, cas_numbers=cas, **kwargs)


GUIDELINE_SOURCE = "기술지침 붙임 1 (ERPG-2 → AEGL-2 → PAC-2 → IDLH 우선순위)"


def guideline_candidates(project: Stage2Project) -> list[Candidate]:
    """위험노출수준 from the 기술지침 끝점농도 tables (law tier; no KOSHA call needed)."""
    _, rows = _rows(project)
    out = []
    for row in rows:
        if _is_mixture(row):
            continue
        cas = _row_cas(row)[0]
        endpoint = cap_endpoints.endpoint_for(cas)
        if endpoint is None:
            continue
        name = _clean(row.get("물질명") or row.get("유해화학물질명"))
        out.append(Candidate(cas, name, "위험노출수준", f"{endpoint.table} {endpoint.value:g} {endpoint.unit}", GUIDELINE_SOURCE))
    return out


def candidates(project: Stage2Project) -> list[Candidate]:
    allowed = set(single_substance_cas(project))
    guideline = guideline_candidates(project)
    covered = {c.cas for c in guideline}
    kosha = [
        Candidate(c.cas, c.chemical_name, c.field, c.value, c.source_text)
        for c in cap_form6_msds_candidates(project)
        if c.cas in allowed and c.field in ROW_COLUMN and not (c.field == "위험노출수준" and c.cas in covered)
    ]
    return guideline + kosha


def has_reference(project: Stage2Project, cas: str) -> bool:
    return stored_msds_reference(project, cas) is not None


def apply_candidates(project: Stage2Project, cas_numbers: list[str]) -> int:
    """Write accepted KOSHA values into the company table; never overwrite entered values."""
    key, rows = _rows(project)
    if not rows:
        return 0
    accepted = set(cas_numbers)
    by_cas: dict[str, list[Candidate]] = {}
    for candidate in candidates(project):
        if candidate.cas in accepted:
            by_cas.setdefault(candidate.cas, []).append(candidate)
    written = 0
    for row in rows:
        cas_list = _row_cas(row)
        if len(cas_list) != 1 or cas_list[0] not in by_cas:
            continue
        from_kosha = False
        for candidate in by_cas[cas_list[0]]:
            column = ROW_COLUMN[candidate.field]
            if not _clean(row.get(column)):
                row[column] = candidate.value
                written += 1
                from_kosha = from_kosha or candidate.source != GUIDELINE_SOURCE
        reference = stored_msds_reference(project, cas_list[0]) or {}
        if from_kosha and not _clean(row.get("SDS 파일명")):
            row["SDS 파일명"] = KOSHA_SDS_FILE
        if from_kosha and not _clean(row.get("SDS 개정일")):
            row["SDS 개정일"] = _clean(reference.get("checked_at_utc"))[:10]
    if written:
        project.set_field(
            DETAILS_KEY, "화학물질 상세(KOSHA 조회값 확인 반영)", rows, "USER_CONFIRMED",
            note="사용자가 KOSHA CAS 조회 후보를 확인하고 반영함. 이미 입력된 값은 덮어쓰지 않음. 제품 SDS와 대조 권장.",
        )
    return written
