from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .project import CONFIRMED_STATUSES, Stage2Project
from .requirements import cap_field_labels, cap_manual_source, cap_requirement_specs


@dataclass(frozen=True)
class CAPDataRequest:
    requirement_key: str
    section: str
    label: str
    manual_pages: tuple[int, ...]
    missing_fields: tuple[str, ...]
    missing_labels: tuple[str, ...]
    suggested_evidence: tuple[str, ...]
    source_owner: str
    input_kind: str
    automation: str
    request_text: str
    priority: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _priority(spec) -> str:
    if spec.input_kind in {"DRAWING", "DRAWING_AND_DATA", "DRAWING_AND_TABLE", "ANALYSIS_DOCUMENT"}:
        return "HIGH"
    if "KORA" in spec.automation or "CALCULATE" in spec.automation:
        return "HIGH"
    if spec.source_owner == "COMPANY":
        return "MEDIUM"
    return "MEDIUM"


def build_cap_data_requests(project: Stage2Project) -> list[CAPDataRequest]:
    """Return unresolved CAP inputs only when CAP is selected for authoring."""
    if not project.cap_in_scope:
        return []

    group = project.cap_group if project.cap_group in {"1군", "2군"} else "1군"
    labels = cap_field_labels()
    requests: list[CAPDataRequest] = []
    for spec in cap_requirement_specs(group):
        missing: list[str] = []
        for field_key in spec.field_keys:
            record = project.get_field(field_key)
            if record is None or record.status not in CONFIRMED_STATUSES:
                missing.append(field_key)
        if not missing:
            continue
        requests.append(
            CAPDataRequest(
                requirement_key=spec.key,
                section=spec.section,
                label=spec.label,
                manual_pages=spec.manual_pages,
                missing_fields=tuple(missing),
                missing_labels=tuple(labels.get(key, key) for key in missing),
                suggested_evidence=spec.suggested_evidence,
                source_owner=spec.source_owner,
                input_kind=spec.input_kind,
                automation=spec.automation,
                request_text=spec.request_text,
                priority=_priority(spec),
            )
        )
    return requests


def cap_request_summary(project: Stage2Project) -> dict[str, Any]:
    rows = build_cap_data_requests(project)
    by_section: dict[str, int] = {}
    for row in rows:
        by_section[row.section] = by_section.get(row.section, 0) + 1
    return {
        "manual_source": cap_manual_source(),
        "request_count": len(rows),
        "high_priority_count": sum(row.priority == "HIGH" for row in rows),
        "by_section": by_section,
        "requests": [row.to_dict() for row in rows],
    }
