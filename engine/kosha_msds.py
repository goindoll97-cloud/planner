from __future__ import annotations

"""KOSHA MSDS reference lookup.

The KOSHA/public-data service is reference material for MSDS preparation and
review. It must never be treated as a supplier/manufacturer/importer product
MSDS or as proof of company-specific composition, use, quantity or conditions.
Only a CAS number is sent to the external search endpoint.

Official public-data dataset: 한국산업안전보건공단_물질안전보건자료 조회 서비스
(data.go.kr 15157612). Current public-data operations use ``msdslist`` and
``chemdetail01`` ... ``chemdetail16`` under ``apis.data.go.kr``. Endpoint
variables remain overridable because public-data gateways can change versions.

Environment variables (never commit the actual key):
- KOSHA_MSDS_SERVICE_KEY (preferred), KOSHA_SERVICE_KEY, or KOSHA_API_KEY
- KOSHA_MSDS_BASE_URL (optional endpoint override)
- KOSHA_MSDS_SEARCH_URL (optional full search override)
- KOSHA_MSDS_SECTION2_URL (legacy Section-2 override)
- KOSHA_MSDS_SECTION_01_URL ... KOSHA_MSDS_SECTION_16_URL (optional)
"""

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote

import requests

from .cap_sds_app1 import SDSApp1Option, app1_sds_options


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "https://apis.data.go.kr/B552468/msds_api"
CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")

MSDS_SECTIONS: dict[int, str] = {
    1: "화학제품과 회사에 관한 정보",
    2: "유해성·위험성",
    3: "구성성분의 명칭 및 함유량",
    4: "응급조치요령",
    5: "폭발·화재시 대처방법",
    6: "누출사고시 대처방법",
    7: "취급 및 저장방법",
    8: "노출방지 및 개인보호구",
    9: "물리화학적 특성",
    10: "안정성 및 반응성",
    11: "독성에 관한 정보",
    12: "환경에 미치는 영향",
    13: "폐기시 주의사항",
    14: "운송에 필요한 정보",
    15: "법적규제 현황",
    16: "그 밖의 참고사항",
}


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


@dataclass(frozen=True)
class KOSHAMSDSSection:
    number: int
    title: str
    items: tuple[tuple[str, str], ...] = ()
    text: str = ""


@dataclass
class KOSHAFullMSDSResult:
    status: str
    cas: str
    message: str
    chem_id: str = ""
    chemical_name: str = ""
    sections: dict[int, KOSHAMSDSSection] = field(default_factory=dict)
    source: str = "한국산업안전보건공단 물질안전보건자료 조회 서비스"
    source_dataset_id: str = "15157612"
    checked_at_utc: str = ""

    @property
    def ready(self) -> bool:
        return self.status == "REFERENCE_READY" and bool(self.sections)

    def to_reference_dict(self) -> dict[str, Any]:
        return {
            "reference_status": self.status,
            "cas": self.cas,
            "chemical_name": self.chemical_name,
            "chem_id": self.chem_id,
            "source": self.source,
            "source_dataset_id": self.source_dataset_id,
            "checked_at_utc": self.checked_at_utc,
            "message": self.message,
            "sections": {
                str(number): {
                    "title": section.title,
                    "items": [[label, detail] for label, detail in section.items],
                    "text": section.text,
                }
                for number, section in sorted(self.sections.items())
            },
        }


def _load_local_env() -> None:
    """Minimal .env reader so the app needs no dotenv dependency.

    Windows 메모장이 붙이는 BOM, 'export KEY=값', 'KEY = 값' 형태를 견디고, 값이 비어 있는 환경변수는 .env 값으로 채운다.
    """
    for path in (PROJECT_ROOT / ".env", Path.cwd() / ".env"):
        if not path.exists():
            continue
        try:
            for raw in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].lstrip()
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value and not os.environ.get(key):
                    os.environ[key] = value
        except OSError:
            continue


