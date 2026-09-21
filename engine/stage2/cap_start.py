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

from ..inventory import IntakeData, MIXTURE_COMPONENT_COLUMNS, MIXTURE_FLAG_COLUMN, validate_intake
from ..stage1_workbook import assess_stage1_from_workbook
from . import cap_judgement
from .project import Stage2Project, create_project_from_stage1_snapshot

BUSINESS_FIELDS = ("사업장명", "사업장 주소", "업종 또는 주요 생산품", "한국표준산업분류(KSIC) 코드")
MATERIAL_TYPE_COLUMN = "단일물질/혼합물"
# 신입사원이 처음 입력하는 최소 물질정보. 단일물질과 혼합제품을 제품 단위로 한 줄씩 적고,
# 혼합제품의 구성성분 CAS·함량은 별도 구성성분 파일 또는 후속 질문에서만 받는다.
CHEMICAL_INPUT_COLUMNS = ("제품명", MATERIAL_TYPE_COLUMN, "CAS No.", "최대 제조·사용량", "최대 저장량", "단위")
LEGACY_CONTENT_COLUMN = "함량(%)"
LEGACY_MIXTURE_COLUMN = MIXTURE_FLAG_COLUMN
LEGACY_MAX_HOLDING_COLUMN = "최대 동시보유량(ton)"
# 전문적인 판정 보조값은 초기 표에서 받지 않고, 실제 판정에 필요할 때만 후속 질문으로 받는다.
EXTRA_INPUT_COLUMNS = (
    "상온·상압 액체 여부(해당 시)", "최대보유량 법정 산정 여부",
    "SDS 제2항 유해성·위험성 분류(선택 입력)",
)
HANDLING_DEFAULT = "저장·사용"
UNIT = "ton"
INPUT_UNIT_OPTIONS = ("kg", "ton")


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


def _quantity_to_ton(value: object, unit: object) -> float | None:
    """kg/ton 입력을 Stage 1 공통 단위인 ton으로 정규화한다."""
    amount = _number(value)
    if amount is None:
        return None
    norm = _clean(unit).lower().replace(" ", "")
    if norm in {"kg", "㎏"}:
        return amount / 1000.0
    if norm in {"ton", "t", "톤"}:
        return amount
    return None


def chemical_frame(rows: list[Mapping[str, Any]]) -> pd.DataFrame:
    """Map the minimal typed columns onto the Stage 1 intake columns.

    신규 입력은 제조·사용량/저장량과 kg·ton 단위만 받는다. 기존 9열 파일이나
    저장 데이터에 있던 최대 동시보유량·전문 입력열은 계속 읽어 하위호환한다.
    """
    records = []
    for row in rows:
        name, cas = _clean(row.get("제품명")), _clean(row.get("CAS No."))
        if not name and not cas:
            continue
        input_unit = _clean(row.get("단위") or row.get("수량 단위")) or UNIT
        kind = _clean(row.get(MATERIAL_TYPE_COLUMN))
        legacy_mixture = _clean(row.get(LEGACY_MIXTURE_COLUMN))
        # 화면에서 사용자가 단일/혼합물을 명시적으로 골랐다면 과거 파일의 숨은 값보다 우선한다.
        if kind == "혼합물":
            mixture = "Y"
        elif kind == "단일물질":
            mixture = "N"
        else:
            mixture = legacy_mixture
        content = _number(row.get(LEGACY_CONTENT_COLUMN))
        if mixture == "N" and content is None:
            content = 100.0
        # 혼합제품 자체의 CAS는 법적 식별키로 사용하지 않는다. 구성성분 CAS는 별도 파일에서 받는다.
        if mixture == "Y":
            cas = ""
        records.append({
            "제품명": name or cas,
            "CAS No.": cas,
            "물질명(알면 입력)": name,
            "함량(%)": content,
            MIXTURE_FLAG_COLUMN: mixture,
            "취급형태": HANDLING_DEFAULT,
            # 판정 엔진은 공통적으로 ton 값을 받는다.
            "수량 단위": UNIT,
            "최대 제조·사용량": _quantity_to_ton(row.get("최대 제조·사용량"), input_unit),
            "최대 저장량": _quantity_to_ton(row.get("최대 저장량"), input_unit),
            # 이전 양식에서 이미 ton으로 저장한 값은 그대로 유지한다.
            "최대 동시보유량(알면 입력)": _number(row.get(LEGACY_MAX_HOLDING_COLUMN)),
        })
        for column in EXTRA_INPUT_COLUMNS:
            records[-1][column] = _clean(row.get(column))
    base = [
        "제품명", "CAS No.", "물질명(알면 입력)", "함량(%)", MIXTURE_FLAG_COLUMN, "취급형태",
        "최대 제조·사용량", "최대 저장량", "수량 단위", "최대 동시보유량(알면 입력)",
    ]
    used = [c for c in EXTRA_INPUT_COLUMNS if any(r.get(c) for r in records)]
    return pd.DataFrame(records, columns=base + used)


