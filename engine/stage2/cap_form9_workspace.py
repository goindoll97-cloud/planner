from __future__ import annotations

"""별지 제9호(장치·설비 목록 및 명세) authoring support.

시설 목록(구분기호·설비명·취급물질·설계용량·취급량)과 물질 정보(CAS·상태·함량)는
앞 서식에서 자동으로 가져오고, 사람은 설비별 연결구·압력·온도만 적는다.
입력은 별도 사실(cap.workspace.equipment_specs)로 저장돼 별지 제1호 시설 표를
다시 저장해도 사라지지 않는다.
"""

from typing import Any, Mapping

from .cap_form9_engine import build_cap_form9_data
from .cap_shared_facts import SPEC_KEY, equipment_specs, spec_key, workspace_facility_rows
from .project import Stage2Project

# (column, label, help)
SPEC_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("최대 연결구 크기(mm)", "최대 연결구 크기(mm)",
     "그 설비에 붙은 배관 연결구 중 가장 큰 호칭경(mm)입니다. P&ID나 배관 명세에서 확인합니다. 해당 없으면 '-'."),
    ("설계압력", "설계압력(MPa)",
     "설계도서의 설계압력입니다. MPa로 적고, kPa·bar로 적으면 자동으로 MPa로 바꿉니다. 해당 없으면 '-'."),
    ("운전압력", "운전압력(MPa)", "평소 운전하는 압력입니다. 단위 규칙은 설계압력과 같습니다."),
    ("설계온도", "설계온도(℃)", "설계도서의 설계온도입니다. 해당 없으면 '-'."),
    ("운전온도", "운전온도(℃)", "평소 운전하는 온도입니다."),
    ("비고", "비고", "P&ID 번호 등 참고할 내용을 적습니다. 없으면 비워 둡니다."),
)
COLUMN_IDS = tuple(column for column, _, _ in SPEC_COLUMNS)
REQUIRED = COLUMN_IDS[:5]


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def rows(project: Stage2Project) -> list[dict[str, Any]]:
    """One row per facility: shared facts (read-only) plus the editable spec columns."""
    prepared = {row["구분기호"] or row["장치·설비명"]: row for row in build_cap_form9_data(project).rows}
    out = []
    for facility in workspace_facility_rows(project):
        tag = _clean(facility.get("설비번호"))
        name = _clean(facility.get("설비명"))
        shown = prepared.get(tag or name, {})
        item = {
            "구분기호": tag, "장치·설비명": name, "취급물질": _clean(facility.get("취급물질")),
            "설계용량(m3)": shown.get("설계용량(m3)", ""), "취급량(ton)": shown.get("취급량(ton)", ""),
        }
        for column in COLUMN_IDS:
            item[column] = _clean(facility.get(column))
        out.append(item)
    return out


def save_specs(project: Stage2Project, edited: list[Mapping[str, Any]]) -> int:
    """Store the edited spec cells per facility; blank cells never erase saved values."""
    current = equipment_specs(project)
    for row in edited:
        tag, name = _clean(row.get("구분기호")), _clean(row.get("장치·설비명"))
        key = spec_key({"설비번호": tag, "설비명": name})
        if not key:
            continue
        entry = dict(current.get(key, {}))
        entry["설비번호"], entry["설비명"] = tag, name
        for column in COLUMN_IDS:
            value = _clean(row.get(column))
            if value:
                entry[column] = value
        current[key] = entry
    project.set_field(SPEC_KEY, "장치·설비 명세(별지 제9호 작성대)", list(current.values()), "USER_CONFIRMED",
                      note="CAP 작성대 별지 제9호에서 연결구·압력·온도 입력")
    return len(current)


def needs(project: Stage2Project) -> list[str]:
    return list(build_cap_form9_data(project).blockers)
