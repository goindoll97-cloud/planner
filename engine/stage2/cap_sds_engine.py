from __future__ import annotations

"""Prepare company-SDS-backed CAP Form 6/7 data without external MSDS lookup.

The company workbook is the factual transcription source. Each Form 6 physical-
property row must identify the actual SDS file and revision/date used. Form 7
hazard information is also company-confirmed and is enriched only with legal
identity and holding quantities that the deterministic CAP engines already
validated.
"""

from dataclasses import dataclass
from collections.abc import Mapping
import re
from typing import Any

from .cap_chemical_legal import build_cap_chemical_legal_data
from .cap_form1_engine import build_cap_form1_data
from .project import CONFIRMED_STATUSES, Stage2Project


_EXPLICIT_NA = {
    "해당없음", "없음", "자료없음", "정보없음", "미해당",
    "na", "n/a", "notapplicable", "notavailable",
}

_FORM6_SDS_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("비중", ("비중", "밀도/비중")),
    ("폭발한계 하한", ("폭발한계 하한", "폭발하한", "LEL")),
    ("폭발한계 상한", ("폭발한계 상한", "폭발상한", "UEL")),
    ("독성구분 항목", ("독성구분 항목", "독성구분-항목")),
    ("독성구분", ("독성구분", "독성구분-구분")),
    ("위험노출수준", ("위험노출수준", "ERPG", "AEGL", "PAC", "IDLH")),
    ("허용농도값", ("허용농도값", "TWA", "노출기준")),
    ("증기압", ("증기압", "증기압(20℃, mmHg)")),
    ("부식성", ("부식성", "부식성(유, 무)")),
)


@dataclass(frozen=True)
class CAPForm6SDSData:
    rows: tuple[dict[str, Any], ...]
    blockers: tuple[str, ...]
    messages: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return bool(self.rows) and not self.blockers


@dataclass(frozen=True)
class CAPForm7Data:
    row: dict[str, Any]
    blockers: tuple[str, ...]
    messages: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return bool(self.row) and not self.blockers


