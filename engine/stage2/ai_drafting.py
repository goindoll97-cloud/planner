from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import re
from typing import Any, Mapping, Protocol

import requests

from .intake import selected_requirement_specs
from .project import CONFIRMED_STATUSES, Stage2Project
from .requirements import RequirementSpec


SYSTEM_LABELS = {
    "PSM": "공정안전보고서",
    "CAP": "화학사고예방관리계획서",
}
DEFAULT_MODEL = "gpt-5.6-terra"
DEFAULT_API_URL = "https://api.openai.com/v1/responses"

_ATTACHMENT_TOKENS = ("DRAWING", "DOCUMENT_SET", "ATTACHMENT")
_TABLE_ONLY_TOKENS = ("STRUCTURED_TABLE", "TABLE_AND_CALCULATION")
_TAG_RE = re.compile(r"\b[A-Z]{1,8}[-_]\d{1,6}\b")
_CAS_RE = re.compile(r"\b\d{2,7}-\d{2}-\d\b")
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])\d+(?:\.\d+)?(?:\s*(?:%|ppm|ppb|kg|g|ton|t|L|m³|Nm³|MPa|kPa|bar|℃|°C|m/s|m|km|h|hr|시간|분|회|명|대|세트|개소|병상|yr))?"
)


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    model: str = DEFAULT_MODEL
    api_url: str = DEFAULT_API_URL
    timeout_seconds: int = 90
    max_output_tokens: int = 12000


@dataclass(frozen=True)
class AIDraftItem:
    system: str
    requirement_key: str
    section: str
    label: str
    draft_text: str
    profile_summary: str
    suggested_additions: tuple[str, ...]
    used_fact_keys: tuple[str, ...]
    legal_basis: str
    model: str
    validation_warnings: tuple[str, ...] = ()

    @property
    def safe_to_store(self) -> bool:
        return not self.validation_warnings


@dataclass(frozen=True)
class AIDraftPackResult:
    system: str
    system_label: str
    profile_summary: str
    generated: tuple[AIDraftItem, ...]
    rejected: tuple[AIDraftItem, ...]
    skipped_requirement_keys: tuple[str, ...]
    model: str


class JSONLLMClient(Protocol):
    model: str

    def generate_json(self, *, instructions: str, prompt: str) -> Mapping[str, Any]: ...


class OpenAIResponsesClient:
    """Small HTTP client for the Responses API.

    API keys are supplied at runtime through Streamlit secrets or environment
    variables. No credential is persisted in the Stage-2 project or repository.
    """

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.model = config.model

    def generate_json(self, *, instructions: str, prompt: str) -> Mapping[str, Any]:
        response = requests.post(
            self.config.api_url,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.model,
                "instructions": instructions,
                "input": prompt,
                "max_output_tokens": self.config.max_output_tokens,
            },
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        raw = response.json()
        text = _extract_response_text(raw)
        return _parse_json_object(text)


def llm_config_from_sources(values: Mapping[str, Any] | None = None) -> LLMConfig | None:
    values = values or {}

    def _get(name: str, default: str = "") -> str:
        value = values.get(name)
        if value not in (None, ""):
            return str(value).strip()
        return str(os.getenv(name, default) or "").strip()

    api_key = _get("OPENAI_API_KEY")
    if not api_key:
        return None
    model = _get("OPENAI_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL
    api_url = _get("OPENAI_RESPONSES_URL", DEFAULT_API_URL) or DEFAULT_API_URL
    timeout_raw = _get("OPENAI_TIMEOUT_SECONDS", "90")
    max_tokens_raw = _get("OPENAI_MAX_OUTPUT_TOKENS", "12000")
    try:
        timeout = max(10, int(timeout_raw))
    except ValueError:
        timeout = 90
    try:
        max_tokens = max(1000, int(max_tokens_raw))
    except ValueError:
        max_tokens = 12000
    return LLMConfig(
        api_key=api_key,
        model=model,
        api_url=api_url,
        timeout_seconds=timeout,
        max_output_tokens=max_tokens,
    )


def _extract_response_text(raw: Mapping[str, Any]) -> str:
    direct = raw.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    chunks: list[str] = []
    output = raw.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, Mapping):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
    if chunks:
        return "\n".join(chunks)

    # Compatibility with chat-completions-shaped gateways.
    choices = raw.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, Mapping):
            message = first.get("message")
            if isinstance(message, Mapping) and isinstance(message.get("content"), str):
                return str(message["content"]).strip()

    raise ValueError("LLM 응답에서 텍스트 출력을 찾지 못했습니다.")


