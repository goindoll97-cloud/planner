from __future__ import annotations

"""Normalize small variations in local-model JSON output.

Local models often obey the requested JSON semantics but vary the container key
(`drafts`, `items`, `sentences`), return a keyed object instead of an array, or
emit a single draft object for a one-item batch.  The report pipeline should not
fail solely because of those harmless shape differences.

This module is intentionally conservative: it only normalizes fields that map to
known requested requirement keys. It never invents or reorders company facts.
"""

from typing import Any, Mapping, Sequence


_CONTAINER_KEYS = (
    "drafts",
    "items",
    "results",
    "sentences",
    "responses",
    "draft_items",
    "초안",
    "문장",
    "문장들",
)
_TEXT_KEYS = ("draft_text", "text", "sentence", "content", "paragraph", "body", "본문")
_KEY_KEYS = ("requirement_key", "requirement", "key", "id", "item_key", "항목키")
_SUGGESTION_KEYS = ("suggested_additions", "suggestions", "suggested", "missing", "확인사항")
_FACT_KEYS = ("used_fact_keys", "used_facts", "fact_keys", "facts")
_PROFILE_KEYS = ("profile_summary", "summary", "site_summary", "사업장요약")


def _known_keys(specs: Sequence[Any]) -> list[str]:
    return [str(getattr(spec, "key", "") or "").strip() for spec in specs if str(getattr(spec, "key", "") or "").strip()]


def _first(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping and mapping.get(key) not in (None, ""):
            return mapping.get(key)
    return None


def _normalize_row(row: Any, *, fallback_key: str = "") -> dict[str, Any] | None:
    if isinstance(row, str):
        text = row.strip()
        if not text:
            return None
        return {
            "requirement_key": fallback_key,
            "draft_text": text,
            "suggested_additions": [],
            "used_fact_keys": [],
        }
    if not isinstance(row, Mapping):
        return None

    requirement_key = str(_first(row, _KEY_KEYS) or fallback_key or "").strip()
    text = _first(row, _TEXT_KEYS)
    if isinstance(text, Mapping):
        text = _first(text, _TEXT_KEYS)
    text = str(text or "").strip()
    suggestions = _first(row, _SUGGESTION_KEYS)
    used_facts = _first(row, _FACT_KEYS)

    if suggestions in (None, ""):
        suggestions = []
    elif isinstance(suggestions, str):
        suggestions = [suggestions]
    elif not isinstance(suggestions, list):
        suggestions = [suggestions]

    if used_facts in (None, ""):
        used_facts = []
    elif isinstance(used_facts, str):
        used_facts = [used_facts]
    elif not isinstance(used_facts, list):
        used_facts = [used_facts]

    if not requirement_key and not text:
        return None
    return {
        "requirement_key": requirement_key,
        "draft_text": text,
        "suggested_additions": suggestions,
        "used_fact_keys": used_facts,
    }


def normalize_draft_response(raw: Mapping[str, Any], specs: Sequence[Any]) -> tuple[str, list[dict[str, Any]]]:
    """Return ``(profile_summary, normalized_rows)`` for known requested specs.

    Accepted shapes include:
    - {"drafts": [...]}
    - {"items": [...]}, {"sentences": [...]}, etc.
    - {"drafts": {"requirement.key": {...}}}
    - {"requirement.key": "text", ...}
    - one direct {"requirement_key": ..., "draft_text": ...} object
    - nested {"data": {...}} containers
    """
    if not isinstance(raw, Mapping):
        raise ValueError("로컬 AI 응답 JSON의 최상위 값은 객체여야 합니다.")

    known = _known_keys(specs)
    known_set = set(known)
    profile_summary = str(_first(raw, _PROFILE_KEYS) or "").strip()

    container: Any = None
    for key in _CONTAINER_KEYS:
        if key in raw:
            container = raw.get(key)
            break

    if container is None and isinstance(raw.get("data"), Mapping):
        nested_profile, nested_rows = normalize_draft_response(raw["data"], specs)
        return profile_summary or nested_profile, nested_rows

    rows: list[dict[str, Any]] = []
    if isinstance(container, list):
        for index, item in enumerate(container):
            fallback = known[index] if len(container) == len(known) and index < len(known) else ""
            normalized = _normalize_row(item, fallback_key=fallback)
            if normalized:
                rows.append(normalized)
    elif isinstance(container, Mapping):
        # Keyed-by-requirement object is a common local-model variation.
        for key, item in container.items():
            fallback = str(key) if str(key) in known_set else ""
            normalized = _normalize_row(item, fallback_key=fallback)
            if normalized:
                rows.append(normalized)
    elif container not in (None, ""):
        normalized = _normalize_row(container, fallback_key=known[0] if len(known) == 1 else "")
        if normalized:
            rows.append(normalized)

    if not rows:
        # Direct single-row response.
        if any(key in raw for key in _TEXT_KEYS) or any(key in raw for key in _KEY_KEYS):
            normalized = _normalize_row(raw, fallback_key=known[0] if len(known) == 1 else "")
            if normalized:
                rows.append(normalized)

    if not rows:
        # Top-level object keyed directly by requested requirement keys.
        for key in known:
            if key not in raw:
                continue
            normalized = _normalize_row(raw.get(key), fallback_key=key)
            if normalized:
                rows.append(normalized)

    # Keep only explicitly requested requirement keys.  For a one-item batch,
    # allow an omitted key and attach it to that sole requested item.
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        req = str(row.get("requirement_key") or "").strip()
        if not req and len(known) == 1:
            req = known[0]
            row["requirement_key"] = req
        if req not in known_set or req in seen:
            continue
        seen.add(req)
        out.append(row)

    if not out:
        keys = ", ".join(str(key) for key in raw.keys())
        raise ValueError(
            "로컬 AI 응답에서 요청한 작성항목의 문장을 찾지 못했습니다. "
            f"응답 키: {keys or '없음'}"
        )
    return profile_summary, out
