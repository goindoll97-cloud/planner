from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pdfplumber


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_ROOT / "data" / "runtime"
OBSERVED_FILE = RUNTIME_DIR / "law_monitor_last_observed.json"
CANDIDATE_DIR = RUNTIME_DIR / "regulatory_candidates"
APPROVED_DIR = PROJECT_ROOT / "data" / "regulatory" / "approved"

CAS_RE = re.compile(r"\b\d{2,7}-\d{2}-\d\b")
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass
class CandidateResult:
    key: str
    status: str
    row_count: int
    source_file: str
    candidate_file: str
    messages: list[str]
    checks: dict[str, Any]


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\u00a0", " ").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    return text.strip()


def _norm_header(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣%]", "", _clean(value)).lower()


def _float(value: Any) -> float | None:
    text = _clean(value).replace(",", "")
    match = NUMBER_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def _int_no(value: Any) -> int | None:
    text = _clean(value)
    match = re.fullmatch(r"\D*(\d{1,4})\D*", text)
    return int(match.group(1)) if match else None


def _observed_rows() -> list[dict[str, Any]]:
    payload = _load_json(OBSERVED_FILE, {})
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    return rows if isinstance(rows, list) else []


def observed_source(key: str) -> dict[str, Any] | None:
    for row in _observed_rows():
        if str(row.get("key", "")) == key:
            return row
    return None


def observed_pdf_paths(key: str) -> list[Path]:
    row = observed_source(key)
    if not row:
        return []
    paths: list[Path] = []
    for raw in row.get("pending_pdf_files", []) or []:
        path = PROJECT_ROOT / str(raw)
        if path.exists() and path.suffix.lower() == ".pdf":
            paths.append(path)
    return paths


def _pick_pdf(key: str, contains: Iterable[str] = ()) -> Path | None:
    files = observed_pdf_paths(key)
    wanted = [str(v) for v in contains if str(v)]
    if wanted:
        for path in files:
            name = path.name.replace(" ", "")
            if all(token.replace(" ", "") in name for token in wanted):
                return path
    return files[0] if len(files) == 1 else None


