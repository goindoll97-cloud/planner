from __future__ import annotations

"""Conservative parser for CAP quantity Appendix 4 maximum-holding rules.

Appendix 4 is not a CAS table. It is a narrative calculation rule set for
manufacturing/use, storage tanks, storage areas, gas-phase materials and
mixtures. This parser preserves the official text as reviewable rule rows and
validates the current legal anchors before approval. It intentionally does not
turn the narrative rules into automatic calculations yet; that is activated
only after the reviewed Appendix 4 DB is approved and the required facility
inputs are implemented.
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pdfplumber

from .regulatory_tables import (
    CANDIDATE_DIR,
    PROJECT_ROOT,
    CandidateResult,
    _clean,
    _write_json,
    observed_pdf_paths,
    observed_source,
)


APP4_COLUMNS = [
    "rule_id",
    "section",
    "subclause",
    "facility_type",
    "rule_type",
    "automation_status",
    "rule_text",
    "source_key",
    "source_title",
    "effective_date",
    "issue_number",
    "source_pdf_sha256",
]

EXPECTED_CORE_RULE_IDS = ["1", "2-가", "2-나", "3-가", "3-나", "3-다", "비고"]


def _source_hash_for_path(source: dict[str, Any], path: Path) -> str:
    hashes = source.get("attachment_hashes", {}) or {}
    if len(hashes) == 1:
        return str(next(iter(hashes.values())))
    logical = re.sub(r"\s+", "", path.stem.split("__", 1)[0])
    for key, digest in hashes.items():
        if re.sub(r"\s+", "", str(key)) in logical:
            return str(digest)
    return ""


def _pick_appendix4_pdf() -> Path | None:
    matches: list[Path] = []
    for path in observed_pdf_paths("CAP_QTY"):
        logical = path.stem.split("__", 1)[0].replace(" ", "")
        if re.search(r"별표0*4(?:_|$)", logical):
            matches.append(path)
    return matches[0] if len(matches) == 1 else None


def _pdf_text(path: Path) -> tuple[str, int]:
    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            try:
                text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            except Exception:
                text = ""
            pages.append(text)
    joined = "\n".join(pages)
    joined = joined.replace("\u00a0", " ").replace("ㆍ", "·")
    joined = re.sub(r"[ \t]+", " ", joined)
    joined = re.sub(r"\s*\n\s*", " ", joined)
    return joined.strip(), len(pages)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _find_span(text: str, start_pattern: str, end_pattern: str | None = None) -> str:
    start = re.search(start_pattern, text, flags=re.I)
    if not start:
        return ""
    end = re.search(end_pattern, text[start.end():], flags=re.I) if end_pattern else None
    stop = start.end() + end.start() if end else len(text)
    return text[start.start():stop].strip()


def _section_after(text: str, section_pattern: str, next_section_pattern: str | None) -> str:
    return _find_span(text, section_pattern, next_section_pattern)


def _clause_marker(marker: str) -> str:
    """Match a legal subclause marker, not an ordinary Korean sentence ending.

    PDF text is flattened to one line. A naive pattern such as ``다\.`` also
    matches the last syllable of ``산정한다.`` and can truncate the preceding
    subclause. Requiring a non-word/Korean boundary before the marker keeps
    actual ``가./나./다.`` clause markers distinct from sentence endings.
    """
    return rf"(?<![0-9A-Za-z가-힣]){re.escape(marker)}\.\s*"


def _parse_core_rules(text: str) -> list[dict[str, str]]:
    """Split the current Appendix 4 into stable legal review rows.

    The raw legal sentence is retained. The parser uses only section/subclause
    markers and never rewrites the legal formula into a guessed numerical rule.
    """
    normalized = re.sub(r"\s+", " ", text).strip()
    sec1 = _section_after(normalized, r"1\.\s*유해화학물질별\s*최대보유량", r"2\.\s*제조[·ㆍ]?사용시설")
    sec2 = _section_after(normalized, r"2\.\s*제조[·ㆍ]?사용시설", r"3\.\s*저장[·ㆍ]?보관시설")
    sec3 = _section_after(normalized, r"3\.\s*저장[·ㆍ]?보관시설", r"(?:※\s*)?비\s*고")
    note = _find_span(normalized, r"(?:※\s*)?비\s*고")

    def sub(section: str, marker: str, next_marker: str | None) -> str:
        if not section:
            return ""
        return _find_span(
            section,
            _clause_marker(marker),
            _clause_marker(next_marker) if next_marker else None,
        )

    rows = [
        {"rule_id": "1", "section": "1", "subclause": "", "facility_type": "전체", "rule_type": "TOTAL_MAX_HOLDING", "rule_text": sec1},
        {"rule_id": "2-가", "section": "2", "subclause": "가", "facility_type": "제조·사용시설", "rule_type": "DESIGN_CAPACITY_AND_DENSITY", "rule_text": sub(sec2, "가", "나")},
        {"rule_id": "2-나", "section": "2", "subclause": "나", "facility_type": "제조·사용시설", "rule_type": "MULTIPHASE_VOLUME", "rule_text": sub(sec2, "나", None)},
        {"rule_id": "3-가", "section": "3", "subclause": "가", "facility_type": "저장탱크", "rule_type": "STORAGE_TANK_DESIGN_CAPACITY", "rule_text": sub(sec3, "가", "나")},
        {"rule_id": "3-나", "section": "3", "subclause": "나", "facility_type": "보관시설", "rule_type": "STORAGE_PLAN_AND_DAILY_MAX", "rule_text": sub(sec3, "나", "다")},
        {"rule_id": "3-다", "section": "3", "subclause": "다", "facility_type": "보관시설", "rule_type": "STORAGE_ONLY_LOWEST_EXCEPTION", "rule_text": sub(sec3, "다", None)},
        {"rule_id": "비고", "section": "비고", "subclause": "", "facility_type": "특수조건", "rule_type": "NOTES", "rule_text": note},
    ]
    return rows


def _anchor_checks(full_text: str, rows: list[dict[str, str]]) -> dict[str, bool]:
    compact = _compact(full_text)
    by_id = {row["rule_id"]: _compact(row.get("rule_text", "")) for row in rows}
    return {
        "title_maximum_holding": "최대보유량산정방법" in compact,
        "all_facilities_sum": all(token in compact for token in ("모든제조", "저장", "어느순간최대로체류")),
        "excluded_transport_and_stopped_facilities": (
            "탱크로리" in compact and "취급중단" in compact and ("사외배관" in compact or "사업외관" in compact)
        ),
        "manufacture_use_design_capacity_density": all(token in by_id.get("2-가", "") for token in ("설계용량", "비중")),
        "simple_mix_final_concentration": all(token in by_id.get("2-가", "") for token in ("단순혼합", "최종함량")),
        "reaction_before_reaction_concentration": all(token in by_id.get("2-가", "") for token in ("반응", "일어나기전", "최종함량")),
        "multiphase_evidence_rule": all(token in by_id.get("2-나", "") for token in ("성상", "증빙", "부피")),
        "storage_tank_design_capacity_density": all(token in by_id.get("3-가", "") for token in ("저장탱크", "설계용량", "비중")),
        "storage_plan_daily_max": (
            ("보관계획도" in by_id.get("3-나", "") or "보관구획도" in by_id.get("3-나", ""))
            and "일일최대보관량" in by_id.get("3-나", "")
        ),
        "storage_only_lowest_rule": all(token in by_id.get("3-다", "") for token in ("보관시설만", "최하위규정수량")),
        "gas_note_present": "기상물질" in by_id.get("비고", "") or "고압가스" in by_id.get("비고", ""),
        "mixture_note_present": "혼합물" in by_id.get("비고", ""),
    }


def build_cap_appendix4_candidate() -> CandidateResult:
    source = observed_source("CAP_QTY")
    path = _pick_appendix4_pdf()
    if not source or path is None:
        return CandidateResult(
            key="CAP_QTY_APP4",
            status="SOURCE_NOT_READY",
            row_count=0,
            source_file="",
            candidate_file="",
            messages=["CAP_QTY의 현행 별표 4 PDF를 정확히 하나 찾지 못했습니다. 법령 감시 결과를 확인하세요."],
            checks={},
        )

    full_text, page_count = _pdf_text(path)
    source_hash = _source_hash_for_path(source, path)
    core_rows = _parse_core_rules(full_text)
    anchors = _anchor_checks(full_text, core_rows)

    failure_reasons: list[str] = []
    if not full_text:
        failure_reasons.append("별표 4 PDF 본문 텍스트 추출 실패")
    missing_rules = [row["rule_id"] for row in core_rows if not row.get("rule_text")]
    if missing_rules:
        failure_reasons.append("핵심 조항 분리 실패: " + ", ".join(missing_rules))
    failed_anchors = [key for key, ok in anchors.items() if not ok]
    if failed_anchors:
        failure_reasons.append("핵심 앵커 검사 실패: " + ", ".join(failed_anchors))

    records: list[dict[str, Any]] = []
    for row in core_rows:
        records.append(
            {
                **row,
                "automation_status": "REFERENCE_ONLY_UNTIL_INPUT_MODEL_APPROVED",
                "source_key": "CAP_QTY_APP4",
                "source_title": source.get("title", "유해화학물질의 규정수량에 관한 규정"),
                "effective_date": source.get("effective_date", ""),
                "issue_number": source.get("issue_number", ""),
                "source_pdf_sha256": source_hash,
            }
        )

    df = pd.DataFrame(records, columns=APP4_COLUMNS)
    checks = {
        "parser_mode": "NARRATIVE_MAX_HOLDING_RULES",
        "pages": page_count,
        "core_rule_rows": len(df),
        "expected_rule_ids": EXPECTED_CORE_RULE_IDS,
        "actual_rule_ids": df["rule_id"].astype(str).tolist() if not df.empty else [],
        "rule_ids_complete": df["rule_id"].astype(str).tolist() == EXPECTED_CORE_RULE_IDS if not df.empty else False,
        **anchors,
        "failure_reasons": failure_reasons,
    }
    status = "REVIEW_REQUIRED" if not failure_reasons else "VALIDATION_FAILED"
    messages = [
        "별표 4는 물질목록이 아니라 시설유형별 최대보유량 산정 규칙이므로, 원문 조항을 계산규칙 후보로 분리해 보존했습니다.",
        "이번 단계에서는 원문 규칙을 승인 DB로 구조화만 하며, 설계용량·비중·혼합/반응·보관계획도 등 필요한 시설정보가 준비되기 전에는 자동 산정에 사용하지 않습니다.",
    ]
    if failure_reasons:
        messages.append("자동추출 품질검사를 통과하지 못했습니다. 승인하지 말고 실패항목을 확인하세요.")
    else:
        messages.append("현행 별표 4의 핵심 최대보유량 산정 조항을 확인했습니다. 공식 PDF와 대조한 뒤 승인하세요.")

    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = CANDIDATE_DIR / "cap_qty_app4_candidate.csv"
    meta_path = CANDIDATE_DIR / "cap_qty_app4_candidate.meta.json"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    _write_json(
        meta_path,
        {
            "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": status,
            "checks": checks,
            "source_file": str(path.relative_to(PROJECT_ROOT)),
            "source_pdf_sha256": source_hash,
        },
    )

    return CandidateResult(
        key="CAP_QTY_APP4",
        status=status,
        row_count=len(df),
        source_file=str(path.relative_to(PROJECT_ROOT)),
        candidate_file=str(csv_path.relative_to(PROJECT_ROOT)),
        messages=messages,
        checks=checks,
    )
