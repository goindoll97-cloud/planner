from __future__ import annotations

import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pdfplumber

from .regulatory_tables import (
    CANDIDATE_DIR,
    PROJECT_ROOT,
    CAS_RE,
    CandidateResult,
    _clean,
    _float,
    _write_json,
    observed_pdf_paths,
    observed_source,
)


CAP3_COLUMNS = [
    "record_key",
    "item_no",
    "variant_type",
    "condition_note",
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
    "source_pdf_sha256",
]

CURRENT_ITEM_COUNT = 100


def _source_hash_for_path(source: dict[str, Any], path: Path) -> str:
    hashes = source.get("attachment_hashes", {}) or {}
    if len(hashes) == 1:
        return str(next(iter(hashes.values())))
    compact_stem = re.sub(r"\s+", "", path.stem.split("__", 1)[0])
    for key, digest in hashes.items():
        if re.sub(r"\s+", "", str(key)) in compact_stem:
            return str(digest)
    return ""


def _pick_appendix3_pdf() -> Path | None:
    """Select exactly CAP_QTY 별표 3, never a hash/name substring match.

    Older code called _pick_pdf(..., ["3"]), so a hexadecimal hash containing
    the character 3 could make 별표 2 win.  Match only the legal appendix marker
    in the filename before the __<hash> suffix.
    """
    candidates: list[Path] = []
    for path in observed_pdf_paths("CAP_QTY"):
        logical_name = path.stem.split("__", 1)[0].replace(" ", "")
        if re.search(r"별표0*3(?:_|$)", logical_name):
            candidates.append(path)
    return candidates[0] if len(candidates) == 1 else None


def _cell(value: Any) -> str:
    return _clean(value).replace("*", "").strip()


def _num(value: Any) -> float | None:
    return _float(_cell(value))


