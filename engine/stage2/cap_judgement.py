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

from ..inventory import IntakeData, MIXTURE_COMPONENT_COLUMNS, MIXTURE_FLAG_COLUMN, validate_intake
from ..stage1_workbook import assess_stage1_from_workbook
from . import cap_chemical_workspace as chem
from .cap_chemical_upload import cas_valid
from .project import Stage2Project, _cap_group_from_status, _subject_from_status

ANSWERS_KEY = "stage1.answers"
PENDING_KEY = "judgement_pending"
QUANTITY_ISSUE = "최대 제조·사용량, 최대 저장량 또는 최대 동시보유량 중 하나는 필요합니다"
YES_NO = ("Y", "N", "모름")


@dataclass(frozen=True)
class Question:
    item: str            # 엔진이 찾는 확인항목 이름(final_conditions의 키)
    system: str          # 화학사고예방관리계획서 / 공정안전보고서 / 공통
    text: str            # 사용자에게 묻는 한 줄 질문(쉬운 말)
    help: str            # ? 안에 넣는 설명(무슨 뜻인지·왜 묻는지·어디서 확인하는지·모르면)
    options: tuple[str, ...] = YES_NO
    trigger: str = ""    # 엔진 요청 문구에 이 글이 있으면 물어야 하는 질문
    follows: str = ""    # 이 질문에 대한 답이 'Y'일 때만 묻는 하위 질문
    choices: tuple[str, ...] = ()  # 법령 목록에서 고르는 질문(드롭다운). 있으면 options 대신 쓴다
    numeric: bool = False          # 숫자만 적는 질문(%, kg 등)


def _exemption_labels() -> tuple[str, ...]:
    from ..cap_final_decision import exemption_options

    return tuple(option.label for option in exemption_options())


def _psm_exclusion_labels() -> tuple[str, ...]:
    from ..consulting_guidance import get_guide

    guide = get_guide("PSM_EXCLUDED_FACILITY")
    return tuple(guide.what_to_check) if guide is not None else ()


def _help(meaning: str, *, why: str = "", where: str = "", example: str = "", unsure: str = "잘 모르면 '모름'을 고르세요. 판정이 보류되고 무엇을 확인해야 하는지 안내됩니다.") -> str:
    parts = [f"**무슨 뜻인가요?** {meaning}"]
    if example:
        parts.append(f"**예를 들면** {example}")
    if why:
        parts.append(f"**왜 묻나요?** {why}")
    if where:
        parts.append(f"**어디서 확인하나요?** {where}")
    if unsure:
        parts.append(f"**모르면?** {unsure}")
    return "\n\n".join(parts)


NOTE8_ITEM = "가스를 전문으로 저장·판매하는 시설 내 가스 여부"
NOTE8_TABLE_MARKER = "전문 가스 저장·판매시설에 해당하는 가스"

