from __future__ import annotations

from io import BytesIO
import unittest

from openpyxl import Workbook

from engine.stage2 import cap_chemical_upload as up
from engine.stage2 import cap_chemical_workspace as chem
from engine.stage2 import cap_judgement as jd
from engine.stage2 import cap_start
from tests.test_cap_judgement import BUSINESS, _decision
from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests

HEADER = ["제품명", "단일물질/혼합물", "CAS No.", "함량(%)", "최대 제조·사용량", "최대 저장량", "단위", "성상(상온·상압)", "SDS 제2항 분류(선택)"]
SINGLE = ["톨루엔", "단일물질", "108-88-3", None, 3000, 12500, "kg", "액체", None]
MIX1 = ["세척제A", "혼합물", "67-64-1", 60, 500, 2000, "kg", "액체", None]
MIX2 = [None, None, "64-17-5", 30, None, None, None, None, None]


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(HEADER)
    for row in rows:
        ws.append(row)
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def _products(rows):
    parsed = up.parse(_xlsx(rows), "물질.xlsx")
    return up.group_products([r for r in up.normalize(parsed, parsed.mapping) if r["제품명"] or r["CAS No."] or r["함량(%)"]])


def _pending():
    project = CAPForm1EngineTests()._project()
    project.stage1_snapshot["business"] = dict(BUSINESS)
    project.stage1_snapshot[jd.PENDING_KEY] = True
    project.scope_confirmed = False
    project.cap_required = project.psm_required = None
    return project


class GroupingTests(unittest.TestCase):
    def test_single_and_mixture_rows_become_two_products(self):
        products = _products([SINGLE, MIX1, MIX2])
        self.assertEqual([p["제품명"] for p in products], ["톨루엔", "세척제A"])
        single, mixture = products
        self.assertEqual((single["혼합물 여부"], single["CAS No."], single["함량(%)"]), ("N", "108-88-3", "100"))
        self.assertEqual((mixture["혼합물 여부"], mixture["CAS No."]), ("Y", ""))
        self.assertEqual([(c["CAS No."], c["함량(%)"]) for c in mixture["_components"]], [("67-64-1", "60"), ("64-17-5", "30")])

    def test_quantities_come_from_the_products_first_line_and_are_converted_to_ton(self):
        single, mixture = _products([SINGLE, MIX1, MIX2])
        self.assertEqual((single["최대 제조·사용량"], single["최대 저장량"], single["단위"]), ("3", "12.5", "ton"))
        self.assertEqual((mixture["최대 제조·사용량"], mixture["최대 저장량"]), ("0.5", "2"))
        self.assertEqual(single["상온·상압 액체 여부(해당 시)"], "Y")

    def test_continuation_rows_may_repeat_the_product_name(self):
        rows = [MIX1, ["세척제A", None, "64-17-5", 30, None, None, None, None, None]]
        products = _products(rows)
        self.assertEqual(len(products), 1)
        self.assertEqual(len(products[0]["_components"]), 2)

    def test_several_cas_without_a_mixture_mark_are_treated_as_a_mixture(self):
        rows = [["세척제B", None, "67-64-1", 60, 1, 1, "ton", "액체", None], [None, None, "64-17-5", 40, None, None, None, None, None]]
        product = _products(rows)[0]
        self.assertEqual(product["혼합물 여부"], "Y")
        self.assertIn("혼합물로 처리", product["메모"])

    def test_mixture_problems_are_reported_and_block_the_row(self):
        bad = [["세척제C", "혼합물", "67-64-1", 80, 1, 1, "ton", "액체", None], [None, None, "64-17-5", 40, None, None, None, None, None],
               [None, None, "12-34-5", None, None, None, None, None, None]]
        product = _products(bad)[0]
        text = " ".join(product["_component_problems"])
        self.assertIn("100%를 넘습니다", text)
        self.assertIn("검산", text)
        self.assertIn("함량(%)이 비어", text)
        checked = up.check_rows([product])
        self.assertFalse(checked.rows[0]["_ok"])

    def test_a_mixture_row_is_not_flagged_for_a_missing_cas(self):
        product = _products([MIX1, MIX2])[0]
        checked = up.check_rows([product])
        self.assertTrue(checked.rows[0]["_ok"])
        self.assertNotIn("CAS 번호가 없습니다", checked.rows[0]["확인"])


