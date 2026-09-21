from __future__ import annotations

"""프로젝트에 이미 입력된 사실로 법정 대상 판정(Stage 1 엔진)을 (다시) 돌리고, 결과를 작성 범위로 반영한다.

시작하기에서 최대보유량을 몰라 판정을 미룬 사업장도, 별지 제1호 시설 입력으로 최대보유량이 계산된 뒤 이 판정을 돌려 범위를
확정한다. 엔진이 "이 답이 필요합니다"라고 요청한 항목만 쉬운 질문으로 바꿔 묻고, 답은 프로젝트에 남겨 다시 판정할 때 쓴다.
판정 규칙은 새로 만들지 않는다: 엑셀 판정과 시작하기가 쓰던 같은 엔진(assess_stage1_from_workbook)을 그대로 호출한다.
"""

from dataclasses import asdict, dataclass, field, is_dataclass
import hashlib
import json
import re
from typing import Any, Callable, Mapping

import pandas as pd

from ..inventory import IntakeData, validate_intake
from ..stage1_workbook import assess_stage1_from_workbook
from . import cap_chemical_workspace as chem
from .project import Stage2Project, _cap_group_from_status, _subject_from_status

ANSWERS_KEY = "stage1.answers"
PENDING_KEY = "judgement_pending"
QUANTITY_ISSUE = "최대 제조·사용량, 최대 저장량 또는 최대 동시보유량 중 하나는 필요합니다"
YES_NO = ("Y", "N", "모름")


@dataclass(frozen=True)
class Question:
    item: str            # 엔진이 찾는 확인항목 이름(final_conditions의 키)
    system: str          # 화학사고예방관리계획서 / 공정안전보고서 / 공통
    text: str            # 사용자에게 묻는 쉬운 문장
    help: str
    options: tuple[str, ...] = YES_NO
    trigger: str = ""    # 엔진 요청 문구에 이 글이 있으면 물어야 하는 질문
    follows: str = ""    # 이 질문에 대한 답이 'Y'일 때만 묻는 하위 질문


QUESTIONS: tuple[Question, ...] = (
    Question("상위 규정수량 이상을 취급하는 개별 주요취급시설 존재 여부", "화학사고예방관리계획서",
             "상위 규정수량 이상의 유해화학물질을 취급하는 개별 시설(주요취급시설)이 있나요?",
             "물질 하나를 하나의 시설(탱크 등)에서 상위 규정수량 이상 취급하면 '예'입니다. 시설별 최대보유량은 별지 제1호에서 계산됩니다. 1군·2군을 가르는 기준입니다.",
             trigger="개별 주요취급시설"),
    Question("법 제23조제1항 단서 해당 여부", "화학사고예방관리계획서",
             "화학물질관리법 제23조제1항 단서에 해당해 작성 의무가 면제되는 시설인가요?",
             "법에서 정한 예외 시설(예: 특정 용도·인허가 시설)이면 '예'입니다. 잘 모르면 '모름'을 고르세요. 판정이 보류되고 확인 방법이 안내됩니다.",
             trigger="법 제23조제1항 단서"),
    Question("법적 예외 적용 유형", "화학사고예방관리계획서", "어떤 예외에 해당하나요?",
             "해당하는 예외의 유형을 법령 표현대로 적습니다.", options=(), follows="법 제23조제1항 단서 해당 여부"),
    Question("시행령 제43조제2항 제외설비 해당 여부", "공정안전보고서",
             "산업안전보건법 시행령 제43조제2항의 제외설비(공정안전보고서 제출 대상에서 빠지는 설비)에 해당하나요?",
             "법령이 정한 제외 설비 유형이면 '예'입니다. 해당하지 않으면 '아니오'입니다.",
             trigger="제외설비 해당 여부"),
    Question("시행령 제43조제2항 제외설비 유형", "공정안전보고서", "어떤 제외설비 유형인가요?",
             "법령상 제외설비 유형을 그대로 적습니다.", options=(), follows="시행령 제43조제2항 제외설비 해당 여부"),
    *(
        q
        for no, label in ((1, "인화성 가스"), (2, "인화성 액체"))
        for q in (
            Question(f"별표 13 제{no}호 {label} 해당 여부", "공정안전보고서",
                     f"귀사의 취급물질·공정에 산업안전보건법 시행령 별표 13 제{no}호({label})에 해당하는 것이 있나요?",
                     f"제{no}호({label}) 규정량 대상 물질을 취급하면 Y, 아니면 N입니다. 잘 모르면 '모름'을 고르세요.",
                     trigger=f"제{no}호({label})"),
            Question(f"별표 13 제{no}호 하루 최대 제조·취급량(kg)", "공정안전보고서",
                     f"제{no}호({label})의 하루 최대 제조·취급량은 몇 kg인가요?",
                     "숫자만 적습니다(kg). 해당 물질을 하루에 가장 많이 제조·취급하는 양입니다.",
                     options=(), follows=f"별표 13 제{no}호 {label} 해당 여부"),
            Question(f"별표 13 제{no}호 최대 저장량(kg)", "공정안전보고서",
                     f"제{no}호({label})의 최대 저장량은 몇 kg인가요?",
                     "숫자만 적습니다(kg). 해당 물질을 한꺼번에 가장 많이 저장하는 양입니다.",
                     options=(), follows=f"별표 13 제{no}호 {label} 해당 여부"),
        )
    ),
    Question("미확인 결정조건 존재 여부", "공통",
             "판정에 영향을 주는데 아직 확인하지 못한 조건이 남아 있나요?",
             "사내에서 아직 확인하지 못한 사실이 있으면 '예'입니다. '예'이면 판정을 보류하고 확인 후 다시 판정합니다.",
             trigger="미확인 결정조건"),
)
_BY_ITEM = {q.item: q for q in QUESTIONS}

