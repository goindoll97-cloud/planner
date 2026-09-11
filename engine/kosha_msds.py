from __future__ import annotations

"""KOSHA MSDS reference lookup for CAP Appendix-1 screening.

The public-data API is used as an *automatic reference/prefill*, not as a
replacement for the supplier/manufacturer's legally provided product MSDS.
Only deterministic text matches to approved Appendix-1 group/category rows are
accepted.  No LLM or fuzzy semantic inference is used.

Public data source:
- 한국산업안전보건공단_물질안전보건자료 조회 서비스
- data.go.kr dataset 15157612
- REST/XML base: https://apis.data.go.kr/B552468/msdschem

Environment variables (keep only in .env / process environment):
- KOSHA_SERVICE_KEY or KOSHA_SERVICE_KEY_DECODED
- KOSHA_API_URL (optional override)
"""

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .cap_sds_app1 import SDSApp1Option, app1_sds_options


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "https://apis.data.go.kr/B552468/msdschem"
CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")


@dataclass
class KOSHAMSDSResult:
    status: str
    cas: str
    message: str
    chem_id: str = ""
    chemical_name: str = ""
    ghs_classifications: list[str] = field(default_factory=list)
    app1_option_keys: list[str] = field(default_factory=list)
    unmatched_classifications: list[str] = field(default_factory=list)
    source: str = "한국산업안전보건공단 물질안전보건자료 조회 서비스"
    source_dataset_id: str = "15157612"
    checked_at_utc: str = ""
    raw_section2_available: bool = False

    @property
    def can_prefill_app1(self) -> bool:
        return self.status == "MATCHED" and bool(self.app1_option_keys)


def _load_local_env() -> None:
    for path in (PROJECT_ROOT / ".env", Path.cwd() / ".env"):
        if not path.exists():
            continue
        try:
            for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value:
                    os.environ.setdefault(key, value)
        except OSError:
            continue


def _credential() -> str:
    _load_local_env()
    return (
        os.getenv("KOSHA_SERVICE_KEY", "").strip()
        or os.getenv("KOSHA_SERVICE_KEY_DECODED", "").strip()
    )


def credential_status() -> dict[str, str]:
    key = _credential()
    return {
        "status": "READY" if key else "MISSING",
        "message": "KOSHA OpenAPI 인증키 설정 완료" if key else ".env에 KOSHA_SERVICE_KEY를 설정하면 CAS 자동조회가 활성화됩니다.",
    }


def _base_url() -> str:
    _load_local_env()
    return os.getenv("KOSHA_API_URL", DEFAULT_BASE_URL).strip().rstrip("/") or DEFAULT_BASE_URL


