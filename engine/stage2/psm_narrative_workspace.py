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
from .intake import selected_requirement_specs

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
class Profile:
    """문서별 서술형 설정: 어떤 항목을 AI가 쓰고, 어떤 사실을 사람이 적는가."""
    system: str
    basic_facts: tuple
    decision_facts: tuple
    items: Any  # 항목 키 목록을 돌려주는 함수(project) -> tuple[str, ...]
    gates: Any = None  # {항목 키: (필요한 사실 키, 안내 문구)}


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
    Fact("business.operation_pattern", "운전 형태", "연속으로 운전하는지, 나누어(회분) 운전하는지 적습니다. (예시) 연속 운전, 회분식"),
    Fact("business.shift_pattern", "근무 형태", "교대 근무 방식입니다. (예시) 3조 3교대, 주간 상근"),
    Fact("business.process_count", "공정 수", "이 보고서에 포함되는 단위 공정의 수입니다."),
    Fact("business.employee_count", "근로자 수", "공정에서 일하는 근로자 수입니다."),
)
DECISION_FACTS = (
    Fact("psm.facts.training", "근로자 교육 결정 사항", "회사가 정한 교육 방식입니다. 프로그램이 알 수 없는 내용이라 직접 적습니다.", fields=(
        ("대상", "교육 대상", "교육을 받는 사람입니다. (예시) 신규 입사자, 공정 운전원, 정비원"),
        ("주기", "교육 주기", "얼마나 자주 교육하는지입니다. (예시) 신규 입사 시, 연 1회"),
        ("방법", "교육 방법", "어떻게 교육하는지입니다. (예시) 현장 실습, 강의, 사내 전산 교육"))),
    Fact("psm.facts.emergency_training", "비상조치 교육·훈련 결정 사항", "비상 상황 대비 교육·훈련 방식입니다.", fields=(
        ("대상", "교육 대상", "비상조치 교육을 받는 사람입니다."),
        ("주기", "훈련 주기", "(예시) 연 2회 비상 훈련"),
        ("방법", "훈련 방법", "(예시) 모의 누출 상황 대응 훈련"))),
    Fact("psm.facts.public_information", "주민 홍보 결정 사항", "인근 주민에게 알리는 방식입니다.", fields=(
        ("대상", "홍보 대상", "(예시) 사업장 반경 내 주민, 인근 학교"),
        ("방법", "홍보 방법", "(예시) 안내문 배포, 주민 설명회, 마을 방송"),
        ("주기", "홍보 주기", "(예시) 연 1회"))),
    Fact("psm.facts.emergency_org", "비상조직 구성", "사고가 났을 때 움직이는 조직입니다.", fields=(
        ("총괄", "비상 총괄", "비상 상황을 지휘하는 직책입니다. (예시) 공장장"),
        ("대응반", "대응반 구성", "(예시) 진화반, 구조반, 방재반, 홍보반과 담당 부서"),
        ("교대", "야간·휴일 대응", "야간이나 휴일에는 누가 맡는지 적습니다."))),
)


PSM_PROFILE = Profile(
    "PSM", BASIC_FACTS, DECISION_FACTS, lambda project: AI_ITEMS,
    {RISK_ITEM: (RISK_REPORT_KEY, "공정위험성평가 보고서를 첨부 자료에 올려야 만들 수 있습니다(대책은 평가 결과에서 나옵니다).")})


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def facts_value(project: Stage2Project, fact: Fact) -> Any:
    record = project.get_field(fact.key)
    if record is None:
        return {} if fact.fields else ""
    return record.value if fact.fields else _clean(record.value)


class ExampleMarkLeft(ValueError):
    """예시 표시가 남은 채로 저장하려 할 때."""


def _check_mark(fact: Fact, value: Any) -> None:
    texts = value.values() if isinstance(value, dict) else [value]
    if any(examples.has_mark(t) for t in texts):
        raise ExampleMarkLeft(f"'{fact.label}'에 '(예시)' 표시가 남아 있습니다. 우리 회사 내용으로 고치고 표시를 지운 뒤 저장하세요.")


def save_fact(project: Stage2Project, fact: Fact, value: Any) -> bool:
    """빈 입력은 저장하지 않는다(이미 적은 값을 지우지 않는다). '(예시)' 표시가 남은 글은 저장하지 않는다."""
    _check_mark(fact, value)
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


def chosen_as_is(project: Stage2Project, profile: Profile = PSM_PROFILE) -> list[str]:
    """예시를 고치지 않고 그대로 저장한 사실들. 회사 실제와 같은지 한 번 더 확인하도록 화면에서 알린다."""
    out = []
    for fact in (*profile.basic_facts, *profile.decision_facts):
        record = project.get_field(fact.key)
        if record is not None and "예시 문구를 고치지 않고" in (record.note or ""):
            out.append(fact.label)
    return out


def missing_basics(project: Stage2Project, profile: Profile = PSM_PROFILE) -> list[str]:
    return [f.label for f in profile.basic_facts if not facts_value(project, f)]


