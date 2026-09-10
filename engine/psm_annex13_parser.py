from __future__ import annotations

import re
import statistics
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
    _pick_pdf,
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

# Current monitored 산업안전보건법 시행령 별표 13 has items 1-51.
# If the official PDF/version changes, the law monitor blocks use until this
# parser and its anchors are reviewed against the amended appendix.
CURRENT_ITEM_COUNT = 51


def _source_hash_for_path(source: dict[str, Any], path: Path) -> str:
    hashes = source.get("attachment_hashes", {}) or {}
    if len(hashes) == 1:
        return str(next(iter(hashes.values())))
    compact_stem = re.sub(r"\s+", "", path.stem.split("__", 1)[0])
    for key, digest in hashes.items():
        if re.sub(r"\s+", "", str(key)) in compact_stem:
            return str(digest)
    return ""


def _word_text(words: list[dict[str, Any]]) -> str:
    ordered = sorted(
        words,
        key=lambda w: (round(float(w.get("top", 0)), 1), float(w.get("x0", 0))),
    )
    return _clean(" ".join(str(w.get("text", "")) for w in ordered))


def _parse_quantity_text(text: str, item_no: int) -> tuple[float | None, float | None, str]:
    """Parse one Annex 13 quantity cell.

    Items 1-2 have separate manufacture/handling and storage thresholds.
    Items 3-51 have one threshold applying to manufacture/handling/storage.
    The caller passes only the quantity column, so CAS numbers and percentage
    values in substance names cannot contaminate the numeric parse.
    """
    raw = _clean(text)
    nums = [float(v) for v in re.findall(r"\d+(?:\.\d+)?", raw.replace(",", ""))]
    if item_no in (1, 2):
        if len(nums) < 2:
            return None, None, raw
        return nums[0], nums[1], raw
    if not nums:
        return None, None, raw
    return nums[0], nums[0], raw


def _make_record(
    source: dict[str, Any],
    source_hash: str,
    item_no: int,
    name: str,
    cas_text: str,
    qty_text: str,
) -> dict[str, Any]:
    cas_list = CAS_RE.findall(_clean(cas_text))
    mfg, storage, normalized_qty = _parse_quantity_text(qty_text, item_no)
    return {
        "item_no": item_no,
        "substance_name": _clean(name),
        "cas_text": ", ".join(cas_list),
        "cas_list": "|".join(cas_list),
        "match_type": "PROPERTY" if not cas_list else "CAS",
        "manufacture_handling_threshold_kg": mfg,
        "storage_threshold_kg": storage,
        "legal_quantity_text": normalized_qty,
        "source_key": "PSM_DECREE",
        "source_title": source.get("title", "산업안전보건법 시행령"),
        "effective_date": source.get("effective_date", ""),
        "issue_number": source.get("issue_number", ""),
        "source_pdf_sha256": source_hash,
    }


def _note_top(words: list[dict[str, Any]], page_height: float) -> float:
    """Return the start of the '비고' block so legal notes are not parsed as rows."""
    hits = [
        float(w.get("top", page_height))
        for w in words
        if str(w.get("text", "")).strip() == "비고"
    ]
    return min(hits) if hits else page_height - 20.0


def _table_quantity_markers(
    words: list[dict[str, Any]],
    note_top: float,
) -> list[dict[str, Any]]:
    """Use the repeated '제조...' text in the quantity column as row anchors.

    The official PDF has vertical column rules but no horizontal row rules.
    Item numbers can sit below the first visual line on wrapped rows (e.g. 23,
    42), whereas every legal row starts with one quantity phrase in the right
    column. This marker is therefore a more reliable row boundary than the item
    number's y coordinate.
    """
    markers = [
        w
        for w in words
        if "제조" in str(w.get("text", ""))
        and float(w.get("x0", 0)) > 300.0
        and float(w.get("top", 0)) < note_top
    ]
    return sorted(markers, key=lambda w: float(w.get("top", 0)))