def _tables_from_pdf(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    settings_list = [
        {},
        {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
            "snap_tolerance": 4,
            "join_tolerance": 4,
            "intersection_tolerance": 5,
        },
        {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "min_words_vertical": 2,
            "min_words_horizontal": 1,
        },
    ]
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            page_tables: list[list[list[Any]]] = []
            for settings in settings_list:
                try:
                    extracted = page.extract_tables(table_settings=settings) or []
                except Exception:
                    extracted = []
                if extracted:
                    page_tables = extracted
                    break
            for table_no, table in enumerate(page_tables, 1):
                if not table:
                    continue
                out.append({"page": page_no, "table": table_no, "rows": table})
    return out


def _merge_continuation_rows(table: list[list[Any]], min_cols: int) -> list[list[str]]:
    """Merge PDF rows whose first column is blank into the prior legal row."""
    merged: list[list[str]] = []
    current: list[str] | None = None
    for raw in table:
        cells = [_clean(v) for v in raw]
        if len(cells) < min_cols:
            cells += [""] * (min_cols - len(cells))
        no = _int_no(cells[0])
        if no is not None:
            if current is not None:
                merged.append(current)
            current = cells
            current[0] = str(no)
        elif current is not None and any(cells):
            for idx in range(min(len(current), len(cells))):
                if not cells[idx]:
                    continue
                current[idx] = (current[idx] + " " + cells[idx]).strip()
    if current is not None:
        merged.append(current)
    return merged


def _find_candidate_table(tables: list[dict[str, Any]], required_header_tokens: Iterable[str]) -> dict[str, Any] | None:
    tokens = [_norm_header(v) for v in required_header_tokens]
    best: tuple[int, dict[str, Any]] | None = None
    for item in tables:
        rows = item["rows"]
        first_rows = rows[:4]
        header_text = " ".join(_norm_header(cell) for row in first_rows for cell in row)
        score = sum(1 for token in tokens if token and token in header_text)
        if score == len(tokens):
            numeric_rows = sum(1 for row in rows if row and _int_no(row[0]) is not None)
            rank = numeric_rows * 10 + len(rows)
            if best is None or rank > best[0]:
                best = (rank, item)
    return best[1] if best else None


def _parse_psm_quantity(text: str) -> tuple[float | None, float | None]:
    clean = _clean(text).replace(",", "")
    numbers = [float(v) for v in re.findall(r"\d+(?:\.\d+)?", clean)]
    if not numbers:
        return None, None
    # Annex 13 items 1-2 use separate manufacture/handling and storage thresholds.
    if "저장" in clean and ("제조" in clean or "취급" in clean) and len(numbers) >= 2:
        return numbers[0], numbers[1]
    return numbers[0], numbers[0]


def build_psm_annex13_candidate() -> CandidateResult:
    source = observed_source("PSM_DECREE")
    path = _pick_pdf("PSM_DECREE", ["13"])
    messages: list[str] = []
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
    table_item = _find_candidate_table(tables, ["유해위험물질", "cas", "규정량"])
    if table_item is None:
        return CandidateResult(
            key="PSM_ANNEX13",
            status="TABLE_NOT_RECOGNIZED",
            row_count=0,
            source_file=str(path.relative_to(PROJECT_ROOT)),
            candidate_file="",
            messages=["별표 13에서 '유해·위험물질/CAS/규정량' 표를 자동 인식하지 못했습니다."],
            checks={"tables_found": len(tables)},
        )

    merged = _merge_continuation_rows(table_item["rows"], 4)
    records: list[dict[str, Any]] = []
    for cells in merged:
        no = _int_no(cells[0])
        if no is None:
            continue
        # Table should be no/name/CAS/quantity. If extraction introduced extra columns,
        # join the middle columns conservatively and keep the last column as quantity.
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

    df = pd.DataFrame(records).drop_duplicates(subset=["item_no"], keep="first")
    df.sort_values("item_no", inplace=True)
    df.reset_index(drop=True, inplace=True)

    missing_name = int(df["substance_name"].eq("").sum()) if not df.empty else 0
    missing_qty = int(
        (df["manufacture_handling_threshold_kg"].isna() | df["storage_threshold_kg"].isna()).sum()
    ) if not df.empty else 0
    numbers = df["item_no"].astype(int).tolist() if not df.empty else []
    consecutive = bool(numbers) and numbers == list(range(min(numbers), max(numbers) + 1))
    checks = {
        "tables_found": len(tables),
        "recognized_page": table_item["page"],
        "recognized_table": table_item["table"],
        "rows": len(df),
        "missing_name": missing_name,
        "missing_quantity": missing_qty,
        "item_numbers_consecutive": consecutive,
        "property_rows": int(df["match_type"].eq("PROPERTY").sum()) if not df.empty else 0,
    }

    status = "REVIEW_REQUIRED"
    if len(df) < 10 or missing_name or missing_qty or not consecutive:
        status = "VALIDATION_FAILED"
        messages.append("자동추출 품질검사를 통과하지 못했습니다. 승인하지 말고 표 추출결과를 확인하세요.")
    else:
        messages.append("자동추출 후보를 만들었습니다. 공식 PDF와 표 행수·수량을 확인한 뒤에만 승인하세요.")

    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = CANDIDATE_DIR / "psm_annex13_candidate.csv"
    meta_path = CANDIDATE_DIR / "psm_annex13_candidate.meta.json"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    _write_json(
        meta_path,
        {
            "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "result": asdict(CandidateResult(
                key="PSM_ANNEX13",
                status=status,
                row_count=len(df),
                source_file=str(path.relative_to(PROJECT_ROOT)),
                candidate_file=str(csv_path.relative_to(PROJECT_ROOT)),
                messages=messages,
                checks=checks,
            )),
        },
    )
    return CandidateResult(
        key="PSM_ANNEX13",
        status=status,
        row_count=len(df),
        source_file=str(path.relative_to(PROJECT_ROOT)),
        candidate_file=str(csv_path.relative_to(PROJECT_ROOT)),
        messages=messages,
        checks=checks,
    )