def _specs(project: Stage2Project, profile: Profile = PSM_PROFILE) -> dict[str, Any]:
    return {spec.key: spec for spec in selected_requirement_specs(project) if spec.system == profile.system}


def _confirmed(project: Stage2Project, key: str) -> bool:
    record = project.get_field(key)
    return record is not None and record.status in CONFIRMED_STATUSES and record.value not in (None, "", [], {})


def item_status(project: Stage2Project, profile: Profile = PSM_PROFILE) -> list[dict[str, Any]]:
    """서술형 항목별 상태: 만들 수 없음(이유) / 초안 만들기 가능 / 초안 있음 / 확인 완료."""
    specs = _specs(project, profile)
    try:
        draftable = {spec.key for spec in drafting.ai_draftable_specs(project, profile.system)}
    except ValueError:
        draftable = set()
    basics = missing_basics(project, profile)
    gates = profile.gates or {}
    out = []
    for key in profile.items(project):
        spec = specs.get(key)
        if spec is None:
            continue  # 이 사업장(예: 2군)에는 해당하지 않는 항목
        record = project.get_field(drafting.ai_draft_field_key(profile.system, key))
        draft = record.value.get("draft_text", "") if record is not None and isinstance(record.value, Mapping) else ""
        adopted = _confirmed(project, spec.field_keys[0]) and (
            record is not None and record.status == "USER_CONFIRMED")
        reason = ""
        if key in gates and not _confirmed(project, gates[key][0]):
            reason = gates[key][1]
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


def generatable_keys(project: Stage2Project, profile: Profile = PSM_PROFILE) -> list[str]:
    return [i["key"] for i in item_status(project, profile) if i["state"] == "초안 만들기 가능"]


def generate(project: Stage2Project, client, keys: list[str] | None = None, profile: Profile = PSM_PROFILE, progress=None):
    """확정된 사실만으로 초안을 만든다. 검증을 통과한 초안만 저장되고, 통과 못 한 것은 이유와 함께 돌려준다."""
    ready = generatable_keys(project, profile)
    wanted = [k for k in (keys or ready) if k in ready]
    if not wanted:
        raise ValueError("지금 초안을 만들 수 있는 항목이 없습니다. 먼저 필요한 사실을 적어 주세요.")
    return generate_system_ai_drafts_batched(project, profile.system, client, store_safe_drafts=True,
                                             requirement_keys=wanted, progress=progress)


def rejection_reason(warnings) -> str:
    """검증 경고를 담당자가 이해할 수 있는 이유와 해결 방법으로 바꾼다."""
    text = " / ".join(str(w) for w in warnings)
    if "다른 항목의 사실" in text:
        return "다른 항목에 적은 사실을 섞어 써서 저장하지 않았습니다. 다시 만들면 달라질 수 있습니다."
    if "수치" in text or "설비 Tag" in text or "CAS" in text:
        detail = text.split(":", 1)[-1].strip() if ":" in text else ""
        return f"입력하지 않은 숫자·설비번호({detail})가 들어가 저장하지 않았습니다. 다시 만들면 달라질 수 있습니다."
    if "초안을 반환하지" in text:
        return "AI가 본문을 돌려주지 않았습니다. 다시 만들어 보세요."
    if "내부" in text or "개발자" in text or "정식 용어" in text:
        return "사용할 수 없는 표현이 들어가 저장하지 않았습니다. 다시 만들면 달라질 수 있습니다."
    return "검증을 통과하지 못했습니다: " + text + " 다시 만들거나, 이 항목의 사실을 더 적어 보세요."


def rejected_rows(result) -> list[dict[str, str]]:
    return [{"label": item.label, "reason": rejection_reason(item.validation_warnings)} for item in result.rejected]


def adopt(project: Stage2Project, key: str, text: str | None = None, profile: Profile = PSM_PROFILE) -> None:
    """담당자가 초안을 확인·승인한다. 승인한 글을 보고서 서식이 읽는 자리에 회사 진술로 기록한다."""
    if key not in profile.items(project):
        raise ValueError(f"지원하지 않는 항목입니다: {key}")
    drafting.approve_ai_draft(project, profile.system, key, text)
    record = project.get_field(drafting.ai_draft_field_key(profile.system, key))
    final_text = _clean(record.value.get("draft_text"))
    spec = _specs(project, profile)[key]
    primary, *others = spec.field_keys
    project.set_field(primary, spec.label, final_text, "USER_CONFIRMED",
                      note="AI 초안을 담당자가 확인·승인해 회사 진술로 채택함")
    for other in others:  # 한 서술이 여러 칸을 함께 다루는 항목(자체감사·사고조사 등)
        record_other = project.get_field(other)
        if record_other is not None and isinstance(record_other.value, list):
            continue  # 표로 입력된 칸은 그대로 둔다(예: 방재 장비 표)
        project.set_field(other, spec.label, f"{spec.label} 본문에 함께 기술함", "USER_CONFIRMED",
                          note="같은 항목 본문에 포함")
