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
import re
from typing import Any

from . import cap_fact_catalog as catalog
from . import cap_fact_status as status
from . import evidence_workspace as ew
from .project import Stage2Project

SITE_SHEET = "사업장 정보"
ENTITY_SHEETS = {"facility": "설비", "material": "물질", "detector": "가스감지기", "scenario": "사고시나리오 검토", "target": "주변 보호대상"}
SCENARIO_FILE = "scenario_review"        # 설비별 사고시나리오 입력은 설비 시트와 따로 둡니다(열이 많음)
GUIDE_SHEET = "안내"
HELP_SHEET = "항목별 작성안내"
EXAMPLE_HEADER = "작성 예시 (회사 값 아님)"
GUIDANCE_HEADER = "작성 안내·법령 참고 (입력하지 마세요)"


def display_header(text: str) -> str:
    return re.sub(r"(?<!M)SDS", "MSDS", str(text))
EXTRA_ROWS = {"facility": 5, "material": 5, "detector": 10, "scenario": 5, "target": 10}     # 새 대상을 적을 빈 줄
ID_HEADER = {"facility": "설비번호", "material": "제품코드", "detector": "감지기 번호", "scenario": "설비번호", "target": "보호대상 명칭"}
NAME_FIELD = {"facility": "name", "material": "name"}
FILENAME = "화학사고예방관리계획서_빈칸전용양식.xlsx"
PSM_FILENAME = "공정안전보고서_업로드양식.xlsx"
BOTH_FILENAME = "사업장자료_업로드양식.xlsx"
TABLE_EXTRA_ROWS = 10
COMPANY_FILENAME = "화사계_회사작성용_전체항목.xlsx"
CAP_TABLE_TITLES = {"cap-relief": "안전밸브", "cap-waste": "처리시설", "cap-change": "변경내역", "cap-components": "혼합제품 구성성분",
                    # 별지 제16호 5~10번 표(1군). 서식 표와 같은 열로 한 줄에 하나씩 받는다.
                    "cap-16-5": "별지16-5 유관기관", "cap-16-6-1": "별지16-6-1 사전정보공유",
                    "cap-16-6-2": "별지16-6-2 지역사회소통", "cap-16-7-1": "별지16-7-1 대피경보",
                    "cap-16-7-2": "별지16-7-2 지자체경보전달", "cap-16-8": "별지16-8 응급의료",
                    "cap-16-9": "별지16-9 대피장소", "cap-16-10": "별지16-10 지역사회고지"}

# Choices in the catalog are closed, legally/formally constrained values.
# The following are shortcuts for *observed company facts* (drawings/MSDS);
# they are helpful suggestions, not a purported exhaustive legal list.
FACT_DROPDOWNS: dict[str, tuple[str, ...]] = {
    "material.toxicity_route": ("흡입", "경구", "경피", "해당 없음", "자료 없음"),
    "material.toxicity_category": ("구분 1", "구분 2", "구분 3", "구분 4", "구분 5", "해당 없음", "자료 없음"),
    "material.corrosive": ("유", "무", "해당 없음", "자료 없음"),
    "detector.interlock": ("예", "아니오"),
    "detector.install_type": ("고정식", "휴대식", "고정식·휴대식"),
    "facility.dike_type": ("방류벽", "방지턱", "트렌치", "이중벽용기", "이중배관", "기타"),
    "cap-relief.9": ("기체", "액체", "2상", "증기"),
    "psm.t16.후열처리여부": ("예", "아니오"),
    "psm.t17.배출상태": ("기체", "액체", "2상", "증기"),
    "psm.t19.실내외 구분": ("실내", "실외"),
    "psm.temergency-resources.구분": ("장비", "인력"),
    "facility.psm15_후열처리 여부": ("예", "아니오"),
}

# These choices match defined checkbox/dropdown fields on the CAP statutory
# general-information form; they are *not* computed legal outcomes.
STATUTORY_CHOICE_IDS = {
    "site.submission_type", "site.joint_emergency_plan",
    "site.other_system_review", "site.residents_in_overall_range",
    "site.recent_accident",
}