def _parse_json_object(text: str) -> Mapping[str, Any]:
    source = str(text or "").strip()
    if source.startswith("```"):
        source = re.sub(r"^```(?:json)?\s*", "", source, flags=re.I)
        source = re.sub(r"\s*```$", "", source)
    try:
        data = json.loads(source)
    except json.JSONDecodeError:
        start = source.find("{")
        end = source.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("LLM 응답이 JSON 객체 형식이 아닙니다.")
        data = json.loads(source[start : end + 1])
    if not isinstance(data, Mapping):
        raise ValueError("LLM 응답 JSON의 최상위 값은 객체여야 합니다.")
    return data


def _compact_value(value: Any, *, max_rows: int = 20, max_chars: int = 8000) -> Any:
    if isinstance(value, list):
        compact = [_compact_value(item, max_rows=max_rows, max_chars=max_chars) for item in value[:max_rows]]
        if len(value) > max_rows:
            compact.append({"_omitted_rows": len(value) - max_rows})
        return compact
    if isinstance(value, Mapping):
        return {str(k): _compact_value(v, max_rows=max_rows, max_chars=max_chars) for k, v in value.items()}
    if isinstance(value, str) and len(value) > max_chars:
        return value[:max_chars] + "…[truncated]"
    return value


def _nonempty(value: Any) -> bool:
    return value not in (None, "", [], {})


def _confirmed_facts(project: Stage2Project) -> dict[str, dict[str, Any]]:
    facts: dict[str, dict[str, Any]] = {}
    for key, record in project.fields.items():
        if key.startswith("ai_draft."):
            continue
        if record.status not in CONFIRMED_STATUSES or not _nonempty(record.value):
            continue
        facts[key] = {
            "label": record.label,
            "value": _compact_value(record.value),
            "status": record.status,
        }
    return facts


def _count_rows(facts: Mapping[str, Mapping[str, Any]], *keys: str) -> int:
    counts: list[int] = []
    for key in keys:
        item = facts.get(key)
        value = item.get("value") if item else None
        if isinstance(value, list):
            counts.append(len([row for row in value if not (isinstance(row, Mapping) and "_omitted_rows" in row)]))
    return max(counts, default=0)


def build_operating_profile(project: Stage2Project) -> dict[str, Any]:
    facts = _confirmed_facts(project)
    chemical_names: list[str] = []
    chemical_record = facts.get("inventory.chemicals") or facts.get("cap.chemical.details")
    value = chemical_record.get("value") if chemical_record else None
    if isinstance(value, list):
        for row in value[:20]:
            if not isinstance(row, Mapping):
                continue
            for key in ("물질명", "화학물질명", "제품명"):
                name = str(row.get(key) or "").strip()
                if name and name not in chemical_names:
                    chemical_names.append(name)
                    break

    return {
        "company_name": (facts.get("business.company_name") or {}).get("value") or project.company_name,
        "site_name": (facts.get("business.site_name") or {}).get("value") or project.site_name,
        "cap_group": project.cap_group,
        "psm_in_scope": project.psm_in_scope,
        "cap_in_scope": project.cap_in_scope,
        "chemical_count": _count_rows(facts, "inventory.chemicals", "cap.chemical.details"),
        "major_chemical_names": chemical_names[:12],
        "facility_count": _count_rows(facts, "inventory.facilities", "psm.psi.equipment_specs", "cap.facility.equipment_specs"),
        "relief_device_count": _count_rows(facts, "psm.psi.relief_device_specs", "cap.safety.relief_device_specs"),
        "gas_detector_count": _count_rows(facts, "psm.psi.gas_detection", "cap.safety.gas_detection"),
        "machinery_count": _count_rows(facts, "psm.psi.machinery_list"),
        "has_process_description": "process.description" in facts,
        "operation_pattern": (facts.get("business.operation_pattern") or {}).get("value", ""),
        "shift_pattern": (facts.get("business.shift_pattern") or {}).get("value", ""),
        "employee_count": (facts.get("business.employee_count") or {}).get("value", ""),
        "process_count": (facts.get("business.process_count") or {}).get("value", ""),
    }


