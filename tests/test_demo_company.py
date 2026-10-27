"""큰 가상 회사 자료를 정답표로 채점합니다.

자동으로 채운 값이 정답과 다르면 안 되고, 일부러 넣은 문제는 모두 사람에게 물어봐야 합니다.
"""
import json
import math
import unittest
from io import BytesIO
from zipfile import ZipFile

from engine.stage2 import demo_company as dc
from engine.stage2 import evidence_workspace as ew
from engine.stage2 import scenario_triage
from engine.stage2.project import Stage2Project


def _same(got, expected):
    if isinstance(expected, float) and isinstance(got, (int, float)) and not isinstance(got, bool):
        return math.isclose(got, expected, rel_tol=1e-9, abs_tol=1e-9)
    return got == expected


class LargeDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.truth = dc.truth()
        cls.codes = {v["name"]: e.split(":", 1)[1] for e, v in cls.truth.items() if e.startswith("material:")}

    def setUp(self):
        self.p = Stage2Project(project_id="large", company_name="가상")
        for name, content in dc.files().items():
            kind, hint = dc.UPLOAD[name]
            ew.ingest(self.p, name, content, kind, hint)
        self.slots = {s["key"]: s for s in ew.slots(self.p)}

    def value(self, slot):
        got = slot["chosen"]["value"]
        return self.codes.get(got, got) if slot["field"] == "product" else got

    def slot(self, entity, field):
        return self.slots.get(f"{entity}|{field}")

    # ---- 자료 자체
    def test_zip_has_seven_files_readme_and_answer_key_with_valid_cas(self):
        with ZipFile(BytesIO(dc.large_demo_zip())) as z:
            names = set(z.namelist())
            key = json.loads(z.read("answer_key.json"))
        self.assertEqual(names, set(dc.files()) | {"README.txt", "answer_key.json"})
        self.assertGreaterEqual(len(dc.PLANTED), 30)
        for entity, values in key["truth"].items():
            if "cas" in values:
                self.assertTrue(ew.cas_valid(values["cas"]), entity)

    def test_files_are_classified_without_asking_except_scan(self):
        for name, content in dc.files().items():
            if name.endswith(".pdf"):
                with self.assertRaises(ValueError):
                    ew.classify_document(name, content)
            else:
                self.assertEqual(ew.classify_document(name, content), dc.UPLOAD[name][0], name)

    # ---- 채점
    def test_no_auto_filled_value_disagrees_with_answer_key(self):
        wrong = []
        for slot in self.slots.values():
            if not slot["chosen"] or slot["entity"] not in self.truth:
                continue
            expected = self.truth[slot["entity"]].get(slot["field"])
            if expected is None or not _same(self.value(slot), expected):
                wrong.append((slot["entity"], slot["field"], self.value(slot), expected))
        # 유일한 예외는 일부러 넣은 띄어쓰기 오류: 값은 자료 그대로이고, 연결이 안 된다고 따로 알려 줍니다.
        self.assertEqual(wrong, [("facility:TK-104", "product", "가상자일렌", "P-04")])
        self.assertTrue(any("TK-104" in t["entity"] and "연결할 수 없습니다" in t["task"] for t in ew.tasks(self.p)))

    def test_most_values_are_filled_automatically(self):
        info = ew.summary(self.p)
        self.assertGreater(info["auto"], 400)
        self.assertLess(info["pending"], 50)

    def test_every_planted_problem_is_asked_not_filled(self):
        asked = {
            ("material:P-05", "concentration"), ("material:P-13", "cas"), ("material:P-16", "substance_state"),
            ("material:P-19", "density"), ("material:P-10", "concentration"),
            ("facility:TK-109", "inventory"), ("facility:TK-112", "inventory"), ("facility:TK-115", "pressure"),
            ("facility:TK-117", "facility_type"), ("facility:RX-203", "pressure"), ("facility:RX-204", "substance_state"),
            ("facility:DR-401", "pressure"), ("facility:DR-402", "pressure"), ("facility:TK-103", "capacity"),
            ("facility:TK-105", "name"), ("facility:TK-107", "inventory"), ("facility:RX-204", "temperature"),
            ("facility:RX-205", "pressure"), ("facility:가상 혼합조 7", "pressure"), ("facility:가상 혼합조 8", "temperature"),
        } | {(f"facility:TK-{n}", "facility_type") for n in range(102, 113)}
        queue = {(i["entity"], i["field"]) for i in ew.review_queue(self.p)}
        self.assertEqual(asked - queue, set())

    def test_missing_values_are_asked(self):
        tasks = " ".join(f"{t['entity']} {t['task']}" for t in ew.tasks(self.p))
        for entity, label in [("facility:TK-118", "운전압력"), ("facility:TK-118", "운전온도"), ("facility:RX-206", "최대보유량")]:
            self.assertIsNone(self.slot(entity, {"운전압력": "pressure", "운전온도": "temperature", "최대보유량": "inventory"}[label]))
            self.assertIn(f"{entity} 기본 운전조건 미확인: {label}", tasks)

    def test_common_spellings_are_normalized(self):
        self.assertEqual(self.value(self.slot("material:P-01", "substance_state")), "액체")        # 액상
        self.assertEqual(self.value(self.slot("material:P-19", "substance_state")), "기체·고압가스")  # 가스
        self.assertEqual(self.value(self.slot("facility:MX-301", "facility_type")), "제조·사용시설")  # 사용시설
        self.assertEqual(self.value(self.slot("facility:CY-501", "substance_state")), "기체·고압가스")  # 기체

    def test_units_differ_by_sheet_but_values_match(self):
        self.assertEqual(self.value(self.slot("facility:RX-201", "capacity")), 8.0)        # 8000 L
        self.assertEqual(self.value(self.slot("facility:RX-201", "inventory")), 5200.0)    # 5.2 ton
        self.assertTrue(_same(self.value(self.slot("facility:RX-201", "pressure")), 0.3))  # 300 kPa, 05에서는 0.3 MPa
        self.assertEqual(len(self.slot("facility:RX-201", "pressure")["facts"]), 2)       # 두 파일이 교차 확인

    def test_total_row_hidden_sheet_gap_fill_and_scan(self):
        self.assertFalse(any(s["entity"] == "facility:합계" for s in self.slots.values()))
        ledger = next(d for d in ew.graph(self.p)["documents"] if d["name"].startswith("03_"))
        self.assertEqual(ledger["rows_without_id"], 1)
        self.assertIn("숨김", self.slot("facility:TK-190", "name")["facts"][0]["location"])
        self.assertEqual(self.value(self.slot("facility:MX-304", "temperature")), 30.0)   # 05가 03의 빈칸을 채움
        scan = next(d for d in ew.graph(self.p)["documents"] if d["name"].endswith(".pdf"))
        self.assertTrue(scan["needs_ocr"])

    def test_numbered_document_hint_is_not_applied_to_other_tables(self):
        # 번호 칸에 적은 값이 번호 열이 있는 표의 빈 번호 줄(합계 등)에 붙으면 안 됩니다.
        p = Stage2Project(project_id="hint", company_name="가상")
        name = "03_설비대장_2026.xlsx"
        ew.ingest(p, name, dc.files()[name], "facility", "RX-205")
        self.assertFalse(any(s["entity"] == "facility:RX-205" and s["field"] == "capacity" and
                             any(f["raw"].startswith("=SUM") for f in s["facts"]) for s in ew.slots(p)))

    def test_answering_with_the_answer_key_leaves_only_expected_gaps(self):
        for item in ew.review_queue(self.p):
            expected = self.truth.get(item["entity"], {}).get(item["field"])
            if expected is None:
                continue      # 설비대장에 없는 이름만 있는 설비: 정답표에 없음
            ew.add_manual(self.p, item["entity"], item["field"], str(expected), "정답표", confirm=True)
        for entity, field in [("facility:TK-118", "pressure"), ("facility:TK-118", "temperature"), ("facility:RX-206", "inventory")]:
            ew.add_manual(self.p, entity, field, str(self.truth[entity][field]), "정답표", confirm=True)
        triage = scenario_triage.evaluate(self.p)
        for slot in ew.slots(self.p):
            if slot["chosen"] and slot["entity"] in self.truth and slot["field"] in self.truth[slot["entity"]]:
                if (slot["entity"], slot["field"]) == ("facility:TK-104", "product"):
                    continue
                self.assertTrue(_same(self.value(slot), self.truth[slot["entity"]][slot["field"]]), (slot["entity"], slot["field"]))
        linked = [r for r in triage["rows"] if r["linked"]]
        self.assertGreaterEqual(len(linked), 37)
        still_assumed = {r["facility"] for r in linked if "assumed" in r["value_states"].values()}
        self.assertEqual(still_assumed, {"facility:TK-190"})   # 폐기예정 탱크는 운전압력이 없는 게 정상


if __name__ == "__main__":
    unittest.main()
