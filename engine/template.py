from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation


TITLE_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FILL = PatternFill("solid", fgColor="5B9BD5")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
NOTE_FILL = PatternFill("solid", fgColor="F3F6F9")
EXAMPLE_FILL = PatternFill("solid", fgColor="E2F0D9")
SECTION_FILL = PatternFill("solid", fgColor="D9EAF7")
WHITE_FONT = Font(color="FFFFFF", bold=True)


def _style_header(ws, cells: str) -> None:
    for row in ws[cells]:
        for cell in row:
            cell.fill = HEADER_FILL
            cell.font = WHITE_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _write_row(ws, row_index: int, values: list[object]) -> None:
    for col_index, value in enumerate(values, start=1):
        ws.cell(row=row_index, column=col_index, value=value)


def _build_guide_sheet(wb: Workbook) -> None:
    ws = wb.active
    ws.title = "00_작성가이드"

    ws.merge_cells("A1:H1")
    ws["A1"] = "화사계·PSM 회사 입력서 작성가이드"
    ws["A1"].fill = TITLE_FILL
    ws["A1"].font = Font(color="FFFFFF", bold=True, size=14)
    ws["A1"].alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A3:H3")
    ws["A3"] = "처음 작성할 때 이것만 기억하세요"
    ws["A3"].fill = SECTION_FILL
    ws["A3"].font = Font(bold=True)

    guide_rows = [
        ["1", "CAS No.", "SDS 제3항의 CAS 번호를 그대로 입력", "혼합제품은 규제성분별 CAS를 각각 한 줄씩 입력"],
        ["2", "함량(%)", "해당 CAS 성분의 제품 내 함량", "범위만 있으면 대표값을 임의로 추정하지 말고 확인 후 입력"],
        ["3", "최대 제조·사용량", "하루 중 가장 많이 제조·사용·취급하는 양", "PSM은 일일 최대량 기준이 중요"],
        ["4", "최대 저장량", "사업장에 저장되는 최대량", "탱크·창고 등 실제 최대 저장량 기준"],
        ["5", "수량 단위", "가능하면 kg 또는 ton 사용", "L 또는 m3이면 질량 환산을 위해 밀도정보가 추가로 필요할 수 있음"],
        ["6", "모르는 값", "추측하지 말고 빈칸 또는 '모름'으로 남김", "프로그램이 필요한 항목만 추가 질문"],
    ]
    for r_idx, row in enumerate(guide_rows, start=5):
        _write_row(ws, r_idx, row)
        ws.cell(r_idx, 1).fill = SECTION_FILL
        ws.cell(r_idx, 1).font = Font(bold=True)
        ws.cell(r_idx, 2).font = Font(bold=True)
        for c in range(1, 5):
            ws.cell(r_idx, c).alignment = Alignment(vertical="top", wrap_text=True)

    ws.merge_cells("A12:H12")
    ws["A12"] = "화학물질 입력 예시 — 실제 입력 시 아래 값을 복사하지 말고 귀사 자료로 바꾸세요"
    ws["A12"].fill = SECTION_FILL
    ws["A12"].font = Font(bold=True)

    headers = ["상황", "제품명", "CAS No.", "물질명", "함량(%)", "최대량 예시", "단위", "작성 포인트"]
    _write_row(ws, 13, headers)
    _style_header(ws, "A13:H13")

    examples = [
        ["순물질", "포스겐", "75-44-5", "포스겐", 100, "사용 300 / 저장 0", "kg", "한 성분의 순물질이면 한 줄로 입력"],
        ["희석용액", "염산 30%", "7647-01-0", "염산", 30, "사용 500 / 저장 2,000", "kg", "제품 전체가 아니라 해당 CAS 성분 함량을 입력"],
        ["혼합제품-성분1", "세정제 A", "67-56-1", "메틸알코올", 20, "사용 1,000 / 저장 500", "kg", "한 제품에 규제성분이 2개면 같은 제품명을 두 줄로 반복하고 성분별 CAS·함량 입력"],
        ["혼합제품-성분2", "세정제 A", "108-88-3", "톨루엔", 10, "사용 1,000 / 저장 500", "kg", "위 행과 같은 제품이지만 다른 규제성분이므로 별도 행"],
        ["부피단위", "암모니아수 25%", "1336-21-6", "암모니아수", 25, "저장 2", "m3", "가능하면 kg로 환산해 입력. m3/L만 있으면 밀도 또는 질량을 추가로 질문할 수 있음"],
        ["CAS 미확인", "원료 B", "", "", 35, "사용 800", "kg", "CAS를 임의 추정하지 말고 SDS 제3항 또는 공급사 자료에서 확인 후 입력 권장"],
    ]
    for r_idx, row in enumerate(examples, start=14):
        _write_row(ws, r_idx, row)
        for c in range(1, 9):
            ws.cell(r_idx, c).fill = EXAMPLE_FILL
            ws.cell(r_idx, c).alignment = Alignment(vertical="top", wrap_text=True)

    ws.merge_cells("A21:H21")
    ws["A21"] = "자주 틀리는 입력"
    ws["A21"].fill = SECTION_FILL
    ws["A21"].font = Font(bold=True)
    mistakes = [
        ["제품 총중량을 함량 100%로 입력", "혼합제품이면 각 규제성분의 실제 함량을 입력"],
        ["CAS 번호 대신 제품코드 입력", "반드시 화학성분 CAS No. 입력"],
        ["평균 사용량 입력", "평균이 아니라 법령판정에 필요한 최대량 입력"],
        ["L·m3를 kg처럼 입력", "단위를 그대로 표시하고 가능하면 밀도로 질량 환산"],
        ["불확실한 값을 추정", "추정 대신 모름/빈칸으로 두고 프로그램의 추가질문에 답변"],
    ]
    for r_idx, row in enumerate(mistakes, start=22):
        _write_row(ws, r_idx, row)
        ws.cell(r_idx, 1).font = Font(bold=True)
        for c in range(1, 3):
            ws.cell(r_idx, c).alignment = Alignment(vertical="top", wrap_text=True)

    widths = [16, 22, 18, 24, 12, 24, 12, 52]
    for i, width in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = width
    ws.freeze_panes = "A4"