def _safe_error(exc: Exception, key: str) -> str:
    text = f"{type(exc).__name__}: {exc}"
    if key:
        text = text.replace(key, "***")
    return re.sub(r"([?&](?:serviceKey|ServiceKey)=)[^&\s]+", r"\1***", text, flags=re.I)


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _norm(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", _clean(value)).lower()


def _all_item_dicts(xml_text: str) -> list[dict[str, str]]:
    if not xml_text.strip():
        return []
    root = ET.fromstring(xml_text)
    rows: list[dict[str, str]] = []
    for item in root.findall(".//item"):
        row = {_clean(child.tag): _clean(child.text) for child in list(item)}
        if row:
            rows.append(row)
    return rows


def parse_search_xml(xml_text: str, requested_cas: str) -> list[dict[str, str]]:
    """Return only rows whose XML fields contain the exact requested CAS.

    KOSHA field names have changed across API revisions, so we identify CAS and
    chemId defensively instead of relying on one undocumented tag name.
    """
    exact: list[dict[str, str]] = []
    for row in _all_item_dicts(xml_text):
        values = {_clean(v) for v in row.values()}
        if requested_cas not in values and not any(requested_cas in v for v in values):
            continue
        chem_id = ""
        for key in ("chemId", "chemID", "chem_id", "msdsId", "msdsID"):
            if row.get(key):
                chem_id = row[key]
                break
        if not chem_id:
            for key, value in row.items():
                if "chemid" in key.lower().replace("_", "") and value:
                    chem_id = value
                    break
        if not chem_id:
            continue
        name = ""
        for key in ("chemNameKor", "chemNmKor", "chemName", "chemNm", "korName"):
            if row.get(key):
                name = row[key]
                break
        exact.append({"chem_id": chem_id, "chemical_name": name, **row})
    return exact


def _split_tokens(text: str) -> list[str]:
    if not text:
        return []
    # KOSHA commonly separates Section-2 classifications with | or newlines.
    parts = re.split(r"[|\n\r]+", text)
    return [part.strip() for part in parts if part.strip() and part.strip() != "자료없음"]


def parse_section2_xml(xml_text: str) -> list[str]:
    classifications: list[str] = []
    if not xml_text.strip():
        return classifications
    root = ET.fromstring(xml_text)
    for item in root.findall(".//item"):
        name = _clean(item.findtext("msdsItemNameKor"))
        detail = _clean(item.findtext("itemDetail"))
        if "유해성·위험성 분류" in name:
            classifications.extend(_split_tokens(detail))
    # stable de-duplication
    return list(dict.fromkeys(classifications))


def _category_from_text(text: str) -> int | None:
    # Examples: '구분 1', '구분1', 'Category 2'.  Do not infer subcategories
    # 1A/1B/1C into a different APP1 row; APP1 itself uses integer categories.
    match = re.search(r"(?:구분|category)\s*[:：]?\s*([123])(?:\D|$)", text, flags=re.I)
    return int(match.group(1)) if match else None


def _group_aliases(group: str) -> set[str]:
    """Deterministic spelling aliases only; no semantic hazard inference."""
    base = _norm(group)
    aliases = {base}
    replacements = (
        ("수생독성", "수생환경유해성"),
        ("수생환경유해성", "수생독성"),
        ("급성독성", "급성독성"),
    )
    for left, right in replacements:
        if left in base:
            aliases.add(base.replace(left, right))
    return {value for value in aliases if value}


def match_app1_options(
    classifications: list[str],
    options: list[SDSApp1Option] | None = None,
) -> tuple[list[str], list[str]]:
    """Map KOSHA Section-2 text to approved APP1 rows conservatively.

    A row is accepted only if the normalized APP1 hazard-group text (or a small
    deterministic spelling alias) is contained in the normalized KOSHA text and
    the integer category is explicitly present.  Ambiguous rows remain unmatched.
    """
    option_rows = app1_sds_options() if options is None else options
    matched: list[str] = []
    unmatched: list[str] = []

    for text in classifications:
        normalized = _norm(text)
        category = _category_from_text(text)
        if category is None:
            unmatched.append(text)
            continue
        hits = []
        for option in option_rows:
            if option.category_no != category:
                continue
            if any(alias and alias in normalized for alias in _group_aliases(option.hazard_group)):
                hits.append(option.key)
        hits = list(dict.fromkeys(hits))
        if len(hits) == 1:
            matched.append(hits[0])
        else:
            unmatched.append(text)

    return list(dict.fromkeys(matched)), list(dict.fromkeys(unmatched))


def _api_ok(xml_text: str) -> bool:
    return bool(re.search(r"<resultCode>\s*0*0\s*</resultCode>", xml_text or "", flags=re.I))


def lookup_by_cas(cas: str, *, timeout: int = 15) -> KOSHAMSDSResult:
    """Search CAS -> KOSHA chemId -> MSDS Section 2 -> APP1 option keys."""
    checked = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cas = _clean(cas)
    if not CAS_RE.fullmatch(cas):
        return KOSHAMSDSResult("INVALID_CAS", cas, "CAS 번호 형식을 확인해 주세요.", checked_at_utc=checked)

    key = _credential()
    if not key:
        return KOSHAMSDSResult(
            "NOT_CONFIGURED",
            cas,
            "KOSHA OpenAPI 인증키가 설정되지 않아 자동조회하지 못했습니다. 회사/제품 SDS 확인으로 계속할 수 있습니다.",
            checked_at_utc=checked,
        )

    base = _base_url()
    try:
        search_response = requests.get(
            f"{base}/chemlist",
            params={
                "serviceKey": key,
                "searchWrd": cas,
                "searchCnd": 1,  # CAS No.
                "numOfRows": 20,
                "pageNo": 1,
            },
            timeout=timeout,
        )
        search_response.raise_for_status()
        search_xml = search_response.text or ""
        if not _api_ok(search_xml):
            return KOSHAMSDSResult("API_ERROR", cas, "KOSHA CAS 검색 API가 정상 응답을 반환하지 않았습니다.", checked_at_utc=checked)

        rows = parse_search_xml(search_xml, cas)
        ids = list(dict.fromkeys(row["chem_id"] for row in rows if row.get("chem_id")))
        if not ids:
            return KOSHAMSDSResult("NO_MATCH", cas, "KOSHA 참고자료에서 이 CAS의 정확한 검색결과를 찾지 못했습니다.", checked_at_utc=checked)
        if len(ids) > 1:
            return KOSHAMSDSResult(
                "AMBIGUOUS",
                cas,
                "같은 CAS에 여러 KOSHA 자료가 검색되어 자동으로 하나를 선택하지 않았습니다. 회사/제품 SDS를 확인해 주세요.",
                checked_at_utc=checked,
            )

        chem_id = ids[0]
        name = next((row.get("chemical_name", "") for row in rows if row.get("chem_id") == chem_id), "")
        detail_response = requests.get(
            f"{base}/getChemDetail02",
            params={"serviceKey": key, "chemId": chem_id},
            timeout=timeout,
        )
        detail_response.raise_for_status()
        detail_xml = detail_response.text or ""
        if not _api_ok(detail_xml):
            return KOSHAMSDSResult(
                "API_ERROR", cas, "KOSHA SDS 제2항 API가 정상 응답을 반환하지 않았습니다.",
                chem_id=chem_id, chemical_name=name, checked_at_utc=checked,
            )

        classifications = parse_section2_xml(detail_xml)
        if not classifications:
            return KOSHAMSDSResult(
                "NO_SECTION2",
                cas,
                "KOSHA 자료에서 SDS 제2항 유해성·위험성 분류를 확인하지 못했습니다.",
                chem_id=chem_id,
                chemical_name=name,
                checked_at_utc=checked,
                raw_section2_available=bool(detail_xml.strip()),
            )

        matched, unmatched = match_app1_options(classifications)
        if not matched:
            return KOSHAMSDSResult(
                "NO_APP1_MATCH",
                cas,
                "KOSHA 제2항 분류는 조회했지만 현재 승인된 별표 1 분류와 자동으로 정확히 연결되는 항목이 없습니다. 회사/제품 SDS로 확인해 주세요.",
                chem_id=chem_id,
                chemical_name=name,
                ghs_classifications=classifications,
                unmatched_classifications=unmatched,
                checked_at_utc=checked,
                raw_section2_available=True,
            )

        return KOSHAMSDSResult(
            "MATCHED",
            cas,
            "CAS 기준으로 KOSHA SDS 제2항 참고분류를 조회하고 별표 1 후보를 자동 연결했습니다. 최종 사용 전 회사/제품 SDS와 일치 여부를 확인하세요.",
            chem_id=chem_id,
            chemical_name=name,
            ghs_classifications=classifications,
            app1_option_keys=matched,
            unmatched_classifications=unmatched,
            checked_at_utc=checked,
            raw_section2_available=True,
        )
    except Exception as exc:
        return KOSHAMSDSResult(
            "API_ERROR",
            cas,
            "KOSHA 자동조회 중 오류가 발생했습니다: " + _safe_error(exc, key),
            checked_at_utc=checked,
        )