def option_values(item: catalog.Fact) -> tuple[str, ...]:
    """Return the closed catalog options, else optional factual entry suggestions."""
    return item.options or FACT_DROPDOWNS.get(item.id, ())


def add_choice_validation(sheet, item: catalog.Fact, address: str) -> bool:
    """Excel dropdown: reject non-catalog values; allow other genuine MSDS/drawing facts."""
    from openpyxl.worksheet.datavalidation import DataValidation

    options = option_values(item)
    if not options:
        return False
    joined = ",".join(options)
    if len(joined) > 250:  # Excel inline list constraint; do not emit broken validation.
        return False
    closed = item.format == "choice"
    prompt = ("목록의 항목을 선택하세요. 해당 사실을 모르면 비워 두세요." if closed else
              "목록에서 고르세요. 실제 MSDS·도면 값이 다르면 직접 입력할 수 있습니다.")
    validation = DataValidation(
        type="list", formula1=f'"{joined}"', allow_blank=True,
        showDropDown=False, showInputMessage=True, promptTitle="회사 사실 선택",
        prompt=prompt, showErrorMessage=closed, errorStyle="stop",
        errorTitle="허용된 선택값이 아닙니다",
        error="법정서식 또는 입력 규격의 선택값 중에서 고르세요.")
    sheet.add_data_validation(validation)
    validation.add(address)
    return True


def apply_training_dropdowns(book) -> None:
    """Add the catalog dropdowns to a training workbook without constraining its example rows.

    Older layout: row 2 instruction, row 3 example, input from row 4 (last header '행 안내').
    Minimal-input layout: row 2 example, input from row 3 (guide cell in row 2 starts with '◀ 2행은 작성 예시').
    Other list dropdowns the file already has (e.g. 별지16 '구분') are kept.
    """
    from openpyxl.utils import range_boundaries
    wanted = company_columns()
    sheet_items: dict[str, list[catalog.Fact]] = {
        SITE_SHEET: wanted["site"],
        **{name: wanted[kind] for kind, name in ENTITY_SHEETS.items()},
        **{sheet_title(table): items for table, items in wanted["tables"].items()},
    }
    for sheet in book.worksheets:
        items = sheet_items.get(sheet.title)
        if not items:
            continue
        by_header = {display_header(item.template_header): item for item in items}
        site = sheet.title == SITE_SHEET
        if site:   # 사업장 정보는 행마다 항목이 다르다: 카탈로그 선택지가 있는 행만 바꾼다.
            targets = {row for row in range(2, sheet.max_row + 1)
                       if (item := by_header.get(str(sheet.cell(row, 1).value or ""))) and option_values(item)}
        else:
            targets = {cell.column for cell in sheet[1]
                       if (item := by_header.get(str(cell.value or ""))) and option_values(item)}

        def covers(dv) -> bool:
            return any(range_boundaries(str(r))[1 if site else 0] in targets for r in dv.sqref.ranges)

        # Replace older list validations on catalog columns so that Excel has one policy per cell.
        sheet.data_validations.dataValidation = [
            dv for dv in sheet.data_validations.dataValidation if dv.type != "list" or not covers(dv)
        ]
        if sheet.title == SITE_SHEET:
            for row in range(2, sheet.max_row + 1):
                item = by_header.get(str(sheet.cell(row, 1).value or ""))
                if item:
                    add_choice_validation(sheet, item, f"B{row}")
        else:
            guide = str(sheet.cell(2, sheet.max_column).value or "")
            start = (4 if any(cell.value == "행 안내" for cell in sheet[1])
                     else 3 if guide.startswith("◀ 2행은 작성 예시") else 2)
            last = max(sheet.max_row + 20, start + 50, 200)
            for cell in sheet[1]:
                item = by_header.get(str(cell.value or ""))
                if item:
                    letter = cell.column_letter
                    add_choice_validation(sheet, item, f"{letter}{start}:{letter}{last}")



def filename(project: Stage2Project) -> str:
    docs = status.project_docs(project)
    return BOTH_FILENAME if len(docs) > 1 else (PSM_FILENAME if docs == ("PSM",) else FILENAME)


