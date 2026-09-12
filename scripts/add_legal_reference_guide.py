from pathlib import Path

TEMPLATE = Path("engine/template.py")
INIT = Path("engine/__init__.py")
TEST = Path("tests/test_template_contract.py")

text = TEMPLATE.read_text(encoding="utf-8")

if "def build_legal_reference_workbook" not in text:
    marker = "\ndef build_minimal_input_workbook() -> bytes:\n"
    if marker not in text:
        raise SystemExit("template insertion marker not found")

    function = r'''

def build_legal_reference_workbook() -> bytes:
    """Return a separate law-only reference workbook for company preparers."""
    wb = Workbook()

    guide = wb.active
    guide.title = "00_사용안내"
    guide.merge_cells("A1:F1")
    guide["A1"] = "PSM·화학사고예방관리계획서 법령 작성 참고"
    guide["A1"].fill = TITLE_FILL
    guide["A1"].font = Font(color="FFFFFF", bold=True, size=14)
    guide["A1"].alignment = Alignment(vertical="center")
    guide.row_dimensions[1].height = 28
    guide.merge_cells("A3:F3")
    guide["A3"] = (
        "회사 입력파일을 작성할 때 법령 확인이 필요한 항목만 정리한 별도 참고파일입니다. "
        "회사 내부자료의 위치·문서명·확인방법은 수록하지 않습니다."
    )
    guide["A3"].fill = NOTE_FILL
    guide["A3"].alignment = Alignment(wrap_text=True)
    guide.merge_cells("A5:F5")
    guide["A5"] = "법령은 개정될 수 있으므로 실제 판정 시 프로그램의 법령 동기화 상태와 국가법령정보센터 최신 현행본을 함께 확인하세요."
    guide["A5"].fill = NOTE_FILL
    guide["A5"].font = Font(bold=True)
    guide["A5"].alignment = Alignment(wrap_text=True)
    _write_row(guide, 7, ["구분", "현행 기준", "핵심 법령", "핵심 조문·별표", "비고", "공식 링크"])
    _style_header(guide, "A7:F7")
    guide_rows = [
        ["공정안전보고서(PSM)", "2026-09-12 확인", "「산업안전보건법」 / 「산업안전보건법 시행령」", "법 제44조제1항 / 시행령 제43조 / 별표 13", "별표 13: 유해·위험물질 규정량", "https://www.law.go.kr/법령/산업안전보건법시행령/제43조"],
        ["화학사고예방관리계획서", "2026-09-12 확인", "「화학물질관리법」 / 같은 법 시행규칙", "법 제23조 / 시행규칙 제19조", "작성·제출 의무 및 법정 예외", "https://www.law.go.kr/법령/화학물질관리법/제23조"],
        ["화학사고예방관리계획서", "시행 2026.5.6", "「유해화학물질의 규정수량에 관한 규정」", "제2조~제4조 / 별표 1~4", "화학물질안전원고시 제2026-4호", "https://www.law.go.kr/admRulLsInfoP.do?admRulId=93578&efYd=0"],
        ["화학사고예방관리계획서", "시행 2026.4.22", "「화학사고예방관리계획서 작성 등에 관한 규정」", "제2조 / 제4조 / 제6조 / 제9조", "화학물질안전원고시 제2026-7호", "https://www.law.go.kr/admRulInfoP.do?admRulSeq=2100000278102"],
    ]
    for row_idx, row in enumerate(guide_rows, start=8):
        _write_row(guide, row_idx, row)
        link = guide.cell(row_idx, 6)
        link.hyperlink = row[5]
        link.style = "Hyperlink"
    _wrap_range(guide, "A1:F11")
    for idx, width in enumerate([28, 22, 48, 46, 44, 50], 1):
        guide.column_dimensions[chr(64 + idx)].width = width
    guide.freeze_panes = "A8"

    def build_reference_sheet(title: str, rows: list[list[str]]) -> None:
        ws = wb.create_sheet(title)
        ws.merge_cells("A1:F1")
        ws["A1"] = f"{title.replace('_', ' ')} — 회사 입력파일 작성항목별 법령 참고"
        ws["A1"].fill = TITLE_FILL
        ws["A1"].font = Font(color="FFFFFF", bold=True, size=13)
        _write_row(ws, 3, ["입력파일 시트", "작성 항목", "법령에서 확인할 내용", "관련 법령·조문·별표", "현행 기준", "국가법령정보센터"])
        _style_header(ws, "A3:F3")
        for row_idx, row in enumerate(rows, start=4):
            _write_row(ws, row_idx, row)
            link = ws.cell(row_idx, 6)
            link.hyperlink = row[5]
            link.style = "Hyperlink"
        _wrap_range(ws, f"A1:F{3 + len(rows)}")
        for idx, width in enumerate([25, 43, 58, 70, 32, 50], 1):
            ws.column_dimensions[chr(64 + idx)].width = width
        ws.freeze_panes = "A4"

    psm_url = "https://www.law.go.kr/법령/산업안전보건법시행령/제43조"
    psm_rows = [
        ["01_사업장기본정보", "업종 또는 주요 생산품 / KSIC 코드", "시행령 제43조제1항 각 호의 사업 종류 해당 여부 확인", "「산업안전보건법」 제44조제1항; 「산업안전보건법 시행령」 제43조제1항", "시행령 [시행 2026.8.1.] 대통령령 제36540호", psm_url],
        ["02_화학물질목록", "CAS No. / 물질명 / 함량(%)", "별표 13 개별 유해·위험물질 및 농도·성분조건 해당 여부 확인", "「산업안전보건법 시행령」 제43조제1항 및 별표 13 「유해·위험물질 규정량」", "별표 13 현행본", psm_url],
        ["02_화학물질목록", "최대 제조·사용량 / 최대 저장량 / 수량 단위", "각 별표 13 항목의 제조·취급 규정량과 저장 규정량 비교", "「산업안전보건법 시행령」 별표 13 및 비고 제1호·제7호", "별표 13 현행본", psm_url],
        ["05_최종판정조건", "시행령 제43조제2항 제외설비 해당 여부 / 유형", "공정안전보고서 제출 대상에서 제외되는 설비인지 확인", "「산업안전보건법 시행령」 제43조제2항", "시행령 현행본", psm_url],
        ["05_최종판정조건", "별표 13 제1호 인화성 가스 해당 여부 및 수량", "인화성 가스에 해당하는지와 제조·취급 5,000kg / 저장 200,000kg 규정량 적용", "「산업안전보건법 시행령」 별표 13 제1호", "제조·취급 5,000kg / 저장 200,000kg", psm_url],
        ["05_최종판정조건", "별표 13 제2호 인화성 액체 해당 여부 및 수량", "인화성 액체에 해당하는지와 제조·취급 5,000kg / 저장 200,000kg 규정량 적용", "「산업안전보건법 시행령」 별표 13 제2호", "제조·취급 5,000kg / 저장 200,000kg", psm_url],
        ["05_최종판정조건", "별표 13 제23호 발연황산 SO3 중량%", "삼산화황 중량 65% 이상 80% 미만 조건 해당 여부 확인", "「산업안전보건법 시행령」 별표 13 제23호", "SO3 65% 이상 80% 미만", psm_url],
        ["05_최종판정조건", "별표 13 제42호 니트로셀룰로오스 질소 함유량%", "질소 함유량 12.6% 이상 조건 해당 여부 확인", "「산업안전보건법 시행령」 별표 13 제42호", "질소 12.6% 이상", psm_url],
        ["05_최종판정조건", "가스를 전문으로 저장·판매하는 시설 내 가스 여부", "별표 13 비고 제8호 적용 여부 확인", "「산업안전보건법 시행령」 별표 13 비고 제8호", "별표 13 현행본", psm_url],
        ["06_PSM_비고8제외수량", "별표13 호수 / 제조·취급 제외량 / 저장 제외량", "비고 제8호에 따라 제외할 수량을 항목별로 구분하고 비고 제7호 합산한 값(R)에 반영", "「산업안전보건법 시행령」 별표 13 비고 제7호·제8호", "별표 13 현행본", psm_url],
    ]
    build_reference_sheet("01_PSM_법령참고", psm_rows)

    cap_law_url = "https://www.law.go.kr/법령/화학물질관리법/제23조"
    cap_rule_url = "https://www.law.go.kr/법령/화학물질관리법시행규칙/제19조"
    cap_qty_url = "https://www.law.go.kr/admRulLsInfoP.do?admRulId=93578&efYd=0"
    cap_write_url = "https://www.law.go.kr/admRulInfoP.do?admRulSeq=2100000278102"
    cap_rows = [
        ["02_화학물질목록", "CAS No. / 물질명 / 함량(%)", "유해화학물질별 상위·하위 규정수량 및 유해·위험성 그룹·물질범위 확인", "「유해화학물질의 규정수량에 관한 규정」 제3조 및 별표 1~3", "화학물질안전원고시 제2026-4호", cap_qty_url],
        ["02_화학물질목록", "상온·상압 액체 여부", "물질 성상에 따라 적용되는 규정수량 및 최대보유량 산정조건 확인", "「유해화학물질의 규정수량에 관한 규정」 제3조·제4조 및 별표 1~4", "화학물질안전원고시 제2026-4호", cap_qty_url],
        ["02_화학물질목록", "최대 동시보유량 / 최대보유량 법정 산정 여부", "사업장 최대보유량의 정의 및 물질별 규정수량 비교방법 확인", "「유해화학물질의 규정수량에 관한 규정」 제2조제2호·제4조; 「화학사고예방관리계획서 작성 등에 관한 규정」 제4조", "고시 제2026-4호 / 제2026-7호", cap_qty_url],
        ["02_화학물질목록", "SDS 제2항 유해성·위험성 분류", "별표 1 유해·위험성 그룹별 규정수량 적용 여부 확인", "「유해화학물질의 규정수량에 관한 규정」 제3조제1호 및 별표 1", "화학물질안전원고시 제2026-4호", cap_qty_url],
        ["04_시설별최대보유량", "시설유형 / 제외시설여부 / 제외사유", "최대보유량에 포함되는 취급시설과 제외되는 범위 확인", "「유해화학물질의 규정수량에 관한 규정」 제4조 및 별표 4; 「화학사고예방관리계획서 작성 등에 관한 규정」 제2조제11호·제4조", "고시 제2026-4호 / 제2026-7호", cap_write_url],
        ["04_시설별최대보유량", "물질성상 / 공정유형 / 별표4 기준함량(%)", "제조·사용시설의 함량기준과 공정유형별 적용조건 확인", "「유해화학물질의 규정수량에 관한 규정」 별표 4", "화학물질안전원고시 제2026-4호", cap_qty_url],
        ["04_시설별최대보유량", "설계용량 / 용량단위 / 비중 또는 밀도", "저장탱크 및 제조·사용시설 최대보유량의 질량 환산기준 확인", "「유해화학물질의 규정수량에 관한 규정」 제4조 및 별표 4", "화학물질안전원고시 제2026-4호", cap_qty_url],
        ["04_시설별최대보유량", "보관계획도 최대량 / 일일최대보관량", "보관시설 최대보유량 산정기준 확인", "「유해화학물질의 규정수량에 관한 규정」 별표 4", "화학물질안전원고시 제2026-4호", cap_qty_url],
        ["04_시설별최대보유량", "직접확인 최대보유량 / 복수성상 증빙", "기체·고압가스·복수성상 등 별표 4의 특수 산정조건 확인", "「유해화학물질의 규정수량에 관한 규정」 별표 4 및 비고", "화학물질안전원고시 제2026-4호", cap_qty_url],
        ["05_최종판정조건", "법 제23조제1항 단서 해당 여부", "화학사고예방관리계획서 작성·제출 의무의 법정 예외 해당 여부 확인", "「화학물질관리법」 제23조제1항 단서; 「화학물질관리법 시행규칙」 제19조제2항; 「화학사고예방관리계획서 작성 등에 관한 규정」 제9조", "법률·시행규칙·고시 현행본", cap_law_url],
        ["05_최종판정조건", "법적 예외 적용 유형 / 관련 취급시설 전체 적용 여부", "법정 예외의 정확한 유형과 적용범위 확인", "「화학물질관리법」 제23조제1항; 같은 법 시행규칙 제19조제2항; 「화학사고예방관리계획서 작성 등에 관한 규정」 제9조", "고시 제2026-7호", cap_rule_url],
        ["05_최종판정조건", "상위 규정수량 이상을 취급하는 개별 주요취급시설 존재 여부", "1군 사업장 작성수준 판단에 필요한 주요취급시설 존재 여부 확인", "「화학물질관리법 시행규칙」 제19조제8항; 「화학사고예방관리계획서 작성 등에 관한 규정」 제2조·제4조", "화학물질안전원고시 제2026-7호", cap_write_url],
        ["05_최종판정조건", "작성수준 1군 / 2군 판단", "물질별 최대보유량과 상위·하위 규정수량을 비교하여 작성수준 결정", "「유해화학물질의 규정수량에 관한 규정」 제3조·제4조 및 별표 1~4; 「화학사고예방관리계획서 작성 등에 관한 규정」 제2조·제4조·제6조", "고시 제2026-4호 / 제2026-7호", cap_write_url],
    ]
    build_reference_sheet("02_화사계_법령참고", cap_rows)

    output = BytesIO()
    wb.save(output)
    return output.getvalue()
'''
    text = text.replace(marker, function + marker, 1)