def _normalize_service_key(key: str) -> str:
    """Undo data.go.kr's "Encoding" (URL-encoded) key format if present.

    ``requests`` URL-encodes query params itself, so pasting the portal's
    percent-encoded key (as opposed to its "Decoding"/raw key) makes the
    ``%`` characters get encoded a second time (``%2B`` -> ``%252B``),
    corrupting the key. The gateway then rejects the mangled key with a bare
    HTTP 403 before it ever reaches the XML business-error path. Decoding a
    key that looks percent-encoded once, up front, makes either key format
    work regardless of which one the user copied.
    """
    if re.search(r"%[0-9A-Fa-f]{2}", key):
        return unquote(key)
    return key


def _credential() -> str:
    _load_local_env()
    key = (
        os.getenv("KOSHA_MSDS_SERVICE_KEY", "").strip()
        or os.getenv("KOSHA_SERVICE_KEY", "").strip()
        or os.getenv("KOSHA_API_KEY", "").strip()
        or os.getenv("KOSHA_SERVICE_KEY_DECODED", "").strip()
    )
    return _normalize_service_key(key)


def credential_status() -> dict[str, str]:
    key = _credential()
    return {
        "status": "READY" if key else "MISSING",
        "message": (
            "KOSHA OpenAPI 인증키 설정 완료"
            if key
            else ".env에 KOSHA_MSDS_SERVICE_KEY를 설정하면 CAS 기반 MSDS 참고자료 조회가 활성화됩니다."
        ),
    }


def _base_url() -> str:
    _load_local_env()
    return (os.getenv("KOSHA_MSDS_BASE_URL") or os.getenv("KOSHA_API_URL") or DEFAULT_BASE_URL).strip().rstrip("/")


def _search_url() -> str:
    _load_local_env()
    return (os.getenv("KOSHA_MSDS_SEARCH_URL") or f"{_base_url()}/msdslist").strip()


def _section_url(section: int) -> str:
    _load_local_env()
    padded = f"{section:02d}"
    explicit = os.getenv(f"KOSHA_MSDS_SECTION_{padded}_URL", "").strip()
    if explicit:
        return explicit
    if section == 2:
        legacy = os.getenv("KOSHA_MSDS_SECTION2_URL", "").strip()
        if legacy:
            return legacy
    return f"{_base_url()}/chemdetail{padded}"


