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
    """Parse Annex 13 quantity wording after the '제조' label.

    Rows 1-2 contain two values (manufacture/handling and storage). Rows 3-34
    contain one value applying to manufacture/handling/storage.  Percentage
    numbers in substance names are excluded because the caller passes only the
    quantity segment beginning at '제조'.
    """
    raw = _clean(text)
    compact = raw.replace(",", "")
    nums = [float(v) for v in re.findall(r"\d+(?:\.\d+)?", compact)]
    if not nums:
        return None, None, raw
    if item_no in (1, 2) and len(nums) >= 2:
        return nums[0], nums[1], raw
    return nums[0], nums[0], raw


def _semantic_row_parse(row_text: str, item_no: int) -> tuple[str, str, str, float | None, float | None]:
    """Parse one visually grouped Annex 13 row from its text.

    This deliberately uses legal-text markers (CAS pattern and the '제조' label)
    rather than assuming that the PDF header's x-position equals the left edge of
    the data column.  That assumption caused 34 row anchors to be found while
    quantity/name fields were still shifted between columns.
    """
    text = _clean(row_text)
    text = re.sub(rf"^\s*{item_no}\s+", "", text, count=1)

    cas_list = CAS_RE.findall(text)
    cas_text = ", ".join(cas_list)

    qty_match = re.search(r"제\s*조", text)
    qty_pos = qty_match.start() if qty_match else -1
    qty_text = text[qty_pos:] if qty_pos >= 0 else ""
    mfg, storage, qty_text = _parse_quantity_text(qty_text, item_no)

    if cas_list:
        first_cas = cas_list[0]
        first_pos = text.find(first_cas)
        name = text[:first_pos] if first_pos >= 0 else text
    elif qty_pos >= 0:
        name = text[:qty_pos]
    else:
        name = text

    name = re.sub(r"\s*[-–—]\s*$", "", name).strip()
    name = re.sub(r"^[-–—]\s*", "", name).strip()
    return _clean(name), cas_text, qty_text, mfg, storage