def _infer_column_boundaries(
    page_payloads: list[tuple[Any, list[dict[str, Any]], float, list[dict[str, Any]]]]
) -> tuple[float, float, float]:
    """Infer stable name/CAS/quantity column boundaries from the official PDF."""
    cas_x: list[float] = []
    qty_x: list[float] = []
    number_x: list[float] = []

    for _, words, note_top, markers in page_payloads:
        qty_x.extend(float(w.get("x0", 0)) for w in markers)
        for w in words:
            top = float(w.get("top", 0))
            if top >= note_top:
                continue
            text = str(w.get("text", "")).strip()
            if CAS_RE.search(text):
                cas_x.append(float(w.get("x0", 0)))
            if re.fullmatch(r"\d{1,2}", text):
                x0 = float(w.get("x0", 0))
                if x0 < 100.0:
                    number_x.append(x0)

    # These fallbacks correspond only to coarse column regions. Current-version
    # anchors below must still pass before approval is enabled.
    name_start = (max(number_x) + 5.0) if number_x else 82.0
    cas_start = (statistics.median(cas_x) - 12.0) if cas_x else 270.0
    qty_start = (statistics.median(qty_x) - 8.0) if qty_x else 343.0
    return name_start, cas_start, qty_start


def _column_marker_rows(
    path: Path,
    source: dict[str, Any],
    source_hash: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, float]]:
    """Parse Annex 13 using quantity-column row markers and x-column separation."""
    records: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    with pdfplumber.open(path) as pdf:
        page_payloads: list[
            tuple[Any, list[dict[str, Any]], float, list[dict[str, Any]]]
        ] = []
        for page in pdf.pages:
            try:
                words = page.extract_words(
                    x_tolerance=1.5,
                    y_tolerance=2.5,
                    keep_blank_chars=False,
                    use_text_flow=False,
                ) or []
            except Exception:
                words = []
            note_top = _note_top(words, float(page.height))
            markers = _table_quantity_markers(words, note_top)
            page_payloads.append((page, words, note_top, markers))

        name_start, cas_start, qty_start = _infer_column_boundaries(page_payloads)
        expected = 1

        for page_no, (page, words, note_top, markers) in enumerate(page_payloads, 1):
            accepted_on_page: list[int] = []
            marker_rows: list[dict[str, Any]] = []

            if expected > CURRENT_ITEM_COUNT:
                diagnostics.append(
                    {
                        "page": page_no,
                        "quantity_markers_before_notes": len(markers),
                        "accepted_items": [],
                        "note_top": round(note_top, 1),
                    }
                )
                continue

            for idx, marker in enumerate(markers):
                if expected > CURRENT_ITEM_COUNT:
                    break

                top = float(marker.get("top", 0)) - 2.0
                bottom = (
                    float(markers[idx + 1].get("top", 0)) - 2.0
                    if idx + 1 < len(markers)
                    else note_top
                )
                row_words = [
                    w
                    for w in words
                    if top <= float(w.get("top", 0)) < bottom
                ]

                left_numbers = [
                    int(str(w.get("text", "")).strip())
                    for w in row_words
                    if float(w.get("x0", 0)) < name_start
                    and re.fullmatch(r"\d{1,2}", str(w.get("text", "")).strip())
                ]

                # The monitored current PDF must expose the next exact legal item
                # number inside each quantity-marker band. Do not guess if absent.
                if expected not in left_numbers:
                    marker_rows.append(
                        {
                            "expected_item": expected,
                            "found_left_numbers": left_numbers,
                            "top": round(top, 1),
                            "bottom": round(bottom, 1),
                            "accepted": False,
                        }
                    )
                    continue

                name_words = [
                    w
                    for w in row_words
                    if name_start <= float(w.get("x0", 0)) < cas_start
                ]
                cas_words = [
                    w
                    for w in row_words
                    if cas_start <= float(w.get("x0", 0)) < qty_start
                ]
                qty_words = [
                    w for w in row_words if float(w.get("x0", 0)) >= qty_start
                ]

                name = _word_text(name_words)
                cas_text = _word_text(cas_words)
                qty_text = _word_text(qty_words)
                records.append(
                    _make_record(
                        source,
                        source_hash,
                        expected,
                        name,
                        cas_text,
                        qty_text,
                    )
                )
                accepted_on_page.append(expected)
                marker_rows.append(
                    {
                        "expected_item": expected,
                        "found_left_numbers": left_numbers,
                        "top": round(top, 1),
                        "bottom": round(bottom, 1),
                        "accepted": True,
                    }
                )
                expected += 1

            diagnostics.append(
                {
                    "page": page_no,
                    "quantity_markers_before_notes": len(markers),
                    "accepted_items": accepted_on_page,
                    "note_top": round(note_top, 1),
                    "marker_rows": marker_rows,
                }
            )

    return (
        records,
        diagnostics,
        {
            "name_start_x": round(name_start, 1),
            "cas_start_x": round(cas_start, 1),
            "quantity_start_x": round(qty_start, 1),
        },
    )


