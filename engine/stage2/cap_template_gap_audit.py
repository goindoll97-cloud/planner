"""Read-only CAP audit: required facts, workbook columns, GIS and output-form coverage.

This is a mapping/availability check, not a claim that every physical blank
cell in the authoritative statutory form has been filled. The actual exported
DOCX and HWP still need a final human comparison against the approved form.
"""
from __future__ import annotations

import csv
from io import StringIO

from . import cap_fact_catalog as catalog
from . import cap_fact_status as status
from . import cap_upload_template as template
from .cap_fact_drafting import generated_fact_ids
from .cap_form_coverage import audit_cap_form_coverage
from .cap_baseline_docx import FORM_TABLE_INDEX


COLUMNS = (
    "구분", "서식", "항목", "필수", "입력·생성 경로",
    "회사 엑셀 위치", "자료 상태", "확인·수정 사항",
)


def rows(project) -> list[dict[str, str]]:
    company = template.company_columns()
    workbook_ids = {item.id for key, items in company.items() if key != "tables" for item in items}
    workbook_ids.update(item.id for items in company["tables"].values() for item in items)
    by_id = {row["_id"]: row for row in status.fact_rows(project, docs=("CAP",))}
    generated = generated_fact_ids()
    out: list[dict[str, str]] = []

    for item in catalog.facts(docs=("CAP",)):
        if item.source == "company" and item.id in generated:
            channel = "프로그램 서술형 초안(회사 근거 확인 필요)"
        elif item.source == "company":
            channel = "회사 작성용 엑셀"
        elif item.source == "project":
            channel = "사업장 등록정보"
        elif item.source == "survey":
            channel = "지도·현장 조사"
        elif item.source == "legal":
            channel = "승인 법령 DB"
        else:
            channel = "자동 계산 엔진"

        excel = ""
        mapping_problem = ""
        if item.id in workbook_ids:
            if item.kind in catalog.SITE_KINDS:
                sheet = template.SITE_SHEET
            elif item.kind == "psm_table":
                sheet = template.sheet_title(item.table)
            elif item.kind == "facility" and item.file == template.SCENARIO_FILE:
                sheet = template.ENTITY_SHEETS["scenario"]
            else:
                sheet = template.ENTITY_SHEETS.get(item.kind, "")
            excel = f"{sheet} · {item.template_header}" if sheet else item.template_header
            if item.kind == "target":
                excel += " (지도 보완본에 포함)"
        elif item.identifier and item.kind in template.ENTITY_SHEETS:
            excel = f"{template.ENTITY_SHEETS[item.kind]} · 식별번호"
        elif item.source == "company" and item.id not in generated:
            mapping_problem = "회사 작성용 엑셀에 대응 열이 없습니다. 사실 카탈로그·양식 매핑을 검토해 주세요."
        elif item.source == "survey":
            excel = "지도 결과·현장 조사에서 생성(기본 회사 엑셀에는 없을 수 있음)"

        state = by_id.get(item.id) or {}
        action = str(state.get("고칠 점") or item.note or "")
        if mapping_problem:
            action = f"{mapping_problem} {action}".strip()
        out.append(dict(zip(COLUMNS, (
            "입력·자동작성 항목",
            item.used_in_text, item.name,
            "필수" if item.required else "해당 시",
            channel, excel, str(state.get("상태") or "별도 확인"),
            action,
        ))))

    for block in audit_cap_form_coverage(project):
        out.append(dict(zip(COLUMNS, (
            "서식별 실제 작성 가능성",
            f"별지 제{block.form_no}호",
            block.item, "필수",
            block.source_kind, "",
            block.state_label,
            block.required_input + (" · " + block.note if block.note else ""),
        ))))

    # The supplied layout baseline does not have a separate Form 14 table.
    # Its initiation-event frequency table is currently inside Form 13.
    if "14" not in FORM_TABLE_INDEX:
        out.append(dict(zip(COLUMNS, (
            "출력서식 구조 점검", "별지 제14호",
            "독립 법정서식 표의 존재·배치", "필수",
            "DOCX 원본서식", "", "출력서식 확인 필요",
            "현재 빈도 계산값은 제13호 영역의 빈도표에 기입합니다. 별지 제14호의 독립 표제·배치는 승인된 원본과 대조해야 합니다.",
        ))))
    return out


def mapping_gaps(project) -> list[dict[str, str]]:
    return [r for r in rows(project) if "대응 열이 없습니다" in r["확인·수정 사항"]]


def csv_bytes(project) -> bytes:
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows(project))
    return ("\ufeff" + output.getvalue()).encode("utf-8")