def sheet_title(table: str) -> str:
    """공정안전보고서 표의 시트 이름(엑셀 규칙: 31자, / 같은 글자 없음). 읽을 때는 시트 이름이 아니라 머리글로 알아봅니다."""
    from . import psm_table_workspace as pt
    title = CAP_TABLE_TITLES.get(table) or (pt.SPECS[table].title if table in pt.SPECS else table)
    for bad in "/\\?*[]:":
        title = title.replace(bad, "·")
    return title[:31]


def _help(item: catalog.Fact) -> str:
    parts = []
    if item.unit:
        parts.append(f"단위 {item.unit}")
    options = option_values(item)
    if options:
        kind = "고정 선택지" if item.format == "choice" else "회사 사실 선택 예시(목록 외 실제 값도 가능)"
        parts.append(kind + ": " + " / ".join(options))
    if item.condition:
        parts.append("해당 시: " + item.condition)
    if item.note:
        parts.append(item.note)
    parts.append("쓰이는 곳: " + item.used_in_text)
    return " · ".join(parts)



LEGAL_CAP = "https://www.law.go.kr/admRulInfoP.do?admRulSeq=2100000279958"
LEGAL_CAP_WRITING = "https://law.go.kr/admRulLsInfoP.do?admRulSeq=2100000285508"
LEGAL_MSDS = "https://www.moel.go.kr/news/enews/report/enewsView.do?news_seq=18712"
LEGAL_PSM = "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000259798"


def _legal_reference(item: catalog.Fact) -> str:
    if item.id in STATUTORY_CHOICE_IDS:
        return LEGAL_CAP_WRITING
    if "SDS" in item.template_header or item.kind == "material":
        return LEGAL_MSDS
    if item.id.startswith(("narrative.change_management.", "narrative.community.",
                           "narrative.public_notice.", "site.company_notice_", "site.survey_")):
        return LEGAL_CAP
    if "사고조사" in item.name:
        return LEGAL_PSM
    return ""


def _guidance(item: catalog.Fact) -> str:
    if item.id in STATUTORY_CHOICE_IDS:
        return ("작성 규정의 사업장 일반정보 서식에 해당하는 선택형 항목입니다. "
                "실제 회사 사실을 확인하여 목록에서 고르세요. " + _help(item))
    if item.id.startswith("narrative.change_management."):
        return ("변경일·변경 전후·검토·승인·교육·조치기록을 실제 대장과 대조하세요. "
                "변경관리대장 5년 보존은 모든 사업장의 법정 보존기간으로 확인되지 않습니다. "
                "화학사고예방관리계획서 이행 등에 관한 규정 제4조제2항의 주요취급시설 "
                "변경내역 관리대장 연간 제출과 구분하세요.")
    if item.id.startswith("narrative.investigation."):
        return ("사고조사 책임자·시점·원인·재발방지 조치와 실제 보존기준을 확인하세요. "
                "가상의 7일 기한을 일반적인 법정 기한으로 간주하지 마세요.")
    if "SDS" in item.template_header or item.kind == "material":
        return ("최신 물질안전보건자료(MSDS)와 값·단위·작성/개정일을 대조하고 "
                "해당 시 제출번호도 확인하세요. " + _help(item))
    if item.id.startswith(("narrative.community.", "narrative.public_notice.", "site.company_notice_")):
        return ("회사 자체 소통 일정과 법정 지역사회 고지는 구분해야 합니다. "
                "승인 계획과 현행 이행 규정의 대상·고지 주기를 확인하세요. " + _help(item))
    if item.id.startswith("site.survey_"):
        return ("지도 검색후보만으로 법정 전수조사를 완료 처리하지 마세요. "
                "실제 사업장 경계·거리·분류를 현장과 대조하세요. " + _help(item))
    return _help(item)


