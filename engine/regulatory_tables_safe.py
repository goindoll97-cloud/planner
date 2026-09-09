from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .regulatory_tables import (
    CANDIDATE_DIR,
    PROJECT_ROOT,
    CAS_RE,
    CandidateResult,
    _clean,
    _float,
    _int_no,
    _merge_continuation_rows,
    _norm_header,
    _parse_psm_quantity,
    _pick_pdf,
    _tables_from_pdf,
    _write_json,
    observed_source,
)


PSM_COLUMNS = [
    "item_no",
    "substance_name",
    "cas_text",
    "cas_list",
    "match_type",
    "manufacture_handling_threshold_kg",
    "storage_threshold_kg",
    "legal_quantity_text",
    "source_key",
    "source_title",
    "effective_date",
    "issue_number",
    "source_pdf_sha256",
]

CAP3_COLUMNS = [
    "item_no",
    "substance_name",
    "cas_text",
    "cas_list",
    "content_threshold_pct",
    "lowest_quantity_ton",
    "lower_quantity_ton",
    "upper_quantity_ton",
    "source_key",
    "source_title",
    "effective_date",
    "issue_number",
]


def _numeric_row_count(rows: list[list[Any]]) -> int:
    return sum(1 for row in rows if row and _int_no(row[0]) is not None)


def _candidate_tables(
    tables: list[dict[str, Any]],
    required_header_tokens: Iterable[str],
    min_cols: int,
) -> list[dict[str, Any]]:
    """Return all page tables belonging to the same legal list.

    Legal appendices usually repeat the header on each page, but some PDF
    generators omit it after page one. We therefore first locate a definite
    header match and then include other table fragments that have the same
    minimum column count and at least two numbered legal rows.
    """
    tokens = [_norm_header(v) for v in required_header_tokens]
    definite: list[dict[str, Any]] = []
    for item in tables:
        rows = item.get("rows", [])
        header_text = " ".join(_norm_header(cell) for row in rows[:5] for cell in row)
        if all(token and token in header_text for token in tokens):
            definite.append(item)
    if not definite:
        return []

    min_page = min(int(item.get("page", 0) or 0) for item in definite)
    selected: list[dict[str, Any]] = []
    for item in tables:
        rows = item.get("rows", [])
        if int(item.get("page", 0) or 0) < min_page or not rows:
            continue
        max_cols = max((len(row or []) for row in rows), default=0)
        if max_cols < min_cols:
            continue
        header_text = " ".join(_norm_header(cell) for row in rows[:5] for cell in row)
        header_match = all(token and token in header_text for token in tokens)
        if header_match or _numeric_row_count(rows) >= 2:
            selected.append(item)
    return selected


def _collect_legal_rows(items: list[dict[str, Any]], min_cols: int) -> list[list[str]]:
    all_rows: list[list[str]] = []
    for item in items:
        all_rows.extend(_merge_continuation_rows(item["rows"], min_cols))
    # The same row can be repeated at page boundaries; item number is the legal key.
    dedup: dict[int, list[str]] = {}
    for row in all_rows:
        no = _int_no(row[0]) if row else None
        if no is None:
            continue
        existing = dedup.get(no)
        if existing is None or sum(len(v) for v in row) > sum(len(v) for v in existing):
            dedup[no] = row
    return [dedup[key] for key in sorted(dedup)]