# 판정 엔진이 물질(행)마다 요구하는 값. 판정 화면의 표에서 입력받아 프로젝트에 남기고, 판정 입력(물질 표)에 덧붙인다.
CHEM_INPUTS_KEY = "stage1.chemical_inputs"
CHEM_INPUT_COLUMNS = (
    "함량(%)", "상온·상압 액체 여부(해당 시)", "최대 제조·사용량", "최대 저장량",
    "최대 동시보유량(알면 입력)", "최대보유량 법정 산정 여부", "SDS 제2항 유해성·위험성 분류(선택 입력)",
)
_EXTRA_INPUT_COLUMNS = ("상온·상압 액체 여부(해당 시)", "최대 제조·사용량", "최대 저장량",
                        "최대보유량 법정 산정 여부", "SDS 제2항 유해성·위험성 분류(선택 입력)")
# 이 문구가 들어 있는 엔진 요청은 물질 표에서 답한다.
CHEM_REQUEST_MARKERS = ("최대 제조·사용량", "SDS 제2항", "법정 사업장 최대보유량", "농도·성상", "함량(%)",
                        "판정 수량을 kg", "CAS No.를 확인")


@dataclass
class Outcome:
    status: str  # DECIDED / NOT_REQUIRED / REQUEST / PENDING / SYSTEM / INVALID
    messages: tuple[str, ...] = ()
    questions: tuple[Question, ...] = ()
    decision: Any = None
    psm_target: bool = False
    cap_target: bool = False
    cap_group: str = ""
    missing_quantity: tuple[str, ...] = field(default_factory=tuple)

    @property
    def cap_status(self) -> str:
        return str(getattr(self.decision, "cap_status", ""))

    @property
    def psm_status(self) -> str:
        return str(getattr(self.decision, "psm_status", ""))


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def display_request(value: object) -> str:
    """판정 엔진 요청 문구 앞의 엑셀 시트 이름('05_최종판정조건: ' 등)은 사용자에게 보이지 않게 뗀다."""
    return re.sub(r"^(?:\d{2}_[^:]+|회사 입력파일):\s*", "", _clean(value))


def _field_text(project: Stage2Project, key: str) -> str:
    record = project.get_field(key)
    return "" if record is None or record.value is None else _clean(record.value)


def is_pending(project: Stage2Project) -> bool:
    return bool(project.stage1_snapshot.get(PENDING_KEY)) and not project.scope_confirmed


def undecided(project: Stage2Project) -> bool:
    """법정 대상 판정을 아직 하지 않은 사업장(판정을 미룬 경우, 또는 판정 결과가 없는 경우)."""
    return is_pending(project) or (not project.scope_confirmed and not project.stage1_snapshot.get("decision"))


def answers(project: Stage2Project) -> dict[str, str]:
    record = project.get_field(ANSWERS_KEY)
    return {str(k): _clean(v) for k, v in record.value.items()} if record is not None and isinstance(record.value, dict) else {}


