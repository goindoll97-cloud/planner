from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pdfplumber

from .no_cas_scope import classify_scope_type
from .regulatory_tables import (
    CANDIDATE_DIR,
    PROJECT_ROOT,
    CandidateResult,
    _clean,
    _write_json,
    observed_pdf_paths,
    observed_source,
)


CAS_RE = re.compile(r"\b\d{2,7}-\d{2}-\d\b")
# 기대값은 사람이 공식 PDF와 대조해 확인한 현재 판의 값이다. 개정으로 물질이 늘거나 줄면 이 검사가 실패해
# 자동 승인이 멈춘다(의도된 안전장치). 값을 바꿀 때는 새 PDF와 후보표를 대조한 뒤 갱신한다.
# 2026-12-19 시행본(발령번호 2026-20): 58쪽, 연번 1~1598, 유해성 세부행 2412.
CURRENT_BASE_ITEM_COUNT = 1598
CURRENT_PAGE_COUNT = 58
CURRENT_HAZARD_RECORD_COUNT = 2412

APP2_COLUMNS = [
    "record_key",
    "item_no",
    "hazard_seq",
    "designation_id",
    "substance_name",
    "cas_text",
    "cas_list",
    "direct_cas",
    "all_cas_in_row",
    "scope_type",
    "hazard_category",
    "content_threshold_pct",
    "lowest_quantity_ton",
    "lower_quantity_ton",
    "upper_quantity_ton",
    "active",
    "deleted",
    "source_text",
    "source_key",
    "source_title",
    "effective_date",
    "issue_number",
    "source_pdf_sha256",
    "source_page",
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


def _pick_appendix2_pdf() -> Path | None:
    matches: list[Path] = []
    for path in observed_pdf_paths("CAP_QTY"):
        logical = path.stem.split("__", 1)[0].replace(" ", "")
        if re.search(r"별표0*2(?:_|$)", logical):
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


def _cas_values(*values: Any) -> list[str]:
    found: list[str] = []
    for value in values:
        compact = re.sub(r"\s+", "", _clean(value))
        found.extend(CAS_RE.findall(compact))
    return list(dict.fromkeys(found))


def _is_appendix2_table(table: list[list[Any]]) -> bool:
    if not table:
        return False
    header = " ".join(_clean(cell) for cell in table[0])
    return all(token in header for token in ("연번", "고유번호", "화학물질명", "CAS", "함량기준", "규정수량"))


def _extract_tables(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            try:
                tables = page.extract_tables() or []
            except Exception:
                tables = []
            matches = [table for table in tables if _is_appendix2_table(table)]
            if len(matches) == 1:
                out.append({"page": page_no, "rows": matches[0]})
            else:
                out.append({"page": page_no, "rows": None, "match_count": len(matches)})
    return out


def _direct_cas_for_scope(scope_type: str, cas_values: list[str]) -> list[str]:
    """Keep component CAS out of the exact-identity path for reaction mixtures."""
    if scope_type in {"REACTION_PRODUCT", "MIXTURE"}:
        return []
    return cas_values


def _build_records(
    tables: list[dict[str, Any]],
    source: dict[str, Any],
    source_hash: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    failures: list[str] = []

    for page_info in tables:
        page_no = int(page_info["page"])
        table = page_info.get("rows")
        if table is None:
            failures.append(f"{page_no}쪽 별표2 표 인식 개수 {page_info.get('match_count', 0)}")
            continue

        current: dict[str, Any] | None = None
        hazard_seq = 0
        for raw in table[1:]:
            cells = list(raw or []) + [None] * 9
            cells = cells[:9]
            no_text = _clean(cells[0])
            if re.fullmatch(r"\d{1,4}", no_text):
                current = {
                    "item_no": int(no_text),
                    "designation_id": _clean(cells[1]),
                    "substance_name": _clean(cells[2]),
                    "cas_text": _clean(cells[3]),
                }
                hazard_seq = 0
            elif current is None:
                continue

            hazard = _clean(cells[4])
            if not hazard:
                continue
            hazard_seq += 1

            name = str(current["substance_name"])
            cas_text = str(current["cas_text"])
            listed_cas = _cas_values(cas_text)
            all_cas = _cas_values(cas_text, name)
            deleted = "삭제" in hazard or "삭제" in name
            if listed_cas:
                tentative_scope = classify_scope_type(name, "", name)
                scope_type = "DIRECT_CAS" if tentative_scope == "NAME_OR_UVCB" else tentative_scope
            else:
                scope_type = classify_scope_type(name, "", name)
            direct_cas = _direct_cas_for_scope(scope_type, listed_cas)

            records.append(
                {
                    "record_key": f"{current['item_no']}:{hazard_seq}",
                    "item_no": int(current["item_no"]),
                    "hazard_seq": hazard_seq,
                    "designation_id": str(current["designation_id"]),
                    "substance_name": name,
                    "cas_text": cas_text,
                    "cas_list": "|".join(listed_cas),
                    "direct_cas": "|".join(direct_cas),
                    "all_cas_in_row": "|".join(all_cas),
                    "scope_type": scope_type,
                    "hazard_category": hazard,
                    "content_threshold_pct": _num(cells[5]),
                    "lowest_quantity_ton": _num(cells[6]),
                    "lower_quantity_ton": _num(cells[7]),
                    "upper_quantity_ton": _num(cells[8]),
                    "active": not deleted,
                    "deleted": deleted,
                    "source_text": name,
                    "source_key": "CAP_QTY_APP2",
                    "source_title": source.get("title", "유해화학물질의 규정수량에 관한 규정"),
                    "effective_date": source.get("effective_date", ""),
                    "issue_number": source.get("issue_number", ""),
                    "source_pdf_sha256": source_hash,
                    "source_page": page_no,
                }
            )

    return records, failures


def _anchor_checks(df: pd.DataFrame) -> dict[str, bool]:
    """핵심 물질이 올바른 모양으로 추출되었는지 보는 앵커 검사.

    개정으로 물질이 중간에 끼어들면 뒤쪽 연번이 전부 밀리므로, 연번이 아니라 CAS로 대상 행을 찾는다.
    (연번에 고정했던 이전 방식은 2026-12 개정에서 한 칸씩 밀리자 내용이 맞는데도 전부 실패했다.)
    맨 앞의 1·4·10번은 개정으로 밀리지 않았으므로 연번 앵커를 그대로 둔다.
    """

    def row(item_no: int, hazard_seq: int = 1) -> pd.DataFrame:
        return df[(df["item_no"].eq(item_no)) & (df["hazard_seq"].eq(hazard_seq))]

    def has_cas(series: pd.Series, cas: str) -> pd.Series:
        return series.astype(str).str.split("|").apply(lambda values: cas in values)

    def special_row(cas: str, category: str) -> pd.DataFrame:
        return df[
            has_cas(df["direct_cas"], cas)
            & df["hazard_category"].astype(str).str.strip().eq(category)
        ]

    r1 = row(1)
    r4 = row(4)
    r10 = row(10)
    ammonia = special_row("7664-41-7", "용액")
    hydrogen_fluoride = special_row("7664-39-3", "용액")
    hydroxylamine_salts = df[
        df["scope_type"].eq("SALT_FAMILY")
        & df["direct_cas"].astype(str).eq("")
        & has_cas(df["all_cas_in_row"], "7803-49-8")
    ]
    acrylate_mixture = df[
        df["scope_type"].eq("REACTION_PRODUCT")
        & df["direct_cas"].astype(str).eq("")
        & has_cas(df["cas_list"], "5459-38-1")
    ]
    dimethylbenzenesulfonic = df[has_cas(df["direct_cas"], "25321-41-9")]

    return {
        "item1_exact_cas": bool(not r1.empty and r1.iloc[0]["direct_cas"] == "1313-60-6"),
        "item1_quantities": bool(
            not r1.empty
            and float(r1.iloc[0]["lowest_quantity_ton"]) == 0.125
            and float(r1.iloc[0]["lower_quantity_ton"]) == 5
            and float(r1.iloc[0]["upper_quantity_ton"]) == 200
        ),
        "item4_casless_salt_family": bool(
            not r4.empty and r4.iloc[0]["direct_cas"] == "" and r4.iloc[0]["scope_type"] == "SALT_FAMILY"
        ),
        "item10_casless_compound_group": bool(
            not r10.empty and r10.iloc[0]["direct_cas"] == "" and r10.iloc[0]["scope_type"] == "COMPOUND_GROUP"
        ),
        "ammonia_solution_variant": bool(
            len(ammonia) == 1
            and pd.isna(ammonia.iloc[0]["content_threshold_pct"])
            and float(ammonia.iloc[0]["lowest_quantity_ton"]) == 0.5
            and float(ammonia.iloc[0]["lower_quantity_ton"]) == 20
            and float(ammonia.iloc[0]["upper_quantity_ton"]) == 400
        ),
        "hydrogen_fluoride_solution_variant": bool(
            len(hydrogen_fluoride) == 1
            and pd.isna(hydrogen_fluoride.iloc[0]["content_threshold_pct"])
            and float(hydrogen_fluoride.iloc[0]["lowest_quantity_ton"]) == 0.1
            and float(hydrogen_fluoride.iloc[0]["lower_quantity_ton"]) == 4
            and float(hydrogen_fluoride.iloc[0]["upper_quantity_ton"]) == 20
        ),
        "hydroxylamine_salts_embedded_parent_cas": bool(not hydroxylamine_salts.empty),
        "acrylate_reaction_mixture_not_direct": bool(
            not acrylate_mixture.empty
            and len(str(acrylate_mixture.iloc[0]["cas_list"]).split("|")) == 3
        ),
        "dimethylbenzenesulfonic_acid_exact_cas": bool(not dimethylbenzenesulfonic.empty),
    }


def _solution_note_item_numbers(path: Path) -> list[int]:
    """1쪽 일반기준 '표의 제N호, 제M호의 물질은 … 용액 구분' 문구가 가리키는 연번."""
    try:
        with pdfplumber.open(path) as pdf:
            text = re.sub(r"\s+", "", pdf.pages[0].extract_text() or "")
    except Exception:
        return []
    match = re.search(r"표의((?:제\d+호[,、，]?)+)의물질은[^.]{0,80}?용액", text)
    return [int(n) for n in re.findall(r"제(\d+)호", match.group(1))] if match else []


def build_cap_appendix2_candidate() -> CandidateResult:
    source = observed_source("CAP_QTY")
    path = _pick_appendix2_pdf()
    if not source or path is None:
        return CandidateResult(
            key="CAP_QTY_APP2",
            status="SOURCE_NOT_READY",
            row_count=0,
            source_file="",
            candidate_file="",
            messages=["CAP_QTY의 현행 별표 2 PDF를 정확히 하나 찾지 못했습니다. 법령 감시 결과를 확인하세요."],
            checks={},
        )

    tables = _extract_tables(path)
    source_hash = _source_hash_for_path(source, path)
    records, extraction_failures = _build_records(tables, source, source_hash)
    df = pd.DataFrame(records, columns=APP2_COLUMNS)
    if not df.empty:
        df.sort_values(["item_no", "hazard_seq"], inplace=True)
        df.reset_index(drop=True, inplace=True)

    base = df.drop_duplicates(subset=["item_no"], keep="first") if not df.empty else pd.DataFrame(columns=df.columns)
    item_numbers = base["item_no"].astype(int).tolist() if not base.empty else []
    casless_base = int(base["direct_cas"].astype(str).eq("").sum()) if not base.empty else 0
    deleted_base = int(base["deleted"].astype(bool).sum()) if not base.empty else 0
    broad_base = int(base["scope_type"].astype(str).ne("DIRECT_CAS").sum()) if not base.empty else 0

    active = df[df["active"].astype(bool)] if not df.empty else df
    # 저확산 and 용액 are legal special rows whose concentration cell can be blank.
    special = active["hazard_category"].astype(str).str.contains("저확산|용액", regex=True, na=False)
    active_general = active[~special]
    missing_required = 0
    if not active_general.empty:
        missing_required = int(
            active_general[["content_threshold_pct", "lowest_quantity_ton", "lower_quantity_ton"]]
            .isna().any(axis=1).sum()
        )

    anchors = _anchor_checks(df)
    # 고시 본문(일반기준)이 가리키는 용액 구분 연번과 표에서 실제 용액 구분이 있는 연번이 다르면 경고한다.
    # 실패는 아니지만 공식 문서 안의 불일치이므로 승인 전에 사람이 확인해야 한다.
    warnings: list[str] = []
    note_items = _solution_note_item_numbers(path)
    table_items = sorted({int(n) for n in df.loc[df["hazard_category"].astype(str).str.strip().eq("용액"), "item_no"]}) if not df.empty else []
    if note_items and note_items != table_items:
        warnings.append(
            f"일반기준 문구는 용액 구분을 제{'·'.join(map(str, note_items))}호로 안내하지만, 표에서 용액 구분이 있는 연번은 "
            f"{'·'.join(map(str, table_items)) or '없음'}입니다. 고시 본문의 번호 표기와 표가 어긋난 것으로 보이니 "
            "대상 물질(암모니아·플루오르화 수소)이 맞는지 확인하세요."
        )
    failure_reasons = list(extraction_failures)
    if len(tables) != CURRENT_PAGE_COUNT:
        failure_reasons.append(f"페이지 검사 수 {len(tables)} != {CURRENT_PAGE_COUNT}")
    if item_numbers != list(range(1, CURRENT_BASE_ITEM_COUNT + 1)):
        failure_reasons.append(f"기본 연번 1~{CURRENT_BASE_ITEM_COUNT} 연속 추출 실패")
    if len(df) != CURRENT_HAZARD_RECORD_COUNT:
        failure_reasons.append(f"유해성 세부행 {len(df)} != {CURRENT_HAZARD_RECORD_COUNT}")
    if missing_required:
        failure_reasons.append(f"활성 일반 유해성행 필수 규정수량 누락 {missing_required}건")
    failed_anchors = [key for key, ok in anchors.items() if not ok]
    if failed_anchors:
        failure_reasons.append("핵심 앵커 검사 실패: " + ", ".join(failed_anchors))

    checks = {
        "parser_mode": "MULTIHAZARD_WITH_CASLESS_SCOPE_CAS_ANCHORS",
        "pages": len(tables),
        "base_items": len(base),
        "hazard_records": len(df),
        "casless_or_nondirect_base_items": casless_base,
        "broad_scope_base_items": broad_base,
        "deleted_base_items": deleted_base,
        "first_item": item_numbers[0] if item_numbers else None,
        "last_item": item_numbers[-1] if item_numbers else None,
        "item_numbers_exactly_1_to_expected": item_numbers == list(range(1, CURRENT_BASE_ITEM_COUNT + 1)),
        "expected_base_items": CURRENT_BASE_ITEM_COUNT,
        "missing_required_active_rows": missing_required,
        **anchors,
        "failure_reasons": failure_reasons,
        "warnings": warnings,
    }

    status = "REVIEW_REQUIRED" if not failure_reasons else "VALIDATION_FAILED"
    messages = [
        "별표 2의 직접 CAS와 CAS 미기재 포괄 규제범위를 함께 보존한 후보표를 만들었습니다. "
        "같은 연번에 여러 유해성 구분이 있으면 각각 별도 행으로 유지합니다."
    ]
    messages.extend(f"확인 필요: {warning}" for warning in warnings)
    if failure_reasons:
        messages.append("자동추출 품질검사를 통과하지 못했습니다. 승인하지 말고 실패항목을 확인하세요.")
    else:
        messages.append(
            "CAS가 '-'인 염류·화합물군뿐 아니라 반응혼합물의 구성성분 CAS, 삭제행, 용액 특수행까지 보존했습니다. 공식 PDF와 확인 후 승인하세요."
        )

    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = CANDIDATE_DIR / "cap_qty_app2_candidate.csv"
    meta_path = CANDIDATE_DIR / "cap_qty_app2_candidate.meta.json"
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
        key="CAP_QTY_APP2",
        status=status,
        row_count=len(df),
        source_file=str(path.relative_to(PROJECT_ROOT)),
        candidate_file=str(csv_path.relative_to(PROJECT_ROOT)),
        messages=messages,
        checks=checks,
    )