TEMPLATE.write_text(text, encoding="utf-8")

init = INIT.read_text(encoding="utf-8")
init = init.replace("from .template import build_minimal_input_workbook", "from .template import build_legal_reference_workbook, build_minimal_input_workbook", 1)
anchor = '''            st.download_button(
                "회사 입력 작성예시·가이드 파일 다운로드",
                data=build_minimal_input_workbook(),
                file_name="PSM_CAP_회사입력_작성예시_가이드_v1.0.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="company_input_guide_download_v10",
                width="stretch",
            )
'''
addition = anchor + '''            st.download_button(
                "법령 작성 참고파일 다운로드",
                data=build_legal_reference_workbook(),
                file_name="PSM_CAP_법령작성참고_v1.0.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="legal_reference_guide_download_v10",
                width="stretch",
            )
            st.caption("법령 참고파일은 입력용 파일이 아닙니다. 각 작성항목과 연결되는 법령·조문·별표만 확인하는 용도입니다.")
'''
if "legal_reference_guide_download_v10" not in init:
    if anchor not in init:
        raise SystemExit("download button anchor not found")
    init = init.replace(anchor, addition, 1)
INIT.write_text(init, encoding="utf-8")

test = TEST.read_text(encoding="utf-8")
test = test.replace("from engine.template import build_minimal_input_workbook", "from engine.template import build_legal_reference_workbook, build_minimal_input_workbook", 1)
if "test_separate_legal_reference_workbook" not in test:
    method = '''\n    def test_separate_legal_reference_workbook(self) -> None:\n        legal = load_workbook(BytesIO(build_legal_reference_workbook()), data_only=False)\n        self.assertEqual(legal.sheetnames, ["00_사용안내", "01_PSM_법령참고", "02_화사계_법령참고"])\n        psm_values = "\\n".join(str(c.value) for row in legal["01_PSM_법령참고"].iter_rows() for c in row if c.value is not None)\n        cap_values = "\\n".join(str(c.value) for row in legal["02_화사계_법령참고"].iter_rows() for c in row if c.value is not None)\n        self.assertIn("「산업안전보건법 시행령」 제43조제1항", psm_values)\n        self.assertIn("별표 13 비고 제7호·제8호", psm_values)\n        self.assertIn("「화학물질관리법」 제23조제1항", cap_values)\n        self.assertIn("「유해화학물질의 규정수량에 관한 규정」", cap_values)\n        self.assertIn("「화학사고예방관리계획서 작성 등에 관한 규정」 제9조", cap_values)\n        combined = psm_values + "\\n" + cap_values\n        for forbidden in ["사업자등록증", "생산계획", "사내", "회사 내부자료"]:\n            self.assertNotIn(forbidden, combined)\n\n'''
    marker = '\n\nif __name__ == "__main__":\n'
    if marker not in test:
        raise SystemExit("test insertion marker not found")
    test = test.replace(marker, method + marker, 1)
TEST.write_text(test, encoding="utf-8")
