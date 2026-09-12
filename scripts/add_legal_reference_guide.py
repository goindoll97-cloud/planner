from pathlib import Path

TEMPLATE = Path("engine/template.py")
TEST = Path("tests/test_template_contract.py")

text = TEMPLATE.read_text(encoding="utf-8")

if "def _build_legal_reference_sheet" not in text:
    marker = "\ndef _build_business_sheet(wb: Workbook) -> None:\n"
    if marker not in text:
        raise SystemExit("template insertion marker not found")

    function = r'''

def _build_legal_reference_sheet(wb: Workbook) -> None:
    """Add a law-only reference sheet for company preparers.

    This sheet intentionally excludes company-internal evidence sources. It tells
    the preparer only which legal provision should be checked for each legally
    material input field used in Stage 1 screening.
    """
    ws = wb.create_sheet("00A_법령작성참고")
    ws.merge_cells("A1:F1")
    ws["A1"] = "PSM·화학사고예방관리계획서 입력항목별 법령 작성 참고"
    ws["A1"].fill = TITLE_FILL
    ws["A1"].font = Font(color="FFFFFF", bold=True, size=14)
    ws["A1"].alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:F2")
    ws["A2"] = (
        "법령 확인이 필요한 작성항목만 정리한 시트입니다. 회사 내부자료의 위치나 확인방법은 적지 않았습니다. "
        "2026-09-12 기준 현행 법령·행정규칙을 기준으로 작성했으며, 실제 작성 시 국가법령정보센터에서 최신 현행본을 다시 확인하세요."
    )
    ws["A2"].fill = NOTE_FILL
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[2].height = 42

    headers = ["작성 시트", "작성 항목", "법령에서 확인할 내용", "관련 법령·조문·별표", "공식 법령 링크", "작성 시 주의사항"]
    _write_row(ws, 4, headers)
    _style_header(ws, "A4:F4")

    psm_law = "https://www.law.go.kr/법령/산업안전보건법/제44조"
    psm_decree = "https://www.law.go.kr/법령/산업안전보건법시행령/제43조"
    cap_law = "https://www.law.go.kr/법령/화학물질관리법/제23조"
    cap_rule = "https://www.law.go.kr/법령/화학물질관리법시행규칙/제19조"
    cap_qty = "https://www.law.go.kr/admRulLsInfoP.do?admRulId=93578&efYd=0"
    cap_write = "https://www.law.go.kr/DRF/lawService.do?ID=2100000278102&OC=me_pr&mobileYn=Y&target=admrul&type=HTML"

    rows = [
        ["01_사업장기본정보", "업종 또는 주요 생산품 / KSIC 코드", "공정안전보고서 제출 대상 사업 종류에 해당하는지 확인", "「산업안전보건법」 제44조제1항; 「산업안전보건법 시행령」 제43조제1항 각 호", psm_decree, "업종명 자체보다 시행령 제43조제1항 각 호의 사업 종류 해당 여부가 핵심"],
        ["02_화학물질목록", "CAS No. / 물질명 / 함량(%)", "PSM 별표 13 개별물질·농도조건 및 화사계 규정수량 물질범위와 대조", "「산업안전보건법 시행령」 제43조제1항 및 별표 13; 「유해화학물질의 규정수량에 관한 규정」 제3조 및 별표 1~3", psm_decree, "CAS 하나로 확정되지 않는 물질군·염·혼합물은 임의 확정하지 않음"],
        ["02_화학물질목록", "취급형태 / 최대 제조·사용량 / 최대 저장량 / 수량 단위", "별표 13 규정량과 제조·취급·저장량을 비교하고, 여러 물질이면 비고 제7호 합산한 값(R)을 산정", "「산업안전보건법 시행령」 별표 13 및 비고 제7호", psm_decree, "제조·취급량과 저장량의 법정 기준을 구분하여 작성"],
        ["02_화학물질목록", "상온·상압 액체 여부", "유해·위험성 그룹 및 물질의 성상에 따라 적용되는 규정수량·최대보유량 산정조건 확인", "「유해화학물질의 규정수량에 관한 규정」 제3조·제4조 및 별표 1~4", cap_qty, "성상을 추정하지 말고 법령상 적용조건이 확정될 수 있게 작성"],
        ["02_화학물질목록", "최대 동시보유량 / 최대보유량 법정 산정 여부", "사업장 내 모든 제조·사용·보관·저장시설에서 어느 순간 최대로 체류할 수 있는 양의 합인지 확인", "「유해화학물질의 규정수량에 관한 규정」 제2조제2호·제4조 및 별표 4; 「화학사고예방관리계획서 작성 등에 관한 규정」 제4조", cap_qty, "법정 최대보유량으로 확인된 값에만 Y 표시"],
        ["02_화학물질목록", "SDS 제2항 유해성·위험성 분류", "유해·위험성 그룹별 규정수량 적용 여부 확인", "「유해화학물질의 규정수량에 관한 규정」 제3조제1호 및 별표 1", cap_qty, "프로그램이 별표 1 그룹을 결정하는 데 필요한 경우에만 사용"],
        ["04_시설별최대보유량", "시설유형 / 제외시설여부 / 제외사유", "최대보유량에 포함되는 시설과 제외되는 시설 범위 확인", "「유해화학물질의 규정수량에 관한 규정」 제4조 및 별표 4; 「화학사고예방관리계획서 작성 등에 관한 규정」 제2조제11호·제4조", cap_qty, "탱크로리 등 법령상 제외대상은 최대보유량에 잘못 합산하지 않음"],
        ["04_시설별최대보유량", "물질성상 / 공정유형 / 별표4 기준함량(%)", "제조·사용시설의 함량기준, 단순혼합·반응 전 최종함량, 복수성상 산정조건 확인", "「유해화학물질의 규정수량에 관한 규정」 별표 4", cap_qty, "공정유형에 따라 어떤 시점의 함량을 적용하는지 달라질 수 있음"],
        ["04_시설별최대보유량", "설계용량 / 용량단위 / 비중 또는 밀도", "저장탱크 및 제조·사용시설의 최대보유량 산정 시 설계용량과 비중 적용", "「유해화학물질의 규정수량에 관한 규정」 제4조 및 별표 4", cap_qty, "용량과 비중의 단위를 맞춰 질량으로 환산할 수 있어야 함"],
        ["04_시설별최대보유량", "보관계획도 최대량 / 일일최대보관량", "보관시설의 최대보유량 산정기준 확인", "「유해화학물질의 규정수량에 관한 규정」 별표 4", cap_qty, "보관구획도 기준량과 일일최대보관량을 법령 기준에 맞게 반영"],
        ["04_시설별최대보유량", "직접확인 최대보유량 / 복수성상 증빙", "기상·고압가스·복수성상 등 일반 용량×비중 방식 외 산정조건 확인", "「유해화학물질의 규정수량에 관한 규정」 별표 4 비고", cap_qty, "증빙이 필요한 예외 산정은 근거가 불명확하면 판정보류"],
        ["05_최종판정조건", "시행령 제43조제2항 제외설비 해당 여부 / 유형", "공정안전보고서 제출 대상에서 제외되는 설비인지 확인", "「산업안전보건법」 제44조제1항; 「산업안전보건법 시행령」 제43조제2항", psm_decree, "해당한다고 판단한 경우 시행령에 규정된 제외설비 유형까지 특정"],
        ["05_최종판정조건", "별표 13 제1호 인화성 가스 해당 여부 및 수량", "인화성 가스 해당 여부와 제조·취급 5,000kg / 저장 200,000kg 규정량 적용", "「산업안전보건법 시행령」 별표 13 제1호", psm_decree, "해당 시 제조·취급량과 저장량을 각각 작성"],
        ["05_최종판정조건", "별표 13 제2호 인화성 액체 해당 여부 및 수량", "인화성 액체 해당 여부와 제조·취급 5,000kg / 저장 200,000kg 규정량 적용", "「산업안전보건법 시행령」 별표 13 제2호", psm_decree, "해당 시 제조·취급량과 저장량을 각각 작성"],
        ["05_최종판정조건", "별표 13 제23호 발연황산 SO3 중량%", "삼산화황 중량 65% 이상 80% 미만 조건 해당 여부 확인", "「산업안전보건법 시행령」 별표 13 제23호", psm_decree, "조건을 충족할 때만 해당 별표 13 항목으로 반영"],
        ["05_최종판정조건", "별표 13 제42호 니트로셀룰로오스 질소 함유량%", "질소 함유량 12.6% 이상 조건 해당 여부 확인", "「산업안전보건법 시행령」 별표 13 제42호", psm_decree, "조건을 충족할 때만 해당 별표 13 항목으로 반영"],
        ["05_최종판정조건", "가스를 전문으로 저장·판매하는 시설 내 가스 여부", "별표 13 비고 제8호 적용 여부 확인", "「산업안전보건법 시행령」 별표 13 비고 제8호", psm_decree, "해당 시 06 시트의 제외수량 작성 필요"],
        ["06_PSM_비고8제외수량", "별표13 호수 / 제조·취급 제외량 / 저장 제외량", "비고 제8호에 따라 합산에서 제외할 수량을 별표 13 항목별로 구분", "「산업안전보건법 시행령」 별표 13 비고 제7호·제8호", psm_decree, "제외량이 실제 확인된 수량을 초과하면 안 됨"],
        ["05_최종판정조건", "법 제23조제1항 단서 해당 여부", "화학사고예방관리계획서 작성·제출 의무의 법정 예외 해당 여부 확인", "「화학물질관리법」 제23조제1항 단서; 「화학물질관리법 시행규칙」 제19조제2항; 「화학사고예방관리계획서 작성 등에 관한 규정」 제9조", cap_law, "단서 또는 작성 면제 시설을 추정해서 적용하지 않음"],
        ["05_최종판정조건", "법적 예외 적용 유형 / 관련 취급시설 전체 적용 여부", "법정 예외가 실제 어떤 유형인지와 사업장 관련 취급시설 전체에 적용되는지 확인", "「화학물질관리법」 제23조제1항; 같은 법 시행규칙 제19조제2항; 「화학사고예방관리계획서 작성 등에 관한 규정」 제9조", cap_rule, "일부 시설에만 적용되면 전체 사업장을 일괄 면제 처리하지 않음"],
        ["05_최종판정조건", "상위 규정수량 이상을 취급하는 개별 주요취급시설 존재 여부", "1군 사업장 판단에 필요한 주요취급시설 존재 여부 확인", "「화학물질관리법 시행규칙」 제19조제8항; 「화학사고예방관리계획서 작성 등에 관한 규정」 제2조제12호의1·제4조", cap_write, "상위 규정수량 이상이라는 사업장 합계만으로 개별 주요취급시설을 자동 확정하지 않음"],
        ["05_최종판정조건", "작성수준 1군 / 2군 판단", "물질별 최대보유량과 상위·하위 규정수량을 비교하여 작성수준 결정", "「유해화학물질의 규정수량에 관한 규정」 제3조·제4조 및 별표 1~4; 「화학사고예방관리계획서 작성 등에 관한 규정」 제2조제12호의1·12호의2, 제4조·제6조", cap_write, "위험도 분석이 아니라 Stage 1의 작성·제출 의무 및 작성수준 판단용"],
    ]

    for r_idx, row in enumerate(rows, start=5):
        _write_row(ws, r_idx, row)
        scheme = row[0]
        ws.cell(r_idx, 1).fill = PSM_FILL if scheme.startswith("05_") and "별표 13" in row[1] or scheme.startswith("06_") else CAP_FILL if scheme.startswith("04_") else NOTE_FILL
        link_cell = ws.cell(r_idx, 5)
        link_cell.hyperlink = row[4]
        link_cell.style = "Hyperlink"

    _wrap_range(ws, f"A1:F{4 + len(rows)}")
    widths = [24, 43, 54, 68, 48, 50]
    for i, width in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = width
    ws.freeze_panes = "A5"
'''
    text = text.replace(marker, function + marker, 1)

