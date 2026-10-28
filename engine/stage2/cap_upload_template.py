"""엑셀 업로드 양식: 아직 파일에서 찾지 못한 사실을 열 이름으로 넣은 엑셀을 만들어 줍니다.

사람은 이 양식을 채워 ‘자료 올리기’에 그대로 올립니다. 열 이름은 파일 읽기 코드가 알아보는 표기
(사실 카탈로그 headers의 첫 번째)만 쓰므로, 채운 값은 다른 회사 파일과 똑같이 읽히고 충돌도 같은 방식으로 검사됩니다.

시트
- 사업장 정보: ‘항목 | 값’ 두 열(사업장에 하나뿐인 사실·서술형)
- 설비 / 물질 / 가스감지기: 한 줄에 대상 하나. 이미 알고 있는 대상은 번호·이름을 미리 적어 둡니다.
- 사고시나리오 검토: 설비 한 줄에 선정할 사고유형·경계까지 거리·물성·개시사건 개수(설비 시트와 같은 설비번호)
- 공정안전보고서 표(동력기계 목록·배관 및 개스킷 명세 등): 서식 표 하나가 시트 하나. 한 줄에 하나씩 적습니다.
- 각 시트의 예시 열: 입력할 값의 예를 표시하며 업로드 시 회사 사실에서 제외함
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

from . import cap_fact_catalog as catalog
from . import cap_fact_status as status
from . import evidence_workspace as ew
from .project import Stage2Project

SITE_SHEET = "사업장 정보"
ENTITY_SHEETS = {"facility": "설비", "material": "물질", "detector": "가스감지기", "scenario": "사고시나리오 검토"}
SCENARIO_FILE = "scenario_review"        # 설비별 사고시나리오 입력은 설비 시트와 따로 둡니다(열이 많음)
GUIDE_SHEET = "안내"
EXTRA_ROWS = {"facility": 5, "material": 5, "detector": 10, "scenario": 5}     # 새 대상을 적을 빈 줄
ID_HEADER = {"facility": "설비번호", "material": "제품코드", "detector": "감지기 번호", "scenario": "설비번호"}
NAME_FIELD = {"facility": "name", "material": "name"}
FILENAME = "화학사고예방관리계획서_빈칸전용양식.xlsx"
PSM_FILENAME = "공정안전보고서_업로드양식.xlsx"
BOTH_FILENAME = "사업장자료_업로드양식.xlsx"
TABLE_EXTRA_ROWS = 10


def filename(project: Stage2Project) -> str:
    docs = status.project_docs(project)
    return BOTH_FILENAME if len(docs) > 1 else (PSM_FILENAME if docs == ("PSM",) else FILENAME)


def sheet_title(table: str) -> str:
    """공정안전보고서 표의 시트 이름(엑셀 규칙: 31자, / 같은 글자 없음). 읽을 때는 시트 이름이 아니라 머리글로 알아봅니다."""
    from . import psm_table_workspace as pt
    title = pt.SPECS[table].title if table in pt.SPECS else table
    for bad in "/\\?*[]:":
        title = title.replace(bad, "·")
    return title[:31]


def _help(item: catalog.Fact) -> str:
    parts = []
    if item.unit:
        parts.append(f"단위 {item.unit}")
    if item.options:
        parts.append("선택: " + " / ".join(item.options))
    if item.condition:
        parts.append("해당 시: " + item.condition)
    if item.note:
        parts.append(item.note)
    parts.append("쓰이는 곳: " + item.used_in_text)
    return " · ".join(parts)


def _wanted(rows: list[dict[str, Any]], only_blank: bool) -> list[catalog.Fact]:
    """양식에 넣을 사실: 빈칸(일부 대상만 빈 것 포함)인 회사 사실. 충돌·확인은 원본 파일을 고쳐야 하므로 넣지 않습니다."""
    by_id = {r["_id"]: r for r in rows}
    out = []
    from .cap_fact_drafting import generated_fact_ids
    generated = generated_fact_ids()
    for item in catalog.facts(company=True):
        if item.id in generated:
            continue
        if item.identifier or not item.readable or item.field_key.startswith("@"):
            continue
        row = by_id.get(item.id)
        if row is None:
            continue
        partial = row["_kind"] in status.ENTITY_NOUN and row["_state"] == status.O and "중" in str(row["값"])
        if not only_blank or row["_state"] == status.BLANK or partial:
            out.append(item)
    return out


def columns(project: Stage2Project, *, only_blank: bool = True, group: str = "", docs=None) -> dict[str, Any]:
    """시트별로 넣을 사실. {‘site’: [...], ‘facility’: [...], ..., ‘tables’: {서식 번호: [그 표의 모든 열]}}.
    공정안전보고서 표는 빈칸이 하나라도 있으면(줄이 없는 표 포함) 그 표의 열을 모두 넣습니다."""
    rows = status.fact_rows(project, group=group, docs=docs)
    out: dict[str, Any] = {"site": [], "facility": [], "material": [], "detector": [], "scenario": [], "tables": {}}
    for item in _wanted(rows, only_blank):
        key = "site" if item.kind in catalog.SITE_KINDS else item.kind
        if item.kind == "facility" and item.file == SCENARIO_FILE:
            key = "scenario"
        if key in out and key != "psm_table":
            out[key].append(item)
    by_id = {r["_id"]: r for r in rows}
    for table, items in catalog.psm_tables().items():
        present = [by_id[i.id] for i in items if i.id in by_id]
        if not present:
            continue
        if status.O in {r["_state"] for r in present} and all(r["값"] == "해당 없음" for r in present if r["_state"] == status.O) \
                and len(present) == 1:
            continue                                    # 적용여부 ‘해당 없음’인 서식
        partial = any(r["_state"] == status.BLANK or (r["_state"] == status.O and "중" in str(r["값"])) for r in present)
        if not only_blank or partial:
            out["tables"][table] = list(items)
    return out


def blank_count(project: Stage2Project, group: str = "") -> int:
    wanted = columns(project, group=group)
    return sum(len(v) for k, v in wanted.items() if k != "tables") + sum(len(v) for v in wanted["tables"].values())


def build(project: Stage2Project, *, only_blank: bool = True, group: str = "", docs=None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    wanted = columns(project, only_blank=only_blank, group=group, docs=docs)
    book = Workbook()
    book.remove(book.active)
    bold, head_fill = Font(bold=True), PatternFill("solid", fgColor="DDEBF7")
    names = {}
    for slot in ew.slots(project):
        if slot["field"] == "name" and slot["chosen"]:
            names[slot["entity"]] = str(slot["chosen"]["value"])

    def choices(sheet, item, column_letter, first_row, last_row):
        if item.format != "choice" or not item.options:
            return
        listed = ",".join(item.options)
        if len(listed) > 250:
            return
        validation = DataValidation(type="list", formula1=f'"{listed}"', allow_blank=True, showErrorMessage=False)
        sheet.add_data_validation(validation)
        validation.add(f"{column_letter}{first_row}:{column_letter}{last_row}")

    if wanted["site"]:
        sheet = book.create_sheet(SITE_SHEET)
        sheet.append(["항목", "값"])
        for cell in sheet[1]:
            cell.font, cell.fill = bold, head_fill
        for row, item in enumerate(wanted["site"], start=2):
            sheet.cell(row=row, column=1, value=item.template_header).font = bold
            sheet.cell(row=row, column=1).comment = Comment(_help(item), "양식")
            if item.kind == "narrative":
                sheet.cell(row=row, column=2).alignment = Alignment(wrap_text=True, vertical="top")
            choices(sheet, item, "B", row, row)
        sheet.column_dimensions["A"].width = 34
        sheet.column_dimensions["B"].width = 70

    for kind, title in ENTITY_SHEETS.items():
        items = wanted[kind]
        if not items:
            continue
        sheet = book.create_sheet(title)
        known = status.entities(project, "facility" if kind == "scenario" else kind)
        name_item = next((i for i in catalog.facts(kinds=["facility" if kind == "scenario" else kind])
                          if i.evidence_field == NAME_FIELD.get(kind)), None)
        header_items = ([name_item] if name_item else []) + [i for i in items if i is not name_item]   # 이름을 번호 바로 옆에
        sheet.append([ID_HEADER[kind]] + [i.template_header for i in header_items])
        for column, cell in enumerate(sheet[1], start=1):
            cell.font, cell.fill = bold, head_fill
            if column > 1:
                cell.comment = Comment(_help(header_items[column - 2]), "양식")
            sheet.column_dimensions[cell.column_letter].width = max(12, min(30, len(str(cell.value)) * 2 + 2))
        for entity in known:
            line = [entity.split(":", 1)[1]] + [""] * len(header_items)
            if name_item is not None and name_item in header_items and entity in names:
                line[1 + header_items.index(name_item)] = names[entity]
            sheet.append(line)
        last = len(known) + 1 + EXTRA_ROWS[kind]
        for column, item in enumerate(header_items, start=2):
            choices(sheet, item, sheet.cell(row=1, column=column).column_letter, 2, last)
        sheet.freeze_panes = "B2"

    for table, items in wanted["tables"].items():
        sheet = book.create_sheet(sheet_title(table))
        sheet.append([i.template_header for i in items])
        for column, cell in enumerate(sheet[1], start=1):
            cell.font, cell.fill = bold, head_fill
            cell.comment = Comment(_help(items[column - 1]), "양식")
            sheet.column_dimensions[cell.column_letter].width = max(12, min(30, len(str(cell.value)) * 2 + 2))
        keys = [i for i in items if i.identifier]
        known = status.entities(project, "psm_table", table)
        for entity in known:
            values = entity.split("/", 1)[1].split(" · ")
            line = [""] * len(items)
            for item, value in zip(keys, values):
                line[items.index(item)] = value
            sheet.append(line)
        for column, item in enumerate(items, start=1):
            choices(sheet, item, sheet.cell(row=1, column=column).column_letter, 2, len(known) + 1 + TABLE_EXTRA_ROWS)
        sheet.freeze_panes = "A2"

    # 예시는 별도 열에만 두며 읽기 엔진에서 제외합니다.
    from openpyxl.utils import get_column_letter
    for sheet in book.worksheets:
        col = sheet.max_column + 1
        sheet.cell(1, col, "예시 (입력하지 마세요)")
        if sheet.title == SITE_SHEET:
            for row, item in enumerate(wanted["site"], 2):
                sheet.cell(row, col, _example(item))
        else:
            items = next((wanted[k] for k, title in ENTITY_SHEETS.items() if title == sheet.title), None)
            if items is None:
                items = next((v for t, v in wanted["tables"].items() if sheet_title(t) == sheet.title), [])
            text = " / ".join(f"{i.template_header}: {_example(i)}" for i in items)
            # 번호가 없는 예시 전용 줄은 만들지 않습니다.
            for row in range(2, max(sheet.max_row, 2) + 1):
                sheet.cell(row, col, text)
        sheet.column_dimensions[get_column_letter(col)].width = 65
        for cell in sheet[get_column_letter(col)]:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.fill = PatternFill("solid", fgColor="FFF2CC")
    if not book.worksheets:
        book.create_sheet(SITE_SHEET).append(["항목", "값", "예시 (입력하지 마세요)"])
    out = BytesIO()
    book.save(out)
    return out.getvalue()


def _example(item: catalog.Fact) -> str:
    """예시 값은 회사 사실로 취급하지 않습니다."""
    if item.options:
        return item.options[0]
    if item.evidence_field == "cas":
        return "108-88-3"
    if item.format == "number":
        return "10" + (" " + item.unit if item.unit else "")
    examples = {"대표자": "홍길동", "공정개요": "원료 입고 → 저장 → 혼합 → 출하",
                "설비명": "원료 저장탱크", "물질명": "톨루엔"}
    if item.kind == "narrative":
        return "안전관리책임자가 매월 비상장비를 점검하고 결과를 기록한다. (실제 담당자·주기에 맞게 작성)"
    return examples.get(item.name, f"사업장의 실제 {item.name} 기재")