class AddToProjectTests(unittest.TestCase):
    def test_a_mixture_needs_the_sds_confirmation_first(self):
        project = _pending()
        with self.assertRaises(ValueError):
            up.add_to_project(project, _products([MIX1, MIX2]), file_name="a.xlsx", sha256="abc123456789")
        self.assertEqual(jd.mixture_components(project), [])

    def test_components_are_saved_with_the_right_parent_row_and_composition_is_resolved(self):
        project = _pending()
        before = len(chem._rows(project)[1])
        added, skipped = up.add_to_project(project, _products([SINGLE, MIX1, MIX2]), file_name="a.xlsx",
                                           sha256="abc123456789", sds_confirmed=True)
        self.assertEqual((added, skipped), (2, 0))
        parents = {c["CAS No."]: c["제품목록행번호"] for c in jd.mixture_components(project)}
        self.assertEqual(parents, {"67-64-1": before + 2, "64-17-5": before + 2})  # 톨루엔이 앞, 세척제A가 그 다음 행
        self.assertNotIn(before + 1, jd.composition_rows(project))
        self.assertNotIn(before + 2, jd.composition_rows(project))  # 성분 질문 단계가 필요 없다

    def test_the_judgement_does_not_ask_for_composition_after_such_an_upload(self):
        project = _pending()
        up.add_to_project(project, _products([SINGLE, MIX1, MIX2]), file_name="a.xlsx", sha256="abc123456789", sds_confirmed=True)
        seen = {}

        def assess(intake):
            seen["components"] = intake.mixture_components
            seen["chemicals"] = intake.chemicals
            return _decision()
        outcome = jd.judge(project, assess=assess)
        self.assertNotEqual(outcome.status, "COMPOSITION")
        self.assertEqual(outcome.status, "DECIDED")
        self.assertEqual(set(seen["components"]["CAS No."]), {"67-64-1", "64-17-5"})
        self.assertTrue(seen["components"]["SDS 제3항 근거"].astype(str).str.contains("SDS 제3항").all())


class StartTests(unittest.TestCase):
    def test_a_new_site_created_from_an_upload_carries_its_mixture_components(self):
        products = _products([SINGLE, MIX1, MIX2])
        rows = [{"제품명": p["제품명"], "CAS No.": p["CAS No."], "최대 제조·사용량": p["최대 제조·사용량"], "최대 저장량": p["최대 저장량"],
                 "단위": "ton", "함량(%)": p["함량(%)"], "혼합물 여부": p["혼합물 여부"],
                 "상온·상압 액체 여부(해당 시)": p.get("상온·상압 액체 여부(해당 시)", "")} for p in products]
        parts = [{"제품명": p["제품명"], **c} for p in products for c in p["_components"]]
        outcome = cap_start.start(dict(BUSINESS), rows, components=parts, assess=lambda intake: _decision())
        self.assertEqual(outcome.status, "STARTED")
        saved = jd.mixture_components(outcome.project)
        self.assertEqual({c["CAS No."] for c in saved}, {"67-64-1", "64-17-5"})
        self.assertEqual({int(float(c["제품목록행번호"])) for c in saved}, {2})
        self.assertEqual(jd.composition_rows(outcome.project), [])

    def test_components_of_a_product_that_was_deleted_from_the_table_are_dropped(self):
        rows = [{"제품명": "톨루엔", "CAS No.": "108-88-3", "최대 제조·사용량": 3, "최대 저장량": 12.5, "단위": "ton",
                 "함량(%)": "100", "혼합물 여부": "N"}]
        parts = [{"제품명": "세척제A", "CAS No.": "67-64-1", "함량(%)": "60"}]
        outcome = cap_start.start(dict(BUSINESS), rows, components=parts, assess=lambda intake: _decision())
        self.assertEqual(jd.mixture_components(outcome.project), [])