def _extract_tables(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            try:
                tables = page.extract_tables() or []
            except Exception:
                tables = []
            for table_no, table in enumerate(tables, 1):
                if not table:
                    continue
                max_cols = max((len(row or []) for row in table), default=0)
                header = " ".join(_clean(v) for v in (table[0] if table else []))
                if max_cols >= 7 and "사고대비물질" in header and "CAS" in header and "상위" in header:
                    out.append({"page": page_no, "table": table_no, "rows": table})
    return out


def _main_record(
    cells: list[Any], source: dict[str, Any], source_hash: str
) -> dict[str, Any] | None:
    if len(cells) < 7:
        return None
    no_text = _clean(cells[0])
    if not re.fullmatch(r"\d{1,3}", no_text):
        return None
    no = int(no_text)
    if not 1 <= no <= CURRENT_ITEM_COUNT:
        return None
    cas_text = _clean(cells[2])
    cas_list = CAS_RE.findall(cas_text)
    return {
        "record_key": str(no),
        "item_no": no,
        "variant_type": "BASE",
        "condition_note": "",
        "substance_name": _clean(cells[1]),
        "cas_text": cas_text,
        "cas_list": "|".join(cas_list),
        "content_threshold_pct": _num(cells[3]),
        "lowest_quantity_ton": _num(cells[4]),
        "lower_quantity_ton": _num(cells[5]),
        "upper_quantity_ton": _num(cells[6]),
        "source_key": "CAP_QTY",
        "source_title": source.get("title", "유해화학물질의 규정수량에 관한 규정"),
        "effective_date": source.get("effective_date", ""),
        "issue_number": source.get("issue_number", ""),
        "source_pdf_sha256": source_hash,
    }


def _variant_record(
    parent: dict[str, Any], cells: list[Any], source: dict[str, Any], source_hash: str
) -> dict[str, Any] | None:
    no = int(parent["item_no"])
    name_text = _clean(cells[1] if len(cells) > 1 else "")
    condition_text = _clean(cells[3] if len(cells) > 3 else "")

    if no in (42, 43, 44) and "용액" in name_text:
        variant_type = "LIQUID_AT_AMBIENT"
        condition_note = "상온·상압에서 성상이 액체인 경우 별표 3 일반기준 1.가.의 * 표시 규정수량 적용"
        content_threshold = parent.get("content_threshold_pct")
        variant_name = name_text
    elif no == 46 and "70" in condition_text and "초과" in condition_text:
        variant_type = "CONCENTRATION_GT_70"
        condition_note = "질산 농도 70% 초과"
        content_threshold = parent.get("content_threshold_pct")
        variant_name = parent.get("substance_name", "")
    else:
        return None

    return {
        "record_key": f"{no}:{variant_type}",
        "item_no": no,
        "variant_type": variant_type,
        "condition_note": condition_note,
        "substance_name": variant_name,
        "cas_text": parent.get("cas_text", ""),
        "cas_list": parent.get("cas_list", ""),
        "content_threshold_pct": content_threshold,
        "lowest_quantity_ton": _num(cells[4] if len(cells) > 4 else None),
        "lower_quantity_ton": _num(cells[5] if len(cells) > 5 else None),
        "upper_quantity_ton": _num(cells[6] if len(cells) > 6 else None),
        "source_key": "CAP_QTY",
        "source_title": source.get("title", "유해화학물질의 규정수량에 관한 규정"),
        "effective_date": source.get("effective_date", ""),
        "issue_number": source.get("issue_number", ""),
        "source_pdf_sha256": source_hash,
    }


def _build_records(
    tables: list[dict[str, Any]], source: dict[str, Any], source_hash: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    current_parent: dict[str, Any] | None = None

    for item in sorted(tables, key=lambda x: (int(x["page"]), int(x["table"]))):
        page_main = 0
        page_variants = 0
        for row_index, raw in enumerate(item["rows"]):
            cells = list(raw or []) + [None] * max(0, 7 - len(raw or []))
            main = _main_record(cells, source, source_hash)
            if main is not None:
                records.append(main)
                current_parent = main
                page_main += 1
                continue
            if row_index == 0 or current_parent is None:
                continue
            variant = _variant_record(current_parent, cells, source, source_hash)
            if variant is not None:
                records.append(variant)
                page_variants += 1
        diagnostics.append(
            {
                "page": item["page"],
                "table": item["table"],
                "main_rows": page_main,
                "variant_rows": page_variants,
            }
        )
    return records, diagnostics


def _eq_num(df: pd.DataFrame, key: str, column: str, expected: float) -> bool:
    part = df[df["record_key"].astype(str).eq(key)]
    if part.empty:
        return False
    values = pd.to_numeric(part[column], errors="coerce")
    return bool((values - expected).abs().lt(1e-12).any())


def _anchor_checks(df: pd.DataFrame) -> dict[str, bool]:
    def cas_ok(key: str, cas: str) -> bool:
        part = df[df["record_key"].astype(str).eq(key)]
        return bool(not part.empty and part["cas_list"].astype(str).str.contains(cas, regex=False).any())

    return {
        "item1_cas_ok": cas_ok("1", "50-00-0"),
        "item1_quantities_ok": _eq_num(df, "1", "lowest_quantity_ton", 0.05)
        and _eq_num(df, "1", "lower_quantity_ton", 2)
        and _eq_num(df, "1", "upper_quantity_ton", 400),
        "item42_base_ok": cas_ok("42", "7647-01-0")
        and _eq_num(df, "42", "lowest_quantity_ton", 0.02)
        and _eq_num(df, "42", "lower_quantity_ton", 0.8)
        and _eq_num(df, "42", "upper_quantity_ton", 4),
        "item42_liquid_variant_ok": _eq_num(df, "42:LIQUID_AT_AMBIENT", "lowest_quantity_ton", 0.2)
        and _eq_num(df, "42:LIQUID_AT_AMBIENT", "lower_quantity_ton", 8)
        and _eq_num(df, "42:LIQUID_AT_AMBIENT", "upper_quantity_ton", 40),
        "item43_liquid_variant_ok": _eq_num(df, "43:LIQUID_AT_AMBIENT", "lowest_quantity_ton", 0.1)
        and _eq_num(df, "43:LIQUID_AT_AMBIENT", "lower_quantity_ton", 4)
        and _eq_num(df, "43:LIQUID_AT_AMBIENT", "upper_quantity_ton", 20),
        "item44_liquid_variant_ok": _eq_num(df, "44:LIQUID_AT_AMBIENT", "lowest_quantity_ton", 0.5)
        and _eq_num(df, "44:LIQUID_AT_AMBIENT", "lower_quantity_ton", 20)
        and _eq_num(df, "44:LIQUID_AT_AMBIENT", "upper_quantity_ton", 400),
        "item46_gt70_variant_ok": _eq_num(df, "46:CONCENTRATION_GT_70", "lowest_quantity_ton", 0.025)
        and _eq_num(df, "46:CONCENTRATION_GT_70", "lower_quantity_ton", 1)
        and _eq_num(df, "46:CONCENTRATION_GT_70", "upper_quantity_ton", 20),
        "item98_has_four_cas": bool(
            not df[df["record_key"].astype(str).eq("98")].empty
            and df.loc[df["record_key"].astype(str).eq("98"), "cas_list"].astype(str).str.count(r"\|").add(1).eq(4).any()
        ),
        "item100_cas_ok": cas_ok("100", "106-99-0"),
        "item100_quantities_ok": _eq_num(df, "100", "lowest_quantity_ton", 0.05)
        and _eq_num(df, "100", "lower_quantity_ton", 2)
        and _eq_num(df, "100", "upper_quantity_ton", 50),
    }


def build_cap_accident_quantity_candidate() -> CandidateResult:
    source = observed_source("CAP_QTY")
    path = _pick_appendix3_pdf()
    if not source or path is None:
        return CandidateResult(
            key="CAP_QTY_APP3",
            status="SOURCE_NOT_READY",
            row_count=0,
            source_file="",
            candidate_file="",
            messages=["CAP_QTY의 현행 별표 3 PDF를 정확히 하나 찾지 못했습니다. 법령 감시 결과의 별표 3 파일을 확인하세요."],
            checks={},
        )

    tables = _extract_tables(path)
    if not tables:
        return CandidateResult(
            key="CAP_QTY_APP3",
            status="TABLE_NOT_RECOGNIZED",
            row_count=0,
            source_file=str(path.relative_to(PROJECT_ROOT)),
            candidate_file="",
            messages=["별표 3의 7열 사고대비물질 규정수량 표를 자동 인식하지 못했습니다."],
            checks={"recognized_tables": 0},
        )

    source_hash = _source_hash_for_path(source, path)
    records, page_diag = _build_records(tables, source, source_hash)
    df = pd.DataFrame(records, columns=CAP3_COLUMNS)
    if not df.empty:
        df.drop_duplicates(subset=["record_key"], keep="first", inplace=True)
        df.sort_values(["item_no", "variant_type"], inplace=True)
        df.reset_index(drop=True, inplace=True)

    base = df[df["variant_type"].eq("BASE")].copy() if not df.empty else pd.DataFrame(columns=df.columns)
    base_numbers = base["item_no"].astype(int).tolist() if not base.empty else []
    required_num_cols = [
        "content_threshold_pct",
        "lowest_quantity_ton",
        "lower_quantity_ton",
        "upper_quantity_ton",
    ]
    missing_required = 0
    if not base.empty:
        missing_required = int(base[required_num_cols].isna().any(axis=1).sum())
        missing_required += int(base["substance_name"].astype(str).str.strip().eq("").sum())

    variant_keys = set(df.loc[df["variant_type"].ne("BASE"), "record_key"].astype(str)) if not df.empty else set()
    expected_variants = {
        "42:LIQUID_AT_AMBIENT",
        "43:LIQUID_AT_AMBIENT",
        "44:LIQUID_AT_AMBIENT",
        "46:CONCENTRATION_GT_70",
    }
    anchors = _anchor_checks(df)
    failure_reasons: list[str] = []
    if base_numbers != list(range(1, CURRENT_ITEM_COUNT + 1)):
        failure_reasons.append("기본 물질 번호 1~100 전체 연속 추출 실패")
    if missing_required:
        failure_reasons.append(f"기본 행 필수값 누락 {missing_required}건")
    if not expected_variants.issubset(variant_keys):
        failure_reasons.append("42·43·44 액체형 또는 46번 70% 초과 특수 규정량 행 누락")
    failed_anchors = [key for key, ok in anchors.items() if not ok]
    if failed_anchors:
        failure_reasons.append("핵심 앵커 검사 실패: " + ", ".join(failed_anchors))

    checks = {
        "parser_mode": "MULTIPAGE_TABLE_WITH_SPECIAL_VARIANTS",
        "recognized_tables": len(tables),
        "base_rows": len(base),
        "variant_rows": len(df) - len(base),
        "total_records": len(df),
        "first_item": base_numbers[0] if base_numbers else None,
        "last_item": base_numbers[-1] if base_numbers else None,
        "item_numbers_exactly_1_to_100": base_numbers == list(range(1, CURRENT_ITEM_COUNT + 1)),
        "base_rows_with_missing_required_value": missing_required,
        "special_variant_keys": sorted(variant_keys),
        "failure_reasons": failure_reasons,
        **anchors,
        "page_diagnostics": page_diag,
    }

    validation_ok = not failure_reasons
    status = "REVIEW_REQUIRED" if validation_ok else "VALIDATION_FAILED"
    messages = [
        "사고대비물질 1~100번과 특수 규정량 4개 행을 모두 추출했고 핵심 앵커 검사를 통과했습니다. 공식 별표 3과 후보표를 최종 대조한 뒤 승인하세요."
        if validation_ok
        else "자동추출 품질검사를 통과하지 못했습니다. " + "; ".join(failure_reasons)
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
    _write_json(
        meta_path,
        {
            "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "result": asdict(result),
        },
    )
    return result
