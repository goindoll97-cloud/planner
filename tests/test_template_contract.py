from __future__ import annotations

import unittest
from io import BytesIO

from openpyxl import load_workbook

from engine.template import build_minimal_input_workbook


class CompanyTemplateContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workbook = load_workbook(BytesIO(build_minimal_input_workbook()), data_only=False)

    def test_guide_download_uses_current_company_input_structure(self) -> None:
        self.assertEqual(
            self.workbook.sheetnames,
            [
                "00_작성가이드",
                "01_사업장기본정보",
                "02_화학물질목록",
                "03_기존문서보유여부",
                "04_시설별최대보유량",
                "05_최종판정조건",
            ],
        )

    def test_chemical_sheet_contains_current_screening_columns(self) -> None:
        ws = self.workbook["02_화학물질목록"]
        headers = [ws.cell(3, col).value for col in range(1, 16)]
        self.assertEqual(
            headers,
            [
                "No.",
                "제품명",
                "CAS No.",
                "물질명(알면 입력)",
                "함량(%)",
                "취급형태",
                "최대 제조·사용량",
                "최대 저장량",
                "수량 단위",
                "최대 동시보유량(알면 입력)",
                "비고",
                "상온·상압 액체 여부(해당 시)",
                "최대보유량 법정 산정 여부",
                "회사/제품 SDS 제2항 보유·확인 여부",
                "SDS 제2항 유해성·위험성 분류(선택 입력)",
            ],
        )

    def test_facility_and_final_condition_sheets_are_present(self) -> None:
        facility = self.workbook["04_시설별최대보유량"]
        final_conditions = self.workbook["05_최종판정조건"]
        self.assertEqual(facility["A3"].value, "적용여부")
        self.assertEqual(facility["V3"].value, "비고")
        self.assertEqual(final_conditions["A2"].value, "제도")
        self.assertEqual(final_conditions["F2"].value, "판정에 미치는 영향")

    def test_guide_points_to_04_facility_sheet(self) -> None:
        guide = self.workbook["00_작성가이드"]
        values = [cell.value for row in guide.iter_rows() for cell in row if isinstance(cell.value, str)]
        self.assertTrue(any("04_시설별최대보유량" in value for value in values))
        self.assertFalse(any("03_시설별최대보유량" in value for value in values))


if __name__ == "__main__":
    unittest.main()
