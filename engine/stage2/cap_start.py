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
from . import cap_judgement
from .project import Stage2Project, create_project_from_stage1_snapshot

BUSINESS_FIELDS = ("사업장명", "사업장 주소", "업종 또는 주요 생산품")
CHEMICAL_INPUT_COLUMNS = ("제품명", "CAS No.", "함량(%)", "최대 동시보유량(ton)")
# 양식에서 함께 받는 판정용 선택 열(cap_chemical_upload.EXTRA_COLUMNS와 같다). 값이 하나라도 있을 때만 판정 입력에 넣는다.
EXTRA_INPUT_COLUMNS = (
    "상온·상압 액체 여부(해당 시)", "최대 제조·사용량", "최대 저장량", "최대보유량 법정 산정 여부",
    "SDS 제2항 유해성·위험성 분류(선택 입력)",
)
HANDLING_DEFAULT = "저장·사용"
UNIT = "ton"


@dataclass(frozen=True)
class StartOutcome:
    status: str  # STARTED / PENDING(판정 대기 사업장을 만듦) / NOT_REQUIRED / SYSTEM / INVALID
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
        for column in EXTRA_INPUT_COLUMNS:
            records[-1][column] = _clean(row.get(column))
    base = ["제품명", "CAS No.", "물질명(알면 입력)", "함량(%)", "취급형태", "수량 단위", "최대 동시보유량(알면 입력)"]
    used = [c for c in EXTRA_INPUT_COLUMNS if any(r.get(c) for r in records)]
    return pd.DataFrame(records, columns=base + used)


def build_intake(business: Mapping[str, Any], rows: list[Mapping[str, Any]]) -> IntakeData:
    frame = chemical_frame(rows)
    fingerprint = hashlib.sha256(
        json.dumps({"business": dict(business), "chemicals": frame.astype(object).where(frame.notna(), None).to_dict("records")},
                   ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return IntakeData(business={k: _clean(business.get(k)) for k in BUSINESS_FIELDS}, chemicals=frame, documents={},
                      source_fingerprint=fingerprint)


def _records(intake: IntakeData) -> list[dict[str, Any]]:
    records = intake.chemicals.astype(object).where(intake.chemicals.notna(), None).to_dict("records")
    for record in records:
        record["물질명"] = record.get("물질명(알면 입력)") or record.get("제품명")
    return records


def _pending(intake: IntakeData, messages: tuple[str, ...], **base: str) -> StartOutcome:
    """판정을 미룬 채 사업장을 만든다. 최대보유량은 별지 제1호 시설 입력으로 계산한 뒤, 판정에 필요한 질문에 답하고 판정한다."""
    snapshot = {"source_fingerprint": intake.source_fingerprint, "business": dict(intake.business), "documents": {},
                "chemicals": _records(intake), "mixture_components": [], "facilities": [], "decision": {}}
    project = create_project_from_stage1_snapshot(snapshot)
    project.stage1_snapshot[cap_judgement.PENDING_KEY] = True
    return StartOutcome("PENDING", messages, project, **base)


def start(business: Mapping[str, Any], rows: list[Mapping[str, Any]], *,
          assess: Callable[[IntakeData], Any] = assess_stage1_from_workbook) -> StartOutcome:
    """사업장을 만든다. 판정에 필요한 정보가 다 있으면 바로 판정하고, 부족하면(최대보유량을 모르거나 판정에 필요한 확인 사항이
    남았으면) 판정을 미룬 사업장을 만들어 별지 작성 화면에서 이어 가게 한다."""
    intake = build_intake(business, rows)
    issues = validate_intake(intake)
    quantity_issues = [i for i in issues if cap_judgement.QUANTITY_ISSUE in i]
    other_issues = [i for i in issues if cap_judgement.QUANTITY_ISSUE not in i]
    if other_issues:
        return StartOutcome("INVALID", tuple(other_issues))
    if quantity_issues:
        return _pending(intake, ("최대보유량을 모르는 물질이 있어 법정 대상 판정을 뒤로 미뤘습니다. 별지 제1호에서 시설을 입력하면 "
                                 "최대보유량이 계산됩니다. 그 뒤 '법정 대상 판정하기'를 눌러 주세요.",))
    decision = assess(intake)
    cap_status = str(getattr(decision, "cap_status", ""))
    base = dict(cap_status=cap_status, cap_explanation=str(getattr(decision, "cap_explanation", "")),
                psm_status=str(getattr(decision, "psm_status", "")))
    if getattr(decision, "system_blockers", None):
        return StartOutcome("SYSTEM", tuple(decision.system_blockers), **base)
    if getattr(decision, "company_requests", None):
        return _pending(intake, tuple(decision.company_requests), **base)
    snapshot = {
        "source_fingerprint": intake.source_fingerprint, "business": dict(intake.business), "documents": {},
        "chemicals": _records(intake), "mixture_components": [], "facilities": [],
        "decision": asdict(decision) if is_dataclass(decision) else dict(vars(decision)),
    }
    project = create_project_from_stage1_snapshot(snapshot)
    psm_target, cap_target = project.psm_required is True, project.cap_required is True
    if not psm_target and not cap_target:
        return StartOutcome("NOT_REQUIRED", (), **base)
    project.set_authoring_scope(psm_selected=psm_target, cap_selected=cap_target)
    return StartOutcome("STARTED", (), project, **base)