def _sample_example(item: catalog.Fact) -> str:
    """Use realistic synthetic company text, never generic 'ask someone' instructions."""
    from . import demo_company_workbook as demo
    if item.id in demo.SITE_VALUES:
        return display_header(str(demo.SITE_VALUES[item.id]))
    if item.file == SCENARIO_FILE:
        value = demo.SCENARIO_VALUES.get("TK-01", {}).get(item.template_header)
        if value is not None:
            return display_header(str(value))
    result = _example(item)
    if item.kind == "narrative" and any(phrase in result for phrase in
                                        ("확인해 입력", "미정이면 미확인", "확인 후 입력")):
        example = {
            "방법": "상황 발생 즉시 비상방송 후 대응반에 무전 전파(가상)",
            "절차": "변경요청서 접수, 위험성 검토, 공장장 승인, 작업자 교육(가상)",
            "주기": "분기 1회 실시하고 점검표에 기록(가상 사내 일정)",
            "대상": "제1공장 근로자 12명과 주변 주민대표(가상)",
            "담당": "가상 안전환경팀 이담당",
        }
        return example.get(item.column, f"안전환경팀이 {item.name}을 매월 점검하고 기록(가상)")
    return display_header(result)

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
    for table, items in catalog.input_tables().items():
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


def company_columns() -> dict[str, Any]:
    """1·2군 전체 입력 항목. 현재 값·판정·누락 여부에 따라 열을 생략하지 않는다."""
    from .cap_fact_drafting import generated_fact_ids
    generated = generated_fact_ids()
    out = {k: [] for k in ("site", *ENTITY_SHEETS)}
    out["tables"] = {}
    for item in catalog.facts(docs=("CAP",)):
        if item.source not in {"company", "project", "survey"} or item.id in generated:
            continue
        if not item.readable:
            continue
        if item.kind == "psm_table":
            out["tables"].setdefault(item.table, []).append(item)
        elif not item.identifier:
            key = "site" if item.kind in catalog.SITE_KINDS else item.kind
            if item.kind == "facility" and item.file == SCENARIO_FILE:
                key = "scenario"
            out[key].append(item)
    # 관련된 자료를 확인하는 항목을 모으고 각 묶음의 카탈로그 순서를 유지합니다.
    order = {"site_info": 0, "process_doc": 1, "containment": 2, "emergency_plan": 3, "survey": 4}
    def related(item):
        if item.id.startswith("site.company_"):
            if any(word in item.id for word in ("operating", "hazard")):
                return (1, "process")
            if "risk_measures" in item.id:
                return (5, "risk")
            return (3, {"response": "resources", "contact": "communication", "facility_first_aid": "shutdown"}.get(
                item.id.removeprefix("site.company_").split("_")[0], "zz"))
        return (order.get(item.file, 2), item.field_key)
    out["site"].sort(key=related)
    return out


# 지도로 확인하는 값. 회사가 엑셀에 적지 않습니다.
# ‘선정할 사고유형’·‘시나리오 선정 근거’는 프로그램 판단을 바꿀 때만 적는 열이라 양식에 둡니다(비우면 프로그램이 정함).
MAP_SCENARIO_IDS = {"facility.boundary_distance", "facility.origin"}


def build_company(*, include_scenario_sheets: bool = False, include_target_sheet: bool = False) -> bytes:
    """회사 배포용 양식. 시나리오 시트에는 회사가 아는 물성·개시사건 개수·완화장치만 두고,
    지도로 얻는 경계 거리·사고원점·주변 보호대상은 ③에서 조사하므로 넣지 않습니다.
    include_scenario_sheets=True는 지도 항목까지 있는 이전 양식(업로드 호환용)입니다."""
    project = Stage2Project(project_id="COMPANY-BLANK", company_name="", cap_required=True)
    return build(project, complete=True, with_map_inputs=include_scenario_sheets,
                 with_target_inputs=include_target_sheet)