def _normalize_system(system: str) -> str:
    value = str(system or "").strip().upper()
    if value not in SYSTEM_LABELS:
        raise ValueError(f"지원하지 않는 보고서 종류입니다: {system}")
    return value


def _selected_for_system(project: Stage2Project, system: str) -> bool:
    return (system == "PSM" and project.psm_in_scope) or (system == "CAP" and project.cap_in_scope)


def ai_draft_field_key(system: str, requirement_key: str) -> str:
    system = _normalize_system(system)
    return f"ai_draft.{system.lower()}.{requirement_key}"


def _eligible_spec(project: Stage2Project, spec: RequirementSpec) -> bool:
    kind = str(spec.input_kind or "").upper()
    if any(token in kind for token in _ATTACHMENT_TOKENS):
        return False
    if any(token in kind for token in _TABLE_ONLY_TOKENS):
        return False
    if not spec.field_keys:
        return False
    for key in spec.field_keys:
        record = project.get_field(key)
        if record and record.status in CONFIRMED_STATUSES and _nonempty(record.value):
            return True
    return False


def ai_draftable_specs(project: Stage2Project, system: str) -> list[RequirementSpec]:
    system = _normalize_system(system)
    if not _selected_for_system(project, system):
        raise ValueError(f"현재 작성범위에 {SYSTEM_LABELS[system]}이(가) 포함되어 있지 않습니다.")
    return [
        spec
        for spec in selected_requirement_specs(project)
        if spec.system == system and _eligible_spec(project, spec)
    ]


def _fact_keys_for_spec(project: Stage2Project, spec: RequirementSpec) -> list[str]:
    result: list[str] = []
    for key in spec.field_keys:
        record = project.get_field(key)
        if record and record.status in CONFIRMED_STATUSES and _nonempty(record.value):
            result.append(key)
    return result


def _system_prompt() -> str:
    return (
        "당신은 대한민국 화학안전 규제문서의 문장작성 보조자다. 법적 적용 여부와 1군·2군 판단은 이미 Rule Engine이 확정했으므로 절대 재판단하지 않는다. "
        "회사 사실은 제공된 VERIFIED/USER_CONFIRMED/CALCULATED 자료만 사용한다. 제공되지 않은 수치, 설비, 인원, 주기, 연락처, 절차, 성능, 위치, 물질, 법적 의무를 절대 만들어내지 않는다. "
        "법적 근거와 작성요건은 회사 사실이 아니며, 공식 용어와 작성목적을 자연스럽게 설명하는 데만 사용한다. "
        "확인되지 않은 내용이 필요하면 본문에 추정해 넣지 말고 suggested_additions에 확인 질문으로 남긴다. "
        "2군 사업장에서는 제공된 작성항목 밖의 외부 비상대응계획을 생성하지 않는다. "
        "draft_text는 실제 보고서에 사용할 수 있는 자연스러운 한국어 문장으로 작성하되, 사실을 부풀리거나 사업장 규모를 과장하지 않는다. "
        "응답은 반드시 JSON 객체만 반환한다."
    )


