from __future__ import annotations

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


CURRENT_HAZARD_GROUP_COUNT = 22
CURRENT_CATEGORY_RECORD_COUNT = 37

APP1_COLUMNS = [
    "record_key",
    "classification_system",
    "hazard_group",
    "category_no",
    "lower_quantity_ton",
    "upper_quantity_ton",
    "selection_rule",
    "source_key",
    "source_title",
    "effective_date",
    "issue_number",
    "source_pdf_sha256",
    "source_page",
    "source_text",
]


def _source_hash_for_path(source: dict[str, Any], path: Path) -> str:
    hashes = source.get("attachment_hashes", {}) or {}
    if len(hashes) == 1:
        return str(next(iter(hashes.values())))
    logical = re.sub(r"\s+", "", path.stem.split("__", 1)[0])
    for key, digest in hashes.items():
        if re.sub(r"\s+", "", str(key)) in logical:
            return str(digest)
    return ""


def _pick_appendix1_pdf() -> Path | None:
    matches: list[Path] = []
    for path in observed_pdf_paths("CAP_QTY"):
        logical = path.stem.split("__", 1)[0].replace(" ", "")
        if re.search(r"별표0*1(?:_|$)", logical):
            matches.append(path)
    return matches[0] if len(matches) == 1 else None


def _num(value: Any) -> float | None:
    text = _clean(value).replace(",", "")
    if not text or text in {"-", "–", "—"}:
        return None
    try:
        return float(text)
    except ValueError:
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(match.group()) if match else None


