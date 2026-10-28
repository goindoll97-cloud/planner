"""사업장 업무에 올린 자료로 별지 제12·13·14호 작성자료를 백엔드에서 작성합니다.

사람이 별지 화면에서 표를 채우고 저장하지 않아도, 자료 접수(④ 보내기) 후 이 함수가
시나리오 목록·계산 입력·개시사건 개수·영향범위 결과를 저장합니다. 이미 사람이 저장한 값은 덮어쓰지 않고
빈 칸만 채웁니다. 자료가 부족한 칸은 비워 두고 `missing()`이 이유를 알려 줍니다.
"""
from __future__ import annotations

from datetime import date

from . import cap_form14_workspace as f14
from . import cap_impact_workspace as iw
from . import cap_scenario_workspace as sc
from . import scenario_evidence as se

AUTO_STATUS = "CALCULATED"
AUTO_NOTE = "사업장 업무 자료 접수에서 자동 작성(출처는 workspace.evidence_graph)"


def _is_person_saved(project, key) -> bool:
    record = project.get_field(key)
    return record is not None and record.status == "USER_CONFIRMED" and "자동 작성" not in record.note


def sync(project) -> dict[str, int]:
    """자동 작성을 실행하고 저장한 건수를 돌려줍니다. 바뀐 것이 없으면 0입니다."""
    counts = {"scenarios": 0, "frequency": 0, "impact": 0}
    saved = sc.saved_scenarios(project)
    person = _is_person_saved(project, sc.SCENARIO_KEY)
    known = {r.get("사고시나리오명") for r in saved}
    proposals = [] if person else [r for r in sc.proposed_scenarios(project) if r["사고시나리오명"] not in known]
    base = saved + proposals
    rows, _ = se.autofill(project, base)
    rows = [{k: ("" if v is None else str(v)) for k, v in r.items()} for r in rows]
    if rows and rows != [{k: str(v) for k, v in r.items()} for r in saved]:
        counts["scenarios"] = sc.save_scenarios(project, rows, status=AUTO_STATUS if not person else "USER_CONFIRMED",
                                                note=AUTO_NOTE)
    if not sc.saved_scenarios(project):
        return counts

    current = f14.rows(project)
    suggested = f14.apply_suggestions(project, current)
    for row in suggested:
        if any(str(row.get(e, "")) != "" for e in f14.EVENT_NAMES) and not str(row.get("개수 산정근거", "")).strip():
            row["개수 산정근거"] = "사업장 업무 자료 접수·설비 유형으로 자동 작성"
    keep = [{k: ("" if v is None else str(v)) for k, v in r.items() if k != "제안"} for r in suggested]
    old = [{k: str(v) for k, v in r.items() if k != "제안"} for r in current]
    stored = project.get_field(f14.FREQUENCY_KEY)
    person14 = _is_person_saved(project, f14.FREQUENCY_KEY)
    if any(any(r.get(e, "") != "" for e in f14.EVENT_NAMES) for r in keep) and (stored is None or keep != old or not stored.value):
        counts["frequency"] = f14.save(project, keep, status=AUTO_STATUS if not person14 else "USER_CONFIRMED", note=AUTO_NOTE)

    impacts = iw.evaluate(project, detection=_grade(project, "leak_detection"), isolation=_grade(project, "leak_isolation"))
    if any(i.off_site_m is not None for i in impacts) and not _is_person_saved(project, iw.IMPACT_TABLE_KEY):
        from hashlib import sha256
        from .project import EvidenceRef
        report = iw.report_docx(project, impacts)
        ref = EvidenceRef(source_type="PROGRAM_OUTPUT", source_name=f"영향범위_분석_근거서_{project.project_id}.docx",
                          sha256=sha256(report).hexdigest(), note=f"자동 작성 {date.today().isoformat()}")
        result = iw.apply_to_forms(project, impacts, evidence_refs=[ref])
        counts["impact"] = result["scenarios"]
    return counts


def _grade(project, field) -> str:
    tags = [t.tag for t in sc.evaluate(project) if t.verdict == sc.TARGET]
    return se.grade_defaults(project, tags).get(field, "C")


def missing(project) -> list[str]:
    """자료로 채우지 못해 사람이 자료를 더 올리거나 답해야 하는 항목."""
    items = []
    if not sc.evaluate(project):
        items.append("별지 제1호 시설 자료가 아직 연결되지 않았습니다. 사업장 업무에서 설비·물질 자료를 올리고 보내세요.")
    for impact in iw.evaluate(project):
        for problem in impact.problems:
            items.append(f"{impact.name}: {problem}")
    items.extend(f14.needs(project))
    return list(dict.fromkeys(items))
