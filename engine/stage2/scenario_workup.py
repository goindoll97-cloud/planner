"""출처가 있는 물질×설비 검토 초안을 만듭니다.

예비 순위와 실제 사고 시나리오 선정 사이의 빈칸을 명시적으로 보존합니다.
이 결과는 계산 입력이나 법적 선정 결과로 저장하지 않습니다.
"""
from __future__ import annotations

from . import evidence_workspace as ew, scenario_triage


NEXT_CHECKS = (
    "설비·배관 연결과 누출 가능한 위치를 도면에서 확인",
    "물질의 유해성·인화성·운전 상태와 적용할 사고 유형을 확인",
    "누출공·지속시간·차단 및 방호설비를 확인",
    "날씨·사업장 경계·주변 사람과 토지 이용을 확인",
    "적용 지침으로 사고 영향과 시나리오 선정 근거를 계산·검토",
)


def compile_workup(project, triage=None):
    """조합별 사실·가정·보류 사유와 검토 순서를 독립적으로 묶습니다."""
    triage = triage if triage is not None else scenario_triage.evaluate(project)
    by_slot = {(s["entity"], s["field"]): s for s in ew.slots(project)}
    packets = []
    for row in triage["rows"]:
        inputs = []
        for field, entity in (("product", row["facility"]), ("name", row["material"]),
                              ("cas", row["material"]), ("inventory", row["facility"]),
                              ("pressure", row["facility"]), ("temperature", row["facility"]),
                              ("concentration", row["material"])):
            slot = by_slot.get((entity, field))
            fact = slot["chosen"] if slot else None
            if not fact and slot and len(slot["facts"]) == 1 and ew.value_problem(field, slot["facts"][0]["value"]) is None:
                fact = slot["facts"][0]
            assumption = row["assumptions"].get(field)
            state = row["value_states"].get(field, "confirmed" if slot and slot["chosen"] else "provisional" if fact else "missing")
            if state == "confirmed" and slot and slot["method"] == "AUTO":
                state = "auto_unreviewed"
            inputs.append({
                "entity": entity, "field": field, "label": ew.LABELS[field],
                "value": row["values"].get(field) if field in scenario_triage.SCORED_FIELDS else (fact["value"] if fact else None),
                "state": state,
                "assumption": assumption,
                "source": ({"document": fact["document"], "location": fact["location"], "sha256": fact["sha256"]}
                           if fact and not assumption else None),
            })
        urgent = [ew.LABELS[f] for f in row["rank_sensitive"]]
        pending = list(dict.fromkeys(row["blockers"]))
        if row["assumptions"]:
            pending.insert(0, "가정한 값은 실제 값으로 확인해야 합니다.")
        if not row["linked"]:
            action = "취급 관계를 자료로 먼저 확인"
        elif urgent:
            action = "순위를 바꾸는 빈 값을 먼저 확인: " + ", ".join(urgent)
        elif pending:
            action = "자료의 충돌·미확인 항목을 확인"
        else:
            action = "사고 유형·누출 조건·주변 영향을 검토"
        packets.append({
            "facility": row["facility"], "material": row["material"], "linked": row["linked"],
            "rank": row["rank"], "score": row["score"], "state": row["state"],
            "action": action, "inputs": inputs, "assumptions": row["assumptions"],
            "conflicts": row["conflicts"],
            "rank_sensitive": row["rank_sensitive"], "rank_critical": row["rank_critical"],
            "pending": pending, "next_checks": list(NEXT_CHECKS) if row["linked"] else [],
            "decision": "사고 시나리오 선정 전 검토 초안",
        })
    return {"method": triage["method"], "sensitivity": triage["sensitivity"], "packets": packets,
            "notice": "비교 점수는 검토 순서입니다. 가정값은 법적 계산이나 사고 영향 계산으로 전달하지 않습니다."}


def markdown(workup, company_name=""):
    """사람이 검토할 수 있는 출처·가정 포함 초안. 결과를 확정된 시나리오라고 표기하지 않습니다."""
    lines = ["# 사고 시나리오 후보 검토 초안", "", company_name, "", workup["notice"], "", workup["method"],
             "", "## 조합별 검토"]
    for packet in workup["packets"]:
        title = f"{packet['facility']} × {packet['material']}"
        lines += ["", f"### {title}", f"- 상태: {packet['state']} / 순서: {packet['rank'] if packet['rank'] is not None else '취급 관계 미확인'}",
                  f"- 다음 할 일: {packet['action']}"]
        for item in packet["inputs"]:
            if item["assumption"]:
                value = item["assumption"]["value"]
                where = f"가정 · {item['assumption']['basis']} · 원자료 없음"
            elif item["source"]:
                value = item["value"]
                source = item["source"]
                where = f"{source['document']} · {source['location']} · SHA256 {source['sha256']} · {item['state']}"
            else:
                value, where = "미확인", "출처 없음"
            lines.append(f"- {item['label']}: {value} [{where}]")
        for field, values in packet["conflicts"].items():
            lines.append(f"- 자료마다 다른 {ew.LABELS[field]}: {' / '.join(values)} (원자료 확인 전 확정 금지)")
        lines += ["- 아직 확인할 것: " + ("; ".join(packet["pending"]) or "기초값의 보류 없음")]
        if packet["next_checks"]:
            lines += ["- 사고 영향 검토 전에 필요한 일: " + "; ".join(packet["next_checks"])]
    lines += ["", "이 자료는 사고 유형·누출량·피해 범위 또는 법적 시나리오 선정 결과가 아닙니다."]
    return "\n".join(lines)
