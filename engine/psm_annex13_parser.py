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

CURRENT_ITEM_COUNT = 34


def _norm(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣%]", "", _clean(value)).lower()


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


def _header_bottom(words: list[dict[str, Any]]) -> float:
    hits = [
        float(w.get("bottom", w.get("top", 0)))
        for w in words
        if any(token in _norm(w.get("text", "")) for token in ("유해위험물질", "cas", "규정량"))
    ]
    return max(hits) if hits else 0.0


def _name_header_x(words: list[dict[str, Any]], width: float) -> float:
    hits = [
        float(w.get("x0", 0))
        for w in words
        if "유해위험물질" in _norm(w.get("text", ""))
    ]
    return min(hits) if hits else width * 0.12


def _parse_quantity_text(text: str, item_no: int) -> tuple[float | None, float | None, str]:
    """Parse one Annex 13 quantity cell/segment.

    Items 1-2 have separate manufacture/handling and storage values. Items 3-34
    have one value applying to manufacture/handling/storage. Only the quantity
    segment is passed to this function so percentages in substance names do not
    contaminate the numeric parse.
    """
    raw = _clean(text)
    compact = raw.replace(",", "")
    nums = [float(v) for v in re.findall(r"\d+(?:\.\d+)?", compact)]
    if not nums:
        return None, None, raw
    if item_no in (1, 2):
        if len(nums) < 2:
            return None, None, raw
        return nums[0], nums[1], raw
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


def _semantic_row_parse(row_text: str, item_no: int) -> tuple[str, str, str]:
    text = _clean(row_text)
    text = re.sub(rf"^\s*{item_no}\s+", "", text, count=1)
    cas_list = CAS_RE.findall(text)
    cas_text = ", ".join(cas_list)

    qty_match = re.search(r"제\s*조", text)
    qty_pos = qty_match.start() if qty_match else -1
    qty_text = text[qty_pos:] if qty_pos >= 0 else ""

    if cas_list:
        first_pos = text.find(cas_list[0])
        name = text[:first_pos] if first_pos >= 0 else text
    elif qty_pos >= 0:
        name = text[:qty_pos]
    else:
        name = text

    name = re.sub(r"\s*[-–—]\s*$", "", name).strip()
    name = re.sub(r"^[-–—]\s*", "", name).strip()
    return _clean(name), cas_text, qty_text


