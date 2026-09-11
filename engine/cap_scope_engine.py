from __future__ import annotations

"""Minimal CAP identity coverage beyond Appendix 3.

Only the parts needed for CAP/PSM are retained from the earlier project:
- exact CAS rows from approved current-law tables;
- broad legal scopes that do not end at one CAS;
- explicit exclusions and component-CAS candidates;
- fail-closed review when scope membership is uncertain.

No PubChem, RDKit, LLM matching, restricted/prohibited-substance modules, or
research validation framework is imported here.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import re

import pandas as pd

from .inventory import IntakeData
from .no_cas_scope import build_no_cas_scope_index, screen_no_cas_scopes


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPROVED_DIR = PROJECT_ROOT / "data" / "regulatory" / "approved"

APPROVED_SCOPE_FILES = {
    "CAP_QTY_APP1": APPROVED_DIR / "cap_qty_app1.csv",
    "CAP_QTY_APP2": APPROVED_DIR / "cap_qty_app2.csv",
}

IDENTITY_COLUMNS = {"scope_type", "direct_cas"}
CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")


@dataclass
class CAPScopeScreen:
    ready_keys: list[str] = field(default_factory=list)
    missing_keys: list[str] = field(default_factory=list)
    direct_hits: list[dict[str, Any]] = field(default_factory=list)
    candidate_rows: list[dict[str, Any]] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    review_required: bool = False
    messages: list[str] = field(default_factory=list)

    @property
    def fully_ready(self) -> bool:
        return not self.missing_keys and len(self.ready_keys) == len(APPROVED_SCOPE_FILES)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def _number(value: Any) -> float | None:
    text = _clean(value).replace(",", "")
    if not text or text in {"-", "–", "—"}:
        return None
    try:
        return float(text)
    except ValueError:
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(match.group()) if match else None


def _truthy(value: Any, default: bool = True) -> bool:
    text = _clean(value).lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "y", "예", "active"}


def _split_cas(value: Any) -> set[str]:
    return {
        token.strip()
        for token in re.split(r"[|;,]", _clean(value))
        if CAS_RE.fullmatch(token.strip())
    }


def _to_ton(value: Any, unit: Any) -> float | None:
    amount = _number(value)
    if amount is None:
        return None
    normalized = _clean(unit).lower().replace(" ", "")
    if normalized == "kg":
        return amount / 1000.0
    if normalized in {"ton", "t", "톤"}:
        return amount
    return None


def _band(max_ton: float, lowest: float | None, lower: float | None, upper: float | None) -> str:
    if upper is not None and max_ton >= upper:
        return "상위 규정수량 이상"
    if lower is not None and max_ton >= lower:
        return "하위 이상·상위 미만"
    if lowest is not None and max_ton >= lowest:
        return "최하위 이상·하위 미만"
    return "하위 규정수량 미만"


def _load_one(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception:
        return pd.DataFrame()
    if frame.empty or not IDENTITY_COLUMNS.issubset(frame.columns):
        return pd.DataFrame()
    return frame.copy()


def load_approved_scope_tables() -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Load only reviewed current-law Appendix 1/2 tables."""
    loaded: dict[str, pd.DataFrame] = {}
    missing: list[str] = []
    for key, path in APPROVED_SCOPE_FILES.items():
        frame = _load_one(path)
        if frame.empty:
            missing.append(key)
        else:
            loaded[key] = frame
    return loaded, missing


def _tag_table(frame: pd.DataFrame, key: str) -> pd.DataFrame:
    out = frame.copy()
    if "source_key" not in out.columns:
        out["source_key"] = key
    else:
        out["source_key"] = out["source_key"].replace("", key)
    if "regime" not in out.columns:
        out["regime"] = key
    return out