def build(project: Stage2Project, *, only_blank: bool = True, group: str = "", docs=None, complete: bool = False,
          with_map_inputs: bool = True, with_target_inputs: bool = False) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wanted = company_columns() if complete else columns(project, only_blank=only_blank, group=group, docs=docs)
    if not with_map_inputs:
        wanted["scenario"] = [i for i in wanted.get("scenario", []) if i.id not in MAP_SCENARIO_IDS]
        if not with_target_inputs:
            wanted["target"] = []
    book = Workbook()
    book.remove(book.active)
    bold, head_fill = Font(bold=True), PatternFill("solid", fgColor="DDEBF7")
    names = {}
    for slot in ew.slots(project):
        if slot["field"] == "name" and slot["chosen"]:
            names[slot["entity"]] = str(slot["chosen"]["value"])

    def choices(sheet, item, column_letter, first_row, last_row):
        add_choice_validation(sheet, item, f"{column_letter}{first_row}:{column_letter}{last_row}")

    if wanted["site"]:
        sheet = book.create_sheet(SITE_SHEET)
        sheet.append(["항목", "값"])
        for cell in sheet[1]:
            cell.font, cell.fill = bold, head_fill
        for row, item in enumerate(wanted["site"], start=2):
            sheet.cell(row=row, column=1, value=display_header(item.template_header)).font = bold
            if item.kind == "narrative":
                sheet.cell(row=row, column=2).alignment = Alignment(wrap_text=True, vertical="top")
            choices(sheet, item, "B", row, row)
        sheet.column_dimensions["A"].width = 34
        sheet.column_dimensions["B"].width = 70

    for kind, title in ENTITY_SHEETS.items():
        items = wanted.get(kind, [])
        if not items:
            continue
        sheet = book.create_sheet(title)
        known = [] if complete else status.entities(project, "facility" if kind == "scenario" else kind)
        name_item = next((i for i in catalog.facts(kinds=["facility" if kind == "scenario" else kind])
                          if i.evidence_field == NAME_FIELD.get(kind)), None)
        header_items = ([name_item] if name_item else []) + [i for i in items if i is not name_item]   # 이름을 번호 바로 옆에
        sheet.append([ID_HEADER[kind]] + [display_header(i.template_header) for i in header_items])
        for column, cell in enumerate(sheet[1], start=1):
            cell.font, cell.fill = bold, head_fill
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
        sheet.append([display_header(i.template_header) for i in items])
        for column, cell in enumerate(sheet[1], start=1):
            cell.font, cell.fill = bold, head_fill
            sheet.column_dimensions[cell.column_letter].width = max(12, min(30, len(str(cell.value)) * 2 + 2))
        keys = [i for i in items if i.identifier]
        known = [] if complete else status.entities(project, "psm_table", table)
        for entity in known:
            values = entity.split("/", 1)[1].split(" · ")
            line = [""] * len(items)
            for item, value in zip(keys, values):
                line[items.index(item)] = value
            sheet.append(line)
        for column, item in enumerate(items, start=1):
            choices(sheet, item, sheet.cell(row=1, column=column).column_letter, 2, len(known) + 1 + TABLE_EXTRA_ROWS)
        sheet.freeze_panes = "A2"

    # Help is visible in the worksheet instead of hidden Excel comments.
    from openpyxl.utils import get_column_letter
    lookup = {}
    for sheet in book.worksheets:
        if sheet.title == SITE_SHEET:
            items = wanted["site"]
        else:
            items = next((wanted.get(k, []) for k, title in ENTITY_SHEETS.items()
                          if title == sheet.title), None)
            if items is None:
                items = next((v for t, v in wanted["tables"].items()
                              if sheet_title(t) == sheet.title), [])
        lookup[sheet.title] = [(display_header(i.template_header), i) for i in items]
        col = sheet.max_column + 1
        guide_col = col + 1
        sheet.cell(1, col, EXAMPLE_HEADER)
        sheet.cell(1, guide_col, GUIDANCE_HEADER)
        if sheet.title == SITE_SHEET:
            for row, item in enumerate(items, 2):
                sheet.cell(row, col, _sample_example(item))
                reference = _legal_reference(item)
                sheet.cell(row, guide_col, _guidance(item) + ("\\n법령·자료: " + reference if reference else ""))
        else:
            for row in range(2, max(sheet.max_row, 2) + 1):
                preview = " | ".join(
                    f"{display_header(i.template_header)}: {_sample_example(i)}" for i in items[:5])
                sheet.cell(row, col, preview + " | 나머지는 항목별 작성안내 참조")
                sheet.cell(row, guide_col, "모든 입력 열의 구체적 예시·단위·법령 참고는 '항목별 작성안내' 시트에 있습니다.")
        for index, fill in ((col, "FFF2CC"), (guide_col, "E7EFF8")):
            letter = get_column_letter(index)
            sheet.column_dimensions[letter].width = 65 if index == col else 75
            for cell in sheet[letter]:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                cell.fill = PatternFill("solid", fgColor=fill)

    help_sheet = book.create_sheet(HELP_SHEET)
    help_sheet.append(["시트", "항목", EXAMPLE_HEADER, "작성 안내·법령 기준", "공식 근거 URL"])
    for sheet_name, entries in lookup.items():
        for header, item in entries:
            help_sheet.append([sheet_name, header, _sample_example(item), _guidance(item), _legal_reference(item)])
    for cell in help_sheet[1]:
        cell.font, cell.fill = bold, head_fill
    for letter, width in (("A", 21), ("B", 36), ("C", 65), ("D", 85), ("E", 75)):
        help_sheet.column_dimensions[letter].width = width
    for row in help_sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        row[2].fill = PatternFill("solid", fgColor="FFF2CC")
        row[3].fill = PatternFill("solid", fgColor="E7EFF8")
        help_sheet.row_dimensions[row[0].row].height = 47
    help_sheet.freeze_panes = "C2"
    help_sheet.auto_filter.ref = help_sheet.dimensions
    if not lookup:
        book.create_sheet(SITE_SHEET).append(["항목", "값", EXAMPLE_HEADER, GUIDANCE_HEADER])
    if complete:
        for sheet in book:
            if sheet.title == HELP_SHEET:
                continue
            sheet.freeze_panes = "B2"
            sheet.sheet_view.zoomScale = 85
            sheet.auto_filter.ref = sheet.dimensions
            sheet.sheet_properties.pageSetUpPr.fitToPage = True
            sheet.page_setup.orientation = "landscape"
            sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
            sheet.page_setup.fitToWidth = 1
            sheet.page_setup.fitToHeight = 0
            sheet.print_title_rows = "1:1"
            sheet.print_options.horizontalCentered = True
            for row in sheet.iter_rows(min_row=2, max_row=max(sheet.max_row, 11)):
                for cell in row[:-2]:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
                    if sheet.title != SITE_SHEET or cell.column == 2:
                        cell.fill = PatternFill("solid", fgColor="E2F0D9")
                sheet.row_dimensions[row[0].row].height = 45 if sheet.title == SITE_SHEET else 36
            if sheet.title == SITE_SHEET:
                sheet.column_dimensions["B"].width = 45
                sheet.freeze_panes = "B2"
                from math import ceil
                for row in sheet.iter_rows(min_row=2):
                    text = str(row[2].value or "")
                    lines = ceil(sum(2 if ord(c) > 127 else 1 for c in text) / 60)
                    sheet.row_dimensions[row[0].row].height = max(45, min(300, lines * 15 + 8))
    out = BytesIO()
    book.save(out)
    return out.getvalue()


