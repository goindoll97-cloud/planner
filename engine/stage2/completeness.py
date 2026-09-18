from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Mapping

from .intake import selected_requirement_specs
from .project import CONFIRMED_STATUSES, Stage2Project
from .requirements import RequirementSpec


PSM_CONDITIONAL_FORM_BY_REQUIREMENT = {
    "psm.psi.fire_protection": "17-3",
    "psm.psi.fire_detection": "17-4",
    "psm.psi.gas_detection": "17-5",
    "psm.psi.fireproofing": "18",
    "psm.psi.local_exhaust": "19",
    "psm.psi.ex_equipment": "20",
    "psm.risk.consequence": "19-2",
}


def _norm(value: object) -> str:
    import re
    return re.sub(r"[^0-9a-z가-힣]", "", str(value or "").lower())


def _explicitly_not_applicable(project: Stage2Project, spec: RequirementSpec) -> bool:
    form_no = PSM_CONDITIONAL_FORM_BY_REQUIREMENT.get(spec.key)
    if not form_no:
        return False
    record = project.get_field("psm.psi.form_applicability")
    if record is None or not isinstance(record.value, list):
        return False
    for row in record.value:
        if not isinstance(row, Mapping):
            continue
        normalized = {_norm(key): value for key, value in row.items()}
        row_form = str(
            normalized.get(_norm("서식번호"))
            or normalized.get(_norm("form_no"))
            or ""
        ).strip()
        if row_form != form_no:
            continue
        applicability = _norm(
            normalized.get(_norm("적용여부"))
            or normalized.get(_norm("applicability"))
            or ""
        )
        basis = str(
            normalized.get(_norm("확인근거"))
            or normalized.get(_norm("basis"))
            or ""
        ).strip()
        return applicability in {"해당없음", "미적용", "아니오", "없음"} and bool(basis)
    return False


@dataclass(frozen=True)
class RequirementResult:
    key: str
    system: str
    section: str
    label: str
    state: str
    completion_pct: float
    missing_fields: tuple[str, ...]
    draft_fields: tuple[str, ...]
    hold_fields: tuple[str, ...]
    legal_basis: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_requirement(project: Stage2Project, spec: RequirementSpec) -> RequirementResult:
    if _explicitly_not_applicable(project, spec):
        return RequirementResult(
            key=spec.key,
            system=spec.system,
            section=spec.section,
            label=spec.label,
            state="NOT_REQUIRED",
            completion_pct=100.0,
            missing_fields=(),
            draft_fields=(),
            hold_fields=(),
            legal_basis=spec.legal_basis,
        )

    if not spec.required:
        return RequirementResult(
            key=spec.key,
            system=spec.system,
            section=spec.section,
            label=spec.label,
            state="NOT_REQUIRED",
            completion_pct=100.0,
            missing_fields=(),
            draft_fields=(),
            hold_fields=(),
            legal_basis=spec.legal_basis,
        )

    if not spec.field_keys:
        return RequirementResult(
            key=spec.key,
            system=spec.system,
            section=spec.section,
            label=spec.label,
            state="HOLD",
            completion_pct=0.0,
            missing_fields=(),
            draft_fields=(),
            hold_fields=(),
            legal_basis=spec.legal_basis,
        )

    confirmed = 0
    missing: list[str] = []
    drafts: list[str] = []
    holds: list[str] = []

    for key in spec.field_keys:
        record = project.get_field(key)
        if record is None:
            missing.append(key)
            continue
        if record.status in CONFIRMED_STATUSES:
            confirmed += 1
        elif record.status == "AI_DRAFT":
            drafts.append(key)
        else:
            holds.append(key)

    pct = confirmed / len(spec.field_keys) * 100.0
    if confirmed == len(spec.field_keys):
        state = "READY"
    elif drafts and not missing and not holds:
        state = "REVIEW_REQUIRED"
    else:
        state = "HOLD"

    return RequirementResult(
        key=spec.key,
        system=spec.system,
        section=spec.section,
        label=spec.label,
        state=state,
        completion_pct=round(pct, 1),
        missing_fields=tuple(missing),
        draft_fields=tuple(drafts),
        hold_fields=tuple(holds),
        legal_basis=spec.legal_basis,
    )


def _aggregate_state(results: list[RequirementResult]) -> str:
    """Fail closed: HOLD always outranks REVIEW_REQUIRED and READY."""
    if not results:
        return "NOT_REQUIRED"
    states = {result.state for result in results}
    if "HOLD" in states:
        return "HOLD"
    if "REVIEW_REQUIRED" in states:
        return "REVIEW_REQUIRED"
    if states.issubset({"READY", "NOT_REQUIRED"}):
        return "READY"
    return "HOLD"


def evaluate_project_completeness(project: Stage2Project) -> dict[str, Any]:
    specs = selected_requirement_specs(project)
    results = [evaluate_requirement(project, spec) for spec in specs]

    def summary(system: str) -> dict[str, Any]:
        selected = [r for r in results if r.system in {"COMMON", system}]
        if not selected:
            return {"required_n": 0, "ready_n": 0, "completion_pct": 100.0, "state": "NOT_REQUIRED"}
        ready = [r for r in selected if r.state == "READY"]
        pct = sum(r.completion_pct for r in selected) / len(selected)
        return {
            "required_n": len(selected),
            "ready_n": len(ready),
            "completion_pct": round(pct, 1),
            "state": _aggregate_state(selected),
        }

    overall_pct = (
        sum(r.completion_pct for r in results) / len(results)
        if results else 100.0
    )

    return {
        "scope_confirmed": project.scope_confirmed,
        "overall": {
            "completion_pct": round(overall_pct, 1),
            "state": _aggregate_state(results),
            "required_n": len(results),
            "ready_n": sum(r.state == "READY" for r in results),
        },
        "psm": summary("PSM") if project.psm_in_scope else {"state": "NOT_REQUIRED", "completion_pct": 100.0},
        "cap": summary("CAP") if project.cap_in_scope else {"state": "NOT_REQUIRED", "completion_pct": 100.0},
        "requirements": [r.to_dict() for r in results],
    }