def _build_pack_prompt(project: Stage2Project, system: str, specs: list[RequirementSpec]) -> tuple[str, dict[str, Any]]:
    facts = _confirmed_facts(project)
    profile = build_operating_profile(project)
    items: list[dict[str, Any]] = []
    used_fact_keys: set[str] = set()

    for spec in specs:
        keys = _fact_keys_for_spec(project, spec)
        used_fact_keys.update(keys)
        items.append({
            "requirement_key": spec.key,
            "section": spec.section,
            "label": spec.label,
            "input_kind": spec.input_kind,
            "legal_basis": spec.legal_basis,
            "writing_request": spec.request_text or spec.description,
            "suggested_evidence": list(spec.suggested_evidence),
            "confirmed_fact_keys": keys,
            "confirmed_facts": {key: facts[key] for key in keys if key in facts},
        })

    # A limited global context helps the model tailor tone/scale without allowing
    # it to invent site facts. Every global fact remains provenance-addressable.
    global_keys = [
        key for key in (
            "business.company_name", "business.address", "business.employee_count",
            "business.operation_pattern", "business.shift_pattern", "business.process_count",
            "inventory.chemicals", "inventory.facilities", "process.description",
            "psm.psi.equipment_specs", "cap.facility.equipment_specs",
            "psm.psi.relief_device_specs", "cap.safety.relief_device_specs",
            "psm.psi.gas_detection", "cap.safety.gas_detection",
        ) if key in facts
    ]
    used_fact_keys.update(global_keys)

    payload = {
        "document": SYSTEM_LABELS[system],
        "fixed_legal_scope": {
            "cap_group": project.cap_group if system == "CAP" else "",
            "psm_in_scope": project.psm_in_scope,
            "cap_in_scope": project.cap_in_scope,
        },
        "operating_profile": profile,
        "global_confirmed_facts": {key: facts[key] for key in global_keys},
        "draft_items": items,
        "output_contract": {
            "profile_summary": "입력 사실에서 직접 관찰되는 사업장 운영·위험 특성 요약. 추정 금지.",
            "drafts": [
                {
                    "requirement_key": "입력된 requirement_key와 정확히 동일",
                    "draft_text": "회사 사실 + 제공된 공식 작성맥락만으로 다듬은 보고서 문장",
                    "suggested_additions": ["회사 확인이 필요한 추가 정보. 본문에는 넣지 않음"],
                    "used_fact_keys": ["실제로 사용한 confirmed_fact_keys 또는 global fact key"],
                }
            ],
        },
    }
    prompt = (
        "아래 JSON은 이미 법적 작성범위가 확정된 사업장의 확인자료다. 사업장 규모와 위험 특성에 맞춰 각 항목의 문장을 보강하라. "
        "연결어, 법적 목적을 설명하는 일반적 표현, 문서체 정리는 허용하지만 새로운 회사 사실을 추가하면 안 된다. "
        "내용이 부족하면 suggested_additions에만 적고 draft_text에서 단정하지 마라. 숫자·설비 Tag·CAS·횟수·기간은 입력 JSON에 있는 값만 사용할 수 있다.\n\n"
        + json.dumps(payload, ensure_ascii=False, default=str)
    )
    return prompt, {key: facts[key] for key in used_fact_keys if key in facts}


def _source_corpus(project: Stage2Project, spec: RequirementSpec, facts: Mapping[str, Any]) -> str:
    source = {
        "cap_group": project.cap_group,
        "legal_basis": spec.legal_basis,
        "request": spec.request_text or spec.description,
        "facts": facts,
    }
    return json.dumps(source, ensure_ascii=False, default=str)


def _unsupported_tokens(draft_text: str, source_corpus: str) -> list[str]:
    warnings: list[str] = []
    for label, regex in (("수치", _NUMBER_RE), ("설비 Tag", _TAG_RE), ("CAS", _CAS_RE)):
        source_tokens = {token.replace(" ", "") for token in regex.findall(source_corpus)}
        draft_tokens = {token.replace(" ", "") for token in regex.findall(draft_text)}
        extra = sorted(token for token in draft_tokens if token not in source_tokens)
        if extra:
            warnings.append(f"확인자료에 없는 {label}: {', '.join(extra[:8])}")
    return warnings


