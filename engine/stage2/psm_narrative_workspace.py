from __future__ import annotations

"""PSM 서술형 항목: 사람은 프로그램이 알 수 없는 사실만 적고, 글은 확정된 사실로 AI가 초안을 쓴다.

- 사실 입력: 공정 개요, 운영 방식, 교육·홍보·비상조직 결정 사항(이 모듈의 FACTS), 비상장비·연락체계와 세안·보호구(표).
- AI 초안: 안전운전지침서, 설비점검·유지보수, 변경요소 관리, 자체감사·사고조사, 사고예방·피해 최소화대책,
  비상조직 임무·절차, 근로자 교육계획, 비상조치 교육계획, 주민홍보계획.
- 초안은 담당자가 확인·승인하기 전까지 AI_DRAFT다. 승인하면 그 글을 회사 진술로 채택한 것으로 보고 보고서 서식이 읽는 자리에 기록한다.
"""

from dataclasses import dataclass
from typing import Any, Mapping

from . import ai_drafting as drafting
from . import narrative_examples as examples
from .local_ai_resilience import generate_system_ai_drafts_batched
from .project import CONFIRMED_STATUSES, Stage2Project
from .requirements import psm_requirement_specs

SYSTEM = "PSM"
PROCESS_KEY = "process.description"
RISK_REPORT_KEY = "psm.risk.report"
RISK_ITEM = "psm.risk.mitigation"

AI_ITEMS = (
    "psm.operation.sop", "psm.operation.maintenance", "psm.operation.moc", "psm.operation.audit_incident",
    RISK_ITEM, "psm.emergency.roles", "psm.operation.training", "psm.emergency.training",
    "psm.emergency.public_information",
)


@dataclass(frozen=True)
class Fact:
    key: str
    label: str
    help: str
    long: bool = False
    fields: tuple[tuple[str, str, str], ...] = ()  # 묶음 사실이면 (이름, 라벨, 도움말)


BASIC_FACTS = (
    Fact(PROCESS_KEY, "공정 개요", "이 공정이 무엇을 어떻게 만드는지 3~5줄로 적습니다. 원료가 들어와서 어떤 설비를 거쳐 무엇이 나오는지 "
         "순서대로 적으면 됩니다. 공정설명서와 다른 서술형 항목의 바탕이 됩니다.", long=True),
    Fact("business.operation_pattern", "운전 형태", "연속으로 운전하는지, 나누어(회분) 운전하는지 적습니다. 예: 연속 운전, 회분식"),
    Fact("business.shift_pattern", "근무 형태", "교대 근무 방식입니다. 예: 3조 3교대, 주간 상근"),
    Fact("business.process_count", "공정 수", "이 보고서에 포함되는 단위 공정의 수입니다."),
    Fact("business.employee_count", "근로자 수", "공정에서 일하는 근로자 수입니다."),
)
DECISION_FACTS = (
    Fact("psm.facts.training", "근로자 교육 결정 사항", "회사가 정한 교육 방식입니다. 프로그램이 알 수 없는 내용이라 직접 적습니다.", fields=(
        ("대상", "교육 대상", "교육을 받는 사람입니다. 예: 신규 입사자, 공정 운전원, 정비원"),
        ("주기", "교육 주기", "얼마나 자주 교육하는지입니다. 예: 신규 입사 시, 연 1회"),
        ("방법", "교육 방법", "어떻게 교육하는지입니다. 예: 현장 실습, 강의, 사내 전산 교육"))),
    Fact("psm.facts.emergency_training", "비상조치 교육·훈련 결정 사항", "비상 상황 대비 교육·훈련 방식입니다.", fields=(
        ("대상", "교육 대상", "비상조치 교육을 받는 사람입니다."),
        ("주기", "훈련 주기", "예: 연 2회 비상 훈련"),
        ("방법", "훈련 방법", "예: 모의 누출 상황 대응 훈련"))),
    Fact("psm.facts.public_information", "주민 홍보 결정 사항", "인근 주민에게 알리는 방식입니다.", fields=(
        ("대상", "홍보 대상", "예: 사업장 반경 내 주민, 인근 학교"),
        ("방법", "홍보 방법", "예: 안내문 배포, 주민 설명회, 마을 방송"),
        ("주기", "홍보 주기", "예: 연 1회"))),
    Fact("psm.facts.emergency_org", "비상조직 구성", "사고가 났을 때 움직이는 조직입니다.", fields=(
        ("총괄", "비상 총괄", "비상 상황을 지휘하는 직책입니다. 예: 공장장"),
        ("대응반", "대응반 구성", "예: 진화반, 구조반, 방재반, 홍보반과 담당 부서"),
        ("교대", "야간·휴일 대응", "야간이나 휴일에는 누가 맡는지 적습니다."))),
)


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def facts_value(project: Stage2Project, fact: Fact) -> Any:
    record = project.get_field(fact.key)
    if record is None:
        return {} if fact.fields else ""
    return record.value if fact.fields else _clean(record.value)