def save_answers(project: Stage2Project, new: Mapping[str, str]) -> None:
    merged = {**answers(project), **{k: _clean(v) for k, v in new.items() if _clean(v)}}
    project.set_field(ANSWERS_KEY, "법정 판정에 필요한 확인 사항(회사 답변)", merged, "USER_CONFIRMED")


def chemical_inputs(project: Stage2Project) -> list[dict[str, str]]:
    record = project.get_field(CHEM_INPUTS_KEY)
    if record is None or not isinstance(record.value, list):
        return []
    return [{str(k): _clean(v) for k, v in row.items()} if isinstance(row, dict) else {} for row in record.value]


def save_chemical_inputs(project: Stage2Project, rows: list[Mapping[str, Any]]) -> None:
    project.set_field(CHEM_INPUTS_KEY, "법정 판정에 필요한 물질별 확인값(회사 입력)",
                      [{k: _clean(v) for k, v in dict(row).items() if k in CHEM_INPUT_COLUMNS} for row in rows],
                      "USER_CONFIRMED")


def request_rows(requests: list[str] | tuple[str, ...], total: int) -> list[int]:
    """엔진 요청 문구에서 물질 표의 행 번호(1부터)를 뽑는다. 행을 특정하지 못하는 요청이 있으면 모든 행을 돌려준다."""
    rows: set[int] = set()
    generic = False
    for text in requests:
        message = display_request(text)
        if not any(marker in message for marker in CHEM_REQUEST_MARKERS):
            continue
        found = {int(n) for n in re.findall(r"(\d+)행", message)}
        lead = re.match(r"^\s*((?:\d+\s*,\s*)*\d+)\s*의", message)
        if lead:
            found |= {int(n) for n in re.findall(r"\d+", lead.group(1))}
        if found:
            rows |= found
        else:
            generic = True
    if generic:
        return list(range(1, total + 1))
    return sorted(n for n in rows if 1 <= n <= total)


def _facility_quantities(project: Stage2Project) -> dict[str, float]:
    """별지 제1호 시설 입력으로 계산된 사업장 내 최대보유량(ton)을 CAS별로 돌려준다(없으면 빈 값)."""
    try:
        from .cap_form1_engine import build_cap_form1_data

        rows = build_cap_form1_data(project).chemical_rows
    except Exception:
        return {}
    out: dict[str, float] = {}
    for row in rows:
        try:
            value = float(str(row.get("사업장 내 최대보유량(ton)") or "").replace(",", ""))
        except ValueError:
            continue
        for key in (_clean(row.get("CAS No.")), _clean(row.get("물질명"))):
            if key:
                out[key] = value
    return out