call_old = "    _build_guide_sheet(wb)\n    _build_business_sheet(wb)"
call_new = "    _build_guide_sheet(wb)\n    _build_legal_reference_sheet(wb)\n    _build_business_sheet(wb)"
if call_old in text:
    text = text.replace(call_old, call_new, 1)
elif "_build_legal_reference_sheet(wb)" not in text:
    raise SystemExit("workbook builder call marker not found")

TEMPLATE.write_text(text, encoding="utf-8")

test = TEST.read_text(encoding="utf-8")
old_list = '''                "00_작성가이드",\n                "01_사업장기본정보",'''
new_list = '''                "00_작성가이드",\n                "00A_법령작성참고",\n                "01_사업장기본정보",'''
if old_list in test:
    test = test.replace(old_list, new_list, 1)

if "test_legal_reference_sheet_contains_only_law_guidance" not in test:
    insert = '''\n    def test_legal_reference_sheet_contains_only_law_guidance(self) -> None:\n        ws = self.workbook["00A_법령작성참고"]\n        headers = [ws.cell(4, col).value for col in range(1, 7)]\n        self.assertEqual(headers, ["작성 시트", "작성 항목", "법령에서 확인할 내용", "관련 법령·조문·별표", "공식 법령 링크", "작성 시 주의사항"])\n        values = [cell.value for row in ws.iter_rows() for cell in row if isinstance(cell.value, str)]\n        joined = "\\n".join(values)\n        self.assertIn("「산업안전보건법 시행령」 제43조제1항", joined)\n        self.assertIn("별표 13 비고 제7호", joined)\n        self.assertIn("「화학물질관리법」 제23조제1항", joined)\n        self.assertIn("「유해화학물질의 규정수량에 관한 규정」", joined)\n        self.assertIn("「화학사고예방관리계획서 작성 등에 관한 규정」 제9조", joined)\n        self.assertNotIn("사업자등록증", joined)\n        self.assertNotIn("생산계획", joined)\n        self.assertNotIn("사내", joined)\n\n'''
    marker2 = '\n\nif __name__ == "__main__":\n'
    if marker2 not in test:
        raise SystemExit("test insertion marker not found")
    test = test.replace(marker2, insert + marker2, 1)

TEST.write_text(test, encoding="utf-8")
