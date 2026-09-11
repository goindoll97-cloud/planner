from __future__ import annotations

"""Conservative screening for regulatory rows that do not enumerate one CAS.

This module is adapted from the earlier goindoll97 project.  It deliberately
separates *candidate discovery* from legal confirmation.  Broad names such as
"... and its salts", compound groups, mixtures, reaction products and UVCB
ranges must never become an automatic positive/negative decision from name
similarity alone.

The current planner will feed this index only from source-verified, approved
current-law tables.  Old project data are not imported as legal rules.
"""

import re
from typing import Any

import pandas as pd

CAS_RE = re.compile(r"(?<!\d)(\d{2,7}-\d{2}-\d)(?!\d)")

STOP = {
    "and", "with", "the", "its", "their", "of", "reaction", "product", "products",
    "mixture", "salt", "salts", "compound", "compounds",
    "반응생성물", "반응혼합물", "혼합물", "염류", "화합물", "화합물군", "및", "그",
}

CHEMICAL_TOKEN_ALIASES = {
    "chloric": "chlorate", "chlorates": "chlorate",
    "nitrous": "nitrite", "nitrites": "nitrite",
    "chromic": "chromate", "chromates": "chromate",
    "dichromate": "chromate", "dichromates": "chromate",
    "hexafluorosilicic": "hexafluorosilicate",
    "hexafluorosilicates": "hexafluorosilicate",
    "tetrafluoroboric": "tetrafluoroborate",
    "tetrafluoroborates": "tetrafluoroborate",
}

DISTINCTIVE_FAMILY_TOKENS = {
    "antimony", "cadmium", "chromate", "hexafluorosilicate", "lead", "mercury",
    "nitrite", "silver", "tin", "tetrafluoroborate", "zinc", "chlorate",
}