def _clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def _norm(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", _clean(value)).lower()


def _row_value(row: Mapping[str, Any], *aliases: str) -> Any:
    normalized = {_norm(key): value for key, value in row.items()}
    for alias in aliases:
        value = normalized.get(_norm(alias))
        if value not in (None, "") and _clean(value):
            return value
    return ""


def _present(value: object) -> bool:
    return bool(_clean(value))


def _present_or_na(value: object) -> bool:
    text = _clean(value)
    if not text:
        return False
    return True  # explicit N/A text is intentionally accepted as a company SDS fact


def _confirmed_rows(project: Stage2Project, *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        rec = project.get_field(key)
        if rec is None or rec.status not in CONFIRMED_STATUSES:
            continue
        if isinstance(rec.value, list):
            rows = [dict(row) for row in rec.value if isinstance(row, Mapping)]
            if rows:
                return rows
    return []


def _index_rows(rows: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_cas: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        cas = _clean(_row_value(row, "CAS 번호", "CAS No.", "CAS", "화학물질식별번호(CAS 번호)"))
        name = _clean(_row_value(row, "물질명", "유해화학물질명", "제품명"))
        if cas:
            by_cas.setdefault(cas, dict(row))
        if name:
            by_name.setdefault(_norm(name), dict(row))
    return by_cas, by_name


def build_cap_form6_sds_data(project: Stage2Project) -> CAPForm6SDSData:
    legal = build_cap_chemical_legal_data(project)
    blockers: list[str] = list(legal.blockers)
    messages: list[str] = list(legal.messages)
    rows: list[dict[str, Any]] = []

    for index, source in enumerate(legal.rows, start=1):
        row = dict(source)
        name = _clean(_row_value(row, "물질명", "유해화학물질명", "제품명"))
        cas = _clean(_row_value(row, "CAS 번호", "CAS No.", "CAS"))
        label = name or cas or f"{index}행"

        for canonical, aliases in _FORM6_SDS_FIELDS:
            value = _row_value(row, *aliases)
            if not _present_or_na(value):
                blockers.append(
                    f"{label}: 회사 제품 SDS에서 '{canonical}' 값을 확인해 입력하거나, "
                    "SDS상 해당 없음/자료 없음이면 그 사실을 명시해 주세요."
                )

        sds_file = _clean(_row_value(row, "SDS 파일명", "MSDS 파일명", "SDS 원본 파일명"))
        sds_revision = _clean(_row_value(row, "SDS 개정일", "MSDS 개정일", "SDS 작성·개정일"))
        if not sds_file:
            blockers.append(f"{label}: 위 물성값의 근거가 된 회사 제품 SDS 파일명을 입력해 주세요.")
        if not sds_revision:
            blockers.append(f"{label}: 회사 제품 SDS의 작성일 또는 개정일을 입력해 주세요.")

        row["SDS 파일명"] = sds_file
        row["SDS 개정일"] = sds_revision
        rows.append(row)

    if rows:
        messages.append(
            "별지 제6호 물성값은 회사가 확인한 제품 SDS 전사값만 사용하며 외부/KOSHA MSDS 자동조회값으로 보완하지 않습니다."
        )

    return CAPForm6SDSData(
        rows=tuple(rows),
        blockers=tuple(dict.fromkeys(blockers)),
        messages=tuple(dict.fromkeys(messages)),
    )


def build_cap_form7_data(project: Stage2Project) -> CAPForm7Data:
    hazard_rows = _confirmed_rows(project, "cap.chemical.hazard_information")
    if not hazard_rows:
        return CAPForm7Data(
            {},
            ("별지 제7호 대표물질의 회사 SDS 유해성 정보와 선정 사유를 입력해 주세요.",),
            (),
        )

    blockers: list[str] = []
    messages: list[str] = []

    if len(hazard_rows) != 1:
        blockers.append(
            "현재 별지 제7호 DOCX baseline은 대표물질 1건을 작성하는 구조입니다. "
            "대표물질로 사용할 1개 행만 남기거나 별도 서식 확장이 필요한지 확인해 주세요."
        )

    source = dict(hazard_rows[0])
    name = _clean(_row_value(source, "물질명", "유해화학물질명", "제품명"))
    cas = _clean(_row_value(source, "CAS 번호", "CAS No.", "CAS"))
    label = name or cas or "대표물질"

    for field, aliases in (
        ("물질명 또는 CAS", ("물질명", "유해화학물질명", "제품명", "CAS 번호", "CAS No.", "CAS")),
        ("인체유해성", ("인체유해성",)),
        ("물리적 위험성", ("물리적 위험성",)),
        ("환경유해성", ("환경유해성",)),
        ("출처", ("출처", "SDS 출처")),
        ("선정 사유", ("선정 사유", "선정사유")),
        ("SDS 파일명", ("SDS 파일명", "MSDS 파일명")),
        ("SDS 개정일", ("SDS 개정일", "MSDS 개정일", "SDS 작성·개정일")),
    ):
        if not any(_present(_row_value(source, alias)) for alias in aliases):
            blockers.append(f"{label}: '{field}'이 비어 있습니다.")

    legal = build_cap_chemical_legal_data(project)
    form1 = build_cap_form1_data(project)
    legal_by_cas, legal_by_name = _index_rows(list(legal.rows))
    form1_by_cas, form1_by_name = _index_rows(list(form1.chemical_rows))

    legal_match = legal_by_cas.get(cas) if cas else None
    if legal_match is None and name:
        legal_match = legal_by_name.get(_norm(name))

    holding_match = form1_by_cas.get(cas) if cas else None
    if holding_match is None and name:
        holding_match = form1_by_name.get(_norm(name))

    if legal_match is None:
        blockers.append(f"{label}: 별지 제6호 법적 물질정보와 연결되지 않아 고유번호를 확정할 수 없습니다.")
    if holding_match is None:
        blockers.append(f"{label}: 별지 제1호 최대보유량 결과와 연결되지 않습니다.")

    row = dict(source)
    if legal_match is not None:
        row["고유번호"] = _clean(legal_match.get("고유번호"))
        if not name:
            row["물질명"] = _clean(_row_value(legal_match, "물질명"))
        if not cas:
            row["CAS 번호"] = _clean(_row_value(legal_match, "CAS 번호", "CAS No."))

    if holding_match is not None:
        row["최대보유량(ton)"] = _clean(holding_match.get("사업장 내 최대보유량(ton)"))
        row["함량(%)"] = _clean(holding_match.get("함량(%)")) or _clean(_row_value(source, "농도", "함량", "함량(%)"))

    if not _clean(row.get("고유번호")):
        blockers.append(f"{label}: 현행 법령 DB에서 별지 제7호에 재사용할 고유번호를 확정하지 못했습니다.")
    if not _clean(row.get("최대보유량(ton)")):
        blockers.append(f"{label}: 별지 제1호에서 재사용할 최대보유량(ton)을 확정하지 못했습니다.")

    messages.append(
        "별지 제7호의 고유번호·최대보유량은 회사가 재입력하지 않고 별지 제6호 법령판정과 별지 제1호 계산결과를 재사용합니다."
    )
    messages.append("인체·물리·환경 유해성과 선정 사유는 회사 SDS/확인자료만 사용합니다.")

    return CAPForm7Data(
        row=row,
        # Form 7 should fail on the selected representative substance, not on
        # an unrelated material's blocker elsewhere in the company inventory.
        blockers=tuple(dict.fromkeys(blockers)),
        messages=tuple(dict.fromkeys(messages)),
    )
