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


# Other keys under which earlier intake stores the same fact.
ALT_KEYS = {
    "registration_no": ("business.registration_no",),
    "representative": ("business.representative",),
    "contact": ("business.phone",),
    "writer_name": ("cap.business.writer_info",),
}
_YES = {"y", "yes", "예", "있음", "해당"}
_NO = {"n", "no", "아니오", "없음", "미해당"}


def _normalized_choice(field_id: str, raw: str) -> str:
    """Map intake answers such as Y/N onto this form's printed options."""
    text = raw.strip()
    key = text.lower()
    if field_id == "joint":
        if "공동" in text or key in _YES:
            return "공동제출"
        if "단독" in text or key in _NO:
            return "단독제출"
    elif field_id == "other_review":
        if key in _NO:
            return "미해당"
        for option in ("공정안전보고서", "안전성향상계획"):
            if option in text:
                return f"해당({option})"
    elif field_id in ("recent_accident", "residents"):
        if key in _YES:
            return "있음"
        if key in _NO:
            return "없음"
    return ""


def suggestion(project: Stage2Project, item: dict[str, Any]) -> tuple[str, str]:
    """(value, where it came from) for a cell the user has not confirmed yet."""
    field_id = item["id"]
    own = current_value(project, item["key"])
    if item["kind"] == "choice":
        if own in item["options"]:
            return "", ""
        value = _normalized_choice(field_id, own)
        if value:
            return value, "회사 자료 입력값"
        if field_id == "other_review" and project.psm_required is False:
            return "미해당", "판정진단: 공정안전보고서 대상이 아님"
        return "", ""
    if own:
        return "", ""
    for key in ALT_KEYS.get(field_id, ()):
        value = current_value(project, key)
        if value:
            return value, "회사 자료 입력값"
    return "", ""


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