def build_cap_accident_quantity_candidate() -> CandidateResult:
    """Extract CAP_QTY appendix 3 (accident-preparedness substances) as a review candidate."""
    source = observed_source("CAP_QTY")
    path = _pick_pdf("CAP_QTY", ["3"])
    messages: list[str] = []
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
    table_item = _find_candidate_table(tables, ["사고대비물질", "cas", "하위규정수량", "상위규정수량"])
    if table_item is None:
        return CandidateResult(
            key="CAP_QTY_APP3",
            status="TABLE_NOT_RECOGNIZED",
            row_count=0,
            source_file=str(path.relative_to(PROJECT_ROOT)),
            candidate_file="",
            messages=["별표 3 사고대비물질 규정수량 표를 자동 인식하지 못했습니다."],
            checks={"tables_found": len(tables)},
        )

    merged = _merge_continuation_rows(table_item["rows"], 7)
    records: list[dict[str, Any]] = []
    for cells in merged:
        no = _int_no(cells[0])
        if no is None:
            continue
        # Expected legal layout: no/name/CAS/content criterion/lowest/lower/upper.
        # When the table has more cells, only the first seven are accepted; this
        # deliberately fails validation rather than guessing a shifted structure.
        if len(cells) < 7:
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

    df = pd.DataFrame(records).drop_duplicates(subset=["item_no"], keep="first")
    if not df.empty:
        df.sort_values("item_no", inplace=True)
        df.reset_index(drop=True, inplace=True)
    missing = 0
    if not df.empty:
        required = ["substance_name", "content_threshold_pct", "lowest_quantity_ton", "lower_quantity_ton", "upper_quantity_ton"]
        missing = int(df[required].isna().any(axis=1).sum()) + int(df["substance_name"].eq("").sum())
    numbers = df["item_no"].astype(int).tolist() if not df.empty else []
    consecutive = bool(numbers) and numbers == list(range(min(numbers), max(numbers) + 1))
    checks = {
        "tables_found": len(tables),
        "recognized_page": table_item["page"],
        "recognized_table": table_item["table"],
        "rows": len(df),
        "rows_with_missing_required_value": missing,
        "item_numbers_consecutive": consecutive,
    }
    status = "REVIEW_REQUIRED"
    if len(df) < 10 or missing or not consecutive:
        status = "VALIDATION_FAILED"
        messages.append("자동추출 품질검사를 통과하지 못했습니다. 승인하지 말고 표 추출결과를 확인하세요.")
    else:
        messages.append("사고대비물질 규정수량 후보를 만들었습니다. 공식 별표 3과 대조한 뒤 승인하세요.")

    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = CANDIDATE_DIR / "cap_qty_app3_candidate.csv"
    meta_path = CANDIDATE_DIR / "cap_qty_app3_candidate.meta.json"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    _write_json(meta_path, {"created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "checks": checks, "status": status})
    return CandidateResult(
        key="CAP_QTY_APP3",
        status=status,
        row_count=len(df),
        source_file=str(path.relative_to(PROJECT_ROOT)),
        candidate_file=str(csv_path.relative_to(PROJECT_ROOT)),
        messages=messages,
        checks=checks,
    )


def candidate_preview(key: str, max_rows: int = 80) -> pd.DataFrame:
    mapping = {
        "PSM_ANNEX13": CANDIDATE_DIR / "psm_annex13_candidate.csv",
        "CAP_QTY_APP3": CANDIDATE_DIR / "cap_qty_app3_candidate.csv",
    }
    path = mapping.get(key)
    if not path or not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False).head(max_rows)


def approve_candidate(key: str) -> dict[str, Any]:
    mapping = {
        "PSM_ANNEX13": (
            CANDIDATE_DIR / "psm_annex13_candidate.csv",
            APPROVED_DIR / "psm_annex13.csv",
        ),
        "CAP_QTY_APP3": (
            CANDIDATE_DIR / "cap_qty_app3_candidate.csv",
            APPROVED_DIR / "cap_qty_app3.csv",
        ),
    }
    pair = mapping.get(key)
    if not pair:
        return {"status": "UNKNOWN_KEY", "message": f"알 수 없는 규제표 후보입니다: {key}"}
    src, dst = pair
    if not src.exists():
        return {"status": "NO_CANDIDATE", "message": "먼저 최신 PDF에서 후보표를 추출하세요."}

    df = pd.read_csv(src)
    if df.empty:
        return {"status": "EMPTY", "message": "후보표가 비어 있어 승인할 수 없습니다."}
    APPROVED_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    audit = APPROVED_DIR / f"{dst.stem}.approval.json"
    _write_json(
        audit,
        {
            "approved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "key": key,
            "row_count": len(df),
            "candidate_file": str(src.relative_to(PROJECT_ROOT)),
            "approved_file": str(dst.relative_to(PROJECT_ROOT)),
        },
    )
    return {
        "status": "APPROVED",
        "message": f"{key} 후보 {len(df)}행을 판정용 승인 DB로 저장했습니다.",
        "approved_file": str(dst.relative_to(PROJECT_ROOT)),
        "row_count": len(df),
    }


def approved_db_status() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for key, name in (("PSM_ANNEX13", "psm_annex13.csv"), ("CAP_QTY_APP3", "cap_qty_app3.csv")):
        path = APPROVED_DIR / name
        count = 0
        if path.exists():
            try:
                count = len(pd.read_csv(path))
            except Exception:
                count = -1
        rows.append({"key": key, "approved": path.exists(), "rows": count, "file": str(path.relative_to(PROJECT_ROOT))})
    return pd.DataFrame(rows)
