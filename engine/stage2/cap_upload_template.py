"""엑셀 업로드 양식: 아직 파일에서 찾지 못한 사실을 열 이름으로 넣은 엑셀을 만들어 줍니다.

사람은 이 양식을 채워 ‘자료 올리기’에 그대로 올립니다. 열 이름은 파일 읽기 코드가 알아보는 표기
(사실 카탈로그 headers의 첫 번째)만 쓰므로, 채운 값은 다른 회사 파일과 똑같이 읽히고 충돌도 같은 방식으로 검사됩니다.

시트
- 사업장 정보: ‘항목 | 값’ 두 열(사업장에 하나뿐인 사실·서술형)
- 설비 / 물질 / 가스감지기: 한 줄에 대상 하나. 이미 알고 있는 대상은 번호·이름을 미리 적어 둡니다.
- 공정안전보고서 표(동력기계 목록·배관 및 개스킷 명세 등): 서식 표 하나가 시트 하나. 한 줄에 하나씩 적습니다.
- 안내: 열마다 단위·선택지·쓰이는 별지(값으로 읽히지 않도록 한 칸짜리 문장으로만 적음)
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

from . import cap_fact_catalog as catalog
from . import cap_fact_status as status
from . import evidence_workspace as ew
from .project import Stage2Project

SITE_SHEET = "사업장 정보"
ENTITY_SHEETS = {"facility": "설비", "material": "물질", "detector": "가스감지기"}
GUIDE_SHEET = "안내"
EXTRA_ROWS = {"facility": 5, "material": 5, "detector": 10}     # 새 대상을 적을 빈 줄
ID_HEADER = {"facility": "설비번호", "material": "제품코드", "detector": "감지기 번호"}
NAME_FIELD = {"facility": "name", "material": "name"}
FILENAME = "화학사고예방관리계획서_업로드양식.xlsx"
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
    for item in catalog.facts(company=True):
        if item.identifier or not item.readable or item.field_key.startswith("@"):
            continue
        row = by_id.get(item.id)
        if row is None:
            continue
        partial = row["_kind"] in status.ENTITY_NOUN and row["_state"] == status.O and "중" in str(row["값"])
        if not only_blank or row["_state"] == status.BLANK or partial:
            out.append(item)
    return out


def columns(project: Stage2Project, *, only_blank: bool = True, group: str = "") -> dict[str, Any]:
    """시트별로 넣을 사실. {‘site’: [...], ‘facility’: [...], ..., ‘tables’: {서식 번호: [그 표의 모든 열]}}.
    공정안전보고서 표는 빈칸이 하나라도 있으면(줄이 없는 표 포함) 그 표의 열을 모두 넣습니다."""
    rows = status.fact_rows(project, group=group)
    out: dict[str, Any] = {"site": [], "facility": [], "material": [], "detector": [], "tables": {}}
    for item in _wanted(rows, only_blank):
        key = "site" if item.kind in catalog.SITE_KINDS else item.kind
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


def build(project: Stage2Project, *, only_blank: bool = True, group: str = "") -> bytes:
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    wanted = columns(project, only_blank=only_blank, group=group)
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
        known = status.entities(project, kind)
        name_item = next((i for i in catalog.facts(kinds=[kind]) if i.evidence_field == NAME_FIELD.get(kind)), None)
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

    guide = book.create_sheet(GUIDE_SHEET)
    lines = [
        filename(project).replace("_", " ").removesuffix(".xlsx"),
        "빈칸을 채워 ‘자료 올리기’에 이 파일을 그대로 올리세요. 열 이름과 시트 이름은 바꾸지 마세요.",
        "이미 올린 파일에서 찾은 값은 넣지 않았어요. 값이 서로 다르게 적힌 항목(충돌)은 원래 파일을 고쳐 다시 올려 주세요.",
        "모르는 칸은 비워 두세요. 해당하지 않으면 ‘해당 없음’, 자료에 없으면 ‘자료 없음’이라고 적으세요.",
        "설비·물질·감지기 시트는 한 줄에 하나씩 적습니다. 번호(설비번호·제품코드·감지기 번호)가 없는 줄은 읽지 않아요.",
        "공정안전보고서 표 시트도 한 줄에 하나씩 적습니다. 구별 열(기계번호·분류코드 등)이 빈 줄은 읽지 않아요.",
        "",
        "열 설명",
    ]
    for key, title in (("site", SITE_SHEET), *ENTITY_SHEETS.items()):
        for item in wanted[key]:
            lines.append(f"· [{title}] {item.template_header} — {_help(item)}")
    for table, items in wanted["tables"].items():
        for item in items:
            lines.append(f"· [{sheet_title(table)}] {item.template_header} — {_help(item)}")
    for line in lines:
        guide.append([line])
    guide["A1"].font = Font(bold=True, size=13)
    guide.column_dimensions["A"].width = 120
    if book.sheetnames and book.sheetnames[0] == GUIDE_SHEET and len(book.sheetnames) > 1:
        book.move_sheet(GUIDE_SHEET, offset=len(book.sheetnames) - 1)
    out = BytesIO()
    book.save(out)
    return out.getvalue()