def _clean(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def _tokens(value: Any) -> set[str]:
    words = re.findall(r"[a-z0-9가-힣]{3,}", _clean(value).lower())
    tokens = {CHEMICAL_TOKEN_ALIASES.get(word, word) for word in words if word not in STOP}
    for word in words:
        for family in DISTINCTIVE_FAMILY_TOKENS:
            if word.endswith(family):
                tokens.add(family)
    return tokens


def _split_cas(value: Any) -> set[str]:
    return set(CAS_RE.findall(_clean(value)))


def _extract_exception_cas(*texts: Any) -> set[str]:
    """Extract CAS values only from explicit exclusion clauses."""
    found: set[str] = set()
    for raw in texts:
        text = _clean(raw)
        if not text:
            continue
        lower = text.lower()
        start = 0
        while True:
            idx = lower.find("excluding", start)
            if idx < 0:
                break
            end_candidates = [
                pos for pos in [
                    lower.find("with the exception", idx + 9),
                    lower.find("except as", idx + 9),
                    lower.find("provided that", idx + 9),
                ] if pos >= 0
            ]
            end = min(end_candidates) if end_candidates else min(len(text), idx + 1200)
            found.update(CAS_RE.findall(text[idx:end]))
            start = idx + 9

        # Korean legal text often places the excluded CAS before the word '제외'.
        for match in re.finditer(r"제외", text):
            left = max(0, match.start() - 800)
            clause = text[left:match.end()]
            boundary = max(clause.rfind("("), clause.rfind("["), clause.rfind(";"), clause.rfind("|"))
            if boundary >= 0:
                clause = clause[boundary + 1:]
            found.update(CAS_RE.findall(clause))
    return found


def classify_scope_type(korean: Any, english: Any = "", source_text: Any = "") -> str:
    text = f"{_clean(korean)} {_clean(english)} {_clean(source_text)}".lower()
    compact = re.sub(r"\s+", "", text)
    if any(token in compact for token in ("반응생성물", "반응혼합물", "reactionproduct", "reactionmixture")):
        return "REACTION_PRODUCT"
    if "mixture" in text or "혼합물" in text:
        return "MIXTURE"
    if any(token in compact for token in ("그염류", "염류", "its salts", "their salts")):
        return "SALT_FAMILY"
    if any(token in compact for token in ("구조범위", "알킬기", "치환기", "탄소수", "일반식", "structuralrange")):
        return "STRUCTURAL_RANGE"
    if any(token in compact for token in ("화합물군", "화합물", "compoundgroup", "compounds")):
        return "COMPOUND_GROUP"
    if any(token in compact for token in ("uvcb", "조성이불명", "중합체", "고분자")):
        return "POLYMER_UVCB"
    return "NAME_OR_UVCB"


def _coalesce(row: pd.Series, *columns: str) -> str:
    for column in columns:
        if column in row.index:
            value = _clean(row.get(column))
            if value:
                return value
    return ""


def build_no_cas_scope_index(master: pd.DataFrame, regime: str = "") -> pd.DataFrame:
    """Build a review index from approved regulatory rows without a direct CAS.

    Expected fields are intentionally flexible so the same matcher can consume
    CAP appendix 1/2 tables once those parsers are approved.  The important
    distinction is between ``direct_cas`` (automatic exact-list identity) and
    CAS values merely embedded in a broad legal description.
    """
    if master is None or master.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for idx, row in master.iterrows():
        row_regime = _coalesce(row, "regime", "source_key", "category")
        if regime and row_regime and row_regime != regime:
            continue

        direct_text = _coalesce(row, "direct_cas")
        direct_cas = _split_cas(direct_text)

        # If a parser only supplies cas_list, it must also explicitly identify
        # the row as DIRECT_CAS before cas_list is treated as direct identity.
        scope_hint = _coalesce(row, "scope_type").upper()
        if not direct_cas and scope_hint == "DIRECT_CAS":
            direct_cas = _split_cas(_coalesce(row, "cas_list", "cas_text", "cas"))
        if direct_cas:
            continue

        korean = _coalesce(row, "regulatory_name", "substance_name", "substance_name_ko", "group_title")
        english = _coalesce(row, "regulatory_name_en", "substance_name_en")
        source = _coalesce(row, "source_text", "legal_text", "condition_note", "group_title")

        embedded = set()
        for value in (
            source,
            english,
            _coalesce(row, "all_cas_in_row"),
            _coalesce(row, "anchor_cas"),
            _coalesce(row, "cas_list"),
            _coalesce(row, "cas_text"),
        ):
            embedded.update(_split_cas(value))

        exceptions = _split_cas(_coalesce(row, "exception_cas", "excluded_cas"))
        exceptions.update(_extract_exception_cas(source, english, korean))
        embedded -= exceptions

        scope_type = scope_hint if scope_hint and scope_hint != "DIRECT_CAS" else classify_scope_type(korean, english, source)
        designation = _coalesce(row, "designation_id", "record_key", "rule_id") or f"ROW-{idx + 1}"

        rows.append({
            "designation_id": designation,
            "regime": row_regime or regime,
            "regulatory_name": korean,
            "regulatory_name_en": english,
            "scope_type": scope_type,
            "embedded_component_cas": ";".join(sorted(embedded)),
            "exception_cas": ";".join(sorted(exceptions)),
            "source_text": source,
            "name_tokens": _tokens(f"{korean} {english}"),
            "source_key": _coalesce(row, "source_key"),
            "effective_date": _coalesce(row, "effective_date"),
            "lowest_quantity_ton": row.get("lowest_quantity_ton") if "lowest_quantity_ton" in row.index else None,
            "lower_quantity_ton": row.get("lower_quantity_ton") if "lower_quantity_ton" in row.index else None,
            "upper_quantity_ton": row.get("upper_quantity_ton") if "upper_quantity_ton" in row.index else None,
            "content_threshold_pct": row.get("content_threshold_pct") if "content_threshold_pct" in row.index else None,
        })
    return pd.DataFrame(rows)


def _inventory_value(row: pd.Series, *columns: str) -> str:
    return _coalesce(row, *columns)


def screen_no_cas_scopes(inventory: pd.DataFrame, index: pd.DataFrame) -> pd.DataFrame:
    """Discover broad-scope candidates without auto-confirming membership.

    Ranking follows the prior project: explicit legal exclusions first, then CAS
    embedded in the legal scope, then conservative name/family candidates.
    """
    if inventory is None or inventory.empty or index is None or index.empty:
        return pd.DataFrame()

    out: list[dict[str, Any]] = []
    for inv_idx, item in inventory.iterrows():
        material_id = _inventory_value(item, "material_id", "No.") or str(inv_idx + 1)
        cas = _inventory_value(item, "cas", "CAS No.")
        chemical_name = _inventory_value(item, "chemical_name", "물질명(알면 입력)")
        product_name = _inventory_value(item, "product_name", "제품명")
        use_description = _inventory_value(item, "use_description", "취급형태", "비고")
        item_tokens = _tokens(f"{chemical_name} {product_name} {use_description}")

        for _, rule in index.iterrows():
            components = {v for v in _clean(rule.get("embedded_component_cas")).split(";") if v}
            exceptions = {v for v in _clean(rule.get("exception_cas")).split(";") if v}
            exception_hit = bool(cas and cas in exceptions)
            component_hit = bool(cas and cas in components)
            rule_tokens = rule.get("name_tokens") if isinstance(rule.get("name_tokens"), set) else set()
            exact_tokens = item_tokens & rule_tokens
            fuzzy_prefixes = {
                a[:8]
                for a in item_tokens
                for b in rule_tokens
                if len(a) >= 8 and len(b) >= 8 and a[:8] == b[:8]
            }
            matched_count = len(exact_tokens) + len(
                fuzzy_prefixes - {token[:8] for token in exact_tokens if len(token) >= 8}
            )
            overlap = matched_count / max(1, min(len(item_tokens), len(rule_tokens)))
            scope = _clean(rule.get("scope_type"))
            family_hit = bool(exact_tokens & DISTINCTIVE_FAMILY_TOKENS)
            name_hit = (overlap >= 0.45 and (scope == "SALT_FAMILY" or matched_count >= 2)) or family_hit

            if not (exception_hit or component_hit or name_hit):
                continue

            if exception_hit:
                match_type = "EXPLICIT_EXCEPTION_CAS"
                reason = "법령의 명시적 제외조건에 회사 CAS가 일치합니다. 포함 후보보다 이 제외근거를 우선 검토해야 합니다."
                score = 1000.0
            elif component_hit and scope in {"REACTION_PRODUCT", "MIXTURE"}:
                match_type = "COMPONENT_CAS_CANDIDATE"
                reason = "법령의 포괄 혼합물·반응생성물 범위 안에 회사 CAS가 구성성분으로 기재되어 있습니다. 규제대상 혼합물 자체인지 추가 확인이 필요합니다."
                score = 800.0
            elif component_hit:
                match_type = "EXACT_SCOPE_CAS_CANDIDATE"
                reason = "법령 원문 포괄범위에 회사 CAS가 포함되어 있으나 직접 CAS 지정행은 아닙니다. 범위 포함 여부를 확인해야 합니다."
                score = 700.0
            else:
                match_type = "NAME_SCOPE_CANDIDATE"
                reason = "회사 물질명과 CAS 미기재 포괄 규제범위가 관련되어 범위 포함 여부를 확인해야 합니다."
                score = float(overlap * 100.0 + matched_count)

            out.append({
                "material_id": material_id,
                "row_no": inv_idx + 1,
                "product_name": product_name,
                "chemical_name": chemical_name,
                "cas": cas,
                "designation_id": rule.get("designation_id"),
                "regime": rule.get("regime"),
                "regulatory_name": rule.get("regulatory_name"),
                "scope_type": scope,
                "candidate_match_type": match_type,
                "candidate_reason": reason,
                "is_explicit_exception": exception_hit,
                "candidate_score": score,
                "source_text": rule.get("source_text"),
                "effective_date": rule.get("effective_date"),
                "candidate_status": "판정보류(포괄 규제범위 확인 필요)",
            })

    if not out:
        return pd.DataFrame()
    frame = pd.DataFrame(out)
    return frame.drop_duplicates(
        subset=["material_id", "designation_id", "regulatory_name", "candidate_match_type"],
        keep="first",
    ).reset_index(drop=True)


def primary_candidate(candidates: pd.DataFrame, material_id: str) -> dict[str, Any] | None:
    """Return the strongest candidate; this still does not auto-confirm scope."""
    if candidates is None or candidates.empty:
        return None
    rows = candidates[candidates["material_id"].astype(str).eq(str(material_id))].copy()
    if rows.empty:
        return None
    rank = {
        "EXPLICIT_EXCEPTION_CAS": 0,
        "COMPONENT_CAS_CANDIDATE": 1,
        "EXACT_SCOPE_CAS_CANDIDATE": 1,
        "NAME_SCOPE_CANDIDATE": 2,
    }
    rows["_rank"] = rows["candidate_match_type"].map(rank).fillna(9)
    rows["_score"] = pd.to_numeric(rows["candidate_score"], errors="coerce").fillna(0.0)
    rows = rows.sort_values(["_rank", "_score"], ascending=[True, False], kind="stable")
    return rows.iloc[0].drop(labels=["_rank", "_score"]).to_dict()