def build_minimal_input_workbook() -> bytes:
    """Return the company-facing minimal intake workbook as XLSX bytes."""
    wb = Workbook()
    _build_guide_sheet(wb)

    ws = wb.create_sheet("01_사업장기본정보")
    ws.merge_cells("A1:E1")
    ws["A1"] = "1. 사업장 기본정보 — 노란색 칸만 입력"
    ws["A1"].fill = TITLE_FILL
    ws["A1"].font = WHITE_FONT
    _write_row(ws, 3, ["항목", "입력값", "필수", "프로그램 활용", "작성예시/설명"])
    _style_header(ws, "A3:E3")

    rows = [
        ["사업장명", "", "Y", "공통", "예: ㈜가나다 대구공장"],
        ["사업장 주소", "", "Y", "화사계", "예: 대구광역시 ○○구 ○○로 123"],
        ["업종 또는 주요 생산품", "", "Y", "PSM", "예: 합성수지 제조 / 도료 제조 / 금속표면처리"],
        ["한국표준산업분류(KSIC) 코드", "", "N", "PSM", "예: 20202. 모르면 비워도 됨"],
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
    widths = [32, 38, 10, 16, 58]
    for i, width in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = width
    ws.freeze_panes = "A4"

    ws2 = wb.create_sheet("02_화학물질목록")
    ws2.merge_cells("A1:K1")
    ws2["A1"] = "2. 화학물질 목록 — 실제 회사 데이터만 입력"
    ws2["A1"].fill = TITLE_FILL
    ws2["A1"].font = WHITE_FONT
    ws2.merge_cells("A2:K2")
    ws2["A2"] = "※ 작성 예시는 00_작성가이드 시트에 있습니다. 이 시트에는 실제 귀사 물질만 입력하세요."
    ws2["A2"].fill = NOTE_FILL
    ws2["A2"].alignment = Alignment(wrap_text=True)
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
    widths2 = [7, 24, 16, 24, 11, 15, 18, 16, 12, 22, 36]
    for i, width in enumerate(widths2, 1):
        ws2.column_dimensions[chr(64 + i)].width = width
    ws2.freeze_panes = "D4"

    ws3 = wb.create_sheet("03_기존문서보유여부")
    ws3.merge_cells("A1:E1")
    ws3["A1"] = "3. 기존 작성자료 보유 여부"
    ws3["A1"].fill = TITLE_FILL
    ws3["A1"].font = WHITE_FONT
    headers3 = ["자료", "보유 여부", "프로그램 활용 시점", "왜 확인하는가", "작성예시/비고"]
    _write_row(ws3, 3, headers3)
    _style_header(ws3, "A3:E3")
    docs = [
        ["공정안전보고서(PSM)", "모름", "1차 판정 후", "기존 공정안전자료 재활용 가능성 확인", "있으면 Y, 없으면 N"],
        ["장외영향평가서", "모름", "화사계 대상 판정 후", "기존 시설·사고영향 자료 재활용 가능성 확인", "있으면 Y, 없으면 N"],
        ["기존 화학사고예방관리계획서", "모름", "변경/재제출 판정 시", "기존 승인 내용과 변경사항 비교", "있으면 Y, 없으면 N"],
        ["위해관리계획서", "모름", "화사계 대상 판정 후", "기존 비상대응 정보 재활용 가능성 확인", "있으면 Y, 없으면 N"],
    ]
    for r_idx, row in enumerate(docs, 4):
        _write_row(ws3, r_idx, row)
        ws3.cell(r_idx, 2).fill = INPUT_FILL
    yn2 = DataValidation(type="list", formula1='"Y,N,모름"')
    ws3.add_data_validation(yn2)
    yn2.add("B4:B7")
    widths3 = [34, 16, 26, 52, 30]
    for i, width in enumerate(widths3, 1):
        ws3.column_dimensions[chr(64 + i)].width = width

    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()