def build_intake(project: Stage2Project) -> tuple[IntakeData, list[str]]:
    """프로젝트의 사업장·물질·시설·답변으로 판정 입력을 만든다. (입력, 최대보유량을 알 수 없는 물질 이름)"""
    business_raw = dict(project.stage1_snapshot.get("business") or {})
    address = project.get_field("business.address")
    business = {
        "사업장명": _clean(business_raw.get("사업장명")) or project.company_name,
        "사업장 주소": _clean(business_raw.get("사업장 주소")) or (_clean(address.value) if address is not None else ""),
        "업종 또는 주요 생산품": _clean(business_raw.get("업종 또는 주요 생산품")) or _field_text(project, "business.main_products"),
    }
    _, rows = chem._rows(project)
    computed = _facility_quantities(project)
    records: list[dict[str, Any]] = []
    missing: list[str] = []
    entered = chemical_inputs(project)
    for index, row in enumerate(rows):
        extra = entered[index] if index < len(entered) else {}
        name = _clean(row.get("물질명") or row.get("제품명") or row.get("유해화학물질명"))
        cas = _clean(row.get("CAS No.") or row.get("CAS 번호") or row.get("CAS"))
        quantity = _clean(extra.get("최대 동시보유량(알면 입력)")) or row.get("최대 동시보유량(알면 입력)")
        if quantity in (None, "") or (isinstance(quantity, float) and quantity != quantity):
            quantity = computed.get(cas) if cas in computed else computed.get(name)
        also_given = _clean(extra.get("최대 제조·사용량")) or _clean(extra.get("최대 저장량"))
        if quantity in (None, "") and not also_given:
            missing.append(name or cas)
        record = {
            "제품명": _clean(row.get("제품명")) or name, "CAS No.": cas, "물질명(알면 입력)": name,
            "함량(%)": _clean(extra.get("함량(%)")) or row.get("함량(%)"), "취급형태": _clean(row.get("취급형태")) or "저장·사용",
            "수량 단위": _clean(row.get("수량 단위")) or "ton", "최대 동시보유량(알면 입력)": quantity,
        }
        for column in _EXTRA_INPUT_COLUMNS:
            record[column] = _clean(extra.get(column))
        records.append(record)
    columns = ["제품명", "CAS No.", "물질명(알면 입력)", "함량(%)", "취급형태", "수량 단위", "최대 동시보유량(알면 입력)"]
    columns += [c for c in _EXTRA_INPUT_COLUMNS if any(r.get(c) for r in records)]
    frame = pd.DataFrame(records, columns=columns)
    fingerprint = hashlib.sha256(json.dumps({"business": business, "chemicals": records, "answers": answers(project)},
                                            ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    mixture = project.stage1_snapshot.get("mixture_components") or []
    intake = IntakeData(business=business, chemicals=frame, documents={}, final_conditions=dict(answers(project)),
                        source_fingerprint=fingerprint,
                        mixture_components=pd.DataFrame(mixture) if mixture else pd.DataFrame())
    return intake, missing


def _questions_for(requests: list[str], current: Mapping[str, str]) -> tuple[Question, ...]:
    wanted: list[Question] = []
    for question in QUESTIONS:
        if question.follows:
            continue
        if question.trigger and any(question.trigger in text for text in requests):
            wanted.append(question)
    for question in QUESTIONS:  # 위 질문에 'Y'라고 답했을 때 이어서 묻는 질문
        if question.follows and any(q.item == question.follows and current.get(q.item, "").upper().startswith(("Y", "예", "해당"))
                                    for q in wanted + [_BY_ITEM[k] for k in current if k in _BY_ITEM]):
            wanted.append(question)
    return tuple(dict.fromkeys(wanted))


def judge(project: Stage2Project, assess: Callable[[IntakeData], Any] = assess_stage1_from_workbook) -> Outcome:
    intake, missing = build_intake(project)
    issues = validate_intake(intake)
    quantity_issues = [i for i in issues if QUANTITY_ISSUE in i]
    other = [i for i in issues if QUANTITY_ISSUE not in i]
    if other:
        return Outcome("INVALID", tuple(other))
    if quantity_issues or missing:
        return Outcome("PENDING", tuple(quantity_issues), missing_quantity=tuple(dict.fromkeys(missing)))
    decision = assess(intake)
    if getattr(decision, "system_blockers", None):
        return Outcome("SYSTEM", tuple(decision.system_blockers), decision=decision)
    requests = list(getattr(decision, "company_requests", None) or [])
    if requests:
        return Outcome("REQUEST", tuple(requests), _questions_for(requests, answers(project)), decision=decision)
    psm = _subject_from_status(getattr(decision, "psm_status", "")) is True
    cap_status = str(getattr(decision, "cap_status", ""))
    cap = _subject_from_status(cap_status) is True
    group = _cap_group_from_status(cap_status)
    if not psm and not cap:
        return Outcome("NOT_REQUIRED", decision=decision, cap_group=group)
    return Outcome("DECIDED", decision=decision, psm_target=psm, cap_target=cap, cap_group=group)


def apply(project: Stage2Project, outcome: Outcome, *, write_psm: bool | None = None, write_cap: bool | None = None) -> None:
    """판정 결과를 프로젝트의 법정 대상 여부와 작성 범위로 반영한다. 선택하지 않으면 대상 문서를 모두 작성한다."""
    if outcome.status not in ("DECIDED", "NOT_REQUIRED"):
        raise ValueError("판정이 끝나지 않아 작성 범위를 정할 수 없습니다.")
    decision = outcome.decision
    project.psm_required = outcome.psm_target if outcome.status == "DECIDED" else False
    project.cap_required = outcome.cap_target if outcome.status == "DECIDED" else False
    project.cap_group = outcome.cap_group
    project.stage1_snapshot["decision"] = asdict(decision) if is_dataclass(decision) else dict(vars(decision))
    project.stage1_snapshot.pop(PENDING_KEY, None)
    if outcome.status == "DECIDED":
        psm = outcome.psm_target if write_psm is None else bool(write_psm and outcome.psm_target)
        cap = outcome.cap_target if write_cap is None else bool(write_cap and outcome.cap_target)
        if not psm and not cap:
            raise ValueError("작성할 문서를 하나 이상 선택해야 합니다.")
        project.set_authoring_scope(psm_selected=psm, cap_selected=cap)
    project.touch()
