from __future__ import annotations

from .cross_validation import CrossValidationReport, ValidationIssue, validate_stage2_project
from .project import Stage2Project


def validate_selected_scope(project: Stage2Project) -> CrossValidationReport:
    """Run existing validation and keep only issues in the selected authoring scope."""
    if not project.scope_confirmed:
        return CrossValidationReport(issues=(), checked_rules=0)

    raw = validate_stage2_project(project)
    allowed_systems = {"COMMON"}
    if project.psm_in_scope:
        allowed_systems.add("PSM")
    if project.cap_in_scope:
        allowed_systems.add("CAP")

    issues: tuple[ValidationIssue, ...] = tuple(
        issue for issue in raw.issues if issue.system in allowed_systems
    )
    return CrossValidationReport(issues=issues, checked_rules=raw.checked_rules)