QUESTIONS: tuple[Question, ...] = (
    Question("상위 규정수량 이상을 취급하는 개별 주요취급시설 존재 여부", "화학사고예방관리계획서",
             "상위 규정수량 이상의 유해화학물질을 취급하는 개별 시설(주요취급시설)이 있나요?",
             _help("사업장 전체가 아니라 탱크·반응기 같은 시설 하나가, 한 가지 유해화학물질을 상위 규정수량 이상 취급하는 경우입니다. "
                   "이런 시설이 있으면 1군, 없으면 2군으로 나뉩니다.",
                   example="사업장 전체에 1.6 ton이 있어도 두 탱크에 0.8 ton씩 나뉘어 있으면 개별 시설은 상위 규정수량 미만일 수 있습니다.",
                   where="시설별 최대 취급량은 별지 제1호에서 계산됩니다. 시설 목록과 각 시설의 최대 저장량을 보면 됩니다."),
             trigger="개별 주요취급시설"),
    Question("법 제23조제1항 단서 해당 여부", "화학사고예방관리계획서",
             "화학사고예방관리계획서를 작성하지 않아도 되는 시설(작성 면제 시설)에 해당하나요?",
             _help("법에서 작성 의무를 면제한 시설입니다. 연구실·학교, 유해화학물질 운반 차량, 군사시설, 의료기관, 항만·철도·공항의 보관시설, "
                   "농약 판매업자 보관시설, 소비자 판매용 포장제품 진열시설, 폐기물 임시보관시설, 주유소 등이 있습니다. "
                   "'예'를 고르면 다음 질문에서 정확한 종류를 목록에서 고릅니다.",
                   why="규정수량을 넘더라도 면제 시설이면 작성하지 않기 때문입니다.",
                   where="시설의 용도와 인허가 서류(사업자등록, 시설 허가·신고)를 보면 됩니다. 일반 제조·저장 공장이 위 목록에 없다면 보통 '아니오'입니다."),
             trigger="법 제23조제1항 단서"),
    Question("법적 예외 적용 유형", "화학사고예방관리계획서", "어떤 면제 시설에 해당하나요?",
             _help("면제 시설의 종류입니다. 목록에서 가장 가까운 것을 고르세요.", unsure="목록에 없거나 확실하지 않으면 앞 질문에서 '모름'으로 바꿔 주세요."),
             options=(), follows="법 제23조제1항 단서 해당 여부", choices=_exemption_labels()),
    Question("법적 예외가 관련 취급시설 전체에 적용되는지", "화학사고예방관리계획서",
             "그 면제는 화학물질을 취급하는 시설 전체에 해당하나요?",
             _help("일부 시설만 면제이면 나머지 시설은 계속 작성 대상입니다. 모든 취급시설이 면제 시설이어야 '예'입니다."),
             follows="법 제23조제1항 단서 해당 여부"),
    Question("시행령 제43조제2항 제외설비 해당 여부", "공정안전보고서",
             "공정안전보고서를 내지 않아도 되는 설비(제외설비)에 해당하나요?",
             _help("법으로 정한 제외 설비입니다. 원자력 설비, 군사시설, 난방용 연료 저장·사용설비, 도매·소매시설, 차량 등의 운송설비, "
                   "LPG 충전·저장시설, 도시가스 공급시설, 비상발전기용 경유 저장탱크·사용설비가 있습니다.",
                   why="규정량을 넘더라도 제외설비이면 제출 대상에서 빠지기 때문입니다.",
                   where="설비의 용도를 보면 됩니다. 위 목록에 없는 일반 공정 설비는 '아니오'입니다."),
             trigger="제외설비 해당 여부"),
    Question("시행령 제43조제2항 제외설비 유형", "공정안전보고서", "어떤 제외설비인가요?",
             _help("제외설비의 종류입니다. 목록에서 고르세요.", unsure="목록에 없으면 앞 질문에서 '모름'으로 바꿔 주세요."),
             options=(), follows="시행령 제43조제2항 제외설비 해당 여부", choices=_psm_exclusion_labels()),
    *(
        q
        for no, label, meaning, example, where in (
            (1, "인화성 가스",
             "불이 붙기 쉬운 기체입니다. 법 기준으로는 20℃, 표준압력에서 가스 상태이고, 불이 붙는 농도 범위의 아래쪽 한계가 13% 이하이거나 "
             "위·아래 한계의 차가 12%p 이상인 물질입니다.",
             "LPG(프로판·부탄), 수소, 아세틸렌, 메탄 같은 연료·공정 가스",
             "제품 SDS 제9항의 '인화 또는 폭발 범위(하한·상한)'와 '성상', 또는 제2항의 '인화성 가스' 분류를 보면 됩니다."),
            (2, "인화성 액체",
             "불이 붙기 쉬운 액체입니다. 법 기준으로는 표준압력에서 인화점이 60℃ 이하이거나, 고온·고압 공정 조건에서 화재·폭발 위험이 있는 "
             "가연성 물질입니다. 인화점이 낮을수록 불이 붙기 쉽습니다.",
             "톨루엔, 아세톤, 메탄올, 에탄올, 시너 같은 유기용제",
             "제품 SDS 제9항의 '인화점'을 보면 됩니다. 60℃ 이하이면 대체로 해당합니다."),
        )
        for q in (
            Question(f"별표 13 제{no}호 {label} 해당 여부", "공정안전보고서",
                     f"취급하는 물질 중 {label}이 있나요?",
                     _help(meaning, example=example,
                           why="공정안전보고서 대상은 물질별 규정량으로 정해지는데, 이 물질군은 물성(SDS)으로 해당 여부를 확인해야 하기 때문입니다.",
                           where=where),
                     trigger=f"제{no}호({label})"),
            Question(f"별표 13 제{no}호 하루 최대 제조·취급량(kg)", "공정안전보고서",
                     f"{label}의 하루 최대 제조·취급량은 얼마인가요?",
                     _help(f"{label}에 해당하는 물질을 하루에 가장 많이 제조하거나 취급하는 양의 합계입니다. 숫자만 적고 단위(kg 또는 ton)를 고르세요.",
                           unsure="모르면 비워 두세요. 하지 않으면 0을 적습니다."),
                     options=(), follows=f"별표 13 제{no}호 {label} 해당 여부", numeric=True),
            Question(f"별표 13 제{no}호 최대 저장량(kg)", "공정안전보고서",
                     f"{label}의 최대 저장량은 얼마인가요?",
                     _help(f"{label}에 해당하는 물질을 한꺼번에 가장 많이 저장하는 양의 합계입니다. 숫자만 적고 단위(kg 또는 ton)를 고르세요.",
                           unsure="모르면 비워 두세요. 저장하지 않으면 0을 적습니다."),
                     options=(), follows=f"별표 13 제{no}호 {label} 해당 여부", numeric=True),
        )
    ),
    Question("별표 13 제23호 발연황산 삼산화황(SO3) 중량%", "공정안전보고서",
             "발연황산 제품의 삼산화황(SO3) 함량은 몇 %인가요?",
             _help("발연황산은 삼산화황(SO3) 함량이 65% 이상 80% 미만일 때 공정안전보고서 규정량 대상(별표 13 제23호)입니다. 숫자만 적으세요.",
                   where="제품 SDS 제3항(구성성분·함유량) 또는 제조사 시험성적서에 적혀 있습니다.", unsure="모르면 비워 두세요. 제조사에 확인한 뒤 다시 판정하면 됩니다."),
             options=(), trigger="제23호 발연황산", numeric=True),
    Question("별표 13 제42호 니트로셀룰로오스 질소 함유량%", "공정안전보고서",
             "니트로셀룰로오스의 질소 함유량은 몇 %인가요?",
             _help("니트로셀룰로오스는 질소 함유량이 12.6% 이상일 때 공정안전보고서 규정량 대상(별표 13 제42호)입니다. 숫자만 적으세요.",
                   where="제품 SDS 제3항 또는 제조사 시험성적서에 적혀 있습니다.", unsure="모르면 비워 두세요. 제조사에 확인한 뒤 다시 판정하면 됩니다."),
             options=(), trigger="제42호 니트로셀룰로오스", numeric=True),
    Question(NOTE8_ITEM, "공정안전보고서",
             "취급하는 가스가 '가스를 전문으로 저장·판매하는 시설'(가스 충전소·판매소 등)의 가스인가요?",
             _help("가스를 사서 저장하고 되파는 것이 주된 일인 시설입니다. 이런 시설의 가스는 규정량 계산(별표 13 비고 제8호)에서 뺄 수 있습니다. "
                   "일반 제조·사용 사업장은 대부분 '아니오'입니다.",
                   why="지금까지 입력한 가스의 양이 공정안전보고서 대상 기준에 이를 만큼 많아서, 이 예외에 해당하는지 확인해야 하기 때문입니다.",
                   where="사업의 종류(가스 충전·판매업 등록 여부)를 보면 됩니다."),
             trigger=NOTE8_ITEM),
    Question("미확인 결정조건 존재 여부", "공통",
             "판정에 영향을 주는데 아직 확인하지 못한 조건이 남아 있나요?",
             _help("사내에서 아직 확인하지 못한 사실이 있으면 '예'입니다.", unsure="'예'이면 판정을 보류하고, 확인한 뒤 다시 판정하면 됩니다."),
             trigger="미확인 결정조건"),
)
_BY_ITEM = {q.item: q for q in QUESTIONS}