def _example(item: catalog.Fact) -> str:
    prefix = "1군만 · " if item.groups == ("1군",) else ""
    return prefix + _example_value(item)


def _example_value(item: catalog.Fact) -> str:
    """예시 값은 회사 사실로 취급하지 않습니다."""
    from .integrated_workbook import EXAMPLE_VALUES
    if item.field_key in EXAMPLE_VALUES and item.kind == "site":
        return str(EXAMPLE_VALUES[item.field_key])
    if item.id.startswith("site.company_"):
        return item.note
    if item.id in {"narrative.f16_contact", "narrative.f16_personnel", "narrative.f16_first_aid"}:
        return item.note
    if item.id == "narrative.community.주기":
        return "기존 운영 일정·주민 협의 결과를 담당자에게 확인. 예: 반기별 간담회(회사 검토용 예시, 법정 횟수 아님). 별도 지역사회 고지 의무와 구분하세요."
    if item.kind == "narrative" and item.column:
        if item.id.startswith("narrative.safety_management.") and item.column in {"방침", "기술기준", "실행"}:
            return item.note
        examples = {"책임자": "환경안전팀장 김○○", "담당": "환경안전팀 김○○", "대상": "해당 업무 담당자·대상 범위를 확인해 입력",
                    "주기": "실제 운영 일정과 해당 법적 기준을 담당자에게 확인 후 입력", "방법": "실제로 사용하는 방법·수단을 확인해 입력"}
        return examples.get(item.column, f"{item.name}을 담당자에게 확인해 간단히 입력. 미정이면 미확인")
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
