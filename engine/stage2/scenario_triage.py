"""물질×설비 조합의 예비 검토 순서를 계산합니다.

이 지표는 누출량, 피해거리, 규정수량 또는 법적 시나리오 판정이 아닙니다.
사람이 어떤 값부터 확인할지 정하는 용도이며, 순위를 바꾸는 값(핵심값)을 찾아 자동 기입 경계에도 씁니다.

값은 세 상태로 구분합니다.
- 확정: 담당자가 확인했거나 규칙이 자동 기입한 값
- 잠정: 아직 확인하지 않았지만 충돌·오류가 없는 후보값 (순위 계산에 사용)
- 가정: 자료에 값이 없거나 충돌·오류가 있어 상향 임시값으로 대체한 값 (순위 계산에 사용하되 보류)
"""
from __future__ import annotations

from bisect import bisect_right
import json
from math import isfinite

from . import evidence_workspace as ew

SCORED_FIELDS = ("inventory", "pressure", "concentration")
UNITS = {"inventory": "kg", "pressure": "MPa", "concentration": "%"}
# 실제 값이 틀렸을 때를 가정해 이 배율로 흔들어 순위가 바뀌는지 봅니다.
LOW_FACTOR, HIGH_FACTOR = 0.5, 2.0


def _positive(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value >= 0 else None


def _score(inventory, pressure, concentration):
    return inventory * (1 + pressure) * concentration / 100


class _Ranker:
    """정렬된 점수에서 이분 탐색으로 등위를 구합니다(동점은 같은 등위)."""

    def __init__(self, scores):
        self.sorted = sorted(scores)

    def rank(self, score, own=None):
        threshold = score + max(1e-8, abs(score) * 1e-10)
        greater = len(self.sorted) - bisect_right(self.sorted, threshold)
        if own is not None and own > threshold:
            greater -= 1
        return 1 + greater


def _entity_values(project):
    """entity → field → {value, state, fact, candidates}. 확정·잠정·충돌·오류를 구분합니다."""
    result = {}
    for slot in ew.slots(project):
        entry = None
        if slot["chosen"]:
            entry = {"value": slot["chosen"]["value"], "state": "confirmed", "fact": slot["chosen"]}
        else:
            facts = slot["facts"]
            valid = [f for f in facts if ew.value_problem(slot["field"], f["value"]) is None]
            distinct = {json.dumps(f["value"], ensure_ascii=False, sort_keys=True) for f in valid}
            if len(valid) == len(facts) and len(distinct) == 1:
                entry = {"value": facts[0]["value"], "state": "provisional", "fact": facts[0]}
            elif len(distinct) > 1:
                numbers = [f["value"] for f in valid if isinstance(f["value"], (int, float))]
                entry = {"value": max(numbers) if numbers and slot["field"] in ew.NUMERIC_FIELDS else None,
                         "state": "conflict", "fact": None, "candidates": sorted({str(f["value"]) for f in valid})}
            else:
                entry = {"value": None, "state": "invalid", "fact": None}
        result.setdefault(slot["entity"], {})[slot["field"]] = entry
    return result


def _source(entry):
    fact = entry.get("fact")
    return {"document": fact["document"], "location": fact["location"], "sha256": fact["sha256"]} if fact else None


def evaluate(project):
    """모든 조합, 출처, 값 상태, 상향 가정, 한 변수씩 변화시킨 순위 민감도를 반환."""
    values = _entity_values(project)
    unchosen = {}
    for slot in ew.slots(project):
        if not slot["chosen"]:
            unchosen.setdefault(slot["entity"], []).append(slot)
    entities = {f["entity"] for f in ew.graph_facts(project)}
    facilities = sorted(k for k in entities if k.startswith("facility:"))
    materials = sorted(k for k in entities if k.startswith("material:"))

    def usable(entity, field):
        entry = values.get(entity, {}).get(field)
        number = _positive(entry["value"]) if entry else None
        return number if entry and entry["state"] != "invalid" else None

    observed_inventory = [usable(k, "inventory") for k in facilities]
    observed_pressure = [usable(k, "pressure") for k in facilities]
    # 기본값은 실제 사업장 상한을 뜻하지 않습니다. 관측 최고값보다 높은 예비 비교값입니다.
    defaults = {"inventory": max(10000.0, 1.5 * max([v for v in observed_inventory if v is not None], default=0)),
                "pressure": max(1.0, 1.5 * max([v for v in observed_pressure if v is not None], default=0)),
                "concentration": 100.0}

    def text_of(entity, field):
        entry = values.get(entity, {}).get(field)
        return str(entry["value"]).strip() if entry and entry["state"] in {"confirmed", "provisional"} and entry["value"] is not None else ""

    names = {m: {text_of(m, "name"), m.split(":", 1)[1]} - {""} for m in materials}
    by_product = {}
    for material, aliases in names.items():
        for alias in aliases:
            by_product.setdefault(alias, set()).add(material)

    rows = []
    for facility in facilities:
        product = text_of(facility, "product")
        matched = by_product.get(product, set()) if product else set()
        for material in materials:
            linked = material in matched
            used, states, assumptions, sources, conflicts = {}, {}, {}, {}, {}
            for field, entity in (("inventory", facility), ("pressure", facility), ("concentration", material)):
                entry = values.get(entity, {}).get(field)
                number = usable(entity, field)
                if entry and entry["state"] == "conflict":
                    conflicts[field] = entry.get("candidates", [])
                if number is None:
                    number = defaults[field]
                    reason = "충돌한 값 중 처리할 수 없어 임시값 사용" if field in conflicts else \
                        ("100% 상향 가정" if field == "concentration" else "관측 최고값×1.5와 임시 비교값 중 큰 값")
                    assumptions[field] = {"value": number, "unit": UNITS[field], "basis": reason}
                    states[field] = "assumed"
                else:
                    states[field] = entry["state"]
                    if entry["state"] == "conflict":
                        assumptions[field] = {"value": number, "unit": UNITS[field], "basis": "충돌한 값 중 큰 값(보수적)"}
                        states[field] = "assumed"
                    elif entry.get("fact"):
                        sources[field] = _source(entry)
                used[field] = number
            score = _score(used["inventory"], used["pressure"], used["concentration"])
            blockers = []
            if not linked:
                blockers.append("설비와 물질의 취급 관계를 확인할 근거가 없습니다.")
            if linked and len(matched) > 1:
                blockers.append("동일한 취급제품에 여러 물질이 연결됩니다. 제품코드를 확인하세요.")
            for entity in (facility, material):
                for slot in unchosen.get(entity, []):
                    blockers.append(f"{ew.LABELS[slot['field']]}: {slot['status']}")
            if not product:
                blockers.append("설비 취급제품 미확인")
            if not text_of(material, "cas"):
                blockers.append("물질 CAS 미확인")
            if usable(facility, "temperature") is None:
                blockers.append("설비 운전온도 미확인")
            rows.append({"facility": facility, "material": material, "linked": linked, "score": score,
                         "values": used, "value_states": states, "assumptions": assumptions, "conflicts": conflicts,
                         "sources": sources, "blockers": list(dict.fromkeys(blockers)),
                         "rank_sensitive": [], "rank_critical": [], "rank": None, "state": "보류"})

    eligible = [r for r in rows if r["linked"]]
    ranker = _Ranker(r["score"] for r in eligible)
    questions, critical_values = [], []
    for row in eligible:
        row["rank"] = baseline = ranker.rank(row["score"], row["score"])
        for field in SCORED_FIELDS:
            current = row["values"][field]
            others = {f: row["values"][f] for f in SCORED_FIELDS if f != field}

            def rescored(value):
                merged = {**others, field: value}
                return _score(merged["inventory"], merged["pressure"], merged["concentration"])

            if field in row["assumptions"]:
                # 값이 없으니 0 ~ 임시값의 2배 범위에서 순위가 바뀌는지 봅니다.
                top = min(100, current * 2) if field == "concentration" else current * 2
                ranks = [ranker.rank(rescored(v), row["score"]) for v in (0, top)]
                if any(r != baseline for r in ranks):
                    row["rank_sensitive"].append(field)
                    assumption = row["assumptions"][field]
                    questions.append({"facility": row["facility"], "material": row["material"], "field": field,
                                      "question": f"{ew.LABELS[field]}의 실제 값을 확인하세요. 가정 {assumption['value']:g}{assumption['unit']}을 바꾸면 예비 순위가 달라집니다.",
                                      "baseline_rank": baseline, "range_ranks": ranks})
            else:
                low, high = current * LOW_FACTOR, current * HIGH_FACTOR
                if field == "concentration":
                    high = min(100, high)
                ranks = [ranker.rank(rescored(v), row["score"]) for v in (low, high)]
                if any(r != baseline for r in ranks):
                    row["rank_critical"].append(field)
                    critical_values.append({"facility": row["facility"], "material": row["material"], "field": field,
                                            "value": current, "state": row["value_states"][field],
                                            "baseline_rank": baseline, "range_ranks": ranks})
    for row in rows:
        if not row["linked"] or row["assumptions"] or row["conflicts"]:
            row["state"] = "보류"
        elif row["blockers"] or any(s == "provisional" for s in row["value_states"].values()):
            row["state"] = "잠정"
        else:
            row["state"] = "예비 검토"
    ordered = sorted(rows, key=lambda r: (not r["linked"], r["rank"] or 0, -r["score"], r["facility"], r["material"]))
    return {"rows": ordered, "questions": questions, "critical_values": critical_values, "defaults": defaults,
            "method": "예비 비교지표=최대보유량(kg)×(1+운전압력(MPa))×함량(%)/100. 안전도·피해거리·법적 시나리오 판정이 아니며 성상·독성·차단설비·누출공·주변 영향은 반영하지 않습니다.",
            "sensitivity": "값이 없거나 충돌·오류인 항목은 한 번에 하나씩 0 및 임시값 2배로, 값이 있는 항목은 0.5배와 2배로 바꾸고 확인된 취급 관계 조합 사이의 상대 순위를 비교합니다. 순위에 영향 없는 결측도 법적·물리적 계산 전에는 확인해야 합니다."}


def critical_slot_keys(project):
    """순위를 바꿀 수 있는 실제 값의 slot 키(설비·물질 식별자|항목)."""
    keys = set()
    for item in evaluate(project)["critical_values"]:
        entity = item["material"] if item["field"] == "concentration" else item["facility"]
        keys.add(f"{entity}|{item['field']}")
    return frozenset(keys)
