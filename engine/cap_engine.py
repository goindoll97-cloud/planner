from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .cap_app1_engine import load_approved_app1
from .cap_scope_engine import assess_cap_scope
from .inventory import IntakeData

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPROVED_CAP3_DB = PROJECT_ROOT / "data" / "regulatory" / "approved" / "cap_qty_app3.csv"
CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")


@dataclass
class CAPHit:
    row_no: int
    product_name: str
    cas: str
    legal_item_no: int
    legal_substance: str
    variant_type: str
    max_holding_ton: float
    lowest_quantity_ton: float | None
    lower_quantity_ton: float | None
    upper_quantity_ton: float | None
    quantity_band: str
    basis: str


@dataclass
class CAPAssessment:
    status: str
    label: str
    hits: list[CAPHit] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    db_ready: bool = False
    partial_only: bool = True
    scope_direct_hits: list[dict[str, Any]] = field(default_factory=list)
    scope_candidates: list[dict[str, Any]] = field(default_factory=list)
    scope_ready_keys: list[str] = field(default_factory=list)
    scope_missing_keys: list[str] = field(default_factory=list)
    scope_review_required: bool = False
    app1_ready: bool = False
    app1_required_rows: list[dict[str, Any]] = field(default_factory=list)


def _clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _number(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        m = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(m.group()) if m else None


def _valid_pct(value: Any) -> float | None:
    pct = _number(value)
    if pct is None or pct < 0 or pct > 100:
        return None
    return pct


def _to_ton(value: Any, unit: Any) -> float | None:
    amount = _number(value)
    if amount is None:
        return None
    norm = _clean(unit).lower().replace(" ", "")
    if norm == "kg":
        return amount / 1000.0
    if norm in {"ton", "t", "톤"}:
        return amount
    return None


def _load_db() -> pd.DataFrame:
    if not APPROVED_CAP3_DB.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(APPROVED_CAP3_DB)
    except Exception:
        return pd.DataFrame()
    required = {
        "record_key", "item_no", "variant_type", "substance_name", "cas_list",
        "content_threshold_pct", "lowest_quantity_ton", "lower_quantity_ton", "upper_quantity_ton",
    }
    if not required.issubset(df.columns):
        return pd.DataFrame()
    for col in ["item_no", "content_threshold_pct", "lowest_quantity_ton", "lower_quantity_ton", "upper_quantity_ton"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _lookup(df: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for _, row in df.iterrows():
        for cas in str(row.get("cas_list", "")).split("|"):
            cas = cas.strip()
            if CAS_RE.fullmatch(cas):
                out.setdefault(cas, []).append(row.to_dict())
    return out


def _band(max_ton: float, lowest: float | None, lower: float | None, upper: float | None) -> str:
    if upper is not None and max_ton >= upper:
        return "상위 규정수량 이상"
    if lower is not None and max_ton >= lower:
        return "하위 이상·상위 미만"
    if lowest is not None and max_ton >= lowest:
        return "최하위 이상·하위 미만"
    return "하위 규정수량 미만"


def assess_cap(intake: IntakeData) -> CAPAssessment:
    """Screen CAP using the current-law quantity-table priority.

    Quantity-source order is fail-closed and material-specific:
    1) Appendix 3 accident-preparedness substances;
    2) Appendix 2 substance-specific/broad legal scopes;
    3) Appendix 1 GHS hazard groups only as the fallback.

    Appendix 1 is never treated as a CAS table. Until verified SDS hazard-group
    data are supplied, an Appendix-1 fallback row remains a blocker rather than
    being guessed from a chemical name or CAS.
    """
    scope = assess_cap_scope(intake)
    app1_db = load_approved_app1()
    app1_ready = not app1_db.empty
    db = _load_db()

    if db.empty:
        blockers = ["사고대비물질 별표 3 승인 DB 필요", *scope.blockers]
        if scope.missing_keys:
            blockers.append("화사계 별표 2 물질범위 DB 미완성")
        if not app1_ready:
            blockers.append("화사계 별표 1 유해·위험성 그룹 DB 미완성")
        if scope.review_required:
            blockers.append(f"CAS 미기재 포괄 규제범위 검토대상 {len(scope.candidate_rows)}건 확인 필요")
        return CAPAssessment(
            status="DB_NOT_READY",
            label="화사계 별표 3 DB 승인 필요",
            messages=[
                "사고대비물질 별표 3 승인 DB가 없어 화사계 규정수량 대조를 시작할 수 없습니다.",
                *scope.messages,
            ],
            questions=scope.questions,
            blockers=list(dict.fromkeys(blockers)),
            db_ready=False,
            scope_direct_hits=scope.direct_hits,
            scope_candidates=scope.candidate_rows,
            scope_ready_keys=scope.ready_keys,
            scope_missing_keys=scope.missing_keys,
            scope_review_required=scope.review_required,
            app1_ready=app1_ready,
        )

    assessment = CAPAssessment(
        status="PARTIAL_SCREEN",
        label="화사계 부분검토",
        db_ready=True,
        partial_only=True,
        scope_direct_hits=list(scope.direct_hits),
        scope_candidates=list(scope.candidate_rows),
        scope_ready_keys=scope.ready_keys,
        scope_missing_keys=scope.missing_keys,
        scope_review_required=scope.review_required,
        questions=list(scope.questions),
        blockers=list(scope.blockers),
        messages=list(scope.messages),
        app1_ready=app1_ready,
    )
    lookup = _lookup(db)
    app3_priority_rows: set[int] = set()

    for idx, row in intake.chemicals.iterrows():
        row_no = idx + 1
        product = _clean(row.get("제품명"))
        cas = _clean(row.get("CAS No."))
        if not CAS_RE.fullmatch(cas):
            assessment.blockers.append(f"화학물질 목록 {row_no}행의 CAS 식별 확인 필요")
            continue
        legal_rows = lookup.get(cas, [])
        if not legal_rows:
            continue

        pct = _valid_pct(row.get("함량(%)"))
        if pct is None:
            assessment.questions.append(f"화학물질 목록 {row_no}행({product or cas})의 함량(%)을 확인해 주세요.")
            assessment.blockers.append(f"별표 3 매칭물질 함량 미확인: {row_no}행")
            app3_priority_rows.add(row_no)
            continue

        base_rows = [r for r in legal_rows if str(r.get("variant_type", "BASE")) == "BASE"]
        if not base_rows:
            assessment.blockers.append(f"별표 3 기본행 누락: CAS {cas}")
            app3_priority_rows.add(row_no)
            continue
        base = base_rows[0]
        minimum = _number(base.get("content_threshold_pct"))
        if minimum is not None and pct < minimum:
            assessment.messages.append(
                f"{product or cas}: 함량 {pct:g}%가 별표 3 적용기준 {minimum:g}% 미만이어서 사고대비물질 규정수량 비교에서는 제외했습니다."
            )
            continue

        # Once Appendix 3 applies to this inventory row, Appendix 2/1 must not
        # override it even if the quantity/state condition still needs follow-up.
        app3_priority_rows.add(row_no)

        holding_ton = _to_ton(row.get("최대 동시보유량(알면 입력)"), row.get("수량 단위"))
        if holding_ton is None:
            unit = _clean(row.get("수량 단위"))
            if unit.lower().replace(" ", "") in {"l", "m3", "㎥"}:
                assessment.questions.append(
                    f"화학물질 목록 {row_no}행({product or cas})은 부피단위입니다. 화사계 최대보유량 비교를 위해 최대 동시보유 질량(kg 또는 ton)이나 밀도를 확인해 주세요."
                )
            else:
                assessment.questions.append(
                    f"화학물질 목록 {row_no}행({product or cas})의 최대 동시보유량을 확인해 주세요. 화사계는 사업장 내 순간 최대보유량을 기준으로 비교합니다."
                )
            assessment.blockers.append(f"화사계 최대보유량 미확인: {row_no}행")
            continue

        chosen = base
        item_no = int(float(base.get("item_no")))
        variants = [r for r in legal_rows if str(r.get("variant_type", "BASE")) != "BASE"]

        if item_no == 46:
            gt70 = [r for r in variants if str(r.get("variant_type")) == "CONCENTRATION_GT_70"]
            if pct > 70 and gt70:
                chosen = gt70[0]
        elif item_no in {42, 43, 44} and any(str(r.get("variant_type")) == "LIQUID_AT_AMBIENT" for r in variants):
            assessment.questions.append(
                f"{product or cas}: 상온·상압에서 액체 상태인지 확인해 주세요. 별표 3 제{item_no}호는 액체인 경우 별도 규정수량을 적용합니다."
            )
            assessment.blockers.append(f"별표 3 제{item_no}호 성상조건 미확인: {row_no}행")
            continue

        lowest = _number(chosen.get("lowest_quantity_ton"))
        lower = _number(chosen.get("lower_quantity_ton"))
        upper = _number(chosen.get("upper_quantity_ton"))
        if lower is None or upper is None:
            assessment.blockers.append(f"별표 3 제{item_no}호 규정수량 값 미확인")
            continue

        variant_type = str(chosen.get("variant_type", "BASE"))
        basis = f"별표 3 우선 적용 / 함량 {pct:g}% / 사용자 입력 최대동시보유량 {holding_ton:g} ton"
        if variant_type == "CONCENTRATION_GT_70":
            basis += " / 질산 70% 초과 특수행 적용"

        assessment.hits.append(
            CAPHit(
                row_no=row_no,
                product_name=product,
                cas=cas,
                legal_item_no=item_no,
                legal_substance=_clean(chosen.get("substance_name")),
                variant_type=variant_type,
                max_holding_ton=round(holding_ton, 8),
                lowest_quantity_ton=lowest,
                lower_quantity_ton=lower,
                upper_quantity_ton=upper,
                quantity_band=_band(holding_ton, lowest, lower, upper),
                basis=basis,
            )
        )

    # Appendix 3 has priority over Appendix 2 on a material-by-material basis.
    assessment.scope_direct_hits = [
        hit for hit in assessment.scope_direct_hits
        if int(hit.get("row_no", -1) or -1) not in app3_priority_rows
    ]
    assessment.scope_candidates = [
        hit for hit in assessment.scope_candidates
        if int(hit.get("row_no", -1) or -1) not in app3_priority_rows
    ]
    assessment.scope_review_required = bool(assessment.scope_candidates)

    app2_priority_rows = {
        int(hit.get("row_no")) for hit in assessment.scope_direct_hits
        if str(hit.get("row_no", "")).isdigit()
    }
    app2_priority_rows.update(
        int(hit.get("row_no")) for hit in assessment.scope_candidates
        if str(hit.get("row_no", "")).isdigit()
    )

    # Appendix 1 is the fallback. Do not guess GHS groups from CAS/name. Collect
    # unresolved rows for a later SDS-based input step instead of auto-deciding.
    fallback_rows: list[dict[str, Any]] = []
    for idx, row in intake.chemicals.iterrows():
        row_no = idx + 1
        if row_no in app3_priority_rows or row_no in app2_priority_rows:
            continue
        fallback_rows.append(
            {
                "row_no": row_no,
                "product_name": _clean(row.get("제품명")),
                "cas": _clean(row.get("CAS No.")),
            }
        )
    assessment.app1_required_rows = fallback_rows

    if fallback_rows:
        if app1_ready:
            assessment.blockers.append(
                f"별표 2·3 미적용 물질 {len(fallback_rows)}개 물질은 별표 1 적용 여부를 위해 SDS 제2항 유해성·위험성 분류 확인 필요"
            )
            assessment.messages.append(
                "별표 1은 CAS 검색표가 아니므로 별표 2·3이 적용되지 않는 물질에 한해 SDS 유해성·위험성 그룹을 확인한 뒤 적용합니다."
            )
        else:
            assessment.blockers.append("화사계 별표 1 유해·위험성 그룹 승인 DB 필요")

    app3_upper = any(h.quantity_band == "상위 규정수량 이상" for h in assessment.hits)
    app3_lower = any(h.quantity_band == "하위 이상·상위 미만" for h in assessment.hits)
    app2_upper = any(str(h.get("quantity_band")) == "상위 규정수량 이상" for h in assessment.scope_direct_hits)
    app2_lower = any(str(h.get("quantity_band")) == "하위 이상·상위 미만" for h in assessment.scope_direct_hits)

    if app3_upper or app2_upper:
        assessment.label = "최대보유량이 상위 규정수량 이상"
        assessment.status = "UPPER_CANDIDATE"
        assessment.messages.append(
            "승인된 화사계 규정수량 표에서 상위 규정수량 이상 조건이 확인되었습니다. 별표 4와 면제·군 분류 규칙 검증 전에는 1군으로 확정하지 않습니다."
        )
    elif app3_lower or app2_lower:
        assessment.label = "최대보유량이 하위 규정수량 이상·상위 규정수량 미만"
        assessment.status = "LOWER_CANDIDATE"
        assessment.messages.append(
            "승인된 화사계 규정수량 표에서 하위 이상·상위 미만 조건이 확인되었습니다. 별표 4와 면제·군 분류 규칙 검증 전에는 2군으로 확정하지 않습니다."
        )
    elif assessment.scope_review_required:
        assessment.label = "화사계 포괄범위 검토 필요"
        assessment.status = "SCOPE_REVIEW_REQUIRED"
        assessment.messages.append(
            "직접 CAS로 끝나지 않는 별표 2 규제범위 검토대상이 있어 CAS 미매칭 또는 하위 규정수량 미만만으로 작성면제를 확정하지 않습니다."
        )
    elif assessment.hits or assessment.scope_direct_hits:
        assessment.label = "확인된 유해화학물질의 최대보유량이 하위 규정수량 미만"
        assessment.status = "BELOW_LOWER_PARTIAL"
    else:
        assessment.label = "화사계 추가검토 필요"
        assessment.status = "NO_CONFIRMED_MATCH_PARTIAL"

    if assessment.scope_review_required:
        assessment.blockers.append(
            f"CAS 미기재 별표 2 포괄 규제범위 검토대상 {len(assessment.scope_candidates)}건의 범위 포함 여부 확인 필요"
        )
    if assessment.scope_missing_keys:
        assessment.blockers.append(
            "화사계 별표 2 물질범위 DB가 승인되지 않아 전체 작성면제 판정 금지"
        )
    assessment.blockers.append("화사계 별표 4 최대보유량 산정규칙 및 작성면제·작성수준 규칙 검증 전 최종 1군/2군/작성면제 확정 금지")
    assessment.questions = list(dict.fromkeys(q for q in assessment.questions if q))
    assessment.blockers = list(dict.fromkeys(b for b in assessment.blockers if b))
    assessment.messages = list(dict.fromkeys(m for m in assessment.messages if m))
    return assessment
