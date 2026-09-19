from __future__ import annotations

"""작성 시작하기: 사업장·물질 몇 가지만 받아 법정 대상 여부를 판정하고 작성 프로젝트를 만든다.

예전에는 판정진단(엑셀 업로드) → 작성범위 선택을 거쳐야 작성 화면에 들어올 수 있었다. 여기서는 같은 Stage 1
판정 엔진(assess_stage1_from_workbook)을 그대로 쓰되 입력을 화면 표로 받는다. 판정 결과 화학사고예방관리계획서 작성·제출 대상(1군·2군)이거나
공정안전보고서 제출 대상일 때만 프로젝트를 만들고, 대상인 문서를 작성 범위로 확정한다(법적 판정을 우회하지 않는다).
"""

from dataclasses import asdict, dataclass, field, is_dataclass
import hashlib
import json
from typing import Any, Callable, Mapping

import pandas as pd

from ..inventory import IntakeData, validate_intake
from ..stage1_workbook import assess_stage1_from_workbook
from .project import Stage2Project, create_project_from_stage1_snapshot

BUSINESS_FIELDS = ("사업장명", "사업장 주소", "업종 또는 주요 생산품")
CHEMICAL_INPUT_COLUMNS = ("제품명", "CAS No.", "함량(%)", "최대 동시보유량(ton)")
HANDLING_DEFAULT = "저장·사용"
UNIT = "ton"


@dataclass(frozen=True)
class StartOutcome:
    status: str  # STARTED / NOT_REQUIRED / REQUEST / SYSTEM / INVALID
    messages: tuple[str, ...] = field(default_factory=tuple)
    project: Stage2Project | None = None
    cap_status: str = ""
    cap_explanation: str = ""
    psm_status: str = ""


def _clean(value: object) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value).strip()


def _number(value: object) -> float | None:
    text = _clean(value).replace(",", "")
    try:
        return float(text) if text else None
    except ValueError:
        return None


def chemical_frame(rows: list[Mapping[str, Any]]) -> pd.DataFrame:
    """Map the four typed columns onto the Stage 1 intake columns; blank rows are dropped."""
    records = []
    for row in rows:
        name, cas = _clean(row.get("제품명")), _clean(row.get("CAS No."))
        if not name and not cas:
            continue
        records.append({
            "제품명": name or cas, "CAS No.": cas, "물질명(알면 입력)": name,
            "함량(%)": _number(row.get("함량(%)")), "취급형태": HANDLING_DEFAULT, "수량 단위": UNIT,
            "최대 동시보유량(알면 입력)": _number(row.get("최대 동시보유량(ton)")),
        })
    return pd.DataFrame(records, columns=[
        "제품명", "CAS No.", "물질명(알면 입력)", "함량(%)", "취급형태", "수량 단위", "최대 동시보유량(알면 입력)"])


def build_intake(business: Mapping[str, Any], rows: list[Mapping[str, Any]]) -> IntakeData:
    frame = chemical_frame(rows)
    fingerprint = hashlib.sha256(
        json.dumps({"business": dict(business), "chemicals": frame.astype(object).where(frame.notna(), None).to_dict("records")},
                   ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return IntakeData(business={k: _clean(business.get(k)) for k in BUSINESS_FIELDS}, chemicals=frame, documents={},
                      source_fingerprint=fingerprint)


def start(business: Mapping[str, Any], rows: list[Mapping[str, Any]], *,
          assess: Callable[[IntakeData], Any] = assess_stage1_from_workbook) -> StartOutcome:
    intake = build_intake(business, rows)
    issues = validate_intake(intake)
    if issues:
        return StartOutcome("INVALID", tuple(issues))
    decision = assess(intake)
    cap_status = str(getattr(decision, "cap_status", ""))
    base = dict(cap_status=cap_status, cap_explanation=str(getattr(decision, "cap_explanation", "")),
                psm_status=str(getattr(decision, "psm_status", "")))
    if getattr(decision, "system_blockers", None):
        return StartOutcome("SYSTEM", tuple(decision.system_blockers), **base)
    if getattr(decision, "company_requests", None):
        return StartOutcome("REQUEST", tuple(decision.company_requests), **base)
    records = intake.chemicals.astype(object).where(intake.chemicals.notna(), None).to_dict("records")
    for record in records:
        record["물질명"] = record.get("물질명(알면 입력)") or record.get("제품명")
    snapshot = {
        "source_fingerprint": intake.source_fingerprint, "business": dict(intake.business), "documents": {},
        "chemicals": records, "mixture_components": [], "facilities": [],
        "decision": asdict(decision) if is_dataclass(decision) else dict(vars(decision)),
    }
    project = create_project_from_stage1_snapshot(snapshot)
    psm_target, cap_target = project.psm_required is True, project.cap_required is True
    if not psm_target and not cap_target:
        return StartOutcome("NOT_REQUIRED", (), **base)
    project.set_authoring_scope(psm_selected=psm_target, cap_selected=cap_target)
    return StartOutcome("STARTED", (), project, **base)
