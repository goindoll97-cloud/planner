from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation


TITLE_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FILL = PatternFill("solid", fgColor="5B9BD5")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
NOTE_FILL = PatternFill("solid", fgColor="F3F6F9")
WHITE_FONT = Font(color="FFFFFF", bold=True)


def _style_header(ws, cells: str) -> None:
    for row in ws[cells]:
        for cell in row:
            cell.fill = HEADER_FILL
            cell.font = WHITE_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _write_row(ws, row_index: int, values: list[str]) -> None:
    """Write a row safely with openpyxl.

    openpyxl does not support assigning a nested list directly to a multi-cell
    range such as ``ws["A3:E3"] = [[...]]``.  Each cell must be written
    individually (or via ``append``).  This helper keeps all template sheets
    consistent and avoids tuple-assignment errors.
    """
    for col_index, value in enumerate(values, start=1):
        ws.cell(row=row_index, column=col_index, value=value)


def build_minimal_input_workbook() -> bytes:
    """Return the company-facing minimal intake workbook as XLSX bytes."""
    wb = Workbook()
    ws = wb.active
    ws.title = "01_사업장기본정보"

    ws.merge_cells("A1:E1")
    ws["A1"] = "1. 사업장 기본정보 — 노란색 칸만 입력"
    ws["A1"].fill = TITLE_FILL
    ws["A1"].font = WHITE_FONT
    _write_row(ws, 3, ["항목", "입력값", "필수", "프로그램 활용", "설명"])
    _style_header(ws, "A3:E3")

    rows = [
        ["사업장명", "", "Y", "공통", "사업자등록 기준 사업장명"],
        ["사업장 주소", "", "Y", "화사계", "유해화학물질을 취급하는 실제 사업장 주소"],
        ["업종 또는 주요 생산품", "", "Y", "PSM", "예: 합성수지 제조, 도료 제조"],
        ["한국표준산업분류(KSIC) 코드", "", "N", "PSM", "알면 입력, 모르면 비워도 됨"],
        ["기존 PSM 보유 여부", "모름", "Y", "공통", "Y / N / 모름"],
        ["기존 장외영향평가서 보유 여부", "모름", "Y", "화사계", "Y / N / 모름"],
        ["기존 화학사고예방관리계획서 보유 여부", "모름", "Y", "화사계", "Y / N / 모름"],
        ["현재 목적", "신규 사전진단", "Y", "공통", "신규 사전진단 / 변경검토 / 재제출검토"],
    ]
    for r_idx, row in enumerate(rows, start=4):
        _write_row(ws, r_idx, row)
        ws.cell(r_idx, 2).fill = INPUT_FILL

    yn = DataValidation(type="list", formula1='"Y,N,모름"', allow_blank=True)
    ws.add_data_validation(yn)
    yn.add("B8:B10")
    purpose = DataValidation(type="list", formula1='"신규 사전진단,변경검토,재제출검토"')
    ws.add_data_validation(purpose)
    purpose.add("B11")

    ws.merge_cells("A13:E13")
    ws["A13"] = "※ 탱크 상세사양·방유제·감지기·공정도·비상조직 등은 대상 판정 후 필요한 경우에만 추가 질문합니다."
    ws["A13"].fill = NOTE_FILL
    ws["A13"].alignment = Alignment(wrap_text=True)
    widths = [32, 38, 10, 16, 56]
    for i, width in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = width
    ws.freeze_panes = "A4"

    ws2 = wb.create_sheet("02_화학물질목록")
    ws2.merge_cells("A1:K1")
    ws2["A1"] = "2. 화학물질 목록 — 회사가 작성하는 핵심 입력표"
    ws2["A1"].fill = TITLE_FILL
    ws2["A1"].font = WHITE_FONT
    headers = [
        "No.", "제품명", "CAS No.", "물질명(알면 입력)", "함량(%)", "취급형태",
        "최대 제조·사용량", "최대 저장량", "수량 단위", "최대 동시보유량(알면 입력)", "비고",
    ]
    _write_row(ws2, 3, headers)
    _style_header(ws2, "A3:K3")
    for r in range(4, 104):
        ws2.cell(r, 1, r - 3)
        for c in range(2, 12):
            ws2.cell(r, c).fill = INPUT_FILL
    dv_type = DataValidation(type="list", formula1='"제조,사용,저장,보관,제조+저장,사용+저장,기타,모름"')
    ws2.add_data_validation(dv_type)
    dv_type.add("F4:F103")
    dv_unit = DataValidation(type="list", formula1='"kg,ton,L,m3,기타"')
    ws2.add_data_validation(dv_unit)
    dv_unit.add("I4:I103")
    widths2 = [7, 24, 16, 24, 11, 15, 18, 16, 12, 22, 30]
    for i, width in enumerate(widths2, 1):
        ws2.column_dimensions[chr(64 + i)].width = width
    ws2.freeze_panes = "D4"

    ws3 = wb.create_sheet("03_기존문서보유여부")
    ws3.merge_cells("A1:E1")
    ws3["A1"] = "3. 기존 작성자료 보유 여부"
    ws3["A1"].fill = TITLE_FILL
    ws3["A1"].font = WHITE_FONT
    headers3 = ["자료", "보유 여부", "프로그램 활용 시점", "왜 확인하는가", "비고"]
    _write_row(ws3, 3, headers3)
    _style_header(ws3, "A3:E3")
    docs = [
        ["공정안전보고서(PSM)", "모름", "1차 판정 후", "기존 공정안전자료 재활용 가능성 확인", ""],
        ["장외영향평가서", "모름", "화사계 대상 판정 후", "기존 시설·사고영향 자료 재활용 가능성 확인", ""],
        ["기존 화학사고예방관리계획서", "모름", "변경/재제출 판정 시", "기존 승인 내용과 변경사항 비교", ""],
        ["위해관리계획서", "모름", "화사계 대상 판정 후", "기존 비상대응 정보 재활용 가능성 확인", ""],
    ]
    for r_idx, row in enumerate(docs, 4):
        _write_row(ws3, r_idx, row)
        ws3.cell(r_idx, 2).fill = INPUT_FILL
    yn2 = DataValidation(type="list", formula1='"Y,N,모름"')
    ws3.add_data_validation(yn2)
    yn2.add("B4:B7")
    widths3 = [34, 16, 26, 52, 24]
    for i, width in enumerate(widths3, 1):
        ws3.column_dimensions[chr(64 + i)].width = width

    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()