def _coordinate_rows(
    path: Path,
    source: dict[str, Any],
    source_hash: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reconstruct rows from item-number y positions.

    This parser is retained as an independent fallback. It can fail on rows where
    the quantity text is vertically offset relative to the item number, so the
    column-stack parser below is preferred whenever it reconstructs a cleaner
    official table.
    """
    records: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            try:
                words = page.extract_words(
                    x_tolerance=1.5,
                    y_tolerance=2.5,
                    keep_blank_chars=False,
                    use_text_flow=False,
                ) or []
            except Exception:
                words = []
            if not words:
                continue

            width = float(page.width)
            header_bottom = _header_bottom(words)
            name_x = _name_header_x(words, width)

            anchors: list[tuple[int, dict[str, Any]]] = []
            for word in words:
                token = str(word.get("text", "")).strip()
                if not re.fullmatch(r"\d{1,2}", token):
                    continue
                no = int(token)
                if not 1 <= no <= CURRENT_ITEM_COUNT:
                    continue
                x0 = float(word.get("x0", 0))
                top = float(word.get("top", 0))
                if x0 >= name_x or top <= header_bottom:
                    continue
                anchors.append((no, word))

            by_no: dict[int, dict[str, Any]] = {}
            for no, word in anchors:
                old = by_no.get(no)
                if old is None or float(word.get("x0", 0)) < float(old.get("x0", 0)):
                    by_no[no] = word
            anchors = sorted(by_no.items(), key=lambda p: float(p[1].get("top", 0)))

            diagnostics.append(
                {
                    "page": page_no,
                    "number_candidates": [no for no, _ in anchors],
                    "header_bottom": round(header_bottom, 1),
                    "name_header_x": round(name_x, 1),
                }
            )
            if not anchors:
                continue

            # Use midpoint row boundaries rather than the next item's top edge.
            # This reduces cross-row leakage when quantity text is centered a few
            # points above/below the item-number glyph.
            centers = [
                (float(word.get("top", 0)) + float(word.get("bottom", word.get("top", 0)))) / 2.0
                for _, word in anchors
            ]
            bounds: list[tuple[float, float]] = []
            for idx, center in enumerate(centers):
                upper = header_bottom if idx == 0 else (centers[idx - 1] + center) / 2.0
                lower = float(page.height) - 28.0 if idx + 1 == len(centers) else (center + centers[idx + 1]) / 2.0
                bounds.append((upper, lower))

            for (no, anchor), (top, bottom) in zip(anchors, bounds):
                row_words = []
                for w in words:
                    w_center = (
                        float(w.get("top", 0))
                        + float(w.get("bottom", w.get("top", 0)))
                    ) / 2.0
                    if top <= w_center < bottom and float(w.get("x0", 0)) >= float(anchor.get("x0", 0)) - 2:
                        row_words.append(w)
                row_text = _word_text(row_words)
                name, cas_text, qty_text = _semantic_row_parse(row_text, no)
                records.append(_make_record(source, source_hash, no, name, cas_text, qty_text))

    best: dict[int, dict[str, Any]] = {}
    for record in records:
        no = int(record["item_no"])
        score = _record_score(record)
        if no not in best or score > _record_score(best[no]):
            best[no] = record
    return [best[k] for k in sorted(best)], diagnostics


def _cell_lines(value: Any) -> list[str]:
    if value is None:
        return []
    text = str(value).replace("\r", "\n")
    lines = []
    for raw in text.split("\n"):
        cleaned = _clean(raw)
        if cleaned:
            lines.append(cleaned)
    return lines


def _number_entries(text: str) -> list[int]:
    values: list[int] = []
    for line in _cell_lines(text):
        for token in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", line):
            value = int(token)
            if 1 <= value <= CURRENT_ITEM_COUNT:
                values.append(value)
    # Preserve order while removing duplicates caused by repeated headers.
    return list(dict.fromkeys(values))


def _name_entries(text: str) -> list[str]:
    lines = [line for line in _cell_lines(text) if "유해" not in _norm(line) or "위험물질" not in _norm(line)]
    out: list[str] = []
    buf = ""
    paren_balance = 0
    for line in lines:
        if not buf:
            buf = line
        else:
            buf = f"{buf} {line}".strip()
        paren_balance += line.count("(") - line.count(")")
        if paren_balance <= 0:
            out.append(_clean(buf))
            buf = ""
            paren_balance = 0
    if buf:
        out.append(_clean(buf))
    return out


def _cas_entries(text: str) -> list[str]:
    lines = [line for line in _cell_lines(text) if "cas" not in _norm(line)]
    out: list[str] = []
    buf = ""
    for line in lines:
        stripped = line.strip()
        if stripped in {"-", "–", "—"}:
            if buf:
                found = CAS_RE.findall(buf)
                if found:
                    out.append(", ".join(found))
                buf = ""
            out.append("")
            continue
        found = CAS_RE.findall(stripped)
        if not found:
            continue
        buf = f"{buf} {stripped}".strip() if buf else stripped
        if not stripped.rstrip().endswith(","):
            combined = CAS_RE.findall(buf)
            if combined:
                out.append(", ".join(combined))
            buf = ""
    if buf:
        combined = CAS_RE.findall(buf)
        if combined:
            out.append(", ".join(combined))
    return out


def _quantity_entries(text: str) -> list[str]:
    """Split a stacked quantity column by the repeated legal marker '제조'."""
    raw = str(text or "").replace("\r", "\n")
    # PDF glyph extraction can insert spaces inside '제조'. Use a lookahead so
    # each occurrence starts a new legal quantity entry and wrapped lines remain
    # attached to the same item.
    parts = re.split(r"(?=제\s*조)", raw)
    return [_clean(part) for part in parts if re.search(r"제\s*조", part)]


def _stacked_table_records(
    path: Path,
    source: dict[str, Any],
    source_hash: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse the official PDF when pdfplumber returns one tall cell per column.

    Some law.go.kr PDFs have vertical column rules but no horizontal row rules.
    pdfplumber therefore returns a table whose first data cell contains
    '1\n2\n...\n34', the second contains all substance names, and so on. This
    method intentionally parses those four independent column stacks instead of
    pretending they are normal row objects.
    """
    tables = _tables_from_pdf(path)
    candidates: list[tuple[tuple[int, int, int, int], list[dict[str, Any]], dict[str, Any]]] = []

    for table_index, item in enumerate(tables, 1):
        rows = item.get("rows", []) or []
        max_cols = max((len(row or []) for row in rows), default=0)
        if max_cols < 4:
            continue

        # Try every consecutive four-column window. This tolerates a leading
        # blank artifact column introduced by PDF table detection.
        for start_col in range(0, max_cols - 3):
            columns: list[str] = []
            for col in range(start_col, start_col + 4):
                pieces = []
                for row in rows:
                    if col < len(row or []) and row[col] is not None:
                        pieces.append(str(row[col]))
                columns.append("\n".join(pieces))

            nums = _number_entries(columns[0])
            if nums != list(range(1, CURRENT_ITEM_COUNT + 1)):
                continue

            names = _name_entries(columns[1])
            cases = _cas_entries(columns[2])
            quantities = _quantity_entries(columns[3])

            diagnostics = {
                "table_index": table_index,
                "page": item.get("page"),
                "start_col": start_col,
                "number_count": len(nums),
                "name_count": len(names),
                "cas_count": len(cases),
                "quantity_count": len(quantities),
            }

            if not (
                len(names) == CURRENT_ITEM_COUNT
                and len(cases) == CURRENT_ITEM_COUNT
                and len(quantities) == CURRENT_ITEM_COUNT
            ):
                candidates.append(((0, len(quantities), len(cases), len(names)), [], diagnostics))
                continue

            records = [
                _make_record(source, source_hash, no, names[idx], cases[idx], quantities[idx])
                for idx, no in enumerate(nums)
            ]
            complete = sum(
                1
                for r in records
                if r.get("manufacture_handling_threshold_kg") is not None
                and r.get("storage_threshold_kg") is not None
            )
            anchors = _anchor_score(records)
            score = (anchors, complete, len(records), 1)
            candidates.append((score, records, diagnostics))

    if not candidates:
        return [], []
    candidates.sort(key=lambda value: value[0], reverse=True)
    best_score, best_records, best_diag = candidates[0]
    best_diag = {**best_diag, "score": list(best_score)}
    return best_records, [best_diag]


def _record_score(record: dict[str, Any]) -> int:
    return (
        1000 * int(record.get("manufacture_handling_threshold_kg") is not None)
        + 1000 * int(record.get("storage_threshold_kg") is not None)
        + 100 * int(bool(record.get("cas_text")) or int(record.get("item_no", 0)) in (1, 2))
        + len(str(record.get("substance_name", "")))
    )


def _anchor_score(records: list[dict[str, Any]]) -> int:
    by_no = {int(r["item_no"]): r for r in records}
    score = 0
    row1 = by_no.get(1, {})
    row2 = by_no.get(2, {})
    row23 = by_no.get(23, {})
    row34 = by_no.get(34, {})
    if re.search(r"인화성\s*가스", str(row1.get("substance_name", ""))):
        score += 1
    if row1.get("manufacture_handling_threshold_kg") == 5000 and row1.get("storage_threshold_kg") == 200000:
        score += 2
    if re.search(r"인화성\s*액체", str(row2.get("substance_name", ""))):
        score += 1
    if row2.get("manufacture_handling_threshold_kg") == 5000 and row2.get("storage_threshold_kg") == 200000:
        score += 2
    if "8014-95-7" in str(row23.get("cas_text", "")) and row23.get("manufacture_handling_threshold_kg") == 20000:
        score += 2
    if "10294-34-5" in str(row34.get("cas_text", "")) and row34.get("manufacture_handling_threshold_kg") == 10000:
        score += 2
    return score


def _choose_records(
    stacked: list[dict[str, Any]],
    coordinate: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    def score(records: list[dict[str, Any]]) -> tuple[int, int, int, int]:
        if not records:
            return (0, 0, 0, 0)
        nums = sorted({int(r["item_no"]) for r in records})
        complete = sum(
            1
            for r in records
            if r.get("manufacture_handling_threshold_kg") is not None
            and r.get("storage_threshold_kg") is not None
        )
        exact_range = int(nums == list(range(1, CURRENT_ITEM_COUNT + 1)))
        return (_anchor_score(records), exact_range, complete, len(records))

    stacked_score = score(stacked)
    coordinate_score = score(coordinate)
    if stacked_score > coordinate_score:
        return stacked, "COLUMN_STACK_TABLE_PARSER", {
            "column_stack_score": list(stacked_score),
            "coordinate_score": list(coordinate_score),
        }
    return coordinate, "SEMANTIC_WORD_ROW_PARSER", {
        "column_stack_score": list(stacked_score),
        "coordinate_score": list(coordinate_score),
    }


def _validation_details(df: pd.DataFrame) -> tuple[list[str], list[int]]:
    reasons: list[str] = []
    problem_items: set[int] = set()
    numbers = df["item_no"].astype(int).tolist() if not df.empty else []

    if numbers != list(range(1, CURRENT_ITEM_COUNT + 1)):
        reasons.append("번호가 1~34 전체 연속으로 추출되지 않음")
        problem_items.update(sorted(set(range(1, CURRENT_ITEM_COUNT + 1)) - set(numbers)))

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

    return reasons, sorted(problem_items)


def _anchor_checks(df: pd.DataFrame) -> dict[str, bool]:
    if df.empty:
        return {
            "item1_name_ok": False,
            "item1_quantity_ok": False,
            "item2_name_ok": False,
            "item2_quantity_ok": False,
            "item23_cas_ok": False,
            "item23_quantity_ok": False,
            "item34_cas_ok": False,
            "item34_quantity_ok": False,
        }

    def row(no: int) -> pd.DataFrame:
        return df[df["item_no"].eq(no)]

    r1, r2, r23, r34 = row(1), row(2), row(23), row(34)
    return {
        "item1_name_ok": bool(r1["substance_name"].astype(str).str.contains("인화성\s*가스", regex=True).any()),
        "item1_quantity_ok": bool(
            (pd.to_numeric(r1["manufacture_handling_threshold_kg"], errors="coerce") == 5000).any()
            and (pd.to_numeric(r1["storage_threshold_kg"], errors="coerce") == 200000).any()
        ),
        "item2_name_ok": bool(r2["substance_name"].astype(str).str.contains("인화성\s*액체", regex=True).any()),
        "item2_quantity_ok": bool(
            (pd.to_numeric(r2["manufacture_handling_threshold_kg"], errors="coerce") == 5000).any()
            and (pd.to_numeric(r2["storage_threshold_kg"], errors="coerce") == 200000).any()
        ),
        "item23_cas_ok": bool(r23["cas_text"].astype(str).str.contains("8014-95-7", regex=False).any()),
        "item23_quantity_ok": bool(
            (pd.to_numeric(r23["manufacture_handling_threshold_kg"], errors="coerce") == 20000).any()
        ),
        "item34_cas_ok": bool(r34["cas_text"].astype(str).str.contains("10294-34-5", regex=False).any()),
        "item34_quantity_ok": bool(
            (pd.to_numeric(r34["manufacture_handling_threshold_kg"], errors="coerce") == 10000).any()
        ),
    }


def _debug_rows(df: pd.DataFrame, item_numbers: list[int]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for no in item_numbers:
        part = df[df["item_no"].eq(no)]
        if part.empty:
            out.append({"item_no": no, "missing": True})
            continue
        row = part.iloc[0]
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
    stacked_records, stacked_diag = _stacked_table_records(path, source, source_hash)
    coordinate_records, coordinate_diag = _coordinate_rows(path, source, source_hash)
    records, parser_mode, parser_scores = _choose_records(stacked_records, coordinate_records)

    df = pd.DataFrame(records, columns=PSM_COLUMNS)
    if not df.empty:
        df.drop_duplicates(subset=["item_no"], keep="first", inplace=True)
        df.sort_values("item_no", inplace=True)
        df.reset_index(drop=True, inplace=True)

    failure_reasons, problem_items = _validation_details(df)
    numbers = df["item_no"].astype(int).tolist() if not df.empty else []
    missing_name = int(df["substance_name"].astype(str).str.strip().eq("").sum()) if not df.empty else 0
    missing_quantity = int(
        (
            df["manufacture_handling_threshold_kg"].isna()
            | df["storage_threshold_kg"].isna()
        ).sum()
    ) if not df.empty else 0

    anchor_checks = _anchor_checks(df)
    for key, ok in anchor_checks.items():
        if not ok:
            failure_reasons.append(f"현재 공식본 앵커 검사 실패: {key}")
            match = re.match(r"item(\d+)_", key)
            if match:
                problem_items = sorted(set(problem_items) | {int(match.group(1))})

    validation_ok = (
        numbers == list(range(1, CURRENT_ITEM_COUNT + 1))
        and missing_name == 0
        and missing_quantity == 0
        and all(anchor_checks.values())
    )

    diagnostic_items = sorted(set(problem_items) | {1, 2, 23, 34})
    checks = {
        "parser_mode": parser_mode,
        **parser_scores,
        "rows": len(df),
        "first_item": numbers[0] if numbers else None,
        "last_item": numbers[-1] if numbers else None,
        "missing_name": missing_name,
        "missing_quantity": missing_quantity,
        "item_numbers_exactly_1_to_34": numbers == list(range(1, CURRENT_ITEM_COUNT + 1)),
        "problem_items": problem_items,
        "failure_reasons": list(dict.fromkeys(failure_reasons)),
        **anchor_checks,
        "diagnostic_rows": _debug_rows(df, diagnostic_items),
        "column_stack_diagnostics": stacked_diag,
        "word_pages": coordinate_diag,
    }

    status = "REVIEW_REQUIRED" if validation_ok else "VALIDATION_FAILED"
    if validation_ok:
        messages = [
            "34개 항목을 모두 추출했고 현재 공식본 핵심 앵커 검사를 통과했습니다. 공식 별표 13과 후보표를 최종 대조한 뒤 승인하세요."
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
