from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable

import pandas as pd
import pdfplumber

from .law_monitor import PROJECT_ROOT, PENDING_PDF_DIR, file_sha256
from .regulatory_db import normalize_cas


CAS_FIND_RE = re.compile(r"\b\d{2,7}-\d{2}-\d\b")
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])\d{1,3}(?:,\d{3})*(?:\.\d+)?")


def _clean_cell(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _table_rows(pdf_path: Path) -> Iterable[dict[str, object]]:
    """Yield raw extracted table rows with page provenance.

    This is deliberately a candidate extractor, not an automatic legal parser.
    It preserves raw cells so an administrator can verify how the PDF was read.
    """
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            tables = page.extract_tables() or []
            for table_no, table in enumerate(tables, 1):
                for row_no, row in enumerate(table or [], 1):
                    cells = [_clean_cell(v) for v in (row or [])]
                    if not any(cells):
                        continue
                    yield {
                        "page": page_no,
                        "table": table_no,
                        "row": row_no,
                        "cells": cells,
                        "raw_text": " | ".join(cells),
                    }


def _numbers_without_cas(text: str, cas: str) -> list[str]:
    working = text.replace(cas, " ") if cas else text
    return NUMBER_RE.findall(working)


def extract_generic_candidates(pdf_path: str | Path, source_key: str) -> pd.DataFrame:
    """Extract review candidates from one official PDF.

    Output is intentionally generic. No row is approved automatically.
    """
    path = Path(pdf_path)
    digest = file_sha256(path)
    rows: list[dict[str, object]] = []
    for item in _table_rows(path):
        text = str(item["raw_text"])
        cas_match = CAS_FIND_RE.search(text)
        cas = normalize_cas(cas_match.group(0)) if cas_match else ""
        nums = _numbers_without_cas(text, cas)
        rows.append(
            {
                "source_key": source_key,
                "source_file": str(path),
                "source_hash": digest,
                "page": item["page"],
                "table": item["table"],
                "row": item["row"],
                "cas_candidate": cas,
                "numeric_candidates": ";".join(nums),
                "raw_text": text,
                "review_status": "검토필요",
            }
        )
    return pd.DataFrame(rows)


def list_pending_pdfs(source_key: str | None = None) -> list[Path]:
    root = PENDING_PDF_DIR
    if source_key:
        root = root / source_key
    if not root.exists():
        return []
    return sorted(root.rglob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)


def build_psm_review_sheet(pdf_path: str | Path) -> pd.DataFrame:
    """Create a PSM Appendix 13 review sheet from generic candidates.

    Values are left for human verification because table layouts can change.
    The columns match the approved DB schema so the reviewed CSV can be
    promoted without another transformation step.
    """
    generic = extract_generic_candidates(pdf_path, "PSM_DECREE")
    if generic.empty:
        return pd.DataFrame(columns=[
            "item_no", "cas", "substance_name", "manufacture_use_kg", "storage_kg",
            "threshold_note", "legal_basis", "source_effective_date", "source_hash",
            "raw_text", "review_status",
        ])
    out = pd.DataFrame()
    out["item_no"] = ""
    out["cas"] = generic["cas_candidate"]
    out["substance_name"] = ""
    out["manufacture_use_kg"] = ""
    out["storage_kg"] = ""
    out["threshold_note"] = ""
    out["legal_basis"] = "산업안전보건법 시행령 제43조제1항 및 별표 13"
    out["source_effective_date"] = ""
    out["source_hash"] = generic["source_hash"]
    out["raw_text"] = generic["raw_text"]
    out["review_status"] = "검토필요"
    return out


def build_cap_review_sheet(pdf_path: str | Path) -> pd.DataFrame:
    """Create a CAP quantity review sheet from generic candidates."""
    generic = extract_generic_candidates(pdf_path, "CAP_QTY")
    if generic.empty:
        return pd.DataFrame(columns=[
            "cas", "substance_name", "lower_ton", "upper_ton", "lowest_ton",
            "legal_basis", "source_effective_date", "source_hash", "raw_text", "review_status",
        ])
    out = pd.DataFrame()
    out["cas"] = generic["cas_candidate"]
    out["substance_name"] = ""
    out["lower_ton"] = ""
    out["upper_ton"] = ""
    out["lowest_ton"] = ""
    out["legal_basis"] = "유해화학물질의 규정수량에 관한 규정"
    out["source_effective_date"] = ""
    out["source_hash"] = generic["source_hash"]
    out["raw_text"] = generic["raw_text"]
    out["review_status"] = "검토필요"
    return out


def save_review_candidate(df: pd.DataFrame, name: str) -> Path:
    target_dir = PROJECT_ROOT / "data" / "runtime" / "rule_candidates"
    target_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", name).strip("_.") or "candidate"
    target = target_dir / f"{safe}.csv"
    df.to_csv(target, index=False, encoding="utf-8-sig")
    return target