def _norm(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", _clean(value)).lower()


def _is_target_table(table: list[list[Any]]) -> bool:
    if not table:
        return False
    text = " ".join(_clean(cell) for row in table[:4] for cell in (row or []))
    compact = _norm(text)
    return all(token in compact for token in ("분류체계", "유해성그룹", "구분1", "하위", "상위"))


def _extract_target_tables(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    settings = [
        {},
        {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
            "snap_tolerance": 4,
            "join_tolerance": 4,
            "intersection_tolerance": 5,
        },
    ]
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            selected: list[list[Any]] | None = None
            for table_settings in settings:
                try:
                    tables = page.extract_tables(table_settings=table_settings) or []
                except Exception:
                    tables = []
                matches = [table for table in tables if _is_target_table(table)]
                if len(matches) == 1:
                    selected = matches[0]
                    break
            if selected is not None:
                out.append({"page": page_no, "rows": selected})
    return out


def _normalize_row(raw: list[Any]) -> list[str]:
    cells = [_clean(v) for v in (raw or [])]
    if len(cells) < 8:
        cells += [""] * (8 - len(cells))
    if len(cells) > 8:
        # The current legal table has exactly eight logical columns. If PDF
        # extraction splits merged cells, preserve the first two identity cells
        # and the last six category quantity cells.
        cells = [cells[0], cells[1], *cells[-6:]]
    return cells[:8]


def _parse_records(tables: list[dict[str, Any]], source: dict[str, Any], source_hash: str) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    failures: list[str] = []
    current_system = ""
    seen_groups: set[tuple[str, str]] = set()

    for page_info in tables:
        page_no = int(page_info["page"])
        for raw in page_info["rows"]:
            cells = _normalize_row(raw)
            system = _clean(cells[0])
            group = _clean(cells[1])
            if system:
                current_system = system

            # Skip the two header rows and any note rows.
            if not group or "유해성 그룹" in group or "유해성그룹" in group:
                continue
            if group in {"하위", "상위"}:
                continue
            if not any(_num(cells[idx]) is not None for idx in range(2, 8)):
                continue

            family = current_system
            if not family:
                failures.append(f"{page_no}쪽 '{group}' 행의 분류체계 병합값을 복원하지 못했습니다.")
                continue

            seen_groups.add((family, group))
            for category_no, lower_idx, upper_idx in ((1, 2, 3), (2, 4, 5), (3, 6, 7)):
                lower = _num(cells[lower_idx])
                upper = _num(cells[upper_idx])
                if lower is None and upper is None:
                    continue
                records.append(
                    {
                        "record_key": f"{len(seen_groups)}:{category_no}:{_norm(group)[:40]}",
                        "classification_system": family,
                        "hazard_group": group,
                        "category_no": category_no,
                        "lower_quantity_ton": lower,
                        "upper_quantity_ton": upper,
                        "selection_rule": "MINIMUM_APPLICABLE_QUANTITY",
                        "source_key": "CAP_QTY_APP1",
                        "source_title": source.get("title", "유해화학물질의 규정수량에 관한 규정"),
                        "effective_date": source.get("effective_date", ""),
                        "issue_number": source.get("issue_number", ""),
                        "source_pdf_sha256": source_hash,
                        "source_page": page_no,
                        "source_text": f"{family} | {group} | 구분{category_no}",
                    }
                )

    return records, failures


def _find_row(df: pd.DataFrame, group_token: str, category_no: int) -> pd.DataFrame:
    if df.empty:
        return df
    compact = df["hazard_group"].astype(str).map(_norm)
    return df[compact.str.contains(_norm(group_token), regex=False) & df["category_no"].eq(category_no)]


def _anchor_checks(df: pd.DataFrame) -> dict[str, bool]:
    anchors = {
        "acute_inhalation_cat1": ("급성독성흡입", 1, 1.0, 20.0),
        "acute_dermal_cat1": ("급성독성경피", 1, 2.0, 100.0),
        "acute_oral_cat1": ("급성독성경구", 1, 4.0, 200.0),
        "flammable_gas_cat1": ("인화성가스", 1, 2.0, 50.0),
        "flammable_liquid_cat3": ("인화성액체", 3, 20.0, 400.0),
        "aquatic_acute_cat1": ("수생독성급성", 1, 20.0, 400.0),
        "aquatic_chronic_cat1": ("수생독성만성", 1, 40.0, 500.0),
    }
    out: dict[str, bool] = {}
    for key, (token, category_no, lower, upper) in anchors.items():
        row = _find_row(df, token, category_no)
        out[key] = bool(
            not row.empty
            and float(row.iloc[0]["lower_quantity_ton"]) == lower
            and float(row.iloc[0]["upper_quantity_ton"]) == upper
        )
    return out


def build_cap_appendix1_candidate() -> CandidateResult:
    source = observed_source("CAP_QTY")
    path = _pick_appendix1_pdf()
    if not source or path is None:
        return CandidateResult(
            key="CAP_QTY_APP1",
            status="SOURCE_NOT_READY",
            row_count=0,
            source_file="",
            candidate_file="",
            messages=["CAP_QTY의 현행 별표 1 PDF를 정확히 하나 찾지 못했습니다. 법령 감시 결과를 확인하세요."],
            checks={},
        )

    tables = _extract_target_tables(path)
    source_hash = _source_hash_for_path(source, path)
    records, parse_failures = _parse_records(tables, source, source_hash)
    df = pd.DataFrame(records, columns=APP1_COLUMNS)
    if not df.empty:
        df.drop_duplicates(subset=["classification_system", "hazard_group", "category_no"], inplace=True)
        df.reset_index(drop=True, inplace=True)

    group_count = int(df[["classification_system", "hazard_group"]].drop_duplicates().shape[0]) if not df.empty else 0
    anchors = _anchor_checks(df)
    missing_lower = int(df["lower_quantity_ton"].isna().sum()) if not df.empty else 0
    failed_anchors = [key for key, ok in anchors.items() if not ok]

    failure_reasons = list(parse_failures)
    if not tables:
        failure_reasons.append("별표 1 유해·위험성 그룹 표를 자동 인식하지 못했습니다.")
    if group_count != CURRENT_HAZARD_GROUP_COUNT:
        failure_reasons.append(f"유해성 그룹 {group_count}개 != 기대값 {CURRENT_HAZARD_GROUP_COUNT}개")
    if len(df) != CURRENT_CATEGORY_RECORD_COUNT:
        failure_reasons.append(f"구분별 규정수량 행 {len(df)}개 != 기대값 {CURRENT_CATEGORY_RECORD_COUNT}개")
    if missing_lower:
        failure_reasons.append(f"하위 규정수량 누락 {missing_lower}건")
    if failed_anchors:
        failure_reasons.append("핵심 앵커 검사 실패: " + ", ".join(failed_anchors))

    checks = {
        "parser_mode": "HAZARD_GROUP_8COL_TO_CATEGORY_ROWS",
        "recognized_tables": len(tables),
        "hazard_groups": group_count,
        "category_records": len(df),
        "missing_lower_quantity": missing_lower,
        **anchors,
        "failure_reasons": failure_reasons,
    }
    status = "REVIEW_REQUIRED" if not failure_reasons else "VALIDATION_FAILED"
    messages = [
        "별표 1은 CAS 목록이 아니라 SDS 유해성·위험성 분류를 적용하는 그룹표이므로, CAS 식별 DB와 분리해 구조화했습니다.",
        "동일 물질이 여러 유해성 그룹에 해당하면 가장 작은 규정수량을 적용하도록 selection_rule을 보존했습니다.",
    ]
    if failure_reasons:
        messages.append("자동추출 품질검사를 통과하지 못했습니다. 승인하지 말고 실패항목을 확인하세요.")
    else:
        messages.append("현행 별표 1의 22개 유해성 그룹과 구분별 규정수량을 추출했습니다. 공식 PDF와 대조한 뒤 승인하세요.")

    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = CANDIDATE_DIR / "cap_qty_app1_candidate.csv"
    meta_path = CANDIDATE_DIR / "cap_qty_app1_candidate.meta.json"
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
        key="CAP_QTY_APP1",
        status=status,
        row_count=len(df),
        source_file=str(path.relative_to(PROJECT_ROOT)),
        candidate_file=str(csv_path.relative_to(PROJECT_ROOT)),
        messages=messages,
        checks=checks,
    )
