from __future__ import annotations

"""Facts entered once in the CAP workspace and reused by every 별지.

The 별지 제1호 facility grid is the single place where 취급시설 are entered.
Forms that list the same facilities (제4·5호 시설 유형별 기수, 제9호 장치·설비
목록, 제10·11호 구분기호 연결) read them through `workspace_facility_rows`
instead of asking again.
"""

from collections.abc import Mapping
from typing import Any

from .project import CONFIRMED_STATUSES, Stage2Project

WORKSPACE_FACILITY_KEY = "cap.workspace.facilities"
EXCLUDED_FLAG = "제외시설여부"


def workspace_facility_rows(project: Stage2Project) -> list[dict[str, Any]]:
    """Confirmed workspace facilities that count as the site's 취급시설."""
    record = project.get_field(WORKSPACE_FACILITY_KEY)
    if record is None or record.status not in CONFIRMED_STATUSES or not isinstance(record.value, list):
        return []
    return [
        dict(row) for row in record.value
        if isinstance(row, Mapping) and str(row.get(EXCLUDED_FLAG, "")).upper() != "Y"
    ]


def workspace_rows_of_type(project: Stage2Project, facility_type: str) -> list[dict[str, Any]]:
    """All confirmed workspace rows of one 시설유형, including ones excluded from holdings."""
    record = project.get_field(WORKSPACE_FACILITY_KEY)
    if record is None or record.status not in CONFIRMED_STATUSES or not isinstance(record.value, list):
        return []
    return [dict(row) for row in record.value if isinstance(row, Mapping) and row.get("시설유형") == facility_type]