def _normalize_suggestions(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    result: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            topic = str(item.get("topic") or item.get("label") or "").strip()
            reason = str(item.get("reason") or "").strip()
            text = " — ".join(part for part in (topic, reason) if part)
        else:
            text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _normalize_fact_keys(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def generate_system_ai_drafts(
    project: Stage2Project,
    system: str,
    client: JSONLLMClient,
    *,
    store_safe_drafts: bool = True,
) -> AIDraftPackResult:
    system = _normalize_system(system)
    specs = ai_draftable_specs(project, system)
    all_system_specs = [spec for spec in selected_requirement_specs(project) if spec.system == system]
    skipped = tuple(spec.key for spec in all_system_specs if spec not in specs)
    if not specs:
        raise ValueError("AI 문장 보강에 사용할 확인된 회사 사실이 없습니다.")

    prompt, global_facts = _build_pack_prompt(project, system, specs)
    raw = client.generate_json(instructions=_system_prompt(), prompt=prompt)
    profile_summary = str(raw.get("profile_summary") or "").strip()
    draft_rows = raw.get("drafts")
    if not isinstance(draft_rows, list):
        raise ValueError("LLM 응답에 drafts 배열이 없습니다.")

    spec_map = {spec.key: spec for spec in specs}
    generated: list[AIDraftItem] = []
    rejected: list[AIDraftItem] = []
    seen: set[str] = set()

    for row in draft_rows:
        if not isinstance(row, Mapping):
            continue
        requirement_key = str(row.get("requirement_key") or "").strip()
        spec = spec_map.get(requirement_key)
        if spec is None or requirement_key in seen:
            continue
        seen.add(requirement_key)
        draft_text = str(row.get("draft_text") or "").strip()
        suggestions = _normalize_suggestions(row.get("suggested_additions"))
        used_fact_keys = _normalize_fact_keys(row.get("used_fact_keys"))
        warnings: list[str] = []
        if not draft_text:
            warnings.append("LLM이 본문 초안을 반환하지 않았습니다.")

        allowed_keys = set(global_facts)
        unknown_keys = sorted(key for key in used_fact_keys if key not in allowed_keys)
        if unknown_keys:
            warnings.append("확인되지 않은 fact key를 참조함: " + ", ".join(unknown_keys[:8]))

        source = _source_corpus(project, spec, global_facts)
        warnings.extend(_unsupported_tokens(draft_text, source))

        item = AIDraftItem(
            system=system,
            requirement_key=spec.key,
            section=spec.section,
            label=spec.label,
            draft_text=draft_text,
            profile_summary=profile_summary,
            suggested_additions=suggestions,
            used_fact_keys=used_fact_keys,
            legal_basis=spec.legal_basis,
            model=getattr(client, "model", "LLM"),
            validation_warnings=tuple(dict.fromkeys(warnings)),
        )
        if item.safe_to_store:
            generated.append(item)
            if store_safe_drafts:
                store_ai_draft(project, item)
        else:
            rejected.append(item)

    return AIDraftPackResult(
        system=system,
        system_label=SYSTEM_LABELS[system],
        profile_summary=profile_summary,
        generated=tuple(generated),
        rejected=tuple(rejected),
        skipped_requirement_keys=skipped,
        model=getattr(client, "model", "LLM"),
    )


def store_ai_draft(project: Stage2Project, item: AIDraftItem) -> str:
    if not item.safe_to_store:
        raise ValueError("검증 경고가 있는 AI 문장은 프로젝트에 저장할 수 없습니다.")
    key = ai_draft_field_key(item.system, item.requirement_key)
    project.set_field(
        key,
        f"AI 문장 보강 · {item.label}",
        {
            "system": item.system,
            "requirement_key": item.requirement_key,
            "section": item.section,
            "label": item.label,
            "draft_text": item.draft_text,
            "profile_summary": item.profile_summary,
            "suggested_additions": list(item.suggested_additions),
            "used_fact_keys": list(item.used_fact_keys),
            "legal_basis": item.legal_basis,
            "model": item.model,
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        },
        "AI_DRAFT",
        note="확인된 회사 사실과 등록된 작성근거만 사용한 LLM 문장 보강 초안. 담당자 승인 전 최종본 사용 금지.",
    )
    return key


def approve_ai_draft(project: Stage2Project, system: str, requirement_key: str, edited_text: str | None = None) -> None:
    key = ai_draft_field_key(system, requirement_key)
    record = project.get_field(key)
    if record is None or not isinstance(record.value, Mapping):
        raise ValueError("승인할 AI 문장 초안이 없습니다.")
    value = dict(record.value)
    text = str(edited_text if edited_text is not None else value.get("draft_text") or "").strip()
    if not text:
        raise ValueError("승인할 문장이 비어 있습니다.")
    # Approval may edit wording but must not introduce unsupported numeric or tag facts.
    spec = next((s for s in selected_requirement_specs(project) if s.key == requirement_key and s.system == _normalize_system(system)), None)
    if spec is None:
        raise ValueError("현재 작성범위에서 해당 작성항목을 찾을 수 없습니다.")
    facts = _confirmed_facts(project)
    warnings = _unsupported_tokens(text, _source_corpus(project, spec, facts))
    if warnings:
        raise ValueError("승인 문장에 확인자료에 없는 구체값이 있습니다: " + "; ".join(warnings))
    value["draft_text"] = text
    value["approved_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    project.set_field(
        key,
        record.label,
        value,
        "USER_CONFIRMED",
        evidence=list(record.evidence),
        note="AI 보강문장을 회사 담당자가 검토·승인함. 원본 회사 사실은 별도 필드에 보존됨.",
    )


def remove_ai_draft(project: Stage2Project, system: str, requirement_key: str) -> bool:
    key = ai_draft_field_key(system, requirement_key)
    if key not in project.fields:
        return False
    del project.fields[key]
    project.touch()
    return True
