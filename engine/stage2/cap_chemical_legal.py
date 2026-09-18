from __future__ import annotations

"""Enrich CAP Annex Form 6 chemical rows with current-law identity fields.

The company remains the source of product/CAS/concentration/physical-property
facts. Legal material classes and the statutory "고유번호" are derived only
from reviewed current-law tables. The Appendix-2 designation ID is used for the
Form-6 unique number because the parser reads it directly from the official
"고유번호" column. Appendix-3 item numbers are never substituted for it.
"""

from dataclasses import dataclass
from collections.abc import Mapping
import re
from typing import Any

import pandas as pd

from engine.cap_scope_engine import (
    load_approved_scope_tables,
    screen_cap_scope_candidates_from_tables,
)
from engine.inventory import IntakeData

from .cap_form1_engine import build_cap_form1_data, mass_to_ton
from .project import CONFIRMED_STATUSES, Stage2Project


@dataclass(frozen=True)
class CAPChemicalLegalData:
    rows: tuple[dict[str, Any], ...]
    blockers: tuple[str, ...]
    messages: tuple[str, ...]
    app2_ready: bool

    @property
    def ready(self) -> bool:
        return self.app2_ready and not self.blockers and bool(self.rows)


def _clean(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def _norm(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", _clean(value)).lower()


def _num(value: object) -> float | None:
    text = _clean(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        m = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(m.group()) if m else None


def _row_value(row: Mapping[str, Any], *aliases: str) -> Any:
    normalized = {_norm(k): v for k, v in row.items()}
    for alias in aliases:
        value = normalized.get(_norm(alias))
        if value not in (None, "") and _clean(value):
            return value
    return ""


def _confirmed_rows(project: Stage2Project, *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        rec = project.get_field(key)
        if rec is None or rec.status not in CONFIRMED_STATUSES:
            continue
        if isinstance(rec.value, list):
            rows = [dict(row) for row in rec.value if isinstance(row, Mapping)]
            if rows:
                return rows
    return []


def _split_cas(value: object) -> set[str]:
    return {
        token.strip()
        for token in re.split(r"[|;,]", _clean(value))
        if re.fullmatch(r"\d{2,7}-\d{2}-\d", token.strip())
    }


def _truthy(value: object) -> bool:
    text = _clean(value).lower()
    return not text or text in {"1", "true", "yes", "y", "예", "active"}


def _material_class(category: object) -> str:
    text = _clean(category)
    n = _norm(text)
    if not n or n in {_norm("용액"), _norm("저확산")}:
        return ""
    if "인체급성유해성" in n:
        return "인체급성유해성물질"
    if "인체만성유해성" in n:
        return "인체만성유해성물질"
    if "생태유해성" in n:
        return "생태유해성물질"
    # Current Appendix 2 is defined around the three classes above. Unknown
    # labels are not promoted into a statutory material class automatically.
    return ""


def _adapt_for_scope(chemicals: list[dict[str, Any]]) -> IntakeData:
    rows: list[dict[str, Any]] = []
    for row in chemicals:
        value = _row_value(row, "최대보유량", "최대보유량(kg)")
        unit = _row_value(row, "단위", "최대보유량 단위")
        if not _clean(unit) and _clean(_row_value(row, "최대보유량(kg)")):
            unit = "kg"
        ton = mass_to_ton(value, unit)
        rows.append({
            "제품명": _row_value(row, "물질명", "유해화학물질명", "제품명"),
            "CAS No.": _row_value(row, "CAS 번호", "CAS No.", "화학물질식별번호"),
            "함량(%)": _row_value(row, "함량(%)", "함량", "농도(%)"),
            "최대 동시보유량(알면 입력)": ton if ton is not None else "",
            "수량 단위": "ton" if ton is not None else "",
        })
    return IntakeData(business={}, chemicals=pd.DataFrame(rows), documents={}, facilities=pd.DataFrame())


def _app2_direct_matches(
    chemicals: list[dict[str, Any]],
    tables: dict[str, pd.DataFrame],
) -> dict[int, list[dict[str, Any]]]:
    matches: dict[int, list[dict[str, Any]]] = {}
    if not tables:
        return matches

    frames: list[pd.DataFrame] = []
    for source_key, raw in tables.items():
        if raw is None or raw.empty:
            continue
        frame = raw.copy()
        if "source_key" not in frame.columns:
            frame["source_key"] = source_key
        if "active" in frame.columns:
            frame = frame[frame["active"].map(_truthy)].copy()
        frames.append(frame)
    if not frames:
        return matches
    master = pd.concat(frames, ignore_index=True, sort=False)

    for row_no, chem in enumerate(chemicals, start=1):
        cas = _clean(_row_value(chem, "CAS 번호", "CAS No.", "화학물질식별번호"))
        if not re.fullmatch(r"\d{2,7}-\d{2}-\d", cas):
            continue
        pct = _num(_row_value(chem, "함량(%)", "함량", "농도(%)"))
        selected: list[dict[str, Any]] = []
        for _, legal in master.iterrows():
            if cas not in _split_cas(legal.get("direct_cas")):
                continue
            threshold = _num(legal.get("content_threshold_pct"))
            if threshold is not None:
                if pct is None or pct < threshold:
                    continue
            selected.append(dict(legal))
        if selected:
            matches[row_no] = selected
    return matches


def build_cap_chemical_legal_data(project: Stage2Project) -> CAPChemicalLegalData:
    chemicals = _confirmed_rows(project, "cap.chemical.details", "inventory.chemicals")
    if not chemicals:
        return CAPChemicalLegalData((), ("유해화학물질 목록이 없어 별지 제6호 법적 물질정보를 작성할 수 없습니다.",), (), False)

    tables, missing = load_approved_scope_tables()
    app2_ready = not missing and bool(tables)
    blockers: list[str] = []
    messages: list[str] = []

    if missing:
        blockers.append("현행 유해화학물질 규정수량 별표 2 승인 DB가 없어 고유번호·물질구분을 확정할 수 없습니다.")

    direct = _app2_direct_matches(chemicals, tables)
    intake = _adapt_for_scope(chemicals)
    broad = screen_cap_scope_candidates_from_tables(intake, tables) if tables else pd.DataFrame()
    broad_rows = {
        int(value)
        for value in (broad.get("row_no", pd.Series(dtype=int)).tolist() if not broad.empty else [])
        if str(value).strip().isdigit()
    }

    form1 = build_cap_form1_data(project)
    accident_cas = {
        _clean(row.get("CAS No."))
        for row in form1.chemical_rows
        if "사고대비물질" in _clean(row.get("물질구분"))
    }

    enriched: list[dict[str, Any]] = []
    for row_no, chem in enumerate(chemicals, start=1):
        row = dict(chem)
        name = _clean(_row_value(chem, "물질명", "유해화학물질명", "제품명"))
        cas = _clean(_row_value(chem, "CAS 번호", "CAS No.", "화학물질식별번호"))

        legal_rows = direct.get(row_no, [])
        classes: list[str] = []
        designation_ids: list[str] = []
        legal_sources: list[str] = []

        for legal in legal_rows:
            material_class = _material_class(legal.get("hazard_category"))
            if material_class and material_class not in classes:
                classes.append(material_class)
            designation = _clean(legal.get("designation_id"))
            if designation and designation not in designation_ids:
                designation_ids.append(designation)
            source = _clean(legal.get("source_key")) or "CAP_QTY_APP2"
            if source not in legal_sources:
                legal_sources.append(source)

        if cas and cas in accident_cas and "사고대비물질" not in classes:
            classes.append("사고대비물질")
            legal_sources.append("CAP_QTY_APP3")

        if classes:
            row["물질구분"] = " / ".join(classes)
        if designation_ids:
            row["고유번호"] = " / ".join(designation_ids)

        row["법적분류 근거"] = " / ".join(dict.fromkeys(legal_sources))
        enriched.append(row)

        if row_no in broad_rows and not legal_rows:
            blockers.append(
                f"{name or cas or f'{row_no}행'}: 별표 2의 CAS 미기재 포괄 규제범위 후보이므로 "
                "범위 포함 여부 확인 전에는 고유번호·물질구분을 자동확정하지 않습니다."
            )
            continue

        if not classes:
            blockers.append(
                f"{name or cas or f'{row_no}행'}: 별표 2 직접 CAS 또는 별표 3 사고대비물질에서 "
                "별지 제6호 물질구분을 확정하지 못했습니다."
            )
        if not designation_ids:
            blockers.append(
                f"{name or cas or f'{row_no}행'}: 현행 별표 2의 고유번호를 확정하지 못했습니다. "
                "사고대비물질 별표 3 연번을 고유번호로 대신 쓰지 않습니다."
            )

    if app2_ready:
        messages.append("별지 제6호 고유번호는 현행 별표 2의 공식 '고유번호' 열에서만 가져옵니다.")
    messages.append("별표 3 사고대비물질 연번은 별지 제6호 고유번호로 변환하지 않습니다.")

    return CAPChemicalLegalData(
        rows=tuple(enriched),
        blockers=tuple(dict.fromkeys(blockers)),
        messages=tuple(dict.fromkeys(messages)),
        app2_ready=app2_ready,
    )