def component_records(frame: pd.DataFrame, components: list[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """업로드한 혼합물 성분을 판정 입력 형식으로 바꾼다. 제품목록행번호는 물질 표에서의 위치(1부터)이고 제품명으로 찾는다."""
    if not components:
        return []
    position = {_clean(name): index + 1 for index, name in enumerate(frame["제품명"].tolist())}
    out = []
    for component in components:
        parent = position.get(_clean(component.get("제품명")))
        if not parent:
            continue  # 표에서 지운 제품의 성분은 버린다
        out.append({
            "적용여부": "Y", "제품목록행번호": parent, "제품명(확인용)": _clean(component.get("제품명")),
            "구성성분명": _clean(component.get("구성성분명")), "CAS No.": _clean(component.get("CAS No.")),
            "함량(%)": _clean(component.get("함량(%)")),
            "SDS 제3항 근거": _clean(component.get("SDS 제3항 근거")) or "회사 입력 파일 — 제품 SDS 제3항과 대조 확인",
        })
    return out


def build_intake(business: Mapping[str, Any], rows: list[Mapping[str, Any]],
                 components: list[Mapping[str, Any]] | None = None) -> IntakeData:
    frame = chemical_frame(rows)
    parts = component_records(frame, components)
    fingerprint = hashlib.sha256(
        json.dumps({"business": dict(business), "chemicals": frame.astype(object).where(frame.notna(), None).to_dict("records"),
                    "components": parts},
                   ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return IntakeData(business={k: _clean(business.get(k)) for k in BUSINESS_FIELDS}, chemicals=frame, documents={},
                      source_fingerprint=fingerprint,
                      mixture_components=pd.DataFrame(parts, columns=MIXTURE_COMPONENT_COLUMNS))


def _records(intake: IntakeData) -> list[dict[str, Any]]:
    records = intake.chemicals.astype(object).where(intake.chemicals.notna(), None).to_dict("records")
    for record in records:
        record["물질명"] = record.get("물질명(알면 입력)") or record.get("제품명")
    return records


def _component_dicts(intake: IntakeData) -> list[dict[str, Any]]:
    frame = intake.mixture_components
    if frame is None or frame.empty:
        return []
    return frame.astype(object).where(frame.notna(), None).to_dict("records")


def _business_args(business: Mapping[str, Any]) -> dict[str, str]:
    return {
        "name": _clean(business.get("사업장명")),
        "address": _clean(business.get("사업장 주소")),
        "industry": _clean(business.get("업종 또는 주요 생산품")),
        "ksic": _clean(business.get("한국표준산업분류(KSIC) 코드")),
    }


def _pending(intake: IntakeData, messages: tuple[str, ...], **base: str) -> StartOutcome:
    """판정을 미룬 채 사업장을 만든다. 최대보유량은 별지 제1호 시설 입력으로 계산한 뒤, 판정에 필요한 질문에 답하고 판정한다."""
    snapshot = {"source_fingerprint": intake.source_fingerprint, "business": dict(intake.business), "documents": {},
                "chemicals": _records(intake), "mixture_components": _component_dicts(intake), "facilities": [], "decision": {}}
    project = create_project_from_stage1_snapshot(snapshot)
    cap_judgement.save_business(project, **_business_args(intake.business))
    project.stage1_snapshot[cap_judgement.PENDING_KEY] = True
    return StartOutcome("PENDING", messages, project, **base)


def start(business: Mapping[str, Any], rows: list[Mapping[str, Any]], *,
          components: list[Mapping[str, Any]] | None = None,
          assess: Callable[[IntakeData], Any] = assess_stage1_from_workbook) -> StartOutcome:
    """사업장을 만든다. 판정에 필요한 정보가 다 있으면 바로 판정하고, 부족하면(최대보유량을 모르거나 판정에 필요한 확인 사항이
    남았으면) 판정을 미룬 사업장을 만들어 별지 작성 화면에서 이어 가게 한다."""
    intake = build_intake(business, rows, components)
    issues = validate_intake(intake)
    quantity_issues = [i for i in issues if cap_judgement.QUANTITY_ISSUE in i]
    mixture_issues = [i for i in issues if "02A_혼합물구성성분에 구성성분을 한 줄 이상" in i]
    other_issues = [i for i in issues if i not in quantity_issues and i not in mixture_issues]
    if other_issues:
        return StartOutcome("INVALID", tuple(other_issues))

    single_cas_issues = []
    for idx, row in intake.chemicals.iterrows():
        if _clean(row.get(MIXTURE_FLAG_COLUMN)).upper() == "N":
            cas = _clean(row.get("CAS No."))
            if not cap_judgement.cas_valid(cas):
                product = _clean(row.get("제품명")) or f"{idx + 1}행"
                single_cas_issues.append(
                    f"{idx + 1}행({product}): 단일물질은 유효한 CAS No.가 반드시 필요합니다. 제품 SDS 제3항에서 확인해 주세요."
                )
    if single_cas_issues:
        return StartOutcome("INVALID", tuple(single_cas_issues))

    if mixture_issues:
        return _pending(
            intake,
            ("혼합제품이 있습니다. 사업장을 만든 뒤 '혼합물 구성성분' 두 번째 파일에 SDS 제3항의 CAS No.와 함량(%)을 입력해 주세요.",),
        )
    # 신규 5열 입력은 성분 함량을 일부러 받지 않는다. 판정 화면에서 단일물질/혼합물을
    # 먼저 확인한 뒤 단일물질은 100%, 혼합물은 SDS 제3항의 구성성분 CAS+함량으로 확정한다.
    composition_missing = []
    for idx, row in intake.chemicals.iterrows():
        content = _clean(row.get("함량(%)"))
        mixture = _clean(row.get(MIXTURE_FLAG_COLUMN))
        if not content and not mixture:
            composition_missing.append(str(idx + 1))
    if composition_missing:
        return _pending(
            intake,
            ("물질 성분 확인이 필요합니다. 법정 대상 판정에서 각 제품이 단일물질인지 혼합물인지 확인해 주세요.",),
        )
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
        "chemicals": _records(intake), "mixture_components": _component_dicts(intake), "facilities": [],
        "decision": asdict(decision) if is_dataclass(decision) else dict(vars(decision)),
    }
    project = create_project_from_stage1_snapshot(snapshot)
    cap_judgement.save_business(project, **_business_args(intake.business))
    psm_target, cap_target = project.psm_required is True, project.cap_required is True
    if not psm_target and not cap_target:
        return StartOutcome("NOT_REQUIRED", (), **base)
    project.set_authoring_scope(psm_selected=psm_target, cap_selected=cap_target)
    return StartOutcome("STARTED", (), project, **base)
