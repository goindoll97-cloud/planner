from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .intake import selected_requirement_specs
from .project import CONFIRMED_STATUSES, Stage2Project
from .requirements import RequirementSpec


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