def build_psm_annex13_candidate() -> CandidateResult:
    source = observed_source("PSM_DECREE")
    path = _pick_pdf("PSM_DECREE", ["별표13"])
    if path is None:
        path = _pick_pdf("PSM_DECREE", ["13"])
    if not source or not path:
        return CandidateResult(
            key="PSM_ANNEX13",
            status="SOURCE_NOT_READY",
            row_count=0,
            source_file="",
            candidate_file="",
            messages=["PSM_DECREE의 현행 별표 13 PDF를 찾지 못했습니다. 법령 감시를 먼저 실행하세요."],
            checks={},
        )

    tables = _tables_from_pdf(path)
    items = _candidate_tables(tables, ["유해위험물질", "cas", "규정량"], 4)
    if not items:
        return CandidateResult(
            key="PSM_ANNEX13",
            status="TABLE_NOT_RECOGNIZED",
            row_count=0,
            source_file=str(path.relative_to(PROJECT_ROOT)),
            candidate_file="",
            messages=["별표 13에서 유해·위험물질/CAS/규정량 표를 자동 인식하지 못했습니다."],
            checks={"tables_found": len(tables)},
        )

    legal_rows = _collect_legal_rows(items, 4)
    records: list[dict[str, Any]] = []
    for cells in legal_rows:
        no = _int_no(cells[0])
        if no is None:
            continue
        name = _clean(cells[1]) if len(cells) > 1 else ""
        cas_text = _clean(cells[2]) if len(cells) > 2 else ""
        qty_text = _clean(" ".join(cells[3:])) if len(cells) > 3 else ""
        mfg_qty, storage_qty = _parse_psm_quantity(qty_text)
        cas_list = CAS_RE.findall(cas_text)
        records.append(
            {
                "item_no": no,
                "substance_name": name,
                "cas_text": cas_text,
                "cas_list": "|".join(cas_list),
                "match_type": "PROPERTY" if not cas_list else "CAS",
                "manufacture_handling_threshold_kg": mfg_qty,
                "storage_threshold_kg": storage_qty,
                "legal_quantity_text": qty_text,
                "source_key": "PSM_DECREE",
                "source_title": source.get("title", "산업안전보건법 시행령"),
                "effective_date": source.get("effective_date", ""),
                "issue_number": source.get("issue_number", ""),
                "source_pdf_sha256": next(iter((source.get("attachment_hashes") or {}).values()), ""),
            }
        )

    # Keep the schema even when zero rows are extracted.  pandas writes a
    # header-only CSV instead of a 0-byte file, so the Streamlit preview can
    # safely read VALIDATION_FAILED results without raising EmptyDataError.
    df = pd.DataFrame(records, columns=PSM_COLUMNS)
    if not df.empty:
        df.drop_duplicates(subset=["item_no"], keep="first", inplace=True)
        df.sort_values("item_no", inplace=True)
        df.reset_index(drop=True, inplace=True)

    numbers = df["item_no"].astype(int).tolist() if not df.empty else []
    consecutive = bool(numbers) and numbers[0] == 1 and numbers == list(range(1, max(numbers) + 1))
    missing_name = int(df["substance_name"].eq("").sum()) if not df.empty else 0
    missing_qty = int(
        (df["manufacture_handling_threshold_kg"].isna() | df["storage_threshold_kg"].isna()).sum()
    ) if not df.empty else 0
    property_rows = int(df["match_type"].eq("PROPERTY").sum()) if not df.empty else 0
    item1_ok = bool(
        not df.empty
        and (df["item_no"] == 1).any()
        and df.loc[df["item_no"] == 1, "substance_name"].astype(str).str.contains("인화성").any()
    )
    item2_ok = bool(
        not df.empty
        and (df["item_no"] == 2).any()
        and df.loc[df["item_no"] == 2, "substance_name"].astype(str).str.contains("인화성").any()
    )
    checks = {
        "pdf_tables_found": len(tables),
        "table_fragments_used": len(items),
        "pages_used": sorted({int(item["page"]) for item in items}),
        "rows": len(df),
        "first_item": numbers[0] if numbers else None,
        "last_item": numbers[-1] if numbers else None,
        "missing_name": missing_name,
        "missing_quantity": missing_qty,
        "item_numbers_consecutive_from_1": consecutive,
        "property_rows": property_rows,
        "items_1_and_2_look_like_flammability_rows": item1_ok and item2_ok,
    }

    validation_ok = (
        len(df) >= 10
        and consecutive
        and not missing_name
        and not missing_qty
        and item1_ok
        and item2_ok
    )
    status = "REVIEW_REQUIRED" if validation_ok else "VALIDATION_FAILED"
    messages = [
        "자동추출 후보를 만들었습니다. 공식 별표 13과 첫 행·마지막 행·행수·규정량을 확인한 뒤에만 승인하세요."
        if validation_ok
        else "자동추출 품질검사를 통과하지 못했습니다. 승인하지 말고 추출 페이지/행수를 확인하세요."
    ]

    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = CANDIDATE_DIR / "psm_annex13_candidate.csv"
    meta_path = CANDIDATE_DIR / "psm_annex13_candidate.meta.json"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    result = CandidateResult(
        key="PSM_ANNEX13",
        status=status,
        row_count=len(df),
        source_file=str(path.relative_to(PROJECT_ROOT)),
        candidate_file=str(csv_path.relative_to(PROJECT_ROOT)),
        messages=messages,
        checks=checks,
    )
    _write_json(meta_path, {"created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "result": asdict(result)})
    return result


def build_cap_accident_quantity_candidate() -> CandidateResult:
    source = observed_source("CAP_QTY")
    path = _pick_pdf("CAP_QTY", ["별표3"])
    if path is None:
        path = _pick_pdf("CAP_QTY", ["3"])
    if not source or not path:
        return CandidateResult(
            key="CAP_QTY_APP3",
            status="SOURCE_NOT_READY",
            row_count=0,
            source_file="",
            candidate_file="",
            messages=["CAP_QTY 별표 3 현행 PDF를 찾지 못했습니다. 법령 감시를 먼저 실행하세요."],
            checks={},
        )

    tables = _tables_from_pdf(path)
    items = _candidate_tables(tables, ["사고대비물질", "cas", "하위규정수량", "상위규정수량"], 7)
    if not items:
        return CandidateResult(
            key="CAP_QTY_APP3",
            status="TABLE_NOT_RECOGNIZED",
            row_count=0,
            source_file=str(path.relative_to(PROJECT_ROOT)),
            candidate_file="",
            messages=["별표 3 사고대비물질 규정수량 표를 자동 인식하지 못했습니다."],
            checks={"tables_found": len(tables)},
        )

    legal_rows = _collect_legal_rows(items, 7)
    records: list[dict[str, Any]] = []
    for cells in legal_rows:
        no = _int_no(cells[0])
        if no is None or len(cells) < 7:
            continue
        cas_list = CAS_RE.findall(cells[2])
        records.append(
            {
                "item_no": no,
                "substance_name": _clean(cells[1]),
                "cas_text": _clean(cells[2]),
                "cas_list": "|".join(cas_list),
                "content_threshold_pct": _float(cells[3]),
                "lowest_quantity_ton": _float(cells[4]),
                "lower_quantity_ton": _float(cells[5]),
                "upper_quantity_ton": _float(cells[6]),
                "source_key": "CAP_QTY",
                "source_title": source.get("title", "유해화학물질의 규정수량에 관한 규정"),
                "effective_date": source.get("effective_date", ""),
                "issue_number": source.get("issue_number", ""),
            }
        )

    # Same fail-closed behavior as the PSM extractor: an unsuccessful parse
    # remains readable as an empty, header-only candidate rather than crashing
    # the administration page.
    df = pd.DataFrame(records, columns=CAP3_COLUMNS)
    if not df.empty:
        df.drop_duplicates(subset=["item_no"], keep="first", inplace=True)
        df.sort_values("item_no", inplace=True)
        df.reset_index(drop=True, inplace=True)

    numbers = df["item_no"].astype(int).tolist() if not df.empty else []
    consecutive = bool(numbers) and numbers[0] == 1 and numbers == list(range(1, max(numbers) + 1))
    missing = 0
    if not df.empty:
        required = ["content_threshold_pct", "lowest_quantity_ton", "lower_quantity_ton", "upper_quantity_ton"]
        missing = int(df[required].isna().any(axis=1).sum()) + int(df["substance_name"].eq("").sum())
    checks = {
        "pdf_tables_found": len(tables),
        "table_fragments_used": len(items),
        "pages_used": sorted({int(item["page"]) for item in items}),
        "rows": len(df),
        "first_item": numbers[0] if numbers else None,
        "last_item": numbers[-1] if numbers else None,
        "rows_with_missing_required_value": missing,
        "item_numbers_consecutive_from_1": consecutive,
    }
    validation_ok = len(df) >= 10 and consecutive and missing == 0
    status = "REVIEW_REQUIRED" if validation_ok else "VALIDATION_FAILED"
    messages = [
        "사고대비물질 규정수량 후보를 만들었습니다. 공식 별표 3과 첫 행·마지막 행·행수·함량/수량을 대조한 뒤 승인하세요."
        if validation_ok
        else "자동추출 품질검사를 통과하지 못했습니다. 승인하지 말고 추출 페이지/열 구조를 확인하세요."
    ]

    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = CANDIDATE_DIR / "cap_qty_app3_candidate.csv"
    meta_path = CANDIDATE_DIR / "cap_qty_app3_candidate.meta.json"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    result = CandidateResult(
        key="CAP_QTY_APP3",
        status=status,
        row_count=len(df),
        source_file=str(path.relative_to(PROJECT_ROOT)),
        candidate_file=str(csv_path.relative_to(PROJECT_ROOT)),
        messages=messages,
        checks=checks,
    )
    _write_json(meta_path, {"created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "result": asdict(result)})
    return result