def _safe_error(exc: Exception, key: str) -> str:
    text = f"{type(exc).__name__}: {exc}"
    if key:
        text = text.replace(key, "***")
    return re.sub(r"([?&](?:serviceKey|ServiceKey)=)[^&\s]+", r"\1***", text, flags=re.I)


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _norm(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", _clean(value)).lower()


def _tag_name(tag: str) -> str:
    return str(tag or "").rsplit("}", 1)[-1]


def _all_item_dicts(xml_text: str) -> list[dict[str, str]]:
    if not xml_text.strip():
        return []
    root = ET.fromstring(xml_text)
    rows: list[dict[str, str]] = []
    for item in root.iter():
        if _tag_name(item.tag).lower() != "item":
            continue
        row = {_tag_name(child.tag): _clean(child.text) for child in list(item)}
        if row:
            rows.append(row)
    return rows


def _value(row: dict[str, str], *candidates: str) -> str:
    compact = {_norm(key): value for key, value in row.items()}
    for candidate in candidates:
        value = compact.get(_norm(candidate), "")
        if value:
            return value
    return ""


def parse_search_xml(xml_text: str, requested_cas: str) -> list[dict[str, str]]:
    """Return exact-CAS rows with a usable chemical ID."""
    exact: list[dict[str, str]] = []
    for row in _all_item_dicts(xml_text):
        record_cas = _value(row, "casNo", "cas", "cas_no")
        if record_cas.replace(" ", "") != requested_cas:
            if requested_cas not in {_clean(v).replace(" ", "") for v in row.values()}:
                continue
        chem_id = _value(row, "chemId", "chem_id", "chemicalId", "msdsId", "chemNo")
        if not chem_id:
            continue
        name = _value(row, "chemNameKor", "chemNmKor", "chemicalNameKor", "chemName", "korName")
        exact.append({"chem_id": chem_id, "chemical_name": name, **row})
    return exact


def _split_tokens(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"[|\n\r;]+", text)
    return [part.strip() for part in parts if part.strip() and part.strip() not in {"자료없음", "해당없음"}]


def parse_detail_xml(xml_text: str) -> list[tuple[str, str]]:
    """Preserve the KOSHA item label/detail pairs without semantic invention."""
    pairs: list[tuple[str, str]] = []
    for row in _all_item_dicts(xml_text):
        label = _value(
            row,
            "msdsItemNameKor", "itemNameKor", "itemNmKor", "itemName", "itemNm", "title", "name",
        )
        detail = _value(row, "itemDetail", "detail", "item_detail", "contents", "content", "value")
        if not detail:
            # Last-resort preservation for schema revisions: keep non-ID leaf text.
            candidates = [
                value for key, value in row.items()
                if value and not re.search(r"(?:id|no|seq|num)$", key, flags=re.I)
            ]
            detail = " | ".join(dict.fromkeys(candidates))
        if detail:
            pairs.append((label, detail))
    return pairs


def parse_section2_xml(xml_text: str) -> list[str]:
    classifications: list[str] = []
    for _label, detail in parse_detail_xml(xml_text):
        classifications.extend(_split_tokens(detail))
    return list(dict.fromkeys(classifications))


def _category_from_text(text: str) -> int | None:
    match = re.search(r"(?:구분|category|cat\.?)[\s:：-]*([123])(?:\D|$)", text, flags=re.I)
    return int(match.group(1)) if match else None


def _group_aliases(group: str) -> set[str]:
    base = _norm(group)
    aliases = {base}
    for left, right in (("수생독성", "수생환경유해성"), ("수생환경유해성", "수생독성")):
        if left in base:
            aliases.add(base.replace(left, right))
    return {value for value in aliases if value}


def match_app1_options(
    classifications: list[str],
    options: list[SDSApp1Option] | None = None,
) -> tuple[list[str], list[str]]:
    """Conservatively map KOSHA Section-2 text to approved APP1 rows."""
    option_rows = app1_sds_options() if options is None else options
    matched: list[str] = []
    unmatched: list[str] = []
    for text in classifications:
        normalized = _norm(text)
        category = _category_from_text(text)
        if category is None:
            continue
        hits: list[str] = []
        for option in option_rows:
            if option.category_no != category:
                continue
            if any(alias in normalized for alias in _group_aliases(option.hazard_group)):
                hits.append(option.key)
        hits = list(dict.fromkeys(hits))
        if len(hits) == 1:
            matched.append(hits[0])
        else:
            unmatched.append(text)
    return list(dict.fromkeys(matched)), list(dict.fromkeys(unmatched))


def _api_error_text(xml_text: str) -> str:
    try:
        root = ET.fromstring(xml_text or "")
    except ET.ParseError:
        return ""
    code = ""
    message = ""
    for node in root.iter():
        tag = _tag_name(node.tag).lower()
        if tag in {"resultcode", "returnreasoncode", "errorcode"}:
            code = _clean(node.text)
        elif tag in {"resultmsg", "errmsg", "message", "returnauthmsg", "errormessage"}:
            message = _clean(node.text)
    if code and code not in {"0", "00", "0000"} and not code.upper().startswith("NORMAL"):
        return f"API resultCode={code}" + (f" ({message})" if message else "")
    return ""


_REQUEST_HEADERS = {
    # data.go.kr's gateway WAF blocks the default python-requests User-Agent
    # as a bot with a bare HTTP 403 (no XML body), independent of whether the
    # service key itself is valid and approved.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}


def _request_xml(url: str, params: dict[str, Any], *, timeout: int, key: str) -> str:
    response = requests.get(url, params=params, timeout=timeout, headers=_REQUEST_HEADERS)
    text = response.text or ""
    # data.go.kr returns its XML business error (e.g. "등록되지 않은 서비스키")
    # alongside a non-200 HTTP status for key/quota problems. Read the body
    # before raise_for_status() would discard it, so the real reason reaches
    # the user instead of a bare "403 Forbidden".
    api_error = _api_error_text(text)
    if api_error:
        raise RuntimeError(api_error)
    response.raise_for_status()
    return text


def _search_exact_cas(cas: str, *, timeout: int, key: str) -> tuple[str, str, str]:
    search_xml = _request_xml(
        _search_url(),
        {"serviceKey": key, "searchWrd": cas, "searchCnd": 1, "numOfRows": 20, "pageNo": 1},
        timeout=timeout,
        key=key,
    )
    rows = parse_search_xml(search_xml, cas)
    ids = list(dict.fromkeys(row["chem_id"] for row in rows if row.get("chem_id")))
    if not ids:
        return "NO_MATCH", "", ""
    if len(ids) > 1:
        return "AMBIGUOUS", "", ""
    chem_id = ids[0]
    name = next((row.get("chemical_name", "") for row in rows if row.get("chem_id") == chem_id), "")
    return "MATCH", chem_id, name


def _validate_cas(cas: str) -> str:
    cas = _clean(cas).replace(" ", "")
    return cas if CAS_RE.fullmatch(cas) else ""


def lookup_by_cas(cas: str, *, timeout: int = 15) -> KOSHAMSDSResult:
    """CAS -> KOSHA Section 2 -> conservative CAP Appendix-1 candidates."""
    checked = datetime.now(timezone.utc).isoformat(timespec="seconds")
    normalized = _validate_cas(cas)
    if not normalized:
        return KOSHAMSDSResult("INVALID_CAS", _clean(cas), "CAS 번호 형식을 확인해 주세요.", checked_at_utc=checked)
    key = _credential()
    if not key:
        return KOSHAMSDSResult(
            "NOT_CONFIGURED", normalized,
            "KOSHA OpenAPI 인증키가 설정되지 않아 자동조회하지 못했습니다. 회사/제품 SDS 확인으로 계속할 수 있습니다.",
            checked_at_utc=checked,
        )
    try:
        search_status, chem_id, name = _search_exact_cas(normalized, timeout=timeout, key=key)
        if search_status == "NO_MATCH":
            return KOSHAMSDSResult("NO_MATCH", normalized, "KOSHA 참고자료에서 이 CAS의 정확한 검색결과를 찾지 못했습니다.", checked_at_utc=checked)
        if search_status == "AMBIGUOUS":
            return KOSHAMSDSResult("AMBIGUOUS", normalized, "같은 CAS에 여러 KOSHA 자료가 검색되어 자동으로 하나를 선택하지 않았습니다. 회사/제품 SDS를 확인해 주세요.", checked_at_utc=checked)

        detail_xml = _request_xml(
            _section_url(2),
            {"serviceKey": key, "chemId": chem_id, "chemNo": chem_id},
            timeout=timeout,
            key=key,
        )
        classifications = parse_section2_xml(detail_xml)
        if not classifications:
            return KOSHAMSDSResult(
                "NO_SECTION2", normalized, "KOSHA 자료에서 SDS 제2항 상세내용을 확인하지 못했습니다.",
                chem_id=chem_id, chemical_name=name, checked_at_utc=checked,
                raw_section2_available=bool(detail_xml.strip()),
            )
        matched, unmatched = match_app1_options(classifications)
        if not matched:
            return KOSHAMSDSResult(
                "NO_APP1_MATCH", normalized,
                "KOSHA 제2항 자료는 조회했지만 현재 승인된 별표 1 분류와 보수적으로 자동 연결되는 항목이 없습니다. 회사/제품 SDS로 확인해 주세요.",
                chem_id=chem_id, chemical_name=name, ghs_classifications=classifications,
                unmatched_classifications=unmatched, checked_at_utc=checked, raw_section2_available=True,
            )
        return KOSHAMSDSResult(
            "MATCHED", normalized,
            "CAS 기준 KOSHA SDS 제2항 참고분류를 조회하고 별표 1 후보를 자동 연결했습니다. 최종 적용 전 회사/제품 SDS와 일치 여부를 확인하세요.",
            chem_id=chem_id, chemical_name=name, ghs_classifications=classifications,
            app1_option_keys=matched, unmatched_classifications=unmatched,
            checked_at_utc=checked, raw_section2_available=True,
        )
    except Exception as exc:
        return KOSHAMSDSResult(
            "API_ERROR", normalized,
            "KOSHA 자동조회 중 오류가 발생했습니다: " + _safe_error(exc, key),
            checked_at_utc=checked,
        )


def lookup_full_msds_by_cas(
    cas: str,
    *,
    sections: Iterable[int] | None = None,
    timeout: int = 20,
) -> KOSHAFullMSDSResult:
    """Retrieve KOSHA reference MSDS sections for one exact CAS.

    This function sends only the CAS number and the KOSHA chemical identifier
    returned for that CAS. It never transmits company identity, quantity,
    process, equipment, product name or other Stage-2 facts.
    """
    checked = datetime.now(timezone.utc).isoformat(timespec="seconds")
    normalized = _validate_cas(cas)
    if not normalized:
        return KOSHAFullMSDSResult("INVALID_CAS", _clean(cas), "CAS 번호 형식을 확인해 주세요.", checked_at_utc=checked)
    key = _credential()
    if not key:
        return KOSHAFullMSDSResult(
            "NOT_CONFIGURED", normalized,
            "KOSHA OpenAPI 인증키가 설정되지 않았습니다. 회사/제품 SDS로 계속 작성할 수 있습니다.",
            checked_at_utc=checked,
        )

    requested = list(dict.fromkeys(int(value) for value in (sections or range(1, 17))))
    invalid = [value for value in requested if value not in MSDS_SECTIONS]
    if invalid:
        return KOSHAFullMSDSResult("INVALID_SECTION", normalized, f"MSDS 항목 번호는 1~16이어야 합니다: {invalid}", checked_at_utc=checked)

    try:
        search_status, chem_id, name = _search_exact_cas(normalized, timeout=timeout, key=key)
        if search_status == "NO_MATCH":
            return KOSHAFullMSDSResult("NO_MATCH", normalized, "KOSHA 참고자료에서 이 CAS의 정확한 검색결과를 찾지 못했습니다.", checked_at_utc=checked)
        if search_status == "AMBIGUOUS":
            return KOSHAFullMSDSResult("AMBIGUOUS", normalized, "같은 CAS에 여러 KOSHA 자료가 검색되어 자동 선택하지 않았습니다. 공급자 SDS를 우선 확인하세요.", checked_at_utc=checked)

        result_sections: dict[int, KOSHAMSDSSection] = {}
        failures: list[str] = []
        for number in requested:
            try:
                xml_text = _request_xml(
                    _section_url(number),
                    {"serviceKey": key, "chemId": chem_id, "chemNo": chem_id},
                    timeout=timeout,
                    key=key,
                )
                items = parse_detail_xml(xml_text)
                text = "\n".join(
                    f"{label}: {detail}" if label else detail
                    for label, detail in items
                    if detail
                ).strip()
                result_sections[number] = KOSHAMSDSSection(
                    number=number,
                    title=MSDS_SECTIONS[number],
                    items=tuple(items),
                    text=text,
                )
            except Exception as exc:
                failures.append(f"{number}항: {_safe_error(exc, key)}")

        if not result_sections:
            return KOSHAFullMSDSResult(
                "API_ERROR", normalized, "KOSHA MSDS 상세항목을 조회하지 못했습니다." + (" / " + " / ".join(failures[:3]) if failures else ""),
                chem_id=chem_id, chemical_name=name, checked_at_utc=checked,
            )

        status = "REFERENCE_READY" if len(result_sections) == len(requested) else "PARTIAL_REFERENCE"
        message = (
            "KOSHA MSDS 16개 항목 참고자료를 조회했습니다. 법정 제품 MSDS가 아니므로 공급자·제조자·수입자 MSDS와 회사 제품정보를 최종 확인하세요."
            if status == "REFERENCE_READY"
            else f"KOSHA MSDS 참고자료를 일부 조회했습니다({len(result_sections)}/{len(requested)}개 항목). 공급자 SDS를 우선 확인하세요."
        )
        if failures:
            message += " 조회 실패: " + " / ".join(failures[:3])
        return KOSHAFullMSDSResult(
            status, normalized, message,
            chem_id=chem_id, chemical_name=name, sections=result_sections,
            checked_at_utc=checked,
        )
    except Exception as exc:
        return KOSHAFullMSDSResult(
            "API_ERROR", normalized,
            "KOSHA MSDS 자동조회 중 오류가 발생했습니다: " + _safe_error(exc, key),
            checked_at_utc=checked,
        )
