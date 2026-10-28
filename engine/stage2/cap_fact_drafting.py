"""회사 파일에서 알아본 사실만으로 서술형 초안을 씁니다(화학사고예방관리계획서·공정안전보고서).

대상은 화학사고예방관리계획서 본문의 서술형 장(사전관리방침, 내부 비상대응계획, 1군의 외부 비상대응계획)과
공정안전보고서의 서술형 항목(안전운전지침서, 설비점검·유지보수, 변경요소 관리, 교육·비상조치·주민홍보 계획 등)입니다.
- 회사 비상대응계획 파일에 그 항목의 글이 있으면(사실 카탈로그 ‘별지 제16호’ 서술) 그 글을 그대로 씁니다.
- 없으면 그 항목의 회사 결정사항(책임자·주기·방법 등, 파일에서 읽은 값)만으로 초안을 만듭니다.
  로컬 AI가 있으면 문장을 다듬고, 없으면 규칙으로 문장을 잇습니다.
- 근거가 없는 부분은 지어내지 않고 ‘[확인 필요: …]’로 남깁니다. AI 문장에 근거 자료에 없는 숫자·설비번호·CAS 번호가
  나오면 그 자리도 ‘[확인 필요]’로 바꿉니다.

초안은 기존 AI 초안 기록(ai_draft.cap.<항목>, ai_draft.psm.<항목>)에 저장되어 ‘AI 작성 항목’ 점검표·검증정보에 나타나고,
초안 문서의 서술형 장에 ‘AI 초안’ 표시와 함께 들어갑니다(사람이 내려받은 문서에서 고칩니다).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Callable

from . import ai_drafting as drafting
from . import cap_fact_catalog as catalog
from . import evidence_workspace as ew
from .cap_fact_status import where
from .cap_narrative_workspace import SECTIONS
from .intake import selected_requirement_specs
from .language_policy import normalize_public_prose
from .project import CONFIRMED_STATUSES, Stage2Project

RULE_MODEL = "규칙 초안(AI 없이 사실만 이어 씀)"
CHECK = "[확인 필요: {}]"
FROM_FILE = "회사 문서에서 읽음"
HAS_DRAFT = "초안 있음"
CAN_DRAFT = "초안 만들기 가능"
NO_BASIS = "근거 부족"
_EXTRA_INSTRUCTIONS = (
    " 이번 요청의 facts는 회사 파일에서 읽은 값뿐이다. facts에 없는 내용은 쓰지 않는다. "
    "missing에 있는 항목은 본문에 '[확인 필요: 항목 이름]'으로 남긴다. "
    "응답은 {\"draft_text\": \"...\"} 형식의 JSON 객체 하나다."
)


@dataclass
class Basis:
    label: str
    value: str
    source: str
    fact_id: str


@dataclass
class Item:
    system: str
    key: str
    label: str
    section: str
    field_key: str
    request: str
    company_text: str = ""
    company_source: str = ""
    basis: list[Basis] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    general: list[Basis] = field(default_factory=list)
    state: str = NO_BASIS
    draft: str = ""
    stale: bool = False          # 파일을 새로 올려 예전 초안이 보류됨(다시 만들어야 함)


def _site_facts(project: Stage2Project) -> dict[str, dict[str, Any]]:
    out = {}
    for slot in ew.slots(project):
        if slot["entity"] == ew.SITE_ENTITY and slot["chosen"]:
            out[slot["field"]] = slot["chosen"]
    return out


def _general(project: Stage2Project, site: dict[str, dict[str, Any]]) -> list[Basis]:
    """모든 서술형 항목이 함께 쓸 수 있는 사업장 사실(파일에서 읽은 것만)."""
    out = [Basis("사업장명", project.company_name, "사업장 만들 때 입력", "site.company_name")]
    for field_name, label, fact_id in (("operation_pattern", "운전 형태", "psm.operation_pattern"),
                                       ("shift_pattern", "근무 형태", "psm.shift_pattern"),
                                       ("employee_count", "근로자 수", "psm.employee_count"),
                                       ("process_count", "공정 수", "psm.process_count")):
        if field_name in site:
            out.append(Basis(label, str(site[field_name]["value"]), where(site[field_name]), fact_id))
    if project.cap_group in {"1군", "2군"}:
        out.append(Basis("작성수준", project.cap_group, "사업장 판정", "legal.writing_level"))
    process = site.get("process_description")
    if process:
        out.append(Basis("공정개요", str(process["value"]), where(process), "narrative.process_description"))
    entities = ew.confirmed_entities(project)
    facilities = sorted(e for e in entities if e.startswith("facility:"))
    if facilities:
        names = [f"{entities[e].get('name', '')} ({e.split(':', 1)[1]})".strip() for e in facilities]
        out.append(Basis("취급시설", ", ".join(names), "설비 목록", "facility.name"))
    materials = sorted(e for e in entities if e.startswith("material:"))
    if materials:
        out.append(Basis("취급 물질", ", ".join(str(entities[e].get("name") or e.split(":", 1)[1]) for e in materials),
                         "물질 목록", "material.name"))
    detectors = sorted(e for e in entities if e.startswith("detector:"))
    if detectors:
        out.append(Basis("고정식 가스감지기", ", ".join(e.split(":", 1)[1] for e in detectors), "가스감지기 명세", "detector.id"))
    return out


def _draft_record(project, system, key):
    return project.get_field(drafting.ai_draft_field_key(system, key))


def systems(project: Stage2Project) -> tuple[str, ...]:
    """서술형 초안을 만들 문서(작성범위에 든 것)."""
    return tuple(s for s, on in (("CAP", project.cap_in_scope), ("PSM", project.psm_in_scope)) if on)


def _wanted_spec(project, spec, system) -> bool:
    if spec.system != system:
        return False
    if system == "CAP":
        return spec.section.startswith(SECTIONS)
    from .psm_narrative_workspace import PSM_PROFILE
    return spec.key in PSM_PROFILE.items(project)


def _owns(fact, owner: str):
    """이 결정사항 사실이 항목의 사실 키(owner)에 들어가면 그 칸 이름, 아니면 None."""
    for key, column in [(fact.field_key, fact.column)] + list(fact.targets):
        if key == owner and column:
            return column
    return None


def input_facts(spec) -> list[catalog.Fact]:
    """서술형 결과물 대신 회사에 요청할 단답형 근거 사실."""
    if spec.system != "CAP" or not spec.section.startswith(SECTIONS):
        return []
    owner = drafting.typed_fact_owner(spec.key)
    return [fact for fact in catalog.facts(kinds=["narrative"])
            if owner and _owns(fact, owner) is not None]


def input_requirement_keys(group: str = "") -> set[str]:
    from .requirements import cap_requirement_specs
    return {spec.key for spec in cap_requirement_specs(group or "1군") if input_facts(spec)}


def generated_fact_ids(group: str = "") -> set[str]:
    """기존 완성 문장은 읽되 새 양식이나 보완 목록에서 제출을 요구하지 않습니다."""
    from .requirements import cap_requirement_specs
    fields = {key for spec in cap_requirement_specs(group or "1군") if input_facts(spec)
              for key in spec.field_keys}
    return {f.id for f in catalog.facts(kinds=["narrative"])
            if not f.column and f.field_key in fields}


def items(project: Stage2Project, system: str = "CAP") -> list[Item]:
    """이 사업장의 서술형 항목과 각각의 근거 사실(화학사고예방관리계획서는 1군·2군에 맞춰)."""
    site = _site_facts(project)
    general = _general(project, site)
    narrative = catalog.facts(kinds=["narrative"])
    out = []
    for spec in selected_requirement_specs(project):
        if not _wanted_spec(project, spec, system):
            continue
        item = Item(system, spec.key, spec.label, spec.section, spec.field_keys[0], spec.request_text or spec.description,
                    general=general)
        for fact in narrative:
            if fact.field_key in spec.field_keys and not fact.column and fact.evidence_field in site:
                chosen = site[fact.evidence_field]
                item.company_text = str(chosen["value"]).strip()
                item.company_source = where(chosen)
        owner = drafting.typed_fact_owner(spec.key)
        for fact in narrative:
            if not owner or _owns(fact, owner) is None:
                continue
            chosen = site.get(fact.evidence_field)
            if chosen:
                item.basis.append(Basis(fact.name, str(chosen["value"]).strip(), where(chosen), fact.id))
            else:
                item.missing.append(fact.name)
        record = _draft_record(project, system, spec.key)
        if record is not None and isinstance(record.value, dict) and str(record.value.get("draft_text") or "").strip():
            if record.status in ("AI_DRAFT", "USER_CONFIRMED"):
                item.draft = str(record.value.get("draft_text") or "")
            else:
                item.stale = True
        if item.company_text:
            item.state = FROM_FILE
        elif item.draft:
            item.state = HAS_DRAFT
        elif item.basis:
            item.state = CAN_DRAFT
        out.append(item)
    return out


def rule_draft(item: Item) -> str:
    """AI 없이 근거 사실만 이어 쓴 초안. 근거가 없는 칸은 [확인 필요]로 남깁니다."""
    if item.company_text:
        return item.company_text
    company = next((b.value for b in item.general if b.fact_id == "site.company_name"), "") or "사업장"
    lines = [f"{company}의 {item.label}은(는) 다음과 같다."]
    for basis in item.basis:
        lines.append(f"- {basis.label}: {basis.value}")
    for label in item.missing:
        lines.append(f"- {label}: " + CHECK.format(label))
    if not item.basis and not item.missing:
        where_to = "안전관리·비상대응계획" if item.system == "CAP" else "공정안전 운영·비상조치 계획"
        lines.append(CHECK.format(f"{item.label}에 대한 회사 자료가 없습니다. {where_to} 파일에 이 항목을 적어 올려 주세요"))
    return "\n".join(lines)


def _corpus(item: Item) -> str:
    return json.dumps([[b.label, b.value] for b in item.basis + item.general] + [item.label, item.request],
                      ensure_ascii=False)


def sanitize(text: str, item: Item) -> tuple[str, list[str]]:
    """근거에 없는 숫자·설비번호·CAS를 [확인 필요]로 바꾸고, 빠진 항목 표시를 보탭니다. (본문, 바꾼 것 목록)"""
    text = drafting.drop_fabricated_claims(normalize_public_prose(text.strip(), item.system))
    source = _corpus(item)
    spans = []          # (시작, 끝, 글자) — CAS·설비번호를 숫자보다 먼저 잡고, 겹치는 것은 한 번만
    for regex in (drafting._CAS_RE, drafting._TAG_RE, drafting._NUMBER_RE):
        known = {token.replace(" ", "") for token in regex.findall(source)}
        for match in regex.finditer(text):
            token = match.group(0)
            if token.replace(" ", "") in known or any(s0 < match.end() and match.start() < e0 for s0, e0, _ in spans):
                if token.replace(" ", "") in known:
                    spans.append((match.start(), match.end(), None))     # 근거 있는 값: 이 자리는 다시 보지 않음
                continue
            spans.append((match.start(), match.end(), token))
    replaced, pieces, last = [], [], 0
    for start, end, token in sorted(spans):
        if token is None or start < last:
            continue
        pieces.append(text[last:start])
        pieces.append(CHECK.format(f"근거 자료에 없는 값 ‘{token}’"))
        replaced.append(token)
        last = end
    text = "".join(pieces) + text[last:]
    for label in item.missing:
        if label not in text:
            text += "\n" + f"- {label}: " + CHECK.format(label)
    return text.strip(), replaced


def ai_draft(item: Item, client) -> tuple[str, list[str]]:
    payload = {"item": item.label, "section": item.section, "writing_request": item.request,
               "facts": [{"항목": b.label, "값": b.value} for b in item.basis + item.general],
               "missing": item.missing}
    instructions = drafting._system_prompt(item.system) + _EXTRA_INSTRUCTIONS
    result = client.generate_json(instructions=instructions, prompt=json.dumps(payload, ensure_ascii=False))
    text = str((result or {}).get("draft_text") or "").strip()
    if not text:
        raise ValueError("AI가 본문을 돌려주지 않았습니다.")
    return sanitize(text, item)


def _store(project: Stage2Project, item: Item, text: str, model: str) -> None:
    draft = drafting.AIDraftItem(
        system=item.system, requirement_key=item.key, section=item.section, label=item.label, draft_text=text,
        profile_summary="회사 파일에서 읽은 사실만으로 쓴 서술형 초안", suggested_additions=tuple(item.missing),
        used_fact_keys=tuple(b.fact_id for b in item.basis), legal_basis="", model=model)
    drafting.store_ai_draft(project, draft)
    record = project.get_field(drafting.ai_draft_field_key(item.system, item.key))
    value = dict(record.value)
    value["basis"] = [{"항목": b.label, "값": b.value, "출처": b.source} for b in item.basis]
    value["from_catalog_facts"] = True
    project.set_field(record.key, record.label, value, record.status,
                      note="회사 파일에서 읽은 사실만 쓴 서술형 초안. 근거가 없는 부분은 [확인 필요]로 남김.")


def generate(project: Stage2Project, client=None, keys: list[str] | None = None, *, refresh: bool = False,
             system: str | None = None,
             on_progress: Callable[[int, int, str], None] | None = None) -> list[dict[str, Any]]:
    """근거가 있는 항목의 초안을 만듭니다(회사 문서에서 읽은 항목은 건너뜀). AI가 실패하면 규칙 초안으로 대신합니다.
    이미 초안이 있는 항목은 refresh=True이거나 keys로 고른 경우에만 다시 만듭니다. system이 없으면 작성범위의 모든 문서."""
    results = []
    pending = [i for s in ((system,) if system else systems(project) or ("CAP",)) for i in items(project, s)
               if (keys is None or i.key in keys) and i.state != FROM_FILE and i.basis
               and not (i.state == HAS_DRAFT and not refresh and keys is None)]
    total = len(pending)
    if on_progress:
        on_progress(0, total, "")
    for index, item in enumerate(pending):
        if on_progress:
            on_progress(index, total, item.label)
        model, replaced, note = RULE_MODEL, [], ""
        text = rule_draft(item)
        if client is not None:
            try:
                text, replaced = ai_draft(item, client)
                model = getattr(client, "model", "로컬 AI")
            except Exception as exc:       # AI가 안 되면 사실만 이은 초안으로
                note = f"AI 문장을 만들지 못해 규칙 초안을 썼습니다({type(exc).__name__})."
                text = rule_draft(item)
        _store(project, item, text, model)
        results.append({"key": item.key, "label": item.label, "model": model, "replaced": replaced, "note": note,
                        "checks": text.count("[확인 필요")})
        if on_progress:
            on_progress(index + 1, total, "")
    return results


def refresh_rule_drafts(project: Stage2Project) -> int:
    """초안이 없거나(새 근거) 파일을 새로 올려 보류된 항목만 규칙 초안으로 다시 씁니다. 만든 수를 돌려줍니다.
    파일을 올리면 프로그램이 서식을 채우듯, 서술형도 근거 사실이 있으면 바로 초안이 생기게 합니다(AI 다듬기는 따로)."""
    made = 0
    for system in systems(project):
        wanted = [item.key for item in items(project, system) if item.state == CAN_DRAFT]
        if wanted:
            made += len(generate(project, None, keys=wanted, system=system))
    return made


def check_count(text: str) -> int:
    return len(re.findall(r"\[확인 필요", text or ""))


def rows(project: Stage2Project, system: str = "CAP") -> list[dict[str, Any]]:
    """화면 표: 항목·상태·근거·확인 필요 수."""
    out = []
    for item in items(project, system):
        if item.state == FROM_FILE:
            basis = item.company_source
        else:
            basis = ", ".join(f"{b.label}" for b in item.basis) or "-"
        state = "자료가 바뀌어 다시 만들어야 함" if item.stale and item.state == CAN_DRAFT else item.state
        out.append({"항목": item.label, "상태": state, "근거 사실": basis,
                    "확인 필요": check_count(item.draft) if item.state == HAS_DRAFT else
                    (len(item.missing) if item.state == CAN_DRAFT else ""),
                    "_key": item.key})
    return out


def confirmed_company_value(project: Stage2Project, key: str) -> bool:
    record = project.get_field(key)
    return record is not None and record.status in CONFIRMED_STATUSES and record.value not in (None, "", [], {})
