"""사실 카탈로그의 사실마다, 올린 회사 파일에서 알아봤는지 보여 줍니다(자료 접수 화면의 사실 표).

한 줄에 사실 하나:
- O: 파일에서 읽어 초안에 쓸 수 있음(출처 파일·위치를 함께 보여 줌)
- 빈칸: 올린 파일에서 찾지 못함(어느 파일에 어느 항목으로 적으면 되는지 알려 줌)
- 충돌: 파일끼리(또는 이미 저장된 값과) 값이 다름 — 절대 O로 표시하지 않음
- 확인: 읽었지만 그대로 쓸 수 없는 값(단위 없음·형식 오류 등)

설비·물질·감지기처럼 대상이 여럿인 사실은 대상마다 따로 보고(매트릭스), 사실 한 줄에는 ‘4대 중 3대’처럼 모읍니다.
계산값·법령 조회값·지도 조사값은 회사가 올리는 사실과 따로 ‘계산됨/계산 전’으로 보여 줍니다.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from . import cap_fact_catalog as catalog
from . import evidence_workspace as ew
from .project import CONFIRMED_STATUSES, Stage2Project

O = "O"
BLANK = ""
CONFLICT = "충돌"
CHECK = "확인"
DONE = "계산됨"
NOT_DONE = "계산 전"
MARK = {O: "O", BLANK: "", CONFLICT: "⚠ 충돌", CHECK: "△ 확인", DONE: "계산됨", NOT_DONE: "계산 전"}
ENTITY_NOUN = {"facility": ("설비", "대"), "material": ("물질", "종"), "detector": ("감지기", "개"), "psm_table": ("", "줄"),
               "target": ("보호대상", "곳")}
ENTITY_PREFIX = {"facility": "facility:", "material": "material:", "detector": "detector:", "psm_table": "table:",
                 "target": "target:"}


# ---------------------------------------------------------------- 사람 말

def where(fact: dict[str, Any]) -> str:
    """‘CSV 행 2 열 4’ 같은 내부 위치를 ‘02_equipment.csv 2번째 줄’로 바꿉니다."""
    doc, location = fact["document"], str(fact["location"])
    if fact.get("method") == "manual" or doc == "담당자 입력":
        return "직접 입력"
    match = re.match(r"^(.*?)\s*행 (\d+)(?: 열 \d+)?$", location)
    if not match:
        return f"{doc} ({location})"
    place, row = match.groups()
    if place == "CSV":
        return f"{doc} {row}번째 줄"
    if doc.lower().endswith((".xlsx", ".xlsm")):
        return f"{doc} ‘{place}’ 시트 {row}번째 줄"
    return f"{doc} {place} {row}번째 줄"


def _short(value: Any, limit: int = 40) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    if isinstance(value, float) and value == int(value):
        text = str(int(value))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _plain(reason: str) -> str:
    if "단위가 없음" in reason:
        return "머리글에 단위가 없어요. 열 이름에 단위를 붙여 주세요(예: 운전압력(MPa))."
    if "문장 또는 AI" in reason:
        return "표가 아닌 문장에서 찾은 값이라 그대로 쓰지 않았어요. 표나 ‘항목: 값’으로 적어 주세요."
    if "이름으로 연결" in reason or "지정한 번호" in reason:
        return "번호(설비번호·제품코드) 없이 이름으로 찾은 값이에요. 번호 열을 넣어 주세요."
    if "수식" in reason:
        return "엑셀 계산식 값이에요. 계산 결과를 값으로 붙여 넣어 주세요."
    if "병합" in reason:
        return "합쳐진 칸(병합 셀)에서 읽은 값이에요. 칸을 나눠 주세요."
    if "범위" in reason:
        return "숫자·단위를 확인해 주세요: " + reason
    return reason


def _fix_blank(item: catalog.Fact) -> str:
    return f"‘{catalog.file_label(item.file)}’ 파일에 ‘{item.template_header}’ 항목을 적어 올려 주세요."


# ---------------------------------------------------------------- 대상별 칸

def _slot_index(project: Stage2Project) -> dict[str, dict[str, Any]]:
    return {slot["key"]: slot for slot in ew.slots(project)}


def _cell(slot: dict[str, Any] | None) -> dict[str, Any]:
    """대상 하나의 사실 하나: 상태, 값, 출처, 고칠 점."""
    if slot is None:
        return {"state": BLANK, "value": "", "source": "", "fix": ""}
    if slot["chosen"]:
        fact = slot["chosen"]
        sources = list(dict.fromkeys(where(f) for f in slot["facts"]))
        return {"state": O, "value": fact["value"], "source": " / ".join(sources), "fix": ""}
    facts = slot["facts"]
    if slot["status"] == "값 충돌":
        parts = [f"{_short(f['value'])} ({where(f)})" for f in facts[:4]]
        return {"state": CONFLICT, "value": "", "source": " / ".join(dict.fromkeys(where(f) for f in facts)),
                "fix": "파일마다 값이 달라요: " + ", ".join(parts) + ". 맞는 값으로 파일을 고쳐 다시 올려 주세요."}
    reasons = ew.review_gate(slot) or [ew.value_problem(slot["field"], facts[0]["value"]) or "확인이 필요해요"]
    return {"state": CHECK, "value": facts[0]["value"], "source": " / ".join(dict.fromkeys(where(f) for f in facts)),
            "fix": _plain(reasons[0])}


def entities(project: Stage2Project, kind: str, table: str = "") -> list[str]:
    """그래프에 있는 이 종류의 대상(제외한 대상 빼고), 번호순. 공정안전보고서 표는 table로 그 서식의 줄만 고릅니다(읽은 순서)."""
    excluded = set(ew.excluded(project))
    prefix = ENTITY_PREFIX.get(kind, kind + ":") + (f"{table}/" if table else "")
    found = list(dict.fromkeys(slot["entity"] for slot in ew.slots(project) if slot["entity"].startswith(prefix)))
    found = [e for e in found if e not in excluded]
    return found if kind == "psm_table" else sorted(found)


def _table_title(table: str) -> str:
    from . import psm_table_workspace as pt
    return pt.SPECS[table].title if table in pt.SPECS else table


def _display_names(project: Stage2Project) -> dict[str, str]:
    names = {}
    for slot in ew.slots(project):
        if slot["field"] == "name":
            fact = slot["chosen"] or (slot["facts"][0] if slot["facts"] else None)
            if fact and str(fact["value"]).strip():
                names[slot["entity"]] = str(fact["value"]).strip()
    return names


def display(entity: str, names: dict[str, str]) -> str:
    if entity == ew.SITE_ENTITY:
        return "사업장"
    kind, code = entity.split(":", 1)
    if kind == "detector":
        return "감지기 " + code
    if kind == "table":
        return code.split("/", 1)[1]
    name = names.get(entity)
    return f"{name} ({code})" if name and name != code else code


# ---------------------------------------------------------------- 계산값·법령 조회값

def _derived_checks(project: Stage2Project) -> dict[str, Callable[[], tuple[bool, str]]]:
    def form1():
        from .cap_form1_engine import build_cap_form1_data
        return build_cap_form1_data(project)

    def all_have(rows, column):
        return bool(rows) and all(str(row.get(column) or "").strip() for row in rows)

    def first(blockers, fallback):
        return blockers[0] if blockers else fallback

    def facility_handling():
        data = form1()
        ok = all_have(data.facility_rows, "취급량(ton)")
        return ok, "" if ok else first(data.blockers, "설비의 설계용량·비중(또는 직접 확인한 양)이 필요해요.")

    def material_holding():
        data = form1()
        ok = all_have(data.chemical_rows, "사업장 내 최대보유량(ton)")
        return ok, "" if ok else first(data.blockers, "설비별 취급량이 먼저 계산돼야 해요.")

    def type_counts():
        from .cap_final_form_runtime import facility_type_counts
        ok = bool(facility_type_counts(project))
        return ok, "" if ok else "설비 목록의 시설유형이 필요해요."

    def lorries():
        ok = any(e.startswith("facility:") for e in ew.confirmed_entities(project))
        return ok, "" if ok else "설비 목록이 필요해요."

    def dike():
        from .cap_form10_engine import build_cap_form10_data
        data = build_cap_form10_data(project)
        return data.ready, "" if data.ready else first(data.blockers, "확산방지설비 자료가 필요해요.")

    def spec_units():
        from .cap_form9_engine import build_cap_form9_data
        data = build_cap_form9_data(project)
        return data.ready, "" if data.ready else first(data.blockers, "설비 사양이 필요해요.")

    def legal_rows():
        from .cap_chemical_legal import build_cap_chemical_legal_data
        data = build_cap_chemical_legal_data(project)
        ok = bool(data.rows) and not data.blockers
        return ok, "" if ok else first(data.blockers, "물질 목록(CAS·함량)이 필요해요.")

    def thresholds():
        data = form1()
        ok = all_have(data.chemical_rows, "하위규정수량(ton)")
        return ok, "" if ok else first(data.blockers, "승인된 법령 기준표가 필요해요.")

    def writing_level():
        ok = project.cap_group in {"1군", "2군"}
        return ok, "" if ok else "‘사업장 판정하기’에서 작성수준을 판정해 주세요."

    return {
        "computed.facility_handling_ton": facility_handling,
        "computed.material_max_holding_ton": material_holding,
        "computed.facility_type_counts": type_counts,
        "computed.lorry_count": lorries,
        "computed.dike_required_volume": dike,
        "computed.dike_effective_volume": dike,
        "computed.dike_review": dike,
        "computed.connection_mm": spec_units,
        "legal.substance_category": legal_rows,
        "legal.unique_number": legal_rows,
        "legal.lower_threshold": thresholds,
        "legal.upper_threshold": thresholds,
        "legal.writing_level": writing_level,
    }


def _derived_row(project, item, checks, slots) -> dict[str, Any]:
    check = checks.get(item.id)
    try:
        ok, why = check() if check else (False, "")
    except Exception:          # 계산 엔진이 실패해도 표는 보여 줍니다
        ok, why = False, "계산하지 못했어요. 앞의 회사 사실을 먼저 채워 주세요."
    note = why
    if item.id == "legal.writing_level":
        slot = slots.get(f"{ew.SITE_ENTITY}|writing_level")
        stated = (slot["chosen"] or slot["facts"][0])["value"] if slot and slot["facts"] else ""
        if stated and ok and str(project.cap_group) not in str(stated):
            note = f"파일에 적힌 값(‘{stated}’)과 판정({project.cap_group})이 달라요. 판정 결과를 씁니다."
        elif stated and not ok:
            note = f"파일에 적힌 값: ‘{stated}’. " + why
    return {"state": DONE if ok else NOT_DONE, "value": project.cap_group if item.id == "legal.writing_level" and ok else "",
            "source": catalog.source_label(item.source), "fix": note}


def _survey_row(project, item) -> dict[str, Any]:
    from .cap_form8_engine import build_cap_form8_data
    try:
        data = build_cap_form8_data(project)
    except Exception:
        data = None
    if data is not None and data.no_protected_targets:
        return {"state": O, "value": "보호대상 없음", "source": "지도·현장 조사", "fix": ""}
    rows = list(data.rows) if data else []
    have = [r for r in rows if str(r.get(item.column) or "").strip()]
    if rows and len(have) == len(rows):
        return {"state": O, "value": f"{len(rows)}곳", "source": "지도·현장 조사", "fix": ""}
    fix = ("‘사고시나리오 결과’ 화면에서 지도에 사업장 경계를 그리고 주변 보호대상 조사표를 내려받아 채워 올려 주세요"
           "(보호대상이 없으면 조사표의 ‘500m 안 보호대상 없음’에 ‘예’).")
    if rows:
        return {"state": CHECK, "value": f"{len(rows)}곳 중 {len(have)}곳", "source": "지도·현장 조사", "fix": fix}
    return {"state": BLANK, "value": "", "source": "", "fix": fix}


# ---------------------------------------------------------------- 사실 한 줄

def _site_row(project, item, slots) -> dict[str, Any]:
    if item.field_key == "@company_name":
        slot = slots.get(f"{ew.SITE_ENTITY}|company_name")
        cell = {"state": O, "value": project.company_name, "source": "사업장 만들 때 입력", "fix": ""}
        if slot and any(str(f["value"]).strip() != project.company_name for f in slot["facts"]):
            cell = {"state": CONFLICT, "value": "", "source": "사업장 만들 때 입력 / 파일",
                    "fix": f"파일의 사업장명이 등록한 이름({project.company_name})과 달라요."}
        return cell
    cell = _cell(slots.get(f"{ew.SITE_ENTITY}|{item.evidence_field}"))
    record = project.get_field(item.field_key) if item.field_key else None
    stored = _stored_value(record, item)
    elsewhere = record is not None and not ew.file_linked(record) and record.status in CONFIRMED_STATUSES \
        and stored not in (None, "", [])
    if cell["state"] == O and elsewhere and str(stored).strip() != str(cell["value"]).strip() \
            and item.id != "site.loading_facility_count":
        return {"state": CONFLICT, "value": "", "source": cell["source"] + " / 이미 저장된 값",
                "fix": f"파일 값 ‘{_short(cell['value'])}’이 이미 저장된 값 ‘{_short(stored)}’과 달라요. 맞는 값을 확인해 주세요."}
    if cell["state"] == BLANK and elsewhere:
        return {"state": O, "value": stored, "source": "파일 아님: 직접 입력한 값", "fix": ""}
    if cell["state"] == BLANK:
        cell["fix"] = _fix_blank(item)
    return cell


def _stored_value(record, item):
    """작성자료에 이미 있는 이 사실의 값(묶음·한 행짜리 표·조건부 서식 적용여부 칸까지 찾아봄)."""
    if record is None:
        return None
    value = record.value
    if not item.column:
        return value
    if item.field_key == ew.APPLICABILITY_KEY:
        form, _, part = item.column.partition("#")
        row = next((r for r in value or [] if isinstance(r, dict) and str(r.get("서식번호")) == form), {})
        return row.get("확인근거" if part else "적용여부")
    if isinstance(value, list) and value and isinstance(value[0], dict) and item.field_key in ew.SINGLE_ROW_KEYS:
        return value[0].get(item.column)
    if isinstance(value, dict):
        return value.get(item.column)
    return None


def _entity_row(project, item, slots, kind_entities) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    noun, counter = ENTITY_NOUN[item.kind]
    targets = kind_entities.get(item.kind, [])
    if item.kind == "psm_table":
        noun = _table_title(item.table)
        targets = kind_entities.get(("psm_table", item.table), [])
    if item.kind == "material" and item.field_key == ew.HAZARD_KEY and item.evidence_field != "representative_reason":
        chosen = {s["entity"] for s in slots.values() if s["field"] == "representative_reason" and s["chosen"]}
        targets = [e for e in targets if e in chosen] or targets
    if item.identifier:
        cells = {e: {"state": O, "value": e.split(":", 1)[1], "source": "", "fix": ""} for e in targets}
        if not targets:
            return {"state": BLANK, "value": "", "source": "", "fix": _fix_blank(item)}, {}
        files = {where(f).split(" ")[0] for s in slots.values() if s["entity"] in targets for f in s["facts"]}
        return {"state": O, "value": f"{noun} {len(targets)}{counter}", "source": ", ".join(sorted(files)), "fix": ""}, cells
    cells = {e: _cell(slots.get(f"{e}|{item.evidence_field}")) for e in targets}
    states = [c["state"] for c in cells.values()]
    if not cells or not any(states):
        return {"state": BLANK, "value": "", "source": "", "fix": _fix_blank(item) if targets else
                f"먼저 ‘{catalog.file_label(item.file)}’ 파일을 올려 주세요."}, cells
    have = sum(s == O for s in states)
    sources = list(dict.fromkeys(c["source"].split(" / ")[0].split(" ")[0] for c in cells.values() if c["source"]))
    if CONFLICT in states:
        bad = [display(e, {}) for e, c in cells.items() if c["state"] == CONFLICT]
        first = next(c for c in cells.values() if c["state"] == CONFLICT)
        return {"state": CONFLICT, "value": f"{len(targets)}{counter} 중 {have}{counter}", "source": ", ".join(sources),
                "fix": f"{', '.join(bad[:5])}: " + first["fix"]}, cells
    if CHECK in states:
        bad = [display(e, {}) for e, c in cells.items() if c["state"] == CHECK]
        first = next(c for c in cells.values() if c["state"] == CHECK)
        return {"state": CHECK, "value": f"{len(targets)}{counter} 중 {have}{counter}", "source": ", ".join(sources),
                "fix": f"{', '.join(bad[:5])}: " + first["fix"]}, cells
    if have == len(targets) or not item.required:
        if len(targets) == 1:
            value = _short(next(c["value"] for c in cells.values() if c["state"] == O))
        else:
            value = f"{len(targets)}{counter} 모두" if have == len(targets) else f"{len(targets)}{counter} 중 {have}{counter}"
        return {"state": O, "value": value, "source": ", ".join(sources), "fix": ""}, cells
    missing = [display(e, {}) for e, c in cells.items() if c["state"] == BLANK]
    return {"state": BLANK, "value": f"{len(targets)}{counter} 중 {have}{counter}", "source": ", ".join(sources),
            "fix": f"{', '.join(missing[:5])}{' 외' if len(missing) > 5 else ''}: " + _fix_blank(item)}, cells


def _not_applicable(project, table: str) -> bool:
    from . import psm_table_workspace as pt
    return table in pt.SPECS and pt.SPECS[table].conditional and pt.applicability(project, table)[0] == pt.NOT_APPLICABLE


def project_docs(project: Stage2Project) -> tuple[str, ...]:
    """이 사업장이 작성하는 문서(작성범위). 정해지지 않았으면 두 문서 모두."""
    docs = tuple(d for d, on in (("CAP", project.cap_in_scope), ("PSM", project.psm_in_scope)) if on)
    return docs or catalog.DOCS


def fact_rows(project: Stage2Project, *, group: str = "", forms=(), docs=None) -> list[dict[str, Any]]:
    """사실 표. 회사 사실을 먼저, 그다음 계산값·법령 조회값·지도 조사값을 보여 줍니다.
    docs=("PSM",)이면 공정안전보고서에 쓰이는 사실만. 공정안전보고서 표는 줄이 없으면 구별 열 한 줄로만 알립니다."""
    docs = project_docs(project) if docs is None else docs
    slots = _slot_index(project)
    kind_entities = {kind: entities(project, kind) for kind in ENTITY_NOUN if kind != "psm_table"}
    for table in catalog.psm_tables():
        kind_entities[("psm_table", table)] = entities(project, "psm_table", table)
    checks = _derived_checks(project)
    rows = []
    shown_tables: set[str] = set()
    for item in catalog.facts(group=group, forms=forms, docs=docs):
        if item.source in ("company", "project"):
            if item.kind in catalog.SITE_KINDS:
                cell = _site_row(project, item, slots)
            elif item.kind == "psm_table" and (_not_applicable(project, item.table) or
                                               not kind_entities[("psm_table", item.table)]):
                if item.table in shown_tables:
                    continue                     # 줄이 없는 표는 한 줄로만 알립니다
                shown_tables.add(item.table)
                if _not_applicable(project, item.table):
                    cell = {"state": O, "value": "해당 없음", "source": "적용여부: 해당 없음", "fix": ""}
                else:
                    cell = {"state": BLANK, "value": "", "source": "",
                            "fix": f"‘{_table_title(item.table)}’ 표를 올려 주세요(한 줄에 하나, 구별 열: "
                                   + ", ".join(i.template_header for i in catalog.psm_tables()[item.table] if i.identifier) + ")."
                                   + (" 해당하지 않으면 사업개요 파일에 ‘적용여부: 해당 없음’과 근거를 적어 주세요."
                                      if _conditional(item.table) else "")}
                item = next(i for i in catalog.psm_tables()[item.table] if i.identifier)
            elif item.kind in ENTITY_NOUN:
                cell, _ = _entity_row(project, item, slots, kind_entities)
            else:
                continue
        elif item.source == "survey":
            if item.kind in catalog.SITE_KINDS:
                cell = _site_row(project, item, slots)
            elif kind_entities.get("target"):
                cell, _ = _entity_row(project, item, slots, kind_entities)
            else:
                cell = _survey_row(project, item)
        else:
            cell = _derived_row(project, item, checks, slots)
        rows.append({"사실": item.label, "종류": catalog.kind_label(item.kind), "상태": MARK[cell["state"]],
                     "값": _short(cell["value"]) if cell["value"] not in (None, "") else "",
                     "출처": cell["source"], "쓰이는 곳": item.used_in_text,
                     "올릴 파일": catalog.file_label(item.file) if item.file else catalog.source_label(item.source),
                     "필요": "필수" if item.required else ("해당 시: " + item.condition if item.condition else "선택"),
                     "고칠 점": cell["fix"],
                     "_id": item.id, "_state": cell["state"], "_company": item.from_company, "_kind": item.kind,
                     "_forms": item.forms, "_groups": item.groups, "_required": item.required, "_docs": item.docs})
    return rows


def _conditional(table: str) -> bool:
    from . import psm_table_workspace as pt
    return table in pt.SPECS and pt.SPECS[table].conditional


def matrix(project: Stage2Project, kind: str, *, forms=(), required_only: bool = False) -> dict[str, Any]:
    """설비×항목·물질×항목·감지기×항목 표. 행=대상, 열=필요 항목, 칸=O/빈칸/⚠ 충돌/△ 확인."""
    slots = _slot_index(project)
    names = _display_names(project)
    targets = entities(project, kind)
    items = [i for i in catalog.facts(kinds=[kind], forms=forms, company=True)
             if not i.identifier and i.evidence_field and (i.required or not required_only)]
    columns = [i.label for i in items]
    rows, problems = [], []
    for entity in targets:
        row = {"대상": display(entity, names)}
        for item in items:
            cell = _cell(slots.get(f"{entity}|{item.evidence_field}"))
            row[item.label] = MARK[cell["state"]]
            if cell["state"] in (CONFLICT, CHECK):
                problems.append({"대상": row["대상"], "항목": item.label, "상태": MARK[cell["state"]], "고칠 점": cell["fix"]})
        rows.append(row)
    return {"columns": columns, "rows": rows, "problems": problems}


# ---------------------------------------------------------------- 올리기 전후 비교

def snapshot(project: Stage2Project) -> dict[str, set]:
    """O인 칸과 충돌인 칸의 모음(사업장 사실 1칸, 대상별 사실은 대상마다 1칸)."""
    slots = _slot_index(project)
    filled, conflicts = set(), set()
    for item in catalog.facts(company=True, docs=project_docs(project)):
        if not item.evidence_field or item.identifier:
            continue
        prefix = ew.SITE_ENTITY if item.kind in catalog.SITE_KINDS else None
        keys = [f"{prefix}|{item.evidence_field}"] if prefix else \
            [f"{e}|{item.evidence_field}" for e in entities(project, item.kind, item.table)] if item.kind in ENTITY_NOUN else []
        for key in keys:
            state = _cell(slots.get(key))["state"]
            if state == O:
                filled.add((item.id, key))
            elif state == CONFLICT:
                conflicts.add((item.id, key))
    return {"filled": filled, "conflicts": conflicts}


def change(before: dict[str, set] | None, after: dict[str, set]) -> dict[str, int]:
    before = before or {"filled": set(), "conflicts": set()}
    return {"filled_added": len(after["filled"] - before["filled"]),
            "filled_removed": len(before["filled"] - after["filled"]),
            "conflicts_added": len(after["conflicts"] - before["conflicts"]),
            "conflicts": len(after["conflicts"])}


def change_text(delta: dict[str, int]) -> str:
    parts = [f"O가 {delta['filled_added']}개 늘었고"]
    parts.append(f"새 충돌 {delta['conflicts_added']}개" if delta["conflicts_added"] else "새 충돌은 없어요")
    text = " ".join(parts)
    if delta["filled_removed"]:
        text += f". O였던 {delta['filled_removed']}개가 다시 확인이 필요해졌어요"
    if delta["conflicts"]:
        text += f" (지금 충돌 {delta['conflicts']}개)"
    return text + "."


def summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    company = [r for r in rows if r["_company"]]
    return {"company": len(company), "filled": sum(r["_state"] == O for r in company),
            "blank_required": sum(r["_state"] == BLANK and r["_required"] for r in company),
            "conflicts": sum(r["_state"] == CONFLICT for r in company), "checks": sum(r["_state"] == CHECK for r in company),
            "derived": len(rows) - len(company), "derived_done": sum(r["_state"] in (DONE, O) for r in rows if not r["_company"])}
