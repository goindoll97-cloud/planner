"""출처가 확인된 물질×설비의 예비 검토 순서를 계산합니다.

이 지표는 누출량, 피해거리, 규정수량 또는 법적 시나리오 판정이 아닙니다.
"""
from __future__ import annotations

from math import isfinite

from . import evidence_workspace as ew


def _positive(value):
    return float(value) if isinstance(value, (int, float)) and isfinite(value) and value >= 0 else None


def _order(rows):
    return sorted(rows, key=lambda r: (-r["score"], r["facility"], r["material"]))


def _relative_rank(rows, target):
    score = target["score"]
    # 동점은 같은 등위로 둡니다. 표시 순서를 바꾸는 것만으로 질문을 만들지 않습니다.
    return 1 + sum(r["score"] > score + max(1e-8, abs(score) * 1e-10) for r in rows)


def evaluate(project):
    """모든 조합, 출처, 상향 가정, 한 변수씩 변화시킨 순위 민감도를 반환."""
    entities = ew.confirmed_entities(project)
    groups = {s["key"]: s for s in ew.slots(project)}
    all_entities={fact['entity'] for fact in ew.graph(project)['facts']}
    facilities = sorted(k for k in all_entities if k.startswith("facility:"))
    materials = sorted(k for k in all_entities if k.startswith("material:"))
    observed_inventory = [_positive(entities.get(k,{}).get("inventory")) for k in facilities]
    observed_pressure = [_positive(entities.get(k,{}).get("pressure")) for k in facilities]
    # 기본값은 실제 사업장 상한을 뜻하지 않습니다. 관측 최고값보다 높은 예비 비교값입니다.
    defaults = {"inventory": max(10000.0, 1.5 * max([v for v in observed_inventory if v is not None], default=0)),
                "pressure": max(1.0, 1.5 * max([v for v in observed_pressure if v is not None], default=0)),
                "concentration": 100.0}
    rows = []
    for f in facilities:
        fv = entities.get(f,{})
        for m in materials:
            mv = entities.get(m,{})
            product = str(fv.get("product", "")).strip()
            linked = bool(product and product in {str(mv.get("name", "")).strip(), m.split(":", 1)[1]})
            assumptions = {}
            sources = {}
            values = {}
            for field, entity, record in (("inventory", f, fv), ("pressure", f, fv), ("concentration", m, mv)):
                chosen = groups.get(entity + "|" + field, {}).get("chosen")
                value = _positive(record.get(field))
                if value is None:
                    value = defaults[field]
                    assumptions[field] = {"value": value, "unit": {"inventory": "kg", "pressure": "MPa", "concentration": "%"}[field],
                                          "basis": "관측 최고값×1.5와 임시 비교값 중 큰 값" if field != "concentration" else "100% 상향 가정"}
                elif chosen:
                    sources[field] = {"document": chosen["document"], "location": chosen["location"], "sha256": chosen["sha256"]}
                values[field] = value
            score = values["inventory"] * (1 + values["pressure"]) * values["concentration"] / 100
            blockers = []
            if not linked:
                blockers.append("설비와 물질의 취급 관계를 확인할 근거가 없습니다.")
            if linked and sum(product in {str(entities.get(k,{}).get("name", "")).strip(), k.split(":",1)[1]} for k in materials)>1:
                blockers.append("동일한 취급제품에 여러 물질이 연결됩니다. 제품코드를 확인하세요.")
            for entity in (f, m):
                for slot in groups.values():
                    if slot["entity"] == entity and not slot["chosen"]:
                        blockers.append(f"{ew.LABELS[slot['field']]}: {slot['status']}")
            if not fv.get("product"):
                blockers.append("설비 취급제품 미확인")
            if not mv.get("cas"):
                blockers.append("물질 CAS 미확인")
            if not fv.get("temperature"):
                blockers.append("설비 운전온도 미확인")
            rows.append({"facility": f, "material": m, "linked": linked, "score": score,
                         "values": values, "assumptions": assumptions, "sources": sources,
                         "blockers": list(dict.fromkeys(blockers)), "rank_sensitive": [],
                         "state": "검토 필요"})
    eligible = [r for r in rows if r["linked"]]
    baseline = {id(r): _relative_rank(eligible, r) for r in eligible}
    questions = []
    for row in eligible:
        for field, assumption in row["assumptions"].items():
            # 하나의 결측값만 0 ~ 가정값 2배로 움직여 상대 순위가 바뀌는지 확인.
            original = row["score"]
            if field == "inventory": others = (1 + row["values"]["pressure"]) * row["values"]["concentration"] / 100
            elif field == "pressure": others = row["values"]["inventory"] * row["values"]["concentration"] / 100
            else: others = row["values"]["inventory"] * (1 + row["values"]["pressure"]) / 100
            ranks = []
            for value in (0, min(100, assumption["value"] * 2) if field == "concentration" else assumption["value"] * 2):
                row["score"] = others * (1 + value if field == "pressure" else value)
                ranks.append(_relative_rank(eligible, row))
            row["score"] = original
            if any(rank != baseline[id(row)] for rank in ranks):
                row["rank_sensitive"].append(field)
                questions.append({"facility": row["facility"], "material": row["material"], "field": field,
                                  "question": f"{ew.LABELS[field]}의 실제 값을 확인하세요. 가정 {assumption['value']:g}{assumption['unit']}을 바꾸면 예비 순위가 달라집니다.",
                                  "baseline_rank": baseline[id(row)], "range_ranks": ranks})
    for row in rows:
        row["rank"] = _relative_rank(eligible, row) if row["linked"] else None
        row["state"] = "보류" if row["blockers"] or row["assumptions"] else "예비 검토"
    return {"rows": _order(rows), "questions": questions, "defaults": defaults,
            "method": "예비 비교지표=최대보유량(kg)×(1+운전압력(MPa))×함량(%)/100. 안전도·피해거리·법적 시나리오 판정이 아니며 성상·독성·차단설비·누출공·주변 영향은 반영하지 않습니다.",
            "sensitivity": "결측값을 한 번에 하나씩 0 및 상향 가정값 2배로 바꾸고, 확인된 취급 관계 조합 사이의 상대 순위를 비교합니다. 순위에 영향 없는 결측도 법적·물리적 계산 전에는 확인해야 합니다."}
