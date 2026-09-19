from __future__ import annotations

"""Authoritative-source policy and conservative KOSHA candidate mapping for CAP.

Legal structure and form names come from the current National Law Information
Center regulation/forms. Detailed authoring guidance comes from NICS-GP2026-8.
KOSHA MSDS values are review candidates only and never overwrite company facts.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .msds_reference import extract_cas_numbers, inventory_chemicals, stored_msds_reference
from .project import Stage2Project


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_LOCK_PATH = PROJECT_ROOT / "data" / "stage2" / "cap_authoritative_sources.json"

FORM6_FIELDS = (
    "물질상태",
    "비중",
    "폭발한계 하한(%)",
    "폭발한계 상한(%)",
    "독성구분-항목",
    "독성구분-구분",
    "위험노출수준",
    "허용농도값",
    "증기압(20℃, mmHg)",
    "부식성(유, 무)",
)

# The manual ties these to current legal designation/classification sources, not
# generic MSDS Section 15 text. They are intentionally outside KOSHA autofill.
NEVER_KOSHA_FORM6_FIELDS = ("물질구분", "고유번호")

FORM6_COMPANY_ALIASES: dict[str, tuple[str, ...]] = {
    "물질상태": ("물리적 상태", "물질상태"),
    "비중": ("비중",),
    "폭발한계 하한(%)": ("폭발한계 하한", "폭발하한", "폭발한계 하한(%)"),
    "폭발한계 상한(%)": ("폭발한계 상한", "폭발상한", "폭발한계 상한(%)"),
    "독성구분-항목": ("독성구분 항목", "독성구분-항목"),
    "독성구분-구분": ("독성구분", "독성구분-구분"),
    "위험노출수준": ("위험노출수준", "ERPG", "AEGL", "PAC", "IDLH"),
    "허용농도값": ("허용농도값", "TWA", "노출기준"),
    "증기압(20℃, mmHg)": ("증기압", "증기압(20℃, mmHg)", "증기압(20℃,mmHg)"),
    "부식성(유, 무)": ("부식성", "부식성(유, 무)", "부식성 유무"),
}


@dataclass(frozen=True)
class CAPReferenceCandidate:
    cas: str
    chemical_name: str
    field: str
    value: str
    section: int
    source_label: str

    @property
    def source_text(self) -> str:
        return f"KOSHA MSDS 제{self.section}항 · {self.source_label}"


def load_cap_source_lock() -> dict[str, Any]:
    payload = json.loads(SOURCE_LOCK_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "cap-authoritative-source-lock-v1":
        raise ValueError("CAP authoritative source lock schema mismatch")
    return payload


def cap_source_declaration() -> tuple[str, str]:
    source = load_cap_source_lock()
    legal = source["legal_structure"]
    manual = source["writing_guidance"]
    legal_text = (
        f"{legal['title']} [시행 {legal['effective_date']}, {legal['notice']}] · "
        "국가법령정보센터 별표·별지 서식"
    )
    manual_text = f"{manual['title']} ({manual['document_code']})"
    return legal_text, manual_text


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _norm(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣%℃]", "", _clean(value)).lower()


def _row_value(row: Mapping[str, object], *aliases: str) -> str:
    normalized = {_norm(key): value for key, value in row.items()}
    for alias in aliases:
        value = normalized.get(_norm(alias))
        if value not in (None, ""):
            return _clean(value)
    return ""


def _company_form6_values(project: Stage2Project) -> dict[str, dict[str, str]]:
    """Return company-entered Form-6 values by CAS, regardless of source alias."""
    rows: list[Mapping[str, object]] = []
    for key in ("cap.chemical.details", "inventory.chemicals"):
        record = project.get_field(key)
        if record is None or not isinstance(record.value, list):
            continue
        rows = [dict(row) for row in record.value if isinstance(row, Mapping)]
        if rows:
            break
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        cas_text = _row_value(row, "CAS 번호", "CAS No.", "CAS", "화학물질식별번호(CAS 번호)", "화학물질식별번호")
        for cas in extract_cas_numbers(cas_text):
            field_values = result.setdefault(cas, {})
            for field, aliases in FORM6_COMPANY_ALIASES.items():
                value = _row_value(row, *aliases)
                if value:
                    field_values[field] = value
    return result


def _section_items(payload: Mapping[str, Any], section: int) -> list[tuple[str, str]]:
    raw_sections = payload.get("sections")
    if not isinstance(raw_sections, Mapping):
        return []
    sec = raw_sections.get(str(section)) or raw_sections.get(section)
    if not isinstance(sec, Mapping):
        return []
    out: list[tuple[str, str]] = []
    items = sec.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                label, detail = _clean(item[0]), _clean(item[1])
                if detail:
                    out.append((label, detail))
    if not out:
        text = _clean(sec.get("text"))
        if text:
            out.append(("상세내용", text))
    return out


def _first_explicit(
    payload: Mapping[str, Any],
    sections: Iterable[int],
    aliases: Iterable[str],
) -> tuple[str, int, str] | None:
    alias_norms = tuple(_norm(alias) for alias in aliases)
    for section in sections:
        for label, detail in _section_items(payload, section):
            label_norm = _norm(label)
            if any(alias and alias in label_norm for alias in alias_norms):
                return detail, section, label or "상세내용"
            # Some KOSHA responses use a broad parent label and put individual
            # properties in the detail text. Accept only an explicit label:value
            # token, never a semantic guess from prose.
            for alias, alias_norm in zip(aliases, alias_norms):
                if not alias_norm:
                    continue
                match = re.search(
                    rf"(?:^|[|;\n\r])\s*{re.escape(alias)}\s*[:：]\s*([^|;\n\r]+)",
                    detail,
                    flags=re.I,
                )
                if match:
                    return match.group(1).strip(), section, alias
    return None


def _explicit_acronym(payload: Mapping[str, Any], acronym: str) -> tuple[str, int, str] | None:
    token = acronym.upper()
    for section in (8, 11, 2):
        for label, detail in _section_items(payload, section):
            hay = f"{label} {detail}"
            if re.search(rf"(?<![A-Za-z]){re.escape(token)}(?![A-Za-z])", hay, flags=re.I):
                return detail, section, label or token
    return None


def _toxicity_category(payload: Mapping[str, Any]) -> tuple[str, str, int, str] | None:
    """Accept only explicit acute-toxicity category statements from Section 2."""
    for label, detail in _section_items(payload, 2):
        pieces = [part.strip() for part in re.split(r"[|;\n\r]+", detail) if part.strip()]
        for text in pieces:
            if "급성" not in text or "독성" not in text:
                continue
            match = re.search(r"구분\s*([1-5])", text)
            if not match:
                continue
            item = re.sub(r"\s*[:：-]?\s*구분\s*[1-5].*$", "", text).strip()
            if not item:
                continue
            return item, f"구분 {match.group(1)}", 2, label or "유해성·위험성 분류"
    return None


def _positive_metal_corrosivity(payload: Mapping[str, Any]) -> tuple[str, int, str] | None:
    # Never infer '무' from silence. Only a positive explicit classification is
    # offered as a candidate.
    for section in (2, 10):
        for label, detail in _section_items(payload, section):
            hay = f"{label} {detail}"
            norm = _norm(hay)
            if ("금속" in norm and "부식" in norm) and not any(
                neg in norm for neg in ("해당없음", "분류되지않음", "자료없음")
            ):
                if re.search(r"구분\s*[1-9]", hay) or any(word in hay for word in ("부식성", "부식시킴", "부식 가능")):
                    return "유", section, label or "금속부식성"
    return None


def _physical_state(payload: Mapping[str, Any]) -> tuple[str, int, str] | None:
    hit = _first_explicit(payload, (9,), ("물리적 상태", "상태", "성상"))
    if not hit:
        return None
    detail, section, label = hit
    match = re.search(r"(기체|액체|고체)", detail)
    return (match.group(1), section, label) if match else None


def cap_form6_msds_candidates(project: Stage2Project) -> list[CAPReferenceCandidate]:
    """Return source-explicit missing-value candidates for official Form 6.

    Existing company values always win. KOSHA candidates remain separate review
    material and are never written into confirmed company fields here.
    """
    company_values = _company_form6_values(project)
    out: list[CAPReferenceCandidate] = []
    for chemical in inventory_chemicals(project):
        payload = stored_msds_reference(project, chemical.cas)
        if not isinstance(payload, Mapping):
            continue
        name = chemical.chemical_name or chemical.product_name or _clean(payload.get("chemical_name"))
        already = company_values.get(chemical.cas, {})

        def add(field: str, hit: tuple[str, int, str] | None) -> None:
            if field in already or not hit:
                return
            value, section, label = hit
            value = _clean(value)
            if value:
                out.append(CAPReferenceCandidate(chemical.cas, name, field, value, section, label))

        add("물질상태", _physical_state(payload))
        add("분자량", _first_explicit(payload, (9, 3), ("분자량",)))
        add("비중", _first_explicit(payload, (9,), ("비중", "상대밀도")))
        add("폭발한계 하한(%)", _first_explicit(payload, (9,), ("폭발한계 하한", "폭발하한", "인화하한", "하한 폭발")))
        add("폭발한계 상한(%)", _first_explicit(payload, (9,), ("폭발한계 상한", "폭발상한", "인화상한", "상한 폭발")))
        add("증기압(20℃, mmHg)", _first_explicit(payload, (9,), ("증기압",)))

        tox = _toxicity_category(payload)
        if tox:
            item, category, section, label = tox
            add("독성구분-항목", (item, section, label))
            add("독성구분-구분", (category, section, label))

        # NICS-GP2026-8 p.42 requires ERPG -> AEGL -> PAC -> IDLH priority.
        for acronym in ("ERPG", "AEGL", "PAC", "IDLH"):
            hit = _explicit_acronym(payload, acronym)
            if hit:
                add("위험노출수준", hit)
                break

        add("허용농도값", _first_explicit(payload, (8,), ("TWA", "시간가중평균", "노출기준")))
        add("부식성(유, 무)", _positive_metal_corrosivity(payload))

    unique: dict[tuple[str, str], CAPReferenceCandidate] = {}
    for candidate in out:
        unique.setdefault((candidate.cas, candidate.field), candidate)
    return list(unique.values())


def cap_form6_candidate_matrix(project: Stage2Project) -> list[dict[str, str]]:
    grouped: dict[str, dict[str, str]] = {}
    source_map: dict[str, list[str]] = {}
    names: dict[str, str] = {}
    for candidate in cap_form6_msds_candidates(project):
        grouped.setdefault(candidate.cas, {})[candidate.field] = candidate.value
        source_map.setdefault(candidate.cas, []).append(f"{candidate.field}: {candidate.source_text}")
        names[candidate.cas] = candidate.chemical_name
    rows: list[dict[str, str]] = []
    for cas, fields in grouped.items():
        row = {"CAS 번호": cas, "유해화학물질명": names.get(cas, "")}
        row.update(fields)
        row["출처"] = " / ".join(source_map.get(cas, []))
        row["검토상태"] = "참고값 · 제품 SDS/증빙 확인 후 회사자료에 확정 입력"
        rows.append(row)
    return rows


def cap_form7_reference_candidates(project: Stage2Project) -> list[dict[str, str]]:
    """Build review-only hazard narratives for Form 7 without selecting substances.

    The manual requires representative substance selection and a selection reason;
    this function deliberately does not invent either.
    """
    rows: list[dict[str, str]] = []
    for chemical in inventory_chemicals(project):
        payload = stored_msds_reference(project, chemical.cas)
        if not isinstance(payload, Mapping):
            continue

        def section_text(numbers: Iterable[int]) -> str:
            chunks: list[str] = []
            for number in numbers:
                for label, detail in _section_items(payload, number):
                    text = f"{label}: {detail}" if label else detail
                    if text and text not in chunks:
                        chunks.append(text)
            return " / ".join(chunks)

        human = section_text((11,))
        physical = section_text((5, 10))
        environment = section_text((12,))
        if not any((human, physical, environment)):
            continue
        rows.append({
            "유해화학물질명": chemical.chemical_name or chemical.product_name or _clean(payload.get("chemical_name")),
            "CAS 번호": chemical.cas,
            "인체유해성 후보": human,
            "물리적 위험성 후보": physical,
            "환경유해성 후보": environment,
            "출처": "KOSHA MSDS 제11항(인체), 제5·10항(물리), 제12항(환경) 참고자료",
            "선정 사유": "[확인 필요: 매뉴얼 p.43~44 기준 대표물질 선정 및 사업장 근거 작성]",
            "검토상태": "참고값 · 별지 제7호 확정자료 아님",
        })
    return rows