def _row(df: pd.DataFrame, no: int) -> pd.Series | None:
    part = df[df["item_no"].eq(no)]
    return None if part.empty else part.iloc[0]


def _value(row: pd.Series | None, column: str) -> Any:
    return None if row is None else row.get(column)


def _quantity_is(row: pd.Series | None, mfg: float, storage: float | None = None) -> bool:
    if row is None:
        return False
    actual_mfg = pd.to_numeric(
        pd.Series([row.get("manufacture_handling_threshold_kg")]), errors="coerce"
    ).iloc[0]
    actual_storage = pd.to_numeric(
        pd.Series([row.get("storage_threshold_kg")]), errors="coerce"
    ).iloc[0]
    wanted_storage = mfg if storage is None else storage
    return bool(actual_mfg == mfg and actual_storage == wanted_storage)


def _anchor_checks(df: pd.DataFrame) -> dict[str, bool]:
    r1 = _row(df, 1)
    r2 = _row(df, 2)
    r23 = _row(df, 23)
    r25 = _row(df, 25)
    r34 = _row(df, 34)
    r35 = _row(df, 35)
    r37 = _row(df, 37)
    r42 = _row(df, 42)
    r48 = _row(df, 48)
    r51 = _row(df, 51)

    return {
        "item1_name_ok": bool(
            r1 is not None
            and re.search(r"인화성\s*가스", str(_value(r1, "substance_name") or ""))
        ),
        "item1_quantity_ok": _quantity_is(r1, 5000, 200000),
        "item2_name_ok": bool(
            r2 is not None
            and re.search(r"인화성\s*액체", str(_value(r2, "substance_name") or ""))
        ),
        "item2_quantity_ok": _quantity_is(r2, 5000, 200000),
        "item23_ok": bool(
            r23 is not None
            and "8014-95-7" in str(_value(r23, "cas_text") or "")
            and _quantity_is(r23, 20000)
        ),
        "item25_multi_cas_ok": bool(
            r25 is not None
            and str(_value(r25, "cas_list") or "").split("|")
            == ["91-08-7", "584-84-9", "26471-62-5"]
            and _quantity_is(r25, 2000)
        ),
        "item34_ok": bool(
            r34 is not None
            and "10294-34-5" in str(_value(r34, "cas_text") or "")
            and _quantity_is(r34, 10000)
        ),
        "item35_page2_ok": bool(
            r35 is not None
            and "1338-23-4" in str(_value(r35, "cas_text") or "")
            and _quantity_is(r35, 10000)
        ),
        "item37_multi_cas_ok": bool(
            r37 is not None
            and str(_value(r37, "cas_list") or "").split("|")
            == ["88-74-4", "99-09-2", "100-01-6", "29757-24-2"]
            and _quantity_is(r37, 2500)
        ),
        "item42_wrapped_name_ok": bool(
            r42 is not None
            and "12.6%" in str(_value(r42, "substance_name") or "")
            and "9004-70-0" in str(_value(r42, "cas_text") or "")
            and _quantity_is(r42, 100000)
        ),
        "item48_ok": bool(
            r48 is not None
            and "7664-39-3" in str(_value(r48, "cas_text") or "")
            and _quantity_is(r48, 10000)
        ),
        "item51_ok": bool(
            r51 is not None
            and "1336-21-6" in str(_value(r51, "cas_text") or "")
            and _quantity_is(r51, 50000)
        ),
    }


def _validation_details(df: pd.DataFrame) -> tuple[list[str], list[int]]:
    reasons: list[str] = []
    problem_items: set[int] = set()
    numbers = df["item_no"].astype(int).tolist() if not df.empty else []
    expected = list(range(1, CURRENT_ITEM_COUNT + 1))

    if numbers != expected:
        reasons.append("번호가 1~51 전체 연속으로 추출되지 않음")
        problem_items.update(sorted(set(expected) - set(numbers)))

    if not df.empty:
        bad_name = df[df["substance_name"].astype(str).str.strip().eq("")]
        if not bad_name.empty:
            reasons.append(f"물질명 누락 {len(bad_name)}행")
            problem_items.update(bad_name["item_no"].astype(int).tolist())

        bad_qty = df[
            df["manufacture_handling_threshold_kg"].isna()
            | df["storage_threshold_kg"].isna()
        ]
        if not bad_qty.empty:
            reasons.append(f"규정량 해석 실패 {len(bad_qty)}행")
            problem_items.update(bad_qty["item_no"].astype(int).tolist())

        cas_required = df[df["item_no"].astype(int).between(3, CURRENT_ITEM_COUNT)]
        bad_cas = cas_required[cas_required["cas_list"].astype(str).str.strip().eq("")]
        if not bad_cas.empty:
            reasons.append(f"CAS 누락 {len(bad_cas)}행")
            problem_items.update(bad_cas["item_no"].astype(int).tolist())

    return reasons, sorted(problem_items)


