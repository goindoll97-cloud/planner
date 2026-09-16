from __future__ import annotations

"""Expose concrete Stage-1 facility blockers instead of one generic request.

The CAP Appendix-4 calculator already identifies the exact company fact that is
missing (for example a missing facility row, density, design capacity, or
verified direct holding mass).  The core decision remains fail-closed; this
runtime hook only replaces the generic company-facing correction sentence with
those existing, actionable blockers.
"""

from typing import Any


_GENERIC_FACILITY_REQUEST = (
    "04_시설별최대보유량: 시설별 최대보유량 산정에 필요한 용량·밀도·"
    "직접확인 최대보유량 등 누락 항목을 확인하여 작성해 주세요."
)


def _replace_generic_facility_request(
    requests: list[str],
    blockers: list[str] | tuple[str, ...],
) -> list[str]:
    """Replace the generic facility request with deduplicated exact blockers."""
    clean_blockers = [str(value or "").strip() for value in blockers]
    clean_blockers = list(dict.fromkeys(value for value in clean_blockers if value))
    if not clean_blockers or _GENERIC_FACILITY_REQUEST not in requests:
        return list(requests)

    replacement = [f"04_시설별최대보유량: {value}" for value in clean_blockers]
    output: list[str] = []
    for request in requests:
        if request == _GENERIC_FACILITY_REQUEST:
            output.extend(replacement)
        else:
            output.append(request)
    return list(dict.fromkeys(output))


def _facility_blockers(intake: Any) -> list[str]:
    """Reproduce only the already-approved facility check to obtain its blockers."""
    from .cap_holding import app4_db_ready, assess_cap_holding
    from .cap_holding_screen import screen_facility_stage

    facilities = getattr(intake, "facilities", None)
    if facilities is None or getattr(facilities, "empty", True):
        return []

    screen = screen_facility_stage(intake)
    if not screen.ready or screen.blockers or not screen.row_numbers or not app4_db_ready():
        return []

    result = assess_cap_holding(
        intake=intake,
        facilities=facilities,
        legal_hits=screen.legal_hits,
        required_row_numbers=screen.row_numbers,
    )
    return list(result.blockers)


def install_stage1_request_detail_runtime() -> None:
    """Patch Stage-1 assessment so company requests name the exact missing facts."""
    from . import stage1_workbook

    original = stage1_workbook.assess_stage1_from_workbook
    if getattr(original, "_planner_detailed_facility_requests", False):
        return

    def assess_with_detailed_requests(intake):
        decision = original(intake)
        if _GENERIC_FACILITY_REQUEST in decision.company_requests:
            blockers = _facility_blockers(intake)
            if blockers:
                decision.company_requests = _replace_generic_facility_request(
                    list(decision.company_requests),
                    blockers,
                )
        return decision

    assess_with_detailed_requests._planner_detailed_facility_requests = True
    stage1_workbook.assess_stage1_from_workbook = assess_with_detailed_requests
