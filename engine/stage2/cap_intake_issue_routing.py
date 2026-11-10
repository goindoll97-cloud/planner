"""Route CAP document checks by the workflow step that can resolve them.

A report-export validation issue is not necessarily an invalid cell in the
company workbook. We must not ask a novice to type a legal designation number
or an impact/GIS result into the initial fact-only input sheet. The final
report validation continues to enforce those requirements independently.
"""
from __future__ import annotations

from typing import Any

EXCEL = "excel"
LEGAL = "legal"
MAP = "map"
INFORMATION = "information"


def route_issue(issue: Any) -> str:
    """Classify a document-check result without altering its status or data."""
    status = str(getattr(issue, "status", "") or "")
    message = str(getattr(issue, "message", "") or "")
    label = str(getattr(issue, "legal_item", "") or "")
    keys = tuple(str(v) for v in (getattr(issue, "field_keys", ()) or ()))
    content = label + " " + message

    if status == "PASS" or "최초 신규제출로 확인되어 변경내역 관리대장을 필수" in content:
        return INFORMATION

    # This is an actual company product fact, required for certain Annex-3
    # quantity conditions. Retain it in the input corrections when absent.
    if "상온·상압 액체 여부" in content and ("필요" in content or "확인" in content):
        return EXCEL

    if any(key.startswith(("cap.offsite.", "cap.site.surrounding_environment",
                           "cap.workspace.form8_review")) for key in keys):
        return MAP

    if any(word in content for word in (
        "KORA/GIS", "GIS/KORA", "사고시나리오별 영향평가",
        "사고영향범위", "총괄영향범위", "총괄영향 범위",
        "주변 보호대상", "보호대상 확인", "장외 영향거리",
    )):
        return MAP

    # A verified legal master DB is required; these are not company facts.
    # Keep validation enabled at final-report generation.
    if any(word in content for word in (
        "고유번호", "유해화학물질 물질구분", "물질구분을 확정",
        "규정수량", "별표 1", "별표 2", "별표 3",
        "Stage 1 판정",
    )):
        return LEGAL

    return EXCEL


def count_routes(issues: Any) -> dict[str, int]:
    count = {EXCEL: 0, LEGAL: 0, MAP: 0, INFORMATION: 0}
    for issue in issues:
        count[route_issue(issue)] += 1
    return count