def save_fact(project: Stage2Project, fact: Fact, value: Any) -> bool:
    """빈 입력은 저장하지 않는다(이미 적은 값을 지우지 않는다)."""
    if fact.fields:
        cleaned = {name: _clean(value.get(name)) for name, _, _ in fact.fields if _clean(value.get(name))}
        if not cleaned:
            return False
        as_is = [name for name, text in cleaned.items() if examples.is_example(fact.key, name, text)]
        project.set_field(fact.key, fact.label, cleaned, "USER_CONFIRMED", note=_as_is_note(as_is))
        return True
    text = _clean(value)
    if not text:
        return False
    as_is = [fact.label] if examples.is_example(fact.key, "", text) else []
    project.set_field(fact.key, fact.label, text, "USER_CONFIRMED", note=_as_is_note(as_is))
    return True


def _as_is_note(names: list[str]) -> str:
    return ("예시 문구를 고치지 않고 그대로 선택함(" + ", ".join(names) + "). 회사 실제와 같은지 확인 필요.") if names else ""


def chosen_as_is(project: Stage2Project) -> list[str]:
    """예시를 고치지 않고 그대로 저장한 사실들. 회사 실제와 같은지 한 번 더 확인하도록 화면에서 알린다."""
    out = []
    for fact in (*BASIC_FACTS, *DECISION_FACTS):
        record = project.get_field(fact.key)
        if record is not None and "예시 문구를 고치지 않고" in (record.note or ""):
            out.append(fact.label)
    return out


def missing_basics(project: Stage2Project) -> list[str]:
    return [f.label for f in BASIC_FACTS if not facts_value(project, f)]


def _specs(project: Stage2Project) -> dict[str, Any]:
    return {spec.key: spec for spec in psm_requirement_specs()}


def _confirmed(project: Stage2Project, key: str) -> bool:
    record = project.get_field(key)
    return record is not None and record.status in CONFIRMED_STATUSES and record.value not in (None, "", [], {})


def item_status(project: Stage2Project) -> list[dict[str, Any]]:
    """서술형 항목별 상태: 만들 수 없음(이유) / 초안 만들기 가능 / 초안 있음 / 확인 완료."""
    specs = _specs(project)
    try:
        draftable = {spec.key for spec in drafting.ai_draftable_specs(project, SYSTEM)}
    except ValueError:
        draftable = set()
    basics = missing_basics(project)
    out = []
    for key in AI_ITEMS:
        spec = specs[key]
        record = project.get_field(drafting.ai_draft_field_key(SYSTEM, key))
        draft = record.value.get("draft_text", "") if record is not None and isinstance(record.value, Mapping) else ""
        adopted = _confirmed(project, spec.field_keys[0]) and (
            record is not None and record.status == "USER_CONFIRMED")
        reason = ""
        if key == RISK_ITEM and not _confirmed(project, RISK_REPORT_KEY):
            reason = "공정위험성평가 보고서를 첨부 자료에 올려야 만들 수 있습니다(대책은 평가 결과에서 나옵니다)."
        elif basics:
            reason = "먼저 적어야 할 사실: " + ", ".join(basics)
        elif key not in draftable and not draft:
            reason = "설비·물질 등 확인된 사실이 아직 부족합니다."
        if adopted:
            state = "확인 완료"
        elif draft:
            state = "초안 있음"
        elif reason:
            state = "만들 수 없음"
        else:
            state = "초안 만들기 가능"
        out.append({"key": key, "label": spec.label, "section": spec.section, "state": state, "reason": reason,
                    "text": draft, "spec": spec, "warnings": ()})
    return out


def generatable_keys(project: Stage2Project) -> list[str]:
    return [i["key"] for i in item_status(project) if i["state"] == "초안 만들기 가능"]


def generate(project: Stage2Project, client, keys: list[str] | None = None):
    """확정된 사실만으로 초안을 만든다. 검증을 통과한 초안만 저장되고, 통과 못 한 것은 이유와 함께 돌려준다."""
    wanted = [k for k in (keys or generatable_keys(project)) if k in generatable_keys(project)]
    if not wanted:
        raise ValueError("지금 초안을 만들 수 있는 항목이 없습니다. 먼저 필요한 사실을 적어 주세요.")
    return generate_system_ai_drafts_batched(project, SYSTEM, client, store_safe_drafts=True, requirement_keys=wanted)


def adopt(project: Stage2Project, key: str, text: str | None = None) -> None:
    """담당자가 초안을 확인·승인한다. 승인한 글을 보고서 서식이 읽는 자리에 회사 진술로 기록한다."""
    if key not in AI_ITEMS:
        raise ValueError(f"지원하지 않는 항목입니다: {key}")
    drafting.approve_ai_draft(project, SYSTEM, key, text)
    record = project.get_field(drafting.ai_draft_field_key(SYSTEM, key))
    final_text = _clean(record.value.get("draft_text"))
    spec = _specs(project)[key]
    primary, *others = spec.field_keys
    project.set_field(primary, spec.label, final_text, "USER_CONFIRMED",
                      note="AI 초안을 담당자가 확인·승인해 회사 진술로 채택함")
    for other in others:  # 한 서술이 두 칸을 함께 다루는 항목(자체감사·사고조사)
        project.set_field(other, spec.label, f"{spec.label} 본문에 함께 기술함", "USER_CONFIRMED",
                          note="같은 항목 본문에 포함")