# 판정 엔진이 물질(행)마다 요구하는 값. 판정 화면의 표에서 입력받아 프로젝트에 남기고, 판정 입력(물질 표)에 덧붙인다.
CHEM_INPUTS_KEY = "stage1.chemical_inputs"
MIXTURE_COMPONENTS_KEY = "inventory.mixture_components"
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
    composition_rows: tuple[int, ...] = field(default_factory=tuple)

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


QUANTITY_COLUMNS = ("최대 제조·사용량", "최대 저장량", "최대 동시보유량(알면 입력)")
UNIT_OPTIONS = ("ton", "kg")
_KG_PER = {"kg": 1.0, "ton": 1000.0}


def _fmt(number: float) -> str:
    return f"{number:.10g}"


def convert_quantity(value: object, unit: str, target: str) -> str:
    """수량 문자열을 kg 또는 ton으로 바꾼다. 비어 있거나 숫자가 아니면 그대로 돌려준다(모르는 값을 0으로 만들지 않는다)."""
    text = _clean(value).replace(",", "")
    if not text or unit not in _KG_PER or target not in _KG_PER or unit == target:
        return _clean(value)
    try:
        return _fmt(float(text) * _KG_PER[unit] / _KG_PER[target])
    except ValueError:
        return _clean(value)


