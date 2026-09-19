from __future__ import annotations

"""별지 제3호(사업장 일반정보) authoring support.

Values already entered or computed in earlier forms are shown as auto-filled
rows and never asked again; only the remaining company facts are requested.
"""

from dataclasses import dataclass
from typing import Any

from . import cap_form2_workspace as f2
from .cap_workspace import load_form_schema
from .project import Stage2Project


@dataclass(frozen=True)
class AutoRow:
    label: str
    value: str
    source: str


def fields(step_id: str | None = None) -> list[dict[str, Any]]:
    items = load_form_schema(3)["sections"][0]["fields"]
    return [item for item in items if step_id is None or item["step"] == step_id]


def current_value(project: Stage2Project, key: str) -> str:
    record = project.get_field(key)
    return "" if record is None or record.value is None else str(record.value).strip()


def auto_rows(project: Stage2Project) -> list[AutoRow]:
    """Cells filled from earlier forms; shown read-only with where they came from."""
    sub = f2.submission(project)
    return [
        AutoRow("사업장명", sub["company"], "판정진단"),
        AutoRow("단위공장명", sub["unit_plant"], "별지 제2호에서 입력"),
        AutoRow("제출구분", " · ".join(x for x in (sub["type"], sub["reason"]) if x), "별지 제2호에서 입력"),
        AutoRow("작성수준", project.cap_group or "", "별지 제1호에서 계산"),
    ]


def missing_labels(project: Stage2Project) -> list[str]:
    """Asked-for cells that are still empty (주민 여부 is optional until 별지 제12·13호)."""
    return [
        item["label"] for item in fields()
        if item["id"] != "residents" and not current_value(project, item["key"])
    ]


def save_fields(project: Stage2Project, values: dict[str, str]) -> int:
    by_id = {item["id"]: item for item in fields()}
    saved = 0
    for field_id, value in values.items():
        item = by_id.get(field_id)
        text = "" if value is None else str(value).strip()
        if item and text:
            project.set_field(item["key"], item["label"], text, "USER_CONFIRMED",
                              note="CAP 작성대 별지 제3호에서 입력")
            saved += 1
    return saved
