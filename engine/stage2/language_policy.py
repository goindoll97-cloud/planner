from __future__ import annotations

import re
from typing import Any

from engine.legal_terminology import load_legal_terminology


_INTERNAL_KEY_RE = re.compile(r"\b(?:psm|cap|business|inventory|documents|ai_draft)(?:\.[A-Za-z0-9_-]+)+\b", re.I)

# These are implementation words, not language that should appear in a legal/report-facing
# paragraph. They remain valid inside code, prompts, metadata, project JSON, and audit logs.
_DEFAULT_DEVELOPER_TERMS = (
    "field_key",
    "requirement_key",
    "confirmed_fact_keys",
    "used_fact_keys",
    "global_confirmed_facts",
    "global_fact_keys",
    "confirmed_fact_catalog",
    "input_facts_sha256",
    "payload",
    "registry",
    "schema",
    "mapping",
    "cross-check",
    "crosscheck",
    "Rule Engine",
    "VERIFIED",
    "USER_CONFIRMED",
    "CALCULATED",
    "AI_DRAFT",
    "HOLD",
    "JSON",
    "LLM",
)

# Only aliases whose replacement is unambiguous are normalized automatically.
# Ambiguous technical terms are left untouched and controlled through the prompt instead.
_DEFAULT_LEGACY_REPLACEMENTS = {
    "내부 비상대응 계획": "내부 비상대응계획",
    "외부 비상대응 계획": "외부 비상대응계획",
    "설비점검·검사 및 유지보수 계획·지침서": "설비점검·검사 및 보수계획, 유지계획 및 지침서",
    "비상장비·인력 보유현황": "비상조치를 위한 장비·인력 보유현황",
}


def _normalize_system(system: str) -> str:
    value = str(system or "").strip().upper()
    if value not in {"PSM", "CAP"}:
        raise ValueError(f"지원하지 않는 보고서 종류입니다: {system}")
    return value


def developer_only_terms() -> tuple[str, ...]:
    policy = load_legal_terminology()
    configured = tuple(str(v).strip() for v in policy.get("developer_only_terms", []) if str(v).strip())
    return tuple(dict.fromkeys((*configured, *_DEFAULT_DEVELOPER_TERMS)))


def legacy_replacements() -> dict[str, str]:
    policy = load_legal_terminology()
    configured = policy.get("legacy_term_replacements") or {}
    result = dict(_DEFAULT_LEGACY_REPLACEMENTS)
    if isinstance(configured, dict):
        for old, new in configured.items():
            old_text = str(old or "").strip()
            new_text = str(new or "").strip()
            if old_text and new_text:
                result[old_text] = new_text
    return result


def canonical_terms_for_system(system: str) -> dict[str, Any]:
    system = _normalize_system(system)
    policy = load_legal_terminology()
    block = policy[system.lower()]["canonical"]
    if system == "PSM":
        return {
            "program": block["program"],
            "sections": list(block.get("sections", [])),
            "official_terms": list((block.get("fields") or {}).values()),
        }
    return {
        "program": block["program"],
        "sections": list(block.get("sections", [])),
        "official_terms": list((block.get("terms") or {}).values()),
    }


def language_policy_for_prompt(system: str) -> dict[str, Any]:
    system = _normalize_system(system)
    policy = load_legal_terminology()
    canonical = canonical_terms_for_system(system)
    return {
        "principle": policy.get("principle", ""),
        "source_priority": list(policy.get("source_priority", [])),
        "program": canonical["program"],
        "canonical_sections": canonical["sections"],
        "canonical_terms": canonical["official_terms"],
        "forbidden_output_terms": list(developer_only_terms()),
        "style_rules": [
            "법령·행정규칙에 정식 명칭이 있는 개념은 해당 정식 명칭을 우선 사용한다.",
            "회사 사실과 운영 설명은 실무자가 바로 이해할 수 있는 자연스러운 한국어 문장으로 작성한다.",
            "프로그램 내부 변수명, 상태값, 데이터구조명, 개발자 용어를 보고서 문장에 노출하지 않는다.",
            "법령 문구를 불필요하게 반복하거나 회사가 확인하지 않은 의무·절차를 새 사실처럼 단정하지 않는다.",
        ],
    }


# 모델이 쓰는 영문 약어는 사용자 문서에 그대로 나가지 않게 정식 명칭으로 바꾼다.
_ABBREVIATIONS = ((re.compile(r"(?<![A-Za-z])PSM(?![A-Za-z])"), "공정안전관리"),
                  (re.compile(r"(?<![A-Za-z])CAP(?![A-Za-z])"), "화학사고예방관리계획서"))


def normalize_public_prose(text: str, system: str) -> str:
    _normalize_system(system)
    result = str(text or "").strip()
    for old, new in legacy_replacements().items():
        result = result.replace(old, new)
    for pattern, new in _ABBREVIATIONS:
        result = pattern.sub(new, result)
    return result


def validate_public_prose(text: str, system: str) -> tuple[str, ...]:
    _normalize_system(system)
    source = str(text or "")
    warnings: list[str] = []

    key_matches = sorted(set(_INTERNAL_KEY_RE.findall(source)))
    if key_matches:
        warnings.append("사용자 문서에 내부 필드명/키가 포함됨: " + ", ".join(key_matches[:8]))

    lower = source.lower()
    found_terms: list[str] = []
    for term in developer_only_terms():
        if term.lower() in lower:
            found_terms.append(term)
    if found_terms:
        warnings.append("사용자 문서에 개발자 내부용어가 포함됨: " + ", ".join(dict.fromkeys(found_terms)))

    for old, new in legacy_replacements().items():
        if old in source:
            warnings.append(f"현행 정식 용어로 바꿔야 함: '{old}' → '{new}'")

    return tuple(dict.fromkeys(warnings))


def assert_public_prose(text: str, system: str) -> str:
    normalized = normalize_public_prose(text, system)
    warnings = validate_public_prose(normalized, system)
    if warnings:
        raise ValueError("보고서 문장 용어검사에 통과하지 못했습니다: " + "; ".join(warnings))
    return normalized