def rows_to_ton(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """표에서 행마다 고른 단위(kg/ton)를 ton으로 통일한다. 판정 엔진과 저장 값은 언제나 ton이다."""
    out = []
    for row in rows:
        unit = _clean(row.get("단위")) or "ton"
        item = {k: v for k, v in dict(row).items() if k != "단위"}
        for column in QUANTITY_COLUMNS:
            if column in item:
                item[column] = convert_quantity(item[column], unit, "ton")
        out.append(item)
    return out


NOTE8_KEY = "stage1.psm_note8_exclusions"
NOTE8_COLUMNS = ("별표13 호수", "제조·취급 제외량(kg)", "저장 제외량(kg)")


def note8_rows(project: Stage2Project) -> list[dict[str, str]]:
    record = project.get_field(NOTE8_KEY)
    if record is None or not isinstance(record.value, list):
        return []
    return [{k: _clean(v) for k, v in row.items()} for row in record.value if isinstance(row, dict)]


def save_note8_rows(project: Stage2Project, rows: list[Mapping[str, Any]]) -> None:
    """'가스를 전문으로 저장·판매하는 시설'의 가스라서 규정량 계산에서 뺄 양(별표 13 호수별, kg)."""
    kept = [{k: _clean(row.get(k)) for k in NOTE8_COLUMNS} for row in rows if any(_clean(row.get(k)) for k in NOTE8_COLUMNS)]
    project.set_field(NOTE8_KEY, "비고 제8호 제외수량(회사 입력)", kept, "USER_CONFIRMED")


def save_chemical_inputs(project: Stage2Project, rows: list[Mapping[str, Any]]) -> None:
    project.set_field(CHEM_INPUTS_KEY, "법정 판정에 필요한 물질별 확인값(회사 입력)",
                      [{k: _clean(v) for k, v in dict(row).items() if k in CHEM_INPUT_COLUMNS} for row in rows],
                      "USER_CONFIRMED")


def mixture_components(project: Stage2Project) -> list[dict[str, Any]]:
    """Return saved SDS Section-3 mixture components, preferring the live project field."""
    record = project.get_field(MIXTURE_COMPONENTS_KEY)
    source = record.value if record is not None and isinstance(record.value, list) else project.stage1_snapshot.get("mixture_components")
    return [dict(row) for row in list(source or []) if isinstance(row, Mapping)]


def _mixture_yes(value: object) -> bool:
    return _clean(value).lower().replace(" ", "") in {"y", "yes", "예", "해당", "혼합물", "1", "true"}


def _mixture_no(value: object) -> bool:
    return _clean(value).lower().replace(" ", "") in {"n", "no", "아니오", "아님", "단일물질", "0", "false", "해당없음"}


def composition_rows(project: Stage2Project) -> list[int]:
    """Rows whose single-substance/mixture identity still needs company confirmation.

    Legacy rows that already contain one valid CAS plus a concentration are kept
    as-is. New minimal-input rows have no concentration, so they are routed to
    the composition questionnaire before either statutory engine runs.
    """
    _, rows = chem._rows(project)
    components = mixture_components(project)
    parents = {
        int(float(row.get("제품목록행번호")))
        for row in components
        if _clean(row.get("제품목록행번호")) and str(row.get("제품목록행번호")).replace(".", "", 1).isdigit()
    }
    unresolved: list[int] = []
    for number, row in enumerate(rows, start=1):
        cas = _clean(row.get("CAS No.") or row.get("CAS 번호") or row.get("CAS"))
        content = _clean(row.get("함량(%)"))
        flag = row.get(MIXTURE_FLAG_COLUMN)
        if _mixture_yes(flag):
            if number not in parents:
                unresolved.append(number)
            continue
        if _mixture_no(flag):
            if not cas_valid(cas):
                unresolved.append(number)
            continue
        # Backward compatibility: old company files already supplied CAS+content.
        if content and cas_valid(cas):
            continue
        unresolved.append(number)
    return unresolved


def save_composition(
    project: Stage2Project,
    classifications: list[Mapping[str, Any]],
    components: list[Mapping[str, Any]],
    *,
    sds_confirmed: bool,
) -> None:
    """Save single/mixture identity using CAS as the legal identifier.

    Single substances require one valid CAS and are stored as 100%. Mixtures
    require at least one SDS Section-3 component; every component requires a
    valid CAS and concentration. Component names are display-only and optional.
    """
    _, rows = chem._rows(project)
    wanted = set(composition_rows(project))
    by_row = {int(float(item.get("행"))): dict(item) for item in classifications if _clean(item.get("행"))}
    if wanted - set(by_row):
        missing = ", ".join(map(str, sorted(wanted - set(by_row))))
        raise ValueError(f"{missing}행의 단일물질/혼합물 여부를 선택해 주세요.")

    component_by_parent: dict[int, list[dict[str, Any]]] = {}
    for raw in components:
        try:
            parent = int(float(raw.get("제품목록행번호")))
        except (TypeError, ValueError):
            continue
        component_by_parent.setdefault(parent, []).append(dict(raw))

    existing = [row for row in mixture_components(project) if int(float(row.get("제품목록행번호") or 0)) not in wanted]
    new_components: list[dict[str, Any]] = []
    any_mixture = False

    for number in sorted(wanted):
        if number <= 0 or number > len(rows):
            raise ValueError(f"{number}행을 물질 목록에서 찾을 수 없습니다.")
        answer = by_row[number]
        kind = _clean(answer.get("구분"))
        row = rows[number - 1]
        product = _clean(row.get("제품명") or row.get("물질명")) or f"{number}행"

        if kind == "단일물질":
            cas = _clean(answer.get("CAS No.") or row.get("CAS No.") or row.get("CAS 번호"))
            if not cas_valid(cas):
                raise ValueError(f"{number}행({product}): 단일물질은 유효한 CAS No.가 반드시 필요합니다.")
            row["CAS No."] = cas
            row["함량(%)"] = 100.0
            row[MIXTURE_FLAG_COLUMN] = "N"
            continue

        if kind != "혼합물":
            raise ValueError(f"{number}행({product}): 단일물질 또는 혼합물을 선택해 주세요.")

        any_mixture = True
        rows[number - 1][MIXTURE_FLAG_COLUMN] = "Y"
        rows[number - 1]["함량(%)"] = ""
        listed = component_by_parent.get(number, [])
        usable = []
        seen: set[str] = set()
        for raw in listed:
            cas = _clean(raw.get("CAS No."))
            pct_text = _clean(raw.get("함량(%)")).replace(",", "")
            name = _clean(raw.get("구성성분명") or raw.get("성분명(선택)"))
            if not cas and not pct_text and not name:
                continue
            if not cas_valid(cas):
                raise ValueError(f"{number}행({product}) 혼합물 구성성분: 모든 성분에 유효한 CAS No.를 입력해 주세요.")
            if cas in seen:
                raise ValueError(f"{number}행({product}) 혼합물 구성성분: CAS {cas}가 중복되었습니다.")
            seen.add(cas)
            try:
                pct = float(pct_text)
            except ValueError:
                raise ValueError(f"{number}행({product}) / CAS {cas}: 함량(%)을 숫자로 입력해 주세요.")
            if pct <= 0 or pct > 100:
                raise ValueError(f"{number}행({product}) / CAS {cas}: 함량(%)은 0 초과 100 이하이어야 합니다.")
            usable.append({
                "적용여부": "해당",
                "제품목록행번호": number,
                "제품명(확인용)": product,
                "구성성분명": name,
                "CAS No.": cas,
                "함량(%)": pct,
                "함량 최저(%)": None,
                "함량 최고(%)": None,
                "SDS 제3항 근거": "사용자 확인: 제품 SDS 제3항",
                "비고": "",
            })
        if not usable:
            raise ValueError(f"{number}행({product}): 혼합물은 SDS 제3항의 구성성분 CAS No.와 함량(%)을 한 줄 이상 입력해 주세요.")
        new_components.extend(usable)

    if any_mixture and not sds_confirmed:
        raise ValueError("혼합물 구성성분의 CAS No.와 함량(%)을 제품 SDS 제3항과 대조했는지 확인해 주세요.")

    all_components = [*existing, *new_components]
    # Keep canonical and inventory rows synchronized so later form screens see the same facts.
    canonical, _ = chem._rows(project)
    keys = [chem.INVENTORY_KEY]
    if canonical == chem.DETAILS_KEY:
        keys.append(chem.DETAILS_KEY)
    for key in keys:
        current = project.get_field(key)
        project.set_field(
            key,
            current.label if current is not None else "화학물질 목록",
            [dict(row) for row in rows],
            "USER_CONFIRMED",
            evidence=list(current.evidence) if current is not None else [],
            note="법정 대상 판정의 단일물질/혼합물 성분 확인 반영",
        )
    project.set_field(
        MIXTURE_COMPONENTS_KEY,
        "혼합물 구성성분",
        all_components,
        "USER_CONFIRMED" if all_components else "HOLD",
        note="혼합물 성분은 제품 SDS 제3항의 CAS No.와 함량을 기준으로 입력",
    )
    project.stage1_snapshot["chemicals"] = [dict(row) for row in rows]
    project.stage1_snapshot["mixture_components"] = [dict(row) for row in all_components]


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


BUSINESS_KEYS = ("사업장명", "사업장 주소", "업종 또는 주요 생산품")


def business_info(project: Stage2Project) -> dict[str, str]:
    """선택한 사업장의 사업장명·주소·업종. 판정 입력과 같은 곳에서 읽는다."""
    raw = dict(project.stage1_snapshot.get("business") or {})
    address = project.get_field("business.address")
    return {
        "사업장명": _clean(raw.get("사업장명")) or project.company_name,
        "사업장 주소": _clean(raw.get("사업장 주소")) or (_clean(address.value) if address is not None else ""),
        "업종 또는 주요 생산품": _clean(raw.get("업종 또는 주요 생산품")) or _field_text(project, "business.main_products"),
    }


def save_business(project: Stage2Project, name: str, address: str, industry: str) -> None:
    """사업장 정보를 고친다. 판정 입력, 프로젝트 이름, 별지 제12호가 읽는 칸(주소·주요 생산품)에 함께 반영한다.
    비워서 저장하면 기존 값을 지우지 않는다."""
    new = {"사업장명": _clean(name), "사업장 주소": _clean(address), "업종 또는 주요 생산품": _clean(industry)}
    current = business_info(project)
    merged = {key: new[key] or current[key] for key in BUSINESS_KEYS}
    snapshot_business = dict(project.stage1_snapshot.get("business") or {})
    snapshot_business.update({key: value for key, value in merged.items() if value})
    project.stage1_snapshot["business"] = snapshot_business
    if merged["사업장명"]:
        project.company_name = merged["사업장명"]
        project.site_name = merged["사업장명"]
        project.set_field("business.company_name", "회사명", merged["사업장명"], "USER_CONFIRMED")
        project.set_field("business.site_name", "사업장명", merged["사업장명"], "USER_CONFIRMED")
    if merged["사업장 주소"]:
        project.set_field("business.address", "사업장 소재지", merged["사업장 주소"], "USER_CONFIRMED")
    if merged["업종 또는 주요 생산품"]:
        project.set_field("business.main_products", "주요 생산품", merged["업종 또는 주요 생산품"], "USER_CONFIRMED")
    project.touch()


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
        extra = {c: _clean(extra.get(c)) or _clean(row.get(c)) for c in CHEM_INPUT_COLUMNS}
        quantity = extra.get("최대 동시보유량(알면 입력)") or row.get("최대 동시보유량(알면 입력)")
        if quantity in (None, "") or (isinstance(quantity, float) and quantity != quantity):
            quantity = computed.get(cas) if cas in computed else computed.get(name)
        also_given = _clean(extra.get("최대 제조·사용량")) or _clean(extra.get("최대 저장량"))
        if quantity in (None, "") and not also_given:
            missing.append(name or cas)
        content = _clean(extra.get("함량(%)")) or _clean(row.get("함량(%)"))
        if _mixture_no(row.get(MIXTURE_FLAG_COLUMN)) and not content:
            content = "100"
        record = {
            "제품명": _clean(row.get("제품명")) or name, "CAS No.": cas, "물질명(알면 입력)": name,
            "함량(%)": content, MIXTURE_FLAG_COLUMN: _clean(row.get(MIXTURE_FLAG_COLUMN)),
            "취급형태": _clean(row.get("취급형태")) or "저장·사용",
            "수량 단위": _clean(row.get("수량 단위")) or "ton", "최대 동시보유량(알면 입력)": quantity,
        }
        for column in _EXTRA_INPUT_COLUMNS:
            record[column] = _clean(extra.get(column))
        records.append(record)
    columns = ["제품명", "CAS No.", "물질명(알면 입력)", "함량(%)", MIXTURE_FLAG_COLUMN, "취급형태", "수량 단위", "최대 동시보유량(알면 입력)"]
    columns += [c for c in _EXTRA_INPUT_COLUMNS if any(r.get(c) for r in records)]
    frame = pd.DataFrame(records, columns=columns)
    fingerprint = hashlib.sha256(json.dumps({"business": business, "chemicals": records, "answers": answers(project), "note8": note8_rows(project)},
                                            ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    mixture = mixture_components(project)
    mixture_frame = pd.DataFrame(mixture, columns=MIXTURE_COMPONENT_COLUMNS) if mixture else pd.DataFrame(columns=MIXTURE_COMPONENT_COLUMNS)
    intake = IntakeData(business=business, chemicals=frame, documents={}, final_conditions=dict(answers(project)),
                        source_fingerprint=fingerprint,
                        mixture_components=mixture_frame,
                        psm_note8_exclusions=pd.DataFrame(note8_rows(project), columns=list(NOTE8_COLUMNS)))
    return intake, missing


_YN_REQUEST = re.compile(r"'([^']{3,80})'[을를] Y/N으로")


def generic_question(message: str) -> Question | None:
    """'항목'을 Y/N으로 확인해 달라는 엔진 요청에 답할 칸을 만든다. 그런 형식이 아니면 None."""
    match = _YN_REQUEST.search(display_request(message))
    if not match:
        return None
    item = match.group(1).strip()
    return Question(item, "공통", f"{item}?", _help("판정 규칙이 사업장에 대해 확인을 요청한 항목입니다. 사업장의 실제 상황에 맞게 답하세요."),
                    trigger=item)


def _questions_for(requests: list[str], current: Mapping[str, str]) -> tuple[Question, ...]:
    wanted: list[Question] = []
    for question in QUESTIONS:
        if question.follows:
            continue
        if question.trigger and any(question.trigger in text for text in requests):
            wanted.append(question)
    for text in requests:
        if any(q.trigger and q.trigger in text for q in wanted) or any(q.trigger and q.trigger in text for q in QUESTIONS):
            continue
        extra = generic_question(text)
        if extra is not None:
            wanted.append(extra)
    for question in QUESTIONS:  # 위 질문에 'Y'라고 답했을 때 이어서 묻는 질문
        if question.follows and any(q.item == question.follows and current.get(q.item, "").upper().startswith(("Y", "예", "해당"))
                                    for q in wanted + [_BY_ITEM[k] for k in current if k in _BY_ITEM]):
            wanted.append(question)
    return tuple(dict.fromkeys(wanted))


def judge(project: Stage2Project, assess: Callable[[IntakeData], Any] = assess_stage1_from_workbook) -> Outcome:
    unresolved_composition = composition_rows(project)
    if unresolved_composition:
        return Outcome(
            "COMPOSITION",
            ("각 제품이 단일물질인지 혼합물인지 확인하고, 혼합물은 SDS 제3항의 구성성분 CAS No.와 함량(%)을 입력해 주세요.",),
            composition_rows=tuple(unresolved_composition),
        )
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