def screen_cap_scope_candidates_from_tables(
    intake: IntakeData,
    tables: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    if not tables:
        return pd.DataFrame()
    prepared = [_tag_table(frame, key) for key, frame in tables.items() if frame is not None and not frame.empty]
    if not prepared:
        return pd.DataFrame()
    master = pd.concat(prepared, ignore_index=True, sort=False)
    if "active" in master.columns:
        master = master[master["active"].map(lambda value: _truthy(value, default=True))].copy()
    scope_index = build_no_cas_scope_index(master)
    if scope_index.empty:
        return pd.DataFrame()
    return screen_no_cas_scopes(intake.chemicals, scope_index)


def screen_cap_direct_from_tables(
    intake: IntakeData,
    tables: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Compare exact CAS rows from approved Appendix 1/2 tables.

    This does not infer chemical family membership. It only uses CAS values that
    the reviewed parser explicitly marked as ``direct_cas``.
    """
    hits: list[dict[str, Any]] = []
    questions: list[str] = []
    blockers: list[str] = []

    for source_key, raw in tables.items():
        if raw is None or raw.empty:
            continue
        table = _tag_table(raw, source_key)
        if "active" in table.columns:
            table = table[table["active"].map(lambda value: _truthy(value, default=True))].copy()

        for inv_idx, item in intake.chemicals.iterrows():
            row_no = inv_idx + 1
            cas = _clean(item.get("CAS No."))
            if not CAS_RE.fullmatch(cas):
                continue
            matched = table[table["direct_cas"].map(lambda value: cas in _split_cas(value))].copy()
            if matched.empty:
                continue

            # The current Appendix 2 contains special '용액' rows for some CAS.
            # Until that condition is answered, using either the base or solution
            # quantities automatically would be unsafe.
            if "hazard_category" in matched.columns and matched["hazard_category"].astype(str).eq("용액").any():
                product = _clean(item.get("제품명")) or cas
                questions.append(
                    f"{product}: 현행 화사계 별표 2에 동일 CAS의 '용액' 특수 규정수량이 있습니다. "
                    "이번 취급물질이 해당 용액 조건인지 확인해 주세요."
                )
                blockers.append(f"별표 2 용액 특수조건 미확인: {row_no}행({cas})")
                continue

            pct = _number(item.get("함량(%)"))
            holding = _to_ton(item.get("최대 동시보유량(알면 입력)"), item.get("수량 단위"))
            if holding is None:
                questions.append(
                    f"화학물질 목록 {row_no}행({cas})의 화사계 최대 동시보유 질량(kg 또는 ton)을 확인해 주세요."
                )
                blockers.append(f"화사계 최대보유량 미확인: {row_no}행")
                continue

            for _, legal in matched.iterrows():
                threshold = _number(legal.get("content_threshold_pct"))
                hazard = _clean(legal.get("hazard_category"))
                if threshold is not None:
                    if pct is None:
                        questions.append(
                            f"화학물질 목록 {row_no}행({cas})의 함량(%)을 확인해 주세요. "
                            f"별표 기준은 {threshold:g}% 이상입니다."
                        )
                        blockers.append(f"별표 1·2 직접 CAS 매칭물질 함량 미확인: {row_no}행")
                        continue
                    if pct < threshold:
                        continue

                lowest = _number(legal.get("lowest_quantity_ton"))
                lower = _number(legal.get("lower_quantity_ton"))
                upper = _number(legal.get("upper_quantity_ton"))
                if lower is None:
                    blockers.append(
                        f"{source_key} {legal.get('record_key', legal.get('item_no', '-'))} 하위 규정수량 확인 필요"
                    )
                    continue

                hits.append(
                    {
                        "source_key": source_key,
                        "row_no": row_no,
                        "product_name": _clean(item.get("제품명")),
                        "cas": cas,
                        "item_no": _clean(legal.get("item_no")),
                        "designation_id": _clean(legal.get("designation_id")),
                        "legal_substance": _clean(legal.get("substance_name")),
                        "hazard_category": hazard,
                        "content_threshold_pct": threshold,
                        "max_holding_ton": round(holding, 8),
                        "lowest_quantity_ton": lowest,
                        "lower_quantity_ton": lower,
                        "upper_quantity_ton": upper,
                        "quantity_band": _band(holding, lowest, lower, upper),
                        "basis": (
                            f"직접 CAS / 함량 {pct:g}%" if pct is not None else "직접 CAS"
                        ) + f" / 최대동시보유량 {holding:g} ton",
                    }
                )

    frame = pd.DataFrame(hits)
    if not frame.empty:
        frame.drop_duplicates(
            subset=["source_key", "row_no", "cas", "item_no", "hazard_category", "lower_quantity_ton", "upper_quantity_ton"],
            inplace=True,
        )
        frame.reset_index(drop=True, inplace=True)
    return frame, list(dict.fromkeys(questions)), list(dict.fromkeys(blockers))


def assess_cap_scope(intake: IntakeData) -> CAPScopeScreen:
    tables, missing = load_approved_scope_tables()
    candidates = screen_cap_scope_candidates_from_tables(intake, tables)
    direct_hits, questions, blockers = screen_cap_direct_from_tables(intake, tables)
    messages: list[str] = []

    if missing:
        messages.append(
            "화사계 별표 1·2의 물질범위 검증이 아직 완성되지 않아, 일부 CAS 미매칭만으로 비대상을 확정하지 않습니다."
        )
    if not direct_hits.empty:
        messages.append(f"화사계 별표 1·2의 승인된 직접 CAS 규칙에서 {len(direct_hits)}개 적용행을 확인했습니다.")
    if not candidates.empty:
        messages.append(
            f"CAS 하나로 특정되지 않는 화사계 규제범위 후보 {len(candidates)}건을 찾았습니다. "
            "이 후보는 이름 유사성만으로 자동확정하지 않고 범위 포함 여부를 확인합니다."
        )

    return CAPScopeScreen(
        ready_keys=sorted(tables.keys()),
        missing_keys=missing,
        direct_hits=direct_hits.to_dict("records") if not direct_hits.empty else [],
        candidate_rows=candidates.to_dict("records") if not candidates.empty else [],
        questions=questions,
        blockers=blockers,
        review_required=not candidates.empty,
        messages=messages,
    )