def _debug_rows(df: pd.DataFrame, item_numbers: list[int]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for no in item_numbers:
        row = _row(df, no)
        if row is None:
            out.append({"item_no": no, "missing": True})
            continue
        out.append(
            {
                "item_no": no,
                "substance_name": row.get("substance_name", ""),
                "cas_text": row.get("cas_text", ""),
                "manufacture_handling_threshold_kg": row.get("manufacture_handling_threshold_kg"),
                "storage_threshold_kg": row.get("storage_threshold_kg"),
                "legal_quantity_text": row.get("legal_quantity_text", ""),
            }
        )
    return out


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

    source_hash = _source_hash_for_path(source, path)
    records, page_diag, boundaries = _column_marker_rows(path, source, source_hash)

    df = pd.DataFrame(records, columns=PSM_COLUMNS)
    if not df.empty:
        df.drop_duplicates(subset=["item_no"], keep="first", inplace=True)
        df.sort_values("item_no", inplace=True)
        df.reset_index(drop=True, inplace=True)

    failure_reasons, problem_items = _validation_details(df)
    anchor_checks = _anchor_checks(df)
    for key, ok in anchor_checks.items():
        if not ok:
            failure_reasons.append(f"현재 공식본 앵커 검사 실패: {key}")

    numbers = df["item_no"].astype(int).tolist() if not df.empty else []
    missing_name = int(df["substance_name"].astype(str).str.strip().eq("").sum()) if not df.empty else 0
    missing_quantity = int(
        (
            df["manufacture_handling_threshold_kg"].isna()
            | df["storage_threshold_kg"].isna()
        ).sum()
    ) if not df.empty else 0
    missing_cas = int(
        df[
            df["item_no"].astype(int).between(3, CURRENT_ITEM_COUNT)
            & df["cas_list"].astype(str).str.strip().eq("")
        ].shape[0]
    ) if not df.empty else 0

    validation_ok = (
        numbers == list(range(1, CURRENT_ITEM_COUNT + 1))
        and missing_name == 0
        and missing_quantity == 0
        and missing_cas == 0
        and all(anchor_checks.values())
    )

    diagnostics_items = sorted(
        set(problem_items) | {1, 2, 23, 25, 34, 35, 37, 42, 48, 51}
    )
    checks = {
        "parser_mode": "QUANTITY_MARKER_COLUMN_PARSER",
        "rows": len(df),
        "first_item": numbers[0] if numbers else None,
        "last_item": numbers[-1] if numbers else None,
        "missing_name": missing_name,
        "missing_quantity": missing_quantity,
        "missing_cas_items_3_to_51": missing_cas,
        "item_numbers_exactly_1_to_51": numbers == list(range(1, CURRENT_ITEM_COUNT + 1)),
        "problem_items": problem_items,
        "failure_reasons": list(dict.fromkeys(failure_reasons)),
        **anchor_checks,
        "column_boundaries": boundaries,
        "diagnostic_rows": _debug_rows(df, diagnostics_items),
        "page_diagnostics": page_diag,
    }

    status = "REVIEW_REQUIRED" if validation_ok else "VALIDATION_FAILED"
    if validation_ok:
        messages = [
            "51개 항목을 모두 추출했고 현재 공식본 핵심 앵커 검사를 통과했습니다. 공식 별표 13과 후보표를 최종 대조한 뒤 승인하세요."
        ]
    else:
        reason_text = "; ".join(list(dict.fromkeys(failure_reasons))) or "원인 미확인"
        messages = [f"자동추출 품질검사를 통과하지 못했습니다. 실패 사유: {reason_text}"]

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
    _write_json(
        meta_path,
        {
            "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "result": asdict(result),
        },
    )
    return result
