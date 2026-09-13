from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .project import CONFIRMED_STATUSES, Stage2Project
from .requirements import psm_example_source, psm_field_labels, psm_requirement_specs


@dataclass(frozen=True)
class PSMDataRequest:
    requirement_key: str
    section: str
    label: str
    example_pages: tuple[int, ...]
    missing_fields: tuple[str, ...]
    missing_labels: tuple[str, ...]
    suggested_evidence: tuple[str, ...]
    cross_checks: tuple[str, ...]
    source_owner: str
    input_kind: str
    automation: str
    request_text: str
    legal_basis: str
    legal_status: str
    outline_checkbox_status: str
    priority: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _priority(spec) -> str:
    if spec.legal_status == "VERIFY_CURRENT":
        return "VERIFY"
    if spec.legal_status in {"STATUTORY_REQUIRED", "STATUTORY_REQUIRED_WHEN_APPLICABLE"}:
        return "HIGH"
    if spec.input_kind in {
        "DRAWING",
        "DRAWING_SET",
        "CALCULATION_AND_DRAWING",
        "STRUCTURED_TABLE_AND_CALCULATION",
        "ANALYSIS_DOCUMENT",
        "CALCULATION_AND_MODEL",
    }:
        return "HIGH"
    if "CALCULATE" in spec.automation or "CROSSCHECK" in spec.automation:
        return "HIGH"
    return "MEDIUM"


def build_psm_data_requests(project: Stage2Project) -> list[PSMDataRequest]:
    """Return unresolved PSM inputs without re-requesting confirmed facts.

    Historical example-book content never becomes legal authority by itself.
    VERIFY_CURRENT rows are shown as non-blocking verification requests even
    when the field has not yet been created, while required rows participate in
    the normal completeness gate.
    """
    if project.psm_required is not True:
        return []

    labels = psm_field_labels()
    requests: list[PSMDataRequest] = []
    for spec in psm_requirement_specs():
        missing: list[str] = []
        for field_key in spec.field_keys:
            record = project.get_field(field_key)
            if record is None or record.status not in CONFIRMED_STATUSES:
                missing.append(field_key)

        if not missing:
            continue
        if not spec.required and spec.legal_status != "VERIFY_CURRENT":
            continue

        requests.append(
            PSMDataRequest(
                requirement_key=spec.key,
                section=spec.section,
                label=spec.label,
                example_pages=spec.manual_pages,
                missing_fields=tuple(missing),
                missing_labels=tuple(labels.get(key, key) for key in missing),
                suggested_evidence=spec.suggested_evidence,
                cross_checks=spec.cross_checks,
                source_owner=spec.source_owner,
                input_kind=spec.input_kind,
                automation=spec.automation,
                request_text=spec.request_text,
                legal_basis=spec.legal_basis,
                legal_status=spec.legal_status,
                outline_checkbox_status=spec.outline_checkbox_status,
                priority=_priority(spec),
            )
        )
    return requests


def psm_request_summary(project: Stage2Project) -> dict[str, Any]:
    rows = build_psm_data_requests(project)
    by_section: dict[str, int] = {}
    for row in rows:
        by_section[row.section] = by_section.get(row.section, 0) + 1
    return {
        "sources": psm_example_source(),
        "request_count": len(rows),
        "high_priority_count": sum(row.priority == "HIGH" for row in rows),
        "verify_count": sum(row.priority == "VERIFY" for row in rows),
        "by_section": by_section,
        "requests": [row.to_dict() for row in rows],
    }