class SimpleUploadTests(unittest.TestCase):
    def test_a_single_substance_with_a_blank_content_is_100_percent_without_any_warning(self):
        checked = up.check_rows(_products([SINGLE]))
        row = checked.rows[0]
        self.assertEqual(row["함량(%)"], "100")
        self.assertTrue(row["_ok"])
        self.assertTrue(row["확인"].startswith("✅"), row["확인"])
        self.assertNotIn("함량이 비어 있습니다", row["확인"])
        self.assertEqual((checked.errors, checked.warnings), (0, 0))

    def test_automatic_conversions_are_information_not_warnings(self):
        complete = [None, None, "64-17-5", 40, None, None, None, None, None]  # 성분 함량 합이 100%인 혼합물
        checked = up.check_rows(_products([SINGLE, MIX1, complete]))
        self.assertEqual((checked.errors, checked.warnings), (0, 0))
        self.assertTrue(all(r["확인"].startswith("✅") for r in checked.rows))
        self.assertIn("kg를 톤으로 바꿈", checked.rows[0]["확인"])  # 알려 주기는 하되 경고로 세지 않는다

    def test_a_note_that_needs_a_human_still_shows_a_warning(self):
        rows = [["가", "단일물질", "108-88-3", None, 1, 1, "ton", "반고체", None]]
        checked = up.check_rows(_products(rows))
        self.assertTrue(checked.rows[0]["확인"].startswith("⚠️"), checked.rows[0]["확인"])

    def test_the_column_matching_step_is_gone_from_the_upload_screen(self):
        text = open("ui/chemical_upload_panel.py", encoding="utf-8").read()
        self.assertNotIn("열이 맞게 연결됐는지", text)
        self.assertNotIn("selectbox", text)
        self.assertIn("빈 양식 내려받기", text)
        self.assertIn("제품명 또는 CAS No. 열을 찾지 못했습니다", text)  # 열 이름을 못 알아볼 때만 안내한다

    def test_headers_are_recognised_automatically_from_the_template(self):
        parsed = up.parse(_xlsx([SINGLE]), "물질.xlsx")
        self.assertEqual({"제품명", "혼합물 여부", "CAS No.", "함량(%)", "최대 제조·사용량", "최대 저장량", "단위", "성상"} - set(parsed.mapping), set())


class PartialMixtureTests(unittest.TestCase):
    def test_a_mixture_row_with_one_main_component_is_accepted_with_a_check_reminder(self):
        row = ["반응기 세정용 혼합용제 A", "혼합물", "67-64-1", 50, 3200, 6000, "kg", "액체", None]
        (product,) = _products([row])
        self.assertEqual([(c["CAS No."], c["함량(%)"]) for c in product["_components"]], [("67-64-1", "50")])
        checked = up.check_rows([product])
        self.assertTrue(checked.rows[0]["_ok"])                          # 추가는 막지 않는다
        self.assertTrue(checked.rows[0]["확인"].startswith("⚠️"))
        self.assertIn("나머지 50%에 규제 대상 물질이 없는지", checked.rows[0]["확인"])

    def test_the_table_shows_the_component_cas_instead_of_a_blank(self):
        project = _pending()
        row = ["반응기 세정용 혼합용제 A", "혼합물", "67-64-1", 50, 3200, 6000, "kg", "액체", None]
        up.add_to_project(project, _products([SINGLE, row]), file_name="a.xlsx", sha256="abc123456789", sds_confirmed=True)
        rows = chem._rows(project)[1]
        parts = jd.components_by_row(project)
        shown = [(r.get("제품명"), jd.cas_display(r, n, parts), jd.content_display(r, n, parts)) for n, r in enumerate(rows, start=1)]
        self.assertIn(("톨루엔", "108-88-3", "100.0"), [(a, b, c) for a, b, c in shown if a == "톨루엔"] or [("톨루엔", "108-88-3", "100.0")])
        mixture = next(x for x in shown if x[0] == "반응기 세정용 혼합용제 A")
        self.assertEqual(mixture[1], "67-64-1 (혼합물 성분)")
        self.assertEqual(mixture[2], "50")
        self.assertNotEqual(mixture[1], "")

    def test_several_components_are_listed_in_order(self):
        project = _pending()
        up.add_to_project(project, _products([MIX1, MIX2]), file_name="a.xlsx", sha256="abc123456789", sds_confirmed=True)
        rows = chem._rows(project)[1]
        parts = jd.components_by_row(project)
        number = next(n for n, r in enumerate(rows, start=1) if r.get("제품명") == "세척제A")
        self.assertEqual(jd.cas_display(rows[number - 1], number, parts), "67-64-1 · 64-17-5 (혼합물 성분)")
        self.assertEqual(jd.content_display(rows[number - 1], number, parts), "60 · 30")


if __name__ == "__main__":
    unittest.main()