def _coordinate_rows(path: Path, source: dict[str, Any], source_hash: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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
                if not 1 <= no <= 34:
                    continue
                x0 = float(word.get("x0", 0))
                top = float(word.get("top", 0))
                if x0 >= name_x or top <= header_bottom:
                    continue
                anchors.append((no, word))

            # One legal item number per page position. Prefer the left-most token
            # if pdfplumber emitted duplicate word objects.
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

            for idx, (no, anchor) in enumerate(anchors):
                top = float(anchor.get("top", 0)) - 1.5
                if idx + 1 < len(anchors):
                    bottom = float(anchors[idx + 1][1].get("top", 0)) - 1.5
                else:
                    bottom = float(page.height) - 28.0

                row_words = [
                    w
                    for w in words
                    if top <= float(w.get("top", 0)) < bottom
                    and float(w.get("x0", 0)) >= float(anchor.get("x0", 0)) - 2
                ]
                row_text = _word_text(row_words)
                name, cas_text, qty_text, mfg, storage = _semantic_row_parse(row_text, no)
                cas_list = CAS_RE.findall(cas_text)

                records.append(
                    {
                        "item_no": no,
                        "substance_name": name,
                        "cas_text": cas_text,
                        "cas_list": "|".join(cas_list),
                        "match_type": "PROPERTY" if not cas_list else "CAS",
                        "manufacture_handling_threshold_kg": mfg,
                        "storage_threshold_kg": storage,
                        "legal_quantity_text": qty_text,
                        "source_key": "PSM_DECREE",
                        "source_title": source.get("title", "산업안전보건법 시행령"),
                        "effective_date": source.get("effective_date", ""),
                        "issue_number": source.get("issue_number", ""),
                        "source_pdf_sha256": source_hash,
                    }
                )

    # De-duplicate across pages. A later/longer reconstruction wins only when it
    # contains more useful legal text.
    best: dict[int, dict[str, Any]] = {}
    for record in records:
        no = int(record["item_no"])
        score = (
            1000 * int(record.get("manufacture_handling_threshold_kg") is not None)
            + 1000 * int(record.get("storage_threshold_kg") is not None)
            + len(str(record.get("substance_name", "")))
            + len(str(record.get("cas_text", "")))
        )
        old = best.get(no)
        old_score = -1
        if old is not None:
            old_score = (
                1000 * int(old.get("manufacture_handling_threshold_kg") is not None)
                + 1000 * int(old.get("storage_threshold_kg") is not None)
                + len(str(old.get("substance_name", "")))
                + len(str(old.get("cas_text", "")))
            )
        if score > old_score:
            best[no] = record

    return [best[k] for k in sorted(best)], diagnostics


def _validation_details(df: pd.DataFrame) -> tuple[list[str], list[int]]:
    reasons: list[str] = []
    problem_items: set[int] = set()
    numbers = df["item_no"].astype(int).tolist() if not df.empty else []

    if numbers != list(range(1, 35)):
        reasons.append("번호가 1~34 전체 연속으로 추출되지 않음")
        missing = sorted(set(range(1, 35)) - set(numbers))
        problem_items.update(missing)

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

        row1 = df[df["item_no"].eq(1)]
        if row1.empty or not row1["substance_name"].astype(str).str.contains("인화성\s*가스", regex=True).any():
            reasons.append("1번 물질명이 '인화성 가스'로 확인되지 않음")
            problem_items.add(1)
        row2 = df[df["item_no"].eq(2)]
        if row2.empty or not row2["substance_name"].astype(str).str.contains("인화성\s*액체", regex=True).any():
            reasons.append("2번 물질명이 '인화성 액체'로 확인되지 않음")
            problem_items.add(2)

        row34 = df[df["item_no"].eq(34)]
        if row34.empty or not row34["cas_text"].astype(str).str.contains("10294-34-5", regex=False).any():
            reasons.append("34번 CAS(10294-34-5) 앵커 확인 실패")
            problem_items.add(34)

    return reasons, sorted(problem_items)


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
    records, page_diag = _coordinate_rows(path, source, source_hash)
    df = pd.DataFrame(records, columns=PSM_COLUMNS)
    if not df.empty:
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

    # Strong current-version anchors. The law monitor blocks changed PDF/version
    # before this parser is used; any future amendment therefore fails closed
    # until these anchors and the parser are reviewed.
    anchor_checks: dict[str, bool] = {
        "item1_name_ok": bool(
            not df.empty
            and df.loc[df["item_no"].eq(1), "substance_name"].astype(str).str.contains("인화성\s*가스", regex=True).any()
        ),
        "item1_quantity_ok": bool(
            not df.empty
            and (pd.to_numeric(df.loc[df["item_no"].eq(1), "manufacture_handling_threshold_kg"], errors="coerce") == 5000).any()
            and (pd.to_numeric(df.loc[df["item_no"].eq(1), "storage_threshold_kg"], errors="coerce") == 200000).any()
        ),
        "item2_name_ok": bool(
            not df.empty
            and df.loc[df["item_no"].eq(2), "substance_name"].astype(str).str.contains("인화성\s*액체", regex=True).any()
        ),
        "item34_cas_ok": bool(
            not df.empty
            and df.loc[df["item_no"].eq(34), "cas_text"].astype(str).str.contains("10294-34-5", regex=False).any()
        ),
        "item34_quantity_ok": bool(
            not df.empty
            and (pd.to_numeric(df.loc[df["item_no"].eq(34), "manufacture_handling_threshold_kg"], errors="coerce") == 10000).any()
        ),
    }

    for key, ok in anchor_checks.items():
        if not ok:
            failure_reasons.append(f"현재 공식본 앵커 검사 실패: {key}")

    validation_ok = (
        numbers == list(range(1, 35))
        and missing_name == 0
        and missing_quantity == 0
        and all(anchor_checks.values())
    )

    checks = {
        "parser_mode": "SEMANTIC_WORD_ROW_PARSER",
        "rows": len(df),
        "first_item": numbers[0] if numbers else None,
        "last_item": numbers[-1] if numbers else None,
        "missing_name": missing_name,
        "missing_quantity": missing_quantity,
        "item_numbers_exactly_1_to_34": numbers == list(range(1, 35)),
        "problem_items": problem_items,
        "failure_reasons": list(dict.fromkeys(failure_reasons)),
        **anchor_checks,
        "word_pages": page_diag,
    }

    status = "REVIEW_REQUIRED" if validation_ok else "VALIDATION_FAILED"
    if validation_ok:
        messages = [
            "34개 항목을 모두 추출했고 핵심 앵커 검사를 통과했습니다. 공식 별표 13과 후보표를 최종 대조한 뒤 승인하세요."
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
